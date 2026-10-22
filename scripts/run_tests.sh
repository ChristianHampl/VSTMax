#!/usr/bin/env bash
# Alle automatischen Tests (Python + nativ, falls gebaut). GUI-Tests laufen headless.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3
if [ -x build/dsp/aime_dsp_tests ]; then build/dsp/aime_dsp_tests; fi
"$PY" scripts/gen_params.py --check
QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q "$@"
