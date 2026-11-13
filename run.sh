#!/bin/sh
# Run PDF Studio on Linux or macOS:  ./run.sh   (extra options go to the server, e.g. --port 9000)
cd "$(dirname "$0")" || exit 1
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    exec "$candidate" run.py "$@"
  fi
done
echo "PDF Studio needs Python 3.11 or newer. Install it from https://www.python.org/downloads/" >&2
echo "(macOS: brew install python; Debian/Ubuntu: sudo apt install python3 python3-venv)" >&2
exit 1
