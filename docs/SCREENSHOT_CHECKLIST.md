# Lab 8 Screenshot Checklist

All screenshots should be placed under `docs/screenshots/` with the exact filenames listed below.
Grafana is accessible at **`http://localhost:3001`** (Login: `admin` / `admin`).

---

### Figure 1: Tempo Service Search
- **Filename**: `docs/screenshots/fig1_tempo_search.png`
- **Location**: Grafana Explore (`http://localhost:3001/explore`)
- **Settings**:
  - Datasource: `tempo`
  - Query Type: `Search`
  - Service Name: `pond-catchment-backend`
- **Expected View**: Trace list displaying root spans such as `POST /analyzeArea` and `POST /analyzeContour` with varying duration bars.

---

### Figure 2: `/analyzeArea` Trace Waterfall
- **Filename**: `docs/screenshots/fig2_analyze_waterfall.png`
- **Location**: Grafana Explore (`http://localhost:3001/explore`)
- **Settings**:
  - Datasource: `tempo`
  - Query Type: `TraceQL` or direct Trace ID lookup
  - Trace ID: `bcdf3306489372a24bbfa529f5cdaae4`
- **Expected View**: Waterfall hierarchy expanding from root span `POST /analyzeArea` (481ms) -> `pond.analyze_area` -> `elevation.fetch` (426ms) -> `snapshot.sample_elevations` (424ms).

---

### Figure 3: Error Trace Details
- **Filename**: `docs/screenshots/fig3_error_trace.png`
- **Location**: Grafana Explore (`http://localhost:3001/explore`)
- **Settings**:
  - Datasource: `tempo`
  - Trace ID: `b74c56168cf141efcd76d88dacd10ed`
- **Expected View**: Span `pond.analyze_area` marked in red with error status, showing the exception event: `fastapi.exceptions.HTTPException: 422: Area 11529.9 km2 exceeds limit of 25.0 km2`.

---

### Figure 4: Grafana Dashboard - Request Rate & Latency
- **Filename**: `docs/screenshots/fig4_dashboard_rate_latency.png`
- **Location**: Dashboard view (`http://localhost:3001/d/pond-otel-dashboard/pond-catchment-otel-dashboard`)
- **Expected View**: Top row panels: "Request rate by status" showing 200, 400, and 422 lines, and "Latency p50 / p95" showing latency trends.

---

### Figure 5: Custom Business Metrics Panels
- **Filename**: `docs/screenshots/fig5_custom_metrics.png`
- **Location**: Dashboard view (`http://localhost:3001/d/pond-otel-dashboard/pond-catchment-otel-dashboard`)
- **Expected View**: Middle and bottom row panels: "Ponds found", "Runoff volume", "Terrain duration p95", and "Cache hit ratio".

---

### Figure 6: Prometheus Query Browser
- **Filename**: `docs/screenshots/fig6_prometheus_metrics.png`
- **Location**: Prometheus UI (`http://localhost:9090/graph`)
- **Settings**:
  - Expression: `sum by (status) (pond_requests_total)`
- **Expected View**: Table or graph view showing status 200 (~111 requests), status 400 (1 request), and status 422 (4 requests).

---

### Figure 7: Loki Logs with Trace IDs
- **Filename**: `docs/screenshots/fig7_loki_logs.png`
- **Location**: Grafana Explore (`http://localhost:3001/explore`)
- **Settings**:
  - Datasource: `loki`
  - Query: `{service_name="pond-catchment-backend"}`
- **Expected View**: Log line stream showing lines with correlated `otelTraceID="748358c6fe3a78180d47e3a7aeaeac0b"` and `otelSpanID="0ad3733b46d1e32d"`.

---

### Figure 8: System Infrastructure & Runtime Status
- **Filename**: `docs/screenshots/fig8_system_status.png`
- **Location**: Terminal
- **Command**:
  ```bash
  docker compose -f /tmp/pond-repo/deploy/otel/docker-compose.yml ps
  curl -s http://127.0.0.1:3000/health
  ```
- **Expected View**: Output showing all 5 docker containers in `Up` status alongside the curl response `{"status":"ok", ...}` on port 3000.
