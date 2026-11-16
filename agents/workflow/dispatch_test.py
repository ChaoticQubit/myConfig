"""Runnable check for dispatch.py: python3 -I -B dispatch_test.py (sets its own temp WORKFLOW_ROOT).

Builds a throwaway sprint folder with status files, a table, a rules file and
stub herdr/tell commands, then drives the engine and one live tick. Exits
non-zero on the first failed assertion; prints "dispatch_test OK" when all pass.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

os.environ.setdefault("WORKFLOW_OWNER_PANE", "w12:p1")

import dispatch

TABLE = """sec feat/v242-harness-* rv-sa241 rv-secreview rv-sec2
code * rv-code rv-code2
sec * rv-secreview rv-sec2
ledger feat/v3-* LEDGER-v3.md
ledger * LEDGER-242-reviews.md
"""

RULES = """# Review rules
- round cap: 2
- queue per pair: 2
"""


def make_engine():
    """Returns an engine with both pairs free and stub file readers."""
    table = dispatch.parse_table(TABLE)
    rules = dispatch.parse_rules(RULES)
    files = {}
    engine = dispatch.Engine(table, rules, dispatch.new_state(), read_file=lambda path: files.get(path, ""))
    for name in ["rv-code", "rv-secreview", "rv-code2", "rv-sec2", "rv-sa241"]:
        engine.feed(name, "IDLE queue empty", "01:00")
    return engine, files


def kinds(actions):
    """Returns the action kinds in order."""
    return [a[0] for a in actions]


def test_done_routes_to_first_free_pair():
    engine, _ = make_engine()
    acts = engine.feed("w-a", "DONE t17 fix/v242-t17 aaaaaaa1..bbbbbbb2 rows written not run; DONE-01:33-t17.md", "01:33")
    tells = [a for a in acts if a[0] == "tell"]
    assert [t[1] for t in tells] == ["rv-code", "rv-secreview"], tells
    assert all("fix/v242-t17" in t[2] and "aaaaaaa1..bbbbbbb2" in t[2] and "bbbbbbb" in t[2] for t in tells), tells
    ledger = [a for a in acts if a[0] == "ledger"]
    assert ledger and ledger[0][1] == "LEDGER-242-reviews.md", ledger
    assert "-> rv-code code + rv-secreview sec" in ledger[0][2], ledger
    assert len(engine.state["assignments"]) == 1


FIX10_0240 = ("02:40 w-v241-fix10 DONE git-config-hooks-241 N1: DONE-02:40-cfg-include.md. fix/v242-cfg-include 8bbfc1a83..4b4832ad7 "
              "(red e61406eff, fix 13234ac0e, style 4b4832ad7): Repo::open refuses an include placed in the checkout or work tree "
              "(IDE 144b judgment reused), new changes_git_include + TUI/desktop sentence. fmt clean, merge-tree clean vs chore 2a6bf0cbb. "
              "Rows written not run. Ready for review routing; then next sweep item.")


def test_pane_name_before_done_routes():
    assert dispatch.parse_line(FIX10_0240)[1] == "DONE"
    assert dispatch.parse_line("02:40 DONE ACK x")[1:] == ("DONE", "ACK x")
    engine, _ = make_engine()
    acts = engine.feed("w-v241-fix10", FIX10_0240, "02:40")
    assert kinds(acts) == ["facts", "tell", "tell", "ledger"], acts
    assert acts[0][2] == "8bbfc1a83..4b4832ad7" and "fix/v242-cfg-include" in acts[1][2], acts
    assert engine.state["assignments"][0]["slug"] == "git-config-hooks-241", engine.state["assignments"]


def test_done_lines_that_do_not_route_go_to_the_leader():
    engine, _ = make_engine()
    for folder, line in [
        ("w-a", "02:41 fix sweep DONE, see DONE-02:41-x.md"),
        ("w-a", "02:42 DONE-PARTIAL t20 fix/v242-t20 aaaaaaa1..bbbbbbb4"),
        ("rv-code", "02:43 DONE item 4 notes written"),
        ("w-b", "02:44 w-b: DONE notes only, nothing to review"),
    ]:
        acts = engine.feed(folder, line, "02:45")
        assert kinds(acts) == ["queue"] and folder in acts[0][1], (line, acts)
    assert engine.feed("w-a", "02:46 ACK leader, DONE expected by 03:00", "02:46") == []
    assert engine.feed("w-a", "02:47 WORKING on it", "02:47") == []


def test_busy_pair_skipped():
    engine, _ = make_engine()
    engine.feed("rv-secreview", "STARTED other (leader 01:30, x..y)", "01:30")
    acts = engine.feed("w-a", "DONE t17 feat/v3-t17 aaaaaaa1..bbbbbbb2", "01:33")
    tells = [a[1] for a in acts if a[0] == "tell"]
    assert tells == ["rv-code", "rv-sec2"], tells
    assert [a for a in acts if a[0] == "ledger"][0][1] == "LEDGER-v3.md"


def test_no_free_pair_waits_then_routes():
    engine, _ = make_engine()
    engine.feed("rv-code", "WORKING x", "01:30")
    engine.feed("rv-code2", "WORKING y", "01:30")
    acts = engine.feed("w-a", "DONE t17 fix/v242-t17 aaaaaaa1..bbbbbbb2", "01:33")
    assert "tell" not in kinds(acts), acts
    assert len(engine.state["pending"]) == 1
    engine.feed("rv-code2", "DONE-REVIEW y r1 ccccccc findings:0", "01:40")
    acts = engine.retry_pending("01:41")
    assert [a[1] for a in acts if a[0] == "tell"] == ["rv-code2", "rv-secreview"], acts
    assert engine.state["pending"] == []


def test_question_goes_to_leader_queue():
    engine, _ = make_engine()
    acts = engine.feed("w-a", "DONE t17 fix/v242-t17 aaaaaaa1..bbbbbbb2 QUESTION-01:30-x.md open", "01:33")
    assert kinds(acts) == ["queue"], acts
    acts = engine.feed("w-b", "DONE t18 fix/v242-t18 aaaaaaa1..bbbbbbb3 add.7 leader call", "01:34")
    assert kinds(acts) == ["queue"], acts
    acts = engine.feed("w-c", "DONE merged t19 into feat/v3-x", "01:35")
    assert kinds(acts) == ["queue"], acts


def test_done_without_branch_reads_done_file():
    engine, files = make_engine()
    files[os.path.join("w-a", "DONE-01:33-ka-t17.md")] = "- Worker: w-a. Branch feat/v3-keepawake-t17, worktree x\n- Range: 3476b2d24..08badb419\n"
    acts = engine.feed("w-a", "DONE ka-t17 rows written not run; DONE-01:33-ka-t17.md", "01:33")
    tells = [a for a in acts if a[0] == "tell"]
    assert len(tells) == 2 and "feat/v3-keepawake-t17" in tells[0][2] and "3476b2d24..08badb419" in tells[0][2], acts
    acts = engine.feed("w-b", "DONE research notes written", "01:34")
    assert kinds(acts) == ["queue"], acts


def test_worker_is_never_its_own_reviewer():
    engine, _ = make_engine()
    acts = engine.feed("rv-code", "DONE fix/v242-own aaaaaaa1..bbbbbbb2 own fix", "01:33")
    tells = [a[1] for a in acts if a[0] == "tell"]
    assert "rv-code" not in tells and tells == ["rv-code2", "rv-secreview"], acts


def test_specific_row_wins_and_tracks_mix():
    engine, _ = make_engine()
    acts = engine.feed("w-a", "DONE env feat/v242-harness-sec aaaaaaa1..bbbbbbb2", "01:33")
    assert [a[1] for a in acts if a[0] == "tell"] == ["rv-code", "rv-sa241"], acts
    engine.feed("rv-sa241", "01:40 11-16 ACK rv-sa241 env", "01:40")
    acts = engine.feed("w-b", "DONE env2 feat/v242-harness-x aaaaaaa3..bbbbbbb4", "01:41")
    assert [a[1] for a in acts if a[0] == "tell"] == ["rv-code2", "rv-secreview"], acts


def test_round2_waits_for_its_round1_reviewers():
    engine, _ = make_engine()
    route_one(engine)
    engine.feed("rv-code", "DONE-REVIEW t17 r1 bbbbbbb2 findings:1 (F1 LOW a)", "01:50")
    engine.feed("rv-secreview", "DONE-REVIEW t17 r1 bbbbbbb2 findings:0", "01:52")
    engine.feed("rv-code", "STARTED other", "01:55")
    acts = engine.feed("w-a", "DONE t17 r2 fix/v242-t17 bbbbbbb2..ddddddd4 folds", "02:10")
    assert "tell" not in kinds(acts) and len(engine.state["pending"]) == 1, acts
    engine.feed("rv-code", "13:00 rv-code: LIMIT. resets 3am", "02:11")
    acts = engine.retry_pending("02:12")
    assert [a[1] for a in acts if a[0] == "tell"] == ["rv-code2", "rv-secreview"], acts


def route_one(engine):
    engine.feed("w-a", "DONE t17 fix/v242-t17 aaaaaaa1..bbbbbbb2 DONE-01:33-t17.md", "01:33")
    engine.feed("rv-code", "STARTED t17", "01:34")
    engine.feed("rv-secreview", "STARTED t17", "01:34")


def test_both_clean_marks_reviewed():
    engine, _ = make_engine()
    route_one(engine)
    acts = engine.feed("rv-code", "DONE-REVIEW t17 r1 bbbbbbb2 findings:0", "01:50")
    assert "ledger" not in kinds(acts), acts
    acts = engine.feed("rv-secreview", "DONE-REVIEW t17 r1 bbbbbbb findings:0 (clean)", "01:52")
    ledger = [a[2] for a in acts if a[0] == "ledger"]
    assert ledger and "REVIEWED both tracks" in ledger[0], acts
    assert any(a[0] == "queue" and "merge" in a[1] for a in acts), acts
    assert "tell" not in kinds(acts)


def test_low_findings_round1_go_to_worker_named():
    engine, files = make_engine()
    route_one(engine)
    files[os.path.join("rv-code", "FINDINGS-01:49-t17.md")] = "## t17\n### F1 Low (perf)\nx\n### F2 LOW (naming)\ny\n### Notes, not counted\n"
    engine.feed("rv-code", "DONE-REVIEW t17 r1 bbbbbbb2 findings:2 (F1 Low perf; F2 LOW naming) FINDINGS-01:49-t17.md", "01:50")
    acts = engine.feed("rv-secreview", "DONE-REVIEW t17 r1 bbbbbbb2 findings:1 (F1 LOW bound gap)", "01:52")
    tells = [a for a in acts if a[0] == "tell"]
    assert len(tells) == 1 and tells[0][1] == "w-a", acts
    msg = tells[0][2]
    assert "F1" in msg and "F2" in msg and "3" in msg and "never amend" in msg, msg
    assert len(msg) <= 700


def test_med_or_high_goes_to_leader():
    engine, _ = make_engine()
    route_one(engine)
    engine.feed("rv-code", "DONE-REVIEW t17 r1 bbbbbbb2 findings:1 (F1 Medium data loss)", "01:50")
    acts = engine.feed("rv-secreview", "DONE-REVIEW t17 r1 bbbbbbb2 findings:0", "01:52")
    assert "tell" not in kinds(acts), acts
    assert any(a[0] == "queue" and "MED" in a[1] for a in acts), acts


def test_count_mismatch_goes_to_leader():
    engine, _ = make_engine()
    route_one(engine)
    engine.feed("rv-code", "DONE-REVIEW t17 r1 bbbbbbb2 findings:3 (F1 LOW a)", "01:50")
    acts = engine.feed("rv-secreview", "DONE-REVIEW t17 r1 bbbbbbb2 findings:0", "01:52")
    assert "tell" not in kinds(acts), acts
    assert any(a[0] == "queue" and "count" in a[1] for a in acts), acts


def test_round2_lows_go_to_backlog_and_round3_to_leader():
    engine, _ = make_engine()
    route_one(engine)
    engine.feed("rv-code", "DONE-REVIEW t17 r1 bbbbbbb2 findings:1 (F1 LOW a)", "01:50")
    engine.feed("rv-secreview", "DONE-REVIEW t17 r1 bbbbbbb2 findings:0", "01:52")
    acts = engine.feed("w-a", "DONE t17 r2 fix/v242-t17 bbbbbbb2..ddddddd4 folds", "02:10")
    tells = [a for a in acts if a[0] == "tell"]
    assert [t[1] for t in tells] == ["rv-code", "rv-secreview"] and "r2" in tells[0][2], acts
    engine.feed("rv-code", "DONE-REVIEW t17 r2 ddddddd4 findings:1 (F1 LOW b)", "02:20")
    acts = engine.feed("rv-secreview", "DONE-REVIEW t17 r2 ddddddd findings:0", "02:21")
    assert "backlog" in kinds(acts) and "tell" not in kinds(acts), acts
    assert any(a[0] == "ledger" and "REVIEWED both tracks" in a[2] for a in acts), acts
    acts = engine.feed("w-a", "DONE t17 r3 fix/v242-t17 ddddddd4..eeeeeee5", "02:40")
    assert kinds(acts) == ["queue"], acts


def test_unmatched_review_is_ignored():
    engine, _ = make_engine()
    acts = engine.feed("rv-code", "DONE-REVIEW other r1 1234567 findings:2 (F1 LOW; F2 LOW)", "01:50")
    assert acts == [], acts


def test_queue_rule_flags_overflow():
    engine, _ = make_engine()
    for name in ["rv-code", "rv-code2"]:
        engine.feed(name, "WORKING z", "01:30")
    acts = []
    for i in range(5):
        acts += engine.feed("w-%d" % i, "DONE s%d fix/v242-s%d aaaaaa%d1..bbbbbb%d2" % (i, i, i, i), "01:3%d" % i)
    assert any(a[0] == "queue" and "QUEUE" in a[1] for a in acts), acts


def test_real_line_shapes():
    engine, files = make_engine()
    engine.resolve_tip = lambda branch: {"fix/v242-ds190": "8adbbc81c0aa"}.get(branch)
    acts = engine.feed("w-a", "DONE ka-t14 feat/v3-x-t14 3476b2d24..4d50d6e44 (4): plan; merge-tree clean vs feat/v3-x f4b8e914f; rows written not run", "00:58")
    assert kinds(acts) == ["facts", "tell", "tell", "ledger"], acts
    assert acts[0][2] == "3476b2d24..4d50d6e44" and all(acts[0][1] in a[2] for a in acts if a[0] == "tell"), acts
    acts = engine.feed("w-b", "DONE KA-T14-r2-nits feat/v3-y 264a734b9..aa77170e4 (1): rv-ds241 r2 N1 + N2; merge-tree clean", "01:45")
    assert kinds(acts) == ["queue"] and "confirm" in acts[0][1], acts
    acts = engine.feed("w-c", "DONE b-r2 fix/v242-z e323238b8..1187c0c0a (1): rv-ds241 CT-1 + guard row", "01:46")
    assert kinds(acts) == ["queue"], acts
    acts = engine.feed("w-d", "DONE 01:08 11-16 T19b merged: 65661c4ad = feat/v242-q (8ccd670b7) into feat/v242-l --no-ff", "01:47")
    assert kinds(acts) == ["queue"], acts
    acts = engine.feed("w-e", "DONE pushed feat/v242-harness-layer 65661c4ad (origin was b3ec6385d)", "01:48")
    assert kinds(acts) == ["queue"], acts
    files[os.path.join("w-f", "DONE-0137-t19b-4.md")] = "Branch feat/v242-harness-t19b4\n"
    acts = engine.feed("w-f", "DONE T19b 19b-4 listed research: 8ccd670b7..10be22dd6 (7 commits). DONE-0137-t19b-4.md", "01:49")
    tells = [a for a in acts if a[0] == "tell"]
    assert len(tells) == 2 and "feat/v242-harness-t19b4" in tells[0][2], acts
    engine, _ = make_engine()
    engine.resolve_tip = lambda branch: {"fix/v242-ds190": "8adbbc81c0aa"}.get(branch)
    acts = engine.feed("w-g", "DONE ds190: fix/v242-ds190 f609f0ef9 red + 8adbbc81c fix; merge-tree clean vs chore/v242 33e038c86; not pushed", "01:50")
    tells = [a for a in acts if a[0] == "tell"]
    assert len(tells) == 2 and "8adbbc81c" in tells[0][2], acts
    acts = engine.feed("w-h", "DONE x fix/v242-gone 1111111aa pushed (off 2222222bb)", "01:51")
    assert kinds(acts) == ["queue"], acts


def test_fold_detection_words():
    fold = lambda text: bool(dispatch.FOLD_RE.search(dispatch.BOILERPLATE_RE.sub(" ", text)))
    assert not fold("ka-t17 a..b rows written not run; lint run 2 queued after 01:50, folds in")
    assert not fold("b-trees x..y (Pattern::fixed_folder, listed_trees)")
    assert fold("bgjobs-2c-lows: fix/v242-bgjobs-2c-lows 0e3931234 L1")
    assert fold("native-flows-f1: fix/v242-native-flows 9ccdfeec3")
    assert fold("T10-fold-r1 feat/v3-connectors-t10 a..b")
    assert fold("mates-refused fold r1: 9ba92c5e0..1141eebb5")


def test_short_slug_never_matches_prose():
    engine, _ = make_engine()
    engine.feed("w-a", "DONE a feat/v242-k aaaaaaa1..bbbbbbb2 (a) keyed", "01:06")
    acts = engine.feed("rv-code", "DONE-REVIEW other r1 1234567 findings:1 (F1 LOW a bound)", "01:20")
    assert acts == [] and engine.state["assignments"][0]["verdicts"]["code"] is None, acts


def test_newer_done_replaces_pending_job():
    engine, _ = make_engine()
    for name in ["rv-code", "rv-code2"]:
        engine.feed(name, "WORKING z", "01:30")
    engine.feed("w-a", "DONE envrule fix/v242-env 4f66cf20e..44c25e0db (2)", "01:34")
    acts = engine.feed("w-a", "DONE envrule-toolchain fix/v242-env 4f66cf20e..2a8b073f6 (4)", "01:38")
    assert "queue" not in kinds(acts) and len(engine.state["pending"]) == 1, acts
    assert engine.state["pending"][0]["tip"] == "2a8b073f6", engine.state["pending"]


def test_shadow_mode_frees_by_status_only():
    engine, _ = make_engine()
    engine.shadow = True
    engine.feed("w-a", "DONE t1 fix/v242-a aaaaaaa1..bbbbbbb2", "01:00")
    engine.feed("rv-code", "DONE-REVIEW other r1 9999999 findings:0", "01:10")
    engine.feed("rv-secreview", "IDLE", "01:10")
    acts = engine.feed("w-b", "DONE t2 fix/v242-b ccccccc1..ddddddd2", "01:11")
    assert [a[1] for a in acts if a[0] == "tell"] == ["rv-code", "rv-secreview"], acts


def test_status_line_parse():
    assert dispatch.parse_line("01:33 DONE ka-t17 x") == ("01:33", "DONE", "ka-t17 x")
    assert dispatch.parse_line("23:43 rv-ds241: LIMIT. t20m8") == ("23:43", "LIMIT", ". t20m8")
    assert dispatch.parse_line("DONE-REVIEW conn-t10s e78b1ebd5 findings:1") == (None, "DONE-REVIEW", "conn-t10s e78b1ebd5 findings:1")
    assert dispatch.parse_line("plain prose") is None


def test_live_tick_end_to_end():
    root = tempfile.mkdtemp(prefix="dispatch-test-")
    leader = os.path.join(root, "leader")
    os.makedirs(leader)
    for name in ["w-a", "rv-code", "rv-secreview", "rv-code2", "rv-sec2", "w-dispatch"]:
        os.makedirs(os.path.join(root, name))
    def status(name, line):
        path = os.path.join(root, name, "status.md")
        old = open(path).read() if os.path.exists(path) else ""
        with open(path, "w") as fh:
            fh.write(line + "\n" + old)
    for name in ["rv-secreview", "rv-code2", "rv-sec2"]:
        status(name, "01:00 IDLE queue empty")
    status("rv-code", "00:50 STARTED old")
    status("rv-code", "01:00 DONE-REVIEW old r1 1234567 findings:0")
    status("w-a", "01:00 WORKING t17")
    with open(os.path.join(leader, "dispatch-table.txt"), "w") as fh:
        fh.write(TABLE)
    with open(os.path.join(leader, "RULES-review.md"), "w") as fh:
        fh.write(RULES)
    agents = {"result": {"agents": [
        {"name": n, "pane_id": "w12:pT%d" % i, "agent_status": "done"}
        for i, n in enumerate(["w-a", "rv-code", "rv-secreview", "rv-code2", "rv-sec2"])
    ] + [{"name": "leader-like", "pane_id": "w12:p1", "agent_status": "working"}]}}
    agents_path = os.path.join(root, "agents.json")
    with open(agents_path, "w") as fh:
        json.dump(agents, fh)
    sent = os.path.join(root, "sent.txt")
    tell = os.path.join(root, "tell.sh")
    with open(tell, "w") as fh:
        fh.write('#!/bin/bash\nprintf "%s\\t%s\\n" "$1" "$2" >> ' + sent + '\necho "sent $1"\n')
    os.chmod(tell, 0o755)
    facts = os.path.join(root, "facts.sh")
    with open(facts, "w") as fh:
        fh.write('#!/bin/bash\necho "## facts for $2"\n')
    env = dict(os.environ, DISPATCH_ROOT=root, DISPATCH_AGENTS_JSON=agents_path, DISPATCH_TELL=tell, DISPATCH_NOW="01:40", DISPATCH_FACTS=facts, WORKFLOW_OWNER_PANE="w12:p1")
    script = os.path.join(HERE, "dispatch.py")
    run = lambda *args: subprocess.run([sys.executable, "-I", "-B", script] + list(args), env=env, capture_output=True, text=True)
    out = run("tick")
    assert out.returncode == 0 and "off" in out.stdout, (out.stdout, out.stderr)
    open(os.path.join(leader, "dispatch-on"), "w").close()
    out = run("tick")
    assert out.returncode == 0 and "initialised" in out.stdout, (out.stdout, out.stderr)
    status("w-a", "01:39 DONE t17 fix/v242-t17 aaaaaaa1..bbbbbbb2 DONE-01:39-t17.md")
    out = run("tick")
    assert out.returncode == 0, (out.stdout, out.stderr)
    lines = open(sent).read().strip().split("\n")
    assert [l.split("\t")[0] for l in lines] == ["w12:pT1", "w12:pT2"], lines
    made = os.listdir(os.path.join(leader, "facts"))
    assert len(made) == 1 and "aaaaaaa1..bbbbbbb2" in open(os.path.join(leader, "facts", made[0])).read(), made
    ledger = open(os.path.join(leader, "LEDGER-242-reviews.md")).read()
    assert "t17 bbbbbbb2 -> rv-code code + rv-secreview sec" in ledger, ledger
    out = run("tick")
    assert open(sent).read().strip().split("\n") == lines, "second tick must not resend"
    agents["result"]["agents"][1]["pane_id"] = "w12:p1"
    with open(agents_path, "w") as fh:
        json.dump(agents, fh)
    assert dispatch.lookup_pane("rv-code", agents) is None
    out = run("dry-run", "--since", "60")
    assert out.returncode == 0 and "WOULD tell" in out.stdout, (out.stdout, out.stderr)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("dispatch_test OK (%d)" % len(tests))


if __name__ == "__main__":
    main()
