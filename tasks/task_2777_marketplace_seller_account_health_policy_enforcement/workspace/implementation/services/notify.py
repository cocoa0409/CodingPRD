"""Transparency notices and supersession (PRD 2.11)."""

import clock
import db

PAYLOAD_KEYS = (
    "policy_rule_code",
    "severity_points_disclosed",
    "appeal_deadline_at",
    "escalation_deadline_at",
    "amount_cents",
    "decision_rationale",
    "evidence_reference",
)


def emit(seller_id, template_code, related_entity_type, related_entity_id, **payload):
    for row in db.by_created(list(db.NOTIFICATIONS.values())):
        if (row["state"] == "SENT"
                and row["seller_id"] == seller_id
                and row["template_code"] == template_code
                and row["related_entity_type"] == related_entity_type
                and row["related_entity_id"] == related_entity_id):
            db.set_field(row, "state", "SUPERSEDED")
    fields = {key: payload.get(key) for key in PAYLOAD_KEYS}
    row = db.new_row(
        "notification",
        seller_id=seller_id,
        template_code=template_code,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        state="SENT",
        sent_at=clock.now(),
        **fields
    )
    db.NOTIFICATIONS[row["id"]] = row
    return row
