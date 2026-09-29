"""The logical clock (PRD 2.5) and the compliance sweep (PRD 3.7)."""

from flask import Blueprint

import envelope
import valid
from guards import CHAIR, COORD, HR, PROVOST, REGISTRAR, REVIEWER, begin
from store import by_created, db, iso, now, touch

bp = Blueprint("misc", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    ctx = begin((CHAIR, REVIEWER, COORD, PROVOST, REGISTRAR, HR))
    body = ctx.require_object_body()
    instant = valid.req_instant(body, "current_utc")
    db.clock = instant
    return envelope.ok({"current_utc": iso(db.clock)})


@bp.route("/provost/compliance-sweeps", methods=["POST"])
def compliance_sweep():
    begin((COORD,))
    swept_at = now()
    marked = []
    for notification in by_created(db.notifications.values()):
        if notification["status"] != "PENDING":
            continue
        if swept_at > notification["due_at"]:
            notification["status"] = "OVERDUE"
            notification["overdue_marked_at"] = swept_at
            touch(notification)
            marked.append(notification["id"])
    return envelope.ok({
        "swept_at": iso(swept_at),
        "marked_overdue_count": len(marked),
        "marked_overdue_notification_ids": marked,
    })
