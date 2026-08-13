# ADR-011 — ESB CRM: Prospectos, Oportunidades y Conversión a Cliente

| Campo | Valor |
|-------|-------|
| **ID** | ADR-011 |
| **Estado** | **ACCEPTED / GO** |
| **Fecha** | 2026-08-13 |
| **Ámbito inicial** | DEV (`/opt/corredores-dev`) |
| **PROD** | **NO TOCAR** hasta cutover explícito |

Documento de decisión completo: contexto maestro de producto (Prospect ≠ Customer, pipeline, Kanban, conversión, RBAC, F1–F9).

## F1 — Domain (DONE 2026-08-13)

### Reutilizado (no duplicado)

| Existente | Uso |
|-----------|-----|
| `Party` + `PartyRole(CLIENT)` | Customer |
| `RenewalOpportunity` | Solo renovaciones — **no** new-business |
| `Interaction` / `Task` | Log móvil / tareas genéricas — **≠** `CrmActivity` |
| `ProducerProfile` | `assigned_producer_id` |
| `AuditEvent` | Auditoría (servicios F2+) |
| `QuoteRequest` stack | Cotizaciones (relación F6) |

### Creado

| Modelo | Tabla |
|--------|-------|
| `CrmLeadSource` | `crm_lead_sources` |
| `CrmLostReason` | `crm_lost_reasons` |
| `CrmPipelineStage` | `crm_pipeline_stages` |
| `CrmProspect` | `crm_prospects` |
| `CrmOpportunity` | `crm_opportunities` |
| `CrmActivity` | `crm_activities` |

Migración: `a011f1c0ffee` ← `f0a1b2c3d4e5`  
Constants: `corredores/domain/crm_constants.py`  
Seed: `corredores/services/crm_catalog_seed.py`  
Tests: `tests/test_crm_adr011_f1.py`

### Constraints clave

- `ck_crm_opp_prospect_or_customer`: opportunity requiere `prospect_id` **o** `customer_id`
- Catálogos únicos por `(organization_id, code)`
- Prospect se conserva al convertir (`converted_customer_id`)

### Gaps / riesgos F1

1. **`office_id`**: soft string — no hay entidad Office en ESB aún.
2. **`assigned_executive_id`**: `subject_id` string, no FK a membership.
3. Cotizaciones / documentos / Hoy / API / UI / GO: fases F3–F9.
4. Prefijo `crm_*` deliberado para no chocar con `/oportunidades` de renovación.
5. No aplicar migración en PROD.

## F2 — AccessContext / RBAC (DONE 2026-08-13)

- `corredores/services/crm_access.py` — scope filters + `require_*_in_scope` (404 anti-IDOR)
- Permisos `crm:read` / `crm:manage` en matriz de roles
- PRODUCER (`ASSIGNED_PORTFOLIO`): prospectos/oportunidades asignadas; oportunidades sobre `customer_id` en cartera; executive subject match
- OWNER/ADMIN/BROKER/PLATFORM: org-wide CRM
- `office_id`: aún sin filtro (sin entidad Office)
- Tests: `tests/test_crm_adr011_f2.py`

## F3 — CRM API (DONE 2026-08-13)

- `corredores/services/crm_service.py` — create/list/assign, stages, WON/LOST/REOPEN, activities, convert
- `corredores/web/crm_routes.py` — REST `/api/crm/v1` (tag OpenAPI `crm-v1`)
- Deduplicación Customer (LINK / CREATE / 409 ambiguous)
- Auditoría `CRM_*` vía `AuditEvent`
- Tests: `tests/test_crm_adr011_f3.py`

Endpoints clave:
`GET/POST /prospects` · `GET/POST /opportunities` · `POST .../won|lost|reopen|convert|stage|assign` · `GET/POST /activities` · catalogs `/stages|/lead-sources|/lost-reasons`

## F4 — Pipeline Web / Kanban (DONE 2026-08-13)

- UI HTML: `/crm` (Kanban), `/crm/prospectos`, `/crm/prospectos/{id}`, `/crm/oportunidades/{id}`
- Router: `corredores/web/crm_ui_routes.py` (reusa `crm_service`)
- Nav Ventas: **CRM / Pipeline** (separado de **Cola renovaciones** `/oportunidades`)
- Acciones: crear prospecto/oportunidad, mover etapa, WON/LOST/reabrir, actividades, convertir a cliente
- Tests: `tests/test_crm_adr011_f4.py`

**STOP** — no iniciar F5+ sin GO.
