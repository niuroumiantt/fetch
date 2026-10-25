#!/usr/bin/env bash
# Weekly listed-50 multi-lane refresh on M5: filings + equity quotes + IR pages.
set -euo pipefail
ROOT="${FETCH_ROOT:-$HOME/code/fetch}"
DATA="${LISTED_DATA_ROOT:-$HOME/.local/share/fetch/listed}"
LOG_DIR="${FETCH_LOG_DIR:-$HOME/.local/state/fetch/logs}"
PRIOR="${FETCHFILINGS_PRIOR_DISCLOSURES:-$HOME/code/inresearch.ai/data/company_disclosures.json}"
mkdir -p "$LOG_DIR" "$DATA" "$HOME/.local/share/fetch/fetchfilings"
cd "$ROOT"
CMD=(python3 fetch refresh --team listed --data-root "$DATA")
if [[ -f "$PRIOR" ]]; then
  CMD+=(--prior-disclosures "$PRIOR")
fi
"${CMD[@]}" | tee "$LOG_DIR/listed-weekly.log"
if [[ -f "$DATA/fetchfilings/disclosures/current.json" ]]; then
  mkdir -p "$HOME/.local/share/fetch/fetchfilings/disclosures"
  cp "$DATA/fetchfilings/disclosures/current.json" \
     "$HOME/.local/share/fetch/fetchfilings/disclosures/current.json"
fi
