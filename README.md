# Corredores — P0 AUTO E2E

Producto asociado a EN1, **aplicación independiente** (ADR-005).

| Dimensión | Valor |
|-----------|--------|
| **Path** | `/opt/corredores` |
| **Fase** | P0 — Dominio AUTO end-to-end |
| **DB** | Propia (`DATABASE_URL`; default SQLite local de desarrollo) |
| **EN1** | Solo abstracciones (`Actor`, `OrganizationContext`, `EntitlementChecker`) hasta ADR-006 |

## Flujo a certificar

```text
Cliente → Submission → AUTO (VehicleRisk) → Policy (+ PolicyTerm)
  → PaymentPlan → Installments → Payment → Saldo/Morosidad
  → Comisión → RenewalOpportunity
```

Sin Excel como fuente operativa.

## No incluido en P0

APIs carriers · IA · WhatsApp · portal completo · siniestros completos · personas operativas · integración real EN1 · optimizer 360 · P1/P2 automation.

## Quick start (dev)

```bash
cd /opt/corredores
source .venv/bin/activate   # o crear venv + pip install -r requirements.txt
export PYTHONPATH=.
python -m corredores.cli doctor
python -m corredores.cli init-db
python -m corredores.cli run-e2e   # columna vertebral AUTO
python -m corredores.cli today
python -m corredores.cli radar
python -m corredores.cli client360 # requiere party_id (tras run-e2e)
pytest -q
python scripts/p0_certify.py       # E2E + 360 + Radar + Hoy + Claim + NBA
```

CLI: `doctor | init-db | run-e2e | today | radar | client360`

## Flujo certificado por `run-e2e`

Cliente → Submission → VehicleRisk → Policy/PolicyTerm → PaymentPlan → Installments → Payment → Cobranza derivada → Comisión (snapshot) → Renovación → Auditoría

`p0_certify.py` añade Cliente 360°, Radar, Hoy, transición Claim y decisión NBA.

## Docs de arquitectura

`/opt/easynodeone/Easy-Wiki/05_Proyectos/corredores-seguros/`  
(EN1 permanece en `/opt/easynodeone/app` — no tocar.)
