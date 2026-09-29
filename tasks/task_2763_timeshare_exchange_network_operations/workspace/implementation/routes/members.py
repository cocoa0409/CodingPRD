"""Member enrollment, dues, tier moves and the ledger views."""

from flask import Blueprint

import shapes
from authz import authenticate, require_acting_identity, require_owner
from errors import ApiError
from response import object_response
from routes.common import ENUM, FK, TEXT, listing, one, read
from services import ledger
from services import requests as request_service
from store import (db, parse_date, serialize, touch, ACTIVE_REQUEST_STATUSES,
                   ENROLLMENT_STATUSES, ENTRY_TYPES, RELATED_ENTITY_TYPES)

bp = Blueprint("members", __name__)

ALL_ROLES = ["Member", "ResortManager", "NetworkOperator", "DisputeAnalyst"]

MEMBER_TRANSITIONS = {
    "PENDING_PAYMENT": [],
    "ACTIVE": ["SUSPENDED"],
    "LAPSED": ["SUSPENDED", "CANCELLED"],
    "SUSPENDED": ["ACTIVE", "CANCELLED"],
    "CANCELLED": [],
}


@bp.route("/members", methods=["POST"])
def create_member():
    caller = authenticate(["NetworkOperator"])
    payload = shapes.body()
    email = shapes.take_string(payload, "email", min_len=1, max_len=320)
    if "@" not in email:
        shapes.bad()
    full_name = shapes.take_string(payload, "full_name", min_len=1, max_len=120)
    tier_id = shapes.take_id(payload, "tier_id")
    home_resort_id = shapes.take_id(payload, "home_resort_id", required=False)
    require_acting_identity(caller)
    tier = shapes.find_tier(tier_id)
    home_resort = shapes.find_resort(home_resort_id) if home_resort_id else None
    for existing in db.members.values():
        if existing["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email must be unique across all members.")
    row = db.new_row({
        "email": email,
        "full_name": full_name,
        "tier_id": tier["id"],
        "home_resort_id": home_resort["id"] if home_resort else None,
        "enrollment_status": "PENDING_PAYMENT",
        "dues_paid_through": None,
        "trading_power_balance": 0,
        "wallet_credit_cents": 0,
        "active_request_count": 0,
    })
    db.members[row["id"]] = row
    return object_response(serialize(row), 201)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    read(ALL_ROLES)
    return one(shapes.find_member(member_id))


@bp.route("/members", methods=["GET"])
def list_members():
    return listing(["NetworkOperator", "DisputeAnalyst"], db.members, [
        ("tier_id", "tier_id", FK, shapes.find_tier),
        ("home_resort_id", "home_resort_id", FK, shapes.find_resort),
        ("enrollment_status", "enrollment_status", ENUM, ENROLLMENT_STATUSES),
    ])


@bp.route("/members/<member_id>/dues-payments", methods=["POST"])
def pay_dues(member_id):
    caller = authenticate(["Member", "NetworkOperator"])
    payload = shapes.body()
    amount_cents = shapes.take_int(payload, "amount_cents", minimum=0)
    paid_through_date = shapes.take_date(payload, "paid_through_date")
    expected_version = shapes.take_int(payload, "expected_member_version")
    require_acting_identity(caller)
    member = shapes.find_member(member_id)
    require_owner(caller, member["id"])
    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if member["enrollment_status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if member["enrollment_status"] == "LAPSED":
        if parse_date(paid_through_date) < db.today():
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
    tier = db.membership_tiers[member["tier_id"]]
    if amount_cents < tier["annual_dues_cents"]:
        raise ApiError("ERR_INSUFFICIENT_DUES_PAYMENT")
    member["dues_paid_through"] = paid_through_date
    if member["enrollment_status"] in ("PENDING_PAYMENT", "LAPSED"):
        member["enrollment_status"] = "ACTIVE"
    ledger.move_cash(member, "DUES_PAYMENT", "MEMBER", member["id"],
                     "Annual dues payment; the excess over dues becomes wallet credit.",
                     amount_cents - tier["annual_dues_cents"])
    touch(member)
    return one(member)


@bp.route("/members/<member_id>/status-changes", methods=["POST"])
def change_member_status(member_id):
    caller = authenticate(["NetworkOperator"])
    payload = shapes.body()
    to_status = shapes.take_enum(payload, "to_status", ENROLLMENT_STATUSES)
    shapes.take_string(payload, "reason", required=False)
    require_acting_identity(caller)
    member = shapes.find_member(member_id)
    if to_status not in MEMBER_TRANSITIONS[member["enrollment_status"]]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if member["enrollment_status"] == "SUSPENDED" and to_status == "ACTIVE":
        paid_through = parse_date(member["dues_paid_through"]) if member["dues_paid_through"] else None
        if paid_through is None or paid_through < db.today():
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
    member["enrollment_status"] = to_status
    touch(member)
    if to_status == "CANCELLED":
        rows = sorted([r for r in db.exchange_requests.values()
                       if r["member_id"] == member["id"]
                       and r["status"] in ACTIVE_REQUEST_STATUSES],
                      key=lambda r: (r["created_at"], r["_seq"]))
        for request_row in rows:
            request_service.release_hold(request_row)
            request_row["status"] = "CANCELLED"
            touch(request_row)
            request_service.refund_charge(request_row, member)
        request_service.sync_active_count(member)
    return one(member)


@bp.route("/members/<member_id>/tier-changes", methods=["POST"])
def change_member_tier(member_id):
    caller = authenticate(["NetworkOperator"])
    payload = shapes.body()
    tier_id = shapes.take_id(payload, "tier_id")
    require_acting_identity(caller)
    member = shapes.find_member(member_id)
    tier = shapes.find_tier(tier_id)
    member["tier_id"] = tier["id"]
    touch(member)
    return one(member)


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------
@bp.route("/ledger-entries/<entry_id>", methods=["GET"])
def get_ledger_entry(entry_id):
    read(["Member", "NetworkOperator", "DisputeAnalyst"])
    return one(shapes.find_entry(entry_id))


@bp.route("/ledger-entries", methods=["GET"])
def list_ledger_entries():
    return listing(["Member", "NetworkOperator", "DisputeAnalyst"], db.ledger_entries, [
        ("member_id", "member_id", FK, shapes.find_member),
        ("entry_type", "entry_type", ENUM, ENTRY_TYPES),
        ("related_entity_type", "related_entity_type", ENUM, RELATED_ENTITY_TYPES),
        ("related_entity_id", "related_entity_id", TEXT, None),
    ])
