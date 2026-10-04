"""ExpirationPlan endpoints (PRD section 3.9)."""
from flask import Blueprint

from calc import score_options
from cascade import sync_building
from dates import parse_date, whole_months_between
from envelope import success
from errors import ApiError
from middleware import (ALL_ROLES, body, is_int, paginate, require_auth)
from store import DB, bump, make_entity, now_dt, now_str, pub, sorted_items

bp = Blueprint("plans", __name__)

COST_KEYS = (
    "succeeding_shell_rate", "succeeding_operating_rate", "succeeding_term_years",
    "relocation_move_cost_cents", "relocation_downtime_cost_cents",
    "market_shell_rate", "market_operating_rate",
    "construction_cost_cents", "construction_operating_rate",
)

OPTIONS = ("SUCCEEDING_LEASE", "RELOCATION", "REPLACEMENT_CONSTRUCTION")


def _get_plan(pid):
    p = DB["plans"].get(pid)
    if not p:
        raise ApiError("ERR_NOT_FOUND", 404, "ExpirationPlan not found")
    return p


@bp.route("/leasing/leases/<lid>/expiration-plans", methods=["POST"])
def create_plan(lid):
    require_auth(["GSALeasingOfficer"])
    l = DB["leases"].get(lid)
    if not l:
        raise ApiError("ERR_NOT_FOUND", 404, "Lease not found")
    # priority 6: plan may be opened only on a COMMENCED or EXPIRING lease
    if l["status"] not in ("COMMENCED", "EXPIRING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "An expiration plan requires a COMMENCED or EXPIRING lease")
    # priority 11: at most one non-terminal plan per lease
    for p in DB["plans"].values():
        if p["lease_id"] == lid and p["status"] in ("OPEN", "OPTION_SELECTED"):
            raise ApiError("ERR_PLAN_ALREADY_OPEN", 409, "The lease already has a plan in OPEN or OPTION_SELECTED")
    e = make_entity()
    e.update({
        "lease_id": lid,
        "status": "OPEN",
        "selected_option": None,
        "option_costs": [],
        "recommended_option": None,
        "cost_params": None,
        "outcome_lease_id": None,
        "outcome_requirement_id": None,
        "outcome_building_id": None,
        "executed_at": None,
    })
    DB["plans"][e["id"]] = e
    return success(pub(e), 201)


@bp.route("/leasing/leases/<lid>/expiration-plans", methods=["GET"])
def list_plans(lid):
    require_auth(ALL_ROLES)
    if lid not in DB["leases"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Lease not found")
    items = [p for p in DB["plans"].values() if p["lease_id"] == lid]
    page, pagination = paginate(sorted_items(items))
    return success([pub(p) for p in page], 200, pagination)


@bp.route("/leasing/expiration-plans/<pid>/select-option", methods=["POST"])
def select_option(pid):
    require_auth(["GSALeasingOfficer"])
    p = _get_plan(pid)
    b = body()
    # priority 5: shape
    if b.get("option") not in OPTIONS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "option must be SUCCEEDING_LEASE, RELOCATION, or REPLACEMENT_CONSTRUCTION")
    params = {}
    for k in COST_KEYS:
        if not is_int(b.get(k)) or b[k] < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, k + " must be a non-negative integer")
        params[k] = b[k]
    # priority 6: state
    if p["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only an OPEN plan can select an option")
    # priority 9: decision deadline — at least 12 whole months to lease end
    l = DB["leases"][p["lease_id"]]
    if whole_months_between(now_dt().date(), parse_date(l["end_date"])) < 12:
        raise ApiError("ERR_OPTION_DEADLINE_PASSED", 422, "Fewer than 12 whole calendar months remain to lease end")
    costs, best = score_options(params, l["leased_sf"])
    p["option_costs"] = costs
    p["recommended_option"] = best
    p["cost_params"] = params
    p["selected_option"] = b["option"]
    p["status"] = "OPTION_SELECTED"
    bump(p)
    return success(pub(p))


def _spawn_requirement(lease, plan, delivery_method):
    """Copy the headcount/sf fields of the requirement that originated the
    expiring lease into a fresh DRAFT requirement for the same agency."""
    src = DB["requirements"].get(lease["requirement_id"])
    e = make_entity()
    e.update({
        "agency_id": lease["agency_id"],
        "title": src["title"] if src else None,
        "base_headcount": src["base_headcount"] if src else None,
        "annual_growth_pct": src["annual_growth_pct"] if src else None,
        "target_occupancy_year": src["target_occupancy_year"] if src else None,
        "sf_per_person": src["sf_per_person"] if src else None,
        "special_needs": [dict(n) for n in src["special_needs"]] if src else [],
        "region_code": src["region_code"] if src else None,
        "mission_points": src["mission_points"] if src else None,
        "population_points": src["population_points"] if src else None,
        "size_points": src["size_points"] if src else None,
        "criticality_points": src["criticality_points"] if src else None,
        "status": "DRAFT",
        "projected_headcount": None,
        "required_security_level": None,
        "required_usable_sf": None,
        "survey_summary": None,
        "delivery_method": delivery_method,
        "source_plan_id": plan["id"],
    })
    DB["requirements"][e["id"]] = e
    return e


@bp.route("/leasing/expiration-plans/<pid>/execute", methods=["POST"])
def execute_plan(pid):
    require_auth(["GSALeasingOfficer"])
    p = _get_plan(pid)
    # priority 6: state
    if p["status"] != "OPTION_SELECTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only an OPTION_SELECTED plan can be executed")
    l = DB["leases"][p["lease_id"]]
    # priority 7: lease must actually be EXPIRING
    if l["status"] != "EXPIRING":
        raise ApiError("ERR_LEASE_NOT_EXPIRING", 409, "The lease is not EXPIRING")
    opt = p["selected_option"]
    cp = p["cost_params"]
    l["executed_option"] = opt
    bump(l)
    if opt == "SUCCEEDING_LEASE":
        nl = make_entity()
        nl.update({
            "requirement_id": l["requirement_id"],
            "building_id": l["building_id"],
            "offer_id": None,
            "agency_id": l["agency_id"],
            "succeeds_lease_id": l["id"],
            "shell_rate_per_sf_yr_cents": cp["succeeding_shell_rate"],
            "operating_rate_per_sf_yr_cents": cp["succeeding_operating_rate"],
            "base_year_tax_per_sf_yr_cents": l["base_year_tax_per_sf_yr_cents"],
            "escalation_method": l["escalation_method"],
            "free_rent_months": l["free_rent_months"],
            "term_months": cp["succeeding_term_years"] * 12,
            "leased_sf": l["leased_sf"],
            "ti_allowance_total_cents": 0,
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
            "current_tax_per_sf_yr_cents": l["base_year_tax_per_sf_yr_cents"],
            "current_cpi_index": None,
            "executed_option": None,
        })
        DB["leases"][nl["id"]] = nl
        p["outcome_lease_id"] = nl["id"]
        sync_building(DB["buildings"].get(l["building_id"]))
    elif opt == "RELOCATION":
        req = _spawn_requirement(l, p, "STANDARD")
        p["outcome_requirement_id"] = req["id"]
    else:  # REPLACEMENT_CONSTRUCTION
        old_b = DB["buildings"].get(l["building_id"])
        nb = make_entity()
        nb.update({
            "building_name": old_b["building_name"] if old_b else None,
            "address": old_b["address"] if old_b else None,
            "region_code": old_b["region_code"] if old_b else None,
            "ownership_type": "FEDERALLY_OWNED",
            "security_capability": old_b["security_capability"] if old_b else None,
            "total_sf": old_b["total_sf"] if old_b else None,
            "available_sf": old_b["total_sf"] if old_b else None,
            "status": "UNDER_CONSTRUCTION",
        })
        DB["buildings"][nb["id"]] = nb
        req = _spawn_requirement(l, p, "NEW_CONSTRUCTION")
        p["outcome_building_id"] = nb["id"]
        p["outcome_requirement_id"] = req["id"]
    p["executed_at"] = now_str()
    p["status"] = "EXECUTED"
    bump(p)
    return success(pub(p))
