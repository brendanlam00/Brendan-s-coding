#!/usr/bin/env bash
# One-step installer for reelbot (Mac / Linux).
#   cd into this folder, then run:  bash install.sh
set -e
cd "$(dirname "$0")"

# Pick the newest Python 3.9+ available (Homebrew's if installed, else the Mac's built-in one).
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3 /usr/bin/python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.9+ not found. On a Mac run:  xcode-select --install   then rerun this script."
  exit 1
fi
echo "Using $($PY --version) ($PY)"

# Recreate the environment if it was made with a Python that's too old or is broken.
if [ -d .venv ] && ! .venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
  echo "Removing old .venv"; rm -rf .venv
fi
[ -d .venv ] || "$PY" -m venv .venv

.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e .
echo "Installed: $(.venv/bin/reelbot --help | head -1)"

if command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg: found"
else
  echo
  echo "NOTE: ffmpeg is not installed. Posting and setup work without it, but video editing needs it."
  echo "      Install it with:  brew install ffmpeg   (needs Homebrew: https://brew.sh)"
fi

cat <<'EOF'

Done. Next:
  source .venv/bin/activate
  reelbot setup
EOF
