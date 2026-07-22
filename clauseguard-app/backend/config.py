from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    fusion_base_url: str = "https://stg-agentic.abafusion.ai"
    fusion_login_url: str = ""
    fusion_username: str = ""
    fusion_password: str = ""
    flow_analysis_id: str = ""
    flow_report_id: str = ""
    flow_report_fallback_id: str = ""

    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 30
    refresh_token_expire_minutes: int = 10080
    algorithm: str = "HS256"

    port: int = 8000
    storage_dir: str = "storage"
    audit_log_path: str = ""  # empty = <storage_dir>/audit_log.jsonl
    allowed_origin: str = "http://localhost:5173"
    mcp_sqlite_path: str = "../../clauseguard-mcp/reports.db"

    quality_loop: str = "off"
    flow_critic_id: str = ""
    flow_refiner_id: str = ""
    quality_threshold: float = 0.75
    quality_max_iterations: int = 2

    @property
    def resolved_login_url(self) -> str:
        return (self.fusion_login_url or self.fusion_base_url).rstrip("/")

    @property
    def quality_loop_enabled(self) -> bool:
        return self.quality_loop.strip().lower() == "on"


settings = Settings()
