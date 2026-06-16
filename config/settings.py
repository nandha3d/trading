"""Central config. Loads from .env via pydantic-settings."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Alice Blue
    alice_user_id: str = Field(default="", alias="ALICE_USER_ID")
    alice_api_key: str = Field(default="", alias="ALICE_API_KEY")
    alice_app_key: str = Field(default="", alias="ALICE_APP_KEY")
    alice_app_secret: str = Field(default="", alias="ALICE_APP_SECRET")
    alice_redirect_url: str = Field(default="", alias="ALICE_REDIRECT_URL")

    # Upstox (historical candles incl. EXPIRED F&O)
    upstox_api_key: str = Field(default="", alias="UPSTOX_API_KEY")
    upstox_api_secret: str = Field(default="", alias="UPSTOX_API_SECRET")
    upstox_redirect_url: str = Field(default="", alias="UPSTOX_REDIRECT_URL")

    # Angel One SmartAPI
    angelone_api_key: str = Field(default="", alias="ANGELONE_API_KEY")
    angelone_client_code: str = Field(default="", alias="ANGELONE_CLIENT_CODE")
    angelone_pin: str = Field(default="", alias="ANGELONE_PIN")
    angelone_totp_secret: str = Field(default="", alias="ANGELONE_TOTP_SECRET")

    # Kaggle
    kaggle_username: str = Field(default="", alias="KAGGLE_USERNAME")
    kaggle_key: str = Field(default="", alias="KAGGLE_KEY")

    # Paths
    data_dir: Path = Field(default=Path("./data"), alias="DATA_DIR")
    lake_dir: Path = Field(default=Path("./data/lake"), alias="LAKE_DIR")
    db_path: Path = Field(default=Path("./data/market.duckdb"), alias="DB_PATH")

    @property
    def alice_ready(self) -> bool:
        return bool(self.alice_user_id and self.alice_api_key)

    @property
    def alice_sso_ready(self) -> bool:
        return bool(self.alice_app_key and self.alice_app_secret)

    @property
    def upstox_ready(self) -> bool:
        return bool(self.upstox_api_key and self.upstox_api_secret)

    @property
    def angelone_ready(self) -> bool:
        return bool(
            self.angelone_api_key and self.angelone_client_code
            and self.angelone_pin and self.angelone_totp_secret
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lake_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
