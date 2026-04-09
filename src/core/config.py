"""Application settings loaded via environment variables."""

from pydantic import model_validator
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

    # Yandex AI Studio (Responses API) — for Deep Research agents
    yandex_api_key: str = ""
    yandex_base_url: str = "https://ai.api.cloud.yandex.net/v1"
    yandex_project_id: str = ""

    # Agent prompt IDs (Yandex AI Studio)
    agent_project_analyst_id: str = ""
    agent_research_strategist_id: str = ""
    agent_technical_researcher_id: str = ""
    agent_architect_id: str = ""
    agent_roadmap_manager_id: str = ""
    agent_hr_specialist_id: str = ""
    agent_risk_analyst_id: str = ""
    agent_quality_reviewer_id: str = ""
    agent_synthesis_manager_id: str = ""
    eval_technical_analyst_id: str = ""
    eval_market_researcher_id: str = ""
    eval_innovator_id: str = ""
    eval_risk_assessor_id: str = ""
    eval_moderator_id: str = ""
    print_full_agent_outputs: bool = True
    save_full_prompts: bool = True
    yandex_retry_backoff_sec: float = 5.0

    # Auth
    jwt_secret_key: str = "supersecret"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24
    
    # Telegram Admin
    telegram_bot_token: str = ""
    public_app_url: str = "http://localhost:8000"

    @model_validator(mode="after")
    def _apply_compat_aliases(self) -> "Settings":
        # Keep backward compatibility between YC_* and YANDEX_* env styles.
        if not self.yc_api_key and self.yandex_api_key:
            self.yc_api_key = self.yandex_api_key
        if not self.yandex_api_key and self.yc_api_key:
            self.yandex_api_key = self.yc_api_key
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
