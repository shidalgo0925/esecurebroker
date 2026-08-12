# BRIEF LOCAL — ESB GO F5A (después de backend READY)

**Backend:** `/api/mobile/v1` · DEV `https://esecurebroker-dev.etsrv.site`  
**Contrato:** `docs/MOBILE_F5A_BACKEND.md` · OpenAPI tag `mobile-v1`

## Qué construir en el teléfono (F5A)

Desde **+** en cliente / 360 / póliza:

1. **Registrar gestión** → `POST /activities`
2. **Tomar foto / adjuntar documento** → `POST /documents/upload` (multipart)

## Contexto obligatorio en cada operación

```text
customer_id          (siempre)
policy_id            (si viene de pantalla póliza / 360 póliza)
activity_type | document_type
client_activity_id | client_upload_id   (UUID estable del device)
```

No enviar `organization_id` de confianza: sale del token.

## Estados locales sugeridos

| Local | Significado |
|-------|-------------|
| LOCAL | creado offline / en cola |
| UPLOADING | request en vuelo |
| SYNCED | ACK `status=SYNCED` recibido |
| FAILED | error no-idempotente / red |

Solo marcar **SYNCED** con ACK persistido (`document_id` / activity `id` + `status=SYNCED`).

## Idempotencia

Reintentos: **mismo** `client_upload_id` / `client_activity_id` + mismo payload.  
409 = conflict (no reutilizar key con otro archivo/contexto).

## Scope

Usuario `producer.alfa@example.invalid`: solo cartera PRIMARY.  
Out-of-scope → 404 (no mostrar como fallo de red genérico).

## Fuera de F5A (no ahora)

Claims write · FCM · offline-first EP1 · F5B
