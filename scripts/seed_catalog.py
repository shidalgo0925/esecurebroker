"""Rewrite seed_catalog as thin wrapper around seed_pilot."""

from __future__ import annotations

from corredores.db import SessionLocal
from corredores.services.seed_pilot import seed_pilot


def main() -> None:
    with SessionLocal() as session:
        report = seed_pilot(session)
        session.commit()
        print("seed OK", report)


if __name__ == "__main__":
    main()
