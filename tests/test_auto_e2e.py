from datetime import date
from decimal import Decimal

from corredores.db import Base, SessionLocal, engine
from corredores.domain import models as _models  # noqa: F401
from corredores.services.auto_e2e import (
    collection_snapshot,
    generate_proposed_installments,
    run_auto_e2e_demo,
    suggest_policy_term,
)
from corredores.domain.enums import TermSource


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_suggest_term_default_one_year():
    eff = date(2026, 1, 15)
    e, x, src = suggest_policy_term(eff)
    assert e == eff
    assert x == date(2027, 1, 15)
    assert src == TermSource.SYSTEM_GENERATED


def test_suggest_term_manual_expiration():
    eff = date(2026, 1, 15)
    e, x, src = suggest_policy_term(eff, expiration_date=date(2026, 6, 30), term_source=TermSource.MANUAL)
    assert x == date(2026, 6, 30)
    assert src == TermSource.MANUAL


def test_proposed_installments_sum():
    rows = generate_proposed_installments(
        start_due=date(2026, 1, 1), count=10, total_amount=Decimal("1000.00")
    )
    assert len(rows) == 10
    assert sum((a for _, _, a in rows), Decimal("0")) == Decimal("1000.00")


def test_auto_e2e_backbone():
    with SessionLocal() as session:
        result = run_auto_e2e_demo(session, today=date(2026, 8, 10))
        snap = collection_snapshot(session, result.policy_id, today=date(2026, 8, 10))
    assert result.policy_id
    assert result.commission_id
    assert result.renewal_id
    assert len(result.installment_ids) == 12
    assert snap[0]["status"] == "PAID"
    assert snap[1]["status"] in {"PENDING", "DUE", "OVERDUE"}
