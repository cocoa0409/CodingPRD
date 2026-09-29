"""Attractions: registration, reads, ride cycles and the two computed reads."""

from flask import Blueprint, request

import calc
import derive
import fetch
import store
import validate
from auth import ALL_ROLES, require_roles
from envelope import list_response
from errors import fail, invalid, ERR_REGULATORY_HOLD_ACTIVE
from reply import computed, made, saved

bp = Blueprint("attractions", __name__)

PARK_AREAS = ("FRONTIER", "LAGOON", "SKYLINE", "KIDS_COVE")
RIDE_CLASSES = ("KIDDIE", "FAMILY", "THRILL", "WATER")

DEFAULT_MEAN_REPAIR_MINUTES = 120


@bp.post("/park-ops/attractions")
@require_roles("ParkOpsAdmin")
def create_attraction():
    data = validate.body()
    name = validate.str_field(data, "name", max_len=120)
    park_area = validate.enum_field(data, "park_area", PARK_AREAS)
    manufacturer = validate.str_field(data, "manufacturer")
    model_code = validate.str_field(data, "model_code")
    ride_class = validate.enum_field(data, "ride_class", RIDE_CLASSES)
    capacity = validate.int_field(data, "theoretical_hourly_capacity",
                                  minimum=1)
    min_operators = validate.int_field(data, "min_operators_required",
                                       minimum=1)
    parts_budget = validate.int_field(data, "parts_budget_cents", minimum=0)
    mean_repair = validate.int_field(data, "mean_repair_minutes",
                                     required=False, minimum=1,
                                     default=DEFAULT_MEAN_REPAIR_MINUTES)
    row = store.create(
        "attractions",
        name=name,
        park_area=park_area,
        manufacturer=manufacturer,
        model_code=model_code,
        ride_class=ride_class,
        theoretical_hourly_capacity=capacity,
        min_operators_required=min_operators,
        parts_budget_cents=parts_budget,
        mean_repair_minutes=mean_repair,
        cumulative_cycles=0,
    )
    return made(derive.ser_attraction, row)


@bp.get("/park-ops/attractions/<attraction_id>")
@require_roles(*ALL_ROLES)
def read_attraction(attraction_id):
    return computed(derive.ser_attraction(fetch.attraction(attraction_id)))


@bp.get("/park-ops/attractions")
@require_roles(*ALL_ROLES)
def list_attractions():
    return list_response(
        store.rows("attractions"),
        derive.ser_attraction,
        filters=(
            ("park_area", "str"),
            ("operational_posture", "str"),
            ("model_code", "str"),
            ("manufacturer", "str"),
            ("active_template_id", "str"),
        ),
        order=("created_at",),
    )


@bp.post("/park-ops/attractions/<attraction_id>/cycles")
@require_roles("MaintenanceTechnician", "RideOperator")
def log_cycles(attraction_id):
    attraction = fetch.attraction(attraction_id)
    data = validate.body()
    validate.date_field(data, "service_date")
    cycles_added = validate.int_field(data, "cycles_added", minimum=0)
    if derive.regulatory_hold(attraction):
        fail(ERR_REGULATORY_HOLD_ACTIVE,
             "A held attraction does not accumulate ride cycles.")
    attraction["cumulative_cycles"] += cycles_added
    return saved(derive.ser_attraction, attraction)


def _window_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    parsed = store.parse_date(raw)
    if parsed is None:
        invalid("%s must be a calendar date in YYYY-MM-DD form." % name)
    return parsed


@bp.get("/park-ops/attractions/<attraction_id>/capacity-impact")
@require_roles(*ALL_ROLES)
def capacity_impact(attraction_id):
    attraction = fetch.attraction(attraction_id)
    today = store.today()
    window_start = _window_param("window_start_date", today)
    window_end = _window_param("window_end_date", today)
    if window_end < window_start:
        invalid("window_end_date must be the same as or later than "
                "window_start_date.")
    return computed(calc.capacity_impact(attraction, window_start, window_end))


@bp.get("/park-ops/attractions/<attraction_id>/dispatch-readiness")
@require_roles(*ALL_ROLES)
def dispatch_readiness(attraction_id):
    attraction = fetch.attraction(attraction_id)
    return computed(calc.dispatch_readiness(attraction))
