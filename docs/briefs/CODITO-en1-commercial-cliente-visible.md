# BRIEF CODITO — EN1: alta ESB debe verse como Cliente (DEV)

**From:** SPAGHETTI / ESB DEV  
**Host EN1:** `https://appdev.easynodeone.com`  
**Producto:** `esecurebroker`  
**Contrato:** ADR-037 · bridge C1 `POST /api/v1/commercial/bootstrap` → `checkout` → `entitlement`

## Problema (repro)

1. Usuario se registra en `https://esecurebroker-dev.etsrv.site/registro`
2. ESB llama bootstrap + checkout (promo) OK
3. Entitlement confirma `customer_id` activo
4. Operador **no ve** el comprador en EN1 UI:
   - `/admin/organizations` (busca org nueva — no aparece)
   - Clientes / Contactos / CRM

Ejemplo vivo DEV:

| Campo | Valor |
|-------|--------|
| Email | `shidalgo0925@outlook.com` |
| Razón social ESB | Easy Technology Services |
| EN1 `customer_id` | **24** |
| EN1 `subscription_id` | **39** |
| Plan | `office` |
| Entitlement | `entitled=true` / `state=active` |

## Expectativa de producto

Si el bridge graba un comprador SaaS, debe existir un registro **visible** en EN1 bajo la **org provider ETS** (no bajo org catálogo PRD `#11` / `en1-prd-catalog`).

Norma ADR-037:

```text
EN1 provider org  ≠  correduría ESB
EN1 customer_id   =  ancla comercial del comprador
ESB organization  =  dominio operativo
```

**No** debe crear una fila engañosa en Organizaciones como si fuera tenant EN1 independiente, **salvo** que el diseño comercial diga explícitamente “tenant SaaS = saas_organization”.  
Lo mínimo aceptable: **Cliente / Contacto / ficha comercial** consultable en UI provider, con:

- legal_name
- email
- customer_id
- product_code = esecurebroker
- subscription status
- link a contract/subscription

## Qué ya hace ESB (no tocar / no rehacer)

Payload bootstrap (ya enviado):

```json
{
  "product_code": "esecurebroker",
  "plan_code": "office|individual|broker",
  "identity": { "email", "full_name", "external_subject_id" },
  "customer": { "email", "legal_name", "country", "phone", "esb_organization_id?" }
}
```

ESB **fail-closed**: sin `customer_id` / `contract_id` / `user_id` no crea cuenta local.

## Gap EN1 (CODITO)

| Gap | Detalle |
|-----|---------|
| G1 | Bootstrap crea identidad comercial API-only; no materializa ficha UI “Cliente” |
| G2 | `/admin/organizations` no es el listado correcto y confunde ops |
| G3 | Falta pantalla o filtro: “Clientes comerciales / Suscripciones producto” por `product_code` |
| G4 | Confirmar `provider_organization_id` en respuesta bootstrap = org ETS real (no catálogo PRD #11) |

## Pedido

1. Confirmar en DEV: para `customer_id=24`, ¿en qué tabla/org queda y cómo se abre en UI?
2. Implementar materialización visible (Cliente o Suscripciones producto) en org provider.
3. Documentar ruta UI exacta para ops ESB.
4. E2E: registro ESB → aparece ficha en EN1 DEV en &lt; 1 min.

## Fuera de alcance ESB

- No inventar segundo alta CRM desde ESB.
- No escribir en `/admin/organizations` desde el APK/ESB.
- No tocar PROD.

## Criterio DONE

Operador en `appdev` encuentra al comprador ESB sin API manual, bajo provider ETS, con email + legal_name + customer_id + suscripción activa.
