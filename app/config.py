"""Application configuration.

Values are read from environment variables / a local ``.env`` file. The
Firefly token may be provided directly (``FIREFLY_TOKEN``) or, preferably, via
a file/secret path (``FIREFLY_TOKEN_FILE``) so it never lives in the image or
the compose file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Firefly III connection -------------------------------------------
    firefly_url: str = ""
    firefly_token: str = ""
    firefly_token_file: str = ""

    # --- Storage -----------------------------------------------------------
    data_dir: str = "./data"

    # --- Conversion defaults (overridable per upload) ---------------------
    self_name: str = ""
    default_currency: str = "EUR"
    import_tag: str = "moneybuster"
    default_asset_account: str = ""
    default_expense_account: str = "MoneyBuster"
    default_category: str = "Sonstiges"

    # --- Firefly write behaviour ------------------------------------------
    auto_create_expense_accounts: bool = False
    auto_create_categories: bool = False
    error_if_duplicate: bool = True
    apply_rules: bool = False

    # --- Server ------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 5000

    @property
    def token(self) -> str:
        """Resolve the token, preferring the secret file when configured."""

        if self.firefly_token_file:
            p = Path(self.firefly_token_file)
            if p.is_file():
                return p.read_text(encoding="utf-8").strip()
        return self.firefly_token.strip()

    @property
    def firefly_configured(self) -> bool:
        return bool(self.firefly_url and self.token)

    # --- Derived paths -----------------------------------------------------
    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def uploads_path(self) -> Path:
        p = self.data_path / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def history_db_path(self) -> Path:
        return self.data_path / "import_history.sqlite"

    @property
    def rules_path(self) -> Path:
        return self.data_path / "rules.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
