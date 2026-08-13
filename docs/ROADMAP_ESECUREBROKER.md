# Roadmap ESecureBroker

**Producto:** ESecureBroker (ESB) — expediente operativo de la correduría  
**Actualizado:** 2026-08-13  
**Ambiente activo:** DEV (`https://esecurebroker-dev.etsrv.site`)  
**PROD:** cerrado hasta F1–F3 ADR-037 + E2E `credential_ref`  
**ADR-037:** SPAGHETTI ACCEPT 2026-08-13 · GO F1 → CODITO (EN1 DEV)  
**Companion Ana/EN1:** `docs/briefs/ANA-roadmap-esb-en1-contexto.md`

---

## Norte

Que una correduría pueda:

1. **Registrarse y pagar** un plan (SoR comercial = EN1)  
2. **Entrar** como OWNER a su organización  
3. **Armar su equipo** (colaboradores, roles, productores)  
4. **Operar** cartera, cobranza, renovaciones, reclamos, documentos  
5. **Trabajar en campo** con ESB GO bajo el mismo AccessContext  

Sin inventar límites comerciales en ESB y sin mezclar “cliente asegurado” con “colaborador”.

---

## Pilares

| Pilar | Qué es | SoR |
|-------|--------|-----|
| **Comercial** | Plan, seats, entitlement, pago | EN1 |
| **Identidad / acceso** | Org, memberships, roles, invitaciones | ESB (ADR-008) |
| **Cartera** | Clientes, pólizas, productores, asignaciones | ESB |
| **Cobranza / CxC** | Cuotas, pagos, morosidad, estados de cuenta | ESB |
| **Captura / import** | Foto póliza, Excel, documentos | ESB |
| **Mobile GO** | `/api/mobile/v1` + AccessContext | ESB (+ LOCAL app) |
| **Inteligencia** | Captura visión, oportunidades IA (acotado) | ESB |

---

## Estado actual (DEV)

### Hecho

| Área | Entrega |
|------|---------|
| Multi-tenant | Orgs, membership, aislamiento ADR-007 |
| RBAC / scope | AccessContext ADR-008 F1–F6 |
| Productores | Profiles, PRIMARY portfolio, seats producer |
| SaaS signup | `/registro` → org + OWNER + bridge EN1 C1 |
| Checkout | Promo EN1; Transferencia / Yappy + comprobante obligatorio |
| Colaboradores F7 | Invitar, roles system/custom, lifecycle, seat reserve |
| Expediente Web | Hoy, clientes, pólizas, cobranza, cotizador, reportes… |
| Mobile Gate B | Auth refresh, `/me`, scope lists |
| Mobile F5A backend | Activities + document upload (ACK/idempotency) — **congelado en producto** |
| ADR-009 incentivos | Schema, calc, settlement, UI Beneficios, alertas Hoy |
| Dashboard cartera | Pestañas Resumen · Cobros · Producción · Metas |
| Identidad org | Logo + datos en Configuración (cabecera PDF) |
| Reportes PDF | Cartera, cobranza, morosidad, pagos, comisiones, cotizaciones, clientes, etc. |
| Importaciones | Motor XLSX operativo (fix shadowing payments) |

### Huecos abiertos

| Hueco | Dueño | Bloquea |
|-------|-------|---------|
| Comprador ≠ Cliente canónico EN1 | CODITO | Narrativa comercial / re-test `/registro` |
| SMTP invitaciones | ESB | Onboarding oficina “de verdad” |
| Verificación comprobantes (bandeja) | ESB ops | Activación sin promo |
| Tarjeta / Stripe ↔ EN1 | ESB+EN1 | Pago automático |
| Revoke cookie web | ESB | Seguridad al desactivar colaborador |
| GO F5A UI | LOCAL | Campo: gestiones/docs desde app |
| PROD | Ana + ADR-037 | Go-live |

---

## Roadmap por fases

```
NOW          NEXT                LATER              PROD
─────        ─────               ─────              ────
F7 pulido    Cliente EN1 (A)     Pagos reales       Gate 037
Checkout     SMTP invites        GO F5A descongelar Certificación
comprobante  Bandeja verify      API admin JSON     Cutover
             Re-test /registro   Identidad ADR-006
```

### FASE 0 — Base operativa (cerrada en DEV)

- Domain Truth pólizas/cuotas/pagos  
- Web piloto multi-org  
- ADR-008 F1–F6  
- Seed Alfa/Beta + mobile users  

### FASE 1 — Onboarding comercial (casi cerrado / gap EN1)

| Ítem | Estado |
|------|--------|
| Registro OWNER | DONE |
| M2M bootstrap/checkout/entitlement | DONE E2E |
| Checkout promo | DONE |
| Transfer / Yappy + comprobante | DONE |
| Cliente canónico visible en EN1 | **NEXT — CODITO** |
| Tarjeta | LATER |

### FASE 2 — Oficina real (F7 — implementado, pulir)

| Ítem | Estado |
|------|--------|
| Colaboradores UI | DONE |
| Roles system + custom | DONE |
| Invitaciones + accept | DONE (link DEV) |
| Seat reserve INVITED | DONE |
| SMTP invite email | NEXT |
| API `/api/admin/v1` | LATER |
| Bandeja verificación pagos | NEXT |

### FASE 3 — Campo (ESB GO)

| Ítem | Estado |
|------|--------|
| Auth + `/me` + scope | DONE |
| F5A backend activities/docs | DONE (congelado producto) |
| F5A UI LOCAL | NEXT tras Fase 1–2 estables |
| Offline / FCM / claims write | Fuera de P0 actual |

### FASE 3b — Incentivos de aseguradora (ADR-009) — P0 DEV

| Ítem | Estado |
|------|--------|
| Schema + calc + settlement | DONE |
| UI Aseguradora → Beneficios | DONE |
| Alertas en Hoy | DONE |
| Feed automático Carrier API (F6) | LATER |

### FASE 4 — Profundidad producto (backlog priorizable)

- Renovaciones / reclamos más ricos  
- SECONDARY portfolio  
- Comisiones por producer  
- Oportunidades IA operativas  
- Identidad EN1 (ADR-006) sustituyendo BrokerAccount  
- Estados de cuenta / cobranza automatismos  

### FASE 5 — Certificación → PROD

Checklist:

1. Cliente canónico EN1 OK  
2. E2E registro → pago → equipo → Web → GO  
3. Seats solo desde entitlement EN1  
4. Runbook comprobantes + soporte  
5. ADR-037 M2M PROD aprobado  
6. Cutover sin tocar datos PROD a ciegas  

---

## Prioridad recomendada (orden de trabajo)

| # | Trabajo | Owner |
|---|---------|-------|
| 1 | Inspección + fix Cliente canónico EN1 | CODITO |
| 2 | Re-prueba E2E `/registro` | ESB + CODITO |
| 3 | SMTP invitaciones colaboradores | ESB |
| 4 | Bandeja verificar comprobantes Banistmo/Yappy | ESB |
| 5 | Descongelar GO F5A (LOCAL) | LOCAL + ESB |
| 6 | Tarjeta cuando EN1 liste | ESB + EN1 |
| 7 | Gate PROD | Ana |

---

## URLs / refs DEV

| Qué | Dónde |
|-----|--------|
| App DEV | https://esecurebroker-dev.etsrv.site |
| Colaboradores | `/configuracion/colaboradores` |
| Roles | `/configuracion/roles` |
| Checkout | `/checkout` |
| Contrato F7 | `docs/ADR-008_F7_COLLABORATORS_RBAC_CONTRACT.md` |
| Impl F7 | `docs/ADR-008_F7_IMPLEMENTATION.md` |
| ADR-008 | `docs/ADR-008_POINTER.md` |
| Brief Ana | `docs/briefs/ANA-roadmap-esb-en1-contexto.md` |
| Brief CODITO Cliente | `docs/briefs/CODITO-en1-cliente-canonico-vs-commercial.md` |

---

## Invariantes que el roadmap no rompe

1. EN1 = SoR comercial (plan/seats/pago).  
2. ESB = SoR operativo de la correduría.  
3. Un Cliente EN1; no “Cliente Comercial”.  
4. Colaborador ≠ asegurado.  
5. System roles inmutables en semántica (GO depende de ellos).  
6. No DELETE destructivo de memberships con historia.  
7. PROD no se toca sin gate.  
8. Fail-closed si no hay entitlement para subir seats.

---

*Documento canónico del roadmap ESB. Actualizar al cerrar cada fase.*
