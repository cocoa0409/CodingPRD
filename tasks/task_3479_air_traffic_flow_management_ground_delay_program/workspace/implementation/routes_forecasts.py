"""CapacityForecast endpoints (PRD 3.3): compute, list, publish."""

from flask import Blueprint, request

from capacity import compute_forecast
from constants import FORECAST_VARIANTS, ROLE_FLOW_MANAGER, ROLES
from errors import ApiError
from serialize import serialize_forecast
from storage import DB, create_entity, get_clock, touch
from util import body_json, paginate, req_dt, req_enum, success_object
from validation import auth_context, check_window, get_facility, get_forecast, require_roles

bp = Blueprint("forecasts", __name__)


@bp.route("/atfm/facilities/<facility_id>/capacity-forecasts", methods=["POST"])
def create_forecast(facility_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    facility = get_facility(facility_id)
    body = body_json()
    variant = req_enum(body, "variant", FORECAST_VARIANTS)
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    check_window(window_start, window_end)
    # The computation runs once, at creation, and is immutable thereafter.
    predicted, included = compute_forecast(facility, variant, window_start, window_end)
    rec = create_entity(
        "forecasts",
        {
            "facility_id": facility["id"],
            "variant": variant,
            "window_start": window_start,
            "window_end": window_end,
            "included_event_ids": included,
            "predicted_acceptance_rate": predicted,
            "status": "DRAFT",
            "published_at": None,
        },
    )
    return success_object(serialize_forecast(rec), 201)


@bp.route("/atfm/facilities/<facility_id>/capacity-forecasts", methods=["GET"])
def list_forecasts(facility_id):
    auth_context()
    require_roles(*ROLES)
    facility = get_facility(facility_id)
    status_filter = request.args.get("status")
    variant_filter = request.args.get("variant")
    rows = [
        f
        for f in DB["forecasts"].values()
        if f["facility_id"] == facility["id"]
        and (status_filter is None or f["status"] == status_filter)
        and (variant_filter is None or f["variant"] == variant_filter)
    ]
    rows.sort(key=lambda f: (f["created_at"], f["_seq"]))
    return paginate([serialize_forecast(f) for f in rows])


@bp.route("/atfm/capacity-forecasts/<forecast_id>/publish", methods=["POST"])
def publish_forecast(forecast_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    forecast = get_forecast(forecast_id)
    if forecast["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", "only a DRAFT forecast can be published"
        )
    forecast["status"] = "PUBLISHED"
    forecast["published_at"] = get_clock()
    touch(forecast)
    return success_object(serialize_forecast(forecast))
