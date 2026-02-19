from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "OmniAudit MCP"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8080

    database_url: str = "sqlite+pysqlite:///./omniaudit.db"
    redis_url: str = "redis://localhost:6379/0"

    object_store_root: Path = Path("./data/objects")
    reports_root: Path = Path("./data/reports")
    sitelint_async_mode: bool = False
    object_store_backend: str = "local"
    object_store_bucket: str | None = None
    object_store_prefix: str = "omniaudit"
    s3_endpoint_url: str | None = None
    s3_region_name: str | None = None
    s3_force_path_style: bool = True
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None

    operator_name: str = "local-operator"
    write_confirmation_secret: str = "dev-confirmation-secret"
    write_confirmation_ttl_seconds: int = 600

    repo_write_allowlist: str = ""
    url_allowlist: str = ""
    url_denylist: str = ""

    mcp_auth_mode: str = "none"
    mcp_api_key: str | None = None

    github_auth_mode: str = "pat"
    github_pat: str | None = None

    github_app_id: str | None = None
    github_app_installation_id: str | None = None
    github_app_private_key: str | None = None

    envelope_master_key_file: Path = Path("./data/secrets/master.key")

    scan_rate_limit_per_minute: int = 10
    github_write_rate_limit_per_minute: int = 30
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    log_format: str = "json"
    prometheus_enabled: bool = True

    @staticmethod
    def _csv_to_set(value: str) -> set[str]:
        value = value.strip()
        if not value:
            return set()
        return {item.strip() for item in value.split(",") if item.strip()}

    @property
    def repo_write_allowlist_set(self) -> set[str]:
        return self._csv_to_set(self.repo_write_allowlist)

    @property
    def url_allowlist_set(self) -> set[str]:
        return self._csv_to_set(self.url_allowlist)

    @property
    def url_denylist_set(self) -> set[str]:
        return self._csv_to_set(self.url_denylist)


settings = Settings()
