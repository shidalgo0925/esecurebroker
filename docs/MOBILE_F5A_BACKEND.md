# ESB GO F5A — Backend contract (DEV)

## Reused domain

| Piece | Source |
|-------|--------|
| Gestiones | `Interaction` + `log_interaction` |
| Documentos | `Document` + `save_party_pdf` |
| Scope | ADR-008 `AccessContext` |
| Storage | `DOCUMENTS_ROOT/{org}/{party}/{uuid}.ext` |

## Endpoints (`/api/mobile/v1`)

| Method | Path | Notes |
|--------|------|--------|
| GET | `/activities?customer_id=&policy_id=` | list scoped |
| POST | `/activities` | create + optional `client_activity_id` |
| GET | `/activities/{id}` | detail |
| GET | `/documents?customer_id=` | list |
| POST | `/documents/upload` | multipart |
| GET | `/documents/{id}` | metadata ACK |

## Activity contract

```json
{
  "customer_id": "...",          // required
  "policy_id": null,             // optional, must belong to customer + in scope
  "activity_type": "VISIT",      // NOTE|CALL|EMAIL|WHATSAPP|VISIT|OTHER
  "note": "...",
  "client_activity_id": "device-uuid"  // idempotency
}
```

Response: `{ id, customer_id, policy_id, activity_type, note, actor_id, created_at, status: "SYNCED", idempotency }`

## Upload contract (multipart)

Fields: `file`, `customer_id`, `client_upload_id` (required), `document_type`, `policy_id?`, `title?`

ACK:

```json
{
  "document_id": "...",
  "status": "SYNCED",
  "created_at": "...",
  "idempotency": "created|replayed",
  "context": {
    "customer_id": "...",
    "policy_id": "...",
    "document_type": "CEDULA",
    "client_upload_id": "..."
  }
}
```

LOCAL mapping: LOCAL → UPLOADING → **SYNCED** only after ACK `status=SYNCED`.

## Idempotency

- Same key + same payload/context/hash → `replayed` (200)
- Same key + different context/file → **409** `idempotency_conflict`

## Permissions

- activities: `activities:read` / `activities:create`
- documents: `documents:read` / `documents:manage`
- + entity in AccessContext scope (404 cross-org/portfolio)

## Not in F5A

Claims write · FCM · offline EP1 · Flutter · PROD
