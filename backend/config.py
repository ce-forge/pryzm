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

    CORS_ORIGINS: list[str] =[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.0.108:3000",
        "http://192.168.0.108",
        "*"
    ]

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    MAXIMUM_TOOL_LOOPS: int = 8  # Max iterations of tool use before giving up and returning a fallback response

    MEMORY_CONTEXT_WINDOW: int = 15  # Max messages sent to Ollama per active chat
    MEMORY_CONDENSE_THRESHOLD: int = 15  # When to trigger the background condenser
    MEMORY_CONDENSE_RETAIN: int = 5  # How many recent messages to exclude from the summary

settings = Settings()