from __future__ import annotations

import logging
from time import perf_counter
from typing import Any
from uuid import uuid4

from omniaudit.core.policy import PolicyEngine
from omniaudit.core.rate_limit import InMemoryRateLimiter
from omniaudit.core.settings import settings
from omniaudit.mcp.schemas import TOOLS
from omniaudit.modules.auditlens.service import AuditLensService
from omniaudit.modules.github.auth import GitHubAppAuthProvider, PATAuthProvider
from omniaudit.modules.github.client import GitHubClient
from omniaudit.modules.releasebutler.service import ReleaseButlerService
from omniaudit.modules.sitelint.service import SiteLintService
from omniaudit.observability.metrics import (
    record_rate_limit_denied,
    record_tool_call,
    record_write_gate_denied,
)
from omniaudit.observability.tracing import tracing_initialized
from omniaudit.security.confirmation import ConfirmationService
from omniaudit.security.envelope import EnvelopeEncryption
from omniaudit.security.risk import RiskGate
from omniaudit.storage.audit_log import AuditLogger
from omniaudit.storage.base import ObjectStore
from omniaudit.storage.credentials import SecretCredentialStore
from omniaudit.storage.dual import DualReadObjectStore
from omniaudit.storage.engine import create_db_engine, create_session_factory, initialize_database
from omniaudit.storage.jobs import JobStore
from omniaudit.storage.objects import LocalObjectStore
from omniaudit.storage.receipts import ReceiptStore
from omniaudit.storage.s3 import S3ObjectStore

logger = logging.getLogger("omniaudit.runtime")


class MCPToolError(RuntimeError):
    pass


class MCPRateLimitError(MCPToolError):
    pass


class AppRuntime:
    def __init__(
        self,
        policy: PolicyEngine,
        risk_gate: RiskGate,
        auditlens: AuditLensService,
        sitelint: SiteLintService,
        releasebutler: ReleaseButlerService,
        jobs: JobStore,
        receipts: ReceiptStore,
        audit_logger: AuditLogger,
        scan_rate_limiter: InMemoryRateLimiter,
        github_write_rate_limiter: InMemoryRateLimiter,
        object_store_backend: str,
    ) -> None:
        self.policy = policy
        self.risk_gate = risk_gate
        self.auditlens = auditlens
        self.sitelint = sitelint
        self.releasebutler = releasebutler
        self.jobs = jobs
        self.receipts = receipts
        self.audit_logger = audit_logger
        self.scan_rate_limiter = scan_rate_limiter
        self.github_write_rate_limiter = github_write_rate_limiter
        self.object_store_backend = object_store_backend


WRITE_TOOLS = {
    "auditlens.create_issue",
    "sitelint.export_report",
    "releasebutler.create_release",
}


def _build_github_client() -> GitHubClient:
    if settings.github_auth_mode == "app":
        if settings.github_app_id and settings.github_app_installation_id and settings.github_app_private_key:
            provider = GitHubAppAuthProvider(
                app_id=settings.github_app_id,
                installation_id=settings.github_app_installation_id,
                private_key_pem=settings.github_app_private_key,
            )
        else:
            provider = PATAuthProvider("MISSING_GITHUB_CREDENTIALS")
    else:
        provider = PATAuthProvider(settings.github_pat or "MISSING_GITHUB_CREDENTIALS")

    return GitHubClient(auth_provider=provider)


def _build_object_store() -> ObjectStore:
    local_store = LocalObjectStore(settings.object_store_root)
    backend = settings.object_store_backend.lower().strip()
    if backend != "s3":
        return local_store

    if not settings.object_store_bucket:
        raise MCPToolError("OBJECT_STORE_BUCKET is required when OBJECT_STORE_BACKEND=s3")

    s3_store = S3ObjectStore(
        bucket=settings.object_store_bucket,
        prefix=settings.object_store_prefix,
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region_name,
        force_path_style=settings.s3_force_path_style,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
    )
    return DualReadObjectStore(primary=s3_store, fallback=local_store)


def build_runtime() -> AppRuntime:
    settings.object_store_root.mkdir(parents=True, exist_ok=True)
    settings.reports_root.mkdir(parents=True, exist_ok=True)

    engine = create_db_engine()
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    object_store = _build_object_store()
    jobs = JobStore(session_factory)
    receipts = ReceiptStore(session_factory, object_store)
    audit_logger = AuditLogger(session_factory)
    envelope = EnvelopeEncryption(settings.envelope_master_key_file)
    credentials = SecretCredentialStore(session_factory, envelope)

    policy = PolicyEngine(
        repo_allowlist=settings.repo_write_allowlist_set,
        url_allowlist=settings.url_allowlist_set,
        url_denylist=settings.url_denylist_set,
    )
    risk_gate = RiskGate(
        ConfirmationService(
            secret=settings.write_confirmation_secret,
            ttl_seconds=settings.write_confirmation_ttl_seconds,
        )
    )

    github = _build_github_client()
    dispatcher = None
    if settings.sitelint_async_mode:
        try:
            from worker.tasks import dispatch_sitelint_scan  # type: ignore

            dispatcher = dispatch_sitelint_scan
        except Exception:
            dispatcher = None

    return AppRuntime(
        policy=policy,
        risk_gate=risk_gate,
        auditlens=AuditLensService(github=github, object_store=object_store),
        sitelint=SiteLintService(
            jobs=jobs,
            object_store=object_store,
            reports_root=settings.reports_root,
            async_mode=settings.sitelint_async_mode and dispatcher is not None,
            dispatcher=dispatcher,
            credentials=credentials,
        ),
        releasebutler=ReleaseButlerService(github=github),
        jobs=jobs,
        receipts=receipts,
        audit_logger=audit_logger,
        scan_rate_limiter=InMemoryRateLimiter(settings.scan_rate_limit_per_minute),
        github_write_rate_limiter=InMemoryRateLimiter(settings.github_write_rate_limit_per_minute),
        object_store_backend=settings.object_store_backend,
    )


def list_tools() -> dict[str, Any]:
    return {"tools": TOOLS}


def _ensure_repo_policy(runtime: AppRuntime, args: dict[str, Any]) -> None:
    repo = args.get("repo")
    if repo:
        runtime.policy.require_repo_write_allowed(repo)


def _ensure_url_policy(runtime: AppRuntime, args: dict[str, Any]) -> None:
    url = args.get("url")
    if url:
        runtime.policy.require_url_allowed(url)


def call_tool(runtime: AppRuntime, name: str, arguments: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
    rid = request_id or f"req_{uuid4().hex}"
    started = perf_counter()

    try:
        result = _call_tool_inner(runtime, rid, name, arguments)
        duration = perf_counter() - started
        status = "gate_denied" if isinstance(result, dict) and result.get("requires_confirmation") else "success"
        record_tool_call(name, status, duration)
        logger.info(
            "tool call completed",
            extra={
                "request_id": rid,
                "tool": name,
                "module_name": name.split(".", 1)[0],
                "duration_ms": int(duration * 1000),
                "status": status,
            },
        )
        return result
    except Exception as exc:
        duration = perf_counter() - started
        status = "rate_limited" if isinstance(exc, MCPRateLimitError) else "error"
        record_tool_call(name, status, duration)
        logger.error(
            "tool call failed",
            extra={
                "request_id": rid,
                "tool": name,
                "module_name": name.split(".", 1)[0] if "." in name else "unknown",
                "duration_ms": int(duration * 1000),
                "status": status,
                "error": str(exc),
            },
            exc_info=True,
        )
        raise


def _call_tool_inner(runtime: AppRuntime, request_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    args = dict(arguments)
    token = args.pop("confirmation_token", None)

    if name == "auditlens.list_runs":
        result = runtime.auditlens.list_runs(
            repo=args["repo"],
            pr_number=args.get("pr_number"),
            branch=args.get("branch"),
        )
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "auditlens.fetch_evidence":
        result = runtime.auditlens.fetch_evidence(
            repo=args["repo"],
            run_id=int(args["run_id"]),
            artifact_name=args["artifact_name"],
        )
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "auditlens.parse_findings":
        result = runtime.auditlens.parse_findings(
            evidence_ref=args["evidence_ref"],
            ruleset_version=args.get("ruleset_version", "v1"),
            parser_profile=args.get("parser_profile", "auto"),
            dedupe_strategy=args.get("dedupe_strategy", "by_id"),
        )
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "auditlens.create_issue":
        if not runtime.github_write_rate_limiter.allow("github-write"):
            record_rate_limit_denied("github-write")
            raise MCPRateLimitError("GitHub write rate limit exceeded")
        _ensure_repo_policy(runtime, args)
        gate = runtime.risk_gate.check_write(name, args, token)
        if not gate.allowed:
            record_write_gate_denied(name)
            response = gate.response or {}
            _log(runtime, request_id, name, arguments, response)
            return response
        result = runtime.auditlens.create_issue(
            repo=args["repo"],
            title=args["title"],
            body=args["body"],
            labels=args.get("labels", []),
            finding_ids=args.get("finding_ids"),
            assignees=args.get("assignees"),
            milestone=int(args["milestone"]) if args.get("milestone") is not None else None,
            template_id=args.get("template_id"),
        )
        receipt = runtime.receipts.create_receipt(name, settings.operator_name, args, result)
        merged = {**result, "receipt_id": receipt.receipt_id}
        _log(runtime, request_id, name, arguments, merged)
        return merged

    if name == "auditlens.propose_patch":
        result = runtime.auditlens.propose_patch(repo=args["repo"], finding_id=args["finding_id"])
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "sitelint.start_scan":
        if not runtime.scan_rate_limiter.allow("scan"):
            record_rate_limit_denied("scan")
            raise MCPRateLimitError("Scan submission rate limit exceeded")
        _ensure_url_policy(runtime, args)
        result = runtime.sitelint.start_scan(
            url=args["url"],
            profile=args["profile"],
            viewport_set=args["viewport_set"],
            auth_profile=args.get("auth_profile"),
            idempotency_key=args.get("idempotency_key"),
            crawl_budget=int(args["crawl_budget"]) if args.get("crawl_budget") is not None else None,
            entry_paths=args.get("entry_paths"),
            auth_profile_id=args.get("auth_profile_id"),
            baseline_scan_id=args.get("baseline_scan_id"),
        )
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "sitelint.get_scan":
        result = runtime.sitelint.get_scan(job_id=args["job_id"])
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "sitelint.get_report":
        result = runtime.sitelint.get_report(scan_id=args["scan_id"], format_name=args.get("format", "json"))
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "sitelint.export_report":
        if not runtime.github_write_rate_limiter.allow("github-write"):
            record_rate_limit_denied("github-write")
            raise MCPRateLimitError("Write rate limit exceeded")
        gate = runtime.risk_gate.check_write(name, args, token)
        if not gate.allowed:
            record_write_gate_denied(name)
            response = gate.response or {}
            _log(runtime, request_id, name, arguments, response)
            return response
        result = runtime.sitelint.export_report(
            scan_id=args["scan_id"],
            format_name=args.get("format", "json"),
            destination=args["destination"],
        )
        receipt = runtime.receipts.create_receipt(name, settings.operator_name, args, result)
        merged = {**result, "receipt_id": receipt.receipt_id}
        _log(runtime, request_id, name, arguments, merged)
        return merged

    if name == "releasebutler.get_latest":
        result = runtime.releasebutler.get_latest(repo=args["repo"])
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "releasebutler.list_assets":
        result = runtime.releasebutler.list_assets(repo=args["repo"], tag=args.get("tag"))
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "releasebutler.verify_asset":
        result = runtime.releasebutler.verify_asset(
            repo=args["repo"],
            asset_id=int(args["asset_id"]),
            checksum_source=args["checksum_source"],
        )
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "releasebutler.generate_notes":
        result = runtime.releasebutler.generate_notes(
            repo=args["repo"],
            tag=args.get("tag"),
            window=int(args.get("window", 20)),
            from_tag=args.get("from_tag"),
            to_tag=args.get("to_tag"),
            fallback_window=int(args["fallback_window"]) if args.get("fallback_window") is not None else None,
            group_by=args.get("group_by"),
            include_pr_links=bool(args.get("include_pr_links", False)),
        )
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "releasebutler.create_release":
        if not runtime.github_write_rate_limiter.allow("github-write"):
            record_rate_limit_denied("github-write")
            raise MCPRateLimitError("GitHub write rate limit exceeded")
        _ensure_repo_policy(runtime, args)
        gate = runtime.risk_gate.check_write(name, args, token)
        if not gate.allowed:
            record_write_gate_denied(name)
            response = gate.response or {}
            _log(runtime, request_id, name, arguments, response)
            return response
        result = runtime.releasebutler.create_release(
            repo=args["repo"],
            tag=args["tag"],
            notes=args["notes"],
            assets=args.get("assets"),
            draft=bool(args.get("draft", False)),
            prerelease=bool(args.get("prerelease", False)),
            dry_run=bool(args.get("dry_run", False)),
            provenance_manifest=bool(args.get("provenance_manifest", False)),
        )
        receipt = runtime.receipts.create_receipt(name, settings.operator_name, args, result)
        merged = {**result, "receipt_id": receipt.receipt_id}
        _log(runtime, request_id, name, arguments, merged)
        return merged

    if name == "core.get_job":
        job = runtime.jobs.get_job(args["job_id"])
        if not job:
            raise MCPToolError(f"Unknown job_id: {args['job_id']}")
        result = {
            "job_id": job.job_id,
            "module": job.module,
            "status": job.status,
            "progress": job.progress,
            "started_at": job.created_at.isoformat() if job.created_at else None,
            "finished_at": job.updated_at.isoformat() if job.status == "completed" else None,
            "result_ref": job.result_ref,
        }
        _log(runtime, request_id, name, arguments, result)
        return result

    if name == "core.list_receipts":
        receipts = runtime.receipts.list_receipts(operation=args.get("operation"))
        result = [
            {
                "receipt_id": row.receipt_id,
                "operation": row.operation,
                "inputs_hash": row.inputs_hash,
                "actor": row.actor,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "result_ref": row.result_ref,
            }
            for row in receipts
        ]
        _log(runtime, request_id, name, arguments, {"count": len(result)})
        return result

    if name == "core.health":
        result = {
            "status": "ok",
            "app": settings.app_name,
            "env": settings.app_env,
            "write_tools": sorted(WRITE_TOOLS),
            "tool_count": len(TOOLS),
            "object_store_backend": runtime.object_store_backend,
            "observability": {
                "logging_format": settings.log_format,
                "tracing_enabled": settings.otel_enabled,
                "otlp_endpoint_configured": bool(settings.otel_exporter_otlp_endpoint),
                "tracing_initialized": tracing_initialized(),
                "metrics_enabled": settings.prometheus_enabled,
            },
        }
        _log(runtime, request_id, name, arguments, result)
        return result

    raise MCPToolError(f"Unknown tool name: {name}")


def _log(runtime: AppRuntime, request_id: str, tool_name: str, arguments: dict[str, Any], output: Any) -> None:
    output_ref = runtime.receipts.object_store.put_json_immutable(
        {
            "tool": tool_name,
            "output": output,
        }
    )
    runtime.audit_logger.append(request_id=request_id, tool_name=tool_name, inputs=arguments, output_ref=output_ref)
