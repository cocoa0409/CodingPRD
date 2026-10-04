"""Mediation and arbitration escalation (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint

import db
import domain
import web
from constants import (
    ALL_ROLES,
    ARBITRATION_OUTCOMES,
    HEARING_ROOM_BUFFER_MINUTES,
    MEDIATION_OFFER_DEADLINE_DAYS,
    MEDIATION_OFFER_WINDOW_DAYS,
    MEDIATION_OUTCOMES,
    MEDIATION_PARTIES,
    MEDIATION_PARTY_RESPONSES,
    ROLE_BUSINESS_REP,
    ROLE_BUREAU_ADMIN,
    ROLE_CONSUMER,
)
from errors import ApiError
from routes_complaints import get_complaint_or_404, serialize_complaint  # noqa: F401

bp = Blueprint("escalation", __name__)


def get_mediation_or_404(case_id):
    case = db.STORE.mediation_cases.get(case_id)
    if case is None:
        raise ApiError("ERR_MEDIATION_NOT_FOUND")
    return case


def get_arbitration_or_404(case_id):
    case = db.STORE.arbitration_cases.get(case_id)
    if case is None:
        raise ApiError("ERR_ARBITRATION_NOT_FOUND")
    return case


def serialize_mediation(case):
    return db.serialize(case)


def serialize_arbitration(case):
    return db.serialize(case)


# ---------------------------------------------------------------------------
# POST /complaints/{id}/mediation-cases
# ---------------------------------------------------------------------------
@bp.route("/complaints/<complaint_id>/mediation-cases", methods=["POST"])
def offer_mediation(complaint_id):
    web.authz({ROLE_BUREAU_ADMIN})
    complaint = get_complaint_or_404(complaint_id)
    # priority 7: from-state (a live mediation holds the complaint in
    # MEDIATION_OFFERED / IN_MEDIATION, so the state gate itself bars a
    # second concurrent mediation)
    if complaint["status"] != "UNRESOLVED":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE")
    # priority 10: mediation window anchored to last_unresolved_at
    now = db.now()
    anchor = complaint["last_unresolved_at"]
    if anchor is None or now > anchor + timedelta(days=MEDIATION_OFFER_WINDOW_DAYS):
        raise ApiError("ERR_MEDIATION_WINDOW_EXPIRED")
    case = db.new_entity(
        "mediation_cases",
        {
            "complaint_id": complaint["id"],
            "status": "OFFERED",
            "offered_at": now,
            "offer_deadline_at": now + timedelta(days=MEDIATION_OFFER_DEADLINE_DAYS),
            "business_response": "PENDING",
            "consumer_response": "PENDING",
            "mediator_id": None,
            "session_start_at": None,
            "session_end_at": None,
        },
    )
    complaint["status"] = "MEDIATION_OFFERED"
    db.touch(complaint)
    return web.success_object(serialize_mediation(case), status=201)


# ---------------------------------------------------------------------------
# GET /complaints/{id}/mediation-cases
# ---------------------------------------------------------------------------
@bp.route("/complaints/<complaint_id>/mediation-cases", methods=["GET"])
def list_mediation_cases(complaint_id):
    web.authz(ALL_ROLES)
    get_complaint_or_404(complaint_id)
    items = [
        c for c in db.STORE.mediation_cases.values()
        if c["complaint_id"] == complaint_id
    ]
    return web.paginated_entities(items, serialize_mediation)


# ---------------------------------------------------------------------------
# POST /mediation-cases/{id}/party-response
# ---------------------------------------------------------------------------
@bp.route("/mediation-cases/<case_id>/party-response", methods=["POST"])
def mediation_party_response(case_id):
    user_id, role = web.authz({ROLE_BUSINESS_REP, ROLE_CONSUMER})
    case = get_mediation_or_404(case_id)
    data = web.body()
    # priority 5: schema
    party = web.require_enum(data, "party", MEDIATION_PARTIES)
    response = web.require_enum(data, "response", MEDIATION_PARTY_RESPONSES)
    # party-level authorization
    if party == "BUSINESS" and role != ROLE_BUSINESS_REP:
        raise ApiError("ERR_UNAUTHORIZED")
    if party == "CONSUMER" and role != ROLE_CONSUMER:
        raise ApiError("ERR_UNAUTHORIZED")
    complaint = get_complaint_or_404(case["complaint_id"])
    # priority 3: ownership — each party answers only its own side
    if party == "BUSINESS" and user_id != complaint["business_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    if party == "CONSUMER" and user_id != complaint["consumer_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    # priority 7: the case must be OFFERED and this side still PENDING
    if case["status"] != "OFFERED":
        raise ApiError("ERR_MEDIATION_INVALID_STATE")
    field = "business_response" if party == "BUSINESS" else "consumer_response"
    if case[field] != "PENDING":
        raise ApiError("ERR_MEDIATION_INVALID_STATE")
    case[field] = response

    if case["business_response"] == "DECLINED" or case["consumer_response"] == "DECLINED":
        # any decline ends the offer; the complaint falls back to UNRESOLVED
        # and last_unresolved_at is deliberately NOT refreshed
        case["status"] = "DECLINED"
        db.touch(case)
        complaint["status"] = "UNRESOLVED"
        db.touch(complaint)
    elif case["business_response"] == "ACCEPTED" and case["consumer_response"] == "ACCEPTED":
        case["status"] = "ACCEPTED"
        db.touch(case)
        complaint["status"] = "IN_MEDIATION"
        db.touch(complaint)
    else:
        # one party answered, the other still pending: stays OFFERED
        db.touch(case)
    return web.success_object(serialize_mediation(case), status=200)


# ---------------------------------------------------------------------------
# POST /mediation-cases/{id}/schedule
# ---------------------------------------------------------------------------
@bp.route("/mediation-cases/<case_id>/schedule", methods=["POST"])
def schedule_mediation(case_id):
    web.authz({ROLE_BUREAU_ADMIN})
    case = get_mediation_or_404(case_id)
    data = web.body()
    # priority 5: schema — end strictly after start
    mediator_id = web.require_string(data, "mediator_id")
    session_start = web.require_datetime(data, "session_start_at")
    session_end = web.require_datetime(data, "session_end_at")
    if session_end <= session_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "session_end_at must be strictly after session_start_at"
        )
    # priority 7: from-state
    if case["status"] != "ACCEPTED":
        raise ApiError("ERR_MEDIATION_INVALID_STATE")
    # priority 12: mediator half-open [start, end) overlap on SCHEDULED cases;
    # back-to-back adjacency (end == other start) does NOT conflict
    for other in db.STORE.mediation_cases.values():
        if other["id"] == case["id"]:
            continue
        if other["status"] != "SCHEDULED":
            continue
        if other["mediator_id"] != mediator_id:
            continue
        other_start = other["session_start_at"]
        other_end = other["session_end_at"]
        if session_start < other_end and other_start < session_end:
            raise ApiError("ERR_MEDIATOR_SCHEDULE_CONFLICT")
    case["mediator_id"] = mediator_id
    case["session_start_at"] = session_start
    case["session_end_at"] = session_end
    case["status"] = "SCHEDULED"
    db.touch(case)
    return web.success_object(serialize_mediation(case), status=200)


# ---------------------------------------------------------------------------
# POST /mediation-cases/{id}/conclude
# ---------------------------------------------------------------------------
@bp.route("/mediation-cases/<case_id>/conclude", methods=["POST"])
def conclude_mediation(case_id):
    web.authz({ROLE_BUREAU_ADMIN})
    case = get_mediation_or_404(case_id)
    data = web.body()
    outcome = web.require_enum(data, "outcome", MEDIATION_OUTCOMES)
    if case["status"] != "SCHEDULED":
        raise ApiError("ERR_MEDIATION_INVALID_STATE")
    complaint = get_complaint_or_404(case["complaint_id"])
    business = db.STORE.businesses.get(complaint["business_id"])
    now = db.now()
    if outcome == "AGREEMENT":
        case["status"] = "CONCLUDED_AGREEMENT"
        complaint["status"] = "MEDIATION_RESOLVED"
        complaint["resolution_outcome"] = "MEDIATION_AGREEMENT"
        complaint["closed_at"] = now
    else:
        case["status"] = "CONCLUDED_NO_AGREEMENT"
        complaint["status"] = "MEDIATION_FAILED"
        complaint["resolution_outcome"] = "MEDIATION_NO_AGREEMENT"
    db.touch(case)
    db.touch(complaint)
    if business is not None:
        domain.regenerate_provisional(business)
    return web.success_object(serialize_mediation(case), status=200)


# ---------------------------------------------------------------------------
# POST /complaints/{id}/arbitration-cases
# ---------------------------------------------------------------------------
@bp.route("/complaints/<complaint_id>/arbitration-cases", methods=["POST"])
def file_arbitration(complaint_id):
    web.authz({ROLE_BUREAU_ADMIN})
    complaint = get_complaint_or_404(complaint_id)
    # priority 7: only a MEDIATION_FAILED complaint is arbitrable (a live
    # arbitration holds the complaint in IN_ARBITRATION, so the state gate
    # itself bars a second concurrent arbitration)
    if complaint["status"] != "MEDIATION_FAILED":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE")
    # informational lineage: the latest CONCLUDED_NO_AGREEMENT mediation case
    failed = [
        c
        for c in db.STORE.mediation_cases.values()
        if c["complaint_id"] == complaint_id and c["status"] == "CONCLUDED_NO_AGREEMENT"
    ]
    source_id = None
    if failed:
        source_id = max(failed, key=lambda c: (c["created_at"], c["_seq"]))["id"]
    case = db.new_entity(
        "arbitration_cases",
        {
            "complaint_id": complaint["id"],
            "source_mediation_case_id": source_id,
            "status": "FILED",
            "hearing_room_id": None,
            "hearing_start_at": None,
            "hearing_end_at": None,
            "outcome": None,
            "decided_at": None,
        },
    )
    complaint["status"] = "IN_ARBITRATION"
    db.touch(complaint)
    return web.success_object(serialize_arbitration(case), status=201)


# ---------------------------------------------------------------------------
# GET /complaints/{id}/arbitration-cases
# ---------------------------------------------------------------------------
@bp.route("/complaints/<complaint_id>/arbitration-cases", methods=["GET"])
def list_arbitration_cases(complaint_id):
    web.authz(ALL_ROLES)
    get_complaint_or_404(complaint_id)
    items = [
        c for c in db.STORE.arbitration_cases.values()
        if c["complaint_id"] == complaint_id
    ]
    return web.paginated_entities(items, serialize_arbitration)


# ---------------------------------------------------------------------------
# POST /arbitration-cases/{id}/schedule-hearing
# ---------------------------------------------------------------------------
@bp.route("/arbitration-cases/<case_id>/schedule-hearing", methods=["POST"])
def schedule_hearing(case_id):
    web.authz({ROLE_BUREAU_ADMIN})
    case = get_arbitration_or_404(case_id)
    data = web.body()
    # priority 5: schema — end strictly after start
    room_id = web.require_string(data, "hearing_room_id")
    hearing_start = web.require_datetime(data, "hearing_start_at")
    hearing_end = web.require_datetime(data, "hearing_end_at")
    if hearing_end <= hearing_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "hearing_end_at must be strictly after hearing_start_at"
        )
    # priority 7: from-state
    if case["status"] != "FILED":
        raise ApiError("ERR_ARBITRATION_INVALID_STATE")
    # priority 12: same-room hearings need a 30-minute buffer on both sides;
    # unlike mediation, adjacency IS a conflict
    buffer = timedelta(minutes=HEARING_ROOM_BUFFER_MINUTES)
    for other in db.STORE.arbitration_cases.values():
        if other["id"] == case["id"]:
            continue
        if other["status"] != "HEARING_SCHEDULED":
            continue
        if other["hearing_room_id"] != room_id:
            continue
        if hearing_start >= other["hearing_end_at"] + buffer:
            continue
        if hearing_end + buffer <= other["hearing_start_at"]:
            continue
        raise ApiError("ERR_HEARING_ROOM_CONFLICT")
    case["hearing_room_id"] = room_id
    case["hearing_start_at"] = hearing_start
    case["hearing_end_at"] = hearing_end
    case["status"] = "HEARING_SCHEDULED"
    db.touch(case)
    return web.success_object(serialize_arbitration(case), status=200)


# ---------------------------------------------------------------------------
# POST /arbitration-cases/{id}/render-decision
# ---------------------------------------------------------------------------
@bp.route("/arbitration-cases/<case_id>/render-decision", methods=["POST"])
def render_decision(case_id):
    web.authz({ROLE_BUREAU_ADMIN})
    case = get_arbitration_or_404(case_id)
    data = web.body()
    outcome = web.require_enum(data, "outcome", ARBITRATION_OUTCOMES)
    if case["status"] != "HEARING_SCHEDULED":
        raise ApiError("ERR_ARBITRATION_INVALID_STATE")
    complaint = get_complaint_or_404(case["complaint_id"])
    business = db.STORE.businesses.get(complaint["business_id"])
    now = db.now()
    case["outcome"] = outcome
    case["decided_at"] = now
    case["status"] = "DECIDED"
    db.touch(case)
    complaint["status"] = "ARBITRATED"
    complaint["resolution_outcome"] = (
        "ARBITRATION_ADVERSE" if outcome == "ADVERSE_TO_BUSINESS" else "ARBITRATION_NO_FAULT"
    )
    complaint["closed_at"] = now
    db.touch(complaint)
    if business is not None:
        domain.regenerate_provisional(business)
    return web.success_object(serialize_arbitration(case), status=200)
