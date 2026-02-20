#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date -u +%Y%m%d-%H%M%S)"
out_dir="artifacts/drills/${timestamp}/s3-unavailability"
mkdir -p "${out_dir}"

cat > "${out_dir}/summary.txt" <<EOF
Drill: S3 unavailable fallback verification
Timestamp: ${timestamp}
Action: run service in dual-read mode and verify legacy local refs remain readable
Expected: read path works for local refs; new writes fail fast with clear error if S3 is down
EOF

echo "Drill evidence written to ${out_dir}"
