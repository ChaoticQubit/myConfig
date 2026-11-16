"""Settings the workflow tools share, read from the environment so one copy serves every project.

WORKFLOW_ROOT: the project's sprint folder (one sub-folder per agent with status.md, plus leader/). Required by every live command.
WORKFLOW_REPO: the project's git repository; default is the git toplevel that holds WORKFLOW_ROOT.
WORKFLOW_OWNER_PANE: the pane no tool ever types into; commands that send text refuse to run without it.
"""

import os
import subprocess
import sys

ROOT = os.environ.get("WORKFLOW_ROOT", "")
OWNER_PANE = os.environ.get("WORKFLOW_OWNER_PANE", "")


def repo(root):
    """Returns WORKFLOW_REPO, else the git toplevel holding root, else an empty string."""
    if os.environ.get("WORKFLOW_REPO"):
        return os.environ["WORKFLOW_REPO"]
    if not root or not os.path.isdir(root):
        return ""
    out = subprocess.run(["git", "-C", root, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def require_root(root):
    """Exits with status 2 unless root is a sprint folder holding leader/."""
    if not root or not os.path.isdir(os.path.join(root, "leader")):
        print("set WORKFLOW_ROOT to the project's sprint folder (it must hold leader/); got %r" % root, file=sys.stderr)
        sys.exit(2)


def require_owner_pane():
    """Exits with status 2 unless WORKFLOW_OWNER_PANE names the pane no tool may type into."""
    if not OWNER_PANE:
        print("set WORKFLOW_OWNER_PANE to the pane no tool may type into (the owner or leader pane)", file=sys.stderr)
        sys.exit(2)
