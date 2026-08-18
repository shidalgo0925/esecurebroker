# Roadmap ESecureBroker

**Producto:** ESecureBroker (ESB) — expediente operativo de la correduría  
**Actualizado:** 2026-08-18  
**Ambiente activo:** DEV (`https://esecurebroker-dev.etsrv.site`)  
**PROD:** cerrado hasta F1–F3 ADR-037 + E2E `credential_ref` · **canal público no cableado a PROD**  
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
6. **Vender por canal público** (landing comercial → datos en ESB, sin login del comprador)

Sin inventar límites comerciales en ESB y sin mezclar “cliente asegurado” con “colaborador”.  
Landing ≠ UI ESB: el cotizador público es vitrina; **ESB es sistema de registro**.

---

## Pilares

| Pilar | Qué es | SoR |
|-------|--------|-----|
| **Comercial SaaS** | Plan, seats, entitlement, pago | EN1 |
| **Identidad / acceso** | Org, memberships, roles, invitaciones | ESB (ADR-008) |
| **Cartera** | Clientes, pólizas, productores, asignaciones | ESB |
| **Cobranza / CxC** | Cuotas, pagos, morosidad, estados de cuenta | ESB |
| **Canal público** | Cotizar / pagar viaje → CRM + Party + Policy | ESB (org del canal) |
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
| **Canal público Avioncito** | Cotizador Grupo Arsi en DEV — ver FASE 3c |

### Huecos abiertos

| Hueco | Dueño | Bloquea |
|-------|-------|---------|
| Comprador ≠ Cliente canónico EN1 | CODITO | Narrativa comercial / re-test `/registro` |
| SMTP invitaciones | ESB | Onboarding oficina “de verdad” |
| Verificación comprobantes (bandeja) | ESB ops | Activación sin promo |
| Tarjeta / Stripe ↔ EN1 | ESB+EN1 | Pago automático SaaS |
| Revoke cookie web | ESB | Seguridad al desactivar colaborador |
| GO F5A UI | LOCAL | Campo: gestiones/docs desde app |
| Tarifas oficiales viaje (canal) | ESB + negocio | Precios reales (hoy `DEV_PLACEHOLDER`) |
| Stripe keys canal público | ESB ops | Checkout tarjeta real (hoy SANDBOX DEV) |
| Transfer / Yappy en canal público | ESB | Alternativas de pago en landing |
| Cablear canal → PROD | Ana + GO explícito | Go-live cotizador |
| PROD plataforma | Ana + ADR-037 | Go-live ESB |

---

## Roadmap por fases

```
NOW                NEXT                     LATER                 PROD
─────              ─────                    ─────                 ────
Canal público DEV  Tarifas oficiales viaje  Stripe canal real     Gate 037
(CRM+Party+Policy) Transfer/Yappy canal     PDF cotización        Canal→PROD (GO)
F7 / checkout SaaS Cliente EN1 (A)          GO F5A descongelar    Cutover
                   Re-test /registro        Identidad ADR-006
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
| SMTP invite email | DONE (usa SMTP de Mantenimiento; fallback enlace UI) |
| API `/api/admin/v1` | LATER |
| Bandeja verificación pagos | DONE (`/mantenimiento/comprobantes`) |

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

### FASE 3c — Canal público de venta (Grupo Arsi / Avioncito) — DEV

Landing comercial **fuera** del chrome ESB; datos bajo org del canal.  
Regla: **pagado → cliente (`Party`) + póliza VIAJE** en cartera ESB. No crea `Payment`/`Allocation` de cobranza (operador/UI).  
**PROD no cableado** hasta GO explícito.

| Ítem | Estado |
|------|--------|
| Modelos canal / quote / travelers / payment attempts | DONE (DEV) |
| Seed Grupo Arsi + planes GLOBAL / MAXIMUS / SUPREME | DONE (DEV; rates placeholder) |
| Wizard público (viaje → planes → datos → pago) | DONE |
| Checkout UX tipo Stripe/Namecheap (formulario + resumen) | DONE |
| Stripe Checkout si keys; si no SANDBOX confirm in-app | DONE (DEV) |
| CRM: prospect + oportunidad → WON al pagar | DONE |
| Emisión: Party CLIENT + Policy ACTIVE + term + 1 cuota | DONE (idempotente) |
| Subdominio `cotizadorgrupoarsi.etsrv.site` + nginx + SSL | DONE → DEV `:8092` |
| `public_channel.base_url` | DONE |
| Tarifas oficiales / carrier default por canal | NEXT |
| PDF cotización / certificado al comprador | LATER |
| Transfer / Yappy en landing | LATER |
| Cablear canal + migración a PROD | LATER — requiere **GO** |

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
| 1 | Tarifas oficiales + carrier default canal Avioncito | ESB + negocio |
| 2 | Inspección + fix Cliente canónico EN1 | CODITO |
| 3 | Re-prueba E2E `/registro` | ESB + CODITO |
| 4 | SMTP invitaciones colaboradores | ESB — DONE |
| 5 | Bandeja verificar comprobantes Banistmo/Yappy | ESB — DONE |
| 6 | Stripe keys canal público (DEV→luego PROD) | ESB ops |
| 7 | Descongelar GO F5A (LOCAL) | LOCAL + ESB |
| 8 | Tarjeta SaaS cuando EN1 liste | ESB + EN1 |
| 9 | Gate PROD + GO canal público | Ana |

---

## URLs / refs DEV

| Qué | Dónde |
|-----|--------|
| App DEV (expediente) | https://esecurebroker-dev.etsrv.site |
| Cotizador público Grupo Arsi | https://cotizadorgrupoarsi.etsrv.site → `/public/avioncito/` |
| Clientes / pólizas canal | DEV `/clientes` · `/polizas` (org **Grupo Arsi**) |
| Colaboradores | `/configuracion/colaboradores` |
| Roles | `/configuracion/roles` |
| Checkout SaaS | `/checkout` |
| Contrato F7 | `docs/ADR-008_F7_COLLABORATORS_RBAC_CONTRACT.md` |
| Impl F7 | `docs/ADR-008_F7_IMPLEMENTATION.md` |
| ADR-008 | `docs/ADR-008_POINTER.md` |
| Brief Ana | `docs/briefs/ANA-roadmap-esb-en1-contexto.md` |
| Brief CODITO Cliente | `docs/briefs/CODITO-en1-cliente-canonico-vs-commercial.md` |

---

## Invariantes que el roadmap no rompe

1. EN1 = SoR comercial SaaS (plan/seats/pago).  
2. ESB = SoR operativo de la correduría (cartera, cobranza, canal público).  
3. Un Cliente EN1; no “Cliente Comercial”.  
4. Colaborador ≠ asegurado.  
5. System roles inmutables en semántica (GO depende de ellos).  
6. No DELETE destructivo de memberships con historia.  
7. PROD no se toca sin gate / GO explícito (incluye canal público).  
8. Fail-closed si no hay entitlement para subir seats.  
9. Landing vende; ESB registra. Precio no se confía del browser.  
10. Cobros de cartera / allocations: solo operador UI o evidencia real (regla de oro).  

---

*Documento canónico del roadmap ESB. Actualizar al cerrar cada fase.*
