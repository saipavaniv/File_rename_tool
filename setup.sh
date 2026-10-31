#!/usr/bin/env bash
# One-time setup on Linux (Ubuntu/Debian). Run as the service user, not root.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
python scripts/make_cert.py "$(hostname -f)"
python -m app.cli create-admin --username admin
chmod 600 .env
echo "Done. Start with: . .venv/bin/activate && python run.py"
