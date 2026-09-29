"""Trading-power and resort-quality disputes."""

from flask import Blueprint

import shapes
from authz import authenticate, require_acting_identity, require_owner
from errors import ApiError
from response import object_response
from routes.common import ENUM, FK, listing, one, read
from services import deposits as deposit_service
from services import ledger
from services import resorts as resort_service
from store import (db, parse_instant, serialize, touch, COUNTED_DEPOSIT_STATUSES,
                   DISPUTE_STATUSES, MAX_DISPUTE_ROUNDS, SUBJECT_TYPES)

bp = Blueprint("disputes", __name__)

ALL_ROLES = ["Member", "ResortManager", "NetworkOperator", "DisputeAnalyst"]
OUTCOMES = ["UPHELD", "DENIED"]


@bp.route("/disputes", methods=["POST"])
def create_dispute():
    caller = authenticate(["Member"])
    payload = shapes.body()
    member_id = shapes.take_id(payload, "member_id")
    subject_type = shapes.take_enum(payload, "subject_type", SUBJECT_TYPES)
    narrative = shapes.take_string(payload, "narrative", min_len=1, max_len=2000)
    deposit_id = shapes.take_id(payload, "deposit_id", required=False)
    resort_id = shapes.take_id(payload, "resort_id", required=False)
    confirmation_id = shapes.take_id(payload, "confirmation_id", required=False)
    require_acting_identity(caller)
    member = shapes.find_member(member_id)
    deposit = shapes.find_deposit(deposit_id) if deposit_id else None
    resort = shapes.find_resort(resort_id) if resort_id else None
    confirmation = shapes.find_confirmation(confirmation_id) if confirmation_id else None
    require_owner(caller, member["id"])
    if deposit is not None:
        require_owner(caller, deposit["member_id"])
    if confirmation is not None:
        stay_request = db.exchange_requests[confirmation["exchange_request_id"]]
        require_owner(caller, stay_request["member_id"])
    if member["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    if subject_type == "RESORT_QUALITY" and confirmation is not None:
        if confirmation["status"] != "COMPLETED":
            raise ApiError("ERR_STAY_NOT_COMPLETED")
    if subject_type == "TRADING_POWER":
        if deposit is None or resort is not None or confirmation is not None:
            raise ApiError("ERR_DISPUTE_SUBJECT_MISMATCH")
    else:
        if deposit is not None or resort is None or confirmation is None:
            raise ApiError("ERR_DISPUTE_SUBJECT_MISMATCH")
        awarded = db.deposits[confirmation["awarded_deposit_id"]]
        if awarded["resort_id"] != resort["id"]:
            raise ApiError("ERR_DISPUTE_SUBJECT_MISMATCH")
    row = db.new_row({
        "member_id": member["id"],
        "subject_type": subject_type,
        "deposit_id": deposit["id"] if deposit is not None else None,
        "resort_id": resort["id"] if resort is not None else None,
        "confirmation_id": confirmation["id"] if confirmation is not None else None,
        "narrative": narrative,
        "status": "OPEN",
        "round_count": 0,
        "granted_power_adjustment": 0,
        "resolution_note": None,
    })
    db.disputes[row["id"]] = row
    return object_response(serialize(row), 201)


@bp.route("/disputes/<dispute_id>", methods=["GET"])
def get_dispute(dispute_id):
    read(ALL_ROLES)
    return one(shapes.find_dispute(dispute_id))


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    return listing(["Member", "NetworkOperator", "DisputeAnalyst"], db.disputes, [
        ("member_id", "member_id", FK, shapes.find_member),
        ("subject_type", "subject_type", ENUM, SUBJECT_TYPES),
        ("deposit_id", "deposit_id", FK, shapes.find_deposit),
        ("resort_id", "resort_id", FK, shapes.find_resort),
        ("confirmation_id", "confirmation_id", FK, shapes.find_confirmation),
        ("status", "status", ENUM, DISPUTE_STATUSES),
    ])


@bp.route("/disputes/<dispute_id>/review", methods=["POST"])
def review_dispute(dispute_id):
    caller = authenticate(["DisputeAnalyst"])
    shapes.body()
    require_acting_identity(caller)
    dispute = shapes.find_dispute(dispute_id)
    if dispute["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    dispute["status"] = "UNDER_REVIEW"
    touch(dispute)
    return one(dispute)


@bp.route("/disputes/<dispute_id>/info-requests", methods=["POST"])
def request_dispute_info(dispute_id):
    caller = authenticate(["DisputeAnalyst"])
    payload = shapes.body()
    shapes.take_string(payload, "question", min_len=1, max_len=2000)
    require_acting_identity(caller)
    dispute = shapes.find_dispute(dispute_id)
    if dispute["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if dispute["round_count"] >= MAX_DISPUTE_ROUNDS:
        raise ApiError("ERR_DISPUTE_ROUND_LIMIT")
    dispute["round_count"] = dispute["round_count"] + 1
    dispute["status"] = "INFO_REQUESTED"
    touch(dispute)
    return one(dispute)


@bp.route("/disputes/<dispute_id>/responses", methods=["POST"])
def respond_to_dispute(dispute_id):
    caller = authenticate(["Member"])
    payload = shapes.body()
    shapes.take_string(payload, "answer", min_len=1, max_len=2000)
    require_acting_identity(caller)
    dispute = shapes.find_dispute(dispute_id)
    require_owner(caller, dispute["member_id"])
    if dispute["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    dispute["status"] = "UNDER_REVIEW"
    touch(dispute)
    return one(dispute)


@bp.route("/disputes/<dispute_id>/resolution", methods=["POST"])
def resolve_dispute(dispute_id):
    caller = authenticate(["DisputeAnalyst"])
    payload = shapes.body()
    outcome = shapes.take_enum(payload, "outcome", OUTCOMES)
    resolution_note = shapes.take_string(payload, "resolution_note", min_len=1, max_len=2000)
    granted = shapes.take_int(payload, "granted_power_adjustment", required=False,
                             minimum=0, default=0)
    require_acting_identity(caller)
    dispute = shapes.find_dispute(dispute_id)
    if dispute["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if outcome == "UPHELD" and dispute["subject_type"] == "TRADING_POWER":
        deposit = db.deposits[dispute["deposit_id"]]
        if (deposit["deposit_status"] not in COUNTED_DEPOSIT_STATUSES
                or parse_instant(deposit["expires_at"]) <= db.now()):
            raise ApiError("ERR_DEPOSIT_EXPIRED")
    dispute["resolution_note"] = resolution_note
    if outcome == "DENIED":
        dispute["status"] = "RESOLVED_DENIED"
        touch(dispute)
        return one(dispute)
    dispute["status"] = "RESOLVED_UPHELD"
    if dispute["subject_type"] == "TRADING_POWER":
        deposit = db.deposits[dispute["deposit_id"]]
        dispute["granted_power_adjustment"] = granted
        deposit["awarded_power"] = deposit["awarded_power"] + granted
        deposit_service.sync_remaining(deposit)
        touch(deposit)
        owner = db.members[deposit["member_id"]]
        ledger.credit_power(owner, "DISPUTE_POWER_GRANT", "DISPUTE", dispute["id"],
                            "Trading power granted by an upheld valuation dispute.", granted)
    else:
        resort = db.resorts[dispute["resort_id"]]
        resort_service.apply_complaint_strike(resort)
    touch(dispute)
    return one(dispute)


@bp.route("/disputes/<dispute_id>/withdrawal", methods=["POST"])
def withdraw_dispute(dispute_id):
    caller = authenticate(["Member"])
    shapes.body()
    require_acting_identity(caller)
    dispute = shapes.find_dispute(dispute_id)
    require_owner(caller, dispute["member_id"])
    if dispute["status"] not in ("OPEN", "UNDER_REVIEW", "INFO_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    dispute["status"] = "WITHDRAWN"
    touch(dispute)
    return one(dispute)
