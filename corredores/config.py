from pydantic_settings import BaseSettings, SettingsConfigDict

# ADR-006 — pareo de entornos (nunca cruzar DEV↔PROD).
EN1_ONBOARDING_PROD = "https://appprd.easynodeone.com/register"
EN1_ONBOARDING_DEV = "https://appdev.easynodeone.com/register"


def default_en1_onboarding_url(app_env: str | None = None) -> str:
    """EN1 register URL for this ESB environment (ADR-006)."""
    env = (app_env or "dev").strip().lower()
    if env in {"prod", "production"}:
        return EN1_ONBOARDING_PROD
    return EN1_ONBOARDING_DEV


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
    # Dueño de plataforma (SaaS): ve / entra a todas las orgs. CSV emails y/o usernames.
    # No rompe aislamiento tenant↔tenant entre corredurías normales (ADR-007).
    platform_admin_emails: str = ""
    platform_admin_usernames: str = ""

    # Self-serve SaaS — UX en ESB; SoR comercial EN1 vía API M2M (ADR-006 Ana).
    # CTAs de landing → /registro (nunca UI EN1).
    saas_signup_enabled: bool = True
    saas_onboarding_url: str | None = None  # deprecated: no usar para CTAs
    saas_contact_email: str | None = "hola@esecurebroker.etsrv.site"
    public_base_url: str = "https://esecurebroker.etsrv.site"
    stripe_secret_key: str | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: str | None = None

    # EN1 commerce M2M — solo DEV hasta certificar. Paths del contrato: CODITO (no inventar SoR).
    en1_commerce_enabled: bool = False
    en1_api_base_url: str | None = None  # ej. https://appdev.easynodeone.com
    en1_m2m_token: str | None = None

    def resolved_en1_onboarding_url(self) -> str:
        """Legacy helper; CTAs ya no usan UI EN1."""
        explicit = (self.saas_onboarding_url or "").strip()
        if explicit:
            return explicit
        return default_en1_onboarding_url(self.app_env)


settings = Settings()
