#!/usr/bin/env bash
# run.sh — lifecycle helper for the passkey-otp sandbox.
#   ./run.sh start | stop | restart | status | smoke
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# --- colours -----------------------------------------------------------------
if [[ -t 1 ]]; then
    R='\033[31m'; G='\033[32m'; Y='\033[33m'; B='\033[34m'; D='\033[2m'; N='\033[0m'
else
    R=''; G=''; Y=''; B=''; D=''; N=''
fi
info()  { printf "${B}[sandbox]${N} %s\n" "$*"; }
ok()    { printf "${G}[ ok ]${N} %s\n" "$*"; }
warn()  { printf "${Y}[warn]${N} %s\n" "$*"; }
err()   { printf "${R}[fail]${N} %s\n" "$*" >&2; }

PID_FILE="$ROOT/.server.pid"
LOG_FILE="$ROOT/logs/server.log"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

# --- venv --------------------------------------------------------------------
# Always activate the sandbox's own .venv — even if a different venv is
# already active in the parent shell. The sandbox pins its own deps and
# must not borrow packages from the parent mgr4smb project.
if [[ -d "$ROOT/.venv" ]]; then
    # shellcheck disable=SC1091
    source "$ROOT/.venv/bin/activate"
fi

_load_env() {
    if [[ -f "$ROOT/.env" ]]; then
        set -a
        # shellcheck disable=SC1090
        source "$ROOT/.env"
        set +a
    fi
}

cmd_status() {
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        ok "server running (pid $(cat "$PID_FILE"))"
        return 0
    fi
    warn "server not running"
    return 1
}

cmd_start() {
    if cmd_status 2>/dev/null; then
        warn "already running — use restart"
        return 0
    fi
    _load_env
    mkdir -p "$ROOT/logs"
    info "starting uvicorn on $HOST:$PORT (log: $LOG_FILE)"
    nohup python -m uvicorn sandbox.api:app --host "$HOST" --port "$PORT" \
        >>"$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        ok "started (pid $(cat "$PID_FILE"))"
    else
        err "server failed to start — see $LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

cmd_stop() {
    if [[ ! -f "$PID_FILE" ]]; then
        warn "no pid file"
        return 0
    fi
    local pid; pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
        info "stopping pid $pid"
        kill "$pid" || true
        sleep 1
        kill -0 "$pid" 2>/dev/null && kill -9 "$pid" || true
    fi
    rm -f "$PID_FILE"
    ok "stopped"
}

cmd_restart() { cmd_stop || true; cmd_start; }

cmd_smoke() {
    _load_env
    local phase="${1:-}"
    if [[ -n "$phase" ]]; then
        python -m sandbox.checks.smoke --phase "$phase"
    else
        python -m sandbox.checks.smoke
    fi
}

case "${1:-status}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    smoke)   shift; cmd_smoke "${1:-}" ;;
    *) echo "usage: $0 {start|stop|restart|status|smoke [phase]}" >&2; exit 2 ;;
esac
