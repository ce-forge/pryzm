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

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

settings = Settings()