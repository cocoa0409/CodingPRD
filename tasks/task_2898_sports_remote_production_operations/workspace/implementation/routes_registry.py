"""Registry surfaces: trucks, transmission paths, crew members, data feeds, logical clock."""

from flask import Blueprint

import domain
import store
from core import (
    ApiError,
    OPERATOR_ROLES,
    Payload,
    ROLE_LEAGUE_OPERATIONS,
    ROLE_PRODUCTION_MANAGER,
    ROLE_TECHNICAL_DIRECTOR,
    actor_id,
    invalid,
    now_utc,
    page_result,
    query_enum,
    query_string,
    require_roles,
    respond_object,
    set_now,
)

bp = Blueprint("registry", __name__, url_prefix="/broadcast-ops")


# ---------------------------------------------------------------------------
# ProductionTruck
# ---------------------------------------------------------------------------
@bp.post("/trucks")
@require_roles(ROLE_PRODUCTION_MANAGER)
def create_truck():
    body = Payload()
    truck_code = body.string("truck_code")
    tier_rating = body.enum("tier_rating", domain.EVENT_TIERS)
    channels = body.integer("camera_channel_capacity", minimum=1)
    power = body.integer("power_draw_amps", minimum=0)
    home_base = body.string("home_base_code")
    engine_hours = body.number("engine_hours_since_service", required=False, default=0, minimum=0)
    interval = body.integer("service_interval_hours", required=False, default=500, minimum=1)
    for existing in store.TRUCKS.values():
        if existing["truck_code"] == truck_code:
            raise invalid("truck_code must be unique across trucks.")

    row = store.new_row(
        truck_code=truck_code,
        tier_rating=tier_rating,
        camera_channel_capacity=channels,
        power_draw_amps=power,
        home_base_code=home_base,
        engine_hours_since_service=engine_hours,
        service_interval_hours=interval,
        hours_to_service=interval - engine_hours,
        last_service_completed_at=None,
        status="AVAILABLE",
    )
    store.TRUCKS[row["id"]] = row
    return respond_object(domain.truck_json(row), 201)


@bp.get("/trucks/<truck_id>")
@require_roles(*OPERATOR_ROLES)
def read_truck(truck_id):
    return respond_object(domain.truck_json(store.find_truck(truck_id)))


@bp.get("/trucks")
@require_roles(*OPERATOR_ROLES)
def list_trucks():
    status = query_enum("status", domain.TRUCK_STATUSES)
    tier = query_enum("tier_rating", domain.EVENT_TIERS)
    rows = store.ordered(store.TRUCKS)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if tier is not None:
        rows = [r for r in rows if r["tier_rating"] == tier]
    return page_result(rows, domain.truck_json)


@bp.post("/trucks/<truck_id>/arrive")
@require_roles(ROLE_PRODUCTION_MANAGER)
def truck_arrive(truck_id):
    truck = store.find_truck(truck_id)
    if truck["status"] != "IN_TRANSIT":
        raise ApiError(
            "ERR_TRUCK_STATE_INVALID", "Only an IN_TRANSIT truck may record an arrival.", 409
        )
    if truck["engine_hours_since_service"] >= truck["service_interval_hours"]:
        store.set_fields(truck, status="IN_MAINTENANCE")
    else:
        store.set_fields(truck, status="AVAILABLE")
    return respond_object(domain.truck_json(truck))


@bp.post("/trucks/<truck_id>/service-complete")
@require_roles(ROLE_PRODUCTION_MANAGER)
def truck_service_complete(truck_id):
    truck = store.find_truck(truck_id)
    if truck["status"] != "IN_MAINTENANCE":
        raise ApiError(
            "ERR_TRUCK_STATE_INVALID",
            "Only an IN_MAINTENANCE truck may close out a service cycle.",
            409,
        )
    store.set_fields(
        truck,
        status="AVAILABLE",
        engine_hours_since_service=0,
        hours_to_service=truck["service_interval_hours"],
        last_service_completed_at=now_utc(),
    )
    return respond_object(domain.truck_json(truck))


# ---------------------------------------------------------------------------
# TransmissionPath
# ---------------------------------------------------------------------------
@bp.post("/transmission-paths")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def create_path():
    body = Payload()
    row = store.new_row(
        path_code=body.string("path_code"),
        path_type=body.enum("path_type", domain.PATH_TYPES),
        carrier_code=body.string("carrier_code"),
        capacity_mbps=body.integer("capacity_mbps", minimum=1),
        guard_band_minutes=body.integer(
            "guard_band_minutes", required=False, default=10, minimum=0
        ),
        redundancy_class=body.enum("redundancy_class", domain.REDUNDANCY_CLASSES),
        committed_mbps_total=0,
        active_booking_count=0,
    )
    store.PATHS[row["id"]] = row
    return respond_object(domain.path_json(row), 201)


@bp.get("/transmission-paths/<path_id>")
@require_roles(*OPERATOR_ROLES)
def read_path(path_id):
    return respond_object(domain.path_json(store.find_path(path_id)))


# ---------------------------------------------------------------------------
# CrewMember
# ---------------------------------------------------------------------------
@bp.post("/crew-members")
@require_roles(ROLE_PRODUCTION_MANAGER)
def create_crew_member():
    body = Payload()
    row = store.new_row(
        full_name=body.string("full_name"),
        position=body.enum("position", domain.CREW_POSITIONS),
        employment_type=body.enum("employment_type", domain.EMPLOYMENT_TYPES),
        union_local=body.string("union_local"),
        certified_tiers=body.enum_array("certified_tiers", domain.EVENT_TIERS),
        hourly_rate_cents=body.integer("hourly_rate_cents", minimum=1),
        home_base_code=body.string("home_base_code"),
        lifetime_meal_penalty_units=0,
    )
    store.CREW_MEMBERS[row["id"]] = row
    return respond_object(domain.crew_member_json(row), 201)


@bp.get("/crew-members/<member_id>")
@require_roles(*OPERATOR_ROLES)
def read_crew_member(member_id):
    return respond_object(domain.crew_member_json(store.find_crew_member(member_id)))


# ---------------------------------------------------------------------------
# DataFeed
# ---------------------------------------------------------------------------
@bp.post("/data-feeds")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def create_feed():
    body = Payload()
    row = store.new_row(
        provider_code=body.string("provider_code"),
        feed_kind=body.enum("feed_kind", domain.FEED_KINDS),
        latency_ms=body.integer("latency_ms", minimum=0),
        contract_expiry_utc=body.instant("contract_expiry_utc"),
        max_concurrent_consumers=body.integer(
            "max_concurrent_consumers", required=False, default=2, minimum=1
        ),
        active_consumer_count=0,
        status="ACTIVE",
    )
    store.FEEDS[row["id"]] = row
    return respond_object(domain.feed_json(row), 201)


@bp.get("/data-feeds/<feed_id>")
@require_roles(*OPERATOR_ROLES)
def read_feed(feed_id):
    return respond_object(domain.feed_json(store.find_feed(feed_id)))


@bp.post("/data-feeds/<feed_id>/suspend")
@require_roles(ROLE_LEAGUE_OPERATIONS)
def suspend_feed(feed_id):
    feed = store.find_feed(feed_id)
    if feed["status"] != "ACTIVE":
        raise ApiError("ERR_FEED_STATE_INVALID", "The data feed is not ACTIVE.", 409)

    store.set_fields(feed, status="SUSPENDED")

    affected = []
    for prep in store.ordered(store.PREPS):
        if prep["data_feed_id"] != feed["id"] or prep["status"] != "VALIDATED":
            continue
        store.set_fields(prep, status="PENDING", feed_validated_at=None)
        production = store.PRODUCTIONS.get(prep["production_id"])
        if production is not None and production["id"] not in [p["id"] for p in affected]:
            affected.append(production)

    domain.recompute_feed_consumers(feed)
    for production in affected:
        domain.recompute_production_stage(production)
    return respond_object(domain.feed_json(feed))


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@require_roles(*OPERATOR_ROLES)
def set_clock():
    body = Payload()
    _present, parsed = body.raw_instant("to_iso8601")
    if parsed is None:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW", "to_iso8601 must be a valid ISO-8601 instant.", 422
        )
    set_now(parsed)
    return respond_object({})
