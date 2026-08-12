# ADR-008 F6 — ESB GO Producer (DEV)

## Goal

Certificar contrato Mobile v1 para rol **PRODUCER** con `scope=ASSIGNED_PORTFOLIO` (sin API v2).

## Delivered

- `/me`: `role=PRODUCER`, `scope=ASSIGNED_PORTFOLIO`, `producer_profile_id`, seats compound
- Listas `/customers` `/policies` + `/today` + detail/360 scoped (F3) — E2E F6
- Anti-IDOR 404 cross-portfolio / cross-org
- Docs `MOBILE_API_V1.md` actualizado
- Seed DEV: `producer.alfa@example.invalid` + PRIMARY sobre póliza Alfa
- Tests: `tests/test_mobile_producer_f6.py`

## Seed

```bash
cd /opt/corredores-dev
ESB_DEV_SEED_PASSWORD=… PYTHONPATH=. .venv/bin/python scripts/seed_mobile_dev_users.py
```

## Not in F6

- Flutter/LOCAL client changes (LOCAL repo)
- FCM / offline / uploads
- SECONDARY assignments
- PROD deploy
