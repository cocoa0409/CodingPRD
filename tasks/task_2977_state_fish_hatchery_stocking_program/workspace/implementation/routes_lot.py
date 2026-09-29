"""Rearing lots: feedings, feed conversion and the stage gates (PRD 3.4)."""

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
from store import Tx, clock, fmt_instant, get_or_404, parse_instant, sort_key, values

bp = Blueprint("lot", __name__)

READ_ROLES = (K.PROGRAM_ADMIN, K.HATCHERY_MANAGER, K.VETERINARIAN, K.REGIONAL_BIOLOGIST)


@bp.get("/rearing-lots/<identifier>")
def get_rearing_lot(identifier):
    user_id, role = authorize(*READ_ROLES)
    lot = get_or_404("rearing_lots", identifier)
    scope_hatchery(role, user_id, lot["hatchery_id"])
    return ok(dump(lot))


@bp.get("/rearing-lots")
def list_rearing_lots():
    authorize(*READ_ROLES)
    hatchery_id = str_filter("hatchery_id")
    spawn_event_id = str_filter("spawn_event_id")
    rearing_stage = enum_filter("rearing_stage", K.REARING_STAGES)
    health_status = enum_filter("health_status", K.HEALTH_STATUSES)
    species = enum_filter("species", K.SPECIES)
    limit, offset = pagination()

    records = values("rearing_lots")
    if hatchery_id is not None:
        records = [r for r in records if r["hatchery_id"] == hatchery_id]
    if spawn_event_id is not None:
        records = [r for r in records if r["spawn_event_id"] == spawn_event_id]
    if rearing_stage is not None:
        records = [r for r in records if r["rearing_stage"] == rearing_stage]
    if health_status is not None:
        records = [r for r in records if r["health_status"] == health_status]
    if species is not None:
        records = [r for r in records if r["species"] == species]
    records.sort(key=sort_key)
    return paginate(records, limit, offset, dump)


@bp.post("/rearing-lots/<identifier>/feedings")
def record_feeding(identifier):
    user_id, role = authorize(K.HATCHERY_MANAGER)
    lot = get_or_404("rearing_lots", identifier)
    scope_hatchery(role, user_id, lot["hatchery_id"])

    body = v.body()
    fed_at = v.req_instant(body, "fed_at")
    feed_lbs = v.req_num(body, "feed_lbs", minimum=Decimal(0))
    avg_weight_g_after = v.req_num(body, "avg_weight_g_after", minimum=Decimal(0))
    mortality_count = v.opt_int(body, "mortality_count", default=0, minimum=Decimal(0))

    if lot["rearing_stage"] in ("RELEASED", "TERMINATED"):
        raise ApiError("ERR_INVALID_STATE", "This lot is no longer being reared.")

    hatchery = get_or_404("hatcheries", lot["hatchery_id"])

    # Priority 13: the hard density cap is tested before anything is written.
    prospective_count = lot["count_on_hand"] - mortality_count
    prospective_biomass = calc.to_lbs(prospective_count, avg_weight_g_after)
    station_biomass = prospective_biomass
    for other in derive.lots_of(hatchery["id"]):
        if other["id"] == lot["id"]:
            continue
        if other["rearing_stage"] not in ("RELEASED", "TERMINATED"):
            station_biomass += Decimal(other["biomass_lbs"])
    prospective_density = calc.density_index(calc.q2(station_biomass),
                                            hatchery["rearing_capacity_lbs"])
    if prospective_density > K.DENSITY_HARD_CAP:
        raise ApiError("ERR_DENSITY_CAP_EXCEEDED",
                       "This feeding would push the station past its density cap.")

    tx = Tx()
    previous_at = parse_instant(lot.get("_last_fed_at") or lot["created_at"])
    weight_before = Decimal(lot["avg_weight_g"])

    lot["count_on_hand"] = prospective_count
    lot["cumulative_mortality_count"] = lot["cumulative_mortality_count"] + mortality_count
    lot["avg_weight_g"] = avg_weight_g_after
    lot["growth_rate_g_per_day"] = calc.growth_rate_g_per_day(
        avg_weight_g_after, weight_before, fed_at, previous_at)
    lot["cumulative_mortality_biomass_lbs"] = calc.q2(
        Decimal(lot["cumulative_mortality_biomass_lbs"])
        + calc.to_lbs(mortality_count, avg_weight_g_after))
    lot["biomass_lbs"] = calc.lot_biomass_lbs(lot)
    lot["cumulative_feed_lbs"] = calc.q2(Decimal(lot["cumulative_feed_lbs"]) + feed_lbs)
    biological, economic = calc.feed_conversion(
        lot["cumulative_feed_lbs"], lot["biomass_lbs"], lot["initial_biomass_lbs"],
        lot["cumulative_mortality_biomass_lbs"])
    lot["fcr_biological"] = biological
    lot["fcr_economic"] = economic
    lot["_last_fed_at"] = fmt_instant(fed_at)
    tx.touch(lot)

    derive.settle_lot_after_feeding(tx, lot)
    derive.recompute_hatchery(tx, hatchery)
    tx.settle()
    # No Feeding resource exists: the operation returns the updated lot, so 200.
    return ok(dump(lot))


@bp.post("/rearing-lots/<identifier>/advance-stage")
def advance_rearing_stage(identifier):
    user_id, role = authorize(K.HATCHERY_MANAGER)
    lot = get_or_404("rearing_lots", identifier)
    scope_hatchery(role, user_id, lot["hatchery_id"])

    body = v.body()
    to_stage = v.req_enum(body, "to_stage", K.REARING_STAGES)

    current = lot["rearing_stage"]
    if current not in K.NEXT_STAGE or K.NEXT_STAGE[current] != to_stage:
        raise ApiError("ERR_INVALID_STATE",
                       "A lot advances exactly one stage at a time.")
    gate = K.STAGE_WEIGHT_GATES[to_stage]
    if Decimal(lot["avg_weight_g"]) < gate:
        raise ApiError("ERR_STAGE_WEIGHT_NOT_MET",
                       "The lot has not reached the minimum mean weight for %s." % to_stage)

    tx = Tx()
    lot["rearing_stage"] = to_stage
    tx.touch(lot)
    derive.recompute_hatchery(tx, get_or_404("hatcheries", lot["hatchery_id"]))
    tx.settle()
    return ok(dump(lot))
