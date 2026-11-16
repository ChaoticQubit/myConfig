#!/bin/bash
set -uo pipefail
[ $# -eq 2 ] || { echo "usage: review-facts.sh <repo> <base..head>" >&2; echo "example: review-facts.sh . origin/main..fix/x" >&2; exit 2; }
cd "$1" || exit 2
range="$2"; tip="${range#*..}"
sigs() { git diff -U0 "$range" -- '*.rs' | awk -v s="$1" '/^\+\+\+ b\//{f=substr($0,7)} substr($0,1,1)==s && $0 ~ /^.[[:space:]]*(pub(\([^)]*\))?[[:space:]]+)?(async[[:space:]]+)?fn[[:space:]]/{n=$0; sub(/.*fn[[:space:]]+/,"",n); sub(/[^A-Za-z0-9_].*/,"",n); p=($0 ~ /^.[[:space:]]*pub[[:space:](]/)?"pub":"private"; print f" "n" "p}' | sort -u; }
echo "## fn signatures changed in $range, with call sites at $tip"
join -j1 <(sigs '-' | awk '{print $1":"$2, $3}' | sort) <(sigs '+' | awk '{print $1":"$2}' | sort) | while read -r key vis; do
  file="${key%%:*}"; f="${key##*:}"
  echo "### $f ($vis, $file)"
  if [ "$vis" = pub ]; then scope=('*.rs'); else scope=("$file" "${file%.rs}/"); fi
  git grep -n -E "(^|[^A-Za-z0-9_])$f\(" "$tip" -- "${scope[@]}" | grep -v -E "fn[[:space:]]+$f\b" | cut -c1-180
done
echo "## new tables"
git diff -U0 "$range" -- '*.rs' '*.sql' | grep -o -E '^\+.*CREATE TABLE( IF NOT EXISTS)? [A-Za-z0-9_]+' | awk '{print $NF}' | sort -u
echo "## include targets missing from $tip"
git diff -U0 "$range" -- '*.rs' | awk '/^\+\+\+ b\//{f=substr($0,7)} /^\+.*include_(str|bytes)!\("/{match($0,/include_(str|bytes)!\("[^"]+"/); p=substr($0,RSTART,RLENGTH); sub(/.*\("/,"",p); sub(/"$/,"",p); print f" "p}' | while read -r src rel; do
  t=$(python3 -I -c 'import os,sys;print(os.path.normpath(os.path.join(os.path.dirname(sys.argv[1]),sys.argv[2])))' "$src" "$rel")
  git cat-file -e "$tip:$t" 2>/dev/null || echo "MISSING $t from $src"
done
