"""HOY home — lenguaje de corredor (no jerga de motores/arquitectura).

Jerarquía Ana:
  1) Dinero / salud del día
  2) Requiere tu atención
  3) El sistema trabajó por ti
  4) Oportunidades detectadas
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from corredores.domain.enums import (
    ClaimStatus,
    CoverageKnowledgeState,
    PaymentPromiseStatus,
    RenewalOpportunityStatus,
)
from corredores.domain.models import (
    AuditEvent,
    Claim,
    Installment,
    Interaction,
    Party,
    Payment,
    PaymentPlan,
    PaymentPromise,
    Policy,
    RenewalOpportunity,
    VehicleRisk,
)
from corredores.services.client_360 import build_client_360
from corredores.services.collection_bands import classify_collection_band, promise_is_broken
from corredores.services.installment_status import (
    DerivedInstallmentStatus,
    derive_installment_status,
    outstanding_balance,
)
from corredores.services.radar import build_radar


def _stamp(*, kind: str, urgency: str, title: str = "") -> str:
    t = title.upper()
    if kind == "PROMESA" or "INCUMPLIDA" in t:
        return "VENCIDA"
    if "VENCID" in t:
        return "VENCIDA"
    if urgency == "urgent" or "VENCE HOY" in t or "URGENTE" in t:
        return "URGENTE"
    return "EN CURSO"


MONTHS_ES = (
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
WEEKDAYS_ES = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)


def format_date_es(d: date) -> str:
    return f"{WEEKDAYS_ES[d.weekday()].capitalize()}, {d.day} de {MONTHS_ES[d.month]}"


def _party_name(p: Party | None) -> str:
    if p is None:
        return "Cliente"
    if p.party_type == "ORGANIZATION":
        return p.legal_name or p.trade_name or "Cliente"
    return " ".join(x for x in [p.first_name or "", p.last_name or ""] if x).strip() or "Cliente"


@dataclass
class MoneyCard:
    key: str
    amount_label: str
    title: str
    subtitle: str
    href: str


@dataclass
class AttentionCard:
    kind: str  # COBRO|RENOVACION|PROMESA|RECLAMO|OTRO
    urgency: str  # urgent|watch|normal
    title: str
    subject: str
    lines: list[str]
    stamp: str = "EN CURSO"  # URGENTE|VENCIDA|EN CURSO
    party_id: str | None = None
    policy_id: str | None = None
    claim_id: str | None = None
    renewal_id: str | None = None
    actions: list[tuple[str, str]] = field(default_factory=list)  # label, href


@dataclass
class AutoActivityLine:
    text: str
    amount_label: str | None = None


@dataclass
class OpportunityLine:
    text: str
    href: str = "/radar"


@dataclass
class TodayHome:
    as_of: date
    date_label: str
    greeting: str
    attention_count: int
    money: list[MoneyCard]
    attention: list[AttentionCard]
    auto_activity: list[AutoActivityLine]
    opportunities: list[OpportunityLine]
    auto_cuotas_managed: int = 0
    reminders_sent_today: int = 0


def build_today_home(
    session: Session,
    organization_id: str,
    *,
    today: date | None = None,
    actor_name: str = "Broker",
) -> TodayHome:
    today = today or date.today()
    radar = build_radar(session, organization_id, today=today)

    # Pagos recibidos hoy
    payments_today = (
        session.query(Payment)
        .filter(Payment.organization_id == organization_id, Payment.payment_date == today)
        .all()
    )
    paid_amt = sum((p.amount for p in payments_today), Decimal("0"))
    paid_n = len(payments_today)

    claims = session.query(Claim).filter_by(organization_id=organization_id).all()
    open_claims = [
        c
        for c in claims
        if c.status
        not in {
            ClaimStatus.CLOSED,
            ClaimStatus.SETTLED,
            ClaimStatus.REJECTED,
        }
    ]
    stuck = [
        c
        for c in open_claims
        if c.status
        in {
            ClaimStatus.DOCUMENTS_PENDING,
            ClaimStatus.UNDER_REVIEW,
            ClaimStatus.SUBMITTED,
        }
    ]

    money = [
        MoneyCard(
            key="por_cobrar",
            amount_label=f"${radar.por_cobrar.amount:,.2f}",
            title="POR COBRAR",
            subtitle=f"{radar.por_cobrar.count} con saldo vencido o por vencer",
            href="/cobranza?vencimiento=vencido",
        ),
        MoneyCard(
            key="por_renovar",
            amount_label=f"${radar.por_renovar.amount:,.2f}",
            title="POR RENOVAR",
            subtitle=f"{radar.por_renovar.count} en próximos 90 días",
            href="/renovaciones",
        ),
        MoneyCard(
            key="pagos_hoy",
            amount_label=str(paid_n),
            title="PAGOS HOY",
            subtitle=f"${paid_amt:,.2f} recibidos" if paid_n else "Sin pagos registrados hoy",
            href="/cobranza",
        ),
        MoneyCard(
            key="reclamos",
            amount_label=str(len(open_claims)),
            title="RECLAMOS",
            subtitle=f"{len(stuck)} con posible estancamiento" if stuck else "Sin reclamos abiertos trabados",
            href="/reclamos",
        ),
    ]

    attention: list[AttentionCard] = []

    # Promesas incumplidas primero
    from corredores.services.promises import refresh_overdue_promises

    refresh_overdue_promises(session, organization_id, actor_id="system")
    promises = (
        session.query(PaymentPromise)
        .filter_by(organization_id=organization_id)
        .all()
    )
    for pr in promises:
        if not promise_is_broken(pr, today=today) and pr.status != PaymentPromiseStatus.BROKEN:
            continue
        # Solo si la cuota sigue con saldo
        if pr.installment_id:
            inst_chk = session.get(Installment, pr.installment_id)
            if inst_chk is not None:
                session.refresh(inst_chk)
                if outstanding_balance(inst_chk) <= 0:
                    continue
        party = session.get(Party, pr.party_id) if pr.party_id else None
        if party is None:
            pol = session.get(Policy, pr.policy_id)
            party = session.get(Party, pol.client_party_id) if pol else None
        cobrar_href = (
            f"/cobranza/pagos/nuevo?installment_id={pr.installment_id}"
            if pr.installment_id
            else f"/cobranza/pagos/nuevo?policy_id={pr.policy_id}"
        )
        prometer_href = cobrar_href + ("&" if "?" in cobrar_href else "?") + "modo=promesa"
        attention.append(
            AttentionCard(
                kind="PROMESA",
                urgency="urgent",
                title="PROMESA INCUMPLIDA",
                subject=_party_name(party),
                lines=[
                    f"Prometió pagar ${pr.promised_amount:,.2f} el {pr.promised_date.day} de {MONTHS_ES[pr.promised_date.month]}",
                ],
                stamp=_stamp(kind="PROMESA", urgency="urgent", title="PROMESA INCUMPLIDA"),
                party_id=party.id if party else None,
                policy_id=pr.policy_id,
                actions=[
                    ("Cobrar ahora", cobrar_href),
                    ("Re-prometer", prometer_href),
                ],
            )
        )

    # Cobros vencidos / vence hoy
    plans = (
        session.query(PaymentPlan)
        .join(Policy, Policy.id == PaymentPlan.policy_id)
        .filter(Policy.organization_id == organization_id)
        .all()
    )
    auto_managed = 0
    for plan in plans:
        policy = session.get(Policy, plan.policy_id)
        party = session.get(Party, policy.client_party_id) if policy else None
        for inst in plan.installments:
            session.refresh(inst)
            bal = outstanding_balance(inst)
            status = derive_installment_status(inst, today)
            if bal <= 0 or status == DerivedInstallmentStatus.CANCELLED:
                continue
            active = (
                session.query(PaymentPromise)
                .filter_by(
                    organization_id=organization_id,
                    installment_id=inst.id,
                    status=PaymentPromiseStatus.ACTIVE,
                )
                .first()
            )
            broken = (
                session.query(PaymentPromise)
                .filter_by(
                    organization_id=organization_id,
                    installment_id=inst.id,
                    status=PaymentPromiseStatus.BROKEN,
                )
                .first()
            )
            band = classify_collection_band(
                inst, active_promise=active, broken_promise=broken, today=today
            )
            if band.value == "AUTOMATIC":
                auto_managed += 1
                continue
            if band.value == "BROKEN_PROMISE":
                continue  # already as PROMESA card
            if status not in (
                DerivedInstallmentStatus.OVERDUE,
                DerivedInstallmentStatus.DUE,
                DerivedInstallmentStatus.PARTIALLY_PAID,
            ) and band.value != "PROMISE":
                continue
            days = (today - inst.due_date).days
            if status == DerivedInstallmentStatus.OVERDUE:
                urgency = "urgent"
                title = "COBRO · URGENTE"
                detail = f"${bal:,.2f} vencidos · {days} días"
            elif status == DerivedInstallmentStatus.DUE:
                urgency = "urgent"
                title = "COBRO · VENCE HOY"
                detail = f"${bal:,.2f} vencen hoy"
            elif band.value == "PROMISE" and active:
                urgency = "watch"
                title = "PROMESA DE PAGO"
                detail = f"Promesa ${active.promised_amount:,.2f} para {active.promised_date.isoformat()}"
            else:
                urgency = "watch"
                title = "COBRO"
                detail = f"${bal:,.2f} · {status.value}"
            attention.append(
                AttentionCard(
                    kind="COBRO",
                    urgency=urgency,
                    title=title,
                    subject=_party_name(party),
                    lines=[detail, f"Cuota {inst.installment_number} · póliza {policy.policy_number or (policy.id[:8] if policy else '—')}"],
                    stamp=_stamp(kind="COBRO", urgency=urgency, title=title),
                    party_id=party.id if party else None,
                    policy_id=policy.id if policy else None,
                    actions=[
                        ("Cobrar", f"/cobranza/pagos/nuevo?installment_id={inst.id}"),
                        ("Prometer", f"/cobranza/pagos/nuevo?installment_id={inst.id}&modo=promesa"),
                    ],
                )
            )

    # Renovaciones
    horizon = today + timedelta(days=37)
    renewals = (
        session.query(RenewalOpportunity)
        .filter_by(organization_id=organization_id)
        .filter(
            RenewalOpportunity.status.in_(
                [
                    RenewalOpportunityStatus.UPCOMING,
                    RenewalOpportunityStatus.CONTACT_PENDING,
                    RenewalOpportunityStatus.CONTACTED,
                    RenewalOpportunityStatus.PROPOSAL_SENT,
                    RenewalOpportunityStatus.WAITING_CLIENT,
                    RenewalOpportunityStatus.QUOTING,
                ]
            )
        )
        .all()
    )
    for ren in renewals:
        if ren.target_date and ren.target_date > horizon:
            continue
        pol = session.get(Policy, ren.previous_policy_id)
        party = session.get(Party, pol.client_party_id) if pol else None
        vehicle = (
            session.query(VehicleRisk).filter_by(policy_id=pol.id).first() if pol else None
        )
        veh = ""
        if vehicle:
            veh = f" · {vehicle.make or ''} {vehicle.model or ''}".strip()
        days_left = (ren.target_date - today).days if ren.target_date else None
        if days_left is not None and days_left <= 14:
            urgency = "urgent" if days_left <= 7 else "watch"
        else:
            urgency = "normal"
        status_es = {
            "PROPOSAL_SENT": "propuesta enviada · sin respuesta",
            "WAITING_CLIENT": "esperando al cliente",
            "CONTACT_PENDING": "pendiente de contactar",
            "CONTACTED": "ya contactado · sigue abierta",
            "QUOTING": "en recotización",
            "UPCOMING": "próxima a vencer",
        }.get(ren.status, ren.status)
        line2 = status_es
        if days_left is not None:
            line2 = f"Vence en {days_left} días · {status_es}"
        attention.append(
            AttentionCard(
                kind="RENOVACION",
                urgency=urgency,
                title="RENOVACIÓN",
                subject=f"{_party_name(party)}{veh}",
                lines=[line2],
                stamp=_stamp(kind="RENOVACION", urgency=urgency, title="RENOVACIÓN"),
                party_id=party.id if party else None,
                policy_id=pol.id if pol else None,
                renewal_id=ren.id,
                actions=[
                    ("Ver renovación", "/renovaciones"),
                    ("Contactar", f"/clientes/{party.id}" if party else "/renovaciones"),
                ],
            )
        )

    # Reclamos estancados
    for c in stuck:
        pol = session.get(Policy, c.policy_id)
        party = session.get(Party, c.party_id or (pol.client_party_id if pol else None))
        age = None
        if c.last_activity_at:
            age = (today - c.last_activity_at.date()).days
        elif c.created_at:
            age = (today - c.created_at.date()).days
        attention.append(
            AttentionCard(
                kind="RECLAMO",
                urgency="watch" if (age or 0) < 14 else "urgent",
                title="RECLAMO · SEGUIMIENTO",
                subject=f"{_party_name(party)} · Reclamo {c.claim_number or c.id[:8]}",
                lines=[
                    f"Sin movimiento hace {age} días · posible estancamiento"
                    if age is not None
                    else f"Estado {c.status}",
                ],
                stamp=_stamp(
                    kind="RECLAMO",
                    urgency="watch" if (age or 0) < 14 else "urgent",
                    title="RECLAMO · SEGUIMIENTO",
                ),
                party_id=party.id if party else None,
                policy_id=c.policy_id,
                claim_id=c.id,
                actions=[
                    ("Ver reclamo", "/reclamos"),
                    ("Actualizar", "/reclamos"),
                ],
            )
        )

    urgency_rank = {"urgent": 0, "watch": 1, "normal": 2}
    kind_rank = {"PROMESA": 0, "COBRO": 1, "RENOVACION": 2, "RECLAMO": 3, "OTRO": 4}
    attention.sort(key=lambda a: (urgency_rank.get(a.urgency, 9), kind_rank.get(a.kind, 9)))

    # Actividad automática (hechos de dominio / auditoría del día)
    auto_activity: list[AutoActivityLine] = []
    if paid_n:
        auto_activity.append(
            AutoActivityLine(f"{paid_n} pagos registrados", f"${paid_amt:,.2f}")
        )
    audits = (
        session.query(AuditEvent)
        .filter(AuditEvent.organization_id == organization_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(40)
        .all()
    )
    reminders = 0
    docs = 0
    ren_notif = 0
    for a in audits:
        if a.created_at and a.created_at.date() != today:
            continue
        if a.action in {"REMINDER_SENT", "COLLECTION_REMINDER"}:
            reminders += 1
        if a.action in {"DOCUMENT_RECEIVED"}:
            docs += 1
        if a.action in {"RENEWAL_NOTIFIED"}:
            ren_notif += 1
    interactions_today = (
        session.query(Interaction)
        .filter(Interaction.organization_id == organization_id)
        .all()
    )
    # count created today if timestamp present
    inter_n = 0
    for it in interactions_today:
        if it.created_at and it.created_at.date() == today:
            inter_n += 1

    if reminders:
        auto_activity.append(AutoActivityLine(f"{reminders} recordatorios de cobro enviados"))
    if inter_n:
        auto_activity.append(AutoActivityLine(f"{inter_n} gestiones registradas hoy"))
    if ren_notif:
        auto_activity.append(AutoActivityLine(f"{ren_notif} renovaciones notificadas"))
    if docs:
        auto_activity.append(AutoActivityLine(f"{docs} documentos recibidos"))
    if auto_managed:
        auto_activity.append(
            AutoActivityLine(f"{auto_managed} cuotas en cobranza automática (sin intervención)")
        )

    # Oportunidades (gaps + renovaciones a recotizar) — hechos, no IA inventando $
    opportunities: list[OpportunityLine] = []
    parties = session.query(Party).filter_by(organization_id=organization_id).limit(50).all()
    gap_clients = 0
    for p in parties:
        try:
            snap = build_client_360(session, organization_id, p.id, today=today)
        except ValueError:
            continue
        if any(g.state == CoverageKnowledgeState.NO_COVERAGE_RECORDED.value for g in snap.gaps):
            gap_clients += 1
        elif any(g.state == CoverageKnowledgeState.UNKNOWN.value for g in snap.gaps) and not snap.policies:
            gap_clients += 1
    if gap_clients:
        opportunities.append(
            OpportunityLine(
                f"{gap_clients} clientes con posibles huecos de cobertura a revisar",
                "/clientes",
            )
        )
    recotizar = [
        r
        for r in renewals
        if r.status
        in {
            RenewalOpportunityStatus.QUOTING,
            RenewalOpportunityStatus.PROPOSAL_SENT,
            RenewalOpportunityStatus.WAITING_CLIENT,
        }
    ]
    if recotizar:
        amt = Decimal("0")
        for r in recotizar:
            pol = session.get(Policy, r.previous_policy_id)
            if pol and pol.annual_premium:
                amt += pol.annual_premium
        opportunities.append(
            OpportunityLine(
                f"{len(recotizar)} renovaciones conviene revisar / recotizar"
                + (f" · ${amt:,.2f}" if amt else ""),
                "/renovaciones",
            )
        )
    if radar.por_vender.count:
        opportunities.append(
            OpportunityLine(
                f"{radar.por_vender.count} oportunidades en radar por vender · ${radar.por_vender.amount:,.2f}",
                "/radar",
            )
        )

    greeting = "Buenos días"
    if today.weekday() >= 5:
        greeting = "Hola"
    # afternoon/evening without tz — keep buenos días as default operational greeting

    return TodayHome(
        as_of=today,
        date_label=format_date_es(today),
        greeting=greeting,
        attention_count=len(attention),
        money=money,
        attention=attention,
        auto_activity=auto_activity,
        opportunities=opportunities,
        auto_cuotas_managed=auto_managed,
        reminders_sent_today=reminders,
    )
