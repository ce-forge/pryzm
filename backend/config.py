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
    LLM_SERVER_URL: str = "http://127.0.0.1:8080"

    # Explicit allowlist. Combining "*" with allow_credentials=True (set in
    # main.py) is rejected by browsers, so wildcarding is off. Defaults to
    # localhost only; tunnel / public-internet origins go here as a
    # comma-separated list in .env (e.g.
    # "http://localhost:3000,https://your-tunnel.trycloudflare.com").
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Regex for private-network origins (RFC1918 + loopback). Pair with
    # main.py's allow_origin_regex so mobile/LAN access works without the
    # user having to enumerate each device's IP. The boundary stays inside
    # the local network — public origins still need to be added explicitly.
    CORS_PRIVATE_NETWORK_REGEX: str = (
        r"^https?://("
        r"127\.0\.0\.1|"
        r"localhost|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r")(:\d+)?$"
    )

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    MAXIMUM_TOOL_LOOPS: int = 8  # Max iterations of tool use before giving up and returning a fallback response

    # Async HTTP timeouts for the LLM server (see core/llm_server.py).
    # LLM_TIMEOUT_SECONDS replaces the hardcoded timeout=120 that bit us in Phase 2
    # when cold-loading 35B models took >120s. Bumping to 180 gives headroom.
    LLM_CONNECT_TIMEOUT_SECONDS: float = 5.0
    LLM_TIMEOUT_SECONDS: float = 180.0
    TOOL_TIMEOUT_SECONDS: float = 30.0

    MEMORY_CONTEXT_WINDOW: int = 5  # Max messages sent to Ollama per active chat
    MEMORY_CONDENSE_THRESHOLD: int = 15  # When to trigger the background condenser
    MEMORY_CONDENSE_RETAIN: int = 5  # How many recent messages to exclude from the summary

    # Upload bytes ceiling. /upload streams the request body and bails with
    # HTTP 413 once cumulative bytes exceed this. Bumped here, not in the
    # endpoint — keep tunables in one place. Sized for image uploads (JPG/PNG/WebP)
    # which dominate above the text-doc baseline; text uploads share this knob.
    UPLOAD_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MiB

    # Image-captioning knobs (services/image_describe.py). Captioning runs the
    # uploaded image through a vision-capable chat model at ingest time; the
    # returned paragraph is what gets chunked and embedded into the RAG store.
    IMAGE_CAPTION_MODEL: str = "gemma-4-E4B-it"
    IMAGE_CAPTION_MAX_TOKENS: int = 600
    IMAGE_CAPTION_TEMPERATURE: float = 0.2

    # When False (default), the network diagnostic tools refuse to operate on
    # RFC1918, loopback, link-local, multicast, CGNAT, and reserved IPs — and
    # also refuse any hostname that resolves to one of those ranges, defeating
    # DNS-rebinding attempts. Flip to True for deployments where the whole
    # point is to diagnose the user's local network.
    NETWORK_TOOLS_ALLOW_PRIVATE: bool = False

settings = Settings()