"""Quality review, discipline and appeals (PRD 3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import cascades
import derive
import serializers as S
from auth import require
from envelope import array_response, object_response, paginate, read_pagination
from errors import ApiError
from store import db, new_row, now, touch
from util import fmt_dt, parse_dt
from validation import (
    body_of,
    enum_field,
    int_field,
    query_enum,
    query_str,
    str_field,
)

bp = Blueprint("complaints", __name__)

CATEGORIES = ("ACCURACY", "ETHICS", "PROFESSIONALISM", "NO_SHOW")
SEVERITIES = ("MINOR", "MAJOR", "SEVERE")
COMPLAINT_STATUSES = (
    "FILED",
    "REVIEWED",
    "SUBSTANTIATED",
    "DISMISSED",
    "APPEALED",
    "UPHELD",
    "VACATED",
)
RECOMMENDATIONS = ("SUBSTANTIATE", "DISMISS")
DISPOSITIONS = ("SUBSTANTIATED", "DISMISSED")
SANCTION_TYPES = ("LETTER", "PROBATION", "SUSPENSION", "REVOCATION")
OUTCOMES = ("UPHELD", "VACATED", "REMANDED")
ACTION_STATUSES = ("IN_EFFECT", "EXPIRED", "RESCINDED")
OPEN_COMPLAINT_STATUSES = ("FILED", "REVIEWED", "APPEALED")
READ_ROLES = ("ProgramAdmin", "QualityReviewer", "SchedulingCoordinator", "Interpreter")


def _release_assignment(complaint, target_status):
    """Move the named assignment's compliance dimension, when one is named."""
    if not complaint["assignment_id"]:
        return
    assignment = db.assignments.get(complaint["assignment_id"])
    if assignment is None:
        return
    if target_status == "CLEAR":
        others = [
            c
            for c in db.complaints.values()
            if c["assignment_id"] == assignment["id"]
            and c["id"] != complaint["id"]
            and c["status"] in OPEN_COMPLAINT_STATUSES
        ]
        if others:
            return
    if assignment["compliance_status"] != target_status:
        assignment["compliance_status"] = target_status
        touch(assignment)


def _action_of(complaint):
    actions = [
        a
        for a in db.disciplinary_actions.values()
        if a["complaint_id"] == complaint["id"] and a["status"] == "IN_EFFECT"
    ]
    return S.created_order(actions)[-1] if actions else None


# --------------------------------------------------------------------------
# intake and reads
# --------------------------------------------------------------------------
@bp.route("/complaints", methods=["POST"])
def create_complaint():
    user_id, _role = require("QualityReviewer", "SchedulingCoordinator", "ProgramAdmin")
    body = body_of(request)
    interpreter_id = str_field(body, "interpreter_id")
    assignment_id = str_field(body, "assignment_id", required=False)
    category = enum_field(body, "category", CATEGORIES)
    severity = enum_field(body, "severity", SEVERITIES)
    narrative = str_field(body, "narrative")

    derive.get_interpreter(interpreter_id)
    assignment = (
        derive.get_assignment(assignment_id) if assignment_id is not None else None
    )

    row = new_row()
    row.update(
        {
            "interpreter_id": interpreter_id,
            "assignment_id": assignment_id,
            "category": category,
            "severity": severity,
            "narrative": narrative,
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
    db.complaints[row["id"]] = row

    if assignment is not None and assignment["compliance_status"] == "CLEAR":
        assignment["compliance_status"] = "UNDER_QUALITY_REVIEW"
        touch(assignment)

    return object_response(S.complaint_out(row), 201)


@bp.route("/complaints", methods=["GET"])
def list_complaints():
    require(*READ_ROLES)
    limit, offset = read_pagination(request.args)
    interpreter_id = query_str(request.args, "interpreter_id")
    assignment_id = query_str(request.args, "assignment_id")
    status = query_enum(request.args, "status", COMPLAINT_STATUSES)
    severity = query_enum(request.args, "severity", SEVERITIES)
    rows = []
    for row in db.complaints.values():
        if interpreter_id is not None and row["interpreter_id"] != interpreter_id:
            continue
        if assignment_id is not None and row["assignment_id"] != assignment_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if severity is not None and row["severity"] != severity:
            continue
        rows.append(row)
    rows = S.created_order(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([S.complaint_out(r) for r in page], limit, offset, total)


@bp.route("/complaints/<complaint_id>", methods=["GET"])
def get_complaint(complaint_id):
    require(*READ_ROLES)
    row = derive.get_complaint(complaint_id)
    return object_response(S.complaint_out(row))


# --------------------------------------------------------------------------
# review and adjudication
# --------------------------------------------------------------------------
@bp.route("/complaints/<complaint_id>/review", methods=["POST"])
def review_complaint(complaint_id):
    user_id, _role = require("QualityReviewer")
    body = body_of(request)
    recommendation = enum_field(body, "recommendation", RECOMMENDATIONS)
    str_field(body, "findings")

    complaint = derive.get_complaint(complaint_id)
    if complaint["filed_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reviewer of a complaint may not be its filer.",
        )
    if complaint["status"] != "FILED":
        raise ApiError(
            "ERR_INVALID_COMPLAINT_STATE",
            "Only a filed complaint may be reviewed.",
        )
    complaint["reviewer_user_id"] = user_id
    complaint["reviewer_recommendation"] = recommendation
    complaint["status"] = "REVIEWED"
    touch(complaint)
    return object_response(S.complaint_out(complaint))


@bp.route("/complaints/<complaint_id>/adjudicate", methods=["POST"])
def adjudicate_complaint(complaint_id):
    user_id, _role = require("ProgramAdmin")
    body = body_of(request)
    disposition = enum_field(body, "disposition", DISPOSITIONS)
    sanction_type = enum_field(body, "sanction_type", SANCTION_TYPES, required=False)
    suspension_days = int_field(body, "suspension_days", required=False, minimum=1)
    if disposition == "SUBSTANTIATED":
        if sanction_type is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "A substantiation requires a sanction_type.",
            )
        if sanction_type == "SUSPENSION" and suspension_days is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "A suspension requires suspension_days.",
            )

    complaint = derive.get_complaint(complaint_id)
    if complaint["status"] != "REVIEWED":
        raise ApiError(
            "ERR_INVALID_COMPLAINT_STATE",
            "Only a reviewed complaint may be adjudicated.",
        )

    if disposition == "SUBSTANTIATED":
        if sanction_type not in derive.SANCTION_WINDOW[complaint["severity"]]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "That sanction is outside the window permitted by the complaint's "
                "severity.",
            )

    complaint["adjudicator_user_id"] = user_id
    complaint["adjudicated_at"] = fmt_dt(now())
    complaint["disposition"] = disposition
    complaint["status"] = disposition
    touch(complaint)

    if disposition == "DISMISSED":
        _release_assignment(complaint, "CLEAR")
        return object_response(S.complaint_out(complaint))

    action = cascades.create_disciplinary_action(
        complaint, sanction_type, suspension_days
    )
    cascades.apply_sanction(action)
    _release_assignment(complaint, "SUBSTANTIATED_DEFECT")
    return object_response(S.complaint_out(complaint))


# --------------------------------------------------------------------------
# appeals
# --------------------------------------------------------------------------
@bp.route("/complaints/<complaint_id>/appeal", methods=["POST"])
def appeal_complaint(complaint_id):
    user_id, role = require("Interpreter")
    body = body_of(request)
    str_field(body, "grounds")
    complaint = derive.get_complaint(complaint_id)
    if role == "Interpreter" and complaint["interpreter_id"] != user_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "This complaint concerns another interpreter.",
        )
    if complaint["status"] != "SUBSTANTIATED":
        raise ApiError(
            "ERR_INVALID_COMPLAINT_STATE",
            "Only a substantiated complaint may be appealed.",
        )
    adjudicated_at = parse_dt(complaint["adjudicated_at"])
    if adjudicated_at is None or now() - adjudicated_at > timedelta(
        days=derive.APPEAL_WINDOW_DAYS
    ):
        raise ApiError(
            "ERR_APPEAL_WINDOW_EXPIRED",
            "The 30-day appeal window has closed.",
        )
    complaint["status"] = "APPEALED"
    complaint["appeal_filed_at"] = fmt_dt(now())
    touch(complaint)
    return object_response(S.complaint_out(complaint))


@bp.route("/complaints/<complaint_id>/appeal-decision", methods=["POST"])
def decide_appeal(complaint_id):
    user_id, _role = require("ProgramAdmin")
    body = body_of(request)
    outcome = enum_field(body, "outcome", OUTCOMES)
    complaint = derive.get_complaint(complaint_id)
    if complaint["adjudicator_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The administrator who adjudicated a complaint may not decide its appeal.",
        )
    if complaint["status"] != "APPEALED":
        raise ApiError(
            "ERR_INVALID_COMPLAINT_STATE",
            "Only an appealed complaint may receive an appeal decision.",
        )

    action = _action_of(complaint)

    if outcome == "UPHELD":
        complaint["status"] = "UPHELD"
        touch(complaint)
        return object_response(S.complaint_out(complaint))

    if outcome == "VACATED":
        complaint["disposition"] = None
        complaint["status"] = "VACATED"
        touch(complaint)
        if action is not None:
            cascades.rescind_action(action)
        _release_assignment(complaint, "CLEAR")
        return object_response(S.complaint_out(complaint))

    complaint["status"] = "FILED"
    complaint["remand_count"] = complaint["remand_count"] + 1
    complaint["reviewer_user_id"] = None
    complaint["reviewer_recommendation"] = None
    complaint["adjudicator_user_id"] = None
    complaint["disposition"] = None
    complaint["adjudicated_at"] = None
    touch(complaint)
    if action is not None:
        cascades.rescind_action(action)
    return object_response(S.complaint_out(complaint))


# --------------------------------------------------------------------------
# disciplinary actions
# --------------------------------------------------------------------------
@bp.route("/disciplinary-actions", methods=["GET"])
def list_disciplinary_actions():
    require(*READ_ROLES)
    limit, offset = read_pagination(request.args)
    complaint_id = query_str(request.args, "complaint_id")
    interpreter_id = query_str(request.args, "interpreter_id")
    status = query_enum(request.args, "status", ACTION_STATUSES)
    action_type = query_enum(request.args, "action_type", SANCTION_TYPES)
    rows = []
    for row in db.disciplinary_actions.values():
        if complaint_id is not None and row["complaint_id"] != complaint_id:
            continue
        if interpreter_id is not None and row["interpreter_id"] != interpreter_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if action_type is not None and row["action_type"] != action_type:
            continue
        rows.append(row)
    rows = sorted(rows, key=lambda r: (r["effective_from"], r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return array_response(
        [S.disciplinary_action_out(r) for r in page], limit, offset, total
    )


@bp.route("/disciplinary-actions/<action_id>", methods=["GET"])
def get_disciplinary_action(action_id):
    require(*READ_ROLES)
    row = derive.get_disciplinary_action(action_id)
    return object_response(S.disciplinary_action_out(row))
