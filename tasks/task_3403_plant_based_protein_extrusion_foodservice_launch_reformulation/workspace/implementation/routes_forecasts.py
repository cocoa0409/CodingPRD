# DemandForecast domain (PRD 3.8): weekly product/channel forecasts keyed by
# the unique (product_id, channel, week_start) triple, PROVISIONAL -> LOCKED ->
# ACTUALIZED with the variance/miss scorecard.
from flask import Blueprint, request

import constants
from errors import err
from middleware import authenticate, authorize
from response import paginate, success
from services import compute_variance
from store import db, flush_dirty, make_entity, mark, public
from validation import Shape, body_json, get_dt, get_enum, get_int, get_str

bp = Blueprint("forecasts", __name__, url_prefix="/protein-ops/demand-forecasts")

ANY_ROLE = constants.ROLES
FORECAST_STATES = ["PROVISIONAL", "LOCKED", "ACTUALIZED"]
FORECAST_TRANSITIONS = {
    ("PROVISIONAL", "LOCKED"),
    ("LOCKED", "ACTUALIZED"),
}


@bp.route("", methods=["POST"])
def create_forecast():
    _user_id, role = authenticate()
    authorize(role, ["DemandPlanner"])

    body = body_json()
    shape = Shape()
    product_id = get_str(body, "product_id", shape)
    channel = get_enum(body, "channel", constants.CHANNELS, shape)
    week_raw, week_dt = get_dt(body, "week_start", shape)
    forecast_cases = get_int(body, "forecast_cases", shape, minv=1)

    # Tier 3: body FK existence (product_id).
    if product_id is not None and product_id not in db["products"]:
        raise err("ERR_NOT_FOUND", "product_id does not reference a product")

    # Tier 8: (product_id, channel, week_start) unique — week_start compared by
    # instant, not raw string.
    if product_id is not None and channel is not None and week_dt is not None:
        for existing in db["forecasts"].values():
            if (
                existing["product_id"] == product_id
                and existing["channel"] == channel
                and existing["_dt"]["week_start"] == week_dt
            ):
                raise err("ERR_UNIQUE_CONSTRAINT", "(product_id, channel, week_start) already exists")
    shape.raise_if_any()

    forecast = make_entity(
        "forecasts",
        {
            "product_id": product_id,
            "channel": channel,
            "week_start": week_raw,
            "forecast_cases": forecast_cases,
            "actual_cases": None,
            "variance_pct": None,
            "is_miss": None,
            "status": "PROVISIONAL",
        },
    )
    forecast["_dt"]["week_start"] = week_dt
    return success(public(forecast), "object", 201)


@bp.route("", methods=["GET"])
def list_forecasts():
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    items = list(db["forecasts"].values())
    for param in ("product_id", "channel", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [f for f in items if f.get(param) == value]
    items.sort(key=lambda f: (f["created_at"], f["_seq"]))
    page, meta = paginate([public(f) for f in items], request.args)
    return success(page, "array", 200, pagination=meta)


@bp.route("/<fid>", methods=["GET"])
def get_forecast(fid):
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    forecast = db["forecasts"].get(fid)
    if forecast is None:
        raise err("ERR_NOT_FOUND", "demand forecast not found")
    return success(public(forecast), "object", 200)


@bp.route("/<fid>/transitions", methods=["POST"])
def forecast_transition(fid):
    _user_id, role = authenticate()
    authorize(role, ["DemandPlanner"])

    forecast = db["forecasts"].get(fid)
    if forecast is None:
        raise err("ERR_NOT_FOUND", "demand forecast not found")

    body = body_json()
    shape = Shape()
    target = get_enum(body, "target_status", FORECAST_STATES, shape)
    actual_cases = get_int(body, "actual_cases", shape, required=False, minv=0)

    # Tier 5: transition must exist from the current state (ACTUALIZED is
    # terminal and rejects everything).
    if target is not None and (forecast["status"], target) not in FORECAST_TRANSITIONS:
        raise err("ERR_INVALID_STATE", "no forecast transition %s -> %s" % (forecast["status"], target))

    if target == "ACTUALIZED":
        # Tier 11: actual_cases is required (zero or more) to actualize.
        if actual_cases is None:
            shape.add("actual_cases", "is required when target_status is ACTUALIZED")
        shape.raise_if_any()
        variance, is_miss = compute_variance(forecast["forecast_cases"], actual_cases)
        forecast["actual_cases"] = actual_cases
        forecast["variance_pct"] = variance
        forecast["is_miss"] = is_miss
    else:
        shape.raise_if_any()

    forecast["status"] = target
    mark(forecast)
    flush_dirty()
    return success(public(forecast), "object", 200)
