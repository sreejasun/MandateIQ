#!/usr/bin/env bash
# One-command start: sets up Python and Node dependencies, builds the web
# interface, and serves everything at http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "Python 3.10+ is required."; exit 1; }
command -v npm >/dev/null || { echo "Node.js 18+ (npm) is required."; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example (mock mode). Add GROQ_API_KEY or Bedrock settings to use a real model."
fi

if [ ! -d backend/.venv ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv backend/.venv
fi
# shellcheck disable=SC1091
source backend/.venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt

echo "Building the web interface..."
(cd frontend && npm install --no-audit --no-fund --silent && npm run build --silent)

echo "MandateIQ is running at http://localhost:8000  (Ctrl+C to stop)"
cd backend
exec uvicorn api.main:app --host 127.0.0.1 --port 8000
