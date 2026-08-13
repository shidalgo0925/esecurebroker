# ADR-009 — Carrier Incentive Plans / Beneficios por Producción y Cobranza

**Producto:** ESecureBroker  
**Estado:** ACCEPTED / GO (DEV)  
**Prioridad:** P0  
**Fecha:** 2026-08-13  
**PROD:** NO TOCAR  

## Canónico (Easy-Wiki)

**[ADR-009_carrier_incentive_plans.md](file:///opt/easynodeone/Easy-Wiki/05_Proyectos/corredores-seguros/adr/ADR-009_carrier_incentive_plans.md)**

```
/opt/easynodeone/Easy-Wiki/05_Proyectos/corredores-seguros/adr/ADR-009_carrier_incentive_plans.md
```

Pointer local: `docs/ADR-009_POINTER.md`.

## Summary

Domain **Carrier Incentive Plans** — Organization → Carrier → IncentivePlan.  
Lifecycle: **ESTIMATED → EARNED** (ESB calc) vs **CLAIMED → RECOGNIZED → PAID** (settlement; never auto).  
Official accumulators use **CONFIRMED** carrier-backed txns only. Reversals never DELETE.

## Implementation gate

| Fase | Estado DEV |
|------|------------|
| F1 Schema | DONE |
| F2 Calculation Engine | DONE |
| F3 Settlement | DONE |
| F4 UI | DONE (`/aseguradoras/{id}/beneficios`) |
| F5 Hoy | DONE (attention cards, org scope) |
| F6 Carrier API feed | Prepared / not blocking P0 |

## Key paths

- Models: `domain/models.py` (`CarrierIncentive*`)
- Constants: `domain/incentive_constants.py`
- Service: `services/carrier_incentives.py`
- UI: `web/carrier_incentive_routes.py`
- Migration: `alembic/versions/d8e9f0a1b2c3_adr009_carrier_incentive_plans.py`
- Tests: `tests/test_carrier_incentives_adr009.py`
- Permissions: `incentives:read` / `incentives:manage` (OWNER/ADMIN; not PRODUCER)

## Invariants

See accepted ADR §21 (wiki). Do not mix with ADR-008 RBAC semantics or ordinary `CommissionRule`.
