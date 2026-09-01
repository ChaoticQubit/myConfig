"""Merge declared MCP servers into each agent's live config file.

Reads the declared server set from MCP_SERVERS_JSON, the previously declared
names from the manifest, and rewrites only the mcpServers key of each
flavor=path target so app-owned state in those files survives untouched.
"""

import json
import os
import sys
import tempfile


def load_manifest(path):
    """Return the server names written by the previous activation run."""
    if not os.path.exists(path):
        return []
    with open(path) as handle:
        return [line.strip() for line in handle if line.strip()]


def load_config(path):
    """Return the parsed config at path, or an empty dict when absent."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return {}
    with open(path) as handle:
        return json.load(handle)


def shape(flavor, entry):
    """Return the server entry rendered in the dialect the target expects."""
    rendered = {"command": entry["command"], "args": list(entry.get("args", []))}
    env = entry.get("env", {})
    if flavor == "code":
        rendered["type"] = "stdio"
        rendered["env"] = env
    elif env:
        rendered["env"] = env
    return rendered


def write_atomic(path, data):
    """Replace path with data, then assert the written file parses back."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=directory)
    with os.fdopen(handle, "w") as out:
        json.dump(data, out, indent=2)
        out.write("\n")
    os.chmod(temp, 0o600)
    os.replace(temp, path)
    with open(path) as check:
        assert json.load(check) == data, f"{path} did not round-trip after write"


def sync(flavor, path, declared, stale):
    """Apply declared and stale servers to one target, return whether it changed."""
    data = load_config(path)
    servers = data.setdefault("mcpServers", {})
    changed = False
    for name in stale:
        if servers.pop(name, None) is not None:
            changed = True
    for name, entry in declared.items():
        rendered = shape(flavor, entry)
        if servers.get(name) != rendered:
            servers[name] = rendered
            changed = True
    if changed:
        write_atomic(path, data)
    return changed


def main():
    manifest_path = sys.argv[1]
    targets = sys.argv[2:]
    declared = json.loads(os.environ["MCP_SERVERS_JSON"])
    assert targets, "mcp-sync needs at least one flavor=path target"
    stale = [name for name in load_manifest(manifest_path) if name not in declared]

    for target in targets:
        flavor, _, path = target.partition("=")
        assert flavor in ("code", "desktop"), f"unknown target flavor {flavor}"
        assert path, f"target {target} has no path"
        if flavor == "desktop" and not os.path.exists(path):
            print(f"skipping {path}: Claude Desktop has never written its config")
            continue
        if sync(flavor, path, declared, stale):
            print(f"updated mcpServers in {path}")

    with open(manifest_path, "w") as out:
        for name in declared:
            out.write(f"{name}\n")


main()
