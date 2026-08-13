"""ADR-008 F7 — Colaboradores + Roles UI routes."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from corredores.domain.membership_roles import ORG_ASSIGNABLE_ROLES
from corredores.domain.models import Organization, OrgInvitation
from corredores.domain.permissions_catalog import (
    PERMISSION_CATALOG,
    PERMISSION_GROUPS,
    SYSTEM_ROLE_LABELS,
    SYSTEM_ROLE_PERMISSIONS,
)
from corredores.services.access_control import AccessDenied, require_permission
from corredores.services.invite_mail import send_collaborator_invite_email
from corredores.services.org_access_admin import (
    AccessAdminError,
    accept_invitation,
    activate_member,
    change_member_role,
    create_custom_role,
    deactivate_member,
    ensure_system_roles,
    get_membership_in_org,
    get_role,
    hash_invite_token,
    invite_collaborator,
    list_collaborators,
    list_roles_for_org,
    resend_invitation,
    revoke_member,
    role_permission_codes,
    seats_banner,
    update_custom_role,
)
from corredores.services.saas_signup import find_account_by_subject
from corredores.web.auth_session import attach_session_cookie
from corredores.web.deps import current_access_context, get_session, resolve_org
from corredores.web.routes import _ctx, _env_flags, templates

router = APIRouter()


def _require_perm(session: Session, request: Request, code: str, msg: str) -> None:
    access = current_access_context(session, request)
    if access is None:
        return
    try:
        require_permission(access, code)
    except AccessDenied as e:
        raise HTTPException(403, msg) from e


def _actor_subject(request: Request) -> str | None:
    from corredores.web.auth_session import read_session

    p = read_session(request)
    return p.actor_id if p else None


def _role_options(session: Session, organization_id: str) -> list[tuple[str, str]]:
    custom = [r for r in list_roles_for_org(session, organization_id) if not r.system_role and r.active]
    opts = [(c, SYSTEM_ROLE_LABELS.get(c, c)) for c in sorted(ORG_ASSIGNABLE_ROLES)]
    opts += [(r.code, r.name) for r in custom]
    return opts


def _role_label(session: Session, organization_id: str, role_code: str) -> str:
    if role_code in SYSTEM_ROLE_LABELS:
        return SYSTEM_ROLE_LABELS[role_code]
    for role in list_roles_for_org(session, organization_id):
        if role.code == role_code:
            return role.name
    return role_code


def _dispatch_invite_mail(
    *,
    session: Session,
    org: Organization,
    to_email: str,
    invitee_name: str,
    role_code: str,
    invite_url: str,
) -> str:
    """Returns mail=sent|skipped|failed for flash query."""
    result = send_collaborator_invite_email(
        to_email=to_email,
        invite_url=invite_url,
        org_name=org.name,
        invitee_name=invitee_name,
        role_label=_role_label(session, org.id, role_code),
    )
    if result.ok:
        return "sent"
    if "deshabilitado" in result.detail or "SMTP incompleto" in result.detail:
        return "skipped"
    return "failed"


@router.get("/configuracion/colaboradores", response_class=HTMLResponse)
def colaboradores_list(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session, request)
    _require_perm(session, request, "members:manage", "sin permiso para administrar colaboradores")
    ensure_system_roles(session)
    return templates.TemplateResponse(
        request,
        "colaboradores.html",
        _ctx(
            request,
            "configuracion",
            org_name=org.name,
            members=list_collaborators(session, org.id),
            seats=seats_banner(session, org.id),
            role_options=_role_options(session, org.id),
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
            invite_url=request.query_params.get("invite_url") or "",
            mail_status=request.query_params.get("mail") or "",
        ),
    )


@router.post("/configuracion/colaboradores/invitar")
def colaboradores_invitar(
    request: Request,
    display_name: str = Form(...),
    email: str = Form(...),
    role_code: str = Form(...),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_perm(session, request, "members:manage", "sin permiso para administrar colaboradores")
    try:
        membership, _inv, raw = invite_collaborator(
            session,
            organization_id=org.id,
            email=email,
            display_name=display_name,
            role_code=role_code,
            actor_subject_id=_actor_subject(request),
        )
        session.commit()
    except AccessAdminError as exc:
        session.rollback()
        return RedirectResponse(
            f"/configuracion/colaboradores?error={quote(str(exc))}", status_code=303
        )
    link = str(request.base_url).rstrip("/") + f"/invitacion/{raw}"
    mail = _dispatch_invite_mail(
        session=session,
        org=org,
        to_email=membership.email or email,
        invitee_name=membership.display_name or display_name,
        role_code=membership.role_code,
        invite_url=link,
    )
    return RedirectResponse(
        f"/configuracion/colaboradores?ok=invited&mail={mail}&invite_url={quote(link, safe='')}",
        status_code=303,
    )


@router.get("/configuracion/colaboradores/{membership_id}", response_class=HTMLResponse)
def colaborador_detalle(
    membership_id: str, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    _require_perm(session, request, "members:manage", "sin permiso para administrar colaboradores")
    m = get_membership_in_org(session, org.id, membership_id)
    if m is None:
        raise HTTPException(404, "no encontrado")
    detail = next((r for r in list_collaborators(session, org.id) if r["id"] == membership_id), None)
    return templates.TemplateResponse(
        request,
        "colaborador_detalle.html",
        _ctx(
            request,
            "configuracion",
            org_name=org.name,
            member=detail,
            membership=m,
            role_options=_role_options(session, org.id),
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
            invite_url=request.query_params.get("invite_url") or "",
            mail_status=request.query_params.get("mail") or "",
        ),
    )


@router.post("/configuracion/colaboradores/{membership_id}/rol")
def colaborador_cambiar_rol(
    membership_id: str,
    request: Request,
    role_code: str = Form(...),
    session: Session = Depends(get_session),
):
    org = resolve_org(session, request)
    _require_perm(session, request, "members:manage", "sin permiso para administrar colaboradores")
    try:
        change_member_role(
            session,
            organization_id=org.id,
            membership_id=membership_id,
            new_role=role_code,
            actor_subject_id=_actor_subject(request),
        )
    except AccessAdminError as exc:
        return RedirectResponse(
            f"/configuracion/colaboradores/{membership_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/configuracion/colaboradores/{membership_id}?ok=role", status_code=303
    )


@router.post("/configuracion/colaboradores/{membership_id}/desactivar")
def colaborador_desactivar(
    membership_id: str, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    _require_perm(session, request, "members:manage", "sin permiso para administrar colaboradores")
    try:
        deactivate_member(
            session,
            organization_id=org.id,
            membership_id=membership_id,
            actor_subject_id=_actor_subject(request),
        )
    except AccessAdminError as exc:
        return RedirectResponse(
            f"/configuracion/colaboradores/{membership_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/configuracion/colaboradores/{membership_id}?ok=deactivated", status_code=303
    )


@router.post("/configuracion/colaboradores/{membership_id}/activar")
def colaborador_activar(
    membership_id: str, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    _require_perm(session, request, "members:manage", "sin permiso para administrar colaboradores")
    try:
        activate_member(
            session,
            organization_id=org.id,
            membership_id=membership_id,
            actor_subject_id=_actor_subject(request),
        )
    except AccessAdminError as exc:
        return RedirectResponse(
            f"/configuracion/colaboradores/{membership_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/configuracion/colaboradores/{membership_id}?ok=activated", status_code=303
    )


@router.post("/configuracion/colaboradores/{membership_id}/revocar")
def colaborador_revocar(
    membership_id: str, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    _require_perm(session, request, "members:manage", "sin permiso para administrar colaboradores")
    try:
        revoke_member(
            session,
            organization_id=org.id,
            membership_id=membership_id,
            actor_subject_id=_actor_subject(request),
        )
    except AccessAdminError as exc:
        return RedirectResponse(
            f"/configuracion/colaboradores/{membership_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse("/configuracion/colaboradores?ok=revoked", status_code=303)


@router.post("/configuracion/colaboradores/{membership_id}/reenviar")
def colaborador_reenviar(
    membership_id: str, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    _require_perm(session, request, "members:manage", "sin permiso para administrar colaboradores")
    try:
        inv, raw = resend_invitation(
            session,
            organization_id=org.id,
            membership_id=membership_id,
            actor_subject_id=_actor_subject(request),
        )
        membership = get_membership_in_org(session, org.id, membership_id)
        session.commit()
    except AccessAdminError as exc:
        session.rollback()
        return RedirectResponse(
            f"/configuracion/colaboradores/{membership_id}?error={quote(str(exc))}",
            status_code=303,
        )
    link = str(request.base_url).rstrip("/") + f"/invitacion/{raw}"
    mail = _dispatch_invite_mail(
        session=session,
        org=org,
        to_email=(membership.email if membership else None) or inv.email,
        invitee_name=(membership.display_name if membership else "") or inv.email,
        role_code=(membership.role_code if membership else None) or inv.role_code,
        invite_url=link,
    )
    return RedirectResponse(
        f"/configuracion/colaboradores/{membership_id}?ok=resent&mail={mail}"
        f"&invite_url={quote(link, safe='')}",
        status_code=303,
    )


@router.get("/configuracion/roles", response_class=HTMLResponse)
def roles_list(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session, request)
    _require_perm(session, request, "roles:read", "sin permiso para ver roles")
    roles = list_roles_for_org(session, org.id)
    return templates.TemplateResponse(
        request,
        "roles.html",
        _ctx(
            request,
            "configuracion",
            org_name=org.name,
            system_roles=[r for r in roles if r.system_role],
            custom_roles=[r for r in roles if not r.system_role],
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
        ),
    )


@router.get("/configuracion/roles/nuevo", response_class=HTMLResponse)
def roles_nuevo_get(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session, request)
    _require_perm(session, request, "roles:manage", "sin permiso para administrar roles")
    return templates.TemplateResponse(
        request,
        "rol_editar.html",
        _ctx(
            request,
            "configuracion",
            org_name=org.name,
            role=None,
            selected=set(),
            permission_groups=PERMISSION_GROUPS,
            all_permissions=PERMISSION_CATALOG,
            error=None,
            readonly=False,
        ),
    )


@router.post("/configuracion/roles/crear")
async def roles_crear(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session, request)
    _require_perm(session, request, "roles:manage", "sin permiso para administrar roles")
    form = await request.form()
    code = str(form.get("code") or "")
    name = str(form.get("name") or "")
    description = str(form.get("description") or "")
    default_scope = str(form.get("default_scope") or "ORGANIZATION")
    perms = [str(v) for v in form.getlist("permissions")]
    try:
        row = create_custom_role(
            session,
            organization_id=org.id,
            code=code,
            name=name,
            description=description,
            default_scope=default_scope,
            permissions=perms,
            actor_id=_actor_subject(request),
        )
    except AccessAdminError as exc:
        return templates.TemplateResponse(
            request,
            "rol_editar.html",
            _ctx(
                request,
                "configuracion",
                org_name=org.name,
                role=None,
                selected=set(perms),
                permission_groups=PERMISSION_GROUPS,
                all_permissions=PERMISSION_CATALOG,
                error=str(exc),
                readonly=False,
            ),
            status_code=400,
        )
    return RedirectResponse(f"/configuracion/roles/{row.id}?ok=created", status_code=303)


@router.get("/configuracion/roles/{role_id}", response_class=HTMLResponse)
def roles_detalle(role_id: str, request: Request, session: Session = Depends(get_session)):
    org = resolve_org(session, request)
    _require_perm(session, request, "roles:read", "sin permiso para ver roles")
    role = get_role(session, org.id, role_id)
    if role is None:
        raise HTTPException(404, "no encontrado")
    if role.system_role:
        selected = set(SYSTEM_ROLE_PERMISSIONS.get(role.code, ()))
    else:
        selected = set(role_permission_codes(session, role.id))
    return templates.TemplateResponse(
        request,
        "rol_editar.html",
        _ctx(
            request,
            "configuracion",
            org_name=org.name,
            role=role,
            selected=selected,
            permission_groups=PERMISSION_GROUPS,
            all_permissions=PERMISSION_CATALOG,
            flash=request.query_params.get("ok"),
            error=request.query_params.get("error"),
            readonly=bool(role.system_role),
        ),
    )


@router.post("/configuracion/roles/{role_id}")
async def roles_guardar(
    role_id: str, request: Request, session: Session = Depends(get_session)
):
    org = resolve_org(session, request)
    _require_perm(session, request, "roles:manage", "sin permiso para administrar roles")
    role = get_role(session, org.id, role_id)
    if role is None:
        raise HTTPException(404, "no encontrado")
    if role.system_role:
        return RedirectResponse(
            f"/configuracion/roles/{role_id}?error={quote('roles de sistema no editables')}",
            status_code=303,
        )
    form = await request.form()
    try:
        update_custom_role(
            session,
            organization_id=org.id,
            role_id=role_id,
            name=str(form.get("name") or role.name),
            description=str(form.get("description") or ""),
            default_scope=str(form.get("default_scope") or role.default_scope),
            permissions=[str(v) for v in form.getlist("permissions")],
            active=str(form.get("active") or "") in {"1", "true", "on", "yes"},
            actor_id=_actor_subject(request),
        )
    except AccessAdminError as exc:
        return RedirectResponse(
            f"/configuracion/roles/{role_id}?error={quote(str(exc))}", status_code=303
        )
    return RedirectResponse(f"/configuracion/roles/{role_id}?ok=saved", status_code=303)


@router.get("/invitacion/{token}", response_class=HTMLResponse)
def invitacion_get(token: str, request: Request, session: Session = Depends(get_session)):
    inv = (
        session.query(OrgInvitation)
        .filter_by(token_hash=hash_invite_token(token), status="PENDING")
        .one_or_none()
    )
    org = session.get(Organization, inv.organization_id) if inv else None
    return templates.TemplateResponse(
        request,
        "invitacion_aceptar.html",
        {
            **_env_flags(),
            "token": token,
            "valid": inv is not None,
            "email": inv.email if inv else "",
            "role_code": inv.role_code if inv else "",
            "org_name": org.name if org else "",
            "error": None,
        },
    )


@router.post("/invitacion/{token}")
def invitacion_post(
    token: str,
    request: Request,
    password: str = Form(...),
    display_name: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        membership = accept_invitation(
            session,
            raw_token=token,
            password=password,
            display_name=display_name or None,
        )
    except AccessAdminError as exc:
        inv = (
            session.query(OrgInvitation)
            .filter_by(token_hash=hash_invite_token(token))
            .one_or_none()
        )
        org = session.get(Organization, inv.organization_id) if inv else None
        return templates.TemplateResponse(
            request,
            "invitacion_aceptar.html",
            {
                **_env_flags(),
                "token": token,
                "valid": inv is not None and inv.status == "PENDING",
                "email": inv.email if inv else "",
                "role_code": inv.role_code if inv else "",
                "org_name": org.name if org else "",
                "error": str(exc),
            },
            status_code=400,
        )

    acc = find_account_by_subject(session, membership.subject_id)
    resp = RedirectResponse("/hoy", status_code=303)
    attach_session_cookie(
        resp,
        username=acc.email if acc else (membership.email or ""),
        organization_id=membership.organization_id,
    )
    return resp
