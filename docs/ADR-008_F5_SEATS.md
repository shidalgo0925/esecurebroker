# ADR-008 F5 — Seats EN1 (DEV)

## Decisiones

| Tema | Decisión |
|------|----------|
| SoR cupo | EN1 cuando `limits.internal_seats` / `limits.producer_seats` llegan en entitlement |
| Mirror | Si EN1 aún no envía compound seats → catálogo PLANES (`en1_plan_mirror` / `plan_catalog`) |
| `internal_seats` | Memberships activas **no** PRODUCER / PLATFORM |
| `producer_seats` | Memberships activas `role=PRODUCER` (profile solo **no** cuenta) |
| Enforcement | Al **activar acceso** (`activate_membership` / grant PRODUCER) |
| No inventar | Sin fake EN1; persist solo si el JSON trae las keys |

## Catálogo mirror (hasta contrato CODITO)

| Plan | internal | producer |
|------|----------|----------|
| individual | 1 | 0 |
| oficina | 15 | 0 |
| broker_red | 15 | ∞ (None) |
| enterprise | ∞ | ∞ |

## Entregado

- `corredores/services/seats.py`
- Columnas `org_subscriptions.seats_limits_source|internal_seats_limit|producer_seats_limit`
- Persist desde entitlement en checkout EN1
- `/me` entitlements.seats = compound (+ `seats_total` legacy)
- UI Productores: cupos + “Activar acceso PRODUCER”

## Fuera de F5 → F6

ESB GO Producer UX (filtros ya en F3; F6 = certificación producto GO).
