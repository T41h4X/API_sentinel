from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SENTINEL_", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./sentinel.db"
    retention_days: int = 30
    masked_fields: List[str] = [
        "password",
        "token",
        "credit_card",
        "authorization",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "private_key",
    ]
    selective_persistence: bool = False
    openapi_spec_path: str = "openapi.yaml"

settings = Settings()
