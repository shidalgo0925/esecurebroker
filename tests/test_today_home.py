from datetime import date

import corredores.db as db
from corredores.db import Base
from corredores.domain import models as _models  # noqa: F401
from corredores.services.auto_e2e import run_auto_e2e_demo
from corredores.services.today_home import build_today_home


def setup_module():
    Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)


def test_today_home_hierarchy_from_domain():
    start = date(2026, 8, 10)
    # Look ahead so unpaid installments from E2E become overdue (attention + por cobrar)
    as_of = date(2026, 11, 15)
    with db.SessionLocal() as session:
        result = run_auto_e2e_demo(session, today=start)
        home = build_today_home(session, result.organization_id, today=as_of)
        session.commit()
    assert len(home.money) == 4
    assert home.money[0].title == "POR COBRAR"
    assert "noviembre" in home.date_label.lower() or "Noviembre" in home.date_label
    assert home.attention_count >= 1
    assert any(a.kind == "COBRO" for a in home.attention)
    assert home.auto_activity  # al menos cuotas en automático o pagos