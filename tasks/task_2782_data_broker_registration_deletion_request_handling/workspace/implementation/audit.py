"""Append-only audit trail (PRD 2.10)."""
from core import add_days, db, make

RETENTION_DAYS = 2555


def actor_direct(caller):
    """An act the caller performed themselves."""
    return (caller.role, caller.user_id)


def actor_system(caller):
    """Cascade-driven events carry the literal role "system"; sweep-driven
    events additionally carry a null actor_user_id (PRD 2.10)."""
    return ("system", caller.user_id if caller is not None else None)


def append(broker, event_type, subject_kind, subject_id, actor, summary):
    """Append one AuditEvent to the broker's trail. sequence_no is per-broker
    and monotonic from 1; audit_sequence_high_water tracks the last value.

    Bumping the high-water mark is bookkeeping and deliberately does not
    advance the broker's version -- PRD 2.5/3.2 pin the broker version delta
    of registration create/submit at exactly one."""
    broker["audit_sequence_high_water"] = broker.get(
        "audit_sequence_high_water", 0) + 1
    actor_role, actor_user_id = actor
    event = make(
        "AuditEvent",
        broker_id=broker["id"],
        sequence_no=broker["audit_sequence_high_water"],
        event_type=event_type,
        subject_kind=subject_kind,
        subject_id=subject_id,
        actor_role=actor_role,
        actor_user_id=actor_user_id,
        summary=summary,
    )
    event["retention_expires_at"] = add_days(event["created_at"],
                                            RETENTION_DAYS)
    db.audits[event["id"]] = event
    return event


def trail(broker_id):
    return sorted(
        (e for e in db.audits.values() if e["broker_id"] == broker_id),
        key=lambda e: e["sequence_no"],
    )
