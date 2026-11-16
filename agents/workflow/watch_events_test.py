"""Runnable check for leader/watch_events.py: python3 -I leader/watch_events_test.py.

Drives Watcher.tick with fake herdr, pane text, machine stats and status files,
and checks the JSON events, the replay after a restart and the owner-pane guard.
"""

import json
import os
import sys
import tempfile

os.environ.setdefault("WORKFLOW_OWNER_PANE", "w12:p1")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import watch_events


class Fake:
    """Holds the fake world one test drives."""

    def __init__(self, root):
        self.root = root
        self.agents = {"result": {"agents": [
            {"name": "w-a", "pane_id": "w12:pT1"},
            {"name": "rv-b", "pane_id": "w12:pT2"},
            {"name": "owner-like", "pane_id": "w12:p1"},
        ]}}
        self.panes = {"w12:pT1": "", "w12:pT2": "", "w12:p1": "Usage limit reached"}
        self.sent = []
        self.stats = {"free_gib": 100, "load": 5, "rust_analyzer": 1, "power": ("AC", 90)}

    def status(self, name, line):
        path = os.path.join(self.root, name, "status.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        old = open(path).read() if os.path.exists(path) else ""
        with open(path, "w") as fh:
            fh.write(line + "\n" + old)

    def watcher(self):
        return watch_events.Watcher(
            root=self.root, state_path=os.path.join(self.root, "state.json"),
            agents=lambda: self.agents, read_pane=lambda pane: self.panes.get(pane, ""),
            send=lambda pane, text: self.sent.append((pane, text)), stats=lambda: dict(self.stats),
            dispatch=lambda: [])


def kinds(events):
    return [e["kind"] for e in events]


def test_status_lines_replay_after_restart():
    f = Fake(tempfile.mkdtemp(prefix="watch-ev-"))
    f.status("w-a", "01:00 WORKING x")
    f.status("rv-b", "01:00 IDLE")
    w = f.watcher()
    assert w.tick() == [], "first pass only records"
    f.status("w-a", "01:05 PROGRESS y")
    f.status("w-a", "01:06 DONE z a..b INCONCLUSIVE")
    ev = w.tick()
    assert [(e["who"], e["state"]) for e in ev] == [("w-a", "PROGRESS"), ("w-a", "DONE")], ev
    assert all(json.loads(json.dumps(e)) == e for e in ev)
    f.status("rv-b", "01:10 DONE-REVIEW q r1 abcdef1 findings:0")
    w2 = f.watcher()
    ev = w2.tick()
    assert [(e["who"], e["state"]) for e in ev] == [("rv-b", "DONE-REVIEW")], ev


def test_limit_once_and_owner_pane_ignored():
    f = Fake(tempfile.mkdtemp(prefix="watch-ev-"))
    w = f.watcher()
    w.tick()
    f.panes["w12:pT1"] = "...\nYou've hit your session limit\n"
    assert kinds(w.tick()) == ["limit"]
    assert kinds(w.tick()) == [], "a limit fires once until it clears"
    f.panes["w12:pT1"] = "working"
    w.tick()
    f.panes["w12:pT1"] = "Usage limit reached"
    assert kinds(w.tick()) == ["limit"]


def test_sleep_api_error_auto_resumes_never_owner():
    f = Fake(tempfile.mkdtemp(prefix="watch-ev-"))
    w = f.watcher()
    w.tick()
    f.panes["w12:pT2"] = "API Error: socket closed, the machine went to sleep\n>"
    f.panes["w12:p1"] = "API Error: the machine went to sleep\n>"
    ev = w.tick()
    assert kinds(ev) == ["auto_resume"] and ev[0]["pane"] == "w12:pT2", ev
    assert [p for p, _ in f.sent] == ["w12:pT2"], f.sent
    f.panes["w12:pT1"] = "API Error: 500 overloaded"
    assert kinds(w.tick()) == ["api_error"]


def test_machine_events_on_change_only():
    f = Fake(tempfile.mkdtemp(prefix="watch-ev-"))
    w = f.watcher()
    w.tick()
    f.stats.update(free_gib=12, load=70, rust_analyzer=6, power=("Battery", 80))
    assert sorted(kinds(w.tick())) == ["disk_low", "load_high", "power", "rust_analyzer"]
    assert kinds(w.tick()) == []
    f.stats.update(load=30)
    f.stats.update(load=65)
    w.tick()
    assert kinds(w.tick()) == []


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("watch_events_test OK (%d)" % len(tests))


if __name__ == "__main__":
    main()
