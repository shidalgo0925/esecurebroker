"""Public sales channel HTTP API + landing (no ESB session)."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from corredores.services.public_channel import (
    PublicChannelError,
    calculate_plans,
    channel_config_dict,
    create_quote,
    get_channel_by_slug,
    get_quote_by_token,
    quote_dict,
    save_beneficiaries,
    save_emergency,
    save_travelers,
    select_plan,
    start_checkout,
    update_trip,
)
from corredores.web.deps import get_session

router = APIRouter(prefix="/public", tags=["public-channel"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _http(exc: PublicChannelError) -> HTTPException:
    return HTTPException(400, str(exc))


class TripIn(BaseModel):
    origin: str | None = None
    destination_region: str
    destination: str | None = None
    start_date: date
    end_date: date
    ages: list[int] = Field(min_length=1, max_length=20)


class SelectPlanIn(BaseModel):
    plan_code: str


class TravelerIn(BaseModel):
    first_name: str
    last_name: str
    birth_date: date | None = None
    age: int | None = None
    identification_number: str | None = None
    email: str | None = None
    phone: str | None = None
    is_pep: bool = False
    is_primary: bool = False


class TravelersIn(BaseModel):
    travelers: list[TravelerIn]


class BeneficiaryIn(BaseModel):
    full_name: str
    relationship: str | None = None
    identification_number: str | None = None
    phone: str | None = None
    share_pct: float | None = None


class BeneficiariesBlockIn(BaseModel):
    traveler_seq: int
    beneficiaries: list[BeneficiaryIn] = Field(default_factory=list)


class BeneficiariesIn(BaseModel):
    items: list[BeneficiariesBlockIn]


class EmergencyIn(BaseModel):
    name: str
    phone: str
    email: str | None = None


@router.get("/{channel}/config")
def public_config(channel: str, session: Session = Depends(get_session)):
    try:
        ch = get_channel_by_slug(session, channel)
        return channel_config_dict(session, ch)
    except PublicChannelError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/{channel}/", response_class=HTMLResponse)
@router.get("/{channel}", response_class=HTMLResponse)
def public_landing(request: Request, channel: str, session: Session = Depends(get_session)):
    try:
        ch = get_channel_by_slug(session, channel)
        cfg = channel_config_dict(session, ch)
    except PublicChannelError as e:
        raise HTTPException(404, str(e)) from e
    return templates.TemplateResponse(
        request,
        "public_channel_quote.html",
        {"channel": channel, "config": cfg},
    )


@router.post("/{channel}/quotes")
def public_create_quote(channel: str, session: Session = Depends(get_session)):
    try:
        ch = get_channel_by_slug(session, channel)
        q = create_quote(session, ch)
        return quote_dict(session, q)
    except PublicChannelError as e:
        raise _http(e) from e


@router.get("/{channel}/quotes/{token}")
def public_get_quote(channel: str, token: str, session: Session = Depends(get_session)):
    try:
        ch = get_channel_by_slug(session, channel)
        q = get_quote_by_token(session, channel=ch, token=token)
        return quote_dict(session, q)
    except PublicChannelError as e:
        raise HTTPException(404 if "no encontrada" in str(e) or "expirada" in str(e) else 400, str(e)) from e


@router.post("/{channel}/quotes/{token}/calculate")
def public_calculate(
    channel: str, token: str, body: TripIn, session: Session = Depends(get_session)
):
    try:
        ch = get_channel_by_slug(session, channel)
        q = get_quote_by_token(session, channel=ch, token=token)
        update_trip(
            session,
            q,
            origin=body.origin,
            destination_region=body.destination_region,
            destination=body.destination,
            start_date=body.start_date,
            end_date=body.end_date,
            ages=body.ages,
        )
        plans = calculate_plans(session, q)
        return {"quote": quote_dict(session, q), "plans": plans}
    except PublicChannelError as e:
        raise _http(e) from e


@router.post("/{channel}/quotes/{token}/select-plan")
def public_select_plan(
    channel: str, token: str, body: SelectPlanIn, session: Session = Depends(get_session)
):
    try:
        ch = get_channel_by_slug(session, channel)
        q = get_quote_by_token(session, channel=ch, token=token)
        select_plan(session, q, body.plan_code)
        return quote_dict(session, q)
    except PublicChannelError as e:
        raise _http(e) from e


@router.post("/{channel}/quotes/{token}/travelers")
def public_travelers(
    channel: str, token: str, body: TravelersIn, session: Session = Depends(get_session)
):
    try:
        ch = get_channel_by_slug(session, channel)
        q = get_quote_by_token(session, channel=ch, token=token)
        save_travelers(session, q, [t.model_dump() for t in body.travelers])
        return quote_dict(session, q)
    except PublicChannelError as e:
        raise _http(e) from e


@router.post("/{channel}/quotes/{token}/beneficiaries")
def public_beneficiaries(
    channel: str, token: str, body: BeneficiariesIn, session: Session = Depends(get_session)
):
    try:
        ch = get_channel_by_slug(session, channel)
        q = get_quote_by_token(session, channel=ch, token=token)
        save_beneficiaries(
            session,
            q,
            [b.model_dump() for b in body.items],
        )
        return quote_dict(session, q)
    except PublicChannelError as e:
        raise _http(e) from e


@router.post("/{channel}/quotes/{token}/emergency-contact")
def public_emergency(
    channel: str, token: str, body: EmergencyIn, session: Session = Depends(get_session)
):
    try:
        ch = get_channel_by_slug(session, channel)
        q = get_quote_by_token(session, channel=ch, token=token)
        save_emergency(session, q, name=body.name, phone=body.phone, email=body.email)
        return quote_dict(session, q)
    except PublicChannelError as e:
        raise _http(e) from e


@router.post("/{channel}/quotes/{token}/checkout")
def public_checkout(channel: str, token: str, session: Session = Depends(get_session)):
    try:
        ch = get_channel_by_slug(session, channel)
        q = get_quote_by_token(session, channel=ch, token=token)
        result = start_checkout(session, q)
        return {"quote": quote_dict(session, q), "checkout": result}
    except PublicChannelError as e:
        raise _http(e) from e


@router.get("/{channel}/quotes/{token}/pay", response_class=HTMLResponse)
def public_pay_page(
    request: Request,
    channel: str,
    token: str,
    attempt_id: str = Query(default=""),
    session: Session = Depends(get_session),
):
    """DEV sandbox payment page (or resume pending Stripe redirect)."""
    try:
        ch = get_channel_by_slug(session, channel)
        q = get_quote_by_token(session, channel=ch, token=token)
    except PublicChannelError as e:
        raise HTTPException(404, str(e)) from e
    from corredores.domain.models import PublicPaymentAttempt

    attempt = session.get(PublicPaymentAttempt, attempt_id) if attempt_id else None
    if attempt is None or attempt.quote_id != q.id:
        raise HTTPException(404, "intento de pago no encontrado")
    return templates.TemplateResponse(
        request,
        "public_channel_pay.html",
        {
            "channel": channel,
            "token": token,
            "attempt_id": attempt.id,
            "amount": str(attempt.amount),
            "currency": attempt.currency,
            "provider": attempt.provider,
            "status": attempt.status,
            "quote_status": q.status,
            "plan": (quote_dict(session, q).get("selected_plan") or {}),
        },
    )


@router.post("/{channel}/quotes/{token}/pay/confirm-sandbox")
def public_pay_confirm_sandbox(
    channel: str,
    token: str,
    attempt_id: str = Query(...),
    session: Session = Depends(get_session),
):
    from corredores.services.public_channel_payments import confirm_sandbox_payment

    try:
        ch = get_channel_by_slug(session, channel)
        q = get_quote_by_token(session, channel=ch, token=token)
        attempt = confirm_sandbox_payment(
            session, channel=ch, quote=q, attempt_id=attempt_id
        )
        return {
            "ok": True,
            "attempt_status": attempt.status,
            "quote": quote_dict(session, q),
        }
    except PublicChannelError as e:
        raise _http(e) from e


@router.get("/{channel}/quotes/{token}/result", response_class=HTMLResponse)
def public_result_page(
    request: Request,
    channel: str,
    token: str,
    attempt_id: str = Query(default=""),
    session_id: str = Query(default=""),
    canceled: str = Query(default=""),
    session: Session = Depends(get_session),
):
    from corredores.services.public_channel_payments import sync_attempt_from_return

    try:
        ch = get_channel_by_slug(session, channel)
        q = get_quote_by_token(session, channel=ch, token=token)
    except PublicChannelError as e:
        raise HTTPException(404, str(e)) from e
    err = None
    if canceled not in ("1", "true", "yes"):
        try:
            sync_attempt_from_return(
                session, attempt_id=attempt_id or None, session_id=session_id or None
            )
            session.refresh(q)
        except PublicChannelError as e:
            err = str(e)
        except Exception:
            pass
    return templates.TemplateResponse(
        request,
        "public_channel_result.html",
        {
            "channel": channel,
            "token": token,
            "quote": quote_dict(session, q),
            "canceled": canceled in ("1", "true", "yes"),
            "error": err,
        },
    )


@router.get("/{channel}/quotes/{token}/status")
def public_status(channel: str, token: str, session: Session = Depends(get_session)):
    try:
        ch = get_channel_by_slug(session, channel)
        q = get_quote_by_token(session, channel=ch, token=token)
        return {
            "status": q.status,
            "payment_status": q.payment_status,
            "checkout_ref": q.checkout_ref,
            "selected_premium": str(q.selected_premium) if q.selected_premium else None,
            "currency": q.currency,
        }
    except PublicChannelError as e:
        raise HTTPException(404, str(e)) from e
