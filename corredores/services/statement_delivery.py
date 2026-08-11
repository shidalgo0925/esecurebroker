"""Account statement delivery — print HTML, email, and automatic batch send.

Uses Domain Truth balances from account_cxc (never invents overdue).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from corredores.config import settings
from corredores.domain.enums import DataSource
from corredores.domain.models import Organization, Party, StatementDelivery
from corredores.services.account_cxc import (
    AccountStatement,
    build_account_statement,
    build_morosity_analysis,
)
from corredores.services.interactions import log_interaction
from corredores.services.mail import mail_configured, send_email

_TEMPLATES = Path(__file__).resolve().parent.parent / "web" / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    autoescape=select_autoescape(["html", "xml"]),
)
_env.filters["money"] = lambda v: f"{Decimal(str(v)):.2f}"


@dataclass
class DeliveryOutcome:
    party_id: str
    party_name: str
    status: str  # SENT|SKIPPED|FAILED
    detail: str
    to_email: str | None = None


@dataclass
class AutoSendReport:
    as_of: date
    dry_run: bool
    candidates: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0
    outcomes: list[DeliveryOutcome] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "dry_run": self.dry_run,
            "candidates": self.candidates,
            "sent": self.sent,
            "skipped": self.skipped,
            "failed": self.failed,
            "outcomes": [
                {
                    "party_id": o.party_id,
                    "party_name": o.party_name,
                    "status": o.status,
                    "detail": o.detail,
                    "to_email": o.to_email,
                }
                for o in self.outcomes
            ],
        }


def _print_css() -> str:
    css_path = Path(__file__).resolve().parent.parent / "web" / "static" / "print.css"
    try:
        return css_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def render_statement_html(
    stmt: AccountStatement,
    *,
    org_name: str,
    view: str = "estado",
    auto_print: bool = False,
    for_email: bool = False,
) -> str:
    """view: estado | movimientos. for_email inlines CSS (no /static link)."""
    tpl = _env.get_template("print_estado_cuenta.html")
    return tpl.render(
        stmt=stmt,
        org_name=org_name,
        view=view,
        auto_print=auto_print and not for_email,
        for_email=for_email,
        embedded_css=_print_css() if for_email else "",
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def render_morosity_html(
    analysis,
    *,
    org_name: str,
    rows: list | None = None,
    aging: str = "",
    auto_print: bool = False,
) -> str:
    tpl = _env.get_template("print_morosidad.html")
    return tpl.render(
        analysis=analysis,
        org_name=org_name,
        rows=rows if rows is not None else analysis.rows,
        aging=aging,
        auto_print=auto_print,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def _text_summary(stmt: AccountStatement, org_name: str) -> str:
    return (
        f"Estado de cuenta — {org_name}\n"
        f"Cliente: {stmt.party_name}\n"
        f"Al: {stmt.as_of}\n"
        f"Saldo abierto: ${stmt.open_balance:.2f}\n"
        f"Vencido: ${stmt.overdue_balance:.2f} ({stmt.overdue_count} cuotas)\n"
        f"\nEste mensaje incluye el detalle en HTML.\n"
    )


def _log_delivery(
    session: Session,
    *,
    organization_id: str,
    party_id: str,
    to_email: str | None,
    status: str,
    trigger: str,
    stmt: AccountStatement,
    detail: str,
    actor_id: str | None,
) -> StatementDelivery:
    row = StatementDelivery(
        organization_id=organization_id,
        party_id=party_id,
        channel="EMAIL",
        trigger=trigger,
        to_email=to_email,
        status=status,
        as_of=stmt.as_of,
        overdue_balance=stmt.overdue_balance,
        open_balance=stmt.open_balance,
        detail=detail[:2000] if detail else None,
        actor_id=actor_id,
    )
    session.add(row)
    session.flush()
    return row


def send_account_statement(
    session: Session,
    organization_id: str,
    party_id: str,
    *,
    to_email: str | None = None,
    trigger: str = "MANUAL",
    actor_id: str | None = None,
    today: date | None = None,
) -> DeliveryOutcome:
    """Build statement from Domain Truth and email it. Logs StatementDelivery + Interaction."""
    org = session.get(Organization, organization_id)
    org_name = org.name if org else "ESecureBroker"
    party = session.get(Party, party_id)
    if party is None or party.organization_id != organization_id:
        return DeliveryOutcome(party_id, "—", "FAILED", "cliente no encontrado")

    name = (
        party.legal_name or party.trade_name
        if getattr(party, "party_type", None) == "ORGANIZATION"
        else " ".join(x for x in [party.first_name or "", party.last_name or ""] if x).strip()
    ) or party_id

    stmt = build_account_statement(session, organization_id, party_id, today=today)
    dest = (to_email or party.email or "").strip()
    if not dest:
        _log_delivery(
            session,
            organization_id=organization_id,
            party_id=party_id,
            to_email=None,
            status="SKIPPED",
            trigger=trigger,
            stmt=stmt,
            detail="sin correo en cliente",
            actor_id=actor_id,
        )
        return DeliveryOutcome(party_id, name, "SKIPPED", "sin correo en cliente", None)

    if not mail_configured():
        _log_delivery(
            session,
            organization_id=organization_id,
            party_id=party_id,
            to_email=dest,
            status="FAILED",
            trigger=trigger,
            stmt=stmt,
            detail="SMTP no configurado",
            actor_id=actor_id,
        )
        return DeliveryOutcome(party_id, name, "FAILED", "SMTP no configurado", dest)

    html = render_statement_html(stmt, org_name=org_name, view="estado", for_email=True)
    subject = f"Estado de cuenta — {name} — {stmt.as_of}"
    result = send_email(
        to_email=dest,
        subject=subject,
        html_body=html,
        text_body=_text_summary(stmt, org_name),
    )
    status = "SENT" if result.ok else "FAILED"
    _log_delivery(
        session,
        organization_id=organization_id,
        party_id=party_id,
        to_email=dest,
        status=status,
        trigger=trigger,
        stmt=stmt,
        detail=result.detail,
        actor_id=actor_id,
    )
    if result.ok:
        log_interaction(
            session,
            organization_id=organization_id,
            party_id=party_id,
            channel="EMAIL",
            summary=f"Estado de cuenta enviado a {dest} (saldo abierto ${stmt.open_balance:.2f}, vencido ${stmt.overdue_balance:.2f})",
            actor_id=actor_id,
            data_source=DataSource.SYSTEM_GENERATED if trigger == "AUTO" else DataSource.MANUAL,
        )
    return DeliveryOutcome(party_id, name, status, result.detail, dest)


def _last_successful_send(
    session: Session, organization_id: str, party_id: str
) -> StatementDelivery | None:
    return (
        session.query(StatementDelivery)
        .filter_by(
            organization_id=organization_id,
            party_id=party_id,
            status="SENT",
            channel="EMAIL",
        )
        .order_by(StatementDelivery.created_at.desc())
        .first()
    )


def run_auto_statement_send(
    session: Session,
    organization_id: str,
    *,
    dry_run: bool = False,
    today: date | None = None,
    actor_id: str | None = "system:auto-statements",
) -> AutoSendReport:
    """Send statements to clients with overdue balance, respecting cooldown and mail config."""
    today = today or date.today()
    report = AutoSendReport(as_of=today, dry_run=dry_run)

    if not settings.statement_auto_enabled and not dry_run:
        report.outcomes.append(
            DeliveryOutcome("—", "—", "SKIPPED", "STATEMENT_AUTO_ENABLED=false")
        )
        report.skipped = 1
        return report

    analysis = build_morosity_analysis(session, organization_id, today=today)
    # Unique parties with overdue from Domain Truth
    seen: set[str] = set()
    party_ids: list[str] = []
    for row in analysis.rows:
        pid = row["party_id"]
        if pid not in seen:
            seen.add(pid)
            party_ids.append(pid)

    cooldown = timedelta(days=max(1, settings.statement_auto_cooldown_days))
    min_days = max(1, settings.statement_auto_min_days_overdue)
    now = datetime.now(timezone.utc)

    for party_id in party_ids:
        stmt = build_account_statement(session, organization_id, party_id, today=today)
        party = session.get(Party, party_id)
        name = stmt.party_name
        report.candidates += 1

        if settings.statement_auto_only_overdue and stmt.overdue_balance <= 0:
            report.skipped += 1
            report.outcomes.append(
                DeliveryOutcome(party_id, name, "SKIPPED", "sin saldo vencido", party.email if party else None)
            )
            continue

        max_days = max((r["days_overdue"] for r in stmt.installments if r.get("days_overdue")), default=0)
        if max_days < min_days:
            report.skipped += 1
            report.outcomes.append(
                DeliveryOutcome(
                    party_id,
                    name,
                    "SKIPPED",
                    f"mora máxima {max_days}d < mínimo {min_days}d",
                    party.email if party else None,
                )
            )
            continue

        dest = (party.email if party else None) or ""
        if not dest.strip():
            report.skipped += 1
            report.outcomes.append(
                DeliveryOutcome(party_id, name, "SKIPPED", "sin correo", None)
            )
            if not dry_run:
                _log_delivery(
                    session,
                    organization_id=organization_id,
                    party_id=party_id,
                    to_email=None,
                    status="SKIPPED",
                    trigger="AUTO",
                    stmt=stmt,
                    detail="sin correo",
                    actor_id=actor_id,
                )
            continue

        last = _last_successful_send(session, organization_id, party_id)
        if last and last.created_at:
            created = last.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if now - created < cooldown:
                report.skipped += 1
                report.outcomes.append(
                    DeliveryOutcome(
                        party_id,
                        name,
                        "SKIPPED",
                        f"cooldown ({settings.statement_auto_cooldown_days}d) — último envío {last.created_at}",
                        dest,
                    )
                )
                continue

        if dry_run:
            report.sent += 1
            report.outcomes.append(
                DeliveryOutcome(
                    party_id,
                    name,
                    "SENT",
                    f"dry-run → {dest} (vencido ${stmt.overdue_balance:.2f})",
                    dest,
                )
            )
            continue

        outcome = send_account_statement(
            session,
            organization_id,
            party_id,
            to_email=dest,
            trigger="AUTO",
            actor_id=actor_id,
            today=today,
        )
        report.outcomes.append(outcome)
        if outcome.status == "SENT":
            report.sent += 1
        elif outcome.status == "SKIPPED":
            report.skipped += 1
        else:
            report.failed += 1

    return report


def recent_deliveries(
    session: Session, organization_id: str, *, limit: int = 40
) -> list[StatementDelivery]:
    return (
        session.query(StatementDelivery)
        .filter_by(organization_id=organization_id)
        .order_by(StatementDelivery.created_at.desc())
        .limit(limit)
        .all()
    )
