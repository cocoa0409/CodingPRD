"""Irregularity cases: opening, investigation and the invalidation cascade."""

from flask import request

import auth
import cascades
import clock
import core
from constants import APPEAL_FLOOR_UTC, APPEAL_WINDOW_DAYS
from core import app, body, enum_field, insert, require, rows, str_field
from entities import make, serialize
from errors import fail
from response import list_response, ok
from validation import require_fk, transition_gate

CONFIRMABLE_FINDINGS = ("SCORE_INVALIDATION_REQUIRED", "WARNING_ONLY")


def _set_block(registration_id, blocked):
    for score in cascades.scores_of_registration(registration_id):
        score["release_blocked"] = blocked


@app.route("/ap-program/irregularity-cases", methods=["POST"])
def create_irregularity_case():
    auth.authenticate(["IntegrityInvestigator", "PlatformAdmin"])
    payload = body()
    exam_registration_id = str_field(payload, "exam_registration_id")
    school_id = str_field(payload, "school_id")
    irregularity_type = enum_field(payload, "irregularity_type", [
        "UNAUTHORIZED_DEVICE", "IMPROPER_ADMINISTRATION", "IDENTITY_DISCREPANCY",
        "MATERIAL_COMPROMISE", "ADMINISTRATOR_MISCONDUCT",
    ])
    require_fk("exam_registrations", exam_registration_id, "exam_registration_id")
    require_fk("schools", school_id, "school_id")
    case = insert("irregularity_cases", make(
        "irregularity_cases",
        exam_registration_id=exam_registration_id,
        test_center_id=school_id,
        irregularity_type=irregularity_type,
        reporter_user_id=payload.get("reporter_user_id"),
    ))
    _set_block(exam_registration_id, True)
    return ok(serialize("irregularity_cases", case), status=201)


@app.route("/ap-program/irregularity-cases", methods=["GET"])
def list_irregularity_cases():
    auth.authenticate(["IntegrityInvestigator", "PlatformAdmin"])
    args = request.args
    registration_id = args.get("exam_registration_id")
    status = args.get("status")
    matching = [
        c for c in rows("irregularity_cases")
        if (registration_id is None or c["exam_registration_id"] == registration_id)
        and (status is None or c["status"] == status)
    ]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, args, lambda r: serialize("irregularity_cases", r))


@app.route("/ap-program/irregularity-cases/<rid>/status-transitions", methods=["POST"])
def transition_irregularity_case(rid):
    _role, actor = auth.authenticate(["IntegrityInvestigator", "SchoolCoordinator"])
    payload = body()
    case, to_status = transition_gate("irregularity_cases", rid, payload, actor=actor)
    if payload.get("reporter_user_id") is not None:
        case["reporter_user_id"] = payload.get("reporter_user_id")
    if payload.get("finding_code") is not None:
        case["finding_code"] = payload.get("finding_code")

    if to_status == "INVESTIGATING":
        if not (case.get("irregularity_type") or "").strip():
            fail("ERR_INVALID_STATE", "The case carries no irregularity type.")
        case["investigation_round"] = case["investigation_round"] + 1
        case["status"] = "INVESTIGATING"
        core.touch(case)
        _set_block(case["exam_registration_id"], True)

    elif to_status == "DECISION_PENDING":
        if case["investigation_round"] < 1:
            fail("ERR_INVALID_STATE", "A decision requires at least one investigation round.")
        if not (case.get("finding_code") or "").strip():
            fail("ERR_INVALID_REQUEST", "Field 'finding_code' is required for a decision.")
        case["status"] = "DECISION_PENDING"
        core.touch(case)

    elif to_status == "CONFIRMED":
        finding = case.get("finding_code")
        if finding not in CONFIRMABLE_FINDINGS:
            fail("ERR_INVALID_STATE", "The recorded finding is not a confirmable one.")
        case["status"] = "CONFIRMED"
        case["_confirmed_at"] = clock.now_iso()
        core.touch(case)
        if finding == "SCORE_INVALIDATION_REQUIRED":
            registration = core.get("exam_registrations", case["exam_registration_id"])
            if registration is not None and registration["status"] != "INVALIDATED":
                cascades.invalidation_cascade(registration)
        else:
            _set_block(case["exam_registration_id"], False)

    elif to_status == "DISMISSED":
        finding = case.get("finding_code")
        if finding not in (None, "", "NO_FINDING"):
            fail("ERR_INVALID_STATE", "Only a NO_FINDING case may be dismissed.")
        case["status"] = "DISMISSED"
        core.touch(case)
        _set_block(case["exam_registration_id"], False)

    elif to_status == "APPEALED":
        confirmed_at = case.get("_confirmed_at")
        if confirmed_at:
            deadline = clock.later(
                clock.shift_days(clock.parse_instant(confirmed_at), APPEAL_WINDOW_DAYS),
                clock.parse_instant(APPEAL_FLOOR_UTC))
        else:
            deadline = clock.parse_instant(APPEAL_FLOOR_UTC)
        if clock.now() >= deadline:
            fail("ERR_APPEAL_WINDOW_CLOSED")
        case["status"] = "APPEALED"
        core.touch(case)

    return ok(serialize("irregularity_cases", case))
