from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:////opt/corredores/var/corredores_p0.db"
    app_env: str = "dev"
    log_level: str = "INFO"


settings = Settings()
