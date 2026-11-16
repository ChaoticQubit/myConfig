#!/bin/bash
set -euo pipefail
F="${WORKFLOW_ROOT:-${ST_ROOT:-}}"
[ -n "$F" ] && [ -d "$F" ] || { echo "set WORKFLOW_ROOT to the project's sprint folder" >&2; exit 2; }
[ $# -ge 3 ] || { echo "usage: st.sh <worker> <STATE> <text>" >&2; echo "example: st.sh w-v242-h3 DONE 'ds190 fix/v242-ds190 a1b2c3d4e..f5e6d7c8b (2) INCONCLUSIVE rows written not run; DONE-01:19-ds190.md'" >&2; exit 2; }
w="$1"; state="$2"; shift 2; msg="$*"
case "$state" in DONE|DONE-REVIEW|WORKING|STARTED|ACK|IDLE|PROGRESS|PHASE|QUESTION|BLOCKED|LIMIT|CORRECTION) ;; *) echo "bad state: $state" >&2; exit 2 ;; esac
case "$w" in ""|.*|*/*) echo "bad worker: $w" >&2; exit 2 ;; esac
[ -d "$F/$w" ] || { echo "no worker folder: $w" >&2; exit 2; }
if [ "$state" = DONE ] && ! printf '%s' "$msg" | grep -qE '(^|[^A-Z])(VERIFIED|INCONCLUSIVE)([^A-Z]|$)'; then
  echo "DONE needs a verdict word: VERIFIED, NOT VERIFIED or INCONCLUSIVE, plus artifact paths (B7)" >&2; exit 4
fi
line="$(date +%H:%M) $state $msg"
[ ${#line} -le 700 ] || { echo "TOO LONG ${#line} chars: put detail in a named file and point to it" >&2; exit 3; }
f="$F/$w/status.md"
tmp=$(mktemp "$f.XXXXXX")
{ printf '%s\n' "$line"; cat "$f" 2>/dev/null || true; } > "$tmp"
mv "$tmp" "$f"
echo "$line"
