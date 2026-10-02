#!/usr/bin/env bash
KEY=~/.ssh/csl559_stu24
REMOTE='echo ip=$(hostname -I | cut -d" " -f1); echo nproc=$(nproc) arch=$(uname -m); free -m | sed -n 2p; for h in api.opentopodata.org power.larc.nasa.gov archive-api.open-meteo.com api.open-elevation.com; do echo "$h dns=$(getent hosts $h | cut -d" " -f1 | head -1) http=$(curl -s -m 10 -o /dev/null -w "%{http_code}" https://$h/ 2>/dev/null)"; done; env | grep -i proxy; crontab -l >/dev/null 2>&1 && echo cron=yes || echo cron=no'
for n in 4 2 3 1; do
  port=$((2292 + n))
  echo "=== sys$n (port $port)"
  for i in 1 2 3 4 5; do
    ssh -n -i "$KEY" -p "$port" -o ConnectTimeout=8 -o BatchMode=yes -o ServerAliveInterval=15 student@10.1.75.51 "$REMOTE"
    rc=$?
    [ $rc -ne 255 ] && break
    echo "attempt $i failed"; sleep 2
  done
done