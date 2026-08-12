# ESB GO — Mobile API v1 (Gate B)

**Namespace:** `/api/mobile/v1`  
**OpenAPI:** `https://esecurebroker-dev.etsrv.site/docs` (tag `mobile-v1`) · `/openapi.json`  
**Entorno:** DEV only (`/opt/corredores-dev`)  
**Scope v1:** `ORGANIZATION` only (`ASSIGNED_PORTFOLIO` **not** implemented)

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

Returns: `identity`, `organization`, `membership`, `role`, `scope`, `permissions`, `entitlements`, `session`, `organizations_available`.

- **Roles v1:** `OWNER` \| `BROKER` \| `PLATFORM` (real today).
- **Scope v1:** always `ORGANIZATION`.
- **Entitlements `source`:** `en1` \| `pending` \| `piloto_mirror` (never invent EN1).

## Resources

| GET | Description |
|-----|-------------|
| `/today` | From `build_today_home` → money, attention, system_work, opportunities |
| `/customers?q=&party_type=` | Search: name, national_id, phone, email (**not** plate/policy) |
| `/customers/{id}` | Detail |
| `/customers/{id}/360` | From `build_client_360` |
| `/policies?q=&status=` | List/search |
| `/policies/{id}` | Detail + vehicle when present |

Cross-tenant IDs → **404** `not_found` (no leak).

## Errors

```json
{ "error": { "code": "...", "message": "...", "details": {} } }
```

## DEV test users (pytest)

| Email | Org | Role |
|-------|-----|------|
| `owner.alfa@example.invalid` | Alfa | OWNER |
| `broker.alfa2@example.invalid` | Alfa | BROKER |
| `broker.beta@example.invalid` | Beta | BROKER |

Password: `secreto123` (tests only).

## Out of v1

PRODUCER / ASSIGNED_PORTFOLIO, full RBAC, uploads, claims write, FCM, offline, price changes.
