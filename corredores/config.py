from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:////opt/corredores/var/corredores_p0.db"
    # Optional override for pytest; if unset, tests derive corredores_test from database_url.
    corredores_test_database_url: str | None = None
    app_env: str = "dev"
    log_level: str = "INFO"


settings = Settings()
