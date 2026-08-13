# ESB — Contrato de administración de Colaboradores, Roles, Permisos y Acceso por Organización

**DESTINO:** SPAGHETTI / ESecureBroker  
**AMBIENTE:** SOLO DEV  
**PROD:** NO TOCAR  
**ESB GO F5A:** congelado mientras se cierra este bloque  
**Autoridad comercial seats:** EN1 (SoR) · ESB solo consume entitlement  
**Extiende:** ADR-008 (F1–F6) — no lo reemplaza  
**F0:** `docs/ADR-008_F7_F0_INSPECTION.md` (inspección; sin implementación)

---

## 0. Objetivo

Construir la administración real del equipo de cada organización/correduría dentro de ESecureBroker.

Cada organización debe poder administrar:

1. Colaboradores  
2. Roles  
3. Permisos  
4. Invitaciones  
5. Activación / desactivación de accesos  
6. Productores vinculados cuando corresponda  
7. Scope de acceso  
8. Consumo de seats según entitlement EN1  
9. Auditoría  

**NO** construir CRUD directo sobre tablas.  
Debe existir **dominio/servicios** de administración de acceso.

Onboarding producto objetivo:

```
Registro → OWNER → crea organización → entra
  → agrega equipo → asigna roles
  → productores reciben cartera
  → trabajan Web / ESB GO con el mismo AccessContext
```

---

## 1. Principio de identidad

Una persona **NO** se duplica por sus funciones.

```
Carlos Pérez
   │
   ├── identidad / subject / BrokerAccount
   │
   ├── OrgMembership
   │      organization = Alfa
   │      role = PRODUCER
   │
   └── ProducerProfile
          organization = Alfa
```

| Relación | Significado |
|----------|-------------|
| `OrgMembership` | ACCESO a ESB |
| `ProducerProfile` | Función OPERATIVA/comercial como productor |

**Prohibido** crear `EmployeeX` / `UserX` / `ProducerX` como tres personas independientes.

---

## 2. Tenancy

Todo lo administrativo pertenece a una `Organization`.

```
Organization
   ├── Memberships / Colaboradores
   ├── Roles (system + custom)
   ├── RolePermissions
   ├── ProducerProfiles
   ├── PortfolioAssignments
   └── Invitations
```

- Admin de Org A **jamás** consulta/modifica/invita/revoca usuarios de Org B.  
- Cross-org → **404** (anti-IDOR; patrón ADR-007/008).  
- `organization_id` **siempre** de sesión/AccessContext — nunca confiar en el browser.  
- `PLATFORM` queda **fuera** del RBAC editable de correduría.

---

## 3. Concepto UX «Colaborador»

«Colaborador» es concepto UX. **No** exige nueva tabla de personas.

Fuente de verdad:

```
OrgMembership
+ Identity / BrokerAccount / subject_id
+ Role
+ AccessContext
```

**Pantalla:** Configuración → Colaboradores  

Columnas mínimas: Nombre · Email · Rol · Scope · Estado · Productor sí/no · Último acceso · Fecha de alta  

Acciones: Agregar · Ver · Editar · Cambiar rol · Activar · Desactivar · Reenviar invitación · Revocar invitación  

**NO DELETE físico** de memberships con historia.

---

## 4. Estados del colaborador (canónicos)

| Estado | Significado |
|--------|-------------|
| `INVITED` | Invitación emitida; aún sin activar |
| `ACTIVE` | Puede autenticarse según permisos |
| `INACTIVE` | Acceso temporalmente deshabilitado |
| `REVOKED` | Acceso retirado |

- No borrar actividad histórica.  
- Desactivación/revocación debe invalidar sesiones/refresh tokens según mecanismo existente (ver F0 gaps).  
- Hoy en código solo existe `OrgMembership.active` boolean → migrar a status (F2).

---

## 5. CRUD Colaboradores — Web

Ruta UX: **Configuración → Colaboradores**

Operaciones: `LIST` · `CREATE/INVITE` · `DETAIL` · `UPDATE` · `ACTIVATE` · `DEACTIVATE` · `REVOKE` · `RESEND INVITATION`

Formulario alta: Nombre · Apellido (si modelo lo separa) · Email · Rol · [Productor cuando corresponda]

---

## 6. Invitaciones

```
OWNER/ADMIN autorizado
   ↓
Agregar colaborador
   ↓
validar email + rol + seat
   ↓
crear invitación
   ↓
enviar email
   ↓
usuario acepta
   ↓
establece/activa credencial
   ↓
OrgMembership ACTIVE
```

Token: aleatorio · expiración · single-use · hash en DB · revocable · opaco en URL.

**Reenviar:** invalida token anterior y genera uno nuevo.

**Seats:** al emitir `INVITED` se **reserva** seat (evita sobreventa por invitaciones paralelas).

---

## 7–8. Roles — System vs Custom

### System roles (protegidos)

| Código | Scope default | Notas |
|--------|---------------|-------|
| `OWNER` | `ORGANIZATION` | ≥1 ACTIVE obligatorio; no eliminable |
| `ADMIN` | `ORGANIZATION` | Administración delegada |
| `BROKER` | `ORGANIZATION` | Operación org-wide |
| `PRODUCER` | `ASSIGNED_PORTFOLIO` | Vincula/crea `ProducerProfile` |
| `COLLECTIONS` | `ORGANIZATION` | Cobranza |

`PLATFORM` **no** es rol editable de organización.

**Regla dura:** no se permite redefinir qué significa un system role ni convertir `PRODUCER` en `ORGANIZATION` arbitrariamente. Protege el contrato que consume ESB GO (`/me`).

### Custom roles (tenant-scoped)

Ejemplos: «Asistente de renovaciones», «Supervisor de reclamos», «Solo lectura».

Modelo conceptual:

```
Role
  id
  organization_id   # NULL = system; UUID = custom de esa org
  code
  name
  description
  system_role       # bool
  active
  default_scope     # ORGANIZATION | ASSIGNED_PORTFOLIO
  created_at / updated_at
```

Custom de Alfa **no** existe para Beta.

---

## 9–10. CRUD Roles — Web

**Configuración → Roles y permisos**

`LIST` · `CREATE` · `DETAIL` · `UPDATE` · `ACTIVATE/DEACTIVATE` · `DUPLICATE` · `ASSIGN PERMISSIONS`

- No DELETE destructivo si alguna membership lo usó.  
- System: visibles, no eliminables, código no editable, permisos mínimos protegidos.  
- Custom: nombre/descripción/permisos editables; scope dentro de combinaciones permitidas.

---

## 11–12. Permissions canónicos

Formato: `resource:operation`

Catálogo inicial (capacidad de dominio — **no** por pantalla):

```
customers:read | create | update
policies:read | create | update
collections:read | create | update | manage
renewals:read | create | update | manage
claims:read | create | update | manage
documents:read | manage
activities:read | create | update
producers:read | manage
reports:read
members:read | manage
roles:read | manage
settings:read | manage
```

Resolución siempre vía:

```
AccessContext → require_permission / apply_scope / require_entity_in_scope
```

**Prohibido** `if role == "ADMIN"` disperso en rutas. ADR-008 F2 sigue como autoridad de enforcement.

---

## 13–14. Scope

Scopes canónicos: `ORGANIZATION` · `ASSIGNED_PORTFOLIO` · `PLATFORM`

| Rol system | Scope |
|------------|-------|
| OWNER / ADMIN / BROKER / COLLECTIONS | `ORGANIZATION` |
| PRODUCER | `ASSIGNED_PORTFOLIO` |

`permission ≠ scope`.  
Ej.: PRODUCER con `policies:read` solo ve pólizas de su cartera.

Custom role: scope `ORGANIZATION` o, si el dominio lo soporta, `ASSIGNED_PORTFOLIO`. Sin combinaciones incoherentes.

---

## 15. Caso especial PRODUCER

Al asignar rol PRODUCER:

```
Persona
  → OrgMembership (role=PRODUCER, scope=ASSIGNED_PORTFOLIO)
  → ProducerProfile (vincular si existe; crear si no)
  → PortfolioAssignments
```

- Al quitar acceso PRODUCER: **NO** borrar `ProducerProfile` automáticamente (histórico).  
- `ProducerProfile` sin membership: **no** consume seat de login.

---

## 16–17. Seats / EN1

EN1 = SoR comercial. ESB recibe entitlement (`plan_code`, `features`, `limits`, `source`).

| Membership ACTIVE / INVITED (reservado) | Bucket |
|-----------------------------------------|--------|
| OWNER / ADMIN / BROKER / COLLECTIONS (+ custom internal) | `internal_seats` |
| PRODUCER | `producer_seats` |

- Seat = acceso (activo o invitación reservada), **no** existencia de persona.  
- Profile-only producer → 0 seats.  
- Al exceder: bloquear con «Llegaste al límite…» + CTA «Administrar plan».  
- Fail-closed si no se puede verificar entitlement en operaciones que aumentan seats.  
- ESB **no** inventa ni hardcodea límites/precios.

---

## 18. Protección OWNER

1. Org debe conservar ≥1 `OWNER` `ACTIVE`.  
2. Un OWNER no puede desactivarse/revocarse a sí mismo si es el último.  
3. Cambio de OWNER = operación explícita.  
4. PLATFORM no se administra desde esta pantalla.  
5. ADMIN no se auto-eleva a OWNER sin flujo explícito de transferencia.

---

## 19. Matriz base de permisos (congelada para implementación)

| Capacidad | OWNER | ADMIN | BROKER | COLLECTIONS | PRODUCER |
|-----------|:-----:|:-----:|:------:|:-----------:|:--------:|
| Dominio cartera (customers/policies…)* | ✓ | ✓ | ✓ | lectura+cobranza | scoped ✓ |
| `collections:manage` | ✓ | ✓ | — | ✓ | — |
| `producers:manage` | ✓ | ✓ | — | — | — |
| `members:read` | ✓ | ✓ | — | — | — |
| `members:manage` | ✓ | ✓** | — | — | — |
| `roles:read` | ✓ | ✓ | — | — | — |
| `roles:manage` | ✓ | política*** | — | — | — |
| `settings:manage` | ✓ | ✓ | — | — | — |

\* Detalle exacto alineado a matriz F2 actual en `access_control.py`, extendida con `members:*` / `roles:*`.  
\*\* ADMIN con `members:manage` por defecto (configurable vía política de producto si se endurece).  
\*\*\* ADMIN: `roles:read` sí; `roles:manage` solo custom roles (no system), salvo que se decida restringir solo a OWNER en F6 UI.

**Congelar en código en F1** como catálogo + matriz; no improvisar por ruta.

---

## 20. API Admin (JSON)

```
/api/admin/v1/members
/api/admin/v1/members/{id}
/api/admin/v1/invitations
/api/admin/v1/roles
/api/admin/v1/roles/{id}
/api/admin/v1/permissions

POST .../activate | deactivate | revoke | resend
```

Web consume servicios de dominio compartidos. ESB GO **no** es requisito P0 de esta API.

---

## 21. Auditoría (acciones)

```
MEMBER_INVITED
MEMBER_INVITATION_RESENT
MEMBER_ACTIVATED
MEMBER_DEACTIVATED
MEMBER_REVOKED
MEMBER_ROLE_CHANGED

ROLE_CREATED
ROLE_UPDATED
ROLE_ACTIVATED
ROLE_DEACTIVATED
ROLE_PERMISSIONS_CHANGED

PRODUCER_LINKED
PRODUCER_ACCESS_GRANTED
PRODUCER_ACCESS_REVOKED
```

Payload: organization · actor · target · timestamp · before/after · metadata segura.  
**Nunca** passwords/tokens.

---

## 22–23. UI propuesta

```
Configuración
├── Organización
├── Colaboradores          ← NEW
├── Roles y permisos       ← NEW
├── Productores            (ya existe; se alinea)
├── Plan y suscripción
└── Integraciones
```

Detalle colaborador: Información · Acceso · Rol/permisos · Productor (si aplica) · Auditoría de seguridad.

Roles UI: system (solo lectura/protegidos) + custom con editor de permisos agrupados por dominio.

---

## 24–25. No confundir dominios

| EN1 | ESB |
|-----|-----|
| Cliente ETS | Organización correduría |
| Contrato / subscription / entitlement | Colaboradores / memberships |
| Plan / limits comerciales | Roles / permissions / ProducerProfile |

| Colaborador ESB | Cliente/Asegurado ESB |
|-----------------|----------------------|
| Trabaja *en* la correduría | Compra/asegura *con* la correduría |

---

## 26. Compatibilidad ESB GO

GO sigue consumiendo `/me`: `role`, `scope`, `permissions`, `entitlements`, `producer_profile_id`.

- No reimplementa RBAC.  
- Cambio de rol → nueva sesión/refresh obtiene contexto actualizado.  
- Acceso revocado → refresh/session deja de funcionar.

---

## 27. Migración / reutilización

**Reutilizar:** `OrgMembership` · `ProducerProfile` · `PortfolioAssignment` · `AccessContext` · enforcement F2/F3 · seats F5 · `AuditEvent`.

**Agregar (tras F0):** status lifecycle · Invitation · Role/RolePermission (si se aprueba catálogo DB) · servicios admin · UI · audit actions · revoke sessions.

Inspeccionar esquema **antes** de crear tablas → ver F0.

---

## 28. Fases

| Fase | Contenido | Implementar? |
|------|-----------|--------------|
| **F0** | Inspección / contrato final | Solo docs ✓ |
| **F1** | Role + Permission catalog (DB o módulo formal + `members:*`/`roles:*`) | Tras aprobación |
| **F2** | Membership lifecycle (INVITED/ACTIVE/INACTIVE/REVOKED) | |
| **F3** | Invitations | |
| **F4** | Seats enforcement EN1 (incl. reserva INVITED) | |
| **F5** | CRUD Colaboradores Web | |
| **F6** | CRUD Roles/Permissions Web | |
| **F7** | Producer linkage (FK membership↔profile) | |
| **F8** | Audit + session revoke | |
| **F9** | E2E (casos §29) | |
| **F10** | Piloto DEV | |

No PROD.

---

## 29. E2E obligatorios

1. OWNER invita ADMIN → acepta → login → ORGANIZATION → permisos OK  
2. OWNER invita PRODUCER → ProducerProfile → ASSIGNED_PORTFOLIO → cartera → GO `/me` OK  
3. COLLECTIONS → cobranza OK · roles/settings denied  
4. Custom role «Supervisor Reclamos» → enforcement server-side  
5. Seat limit → última OK · siguiente bloqueada  
6. Desactivar → login/refresh revocado · histórico permanece  
7. Cross-org Alfa→Beta → 404  
8. Último OWNER → no desactivar/revocar  
9. Producer sin login → profile existe · 0 seat  
10. Reactivar → revalida seat · histórico intacto  

---

## 30. Invariantes (congelados)

1. Colaborador pertenece a Organization.  
2. Organization nunca viene confiada del cliente.  
3. No DELETE destructivo de memberships con historia.  
4. ≥1 OWNER ACTIVE por org.  
5. PLATFORM fuera de administración tenant.  
6. Permission y Scope son conceptos separados.  
7. Enforcement siempre server-side.  
8. PRODUCER usa ASSIGNED_PORTFOLIO.  
9. ProducerProfile no implica login.  
10. Membership PRODUCER no duplica ProducerProfile.  
11. Seats provienen del entitlement EN1.  
12. ESB no hardcodea precios.  
13. Custom roles son tenant-scoped.  
14. System roles están protegidos (código/scope/semántica).  
15. Cross-org/cross-scope protegido contra IDOR (404).  
16. Revocar acceso no borra actividad histórica.  
17. Cambios sensibles quedan auditados.  
18. ESB GO consume AccessContext; no inventa seguridad.  
19. Cliente asegurado ≠ colaborador.  
20. Cliente ETS en EN1 ≠ colaborador ESB.  

---

## 31. Decisiones de diseño (congeladas aquí)

| Decisión | Resolución |
|----------|------------|
| CRUD roles | Sí, con system roles inmutables en semántica |
| Custom roles | Sí, tenant-scoped, a partir de catálogo de permissions |
| Invitaciones | Obligatorias para alta operativa (no solo seed) |
| Seat INVITED | Reserva seat al invitar |
| Delete membership | No; solo INACTIVE/REVOKED |
| Producer + colaborador | Misma persona; dos relaciones |
| EN1 | Solo seats/entitlement; no plantilla laboral |
| F5A Mobile | Congelado durante este bloque |

---

## 32. Entrega F0 (este turno)

Ver `docs/ADR-008_F7_F0_INSPECTION.md`.

**NO IMPLEMENTAR** Colaboradores/Roles UI ni migraciones en F0.  
**NO PROD.**  
**NO romper** ADR-008 F1–F6.
