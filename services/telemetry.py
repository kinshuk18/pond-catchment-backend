import logging
import os
import socket

_LOGGER = logging.getLogger(__name__)

try:
    from opentelemetry import metrics, trace
    # from opentelemetry.exporter.otlp.proto.http.log_exporter import OTLPLogExporter  # not in 1.26.0
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except ImportError:
    _LOGGER.warning("OTEL imports failed; telemetry disabled", exc_info=True)
    metrics = None
    trace = None
    OTLPLogExporter = None
    OTLPMetricExporter = None
    OTLPSpanExporter = None
    FastAPIInstrumentor = None
    HTTPXClientInstrumentor = None
    LoggingInstrumentor = None
    LoggerProvider = None
    LoggingHandler = None
    BatchLogRecordProcessor = None
    MeterProvider = None
    PeriodicExportingMetricReader = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None


def _enabled() -> bool:
    value = os.getenv("OTEL_ENABLED", "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _payload_endpoint(base_url: str, suffix: str) -> str:
    return base_url.rstrip("/") + suffix


def get_tracer(name: str = "pond-catchment-backend"):
    if trace is not None:
        return trace.get_tracer(name)
    from main import _NoopTracer
    return _NoopTracer()


def record_span_error(span, exc: Exception, status_code: int = None):
    if span is None or trace is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode
        if status_code:
            span.set_attribute("http.status_code", status_code)
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
    except Exception:
        pass


def init_telemetry(app):
    if not _enabled() or metrics is None or trace is None:
        return None, {}, lambda: None

    try:
        base_url = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT",
                             "http://localhost:4318")
        resource = Resource.create({
            "service.name": os.getenv("OTEL_SERVICE_NAME", "pond-catchment-backend"),
            "service.version": "1.1",
            "service.instance.id": f"{socket.gethostname()}-{os.getpid()}",
            # "deployment.environment": "sys4",
            "deployment.environment": os.getenv("DEPLOY_ENV", "local"),
            "pond.data_mode": os.getenv("DATA_MODE", "snapshot"),
        })

        trace_provider = TracerProvider(resource=resource)
        span_exporter = OTLPSpanExporter(
            endpoint=_payload_endpoint(base_url, "/v1/traces"), timeout=3
        )
        span_processor = BatchSpanProcessor(span_exporter)
        trace_provider.add_span_processor(span_processor)
        trace.set_tracer_provider(trace_provider)

        # meter = metrics.get_meter(
        #     "pond-catchment-backend",
        #     version="1.1",
        #     instrumenting_library_version="1.1",
        # )
        metric_exporter = OTLPMetricExporter(
            endpoint=_payload_endpoint(base_url, "/v1/metrics"), timeout=3
        )
        metric_reader = PeriodicExportingMetricReader(
            metric_exporter,
            export_interval_millis=int(
                os.getenv("OTEL_METRIC_EXPORT_INTERVAL", "5000")),
        )
        # meter_provider = MeterProvider(
        #     resource=resource, metric_readers=[metric_reader])
        _latency_buckets = [0.01, 0.025, 0.05,
                            0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[metric_reader],
            views=[
                View(instrument_name="pond_request_duration_seconds",
                     aggregation=ExplicitBucketHistogramAggregation(_latency_buckets)),
                View(instrument_name="pond_terrain_duration_seconds",
                     aggregation=ExplicitBucketHistogramAggregation(_latency_buckets)),
            ],
        )
        metrics.set_meter_provider(meter_provider)
        meter = meter_provider.get_meter("pond-catchment-backend", "1.1")

        logger_provider = LoggerProvider(resource=resource)
        log_exporter = OTLPLogExporter(
            endpoint=_payload_endpoint(base_url, "/v1/logs"), timeout=3
        )
        log_processor = BatchLogRecordProcessor(log_exporter)
        logger_provider.add_log_record_processor(log_processor)
        root_logger = logging.getLogger()
        otel_handler = LoggingHandler(
            level=logging.INFO, logger_provider=logger_provider)
        otel_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s trace_id=%(otelTraceID)s span_id=%(otelSpanID)s %(message)s"
            )
        )
        root_logger.addHandler(otel_handler)
        root_logger.setLevel(logging.INFO)
        if LoggingInstrumentor is not None:
            LoggingInstrumentor().instrument(set_logging_format=True, log_level=logging.INFO)

        if FastAPIInstrumentor is not None:
            FastAPIInstrumentor.instrument_app(
                app, excluded_urls="health,metrics")
        if HTTPXClientInstrumentor is not None:
            HTTPXClientInstrumentor().instrument()

        tracer = trace.get_tracer("pond-catchment-backend")
        instruments = {
            "requests_total": meter.create_counter(
                "pond_requests_total",
                unit="1",
                description="Total requests by endpoint, status, and cache state.",
            ),
            "request_duration_seconds": meter.create_histogram(
                "pond_request_duration_seconds",
                unit="s",
                description="Request latency in seconds.",
                # explicit_bucket_boundaries_advisory=[
                #     0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],  # needs API >= 1.30
            ),
            "cache_events_total": meter.create_counter(
                "pond_cache_events_total",
                unit="1",
                description="Cache hit/miss/dedup counts.",
            ),
            "backpressure_rejections_total": meter.create_counter(
                "pond_backpressure_rejections_total",
                unit="1",
                description="Backpressure rejections.",
            ),
            "upstream_errors_total": meter.create_counter(
                "pond_upstream_errors_total",
                unit="1",
                description="Upstream dependency errors by source.",
            ),
            "inflight_requests": meter.create_up_down_counter(
                "pond_inflight_requests",
                unit="1",
                description="Current in-flight analyze requests.",
            ),
            "terrain_duration_seconds": meter.create_histogram(
                "pond_terrain_duration_seconds",
                unit="s",
                description="Terrain analysis runtime.",
                # explicit_bucket_boundaries_advisory=[
                #     0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],  # needs API >= 1.30
            ),
            "ponds_found": meter.create_histogram(
                "pond_ponds_found",
                unit="1",
                description="Number of ponds found during analysis.",
            ),
            "runoff_volume_m3": meter.create_histogram(
                "pond_runoff_volume_m3",
                unit="m3",
                description="Annual runoff volume per pond.",
            ),
            "analyses_total": meter.create_counter(
                "pond_analyses_total",
                unit="1",
                description="Total completed pond area analyses.",
            ),
            "dem_load_duration_seconds": meter.create_histogram(
                "pond_dem_load_duration_seconds",
                unit="s",
                description="Duration to fetch or sample elevation grid.",
            ),
            "rainfall_fetch_failures_total": meter.create_counter(
                "pond_rainfall_fetch_failures_total",
                unit="1",
                description="Rainfall data source fetch failures.",
            ),
        }

        def shutdown():
            try:
                span_processor.shutdown()
                metric_reader.shutdown()
                log_processor.shutdown()
            except Exception:
                pass

        app.state.telemetry = {"tracer": tracer,
                               "instruments": instruments, "shutdown": shutdown}
        return tracer, instruments, shutdown
    except Exception:
        _LOGGER.warning(
            "OTEL initialization failed; telemetry disabled", exc_info=True)
        return None, {}, lambda: None
