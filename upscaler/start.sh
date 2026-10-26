#!/usr/bin/env bash
# Start (or restart) the upscaler on 127.0.0.1:12130. Safe to run from cron @reboot.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${UPSCALER_PORT:-12130}"
mkdir -p data

if [ ! -x .venv/bin/python ]; then
  # Ubuntu's python3 may lack ensurepip (python3-venv not installed): bootstrap pip ourselves
  python3 -m venv --without-pip .venv
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o data/get-pip.py
  .venv/bin/python data/get-pip.py --quiet
  .venv/bin/pip install --quiet torch --index-url "${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu128}"
  .venv/bin/pip install --quiet -r requirements.txt
fi

pkill -f "uvicorn server:app --host 127.0.0.1 --port ${PORT}" 2>/dev/null || true
nohup .venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port "${PORT}" >> data/server.log 2>&1 &
echo "upscaler started on 127.0.0.1:${PORT} (log: $(pwd)/data/server.log)"
