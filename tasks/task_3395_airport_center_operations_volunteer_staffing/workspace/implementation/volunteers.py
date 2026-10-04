"""Volunteer and background-screening endpoints."""

from flask import Blueprint, request

from constants import SCREENING_VALIDITY_MONTHS, SCREENING_VERDICTS
from helpers import (
    add_months,
    authn,
    base_entity,
    body,
    bump,
    err,
    get_center,
    get_screening,
    get_volunteer,
    now,
    paginate,
    req_enum,
    req_int,
    req_str,
    require_role,
    serialize,
    success_list,
    success_object,
)
from storage import STORE

bp = Blueprint("volunteers", __name__)


@bp.route("/volunteers", methods=["POST"])
def register_volunteer():
    _, role = authn()
    require_role(role, ("Anonymous",))
    b = body()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    home_center_id = req_str(b, "home_center_id")
    get_center(home_center_id)

    vol = base_entity()
    vol.update({
        "full_name": full_name,
        "email": email,
        "home_center_id": home_center_id,
        "status": "APPLIED",
        "no_show_strikes": 0,
        "total_hours": 0,
    })
    STORE.volunteers[vol["id"]] = vol
    return success_object(serialize(vol), status=201)


@bp.route("/volunteers/<vid>", methods=["GET"])
def get_volunteer_route(vid):
    _, role = authn()
    require_role(role, ("PlatformAdmin", "CenterManager", "Volunteer"))
    vol = get_volunteer(vid)
    return success_object(serialize(vol))


@bp.route("/volunteers", methods=["GET"])
def list_volunteers():
    _, role = authn()
    require_role(role, ("PlatformAdmin", "CenterManager"))
    home_center_id = request.args.get("home_center_id")
    items = list(STORE.volunteers.values())
    if home_center_id is not None:
        items = [v for v in items if v["home_center_id"] == home_center_id]
    page, meta = paginate(items)
    return success_list(page, meta)


@bp.route("/volunteers/<vid>/screenings", methods=["POST"])
def open_screening(vid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    b = body()
    expected = req_int(b, "expected_volunteer_version")
    vol = get_volunteer(vid)

    if expected != vol["version"]:
        err("ERR_STALE_VERSION", 412, "Volunteer version has advanced; re-read before screening")

    if vol["status"] == "SCREENING":
        err("ERR_SCREENING_ALREADY_OPEN", 409, "Volunteer already has an open screening")
    if vol["status"] not in ("APPLIED", "INACTIVE", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409, "Screening may only open from APPLIED, INACTIVE or SUSPENDED")

    sc = base_entity()
    sc.update({
        "volunteer_id": vol["id"],
        "status": "SUBMITTED",
        "claimed_by_user_id": None,
        "decided_by_user_id": None,
        "expires_at": None,
    })
    STORE.screenings[sc["id"]] = sc

    vol["status"] = "SCREENING"
    bump(vol)
    return success_object(serialize(sc), status=201)


@bp.route("/volunteers/<vid>/screenings", methods=["GET"])
def list_screenings(vid):
    _, role = authn()
    require_role(role, ("PlatformAdmin", "CenterManager", "Volunteer"))
    vol = get_volunteer(vid)
    items = [s for s in STORE.screenings.values() if s["volunteer_id"] == vol["id"]]
    page, meta = paginate(items)
    return success_list(page, meta)


@bp.route("/screenings/<sid>/claim", methods=["POST"])
def claim_screening(sid):
    uid, role = authn()
    require_role(role, ("CenterManager",))
    sc = get_screening(sid)
    if sc["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Only a SUBMITTED screening can be claimed")
    sc["status"] = "IN_REVIEW"
    sc["claimed_by_user_id"] = uid
    bump(sc)
    return success_object(serialize(sc))


@bp.route("/screenings/<sid>/decide", methods=["POST"])
def decide_screening(sid):
    uid, role = authn()
    require_role(role, ("CenterManager",))
    b = body()
    verdict = req_enum(b, "verdict", SCREENING_VERDICTS)
    sc = get_screening(sid)
    if sc["status"] != "IN_REVIEW":
        err("ERR_INVALID_STATE", 409, "Only an IN_REVIEW screening can be decided")
    if uid == sc["claimed_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 409, "Decider must differ from the claimer")

    sc["decided_by_user_id"] = uid
    vol = STORE.volunteers.get(sc["volunteer_id"])
    if verdict == "CLEARED":
        sc["status"] = "CLEARED"
        sc["expires_at"] = add_months(now(), SCREENING_VALIDITY_MONTHS)
        if vol is not None and vol["status"] == "SCREENING":
            vol["status"] = "CLEARED"
            bump(vol)
    else:
        sc["status"] = "REJECTED"
        if vol is not None and vol["status"] == "SCREENING":
            vol["status"] = "APPLIED"
            bump(vol)
    bump(sc)
    return success_object(serialize(sc))
