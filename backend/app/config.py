"""Environment-driven settings. Secrets come only from env / .env (never committed)."""
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
MIN_FACULTY_KEY_LEN = 16
APP_VERSION = "0.3.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # SQLite locally; PostgreSQL in production (e.g. postgresql+psycopg://user:pw@host/db).
    database_url: str = f"sqlite:///{(ROOT / 'acadza.db').as_posix()}"
    data_dir: Path = ROOT / "data"
    frontend_dir: Path = ROOT / "frontend"
    boot_import: bool = True             # empty DB on startup → verified import of data/
    boot_triage: bool = True             # no triage run yet on startup → run the rules engine (proposals only)

    # Faculty writes (RULES R-85). Unset or too short → writes disabled (fail closed).
    faculty_access_key: SecretStr | None = None
    cors_origins: str = ""               # comma-separated, dev only; never "*"
    max_body_bytes: int = 64 * 1024
    log_level: str = "INFO"

    # Engine (Phase 4+). Shown read-only by /settings.
    llm_provider: str = "none"
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    llm_base_url: str = ""
    auto_apply_min_confidence: float = 0.85
    no_change_min_confidence: float = 0.60

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        # Hosted Postgres (Render/Neon/Supabase) hands out postgres:// URLs; SQLAlchemy needs a driver.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, v: str) -> str:
        if "*" in v:
            raise ValueError("CORS_ORIGINS must list explicit origins; '*' is not allowed")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def writes_enabled(self) -> bool:
        k = self.faculty_access_key
        return bool(k) and len(k.get_secret_value()) >= MIN_FACULTY_KEY_LEN


settings = Settings()
