from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:////opt/corredores/var/corredores_p0.db"
    # Optional override for pytest; if unset, tests derive corredores_test from database_url.
    corredores_test_database_url: str | None = None
    app_env: str = "dev"
    log_level: str = "INFO"
    documents_root: str = "/opt/corredores/var/documents"
    openai_api_key: str | None = None
    openai_vision_model: str = "gpt-4o-mini"

    # SMTP — off by default until configured
    mail_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_tls: bool = True
    smtp_ssl: bool = False

    # Auto-send account statements (CLI + systemd timer)
    statement_auto_enabled: bool = False
    statement_auto_min_days_overdue: int = 1
    statement_auto_cooldown_days: int = 7
    statement_auto_only_overdue: bool = True

    # Piloto gate — single or multi env credential + signed cookie (ADR-006/007)
    auth_enabled: bool = True
    auth_username: str = "broker"
    auth_password: str | None = None
    # Optional multi-user: "user:pass|user2:pass2" or "user:pass:Display Name|..."
    auth_users: str | None = None
    auth_secret: str | None = None
    auth_cookie_name: str = "esb_session"
    auth_session_days: int = 14
    auth_display_name: str = "Broker ESecureBroker"

    # Self-serve SaaS — billing/identidad definitivos en EN1 (ADR-006)
    # Landing comercial es ESecureBroker; CTAs apuntan a EN1 cuando haya URL.
    saas_signup_enabled: bool = True
    saas_onboarding_url: str | None = None  # ej. https://app.example.com/subscribe?product=esecurebroker
    saas_contact_email: str | None = "hola@esecurebroker.etsrv.site"
    public_base_url: str = "https://esecurebroker.etsrv.site"
    stripe_secret_key: str | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: str | None = None


settings = Settings()
