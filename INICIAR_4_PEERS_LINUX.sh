#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 scripts/run_config.py config/4_peers.json
