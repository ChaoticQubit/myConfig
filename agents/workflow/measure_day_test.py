"""Runnable check for leader/measure_day.py: python3 -I leader/measure_day_test.py.

Covers the status-line dating across midnight, the merged-branch rule, token
dedupe by message id and the findings count. Prints "measure_day_test OK".
"""

import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import measure_day

D16 = datetime.date(2026, 11, 16)
D15 = datetime.date(2026, 11, 15)


def test_status_dates_cross_midnight():
    text = "\n".join([
        "01:43 11-16 DONE-REVIEW a",
        "00:10 LIMIT usage limit reached",
        "23:46 LIMIT usage limit reached; x",
        "23:40 WORKING y",
        "plain prose",
        "16:44 LIMIT usage limit reached",
        "09:00 11-14 IDLE",
    ])
    dated = measure_day.dated_lines(text, D16)
    got = [(d.isoformat(), kind) for d, kind, _ in dated]
    assert got == [("2026-11-16", "DONE-REVIEW"), ("2026-11-16", "LIMIT"), ("2026-11-15", "LIMIT"),
                   ("2026-11-15", "WORKING"), ("2026-11-15", "LIMIT"), ("2026-11-14", "IDLE")], got


def test_merged_branch_rule():
    subjects = [
        "Merge fix/v242-ds191 (1debe07c1) into chore/v242: rows",
        "Merge branch 'feat/v3-connectors-t12' into feat/v3-connectors",
        "Merge branch 'feat/v3-connectors-t12' into feat/v3-connectors",
        "Merge chore/v242 into feat/v242-github-publish",
        "Merge remote-tracking branch 'origin/feat/v242-harness-layer' into feat/v242-harness-t20",
        "Merge feat/v242-harness-layer into feat/v242-harness-t25",
        "Merge branch 'fix/x' into chore/v241",
    ]
    assert measure_day.merged_branches(subjects) == ["feat/v3-connectors-t12", "fix/v242-ds191", "fix/x"], measure_day.merged_branches(subjects)


def test_tokens_dedupe_and_day_filter():
    root = tempfile.mkdtemp(prefix="measure-day-")
    proj = os.path.join(root, "-Users-x-Projects-CrazyAgent--worktrees-a")
    os.makedirs(proj)
    usage = {"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": 5}
    rows = [
        {"timestamp": "2026-11-16T08:00:00.000Z", "message": {"id": "m1", "usage": usage}},
        {"timestamp": "2026-11-16T08:00:01.000Z", "message": {"id": "m1", "usage": usage}},
        {"timestamp": "2026-11-16T09:00:00.000Z", "message": {"id": "m2", "usage": usage}},
        {"timestamp": "2026-11-10T09:00:00.000Z", "message": {"id": "m3", "usage": usage}},
        {"timestamp": "2026-11-16T09:30:00.000Z", "type": "user", "message": {"content": "hi"}},
    ]
    with open(os.path.join(proj, "s.jsonl"), "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    start = datetime.datetime(2026, 11, 16, tzinfo=datetime.timezone.utc)
    t = measure_day.tokens(root, "-Users-x-Projects-CrazyAgent", start, start + datetime.timedelta(days=1))
    assert t == {"messages": 2, "input": 20, "cache_write": 200, "cache_read": 2000, "output": 10}, t


def test_findings_count():
    text = "## t\n### F1 Medium (data loss)\nx\n### F2 Low (perf)\nF3 LOW (bound)\n### Notes, not counted\nF9 HIGH ignored\n"
    assert measure_day.count_findings(text) == {"MED": 1, "LOW": 2}, measure_day.count_findings(text)


BUDGET_MD = """# Weekly token budget

- cap: 250M
- counted since: 2026-11-15T07:41Z
- week ends: 2026-11-18T11:59Z

| line | share | branch | folder |
|---|---|---|---|
| review | 30% | - | ^--worktrees-(rv-\\|sec[0-9]+-) |
| 2.4.2 | 30% | v242 | v242 |
| V3 | 20% | v3 | v3 |
| leader | 20% | - | ^$\\|^--local-state |
"""


def test_budget_parse_and_line_rule():
    b = measure_day.parse_budget(BUDGET_MD)
    assert b["cap"] == 250_000_000 and b["since"].isoformat() == "2026-11-15T07:41:00+00:00", b
    assert [r[0] for r in b["lines"]] == ["review", "2.4.2", "V3", "leader"], b["lines"]
    assert abs(sum(r[1] for r in b["lines"]) - 1.0) < 1e-9
    rule = lambda suf, br: measure_day.line_for(b["lines"], suf, br)
    assert rule("--worktrees-rv-code2", "feat/v242-x") == "review"
    assert rule("--worktrees-v241-ds144", "fix/v242-y") == "2.4.2"
    assert rule("--worktrees-v3-keepawake", "") == "V3"
    assert rule("", "feat/app-build18") == "leader"
    assert rule("--worktrees-odd", "main") == "other"


def test_budget_check_flags_runout():
    b = measure_day.parse_budget(BUDGET_MD)
    now = datetime.datetime(2026, 11, 16, 7, 0, tzinfo=datetime.timezone.utc)
    used = {"review": 80_000_000, "2.4.2": 20_000_000, "V3": 30_000_000, "leader": 60_000_000, "other": 5_000_000}
    out = measure_day.budget_check(b, used, now, rate_per_hour=8_000_000)
    assert out["total"] == 195_000_000 and out["left"] == 55_000_000, out
    assert out["runs_out_before_reset"] and 6.8 < out["hours_left"] < 6.9, out
    flags = {r["line"]: r["flag"] for r in out["rows"]}
    assert flags == {"review": "OVER", "2.4.2": "ok", "V3": "ok", "leader": "OVER", "other": "unbudgeted"}, flags


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("measure_day_test OK (%d)" % len(tests))


if __name__ == "__main__":
    main()
