"""Assisted Excel import — Domain Truth from structured rows (D-02/D-09/D-16).

Rules:
- Coexistence: upsert by keys; never wipe MANUAL operational rows.
- Colors never become OVERDUE; green/PAGADO may create Payment facts only.
- AUTO EMITIDO → operational Policy+VehicleRisk+PaymentPlan.
- Non-AUTO → historical Policy (read path) when EMITIDO; else Submission only.
- Logs/reports use row numbers only — never dump PII.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from corredores.domain.enums import (
    DataSource,
    DueDateSource,
    PartyRoleType,
    PartyType,
    PolicyStatus,
    SubmissionStatus,
    TermSource,
)
from corredores.domain.models import (
    AuditEvent,
    Carrier,
    Installment,
    InsuranceLine,
    Organization,
    Party,
    PartyRole,
    PaymentPlan,
    Policy,
    PolicyTerm,
    Submission,
    Task,
    VehicleRisk,
)
from corredores.services.auto_e2e import ensure_auto_line, suggest_policy_term
from corredores.services.payments import record_payment


LINE_ALIASES: dict[str, str] = {
    "AUTOMÓVIL": "AUTO",
    "AUTOMOVIL": "AUTO",
    "AUTO": "AUTO",
    "MOTO": "MOTO",
    "ASIENTO": "AP",
    "ACCIDENTES PERSONALES": "AP",
    "VIDA INDIVIDUAL": "VIDA",
    "SALUD INDIVIDUAL": "SALUD",
    "MULTIRIESGO RESIDENCIAL": "HOGAR",
    "MULTIRIESGO COMERCIAL": "COMERCIAL",
    "INCENDIO Y ALIADAS": "INCENDIO",
    "INCENDIO": "INCENDIO",
    "TRANSPORTE DE CARGA TERRESTRE": "TRANSPORTE",
    "TRANSPORTE": "TRANSPORTE",
    "RC": "RC",
    "RESPONSABILIDAD CIVIL": "RC",
}

EXCEL_STATUS_MAP: dict[str, str] = {
    "COTIZADO": SubmissionStatus.QUOTED,
    "EN PROCESO": SubmissionStatus.ISSUING,
    "EMITIDO": SubmissionStatus.ISSUED,
    "ANULADO": SubmissionStatus.CANCELLED,
    "CANCELACION": SubmissionStatus.CANCELLED,
    "DECLINADO": SubmissionStatus.DECLINED,
    "PENDIENTE": SubmissionStatus.DRAFT,
    "RENOVACION": SubmissionStatus.QUOTED,
}


def _norm(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().upper())


def _dec(value: object | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _as_date(value: object | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


@dataclass
class PartyImportRow:
    row_number: int
    first_name: str | None = None
    last_name: str | None = None
    national_id: str | None = None
    phone: str | None = None
    district: str | None = None
    address: str | None = None
    birth_date: date | None = None
    party_type: str = PartyType.PERSON


@dataclass
class EmissionImportRow:
    row_number: int
    excel_status: str
    carrier_name: str | None = None
    risk_label: str | None = None
    coverage_type: str | None = None
    contractor_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    national_id: str | None = None
    policy_number: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    plate: str | None = None
    vehicle_type: str | None = None
    usage: str | None = None
    premium: Decimal | None = None
    annual_premium: Decimal | None = None
    num_payments: int | None = None
    installment_amounts: list[Decimal | None] = field(default_factory=list)
    # True = Excel green / paid hint — may create Payment; False/None never invents OVERDUE
    installment_paid_hints: list[bool | None] = field(default_factory=list)
    payment_form: str | None = None
    pago_column: str | None = None  # NORMAL|PAGADO|ATRASADO|CANCELADO — not status machine
    effective_date: date | None = None
    expiration_date: date | None = None
    registro_date: date | None = None


@dataclass
class ImportReport:
    parties_upserted: int = 0
    submissions_created: int = 0
    policies_created: int = 0
    policies_skipped_existing: int = 0
    installments_created: int = 0
    payments_from_hint: int = 0
    tasks_created: int = 0
    warnings: list[str] = field(default_factory=list)
    rows_processed: int = 0

    def as_dict(self) -> dict:
        return {
            "parties_upserted": self.parties_upserted,
            "submissions_created": self.submissions_created,
            "policies_created": self.policies_created,
            "policies_skipped_existing": self.policies_skipped_existing,
            "installments_created": self.installments_created,
            "payments_from_hint": self.payments_from_hint,
            "tasks_created": self.tasks_created,
            "warnings": list(self.warnings),
            "rows_processed": self.rows_processed,
        }


def ensure_line(session: Session, code: str, name: str | None = None) -> InsuranceLine:
    if code == "AUTO":
        return ensure_auto_line(session)
    row = session.query(InsuranceLine).filter_by(code=code).one_or_none()
    if row is None:
        row = InsuranceLine(code=code, name=name or code, operational_in_p0=False)
        session.add(row)
        session.flush()
    return row


def ensure_carrier(session: Session, organization_id: str, name: str) -> Carrier:
    code = re.sub(r"[^A-Z0-9]+", "", _norm(name))[:40] or "UNK"
    row = (
        session.query(Carrier)
        .filter_by(organization_id=organization_id, code=code)
        .one_or_none()
    )
    if row is None:
        row = Carrier(organization_id=organization_id, code=code, name=name.strip())
        session.add(row)
        session.flush()
    return row


def upsert_party(
    session: Session,
    *,
    organization_id: str,
    row: PartyImportRow | EmissionImportRow,
    report: ImportReport,
) -> Party | None:
    nid = (row.national_id or "").strip() or None
    first = (getattr(row, "first_name", None) or "").strip() or None
    last = (getattr(row, "last_name", None) or "").strip() or None
    if not nid and not first and not last:
        report.warnings.append(f"row {row.row_number}: party skipped (no identity keys)")
        return None

    party: Party | None = None
    if nid:
        party = (
            session.query(Party)
            .filter_by(organization_id=organization_id, national_id=nid)
            .one_or_none()
        )
    if party is None and first and last:
        party = (
            session.query(Party)
            .filter_by(organization_id=organization_id, first_name=first, last_name=last)
            .one_or_none()
        )
    if party is None:
        party = Party(
            organization_id=organization_id,
            party_type=getattr(row, "party_type", PartyType.PERSON) or PartyType.PERSON,
            first_name=first,
            last_name=last,
            national_id=nid,
            phone=getattr(row, "phone", None),
            district=getattr(row, "district", None),
            address=getattr(row, "address", None),
            birth_date=getattr(row, "birth_date", None),
            data_source=DataSource.EXCEL_IMPORT,
        )
        session.add(party)
        session.flush()
        report.parties_upserted += 1
    else:
        # Fill blanks only — do not overwrite richer MANUAL data.
        if not party.phone and getattr(row, "phone", None):
            party.phone = row.phone  # type: ignore[attr-defined]
        if not party.district and getattr(row, "district", None):
            party.district = row.district  # type: ignore[attr-defined]
        if not party.address and getattr(row, "address", None):
            party.address = row.address  # type: ignore[attr-defined]
        if not party.birth_date and getattr(row, "birth_date", None):
            party.birth_date = row.birth_date  # type: ignore[attr-defined]
        report.parties_upserted += 1
    return party


def map_line_code(risk_label: str | None) -> str | None:
    key = _norm(risk_label)
    return LINE_ALIASES.get(key)


def map_submission_status(excel_status: str) -> str | None:
    return EXCEL_STATUS_MAP.get(_norm(excel_status))


def import_parties(
    session: Session,
    *,
    organization_id: str,
    rows: Sequence[PartyImportRow],
    report: ImportReport | None = None,
) -> ImportReport:
    report = report or ImportReport()
    for row in rows:
        report.rows_processed += 1
        party = upsert_party(session, organization_id=organization_id, row=row, report=report)
        if party is None:
            continue
        existing = (
            session.query(PartyRole)
            .filter(
                PartyRole.organization_id == organization_id,
                PartyRole.party_id == party.id,
                PartyRole.role_type == PartyRoleType.CLIENT,
                PartyRole.context_type == "GLOBAL",
                PartyRole.context_id.is_(None),
            )
            .one_or_none()
        )
        if existing is None:
            session.add(
                PartyRole(
                    organization_id=organization_id,
                    party_id=party.id,
                    role_type=PartyRoleType.CLIENT,
                    context_type="GLOBAL",
                    context_id=None,
                )
            )
    return report


def _installment_schedule(
    *,
    amounts: Sequence[Decimal | None],
    num_payments: int | None,
    annual_premium: Decimal | None,
    premium: Decimal | None,
    start: date,
) -> list[tuple[int, date, Decimal]]:
    cleaned = [(i + 1, a) for i, a in enumerate(amounts) if a is not None and a > 0]
    if cleaned:
        return [(n, start + relativedelta(months=n - 1), a) for n, a in cleaned]

    total = annual_premium or premium
    count = num_payments or 1
    if total is None or count < 1:
        return []
    base = (total / count).quantize(Decimal("0.01"))
    rows: list[tuple[int, date, Decimal]] = []
    allocated = Decimal("0")
    for i in range(1, count + 1):
        amt = total - allocated if i == count else base
        allocated += amt
        rows.append((i, start + relativedelta(months=i - 1), amt))
    return rows


def import_emissions(
    session: Session,
    *,
    organization_id: str,
    rows: Sequence[EmissionImportRow],
    actor_id: str = "excel-import",
    report: ImportReport | None = None,
) -> ImportReport:
    report = report or ImportReport()
    for row in rows:
        report.rows_processed += 1
        status_key = _norm(row.excel_status)

        # D-10: GESTIONADO / CAMBIO DE CORREDOR are process hooks, not policy status.
        if status_key in {"GESTIONADO", "CAMBIO DE CORREDOR"}:
            party = upsert_party(session, organization_id=organization_id, row=row, report=report)
            session.add(
                Task(
                    organization_id=organization_id,
                    title=f"Excel status follow-up ({status_key})",
                    status="OPEN",
                    party_id=party.id if party else None,
                    related_type="EXCEL_ROW",
                    related_id=str(row.row_number),
                    actor_id=actor_id,
                )
            )
            report.tasks_created += 1
            continue

        sub_status = map_submission_status(row.excel_status)
        if sub_status is None:
            report.warnings.append(f"row {row.row_number}: unknown status skipped")
            continue

        line_code = map_line_code(row.risk_label) or "AUTO"
        line = ensure_line(session, line_code, name=row.risk_label)
        if not row.carrier_name:
            report.warnings.append(f"row {row.row_number}: missing carrier")
            continue
        carrier = ensure_carrier(session, organization_id, row.carrier_name)
        party = upsert_party(session, organization_id=organization_id, row=row, report=report)
        if party is None:
            continue

        submission = Submission(
            organization_id=organization_id,
            client_party_id=party.id,
            carrier_id=carrier.id,
            insurance_line_id=line.id,
            status=sub_status,
            notes=f"import row {row.row_number}",
            data_source=DataSource.EXCEL_IMPORT,
        )
        session.add(submission)
        session.flush()
        report.submissions_created += 1

        if sub_status != SubmissionStatus.ISSUED:
            continue

        policy_number = (row.policy_number or "").strip() or None
        if policy_number:
            existing = (
                session.query(Policy)
                .filter_by(
                    organization_id=organization_id,
                    carrier_id=carrier.id,
                    policy_number=policy_number,
                )
                .one_or_none()
            )
            if existing is not None:
                report.policies_skipped_existing += 1
                report.warnings.append(f"row {row.row_number}: policy exists, coexistence skip")
                continue

        eff = row.effective_date or row.registro_date or date.today()
        exp_in = row.expiration_date
        eff, exp, term_src = suggest_policy_term(
            eff,
            expiration_date=exp_in,
            term_source=TermSource.IMPORT if exp_in else TermSource.SYSTEM_GENERATED,
        )
        if exp_in:
            term_src = TermSource.IMPORT

        policy_status = PolicyStatus.ACTIVE
        if status_key in {"ANULADO", "CANCELACION"}:
            policy_status = PolicyStatus.CANCELLED

        policy = Policy(
            organization_id=organization_id,
            submission_id=submission.id,
            carrier_id=carrier.id,
            insurance_line_id=line.id,
            policy_number=policy_number,
            status=policy_status,
            client_party_id=party.id,
            net_premium=row.premium,
            gross_premium=row.premium,
            annual_premium=row.annual_premium or row.premium,
            data_source=DataSource.EXCEL_IMPORT,
        )
        session.add(policy)
        session.flush()
        session.add(
            PolicyTerm(
                policy_id=policy.id,
                effective_date=eff,
                expiration_date=exp,
                term_source=term_src,
            )
        )
        report.policies_created += 1

        if line.code == "AUTO":
            session.add(
                VehicleRisk(
                    organization_id=organization_id,
                    submission_id=submission.id,
                    policy_id=policy.id,
                    make=row.make,
                    model=row.model,
                    year=row.year,
                    plate=row.plate,
                    vehicle_type=row.vehicle_type,
                    usage=_norm(row.usage) or None,
                )
            )

        schedule = _installment_schedule(
            amounts=row.installment_amounts,
            num_payments=row.num_payments,
            annual_premium=row.annual_premium,
            premium=row.premium,
            start=eff,
        )
        if schedule:
            plan = PaymentPlan(policy_id=policy.id, confirmed=True, notes="excel import")
            session.add(plan)
            session.flush()
            for n, due, amount in schedule:
                inst = Installment(
                    payment_plan_id=plan.id,
                    installment_number=n,
                    due_date=due,
                    amount=amount,
                    due_date_source=DueDateSource.IMPORT,
                )
                session.add(inst)
                session.flush()
                report.installments_created += 1

                paid_hint = False
                if n - 1 < len(row.installment_paid_hints):
                    paid_hint = bool(row.installment_paid_hints[n - 1])
                if _norm(row.pago_column) == "PAGADO" and n == 1:
                    paid_hint = True
                # D-02: never map red/ATRASADO → OVERDUE; only optional Payment from green/PAGADO.
                if paid_hint:
                    record_payment(
                        session,
                        organization_id=organization_id,
                        policy_id=policy.id,
                        amount=amount,
                        payment_date=due,
                        installment_id=inst.id,
                        actor_id=actor_id,
                        method="EXCEL_HINT",
                        reference=f"import_row_{row.row_number}_inst_{n}",
                        data_source=DataSource.EXCEL_IMPORT,
                    )
                    report.payments_from_hint += 1

        session.add(
            AuditEvent(
                organization_id=organization_id,
                actor_id=actor_id,
                entity_type="Policy",
                entity_id=policy.id,
                action="EXCEL_IMPORTED",
                detail_json=json.dumps(
                    {
                        "row": row.row_number,
                        "line": line.code,
                        "operational_p0": line.operational_in_p0,
                    }
                ),
            )
        )
    return report


def run_assisted_import(
    session: Session,
    *,
    org_name: str = "ESecureBroker",
    parties: Iterable[PartyImportRow] = (),
    emissions: Iterable[EmissionImportRow] = (),
    actor_id: str = "excel-import",
) -> ImportReport:
    org = session.query(Organization).filter_by(name=org_name).one_or_none()
    if org is None:
        legacy = session.query(Organization).filter_by(name="Piloto Corredores").one_or_none()
        if legacy is not None:
            legacy.name = org_name
            org = legacy
        else:
            org = Organization(name=org_name)
            session.add(org)
            session.flush()

    report = ImportReport()
    import_parties(session, organization_id=org.id, rows=list(parties), report=report)
    import_emissions(
        session,
        organization_id=org.id,
        rows=list(emissions),
        actor_id=actor_id,
        report=report,
    )
    session.flush()
    return report
