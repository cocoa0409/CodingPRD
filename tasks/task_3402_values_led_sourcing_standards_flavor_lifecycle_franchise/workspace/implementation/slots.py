"""Plant production slots (PRD sections 2.10 and 3.4).

capacity_units = ceil(planned_pints/100 * chunk_factor * swirl_factor), where
chunk_factor is 1.5 when chunk_load_pct >= 20 (else 1.0) and swirl_factor is
1.25 when swirl_load_pct >= 15 (else 1.0); the factors multiply. The
plant-shift pool sums capacity_units over PLANNED/CONFIRMED slots in the same
(plant, date, shift) bucket against the plant's per-shift budget. Creation
applies the date check first and the capacity check second.
"""
from datetime import date
from decimal import Decimal, ROUND_CEILING

from flask import Blueprint, request

from auth import authenticate, authorize
from db import LOGICAL_CLOCK, STORE, new_resource, public, sorted_items, touch
from envelope import ok, ok_list, pagination_args
from errors import fail
from flavors import get_flavor
from validate import (PLANT_CODES, SHIFTS, get_body, req_date, req_enum,
                      req_int, req_str)

bp = Blueprint("slots", __name__)

CHUNK_HEAVY_THRESHOLD_PCT = 20
CHUNK_FACTOR = Decimal("1.5")
SWIRL_HEAVY_THRESHOLD_PCT = 15
SWIRL_FACTOR = Decimal("1.25")
PLANT_SHIFT_CAPACITY_UNITS = {
    "VT_WATERBURY": 1000,
    "VT_ST_ALBANS": 800,
    "NL_HELLENDOORN": 600,
}

SCHEDULABLE_FLAVOR_STATES = ("TEST_BATCH", "LIMITED_RUN", "CORE_LINE")


def get_slot(sid):
    s = STORE["slots"].get(sid)
    if s is None:
        fail("ERR_SLOT_NOT_FOUND", "ProductionSlot id does not exist")
    return s


def capacity_units_for(flavor, planned_pints):
    chunk_factor = (CHUNK_FACTOR
                    if Decimal(str(flavor["chunk_load_pct"]))
                    >= CHUNK_HEAVY_THRESHOLD_PCT else Decimal("1"))
    swirl_factor = (SWIRL_FACTOR
                    if Decimal(str(flavor["swirl_load_pct"]))
                    >= SWIRL_HEAVY_THRESHOLD_PCT else Decimal("1"))
    raw = (Decimal(planned_pints) / Decimal(100)) * chunk_factor * swirl_factor
    return int(raw.to_integral_value(rounding=ROUND_CEILING))


def pool_usage(plant_code, production_date, shift, exclude_id=None):
    total = 0
    for s in STORE["slots"].values():
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        if (s["plant_code"] == plant_code
                and s["production_date"] == production_date
                and s["shift"] == shift
                and s["status"] in ("PLANNED", "CONFIRMED")):
            total += s["capacity_units"]
    return total


def _check_capacity(plant_code, production_date, shift, units,
                    exclude_id=None):
    budget = PLANT_SHIFT_CAPACITY_UNITS[plant_code]
    used = pool_usage(plant_code, production_date, shift, exclude_id)
    if used + units > budget:
        fail("ERR_PLANT_CAPACITY_EXCEEDED",
             "The plant-shift capacity-unit pool would be exceeded")


@bp.post("/production-slots")
def create_slot():
    _, role = authenticate()
    authorize(role, ("PlantScheduler",))
    body = get_body()
    plant_code = req_enum(body, "plant_code", PLANT_CODES)
    flavor_id = req_str(body, "flavor_id")
    production_date = req_date(body, "production_date")
    shift = req_enum(body, "shift", SHIFTS)
    planned_pints = req_int(body, "planned_pints", 1)
    flavor = STORE["flavors"].get(flavor_id)
    if flavor is None:
        fail("ERR_FLAVOR_NOT_FOUND",
             "flavor_id references a flavor that does not exist")
    # Date check first, capacity check second.
    if date.fromisoformat(production_date) < LOGICAL_CLOCK["now"].date():
        fail("ERR_SLOT_DATE_PAST",
             "production_date may not be before the current logical date")
    units = capacity_units_for(flavor, planned_pints)
    _check_capacity(plant_code, production_date, shift, units)
    r = new_resource()
    r.update({
        "plant_code": plant_code,
        "flavor_id": flavor_id,
        "production_date": production_date,
        "shift": shift,
        "planned_pints": planned_pints,
        "capacity_units": units,
        "status": "PLANNED",
    })
    STORE["slots"][r["id"]] = r
    return ok(public(r), 201)


@bp.get("/production-slots")
def list_slots():
    _, role = authenticate()
    authorize(role, ("PlantScheduler", "FlavorManager"))
    items = list(STORE["slots"].values())
    flavor_id = request.args.get("flavor_id")
    plant_code = request.args.get("plant_code")
    production_date = request.args.get("production_date")
    status = request.args.get("status")
    if flavor_id is not None:
        items = [s for s in items if s["flavor_id"] == flavor_id]
    if plant_code is not None:
        items = [s for s in items if s["plant_code"] == plant_code]
    if production_date is not None:
        items = [s for s in items if s["production_date"] == production_date]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = [public(s) for s in sorted_items(items)]
    limit, offset = pagination_args()
    return ok_list(items, limit, offset)


@bp.get("/production-slots/<sid>")
def read_slot(sid):
    _, role = authenticate()
    authorize(role, ("PlantScheduler", "FlavorManager"))
    return ok(public(get_slot(sid)))


@bp.post("/production-slots/<sid>/confirm")
def confirm_slot(sid):
    _, role = authenticate()
    authorize(role, ("PlantScheduler",))
    s = get_slot(sid)
    if s["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "Only a PLANNED slot can be confirmed")
    flavor = get_flavor(s["flavor_id"])
    if flavor["status"] not in SCHEDULABLE_FLAVOR_STATES:
        fail("ERR_FLAVOR_NOT_SCHEDULABLE",
             "Slot confirm requires the flavor in TEST_BATCH, LIMITED_RUN "
             "or CORE_LINE")
    # Capacity re-check; the slot's own PLANNED units are excluded so they
    # are not double-counted.
    _check_capacity(s["plant_code"], s["production_date"], s["shift"],
                    s["capacity_units"], exclude_id=s["id"])
    s["status"] = "CONFIRMED"
    touch(s)
    return ok(public(s))


@bp.post("/production-slots/<sid>/cancel")
def cancel_slot(sid):
    _, role = authenticate()
    authorize(role, ("PlantScheduler",))
    s = get_slot(sid)
    if s["status"] not in ("PLANNED", "CONFIRMED"):
        fail("ERR_INVALID_STATE",
             "Only a PLANNED or CONFIRMED slot can be cancelled")
    # Cancelled slots no longer count against the pool: units released.
    s["status"] = "CANCELLED"
    touch(s)
    return ok(public(s))
