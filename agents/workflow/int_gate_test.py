"""Runnable check for int_gate.py: python3 -I -B int_gate_test.py.

Plans steps from changed files, bisects a list with a stub check, and runs the
whole red path on a throwaway git repo (three merges, one bad) with a stub
runner, so no cargo and no slot is used. Prints "int_gate_test OK" when all pass.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import int_gate

PACKAGES = {"crates/crazyagent": "crazyagent", "apps/desktop/src-tauri": "crazyagent-desktop"}


def names(steps):
    return [s["name"] for s in steps]


def test_plan_steps_from_changed_files():
    files = [
        "crates/crazyagent/src/a.rs",
        "crates/crazyagent/tests/foo.rs",
        "crates/crazyagent/tests/helpers/mod.rs",
        "apps/desktop/src-tauri/tests/bar.rs",
        "docs/x.md",
    ]
    steps = int_gate.plan_steps(files, PACKAGES, exists=lambda path: True)
    assert names(steps) == ["check", "clippy", "lib crazyagent", "lib crazyagent-desktop", "tests crazyagent", "tests crazyagent-desktop"], names(steps)
    assert steps[1]["cmd"][-2:] == ["-D", "warnings"], steps[1]
    assert "--test" in steps[4]["cmd"] and "foo" in steps[4]["cmd"] and "mod" not in steps[4]["cmd"], steps[4]
    assert all("--locked" in s["cmd"] and "--offline" in s["cmd"] for s in steps), steps


def test_plan_skips_docs_only_and_deleted_tests():
    assert int_gate.plan_steps(["docs/x.md", "README.md"], PACKAGES, exists=lambda p: True) == []
    steps = int_gate.plan_steps(["crates/crazyagent/tests/gone.rs"], PACKAGES, exists=lambda p: False)
    assert names(steps) == ["check", "clippy", "lib crazyagent"], names(steps)
    steps = int_gate.plan_steps(["Cargo.lock"], PACKAGES, exists=lambda p: True)
    assert names(steps) == ["check", "clippy", "lib crazyagent"], names(steps)


def test_bisect_finds_first_red_with_few_runs():
    commits = ["c1", "c2", "c3", "c4", "c5", "c6", "c7"]
    calls = []
    def green(sha):
        calls.append(sha)
        return commits.index(sha) < 4
    assert int_gate.bisect(commits, green) == "c5"
    assert len(calls) <= 3, calls
    assert int_gate.bisect(["only"], lambda sha: False) == "only"


def git(repo, *args):
    out = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)
    assert out.returncode == 0, (args, out.stderr)
    return out.stdout.strip()


def make_repo():
    root = tempfile.mkdtemp(prefix="int-gate-test-")
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "chore/v242")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    os.makedirs(os.path.join(repo, "crates/crazyagent/src"))
    with open(os.path.join(repo, "crates/crazyagent/src/lib.rs"), "w") as fh:
        fh.write("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    for i, bad in [(1, False), (2, True), (3, False)]:
        git(repo, "checkout", "-q", "-b", "fix/b%d" % i, base)
        path = os.path.join(repo, "crates/crazyagent/src/f%d.rs" % i)
        with open(path, "w") as fh:
            fh.write("x\n")
        if bad:
            with open(os.path.join(repo, "crates/crazyagent/src/BAD"), "w") as fh:
                fh.write("red\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "b%d" % i)
        git(repo, "checkout", "-q", "chore/v242")
        git(repo, "merge", "--no-ff", "-q", "-m", "Merge fix/b%d into chore/v242" % i, "fix/b%d" % i)
    return root, repo, base


def test_red_batch_names_bad_merge_and_leaves_branch_alone():
    root, repo, base = make_repo()
    head = git(repo, "rev-parse", "HEAD")
    calls = []
    def runner(step, worktree, target, log):
        calls.append((step["name"], worktree))
        return not os.path.exists(os.path.join(worktree, "crates/crazyagent/src/BAD"))
    cfg = int_gate.Config(
        worktree=repo, scratch=os.path.join(root, "scratch"), state_dir=os.path.join(root, "state"),
        log_dir=os.path.join(root, "logs"), hold=os.path.join(root, "HOLD"), queue=os.path.join(root, "queue.md"),
        runner=runner, packages=lambda wt: PACKAGES, free_gib=lambda path: 100, fmt=lambda wt, files: [])
    result = int_gate.run(cfg, base)
    assert result["verdict"] == "red", result
    bad = git(repo, "rev-parse", "HEAD^1")
    assert result["bad"] == bad, (result, bad)
    assert result["confirmed"] is True, result
    assert git(repo, "rev-parse", "HEAD") == head and git(repo, "status", "--porcelain") == ""
    assert git(repo, "branch", "--show-current") == "chore/v242"
    assert any(w == cfg.scratch for _, w in calls), calls
    queue = open(cfg.queue).read()
    assert bad[:9] in queue and "Merge fix/b2" in queue, queue
    assert not os.path.exists(os.path.join(cfg.state_dir, "repo.green"))


def test_green_batch_records_green_and_hold_refuses():
    root, repo, base = make_repo()
    cfg = int_gate.Config(
        worktree=repo, scratch=os.path.join(root, "scratch"), state_dir=os.path.join(root, "state"),
        log_dir=os.path.join(root, "logs"), hold=os.path.join(root, "HOLD"), queue=os.path.join(root, "queue.md"),
        runner=lambda step, wt, target, log: True, packages=lambda wt: PACKAGES, free_gib=lambda path: 100, fmt=lambda wt, files: [])
    open(cfg.hold, "w").close()
    result = int_gate.run(cfg, base)
    assert result["verdict"] == "hold", result
    os.remove(cfg.hold)
    result = int_gate.run(cfg, base)
    assert result["verdict"] == "green", result
    assert open(os.path.join(cfg.state_dir, "repo.green")).read().strip() == git(repo, "rev-parse", "HEAD")
    result = int_gate.run(cfg, None)
    assert result["verdict"] == "nothing", result


def red_cfg(root, repo, runner, free):
    return int_gate.Config(
        worktree=repo, scratch=os.path.join(root, "scratch"), state_dir=os.path.join(root, "state"),
        log_dir=os.path.join(root, "logs"), hold=os.path.join(root, "HOLD"), queue=os.path.join(root, "queue.md"),
        runner=runner, packages=lambda wt: PACKAGES, free_gib=lambda path: free, fmt=lambda wt, files: [])


def test_red_at_base_blames_no_merge():
    root, repo, base = make_repo()
    cfg = red_cfg(root, repo, lambda step, wt, target, log: False, 100)
    result = int_gate.run(cfg, base)
    assert result["verdict"] == "red" and result["bad"] is None and "base" in result["why"], result
    assert "red at the base" in open(cfg.queue).read()


def make_repo_broken_below(n_good, n_red_below):
    """Linear history: n_good green commits, a break, n_red_below more red commits, then make_repo-style merges on top."""
    root = tempfile.mkdtemp(prefix="int-gate-below-")
    repo = os.path.join(root, "repo")
    os.makedirs(os.path.join(repo, "crates/crazyagent/src"))
    git(repo, "init", "-q", "-b", "chore/v242")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    def commit(msg, bad=False):
        with open(os.path.join(repo, "crates/crazyagent/src/lib.rs"), "a") as fh:
            fh.write(msg + "\n")
        if bad:
            with open(os.path.join(repo, "crates/crazyagent/src/BAD"), "w") as fh:
                fh.write("red\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", msg)
        return git(repo, "rev-parse", "HEAD")
    good = [commit("good %d" % i) for i in range(n_good)]
    brk = commit("the break", bad=True)
    for i in range(n_red_below):
        commit("red %d" % i)
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "fix/b1", base)
    with open(os.path.join(repo, "crates/crazyagent/src/f1.rs"), "w") as fh:
        fh.write("x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "b1")
    git(repo, "checkout", "-q", "chore/v242")
    git(repo, "merge", "--no-ff", "-q", "-m", "Merge fix/b1 into chore/v242", "fix/b1")
    return root, repo, base, brk, good


def test_red_base_finds_first_red_below_it():
    root, repo, base, brk, good = make_repo_broken_below(3, 11)
    calls = []
    def runner(step, wt, target, log):
        calls.append(wt)
        return not os.path.exists(os.path.join(wt, "crates/crazyagent/src/BAD"))
    result = int_gate.run(red_cfg(root, repo, runner, 100), base)
    assert result["verdict"] == "red" and result["bad"] is None, result
    assert result["below_base"] == brk and result["last_green"] == good[-1], (result, brk)
    queue = open(os.path.join(root, "queue.md")).read()
    assert "first red below the base" in queue and brk[:9] in queue and "the break" in queue, queue
    assert len(calls) <= 12, len(calls)


def test_red_base_search_is_bounded():
    root, repo, base, brk, good = make_repo_broken_below(0, 45)
    calls = []
    def runner(step, wt, target, log):
        calls.append(wt)
        return False
    result = int_gate.run(red_cfg(root, repo, runner, 100), base)
    assert result["below_base"] is None and "40" in result["why"], result
    assert len(calls) <= 1 + 1 + 7, len(calls)


def test_low_disk_skips_bisect():
    root, repo, base = make_repo()
    calls = []
    def runner(step, wt, target, log):
        calls.append(wt)
        return False
    cfg = red_cfg(root, repo, runner, 5)
    result = int_gate.run(cfg, base)
    assert result["verdict"] == "red" and result["bad"] is None and "disk" in result["why"], result
    assert calls == [repo], calls
    assert not os.path.exists(cfg.scratch)


def test_scratch_target_removed_after_bisect():
    root, repo, base = make_repo()
    def runner(step, wt, target, log):
        os.makedirs(target, exist_ok=True)
        return not os.path.exists(os.path.join(wt, "crates/crazyagent/src/BAD"))
    cfg = red_cfg(root, repo, runner, 100)
    int_gate.run(cfg, base)
    assert not os.path.exists(cfg.scratch_target)


def test_prepare_hook():
    tree = tempfile.mkdtemp(prefix="int-gate-prep-")
    os.environ.pop("INT_GATE_PREPARE", None)
    assert int_gate.prepare(tree) == "none"
    os.environ["INT_GATE_PREPARE"] = "mkdir -p dist && printf x > dist/index.html"
    assert int_gate.prepare(tree) == "hook"
    assert open(os.path.join(tree, "dist/index.html")).read() == "x"
    os.environ["INT_GATE_PREPARE"] = "exit 3"
    assert int_gate.prepare(tree) == "hook rc=3"
    os.environ.pop("INT_GATE_PREPARE")


def test_fmt_red_names_the_commit_without_bisect():
    root, repo, base = make_repo()
    calls = []
    def runner(step, wt, target, log):
        calls.append(step["name"])
        return True
    cfg = red_cfg(root, repo, runner, 100)
    cfg.fmt = lambda wt, files: [f for f in files if f.endswith("f2.rs")]
    result = int_gate.run(cfg, base)
    assert result["verdict"] == "red" and result["step"] == "fmt", result
    assert result["fmt"] == ["crates/crazyagent/src/f2.rs"], result
    assert "Merge fix/b2" in result["subject"], result
    assert "check" in calls and not os.path.exists(cfg.scratch), calls
    assert "f2.rs" in open(cfg.queue).read()
    cfg.fmt = lambda wt, files: []
    assert int_gate.run(cfg, base)["verdict"] == "green"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("int_gate_test OK (%d)" % len(tests))


if __name__ == "__main__":
    main()
