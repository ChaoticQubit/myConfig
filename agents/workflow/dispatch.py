"""Leader dispatcher (DEC-184 G7): routes worker DONE lines to a free reviewer pair.

Commands: tick (one pass, live only when leader/dispatch-on exists), dry-run
[--since MIN] (replays recent status lines, sends nothing), status, close ID,
route <branch> <base>..<tip> <code-rv> <sec-rv> [rN] [worker] (records a leader route, tells both),
drop <branch> <reason> (removes its pending or open item, logs it).
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
DONE_TOKEN_RE = re.compile(
    r"^(?:(\d\d:\d\d)\s+)?(?:\d\d-\d\d\s+)?(?:[A-Za-z0-9][\w.-]*:\s+|[a-z][\w.-]*\s+(?=D))?"
    r"(DONE-\d\d:?\d\d-([A-Za-z0-9._-]+?))(?:\.md)?:?(?=\s|$)(.*)$"
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
    r"(?i:\bfold(?:s|ed|ing)?\b(?!\s+in\b))|(?i:\blows?\b)|-f\d+\b"
    r"|\brv-[\w-]+\s+(?:r\d\s+)?(?:[A-Z][A-Z0-9]*-?\d+|nits?\b|\d+ nits?\b)|FINDINGS-"
    r"|-R\d+-[A-Z]+\d+\b|(?<![\w/.-])r\d+\s+\(?[A-Z]{1,4}\d+\b"
)
FINDINGS_FILE_RE = re.compile(r"\b(FINDINGS-\d\d:\d\d-[A-Za-z0-9._-]+?\.md)")
ROUND_RE = re.compile(r"(?<![\w/.-])r(\d)(?![\w.-])|\bround (\d)\b")
COUNT_RE = re.compile(r"\bfindings:\s*(\d+)")
ITEM_RE = re.compile(r"\b([A-Z][A-Z0-9]*-?\d+[a-z]?)\b\s*[:(-]?\s*((?i:critical|high|medium|med|low))\b")
SEV = r"(?:critical|high|medium|med|low)"
CLOSED_AFTER_RE = re.compile(
    r"(?:/" + SEV + r")?(?:\s*\+\s*(?:[a-z][\w-]*\s+)?[A-Z][A-Z0-9]*-?\d+[a-z]?(?:\s+" + SEV + r")?)*\s+closed\b", re.I
)
NOTES_RE = re.compile(r"^#{1,4}\s*(notes|closures|checked|nits|advisor|read list)", re.I)
NO_CODE_RE = re.compile(r"\bno[ -]code\b|\bno (?:new )?commits\b|\bnothing to review\b", re.I)
NO_WORK_RE = re.compile(r"\bno branch(?=\s*(?:[,.;:)]|$))|(?:^|[(,:;.]\s*)read[ -]only(?=\s*(?:[,;)]|$))", re.I)
DONE_WORD_RE = re.compile(r"(?<![\w-])DONE(?![\w-])")
LEADER_DONE_RE = re.compile(r"QUESTION|ASK-|leader call|owner question", re.I)
LEADER_REVIEW_RE = re.compile(r"leader call|QUESTION|owner question", re.I)

FREE_KINDS = {"DONE-REVIEW", "IDLE", "DONE"}
BUSY_KINDS = {"STARTED", "START", "WORKING", "ACK", "PROGRESS", "REVIEWING", "PAUSED", "HOLD", "STEP", "PHASE"}
BLOCKING_SEVERITIES = {"CRITICAL", "HIGH", "MED"}


def parse_line(line):
    """Splits one status line into (time or None, KIND, rest), or None when it is prose.

    Accepts "HH:MM KIND rest", "HH:MM name: KIND rest", "HH:MM name KIND rest" (a lowercase pane name) and "KIND rest" (no time).
    A DONE file name in the KIND place ("HH:MM DONE-HH:MM-<slug>[.md]: rest") reads as "DONE <slug>: rest DONE-HH:MM-<slug>.md".
    """
    t = DONE_TOKEN_RE.match(line.strip())
    if t:
        return (t.group(1), "DONE", "%s: %s %s.md" % (t.group(3), t.group(4).strip(), t.group(2)))
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    return (m.group(1), m.group(2), m.group(3).strip())


def parse_table(text):
    """Reads dispatch-table.txt rows "code|sec <branch-glob> <name>...", "ledger <branch-glob> <file>" and "line <branch-glob> <integration-branch>".

    The first row whose glob matches a branch wins for that track; names are the fallback order.
    Returns {"code": [(glob, names)], "sec": [(glob, names)], "ledgers": [(glob, file)], "lines": [(glob, branch)]}.
    """
    table = {"code": [], "sec": [], "ledgers": [], "lines": []}
    for raw in text.splitlines():
        parts = raw.split()
        if len(parts) >= 3 and parts[0] in ("code", "sec"):
            assert len(set(parts[2:])) == len(parts[2:]), "duplicate reviewer in row: %s" % raw
            table[parts[0]].append((parts[1], parts[2:]))
        elif len(parts) == 3 and parts[0] == "ledger":
            table["ledgers"].append((parts[1], parts[2]))
        elif len(parts) == 3 and parts[0] == "line":
            table["lines"].append((parts[1], parts[2]))
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


NEXT_TASK_RE = re.compile(r"(?:^|[.;)]\s+)(?:Now|Next|Then|Starting|Back on|Back to)\b")


def split_items(text):
    """Splits a DONE naming several ranges into one text per range, cut at the '; ' before each later range.

    Ranges sharing one tip (a second base for the same work) are one item.
    Returns [text] for one tip (or no range), the parts when each holds exactly one distinct range, else None.
    """
    ms = list(RANGE_RE.finditer(text))
    if len({m.group(2)[:7] for m in ms}) < 2:
        return [text]
    firsts = [m for i, m in enumerate(ms) if m.group(0) not in {x.group(0) for x in ms[:i]}]
    cuts = []
    for prev, m in zip(firsts, firsts[1:]):
        cut = text.rfind("; ", prev.end(), m.start())
        if cut < 0:
            return None
        cuts.append(cut)
    parts = [text[a:b].strip(" ;") for a, b in zip([0] + [c + 2 for c in cuts], cuts + [len(text)])]
    if any(len({m.group(0) for m in RANGE_RE.finditer(p)}) != 1 for p in parts):
        return None
    return parts


def job_slug(rest, branch, done_file, file_first=False):
    """Returns a DONE's slug: its first token when slug-shaped, the branch tail when it names the branch, else the DONE file's slug.

    A version (2.4.2), a round word (r2) or an id list (PROTO-3-SEC-F1/F2) is no slug; the branch tail is the last resort.
    file_first (one item of a several-item line) takes the DONE file's slug before the first token.
    """
    tokens = [t for t in re.split(r"[\s;,]+", rest) if t]
    first = tokens[0].rstrip(":") if tokens else ""
    tail = branch.split("/")[-1]
    m = re.fullmatch(r"DONE-\d\d:?\d\d-(.+)\.md", done_file or "")
    if file_first and m:
        return m.group(1)
    if first == branch:
        return tail
    if re.fullmatch(r"[A-Za-z][\w.-]*", first) and not re.fullmatch(r"r\d", first):
        return first
    return m.group(1) if m else tail


def done_head(text):
    """Returns the part of a DONE about this work: everything before its first next-task sentence ("Now: ...", "Next: ...").

    Fold and round words after that marker describe the worker's next task, not this DONE.
    """
    m = NEXT_TASK_RE.search(text)
    return text[:m.start()] if m else text


def items_in(text):
    """Returns ordered unique (id, severity) pairs a text names as open.

    An item is closed, and left out, only when "closed" follows its severity directly or after a + chain of items
    ("F1 MED closed", "F1 MED + rv-code4 F1 MED + N1 closed"); "fail-closed", "not closed" or closed later in its text keep it open.
    """
    seen, out = set(), []
    for m in ITEM_RE.finditer(text):
        fid, sev = m.group(1), m.group(2)
        if CLOSED_AFTER_RE.match(text, m.end()):
            continue
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
    read_file(relpath), list_dir(folder), resolve_tip(branch) and count_ahead(tip, line, hhmm) are injected so tests need
    no real sprint folder or repo; count_ahead returns the commits tip has past line as it stood at hhmm, or None when unknown;
    is_ancestor(old, new) returns True, False or None (unknown).
    """

    def __init__(self, table, rules, state, read_file=None, list_dir=None, resolve_tip=None, count_ahead=None, is_ancestor=None):
        self.table = table
        self.rules = rules
        self.state = state
        self.read_file = read_file or (lambda path: "")
        self.list_dir = list_dir or (lambda folder: [])
        self.resolve_tip = resolve_tip or (lambda branch: None)
        self.count_ahead = count_ahead or (lambda tip, line, hhmm: None)
        self.is_ancestor = is_ancestor or (lambda old, new: None)
        self.shadow = False
        self.unavailable = set()
        self.present = None
        self.reviewer_names = {n for track in ("code", "sec") for _, names in table[track] for n in names}

    def is_reviewer(self, folder):
        return folder in self.reviewer_names or folder.startswith("rv-")

    def feed(self, folder, line, hhmm):
        """Processes one status line written by folder at hhmm; returns actions.

        A line holding the word DONE that is not handled as a DONE or a reviewer's DONE-REVIEW goes to the leader queue.
        """
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
        handled = kind.startswith("DONE") and (kind != "DONE-REVIEW" or self.is_reviewer(folder))
        if not handled and DONE_WORD_RE.search(line):
            actions.append(("queue", "%s line holds DONE but is no DONE status, not routed: %s" % (folder, line.strip()[:220])))
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

    def has_pane(self, name):
        """False only when the live pane list is known and has no single pane for name; tests leave present as None."""
        return self.present is None or name in self.present

    def is_free(self, name):
        info = self.state["reviewers"].get(name)
        if info is None or info["kind"] not in FREE_KINDS:
            return False
        if name in self.unavailable or not self.has_pane(name):
            return False
        return self.shadow or self.open_for(name) is None

    def is_gone(self, name):
        info = self.state["reviewers"].get(name)
        return name in self.unavailable or not self.has_pane(name) or (info is not None and info["kind"] == "LIMIT")

    def ledger_for(self, branch):
        for glob, path in self.table["ledgers"]:
            if fnmatch.fnmatch(branch, glob):
                return path
        raise AssertionError("no ledger row matches %s" % branch)

    def line_for(self, branch):
        """Returns the integration branch of the first line row whose glob matches branch, or None."""
        for glob, line in self.table["lines"]:
            if fnmatch.fnmatch(branch, glob):
                return line
        return None

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

    def on_done(self, folder, rest, hhmm, item=False):
        """Handles a worker DONE: route to a pair, park it, or hand it to the leader queue.

        A line naming several ranges is handled item by item (item=True); one that cannot be split goes to the leader.
        """
        short = rest[:220]
        clean = BOILERPLATE_RE.sub(" ", rest)
        if LEADER_DONE_RE.search(clean):
            return [("queue", "%s DONE needs the leader (question or leader call): %s" % (folder, short))]
        if NOT_REVIEW_RE.search(re.sub(r"^\d\d:\d\d\s+(\d\d-\d\d\s+)?", "", clean)):
            return [("queue", "%s DONE reports a merge or push: leader reads it: %s" % (folder, short))]
        parts = [clean] if item else split_items(clean)
        if parts is None:
            return [("queue", "%s DONE holds %d ranges not split by '; ' into one item each: leader routes them: %s"
                     % (folder, len({m.group(0) for m in RANGE_RE.finditer(clean)}), short))]
        if len(parts) > 1:
            return [act for part in parts for act in self.on_done(folder, part, hhmm, item=True)]
        if (NO_CODE_RE.search(clean) or NO_WORK_RE.search(done_head(clean))) and not RANGE_RE.search(clean):
            return [("queue", "%s DONE says no code: nothing for reviewers, leader reads it: %s" % (folder, short))]
        branch, rng, done_file = self.find_work(folder, clean)
        if branch is None or rng is None:
            return [("queue", "%s DONE not routed (no branch, or no range and no named tip): %s" % (folder, short))]
        line = self.line_for(branch)
        if line is not None and self.count_ahead(rng[1], line, hhmm) == 0:
            return [("queue", "%s DONE %s tip %s has 0 commits ahead of %s: nothing for reviewers, leader reads it: %s"
                     % (folder, branch, rng[1][:9], line, short))]
        slug = job_slug(rest, branch, done_file, file_first=item)
        prior = [a for a in self.state["assignments"] if a["branch"] == branch and not a.get("dropped")]
        waiting = [p for p in self.state["pending"] if p["branch"] == branch]
        if waiting:
            assert len(waiting) == 1, waiting
            waiting[0].update(slug=slug, range=rng[0], tip=rng[1], done_file=done_file or waiting[0]["done_file"])
            return []
        if any(not a["closed"] for a in prior):
            return [("queue", "%s DONE %s while its review is still open: leader" % (folder, slug))]
        head = done_head(clean)
        named = [int(a or b) for a, b in ROUND_RE.findall(head)]
        if not prior and (FOLD_RE.search(head) or max(named + [1]) > 1):
            return [("queue", "%s DONE %s folds findings of a leader-routed review: leader routes the confirm" % (folder, slug))]
        last = prior[-1] if prior else None
        rnd = last["round"] + 1 if last else 1
        if last is not None and rnd > self.rules["round_cap"]:
            return self.past_cap(folder, slug, branch, rng[1], last, hhmm)
        rng_text, tip = rng
        if last is not None:
            rng_text, tip, why = self.next_range(last, rng)
            if why:
                return [("queue", "%s DONE %s %s: %s: leader" % (folder, slug, branch, why))]
        job = {"slug": slug, "branch": branch, "range": rng_text, "tip": tip, "worker": folder,
               "round": rnd, "done_file": done_file, "t": hhmm,
               "prefer": (last["code"], last["sec"]) if last else None}
        self.state["pending"].append(job)
        actions = self.retry_pending(hhmm, only=job)
        if job in self.state["pending"]:
            actions += self.queue_rule()
        return actions

    def next_range(self, last, rng):
        """Returns (range, tip, None) for the round after last, or (None, None, why) when it cannot be read as a delta.

        The worker's range stands when its base is the last reviewed tip or after it (a fold that skips a merge of the line);
        an older base becomes last reviewed tip..new tip.
        """
        old, tip = last["tip"], rng[1]
        if tip[:7] == old[:7]:
            return None, None, "no new commits since r%d tip %s" % (last["round"], old[:9])
        m = RANGE_RE.fullmatch(rng[0])
        if m and (m.group(1)[:7] == old[:7] or self.is_ancestor(old, m.group(1)) is True):
            return rng[0], tip, None
        if self.is_ancestor(old, tip) is False:
            return None, None, "r%d tip %s is not in %s (rebased?)" % (last["round"], old[:9], tip[:9])
        return "%s..%s" % (old, tip), tip, None

    def past_cap(self, folder, slug, branch, tip, last, hhmm):
        """A fold after the last allowed round: the leader only for an open HIGH, else backlog with branch, tip and findings files."""
        v = last["verdicts"]
        tracks = [tr for tr in ("code", "sec") if v[tr]]
        highs = ["%s %s %s" % (last[tr], fid, sev) for tr in tracks for fid, sev in v[tr]["items"] if sev in ("CRITICAL", "HIGH")]
        files = " ".join("F/%s/%s" % (last[tr], v[tr]["file"]) for tr in tracks if v[tr]["file"])
        cap = self.rules["round_cap"]
        if highs:
            return [("queue", "%s DONE %s %s %s: fold after r%d with an open HIGH (%s): leader decides r%d. %s"
                     % (folder, slug, branch, tip[:9], last["round"], "; ".join(highs), last["round"] + 1, files))]
        return [("backlog", "%s %s %s fold after r%d, past round cap %d, not reviewed (no open HIGH); findings %s; worker %s"
                 % (slug, branch, tip, last["round"], cap, files or "none named", folder)),
                ("ledger", self.ledger_for(branch), "%s %s %s fold after r%d -> backlog (round cap %d, no open HIGH)"
                 % (hhmm, slug, tip[:9], last["round"], cap))]

    def drop(self, branch, reason, hhmm):
        """Removes branch's pending item and closes its open review on the leader's word; returns one ledger line each.

        A dropped review was never reviewed, so later DONEs on the branch do not count it as a round.
        Raises ValueError when the reason is empty or nothing is pending or open on branch.
        """
        reason = " ".join(reason.split())
        if not reason:
            raise ValueError("drop needs a reason")
        waiting = [p for p in self.state["pending"] if p["branch"] == branch]
        still = [a for a in self.state["assignments"] if a["branch"] == branch and not a["closed"]]
        if not waiting and not still:
            raise ValueError("nothing pending or open on %s" % branch)
        self.state["pending"] = [p for p in self.state["pending"] if p["branch"] != branch]
        ledger = self.ledger_for(branch)
        actions = [("ledger", ledger, "%s %s %s pending dropped by leader: %s" % (hhmm, p["slug"], p["tip"][:9], reason)) for p in waiting]
        for a in still:
            a["closed"] = True
            a["dropped"] = reason
            actions.append(("ledger", ledger, "%s %s %s #%d open (%s + %s) dropped by leader: %s"
                            % (hhmm, a["slug"], a["tip"][:9], a["id"], a["code"], a["sec"], reason)))
        assert not any(p["branch"] == branch for p in self.state["pending"]) and len(actions) == len(waiting) + len(still)
        return actions

    def leader_route(self, branch, rng, code, sec, rnd, worker, hhmm):
        """Records a route the leader chose (any two reviewers, any round) and returns its facts, tells and ledger line.

        rnd is None (next round on the branch) or "rN". Raises ValueError for input the leader must fix.
        """
        m = RANGE_RE.fullmatch(rng)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._/-]*", branch) or m is None:
            raise ValueError("branch and <base>..<tip> range needed, got %s %s" % (branch, rng))
        if code == sec or worker in (code, sec):
            raise ValueError("code, sec and worker must be three different names: %s %s %s" % (code, sec, worker))
        missing = [n for n in (code, sec) if not self.has_pane(n)]
        if missing:
            raise ValueError("no live pane for %s" % ", ".join(missing))
        if rnd is not None and not re.fullmatch(r"r[1-9]\d?", rnd):
            raise ValueError("round must look like r1 or r2, got %s" % rnd)
        prior = [a for a in self.state["assignments"] if a["branch"] == branch and not a.get("dropped")]
        still = [a for a in prior if not a["closed"]]
        if still:
            raise ValueError("review #%d on %s is still open: dispatch.sh close %d first" % (still[0]["id"], branch, still[0]["id"]))
        number = int(rnd[1:]) if rnd else (prior[-1]["round"] + 1 if prior else 1)
        self.state["pending"] = [p for p in self.state["pending"] if p["branch"] != branch]
        job = {"slug": branch.split("/")[-1], "branch": branch, "range": rng, "tip": m.group(2), "worker": worker,
               "round": number, "done_file": None, "t": hhmm, "leader": True}
        return self.assign(job, (code, sec), hhmm)

    def pick_one(self, track, job, prefer, avoid=None):
        """Returns the reviewer for one track: the earlier round's reviewer when free, else the first free name (never avoid)."""
        if prefer is not None and prefer != avoid and self.is_free(prefer):
            return prefer
        for name in row_for(self.table[track], job["branch"]):
            if name not in (job["worker"], avoid) and self.is_free(name):
                return name
        return None

    def pick_pair(self, job):
        """Returns (code, sec) for a job, or None while either track has no free reviewer."""
        prefer = job["prefer"] or (None, None)
        code = self.pick_one("code", job, prefer[0])
        sec = self.pick_one("sec", job, prefer[1], avoid=code)
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
        line = "%s %s %s -> %s code + %s sec (%s #%d %s)" % (hhmm, a["slug"], a["tip"], code, sec,
                                                             "leader route" if a.get("leader") else "dispatch", a["id"], rnd)
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
        named = "; ".join("%s %s" % (a[tr], ", ".join("%s %s" % tuple(i) for i in v[tr]["items"]) or "CLEAN") for tr in ("code", "sec"))
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
    return Engine(table, rules, state, read_file=lambda rel: read_text(os.path.join(ROOT, rel)), list_dir=list_dir, resolve_tip=git_tip,
                  count_ahead=lambda tip, line, hhmm: git_ahead(REPO, tip, line, hhmm),
                  is_ancestor=lambda old, new: git_is_ancestor(REPO, old, new))


def git_tip(branch):
    """Returns the full sha a local branch points at (read only), or None."""
    assert re.match(r"^[A-Za-z][A-Za-z0-9._/-]*$", branch), branch
    out = subprocess.run(["git", "-C", REPO, "rev-parse", "--verify", "-q", "refs/heads/%s^{commit}" % branch],
                         capture_output=True, text=True, timeout=30)
    return out.stdout.strip() if out.returncode == 0 else None


def git_ahead(repo, tip, line, hhmm=None):
    """Returns how many commits tip has that the local integration branch line lacks (read only), or None when either does not resolve.

    With hhmm, line is read from its reflog as it stood at the end of that minute today, so a replay counts against the line of
    that time; a minute still ahead of now reads the current tip.
    """
    assert re.match(r"^[0-9a-f]{7,40}$", tip), tip
    assert re.match(r"^[A-Za-z][A-Za-z0-9._/-]*$", line), line
    assert hhmm is None or re.match(r"^\d\d:\d\d$", hhmm), hhmm
    ref = "refs/heads/%s" % line if hhmm is None else "refs/heads/%s@{%s:59}" % (line, hhmm)
    out = subprocess.run(["git", "-C", repo, "rev-list", "--count", "%s..%s" % (ref, tip), "--"],
                         capture_output=True, text=True, timeout=30)
    return int(out.stdout.strip()) if out.returncode == 0 else None


def git_is_ancestor(repo, old, new):
    """Returns True when commit old is new or an ancestor of it, False when not, None when git cannot tell (read only)."""
    assert re.match(r"^[0-9a-f]{7,40}$", old) and re.match(r"^[0-9a-f]{7,40}$", new), (old, new)
    out = subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", old, new], capture_output=True, text=True, timeout=30)
    return {0: True, 1: False}.get(out.returncode)


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
        engine.present = {n for n in present if n and lookup_pane(n, agents)}
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


def worker_for(branch, reviewers):
    """Returns the one worker folder whose recent status lines name branch, or None when none or several do."""
    rx = re.compile(r"(?<![\w/-])%s(?![\w/-])" % re.escape(branch))
    hits = [f for f in status_folders() if not f.startswith("rv-") and f not in reviewers and any(rx.search(l) for l in head(f))]
    return hits[0] if len(hits) == 1 else None


def cmd_route(args):
    """Records a route the leader chose and tells both reviewers: route <branch> <base>..<tip> <code-rv> <sec-rv> [rN] [worker]."""
    if not 4 <= len(args) <= 6:
        print("usage: dispatch.sh route <branch> <base>..<tip> <code-rv> <sec-rv> [r1|r2] [worker]")
        return 2
    branch, rng, code, sec = args[:4]
    rnd = next((x for x in args[4:] if re.fullmatch(r"r\d+", x)), None)
    named = [x for x in args[4:] if x != rnd]
    if len(named) > 1:
        print("route takes one worker name, got %s" % named)
        return 2
    wfenv.require_owner_pane()
    if not os.path.exists(STATE_PATH):
        print("dispatch not initialised: run one tick first")
        return 2
    if not take_lock():
        print("dispatch locked (a tick is running): run route again")
        return 1
    try:
        hhmm = now_hhmm()
        state = json.loads(read_text(STATE_PATH))
        engine = make_engine(state)
        agents = load_agents()
        missing = [n for n in (code, sec) if lookup_pane(n, agents) is None]
        if missing:
            print("route refused: no single live pane named %s" % ", ".join(missing))
            return 3
        worker = named[0] if named else worker_for(branch, engine.reviewer_names)
        if worker is None or not os.path.isdir(os.path.join(ROOT, worker)):
            print("route refused: no single worker folder names %s; pass the worker as the last argument" % branch)
            return 2
        try:
            actions = engine.leader_route(branch, rng, code, sec, rnd, worker, hhmm)
        except ValueError as err:
            print("route refused: %s" % err)
            return 2
        run_actions(actions, hhmm, agents)
        save_state(state)
        a = state["assignments"][-1]
        print("routed #%d %s r%d %s -> %s code + %s sec (worker %s)" % (a["id"], a["branch"], a["round"], a["range"], code, sec, worker))
        return 0
    finally:
        os.rmdir(LOCK_DIR)


def cmd_drop(args):
    """Drops a branch's pending or open item on the leader's word and logs it: drop <branch> <reason...>."""
    if len(args) < 2:
        print("usage: dispatch.sh drop <branch> <reason>")
        return 2
    if not os.path.exists(STATE_PATH):
        print("dispatch not initialised: run one tick first")
        return 2
    if not take_lock():
        print("dispatch locked (a tick is running): run drop again")
        return 1
    try:
        hhmm = now_hhmm()
        state = json.loads(read_text(STATE_PATH))
        engine = make_engine(state)
        try:
            actions = engine.drop(args[0], " ".join(args[1:]), hhmm)
        except ValueError as err:
            print("drop refused: %s" % err)
            return 2
        assert all(act[0] == "ledger" for act in actions), actions
        run_actions(actions, hhmm, {})
        save_state(state)
        for act in actions:
            print(act[2])
        return 0
    finally:
        os.rmdir(LOCK_DIR)


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
    if cmd == "route":
        return cmd_route(argv[2:])
    if cmd == "drop":
        return cmd_drop(argv[2:])
    if cmd == "close" and len(argv) == 3:
        return cmd_close(int(argv[2]))
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
