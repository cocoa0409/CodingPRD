"""Case notes: append (AUDIT reserved to the system) and list."""
from flask import Blueprint

from auth import require_role, require_ownership
from errors import ApiError
from helpers import (
    body_json, req_str, req_enum,
    get_case, ser_note, NOTE_TYPES,
)
from store import db
from util import now, new_id, success, paginate

bp = Blueprint("notes", __name__)


@bp.route("/reemployment/case-notes", methods=["POST"])
def create_note():
    role, uid = require_role("Ombudsman", "ProgramCoordinator")
    body = body_json()
    case_id = req_str(body, "case_id")
    note_type = req_enum(body, "note_type", NOTE_TYPES)
    if note_type == "AUDIT":
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "note_type AUDIT is reserved to system-generated entries",
        )
    text = req_str(body, "body")
    case = get_case(case_id)
    if role == "Ombudsman":
        # An ombudsman documents only cases assigned to them.
        require_ownership(case["assigned_ombudsman_id"] == uid)
    nid = new_id()
    n = {
        "id": nid, "case_id": case_id, "note_type": note_type, "body": text,
        "author_role": role, "author_id": uid,
        "created_at": now(), "_seq": db.next_seq(),
    }
    db.notes[nid] = n
    return success(ser_note(n), "object", 201)


@bp.route("/reemployment/cases/<cid>/notes", methods=["GET"])
def list_notes(cid):
    require_role("Ombudsman", "ProgramCoordinator")
    get_case(cid)
    items = [n for n in db.notes.values() if n["case_id"] == cid]
    items.sort(key=lambda n: (n["created_at"], n["_seq"]))
    page, meta = paginate(items)
    return success([ser_note(n) for n in page], "array", 200, meta)
