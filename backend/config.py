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

    # Shared bearer token for all API clients. No default — Pydantic raises at
    # startup if the env var is missing, which is the correct fail-fast shape
    # for a required secret.
    PRYZM_API_TOKEN: str

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        safe_password = urllib.parse.quote_plus(self.DB_PASSWORD)
        return f"postgresql://{self.DB_USER}:{safe_password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    REDIS_URL: str = "redis://127.0.0.1:6379"
    OLLAMA_URL: str = "http://127.0.0.1:11434"

    # Explicit allowlist. Combining "*" with allow_credentials=True (set in
    # main.py) is rejected by browsers, so wildcarding is off. Defaults to
    # localhost only; for LAN/tunnel access set CORS_ORIGINS in .env as a
    # comma-separated list (e.g. "http://localhost:3000,http://192.168.1.50:3000").
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    MAXIMUM_TOOL_LOOPS: int = 8  # Max iterations of tool use before giving up and returning a fallback response

    # Async HTTP timeouts for the Ollama client (see core/ollama.py).
    # LLM_TIMEOUT_SECONDS replaces the hardcoded timeout=120 that bit us in Phase 2
    # when cold-loading 35B models took >120s. Bumping to 180 gives headroom.
    OLLAMA_CONNECT_TIMEOUT_SECONDS: float = 5.0
    LLM_TIMEOUT_SECONDS: float = 180.0
    TOOL_TIMEOUT_SECONDS: float = 30.0

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