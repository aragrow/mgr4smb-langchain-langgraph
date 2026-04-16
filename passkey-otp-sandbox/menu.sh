#!/usr/bin/env bash
# passkey-otp-sandbox operations menu — mirrors mgr4smb/menu.sh but
# tailored to the sandbox surface (no Jobber, single dev client,
# MongoDB-backed passkeys, in-memory OTP).
#
# Usage: ./menu.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE=".server.pid"
LOG_FILE="logs/server.log"
VENV="$SCRIPT_DIR/.venv"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------
_info()  { printf '\033[36m▸ %s\033[0m\n' "$*"; }
_ok()    { printf '\033[32m✓ %s\033[0m\n' "$*"; }
_warn()  { printf '\033[33m! %s\033[0m\n' "$*"; }
_err()   { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# Environment checks
# ---------------------------------------------------------------------------
_require_venv() {
    if [[ ! -f "$VENV/bin/activate" ]]; then
        _err ".venv not found at $VENV. Run: uv venv .venv && uv pip install -e ."
        exit 1
    fi
}

_require_env() {
    if [[ ! -f ".env" ]]; then
        _err ".env file not found. Copy .env.example to .env and fill in secrets."
        exit 1
    fi
}

_activate_venv() {
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
}

# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------
_is_running() {
    [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null
}

start_server() {
    _require_venv
    _require_env

    if _is_running; then
        _warn "Server already running (PID $(cat "$PID_FILE"))"
        return 0
    fi

    if [[ -f "$PID_FILE" ]]; then
        _warn "Removing stale PID file"
        rm -f "$PID_FILE"
    fi

    if command -v lsof >/dev/null 2>&1; then
        local occupant
        occupant=$(lsof -i ":$PORT" -sTCP:LISTEN -n -P 2>/dev/null | awk 'NR==2 {print $1" (PID "$2")"}')
        if [[ -n "$occupant" ]]; then
            _err "Port $PORT is already in use by: $occupant"
            _err "Either stop that process or set PORT to a different port."
            return 1
        fi
    fi

    mkdir -p logs
    _info "Starting uvicorn on ${HOST}:${PORT} in the background…"
    _activate_venv

    # </dev/null detaches stdin so the child can't grab the TTY;
    # nohup + & puts it in the background;
    # disown removes it from the shell's job table so job-control
    # messages ("[1]+ Done …") never appear when the menu loop repaints.
    nohup "$VENV/bin/uvicorn" sandbox.api:app \
        --host "$HOST" --port "$PORT" \
        </dev/null >> "$LOG_FILE" 2>&1 &

    local pid=$!
    echo "$pid" > "$PID_FILE"
    disown "$pid" 2>/dev/null || true
    sleep 2

    if _is_running; then
        _ok "Server running in background (PID $pid, log: $LOG_FILE)"
        _info "Chat UI:   http://${HOST}:${PORT}/ui"
        _info "Health:    http://${HOST}:${PORT}/health"
        _info "You can keep using the menu while the server runs."
    else
        _err "Server failed to start — check $LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_server() {
    if ! _is_running; then
        _warn "Server not running"
        rm -f "$PID_FILE"
        return 0
    fi
    local pid; pid=$(cat "$PID_FILE")
    _info "Stopping server (PID $pid)…"
    kill -TERM "$pid" 2>/dev/null || true
    for _ in {1..10}; do
        if ! kill -0 "$pid" 2>/dev/null; then break; fi
        sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
        _warn "SIGTERM timed out; sending SIGKILL"
        kill -KILL "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
    _ok "Server stopped"
}

restart_server() { stop_server || true; start_server; }

status_server() {
    if _is_running; then
        local pid; pid=$(cat "$PID_FILE")
        local uptime; uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ' || echo 'unknown')
        _ok "Server running (PID $pid, uptime $uptime, port $PORT)"
        _info "Health: curl -sS http://${HOST}:${PORT}/health"
    else
        _warn "Server not running"
        if command -v lsof >/dev/null 2>&1; then
            local occupant
            occupant=$(lsof -i ":$PORT" -sTCP:LISTEN -n -P 2>/dev/null | awk 'NR==2 {print $1" (PID "$2")"}')
            if [[ -n "$occupant" ]]; then
                _warn "Port $PORT is in use by another process: $occupant"
            fi
        fi
    fi
}

health_check() {
    if ! command -v curl >/dev/null 2>&1; then
        _err "curl not found — cannot run health check"
        return 1
    fi
    local url="http://${HOST}:${PORT}/health"
    _info "GET $url"
    local body status
    body=$(curl -sS -o /dev/stdout -w "\n__HTTP_STATUS__:%{http_code}" "$url" 2>&1) || {
        _err "Could not reach $url (is the server running?)"
        return 1
    }
    status="${body##*__HTTP_STATUS__:}"
    body="${body%__HTTP_STATUS__:*}"
    if command -v python3 >/dev/null 2>&1 && [[ -n "$body" ]]; then
        pretty=$(printf '%s' "$body" | python3 -c \
            "import json,sys; d=json.loads(sys.stdin.read()); print(json.dumps(d, indent=2))" \
            2>/dev/null) && body="$pretty"
    fi
    printf '%s\n' "$body"
    case "$status" in
        200) _ok  "Health: OK (HTTP $status)" ;;
        503) _warn "Health: DEGRADED (HTTP $status)" ;;
          *) _err  "Health: UNEXPECTED (HTTP $status)" ;;
    esac
}

tail_logs() {
    if [[ ! -f "$LOG_FILE" ]]; then
        _warn "No log file yet at $LOG_FILE"; return 0
    fi
    _info "Tailing $LOG_FILE — Ctrl-C to stop"
    tail -f "$LOG_FILE"
}

# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------
_run_py() { _require_venv; _require_env; _activate_venv; python "$@"; }

smoke_all() {
    _info "Running full smoke suite (phases 1–7)…"
    _run_py -m sandbox.checks.smoke
}

smoke_phase() {
    read -r -p "Phase number (1–7): " p
    [[ -z "$p" ]] && { _err "Phase required"; return 1; }
    _info "Running phase $p…"
    _run_py -m sandbox.checks.smoke --phase "$p"
}

# ---------------------------------------------------------------------------
# JWT (single dev client — no clients.json in the sandbox)
# ---------------------------------------------------------------------------
mint_jwt() {
    read -r -p "Token expiration in days [365]: " days
    days=${days:-365}
    _require_venv; _require_env; _activate_venv
    local token; token=$(python scripts/issue_dev_jwt.py --days "$days" 2>/dev/null)
    echo
    _info "Save this JWT — paste it into Settings → JWT token in the chat UI:"
    echo
    echo "  $token"
    echo
    _ok "JWT minted ($(echo "$token" | wc -c | tr -d ' ') chars, expires in $days days)"
}

# ---------------------------------------------------------------------------
# Passkey management (MongoDB, per user_email)
# ---------------------------------------------------------------------------
list_passkeys() {
    read -r -p "User email (blank = all users): " email
    _require_venv; _require_env; _activate_venv
    python - <<PYEOF
from sandbox.config import settings
from sandbox.webauthn import storage

email = """$email""".strip().lower()
storage.init_db()
coll = storage._coll()
query = {"user_email": email} if email else {}
rows = list(coll.find(query, sort=[("user_email", 1), ("created_at", 1)]))

if not rows:
    print("  No passkeys registered.")
    raise SystemExit(0)

print()
print(f"  ({settings.mongodb_passkey_db}.{settings.mongodb_passkey_collection})")
print(f"  {'USER_EMAIL':<35} {'CREDENTIAL_ID (trunc)':<25} {'COUNTER':<7} CREATED")
print(f"  {'-'*35} {'-'*25} {'-'*7} {'-'*25}")
for r in rows:
    cid = (r.get('credential_id') or '')[:22] + ('…' if len(r.get('credential_id') or '') > 22 else '')
    created = (r.get('created_at') or '')[:19]
    print(f"  {r.get('user_email',''):<35} {cid:<25} {str(r.get('sign_counter',0)):<7} {created}")
print()
PYEOF
}

delete_passkey() {
    list_passkeys
    read -r -p "User email: " email
    [[ -z "$email" ]] && { _err "Email required"; return 1; }
    read -r -p "Credential ID (full, base64url): " cid
    [[ -z "$cid" ]] && { _err "Credential ID required"; return 1; }
    _require_venv; _require_env; _activate_venv
    python - <<PYEOF
from sandbox.webauthn import storage
email = """$email""".strip().lower()
cid = """$cid""".strip()
removed = storage.remove(email, cid)
print(f"  Removed {removed} row(s).")
PYEOF
    _ok "Done"
}

reset_all_passkeys() {
    read -r -p "Delete ALL registered passkeys? This cannot be undone. Type 'yes' to confirm: " confirm
    [[ "$confirm" != "yes" ]] && { _warn "Cancelled"; return 0; }
    _require_venv; _require_env; _activate_venv
    python - <<'PYEOF'
from sandbox.config import settings
from sandbox.webauthn import storage
storage.init_db()
result = storage._coll().delete_many({})
print(f"  Deleted {result.deleted_count} document(s) from "
      f"{settings.mongodb_passkey_db}.{settings.mongodb_passkey_collection}.")
PYEOF
    _ok "Passkey collection wiped"
}

# ---------------------------------------------------------------------------
# OTP inspection (in-memory — only populated while the server is running
# in THIS process. Useful from the smoke tests, not for the live server
# since that runs in a separate process.)
# ---------------------------------------------------------------------------
peek_otp() {
    _require_venv; _require_env; _activate_venv
    python - <<'PYEOF'
from sandbox.tools import otp_store
store = otp_store._store  # internal dict, intentional peek
if not store:
    print("  No pending OTP codes in this process.")
    print("  (Note: live server OTP codes live in the server process —")
    print("   check logs/server.log for the printed ===== OTP banner =====.)")
else:
    print()
    for email, entry in store.items():
        print(f"  {email:<35} code={entry['code']}  expires_at={entry['expires_at']:.0f}")
    print()
PYEOF
}

# ---------------------------------------------------------------------------
# Knowledge base — local JSON ↔ MongoDB Atlas
# ---------------------------------------------------------------------------
ingest_kb_to_mongo() {
    _require_venv; _require_env; _activate_venv
    _info "Running scripts/ingest_kb_to_mongo.py"
    _info "Requires MONGODB_ATLAS_URI in .env and an Atlas Vector Search"
    _info "index on the target collection (see script output for details)."
    echo
    python scripts/ingest_kb_to_mongo.py
}

rebuild_kb_cache() {
    if [[ -f "$SCRIPT_DIR/.kb_embeddings.json" ]]; then
        rm -f "$SCRIPT_DIR/.kb_embeddings.json"
        _ok "Removed .kb_embeddings.json — next query rebuilds the cache."
    else
        _warn "No .kb_embeddings.json to remove."
    fi
    _info "Reminder: restart the server so the in-process cache clears too."
}

# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
show_menu() {
    cat <<'EOF'

══════════════════════════════════════════════════════════════
          passkey-otp-sandbox — Operations Menu
══════════════════════════════════════════════════════════════

┌─ SERVER ─────────────────────────────────────────────────────
│    1) Start server
│    2) Stop server
│    3) Restart server
│    4) Server status
│    5) Health check  (GET /health)
│    6) Tail server log (Ctrl-C to stop)
└──────────────────────────────────────────────────────────────

┌─ SMOKE TESTS ────────────────────────────────────────────────
│    7) Run full smoke suite (phases 1–7)
│    8) Run single phase
└──────────────────────────────────────────────────────────────

┌─ JWT  (single dev client — no clients.json) ─────────────────
│    9) Mint dev JWT
└──────────────────────────────────────────────────────────────

┌─ PASSKEYS  (MongoDB) ────────────────────────────────────────
│   10) List registered passkeys
│   11) Delete a passkey
│   12) Reset ALL passkeys (wipe table)
└──────────────────────────────────────────────────────────────

┌─ OTP  (in-memory — for debugging) ───────────────────────────
│   13) Peek pending OTP codes
└──────────────────────────────────────────────────────────────

┌─ KNOWLEDGE BASE  (local JSON → MongoDB Atlas) ───────────────
│   14) Ingest knowledge_base.json into MongoDB  (requires MONGODB_ATLAS_URI)
│   15) Rebuild local embeddings cache  (delete .kb_embeddings.json)
└──────────────────────────────────────────────────────────────

   16) Exit
══════════════════════════════════════════════════════════════
EOF
}

_pause() {
    # Give the user a chance to read the action's output before the menu
    # redraws on top of it. Skipped for interactive commands (tail -f) and
    # for exit.
    echo
    read -r -p "  Press Enter to return to the menu… " _ || true
}

main() {
    while true; do
        show_menu
        read -r -p "  Choice: " choice
        case "$choice" in
            1)  start_server      || true; _pause ;;
            2)  stop_server       || true; _pause ;;
            3)  restart_server    || true; _pause ;;
            4)  status_server     || true; _pause ;;
            5)  health_check      || true; _pause ;;
            6)  tail_logs         || true ;;  # tail -f already waits for Ctrl-C
            7)  smoke_all         || true; _pause ;;
            8)  smoke_phase       || true; _pause ;;
            9)  mint_jwt          || true; _pause ;;
            10) list_passkeys     || true; _pause ;;
            11) delete_passkey    || true; _pause ;;
            12) reset_all_passkeys || true; _pause ;;
            13) peek_otp             || true; _pause ;;
            14) ingest_kb_to_mongo   || true; _pause ;;
            15) rebuild_kb_cache     || true; _pause ;;
            16) _info "Bye."; exit 0 ;;
            *)  _warn "Invalid choice: $choice"; _pause ;;
        esac
    done
}

main "$@"
