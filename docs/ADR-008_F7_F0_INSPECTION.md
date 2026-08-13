# ADR-008 F7 — F0 Inspection (Colaboradores / RBAC Admin)

**Ambiente:** SOLO `/opt/corredores-dev`  
**Fecha:** 2026-08-13  
**Estado:** INSPECCIÓN COMPLETA — **sin implementación**  
**Contrato:** `docs/ADR-008_F7_COLLABORATORS_RBAC_CONTRACT.md`

---

## A. Tablas / modelos reutilizables

| Pieza | Existe | Ubicación |
|-------|--------|-----------|
| Organization | ✓ | `domain/models.py` |
| OrgMembership | ✓ | `domain/models.py` · Alembic F1 |
| BrokerAccount | ✓ | `domain/models.py` |
| ProducerProfile | ✓ | `domain/models.py` |
| PortfolioAssignment | ✓ | `domain/models.py` |
| AccessContext | ✓ runtime | `services/access_control.py` |
| AuditEvent | ✓ genérico | `domain/models.py` |
| OrgSubscription + seat limits | ✓ | F5 `seats.py` + columnas |
| MobileRefreshToken | ✓ | Gate B / mobile |
| Role / RolePermission tables | ✗ | — |
| Invitation | ✗ | — |
| Membership status enum | ✗ | solo `active: bool` |

---

## B. Gap exacto OrgMembership

**Hoy:**

```
id, organization_id, subject_id, display_name,
role_code, active (bool), external_en1_membership_id,
created_at, updated_at
```

**Falta vs contrato:**

| Campo / concepto | Gap |
|------------------|-----|
| `status` INVITED\|ACTIVE\|INACTIVE\|REVOKED | Solo boolean |
| `scope` persistido | Derivado de rol (`DEFAULT_SCOPE_BY_ROLE`) |
| invitation metadata | No |
| `producer_profile_id` FK | Link por email heurístico |
| last_login_at | No en membership |

**Riesgo:** `ensure_membership` puede reactivar sin pasar por `assert_can_activate_role` (dos caminos). Unificar en servicio de dominio F2.

---

## C. Gap Role / Permissions

- Códigos system: `domain/membership_roles.py`  
- Matriz hardcoded: `access_control._ROLE_PERMISSIONS`  
- **No** existen `members:read|manage` ni `roles:read|manage` aún  
- Custom roles: **0**  

**Decisión F1 (propuesta):**

1. Formalizar catálogo de permissions como módulo/DB seed.  
2. Introducir tablas `roles` + `role_permissions` para custom; system roles seed con `organization_id=NULL` y flag `system_role=true`.  
3. System roles: permisos mínimos **inmutables** vía código o constraint; UI no puede convertir PRODUCER→ORGANIZATION.  
4. Extender matriz OWNER/ADMIN con `members:*` / `roles:*` antes de UI.

---

## D. Gap invitations

Ningún modelo, token, email ni endpoint.  
Alta actual: signup OWNER + seed + grant producer por email existente.

**Necesario F3:** `org_invitations` (token_hash, email, org, role_code, status, expires_at, created_by, consumed_at).

---

## E. Session / revoke hoy

| Canal | Estado |
|-------|--------|
| Cookie web HMAC | Stateless — **no** se puede matar remotamente al desactivar |
| Mobile refresh | `revoked_at` existe; falta *revoke-all-for-subject(+org)* al desactivar membership |
| Access JWT mobile | Stateless hasta `exp` (~1h) |

**F8 debe:** bulk-revoke refresh; documentar ventana residual del access token; opción denylist cookie o rotación `auth_secret` por subject (fase posterior si hace falta).

---

## F. ProducerProfile linkage

- Profile ≠ membership (correcto, D-15).  
- Link GO: email Party ≈ username (`find_producer_profile_for_subject`).  
- UI Productores ya otorga acceso si existe `BrokerAccount` por email.

**F7:** FK opcional `org_memberships.producer_profile_id` (+ unique por org) para dejar de depender del email.

---

## G. Entitlement / seats disponible

- Límites: `OrgSubscription.internal_seats_limit` / `producer_seats_limit` + source EN1.  
- Uso: memberships `active=True` (internal vs PRODUCER).  
- Enforcement en `activate_membership` / `assert_can_activate_role`.  
- **No** reserva por INVITED (no existe INVITED).  
- Fallback plan catalog si no hay límites EN1.

Alineado a contrato §16–17; falta reserva INVITED (F4).

---

## H. Auditoría reutilizable

`AuditEvent` sirve (`entity_type` + `action` + `detail_json`).  
Hoy **cero** acciones `MEMBER_*` / `ROLE_*`. Convención en contrato §21 — cablear en servicios F2–F6.

---

## I. Migraciones necesarias (lista; no escritas)

1. `org_memberships.status` (+ backfill ACTIVE/INACTIVE) · deprecar o sincronizar `active`  
2. Timestamps invite/accept/revoke + actor opcional  
3. `org_memberships.producer_profile_id` nullable FK  
4. `org_invitations`  
5. `roles` + `role_permissions` (+ seed system)  
6. Indexes status / token_hash / email pending  
7. (Opcional código) helper revoke-all refresh — puede no requerir schema  

**No** tocar PROD. **No** destruir F1–F6.

---

## J. API propuesta final

Ver contrato §20. Prefijo: `/api/admin/v1/…`  
Web HTML usa mismos servicios de dominio (no lógica en rutas).

---

## K. UI propuesta final

```
Configuración
├── Colaboradores          NEW  /configuracion/colaboradores
├── Roles y permisos       NEW  /configuracion/roles
├── Productores            EXISTE /productores (alinear grant con invitaciones)
├── Plan y suscripción     (checkout / entitlement)
└── …actual
```

NAV footer / Configuración — **no** inventar segundo menú de «usuarios».

---

## L. Matriz roles / permissions

Base F2 en `access_control.py` + extensión contrato §19.

Pendiente F1: añadir `members:*`, `roles:*`, `settings:read` explícito; alinear nombres `collections:create|update` vs `manage` actuales.

---

## M. Riesgos

| Riesgo | Mitigación |
|--------|------------|
| Dos paths de activación (`ensure_membership` vs `activate_membership`) | Un solo servicio dominio seats-aware |
| Cookie web no revocable | F8 + TTL corto / re-check membership en middleware |
| Email linkage producer | FK F7 |
| Custom roles mal configurados abren PLATFORM | PLATFORM fuera de catálogo tenant |
| Sobreventa seats con invites | Reserva INVITED F4 |
| Romper GO `/me` | System role codes/scopes inmutables |
| IDOR cross-org | 404 + org de sesión únicamente |
| Scope Web HTML incompleto (F3 nota) | No empeorar; nuevos admin endpoints 100% scoped |

---

## N. Plan F1–F10 (orden)

| # | Fase | Dependencia |
|---|------|-------------|
| F1 | Catálogo Role/Permission + `members:*`/`roles:*` en AccessContext | Aprobación contrato |
| F2 | Lifecycle membership status | F1 |
| F3 | Invitations + email | F2 |
| F4 | Seat reserve INVITED + fail-closed | F3 |
| F5 | UI/API Colaboradores | F3–F4 |
| F6 | UI/API Roles | F1 |
| F7 | Producer FK linkage | F5 |
| F8 | Audit actions + revoke sessions | F2+ |
| F9 | E2E §29 | F5–F8 |
| F10 | Piloto DEV (Alfa/Beta) | F9 |

---

## Congruencia con trabajo en paralelo

| Hilo | Estado |
|------|--------|
| EN1 «Cliente canónico» vs `ets_commercial_customer` | CODITO — brief aparte; **no** bloquea F1 ESB internos, sí aclara seats entitlement |
| ESB GO F5A | **Congelado** |
| PROD | **No tocar** |
| Checkout Banistmo/Yappy + comprobante | Independiente; no mezclar con RBAC |

---

## Veredicto F0

Base ADR-008 F1–F6 es **suficiente** para extender.  
Gaps críticos: **lifecycle**, **invitations**, **custom roles**, **members/roles permissions**, **UI Configuración**, **revoke session**, **FK producer**.

**Siguiente turno (tras tu OK):** F1 — catálogo + permisos `members:*`/`roles:*` sin UI completa, o F1+F2 juntos si se prefiere schema primero.

**NO IMPLEMENTADO en este turno** (solo contrato + F0).
