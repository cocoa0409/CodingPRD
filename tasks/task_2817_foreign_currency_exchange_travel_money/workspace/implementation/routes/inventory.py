"""Inventory positions and the seasonal stocking-plan workflow."""
from flask import Blueprint

import calc
from core import (
    D,
    all_rows,
    actor,
    body,
    clock,
    endpoint,
    fail,
    listing,
    need,
    need_currency,
    new_row,
    ok,
    opt_list,
    opt_str,
    parse_note_lines,
    public,
    req_enum,
    req_int,
    req_list,
    req_str,
    require_branch_active,
    require_not_frozen,
    store,
    touch,
)

bp = Blueprint("inventory", __name__)

POSITION_READERS = ("PlatformAdmin", "TreasuryOfficer", "BranchManager", "BranchTeller")
PLAN_READERS = ("PlatformAdmin", "TreasuryOfficer", "BranchManager")


# ==========================================================================
# Inventory positions
# ==========================================================================
@bp.post("/inventory-positions")
@endpoint(["BranchManager", "TreasuryOfficer"])
def create_position():
    b = body()
    branch = need("Branch", req_str(b, "branch_id"))
    currency_code = req_str(b, "currency_code")
    need_currency(currency_code)
    raw = req_list(b, "opening_denomination_mix")
    lines = parse_note_lines(
        raw,
        "opening_denomination_mix",
        count_keys=("note_count", "available_note_count"),
        min_count=0,
    )
    if calc.branch_position(branch["id"], currency_code) is not None:
        fail("ERR_POSITION_ALREADY_EXISTS")
    row = new_row("InventoryPosition")
    row["branch_id"] = branch["id"]
    row["currency_code"] = currency_code
    row["denomination_mix"] = [
        {
            "denomination_minor_units": line["denomination_minor_units"],
            "available_note_count": line["note_count"],
            "quarantined_note_count": 0,
            "written_off_note_count": 0,
        }
        for line in lines
    ]
    row["total_minor_units"] = 0
    row["quarantined_minor_units"] = 0
    row["usd_equivalent_cents"] = 0
    row["status"] = "OPEN"
    store(row)
    calc.inventory_cascade(row, branch)
    touch(branch)
    return ok(public(row), 201)


@bp.get("/inventory-positions/<position_id>")
@endpoint(POSITION_READERS)
def read_position(position_id):
    return ok(public(need("InventoryPosition", position_id)))


@bp.get("/inventory-positions")
@endpoint(POSITION_READERS)
def list_positions():
    return listing(
        "InventoryPosition",
        {"branch_id": "branch_id", "currency_code": "currency_code", "status": "status"},
    )


# ==========================================================================
# Inventory plans
# ==========================================================================
def _parse_target_lines(raw, field="target_lines"):
    """rank 3 resolves each currency_code before rank 4 checks the baseline."""
    entries = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "%s entries must be objects." % field)
        code = entry.get("currency_code")
        if not isinstance(code, str) or not code:
            fail("ERR_INVALID_REQUEST", "%s[].currency_code is required." % field)
        need_currency(code)
        entries.append(entry)
    out = []
    seen = set()
    for entry in entries:
        baseline = entry.get("baseline_daily_minor_units")
        if isinstance(baseline, bool) or not isinstance(baseline, int) or baseline < 0:
            fail(
                "ERR_INVALID_REQUEST",
                "%s[].baseline_daily_minor_units must be an integer >= 0." % field,
            )
        code = entry["currency_code"]
        if code in seen:
            fail("ERR_INVALID_REQUEST", "%s contains duplicate currencies." % field)
        seen.add(code)
        out.append({"currency_code": code, "baseline_daily_minor_units": baseline})
    out.sort(key=lambda e: e["currency_code"])
    return out


@bp.post("/inventory-plans")
@endpoint(["BranchManager"])
def create_plan():
    b = body()
    branch = need("Branch", req_str(b, "branch_id"))
    corridor = need("TravelCorridor", req_str(b, "travel_corridor_id"))
    raw_lines = opt_list(b, "target_lines", default=None)
    target_lines = _parse_target_lines(raw_lines) if raw_lines is not None else []
    season_days = req_int(b, "season_days", minimum=1, maximum=366)
    require_branch_active(branch)
    row = new_row("InventoryPlan")
    row["branch_id"] = branch["id"]
    row["travel_corridor_id"] = corridor["id"]
    row["season_days"] = season_days
    row["target_lines"] = target_lines
    row["computed_targets"] = []
    row["status"] = "DRAFT"
    row["revision_count"] = 0
    row["submitted_by_user_id"] = None
    row["reviewed_by_user_id"] = None
    row["review_note"] = None
    store(row)
    return ok(public(row), 201)


@bp.post("/inventory-plans/<plan_id>/submit")
@endpoint(["BranchManager"])
def submit_plan(plan_id):
    plan = need("InventoryPlan", plan_id)
    b = body()
    raw_lines = opt_list(b, "target_lines", default=None)
    replacement = _parse_target_lines(raw_lines) if raw_lines is not None else None
    if plan["status"] != "DRAFT":
        fail("ERR_PLAN_INVALID_STATE")
    if replacement is not None:
        plan["target_lines"] = replacement
    if not plan["target_lines"]:
        fail("ERR_PLAN_NO_TARGET_LINES")
    branch = need("Branch", plan["branch_id"])
    corridor = need("TravelCorridor", plan["travel_corridor_id"])
    plan["computed_targets"] = calc.corridor_targets(plan, corridor, branch)
    plan["status"] = "SUBMITTED"
    plan["submitted_by_user_id"] = actor()
    touch(plan)
    return ok(public(plan))


@bp.post("/inventory-plans/<plan_id>/review")
@endpoint(["TreasuryOfficer"])
def review_plan(plan_id):
    plan = need("InventoryPlan", plan_id)
    b = body()
    decision = req_enum(b, "decision", ("APPROVE", "REJECT"))
    review_note = opt_str(b, "review_note")
    if plan["status"] != "SUBMITTED":
        fail("ERR_PLAN_INVALID_STATE")
    if actor() == plan["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    plan["reviewed_by_user_id"] = actor()
    plan["review_note"] = review_note
    if decision == "APPROVE":
        branch = need("Branch", plan["branch_id"])
        corridor = need("TravelCorridor", plan["travel_corridor_id"])
        plan["computed_targets"] = calc.corridor_targets(plan, corridor, branch)
        plan["status"] = "APPROVED"
    else:
        plan["status"] = "DRAFT"
        plan["revision_count"] += 1
    touch(plan)
    return ok(public(plan))


@bp.post("/inventory-plans/<plan_id>/activate")
@endpoint(["BranchManager"])
def activate_plan(plan_id):
    plan = need("InventoryPlan", plan_id)
    if plan["status"] != "APPROVED":
        fail("ERR_PLAN_INVALID_STATE")
    branch = need("Branch", plan["branch_id"])
    require_not_frozen(branch)
    corridor = need("TravelCorridor", plan["travel_corridor_id"])
    now = clock()
    if not (D(corridor["season_start_date"]) <= now < D(corridor["season_end_date"])):
        fail("ERR_PLAN_OUTSIDE_SEASON")
    plan["status"] = "ACTIVE"
    touch(plan)
    return ok(public(plan))


@bp.get("/inventory-plans/<plan_id>")
@endpoint(PLAN_READERS)
def read_plan(plan_id):
    return ok(public(need("InventoryPlan", plan_id)))


@bp.get("/inventory-plans")
@endpoint(PLAN_READERS)
def list_plans():
    return listing(
        "InventoryPlan",
        {
            "branch_id": "branch_id",
            "travel_corridor_id": "travel_corridor_id",
            "status": "status",
        },
    )


def branch_sells_exotic(branch_id, currency_code):
    """An EXOTIC currency is sellable only where an ACTIVE plan names it."""
    for plan in all_rows("InventoryPlan"):
        if plan["branch_id"] != branch_id or plan["status"] != "ACTIVE":
            continue
        for target in plan["computed_targets"]:
            if target["currency_code"] == currency_code:
                return True
    return False
