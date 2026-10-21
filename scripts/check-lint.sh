#!/bin/sh
set -eu
ruff check --no-cache .
python scripts/check-release.py
