"""Loyalty members, their standing transitions and the points ledger."""

from flask import Blueprint

from db import db
from errors import fail
from middleware import require
from response import envelope, paginate
from services.core import (
    get_member,
    get_store,
    log_record,
    new_record,
    recompute_soft_hold,
    release_queue_units,
    touch,
)
from utils import body, list_params, matches, out, require_fields

bp = Blueprint("members", __name__)


def ledger_entries(member_id):
    return sorted([e for e in db().loyalty_ledger.values() if e["member_id"] == member_id],
                  key=lambda e: (e["created_at"], e["id"]))


@bp.route("/stores/members", methods=["POST"])
def create_member():
    require("PlatformAdmin")
    payload = body()
    require_fields(payload, "email", "display_name", "home_store_id")
    home = get_store(payload["home_store_id"])

    for existing in db().members.values():
        if existing["email"] == payload["email"]:
            fail("ERR_CONSTRAINT_VIOLATION", "A member email must be globally unique.")

    member = new_record({
        "email": payload["email"],
        "display_name": payload["display_name"],
        "tier": "STANDARD",
        "home_store_id": home["id"],
        "passed_mb_reservations": 0,
        "points_balance": 0,
        "stage": "ACTIVE",
    })
    db().members[member["id"]] = member
    return envelope(out(member), status=201)


@bp.route("/stores/members", methods=["GET"])
def list_members():
    require("PlatformAdmin", "StoreAssociate")
    params = list_params()
    items = [m for m in db().members.values() if matches(m, params, "home_store_id")]
    items.sort(key=lambda m: (m["created_at"], m["id"]))
    page, pagination = paginate(items, params)
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/members/<member_id>", methods=["GET"])
def read_member(member_id):
    require("PlatformAdmin", "StoreAssociate", "Member")
    return envelope(out(get_member(member_id)))


@bp.route("/stores/members/<member_id>", methods=["PATCH"])
def patch_member(member_id):
    require("PlatformAdmin")
    payload = body()
    member = get_member(member_id)
    if "tier" in payload and payload["tier"] is not None:
        if payload["tier"] not in ("STANDARD", "VIP"):
            fail("ERR_CONSTRAINT_VIOLATION", "tier must be STANDARD or VIP.")
        member["tier"] = payload["tier"]
    if "points_balance" in payload and payload["points_balance"] is not None:
        member["points_balance"] = int(payload["points_balance"])
    touch(member)
    return envelope(out(member))


@bp.route("/stores/members/<member_id>/suspend", methods=["POST"])
def suspend_member(member_id):
    require("StoreAssociate")
    payload = body()
    member = get_member(member_id)

    if member["stage"] not in ("ACTIVE", "RESTRICTED"):
        fail("ERR_INVALID_STATE",
             "Only an active or restricted member may be suspended.")

    granted = [q for q in db().launch_queues.values()
               if q["member_id"] == member["id"] and q["status"] == "GRANTED"]
    if not granted and not payload.get("reason_code"):
        fail("ERR_INVALID_STATE",
             "Suspension requires a granted queue row or a justified reason code.")

    member["stage"] = "SUSPENDED"
    touch(member)

    for queue in db().launch_queues.values():
        if queue["member_id"] != member["id"]:
            continue
        if queue["status"] == "WAITING":
            queue["status"] = "VOIDED"
            touch(queue)
            launch = db().theme_launches.get(queue["launch_id"])
            if launch is not None:
                recompute_soft_hold(launch)
        elif queue["status"] == "GRANTED":
            release_queue_units(queue)

    return envelope(out(member))


@bp.route("/stores/members/<member_id>/reinstate", methods=["POST"])
def reinstate_member(member_id):
    require("StoreAssociate")
    member = get_member(member_id)

    home = get_store(member["home_store_id"])
    required = int(home["wall_bin_capacity_grams"]) * 0.25
    if home["bin_engine_mass_grams"] < required:
        fail("ERR_INVALID_STATE",
             "The member's home store does not hold enough live engine mass.")

    member["stage"] = "ACTIVE"
    member["passed_mb_reservations"] = 0
    touch(member)
    return envelope(out(member))


# ---------------------------------------------------------------------------
# Loyalty ledger
# ---------------------------------------------------------------------------
@bp.route("/stores/loyalty-ledger", methods=["POST"])
def post_ledger():
    require("PlatformAdmin")
    payload = body()
    require_fields(payload, "member_id", "entry_kind", "points_delta", "reason")
    member = get_member(payload["member_id"])

    if payload["entry_kind"] not in ("REDEMPTION", "REPLACEMENT_GRANT", "MANUAL_ADJUSTMENT"):
        fail("ERR_CONSTRAINT_VIOLATION",
             "entry_kind must be REDEMPTION, REPLACEMENT_GRANT or MANUAL_ADJUSTMENT.")
    delta = int(payload["points_delta"])
    if delta == 0:
        fail("ERR_CONSTRAINT_VIOLATION", "points_delta must be non-zero.")

    entry = log_record({
        "member_id": member["id"],
        "entry_kind": payload["entry_kind"],
        "points_delta": delta,
        "reason": payload["reason"],
    })
    db().loyalty_ledger[entry["id"]] = entry
    member["points_balance"] += delta
    touch(member)
    return envelope(out(entry), status=201)


@bp.route("/stores/members/<member_id>/loyalty-ledger", methods=["GET"])
def member_ledger(member_id):
    require("PlatformAdmin", "Member")
    member = get_member(member_id)
    items = ledger_entries(member["id"])
    page, pagination = paginate(items, list_params())
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/loyalty-ledger", methods=["GET"])
def list_ledger():
    require("PlatformAdmin", "Member")
    params = list_params()
    items = [e for e in db().loyalty_ledger.values()
             if matches(e, params, "member_id", "entry_kind")]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, pagination = paginate(items, params)
    return envelope(out(page), response_type="array", pagination=pagination)