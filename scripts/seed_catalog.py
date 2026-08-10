"""Seed catalog lines — AUTO operational in P0; others catalog-only."""

from __future__ import annotations

from corredores.db import SessionLocal
from corredores.domain.models import InsuranceLine, Organization


LINES = [
    ("AUTO", "Automóvil", True),
    ("MOTO", "Moto", False),
    ("HOGAR", "Multirriesgo residencial", False),
    ("COMERCIAL", "Multirriesgo comercial", False),
    ("RC", "Responsabilidad civil", False),
    ("INCENDIO", "Incendio y aliadas", False),
    ("TRANSPORTE", "Transporte", False),
    ("VIDA", "Vida individual", False),
    ("SALUD", "Salud individual", False),
    ("AP", "Accidentes personales", False),
]


def main() -> None:
    with SessionLocal() as session:
        org = session.query(Organization).filter_by(name="Piloto Corredores").one_or_none()
        if org is None:
            org = Organization(name="Piloto Corredores")
            session.add(org)
            session.flush()
        for code, name, p0 in LINES:
            row = session.query(InsuranceLine).filter_by(code=code).one_or_none()
            if row is None:
                session.add(InsuranceLine(code=code, name=name, operational_in_p0=p0))
            else:
                row.name = name
                row.operational_in_p0 = p0
        session.commit()
        print("seed OK org=", org.id)


if __name__ == "__main__":
    main()
