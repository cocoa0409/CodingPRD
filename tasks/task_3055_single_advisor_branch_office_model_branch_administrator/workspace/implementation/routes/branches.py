"""Branch routes: proposal, site approval + lease, lifecycle, OCC-guarded PATCH,
and branch-scoped list endpoints (§3.3)."""
from datetime import datetime, timezone
from flask import Blueprint, request

import db
from errors import err
from middleware import auth_context, require_role
from helpers import (
    body_json, require_fields, require_string, parse_dt, get_or_404,
    stamp_new, touch, paginate, sort_by_created_at, recompute_tier,
    recompute_staffing, release_territory,
)
from response import success_object, success_list

bp = Blueprint("branches", __name__)
PREFIX = "/branch-office/branches"


def _current_month_window():
    now = db.clock.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


@bp.route(PREFIX, methods=["POST"])
def create_branch():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    body = body_json()
    require_fields(body, ["community_name", "site_address", "territory_id"])
    community = require_string(body, "community_name")
    site = require_string(body, "site_address")
    territory = get_or_404(db.territories, body["territory_id"], "Territory")
    branch = stamp_new({
        "community_name": community,
        "operating_status": "PROPOSED",
        "staffing_status": "UNSTAFFED",
        "site_address": site,
        "household_count": 0,
        "assets_under_care_dollars": 0,
        "territory_id": territory["id"],
    })
    recompute_tier(branch)
    db.branches[branch["id"]] = branch
    return success_object(branch, 201)


@bp.route(PREFIX, methods=["GET"])
def list_branches():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "CompliancePrincipal"})
    items = list(db.branches.values())
    tid = request.args.get("territory_id")
    if tid:
        items = [b for b in items if b.get("territory_id") == tid]
    ops = request.args.get("operating_status")
    if ops:
        items = [b for b in items if b.get("operating_status") == ops]
    tier = request.args.get("service_tier")
    if tier:
        items = [b for b in items if b.get("service_tier") == tier]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<bid>", methods=["GET"])
def get_branch(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor", "BranchAdministrator", "CompliancePrincipal"})
    return success_object(get_or_404(db.branches, bid, "Branch"))


@bp.route(f"{PREFIX}/<bid>", methods=["PATCH"])
def patch_branch(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    branch = get_or_404(db.branches, bid, "Branch")
    body = body_json()
    # Input-shape backstop (priority 18) runs before the stale-version check (19).
    updates = {}
    for f in ("household_count", "assets_under_care_dollars"):
        if f in body:
            v = body[f]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise err("ERR_INVALID_REQUEST", f"{f} must be an integer >= 0.")
            updates[f] = v
    # OCC (priority 19): expected_branch_version mandatory on this path
    if "expected_branch_version" not in body:
        raise err("ERR_INVALID_REQUEST", "expected_branch_version is required.")
    ev = body["expected_branch_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise err("ERR_INVALID_REQUEST", "expected_branch_version must be an integer.")
    if ev != branch.get("version"):
        raise err("ERR_STALE_VERSION", "expected_branch_version does not match the branch's current version.")
    for f, v in updates.items():
        branch[f] = v
    recompute_tier(branch)
    touch(branch)
    return success_object(branch)


@bp.route(f"{PREFIX}/<bid>/approve-site", methods=["POST"])
def approve_site(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    branch = get_or_404(db.branches, bid, "Branch")
    body = body_json()
    require_fields(body, ["monthly_rent_cents", "term_start", "term_end"])
    rent = body["monthly_rent_cents"]
    if isinstance(rent, bool) or not isinstance(rent, int) or rent <= 0:
        raise err("ERR_INVALID_REQUEST", "monthly_rent_cents must be a positive integer.")
    term_start = parse_dt(body["term_start"], "term_start")
    term_end = parse_dt(body["term_end"], "term_end")
    if term_end < term_start:
        raise err("ERR_INVALID_REQUEST", "term_end must be on or after term_start.")
    # state
    if branch.get("operating_status") != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Branch is not PROPOSED.")
    territory = db.territories.get(branch.get("territory_id"))
    if territory is None:
        raise err("ERR_NOT_FOUND", "Branch territory not found.")
    if territory.get("status") == "RETIRED":
        raise err("ERR_INVALID_STATE", "Branch territory is RETIRED.")
    # lease overlap: closed-interval intersection with another SIGNED lease
    # at the same site address (adjacency conflicts).
    for lease in db.leases.values():
        if lease.get("status") != "SIGNED":
            continue
        other_branch = db.branches.get(lease.get("branch_id"))
        if other_branch is None or other_branch.get("site_address") != branch.get("site_address"):
            continue
        if other_branch["id"] == branch["id"]:
            continue
        ls = parse_dt(lease["term_start"], "term_start")
        le = parse_dt(lease["term_end"], "term_end")
        # closed interval overlap: [term_start, term_end] intersects [ls, le]
        if term_start <= le and ls <= term_end:
            raise err("ERR_LEASE_OVERLAP", "Lease window intersects another SIGNED lease on the same site.")
    lease = stamp_new({
        "branch_id": branch["id"],
        "monthly_rent_cents": rent,
        "term_start": db.iso_format(term_start),
        "term_end": db.iso_format(term_end),
        "status": "SIGNED",
    })
    db.leases[lease["id"]] = lease
    branch["operating_status"] = "SITE_APPROVED"
    touch(branch)
    return success_object(branch)


@bp.route(f"{PREFIX}/<bid>/open", methods=["POST"])
def open_branch(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    branch = get_or_404(db.branches, bid, "Branch")
    if branch.get("operating_status") != "SITE_APPROVED":
        raise err("ERR_INVALID_STATE", "Branch is not SITE_APPROVED.")
    if branch.get("staffing_status") != "FULLY_STAFFED":
        raise err("ERR_BRANCH_NOT_FULLY_STAFFED", "Branch must be FULLY_STAFFED to open.")
    branch["operating_status"] = "OPEN"
    touch(branch)
    # side effect: first OPEN financial period covering the current calendar month
    start, end = _current_month_window()
    period = stamp_new({
        "branch_id": branch["id"],
        "period_start": db.iso_format(start),
        "period_end": db.iso_format(end),
        "status": "OPEN",
        "gross_revenue_cents": 0,
        "total_charges_cents": 0,
        "net_profit_cents": 0,
        "advisor_share_cents": 0,
        "deficit_carryforward_cents": 0,
    })
    db.financial_periods[period["id"]] = period
    return success_object(branch)


@bp.route(f"{PREFIX}/<bid>/suspend", methods=["POST"])
def suspend_branch(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    branch = get_or_404(db.branches, bid, "Branch")
    if branch.get("operating_status") != "OPEN":
        raise err("ERR_INVALID_STATE", "Branch is not OPEN.")
    branch["operating_status"] = "SUSPENDED"
    touch(branch)
    return success_object(branch)


@bp.route(f"{PREFIX}/<bid>/reinstate", methods=["POST"])
def reinstate_branch(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    branch = get_or_404(db.branches, bid, "Branch")
    if branch.get("operating_status") != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Branch is not SUSPENDED.")
    if branch.get("staffing_status") != "FULLY_STAFFED":
        raise err("ERR_BRANCH_NOT_FULLY_STAFFED", "Branch must be FULLY_STAFFED to reinstate.")
    branch["operating_status"] = "OPEN"
    touch(branch)
    return success_object(branch)


@bp.route(f"{PREFIX}/<bid>/close", methods=["POST"])
def close_branch(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    branch = get_or_404(db.branches, bid, "Branch")
    if branch.get("operating_status") != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Branch is not SUSPENDED.")
    # no goodwill transfer OFFERED/NEGOTIATING/ACCEPTED (priority 24)
    for t in db.goodwill_transfers.values():
        if t.get("branch_id") == bid and t.get("status") in ("OFFERED", "NEGOTIATING", "ACCEPTED"):
            raise err("ERR_TRANSFER_ACTIVE", "A goodwill transfer on the branch is active.")
    # all periods must be FINALIZED
    for p in db.financial_periods.values():
        if p.get("branch_id") == bid and p.get("status") in ("OPEN", "CLOSED"):
            raise err("ERR_INVALID_STATE", "All financial periods must be FINALIZED before close.")
    # cascade
    for adm in db.administrators.values():
        if adm.get("branch_id") == bid and adm.get("status") in ("ACTIVE", "ON_LEAVE"):
            adm["status"] = "RELEASED"
            adm["branch_id"] = None
            touch(adm)
    for lease in db.leases.values():
        if lease.get("branch_id") == bid and lease.get("status") == "SIGNED":
            lease["status"] = "TERMINATED"
            touch(lease)
    territory = db.territories.get(branch.get("territory_id"))
    if territory is not None and territory.get("status") == "ASSIGNED":
        release_territory(territory)
    branch["operating_status"] = "CLOSED"
    recompute_staffing(branch)
    touch(branch)
    return success_object(branch)


# ---- branch-scoped list endpoints ----

@bp.route(f"{PREFIX}/<bid>/financial-periods", methods=["GET"])
def branch_periods(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    get_or_404(db.branches, bid, "Branch")
    items = [p for p in db.financial_periods.values() if p.get("branch_id") == bid]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<bid>/leases", methods=["GET"])
def branch_leases(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    get_or_404(db.branches, bid, "Branch")
    items = [l for l in db.leases.values() if l.get("branch_id") == bid]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<bid>/administrators", methods=["GET"])
def branch_admins(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    get_or_404(db.branches, bid, "Branch")
    items = [a for a in db.administrators.values() if a.get("branch_id") == bid]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<bid>/goodwill-transfers", methods=["GET"])
def branch_transfers(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    get_or_404(db.branches, bid, "Branch")
    items = [t for t in db.goodwill_transfers.values() if t.get("branch_id") == bid]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<bid>/charges", methods=["GET"])
def branch_charges(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    get_or_404(db.branches, bid, "Branch")
    items = [c for c in db.charges.values() if c.get("branch_id") == bid]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<bid>/assign-administrator", methods=["POST"])
def assign_administrator(bid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    branch = get_or_404(db.branches, bid, "Branch")
    body = body_json()
    require_fields(body, ["administrator_id"])
    adm = get_or_404(db.administrators, body["administrator_id"], "BranchOfficeAdministrator")
    if adm.get("status") != "HIRED":
        raise err("ERR_INVALID_STATE", "Administrator is not HIRED.")
    for a in db.administrators.values():
        if a.get("branch_id") == bid and a.get("status") == "ACTIVE":
            raise err("ERR_BOA_ALREADY_ASSIGNED", "Branch already has an ACTIVE administrator.")
    adm["branch_id"] = bid
    adm["status"] = "ACTIVE"
    touch(adm)
    recompute_staffing(branch)
    touch(branch)
    return success_object(adm)
