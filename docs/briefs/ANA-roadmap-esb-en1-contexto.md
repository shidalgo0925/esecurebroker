# Roadmap para Ana — ESecureBroker × EN1 (contexto actual)

**Fecha:** 2026-08-13  
**Ambiente de trabajo:** SOLO DEV (`esecurebroker-dev` / EN1 `appdev`)  
**PROD:** no se toca hasta gate explícito (ADR-037)  
**Audiencia:** Ana (producto / gobierno comercial + onboarding)

---

## 1. En una frase

Estamos cerrando el **onboarding real de una correduría**:  
registro → plan/pago EN1 → OWNER en ESB → equipo (colaboradores/roles) → trabajo Web/GO —  
con EN1 como SoR comercial y ESB como SoR operativo de la oficina.

---

## 2. Quién hace qué (fronteras)

| Dominio | Dueño | Qué decide |
|---------|-------|------------|
| Cliente ETS, contrato, subscription, plan, seats/limits | **EN1 (CODITO)** | SoR comercial |
| Organización correduría, colaboradores, roles, cartera, pólizas | **ESB (SPAGHETTI)** | SoR operativo |
| Identidad larga (ADR-006) | EN1 + ESB | Hoy: login local BrokerAccount; puente M2M C1 |
| Mobile GO RBAC | ESB AccessContext | GO no inventa seguridad; consume `/me` |

**Decisión de producto congelada (Ana/equipo):**  
Una persona/empresa = **un Cliente canónico en EN1**.  
Contacto, usuario, comprador, suscriptor = relaciones de ese Cliente.  
**No** crear “Cliente Comercial” paralelo.

---

## 3. Mapa del viaje del cliente (estado)

```
Landing ESB
   → /registro (OWNER + org local)
   → EN1 bootstrap/checkout (M2M C1)
   → entitlement (seats/plan)
   → /checkout ESB (promo | transferencia | Yappy + comprobante)
   → /hoy
   → Configuración → Colaboradores / Roles
   → Productores + cartera
   → Web + ESB GO (mismo AccessContext)
```

| Tramo | Estado DEV | Nota para Ana |
|-------|------------|---------------|
| Registro + plan | **OK** | Cambio de plan en pending arreglado |
| M2M E2E $0/promo → entitlement → `/hoy` | **OK** | Prueba real hecha |
| Comprador visible como Cliente EN1 | **GAP** | Está en capa comercial; no en Cliente canónico UI |
| Checkout promo | **OK** | Código obligatorio (DEV) |
| Transferencia / Yappy + comprobante | **OK** | Activación sujeta a verificación manual |
| Tarjeta / Stripe | **Pronto** | No cableado a EN1 aún |
| Colaboradores + roles + invitaciones | **OK (F7)** | UI Configuración; seats reservan al invitar |
| ESB GO F5A (activities/upload) | **Congelado** | Reanudar cuando cierre Cliente EN1 + F7 estabilice |
| PROD | **Cerrado** | ADR-037 gate |

---

## 4. Roadmap por olas (lo que viene)

### Ola A — Comercial EN1 (bloqueante de narrativa “cliente”)  
**Owner:** CODITO · **ESB espera decisión, no inventa modelo**

1. **Inspección** Cliente canónico vs `ets_commercial_customer`  
   Brief: `docs/briefs/CODITO-en1-cliente-canonico-vs-commercial.md`
2. Decisión Ana/CODITO: cómo bootstrap C1 materializa el Cliente único  
3. Implementación EN1 (additive si se puede; sin romper C1)  
4. Re-prueba E2E desde ESB `/registro` → Cliente visible en UI EN1  
5. Alinear espejo ESB (`external_en1_org_id` / ids) si hace falta

**Éxito:** el comprador del plan se ve y se opera como Cliente ETS normal, no como figura sombra.

---

### Ola B — Onboarding oficina ESB (en curso / pulido)  
**Owner:** SPAGHETTI

| Ítem | Estado | Siguiente |
|------|--------|-----------|
| ADR-008 F1–F6 (RBAC, producers, seats, GO) | DONE | — |
| F7 Colaboradores / Roles / Invitaciones | DONE DEV | SMTP real de invitación; API admin JSON opcional |
| Comprobante transferencia/Yappy | DONE DEV | Cola de verificación + inhabilitar si inválido |
| Plan / seats enforcement | DONE | Seguir fail-closed con entitlement EN1 |
| Cookie revoke al desactivar | Parcial | Mobile refresh sí; web cookie aún TTL |

**Éxito:** OWNER registra → invita equipo → roles → productores con cartera → Web/GO coherentes.

---

### Ola C — Pagos “de verdad”  
**Owner:** ESB + EN1 (contrato pago)

1. Verificación operativa de comprobantes (bandeja interna)  
2. Cableado tarjeta cuando EN1/Stripe esté listo  
3. Yappy/transferencia: ACK comercial en EN1 (no solo audit ESB)  
4. Estados subscription: pending → active / past_due alineados a EN1

**Éxito:** pagar sin promo activa entitlement sin intervención ad-hoc.

---

### Ola D — Mobile / GO  
**Owner:** LOCAL + SPAGHETTI

1. Descongelar F5A (activities + documentos) cuando A+B estables  
2. Validar `/me` tras cambios de rol/revoke (F7)  
3. SECONDARY portfolio / comisiones producer = ADR futuro (no P0)

**Éxito:** mismo AccessContext Web = GO; revoke corta sesión móvil.

---

### Ola E — Certificación → PROD  
**Owner:** Ana + gobierno ADR-037

Solo cuando:

- [ ] Cliente canónico EN1 OK en DEV  
- [ ] E2E registro→pago→equipo→GO verde  
- [ ] Seats EN1 SoR sin mirror frágil  
- [ ] Runbook operacion comprobantes / soporte  
- [ ] Gate ADR-037 M2M PROD aprobado  

---

## 5. Decisiones que necesitamos de Ana

| # | Pregunta | Impacto |
|---|----------|---------|
| D1 | ¿Confirmas “un Cliente EN1” (sin Cliente Comercial)? | Define trabajo CODITO Ola A |
| D2 | ¿Quién verifica comprobantes Banistmo/Yappy en piloto? (humano / proceso) | Operación Ola C |
| D3 | ¿ADMIN puede `roles:manage` o solo OWNER? | Política F7 (hoy ADMIN sí, custom only) |
| D4 | ¿Prioridad post-Cliente: SMTP invitaciones vs tarjeta vs GO F5A? | Orden Olas B/C/D |
| D5 | ¿Cuándo reabrimos PROD conversation? | Solo tras checklist Ola E |

---

## 6. Qué no estamos haciendo ahora

- Tocar PROD / `esecurebroker`  
- Inventar límites/precios en ESB (EN1 SoR)  
- CRUD destructivo de memberships  
- Redefinir semántica de OWNER/ADMIN/BROKER/PRODUCER/COLLECTIONS  
- Mezclar colaborador ESB con cliente/asegurado  
- “Cliente Comercial” como entidad de negocio

---

## 7. Dónde leer más (DEV)

| Tema | Doc |
|------|-----|
| Este roadmap | `docs/briefs/ANA-roadmap-esb-en1-contexto.md` |
| Colaboradores contrato | `docs/ADR-008_F7_COLLABORATORS_RBAC_CONTRACT.md` |
| F7 implementación | `docs/ADR-008_F7_IMPLEMENTATION.md` |
| ADR-008 pointer | `docs/ADR-008_POINTER.md` |
| Brief CODITO Cliente canónico | `docs/briefs/CODITO-en1-cliente-canonico-vs-commercial.md` |
| Brief CODITO visibilidad cliente | `docs/briefs/CODITO-en1-commercial-cliente-visible.md` |
| M2M / PROD gate | ADR-037 (EN1 + EasyWiki) |

---

## 8. Mensaje corto para Ana (copiar/pegar)

> Ana: en DEV ya tenemos E2E comercial M2M (registro→entitlement→/hoy), checkout con promo/transfer/Yappy+comprobante, y administración real de colaboradores/roles (ADR-008 F7).  
> El hueco de producto está en EN1: el comprador no materializa el **Cliente canónico** (decisión: un Cliente, sin “Cliente Comercial”). Eso es inspección/implementación CODITO; después repetimos `/registro`.  
> ESB GO F5A y PROD siguen congelados. Necesitamos tu OK a D1–D4 del roadmap para ordenar la siguiente ola.

---

*Documento vivo — actualizar al cerrar Ola A o cambiar prioridad Ana.*
