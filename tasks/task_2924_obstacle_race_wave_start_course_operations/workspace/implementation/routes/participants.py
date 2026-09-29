"""Participants (PRD 3.5): enrolment and the waiver that resolves clearance."""

from flask import Blueprint, g

import auth
import db
import validation
from errors import fail
from routes import common

bp = Blueprint("participants", __name__)


@bp.post("/ocr/participants")
def enrol_participant():
    auth.require(auth.SITE_OPS_LEAD, auth.RACE_DIRECTOR)
    payload = validation.body()
    full_name = validation.field_str(payload, "full_name", 1, 120)
    birth_year = validation.field_int(payload, "birth_year", minimum=1900, maximum=2026)
    email = validation.field_str(payload, "email", 1)
    chip_id = validation.field_str(payload, "chip_id", 1)

    # Rung 22: email and chip_id are unique across every enrolled human.
    for peer in db.all_rows("participants"):
        if peer["email"] == email:
            fail("ERR_UNIQUENESS_CONFLICT", "email %s is already enrolled." % email)
        if peer["chip_id"] == chip_id:
            fail("ERR_UNIQUENESS_CONFLICT", "chip_id %s is already bonded." % chip_id)

    row = db.insert(
        "participants",
        {
            "full_name": full_name,
            "birth_year": birth_year,
            "email": email,
            "chip_id": chip_id,
            "waiver_signed": False,
            "medical_flags": [],
            "clearance_status": "PENDING",
        },
    )
    return common.created(row)


@bp.get("/ocr/participants")
def list_participants():
    auth.require(auth.SITE_OPS_LEAD, auth.RACE_DIRECTOR, auth.SAFETY_OFFICER)
    clearance_status = validation.query_enum("clearance_status", validation.CLEARANCE_STATUSES)
    rows = db.all_rows("participants")
    if clearance_status is not None:
        rows = [r for r in rows if r["clearance_status"] == clearance_status]
    return common.listing(rows)


@bp.get("/ocr/participants/<participant_id>")
def read_participant(participant_id):
    auth.require(
        auth.SITE_OPS_LEAD, auth.RACE_DIRECTOR, auth.SAFETY_OFFICER, auth.PARTICIPANT
    )
    participant = validation.path_participant(participant_id)
    return common.ok(participant)


@bp.post("/ocr/participants/<participant_id>/waiver")
def sign_waiver(participant_id):
    auth.require(auth.PARTICIPANT, auth.RACE_DIRECTOR)
    participant = validation.path_participant(participant_id)
    payload = validation.body()
    validation.field_str(payload, "signature_name", 1)
    flags = validation.field_str_list(payload, "medical_flags", default=None)

    # Rung 6: a Participant may sign only their own row.
    if g.role == auth.PARTICIPANT and participant["id"] != g.user_id:
        fail("ERR_NOT_ENTRY_OWNER", "A participant may only sign their own waiver.")

    # Rung 9: neither transition is admissible once clearance has left PENDING.
    if participant["clearance_status"] != "PENDING":
        fail("ERR_ENTRY_STATE_INVALID", "This waiver has already been resolved.")

    declared = list(flags) if flags is not None else []
    blocking = [f for f in declared if f in validation.BLOCKING_MEDICAL_FLAGS]

    with db.mutation(participant) as row:
        row["waiver_signed"] = True
        row["medical_flags"] = declared
        row["clearance_status"] = "MEDICALLY_HELD" if blocking else "CLEARED"
    return common.ok(participant)
