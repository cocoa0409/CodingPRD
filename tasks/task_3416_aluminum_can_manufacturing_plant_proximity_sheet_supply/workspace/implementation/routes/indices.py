"""Metal price index publication (period unique globally)."""
from flask import Blueprint

from db import store, new_id, now_iso
from errors import ApiError, ERR_DUPLICATE_PERIOD
from middleware import actor, require_role
from response import ok_object
from services import calc
from services.serialize import index_public
from validation import body_json, req_str, req_num, parse_period

bp = Blueprint("indices", __name__)


@bp.post("/metal-price-indices")
def create_index():
    _, role = actor()
    require_role(role, ["PlatformAdmin"])
    data = body_json()
    period = parse_period(req_str(data, "period"), "period")
    index_cents_per_lb = req_num(data, "index_cents_per_lb", gt=0)
    if calc.find_index(period) is not None:
        raise ApiError(ERR_DUPLICATE_PERIOD[0], ERR_DUPLICATE_PERIOD[1],
                       "A metal price index for period %s already exists." % period)
    row = {
        "id": new_id(),
        "period": period,
        "index_cents_per_lb": index_cents_per_lb,
        "created_at": now_iso(),
    }
    store["indices"][row["id"]] = row
    return ok_object(index_public(row), code=201)
