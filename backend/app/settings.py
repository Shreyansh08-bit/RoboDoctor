from pathlib import Path
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / '.env', extra='ignore'
    )
    model_name: str = 'gemma3:4b'
    ollama_base_url: str = 'http://127.0.0.1:11434'
    ai_timeout_seconds: float = 180

    @field_validator('ollama_base_url')
    @classmethod
    def local_only(cls, value: str) -> str:
        url = urlparse(value)
        if (url.scheme != 'http' or url.hostname not in {'localhost', '127.0.0.1', '::1'}
                or url.username or url.password or url.query or url.fragment
                or url.path not in {'', '/'}):
            raise ValueError('Ollama must use an HTTP loopback address without credentials or path')
        return value.rstrip('/')

    @field_validator('model_name')
    @classmethod
    def no_cloud_models(cls, value: str) -> str:
        if 'cloud' in value.lower() or not value.strip() or len(value) > 100:
            raise ValueError('Select a downloaded local model, not a cloud model')
        return value


settings = Settings()
