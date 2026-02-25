"""Application configuration and settings."""

import logging
from pathlib import Path
from typing import Optional

from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration from environment variables."""

    model_config = ConfigDict(env_file=".env", case_sensitive=False)

    # Schwab API
    schwab_api_key: Optional[str] = Field(default=None, alias="SCHWAB_API_KEY")
    schwab_app_secret: Optional[str] = Field(default=None, alias="SCHWAB_APP_SECRET")
    schwab_callback_url: Optional[str] = Field(default=None, alias="SCHWAB_CALLBACK_URL")
    schwab_token_path: str = Field(default="token.json", alias="SCHWAB_TOKEN_PATH")

    # Massive API
    massive_api_key: Optional[str] = Field(default=None, alias="MASSIVE_API_KEY")

    # Streaming
    stream_refresh_interval: int = Field(default=5, alias="STREAM_REFRESH_INTERVAL")
    stream_reconnect_timeout: int = Field(default=30, alias="STREAM_RECONNECT_TIMEOUT")
    stream_strikes_range: int = Field(default=20, alias="STREAM_STRIKES_RANGE")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    def setup_logging(self) -> None:
        """Configure logging."""
        logging.basicConfig(
            level=getattr(logging, self.log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    @property
    def token_path(self) -> Path:
        """Get token path as Path object."""
        return Path(self.schwab_token_path)


# Global settings instance
try:
    settings = Settings()  # type: ignore
except Exception:
    # Fallback if .env doesn't exist
    settings = Settings(
        schwab_api_key="",
        schwab_app_secret="",
        schwab_callback_url="",
        massive_api_key="",
    )  # type: ignore
