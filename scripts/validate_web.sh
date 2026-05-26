#!/bin/bash
# Validate the web calculator's JS engine against Python-generated test vectors.
# Usage: ./scripts/validate_web.sh
#
# To regenerate test vectors (requires Python 3.11+):
#   python3 scripts/generate_test_vectors.py

set -e
cd "$(dirname "$0")/.."

echo "Running JS parity validation..."
node tests/validate_js_parity.mjs
