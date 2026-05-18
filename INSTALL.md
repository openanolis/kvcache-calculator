# Installation & Deployment Guide

## Prerequisites

- Python **≥ 3.11**
- `pip` (bundled with Python)

## Quick Install

```bash
pip install -e .
```

This installs the `kvcache-upper-bound` CLI command and all runtime dependencies.

## Development Install

```bash
pip install -e ".[dev]"
```

Adds `pytest` for running the test suite.

## Docker Deployment

Minimal example for containerized use:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e .
ENTRYPOINT ["kvcache-upper-bound"]
```

Build and run:

```bash
docker build -t kvcache-upper-bound .
docker run --rm -v "$(pwd)/traces:/traces" -v "$(pwd)/outputs:/outputs" \
  kvcache-upper-bound analyze-buckets \
  --trace /traces/my_trace.jsonl \
  --config configs/example.json --output-dir /outputs
```

## Verifying the Install

```bash
kvcache-upper-bound --help
```

A usage message confirms the tool is installed correctly.

## Running the Tests

```bash
python3 -m unittest discover tests/
```

Or with `pytest` (after a dev install):

```bash
pytest tests/
```
