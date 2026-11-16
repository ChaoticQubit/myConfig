#!/bin/bash
exec python3 -I -B "$(dirname "$0")/dispatch.py" "$@"
