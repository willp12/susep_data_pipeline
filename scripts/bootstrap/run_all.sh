#!/usr/bin/env bash
# run_all.sh — runs the bootstrap scripts in order, stopping on the first error.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SCRIPTS=(
  "00_preflight.sh"
  "02_gcp_apis.sh"
  "03_gcp_bigquery.sh"
  "04_gcp_gcs_reports.sh"
  "05_gcp_ingest_sa.sh"
)

printf '[bootstrap] Running %d scripts from %s\n' "${#SCRIPTS[@]}" "${SCRIPT_DIR}"

for script in "${SCRIPTS[@]}"; do
  path="${SCRIPT_DIR}/${script}"
  [[ -x "${path}" ]] || chmod +x "${path}"
  printf '\n[bootstrap] >>> %s\n' "${script}"
  bash "${path}"
done

printf '\n[bootstrap] All scripts completed OK.\n'
