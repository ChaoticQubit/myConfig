"""Post-batch check (DEC-184 G1): after merge242.sh lands a batch, check it once, bisect it when red.

Usage: int-gate.sh <int-worktree> [base-sha], or int-gate.sh <int-worktree> <base-sha> --plan to preview. Base defaults to the last green sha recorded for that worktree.
Needs WORKFLOW_ROOT (sprint folder, holds leader/); optional INT_GATE_ENV (file sourced before each step),
INT_GATE_RUNNER (script each step runs through, e.g. slot.sh), INT_GATE_PREPARE (command run in a tree before its steps),
INT_GATE_HOLD (file whose presence pauses the check). Steps: cargo check and clippy on all targets, lib tests of every touched package,
and every tests/*.rs file the batch changed. Red: binary search over the batch's first-parent commits
in a scratch detached worktree, then revert the bad merge on HEAD there to confirm. Never moves the shared branch.
A red base: gallop back over at most 40 first-parent commits below it to the last green, then bisect to the first red.
"""

import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import wfenv

F = wfenv.ROOT
R = wfenv.repo(F)
LEADER = os.path.join(F, "leader")
CARGO = ["--locked", "--offline"]
TEST_FILE_RE = re.compile(r"^tests/([A-Za-z0-9_]+)\.rs$")
TEST_HOST = os.environ.get("INT_GATE_TEST_HOST", "")
ROOT_FILES = ("Cargo.toml", "Cargo.lock", "rust-toolchain", "rust-toolchain.toml")
MIN_FREE_GIB = int(os.environ.get("INT_GATE_MIN_FREE_GIB", "20"))


class Config:
    """Paths and hooks for one run; runner(step, worktree, target, log) -> bool green, packages(worktree) -> {dir: name}."""

    def __init__(self, worktree, scratch, state_dir, log_dir, hold, queue, runner, packages, free_gib=None, fmt=None, host=None):
        self.worktree = os.path.abspath(worktree)
        self.scratch = scratch
        self.scratch_target = scratch.rstrip("/") + "-target"
        self.state_dir = state_dir
        self.log_dir = log_dir
        self.hold = hold
        self.queue = queue
        self.runner = runner
        self.packages = packages
        self.free_gib = free_gib or (lambda path: shutil.disk_usage(path).free / 2 ** 30)
        self.fmt = fmt or rustfmt_check
        self.host = host


def git(repo, *args, check=True):
    out = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)
    if check:
        assert out.returncode == 0, "git %s: %s" % (" ".join(args), out.stderr.strip()[:300])
    return out.stdout.strip() if check else out


def test_host(spec):
    """Parses "<bin>:<ENV>" (INT_GATE_TEST_HOST) into (bin, env), or None when spec is empty."""
    if not spec:
        return None
    m = re.fullmatch(r"([A-Za-z0-9_-]+):([A-Z][A-Z0-9_]*)", spec)
    if m is None:
        raise ValueError("INT_GATE_TEST_HOST must be <bin>:<ENV>, got %r" % spec)
    return m.group(1), m.group(2)


def step_env(step, target):
    """Returns a step's extra environment with {target} filled by the absolute target dir the step builds into."""
    assert os.path.isabs(target), "target must be absolute: %s" % target
    return {k: v.replace("{target}", target) for k, v in step.get("env", {}).items()}


def plan_steps(files, packages, exists, host=None):
    """Returns the ordered steps for a batch's changed files; [] when no package or root manifest changed.

    packages maps a package dir (repo-relative, in workspace order) to its name; exists(path) says a file is at HEAD.
    host (bin, ENV): every cargo test step first builds that bin into its own target and gets ENV=<target>/debug/<bin>,
    so bisect and confirm in the scratch tree build their own host too.
    """
    def with_host(step):
        if host is None:
            return step
        return dict(step, pre=["cargo", "build"] + CARGO + ["--bin", host[0]], env={host[1]: "{target}/debug/" + host[0]})

    touched = [d for d in packages if any(f.startswith(d + "/") for f in files)]
    root = any(f in ROOT_FILES or f.startswith(".cargo/") for f in files)
    if not touched and not root:
        return []
    if not touched:
        touched = [d for d in packages if packages[d] == "crazyagent"] or list(packages)[:1]
    steps = [
        {"name": "check", "cmd": ["cargo", "check"] + CARGO + ["--workspace", "--all-targets"], "tests": []},
        {"name": "clippy", "cmd": ["cargo", "clippy"] + CARGO + ["--workspace", "--all-targets", "--", "-D", "warnings"], "tests": []},
    ]
    for d in touched:
        steps.append(with_host({"name": "lib %s" % packages[d], "cmd": ["cargo", "test", "-p", packages[d]] + CARGO + ["--no-fail-fast", "--lib"], "tests": []}))
    for d in touched:
        tests = sorted({m.group(1) for f in files if f.startswith(d + "/") and exists(f)
                        for m in [TEST_FILE_RE.match(f[len(d) + 1:])] if m})
        if tests:
            cmd = ["cargo", "test", "-p", packages[d]] + CARGO + ["--no-fail-fast"]
            for t in tests:
                cmd += ["--test", t]
            steps.append(with_host({"name": "tests %s" % packages[d], "cmd": cmd, "tests": tests, "dir": d}))
    assert all(s["cmd"][0] == "cargo" and s.get("pre", ["cargo"])[0] == "cargo" for s in steps)
    return steps


def bisect(commits, green):
    """Returns the first commit where green(sha) is False, given the base before commits[0] is green and commits[-1] is red."""
    assert commits, "nothing to bisect"
    lo, hi = -1, len(commits) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if green(commits[mid]):
            lo = mid
        else:
            hi = mid
    return commits[hi]


def step_for_tree(step, tree):
    """Narrows a tests step to the test files present in a checked-out tree; None when none are there yet."""
    if not step["tests"]:
        return step
    have = [t for t in step["tests"] if os.path.exists(os.path.join(tree, step["dir"], "tests", t + ".rs"))]
    if not have:
        return None
    cmd = [c for c in step["cmd"] if c != "--test" and c not in step["tests"]]
    for t in have:
        cmd += ["--test", t]
    return dict(step, cmd=cmd, tests=have)


def prepare(tree):
    """Runs INT_GATE_PREPARE in tree (a project's pre-build step, e.g. a frontend stub); returns none, hook or hook rc=N."""
    hook = os.environ.get("INT_GATE_PREPARE", "")
    if not hook:
        return "none"
    rc = subprocess.run(["bash", "-c", hook], cwd=tree, capture_output=True, timeout=900).returncode
    return "hook" if rc == 0 else "hook rc=%d" % rc


def env_file():
    """Returns INT_GATE_ENV, else WORKFLOW_ROOT/env.sh when it exists, else an empty string (nothing sourced)."""
    default = os.path.join(F, "env.sh") if F else ""
    return os.environ.get("INT_GATE_ENV") or (default if default and os.path.isfile(default) else "")


def step_runner_path():
    """Returns INT_GATE_RUNNER, else WORKFLOW_ROOT/slot.sh when it exists, else an empty string (steps run directly)."""
    default = os.path.join(F, "slot.sh") if F else ""
    return os.environ.get("INT_GATE_RUNNER") or (default if default and os.path.isfile(default) else "")


def scratch_at(cfg, sha):
    """Puts the scratch worktree at sha, detached and clean, creating it on first use."""
    if not os.path.isdir(cfg.scratch):
        git(cfg.worktree, "worktree", "add", "-q", "--detach", cfg.scratch, sha)
    else:
        assert git(cfg.scratch, "rev-parse", "--show-toplevel") == os.path.realpath(cfg.scratch), cfg.scratch
        git(cfg.scratch, "reset", "-q", "--hard")
        git(cfg.scratch, "clean", "-fdq")
        git(cfg.scratch, "checkout", "-q", "--detach", sha)
    prepare(cfg.scratch)


def now():
    return time.strftime("%H:%M")


def append(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as fh:
        fh.write(line.rstrip("\n") + "\n")


def run(cfg, base):
    """Checks the batch base..HEAD of cfg.worktree; returns a dict with verdict hold, dirty, no-base, nothing, green or red."""
    if os.path.exists(cfg.hold):
        return {"verdict": "hold"}
    if git(cfg.worktree, "status", "--porcelain"):
        return {"verdict": "dirty"}
    os.makedirs(cfg.state_dir, exist_ok=True)
    name = os.path.basename(cfg.worktree.rstrip("/"))
    green_file = os.path.join(cfg.state_dir, name + ".green")
    head = git(cfg.worktree, "rev-parse", "HEAD")
    branch = git(cfg.worktree, "branch", "--show-current")
    if base is None:
        if not os.path.exists(green_file):
            return {"verdict": "no-base"}
        base = open(green_file).read().strip()
    base = git(cfg.worktree, "rev-parse", "--verify", base + "^{commit}")
    if base == head:
        return {"verdict": "nothing"}
    assert git(cfg.worktree, "merge-base", "--is-ancestor", base, head, check=False).returncode == 0, "base is not an ancestor of HEAD"
    commits = git(cfg.worktree, "rev-list", "--first-parent", "--reverse", "%s..%s" % (base, head)).split()
    files = [f for f in git(cfg.worktree, "diff", "--name-only", base, head).split("\n") if f]
    steps = plan_steps(files, cfg.packages(cfg.worktree), lambda p: os.path.exists(os.path.join(cfg.worktree, p)), host=cfg.host)
    target = os.path.join(cfg.worktree, ".local-state", "target")
    stamp = "%s-%s" % (name, head[:9])
    dist = prepare(cfg.worktree) if steps else "none"
    rs_files = [f for f in files if f.endswith(".rs") and os.path.exists(os.path.join(cfg.worktree, f))]
    fmt_bad = sorted(cfg.fmt(cfg.worktree, rs_files)) if rs_files else []
    assert set(fmt_bad) <= set(rs_files), fmt_bad
    red = None
    for step in steps:
        log = os.path.join(cfg.log_dir, "int-%s-%s.log" % (stamp, step["name"].replace(" ", "-")))
        if not cfg.runner(step, cfg.worktree, target, log):
            red = (step, log)
            break
    summary = "%s int-gate %s %s %s..%s: %d commits, prepare %s, fmt %d of %d changed files off, steps %s" % (
        now(), name, branch, base[:9], head[:9], len(commits), dist, len(fmt_bad), len(rs_files),
        ", ".join(s["name"] for s in steps) or "none (no Rust change)")
    if red is None and fmt_bad:
        bad = git(cfg.worktree, "log", "-1", "--first-parent", "--format=%H", "%s..%s" % (base, head), "--", fmt_bad[0]).strip() or head
        subject = git(cfg.worktree, "log", "-1", "--format=%s", bad)
        line = "%s RED %s %s: step 'fmt' (D1): %d changed file(s) not rustfmt-clean: %s; first one last changed by %s \"%s\"" % (
            now(), name, head[:9], len(fmt_bad), " ".join(fmt_bad[:6]), bad[:9], subject[:140])
        append(cfg.queue, line)
        append(os.path.join(cfg.log_dir, "int-gate.log"), summary + ": " + line)
        return {"verdict": "red", "step": "fmt", "fmt": fmt_bad, "bad": bad, "subject": subject, "confirmed": None, "why": "fmt", "log": None}
    if red is None:
        with open(green_file, "w") as fh:
            fh.write(head + "\n")
        append(os.path.join(cfg.log_dir, "int-gate.log"), summary + ": GREEN")
        return {"verdict": "green", "head": head, "steps": [s["name"] for s in steps]}
    step, log = red
    result = {"verdict": "red", "step": step["name"], "bad": None, "subject": None, "confirmed": None, "why": "", "log": log, "fmt": fmt_bad,
              "below_base": None, "last_green": None}
    free = cfg.free_gib(os.path.dirname(os.path.abspath(cfg.scratch)))
    if free < MIN_FREE_GIB:
        result["why"] = "bisect skipped: disk %.0f GiB free < %d" % (free, MIN_FREE_GIB)
    else:
        try:
            result.update(find_bad(cfg, step, base, head, commits, log))
        finally:
            if os.path.isdir(cfg.scratch):
                scratch_at(cfg, head)
            if not os.environ.get("INT_GATE_KEEP_SCRATCH"):
                shutil.rmtree(cfg.scratch_target, ignore_errors=True)
    if result["bad"]:
        word = {True: "yes, HEAD minus it is green", False: "no, still red without it (interaction)", None: "revert conflicts"}[result["confirmed"]]
        line = "%s RED %s %s: step '%s'; first red commit %s \"%s\"; revert check: %s; log %s" % (
            now(), name, head[:9], step["name"], result["bad"][:9], result["subject"][:140], word, log)
    else:
        line = "%s RED %s %s: step '%s'; %s; no merge named; log %s" % (now(), name, head[:9], step["name"], result["why"], log)
    append(cfg.queue, line)
    append(os.path.join(cfg.log_dir, "int-gate.log"), summary + ": " + line)
    return result


def find_bad(cfg, step, base, head, commits, log):
    """Checks the base is green for the red step, then bisects and confirms; returns the fields for the result."""
    def green_at(sha):
        scratch_at(cfg, sha)
        narrowed = step_for_tree(step, cfg.scratch)
        if narrowed is None:
            return True
        return cfg.runner(narrowed, cfg.scratch, cfg.scratch_target, log + ".at-" + sha[:9])
    if not green_at(base):
        return below_base(cfg, base, green_at)
    bad = bisect(commits, green_at) if len(commits) > 1 else commits[0]
    return {"bad": bad, "subject": git(cfg.worktree, "log", "-1", "--format=%s", bad), "confirmed": confirm(cfg, step, head, bad, log)}


BELOW_MAX = 40


def below_base(cfg, base, green_at):
    """Base is red: probes first-parent commits 1, 2, 4 ... BELOW_MAX below it for the last green, then bisects to the first red."""
    chain = git(cfg.worktree, "rev-list", "--first-parent", "--max-count=%d" % (BELOW_MAX + 1), base).split()
    assert chain and chain[0] == base, chain
    last = len(chain) - 1
    red, green, probe = 0, None, 1
    while probe <= last:
        if green_at(chain[probe]):
            green = probe
            break
        red = probe
        if probe == last:
            break
        probe = min(probe * 2, last)
    if green is None:
        return {"why": "red at the base too, and at every probe back %d first-parent commits (cap %d): environment or an older break" % (last, BELOW_MAX)}
    assert red < green, (red, green)
    first_red = bisect(list(reversed(chain[red:green])), green_at)
    last_green = chain[chain.index(first_red) + 1]
    subject = git(cfg.worktree, "log", "-1", "--format=%s", first_red)
    return {"why": "red at the base too; first red below the base %s \"%s\" (last green %s)" % (first_red[:9], subject[:140], last_green[:9]),
            "below_base": first_red, "last_green": last_green}


def confirm(cfg, step, head, bad, log):
    """Reverts bad on HEAD in the scratch worktree and reruns the red step: True green, False red, None on conflict."""
    scratch_at(cfg, head)
    parents = git(cfg.scratch, "rev-list", "--parents", "-n", "1", bad).split()
    args = ["revert", "--no-commit"] + (["-m", "1"] if len(parents) > 2 else []) + [bad]
    if git(cfg.scratch, *args, check=False).returncode != 0:
        git(cfg.scratch, "revert", "--abort", check=False)
        return None
    narrowed = step_for_tree(step, cfg.scratch)
    ok = True if narrowed is None else cfg.runner(narrowed, cfg.scratch, cfg.scratch_target, log + ".revert-" + bad[:9])
    git(cfg.scratch, "reset", "-q", "--hard")
    return bool(ok)


FMT_DIFF_RE = re.compile(r"^Diff in (.+?\.rs)(?::\d+:| at line \d+:)")


def rustfmt_check(worktree, files):
    """Returns the files (repo-relative) rustfmt --check would change; diffs in files outside the list are ignored."""
    script = '[ -z "$1" ] || source "$1"; shift; exec rustfmt --check --edition 2024 "$@"'
    out = subprocess.run(["bash", "-c", script, "int-gate", env_file()] + files, cwd=worktree, capture_output=True, text=True, timeout=600)
    root = os.path.realpath(worktree)
    wanted = set(files)
    bad = set()
    for line in out.stdout.split("\n"):
        m = FMT_DIFF_RE.match(line)
        if m:
            rel = os.path.relpath(os.path.realpath(m.group(1)), root)
            if rel in wanted:
                bad.add(rel)
    assert out.returncode == 0 or "Diff in" in out.stdout or out.stderr, "rustfmt failed without a diff"
    return sorted(bad)


def step_runner(step, worktree, target, log):
    """Runs one step through INT_GATE_RUNNER (or directly) after sourcing INT_GATE_ENV, output to log; True on exit 0.

    A step's pre command (the test host build) runs first, through the runner too; a red pre makes the step red.
    """
    os.makedirs(os.path.dirname(log), exist_ok=True)
    extra = step_env(step, target)
    env = dict(os.environ, **extra)
    script = '[ -z "$1" ] || source "$1"; export CARGO_TARGET_DIR="$2" CARGO_PROFILE_TEST_DEBUG=line-tables-only; r="$3"; shift 3; if [ -n "$r" ]; then exec bash "$r" "$@"; else exec "$@"; fi'
    with open(log, "w") as fh:
        fh.write("%s %s in %s\n" % (time.strftime("%H:%M:%S"), " ".join(step["cmd"]), worktree))
        fh.write("".join("env %s=%s\n" % kv for kv in sorted(extra.items())))
        fh.flush()
        rc = 0
        for cmd in ([step["pre"]] if step.get("pre") else []) + [step["cmd"]]:
            rc = subprocess.run(["bash", "-c", script, "int-gate", env_file(), target, step_runner_path()] + cmd, cwd=worktree, env=env,
                                stdout=fh, stderr=subprocess.STDOUT).returncode
            if rc != 0:
                break
        fh.write("%s rc=%d\n" % (time.strftime("%H:%M:%S"), rc))
    print("%s %s rc=%d (%s)" % (now(), step["name"], rc, log))
    return rc == 0


def cargo_packages(worktree):
    """Maps each workspace package dir (relative to worktree, workspace order) to its name via cargo metadata."""
    script = '[ -z "$1" ] || source "$1"; exec cargo metadata --no-deps --offline --format-version 1'
    out = subprocess.run(["bash", "-c", script, "int-gate", env_file()], cwd=worktree, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[:300]
    import json
    meta = json.loads(out.stdout)
    root = os.path.realpath(worktree)
    by_id = {p["id"]: p for p in meta["packages"]}
    result = {}
    for pid in meta["workspace_members"]:
        d = os.path.relpath(os.path.dirname(os.path.realpath(by_id[pid]["manifest_path"])), root)
        if not d.startswith(".."):
            result[d] = by_id[pid]["name"]
    assert result, "no workspace packages under %s" % worktree
    return result


def plan_only(worktree, base):
    """Prints the batch commits and the steps a run would take; runs nothing."""
    head = git(worktree, "rev-parse", "HEAD")
    commits = git(worktree, "log", "--first-parent", "--reverse", "--format=%h %s", "%s..%s" % (base, head)).split("\n")
    files = [f for f in git(worktree, "diff", "--name-only", base, head).split("\n") if f]
    print("batch %s..%s: %d commits, %d files" % (base[:9], head[:9], len(commits), len(files)))
    for c in commits:
        print("  " + c[:150])
    for step in plan_steps(files, cargo_packages(worktree), lambda p: os.path.exists(os.path.join(worktree, p)), host=test_host(TEST_HOST)):
        pre = "%s && " % " ".join(step["pre"]) if step.get("pre") else ""
        env = "".join("%s=%s " % kv for kv in sorted(step.get("env", {}).items()))
        print("step %s: %s%s%s" % (step["name"], pre, env, " ".join(step["cmd"])))
    return 0


def main(argv):
    if len(argv) == 4 and argv[3] == "--plan":
        return plan_only(os.path.abspath(argv[1]), argv[2])
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    wfenv.require_root(F)
    lock = os.path.join(LEADER, ".int-gate.lock")
    try:
        os.mkdir(lock)
    except FileExistsError:
        print("int-gate already running (%s)" % lock)
        return 1
    try:
        cfg = Config(
            worktree=argv[1], scratch=os.path.join(R, ".worktrees", "int-gate-scratch"),
            state_dir=os.path.join(LEADER, "int-gate-state"), log_dir=os.path.join(LEADER, "logs"),
            hold=os.environ.get("INT_GATE_HOLD") or os.path.join(F, "slots", "HOLD"), queue=os.path.join(LEADER, "dispatch-leader-queue.md"),
            runner=step_runner, packages=cargo_packages, host=test_host(TEST_HOST))
        result = run(cfg, argv[2] if len(argv) == 3 else None)
        print(" ".join("%s=%s" % kv for kv in result.items()))
        return {"green": 0, "nothing": 0, "red": 1}.get(result["verdict"], 3)
    finally:
        os.rmdir(lock)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
