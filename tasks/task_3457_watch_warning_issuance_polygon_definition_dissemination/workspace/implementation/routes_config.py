"""Configuration endpoints: offices, zones, neighbor agreements, alert
channels, forecasters, and office sub-collection reads."""
from flask import Blueprint

from auth import authenticate, require_role
from constants import (
    AREA_METHODS,
    CHANNEL_STATUSES,
    CHANNEL_TYPES,
    DEFAULT_COORDINATION_TIMEOUT_MINUTES,
    FORECASTER_LEVELS,
    HAZARD_TYPES,
    POPULATION_TIERS,
    PRODUCT_LEVELS,
    WEA_ABSOLUTE_MAX_CHARS,
)
from db import STORE
from errors import api_error
from serialize import serialize
from util import as_int, as_number, base_entity, envelope, get_body, list_response

bp = Blueprint("config", __name__, url_prefix="/alerts")

ADMIN = ["PlatformAdmin"]
ANY_ROLE = ["PlatformAdmin", "Forecaster", "MeteorologistInCharge", "VerificationAnalyst", "EmergencyManager"]


def _require_str(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not value:
        raise api_error("ERR_INVALID_REQUEST", "Missing or invalid required field: %s" % field)
    return value


def _get_office_or_404(office_id):
    office = STORE["offices"].get(office_id)
    if office is None:
        raise api_error("ERR_OFFICE_NOT_FOUND", "ForecastOffice %s does not exist." % office_id)
    return office


# ---------------------------------------------------------------------------
# ForecastOffice
# ---------------------------------------------------------------------------
@bp.post("/offices")
def create_office():
    role, _uid, _fc = authenticate()
    require_role(role, ADMIN)
    body = get_body()
    office_code = _require_str(body, "office_code")
    name = _require_str(body, "name")
    region = _require_str(body, "region")
    area_method = body.get("area_method", "PLANAR")
    if area_method not in AREA_METHODS:
        raise api_error("ERR_INVALID_REQUEST", "area_method must be one of %s" % AREA_METHODS)
    # constraint: office_code is unique across the network
    for existing in STORE["offices"].values():
        if existing["office_code"] == office_code:
            raise api_error("ERR_INVALID_REQUEST", "office_code must be unique.")
    office = base_entity()
    office.update({
        "office_code": office_code,
        "name": name,
        "region": region,
        "area_method": area_method,
        "performance_band": "SATISFACTORY",
        "last_statistic_at": None,
    })
    STORE["offices"][office["id"]] = office
    return envelope(serialize(office), "object", 201)


@bp.get("/offices/<office_id>")
def get_office(office_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    return envelope(serialize(_get_office_or_404(office_id)), "object", 200)


@bp.get("/offices/<office_id>/zones")
def list_office_zones(office_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    _get_office_or_404(office_id)
    zones = [z for z in STORE["zones"].values() if z["office_id"] == office_id]
    return list_response(zones, serialize)


@bp.get("/offices/<office_id>/forecasters")
def list_office_forecasters(office_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    _get_office_or_404(office_id)
    rows = [f for f in STORE["forecasters"].values() if f["office_id"] == office_id]
    return list_response(rows, serialize)


@bp.get("/offices/<office_id>/neighbor-agreements")
def list_office_agreements(office_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    _get_office_or_404(office_id)
    rows = [
        a for a in STORE["agreements"].values()
        if a["office_a_id"] == office_id or a["office_b_id"] == office_id
    ]
    return list_response(rows, serialize)


@bp.get("/offices/<office_id>/storm-events")
def list_office_storms(office_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    _get_office_or_404(office_id)
    rows = [s for s in STORE["storms"].values() if s["office_id"] == office_id]
    rows = _apply_filter(rows, "status")
    return list_response(rows, serialize)


@bp.get("/offices/<office_id>/verification-statistics")
def list_office_stats(office_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    _get_office_or_404(office_id)
    rows = [s for s in STORE["stats"].values() if s["office_id"] == office_id]
    rows = _apply_filter(rows, "hazard_type")
    return list_response(rows, serialize)


def _apply_filter(rows, field):
    from flask import request
    value = request.args.get(field)
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


# ---------------------------------------------------------------------------
# CountyZone
# ---------------------------------------------------------------------------
@bp.post("/zones")
def create_zone():
    role, _uid, _fc = authenticate()
    require_role(role, ADMIN)
    body = get_body()
    zone_code = _require_str(body, "zone_code")
    name = _require_str(body, "name")
    office_id = body.get("office_id")
    if not isinstance(office_id, str) or not office_id:
        raise api_error("ERR_INVALID_REQUEST", "office_id is required.")
    population_tier = body.get("population_tier")
    if population_tier not in POPULATION_TIERS:
        raise api_error("ERR_INVALID_REQUEST", "population_tier must be one of %s" % POPULATION_TIERS)
    bounds = {}
    for field in ("lat_min", "lat_max", "lon_min", "lon_max", "surveyed_area_sq_km"):
        value = as_number(body.get(field))
        if value is None:
            raise api_error("ERR_INVALID_REQUEST", "%s must be a number." % field)
        bounds[field] = value
    if not bounds["lat_max"] > bounds["lat_min"]:
        raise api_error("ERR_INVALID_REQUEST", "lat_max must be strictly greater than lat_min.")
    if not bounds["lon_max"] > bounds["lon_min"]:
        raise api_error("ERR_INVALID_REQUEST", "lon_max must be strictly greater than lon_min.")
    coastal = body.get("coastal", False)
    if not isinstance(coastal, bool):
        raise api_error("ERR_INVALID_REQUEST", "coastal must be a boolean.")
    # existence (tier 5): office FK
    _get_office_or_404(office_id)
    # constraint: zone_code is unique across the network
    for existing in STORE["zones"].values():
        if existing["zone_code"] == zone_code:
            raise api_error("ERR_INVALID_REQUEST", "zone_code must be unique.")
    zone = base_entity()
    zone.update({
        "zone_code": zone_code,
        "name": name,
        "office_id": office_id,
        "lat_min": bounds["lat_min"],
        "lat_max": bounds["lat_max"],
        "lon_min": bounds["lon_min"],
        "lon_max": bounds["lon_max"],
        "surveyed_area_sq_km": bounds["surveyed_area_sq_km"],
        "population_tier": population_tier,
        "coastal": coastal,
    })
    STORE["zones"][zone["id"]] = zone
    return envelope(serialize(zone), "object", 201)


# ---------------------------------------------------------------------------
# NeighborAgreement
# ---------------------------------------------------------------------------
@bp.post("/neighbor-agreements")
def create_agreement():
    role, _uid, _fc = authenticate()
    require_role(role, ADMIN)
    body = get_body()
    office_a_id = body.get("office_a_id")
    office_b_id = body.get("office_b_id")
    if not isinstance(office_a_id, str) or not isinstance(office_b_id, str):
        raise api_error("ERR_INVALID_REQUEST", "office_a_id and office_b_id are required.")
    hazard_types = body.get("hazard_types")
    if not isinstance(hazard_types, list) or any(h not in HAZARD_TYPES for h in hazard_types):
        raise api_error("ERR_INVALID_REQUEST", "hazard_types must be a list of hazard enums.")
    timeout = body.get("coordination_timeout_minutes", DEFAULT_COORDINATION_TIMEOUT_MINUTES)
    timeout = as_int(timeout)
    if timeout is None:
        raise api_error("ERR_INVALID_REQUEST", "coordination_timeout_minutes must be an integer.")
    # existence (tier 5)
    _get_office_or_404(office_a_id)
    _get_office_or_404(office_b_id)
    # constraint (tier 10): the unordered office pair is unique
    for existing in STORE["agreements"].values():
        if {existing["office_a_id"], existing["office_b_id"]} == {office_a_id, office_b_id}:
            raise api_error(
                "ERR_DUPLICATE_AGREEMENT",
                "A NeighborAgreement already exists for this unordered office pair.",
            )
    agreement = base_entity()
    agreement.update({
        "office_a_id": office_a_id,
        "office_b_id": office_b_id,
        "hazard_types": list(hazard_types),
        "coordination_timeout_minutes": timeout,
    })
    STORE["agreements"][agreement["id"]] = agreement
    return envelope(serialize(agreement), "object", 201)


# ---------------------------------------------------------------------------
# AlertChannel
# ---------------------------------------------------------------------------
@bp.post("/alert-channels")
def create_channel():
    role, _uid, _fc = authenticate()
    require_role(role, ADMIN)
    body = get_body()
    name = _require_str(body, "name")
    channel_type = body.get("channel_type")
    if channel_type not in CHANNEL_TYPES:
        raise api_error("ERR_INVALID_REQUEST", "channel_type must be one of %s" % CHANNEL_TYPES)
    supports_levels = body.get("supports_levels")
    if not isinstance(supports_levels, list) or any(l not in PRODUCT_LEVELS for l in supports_levels):
        raise api_error("ERR_INVALID_REQUEST", "supports_levels must be a list of product levels.")
    max_message_chars = as_int(body.get("max_message_chars"))
    if max_message_chars is None:
        raise api_error("ERR_INVALID_REQUEST", "max_message_chars must be an integer.")
    if channel_type == "WEA" and max_message_chars > WEA_ABSOLUTE_MAX_CHARS:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "WEA channels must declare max_message_chars <= %d." % WEA_ABSOLUTE_MAX_CHARS,
        )
    requires_confirmation = body.get("requires_confirmation", False)
    if not isinstance(requires_confirmation, bool):
        raise api_error("ERR_INVALID_REQUEST", "requires_confirmation must be a boolean.")
    status = body.get("status", "ACTIVE")
    if status not in CHANNEL_STATUSES:
        raise api_error("ERR_INVALID_REQUEST", "status must be one of %s" % CHANNEL_STATUSES)
    # constraint: channel name is unique across the network
    for existing in STORE["channels"].values():
        if existing["name"] == name:
            raise api_error("ERR_INVALID_REQUEST", "name must be unique.")
    channel = base_entity()
    channel.update({
        "name": name,
        "channel_type": channel_type,
        "supports_levels": list(supports_levels),
        "max_message_chars": max_message_chars,
        "requires_confirmation": requires_confirmation,
        "status": status,
    })
    STORE["channels"][channel["id"]] = channel
    return envelope(serialize(channel), "object", 201)


# ---------------------------------------------------------------------------
# Forecaster
# ---------------------------------------------------------------------------
@bp.post("/forecasters")
def create_forecaster():
    role, _uid, _fc = authenticate()
    require_role(role, ADMIN)
    body = get_body()
    office_id = body.get("office_id")
    if not isinstance(office_id, str) or not office_id:
        raise api_error("ERR_INVALID_REQUEST", "office_id is required.")
    full_name = _require_str(body, "full_name")
    employee_code = _require_str(body, "employee_code")
    level = body.get("level")
    if level not in FORECASTER_LEVELS:
        raise api_error("ERR_INVALID_REQUEST", "level must be one of %s" % FORECASTER_LEVELS)
    _get_office_or_404(office_id)
    # constraint: employee_code is unique across the network
    for existing in STORE["forecasters"].values():
        if existing["employee_code"] == employee_code:
            raise api_error("ERR_INVALID_REQUEST", "employee_code must be unique.")
    forecaster = base_entity()
    forecaster.update({
        "office_id": office_id,
        "full_name": full_name,
        "employee_code": employee_code,
        "level": level,
    })
    STORE["forecasters"][forecaster["id"]] = forecaster
    return envelope(serialize(forecaster), "object", 201)
