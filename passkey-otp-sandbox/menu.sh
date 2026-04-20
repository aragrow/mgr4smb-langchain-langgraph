#!/usr/bin/env bash
# otp-sandbox operations menu — mirrors mgr4smb/menu.sh but tailored
# to the sandbox surface: OTP-only authentication via GHL, read-only
# Jobber queries through the account_agent, reschedule flow via the
# reschedule / vendor_notifier / client_notifier agents, and a
# single dev client (no clients.json).
#
# The directory is still named passkey-otp-sandbox/ to preserve git
# history; the passkey code paths were removed earlier.
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
# Client + JWT management (clients.json registry)
# ---------------------------------------------------------------------------
_run_inline_py() {
    _require_venv; _require_env; _activate_venv
    python - "$@"
}

create_client() {
    read -r -p "Client name (e.g. Aragrow LLC): " name
    [[ -z "$name" ]] && { _err "Name required"; return 1; }

    read -r -p "Token expiration in days [365]: " days
    days=${days:-365}

    _run_inline_py <<PYEOF
import fcntl
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sandbox.auth import issue_token
from sandbox.config import settings

name = """$name""".strip()
days = int("""$days""".strip())
client_id = str(uuid.uuid4())

path = settings.clients_file
path.touch(exist_ok=True)

with open(path, "r+" if path.stat().st_size else "w+") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    try:
        f.seek(0)
        raw = f.read()
        data = json.loads(raw) if raw.strip() else {"clients": []}
        data.setdefault("clients", []).append({
            "client_id": client_id,
            "name": name,
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        f.seek(0)
        f.truncate()
        json.dump(data, f, indent=2)
        f.write("\n")
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)

path.chmod(0o600)
token = issue_token(client_id, expires_in_days=days)
print()
print(f"  Client ID: {client_id}")
print(f"  Name:      {name}")
print(f"  Expires:   {days} days")
print()
print("  JWT token (save it now — cannot be retrieved later):")
print(f"  {token}")
print()
PYEOF
    _ok "Client created"
}

list_clients() {
    _run_inline_py <<'PYEOF'
import json
from sandbox.config import settings

path = settings.clients_file
if not path.exists():
    print("  No clients.json yet.")
    raise SystemExit(0)

data = json.loads(path.read_text() or '{"clients": []}')
clients = data.get("clients", [])
if not clients:
    print("  No clients registered.")
    raise SystemExit(0)

print()
print(f"  {'CLIENT_ID':<40} {'NAME':<25} ENABLED  CREATED")
print(f"  {'-'*40} {'-'*25} {'-'*7}  {'-'*25}")
for c in clients:
    cid = c.get("client_id", "")
    name = c.get("name", "")[:24]
    enabled = "yes" if c.get("enabled") else "no"
    created = c.get("created_at", "")[:19]
    print(f"  {cid:<40} {name:<25} {enabled:<7}  {created}")
print()
PYEOF
}

reissue_jwt() {
    list_clients
    read -r -p "Client ID to reissue: " cid
    [[ -z "$cid" ]] && { _err "Client ID required"; return 1; }

    read -r -p "Token expiration in days [365]: " days
    days=${days:-365}

    _run_inline_py <<PYEOF
import json
from sandbox.auth import issue_token
from sandbox.config import settings

cid = """$cid""".strip()
days = int("""$days""".strip())

data = json.loads(settings.clients_file.read_text() or '{"clients": []}')
client = next((c for c in data.get("clients", []) if c.get("client_id") == cid), None)
if not client:
    raise SystemExit(f"Client {cid} not found.")
if not client.get("enabled"):
    raise SystemExit(f"Client {cid} is disabled. Re-enable first.")

token = issue_token(cid, expires_in_days=days)
print()
print(f"  Client: {client.get('name')} ({cid})")
print(f"  New JWT (save it now — cannot be retrieved later):")
print(f"  {token}")
print()
print("  Note: the previous token remains valid until its own expiry.")
print("  To invalidate it immediately, revoke this client.")
print()
PYEOF
    _ok "JWT reissued"
}

revoke_client() {
    list_clients
    read -r -p "Client ID to disable: " cid
    [[ -z "$cid" ]] && { _err "Client ID required"; return 1; }

    _run_inline_py <<PYEOF
import fcntl
import json
from sandbox.config import settings

cid = """$cid""".strip()
path = settings.clients_file

with open(path, "r+") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    try:
        f.seek(0)
        data = json.loads(f.read() or '{"clients": []}')
        found = False
        for c in data.get("clients", []):
            if c.get("client_id") == cid:
                c["enabled"] = False
                found = True
                break
        if not found:
            raise SystemExit(f"Client {cid} not found.")
        f.seek(0)
        f.truncate()
        json.dump(data, f, indent=2)
        f.write("\n")
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)

print(f"  Client {cid} disabled. Existing tokens will be rejected on next request.")
PYEOF
    _ok "Client revoked"
}

# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
show_menu() {
    cat <<'EOF'

══════════════════════════════════════════════════════════════
              otp-sandbox — Operations Menu
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

┌─ CLIENTS & JWTS  (clients.json registry) ────────────────────
│    9) Create new client + JWT
│   10) List clients
│   11) Reissue JWT for existing client
│   12) Revoke client (disable)
└──────────────────────────────────────────────────────────────

   13) Exit
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
            1)  start_server        || true; _pause ;;
            2)  stop_server         || true; _pause ;;
            3)  restart_server      || true; _pause ;;
            4)  status_server       || true; _pause ;;
            5)  health_check        || true; _pause ;;
            6)  tail_logs           || true ;;  # tail -f already waits for Ctrl-C
            7)  smoke_all           || true; _pause ;;
            8)  smoke_phase         || true; _pause ;;
            9)  create_client       || true; _pause ;;
            10) list_clients        || true; _pause ;;
            11) reissue_jwt         || true; _pause ;;
            12) revoke_client       || true; _pause ;;
            13) _info "Bye."; exit 0 ;;
            *)  _warn "Invalid choice: $choice"; _pause ;;
        esac
    done
}

main "$@"
