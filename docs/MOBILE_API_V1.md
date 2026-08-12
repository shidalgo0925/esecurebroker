# ESB GO — Mobile API v1 (Gate B + ADR-008 F6 Producer)

**Namespace:** `/api/mobile/v1`  
**OpenAPI:** `https://esecurebroker-dev.etsrv.site/docs` (tag `mobile-v1`) · `/openapi.json`  
**Entorno:** DEV only (`/opt/corredores-dev`)

## Scope

| Role | `scope` | Visibilidad |
|------|---------|-------------|
| OWNER / ADMIN / BROKER / COLLECTIONS | `ORGANIZATION` | Cartera de la org (según permissions) |
| PRODUCER | `ASSIGNED_PORTFOLIO` | Policies PRIMARY vigentes (+ clientes/derivados) |
| PLATFORM | org operativa `ORGANIZATION` | Acceso SaaS |

Misma política Web/Mobile vía `AccessContext`. **No** Mobile API v2 por esta capacidad.

## Auth

| Method | Path | Notes |
|--------|------|--------|
| POST | `/auth/login` | JSON `{username,password}` → access + refresh Bearer |
| POST | `/auth/refresh` | Rotate refresh; new access |
| POST | `/auth/logout` | Revoke refresh |
| POST | `/session/organization` | Bind org (membership required); re-issues tokens |

Access token: HMAC signed (not Web cookie). Refresh: opaque, hashed in `mobile_refresh_tokens`.

Header: `Authorization: Bearer <access_token>`

### Multi-org

1. Login with multiple memberships → `requires_organization_selection=true` + `organizations[]`.
2. Client calls `POST /session/organization` with `organization_id`.
3. Arbitrary `organization_id` without membership → **403**.

## `/me`

Returns: `identity`, `organization`, `membership`, `role`, `scope`, `permissions`, `entitlements`, `session`, `organizations_available`, `producer_profile_id`.

- **Roles:** `OWNER` \| `ADMIN` \| `BROKER` \| `PRODUCER` \| `COLLECTIONS` \| `PLATFORM`
- **PRODUCER:** `scope=ASSIGNED_PORTFOLIO` + `producer_profile_id` (link Party.email ↔ username)
- **Entitlements `source`:** `en1` \| `en1_plan_mirror` \| `pending` \| `piloto_mirror`
- **Entitlements `seats`:** compound `{internal_seats, producer_seats, source}` (+ `seats_total` legacy)

## Resources (scoped)

| GET | Description |
|-----|-------------|
| `/today` | `build_today_home` filtrado por AccessContext |
| `/customers?q=&party_type=` | Lista/search scoped · **P0:** solo clientes con ≥1 PRIMARY en portfolio |
| `/customers/{id}` | Detail · fuera de scope → **404** |
| `/customers/{id}/360` | 360 filtrado; 0 policies visibles → **404** (misma allowlist que lista) |
| `/policies?q=&status=` | Lista scoped |
| `/policies/{id}` | Detail · fuera de scope → **404** |
| `/activities` | List/create gestiones (F5A) · contexto customer obligatorio |
| `/activities/{id}` | Detail gestión |
| `/documents?customer_id=` | List documentos del cliente |
| `/documents/upload` | Multipart upload idempotente (`client_upload_id`) |
| `/documents/{id}` | Metadata / ACK |

Cross-tenant / cross-portfolio → **404** `not_found` (no leak).

Ver también: `docs/MOBILE_F5A_BACKEND.md` · brief LOCAL `docs/briefs/LOCAL-f5a-after-backend.md`.

## Errors

```json
{ "error": { "code": "...", "message": "...", "details": {} } }
```

## DEV test users

Seed: `scripts/seed_mobile_dev_users.py` · password `ESB_DEV_SEED_PASSWORD`

| Email | Org | Role / scope |
|-------|-----|----------------|
| `owner.alfa@example.invalid` | Alfa | OWNER / ORGANIZATION |
| `broker.alfa2@example.invalid` | Alfa | BROKER / ORGANIZATION |
| `producer.alfa@example.invalid` | Alfa | PRODUCER / ASSIGNED_PORTFOLIO |
| `broker.beta@example.invalid` | Beta | BROKER / ORGANIZATION |
| `multi.dev@example.invalid` | Alfa+Beta | BROKER |

Alfa plan seed: `broker_red` (permite producer seats). Beta: `oficina`.

## Out of v1 (aún)

Claims write, FCM, offline-first EP1, price changes, SECONDARY portfolio.
