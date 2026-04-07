"""Application settings loaded via environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"

    # Database
    database_url: str

    # Redis
    redis_url: str

    # Yandex Cloud
    yc_api_key: str
    yc_folder_id: str
    yc_agent_id_intake: str
    yc_agent_id_research: str

    # Tracker
    tracker_token: str
    tracker_org_id: str
    tracker_queue_key: str

    # Sourcecraft
    sourcecraft_token: str
    sourcecraft_base_url: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
