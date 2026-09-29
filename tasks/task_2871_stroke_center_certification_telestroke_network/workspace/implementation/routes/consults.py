"""Telestroke consults: routing, acceptance, sessions and completion
(PRD 3.3, 3.4).
"""
from flask import Blueprint

import db
import response as resp
from constants import (
    CASE_TERMINAL,
    CONSULT_DECLINE_LIMIT,
    CONSULT_LIVE,
    NEUROLOGIST_COOLDOWN_MIN,
    PRIVILEGE_SCOPES,
    RECOMMENDATIONS,
    VIDEO_QUALITIES,
)
from errors import fail
from middleware import (
    Field,
    apply_filters,
    authenticate,
    load_path,
    load_ref,
    pagination,
    read_body,
)
from services import calculations as calc
from services import derive
from services import routing

bp = Blueprint("consults", __name__)

CREATE_SPEC = [
    Field("case_id", "str"),
    Field("agreement_id", "str"),
    Field("requested_privilege_scope", "str", enum=PRIVILEGE_SCOPES),
    Field("expected_case_version", "int"),
]

DECLINE_SPEC = [Field("last_decline_reason", "str", min_len=1)]

SESSION_SPEC = [
    Field("started_at", "dt"),
    Field("ended_at", "dt"),
    Field("video_quality", "str", enum=VIDEO_QUALITIES),
    Field("disconnect_count", "int", minimum=0),
]

COMPLETE_SPEC = [
    Field("recommendation", "str", enum=RECOMMENDATIONS),
    Field("nihss_score", "int", minimum=0, maximum=42),
]


def _owner_or_fail(consult, user_id):
    """PRD 2.11 rule 4: consult ownership outranks request shape."""
    if consult.get("assigned_neurologist_id") != user_id:
        fail("ERR_NOT_CONSULT_OWNER",
             "The acting neurologist is not this consult's assignee.")
    neurologist = db.get("neurologists", user_id)
    if neurologist is None:
        fail("ERR_NOT_CONSULT_OWNER",
             "The acting neurologist is not this consult's assignee.")
    return neurologist


def _route(consult, agreement, case):
    """Run the selector for the pass already counted in routing_attempt_count."""
    winner = routing.select(consult, agreement, case)
    if winner is not None:
        consult["assigned_neurologist_id"] = winner["id"]
        consult["assigned_at"] = db.now_raw()
        consult["status"] = "ASSIGNED"
        derive.recompute_neurologist_active_count(winner)
    else:
        consult["status"] = "ESCALATED_UNFILLED"
        consult["assigned_neurologist_id"] = None
        derive.open_system_deviation(
            case, "CONSULT_UNFILLED", "MAJOR",
            "No on-call neurologist was available to fill the telestroke consult.")
    derive.recompute_agreement_active_count(agreement)
    return winner


@bp.route("/consults", methods=["POST"])
def create_consult():
    authenticate(("EdPhysician",))
    body = read_body(CREATE_SPEC)
    case = load_ref("cases", body["case_id"])
    agreement = load_ref("agreements", body["agreement_id"])
    if body["expected_case_version"] != case["version"]:
        fail("ERR_STALE_CASE_VERSION",
             "expected_case_version %s does not match the case's current version %s."
             % (body["expected_case_version"], case["version"]))
    if case["status"] in CASE_TERMINAL or case["status"] not in (
            "ACTIVATED", "IMAGING_COMPLETE"):
        fail("ERR_CASE_NOT_ACTIVE",
             "No consult request is declared from case status %s." % case["status"])
    center = db.get("centers", case["center_id"])
    if center is None or center["equipment_readiness_posture"] == "OFFLINE":
        fail("ERR_CENTER_EQUIPMENT_OFFLINE",
             "The facility's equipment readiness posture is OFFLINE.")
    if agreement["spoke_center_id"] != case["center_id"]:
        fail("ERR_AGREEMENT_CENTER_MISMATCH",
             "The agreement's spoke_center_id is not the case's facility.")
    now = db.now_dt()
    if now < db.parse_iso(agreement["effective_from"]):
        fail("ERR_AGREEMENT_WINDOW_CLOSED",
             "The agreement's coverage window has not yet opened.")
    # The expiry check is the last thing before the ACTIVE guard: an expired
    # ACTIVE agreement is terminated here and then, and the request that
    # triggered the termination is rejected because it is no longer ACTIVE.
    if now >= db.parse_iso(agreement["effective_until"]) and agreement["status"] == "ACTIVE":
        agreement["status"] = "TERMINATED"
        db.touch(agreement)
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE",
             "The agreement's status is %s." % agreement["status"])
    live = [c for c in db.all_of("consults")
            if c["agreement_id"] == agreement["id"] and c["status"] in CONSULT_LIVE]
    if len(live) >= agreement["max_concurrent_consults"]:
        fail("ERR_AGREEMENT_CONSULT_CAPACITY",
             "The agreement already carries %d live consults." % len(live))
    record = {
        "case_id": case["id"],
        "agreement_id": agreement["id"],
        "assigned_neurologist_id": None,
        "requested_privilege_scope": body["requested_privilege_scope"],
        "status": "REQUESTED",
        "requested_at": db.now_raw(),
        "assigned_at": None,
        "accepted_at": None,
        "completed_at": None,
        "response_latency_seconds": None,
        "decline_count": 0,
        "routing_attempt_count": 1,
        "excluded_neurologist_ids": [],
        "video_sessions": [],
        "valid_video_session_count": 0,
        "recommendation": None,
        "nihss_score": None,
        "last_decline_reason": None,
        "cancellation_reason": None,
    }
    db.insert("consults", record)
    _route(record, agreement, case)
    case["status"] = "CONSULT_IN_PROGRESS"
    db.touch(case)
    return resp.object_response(record, 201)


@bp.route("/consults/<record_id>", methods=["GET"])
def read_consult(record_id):
    authenticate("any")
    return resp.object_response(load_path("consults", record_id))


@bp.route("/consults", methods=["GET"])
def list_consults():
    authenticate("any")
    limit, offset = pagination()
    records = apply_filters(db.all_of("consults"), {
        "case_id": "case_id",
        "agreement_id": "agreement_id",
        "assigned_neurologist_id": "assigned_neurologist_id",
        "status": "status",
        "requested_privilege_scope": "requested_privilege_scope",
    })
    return resp.list_response(records, limit, offset)


@bp.route("/consults/<record_id>/accept", methods=["POST"])
def accept_consult(record_id):
    user_id, _role = authenticate(("Neurologist",))
    record = load_path("consults", record_id)
    neurologist = _owner_or_fail(record, user_id)
    read_body([])
    if record["status"] != "ASSIGNED":
        fail("ERR_INVALID_CONSULT_STATE",
             "No acceptance is declared from %s." % record["status"])
    if neurologist["on_call_state"] != "ON_CALL":
        fail("ERR_INVALID_ONCALL_TRANSITION",
             "The neurologist's on_call_state is %s." % neurologist["on_call_state"])
    for other in db.all_of("consults"):
        if (other["id"] != record["id"]
                and other["assigned_neurologist_id"] == neurologist["id"]
                and other["status"] == "IN_SESSION"):
            fail("ERR_INVALID_CONSULT_STATE",
                 "The neurologist already holds a consult IN_SESSION.")
    last_completed = neurologist["last_consult_completed_at"]
    if last_completed is not None:
        elapsed = db.floor_minutes(db.parse_iso(last_completed), db.now_dt())
        if elapsed < NEUROLOGIST_COOLDOWN_MIN:
            fail("ERR_NEUROLOGIST_COOLDOWN_ACTIVE",
                 "Only %d whole minutes have elapsed since the last completion."
                 % elapsed)
    record["status"] = "IN_SESSION"
    record["accepted_at"] = db.now_raw()
    record["response_latency_seconds"] = db.elapsed_seconds(
        db.parse_iso(record["requested_at"]), db.now_dt())
    db.touch(record)
    db.setf(neurologist, "on_call_state", "IN_CONSULT")
    return resp.object_response(record)


@bp.route("/consults/<record_id>/decline", methods=["POST"])
def decline_consult(record_id):
    user_id, _role = authenticate(("Neurologist",))
    record = load_path("consults", record_id)
    neurologist = _owner_or_fail(record, user_id)
    body = read_body(DECLINE_SPEC)
    if record["status"] != "ASSIGNED":
        fail("ERR_INVALID_CONSULT_STATE",
             "No decline is declared from %s." % record["status"])
    agreement = db.get("agreements", record["agreement_id"])
    case = db.get("cases", record["case_id"])
    # The decliner is excluded before anything else happens so the selector
    # cannot pick them again.
    record["excluded_neurologist_ids"] = (
        record["excluded_neurologist_ids"] + [neurologist["id"]])
    record["decline_count"] = record["decline_count"] + 1
    record["last_decline_reason"] = body["last_decline_reason"]
    record["assigned_neurologist_id"] = None
    derive.recompute_neurologist_active_count(neurologist)
    if record["decline_count"] >= CONSULT_DECLINE_LIMIT:
        record["status"] = "ESCALATED_UNFILLED"
        db.touch(record)
        if case is not None:
            derive.open_system_deviation(
                case, "CONSULT_UNFILLED", "MAJOR",
                "The telestroke consult was declined %d times and escalated."
                % record["decline_count"])
        if agreement is not None:
            derive.recompute_agreement_active_count(agreement)
    else:
        record["status"] = "REQUESTED"
        record["routing_attempt_count"] = record["routing_attempt_count"] + 1
        db.touch(record)
        if agreement is not None and case is not None:
            _route(record, agreement, case)
    return resp.object_response(record)


@bp.route("/consults/<record_id>/video-sessions", methods=["POST"])
def append_video_session(record_id):
    user_id, _role = authenticate(("Neurologist",))
    record = load_path("consults", record_id)
    _owner_or_fail(record, user_id)
    body = read_body(SESSION_SPEC)
    if record["status"] != "IN_SESSION":
        fail("ERR_INVALID_CONSULT_STATE",
             "A video session is recorded against an IN_SESSION consult, not %s."
             % record["status"])
    duration = calc.session_duration_seconds(body["started_at"], body["ended_at"])
    valid = calc.session_valid(duration, body["video_quality"],
                              body["disconnect_count"])
    session = {
        "started_at": body["started_at"],
        "ended_at": body["ended_at"],
        "video_quality": body["video_quality"],
        "disconnect_count": body["disconnect_count"],
        "duration_seconds": duration,
        "session_valid": valid,
    }
    record["video_sessions"] = record["video_sessions"] + [session]
    record["valid_video_session_count"] = len(
        [s for s in record["video_sessions"] if s["session_valid"]])
    db.touch(record)
    if not valid:
        case = db.get("cases", record["case_id"])
        if case is not None:
            derive.open_system_deviation(
                case, "INVALID_VIDEO_SESSION", "MINOR",
                "A recorded video session did not meet the validity thresholds.")
    return resp.object_response(record, 201)


@bp.route("/consults/<record_id>/complete", methods=["POST"])
def complete_consult(record_id):
    user_id, _role = authenticate(("Neurologist",))
    record = load_path("consults", record_id)
    neurologist = _owner_or_fail(record, user_id)
    body = read_body(COMPLETE_SPEC)
    if record["status"] != "IN_SESSION":
        fail("ERR_INVALID_CONSULT_STATE",
             "No completion is declared from %s." % record["status"])
    if record["valid_video_session_count"] < 1:
        fail("ERR_NO_VALID_VIDEO_SESSION",
             "The consult carries no valid video session.")
    for session in record["video_sessions"]:
        if session["ended_at"] is None:
            fail("ERR_NO_VALID_VIDEO_SESSION",
                 "A recorded video session has not been terminated.")
    record["status"] = "COMPLETED"
    record["completed_at"] = db.now_raw()
    record["recommendation"] = body["recommendation"]
    record["nihss_score"] = body["nihss_score"]
    db.touch(record)
    if neurologist["on_call_state"] == "IN_CONSULT":
        neurologist["on_call_state"] = "ON_CALL"
    neurologist["last_consult_completed_at"] = db.now_raw()
    neurologist["completed_consult_count"] = neurologist["completed_consult_count"] + 1
    db.touch(neurologist)
    derive.recompute_neurologist_active_count(neurologist)
    agreement = db.get("agreements", record["agreement_id"])
    if agreement is not None:
        derive.recompute_agreement_active_count(agreement)
    return resp.object_response(record)
