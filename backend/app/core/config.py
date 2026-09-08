from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.ishv2ultracore import ISHV2UltraCore


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./ishbounty.db"
    github_webhook_secret: str = ""
    allowed_origins: str = "http://localhost:5173"
    api_key: str = Field(default="", validation_alias="ISHB_API_KEY")
    ishv2ultracore_store_path: str = Field(default="", validation_alias="ISHV2_ULTRACORE_STORE_PATH")
    ishv2ultracore_master_key: str = Field(default="", validation_alias="ISHV2_ULTRACORE_MASTER_KEY")
    payment_api_url: str = Field(default="", validation_alias="ISHB_PAYMENT_API_URL")
    payment_api_token: str = Field(default="", validation_alias="ISHB_PAYMENT_API_TOKEN")
    payment_webhook_secret: str = Field(default="", validation_alias="ISHB_PAYMENT_WEBHOOK_SECRET")
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @property
    def origins(self) -> list[str]:
        return [x.strip() for x in self.allowed_origins.split(",") if x.strip()]

    def get_secret(self, name: str, fallback: str = "") -> str:
        if self.ishv2ultracore_store_path and self.ishv2ultracore_master_key:
            store = ISHV2UltraCore(self.ishv2ultracore_store_path, self.ishv2ultracore_master_key)
            stored = store.get(name)
            if stored is not None:
                return stored
        return fallback

    @property
    def effective_api_key(self) -> str:
        return self.get_secret("api_key", self.api_key)

    @property
    def effective_github_webhook_secret(self) -> str:
        return self.get_secret("github_webhook_secret", self.github_webhook_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
