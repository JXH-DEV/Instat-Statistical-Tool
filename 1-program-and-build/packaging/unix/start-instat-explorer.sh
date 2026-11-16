#!/bin/sh
# Start INSTAT Explorer (macOS and Linux). The first start sets everything up (needs the internet, a few minutes).
cd "$(dirname "$0")" || exit 1
HERE=$(pwd)
VENV="$HERE/.venv"
WANT=$(cat VERSION 2>/dev/null | tr -d '\r')
HAVE=$(cat "$VENV/installed.txt" 2>/dev/null)

fail() {
  echo
  echo "The set-up did not finish. Check the internet connection and run this file again."
  rm -rf "$VENV"
  printf "Press Enter to close. "; read -r _
  exit 1
}

if [ "$HAVE" != "$WANT" ] || [ ! -x "$VENV/bin/python" ]; then
  PY=""
  for c in python3.14 python3.13 python3.12 python3.11 python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import struct, sys; sys.exit(0 if sys.version_info >= (3, 11) and struct.calcsize("P") == 8 else 1)' 2>/dev/null; then PY=$c; break; fi
  done
  if [ -z "$PY" ]; then
    echo "INSTAT Explorer needs 64-bit Python 3.11 or newer, and it was not found."
    echo "Install it from https://www.python.org/downloads/ (macOS) or with your package manager (Linux), then run this file again."
    echo "Python 3.11 ose me i ri (64-bit) nuk u gjet. Instalojeni dhe provojeni perseri."
    printf "Press Enter to close. "; read -r _
    exit 1
  fi
  echo
  echo "First start of this version: INSTAT Explorer is being set up. This happens only once."
  rm -rf "$VENV"
  "$PY" -m venv "$VENV" || fail
  if [ -d "$HERE/wheelhouse" ]; then
    "$VENV/bin/python" -m pip install --disable-pip-version-check --no-index --find-links "$HERE/wheelhouse" --find-links "$HERE/wheel" "instat-explorer==$WANT" || fail
  else
    "$VENV/bin/python" -m pip install --disable-pip-version-check --find-links "$HERE/wheel" "instat-explorer==$WANT" || fail
  fi
  echo "$WANT" > "$VENV/installed.txt"
fi

# Downloaded files and exports stay in the "data" folder next to this file.
INSTAT_DATA_DIR="$HERE/data" exec "$VENV/bin/python" -m instatkit serve
