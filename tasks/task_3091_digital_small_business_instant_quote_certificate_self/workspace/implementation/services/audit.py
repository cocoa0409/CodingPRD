"""Append-only audit trail."""
import db


def record(actor_role, actor_id, entity_type, entity_id, action, before=None, after=None):
    ev = {
        "id": db.new_id(),
        "created_at": db.fmt_iso(db.clock_now()),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "before_snapshot": before or {},
        "after_snapshot": after or {},
        "_seq": db.next_seq(),
    }
    db.audit_events[ev["id"]] = ev
    return ev
