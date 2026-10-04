"""Guest registration/eligibility and visit check-in endpoints."""

from flask import Blueprint, request

from constants import GUEST_CATEGORIES
from helpers import (
    authn,
    base_entity,
    body,
    bump,
    err,
    get_center,
    get_checkin,
    get_guest,
    now,
    paginate,
    req_date,
    req_enum,
    req_str,
    require_role,
    serialize,
    success_list,
    success_object,
    today,
)
from storage import STORE

bp = Blueprint("guests", __name__)


def enforce_eligibility(guest):
    """Lazy expiry: flips the guest EXPIRED on the spot when verification lapsed."""
    if guest["eligibility_status"] == "ELIGIBLE":
        exp = _date_of(guest["verification_expires_on"])
        if exp < today():
            guest["eligibility_status"] = "EXPIRED"
            bump(guest)
    if guest["eligibility_status"] != "ELIGIBLE":
        err("ERR_GUEST_INELIGIBLE", 403, "Guest eligibility has expired")


def _date_of(s):
    from datetime import date
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


@bp.route("/guests", methods=["POST"])
def register_guest():
    _, role = authn()
    require_role(role, ("Anonymous",))
    b = body()
    full_name = req_str(b, "full_name")
    category = req_enum(b, "category", GUEST_CATEGORIES)
    # A past verification_expires_on is accepted at registration (lazy expiry).
    expires = req_date(b, "verification_expires_on")

    guest = base_entity()
    guest.update({
        "full_name": full_name,
        "category": category,
        "verification_expires_on": expires.isoformat(),
        "eligibility_status": "ELIGIBLE",
    })
    STORE.guests[guest["id"]] = guest
    return success_object(serialize(guest), status=201)


@bp.route("/guests/<gid>", methods=["GET"])
def get_guest_route(gid):
    _, role = authn()
    require_role(role, ("PlatformAdmin", "CenterManager", "Guest"))
    guest = get_guest(gid)
    return success_object(serialize(guest))


@bp.route("/guests/<gid>/reverify", methods=["POST"])
def reverify_guest(gid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    b = body()
    new_expiry = req_date(b, "verification_expires_on")
    guest = get_guest(gid)
    if guest["eligibility_status"] != "EXPIRED":
        err("ERR_INVALID_STATE", 409, "Only an EXPIRED guest can be reverified")
    if new_expiry < today():
        err("ERR_VALIDATION", 400, "verification_expires_on must be on or after the current date")
    guest["verification_expires_on"] = new_expiry.isoformat()
    guest["eligibility_status"] = "ELIGIBLE"
    bump(guest)
    return success_object(serialize(guest))


@bp.route("/centers/<cid>/check-ins", methods=["POST"])
def create_checkin(cid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    b = body()
    guest_id = req_str(b, "guest_id")
    center = get_center(cid)
    guest = get_guest(guest_id)

    if center["posture"] == "CLOSED":
        err("ERR_CENTER_CLOSED", 409, "Center posture is CLOSED")

    for ci in STORE.checkins.values():
        if ci["center_id"] == cid and ci["guest_id"] == guest["id"] and ci["status"] == "CHECKED_IN":
            err("ERR_ALREADY_CHECKED_IN", 409, "Guest already checked in at this center")

    enforce_eligibility(guest)

    if center["current_occupancy"] >= center["occupancy_cap"]:
        err("ERR_CENTER_AT_CAPACITY", 409, "Center is at occupancy capacity")

    ci = base_entity()
    ci.update({
        "center_id": center["id"],
        "guest_id": guest["id"],
        "checked_in_at": now(),
        "checked_out_at": None,
        "status": "CHECKED_IN",
    })
    STORE.checkins[ci["id"]] = ci

    center["current_occupancy"] += 1
    bump(center)
    return success_object(serialize(ci), status=201)


@bp.route("/check-ins/<cid>", methods=["GET"])
def get_checkin_route(cid):
    uid, role = authn()
    require_role(role, ("PlatformAdmin", "CenterManager", "Guest"))
    ci = get_checkin(cid)
    if role == "Guest" and ci["guest_id"] != uid:
        err("ERR_FORBIDDEN", 403, "Guests may only view their own check-ins")
    return success_object(serialize(ci))


@bp.route("/check-ins", methods=["GET"])
def list_checkins():
    _, role = authn()
    require_role(role, ("PlatformAdmin", "CenterManager"))
    guest_id = request.args.get("guest_id")
    center_id = request.args.get("center_id")
    items = list(STORE.checkins.values())
    if guest_id is not None:
        items = [c for c in items if c["guest_id"] == guest_id]
    if center_id is not None:
        items = [c for c in items if c["center_id"] == center_id]
    page, meta = paginate(items)
    return success_list(page, meta)
