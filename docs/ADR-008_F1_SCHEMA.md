# ADR-008 F1 Schema (DEV)

## Decisiones F1

| Tema | Decisión |
|------|----------|
| default_producer | Columna opcional `parties.default_producer_profile_id` — no ownership |
| PartyRole AGENT | Al crear ProducerProfile (`sync_agent_party_role=True`): asegura `PartyRole(AGENT, GLOBAL)`. No toca EXECUTIVE/REFERRER/CLIENT. No crea Membership. |
| PRIMARY vigente | Índice único parcial `uq_portfolio_primary_policy_active` + servicio `assign_policy_primary` |
| Roles | Constantes en `corredores/domain/membership_roles.py` — sin enforcement RBAC |

## Tablas

- `producer_profiles`
- `portfolio_assignments`
- `parties.default_producer_profile_id` (+ FK en Alembic Postgres)

## Migración

`alembic/versions/f8a901b2c3d4_adr008_f1_producer_portfolio.py`

## No incluido (F2+)

AccessContext, scope filtering, Admin UI, seats, Mobile scope change.
