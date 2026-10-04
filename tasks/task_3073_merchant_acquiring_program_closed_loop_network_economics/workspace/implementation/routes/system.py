"""Industry categories, the logical clock and the sweep-generation stamps."""

from flask import Blueprint, request

from auth import authenticate, require_role
from clock import format_iso
from db import STORE
from errors import ERR_INVALID_REQUEST, ApiError
from paging import paginate, pagination, sort_rows
from response import ok_array, ok_object
from routes import _common
from validation import (
    body_object,
    optional_bool,
    require_datetime,
    require_enum,
    require_int,
    require_string,
)

bp = Blueprint("system", __name__)

RISK_TIERS = ("LOW", "MEDIUM", "HIGH")


# --- Clock -----------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkIssuer"])
    body = body_object(request.get_json(silent=True) or {}, {"current_utc"})
    current_utc = require_datetime(body, "current_utc")
    STORE.clock.set(current_utc)
    _reevaluate_clock_rules()
    return ok_object({"wall_clock_utc": format_iso(STORE.clock.now())})


def _reevaluate_clock_rules():
    from services import disputes

    with STORE.lock:
        disputes.settle_auto_acceptances(STORE)


# --- Industry categories ---------------------------------------------------

@bp.post("/industry-categories")
def create_industry_category():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkAcquirer"])
    body = body_object(
        request.get_json(silent=True) or {},
        {"industry_code", "industry_name", "risk_tier", "base_discount_rate_bps",
         "high_risk_flag"},
    )
    industry_code = require_string(body, "industry_code")
    industry_name = require_string(body, "industry_name")
    risk_tier = require_enum(body, "risk_tier", RISK_TIERS)
    base_discount_rate_bps = require_int(body, "base_discount_rate_bps", minimum=0)
    high_risk_flag = optional_bool(body, "high_risk_flag", False)

    if industry_code in STORE.industry_categories_by_code:
        raise ApiError(ERR_INVALID_REQUEST, "industry_code must be unique.")

    with STORE.lock:
        row_id = STORE.new_id()
        now = STORE.clock.now()
        row = {
            "id": row_id,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": STORE.next_created_seq(),
            "industry_code": industry_code,
            "industry_name": industry_name,
            "risk_tier": risk_tier,
            "base_discount_rate_bps": base_discount_rate_bps,
            "high_risk_flag": high_risk_flag,
        }
        STORE.industry_categories[row_id] = row
        STORE.industry_categories_by_code[industry_code] = row_id
    return ok_object(_common.render(row)), 201


@bp.get("/industry-categories/<industry_category_id>")
def get_industry_category(industry_category_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkAcquirer"])
    row = _common.industry_category(industry_category_id)
    return ok_object(_common.render(row))


@bp.get("/industry-categories")
def list_industry_categories():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkAcquirer"])
    limit, offset = pagination(request.args)
    rows = sort_rows(STORE.industry_categories.values(), "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


# --- Sweep generations -----------------------------------------------------

@bp.post("/_sweep-index/stamp")
def stamp_sweep_index():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkAcquirer"])
    body = body_object(request.get_json(silent=True) or {}, {"sweep_index", "rolled_at"})
    sweep_index = require_int(body, "sweep_index")
    rolled_at = require_datetime(body, "rolled_at")

    for existing in STORE.sweep_index_stamps.values():
        if existing["sweep_index"] == sweep_index:
            raise ApiError(ERR_INVALID_REQUEST, "sweep_index must be unique.")

    with STORE.lock:
        row_id = STORE.new_id()
        now = STORE.clock.now()
        row = {
            "id": row_id,
            "created_at": now,
            "_seq": STORE.next_created_seq(),
            "_append_only": True,
            "sweep_index": sweep_index,
            "rolled_at": rolled_at,
        }
        STORE.sweep_index_stamps[row_id] = row
        STORE.latest_sweep_index = sweep_index
    return ok_object(_common.render(row))


@bp.get("/sweep-index-stamps")
def list_sweep_index_stamps():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkAcquirer"])
    limit, offset = pagination(request.args)
    rows = sort_rows(STORE.sweep_index_stamps.values(), "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)