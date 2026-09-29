"""Brood groups, the spawning window, and egg takes (PRD 3.2 and 3.3)."""

from decimal import Decimal

from flask import Blueprint

import calc
import constants as K
import derive
import validators as v
from auth import authorize, scope_hatchery
from envelope import created, enum_filter, ok, pagination, paginate, str_filter
from errors import ApiError
from serialize import dump
from store import (Tx, base_record, clock, fmt_instant, get_or_404, insert, parse_instant,
                   sort_key, values)

bp = Blueprint("brood", __name__)

READ_ROLES = (K.PROGRAM_ADMIN, K.HATCHERY_MANAGER, K.VETERINARIAN, K.REGIONAL_BIOLOGIST)


def _hatchery_of_brood(brood):
    return get_or_404("hatcheries", brood["hatchery_id"])


# --- brood groups -----------------------------------------------------------

@bp.post("/brood-stocks")
def create_brood_stock():
    user_id, role = authorize(K.HATCHERY_MANAGER, K.PROGRAM_ADMIN)
    body = v.body()
    hatchery = get_or_404("hatcheries", v.req_id(body, "hatchery_id"))
    scope_hatchery(role, user_id, hatchery["id"])

    species = v.req_enum(body, "species", K.SPECIES)
    strain = v.req_str(body, "strain")
    female_count = v.req_int(body, "female_count", minimum=Decimal(1))
    male_count = v.req_int(body, "male_count", minimum=Decimal(1))
    fecundity = v.req_int(body, "expected_fecundity_per_female", minimum=Decimal(1))
    window_start = v.req_instant(body, "spawning_window_start")
    window_end = v.req_instant(body, "spawning_window_end")
    v.strictly_after("spawning_window_end", window_end, "spawning_window_start", window_start)
    egg_take_target = v.req_int(body, "egg_take_target")

    record = base_record()
    record.update({
        "hatchery_id": hatchery["id"],
        "species": species,
        "strain": strain,
        "female_count": female_count,
        "male_count": male_count,
        "expected_fecundity_per_female": fecundity,
        "females_reserved": 0,
        "females_spent": 0,
        "females_available": female_count,
        "spawning_window_start": fmt_instant(window_start),
        "spawning_window_end": fmt_instant(window_end),
        "egg_take_target": egg_take_target,
        "cumulative_eggs_taken": 0,
        "status": "READY",
    })
    insert("brood_stocks", record)
    return created(dump(record))


@bp.get("/brood-stocks/<identifier>")
def get_brood_stock(identifier):
    user_id, role = authorize(*READ_ROLES)
    brood = get_or_404("brood_stocks", identifier)
    scope_hatchery(role, user_id, brood["hatchery_id"])
    return ok(dump(brood))


@bp.get("/brood-stocks")
def list_brood_stocks():
    authorize(*READ_ROLES)
    hatchery_id = str_filter("hatchery_id")
    species = enum_filter("species", K.SPECIES)
    status = enum_filter("status", K.BROOD_STATUSES)
    limit, offset = pagination()

    records = values("brood_stocks")
    if hatchery_id is not None:
        records = [r for r in records if r["hatchery_id"] == hatchery_id]
    if species is not None:
        records = [r for r in records if r["species"] == species]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records.sort(key=sort_key)
    return paginate(records, limit, offset, dump)


@bp.post("/brood-stocks/<identifier>/open-spawning-window")
def open_spawning_window(identifier):
    user_id, role = authorize(K.HATCHERY_MANAGER)
    brood = get_or_404("brood_stocks", identifier)
    scope_hatchery(role, user_id, brood["hatchery_id"])

    if brood["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", "Only a READY brood group may be opened.")
    now = clock()
    start = parse_instant(brood["spawning_window_start"])
    end = parse_instant(brood["spawning_window_end"])
    if now < start or now >= end:
        raise ApiError("ERR_SPAWN_WINDOW_CLOSED",
                       "The logical clock is outside this group's spawning window.")
    hatchery = _hatchery_of_brood(brood)
    if hatchery["operating_posture"] == "FROZEN":
        raise ApiError("ERR_HATCHERY_FROZEN", "This station is frozen.")

    tx = Tx()
    brood["status"] = "SPAWNING"
    tx.touch(brood)
    tx.settle()
    return ok(dump(brood))


# --- egg takes --------------------------------------------------------------

@bp.post("/spawn-events")
def create_spawn_event():
    user_id, role = authorize(K.HATCHERY_MANAGER)
    body = v.body()
    brood = get_or_404("brood_stocks", v.req_id(body, "brood_stock_id"))
    scope_hatchery(role, user_id, brood["hatchery_id"])

    planned_take_date = v.req_instant(body, "planned_take_date")
    females_spawned = v.req_int(body, "females_spawned", minimum=Decimal(1))
    target_release_count = v.req_int(body, "target_release_count")

    if brood["status"] != "SPAWNING":
        raise ApiError("ERR_BROOD_STOCK_NOT_SPAWNING",
                       "Egg takes may only be planned against a SPAWNING group.")
    hatchery = _hatchery_of_brood(brood)
    if hatchery["operating_posture"] == "FROZEN":
        raise ApiError("ERR_HATCHERY_FROZEN", "This station is frozen.")
    if hatchery["operating_posture"] == "RESTRICTED":
        raise ApiError("ERR_HATCHERY_RESTRICTED", "This station is restricted.")

    if females_spawned > brood["females_available"]:
        raise ApiError("ERR_BROOD_FEMALES_INSUFFICIENT",
                       "The group does not hold that many available females.")

    planned_eggs = females_spawned * brood["expected_fecundity_per_female"]
    reserved_af = calc.water_af_for_eggs(planned_eggs)
    if reserved_af > Decimal(hatchery["water_available_af"]):
        raise ApiError("ERR_WATER_RIGHT_EXCEEDED",
                       "The take would reserve more acre-feet than the station has available.")

    survival = calc.cumulative_survival(hatchery["density_index"])
    record = base_record()
    record.update({
        "brood_stock_id": brood["id"],
        "planned_take_date": fmt_instant(planned_take_date),
        "females_spawned": females_spawned,
        "target_release_count": target_release_count,
        "planned_eggs": planned_eggs,
        "water_reserved_af": reserved_af,
        "cumulative_survival": survival,
        "required_eggs_for_target": calc.required_eggs_for_target(target_release_count, survival),
        "projected_release_count": calc.projected_release_count(planned_eggs, survival),
        "eggs_taken": None,
        "taken_at": None,
        "status": "PLANNED",
    })
    insert("spawn_events", record)

    tx = Tx()
    derive.recompute_brood(tx, brood)
    derive.recompute_hatchery(tx, hatchery)
    tx.settle()
    return created(dump(record))


@bp.get("/spawn-events/<identifier>")
def get_spawn_event(identifier):
    user_id, role = authorize(*READ_ROLES)
    event = get_or_404("spawn_events", identifier)
    brood = get_or_404("brood_stocks", event["brood_stock_id"])
    scope_hatchery(role, user_id, brood["hatchery_id"])
    return ok(dump(event))


@bp.get("/spawn-events")
def list_spawn_events():
    authorize(*READ_ROLES)
    brood_stock_id = str_filter("brood_stock_id")
    status = enum_filter("status", K.SPAWN_STATUSES)
    limit, offset = pagination()

    records = values("spawn_events")
    if brood_stock_id is not None:
        records = [r for r in records if r["brood_stock_id"] == brood_stock_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records.sort(key=sort_key)
    return paginate(records, limit, offset, dump)


@bp.post("/spawn-events/<identifier>/record-take")
def record_spawn_take(identifier):
    user_id, role = authorize(K.HATCHERY_MANAGER)
    event = get_or_404("spawn_events", identifier)
    brood = get_or_404("brood_stocks", event["brood_stock_id"])
    scope_hatchery(role, user_id, brood["hatchery_id"])

    body = v.body()
    eggs_taken = v.req_int(body, "eggs_taken", minimum=Decimal(1))
    taken_at = v.req_instant(body, "taken_at")
    v.not_after_clock("taken_at", taken_at, clock())

    if event["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "Only a PLANNED take may be recorded.")
    if brood["status"] != "SPAWNING":
        raise ApiError("ERR_BROOD_STOCK_NOT_SPAWNING",
                       "The brood group is no longer SPAWNING.")
    hatchery = _hatchery_of_brood(brood)
    if hatchery["operating_posture"] == "FROZEN":
        raise ApiError("ERR_HATCHERY_FROZEN", "This station is frozen.")

    consumed_af = calc.water_af_for_eggs(eggs_taken)
    headroom = Decimal(hatchery["water_available_af"]) + Decimal(event["water_reserved_af"])
    if consumed_af > headroom:
        raise ApiError("ERR_WATER_RIGHT_EXCEEDED",
                       "The eggs actually taken would consume more acre-feet than remain.")

    tx = Tx()
    event["eggs_taken"] = eggs_taken
    event["taken_at"] = fmt_instant(taken_at)
    event["status"] = "TAKEN"
    tx.touch(event)

    derive.recompute_brood(tx, brood)
    if brood["cumulative_eggs_taken"] >= brood["egg_take_target"]:
        if brood["status"] == "SPAWNING":
            brood["status"] = "CLOSED"
            tx.touch(brood)

    lot = base_record()
    lot.update({
        "hatchery_id": hatchery["id"],
        "spawn_event_id": event["id"],
        "species": brood["species"],
        "initial_count": eggs_taken,
        "initial_biomass_lbs": calc.to_lbs(eggs_taken, K.EGG_WEIGHT_G),
        "count_on_hand": eggs_taken,
        "reserved_count": 0,
        "cumulative_mortality_count": 0,
        "cumulative_mortality_biomass_lbs": calc.q2(0),
        "avg_weight_g": K.EGG_WEIGHT_G,
        "growth_rate_g_per_day": None,
        "biomass_lbs": calc.to_lbs(eggs_taken, K.EGG_WEIGHT_G),
        "cumulative_feed_lbs": calc.q2(0),
        "fcr_biological": None,
        "fcr_economic": None,
        "rearing_stage": "EGG",
        "health_status": "UNSCREENED",
        "certificate_expires_at": None,
    })
    insert("rearing_lots", lot)

    derive.recompute_hatchery(tx, hatchery)
    tx.settle()
    return ok(dump(event))


@bp.post("/spawn-events/<identifier>/cancel")
def cancel_spawn_event(identifier):
    user_id, role = authorize(K.HATCHERY_MANAGER, K.PROGRAM_ADMIN)
    event = get_or_404("spawn_events", identifier)
    brood = get_or_404("brood_stocks", event["brood_stock_id"])
    scope_hatchery(role, user_id, brood["hatchery_id"])

    if event["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "Only a PLANNED take may be cancelled.")

    tx = Tx()
    event["status"] = "CANCELLED"
    tx.touch(event)
    derive.recompute_brood(tx, brood)
    derive.recompute_hatchery(tx, get_or_404("hatcheries", brood["hatchery_id"]))
    tx.settle()
    return ok(dump(event))
