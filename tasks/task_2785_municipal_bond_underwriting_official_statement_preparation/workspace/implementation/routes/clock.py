"""The logical clock capability (PRD 2.3, 3)."""
from flask import Blueprint

import db
import response
from middleware import ALL_ROLES, authenticate
from validation import parse_body, spec

bp = Blueprint("clock", __name__)


@bp.route("/bond-offerings/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(ALL_ROLES)
    body = parse_body([spec("current_utc", "datetime")])
    current_utc = body["current_utc"]
    db.set_clock(current_utc)
    due = [
        row
        for row in db.db.presentations.values()
        if row["status"] == "SCHEDULED" and row["ends_at"] <= current_utc
    ]
    due.sort(key=lambda row: (row["ends_at"], row["created_at"], row["_seq"]))
    held_ids = []
    for presentation in due:
        presentation["status"] = "HELD"
        db.touch(presentation)
        held_ids.append(presentation["id"])
    return response.ok(
        {"current_utc": response.iso(current_utc), "held_presentation_ids": held_ids}
    )
