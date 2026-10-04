"""Households and their monthly consumption records."""
import uuid

from flask import Blueprint

from store import db, next_seq
from helpers import (
    ApiError, body, created, find, init_common, list_ok, need, now_iso, ok,
    parse_period_val, period_not_future, require_roles, v_int, v_str,
)
from serializers import household_out, consumption_out

bp = Blueprint("households", __name__)


@bp.post("/households")
@require_roles("PlatformAdmin")
def create_household():
    b = body()
    hh = init_common({
        "region": v_str(b, "region"),
        "size": v_int(b, "size", minv=1),
    })
    db["households"][hh["id"]] = hh
    return created(household_out(hh))


@bp.get("/households/<rid>")
@require_roles("PlatformAdmin", "SupportAgent")
def get_household(rid):
    return ok(household_out(find("households", rid)))


@bp.post("/households/<rid>/consumption-records")
@require_roles("PlatformAdmin")
def create_consumption(rid):
    hh = find("households", rid)
    b = body()
    period = parse_period_val(need(b, "period"))
    period_not_future(period)
    pods = v_int(b, "pods_brewed", minv=0)
    for r in db["consumption"].values():
        if r["household_id"] == hh["id"] and r["period"] == period:
            raise ApiError("ERR_DUPLICATE_CONSUMPTION_PERIOD", 409,
                           "A consumption record already exists for this period")
    rec = {
        "id": str(uuid.uuid4()),
        "household_id": hh["id"],
        "period": period,
        "pods_brewed": pods,
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    db["consumption"][rec["id"]] = rec
    return created(consumption_out(rec))


@bp.get("/households/<rid>/consumption-records")
@require_roles("PlatformAdmin", "SupportAgent")
def list_consumption(rid):
    hh = find("households", rid)
    items = [r for r in db["consumption"].values() if r["household_id"] == hh["id"]]
    items.sort(key=lambda r: r["period"], reverse=True)
    return list_ok(items, consumption_out)
