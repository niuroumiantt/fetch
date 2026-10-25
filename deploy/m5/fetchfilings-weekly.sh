#!/usr/bin/env bash
# Weekly fetchfilings refresh on M5: discover + collect + disclosures projection.
set -euo pipefail
ROOT="${FETCH_ROOT:-$HOME/code/fetch}"
DATA="${FETCHFILINGS_DATA_ROOT:-$HOME/.local/share/fetch/fetchfilings}"
LOG_DIR="${FETCH_LOG_DIR:-$HOME/.local/state/fetch/logs}"
PRIOR="${FETCHFILINGS_PRIOR_DISCLOSURES:-$HOME/code/inresearch.ai/data/company_disclosures.json}"
mkdir -p "$LOG_DIR" "$DATA"
cd "$ROOT"
ARGS=(python3 fetch refresh --team fetchfilings --data-root "$DATA")
if [[ -f "$PRIOR" ]]; then
  ARGS+=(--prior-disclosures "$PRIOR")
fi
exec "${ARGS[@]}"
