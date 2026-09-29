"""The logical clock, stations, and the discharge-monitoring record."""

from decimal import Decimal

from flask import Blueprint

import calc
import constants as K
import derive
import validators as v
from auth import authorize, scope_hatchery
from envelope import created, enum_filter, ok, pagination, paginate
from errors import ApiError
from serialize import dump
from store import Tx, base_record, clock, db, get_or_404, insert, parse_instant, values

bp = Blueprint("hatchery", __name__)


# --- the logical clock ------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(K.PROGRAM_ADMIN)
    body = v.body()
    current_utc = v.req_instant(body, "current_utc")
    db.current_utc = current_utc
    tx = Tx()
    derive.apply_clock(tx)
    tx.settle()
    from store import fmt_instant
    return ok({"current_utc": fmt_instant(clock())})


# --- stations ---------------------------------------------------------------

@bp.post("/hatcheries")
def create_hatchery():
    authorize(K.PROGRAM_ADMIN)
    body = v.body()
    name = v.req_str(body, "name")
    station_code = v.req_str(body, "station_code", pattern=r"^[A-Z0-9]{4}$")
    water_source_type = v.req_enum(body, "water_source_type", K.WATER_SOURCE_TYPES)
    annual_water_right_af = v.req_num(body, "annual_water_right_af")
    rearing_capacity_lbs = v.req_num(body, "rearing_capacity_lbs")
    oxygen_supply_lpm = v.req_num(body, "oxygen_supply_lpm")
    effluent_permit_number = v.req_str(body, "effluent_permit_number")
    tss_permit_limit_mg_l = v.req_num(body, "tss_permit_limit_mg_l")
    annual_budget_cents = v.req_int(body, "annual_budget_cents")

    for existing in values("hatcheries"):
        if existing["station_code"] == station_code:
            raise ApiError("ERR_DUPLICATE_STATION_CODE",
                           "station_code is already registered to another station.")

    water_right = calc.q4(annual_water_right_af)
    record = base_record()
    record.update({
        "name": name,
        "station_code": station_code,
        "water_source_type": water_source_type,
        "annual_water_right_af": water_right,
        "water_reserved_af": calc.q4(0),
        "water_used_af": calc.q4(0),
        "water_available_af": water_right,
        "rearing_capacity_lbs": rearing_capacity_lbs,
        "biomass_on_hand_lbs": calc.q2(0),
        "density_index": calc.q4(0),
        "oxygen_supply_lpm": oxygen_supply_lpm,
        "effluent_permit_number": effluent_permit_number,
        "tss_permit_limit_mg_l": tss_permit_limit_mg_l,
        "exceedance_count_rolling": 0,
        "operating_posture": "OPEN",
        "annual_budget_cents": annual_budget_cents,
        "budget_committed_cents": 0,
        "budget_spent_cents": 0,
        "budget_available_cents": annual_budget_cents,
    })
    insert("hatcheries", record)
    return created(dump(record))


@bp.get("/hatcheries/<identifier>")
def get_hatchery(identifier):
    user_id, role = authorize(K.PROGRAM_ADMIN, K.HATCHERY_MANAGER, K.VETERINARIAN,
                              K.REGIONAL_BIOLOGIST)
    hatchery = get_or_404("hatcheries", identifier)
    scope_hatchery(role, user_id, hatchery["id"])
    return ok(dump(hatchery))


# --- discharge monitoring ---------------------------------------------------

@bp.get("/hatcheries/<identifier>/effluent-readings")
def list_hatchery_effluent_readings(identifier):
    user_id, role = authorize(K.PROGRAM_ADMIN, K.HATCHERY_MANAGER)
    hatchery = get_or_404("hatcheries", identifier)
    scope_hatchery(role, user_id, hatchery["id"])
    status = enum_filter("status", K.READING_STATUSES)
    limit, offset = pagination()

    records = derive.readings_of(hatchery["id"])
    if status is not None:
        records = [r for r in records if r["status"] == status]
    # "the discharge-monitoring record of a station ... is returned newest sample first"
    records.sort(key=lambda r: (r["sampled_at"], r["_seq"]), reverse=True)
    return paginate(records, limit, offset, dump)


@bp.post("/effluent-readings")
def create_effluent_reading():
    user_id, role = authorize(K.HATCHERY_MANAGER, K.PROGRAM_ADMIN)
    body = v.body()
    hatchery = get_or_404("hatcheries", v.req_id(body, "hatchery_id"))
    scope_hatchery(role, user_id, hatchery["id"])

    sampled_at = v.req_instant(body, "sampled_at")
    tss_mg_l = v.req_num(body, "tss_mg_l", minimum=Decimal(0))
    total_phosphorus_mg_l = v.req_num(body, "total_phosphorus_mg_l", minimum=Decimal(0))
    flow_af = v.req_num(body, "flow_af", minimum=Decimal(0))
    v.not_after_clock("sampled_at", sampled_at, clock())

    status, margin = calc.effluent_classification(
        tss_mg_l, total_phosphorus_mg_l, hatchery["tss_permit_limit_mg_l"])

    from store import fmt_instant
    record = base_record(with_revision=False)
    record.update({
        "hatchery_id": hatchery["id"],
        "sampled_at": fmt_instant(sampled_at),
        "tss_mg_l": tss_mg_l,
        "total_phosphorus_mg_l": total_phosphorus_mg_l,
        "flow_af": calc.q4(flow_af),
        "status": status,
        "exceedance_margin_mg_l": margin,
    })
    insert("effluent_readings", record)

    tx = Tx()
    derive.recompute_hatchery(tx, hatchery)
    tx.settle()
    return created(dump(record))
