"""Budget fund routes."""
from flask import Blueprint, request
from db import stores
from middleware import require_roles
from response import success, paginate
from engine import (
    new_id, now, touch_common, require_body, req_field, req_datetime,
    get_library, get_fund, serialize, recompute_fund,
)
from errors import (
    err, ERR_LIBRARY_NOT_FOUND, ERR_FUND_NOT_FOUND, ERR_FORBIDDEN,
    ERR_FUND_PERIOD_OVERLAP, ERR_FUND_CLOSED, ERR_FUND_HAS_OPEN_COMMITMENTS,
)

bp = Blueprint("funds", __name__)


def _serialize_fund(f):
    recompute_fund(f)
    return serialize(f)


@bp.post("/lending/libraries/<lid>/budget-funds")
def create_fund(lid):
    body = require_body()
    fiscal_year = req_field(body, "fiscal_year", (int,))
    period_start = req_datetime(body, "period_start")
    period_end = req_datetime(body, "period_end")
    budget_cents = req_field(body, "budget_cents", (int,))
    role, uid = require_roles({"LibraryAdmin"})
    get_library(lid, ERR_LIBRARY_NOT_FOUND)
    if uid != lid:
        raise err(ERR_FORBIDDEN, "LibraryAdmin may only manage their own library's funds")
    for f in stores["funds"].values():
        if f["library_id"] != lid:
            continue
        if period_start < f["_period_end"] and f["_period_start"] < period_end:
            raise err(ERR_FUND_PERIOD_OVERLAP, "fund period overlaps a sibling fund")
    f = {
        "id": new_id(),
        "library_id": lid,
        "fiscal_year": fiscal_year,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "budget_cents": budget_cents,
        "committed_cents": 0,
        "spent_cents": 0,
        "cpc_accrued_cents": 0,
        "available_committed_cents": budget_cents,
        "available_actual_cents": budget_cents,
        "status": "OPEN",
    }
    touch_common(f, created=True)
    f["_seq"] = len(stores["funds"])
    f["_period_start"] = period_start
    f["_period_end"] = period_end
    stores["funds"][f["id"]] = f
    return success(serialize(f), 201)


@bp.get("/lending/libraries/<lid>/budget-funds")
def list_funds(lid):
    require_roles({"LibraryAdmin", "SystemAnalyst"})
    get_library(lid, ERR_LIBRARY_NOT_FOUND)
    status = request.args.get("status")
    items = [f for f in stores["funds"].values() if f["library_id"] == lid]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items.sort(key=lambda f: (f["created_at"], f["_seq"]))
    page, meta = paginate([_serialize_fund(f) for f in items], request.args)
    return success(page, 200, meta)


@bp.get("/lending/budget-funds/<fid>")
def read_fund(fid):
    require_roles({"LibraryAdmin", "SystemAnalyst"})
    f = get_fund(fid, ERR_FUND_NOT_FOUND)
    return success(_serialize_fund(f))


@bp.post("/lending/budget-funds/<fid>/close")
def close_fund(fid):
    role, uid = require_roles({"LibraryAdmin"})
    f = get_fund(fid, ERR_FUND_NOT_FOUND)
    if uid != f["library_id"]:
        raise err(ERR_FORBIDDEN, "LibraryAdmin may only close their own library's funds")
    if f["status"] != "OPEN":
        raise err(ERR_FUND_CLOSED, "fund is not OPEN")
    for o in stores["orders"].values():
        if o["budget_fund_id"] == fid and o["status"] == "APPROVED":
            raise err(ERR_FUND_HAS_OPEN_COMMITMENTS, "APPROVED orders remain on this fund")
    f["status"] = "CLOSED"
    touch_common(f)
    recompute_fund(f)
    return success(serialize(f))
