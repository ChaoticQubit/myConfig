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
import time

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
    acts = engine.feed("w-a", "02:46 ACK leader, DONE expected by 03:00", "02:46")
    assert kinds(acts) == ["queue"] and "DONE expected" in acts[0][1], acts
    assert engine.feed("w-a", "02:47 WORKING on it", "02:47") == []


FIX6_0254 = ("02:54 DONE combo-five: -44 and -64 already FIXED on chore/v242 be9eaae14 (d3ec436f0 via 183dc4ad1, "
             "c4924585c via eade043f7), no code; DONE-02:54-combo-five.md")
LINE_TABLE = TABLE + "line *v242* chore/v242\nline feat/v3-* chore/v3\n"
COMBO_TIP = "be9eaae144de1d52e6b3453417bce7aea659f057"
COMBO_FILE = ("Verdict word: VERIFIED (read only, at the tip; nothing run, per DEC-170). fix/v242-combo-five has no commits: "
              "it sits at be9eaae14, and its clean worktree is .worktrees/v242-combo-five. I remove both on your OK.\n")


def line_engine(ahead):
    """Returns an engine with line rows, fix6's real DONE file, fix/v242-combo-five and chore/v242 at one tip, ahead counts from a dict."""
    files = {"w-v241-fix6/DONE-02:54-combo-five.md": COMBO_FILE}
    engine = dispatch.Engine(dispatch.parse_table(LINE_TABLE), dispatch.parse_rules(RULES), dispatch.new_state(),
                             read_file=lambda p: files.get(p, ""),
                             resolve_tip=lambda b: COMBO_TIP if b in ("fix/v242-combo-five", "chore/v242") else None,
                             count_ahead=lambda tip, line, hhmm: ahead.get((tip, line)))
    for name in ["rv-code", "rv-secreview", "rv-code2", "rv-sec2"]:
        engine.feed(name, "IDLE", "02:50")
    return engine


def test_no_code_done_goes_to_leader_not_reviewers():
    assert dispatch.parse_table(LINE_TABLE)["lines"] == [("*v242*", "chore/v242"), ("feat/v3-*", "chore/v3")]
    engine = line_engine({(COMBO_TIP, "chore/v242"): 0})
    acts = engine.feed("w-v241-fix6", FIX6_0254, "02:54")
    assert kinds(acts) == ["queue"] and "says no code" in acts[0][1], acts
    acts = engine.feed("w-v241-fix6", FIX6_0254.replace(", no code", ""), "02:54")
    assert kinds(acts) == ["queue"] and "fix/v242-combo-five tip be9eaae14 has 0 commits ahead of chore/v242" in acts[0][1], acts
    assert engine.state["assignments"] == [] and engine.state["pending"] == []


def test_zero_commits_ahead_of_line_goes_to_leader():
    engine = line_engine({("bbbbbbb2", "chore/v242"): 0, ("bbbbbbb3", "chore/v242"): 2})
    acts = engine.feed("w-a", "02:56 DONE t30 fix/v242-t30 aaaaaaa1..bbbbbbb2 rows written", "02:56")
    assert kinds(acts) == ["queue"] and "0 commits ahead of chore/v242" in acts[0][1], acts
    acts = engine.feed("w-a", "02:57 DONE t31 fix/v242-t31 aaaaaaa1..bbbbbbb3 rows written", "02:57")
    assert "tell" in kinds(acts), acts
    acts = engine.feed("w-b", "02:58 DONE t32 fix/other-t32 aaaaaaa1..bbbbbbb4", "02:58")
    assert "tell" in kinds(acts), acts


def test_git_ahead_counts_commits_past_the_line():
    repo = tempfile.mkdtemp(prefix="dispatch-ahead-")
    run = lambda *a: subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True, check=True).stdout.strip()
    run("init", "-q", "-b", "chore/x")
    run("-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "a")
    line_tip = run("rev-parse", "HEAD")
    assert dispatch.git_ahead(repo, line_tip, "chore/x") == 0
    run("checkout", "-q", "-b", "fix/y")
    run("-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "b")
    assert dispatch.git_ahead(repo, run("rev-parse", "HEAD"), "chore/x") == 1
    assert dispatch.git_ahead(repo, run("rev-parse", "HEAD"), "chore/x", time.strftime("%H:%M")) == 1
    assert dispatch.git_ahead(repo, line_tip, "chore/missing") is None


H6_0306 = ("03:06 DONE-03:06-linux-strict-switch: feat/v242-linux-strict-switch 2a6bf0cbb..daea3888b INCONCLUSIVE "
           "(written, not run). Both tracks (sandbox class). Flag: TUI GitHub hint now \"g Sign out\". Next: S1 rights branch off chore/v242 tip.")


def test_done_file_name_as_kind_routes():
    assert dispatch.parse_line(H6_0306)[:2] == ("03:06", "DONE"), dispatch.parse_line(H6_0306)
    assert dispatch.parse_line("02:29 DONE-02:29-agent.md fix/v242-a e1d9800b0..9e399832e")[2].startswith("agent: fix/v242-a ")
    assert dispatch.parse_line("03:08 DONE-REVIEW t r1 abcdef1 findings:0")[1] == "DONE-REVIEW"
    engine, _ = make_engine()
    acts = engine.feed("w-v242-h6", H6_0306, "03:06")
    assert kinds(acts) == ["facts", "tell", "tell", "ledger"], acts
    assert acts[0][2] == "2a6bf0cbb..daea3888b" and "feat/v242-linux-strict-switch" in acts[1][2], acts
    job = engine.state["assignments"][0]
    assert job["slug"] == "linux-strict-switch" and job["done_file"] == "DONE-03:06-linux-strict-switch.md", job


H6_0229 = ("02:29 DONE-02:29-linux-agent-launch.md fix/v242-linux-agent-launch e1d9800b0..9e399832e for review: DS-194 red 786b6797c "
           "(green at red macOS) + fix 9e399832e (Linux npm via InstalledSandbox, sockets+supervisor, macOS byte-identical); N3 no code: "
           "prepare already refuses Linux up front (runtime.rs:9218 DEC-094, row tests.rs:3700), my 02:24 late-failure claim corrected; "
           "merge-tree clean vs chore 8bbfc1a83 + sbx2; fmt 0; not built")


def test_no_code_item_in_a_ranged_done_still_routes():
    engine = line_engine({("9e399832e", "chore/v242"): 2})
    acts = engine.feed("w-v242-h6", H6_0229, "02:29")
    assert "tell" in kinds(acts), acts
    assert engine.state["assignments"][0]["slug"] == "linux-agent-launch", engine.state["assignments"]


SECREVIEW_0318 = ("03:18 DONE-REVIEW agent-home-config r2 72374bb findings:0 (rv-sec3 F1 MED + rv-code4 F1 MED + N1 closed: real .cargo "
                  "keeps only registry/git links, relinked to owner caches read-only per Seatbelt, re-pointed links replaced; 0 open; "
                  "FINDINGS-03:15-agent-home-config-r2.md)")
DS241_0313 = ("03:13 rv-ds241: DONE-REVIEW code r2 confirm fix/v242-agent-home-config 81726813d..72374bb: clean, rv-code4 F1 + rv-sec3 F1 MED "
              "closed (keep_only CARGO_KEPT links-only allowlist sweeps real registry/git and all config, then prepare_cargo_home relinks to "
              "owner read-only caches; guard keeps owner home), rv-sec3 N1 credentials.toml closed; rows red by assertion; N1 no "
              "foreign-link row at this level, N2 behavior line for docs; F/rv-ds241/FINDINGS-03:13-agent-home-config-r2.md")
SEC4_1116 = ("11:16 IDLE queue empty (NEXT-11:00 1/1 + item 2 DROPPED, NEXT-11:03 repin r2, NEXT-11:05 team-stop r3, NEXT-11:12 3/3 done; "
             "all findings:0)")
LIVE_0320 = ["rv-sa241", "rv-sec3", "rv-sec2", "rv-ds241", "rv-code", "rv-secreview", "rv-code2", "rv-code4"]


def test_closed_findings_do_not_count_as_open():
    assert dispatch.items_in(SECREVIEW_0318) == [] and dispatch.items_in(DS241_0313) == []
    assert dispatch.items_in("findings:1 (F1 MED: the closed socket leaks)") == [("F1", "MED")]
    assert dispatch.items_in("findings:2 (F1 LOW naming, F2 MED closed)") == [("F1", "LOW")]
    for still_open in ["findings:2 (PU-1 Medium fail-closed: 16 new app plugin/Search commands in build.rs",
                       "findings:3 (F1 MEDIUM master Complete/Closed on sub review_ready work releases",
                       "findings:1 (F1 LOW r1 F1 NOT closed: global cap is id distance",
                       "findings:2 (F1 LOW r1 F1 NARROWED not closed: user-space swap window gone",
                       "findings:1 (F1 LOW fails closed: TMPDIR is the walked ca-<hash> tmp",
                       "F4 LOW uid pin first-start signal. Closed: r1 F2 F4 F5 N1"]:
        assert len(dispatch.items_in(still_open)) == 1, still_open
    table = dispatch.parse_table("code * rv-ds241\nsec * rv-secreview\nledger * LEDGER-242-reviews.md\n")
    engine = dispatch.Engine(table, dispatch.parse_rules(RULES), dispatch.new_state())
    for name in ["rv-ds241", "rv-secreview"]:
        engine.feed(name, "IDLE", "03:10")
    job = {"slug": "agent-home-config", "branch": "fix/v242-agent-home-config", "range": "81726813d..72374bbc8", "tip": "72374bbc8",
           "worker": "w-v241-fix7", "round": 2, "done_file": None, "t": "03:10", "prefer": None}
    engine.state["pending"].append(job)
    engine.retry_pending("03:10", only=job)
    assert [(x["code"], x["sec"]) for x in engine.state["assignments"]] == [("rv-ds241", "rv-secreview")], engine.state
    assert engine.feed("rv-secreview", SECREVIEW_0318, "03:18") == []
    acts = engine.feed("rv-ds241", DS241_0313, "03:19")
    queue = [x[1] for x in acts if x[0] == "queue"]
    assert len(queue) == 1 and "rv-ds241 gave no findings:N" in queue[0] and "F1 MED" not in queue[0] and " named" not in queue[0], acts


def test_reviewer_without_a_live_pane_is_never_chosen():
    table = dispatch.parse_table("code * rv-code rv-code2\nsec * rv-sec4 rv-secreview\nledger * LEDGER-242-reviews.md\n")
    engine = dispatch.Engine(table, dispatch.parse_rules(RULES), dispatch.new_state())
    for name in ["rv-code", "rv-code2", "rv-secreview"]:
        engine.feed(name, "IDLE", "03:00")
    engine.feed("rv-sec4", SEC4_1116, "03:00")
    engine.present = set(LIVE_0320)
    acts = engine.feed("w-a", "03:20 DONE t50 fix/v242-t50 aaaaaaa1..bbbbbbb8 rows written", "03:20")
    assert [a[1] for a in acts if a[0] == "tell"] == ["rv-code", "rv-secreview"], acts
    engine.present = set(LIVE_0320) | {"rv-sec4"}
    engine.feed("w-b", "03:21 DONE t51 fix/v242-t51 aaaaaaa1..bbbbbbb9 rows written", "03:21")
    assert engine.state["assignments"][-1]["sec"] == "rv-sec4", engine.state["assignments"][-1]
    engine.feed("rv-code2", "DONE-REVIEW t51 r1 bbbbbbb9 findings:1 (F1 LOW name)", "03:22")
    engine.feed("rv-sec4", "DONE-REVIEW t51 r1 bbbbbbb9 findings:0", "03:22")
    engine.feed("rv-code", "DONE-REVIEW t50 r1 bbbbbbb8 findings:0", "03:22")
    engine.feed("rv-secreview", "DONE-REVIEW t50 r1 bbbbbbb8 findings:0", "03:22")
    engine.present = set(LIVE_0320)
    acts = engine.feed("w-b", "03:23 DONE t51 fix/v242-t51 bbbbbbb9..ccccccc9 r2 folds rv-code2 F1", "03:23")
    assert "rv-sec4" not in [a[1] for a in acts if a[0] == "tell"], acts
    assert engine.state["assignments"][-1]["sec"] == "rv-secreview", engine.state["assignments"][-1]


def reload(engine):
    """Returns a new engine on a JSON copy of engine's state, the way every live tick reloads dispatch-state.json."""
    return dispatch.Engine(engine.table, engine.rules, json.loads(json.dumps(engine.state)), read_file=engine.read_file,
                           list_dir=engine.list_dir, resolve_tip=engine.resolve_tip, count_ahead=engine.count_ahead)


def test_json_reloaded_state_acts_like_in_memory_state():
    kept, _ = make_engine()
    reloaded, _ = make_engine()
    steps = [
        ("w-a", "DONE t40 fix/v242-t40 aaaaaaa1..bbbbbbb5 rows written", "03:00"),
        ("w-b", "DONE t41 fix/v242-t41 aaaaaaa1..bbbbbbb6 rows written", "03:00"),
        ("w-c", "DONE t42 fix/v242-t42 aaaaaaa1..bbbbbbb7 rows written", "03:00"),
        ("rv-code", "DONE-REVIEW t40 r1 bbbbbbb5 findings:1 (F1 LOW naming)", "03:01"),
        ("rv-secreview", "DONE-REVIEW t40 r1 bbbbbbb5 findings:1 (S1 MED path check)", "03:02"),
        ("rv-code2", "DONE-REVIEW t41 r1 bbbbbbb6 findings:0", "03:03"),
        ("rv-sec2", "DONE-REVIEW t41 r1 bbbbbbb6 findings:2 (S1 LOW a)", "03:03"),
        ("rv-code", "DONE-REVIEW t42 r1 bbbbbbb7 findings:0", "03:03"),
        ("rv-secreview", "DONE-REVIEW t42 r1 bbbbbbb7 findings:1 (S2 LOW b)", "03:03"),
        ("w-a", "DONE t40 fix/v242-t40 bbbbbbb5..ccccccc5 r2 folds rv-secreview S1", "03:04"),
        ("rv-code", "DONE-REVIEW t40 r2 ccccccc5 findings:0", "03:05"),
        ("rv-secreview", "DONE-REVIEW t40 r2 ccccccc5 findings:0", "03:05"),
        ("w-a", "DONE t40 fix/v242-t40 ccccccc5..ddddddd5 r3", "03:07"),
    ]
    for folder, line, hhmm in steps:
        reloaded = reload(reloaded)
        a = kept.feed(folder, line, hhmm) + kept.retry_pending(hhmm)
        reloaded = reload(reloaded)
        b = reloaded.feed(folder, line, hhmm) + reloaded.retry_pending(hhmm)
        assert a == b, (line, a, b)
    assert json.loads(json.dumps(kept.state)) == json.loads(json.dumps(reloaded.state))
    assert len(kept.state["assignments"]) == 4 and all(x["closed"] for x in kept.state["assignments"]), kept.state["assignments"]


H6_0326 = "03:26 S1 DONE (feat/v242-linux-team-s1-rights 485f4b08c INCONCLUSIVE). Now: strict fold rv-sec2 F1 (stale read refusal)"


def test_any_line_with_done_that_does_not_route_reaches_the_leader():
    engine, _ = make_engine()
    acts = engine.feed("w-v242-h6", H6_0326, "03:26")
    assert kinds(acts) == ["queue"] and "w-v242-h6" in acts[0][1] and "S1 DONE (feat/v242-linux-team-s1-rights" in acts[0][1], acts
    acts = engine.feed("rv-code", "03:27 STARTED t60 after w-a DONE (leader 03:26)", "03:27")
    assert kinds(acts) == ["queue"], acts
    assert engine.feed("rv-code", "03:28 DONE-REVIEW t60 r1 abcdef1 findings:0", "03:28") == []
    assert engine.feed("w-a", "03:29 WORKING on t61, done soon", "03:29") == []


BUGREPEAT_0338 = ("03:38 w-bug-repeat: DONE E2E-TUI-SCRATCH-HOME fix/v242-e2e-tui-scratch-home 766929ce8..e936f84e9 INCONCLUSIVE "
                  "(written, not run): e2e_tui Pty::launch 7->0 (removed), Engine::start 14->0, every engine via engine_at (private HOME + "
                  "XDG config/data), managed_setup:164 on a refusing port; fmt rc 0, merge-tree clean vs chore f5e69229e. "
                  "DONE-0337-e2e-tui-scratch-home.md. Now: rv-sec3 F1 fold on engine-hermetic.")
FIX11_0224 = ("02:24 DONE gsb2-lows r1 fold: fix/v242-gsb2-lows 0923f730c..d12e9181e (2): rv-ds241 L1 (886744dd1 red row: failed latest "
              "read past the budget with a kept ok-null read -> 'read'; d12e9181e lostStartStep takes failed = readFailed !== null, 'over' "
              "only on an answered no-publish latest read) + N1 (effect deps add projectId; card regexes pin call and deps); merge-tree "
              "clean vs chore/v242 1c1d00072; rows written not run; TS only.")


def test_fold_is_read_from_the_done_head_not_the_next_task():
    engine, _ = make_engine()
    acts = engine.feed("w-bug-repeat", BUGREPEAT_0338, "03:38")
    assert kinds(acts) == ["facts", "tell", "tell", "ledger"], acts
    job = engine.state["assignments"][0]
    assert (job["slug"], job["round"], job["done_file"]) == ("E2E-TUI-SCRATCH-HOME", 1, "DONE-0337-e2e-tui-scratch-home.md"), job
    acts = engine.feed("w-v241-fix11", FIX11_0224, "02:24")
    assert kinds(acts) == ["queue"] and "folds findings" in acts[0][1], acts


H6_0341 = "03:41 DONE linux-strict-fold feat/v242-linux-strict-switch 883b15788..0c488d35d INCONCLUSIVE; DONE-03:41-strict-fold-stale-read.md"
ANCESTRY = {("daea3888b", "883b15788"): True, ("daea3888b", "2a6bf0cbb"): False, ("daea3888b", "0c488d35d"): True,
            ("daea3888b", "eeeeeee11"): False}


def strict_r1(reviews=True):
    """Returns an engine where the leader routed h6's strict switch r1 (2a6bf0cbb..daea3888b) and both reviews came in."""
    engine, files = make_engine()
    engine.is_ancestor = lambda old, new: ANCESTRY.get((old[:9], new[:9]))
    acts = engine.leader_route("feat/v242-linux-strict-switch", "2a6bf0cbb..daea3888b", "rv-code2", "rv-sec2", None, "w-v242-h6", "03:07")
    if reviews:
        engine.feed("rv-code2", "03:15 DONE-REVIEW linux-strict-switch r1 daea3888b findings:0", "03:15")
        engine.feed("rv-sec2", "03:18 DONE-REVIEW linux-strict-switch r1 daea3888b findings:2 (F1 LOW stale read, F2 LOW words)", "03:18")
    return engine, acts


def test_leader_route_is_recorded_and_tells_both():
    engine, acts = strict_r1(reviews=False)
    assert [a[1] for a in acts if a[0] == "tell"] == ["rv-code2", "rv-sec2"], acts
    a = engine.state["assignments"][-1]
    assert (a["leader"], a["round"], a["tip"], a["worker"], a["range"]) == (True, 1, "daea3888b", "w-v242-h6", "2a6bf0cbb..daea3888b"), a
    assert "leader route" in [x for x in acts if x[0] == "ledger"][0][2], acts
    for bad in [("feat/x", "2a6bf0cbb..daea3888b", "rv-code2", "rv-code2"), ("feat/x", "nope", "rv-code2", "rv-sec2"),
                ("feat/v242-linux-strict-switch", "daea3888b..fffffff1", "rv-code", "rv-sec3")]:
        try:
            engine.leader_route(bad[0], bad[1], bad[2], bad[3], None, "w-v242-h6", "03:08")
            raise AssertionError("accepted %s" % (bad,))
        except ValueError:
            pass


def test_fold_on_a_known_branch_routes_r2_to_the_r1_pair():
    engine, _ = strict_r1()
    acts = engine.feed("w-v242-h6", H6_0341, "03:41")
    tells = [x for x in acts if x[0] == "tell"]
    assert [t[1] for t in tells] == ["rv-code2", "rv-sec2"] and " r2:" in tells[0][2] and "883b15788..0c488d35d" in tells[0][2], acts
    assert engine.state["assignments"][-1]["round"] == 2
    engine, _ = strict_r1()
    acts = engine.feed("w-v242-h6", H6_0341.replace("883b15788..", "2a6bf0cbb.."), "03:41")
    assert "daea3888b..0c488d35d" in [x for x in acts if x[0] == "tell"][0][2], acts
    engine, _ = strict_r1()
    acts = engine.feed("w-v242-h6", H6_0341.replace("883b15788..0c488d35d", "2a6bf0cbb..eeeeeee11"), "03:41")
    assert kinds(acts) == ["queue"] and "not in" in acts[0][1], acts
    engine, _ = strict_r1()
    engine.feed("rv-code2", "03:30 STARTED other", "03:30")
    acts = engine.feed("w-v242-h6", H6_0341, "03:41")
    assert [x[1] for x in acts if x[0] == "tell"] == ["rv-code", "rv-sec2"], acts


def test_fix11_fold_routes_r2_after_a_leader_route():
    engine, _ = make_engine()
    engine.leader_route("fix/v242-gsb2-lows", "1b963569f..0923f730c", "rv-ds241", "rv-sec2", "r1", "w-v241-fix11", "02:19")
    engine.feed("rv-ds241", "02:22 DONE-REVIEW gsb2-lows r1 0923f730c findings:1 (L1 LOW read past the budget)", "02:22")
    engine.feed("rv-sec2", "02:22 DONE-REVIEW gsb2-lows r1 0923f730c findings:0", "02:22")
    acts = engine.feed("w-v241-fix11", FIX11_0224, "02:24")
    tells = [x for x in acts if x[0] == "tell"]
    assert [t[1] for t in tells] == ["rv-ds241", "rv-sec2"] and "0923f730c..d12e9181e" in tells[0][2], acts


def test_fold_past_the_round_cap():
    for sec_line, want in [("findings:1 (S1 HIGH socket left open) FINDINGS-03:50-linux-strict-switch-r2.md", "queue"),
                           ("findings:1 (S1 LOW wording) FINDINGS-03:50-linux-strict-switch-r2.md", "backlog")]:
        engine, _ = strict_r1()
        engine.feed("w-v242-h6", H6_0341, "03:41")
        engine.feed("rv-code2", "03:50 DONE-REVIEW linux-strict-switch r2 0c488d35d findings:0", "03:50")
        engine.feed("rv-sec2", "03:50 DONE-REVIEW linux-strict-switch r2 0c488d35d " + sec_line, "03:50")
        acts = engine.feed("w-v242-h6", "04:05 DONE linux-strict-fold2 feat/v242-linux-strict-switch 0c488d35d..fffffff12 r2 fold", "04:05")
        assert "tell" not in kinds(acts), acts
        if want == "queue":
            assert kinds(acts) == ["queue"] and "open HIGH" in acts[0][1] and "S1" in acts[0][1], acts
        else:
            back = [x[1] for x in acts if x[0] == "backlog"]
            assert "queue" not in kinds(acts) and back, acts
            assert "feat/v242-linux-strict-switch" in back[0] and "fffffff12" in back[0] and "F/rv-sec2/FINDINGS-03:50-linux-strict-switch-r2.md" in back[0], back


FIX8_0354 = ("03:54 w-v241-fix8 DONE fix/v242-harness-sec-r2 76b997050..769bfb115 INCONCLUSIVE (rows written, not run, DEC-170; rustfmt "
             "clean both commits) DONE-03:54-harness-sec-r2.md. Supersedes the 03:54 line's two verdict words. Red 2a11f33b6, fix 769bfb115. "
             "No slot jobs.")


def test_round_word_inside_a_branch_or_slug_is_not_a_round():
    engine, _ = make_engine()
    acts = engine.feed("w-v241-fix8", FIX8_0354, "03:54")
    assert kinds(acts) == ["facts", "tell", "tell", "ledger"], acts
    job = engine.state["assignments"][0]
    assert (job["slug"], job["round"], job["done_file"]) == ("v242-harness-sec-r2", 1, "DONE-03:54-harness-sec-r2.md"), job
    assert dispatch.ROUND_RE.findall("harness-sec-r2 DONE-03:54-x-r2.md fix/v242-y-r3") == []
    assert [a or b for a, b in dispatch.ROUND_RE.findall("(r1 fold batch), r2: and round 3")] == ["1", "2", "3"]
    acts = engine.feed("w-b", "03:55 DONE t70-r2 fix/v242-t70 aaaaaaa1..bbbbbbb9 r2 folds rv-code F1", "03:55")
    assert kinds(acts) == ["queue"] and "folds findings" in acts[0][1], acts


H4_0410 = ('04:10 11-16 DONE 2.4.2 PROTO-3-SEC-F1/F2 fix/v242-proto3-kept-route f5e69229e..f2cfded27 (2): a recheck kept an ended an'
           'swer as running with no validate_auth_reply (F2 open); shared validated() now checks it on the kept route and in settle_'
           'auth, failure leaves it stuck; red d14292157 (running_answer extracted unchanged; R1 red, R2-R4 coverage incl. new sign-'
           'in after a kept end, ending refusal, all six ended phases) fix f2cfded27; ending refusal (no reply) still kept unchecked'
           '; DONE-04:10-proto3-kept-route.md; merge-tree clean vs chore/v242 f5e69229e; fmt --check clean; rows written not run. Id'
           'le: waiting on reviews (slice B 03:13, probe-cache 03:58, proto3 04:10)')


def test_backlog_ids_and_versions_are_not_slugs_or_findings():
    engine, _ = make_engine()
    acts = engine.feed("w-v242-h4", H4_0410, "04:10")
    assert kinds(acts) == ["facts", "tell", "tell", "ledger"], acts
    job = engine.state["assignments"][0]
    assert (job["slug"], job["branch"], job["range"], job["round"]) == (
        "proto3-kept-route", "fix/v242-proto3-kept-route", "f5e69229e..f2cfded27", 1), job
    assert dispatch.FOLD_RE.search("PROTO-3-SEC-F1/F2 DS-TRUST-F2") is None
    assert dispatch.FOLD_RE.search("agent-home-f1 fold") and dispatch.FOLD_RE.search("fix/v241-x-f2")


FIX8_0423 = ('04:23 w-v241-fix8 DONE rcli slot reach trace (read-only, 02e94a923): NOT REAL, no branch. DONE-04:23-rcli-slot-reach.md.'
             ' rcli and listed slots never coincide (listed_key digest of listed/<id>; configured rcli home refused inside native-prof'
             'iles and must be canonical), and guard_engine_around denies native-profiles and every other home. Found by reading: a li'
             'sted master home sits inside native-profiles, so clear_of_secrets likely refuses every listed master sandbox (latent, un'
             'tested).')


def test_read_only_or_no_branch_done_without_a_range_never_routes():
    engine, files = make_engine()
    files["w-v241-fix8/DONE-04:23-rcli-slot-reach.md"] = "Read at feat/v242-harness-layer 02e94a923, nothing written.\n"
    engine.resolve_tip = lambda branch: {"feat/v242-harness-layer": "02e94a923aa"}.get(branch)
    acts = engine.feed("w-v241-fix8", FIX8_0423, "04:23")
    assert kinds(acts) == ["queue"] and "no code" in acts[0][1], acts
    assert engine.state["assignments"] == [] and engine.state["pending"] == []
    for words in ("no branch", "read only", "Read-only"):
        assert dispatch.NO_WORK_RE.search("trace (%s, 02e94a923)" % words), words
    for text in ("list first/last_line read only engine-run turns", "names no branch when checked out", "risk low (read-only folders)",
                 "Run 1 real store read-only: PASS", "model-access-read-only missing"):
        assert dispatch.NO_WORK_RE.search(text) is None, text
    engine, files = make_engine()
    engine.resolve_tip = lambda branch: {"fix/b19-kept": "bb5febbb9aa"}.get(branch)
    acts = engine.feed("w-usagefix", "05:13 DONE KEPT-L1 bb5febbb9 (fix/b19-kept, worktree clean). Next: root cause (read-only)", "05:13")
    assert kinds(acts) == ["tell", "tell", "ledger"], acts
    engine, files = make_engine()
    acts = engine.feed("w-a", "04:24 DONE ro-fix fix/v242-ro aaaaaaa1..bbbbbbb9 read-only mount refused", "04:24")
    assert kinds(acts) == ["facts", "tell", "tell", "ledger"], acts


FIX7_0437 = ('04:37 11-16 fix7 DONE x2 INCONCLUSIVE (red-green job rg-v242-0434 queued, verdict line follows): LINUX-KILL-GROUP r1 fol'
             'd e2e8a696b..20b3563a5 (rcli host + server check followed, rcli leftovers held with profile; sec LOW F1 subreaper not sm'
             'all -> backlog) DONE-04:37-linux-kill-group-f1.md; LAND-UPDATING-STUCK f5e69229e..dbf2c3afd DONE-04:37-land-updating-stu'
             'ck.md')


def test_a_line_with_two_ranges_routes_each_item_or_goes_to_the_leader():
    engine, files = make_engine()
    files["w-v241-fix7/DONE-04:37-linux-kill-group-f1.md"] = "# kill group\n\nBranch fix/v242-linux-kill-group. Fold range e2e8a696b..20b3563a5.\n"
    files["w-v241-fix7/DONE-04:37-land-updating-stuck.md"] = "# stuck\n\nBranch fix/v242-land-updating-stuck. Range f5e69229e..dbf2c3afd.\n"
    acts = engine.feed("w-v241-fix7", FIX7_0437, "04:37")
    queued = [a[1] for a in acts if a[0] == "queue"]
    assert len(queued) == 1 and "linux-kill-group-f1 folds findings" in queued[0], acts
    made = [(a["branch"], a["range"], a["slug"], a["done_file"]) for a in engine.state["assignments"]]
    assert made == [("fix/v242-land-updating-stuck", "f5e69229e..dbf2c3afd", "land-updating-stuck", "DONE-04:37-land-updating-stuck.md")], made
    acts = engine.feed("w-b", "04:40 DONE t71 fix/v242-t71 aaaaaaa1..bbbbbbb2 rebased from ccccccc3..ddddddd4", "04:40")
    assert kinds(acts) == ["queue"] and "2 ranges" in acts[0][1], acts
    acts = engine.feed("w-b", "04:41 DONE t72 fix/v242-t72 aaaaaaa1..bbbbbbb3, range aaaaaaa1..bbbbbbb3 as before", "04:41")
    assert kinds(acts) == ["facts", "tell", "tell", "ledger"], acts
    engine, _ = make_engine()
    acts = engine.feed("w-c", "04:42 DONE t73 fix/v242-t73 aaaaaaa1..bbbbbbb4 (2, branch now ccccccc5..bbbbbbb4 (6))", "04:42")
    assert kinds(acts) == ["facts", "tell", "tell", "ledger"] and engine.state["assignments"][-1]["range"] == "aaaaaaa1..bbbbbbb4", acts


def test_drop_removes_a_pending_or_open_item_and_logs_it():
    engine, _ = make_engine()
    engine.feed("w-a", "04:40 DONE one fix/v242-one aaaaaaa1..bbbbbbb2", "04:40")
    engine.present = set()
    engine.feed("w-b", "04:41 DONE two fix/v242-two ccccccc3..ddddddd4", "04:41")
    assert [p["branch"] for p in engine.state["pending"]] == ["fix/v242-two"]
    acts = engine.drop("fix/v242-two", "leader-read and merged", "04:52")
    assert engine.state["pending"] == [] and kinds(acts) == ["ledger"], acts
    assert acts[0][2] == "04:52 two ddddddd4 pending dropped by leader: leader-read and merged", acts
    acts = engine.drop("fix/v242-one", "merged", "04:53")
    job = engine.state["assignments"][0]
    assert job["closed"] and job["dropped"] == "merged" and kinds(acts) == ["ledger"], job
    assert "#1 open (rv-code + rv-secreview) dropped by leader: merged" in acts[0][2], acts
    for branch, reason in (("fix/v242-one", "again"), ("fix/v242-none", "x"), ("fix/v242-two", " ")):
        try:
            engine.drop(branch, reason, "04:54")
            raise AssertionError("drop accepted %s %r" % (branch, reason))
        except ValueError as err:
            assert branch in str(err) or "reason" in str(err), err


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


def test_round2_takes_a_free_reviewer_when_its_round1_reviewer_is_busy():
    engine, _ = make_engine()
    route_one(engine)
    engine.feed("rv-code", "DONE-REVIEW t17 r1 bbbbbbb2 findings:1 (F1 LOW a)", "01:50")
    engine.feed("rv-secreview", "DONE-REVIEW t17 r1 bbbbbbb2 findings:0", "01:52")
    engine.feed("rv-code", "STARTED other", "01:55")
    acts = engine.feed("w-a", "DONE t17 r2 fix/v242-t17 bbbbbbb2..ddddddd4 folds", "02:10")
    assert [a[1] for a in acts if a[0] == "tell"] == ["rv-code2", "rv-secreview"], acts
    assert engine.state["pending"] == [] and engine.state["assignments"][-1]["round"] == 2


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


def test_round2_lows_go_to_backlog_and_a_fold_after_r2_too():
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
    assert kinds(acts) == ["backlog", "ledger"] and "eeeeeee5" in acts[0][1] and "no open HIGH" in acts[0][1], acts


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
    assert fold("T23-R1-L3 branch fix/v21-ide-4 range 901fa38e")
    assert fold("FBTMUX-P1 r1 (L1 Save follows No limit, L2 re")
    assert fold("V241-DS-FIXES r1 F1 fix/v241-ds-fixes 7136ac4")
    assert not fold("DS-TRUST-R2 fix/v241-ds-trust 71770b425..ad82")
    assert not fold("t17 r2 fix/v242-t17 bbbbbbb2..ddddddd4")


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
    status("w-a", "01:40 WORKING t18 fix/v242-t18")
    out = run("route", "fix/v242-t18", "ccccccc1..ddddddd1", "rv-code2", "rv-sec2")
    assert out.returncode == 0, (out.stdout, out.stderr)
    now = open(sent).read().strip().split("\n")
    assert [l.split("\t")[0] for l in now[len(lines):]] == ["w12:pT3", "w12:pT4"], now
    state = json.load(open(os.path.join(leader, "dispatch-state.json")))
    made = [x for x in state["assignments"] if x["branch"] == "fix/v242-t18"]
    assert len(made) == 1 and made[0]["leader"] and made[0]["worker"] == "w-a" and made[0]["round"] == 1, made
    out = run("route", "fix/v242-t19", "ccccccc1..ddddddd2", "rv-code2", "rv-sec4", "w-a")
    assert out.returncode == 3 and "rv-sec4" in out.stdout, (out.stdout, out.stderr)
    out = run("route", "fix/v242-t20", "ccccccc1..ddddddd3", "rv-code", "rv-sec2")
    assert out.returncode == 2 and "worker" in out.stdout, (out.stdout, out.stderr)
    assert len(open(sent).read().strip().split("\n")) == len(now)
    out = run("drop", "fix/v242-t18", "leader-read", "and", "merged")
    assert out.returncode == 0 and "dropped" in out.stdout and "rv-code2" in out.stdout, (out.stdout, out.stderr)
    state = json.load(open(os.path.join(leader, "dispatch-state.json")))
    gone = [x for x in state["assignments"] if x["branch"] == "fix/v242-t18"]
    assert gone[0]["closed"] and gone[0]["dropped"] == "leader-read and merged", gone
    assert "dropped by leader: leader-read and merged" in open(os.path.join(leader, "LEDGER-242-reviews.md")).read()
    for args in (("drop", "fix/v242-t18", "again"), ("drop", "fix/v242-t18")):
        out = run(*args)
        assert out.returncode == 2, (args, out.stdout, out.stderr)
    assert len(open(sent).read().strip().split("\n")) == len(now)
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
