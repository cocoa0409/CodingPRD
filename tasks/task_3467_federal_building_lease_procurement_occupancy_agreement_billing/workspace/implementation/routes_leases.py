"""Lease read/commence/tax-statement endpoints (PRD section 3.4)."""
from datetime import timedelta

from flask import Blueprint, request

from calc import ti_schedule
from dates import add_months, parse_date
from envelope import success
from errors import ApiError
from middleware import (ALL_ROLES, body, is_int, is_num, paginate, require_auth)
from store import DB, bump, now_dt, pub, sorted_items

bp = Blueprint("leases", __name__)


def _get_lease(lid):
    l = DB["leases"].get(lid)
    if not l:
        raise ApiError("ERR_NOT_FOUND", 404, "Lease not found")
    return l


@bp.route("/leasing/leases/<lid>", methods=["GET"])
def get_lease(lid):
    require_auth(ALL_ROLES)
    return success(pub(_get_lease(lid)))


@bp.route("/leasing/leases", methods=["GET"])
def list_leases():
    require_auth(ALL_ROLES)
    items = list(DB["leases"].values())
    for f in ("requirement_id", "building_id", "agency_id", "offer_id", "succeeds_lease_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l.get(f) == v]
    page, pagination = paginate(sorted_items(items))
    return success([pub(l) for l in page], 200, pagination)


@bp.route("/leasing/leases/<lid>/commence", methods=["POST"])
def commence_lease(lid):
    require_auth(["GSALeasingOfficer"])
    l = _get_lease(lid)
    b = body()
    # priority 5: shape (incl. cpi_base_index presence vs escalation_method)
    comm = parse_date(b.get("commencement_date"))
    if comm is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "commencement_date must be an ISO date")
    if not is_int(b.get("ti_buildout_cost_cents")) or b["ti_buildout_cost_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "ti_buildout_cost_cents must be an integer >= 0")
    if b.get("ti_amort_method") not in ("ANNUITY", "STRAIGHT_LINE"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "ti_amort_method must be ANNUITY or STRAIGHT_LINE")
    has_cpi = "cpi_base_index" in b and b.get("cpi_base_index") is not None
    if l["escalation_method"] == "CPI_INDEXED":
        if not has_cpi or not is_num(b["cpi_base_index"]):
            raise ApiError("ERR_INVALID_REQUEST", 400, "cpi_base_index is required for CPI_INDEXED leases")
    else:
        if has_cpi:
            raise ApiError("ERR_INVALID_REQUEST", 400, "cpi_base_index must be omitted for BASE_YEAR_STOP leases")
    # priority 6: state
    if l["status"] != "AWARDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only an AWARDED lease can be commenced")
    # priority 9: commencement window [awarded_date, awarded_date + 24 months]
    awarded = parse_date(l["awarded_date"][:10])
    if comm < awarded or comm > add_months(awarded, 24):
        raise ApiError("ERR_COMMENCEMENT_OUT_OF_WINDOW", 422,
                       "commencement_date must be on or after the award date and within 24 months of it")
    l["commencement_date"] = b["commencement_date"]
    l["ti_buildout_cost_cents"] = b["ti_buildout_cost_cents"]
    l["ti_amort_method"] = b["ti_amort_method"]
    if l["escalation_method"] == "CPI_INDEXED":
        l["cpi_base_index"] = b["cpi_base_index"]
        l["current_cpi_index"] = b["cpi_base_index"]
    l["end_date"] = (add_months(comm, l["term_months"]) - timedelta(days=1)).isoformat()
    P = max(0, b["ti_buildout_cost_cents"] - l["ti_allowance_total_cents"])
    l["ti_amortized_principal_cents"] = P
    l["ti_schedule_monthly_cents"] = ti_schedule(P, l["term_months"], l["ti_amort_method"])
    l["status"] = "COMMENCED"
    bump(l)
    return success(pub(l))


@bp.route("/leasing/leases/<lid>/tax-statements", methods=["POST"])
def add_tax_statement(lid):
    require_auth(["GSALeasingOfficer"])
    l = _get_lease(lid)
    b = body()
    # priority 5: shape (incl. cpi_index presence vs escalation_method)
    if not is_int(b.get("tax_year")):
        raise ApiError("ERR_INVALID_REQUEST", 400, "tax_year must be an integer")
    if not is_int(b.get("actual_tax_per_sf_yr_cents")) or b["actual_tax_per_sf_yr_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "actual_tax_per_sf_yr_cents must be an integer >= 0")
    has_cpi = "cpi_index" in b and b.get("cpi_index") is not None
    if l["escalation_method"] == "CPI_INDEXED":
        if not has_cpi or not is_num(b["cpi_index"]):
            raise ApiError("ERR_INVALID_REQUEST", 400, "cpi_index is required for CPI_INDEXED leases")
    else:
        if has_cpi:
            raise ApiError("ERR_INVALID_REQUEST", 400, "cpi_index must be omitted for BASE_YEAR_STOP leases")
    # priority 7: lease must be COMMENCED or EXPIRING
    if l["status"] not in ("COMMENCED", "EXPIRING"):
        raise ApiError("ERR_LEASE_NOT_COMMENCED", 409, "Tax statements require a COMMENCED or EXPIRING lease")
    # priority 11: one statement per tax_year per lease
    for s in l["tax_statements"]:
        if s["tax_year"] == b["tax_year"]:
            raise ApiError("ERR_DUPLICATE_TAX_YEAR", 409, "A tax statement for this tax_year already exists")
    stmt = {
        "tax_year": b["tax_year"],
        "actual_tax_per_sf_yr_cents": b["actual_tax_per_sf_yr_cents"],
        "cpi_index": b.get("cpi_index") if l["escalation_method"] == "CPI_INDEXED" else None,
    }
    l["tax_statements"].append(stmt)
    # recompute current values against the year of the current logical clock
    yr = now_dt().year
    qual = [s for s in l["tax_statements"] if s["tax_year"] <= yr]
    if qual:
        latest = max(qual, key=lambda s: s["tax_year"])
        l["current_tax_per_sf_yr_cents"] = latest["actual_tax_per_sf_yr_cents"]
        l["current_cpi_index"] = latest["cpi_index"]
    else:
        l["current_tax_per_sf_yr_cents"] = l["base_year_tax_per_sf_yr_cents"]
        l["current_cpi_index"] = l["cpi_base_index"]
    bump(l)
    return success(pub(l), 201)
