# Pond Catchment Planner

Web app for siting a village pond. Select an area on a map. The backend suggests candidate pond sites, delineates each site's catchment, and estimates annual runoff volume. The frontend overlays sites, catchments and volumes on the map.

Name: Kinshuk Gupta, ID: 12341190

## Submission status

- Submitted after the Sep 28 deadline. No extension was granted.
- Deployed on one allotted system (sys4) only: a single FastAPI service run as `uvicorn --workers 4` on port 3000. There is no load balancer and no multi-system deployment.
- Front-end URL: http://10.1.75.51:3296/ (institute gateway). Likely reachable only from the campus network or VPN. See `docs/PUBLIC_ACCESS.md`.
- Demo video: [YOUTUBE URL]

## What it does

- Map area selection (Leaflet, rectangle draw).
- Suggested pond locations (top 3 candidates per area).
- Catchment area and annual water volume per candidate, overlaid on the map.
- Stress and system-limit handling: input validation, caching, backpressure, metrics. Measured limits are below.

## Layout

```
main.py                        FastAPI app: routes, validation, cache, backpressure, metrics
services/elevation_client.py   elevation grid (local SRTM tile in snapshot mode, live APIs in live mode)
services/rainfall_engine.py    rainfall and runoff volume
services/hydrology_engine.py   candidate sites and catchments
services/kml_parser.py         Phase 2 KML input
services/snapshot.py           snapshot data loading and coverage check
frontend/index.html            Leaflet UI, served by the same app (single origin)
deploy/                        deploy.sh, run.sh, stress.py, smoke_test.py, probe scripts
docs/                          stress_results.txt, api_flake.txt, PUBLIC_ACCESS.md
data/                          N21E081.hgt (not in git), rainfall_snapshot.json
```

## Setup

Python 3.12.

```
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
mkdir -p data
curl -L -o data/N21E081.hgt.gz https://elevation-tiles-prod.s3.amazonaws.com/skadi/N21/N21E081.hgt.gz
gunzip data/N21E081.hgt.gz
ls -l data/N21E081.hgt
```

The last command should show 25934402 bytes (SRTM1, 3601x3601, about 30 m). The tile is gitignored.

`data/rainfall_snapshot.json` must also be present. [CONFIRM it is committed. If not, regenerate it with `deploy/prefetch_snapshot.py`, which needs outbound access to Open-Meteo.]

## Run

```
DATA_MODE=snapshot uvicorn main:app --host 0.0.0.0 --port 3000 --workers 4
```

Open http://localhost:3000/.

On sys4 the app is managed with `deploy/run.sh` (start, stop, restart, status). `deploy/deploy.sh` ships the code over tar and ssh and swaps `~/pond` with `~/pond-prev`. Both scripts assume the author's ssh alias `sys4`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| DATA_MODE | none set here [CONFIRM default] | `live`, `snapshot` or `auto` |
| MAX_AREA_KM2 | 25 | largest accepted selection |
| MAX_INFLIGHT | 8 | concurrent analyses per worker process; above this the app returns 503 with Retry-After |

In snapshot mode, boxes outside lon 81 to 82 and lat 21 to 22 return 422.

## API

- `GET /health`: status, version, uptime, worker pid, cache size, data mode.
- `GET /metrics`: request, error, cache and latency counters for the worker that answers. Counters are per process, so repeated calls can come from different workers.
- `POST /analyzeArea` with `{"min_lat":21.16,"max_lat":21.17,"min_lon":81.30,"max_lon":81.31}`. The response carries the `X-Cache` header: MISS, HIT or DEDUP (an identical request already in flight).

Observed for the box above: 3 candidate sites, rainfall 1543.6 mm/yr, runoff 227.3 mm, site #1 volume 6,018 m3/yr. The three sites are 100 to 170 m apart with catchments of about 2.6 ha, so they probably overlap. Do not add their volumes.

## Data and method

- Elevation: SRTM1 tile N21E081 from AWS Terrain Tiles.
- Rainfall: 25 Open-Meteo cells at 0.25 degree spacing, 2021-10-02 to 2026-10-02, nearest cell used. This is reanalysis-derived data, not gauge data.
- Runoff: SCS Curve Number, default CN 82. [CONFIRM against rainfall_engine.py]
- Sites and catchments: DEM-based sink detection and catchment delineation. [CONFIRM against hydrology_engine.py]
- Live mode (OpenTopoData, NASA POWER, Open-Meteo) exists but was unreliable from the deployment host, which is why the deployment runs in snapshot mode.

## Measured results

Source files: `docs/stress_results.txt`, `docs/api_flake.txt`. Every number below comes from one run. There were no repetitions.

Test conditions for the stress run: client and server on the same host (sys4), loopback to port 3000, 4 workers, 30 s client timeout.

| Scenario | Concurrency | Result |
|---|---|---|
| GET /health, 200 requests | 1 | 200/200 OK, 186.9 req/s, p50 3.9 ms, p95 15.3 ms |
| | 8 | 200/200 OK, 144.7 req/s, p50 71.5 ms, p95 97.1 ms |
| | 32 | 200/200 OK, 124.7 req/s, p50 183.7 ms, p95 380.7 ms |
| | 64 | 200/200 OK, 124.8 req/s, p50 118.5 ms, p95 401.6 ms |
| POST /analyzeArea, same box, 100 requests | 8 | 92 OK (84 HIT, 8 DEDUP), 8 client timeouts at 30 s, 96.6 s wall |
| POST /analyzeArea, 60 distinct boxes | 1 | 60 OK (59 MISS, 1 HIT), p50 301.5 ms, p95 786.6 ms, max 10.3 s |
| | 8 | 58 OK, 2 dropped connections |
| | 16 | 10 OK, 50 returned 503 |
| | 40 | 14 OK, 8 returned 503, 38 dropped connections |

Notes on the table:
- The same 60 boxes are reused at every concurrency level, so the cache was warm for levels after the first. Only concurrency 1 is a cold-cache result.
- Because the client shares the host with the server, the /health throughput is a lower bound for the server.
- Cold analysis on an idle sys4, three distinct 1.2 km2 boxes, sequential: 0.62 s, 3.64 s, 0.24 s.
- Earlier single samples: live mode cold 12.1 s and cached 2 ms. Snapshot mode in-process: cold 87 ms and HIT 2 ms.

Live API reliability (HTTP 200 count out of 3 probes per system):

| System | OpenTopoData | NASA POWER | Open-Meteo |
|---|---|---|---|
| sys1 | 2 | 1 | 1 |
| sys2 | 2 | 2 | 2 |
| sys3 | 1 | 2 | 1 |
| sys4 | 0 | 2 | 1 |

Open-Elevation never returned 200.

## Known limits

- Cache, in-flight dedupe, MAX_INFLIGHT and /metrics are per worker process. With 4 workers the nominal backpressure limit is about 32 and cache hits depend on which worker serves the request.
- Worker processes died during the stress run and uvicorn started replacements (`Child process died` in `uvicorn.log`). Requests in flight on a dead worker were dropped. The cgroup visible from the ssh session reports a 512 MiB memory limit and 5 OOM kills. The cause of the worker deaths is not confirmed. The memory limit is the leading suspect.
- One host, one parent process. A host or parent failure takes the service down. No kill-worker or failover test was run, and no failover is claimed.
- Snapshot coverage is one 1 degree by 1 degree tile.
- Not measured: snapshot elevation against live OpenTopoData, rainfall against gauge normals, hydrology_engine behaviour under sustained load, cache behaviour under concurrency, sys4 disk headroom (quota 1.5 GB, about 280 MB uploaded).

## Tests

```
python deploy/smoke_test.py
python deploy/stress.py http://127.0.0.1:3000
```

[CONFIRM smoke_test.py takes no required arguments.]

## Data attribution

SRTM elevation via AWS Terrain Tiles. Rainfall from Open-Meteo. NASA POWER is used in live mode only.
