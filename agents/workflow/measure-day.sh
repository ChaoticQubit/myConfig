#!/bin/bash
exec python3 -I -B "$(dirname "$0")/measure_day.py" "$@"
