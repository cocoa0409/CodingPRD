"""Matching interpreters to hearings and serving the work (PRD 3.6, 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import cascades
import derive
import pay
import serializers as S
from auth import require
from envelope import array_response, object_response, paginate, read_pagination
from errors import ApiError
from store import db, new_row, now, touch
from util import fmt_dt, parse_dt
from validation import (
    body_of,
    bool_field,
    datetime_field,
    enum_field,
    int_field,
    num_field,
    query_enum,
    query_str,
    str_field,
)

bp = Blueprint("assignments", __name__)

DELIVERY_MODES = ("IN_PERSON", "VRI", "TELEPHONIC")
SERVICE_STATUSES = (
    "PROPOSED",
    "CONFIRMED",
    "CHECKED_IN",
    "COMPLETED",
    "DECLINED",
    "CANCELLED",
    "SUPERSEDED",
    "NO_SHOW",
)
COMPLIANCE_STATUSES = ("CLEAR", "UNDER_QUALITY_REVIEW", "SUBSTANTIATED_DEFECT")
CANCEL_REASONS = (
    "INTERPRETER_DECLINED",
    "COURT_CONTINUANCE",
    "INTERPRETER_SUSPENDED",
    "CREDENTIAL_LAPSED",
    "CREDENTIAL_REVOKED",
    "EQUIPMENT_WITHDRAWN",
    "COORDINATOR_CANCELLED",
)
READ_ROLES = (
    "ProgramAdmin",
    "SchedulingCoordinator",
    "FiscalOfficer",
    "QualityReviewer",
    "Interpreter",
)
COVERING_STATUSES = ("CONFIRMED", "CHECKED_IN", "COMPLETED")


def _owner_gate(assignment, user_id, role):
    """Ladder priority 6: an Interpreter caller must own the assignment."""
    if role == "Interpreter" and assignment["interpreter_id"] != user_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "This assignment belongs to another interpreter.",
        )


# --------------------------------------------------------------------------
# creation
# --------------------------------------------------------------------------
@bp.route("/assignments", methods=["POST"])
def create_assignment():
    require("SchedulingCoordinator", "ProgramAdmin")
    body = body_of(request)
    hearing_id = str_field(body, "hearing_id")
    interpreter_id = str_field(body, "interpreter_id", required=False)
    delivery_mode = enum_field(body, "delivery_mode", DELIVERY_MODES)
    vendor_served = bool_field(body, "vendor_served", required=False, default=False)
    estimated_miles = num_field(
        body, "estimated_one_way_miles", required=False, default=0, minimum=0
    )
    expected_version = int_field(body, "expected_hearing_version")

    hearing = derive.get_hearing(hearing_id)
    interpreter = (
        derive.get_interpreter(interpreter_id) if interpreter_id is not None else None
    )

    if hearing["version"] != expected_version:
        raise ApiError(
            "ERR_STALE_HEARING_VERSION",
            "The hearing has been modified since it was last read.",
        )

    if hearing["status"] in ("SERVED", "UNMET", "CONTINUED"):
        raise ApiError(
            "ERR_HEARING_NOT_SCHEDULABLE",
            "This hearing is no longer schedulable.",
        )

    courthouse = db.courthouses[hearing["courthouse_id"]]
    language = db.languages[hearing["language_id"]]
    credential = None

    if interpreter is not None:
        if interpreter["roster_status"] != "ACTIVE":
            raise ApiError(
                "ERR_INTERPRETER_NOT_ON_ACTIVE_ROSTER",
                "The named interpreter is not on the active roster.",
            )
        credential = derive.best_active_credential(
            interpreter["id"], hearing["language_id"]
        )
        if credential is None:
            raise ApiError(
                "ERR_CREDENTIAL_NOT_ACTIVE",
                "The interpreter holds no active credential in the hearing's language.",
            )
        required = derive.required_min_tier(hearing)
        if derive.TIER_RANK[credential["tier"]] < derive.TIER_RANK[required]:
            raise ApiError(
                "ERR_TIER_BELOW_HEARING_REQUIREMENT",
                "The credential tier is below the hearing's requirement.",
            )
        if interpreter["ethics_training_status"] != "COMPLETED":
            raise ApiError(
                "ERR_ETHICS_TRAINING_INCOMPLETE",
                "The interpreter has not completed mandatory ethics training.",
            )
        if hearing["priority_class"] == "A":
            rolling = derive.quality_scores(interpreter["id"])[0]
            if rolling < derive.QUALITY_FLOOR:
                raise ApiError(
                    "ERR_QUALITY_SCORE_BELOW_ASSIGNMENT_FLOOR",
                    "The interpreter's rolling quality score is below the floor "
                    "for a class A hearing.",
                )

    covered = [
        a
        for a in derive.assignments_of_hearing(hearing_id)
        if a["service_status"] in COVERING_STATUSES
    ]
    if hearing["status"] == "COVERED" or covered:
        raise ApiError(
            "ERR_HEARING_ALREADY_COVERED",
            "This hearing already carries an accepted assignment.",
        )

    if delivery_mode == "VRI":
        if (
            courthouse["remote_equipment_tier"] not in ("BASIC", "CERTIFIED_VRI")
            or courthouse["status"] != "OPEN"
        ):
            raise ApiError(
                "ERR_REMOTE_EQUIPMENT_UNAVAILABLE",
                "This courthouse cannot host video remote interpreting.",
            )

    if delivery_mode == "TELEPHONIC":
        if not language["telephonic_vendor_available"]:
            raise ApiError(
                "ERR_TELEPHONIC_NOT_PERMITTED",
                "Telephonic delivery is not available in this language.",
            )
        if vendor_served and (
            language["tier_class"] != "RARE" or interpreter_id is not None
        ):
            raise ApiError(
                "ERR_TELEPHONIC_NOT_PERMITTED",
                "Vendor service is permitted only for a rare language with no "
                "named interpreter.",
            )

    if delivery_mode == "VRI" and derive.vri_occupancy_exceeded(hearing, courthouse):
        raise ApiError(
            "ERR_VRI_CAPACITY_EXCEEDED",
            "Concurrent video-remote occupancy would exceed the courthouse capacity.",
        )

    if interpreter is not None:
        conflict = derive.interval_conflict(interpreter["id"], hearing, delivery_mode)
        if conflict == "ERR_INTERPRETER_DOUBLE_BOOKED":
            raise ApiError(
                conflict, "The interpreter is already booked for that window."
            )
        if conflict == "ERR_TRAVEL_BUFFER_VIOLATION":
            raise ApiError(
                conflict,
                "Less than 60 minutes separates two in-person appearances at "
                "different courthouses.",
            )

    if now() >= parse_dt(hearing["scheduled_start"]):
        raise ApiError(
            "ERR_HEARING_WINDOW_CLOSED",
            "The hearing's start instant has already passed.",
        )

    for existing in derive.assignments_of_hearing(hearing_id):
        if existing["service_status"] == "PROPOSED":
            existing["service_status"] = "SUPERSEDED"
            touch(existing)
            touch(hearing)

    row = new_row()
    row.update(
        {
            "hearing_id": hearing_id,
            "interpreter_id": interpreter_id,
            "credential_id": credential["id"] if credential is not None else None,
            "credential_tier_snapshot": (
                credential["tier"] if credential is not None else None
            ),
            "delivery_mode": delivery_mode,
            "vendor_served": vendor_served,
            "estimated_one_way_miles": estimated_miles,
            "actual_one_way_miles": None,
            "service_status": "PROPOSED",
            "compliance_status": "CLEAR",
            "check_in_utc": None,
            "actual_end_utc": None,
            "cancel_reason_code": None,
        }
    )
    db.assignments[row["id"]] = row
    touch(hearing)
    return object_response(S.assignment_out(row), 201)


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    require(*READ_ROLES)
    limit, offset = read_pagination(request.args)
    hearing_id = query_str(request.args, "hearing_id")
    interpreter_id = query_str(request.args, "interpreter_id")
    credential_id = query_str(request.args, "credential_id")
    service_status = query_enum(request.args, "service_status", SERVICE_STATUSES)
    compliance_status = query_enum(
        request.args, "compliance_status", COMPLIANCE_STATUSES
    )
    rows = []
    for row in db.assignments.values():
        if hearing_id is not None and row["hearing_id"] != hearing_id:
            continue
        if interpreter_id is not None and row["interpreter_id"] != interpreter_id:
            continue
        if credential_id is not None and row["credential_id"] != credential_id:
            continue
        if service_status is not None and row["service_status"] != service_status:
            continue
        if compliance_status is not None and row["compliance_status"] != compliance_status:
            continue
        rows.append(row)
    rows = S.created_order(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([S.assignment_out(r) for r in page], limit, offset, total)


@bp.route("/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    require(*READ_ROLES)
    row = derive.get_assignment(assignment_id)
    return object_response(S.assignment_out(row))


# --------------------------------------------------------------------------
# acceptance and refusal
# --------------------------------------------------------------------------
@bp.route("/assignments/<assignment_id>/confirm", methods=["POST"])
def confirm_assignment(assignment_id):
    user_id, role = require("Interpreter", "SchedulingCoordinator")
    body_of(request)
    assignment = derive.get_assignment(assignment_id)
    _owner_gate(assignment, user_id, role)

    if assignment["service_status"] != "PROPOSED":
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "Only a proposed assignment may be confirmed.",
        )

    hearing = db.hearings[assignment["hearing_id"]]
    courthouse = db.courthouses[hearing["courthouse_id"]]
    if now() >= parse_dt(hearing["scheduled_start"]):
        raise ApiError(
            "ERR_HEARING_WINDOW_CLOSED",
            "The hearing's start instant has already passed.",
        )

    if not assignment["vendor_served"]:
        interpreter = db.interpreters[assignment["interpreter_id"]]
        if interpreter["roster_status"] != "ACTIVE":
            raise ApiError(
                "ERR_INTERPRETER_NOT_ON_ACTIVE_ROSTER",
                "The interpreter is no longer on the active roster.",
            )
        credential = db.credentials.get(assignment["credential_id"])
        if credential is None or credential["status"] != "ACTIVE":
            raise ApiError(
                "ERR_CREDENTIAL_NOT_ACTIVE",
                "The pinned credential is no longer active.",
            )

    if assignment["delivery_mode"] == "IN_PERSON" and courthouse["status"] != "OPEN":
        raise ApiError(
            "ERR_REMOTE_EQUIPMENT_UNAVAILABLE",
            "The courthouse is closed to in-person appearances.",
        )
    if (
        assignment["delivery_mode"] == "VRI"
        and courthouse["remote_equipment_tier"] != "CERTIFIED_VRI"
    ):
        raise ApiError(
            "ERR_REMOTE_EQUIPMENT_UNAVAILABLE",
            "Confirming video remote interpreting requires a certified facility.",
        )

    schedule = None
    if not assignment["vendor_served"]:
        schedule = derive.schedule_for_hearing(hearing)
        if schedule is None:
            raise ApiError(
                "ERR_RATE_SCHEDULE_NOT_EFFECTIVE",
                "No rate schedule is in effect for the hearing's date.",
            )
        figures = pay.compute(assignment, "PROVISIONAL", schedule)
        if figures["total_cents"] > derive.available_pay_cents(courthouse):
            raise ApiError(
                "ERR_COURTHOUSE_BUDGET_EXCEEDED",
                "The provisional amount exceeds the courthouse's available budget.",
            )

    assignment["service_status"] = "CONFIRMED"
    touch(assignment)
    if schedule is not None:
        cascades.create_claim(assignment, schedule)
        touch(courthouse)
    if hearing["status"] == "SCHEDULED":
        hearing["status"] = "COVERED"
        touch(hearing)
    return object_response(S.assignment_out(assignment))


@bp.route("/assignments/<assignment_id>/decline", methods=["POST"])
def decline_assignment(assignment_id):
    user_id, role = require("Interpreter")
    body = body_of(request)
    enum_field(body, "reason_code", CANCEL_REASONS)
    assignment = derive.get_assignment(assignment_id)
    _owner_gate(assignment, user_id, role)
    if assignment["service_status"] != "PROPOSED":
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "Only a proposed assignment may be declined.",
        )
    assignment["service_status"] = "DECLINED"
    assignment["cancel_reason_code"] = "INTERPRETER_DECLINED"
    touch(assignment)
    return object_response(S.assignment_out(assignment))


# --------------------------------------------------------------------------
# service
# --------------------------------------------------------------------------
@bp.route("/assignments/<assignment_id>/check-in", methods=["POST"])
def check_in_assignment(assignment_id):
    user_id, role = require("Interpreter")
    body_of(request)
    assignment = derive.get_assignment(assignment_id)
    _owner_gate(assignment, user_id, role)
    if assignment["service_status"] != "CONFIRMED":
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "Only a confirmed assignment may be checked in.",
        )
    interpreter = db.interpreters[assignment["interpreter_id"]]
    if interpreter["roster_status"] != "ACTIVE":
        raise ApiError(
            "ERR_INTERPRETER_NOT_ON_ACTIVE_ROSTER",
            "The interpreter is no longer on the active roster.",
        )
    assignment["check_in_utc"] = fmt_dt(now())
    assignment["service_status"] = "CHECKED_IN"
    touch(assignment)
    return object_response(S.assignment_out(assignment))


@bp.route("/assignments/<assignment_id>/complete", methods=["POST"])
def complete_assignment(assignment_id):
    user_id, role = require("Interpreter", "SchedulingCoordinator")
    body = body_of(request)
    actual_end = datetime_field(body, "actual_end_utc")
    miles = num_field(body, "one_way_miles", required=False, default=0, minimum=0)

    assignment = derive.get_assignment(assignment_id)
    _owner_gate(assignment, user_id, role)

    vendor = assignment["vendor_served"]
    expected_state = "CONFIRMED" if vendor else "CHECKED_IN"
    if assignment["service_status"] != expected_state:
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "This assignment cannot be completed from its current state.",
        )

    hearing = db.hearings[assignment["hearing_id"]]
    courthouse = db.courthouses[hearing["courthouse_id"]]
    scheduled_start = parse_dt(hearing["scheduled_start"])
    scheduled_end = parse_dt(hearing["scheduled_end"])
    latest = scheduled_end + timedelta(hours=derive.MAX_OVERRUN_HOURS)
    window_ok = scheduled_start <= actual_end <= latest
    if window_ok:
        if vendor:
            window_ok = actual_end > scheduled_start
        else:
            window_ok = actual_end > parse_dt(assignment["check_in_utc"])
    if not window_ok:
        raise ApiError(
            "ERR_HEARING_WINDOW_CLOSED",
            "actual_end_utc lies outside the permitted completion envelope.",
        )

    claim = None
    schedule = None
    if not vendor:
        if derive.schedule_for_hearing(hearing) is None:
            raise ApiError(
                "ERR_RATE_SCHEDULE_NOT_EFFECTIVE",
                "No rate schedule is in effect for the hearing's date.",
            )
        claim = derive.claim_for_assignment(assignment["id"])
        if claim is not None:
            schedule = db.rate_schedules[claim["rate_schedule_id"]]
            probe = dict(assignment)
            probe["actual_end_utc"] = fmt_dt(actual_end)
            probe["actual_one_way_miles"] = miles
            figures = pay.compute(probe, "FINAL", schedule)
            headroom = (
                derive.available_pay_cents(courthouse)
                + claim["provisional_total_cents"]
            )
            if figures["total_cents"] > headroom:
                raise ApiError(
                    "ERR_COURTHOUSE_BUDGET_EXCEEDED",
                    "The final amount exceeds the courthouse's available budget.",
                )

    assignment["actual_end_utc"] = fmt_dt(actual_end)
    assignment["actual_one_way_miles"] = miles
    assignment["service_status"] = "COMPLETED"
    touch(assignment)

    if claim is not None and claim["status"] == "ENCUMBERED":
        cascades.finalize_claim(claim, "FINAL", schedule)
        touch(courthouse)
        touch(db.interpreters[assignment["interpreter_id"]])

    if hearing["status"] == "COVERED":
        hearing["status"] = "SERVED"
        touch(hearing)
    return object_response(S.assignment_out(assignment))


# --------------------------------------------------------------------------
# withdrawal
# --------------------------------------------------------------------------
@bp.route("/assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    require("SchedulingCoordinator", "ProgramAdmin")
    body = body_of(request)
    reason_code = enum_field(body, "reason_code", CANCEL_REASONS)
    assignment = derive.get_assignment(assignment_id)
    if assignment["service_status"] not in derive.CANCELLABLE_SERVICE_STATUSES:
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "Only a proposed or confirmed assignment may be cancelled.",
        )
    hearing = db.hearings[assignment["hearing_id"]]
    if now() >= parse_dt(hearing["scheduled_start"]):
        raise ApiError(
            "ERR_HEARING_WINDOW_CLOSED",
            "The hearing's start instant has already passed.",
        )
    cascades.cancel_assignment(assignment, reason_code)
    return object_response(S.assignment_out(assignment))


@bp.route("/assignments/<assignment_id>/no-show", methods=["POST"])
def no_show_assignment(assignment_id):
    user_id, _role = require("SchedulingCoordinator", "ProgramAdmin")
    body_of(request)
    assignment = derive.get_assignment(assignment_id)
    if assignment["service_status"] != "CONFIRMED":
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "Only a confirmed assignment may be recorded as a no-show.",
        )
    hearing = db.hearings[assignment["hearing_id"]]
    if now() < parse_dt(hearing["scheduled_start"]):
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "A no-show may only be recorded once the hearing has started.",
        )
    courthouse = db.courthouses[hearing["courthouse_id"]]

    assignment["service_status"] = "NO_SHOW"
    if assignment["compliance_status"] == "CLEAR":
        assignment["compliance_status"] = "UNDER_QUALITY_REVIEW"
    touch(assignment)

    claim = derive.claim_for_assignment(assignment["id"])
    if claim is not None and claim["status"] == "ENCUMBERED":
        cascades.void_claim(claim)
        touch(courthouse)

    complaint = new_row()
    complaint.update(
        {
            "interpreter_id": assignment["interpreter_id"],
            "assignment_id": assignment["id"],
            "category": "NO_SHOW",
            "severity": "MAJOR",
            "narrative": "The confirmed interpreter failed to appear for the hearing.",
            "filed_by_user_id": user_id,
            "reviewer_user_id": None,
            "reviewer_recommendation": None,
            "adjudicator_user_id": None,
            "disposition": None,
            "status": "FILED",
            "adjudicated_at": None,
            "appeal_filed_at": None,
            "remand_count": 0,
        }
    )
    db.complaints[complaint["id"]] = complaint

    if hearing["status"] == "COVERED":
        hearing["status"] = "UNMET"
        touch(hearing)
    return object_response(S.assignment_out(assignment))
