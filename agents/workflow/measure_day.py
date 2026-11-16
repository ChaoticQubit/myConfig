"""Day measure for the DEC-184 G5 effort trial: tokens per merged branch, findings per branch, limit stops.

Usage: measure-day.sh [DAY] [BASELINE], dates as YYYY-MM-DD; DAY defaults to today, BASELINE to $WORKFLOW_BASELINE_DAY.
Needs WORKFLOW_ROOT (sprint folder); the repository comes from WORKFLOW_REPO or the git toplevel holding it.
measure-day.sh budget prints only the weekly budget check from $WORKFLOW_ROOT/leader/budget.md (also printed after every day report).
Merged branches come from git merge subjects, findings from FINDINGS-*.md files written that day,
limit stops from LIMIT status lines, tokens from this project's Claude Code transcripts (read only).
"""

import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dispatch
import wfenv

F = wfenv.ROOT
R = wfenv.repo(F)
PROJECTS = os.path.expanduser("~/.claude/projects")
PREFIX = "-" + R.strip("/").replace("/", "-").replace(".", "-")
DATE_RE = re.compile(r"^\d\d:\d\d\s+(\d\d)-(\d\d)\b")
MERGE_RE = re.compile(
    r"^Merge (?:branch |remote-tracking branch |commit )?'?([\w./-]+?)'?(?: \([0-9a-f]{7,40}\))? into '?([\w./-]+?)'?(?=[:\s]|$)"
)
SEVERITIES = ("CRITICAL", "HIGH", "MED", "LOW")


def dated_lines(text, top_date):
    """Dates each status line, newest first: an explicit MM-DD wins, and a jump back past midnight steps one day back.

    Returns [(date, KIND, line)] for lines that parse as status lines.
    """
    out, date, prev = [], top_date, None
    for line in text.split("\n"):
        parsed = dispatch.parse_line(line)
        if parsed is None or parsed[0] is None:
            continue
        minute = dispatch.minutes(parsed[0])
        explicit = DATE_RE.match(line.strip())
        if explicit:
            date = datetime.date(top_date.year, int(explicit.group(1)), int(explicit.group(2)))
        elif prev is not None and minute > prev + 60:
            date = date - datetime.timedelta(days=1)
        prev = minute
        out.append((date, parsed[1], line))
    return out


def merged_branches(subjects):
    """Returns sorted distinct work branches merged into a chore/ line or into their own parent line."""
    names = set()
    for subject in subjects:
        m = MERGE_RE.match(subject)
        if not m:
            continue
        source, target = m.group(1), m.group(2)
        if source.startswith(("chore/", "origin/")):
            continue
        if target.startswith("chore/") or source.startswith(target + "-"):
            names.add(source)
    return sorted(names)


def usage_rows(root, prefix, earliest):
    """Yields (folder suffix, time, usage, git branch) once per assistant message id from root/<prefix>* transcripts."""
    seen = set()
    for name in sorted(os.listdir(root)):
        if not name.startswith(prefix):
            continue
        suffix = name[len(prefix):]
        for folder, _, files in os.walk(os.path.join(root, name)):
            for fname in files:
                path = os.path.join(folder, fname)
                if not fname.endswith(".jsonl") or os.path.getmtime(path) < earliest.timestamp():
                    continue
                with open(path, errors="replace") as fh:
                    for line in fh:
                        if '"usage"' not in line:
                            continue
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        msg = row.get("message") if isinstance(row.get("message"), dict) else {}
                        usage, mid, ts = msg.get("usage"), msg.get("id") or row.get("requestId"), row.get("timestamp")
                        if not isinstance(usage, dict) or not mid or not ts or mid in seen:
                            continue
                        when = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if when < earliest:
                            continue
                        seen.add(mid)
                        yield suffix, when, usage, row.get("gitBranch") or ""


def token_days(root, prefix, ranges):
    """Sums assistant usage per [start, end) range over transcripts under root/<prefix>*, deduped by message id."""
    sums = [{"messages": 0, "input": 0, "cache_write": 0, "cache_read": 0, "output": 0} for _ in ranges]
    earliest = min(start for start, _ in ranges)
    for _, when, usage, _ in usage_rows(root, prefix, earliest):
        for i, (start, end) in enumerate(ranges):
            if start <= when < end:
                s = sums[i]
                s["messages"] += 1
                s["input"] += int(usage.get("input_tokens") or 0)
                s["cache_write"] += int(usage.get("cache_creation_input_tokens") or 0)
                s["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
                s["output"] += int(usage.get("output_tokens") or 0)
    return sums


def work(usage):
    """Work tokens of one message: input + cache write + output (cache reads left out)."""
    return int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0) + int(usage.get("output_tokens") or 0)


def parse_budget(text):
    """Reads cap, counted-since, week-end and the line table (line, share, branch regex, folder regex) from budget.md."""
    def field(key):
        m = re.search(r"^- %s:\s*(\S+)" % re.escape(key), text, re.M)
        assert m, "budget.md has no '- %s:' line" % key
        return m.group(1)
    def when(v):
        return datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
    cap = field("cap")
    assert re.fullmatch(r"\d+(\.\d+)?M", cap), cap
    lines = []
    for row in text.split("\n"):
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)[1:-1]]
        if len(cells) != 4 or not cells[1].endswith("%") or not cells[1][:-1].replace(".", "").isdigit():
            continue
        branch, folder = (None if c == "-" else re.compile(c) for c in cells[2:])
        lines.append((cells[0], float(cells[1][:-1]) / 100, branch, folder))
    assert lines and abs(sum(l[1] for l in lines) - 1.0) < 0.001, "budget shares must add to 100%"
    b = {"cap": int(float(cap[:-1]) * 1_000_000), "since": when(field("counted since")), "week_end": when(field("week ends")), "lines": lines}
    assert b["since"] < b["week_end"], b
    return b


def line_for(lines, suffix, branch):
    """Names the budget line of one message: branch-less rows claim their folders first, then branch rules, then folder rules."""
    for name, _, br, folder in lines:
        if br is None and folder is not None and folder.search(suffix):
            return name
    for name, _, br, _ in lines:
        if br is not None and branch and br.search(branch):
            return name
    for name, _, _, folder in lines:
        if folder is not None and folder.search(suffix):
            return name
    return "other"


def budget_check(b, used, now, rate_per_hour):
    """Compares work tokens per line with each line's share of the cap and says whether the week runs out before its reset."""
    total = sum(used.values())
    left = b["cap"] - total
    to_reset = (b["week_end"] - now).total_seconds() / 3600
    hours_left = left / rate_per_hour if rate_per_hour > 0 else float("inf")
    rows = []
    for name, share, _, _ in b["lines"]:
        budget = share * b["cap"]
        rows.append({"line": name, "used": used.get(name, 0), "budget": budget, "flag": "OVER" if used.get(name, 0) > budget else "ok"})
    for name in sorted(set(used) - {l[0] for l in b["lines"]}):
        rows.append({"line": name, "used": used[name], "budget": 0, "flag": "unbudgeted"})
    return {"total": total, "left": left, "hours_to_reset": to_reset, "hours_left": hours_left,
            "runs_out_before_reset": left <= 0 or hours_left < to_reset, "rows": rows}


def budget_report(path, now=None):
    """Prints the weekly budget check from budget.md and the transcripts; rate is the last 6 hours' work tokens per hour."""
    if not os.path.isfile(path):
        print("budget: no %s" % path)
        return None
    b = parse_budget(open(path).read())
    now = now or datetime.datetime.now(datetime.timezone.utc)
    used, recent = {}, 0
    window = now - datetime.timedelta(hours=6)
    for suffix, when, usage, branch in usage_rows(PROJECTS, PREFIX, min(b["since"], window)):
        if when >= now:
            continue
        if when >= b["since"]:
            key = line_for(b["lines"], suffix, branch)
            used[key] = used.get(key, 0) + work(usage)
        if when >= window:
            recent += work(usage)
    hours = min(6.0, max((now - b["since"]).total_seconds() / 3600, 0.25))
    out = budget_check(b, used, now, recent / hours)
    print("budget week (cap %s since %s, resets %s): used %s, left %s, at %s/h %.1f h left vs %.1f h to reset%s" % (
        fmt_m(b["cap"]), b["since"].isoformat()[:16], b["week_end"].isoformat()[:16], fmt_m(out["total"]), fmt_m(out["left"]),
        fmt_m(recent / hours), out["hours_left"], out["hours_to_reset"], ": RUNS OUT BEFORE RESET" if out["runs_out_before_reset"] else ""))
    for r in out["rows"]:
        print("  %-14s %10s of %10s  %s" % (r["line"], fmt_m(r["used"]), fmt_m(r["budget"]), r["flag"]))
    return out


def tokens(root, prefix, start, end):
    """Token sums for one [start, end) range."""
    return token_days(root, prefix, [(start, end)])[0]


def count_findings(text):
    """Counts findings by severity in one FINDINGS file, stopping at its notes or closures."""
    counts = {}
    for _, sev in dispatch.items_in_findings_file(text):
        counts[sev] = counts.get(sev, 0) + 1
    return counts


def day_range(day):
    start = datetime.datetime.combine(day, datetime.time(0)).astimezone()
    return start, start + datetime.timedelta(days=1)


def measure(days):
    """Returns one row of numbers per day."""
    ranges = [day_range(d) for d in days]
    toks = token_days(PROJECTS, PREFIX, ranges)
    rows = []
    for day, (start, end), tok in zip(days, ranges, toks):
        subjects = subprocess.run(
            ["git", "-C", R, "log", "--all", "--merges", "--since=%s" % start.isoformat(), "--until=%s" % end.isoformat(), "--format=%s"],
            capture_output=True, text=True, check=True).stdout.split("\n")
        merged = merged_branches(subjects)
        findings, files, limits = {}, 0, []
        for folder in sorted(os.listdir(F)):
            path = os.path.join(F, folder)
            if not os.path.isdir(path):
                continue
            for fname in os.listdir(path):
                full = os.path.join(path, fname)
                if fname.startswith("FINDINGS-") and fname.endswith(".md"):
                    if datetime.date.fromtimestamp(os.path.getmtime(full)) == day:
                        files += 1
                        for sev, n in count_findings(dispatch.read_text(full)).items():
                            findings[sev] = findings.get(sev, 0) + n
            status = os.path.join(path, "status.md")
            if os.path.isfile(status):
                top = datetime.date.fromtimestamp(os.path.getmtime(status))
                limits += [folder for d, kind, _ in dated_lines(dispatch.read_text(status), top) if d == day and kind == "LIMIT"]
        rows.append({"day": day, "merged": len(merged), "tokens": tok, "findings": findings, "findings_files": files, "limits": limits})
    return rows


def fmt_m(n):
    return "%.1fM" % (n / 1e6)


def report(rows):
    """Prints the rows side by side, baseline first."""
    def per(n, row):
        return fmt_m(n / row["merged"]) if row["merged"] else "n/a"
    lines = [("", [r["day"].isoformat() for r in rows])]
    lines.append(("merged branches", [str(r["merged"]) for r in rows]))
    lines.append(("assistant messages", [str(r["tokens"]["messages"]) for r in rows]))
    lines.append(("tokens in+write+out", [fmt_m(r["tokens"]["input"] + r["tokens"]["cache_write"] + r["tokens"]["output"]) for r in rows]))
    lines.append(("  per merged branch", [per(r["tokens"]["input"] + r["tokens"]["cache_write"] + r["tokens"]["output"], r) for r in rows]))
    lines.append(("output tokens", [fmt_m(r["tokens"]["output"]) for r in rows]))
    lines.append(("cache read tokens", [fmt_m(r["tokens"]["cache_read"]) for r in rows]))
    lines.append(("FINDINGS files", [str(r["findings_files"]) for r in rows]))
    for sev in SEVERITIES:
        lines.append(("findings %s" % sev, [str(r["findings"].get(sev, 0)) for r in rows]))
    lines.append(("  findings per branch", ["%.1f" % (sum(r["findings"].values()) / r["merged"]) if r["merged"] else "n/a" for r in rows]))
    lines.append(("limit stops", [str(len(r["limits"])) for r in rows]))
    width = max(len(l[0]) for l in lines) + 2
    for label, cells in lines:
        print(label.ljust(width) + "".join(c.rjust(14) for c in cells))
    for r in rows:
        if r["limits"]:
            print("limit stops %s: %s" % (r["day"].isoformat(), ", ".join(sorted(set(r["limits"])))))


def main(argv):
    wfenv.require_root(F)
    if argv[1:2] == ["budget"]:
        budget_report(os.path.join(F, "leader", "budget.md"))
        return 0
    day = datetime.date.fromisoformat(argv[1]) if len(argv) > 1 else datetime.date.today()
    if len(argv) <= 2 and not os.environ.get("WORKFLOW_BASELINE_DAY"):
        print("pass BASELINE or set WORKFLOW_BASELINE_DAY (YYYY-MM-DD)", file=sys.stderr)
        return 2
    base = datetime.date.fromisoformat(argv[2] if len(argv) > 2 else os.environ["WORKFLOW_BASELINE_DAY"])
    assert base != day, "baseline and day are the same"
    report(measure([base, day]))
    print()
    budget_report(os.path.join(F, "leader", "budget.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
