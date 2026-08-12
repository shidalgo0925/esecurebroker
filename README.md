# ESecureBroker — P0 AUTO E2E

Producto comercial **ESecureBroker** (corredores de seguros), asociado a EN1, **aplicación independiente** (ADR-005).

| Dimensión | Valor |
|-----------|--------|
| **Nombre** | **ESecureBroker** |
| **Fase** | P0 — Dominio AUTO end-to-end |
| **EN1** | Solo abstracciones (`Actor`, `OrganizationContext`, `EntitlementChecker`) hasta ADR-006 |

## Entornos (prod / dev)

| | **PROD** | **DEV** |
|---|---|---|
| Path | `/opt/corredores` | `/opt/corredores-dev` |
| Host | https://esecurebroker.etsrv.site | https://esecurebroker-dev.etsrv.site |
| Puerto local | `127.0.0.1:8091` | `127.0.0.1:8092` |
| Systemd | `esecurebroker.service` | `esecurebroker-dev.service` |
| `APP_ENV` | `prod` | `dev` |
| DB | Postgres `corredores` | Postgres `corredores_dev` |
| Cookie | `esb_session` | `esb_session_dev` |
| Statements timer | `esecurebroker-statements.timer` | **no** (evitar mails reales) |
| Alta / checkout (UX) | `/registro` → `/checkout` (ESB) | `/registro` → `/checkout` (ESB) |
| SoR comercial | EN1 PROD vía API M2M (futuro) | EN1 DEV vía API M2M (`saas.en1_*`) |

ADR-006 Ana: el usuario **nunca** ve UI EN1. CTAs locales. Comercio M2M off hasta contrato CODITO (`EN1_COMMERCE_ENABLED`).  
Sin simular EN1: si la API no está, esa parte falla cerrada (puente piloto solo con flag off).

Flujo de trabajo: desarrollar y probar en `/opt/corredores-dev` → commit/push → `git pull` en `/opt/corredores` → `sudo systemctl restart esecurebroker`.

TLS DEV (tras crear DNS en Cloudflare A `esecurebroker-dev` → `86.48.20.243`, proxy naranja OK):

```bash
sudo bash /opt/corredores/deploy/enable_dev_tls.sh
```

**Importante:** usar un solo nivel bajo `etsrv.site` (`esecurebroker-dev.etsrv.site`).  
`dev.esecurebroker.etsrv.site` es subdominio anidado: Cloudflare Universal SSL (gratis) **no** emite cert de borde para `*.*.etsrv.site`.

Mientras no exista el DNS, DEV responde en `http://127.0.0.1:8092`.

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
python -m corredores.cli seed       # líneas + carriers + CommissionRule piloto
# import asistido (PII restringido — no loguea celdas):
# python -m corredores.cli import-excel --asegurados PATH --emisiones PATH
python -m corredores.cli serve       # UI piloto http://127.0.0.1:8091/hoy
pytest -q
python scripts/p0_certify.py       # E2E + 360 + Radar + Hoy + Claim + NBA
```

CLI: `doctor | init-db | run-e2e | today | radar | client360 | seed | import-excel | serve`

## Flujo certificado por `run-e2e`

Cliente → Submission → VehicleRisk → Policy/PolicyTerm → PaymentPlan → Installments → Payment → Cobranza derivada → Comisión (snapshot) → Renovación → Auditoría

`p0_certify.py` añade Cliente 360°, Radar, Hoy, transición Claim y decisión NBA.

## Docs de arquitectura

`/opt/easynodeone/Easy-Wiki/05_Proyectos/corredores-seguros/`  
(EN1 permanece en `/opt/easynodeone/app` — no tocar.)
