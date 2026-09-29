"""The self-study document: the draft edit path and its three transitions
(PRD 3.3)."""

from flask import Blueprint

import envelope
import serial
import valid
from errors import ApiError
from guards import (ACTIONS_SELF_STUDY, CHAIR, COORD, OWNERS_SELF_STUDY, begin,
                    program_of_self_study)
from store import db, now, touch

bp = Blueprint("selfstudy", __name__)


@bp.route("/provost/self-studies/<sid>", methods=["PATCH"])
def edit_self_study(sid):
    ctx = begin((CHAIR,))
    row = db.self_studies.get(sid)
    ctx.chair_owner(program_of_self_study(row))
    ctx.require(row, "ERR_SELF_STUDY_NOT_FOUND")

    body = ctx.require_object_body()
    narrative = valid.opt_str(body, "narrative", 1, 20000)
    sections = None
    if body.get("section_codes") is not None:
        sections = valid.code_array(body, "section_codes", 1, 20,
                                    allow_empty=True)
    attestation = valid.opt_str(body, "attestation_note", 1, 2000)

    ctx.not_terminal(program_of_self_study(row))

    if row["state"] != "DRAFT":
        raise ApiError("ERR_SELF_STUDY_NOT_DRAFT")

    if narrative is not None:
        row["narrative"] = narrative
    if sections is not None:
        row["section_codes"] = sections
    if attestation is not None:
        row["attestation_note"] = attestation
    touch(row)
    return envelope.ok(serial.self_study(row))


@bp.route("/provost/self-studies/<sid>/transitions", methods=["POST"])
def transition_self_study(sid):
    ctx = begin((CHAIR, COORD), OWNERS_SELF_STUDY)
    row = db.self_studies.get(sid)
    ctx.chair_owner(program_of_self_study(row))
    ctx.require(row, "ERR_SELF_STUDY_NOT_FOUND")

    body = ctx.require_object_body()
    action = valid.req_enum(body, "action", ACTIONS_SELF_STUDY)
    attestation = None
    revision_notes = None
    if action == "SUBMIT":
        attestation = valid.opt_str(body, "attestation_note", 1, 2000)
    elif action == "RETURN":
        revision_notes = valid.opt_str(body, "revision_notes", 1, 2000)

    ctx.not_terminal(program_of_self_study(row))

    cycle = db.cycles.get(row["cycle_id"])

    if action == "SUBMIT":
        if row["state"] != "DRAFT":
            raise ApiError("ERR_SELF_STUDY_NOT_DRAFT")
        if cycle is not None and now() > cycle["self_study_due_at"]:
            raise ApiError("ERR_SELF_STUDY_WINDOW_CLOSED")
        if not row["section_codes"] or serial.missing_section_codes(row):
            raise ApiError("ERR_SELF_STUDY_SECTIONS_INCOMPLETE")
        row["state"] = "SUBMITTED"
        row["submitted_at"] = now()
        if attestation is not None:
            row["attestation_note"] = attestation
        touch(row)
        return envelope.ok(serial.self_study(row))

    if row["state"] != "SUBMITTED":
        raise ApiError("ERR_SELF_STUDY_NOT_DRAFT")

    if action == "RETURN":
        if row["revision_round"] >= 2:
            raise ApiError("ERR_REVISION_LIMIT_REACHED")
        row["state"] = "DRAFT"
        row["revision_round"] = row["revision_round"] + 1
        row["revision_notes"] = revision_notes
        row["submitted_at"] = None
        touch(row)
        return envelope.ok(serial.self_study(row))

    # ACCEPT
    row["state"] = "ACCEPTED"
    row["accepted_at"] = now()
    touch(row)
    if cycle is not None and cycle["state"] == "SELF_STUDY_OPEN":
        cycle["state"] = "SELF_STUDY_ACCEPTED"
        touch(cycle)
    return envelope.ok(serial.self_study(row))
