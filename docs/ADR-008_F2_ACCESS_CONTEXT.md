# ADR-008 F2 — AccessContext / RBAC (DEV)

## Delivered

- `corredores/services/access_control.py`
  - `AccessContext`, `resolve_access_context`
  - `require_permission`, `apply_scope_to_policy_query`, `apply_scope_to_party_query`
  - `require_policy_in_scope`, `require_party_in_scope` (404 anti-IDOR)
- Mobile `/me` reports `role`, `scope`, `permissions`, `producer_profile_id`
- Mobile customer/policy **detail** + 360 policy filter use AccessContext
- PRODUCER → `scope=ASSIGNED_PORTFOLIO` when Membership + profile linked by Party.email

## Not in F2 (→ F3)

- `build_today_home` scoped lists
- Mobile `/customers` and `/policies` **list** filtering
- Producer Admin UI / seats

## Link Membership → ProducerProfile (temporary)

Match `Party.email` (lower) to username. Future: explicit FK on membership (optional).
