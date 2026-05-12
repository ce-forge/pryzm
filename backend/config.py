from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import computed_field
import urllib.parse

class Settings(BaseSettings):
    PROJECT_NAME: str = "DaiNamik Pryzm"
    VERSION: str = "1.0.0"
    
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_NAME: str

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        safe_password = urllib.parse.quote_plus(self.DB_PASSWORD)
        return f"postgresql://{self.DB_USER}:{safe_password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    REDIS_URL: str = "redis://127.0.0.1:6379"
    OLLAMA_URL: str = "http://127.0.0.1:11434"

    # Explicit allowlist. Combining "*" with allow_credentials=True (set in
    # main.py) is rejected by browsers, so wildcarding is off. If a deployment
    # needs additional origins (e.g. a tunnel for remote access), they should
    # be appended here or surfaced via env var rather than re-introducing "*".
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.0.108:3000",
        "http://192.168.0.108",
    ]

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    MAXIMUM_TOOL_LOOPS: int = 8  # Max iterations of tool use before giving up and returning a fallback response

    MEMORY_CONTEXT_WINDOW: int = 5  # Max messages sent to Ollama per active chat
    MEMORY_CONDENSE_THRESHOLD: int = 15  # When to trigger the background condenser
    MEMORY_CONDENSE_RETAIN: int = 5  # How many recent messages to exclude from the summary

    # Upload bytes ceiling. /upload streams the request body and bails with
    # HTTP 413 once cumulative bytes exceed this. Bumped here, not in the
    # endpoint — keep tunables in one place.
    UPLOAD_MAX_BYTES: int = 100 * 1024  # 100 KiB

    # When False (default), the network diagnostic tools refuse to operate on
    # RFC1918, loopback, link-local, multicast, CGNAT, and reserved IPs — and
    # also refuse any hostname that resolves to one of those ranges, defeating
    # DNS-rebinding attempts. Flip to True for deployments where the whole
    # point is to diagnose the user's local network.
    NETWORK_TOOLS_ALLOW_PRIVATE: bool = False

settings = Settings()