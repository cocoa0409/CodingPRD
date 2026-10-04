"""Site agreement endpoints: draft, list, activate (OCC + supersede), renew."""

from flask import Blueprint

from helpers import (
    authn,
    base_entity,
    body,
    bump,
    err,
    get_agreement,
    get_center,
    paginate,
    req_bool,
    req_date,
    req_int,
    req_str,
    require_role,
    serialize,
    success_list,
    success_object,
    validation,
)
from services import recompute_center
from storage import STORE

bp = Blueprint("agreements", __name__)

READ_ROLES = ("PlatformAdmin", "CenterManager", "Volunteer", "Guest")


@bp.route("/centers/<cid>/site-agreements", methods=["POST"])
def draft_agreement(cid):
    _, role = authn()
    require_role(role, ("PlatformAdmin",))
    b = body()
    sqft = req_int(b, "facility_space_sqft", minimum=1)
    utilities = req_bool(b, "utilities_included")
    access_terms = req_str(b, "access_terms")
    security_level = req_int(b, "security_level", minimum=1, maximum=5)
    start_date = req_date(b, "start_date")
    end_date = req_date(b, "end_date")
    if start_date > end_date:
        validation("start_date must not be later than end_date")
    center = get_center(cid)

    ag = base_entity()
    ag.update({
        "center_id": center["id"],
        "facility_space_sqft": sqft,
        "utilities_included": utilities,
        "access_terms": access_terms,
        "security_level": security_level,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "status": "SUBMITTED",
    })
    STORE.agreements[ag["id"]] = ag
    return success_object(serialize(ag), status=201)


@bp.route("/centers/<cid>/site-agreements", methods=["GET"])
def list_agreements(cid):
    _, role = authn()
    require_role(role, READ_ROLES)
    center = get_center(cid)
    items = [a for a in STORE.agreements.values() if a["center_id"] == center["id"]]
    page, meta = paginate(items)
    return success_list(page, meta)


@bp.route("/site-agreements/<aid>/activate", methods=["POST"])
def activate_agreement(aid):
    _, role = authn()
    require_role(role, ("PlatformAdmin",))
    b = body()
    expected = req_int(b, "expected_center_version")
    ag = get_agreement(aid)
    center = get_center(ag["center_id"])

    if expected != center["version"]:
        err("ERR_STALE_VERSION", 412, "Center version has advanced; re-read before activating")

    if ag["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Only a SUBMITTED agreement can be activated")

    # Date ordering re-verified at activation time (PRD 3.1).
    if ag["start_date"] > ag["end_date"]:
        validation("start_date must not be later than end_date")

    # Supersede: any other ACTIVE agreement of the same center -> TERMINATED.
    for other in STORE.agreements.values():
        if other["center_id"] == center["id"] and other["id"] != ag["id"] and other["status"] == "ACTIVE":
            other["status"] = "TERMINATED"
            bump(other)

    ag["status"] = "ACTIVE"
    bump(ag)
    center["active_agreement_id"] = ag["id"]
    recompute_center(center)  # stores posture/coverage; bumps center version once
    return success_object(serialize(ag))


@bp.route("/site-agreements/<aid>/renew", methods=["POST"])
def renew_agreement(aid):
    _, role = authn()
    require_role(role, ("PlatformAdmin",))
    b = body()
    new_end = req_date(b, "new_end_date")
    ag = get_agreement(aid)
    center = get_center(ag["center_id"])

    if ag["status"] != "RENEWAL_DUE":
        err("ERR_RENEWAL_WINDOW_NOT_OPEN", 409, "Agreement is not in its renewal window")
    if new_end.isoformat() <= ag["end_date"]:
        validation("new_end_date must be strictly later than the current end_date")

    ag["end_date"] = new_end.isoformat()
    ag["status"] = "ACTIVE"
    bump(ag)
    recompute_center(center)
    return success_object(serialize(ag))
