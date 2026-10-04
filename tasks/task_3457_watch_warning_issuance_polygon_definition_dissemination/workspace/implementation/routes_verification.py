"""VerificationEvent and VerificationStatistic endpoints (PRD §3.8)."""
from flask import Blueprint, request

from auth import authenticate, require_role
from calculations import (
    compute_statistic,
    derive_performance_band,
    matched_products_for_event,
)
from constants import ADJUDICATION_OUTCOMES, HAZARD_TYPES, MATCHING_VARIANTS
from db import STORE, now
from errors import api_error
from serialize import serialize
from util import as_number, base_entity, envelope, get_body, list_response, parse_dt, touch

bp = Blueprint("verification", __name__, url_prefix="/alerts")

ANALYST = ["VerificationAnalyst"]
ANY_ROLE = ["PlatformAdmin", "Forecaster", "MeteorologistInCharge", "VerificationAnalyst", "EmergencyManager"]


def _get_event_or_404(event_id):
    event = STORE["vevents"].get(event_id)
    if event is None:
        raise api_error(
            "ERR_VERIFICATION_EVENT_NOT_FOUND", "VerificationEvent %s does not exist." % event_id
        )
    return event


@bp.post("/verification-events")
def create_event():
    role, _uid, _fc = authenticate()
    require_role(role, ANALYST)
    body = get_body()
    # tier 4: schema
    zone_id = body.get("zone_id")
    if not isinstance(zone_id, str) or not zone_id:
        raise api_error("ERR_INVALID_REQUEST", "zone_id is required.")
    hazard_type = body.get("hazard_type")
    if hazard_type not in HAZARD_TYPES:
        raise api_error("ERR_INVALID_REQUEST", "hazard_type must be one of %s" % HAZARD_TYPES)
    observed_at = parse_dt(body.get("observed_at"))
    if observed_at is None:
        raise api_error("ERR_INVALID_REQUEST", "observed_at is required and must be ISO 8601.")
    location_lat = as_number(body.get("location_lat"))
    location_lon = as_number(body.get("location_lon"))
    if location_lat is None or location_lon is None:
        raise api_error("ERR_INVALID_REQUEST", "location_lat and location_lon must be numbers.")
    magnitude = body.get("magnitude")
    if not isinstance(magnitude, str) or not magnitude:
        raise api_error("ERR_INVALID_REQUEST", "magnitude is required.")
    storm_event_id = body.get("storm_event_id")
    if storm_event_id is not None and not isinstance(storm_event_id, str):
        raise api_error("ERR_INVALID_REQUEST", "storm_event_id must be a string.")
    # tier 5: body FK existence (zone, then storm)
    if STORE["zones"].get(zone_id) is None:
        raise api_error("ERR_ZONE_NOT_FOUND", "CountyZone %s does not exist." % zone_id)
    if storm_event_id and STORE["storms"].get(storm_event_id) is None:
        raise api_error("ERR_STORM_EVENT_NOT_FOUND", "StormEvent %s does not exist." % storm_event_id)
    event = base_entity()
    event.update({
        "zone_id": zone_id,
        "storm_event_id": storm_event_id,
        "hazard_type": hazard_type,
        "observed_at": observed_at,
        "location_lat": location_lat,
        "location_lon": location_lon,
        "magnitude": magnitude,
        "status": "REPORTED",
        "matched_product_ids": [],
        "adjudicated_at": None,
    })
    STORE["vevents"][event["id"]] = event
    return envelope(serialize(event), "object", 201)


@bp.get("/verification-events/<event_id>")
def get_event(event_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    return envelope(serialize(_get_event_or_404(event_id)), "object", 200)


@bp.get("/verification-events")
def list_events():
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    rows = list(STORE["vevents"].values())
    for field in ("zone_id", "storm_event_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [e for e in rows if e.get(field) == value]
    return list_response(rows, serialize)


@bp.post("/verification-events/<event_id>/adjudicate")
def adjudicate_event(event_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANALYST)
    body = get_body()
    outcome = body.get("outcome")
    if outcome not in ADJUDICATION_OUTCOMES:
        raise api_error("ERR_INVALID_REQUEST", "outcome must be one of %s" % ADJUDICATION_OUTCOMES)
    event = _get_event_or_404(event_id)
    if event["status"] != "REPORTED":
        raise api_error("ERR_INVALID_EVENT_STATE", "VerificationEvent is no longer REPORTED.")
    stamp = now()
    event["adjudicated_at"] = stamp
    if outcome == "REJECTED":
        event["status"] = "REJECTED"
        touch(event)
        return envelope(serialize(event), "object", 200)
    # CONFIRMED: POLYGON_STRICT matching across all offices' products
    event["status"] = "CONFIRMED"
    matches = matched_products_for_event(event)
    event["matched_product_ids"] = [p["id"] for p in matches]
    touch(event)
    for product in matches:
        was_zero = product["verified_event_count"] == 0
        product["verified_event_count"] += 1
        if was_zero and product["verified_event_count"] >= 1:
            product["verification_status"] = "VERIFIED"
        touch(product)
    return envelope(serialize(event), "object", 200)


@bp.post("/verification-statistics")
def create_statistic():
    role, _uid, _fc = authenticate()
    require_role(role, ANALYST)
    body = get_body()
    # tier 4: schema
    office_id = body.get("office_id")
    if not isinstance(office_id, str) or not office_id:
        raise api_error("ERR_INVALID_REQUEST", "office_id is required.")
    hazard_type = body.get("hazard_type")
    if hazard_type not in HAZARD_TYPES:
        raise api_error("ERR_INVALID_REQUEST", "hazard_type must be one of %s" % HAZARD_TYPES)
    period_start = parse_dt(body.get("period_start"))
    period_end = parse_dt(body.get("period_end"))
    if period_start is None or period_end is None:
        raise api_error("ERR_INVALID_REQUEST", "period_start and period_end must be ISO 8601.")
    matching_variant = body.get("matching_variant")
    if matching_variant not in MATCHING_VARIANTS:
        raise api_error("ERR_INVALID_REQUEST", "matching_variant must be one of %s" % MATCHING_VARIANTS)
    # tier 5: office FK existence
    office = STORE["offices"].get(office_id)
    if office is None:
        raise api_error("ERR_OFFICE_NOT_FOUND", "ForecastOffice %s does not exist." % office_id)
    measures = compute_statistic(office_id, hazard_type, period_start, period_end, matching_variant)
    stamp = now()
    statistic = base_entity()
    statistic.update({
        "office_id": office_id,
        "hazard_type": hazard_type,
        "period_start": period_start,
        "period_end": period_end,
        "matching_variant": matching_variant,
        "computed_at": stamp,
    })
    statistic.update(measures)
    STORE["stats"][statistic["id"]] = statistic
    # cascade onto the office under review
    office["performance_band"] = derive_performance_band(statistic)
    office["last_statistic_at"] = stamp
    touch(office)
    return envelope(serialize(statistic), "object", 201)
