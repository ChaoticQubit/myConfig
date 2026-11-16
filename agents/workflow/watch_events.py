"""Leader watcher (TOOLS-REPORT B5): one JSON line per event, the same checks as watch.sh.

Usage: WORKFLOW_ROOT=<sprint folder> WORKFLOW_OWNER_PANE=<pane> python3 -I -B watch_events.py [--once]. Every 30 s: new status lines of every named herdr agent,
usage limits and API errors in their panes (a sleep API error gets the watch.sh auto-resume, never on w12:p1),
disk, load, rust-analyzer count, AC or battery, and one dispatch tick when leader/dispatch-on exists.
State in $WORKFLOW_ROOT/leader/watch-events-state.json, so a restart replays lines it missed. Events also go to leader/logs/events.jsonl.
"""

import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dispatch
import wfenv

F = wfenv.ROOT
LEADER = os.path.join(F, "leader")
OWNER_PANE = wfenv.OWNER_PANE
HEAD = 15
LIMIT_RE = re.compile(r"Usage limit reached|reached your .* limit|hit your .* limit")
RESUME_TEXT = "Your last reply was cut by an API error (the machine slept). Resume the task you were on from your BRIEF.md and status.md."


class Watcher:
    """One watch pass per tick(); every outside call is injected so tests need no herdr or machine."""

    def __init__(self, root, state_path, agents, read_pane, send, stats, dispatch):
        self.root = root
        self.state_path = state_path
        self.agents = agents
        self.read_pane = read_pane
        self.send = send
        self.stats = stats
        self.dispatch = dispatch
        self.state = json.loads(dispatch_read(state_path) or "null") or {"seen": {}}
        self.lim, self.err = set(), set()
        self.flags = {}
        self.power = None

    def named(self):
        rows = self.agents().get("result", {}).get("agents", [])
        return [(a["name"], a.get("pane_id")) for a in rows if a.get("name")]

    def tick(self):
        """Runs one pass and returns its events (dicts with t and kind)."""
        t = time.strftime("%H:%M")
        events = []
        agents = self.named()
        first = not self.state["seen"]
        for name, _ in agents:
            path = os.path.join(self.root, name, "status.md")
            if not os.path.isfile(path):
                continue
            lines = [l for l in dispatch_read(path).split("\n")[:HEAD] if l.strip()]
            if not lines:
                continue
            seen = self.state["seen"].get(name)
            if not first and seen is not None and lines[0] != seen:
                new = []
                for line in lines:
                    if line == seen:
                        break
                    new.append(line)
                for line in reversed(new):
                    parsed = dispatch.parse_line(line)
                    events.append({"t": t, "kind": "status", "who": name, "state": parsed[1] if parsed else "", "line": line[:400]})
            self.state["seen"][name] = lines[0]
        for name, pane in agents:
            if not pane or pane == OWNER_PANE:
                continue
            tail = "\n".join(self.read_pane(pane).split("\n")[-12:])
            if LIMIT_RE.search(tail):
                if pane not in self.lim:
                    self.lim.add(pane)
                    events.append({"t": t, "kind": "limit", "who": name, "pane": pane})
            else:
                self.lim.discard(pane)
            if "API Error" in tail:
                if pane not in self.err:
                    self.err.add(pane)
                    if "went to sleep" in tail and "esc to interrupt" not in tail:
                        self.send(pane, RESUME_TEXT)
                        events.append({"t": t, "kind": "auto_resume", "who": name, "pane": pane})
                    else:
                        line = next((l for l in tail.split("\n") if "API Error" in l), "")
                        events.append({"t": t, "kind": "api_error", "who": name, "pane": pane, "line": line[:120]})
            else:
                self.err.discard(pane)
        events += self.machine(t)
        for line in self.dispatch():
            events.append({"t": t, "kind": "dispatch", "line": line[:400]})
        save_json(self.state_path, self.state)
        return events

    def machine(self, t):
        s = self.stats()
        out = []
        def edge(key, on, off, event):
            if on and not self.flags.get(key):
                self.flags[key] = True
                out.append(dict(event, t=t))
            elif off:
                self.flags[key] = False
        edge("disk", s["free_gib"] < 25, s["free_gib"] >= 25, {"kind": "disk_low", "free_gib": s["free_gib"]})
        edge("load", s["load"] > 60, s["load"] < 40, {"kind": "load_high", "load": s["load"]})
        edge("ra", s["rust_analyzer"] > 4, s["rust_analyzer"] <= 4, {"kind": "rust_analyzer", "count": s["rust_analyzer"]})
        if s["power"] != self.power:
            if self.power is not None:
                out.append({"t": t, "kind": "power", "source": s["power"][0], "percent": s["power"][1]})
            self.power = s["power"]
        return out


def dispatch_read(path):
    return dispatch.read_text(path)


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def run(cmd, timeout=30):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout


def real_stats():
    """Reads free disk (GiB), 5-minute load, rust-analyzer count and (source, percent) from pmset."""
    df = run(["df", "-g", "/"]).strip().split("\n")[-1].split()
    load = run(["sysctl", "-n", "vm.loadavg"]).replace("{", "").split()
    ra = [l for l in run(["pgrep", "-x", "rust-analyzer"]).split("\n") if l.strip()]
    batt = run(["pmset", "-g", "batt"])
    source = "AC" if "AC Power" in batt else ("Battery" if "Battery Power" in batt else "unknown")
    pct = re.search(r"(\d+)%", batt)
    return {"free_gib": int(df[3]) if len(df) > 3 and df[3].isdigit() else 999,
            "load": int(float(load[1])) if len(load) > 1 else 0,
            "rust_analyzer": len(ra), "power": (source, int(pct.group(1)) if pct else -1)}


def real_send(pane, text):
    assert pane != OWNER_PANE
    run(["herdr", "pane", "send-text", pane, text])
    run(["herdr", "pane", "send-keys", pane, "Enter"])
    with open(os.path.join(LEADER, "logs", "auto-resume.log"), "a") as fh:
        fh.write("%s AUTO-RESUMED pane %s after a sleep API error (watch_events)\n" % (time.strftime("%H:%M"), pane))


def real_dispatch():
    if not os.path.exists(os.path.join(LEADER, "dispatch-on")):
        return []
    out = run(["bash", os.path.join(HERE, "dispatch.sh"), "tick"], timeout=600)
    return [l for l in out.split("\n") if l.strip() and not l.startswith("dispatch tick ")] if out else []


def main(argv):
    wfenv.require_root(F)
    wfenv.require_owner_pane()
    w = Watcher(root=F, state_path=os.path.join(LEADER, "watch-events-state.json"),
                agents=lambda: json.loads(run(["herdr", "agent", "list"]) or '{"result":{"agents":[]}}'),
                read_pane=lambda pane: run(["herdr", "pane", "read", pane]), send=real_send, stats=real_stats,
                dispatch=real_dispatch)
    log = os.path.join(LEADER, "logs", "events.jsonl")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    while True:
        for event in w.tick():
            line = json.dumps(event, ensure_ascii=False)
            print(line, flush=True)
            with open(log, "a") as fh:
                fh.write(line + "\n")
        if "--once" in argv:
            return 0
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
