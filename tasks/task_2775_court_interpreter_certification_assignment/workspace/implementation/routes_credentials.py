"""The credential pipeline: applications, examinations, activation, cycles."""
from flask import Blueprint, request

import cascades
import derive
import serializers as S
from auth import require
from envelope import array_response, object_response, paginate, read_pagination
from errors import ApiError
from store import db, new_row, sort_created, today, touch
from util import add_days, fmt_date, parse_date
from validation import (
    body_of,
    date_field,
    enum_field,
    int_field,
    num_field,
    query_enum,
    query_str,
    str_field,
)

bp = Blueprint("credentials", __name__)

CREDENTIAL_STATUSES = (
    "PENDING_WRITTEN",
    "PENDING_ORAL",
    "PENDING_ETHICS",
    "ACTIVE",
    "LAPSED",
    "DENIED",
    "WITHDRAWN",
    "REVOKED",
)
EXAM_TYPES = ("WRITTEN", "ORAL")
READ_ROLES = (
    "ProgramAdmin",
    "CredentialingOfficer",
    "SchedulingCoordinator",
    "QualityReviewer",
    "Interpreter",
)


def _passing_floor(target_tier, exam_type):
    if exam_type == "WRITTEN":
        return derive.WRITTEN_FLOOR[target_tier]
    return derive.ORAL_FLOOR[target_tier]


def _best_score(credential_id, exam_type):
    attempts = S.attempts_of(credential_id, exam_type)
    return max([a["score"] for a in attempts]) if attempts else None


# --------------------------------------------------------------------------
# applications
# --------------------------------------------------------------------------
@bp.route("/credentials", methods=["POST"])
def create_credential():
    require("CredentialingOfficer")
    body = body_of(request)
    interpreter_id = str_field(body, "interpreter_id")
    language_id = str_field(body, "language_id")
    target_tier = enum_field(body, "target_tier", derive.TIERS)
    expected_version = int_field(body, "expected_interpreter_version")

    interpreter = derive.get_interpreter(interpreter_id)
    language = derive.get_language(language_id)

    if interpreter["version"] != expected_version:
        raise ApiError(
            "ERR_STALE_INTERPRETER_VERSION",
            "The interpreter has been modified since it was last read.",
        )

    if target_tier == "PROVISIONAL" and not (
        language["tier_class"] == "RARE" or not language["oral_exam_available"]
    ):
        raise ApiError(
            "ERR_PROVISIONAL_TIER_NOT_PERMITTED",
            "A provisional tier is not permitted for a fully examinable language.",
        )

    superseded = None
    for existing in derive.credentials_of(interpreter_id):
        if existing["language_id"] != language_id:
            continue
        if existing["status"] not in derive.LIVE_CREDENTIAL_STATUSES:
            continue
        upgradable = existing["status"] in (
            "PENDING_WRITTEN",
            "PENDING_ORAL",
            "PENDING_ETHICS",
        ) and derive.TIER_RANK[target_tier] > derive.TIER_RANK[existing["target_tier"]]
        if upgradable and superseded is None:
            superseded = existing
            continue
        raise ApiError(
            "ERR_DUPLICATE_ACTIVE_CREDENTIAL",
            "The interpreter already holds a live credential in that language.",
        )

    row = new_row()
    row.update(
        {
            "interpreter_id": interpreter_id,
            "language_id": language_id,
            "target_tier": target_tier,
            "tier": None,
            "status": "PENDING_WRITTEN",
            "issued_on": None,
            "expires_on": None,
            "grace_through": None,
            "cycle_credit_hours": 0,
            "renewal_count": 0,
        }
    )
    db.credentials[row["id"]] = row

    if superseded is not None:
        superseded["status"] = "WITHDRAWN"
        touch(superseded)
        touch(interpreter)
    elif interpreter["roster_status"] == "APPLICANT":
        interpreter["roster_status"] = "CANDIDATE"
        touch(interpreter)

    if target_tier == "PROVISIONAL" and language["tier_class"] == "RARE":
        row["status"] = "PENDING_ETHICS"
        touch(row)

    return object_response(S.credential_out(row), 201)


@bp.route("/credentials", methods=["GET"])
def list_credentials():
    require(*READ_ROLES)
    limit, offset = read_pagination(request.args)
    interpreter_id = query_str(request.args, "interpreter_id")
    language_id = query_str(request.args, "language_id")
    status = query_enum(request.args, "status", CREDENTIAL_STATUSES)
    target_tier = query_enum(request.args, "target_tier", derive.TIERS)
    rows = []
    for row in db.credentials.values():
        if interpreter_id is not None and row["interpreter_id"] != interpreter_id:
            continue
        if language_id is not None and row["language_id"] != language_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if target_tier is not None and row["target_tier"] != target_tier:
            continue
        rows.append(row)
    rows = sort_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([S.credential_out(r) for r in page], limit, offset, total)


@bp.route("/credentials/<credential_id>", methods=["GET"])
def get_credential(credential_id):
    require(*READ_ROLES)
    row = derive.get_credential(credential_id)
    return object_response(S.credential_out(row))


# --------------------------------------------------------------------------
# examinations
# --------------------------------------------------------------------------
@bp.route("/credentials/<credential_id>/exam-attempts", methods=["POST"])
def create_exam_attempt(credential_id):
    require("CredentialingOfficer")
    body = body_of(request)
    exam_type = enum_field(body, "exam_type", EXAM_TYPES)
    score = num_field(body, "score", minimum=0, maximum=100)
    taken_on = date_field(body, "taken_on")

    credential = derive.get_credential(credential_id)
    if credential["status"] not in ("PENDING_WRITTEN", "PENDING_ORAL"):
        raise ApiError(
            "ERR_INVALID_CREDENTIAL_STATE",
            "Examination attempts may only be recorded while an application is pending.",
        )

    same_type = S.attempts_of(credential_id, exam_type)
    if len(same_type) >= derive.MAX_ATTEMPTS_PER_EXAM:
        raise ApiError(
            "ERR_EXAM_ATTEMPT_LIMIT_REACHED",
            "The examination attempt limit for this credential has been reached.",
        )

    failed = [a for a in same_type if a["result"] == "FAIL"]
    if failed:
        latest = max(parse_date(a["taken_on"]) for a in failed)
        if (taken_on - latest).days < derive.RETAKE_WAIT_DAYS:
            raise ApiError(
                "ERR_EXAM_RETAKE_TOO_SOON",
                "The retake waiting period has not yet elapsed.",
            )

    language = db.languages[credential["language_id"]]
    if exam_type == "ORAL" and not language["oral_exam_available"]:
        raise ApiError(
            "ERR_ORAL_EXAM_NOT_OFFERED",
            "No oral performance examination exists in that language.",
        )

    floor = _passing_floor(credential["target_tier"], exam_type)
    attempt = new_row(common=False)
    attempt.update(
        {
            "credential_id": credential_id,
            "exam_type": exam_type,
            "score": score,
            "taken_on": fmt_date(taken_on),
            "attempt_ordinal": 0,
            "result": "PASS" if score >= floor else "FAIL",
        }
    )
    db.exam_attempts[attempt["id"]] = attempt
    ordered = S.attempts_of(credential_id, exam_type)
    attempt["attempt_ordinal"] = ordered.index(attempt) + 1
    touch(credential)

    count = len(ordered)
    best = _best_score(credential_id, exam_type)
    if count >= derive.MAX_ATTEMPTS_PER_EXAM and best is not None and best < floor:
        if exam_type == "WRITTEN" and credential["status"] == "PENDING_WRITTEN":
            credential["status"] = "DENIED"
            touch(credential)
        elif exam_type == "ORAL" and credential["status"] == "PENDING_ORAL":
            credential["status"] = "DENIED"
            touch(credential)

    return object_response(S.exam_attempt_out(attempt), 201)


@bp.route("/credentials/<credential_id>/exam-attempts", methods=["GET"])
def list_exam_attempts(credential_id):
    require("ProgramAdmin", "CredentialingOfficer", "QualityReviewer", "Interpreter")
    limit, offset = read_pagination(request.args)
    exam_type = query_enum(request.args, "exam_type", EXAM_TYPES)
    derive.get_credential(credential_id)
    rows = S.attempts_of(credential_id, exam_type)
    page, total = paginate(rows, limit, offset)
    return array_response([S.exam_attempt_out(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# advancement
# --------------------------------------------------------------------------
@bp.route("/credentials/<credential_id>/advance", methods=["POST"])
def advance_credential(credential_id):
    require("CredentialingOfficer")
    body_of(request)
    credential = derive.get_credential(credential_id)
    status = credential["status"]
    if status not in ("PENDING_WRITTEN", "PENDING_ORAL", "PENDING_ETHICS"):
        raise ApiError(
            "ERR_INVALID_CREDENTIAL_STATE",
            "This credential is not at a stage that can be advanced.",
        )

    language = db.languages[credential["language_id"]]
    interpreter = db.interpreters[credential["interpreter_id"]]
    target = credential["target_tier"]

    if status == "PENDING_WRITTEN":
        written_best = _best_score(credential_id, "WRITTEN")
        written_floor = derive.WRITTEN_FLOOR[target]
        if (
            target in ("MASTER", "CERTIFIED")
            and language["oral_exam_available"]
            and written_best is not None
            and written_best >= written_floor
        ):
            credential["status"] = "PENDING_ORAL"
        elif (
            written_best is not None
            and written_best >= 80
            and (target == "REGISTERED" or not language["oral_exam_available"])
        ):
            credential["status"] = "PENDING_ETHICS"
        else:
            raise ApiError(
                "ERR_INVALID_CREDENTIAL_STATE",
                "The written stage requirement has not been met.",
            )
        touch(credential)
        return object_response(S.credential_out(credential))

    if status == "PENDING_ORAL":
        oral_best = _best_score(credential_id, "ORAL")
        if oral_best is None or oral_best < derive.ORAL_FLOOR[target]:
            raise ApiError(
                "ERR_INVALID_CREDENTIAL_STATE",
                "The oral stage requirement has not been met.",
            )
        credential["status"] = "PENDING_ETHICS"
        touch(credential)
        return object_response(S.credential_out(credential))

    if interpreter["ethics_training_status"] != "COMPLETED":
        raise ApiError(
            "ERR_ETHICS_TRAINING_INCOMPLETE",
            "The holder has not completed mandatory ethics training.",
        )
    issued_on = today()
    expires_on = add_days(issued_on, derive.CYCLE_DAYS[target])
    credential["status"] = "ACTIVE"
    credential["tier"] = target
    credential["issued_on"] = fmt_date(issued_on)
    credential["expires_on"] = fmt_date(expires_on)
    credential["grace_through"] = fmt_date(add_days(expires_on, derive.GRACE_DAYS))
    touch(credential)
    touch(language)
    if interpreter["roster_status"] in ("CANDIDATE", "INACTIVE"):
        interpreter["roster_status"] = "ACTIVE"
    touch(interpreter)
    return object_response(S.credential_out(credential))


# --------------------------------------------------------------------------
# cycles
# --------------------------------------------------------------------------
@bp.route("/credentials/<credential_id>/renew", methods=["POST"])
def renew_credential(credential_id):
    require("CredentialingOfficer")
    body = body_of(request)
    hours = num_field(body, "cycle_credit_hours", minimum=0)

    credential = derive.get_credential(credential_id)
    if credential["status"] not in ("ACTIVE", "LAPSED"):
        raise ApiError(
            "ERR_INVALID_CREDENTIAL_STATE",
            "Only an active or lapsed credential may be renewed.",
        )
    interpreter = db.interpreters[credential["interpreter_id"]]
    if interpreter["roster_status"] == "REVOKED":
        raise ApiError(
            "ERR_INVALID_CREDENTIAL_STATE",
            "A revoked interpreter's credential may not be renewed.",
        )
    if hours < derive.MIN_RENEWAL_CREDIT_HOURS:
        raise ApiError(
            "ERR_INSUFFICIENT_CREDIT_HOURS",
            "At least 16 continuing-education hours are required.",
        )
    was_lapsed = credential["status"] == "LAPSED"
    if was_lapsed:
        grace_through = parse_date(credential["grace_through"])
        if grace_through is None or today() > grace_through:
            raise ApiError(
                "ERR_RENEWAL_GRACE_EXPIRED",
                "The renewal grace window for this credential has closed.",
            )

    current_expiry = parse_date(credential["expires_on"])
    base = current_expiry if current_expiry and current_expiry > today() else today()
    expires_on = add_days(base, derive.CYCLE_DAYS[credential["target_tier"]])
    credential["expires_on"] = fmt_date(expires_on)
    credential["grace_through"] = fmt_date(add_days(expires_on, derive.GRACE_DAYS))
    credential["cycle_credit_hours"] = hours
    credential["renewal_count"] = credential["renewal_count"] + 1
    if was_lapsed:
        credential["status"] = "ACTIVE"
        credential["tier"] = credential["target_tier"]
    touch(credential)

    if was_lapsed:
        touch(db.languages[credential["language_id"]])
        suspended = [
            a
            for a in db.disciplinary_actions.values()
            if a["interpreter_id"] == interpreter["id"]
            and a["action_type"] == "SUSPENSION"
            and a["status"] == "IN_EFFECT"
        ]
        if interpreter["roster_status"] == "INACTIVE" and not suspended:
            interpreter["roster_status"] = "ACTIVE"
        touch(interpreter)
    return object_response(S.credential_out(credential))


@bp.route("/credentials/<credential_id>/revoke", methods=["POST"])
def revoke_credential(credential_id):
    require("ProgramAdmin")
    body = body_of(request)
    str_field(body, "reason")
    credential = derive.get_credential(credential_id)
    if credential["status"] not in derive.LIVE_CREDENTIAL_STATUSES:
        raise ApiError(
            "ERR_INVALID_CREDENTIAL_STATE",
            "This credential has already reached a terminal status.",
        )
    cascades.revoke_credential(credential)
    return object_response(S.credential_out(credential))
