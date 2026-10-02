#!/usr/bin/env bash
set -euo pipefail

GATEWAY=10.1.75.51
USER_=student
KEY="$HOME/.ssh/csl559_stu24"

sys_name() {
  case "$1" in
    2296) echo sys4 ;;
    2294) echo sys2 ;;
    2295) echo sys3 ;;
    2293) echo sys1 ;;
    *) echo "sys?" ;;
  esac
}

probe_sys() {
  local port="$1"
  local label
  label="$(sys_name "$port")"
  local ssh_cmd=(ssh -n -o ConnectTimeout=8 -o BatchMode=yes -o ServerAliveInterval=15 -p "$port" -i "$KEY" "$USER_@$GATEWAY")
  local tmp
  tmp="$(mktemp)"
  local attempt rc
  for attempt in 1 2 3 4 5; do
    if "${ssh_cmd[@]}" 'set -e; printf "HOST:%s\n" "$(hostname)"; printf "GETENT:%s\n" "$(getent hosts api.opentopodata.org power.larc.nasa.gov archive-api.open-meteo.com api.open-elevation.com | tr "\n" ";" )"; printf "CURL_OPENTOPO:%s\n" "$(curl -sS -m 10 --retry 2 -o /dev/null -w "%{http_code}" https://api.opentopodata.org/v1/srtm90m/ || true)"; printf "CURL_POWER:%s\n" "$(curl -sS -m 10 --retry 2 -o /dev/null -w "%{http_code}" https://power.larc.nasa.gov/ || true)"; printf "CURL_OM:%s\n" "$(curl -sS -m 10 --retry 2 -o /dev/null -w "%{http_code}" https://archive-api.open-meteo.com/ || true)"; printf "CURL_OE:%s\n" "$(curl -sS -m 10 --retry 2 -o /dev/null -w "%{http_code}" https://api.open-elevation.com/ || true)"; printf "PROXY:%s\n" "$(env | grep -i proxy | tr "\n" ";" || true)"; printf "ETC_PROXY:%s\n" "$(grep -ri proxy /etc/environment /etc/apt/apt.conf.d 2>/dev/null | head -5 | tr "\n" ";" || true)"; printf "NPROC:%s\n" "$(nproc)"; printf "FREE:%s\n" "$(free -m | awk 'NR==2{print $2","$3","$4}')