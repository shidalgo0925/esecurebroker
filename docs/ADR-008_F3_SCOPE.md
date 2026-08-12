# ADR-008 F3 — Scope enforcement (DEV)

## Delivered

- `scope_allowlists(session, ctx)` → `(policy_ids, party_ids)`
- Mobile `/customers`, `/policies` lists filtered by AccessContext
- Mobile `/today` → `build_today_home(..., policy_ids, party_ids)`
- Mobile 360 uses same allowlist (0 policies → 404)
- Web `/hoy` + `/radar` respect AccessContext when auth on
- `build_radar(..., policy_ids=)` scoped aggregates

## Not in F3 (→ F4+)

- Producer Admin UI (alta/assign/reassign)
- Seats EN1
- Full Web customers/policies HTML list scoping (beyond Hoy/Radar)
- Claims/documents/renewals dedicated surfaces scoped end-to-end

## Compat

OWNER/ADMIN/BROKER: `ORGANIZATION` — comportamiento previo.
PRODUCER: `ASSIGNED_PORTFOLIO` — solo PRIMARY vigente.
