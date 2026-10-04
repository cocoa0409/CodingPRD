"""Routes: incentives."""

from flask import Blueprint

from db import db, iso3
from errors import ApiError
from helpers import (
    auth, require_role, body, idem_begin, dt_field,
    opt_string, opt_integer, opt_boolean, fresh_row, touch, get_or_404,
)
from response import success_obj
import services as svc

bp = Blueprint("incentives", __name__)

INCENTIVE_TYPES = ["PRICE_CUT", "CLOSING_COST_CREDIT", "RATE_BUYDOWN"]
SERIES_CODES = ["EXPRESS", "CLASSIC", "VENTURE", "FREEDOM"]


@bp.post("/communities/<cid>/incentives")
def create_incentive(cid):
    role, _ = auth()
    ctx = idem_begin()
    c = get_or_404(db.communities, cid)
    require_role(role, ["COMMUNITY_MANAGER"])
    b = body()

    itype = b.get("type")
    if itype is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing required field: type")
    if not isinstance(itype, str) or itype not in INCENTIVE_TYPES:
        raise ApiError("ERR_VALIDATION", 400, "Field type has invalid value")

    window_start = dt_field(b, "window_start")
    window_end = dt_field(b, "window_end")

    series_code = b.get("series_code")
    if series_code is not None:
        if not isinstance(series_code, str) or series_code not in SERIES_CODES:
            raise ApiError("ERR_VALIDATION", 400, "Field series_code has invalid value")

    if itype == "RATE_BUYDOWN":
        value_pct = b.get("value_pct")
        if value_pct is None:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: value_pct")
        if not isinstance(value_pct, (int, float)) or isinstance(value_pct, bool):
            raise ApiError("ERR_VALIDATION", 400, "Field value_pct must be a number")
        value_cents = None
    else:
        value_cents = b.get("value_cents")
        if value_cents is None:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: value_cents")
        if not isinstance(value_cents, int) or isinstance(value_cents, bool):
            raise ApiError("ERR_VALIDATION", 400, "Field value_cents must be an integer")
        value_pct = None

    auto_flag = opt_boolean(b, "auto_activate_on_overheld", False)

    # 8: same-type + same-series window conflict with 7-day buffer
    new_start, new_end = window_start, window_end
    for inc in db.incentives.values():
        if inc["community_id"] != cid:
            continue
        if inc["type"] != itype:
            continue
        if inc.get("series_code") != series_code:
            continue
        ex_start = svc.dt_or_none(inc["window_start"])
        ex_end = svc.dt_or_none(inc["window_end"])
        if new_start < ex_end + svc.INCENTIVE_BUFFER and ex_start < new_end + svc.INCENTIVE_BUFFER:
            raise ApiError(
                "ERR_INCENTIVE_WINDOW_CONFLICT", 409,
                "Incentive window overlaps or lacks the 7-day buffer",
            )

    row = fresh_row()
    row.update({
        "community_id": cid,
        "type": itype,
        "value_cents": value_cents,
        "value_pct": value_pct,
        "series_code": series_code,
        "window_start": iso3(window_start),
        "window_end": iso3(window_end),
        "auto_activate_on_overheld": auto_flag,
        "cancelled": False,
    })
    db.incentives[row["id"]] = row
    svc.refresh_community_home_pricing(cid)
    return success_obj(svc.ser_incentive(row), status=201)


@bp.get("/incentives/<iid>")
def get_incentive(iid):
    auth()
    inc = get_or_404(db.incentives, iid)
    return success_obj(svc.ser_incentive(inc))


@bp.post("/incentives/<iid>/cancel")
def cancel_incentive(iid):
    role, _ = auth()
    ctx = idem_begin()
    inc = get_or_404(db.incentives, iid)
    require_role(role, ["COMMUNITY_MANAGER"])
    body()
    status = svc.incentive_status(inc)
    if status not in ("SCHEDULED", "ACTIVE"):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "Incentive cannot be cancelled from status " + status,
        )
    inc["cancelled"] = True
    touch(inc)
    svc.refresh_community_home_pricing(inc["community_id"])
    return success_obj(svc.ser_incentive(inc))
