#!/usr/bin/env bash
set -u

APP=$HOME/pond
PORT=${PORT:-3000}
WORKERS=${WORKERS:-4}
PIDFILE=$APP/uvicorn.pid
LOG=$APP/uvicorn.log

export PYTHONPATH="$APP/pydeps"
export DATA_MODE=snapshot

alive() {
  [ -f "$PIDFILE" ] || return 1
  pid=$(cat "$PIDFILE")
  kill -0 "$pid" 2>/dev/null
}

health_check() {
  python3 -c '
import sys
import time
import urllib.request

url = sys.argv[1]
last_error = None
for attempt in range(20):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            body = response.read().decode("utf-8", "replace")
            if response.status == 200 and "snapshot" in body:
                raise SystemExit(0)
            last_error = f"unexpected status {response.status}"
    except Exception as exc:
        last_error = str(exc)
    if attempt < 19:
        time.sleep(1)
raise SystemExit(1 if last_error else 1)
' "http://127.0.0.1:$PORT/health"
}

do_start() {
  if alive; then
    echo "already running"
    exit 0
  fi

  cd "$APP" || exit 1
  setsid nohup python3 -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --workers "$WORKERS" > "$LOG" 2>&1 < /dev/null &
  echo $! > "$PIDFILE"

  if health_check && alive; then
    echo "healthy"
    exit 0
  fi

  tail -n 30 "$LOG"
  exit 1
}

do_stop() {
  if alive; then
    pid=$(cat "$PIDFILE")
    kill -TERM "$pid"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      if kill -0 "$pid" 2>/dev/null; then
        sleep 1
      else
        break
      fi
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL -- "-$pid" 2>/dev/null
      kill -KILL "$pid" 2>/dev/null
    fi
  fi
  rm -f "$PIDFILE"
}

do_status() {
  if alive; then
    echo "alive"
  else
    echo "dead"
  fi
  python3 -c '
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=3) as response:
        print(f"health {response.status}")
except Exception as exc:
    print(f"health error {exc}")
' "http://127.0.0.1:$PORT/health"
}

case "${1:-}" in
  start)
    do_start
    ;;
  stop)
    do_stop
    ;;
  restart)
    do_stop
    do_start
    ;;
  status)
    do_status
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status}"
    exit 2
    ;;
esac