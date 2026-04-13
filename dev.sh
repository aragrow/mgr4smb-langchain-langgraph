#!/usr/bin/env bash
# mgr4smb developer menu — one-time Jobber OAuth bootstrap.
#
# This menu covers ONLY the two scripts that complete Jobber authentication.
# Server lifecycle (start/stop/restart) and production client/JWT management
# live in menu.sh.
#
# Usage: ./dev.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv"

# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------
_info()  { printf '\033[36m▸ %s\033[0m\n' "$*"; }
_ok()    { printf '\033[32m✓ %s\033[0m\n' "$*"; }
_warn()  { printf '\033[33m! %s\033[0m\n' "$*"; }
_err()   { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; }

_require_venv() {
    if [[ ! -f "$VENV/bin/activate" ]]; then
        _err ".venv not found at $VENV."
        _err "Create it with:  uv venv .venv && uv pip install -e ."
        exit 1
    fi
}

_require_env() {
    if [[ ! -f ".env" ]]; then
        _err ".env file not found. Copy .env.example to .env and fill in secrets."
        exit 1
    fi
}

_run_script() {
    _require_venv
    _require_env
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
    python "$@"
}

# ---------------------------------------------------------------------------
# Jobber OAuth bootstrap — the two auth scripts
# ---------------------------------------------------------------------------
authorize_jobber() {
    _info "Launching scripts/authorize_jobber.py"
    _info "This opens the Jobber authorize URL in your default browser."
    _info "After you grant access the browser will redirect to"
    _info "http://localhost:8765/callback?code=…  — copy the whole URL"
    _info "or just the code= value for the next step."
    echo
    _run_script scripts/authorize_jobber.py
}

bootstrap_jobber() {
    _info "Launching scripts/bootstrap_jobber_tokens.py"
    _info "Paste the code (or full redirect URL) when prompted."
    _info "On success .tokens.json is written with mode 0600."
    echo
    _run_script scripts/bootstrap_jobber_tokens.py
}

# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
show_menu() {
    cat <<'EOF'

═══════════════════════════════════════
  mgr4smb — Jobber OAuth Bootstrap
═══════════════════════════════════════
  1) Authorize Jobber   (open authorize URL in browser)
  2) Bootstrap tokens   (paste code, write .tokens.json)
  3) Exit

  Typical flow:  run 1, grant access in the browser,
                 then run 2 and paste the redirect URL.
═══════════════════════════════════════
EOF
}

main() {
    while true; do
        show_menu
        read -r -p "  Choice: " choice
        case "$choice" in
            1) authorize_jobber ;;
            2) bootstrap_jobber ;;
            3) _info "Bye."; exit 0 ;;
            *) _warn "Invalid choice: $choice" ;;
        esac
    done
}

main "$@"
