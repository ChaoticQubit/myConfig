#!/bin/bash
exec python3 -I -B "$(dirname "$0")/int_gate.py" "$@"
