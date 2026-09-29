"""Travel room stays: flat reads and cancellation (PRD section 3.7)."""

from flask import Blueprint, request

import auth
import derive
import envelope
import pagelib
import serialize
import store
import validate
from errors import fail

bp = Blueprint("rooms", __name__)

STAY_STATUSES = ("BOOKED", "CANCELLED")


@bp.get("/room-stays")
@auth.endpoint("NgbAdmin", "ComplianceAuditor", "SafeSportOfficer")
def list_room_stays():
    args = request.args
    validate.query_enum(args, "status", STAY_STATUSES)
    rows = [s for s in store.ROOM_STAYS.values()
            if pagelib.match(s, args, "club_id")
            and pagelib.match(s, args, "member_id")
            and pagelib.match(s, args, "trip_label")
            and pagelib.match(s, args, "room_number")
            and pagelib.match(s, args, "status")]
    rows.sort(key=lambda s: (s["check_in"], s["created_at"], s["_seq"]))
    return pagelib.page(rows, serialize.room_stay, args)


@bp.get("/room-stays/<room_stay_id>")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer")
def read_room_stay(room_stay_id):
    row = auth.room_stay(room_stay_id)
    auth.scope(row["club_id"])
    return envelope.ok(serialize.room_stay(row))


@bp.post("/room-stays/<room_stay_id>/cancel")
@auth.endpoint("ClubAdministrator")
def cancel_room_stay(room_stay_id):
    row = auth.room_stay(room_stay_id)
    auth.scope(row["club_id"])
    data = validate.body(auth.payload(), {"reason": validate.string(min_len=1, max_len=1000)})
    if row["status"] != "BOOKED":
        fail("ERR_ROOM_STAY_INVALID_STATE", "only a BOOKED stay may be cancelled")
    row["status"] = "CANCELLED"
    row["cancel_reason"] = data["reason"]
    store.bump(row)
    derive.recompute_all()
    return envelope.ok(serialize.room_stay(row))
