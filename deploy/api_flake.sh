#!/usr/bin/env bash
KEY=~/.ssh/csl559_stu24
REMOTE='for n in 1 2 3; do
for u in "https://api.opentopodata.org/v1/srtm90m?locations=21.2,81.3" "https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR&community=AG&longitude=81.3&latitude=21.2&start=20240101&end=20240107&format=JSON" "https://archive-api.open-meteo.com/v1/archive?latitude=21.2&longitude=81.3&start_date=2024-01-01&end_date=2024-01-07&daily=precipitation_sum" "https://api.open-elevation.com/api/v1/lookup?locations=21.2,81.3"; do
echo "$(echo $u | cut -d/ -f3) $(curl -s -m 8 -o /dev/null -w "%{http_code} %{time_total}s" "$u")"
done; done'
for n in 1 2 3 4; do
  (
    port=$((2292 + n))
    for i in 1 2 3 4 5; do
      out=$(ssh -n -i "$KEY" -p "$port" -o ConnectTimeout=8 -o BatchMode=yes -o ServerAliveInterval=15 student@10.1.75.51 "$REMOTE" 2>&1)
      rc=$?
      [ $rc -ne 255 ] && break
      sleep 2
    done
    echo "=== sys$n (ssh rc=$rc)"; echo "$out"
  ) > /tmp/flake_$n.txt &
done
wait
cat /tmp/flake_1.txt /tmp/flake_2.txt /tmp/flake_3.txt /tmp/flake_4.txt