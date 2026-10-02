#!/usr/bin/env bash
set -u
set -o pipefail

HOST=sys4
DEPS=${DEPS:-$HOME/build/pond_pydeps}

sshr() {
  local attempt rc
  for attempt in 1 2 3 4 5; do
    ssh -o ConnectTimeout=8 "$@"
    rc=$?
    if [ "$rc" -ne 255 ]; then
      return "$rc"
    fi
    if [ "$attempt" -lt 5 ]; then
      sleep 2
    fi
  done
  return 255
}

push() {
  local remote=$1 attempt
  shift
  for attempt in 1 2 3 4 5; do
    if tar "$@" | ssh -o ConnectTimeout=8 "$HOST" "$remote"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

missing=()
for path in main.py services frontend data/rainfall_snapshot.json data/N21E081.hgt deploy/run.sh; do
  [ -e "$path" ] || missing+=("$path")
done
[ -d "$DEPS" ] || missing+=("$DEPS")

if [ "${#missing[@]}" -ne 0 ]; then
  printf 'missing: %s\n' "${missing[@]}"
  exit 1
fi

sshr "$HOST" 'rm -rf ~/pond-new ~/pond-prev; mkdir -p ~/pond-new/data'

push 'tar xzf - -C ~/pond-new' -czf - --exclude='__pycache__' main.py services frontend data/rainfall_snapshot.json data/N21E081.hgt requirements.txt || exit 1
push 'tar xzf - -C ~/pond-new' -czf - -C deploy run.sh || exit 1
push 'mkdir -p ~/pond-new/pydeps; tar xzf - -C ~/pond-new/pydeps' -czf - --exclude='__pycache__' -C "$DEPS" . || exit 1

size_line=$(sshr "$HOST" 'du -sh ~/pond-new') || exit 1
size_value=${size_line%%[[:space:]]*}
case $size_value in
  *K) size_mb=$(awk -v v="${size_value%K}" 'BEGIN { print v / 1024 }') ;;
  *M) size_mb=${size_value%M} ;;
  *G) size_mb=$(awk -v v="${size_value%G}" 'BEGIN { print v * 1024 }') ;;
  *T) size_mb=$(awk -v v="${size_value%T}" 'BEGIN { print v * 1024 * 1024 }') ;;
  *) size_mb=$size_value ;;
esac

if ! awk -v mb="$size_mb" 'BEGIN { exit !(mb <= 1200) }'; then
  echo "remote size exceeds 1200 MB: $size_line"
  exit 1
fi

ssh -o ConnectTimeout=8 "$HOST" 'bash ~/pond/run.sh stop 2>/dev/null; rm -rf ~/pond-prev; [ -d ~/pond ] && mv ~/pond ~/pond-prev; mv ~/pond-new ~/pond; bash ~/pond/run.sh start'
rc=$?
if [ "$rc" -eq 255 ]; then
  echo "SSH LOST during swap; state unknown. Check: ssh sys4 'ls ~; bash ~/pond/run.sh status'"
  exit 1
fi
if [ "$rc" -ne 0 ]; then
  sshr "$HOST" 'bash ~/pond/run.sh stop 2>/dev/null; rm -rf ~/pond-failed; mv ~/pond ~/pond-failed; if [ -d ~/pond-prev ]; then mv ~/pond-prev ~/pond && bash ~/pond/run.sh start; fi'
  echo "ROLLED BACK"
  exit 1
fi

echo "DEPLOYED"