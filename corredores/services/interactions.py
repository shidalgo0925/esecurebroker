"""Interaction + Task helpers — activity replaces Excel 'GESTIONADO'."""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy.orm import Session

from corredores.domain.enums import DataSource
from corredores.domain.models import AuditEvent, Interaction, Task


def log_interaction(
    session: Session,
    *,
    organization_id: str,
    summary: str,
    channel: str = "NOTE",
    party_id: str | None = None,
    policy_id: str | None = None,
    actor_id: str | None = None,
    data_source: str = DataSource.MANUAL,
) -> Interaction:
    row = Interaction(
        organization_id=organization_id,
        party_id=party_id,
        policy_id=policy_id,
        channel=channel,
        summary=summary,
        actor_id=actor_id,
        data_source=data_source,
    )
    session.add(row)
    session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="Interaction",
            entity_id=row.id,
            action="LOGGED",
            detail_json=json.dumps({"channel": channel}),
        )
    )
    session.flush()
    return row


def create_task(
    session: Session,
    *,
    organization_id: str,
    title: str,
    due_date: date | None = None,
    party_id: str | None = None,
    policy_id: str | None = None,
    related_type: str | None = None,
    related_id: str | None = None,
    actor_id: str | None = None,
) -> Task:
    task = Task(
        organization_id=organization_id,
        title=title,
        status="OPEN",
        due_date=due_date,
        party_id=party_id,
        policy_id=policy_id,
        related_type=related_type,
        related_id=related_id,
        actor_id=actor_id,
    )
    session.add(task)
    session.flush()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="Task",
            entity_id=task.id,
            action="CREATED",
            detail_json=json.dumps({"title": title}),
        )
    )
    session.flush()
    return task


def complete_task(
    session: Session, task: Task, *, actor_id: str | None = None
) -> Task:
    task.status = "DONE"
    session.add(
        AuditEvent(
            organization_id=task.organization_id,
            actor_id=actor_id,
            entity_type="Task",
            entity_id=task.id,
            action="DONE",
            detail_json="{}",
        )
    )
    session.flush()
    return task
