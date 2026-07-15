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

    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 30
    refresh_token_expire_minutes: int = 10080
    algorithm: str = "HS256"

    storage_dir: str = "storage"
    allowed_origin: str = "http://localhost:5173"

    @property
    def resolved_login_url(self) -> str:
        return (self.fusion_login_url or self.fusion_base_url).rstrip("/")


settings = Settings()
