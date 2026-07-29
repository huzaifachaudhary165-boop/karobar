#!/usr/bin/env bash
# Karobar developer helper.
#
#   ./scripts/dev.sh setup     install backend + mobile dependencies
#   ./scripts/dev.sh seed      rebuild the demo database
#   ./scripts/dev.sh api       run the backend with reload
#   ./scripts/dev.sh app       run the Flutter app
#   ./scripts/dev.sh test      backend tests + flutter analyze + flutter test
#   ./scripts/dev.sh check     configuration report

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
MOBILE="$ROOT/mobile"
export PYTHONPATH="$BACKEND"

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }

case "${1:-check}" in
  setup)
    step 'Installing backend dependencies'
    (cd "$BACKEND" && python -m pip install -r requirements.txt)
    if [ ! -f "$BACKEND/.env" ]; then
      cp "$BACKEND/.env.example" "$BACKEND/.env"
      printf '\033[33mCreated backend/.env — add your SECRET_KEY and ANTHROPIC_API_KEY.\033[0m\n'
    fi
    step 'Installing Flutter dependencies'
    (cd "$MOBILE" && flutter pub get)
    ;;

  seed)
    step 'Rebuilding demo data'
    (cd "$BACKEND" && rm -f karobar.db && python -m app.cli seed)
    ;;

  api)
    step 'Starting the API on http://127.0.0.1:8000'
    (cd "$BACKEND" && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000)
    ;;

  app)
    step 'Starting the Flutter app'
    (cd "$MOBILE" && flutter run)
    ;;

  test)
    step 'Backend tests'
    (cd "$BACKEND" && python -m pytest -q)
    step 'Flutter analyze'
    (cd "$MOBILE" && flutter analyze)
    step 'Flutter tests'
    (cd "$MOBILE" && flutter test)
    printf '\n\033[32mAll checks passed.\033[0m\n'
    ;;

  migrate)
    step 'Applying database migrations'
    (cd "$BACKEND" && python -m alembic upgrade head)
    ;;

  reset)
    step 'Resetting the database'
    (cd "$BACKEND" && python -m app.cli reset)
    ;;

  check)
    (cd "$BACKEND" && python -m app.cli check)
    ;;

  *)
    echo "Unknown command: $1" >&2
    echo "Use one of: setup seed api app test migrate reset check" >&2
    exit 1
    ;;
esac
