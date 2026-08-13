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

**STOP** — no iniciar F2 sin GO.
