# ADR-037 — ACCEPT (SPAGHETTI / ESB)

| Campo | Valor |
|-------|-------|
| **ADR** | ADR-037 — Integraciones M2M, Credenciales y Operación |
| **Fecha ACCEPT ESB** | 2026-08-13 |
| **Actor** | SPAGHETTI (consumidor ESB) |
| **Ámbito** | Diseño / gobierno — **no** es GO de implementación ESB F2 |
| **Canónico** | EasyWiki `00_Gobierno/ADR/ADR-037-INTEGRATIONS-M2M-CREDENTIALS-OPERATIONS.md` |

---

## Decisión

SPAGHETTI **ACCEPT** el ADR-037 tal como está publicado (checklist diseño §14 ítems 1–16 + gate PROD §13).

Implicaciones:

1. El E2E DEV (C1 + promo $0 + token/silo artesanal) **sigue válido solo en DEV**.
2. **PROD M2M comercial = OFF** hasta F1 + F2 + F3 + E2E con `credential_ref`.
3. Prohibido repetir scp / path tribal / raw en settings como runbook PROD.
4. Implementación F1–F3 **requiere GO explícito por fase**.

---

## Aceptación conjunta

| Parte | Estado | Fecha |
|-------|--------|-------|
| SPAGHETTI (ESB) | **ACCEPT** | 2026-08-13 |
| CODITO (EN1) | Pendiente confirmar en canónico EN1 / wiki | — |

Sin ACCEPT CODITO el documento puede quedar “ACCEPT parcial ESB”; el GO F1 sigue siendo del dueño EN1.

---

## GO F1 (autorización de arranque — dueño CODITO)

| Campo | Valor |
|-------|-------|
| **Fase** | F1 — Integration Center EN1 |
| **Dueño** | **CODITO** |
| **Ambiente** | Solo **EN1 DEV** |
| **GO desde ESB** | **Sí** (2026-08-13) — SPAGHETTI no bloquea el arranque F1 |
| **Fuera de alcance F1** | ESB UI Integraciones (F2), dual-key (F3), STG/PROD, Payment Domain / cobro real |

### Entrega mínima F1 (del ADR §13)

- Entidad **Integration** + ligar keys existentes del API Center
- Health: `CONNECTED` / `DEGRADED` / `DISCONNECTED`
- Acción **Probar** (probe controlado) en DEV
- Sin raw secrets en respuestas de status/health

### Handoff

Brief operativo: `docs/briefs/CODITO-adr037-go-f1.md`

---

## Qué hace ESB mientras tanto

- Producto DEV puede seguir (no bloqueado por 037).
- M2M DEV: mecanismo actual (`EN1_M2M_TOKEN` / silo) hasta F2.
- **No** implementar pantalla Integration Center en EN1.
- **No** pull/cutover PROD.
- F2 ESB (`credential_ref` + Integraciones) espera GO F2 tras F1 usable en DEV.

---

## Changelog

| Fecha | Nota |
|-------|------|
| 2026-08-13 | SPAGHETTI ACCEPT + GO F1 (CODITO) registrado en ESB DEV |
