"""LeaseOffer endpoints and lease award (PRD section 3.3)."""
from flask import Blueprint, request

from cascade import sync_building
from dates import parse_iso_dt
from envelope import success
from errors import ApiError
from middleware import (ALL_ROLES, body, is_int, paginate, require_auth)
from store import DB, bump, make_entity, now_dt, now_str, pub, sorted_items

bp = Blueprint("offers", __name__)


def _get_offer(oid):
    o = DB["offers"].get(oid)
    if not o:
        raise ApiError("ERR_NOT_FOUND", 404, "LeaseOffer not found")
    return o


@bp.route("/leasing/space-requirements/<rid>/offers", methods=["POST"])
def create_offer(rid):
    require_auth(["LessorRep"])
    # priority 4: path id first, then body building_id
    r = DB["requirements"].get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND", 404, "SpaceRequirement not found")
    b = body()
    building_id = b.get("building_id")
    if building_id is not None and building_id not in DB["buildings"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Building not found")
    # priority 5: shape and field domains
    if not isinstance(building_id, str) or building_id == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "building_id is required")
    if not isinstance(b.get("lessor_name"), str) or b["lessor_name"] == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "lessor_name is required")
    if not is_int(b.get("shell_rate_per_sf_yr_cents")) or b["shell_rate_per_sf_yr_cents"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "shell_rate_per_sf_yr_cents must be > 0")
    if not is_int(b.get("operating_rate_per_sf_yr_cents")) or b["operating_rate_per_sf_yr_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "operating_rate_per_sf_yr_cents must be >= 0")
    if not is_int(b.get("base_year_tax_per_sf_yr_cents")) or b["base_year_tax_per_sf_yr_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "base_year_tax_per_sf_yr_cents must be >= 0")
    if b.get("escalation_method") not in ("BASE_YEAR_STOP", "CPI_INDEXED"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "escalation_method must be BASE_YEAR_STOP or CPI_INDEXED")
    if not is_int(b.get("ti_allowance_per_sf_cents")) or b["ti_allowance_per_sf_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "ti_allowance_per_sf_cents must be >= 0")
    if not is_int(b.get("free_rent_months")) or not (0 <= b["free_rent_months"] <= 24):
        raise ApiError("ERR_INVALID_REQUEST", 400, "free_rent_months must be within 0..24")
    if not is_int(b.get("term_years")) or not (5 <= b["term_years"] <= 20):
        raise ApiError("ERR_INVALID_REQUEST", 400, "term_years must be within 5..20")
    if parse_iso_dt(b.get("valid_until")) is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "valid_until must be an ISO8601 datetime")
    # priority 7: solicitation gate
    if r["status"] != "SOLICITING":
        raise ApiError("ERR_REQUIREMENT_NOT_SOLICITING", 409, "Offers may only be submitted against a SOLICITING requirement")
    e = make_entity()
    e.update({
        "requirement_id": rid,
        "building_id": building_id,
        "lessor_name": b["lessor_name"],
        "shell_rate_per_sf_yr_cents": b["shell_rate_per_sf_yr_cents"],
        "operating_rate_per_sf_yr_cents": b["operating_rate_per_sf_yr_cents"],
        "base_year_tax_per_sf_yr_cents": b["base_year_tax_per_sf_yr_cents"],
        "escalation_method": b["escalation_method"],
        "ti_allowance_per_sf_cents": b["ti_allowance_per_sf_cents"],
        "free_rent_months": b["free_rent_months"],
        "term_years": b["term_years"],
        "valid_until": b["valid_until"],
        "status": "SUBMITTED",
        "rejection_reason": None,
    })
    DB["offers"][e["id"]] = e
    return success(pub(e), 201)


@bp.route("/leasing/offers/<oid>", methods=["GET"])
def get_offer(oid):
    require_auth(ALL_ROLES)
    return success(pub(_get_offer(oid)))


@bp.route("/leasing/offers", methods=["GET"])
def list_offers():
    require_auth(ALL_ROLES)
    items = list(DB["offers"].values())
    for f in ("requirement_id", "building_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [o for o in items if o.get(f) == v]
    page, pagination = paginate(sorted_items(items))
    return success([pub(o) for o in page], 200, pagination)


@bp.route("/leasing/offers/<oid>/evaluate", methods=["POST"])
def evaluate_offer(oid):
    require_auth(["GSALeasingOfficer"])
    o = _get_offer(oid)
    if o["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a SUBMITTED offer can move into evaluation")
    o["status"] = "UNDER_EVALUATION"
    bump(o)
    return success(pub(o))


@bp.route("/leasing/offers/<oid>/select", methods=["POST"])
def select_offer(oid):
    require_auth(["GSALeasingOfficer"])
    o = _get_offer(oid)
    # priority 6: state-transition validity
    if o["status"] != "UNDER_EVALUATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only an UNDER_EVALUATION offer can be selected")
    r = DB["requirements"][o["requirement_id"]]
    # priority 7: cross-entity gate
    if r["status"] != "SOLICITING":
        raise ApiError("ERR_REQUIREMENT_NOT_SOLICITING", 409, "Requirement is no longer SOLICITING")
    bld = DB["buildings"][o["building_id"]]
    # priority 8: award safety
    if bld["security_capability"] < r["required_security_level"]:
        raise ApiError("ERR_SECURITY_LEVEL_INSUFFICIENT", 422, "Offered building security capability below required level")
    # priority 9: temporal
    if parse_iso_dt(o["valid_until"]) < now_dt():
        raise ApiError("ERR_OFFER_EXPIRED", 422, "Offer validity deadline has passed")
    # priority 11: capacity
    if bld["available_sf"] < r["required_usable_sf"]:
        raise ApiError("ERR_BUILDING_CAPACITY_EXCEEDED", 422, "Offered building lacks the required square footage")
    # side effects: select this offer, award requirement, reject siblings,
    # create the lease, commit building space
    o["status"] = "SELECTED"
    bump(o)
    r["status"] = "AWARDED"
    bump(r)
    for sib in DB["offers"].values():
        if (sib["requirement_id"] == r["id"] and sib["id"] != o["id"]
                and sib["status"] in ("SUBMITTED", "UNDER_EVALUATION")):
            sib["status"] = "REJECTED"
            sib["rejection_reason"] = "AUTO_NOT_SELECTED"
            bump(sib)
    lease = make_entity()
    lease.update({
        "requirement_id": r["id"],
        "building_id": o["building_id"],
        "offer_id": o["id"],
        "agency_id": r["agency_id"],
        "succeeds_lease_id": None,
        "shell_rate_per_sf_yr_cents": o["shell_rate_per_sf_yr_cents"],
        "operating_rate_per_sf_yr_cents": o["operating_rate_per_sf_yr_cents"],
        "base_year_tax_per_sf_yr_cents": o["base_year_tax_per_sf_yr_cents"],
        "escalation_method": o["escalation_method"],
        "free_rent_months": o["free_rent_months"],
        "term_months": o["term_years"] * 12,
        "leased_sf": r["required_usable_sf"],
        "ti_allowance_total_cents": o["ti_allowance_per_sf_cents"] * r["required_usable_sf"],
        "status": "AWARDED",
        "awarded_date": now_str(),
        "commencement_date": None,
        "end_date": None,
        "ti_buildout_cost_cents": None,
        "ti_amort_method": None,
        "cpi_base_index": None,
        "ti_amortized_principal_cents": None,
        "ti_schedule_monthly_cents": [],
        "tax_statements": [],
        "current_tax_per_sf_yr_cents": o["base_year_tax_per_sf_yr_cents"],
        "current_cpi_index": None,
        "executed_option": None,
    })
    DB["leases"][lease["id"]] = lease
    sync_building(bld)
    return success(pub(lease), 201)


@bp.route("/leasing/offers/<oid>/withdraw", methods=["POST"])
def withdraw_offer(oid):
    require_auth(["LessorRep"])
    o = _get_offer(oid)
    if o["status"] not in ("SUBMITTED", "UNDER_EVALUATION"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a non-terminal offer can be withdrawn")
    o["status"] = "WITHDRAWN"
    o["rejection_reason"] = "WITHDRAWN_BY_LESSOR"
    bump(o)
    return success(pub(o))
