"""Capital cycles and innovation projects (priority-ranked waterfall)."""

from flask import Blueprint, request

import storage
from calculations import new_record, bump, innovation_priority, run_waterfall
from envelope import success, paginate, sorted_by_created
from errors import fail
from rbac import guard, synchronized, authenticate, require_role, ALL_ROLES
from serializers import cycle_out, project_out
from validation import body_json, f_str, f_int, f_dt

bp = Blueprint("capital", __name__, url_prefix="/portfolio")


@bp.post("/capital-cycles")
@synchronized
def create_cycle():
    guard(["FinanceController"])
    body = body_json(required=True)
    period_code = f_str(body, "period_code")
    total_capital = f_int(body, "total_capital_cents", 1)
    window_start = f_dt(body, "window_start")
    window_end = f_dt(body, "window_end")
    # step 11: period_code unique across all cycles
    if any(c["period_code"] == period_code for c in storage.cycles.values()):
        fail("ERR_DUPLICATE", f"period_code '{period_code}' already exists")
    # step 16: window validity + half-open [start, end) non-overlap.
    # Overlap iff start < other_end AND end > other_start; adjacency allowed.
    if not window_start < window_end:
        fail("ERR_CYCLE_WINDOW_OVERLAP",
             "window_start must be strictly before window_end")
    for c in storage.cycles.values():
        if window_start < c["window_end"] and window_end > c["window_start"]:
            fail("ERR_CYCLE_WINDOW_OVERLAP",
                 "funding window overlaps an existing cycle's window")
    rec = new_record()
    rec.update({
        "period_code": period_code,
        "total_capital_cents": total_capital,
        "window_start": window_start,
        "window_end": window_end,
        "allocated_cents": 0,
        "cycle_status": "ALLOCATING",
    })
    storage.cycles[rec["id"]] = rec
    return success(cycle_out(rec), status=201)


@bp.post("/capital-cycles/<cid>/run-selection")
@synchronized
def run_selection(cid):
    guard(["FinanceController"])
    cycle = storage.cycles.get(cid)
    if cycle is None:
        fail("ERR_NOT_FOUND", f"capital cycle {cid} not found")
    # step 7: selection runs once, on an ALLOCATING cycle
    if cycle["cycle_status"] != "ALLOCATING":
        fail("ERR_INVALID_STATE", "run-selection requires cycle ALLOCATING")
    run_waterfall(cycle)
    cycle["cycle_status"] = "LOCKED"
    bump(cycle)
    return success(cycle_out(cycle))


@bp.post("/innovation-projects")
@synchronized
def create_project():
    user_id, role = authenticate()
    require_role(role, ["PortfolioManager", "BrandManager"])
    body = body_json(required=True)
    brand_id = f_str(body, "brand_id")
    funding_cycle_id = f_str(body, "funding_cycle_id")
    title = f_str(body, "title")
    requested = f_int(body, "requested_capital_cents", 1)
    expected_year3 = f_int(body, "expected_revenue_cents_year3", 0)
    fit = f_int(body, "strategic_fit_score", 0, 100)
    # step 6: body FKs resolve
    brand = storage.brands.get(brand_id)
    if brand is None:
        fail("ERR_NOT_FOUND", f"brand {brand_id} not found")
    cycle = storage.cycles.get(funding_cycle_id)
    if cycle is None:
        fail("ERR_NOT_FOUND", f"capital cycle {funding_cycle_id} not found")
    # step 7: brand ACTIVE or UNDER_REVIEW; cycle ALLOCATING
    if brand["brand_status"] not in ("ACTIVE", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE",
             "project create requires brand ACTIVE or UNDER_REVIEW")
    if cycle["cycle_status"] != "ALLOCATING":
        fail("ERR_INVALID_STATE", "project create requires cycle ALLOCATING")
    # step 9: entity-backed ownership for BrandManager callers
    if role == "BrandManager" and user_id != brand_id:
        fail("ERR_OWNERSHIP_MISMATCH",
             "BrandManager may propose projects only for the owned brand")
    # step 22: project size against the cycle total
    if requested > cycle["total_capital_cents"]:
        fail("ERR_CAPITAL_REQUEST_TOO_LARGE",
             "requested_capital_cents exceeds the cycle's total_capital_cents")
    rec = new_record()
    rec.update({
        "brand_id": brand_id,
        "funding_cycle_id": funding_cycle_id,
        "title": title,
        "requested_capital_cents": requested,
        "expected_revenue_cents_year3": expected_year3,
        "strategic_fit_score": fit,
        "priority_score": innovation_priority(brand, fit, expected_year3),
        "project_status": "PROPOSED",
    })
    storage.projects[rec["id"]] = rec
    return success(project_out(rec), status=201)


@bp.get("/innovation-projects")
@synchronized
def list_projects():
    guard(ALL_ROLES)
    records = list(storage.projects.values())
    for param in ("brand_id", "funding_cycle_id", "project_status"):
        value = request.args.get(param)
        if value is not None:
            records = [p for p in records if p[param] == value]
    page, meta = paginate(sorted_by_created(records))
    return success([project_out(p) for p in page], response_type="array",
                   pagination=meta)


@bp.get("/innovation-projects/<pid>")
@synchronized
def get_project(pid):
    guard(ALL_ROLES)
    p = storage.projects.get(pid)
    if p is None:
        fail("ERR_NOT_FOUND", f"innovation project {pid} not found")
    return success(project_out(p))
