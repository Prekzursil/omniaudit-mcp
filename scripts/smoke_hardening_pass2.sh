#!/usr/bin/env bash
set -euo pipefail

OMNIAUDIT_MCP_URL="${OMNIAUDIT_MCP_URL:-http://localhost:8080/mcp}"
OMNIAUDIT_METRICS_URL="${OMNIAUDIT_METRICS_URL:-http://localhost:8080/metrics}"
SMOKE_REPO="${SMOKE_REPO:-Prekzursil/omniaudit-mcp}"
SMOKE_URL="${SMOKE_URL:-https://example.com}"
SMOKE_KEEP_EVIDENCE="${SMOKE_KEEP_EVIDENCE:-true}"
SMOKE_PREFLIGHT_ONLY="${SMOKE_PREFLIGHT_ONLY:-false}"

# Early dependency guard using only shell builtins so a restricted PATH fails
# deterministically with exit 10 *before* any external command (date, mkdir, jq)
# is invoked. This keeps preflight from crashing with 127 under a stripped PATH.
for _smoke_dep in curl jq docker gh; do
  if ! command -v "${_smoke_dep}" >/dev/null 2>&1; then
    printf '[smoke-pass2] FAIL (10): Missing dependency: %s\n' "${_smoke_dep}" >&2
    exit 10
  fi
done

SMOKE_TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
SMOKE_TAG="smoke/v${SMOKE_TIMESTAMP}-hardening-pass2"
SMOKE_RELEASE_NAME="Smoke Hardening Pass 2 ${SMOKE_TIMESTAMP} UTC"
ARTIFACT_ROOT="artifacts/smoke/${SMOKE_TIMESTAMP}"
RESPONSES_DIR="${ARTIFACT_ROOT}/responses"
SUMMARY_FILE="${ARTIFACT_ROOT}/summary.json"
ENV_FILE=".env"
ENV_BACKUP="${ARTIFACT_ROOT}/.env.backup"
HEALTH_URL="${OMNIAUDIT_MCP_URL%/mcp}/healthz"

mkdir -p "${RESPONSES_DIR}"

log() {
  printf '[smoke-pass2] %s\n' "$*"
}

write_summary() {
  local legacy_ok="$1"
  local s3_ok="$2"
  local release_ok="$3"
  local metrics_ok="$4"
  local release_url="$5"
  local error_msg="${6:-}"
  jq -n \
    --arg timestamp_utc "${SMOKE_TIMESTAMP}" \
    --arg smoke_tag "${SMOKE_TAG}" \
    --arg release_url "${release_url}" \
    --arg error "${error_msg}" \
    --argjson legacy_ref_read_ok "${legacy_ok}" \
    --argjson s3_ref_write_ok "${s3_ok}" \
    --argjson release_upload_ok "${release_ok}" \
    --argjson metrics_ok "${metrics_ok}" \
    '{
      timestamp_utc: $timestamp_utc,
      smoke_tag: $smoke_tag,
      release_url: $release_url,
      legacy_ref_read_ok: $legacy_ref_read_ok,
      s3_ref_write_ok: $s3_ref_write_ok,
      release_upload_ok: $release_upload_ok,
      metrics_ok: $metrics_ok,
      error: (if $error == "" then null else $error end)
    }' > "${SUMMARY_FILE}"
}

fail() {
  local code="$1"
  local message="$2"
  write_summary false false false false "" "${message}"
  log "FAIL (${code}): ${message}"
  exit "${code}"
}

require_cmd() {
  local cmd="$1"
  command -v "${cmd}" >/dev/null 2>&1 || fail 10 "Missing dependency: ${cmd}"
}

set_env_key() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}

mcp_call() {
  local call_id="$1"
  local tool_name="$2"
  local args_json="$3"
  local output_file="$4"

  local payload
  payload="$(jq -cn --arg id "${call_id}" --arg name "${tool_name}" --argjson args "${args_json}" \
    '{jsonrpc:"2.0", id:$id, method:"tools/call", params:{name:$name, arguments:$args}}')"
  curl -fsS "${OMNIAUDIT_MCP_URL}" \
    -H 'Content-Type: application/json' \
    -d "${payload}" > "${output_file}" || fail 20 "MCP request failed for ${tool_name}"

  if jq -e '.error' "${output_file}" >/dev/null 2>&1; then
    local err_msg
    err_msg="$(jq -r '.error.message // "unknown MCP error"' "${output_file}")"
    fail 20 "MCP tool error for ${tool_name}: ${err_msg}"
  fi
}

wait_for_health() {
  for _ in $(seq 1 60); do
    if curl -fsS "${HEALTH_URL}" | jq -e '.status == "ok"' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  fail 10 "Service health check failed at ${HEALTH_URL}"
}

poll_job_completion() {
  local job_id="$1"
  local prefix="$2"
  local output_file="${RESPONSES_DIR}/${prefix}_job_final.json"
  local status=""
  for i in $(seq 1 60); do
    local args
    args="$(jq -cn --arg job_id "${job_id}" '{job_id:$job_id}')"
    mcp_call "${prefix}-job-${i}" "core.get_job" "${args}" "${RESPONSES_DIR}/${prefix}_job_${i}.json"
    status="$(jq -r '.result.structuredContent.status // ""' "${RESPONSES_DIR}/${prefix}_job_${i}.json")"
    cp "${RESPONSES_DIR}/${prefix}_job_${i}.json" "${output_file}"
    if [[ "${status}" == "completed" ]]; then
      printf '%s\n' "${output_file}"
      return 0
    fi
    sleep 2
  done
  fail 20 "Timed out waiting for job completion: ${job_id}"
}

legacy_ref_read_ok=false
s3_ref_write_ok=false
release_upload_ok=false
metrics_ok=false
release_url=""

if [[ ! -f "${ENV_FILE}" ]]; then
  fail 10 "Missing ${ENV_FILE}"
fi

require_cmd curl
require_cmd jq
require_cmd docker
require_cmd gh

gh auth status >/dev/null 2>&1 || fail 10 "gh auth status failed"
docker info >/dev/null 2>&1 || fail 10 "Docker daemon unavailable"
gh repo view "${SMOKE_REPO}" >/dev/null 2>&1 || fail 10 "Smoke repo not found: ${SMOKE_REPO}"

if [[ "${SMOKE_PREFLIGHT_ONLY}" == "true" ]]; then
  write_summary false false false false "" ""
  log "Preflight-only mode complete."
  exit 0
fi

cp "${ENV_FILE}" "${ENV_BACKUP}"
# shellcheck disable=SC2329,SC2317  # invoked indirectly via the EXIT trap below
restore_env() {
  # shellcheck disable=SC2317  # body runs only via the EXIT trap; reachability analysis can't see that
  if [[ -f "${ENV_BACKUP}" ]]; then
    cp "${ENV_BACKUP}" "${ENV_FILE}"
    docker compose restart api worker >/dev/null 2>&1 || true
  fi
}
trap restore_env EXIT

mkdir -p "${ARTIFACT_ROOT}"
printf 'smoke artifact generated at %s\n' "${SMOKE_TIMESTAMP}" > "${ARTIFACT_ROOT}/sample-asset.txt"

log "Starting compose stack."
docker compose up -d --build >/dev/null || fail 10 "docker compose up failed"
wait_for_health

log "Running local backend scan."
set_env_key OBJECT_STORE_BACKEND local
docker compose restart api worker >/dev/null || fail 10 "Failed to restart services in local mode"
wait_for_health

local_scan_args="$(jq -cn --arg url "${SMOKE_URL}" '{url:$url, profile:"standard", viewport_set:"desktop_mobile"}')"
mcp_call "local-scan-start" "sitelint.start_scan" "${local_scan_args}" "${RESPONSES_DIR}/local_scan_start.json"
legacy_job_id="$(jq -r '.result.structuredContent.job_id // ""' "${RESPONSES_DIR}/local_scan_start.json")"
[[ -n "${legacy_job_id}" ]] || fail 20 "legacy_job_id missing"
legacy_job_file="$(poll_job_completion "${legacy_job_id}" "legacy")"
legacy_result_ref="$(jq -r '.result.structuredContent.result_ref // ""' "${legacy_job_file}")"
if [[ -z "${legacy_result_ref}" || "${legacy_result_ref}" == s3://* ]]; then
  fail 30 "Legacy result_ref is missing or unexpectedly s3:// (${legacy_result_ref})"
fi
legacy_ref_read_ok=true

log "Switching to S3 backend and running second scan."
set_env_key OBJECT_STORE_BACKEND s3
docker compose restart api worker >/dev/null || fail 10 "Failed to restart services in s3 mode"
wait_for_health

s3_scan_args="$(jq -cn --arg url "${SMOKE_URL}" '{url:$url, profile:"standard", viewport_set:"desktop_mobile", crawl_budget:2, entry_paths:["/","/"]}')"
mcp_call "s3-scan-start" "sitelint.start_scan" "${s3_scan_args}" "${RESPONSES_DIR}/s3_scan_start.json"
s3_job_id="$(jq -r '.result.structuredContent.job_id // ""' "${RESPONSES_DIR}/s3_scan_start.json")"
[[ -n "${s3_job_id}" ]] || fail 20 "s3_job_id missing"
s3_job_file="$(poll_job_completion "${s3_job_id}" "s3")"
s3_result_ref="$(jq -r '.result.structuredContent.result_ref // ""' "${s3_job_file}")"
if [[ "${s3_result_ref}" != s3://* ]]; then
  fail 30 "S3 result_ref does not start with s3:// (${s3_result_ref})"
fi
s3_ref_write_ok=true

legacy_report_args="$(jq -cn --arg scan_id "${legacy_job_id}" '{scan_id:$scan_id, format:"json"}')"
mcp_call "legacy-report" "sitelint.get_report" "${legacy_report_args}" "${RESPONSES_DIR}/legacy_report_after_s3.json"
jq -e '.result.structuredContent.report' "${RESPONSES_DIR}/legacy_report_after_s3.json" >/dev/null || \
  fail 30 "Failed to read legacy report after S3 cutover"

log "Creating smoke release with local asset upload."
release_notes="SMOKE-EVIDENCE: hardening pass2 ${SMOKE_TIMESTAMP}"
release_create_args="$(jq -cn \
  --arg repo "${SMOKE_REPO}" \
  --arg tag "${SMOKE_TAG}" \
  --arg notes "${release_notes}" \
  --arg asset "${ARTIFACT_ROOT}/sample-asset.txt" \
  --arg name "${SMOKE_RELEASE_NAME}" \
  '{repo:$repo, tag:$tag, notes:($notes + "\n\nRelease name: " + $name), assets:[$asset], provenance_manifest:true}')"

mcp_call "release-create-initial" "releasebutler.create_release" "${release_create_args}" "${RESPONSES_DIR}/release_create_initial.json"
confirmation_token="$(jq -r '.result.structuredContent.confirmation_token // ""' "${RESPONSES_DIR}/release_create_initial.json")"
[[ -n "${confirmation_token}" ]] || fail 40 "Missing confirmation_token for release creation"

release_confirm_args="$(jq -cn \
  --arg repo "${SMOKE_REPO}" \
  --arg tag "${SMOKE_TAG}" \
  --arg notes "${release_notes}" \
  --arg asset "${ARTIFACT_ROOT}/sample-asset.txt" \
  --arg token "${confirmation_token}" \
  '{repo:$repo, tag:$tag, notes:$notes, assets:[$asset], confirmation_token:$token, provenance_manifest:true}')"

mcp_call "release-create-confirmed" "releasebutler.create_release" "${release_confirm_args}" "${RESPONSES_DIR}/release_create_confirmed.json"
release_id="$(jq -r '.result.structuredContent.release_id // ""' "${RESPONSES_DIR}/release_create_confirmed.json")"
uploaded_count="$(jq -r '.result.structuredContent.uploaded_assets | length' "${RESPONSES_DIR}/release_create_confirmed.json")"
failed_count="$(jq -r '.result.structuredContent.failed_assets | length' "${RESPONSES_DIR}/release_create_confirmed.json")"
release_url="$(jq -r '.result.structuredContent.release_url // ""' "${RESPONSES_DIR}/release_create_confirmed.json")"

if [[ -z "${release_id}" || "${uploaded_count}" -lt 1 || "${failed_count}" -ne 0 ]]; then
  fail 40 "Release upload validation failed (release_id=${release_id}, uploaded=${uploaded_count}, failed=${failed_count})"
fi

list_assets_args="$(jq -cn --arg repo "${SMOKE_REPO}" --arg tag "${SMOKE_TAG}" '{repo:$repo, tag:$tag}')"
mcp_call "release-list-assets" "releasebutler.list_assets" "${list_assets_args}" "${RESPONSES_DIR}/release_list_assets.json"
jq -e '.result.structuredContent.assets[] | select(.name=="sample-asset.txt")' "${RESPONSES_DIR}/release_list_assets.json" >/dev/null || \
  fail 40 "Uploaded smoke asset not found in release asset list"
release_upload_ok=true

log "Validating metrics endpoint."
metrics_out="${ARTIFACT_ROOT}/metrics.txt"
curl -fsS "${OMNIAUDIT_METRICS_URL}" > "${metrics_out}" || fail 50 "Failed to fetch metrics"
grep -q 'omniaudit_tool_calls_total' "${metrics_out}" || fail 50 "Missing omniaudit_tool_calls_total"
grep -q 'omniaudit_write_gate_denied_total' "${metrics_out}" || fail 50 "Missing omniaudit_write_gate_denied_total"
grep -q 'omniaudit_rate_limit_denied_total' "${metrics_out}" || fail 50 "Missing omniaudit_rate_limit_denied_total"
metrics_ok=true

write_summary "${legacy_ref_read_ok}" "${s3_ref_write_ok}" "${release_upload_ok}" "${metrics_ok}" "${release_url}" ""

log "Smoke complete."
printf '\n'
printf '%-24s %s\n' "legacy_ref_read_ok" "${legacy_ref_read_ok}"
printf '%-24s %s\n' "s3_ref_write_ok" "${s3_ref_write_ok}"
printf '%-24s %s\n' "release_upload_ok" "${release_upload_ok}"
printf '%-24s %s\n' "metrics_ok" "${metrics_ok}"
printf '%-24s %s\n' "release_url" "${release_url}"
printf '%-24s %s\n' "smoke_tag" "${SMOKE_TAG}"
printf '%-24s %s\n' "timestamp_utc" "${SMOKE_TIMESTAMP}"

if [[ "${SMOKE_KEEP_EVIDENCE}" == "true" ]]; then
  log "Evidence retained (release/tag/assets preserved)."
fi

log "PASS"
exit 0
