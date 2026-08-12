# ADR-008 F2 — AccessContext / RBAC (DEV)

**Estado:** DONE · commit `7632049`

## Delivered

- `corredores/services/access_control.py`
  - `AccessContext`, `resolve_access_context`
  - `require_permission`, `apply_scope_to_policy_query`, `apply_scope_to_party_query`
  - `require_policy_in_scope`, `require_party_in_scope` (404 anti-IDOR)
- Mobile `/me` reports `role`, `scope`, `permissions`, `producer_profile_id`
- Mobile customer/policy **detail** use AccessContext
- PRODUCER → `scope=ASSIGNED_PORTFOLIO` when Membership + profile linked by Party.email

## Deferred to F3 (now in progress / done separately)

- Listas `/customers` `/policies`, `/today`, Web Hoy/Radar scoped

## Link Membership → ProducerProfile (temporary)

Match `Party.email` (lower) to username. Future: explicit FK on membership (optional).
