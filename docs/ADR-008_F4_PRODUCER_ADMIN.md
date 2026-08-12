# ADR-008 F4 — Producer Admin (DEV)

## Delivered

- Service: `create_producer_person`, `reassign_policy_primary` (reason + assigned_by),
  `list_producer_profiles`, `assignment_history_for_policy`, `active_assignments_for_producer`
- Web UI (Gestión → Productores):
  - `/productores` — list + alta
  - `/productores/{id}` — cartera activa + assign/reassign
  - `/polizas/{id}/productor` — historial + reasignar
- Link desde detalle de póliza → Productor
- Gate `producers:manage` vía AccessContext (auth on)

## Not in F4 (→ F5+)

- Seats EN1 (`producer_seats` / `internal_seats`)
- Crear OrgMembership PRODUCER al alta (acceso sistema)
- SECONDARY collaborators

## PROD

No tocado.
