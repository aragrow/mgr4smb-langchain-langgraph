#!/usr/bin/env bash
# mgr4smb operations menu — start/stop/restart server + manage clients/JWTs
#
# Usage: ./menu.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE=".mgr4smb.pid"
LOG_FILE="logs/server.log"
VENV="$SCRIPT_DIR/.venv"
CLIENTS_FILE="clients.json"
HOST="${MGR4SMB_HOST:-0.0.0.0}"
PORT="${MGR4SMB_PORT:-8000}"

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

    mkdir -p logs
    _info "Starting uvicorn on ${HOST}:${PORT}…"

    # shellcheck disable=SC1091
    source "$VENV/bin/activate"

    nohup "$VENV/bin/uvicorn" mgr4smb.api:app \
        --host "$HOST" --port "$PORT" \
        >> "$LOG_FILE" 2>&1 &

    local pid=$!
    echo "$pid" > "$PID_FILE"
    sleep 2

    if _is_running; then
        _ok "Server started (PID $pid, log: $LOG_FILE)"
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

    local pid
    pid=$(cat "$PID_FILE")
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

restart_server() {
    stop_server || true
    start_server
}

status_server() {
    if _is_running; then
        local pid
        pid=$(cat "$PID_FILE")
        local uptime
        uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ' || echo 'unknown')
        _ok "Server running (PID $pid, uptime $uptime, port $PORT)"
        _info "Health check: curl -sS http://localhost:${PORT}/health"
    else
        _warn "Server not running"
    fi
}

# ---------------------------------------------------------------------------
# Client + JWT management (uses Python helpers via .venv)
# ---------------------------------------------------------------------------
_run_py() {
    _require_venv
    _require_env
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
    python - "$@"
}

create_client() {
    read -r -p "Client name (e.g. Aragrow LLC): " name
    [[ -z "$name" ]] && { _err "Name required"; return 1; }

    read -r -p "Token expiration in days [365]: " days
    days=${days:-365}

    _run_py <<PYEOF
import fcntl
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mgr4smb.auth import issue_token
from mgr4smb.config import settings

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
    _run_py <<'PYEOF'
import json
from pathlib import Path
from mgr4smb.config import settings

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

reissue_client() {
    list_clients
    read -r -p "Client ID (UUID) to reissue: " cid
    [[ -z "$cid" ]] && { _err "Client ID required"; return 1; }

    read -r -p "Token expiration in days [365]: " days
    days=${days:-365}

    _run_py <<PYEOF
import json
from mgr4smb.auth import issue_token
from mgr4smb.config import settings

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
print("  To invalidate it immediately, revoke this client (option 8).")
print()
PYEOF
    _ok "JWT reissued"
}

revoke_client() {
    list_clients
    read -r -p "Client ID (UUID) to disable: " cid
    [[ -z "$cid" ]] && { _err "Client ID required"; return 1; }

    _run_py <<PYEOF
import fcntl
import json
from pathlib import Path
from mgr4smb.config import settings

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

═══════════════════════════════════════
  mgr4smb — Operations Menu
═══════════════════════════════════════
  1) Start server
  2) Stop server
  3) Restart server
  4) Server status
  5) Create new client + JWT
  6) List clients
  7) Reissue JWT for existing client
  8) Revoke client (disable)
  9) Exit
═══════════════════════════════════════
EOF
}

main() {
    while true; do
        show_menu
        read -r -p "  Choice: " choice
        case "$choice" in
            1) start_server ;;
            2) stop_server ;;
            3) restart_server ;;
            4) status_server ;;
            5) create_client ;;
            6) list_clients ;;
            7) reissue_client ;;
            8) revoke_client ;;
            9) _info "Bye."; exit 0 ;;
            *) _warn "Invalid choice: $choice" ;;
        esac
    done
}

main "$@"
