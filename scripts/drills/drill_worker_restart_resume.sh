#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date -u +%Y%m%d-%H%M%S)"
out_dir="artifacts/drills/${timestamp}/worker-restart-resume"
mkdir -p "${out_dir}"

cat > "${out_dir}/summary.txt" <<EOF
Drill: Worker restart and job resume behavior
Timestamp: ${timestamp}
Action: start async SiteLint job, restart worker process, poll core.get_job
Expected: job state survives restart and resumes to completed or deterministic failure state
EOF

echo "Drill evidence written to ${out_dir}"
