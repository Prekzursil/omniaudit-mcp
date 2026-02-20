#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date -u +%Y%m%d-%H%M%S)"
out_dir="artifacts/drills/${timestamp}/github-api-outage"
mkdir -p "${out_dir}"

cat > "${out_dir}/summary.txt" <<EOF
Drill: GitHub API transient outage simulation
Timestamp: ${timestamp}
Action: invoke releasebutler.generate_notes with invalid API base override
Expected: graceful tool failure with logged error and no process crash
EOF

echo "Drill evidence written to ${out_dir}"
