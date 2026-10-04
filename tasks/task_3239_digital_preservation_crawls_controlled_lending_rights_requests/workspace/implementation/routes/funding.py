"""Funding grants and budget lines (OCC on grant version)."""
from flask import Blueprint, request

import db
from errors import (
    ERR_GRANT_EXHAUSTED, ERR_INVALID_STATE, ERR_STALE_VERSION, not_found,
    raise_err, validation,
)
from middleware import require_roles
from models import serialize_budget_line, serialize_grant, stamp_new, touch
from response import paginate, parse_pagination, success_list, success_object
from services import grant_counters, recompute_grant

bp = Blueprint("funding", __name__)


@bp.post("/archive/funding-grants")
def create_grant():
    require_roles("FinanceAdmin")
    body = request.get_json(silent=True) or {}
    donor_name = body.get("donor_name")
    amount = body.get("amount_cents")
    if not isinstance(donor_name, str) or not donor_name:
        validation("donor_name is required")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        validation("amount_cents must be an integer > 0")
    g = stamp_new()
    g.update({
        "donor_name": donor_name,
        "amount_cents": amount,
        "reserved_cents": 0,
        "spent_cents": 0,
        "status": "OPEN",
    })
    db.grants[g["id"]] = g
    return success_object(serialize_grant(g), status=201)


@bp.get("/archive/funding-grants/<gid>")
def get_grant(gid):
    require_roles("FinanceAdmin", "Admin")
    g = db.grants.get(gid)
    if g is None:
        not_found("Funding grant not found")
    return success_object(serialize_grant(g))


@bp.post("/archive/funding-grants/<gid>/close")
def close_grant(gid):
    require_roles("FinanceAdmin")
    g = db.grants.get(gid)
    if g is None:
        not_found("Funding grant not found")
    if g["status"] not in ("OPEN", "EXHAUSTED"):
        raise_err(ERR_INVALID_STATE, "Grant is not OPEN or EXHAUSTED")
    if g["reserved_cents"] != 0:
        validation("Grant cannot be closed while reserved_cents is non-zero")
    g["status"] = "CLOSED"
    touch(g)
    return success_object(serialize_grant(g))


@bp.post("/archive/budget-lines")
def create_budget_line():
    require_roles("FinanceAdmin")
    body = request.get_json(silent=True) or {}
    grant_id = body.get("grant_id")
    category = body.get("category")
    reservation = body.get("budget_reservation_cents")
    if grant_id is not None and grant_id not in db.grants:
        not_found("Funding grant not found")
    if not isinstance(grant_id, str) or not grant_id:
        validation("grant_id is required")
    if category not in ("STORAGE", "BANDWIDTH", "SCAN_LABOR", "PETABYTE_INSURANCE"):
        validation("category must be STORAGE, BANDWIDTH, SCAN_LABOR, or PETABYTE_INSURANCE")
    if isinstance(reservation, bool) or not isinstance(reservation, int) or reservation <= 0:
        validation("budget_reservation_cents must be an integer > 0")
    grant = db.grants[grant_id]
    # Priority 19: grant capacity (equality allowed).
    util = grant["reserved_cents"] + grant["spent_cents"]
    if util + reservation > grant["amount_cents"]:
        raise_err(ERR_GRANT_EXHAUSTED, "Reservation would exceed the grant amount")
    line = stamp_new()
    line.update({
        "grant_id": grant_id,
        "category": category,
        "budget_reservation_cents": reservation,
        "actual_spend_cents": 0,
        "status": "OPEN",
    })
    db.budget_lines[line["id"]] = line
    recompute_grant(grant, bump_version=True)
    return success_object(serialize_budget_line(line), status=201)


@bp.get("/archive/funding-grants/<gid>/budget-lines")
def list_grant_budget_lines(gid):
    require_roles("FinanceAdmin", "Admin")
    if gid not in db.grants:
        not_found("Funding grant not found")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    category = request.args.get("category")
    rows = [l for l in db.budget_lines.values() if l["grant_id"] == gid]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    if category is not None:
        rows = [l for l in rows if l["category"] == category]
    rows.sort(key=lambda l: l["created_at"])
    page, total = paginate([serialize_budget_line(l) for l in rows], limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/archive/budget-lines/<lid>")
def get_budget_line(lid):
    require_roles("FinanceAdmin", "Admin")
    line = db.budget_lines.get(lid)
    if line is None:
        not_found("Budget line not found")
    return success_object(serialize_budget_line(line))


def _occ_check_grant(body, grant):
    expected = body.get("expected_grant_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        validation("expected_grant_version is required and must be an integer")
    if expected != grant["version"]:
        raise_err(ERR_STALE_VERSION, "Stale expected_grant_version")


@bp.post("/archive/budget-lines/<lid>/settle")
def settle_budget_line(lid):
    require_roles("FinanceAdmin")
    line = db.budget_lines.get(lid)
    if line is None:
        not_found("Budget line not found")
    if line["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Budget line is not OPEN")
    body = request.get_json(silent=True) or {}
    actual = body.get("actual_spend_cents")
    if isinstance(actual, bool) or not isinstance(actual, int) or actual < 0:
        validation("actual_spend_cents must be an integer >= 0")
    grant = db.grants[line["grant_id"]]
    _occ_check_grant(body, grant)
    line["actual_spend_cents"] = actual
    line["status"] = "SETTLED"
    touch(line)
    recompute_grant(grant, bump_version=True)
    return success_object(serialize_budget_line(line))


@bp.post("/archive/budget-lines/<lid>/release")
def release_budget_line(lid):
    require_roles("FinanceAdmin")
    line = db.budget_lines.get(lid)
    if line is None:
        not_found("Budget line not found")
    if line["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Budget line is not OPEN")
    body = request.get_json(silent=True) or {}
    grant = db.grants[line["grant_id"]]
    _occ_check_grant(body, grant)
    line["status"] = "RELEASED"
    touch(line)
    recompute_grant(grant, bump_version=True)
    return success_object(serialize_budget_line(line))
