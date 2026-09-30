#!/usr/bin/env bash
# Proof Flower: one-command local run. Usage: ./run.sh   (or ./run.sh docker)
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" = "docker" ]; then
  echo "Building image..."
  docker build -t proof-flower:1.0 .
  echo "Starting proof-flower:1.0 on http://localhost:8000 ..."
  docker run --rm -p 8000:8000 --env-file .env proof-flower:1.0
  exit 0
fi
command -v python3 >/dev/null || { echo 'Python 3 not found. Install it from python.org.' >&2; exit 1; }
[ -f .env ] || { cp .env.example .env; echo "Created .env (add GEMINI_API_KEY for live mode; demo works without it)."; }
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -q -r requirements.txt
( sleep 4; echo; echo "Health check:"; curl -s "http://127.0.0.1:${PORT:-8000}/api/evals?business_id=casa_coqui" | head -c 300; echo; echo "Open http://127.0.0.1:${PORT:-8000}" ) &
exec python3 -m uvicorn app:app --host 127.0.0.1 --port "${PORT:-8000}"
