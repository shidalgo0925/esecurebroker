# ADR-008 F7 — Implementation notes (DEV)

**Estado:** implementado en DEV (2026-08-13)  
**PROD:** no tocado  
**Contrato:** `ADR-008_F7_COLLABORATORS_RBAC_CONTRACT.md`

## Entregado

| Pieza | Ubicación |
|-------|-----------|
| Permission catalog + system matrix | `domain/permissions_catalog.py` |
| Membership statuses | `domain/membership_roles.py` |
| Models: status, OrgRole, OrgRolePermission, OrgInvitation | `domain/models.py` |
| Migration | `alembic/versions/c7d8e9f0a1b2_adr008_f7_collaborators_rbac.py` |
| Domain services | `services/org_access_admin.py` |
| Seat hold INVITED+ACTIVE | `services/seats.py` |
| AccessContext custom roles + FK producer | `services/access_control.py` |
| Web UI | `/configuracion/colaboradores`, `/configuracion/roles` |
| Invite accept | `/invitacion/{token}` (público) |
| Tests | `tests/test_org_access_admin_f7.py` |

## UX

1. OWNER/ADMIN → Configuración → **Colaboradores** → Invitar  
2. Invitar / reenviar → SMTP si está configurado (`invite_mail.py`); si no, enlace en UI  
3. Colaborador abre `/invitacion/...` → crea contraseña → `/hoy`  
4. **Roles y permisos** → ver system (RO) + crear custom  

## Pendiente / siguiente

- API JSON `/api/admin/v1/...` (contrato §20)  
- E2E UI completo casos §29  
- Cookie web denylist (hoy solo refresh mobile revoke)  
- CODITO Cliente canónico EN1 (paralelo)  
