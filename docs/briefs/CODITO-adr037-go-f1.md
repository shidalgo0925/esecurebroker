# CODITO — GO F1 ADR-037 (Integration Center EN1)

| Campo | Valor |
|-------|-------|
| **Fecha** | 2026-08-13 |
| **De** | SPAGHETTI / ESB DEV |
| **Para** | CODITO / EN1 |
| **ADR** | ADR-037 |
| **Fase** | **F1** |
| **Ambiente** | **EN1 DEV only** |

---

## Estado gobierno

- SPAGHETTI: **ACCEPT** ADR-037 (`docs/ADR-037_ACCEPT.md` en ESB).
- CODITO: confirmar ACCEPT en canónico EN1 / EasyWiki si aún no está marcado.
- ESB autoriza el **arranque de implementación F1** en EN1 DEV (no bloquea).

---

## Pedido

Implementar **F1** según ADR-037 §13:

1. Integration Center (evolución API Center): entidad **Integration** + bind de keys.
2. Health: `CONNECTED` | `DEGRADED` | `DISCONNECTED`.
3. Acción **Probar** (probe) en DEV.
4. Auditoría mínima de bind/test/status **sin** devolver secrets.

Contrato comercial C1 (`/api/v1/commercial/*`) **no** debe romperse; F1 es ops de credenciales, no redesign del bridge.

---

## Fuera de este GO

| Tema | Quién / cuándo |
|------|----------------|
| ESB Integraciones + `credential_ref` (F2) | SPAGHETTI — GO F2 post-F1 |
| Dual-key / revoke UI (F3) | Conjunto — GO F3 |
| STG / PROD M2M | Tras F1–F3 + E2E `credential_ref` |
| Cobro real / Cubo / Payment Domain | Carril aparte (análisis) |
| Cliente canónico vs commercial customer | Brief aparte (prioridad producto) |

---

## Criterio de done F1 (para avisar a ESB)

- [ ] Integration visible en EN1 DEV (UI/admin)
- [ ] Key M2M ESB ligada a una Integration
- [ ] Health + Probar funcionan en DEV
- [ ] Doc corta de cómo ESB leerá status en F2 (contrato probe/status)

Cuando F1 esté usable → ESB prepara GO F2.

---

## Refs

- EasyWiki: `00_Gobierno/ADR/ADR-037-INTEGRATIONS-M2M-CREDENTIALS-OPERATIONS.md`
- ESB ACCEPT: `docs/ADR-037_ACCEPT.md`
- ESB DEV: https://esecurebroker-dev.etsrv.site
- EN1 DEV: https://appdev.easynodeone.com
