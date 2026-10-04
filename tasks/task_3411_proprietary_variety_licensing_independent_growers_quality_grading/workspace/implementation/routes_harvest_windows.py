"""HarvestWindow endpoints: plan, get, list."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import store
from errors import (
    err,
    ERR_HARVEST_WINDOW_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_VARIETY_NOT_FOUND,
)
from helpers import (
    as_dt,
    as_pos_int,
    as_str,
    body,
    dump,
    paginate,
    req_field,
    require_roles,
    success,
)

bp = Blueprint("harvest_windows", __name__)

ANY_ROLE = constants.ROLES


def get_window_or_404(window_id):
    w = store.db["harvest_windows"].get(window_id)
    if w is None:
        raise err(ERR_NOT_FOUND, "No harvest window with the given id")
    return w


@bp.route("/licensing/harvest-windows", methods=["POST"])
@require_roles("PlatformAdmin")
def create_harvest_window():
    b = body()
    region_code = as_str(req_field(b, "region_code"), "region_code")
    variety_id = as_str(req_field(b, "variety_id"), "variety_id")
    week_start = as_dt(req_field(b, "week_start"), "week_start")
    week_end = as_dt(req_field(b, "week_end"), "week_end")
    target_volume_kg = as_pos_int(req_field(b, "target_volume_kg"), "target_volume_kg")
    if week_end <= week_start:
        raise err(ERR_INVALID_REQUEST, "week_end must be after week_start")
    variety = store.db["varieties"].get(variety_id)
    if variety is None:
        raise err(ERR_VARIETY_NOT_FOUND, "No variety with the given id")
    # Half-open overlap on same (region_code, variety_id); pure adjacency allowed
    for w in store.db["harvest_windows"].values():
        if (
            w["region_code"] == region_code
            and w["variety_id"] == variety_id
            and w["week_start"] < week_end
            and week_start < w["week_end"]
        ):
            raise err(ERR_HARVEST_WINDOW_OVERLAP, "Harvest window overlaps an existing window")
    rec = store.init_record({
        "region_code": region_code,
        "variety_id": variety_id,
        "week_start": week_start,
        "week_end": week_end,
        "target_volume_kg": target_volume_kg,
        "booked_volume_kg": Decimal(0),
    })
    store.db["harvest_windows"][rec["id"]] = rec
    return success(dump(rec), code=201)


@bp.route("/licensing/harvest-windows/<harvestWindowId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_harvest_window(harvestWindowId):
    return success(dump(get_window_or_404(harvestWindowId)))


@bp.route("/licensing/harvest-windows", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_harvest_windows():
    items = list(store.db["harvest_windows"].values())
    for f in ("variety_id", "region_code"):
        val = request.args.get(f)
        if val is not None:
            items = [x for x in items if x.get(f) == val]
    page, pagination = paginate(items)
    return success(page, pagination=pagination)
