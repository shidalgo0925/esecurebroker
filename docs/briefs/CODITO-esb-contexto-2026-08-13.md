# CODITO — Contexto ESB (lo último realizado) · 2026-08-13

**DESTINO:** CODITO / EasyNodeOne (DEV)  
**DE:** SPAGHETTI / ESecureBroker  
**AMBIENTE:** solo DEV · `https://esecurebroker-dev.etsrv.site` ↔ EN1 `https://appdev.easynodeone.com`  
**PROD:** **no tocar** (gate ADR-037)  
**Repo ESB:** `main` @ `7f30879` (y commits previos del día)

---

## 1. En una frase

Hoy en ESB DEV se cerró **producto operativo** (incentivos cia, dashboard, identidad/PDF, importaciones) y se reafirmó que el puente comercial M2M sigue en DEV; **PROD y el modelo de credenciales M2M siguen bajo ADR-037** (pendiente aceptación conjunta).

---

## 2. Fronteras (sin cambio)

| Dominio | Dueño |
|---------|--------|
| SoR comercial (cliente, contrato, subscription, plan, seats, entitlement, M2M keys) | **EN1 / CODITO** |
| SoR operativo (org correduría, cartera, cobranza, colaboradores, reportes) | **ESB / SPAGHETTI** |
| Gate PROD M2M / secret delivery | **ADR-037** (CODITO + SPAGHETTI) |

ESB **no** emite API keys EN1. ESB **no** inventa Cliente canónico.

---

## 3. Numeración ADR (importante)

| ID | Tema | Nota |
|----|------|------|
| **ADR-037** | Integraciones M2M, credenciales y operación | Canónico M2M · EasyWiki `00_Gobierno/ADR/ADR-037-…` · **gate PROD** |
| **ADR-009** (ESB) | Carrier Incentive Plans / beneficios cia | **No** es M2M · dominio ESB puro · ACCEPTED en DEV |
| Stub viejo «ADR-009 M2M» en wiki ESB | SUPERSEDED | Apunta a ADR-037 |

No reutilizar 009 para Caja/M2M.

---

## 4. Lo entregado hoy en ESB DEV (para tu radar)

### 4.1 Relevante a EN1 / puente (indirecto)

| Ítem | Estado | Impacto CODITO |
|------|--------|----------------|
| Checkout promo / Transfer / Yappy + comprobante | Ya estaba DONE | Sigue igual; **bandeja verify** ESB aún abierta |
| E2E registro → bootstrap → entitlement | Sigue OK en DEV | Sin cambio de contrato C1 |
| Landing ESB actualizado | DONE | Copy menciona reportes/equipo; CTAs siguen `/registro` |
| Pedido pull a PRD ESB | **Rechazado** lado ESB | Alineado con gate ADR-037 |

### 4.2 Solo ESB (no requiere acción CODITO)

| Ítem | Commit / nota |
|-------|----------------|
| ADR-009 incentivos cia (schema, calc, UI Beneficios, Hoy) | `bdc5a0a` |
| Fix Importaciones (`record_payment` shadowing package `payments/`) | dentro de `f934087` |
| Dashboard Cartera: Cobros · Producción · Metas | `f934087` |
| Identidad org + logo (Configuración) + reportes PDF | `f934087` |
| PDF en pantallas operativas + Descargas | `f934087` |
| Retorno global topbar | `f934087` |
| Landing sync + cleanup copias static | `7f30879` |

**ADR-009 F6** (feed automático desde Carrier API) = LATER; hoy los acumulados de incentivo se cargan en ESB (manual/confirmado). **No** pide endpoints nuevos a EN1.

---

## 5. Abierto que **sí** es de CODITO / conjunto

| # | Tema | Dueño | Estado pedido |
|---|------|-------|---------------|
| 1 | **Cliente canónico** vs `ets_commercial_customer` | CODITO | Inspección pedida (briefs previos); **sin fix aún** |
| 2 | Re-test E2E `/registro` tras #1 | ESB + CODITO | Esperando #1 |
| 3 | **ADR-037** aceptación + diseño ops secretos PROD | CODITO + SPAGHETTI | Publicado; **no implementado** |
| 4 | Tarjeta / Stripe ↔ EN1 | ESB + EN1 | LATER |
| 5 | Gate cutover PROD | Ana + ADR-037 | Cerrado |

Briefs ya en ESB:

- `docs/briefs/CODITO-en1-cliente-canonico-vs-commercial.md`  
- `docs/briefs/CODITO-en1-commercial-cliente-visible.md`  
- `docs/briefs/ANA-roadmap-esb-en1-contexto.md`

---

## 6. Lo que **no** pedimos a CODITO ahora

- Implementar pantalla Integration Center (eso es GO post-aceptación ADR-037).  
- Endpoints para incentivos de aseguradora (dominio ESB).  
- Deploy / pull a EN1 PROD o ESB PROD.  
- Cambiar contrato C1 `commercial/bootstrap|checkout|entitlement` salvo bug reportado.

---

## 7. Pedido concreto a CODITO (siguiente)

1. **Prioridad:** cerrar inspección Cliente canónico (brief §pedido) y devolver mapa tabla/UI + si bootstrap debe materializar Cliente.  
2. **En paralelo (gobierno):** revisar ADR-037 y marcar aceptación / gaps antes de cualquier diseño de secret delivery PROD.  
3. Avisar a ESB cuando haya resultado de #1 para re-probar `/registro` en DEV.

---

## 8. Refs rápidas

| Qué | Dónde |
|-----|--------|
| ESB DEV | https://esecurebroker-dev.etsrv.site |
| EN1 DEV | https://appdev.easynodeone.com |
| ADR-037 | EasyWiki `00_Gobierno/ADR/ADR-037-INTEGRATIONS-M2M-CREDENTIALS-OPERATIONS.md` |
| Roadmap ESB | `docs/ROADMAP_ESECUREBROKER.md` |
| Este brief | `docs/briefs/CODITO-esb-contexto-2026-08-13.md` |

---

**Firma:** SPAGHETTI · ESB DEV · 2026-08-13  
**PROD:** no se toca.
