from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog


def audit(
    db: Session,
    org_id: str,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    from_state: str | None = None,
    to_state: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append-only audit record. Detail must never carry raw customer data."""
    db.add(
        AuditLog(
            org_id=org_id,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            from_state=from_state,
            to_state=to_state,
            detail=detail or {},
        )
    )
