"""Application configuration loaded from environment / .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings.

    All values can be set via environment variables or a `.env` file. The
    Firefly credentials are optional at startup so the converter / preview can
    be used without a configured Firefly instance; they are only required when
    actually pushing transactions to the API.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    # --- Firefly III connection -------------------------------------------
    firefly_base_url: str = ""
    firefly_token: str = ""

    # --- Conversion defaults ----------------------------------------------
    # Asset account in Firefly that money is paid from / received into.
    default_asset_account: str = "MoneyBuster"
    # Fallback expense / revenue accounts when no better name is available.
    default_expense_account: str = "MoneyBuster Expenses"
    default_revenue_account: str = "MoneyBuster Income"
    # ISO 4217 currency code used when the export does not specify one.
    default_currency: str = "EUR"
    # Tag attached to every imported transaction (for easy bulk removal).
    import_tag: str = "moneybuster"

    # --- Behaviour ---------------------------------------------------------
    # When true a positive bill amount becomes a deposit instead of a
    # withdrawal (use if your export represents spending as positive income).
    invert_sign: bool = False
    # Ask Firefly to reject duplicates based on the transaction hash.
    error_if_duplicate: bool = True
    # Apply Firefly's rules engine to imported transactions.
    apply_rules: bool = False

    # --- Server ------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8080

    @property
    def firefly_configured(self) -> bool:
        return bool(self.firefly_base_url and self.firefly_token)


settings = Settings()
