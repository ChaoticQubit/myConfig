"""Leader dispatcher (DEC-184 G7): routes worker DONE lines to a free reviewer pair.

Commands: tick (one pass, live only when leader/dispatch-on exists), dry-run
[--since MIN] (replays recent status lines, sends nothing), status, close ID.
Reads status.md line 1 history, leader/dispatch-table.txt and leader/RULES-review.md.
Writes tells (leader/tell.sh), ledger lines, leader/dispatch-leader-queue.md and w-dispatch/status.md.
Paths: WORKFLOW_ROOT (sprint folder), WORKFLOW_REPO, WORKFLOW_OWNER_PANE (see wfenv.py); DISPATCH_ROOT and DISPATCH_REPO still work.
"""

import fnmatch
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import wfenv

ROOT = os.environ.get("WORKFLOW_ROOT") or os.environ.get("DISPATCH_ROOT") or ""
LEADER = os.path.join(ROOT, "leader")
REPO = os.environ.get("DISPATCH_REPO") or wfenv.repo(ROOT)
STATE_PATH = os.path.join(LEADER, "dispatch-state.json")
ON_FLAG = os.path.join(LEADER, "dispatch-on")
QUEUE_PATH = os.path.join(LEADER, "dispatch-leader-queue.md")
MONITOR_DIR = os.path.join(ROOT, "w-dispatch")
LOCK_DIR = os.path.join(LEADER, ".dispatch.lock")
OWNER_PANE = wfenv.OWNER_PANE
TELL_MAX = 700
HEAD_LINES = 15
SKIP_FOLDERS = {"leader", "w-dispatch"}

LINE_RE = re.compile(
    r"^(?:(\d\d:\d\d)\s+)?(?:\d\d-\d\d\s+)?(?:[A-Za-z0-9][\w.-]*:\s+|[a-z][\w.-]*\s+(?=[A-Z]))?([A-Z][A-Z0-9]+(?:-[A-Z0-9]+)*)\b(.*)$"
)
RANGE_RE = re.compile(r"\b([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})\b")
WORK_BRANCH_RE = re.compile(r"\b((?:feat|fix|hotfix|perf|refactor|docs|test)/[A-Za-z0-9._/-]*[A-Za-z0-9])")
ANY_BRANCH_RE = re.compile(r"\b((?:chore|review)/[A-Za-z0-9._/-]*[A-Za-z0-9])")
FILE_BRANCH_RE = re.compile(r"\bBranch:?\s+`?([A-Za-z0-9._-]+/[A-Za-z0-9._/-]*[A-Za-z0-9])")
DONE_FILE_RE = re.compile(r"\b(DONE-\d\d:?\d\d-[A-Za-z0-9._-]+?\.md)")
SHA_RE = re.compile(r"(?<!\w)([0-9a-f]{7,40})(?!\w)")
BASE_SHA_RE = re.compile(r"(?:\boff|\bvs\s+\S+|\bwas|\bbase)\s+\(?([0-9a-f]{7,40})")
BOILERPLATE_RE = re.compile(r"merge-tree[^;.]*|skip merges?[^;)]*|merge of \S+ [0-9a-f]{7,40}|\d+ \S+ merges", re.I)
NOT_REVIEW_RE = re.compile(r"--no-ff|\bmerged\s*:|^\S*merge\b|^pushed\b", re.I)
FOLD_RE = re.compile(
    r"(?i:\bfold(?:s|ed|ing)?\b(?!\s+in\b))|(?i:\blows?\b|-f\d+\b)"
    r"|\brv-[\w-]+\s+(?:r\d\s+)?(?:[A-Z][A-Z0-9]*-?\d+|nits?\b|\d+ nits?\b)|FINDINGS-"
)
FINDINGS_FILE_RE = re.compile(r"\b(FINDINGS-\d\d:\d\d-[A-Za-z0-9._-]+?\.md)")
ROUND_RE = re.compile(r"(?:\br(\d)\b|\bround (\d)\b)")
COUNT_RE = re.compile(r"\bfindings:\s*(\d+)")
ITEM_RE = re.compile(r"\b([A-Z][A-Z0-9]*-?\d+[a-z]?)\b\s*[:(-]?\s*((?i:critical|high|medium|med|low))\b")
NOTES_RE = re.compile(r"^#{1,4}\s*(notes|closures|checked|nits|advisor|read list)", re.I)
DONE_WORD_RE = re.compile(r"(?<![\w-])DONE(?![\w-])")
LEADER_DONE_RE = re.compile(r"QUESTION|ASK-|leader call|owner question", re.I)
LEADER_REVIEW_RE = re.compile(r"leader call|QUESTION|owner question", re.I)

FREE_KINDS = {"DONE-REVIEW", "IDLE", "DONE"}
BUSY_KINDS = {"STARTED", "START", "WORKING", "ACK", "PROGRESS", "REVIEWING", "PAUSED", "HOLD", "STEP", "PHASE"}
BLOCKING_SEVERITIES = {"CRITICAL", "HIGH", "MED"}


def parse_line(line):
    """Splits one status line into (time or None, KIND, rest), or None when it is prose.

    Accepts "HH:MM KIND rest", "HH:MM name: KIND rest", "HH:MM name KIND rest" (a lowercase pane name) and "KIND rest" (no time).
    """
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    return (m.group(1), m.group(2), m.group(3).strip())


def parse_table(text):
    """Reads dispatch-table.txt rows "code|sec <branch-glob> <name>..." and "ledger <branch-glob> <file>".

    The first row whose glob matches a branch wins for that track; names are the fallback order.
    Returns {"code": [(glob, names)], "sec": [(glob, names)], "ledgers": [(glob, file)]}.
    """
    table = {"code": [], "sec": [], "ledgers": []}
    for raw in text.splitlines():
        parts = raw.split()
        if len(parts) >= 3 and parts[0] in ("code", "sec"):
            assert len(set(parts[2:])) == len(parts[2:]), "duplicate reviewer in row: %s" % raw
            table[parts[0]].append((parts[1], parts[2:]))
        elif len(parts) == 3 and parts[0] == "ledger":
            table["ledgers"].append((parts[1], parts[2]))
    assert table["code"] and table["sec"], "dispatch table needs code and sec rows"
    assert table["ledgers"], "dispatch table has no ledger rows"
    codes = {n for _, names in table["code"] for n in names}
    secs = {n for _, names in table["sec"] for n in names}
    assert not (codes & secs), "a reviewer sits in both tracks: %s" % sorted(codes & secs)
    return table


def row_for(rows, branch):
    """Returns the reviewer names of the first row whose glob matches branch, or []."""
    for glob, names in rows:
        if fnmatch.fnmatch(branch, glob):
            return names
    return []


def parse_rules(text):
    """Reads the numbers the dispatcher needs from RULES-review.md (defaults 2 and 2)."""
    cap = re.search(r"round cap:\s*(\d+)", text)
    per_pair = re.search(r"queue per pair:\s*(\d+)", text)
    rules = {"round_cap": int(cap.group(1)) if cap else 2, "queue_per_pair": int(per_pair.group(1)) if per_pair else 2}
    assert rules["round_cap"] >= 1 and rules["queue_per_pair"] >= 1
    return rules


def new_state():
    """Returns an empty dispatcher state."""
    return {"seen": {}, "reviewers": {}, "assignments": [], "pending": [], "flags": {}, "next_id": 1}


def lookup_pane(name, agents):
    """Returns the pane id for an exact agent name, or None (missing, ambiguous or the owner pane)."""
    rows = [a for a in agents.get("result", {}).get("agents", []) if a.get("name") == name]
    if len(rows) != 1:
        return None
    pane = rows[0].get("pane_id")
    if not pane or pane == OWNER_PANE:
        return None
    return pane


def severity(word):
    """Normalises a severity word to CRITICAL, HIGH, MED or LOW."""
    w = word.upper()
    return "MED" if w in ("MEDIUM", "MED") else w


def items_in(text):
    """Returns ordered unique (id, severity) pairs named in a text."""
    seen, out = set(), []
    for fid, sev in ITEM_RE.findall(text):
        if fid not in seen:
            seen.add(fid)
            out.append((fid, severity(sev)))
    return out


def items_in_findings_file(text):
    """Returns (id, severity) pairs named in a FINDINGS file before its notes or closures."""
    kept = []
    for line in text.splitlines():
        if NOTES_RE.match(line.strip()):
            break
        kept.append(line)
    return items_in("\n".join(kept))


class Engine:
    """Pure routing logic: feed status lines in time order, get actions back.

    Actions: ("tell", name, text), ("ledger", file, line), ("queue", line), ("backlog", line).
    read_file(relpath) and list_dir(folder) are injected so tests need no real sprint folder.
    """

    def __init__(self, table, rules, state, read_file=None, list_dir=None, resolve_tip=None):
        self.table = table
        self.rules = rules
        self.state = state
        self.read_file = read_file or (lambda path: "")
        self.list_dir = list_dir or (lambda folder: [])
        self.resolve_tip = resolve_tip or (lambda branch: None)
        self.shadow = False
        self.unavailable = set()
        self.reviewer_names = {n for track in ("code", "sec") for _, names in table[track] for n in names}

    def is_reviewer(self, folder):
        return folder in self.reviewer_names or folder.startswith("rv-")

    def feed(self, folder, line, hhmm):
        """Processes one status line written by folder at hhmm; returns actions."""
        parsed = parse_line(line)
        if parsed is None:
            if DONE_WORD_RE.search(line):
                return [("queue", "%s line with DONE did not parse, not routed: %s" % (folder, line.strip()[:220]))]
            return []
        kind, rest = parsed[1], parsed[2]
        actions = []
        if kind == "DONE":
            actions += self.on_done(folder, rest, hhmm)
        elif kind.startswith("DONE") and kind != "DONE-REVIEW":
            actions.append(("queue", "%s %s is not a DONE the dispatcher routes: %s" % (folder, kind, rest[:220])))
        if self.is_reviewer(folder):
            if kind == "DONE-REVIEW":
                actions += self.on_review(folder, rest, hhmm)
            self.note_reviewer(folder, kind, hhmm)
        return actions

    def note_reviewer(self, name, kind, hhmm):
        if kind in FREE_KINDS or kind in BUSY_KINDS or kind == "LIMIT":
            self.state["reviewers"][name] = {"kind": kind, "t": hhmm}

    def open_for(self, name):
        for a in self.state["assignments"]:
            if a["closed"]:
                continue
            if (a["code"] == name and a["verdicts"]["code"] is None) or (a["sec"] == name and a["verdicts"]["sec"] is None):
                return a
        return None

    def is_free(self, name):
        info = self.state["reviewers"].get(name)
        if info is None or info["kind"] not in FREE_KINDS:
            return False
        if name in self.unavailable:
            return False
        return self.shadow or self.open_for(name) is None

    def is_gone(self, name):
        info = self.state["reviewers"].get(name)
        return name in self.unavailable or (info is not None and info["kind"] == "LIMIT")

    def ledger_for(self, branch):
        for glob, path in self.table["ledgers"]:
            if fnmatch.fnmatch(branch, glob):
                return path
        raise AssertionError("no ledger row matches %s" % branch)

    def find_work(self, folder, rest):
        done_file = DONE_FILE_RE.search(rest)
        done_file = done_file.group(1) if done_file else None
        body = self.read_file(os.path.join(folder, done_file)) if done_file else ""
        branch = None
        m = FILE_BRANCH_RE.search(body)
        if m:
            branch = m.group(1)
        for rx in (WORK_BRANCH_RE, ANY_BRANCH_RE):
            if branch is None:
                m = rx.search(rest) or rx.search(body)
                branch = m.group(1) if m else None
        rng = RANGE_RE.search(rest) or RANGE_RE.search(body)
        if rng:
            return branch, (rng.group(0), rng.group(2)), done_file
        if branch is None:
            return branch, None, done_file
        return branch, self.single_tip(branch, rest), done_file

    def single_tip(self, branch, rest):
        """For a DONE that lists commits but no range: the branch tip, only when the line names it and it is not a base."""
        tip = self.resolve_tip(branch)
        if not tip:
            return None
        bases = {s[:7] for s in BASE_SHA_RE.findall(rest)}
        listed = [s for s in SHA_RE.findall(rest) if s[:7] not in bases]
        if tip[:7] not in {s[:7] for s in listed}:
            return None
        return ("commits %s (tip %s)" % (" ".join(s[:9] for s in listed), tip[:9]), tip)

    def on_done(self, folder, rest, hhmm):
        """Handles a worker DONE: route to a pair, park it, or hand it to the leader queue."""
        short = rest[:220]
        clean = BOILERPLATE_RE.sub(" ", rest)
        if LEADER_DONE_RE.search(clean):
            return [("queue", "%s DONE needs the leader (question or leader call): %s" % (folder, short))]
        if NOT_REVIEW_RE.search(re.sub(r"^\d\d:\d\d\s+(\d\d-\d\d\s+)?", "", clean)):
            return [("queue", "%s DONE reports a merge or push: leader reads it: %s" % (folder, short))]
        branch, rng, done_file = self.find_work(folder, clean)
        if branch is None or rng is None:
            return [("queue", "%s DONE not routed (no branch, or no range and no named tip): %s" % (folder, short))]
        tokens = [t for t in re.split(r"[\s;,]+", rest) if t]
        slug = tokens[0].rstrip(":") if tokens and not re.match(r"^r\d$", tokens[0]) else branch.split("/")[-1]
        if "/" in slug:
            slug = slug.split("/")[-1]
        prior = [a for a in self.state["assignments"] if a["branch"] == branch]
        waiting = [p for p in self.state["pending"] if p["branch"] == branch]
        if waiting:
            assert len(waiting) == 1, waiting
            waiting[0].update(slug=slug, range=rng[0], tip=rng[1], done_file=done_file or waiting[0]["done_file"])
            return []
        if any(not a["closed"] for a in prior):
            return [("queue", "%s DONE %s while its review is still open: leader" % (folder, slug))]
        named = [int(a or b) for a, b in ROUND_RE.findall(clean)]
        if not prior and (FOLD_RE.search(clean) or max(named + [1]) > 1):
            return [("queue", "%s DONE %s folds findings of a leader-routed review: leader routes the confirm" % (folder, slug))]
        rnd = len(prior) + 1
        if rnd > self.rules["round_cap"]:
            return [("queue", "%s DONE %s r%d over round cap %d: leader (only an open HIGH earns another round)" % (folder, slug, rnd, self.rules["round_cap"]))]
        job = {"slug": slug, "branch": branch, "range": rng[0], "tip": rng[1], "worker": folder,
               "round": rnd, "done_file": done_file, "t": hhmm,
               "prefer": (prior[-1]["code"], prior[-1]["sec"]) if prior else None}
        self.state["pending"].append(job)
        actions = self.retry_pending(hhmm, only=job)
        if job in self.state["pending"]:
            actions += self.queue_rule()
        return actions

    def pick_one(self, track, job, prefer):
        """Returns the reviewer for one track: the earlier round's reviewer when it can still take it, else the first free name."""
        if prefer is not None and not self.is_gone(prefer):
            return prefer if self.is_free(prefer) else None
        for name in row_for(self.table[track], job["branch"]):
            if name != job["worker"] and self.is_free(name):
                return name
        return None

    def pick_pair(self, job):
        """Returns (code, sec) for a job, or None while either track has no free reviewer."""
        prefer = job["prefer"] or (None, None)
        code = self.pick_one("code", job, prefer[0])
        sec = self.pick_one("sec", job, prefer[1])
        if code is None or sec is None:
            return None
        return code, sec

    def retry_pending(self, hhmm, only=None):
        """Routes waiting jobs (oldest first) to free pairs; returns actions."""
        actions = []
        for job in list(self.state["pending"]):
            if only is not None and job is not only:
                continue
            pair = self.pick_pair(job)
            if pair is None:
                continue
            self.state["pending"].remove(job)
            actions += self.assign(job, pair, hhmm)
        if not self.over_queue():
            self.state["flags"]["queue_over"] = False
        return actions

    def assign(self, job, pair, hhmm):
        code, sec = pair
        assert code != sec and job["worker"] not in pair, (job, pair)
        a = dict(job, id=self.state["next_id"], code=code, sec=sec, routed=hhmm, closed=False,
                 verdicts={"code": None, "sec": None})
        a.pop("prefer", None)
        self.state["next_id"] += 1
        self.state["assignments"].append(a)
        ref = "F/%s/%s" % (a["worker"], a["done_file"]) if a["done_file"] else "DONE line in F/%s/status.md" % a["worker"]
        tip7 = a["tip"][:7]
        rnd = "r%d" % a["round"]
        confirm = "" if a["round"] == 1 else " Round %d of %d: check the r%d findings are closed." % (a["round"], self.rules["round_cap"], a["round"] - 1)
        head = "%s dispatch (leader tool, DEC-184 G7) #%d: %s" % (hhmm, a["id"], a["slug"])
        where = "%s %s (%s; %s)." % (a["branch"], a["range"], a["worker"], ref)
        facts = []
        if RANGE_RE.fullmatch(a["range"]):
            rel = "leader/facts/%d-%s.txt" % (a["id"], re.sub(r"[^A-Za-z0-9._-]", "_", a["slug"])[:40])
            facts = [("facts", rel, a["range"])]
            where += " Facts (changed fn callers, new tables, missing includes): F/%s." % rel
        tail = " FINDINGS + DONE-REVIEW naming %s." % tip7
        code_msg = "%s code %s: %s%s%s" % (head, rnd, where, confirm, tail)
        sec_msg = "%s security %s: %s Scope and risk rows: the DONE file.%s%s" % (head, rnd, where, confirm, tail)
        for msg in (code_msg, sec_msg):
            assert len(msg) <= TELL_MAX, len(msg)
        line = "%s %s %s -> %s code + %s sec (dispatch #%d %s)" % (hhmm, a["slug"], a["tip"], code, sec, a["id"], rnd)
        return facts + [("tell", code, code_msg), ("tell", sec, sec_msg), ("ledger", self.ledger_for(a["branch"]), line)]

    def pair_count(self):
        """Counts reviewer pairs: the smaller of the two default (last-row) pools."""
        return max(1, min(len(self.table["code"][-1][1]), len(self.table["sec"][-1][1])))

    def over_queue(self):
        return len(self.state["pending"]) > self.rules["queue_per_pair"] * self.pair_count()

    def queue_rule(self):
        if self.over_queue() and not self.state["flags"].get("queue_over"):
            self.state["flags"]["queue_over"] = True
            return [("queue", "QUEUE %d branches wait for %d pairs: next free worker verifies, no new code (RULES-review.md)"
                     % (len(self.state["pending"]), self.pair_count()))]
        return []

    def match_review(self, name, rest):
        cands = []
        for a in self.state["assignments"]:
            if a["closed"]:
                continue
            for track in ("code", "sec"):
                if a[track] == name and a["verdicts"][track] is None:
                    cands.append((a, track))
        for a, track in cands:
            if a["tip"][:7] in rest:
                return a, track
        for a, track in cands:
            if len(a["slug"]) >= 4 and re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(a["slug"]), rest):
                return a, track
        return None, None

    def findings_file(self, name, rest, slug):
        m = FINDINGS_FILE_RE.search(rest)
        if m:
            return m.group(1)
        names = sorted(n for n in self.list_dir(name) if n.startswith("FINDINGS-") and slug in n)
        return names[-1] if names else None

    def on_review(self, name, rest, hhmm):
        """Records a DONE-REVIEW for a dispatched job; resolves the job once both tracks are in."""
        a, track = self.match_review(name, rest)
        if a is None:
            return []
        count = COUNT_RE.search(rest)
        count = int(count.group(1)) if count else None
        items = items_in(rest)
        fname = self.findings_file(name, rest, a["slug"])
        if count is not None and len(items) < count and fname:
            from_file = items_in_findings_file(self.read_file(os.path.join(name, fname)))
            if len(from_file) >= len(items):
                items = from_file
        a["verdicts"][track] = {"count": count, "items": items, "file": fname, "leader": bool(LEADER_REVIEW_RE.search(rest)), "t": hhmm}
        if a["verdicts"]["code"] is None or a["verdicts"]["sec"] is None:
            return []
        a["closed"] = True
        return self.resolve(a, hhmm)

    def resolve(self, a, hhmm):
        v = a["verdicts"]
        ledger = self.ledger_for(a["branch"])
        tag = "%s %s %s r%d" % (hhmm, a["slug"], a["tip"], a["round"])
        problems = []
        for track in ("code", "sec"):
            t = v[track]
            if t["count"] is None:
                problems.append("%s gave no findings:N" % a[track])
            elif len(t["items"]) != t["count"]:
                problems.append("%s findings count %d vs %d named" % (a[track], t["count"], len(t["items"])))
            if t["leader"]:
                problems.append("%s asks a leader call" % a[track])
        blocking = [(a[tr], fid, sev) for tr in ("code", "sec") for fid, sev in v[tr]["items"] if sev in BLOCKING_SEVERITIES]
        named = "; ".join("%s %s" % (a[tr], ", ".join("%s %s" % i for i in v[tr]["items"]) or "CLEAN") for tr in ("code", "sec"))
        files = " ".join("F/%s/%s" % (a[tr], v[tr]["file"]) for tr in ("code", "sec") if v[tr]["file"])
        if problems or blocking:
            why = "; ".join(problems + ["%s %s %s" % b for b in blocking])
            return [("ledger", ledger, "%s: %s -> leader (dispatch #%d)" % (tag, named, a["id"])),
                    ("queue", "%s %s r%d: %s (MED/HIGH, count or leader call): leader decides. %s" % (a["slug"], a["branch"], a["round"], why, files))]
        lows = [(a[tr], fid) for tr in ("code", "sec") for fid, _ in v[tr]["items"]]
        if not lows:
            return [("ledger", ledger, "%s REVIEWED both tracks: code CLEAN %s, sec CLEAN %s (dispatch #%d)" % (tag, a["code"], a["sec"], a["id"])),
                    ("queue", "%s %s %s REVIEWED both tracks r%d: ready to merge (%s)" % (a["slug"], a["branch"], a["tip"], a["round"], a["worker"]))]
        if a["round"] >= self.rules["round_cap"]:
            return [("backlog", "%s %s %s r%d LOW after the round cap (G9): %s %s" % (a["slug"], a["branch"], a["tip"], a["round"], named, files)),
                    ("ledger", ledger, "%s REVIEWED both tracks, %d LOW to backlog (G9): %s (dispatch #%d)" % (tag, len(lows), named, a["id"])),
                    ("queue", "%s %s %s REVIEWED both tracks r%d, %d LOW to backlog: ready to merge (%s)" % (a["slug"], a["branch"], a["tip"], a["round"], len(lows), a["worker"]))]
        msg = "%s dispatch #%d: %s r%d reviews in, %d LOW to fold: %s. Files: %s. Fold all %d as new commits (never amend), then DONE r%d with the new range." % (
            hhmm, a["id"], a["slug"], a["round"], len(lows), named, files or "the reviewers' status lines", len(lows), a["round"] + 1)
        if len(msg) > TELL_MAX:
            ids = "; ".join("%s %s" % (a[tr], ",".join(fid for fid, _ in v[tr]["items"])) for tr in ("code", "sec"))
            msg = "%s dispatch #%d: %s r%d: %d LOW to fold (%s). Files: %s. Fold all as new commits (never amend), then DONE r%d." % (
                hhmm, a["id"], a["slug"], a["round"], len(lows), ids, files, a["round"] + 1)
        assert len(msg) <= TELL_MAX, len(msg)
        return [("tell", a["worker"], msg),
                ("ledger", ledger, "%s: %s -> %s fold (dispatch #%d)" % (tag, named, a["worker"], a["id"]))]


def now_hhmm():
    return os.environ.get("DISPATCH_NOW") or time.strftime("%H:%M")


def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def read_text(path):
    try:
        with open(path, errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def status_folders(max_age_days=2.0):
    """Lists sprint folders whose status.md changed in the last max_age_days."""
    out, cutoff = [], time.time() - max_age_days * 86400
    for name in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, name, "status.md")
        if name in SKIP_FOLDERS or not os.path.isfile(path):
            continue
        if os.path.getmtime(path) >= cutoff:
            out.append(name)
    return out


def head(folder, n=HEAD_LINES):
    lines = read_text(os.path.join(ROOT, folder, "status.md")).split("\n")
    return [l for l in lines[:n] if l.strip()]


def load_agents():
    path = os.environ.get("DISPATCH_AGENTS_JSON")
    if path:
        return json.loads(read_text(path))
    out = subprocess.run(["herdr", "agent", "list"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr[:200]
    return json.loads(out.stdout)


def make_engine(state):
    table = parse_table(read_text(os.path.join(LEADER, "dispatch-table.txt")))
    rules = parse_rules(read_text(os.path.join(LEADER, "RULES-review.md")))
    list_dir = lambda folder: os.listdir(os.path.join(ROOT, folder)) if os.path.isdir(os.path.join(ROOT, folder)) else []
    return Engine(table, rules, state, read_file=lambda rel: read_text(os.path.join(ROOT, rel)), list_dir=list_dir, resolve_tip=git_tip)


def git_tip(branch):
    """Returns the full sha a local branch points at (read only), or None."""
    assert re.match(r"^[A-Za-z][A-Za-z0-9._/-]*$", branch), branch
    out = subprocess.run(["git", "-C", REPO, "rev-parse", "--verify", "-q", "refs/heads/%s^{commit}" % branch],
                         capture_output=True, text=True, timeout=30)
    return out.stdout.strip() if out.returncode == 0 else None


def append(path, line):
    with open(path, "a") as fh:
        fh.write(line.rstrip("\n") + "\n")


def prepend(path, line):
    old = read_text(path)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(line + "\n" + old)
    os.replace(tmp, path)


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, STATE_PATH)


def run_actions(actions, hhmm, agents):
    """Executes actions for real: tells via tell.sh, ledger and queue appends."""
    tell = os.environ.get("DISPATCH_TELL") or os.path.join(LEADER, "tell.sh")
    os.makedirs(MONITOR_DIR, exist_ok=True)
    follow = []
    facts_script = os.environ.get("DISPATCH_FACTS") or os.path.join(HERE, "review-facts.sh")
    for act in actions:
        if act[0] == "facts":
            path = os.path.join(ROOT, act[1])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            try:
                out = subprocess.run(["bash", facts_script, REPO, act[2]], capture_output=True, text=True, timeout=120)
                rc, text = out.returncode, out.stdout if out.returncode == 0 else "review-facts failed rc=%d: %s\n" % (out.returncode, out.stderr[:500])
            except (OSError, subprocess.TimeoutExpired) as err:
                rc, text = -1, "review-facts did not finish: %s\n" % err
            with open(path, "w") as fh:
                fh.write(text)
            print("facts %s rc=%d" % (act[1], rc))
        elif act[0] == "tell":
            pane = lookup_pane(act[1], agents)
            if pane is None:
                follow.append(("queue", "no single pane named %s (or it is the owner pane): send by hand: %s" % (act[1], act[2][:300])))
                continue
            out = subprocess.run(["bash", tell, pane, act[2]], capture_output=True, text=True, timeout=60)
            print("tell %s %s rc=%d %s" % (act[1], pane, out.returncode, out.stdout.strip()[:60]))
            if out.returncode != 0:
                follow.append(("queue", "tell to %s failed (rc %d): %s" % (act[1], out.returncode, act[2][:300])))
        elif act[0] == "ledger":
            append(os.path.join(LEADER, act[1]), act[2])
            print("ledger %s: %s" % (act[1], act[2]))
        elif act[0] == "backlog":
            append(os.path.join(LEADER, "backlog.md"), "- %s %s (dispatch)" % (hhmm, act[1]))
            print("backlog: %s" % act[1])
    for act in actions + follow:
        if act[0] == "queue":
            line = "%s %s" % (hhmm, act[1])
            append(QUEUE_PATH, line)
            prepend(os.path.join(MONITOR_DIR, "status.md"), "%s LEADER %s" % (hhmm, act[1][:600]))
            print("queue: %s" % act[1])


def take_lock():
    try:
        os.mkdir(LOCK_DIR)
        return True
    except FileExistsError:
        if time.time() - os.path.getmtime(LOCK_DIR) > 600:
            os.rmdir(LOCK_DIR)
            return take_lock()
        return False


def cmd_tick():
    """One live pass. Off unless leader/dispatch-on exists; the first pass only records what it has seen."""
    if not os.path.exists(ON_FLAG):
        print("dispatch off (touch leader/dispatch-on to switch on)")
        return 0
    wfenv.require_owner_pane()
    if not take_lock():
        print("dispatch locked (another tick is running)")
        return 0
    try:
        hhmm = now_hhmm()
        first = not os.path.exists(STATE_PATH)
        state = new_state() if first else json.loads(read_text(STATE_PATH))
        engine = make_engine(state)
        agents = load_agents()
        rows = agents.get("result", {}).get("agents", [])
        working = {a.get("name") for a in rows if a.get("agent_status") == "working"}
        present = {a.get("name") for a in rows}
        engine.unavailable = {n for n in engine.reviewer_names if n in working or n not in present}
        actions = []
        for folder in status_folders():
            lines = head(folder)
            if not lines:
                continue
            seen = state["seen"].get(folder)
            if first or seen is None:
                if engine.is_reviewer(folder):
                    for line in reversed(lines):
                        parsed = parse_line(line)
                        if parsed:
                            engine.note_reviewer(folder, parsed[1], hhmm)
                state["seen"][folder] = lines[0]
                continue
            new = []
            for line in lines:
                if line == seen:
                    break
                new.append(line)
            else:
                new = lines[:1]
            for line in reversed(new):
                p = parse_line(line)
                actions += engine.feed(folder, line, (p[0] if p and p[0] else hhmm))
            state["seen"][folder] = lines[0]
        actions += engine.retry_pending(hhmm)
        if first:
            save_state(state)
            print("dispatch initialised (%d status files seen, nothing sent)" % len(state["seen"]))
            return 0
        run_actions(actions, hhmm, agents)
        save_state(state)
        print("dispatch tick %s: %d actions, %d pending, %d open" % (
            hhmm, len(actions), len(state["pending"]), sum(1 for a in state["assignments"] if not a["closed"])))
        return 0
    finally:
        os.rmdir(LOCK_DIR)


def window_lines(folder, since, now_m):
    """Returns [(age_min, hhmm, line)] from the top of a status file, newest first, within since minutes."""
    out, last_t, last_age = [], None, -1
    for line in head(folder, 400):
        p = parse_line(line)
        t = p[0] if p and p[0] else last_t
        if t is None:
            continue
        age = (now_m - minutes(t)) % 1440
        if age < last_age - 5:
            break
        if age > since:
            break
        out.append((age, t, line))
        last_t, last_age = t, age
    return out


def state_before(folder, since, now_m):
    """Returns the newest status line of a folder that is older than the window, or None."""
    last_t, last_age = None, -1
    for line in head(folder, 400):
        p = parse_line(line)
        t = p[0] if p and p[0] else last_t
        if t is None:
            continue
        age = (now_m - minutes(t)) % 1440
        if age < last_age - 5:
            return None
        if age > since:
            return line, t
        last_t, last_age = t, age
    return None


def cmd_dry_run(since):
    """Replays the last since minutes of status lines through the engine; prints, sends nothing."""
    hhmm = now_hhmm()
    now_m = minutes(hhmm)
    state = new_state()
    engine = make_engine(state)
    engine.shadow = True
    events = []
    for folder in status_folders():
        if engine.is_reviewer(folder):
            before = state_before(folder, since, now_m)
            parsed = parse_line(before[0]) if before else None
            if parsed:
                engine.note_reviewer(folder, parsed[1], before[1])
        for age, t, line in window_lines(folder, since, now_m):
            events.append((age, folder, t, line))
    events.sort(key=lambda e: -e[0])
    print("# Dispatch dry run %s, last %d min, %d status lines\n" % (hhmm, since, len(events)))
    dones = []
    for age, folder, t, line in events:
        acts = engine.feed(folder, line, t) + engine.retry_pending(t)
        p = parse_line(line)
        if p and p[1] == "DONE" and not (engine.is_reviewer(folder) and not RANGE_RE.search(p[2])):
            dones.append((t, folder, line, acts))
        for act in acts:
            print("- %s WOULD %s %s" % (t, act[0], " | ".join(str(x) for x in act[1:])[:500]))
    print("\n## Reviews in the window, through the resolution rules\n")
    tally = {}
    for age, folder, t, line in events:
        p = parse_line(line)
        if not p or p[1] != "DONE-REVIEW":
            continue
        verdict = review_verdict(engine, folder, p[2])
        tally[verdict] = tally.get(verdict, 0) + 1
        print("- %s %s: %s || %s" % (t, folder, verdict, p[2][:150]))
    print("\nTally: %s" % ", ".join("%s %d" % kv for kv in sorted(tally.items(), key=lambda kv: -kv[1])))
    print("\n## Pending at the end: %d" % len(state["pending"]))
    for job in state["pending"]:
        print("- %s %s %s (since %s)" % (job["worker"], job["slug"], job["range"], job["t"]))
    print("\n## Compare with the ledgers (same window)\n")
    ledgers = {}
    for _, path in engine.table["ledgers"]:
        ledgers[path] = [l for l in read_text(os.path.join(LEADER, path)).split("\n") if re.match(r"^\d\d:\d\d ", l)
                         and (now_m - minutes(l[:5])) % 1440 <= since + 10]
    for t, folder, line, acts in dones:
        clean = BOILERPLATE_RE.sub(" ", line)
        keys = {x[:7] for x in SHA_RE.findall(clean)}
        br = WORK_BRANCH_RE.search(clean) or ANY_BRANCH_RE.search(clean)
        if br:
            keys.add(br.group(1).split("/")[-1].split("-")[-1])
        keys = {k for k in keys if len(k) >= 4}
        later = lambda l: (minutes(l[:5]) - minutes(t)) % 1440 <= 60
        print("### %s %s: %s" % (t, folder, line[:240]))
        later_route = [a for a in state["assignments"] if a["worker"] == folder and a["t"] == t and a["routed"] != t]
        parked = "parked, routed at %s to %s + %s" % (later_route[0]["routed"], later_route[0]["code"], later_route[0]["sec"]) if later_route else "parked (no free pair)"
        print("- dispatcher: %s" % ("; ".join("%s %s" % (a[0], a[1] if a[0] != "queue" else a[1][:160]) for a in acts) or parked))
        hits = [l for lines in ledgers.values() for l in lines if later(l) and any(re.search(r"(?<![\w-])%s" % re.escape(k), l) for k in keys)]
        print("- ledger: %s" % (" || ".join(h[:220] for h in hits[:3]) or "no ledger line found"))
    return 0


def review_verdict(engine, folder, rest):
    """Names what the resolution rules would do with one DONE-REVIEW line, read on its own."""
    count = COUNT_RE.search(rest)
    items = items_in(rest)
    fname = FINDINGS_FILE_RE.search(rest)
    if count and len(items) < int(count.group(1)) and fname:
        from_file = items_in_findings_file(engine.read_file(os.path.join(folder, fname.group(1))))
        items = from_file if len(from_file) >= len(items) else items
    if count is None:
        return "leader (no findings:N)"
    if LEADER_REVIEW_RE.search(rest):
        return "leader (leader call)"
    if any(sev in BLOCKING_SEVERITIES for _, sev in items):
        return "leader (MED/HIGH)"
    if len(items) != int(count.group(1)):
        return "leader (count %s vs %d named)" % (count.group(1), len(items))
    return "clean track" if not items else "LOW only: worker fold or backlog"


def cmd_status():
    state = json.loads(read_text(STATE_PATH) or "null") or new_state()
    print("on" if os.path.exists(ON_FLAG) else "off")
    for a in state["assignments"]:
        if not a["closed"]:
            print("open #%d %s %s %s r%d -> %s + %s" % (a["id"], a["slug"], a["branch"], a["tip"][:9], a["round"], a["code"], a["sec"]))
    for job in state["pending"]:
        print("pending %s %s %s since %s" % (job["worker"], job["slug"], job["range"], job["t"]))
    return 0


def cmd_close(ident):
    if not take_lock():
        print("dispatch locked")
        return 1
    try:
        state = json.loads(read_text(STATE_PATH))
        hit = [a for a in state["assignments"] if a["id"] == ident]
        assert len(hit) == 1, "no assignment #%d" % ident
        hit[0]["closed"] = True
        save_state(state)
        print("closed #%d" % ident)
        return 0
    finally:
        os.rmdir(LOCK_DIR)


def main(argv):
    wfenv.require_root(ROOT)
    cmd = argv[1] if len(argv) > 1 else "tick"
    if cmd == "tick":
        return cmd_tick()
    if cmd == "dry-run":
        since = int(argv[argv.index("--since") + 1]) if "--since" in argv else 120
        assert 1 <= since <= 1380, "since must be 1..1380 minutes"
        return cmd_dry_run(since)
    if cmd == "status":
        return cmd_status()
    if cmd == "close" and len(argv) == 3:
        return cmd_close(int(argv[2]))
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
