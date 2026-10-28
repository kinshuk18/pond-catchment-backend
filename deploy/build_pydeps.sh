#!/usr/bin/env bash
set -eu

PYTHON_BIN=${PYTHON_BIN:-python3}
TARGET=${TARGET:-$HOME/pond/pydeps}
mkdir -p "$TARGET"

"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install \
  --target "$TARGET" \
  --python-version 3.12 \
  --only-binary=:all: \
  fastapi==0.115.0 \
  uvicorn==0.30.6 \
  python-multipart==0.0.9 \
  numpy==2.5.1 \
  scipy==1.18.0 \
  beautifulsoup4==4.12.3 \
  lxml==5.3.0 \
  httpx==0.27.2 \
  opentelemetry-api==1.26.0 \
  opentelemetry-sdk==1.26.0 \
  opentelemetry-exporter-otlp-proto-http==1.26.0 \
  opentelemetry-instrumentation-fastapi==0.47b0 \
  opentelemetry-instrumentation-logging==0.47b0 \
  opentelemetry-instrumentation-httpx==0.47b0
