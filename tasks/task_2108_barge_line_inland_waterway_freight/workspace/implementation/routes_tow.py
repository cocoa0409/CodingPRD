"""Tows and barge assignments: makeup, light-loading, the voyage and the
discharge axis."""
from flask import Blueprint

import calc
from common import (ALL_ROLES, ApiError, apply_filters, authenticate, created,
                    f_dt, f_int, f_num, f_str, fetch, get_body, make_record, ok,
                    paged_response, pagination, sorted_rows, store, touch)
from schema import ser_assignment, ser_tow

bp = Blueprint("tow", __name__)


# ---------------------------------------------------------------------------
# Tows
# ---------------------------------------------------------------------------
@bp.post("/tows")
def create_tow():
    authenticate(["TowboatDispatcher"])
    body = get_body()
    rec = make_record({
        "towboat_name": f_str(body, "towboat_name"),
        "horsepower": f_int(body, "horsepower", gt=0),
        "origin_mile": f_num(body, "origin_mile"),
        "destination_mile": f_num(body, "destination_mile"),
        "controlling_gauge_station": f_str(body, "controlling_gauge_station"),
        "status": "BUILDING",
        "barge_count": 0,
        "total_loaded_tons": 0,
        "max_draft_feet": 0,
        "allowed_draft_feet": 0,
        "draft_restriction_band": None,
        "accrued_delay_minutes": 0,
        "pending_lock_reservation_count": 0,
        "departed_at": None,
        "arrived_at": None,
    })
    store.tows[rec["id"]] = rec
    return created(ser_tow(rec))


@bp.get("/tows/<tow_id>")
def get_tow(tow_id):
    authenticate(ALL_ROLES)
    return ok(ser_tow(fetch(store.tows, tow_id, "ERR_TOW_NOT_FOUND")))


@bp.get("/tows")
def list_tows():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.tows), [("status", "status")])
    return paged_response(rows, ser_tow, limit, offset)


# ---------------------------------------------------------------------------
# Makeup: adding a barge to a tow
# ---------------------------------------------------------------------------
@bp.post("/tows/<tow_id>/barge-assignments")
def add_assignment(tow_id):
    authenticate(["TowboatDispatcher"])
    body = get_body()
    barge_id = f_str(body, "barge_id")
    contract_id = f_str(body, "freight_contract_id")
    loaded_tons = f_int(body, "loaded_tons", gt=0)
    cut_position = f_int(body, "cut_position", gt=0)

    tow = fetch(store.tows, tow_id, "ERR_TOW_NOT_FOUND")
    barge = fetch(store.barges, barge_id, "ERR_BARGE_NOT_FOUND")
    contract = fetch(store.freight_contracts, contract_id,
                     "ERR_FREIGHT_CONTRACT_NOT_FOUND")

    # priority 9 - state preconditions
    if tow["status"] != "BUILDING":
        raise ApiError("ERR_TOW_INVALID_STATE")
    if contract["movement_status"] not in ("ACTIVE", "IN_TRANSIT"):
        raise ApiError("ERR_CONTRACT_MOVEMENT_INVALID_STATE")
    if barge["operational_status"] == "OUT_OF_SERVICE":
        raise ApiError("ERR_BARGE_NOT_AVAILABLE")

    commodity = store.commodities.get(contract["commodity_id"])
    level, prohibited = calc.resolve_requirement(barge, commodity)
    if prohibited:
        raise ApiError("ERR_CARGO_INCOMPATIBLE")
    if not calc.cleanliness_ok(barge, level):
        raise ApiError("ERR_BARGE_CLEANLINESS_INSUFFICIENT")
    if loaded_tons > barge["capacity_tons"]:
        raise ApiError("ERR_BARGE_CAPACITY_EXCEEDED")
    for a in calc.tow_assignments(tow_id):
        if a["status"] != "DROPPED" and a["cut_position"] == cut_position:
            raise ApiError("ERR_DUPLICATE_CUT_POSITION")
    for a in store.barge_assignments.values():
        if a["barge_id"] == barge_id and a["status"] in calc.ACTIVE_ASSIGNMENT_STATUSES:
            raise ApiError("ERR_BARGE_ALREADY_ASSIGNED")

    rec = make_record({
        "tow_id": tow_id,
        "barge_id": barge_id,
        "freight_contract_id": contract_id,
        "cut_position": cut_position,
        "loaded_tons": loaded_tons,
        "barge_draft_feet": calc.barge_draft(barge, loaded_tons),
        "status": "PLANNED",
        "discharge_status": "NOT_ARRIVED",
        "arrived_at": None,
        "unload_started_at": None,
        "unload_finished_at": None,
        "discharged_tons": None,
        "gross_laytime_hours": 0,
        "net_laytime_hours": 0,
        "delay_attributed_minutes": 0,
    })
    store.barge_assignments[rec["id"]] = rec
    calc.recompute_tow_profile(tow)
    touch(tow)
    return created(ser_assignment(rec))


# ---------------------------------------------------------------------------
# Sealing the makeup
# ---------------------------------------------------------------------------
@bp.post("/tows/<tow_id>/seal")
def seal_tow(tow_id):
    authenticate(["TowboatDispatcher"])
    tow = fetch(store.tows, tow_id, "ERR_TOW_NOT_FOUND")
    if tow["status"] != "BUILDING":
        raise ApiError("ERR_TOW_INVALID_STATE")
    active = calc.active_assignments(tow_id)
    if len(active) < 1:
        raise ApiError("ERR_TOW_INVALID_STATE",
                       "A tow with no active assignment cannot be sealed.")

    # priorities 11 and 12 are re-examined against the world as it stands now
    requirements = []
    for a in active:
        barge = store.barges.get(a["barge_id"])
        contract = store.freight_contracts.get(a["freight_contract_id"])
        commodity = store.commodities.get(contract["commodity_id"]) if contract else None
        level, prohibited = calc.resolve_requirement(barge, commodity)
        requirements.append((a, barge, level, prohibited))
    for _a, _barge, _level, prohibited in requirements:
        if prohibited:
            raise ApiError("ERR_CARGO_INCOMPATIBLE")
    for _a, barge, level, _prohibited in requirements:
        if not calc.cleanliness_ok(barge, level):
            raise ApiError("ERR_BARGE_CLEANLINESS_INSUFFICIENT")

    # priority 13
    reading = calc.controlling_reading(tow["controlling_gauge_station"])
    if reading is None:
        raise ApiError("ERR_NO_RIVER_STAGE_READING")
    max_draft = max((a["barge_draft_feet"] for a in active), default=0)
    if calc.dec_gt(max_draft, reading["max_draft_feet"]):
        raise ApiError("ERR_DRAFT_EXCEEDS_RESTRICTION")
    if len(active) > reading["tow_size_cap_barges"]:
        raise ApiError("ERR_TOW_SIZE_CAP_EXCEEDED")

    tow["status"] = "SEALED"
    for a in active:
        if a["status"] == "PLANNED":
            a["status"] = "CONFIRMED"
            touch(a)
            barge = store.barges.get(a["barge_id"])
            if barge is not None and barge["operational_status"] in ("IDLE", "FLEETED"):
                barge["operational_status"] = "IN_TOW"
                touch(barge)
    calc.recompute_tow_profile(tow)
    touch(tow)
    return ok(ser_tow(tow))


# ---------------------------------------------------------------------------
# The voyage
# ---------------------------------------------------------------------------
@bp.post("/tows/<tow_id>/depart")
def depart_tow(tow_id):
    authenticate(["TowboatDispatcher"])
    body = get_body()
    departed_at = f_dt(body, "departed_at")
    tow = fetch(store.tows, tow_id, "ERR_TOW_NOT_FOUND")
    if tow["status"] != "SEALED":
        raise ApiError("ERR_TOW_INVALID_STATE")
    confirmed = [a for a in calc.tow_assignments(tow_id) if a["status"] == "CONFIRMED"]
    confirmed.sort(key=lambda a: a["cut_position"])
    barge_ids = {a["barge_id"] for a in confirmed}

    tow["status"] = "UNDERWAY"
    tow["departed_at"] = departed_at
    touch(tow)

    for a in confirmed:
        a["status"] = "LOADED"
        touch(a)

    fleets = [f for f in store.fleeting_assignments.values()
              if f["status"] == "RESERVED" and f["barge_id"] in barge_ids]
    fleets.sort(key=lambda f: (f["created_at"], f["_seq"]))
    for f in fleets:
        berth = store.fleeting_berths.get(f["fleeting_berth_id"])
        f["status"] = "RELEASED"
        f["released_at"] = departed_at
        if berth is not None:
            days, fee = calc.release_fee(berth, f["start_at"], departed_at)
            f["billable_days"] = days
            f["fee_cents"] = fee
            berth["occupied_barge_count"] = max(0, berth["occupied_barge_count"] - 1)
            touch(berth)
        touch(f)

    contract_ids = []
    for a in confirmed:
        if a["freight_contract_id"] not in contract_ids:
            contract_ids.append(a["freight_contract_id"])
    contracts = [store.freight_contracts[c] for c in contract_ids
                 if c in store.freight_contracts]
    contracts.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for c in contracts:
        if c["movement_status"] == "ACTIVE":
            c["movement_status"] = "IN_TRANSIT"
            touch(c)
    return ok(ser_tow(tow))


@bp.post("/tows/<tow_id>/resume")
def resume_tow(tow_id):
    authenticate(["TowboatDispatcher"])
    tow = fetch(store.tows, tow_id, "ERR_TOW_NOT_FOUND")
    if tow["status"] != "DELAYED":
        raise ApiError("ERR_TOW_INVALID_STATE")
    tow["status"] = "UNDERWAY"
    touch(tow)
    return ok(ser_tow(tow))


@bp.post("/tows/<tow_id>/arrive")
def arrive_tow(tow_id):
    authenticate(["TowboatDispatcher"])
    body = get_body()
    arrived_at = f_dt(body, "arrived_at")
    tow = fetch(store.tows, tow_id, "ERR_TOW_NOT_FOUND")
    if tow["status"] not in ("UNDERWAY", "DELAYED"):
        raise ApiError("ERR_TOW_INVALID_STATE")
    if tow["departed_at"] is not None and arrived_at < tow["departed_at"]:
        raise ApiError("ERR_UNLOAD_SEQUENCE_INVALID")
    tow["status"] = "ARRIVED"
    tow["arrived_at"] = arrived_at
    touch(tow)
    return ok(ser_tow(tow))


@bp.post("/tows/<tow_id>/break-up")
def break_up_tow(tow_id):
    authenticate(["TowboatDispatcher"])
    tow = fetch(store.tows, tow_id, "ERR_TOW_NOT_FOUND")
    if tow["status"] != "ARRIVED":
        raise ApiError("ERR_TOW_INVALID_STATE")
    loaded = [a for a in calc.tow_assignments(tow_id) if a["status"] == "LOADED"]
    loaded.sort(key=lambda a: a["cut_position"])
    for a in loaded:
        if a["discharge_status"] not in calc.BILLABLE_DISCHARGE_STATUSES:
            raise ApiError("ERR_TOW_INVALID_STATE",
                           "Every loaded barge must have discharged before break-up.")
    tow["status"] = "BROKEN_UP"
    touch(tow)
    for a in loaded:
        a["status"] = "DISCHARGED"
        touch(a)
        barge = store.barges.get(a["barge_id"])
        if barge is not None and barge["operational_status"] == "IN_TOW":
            barge["operational_status"] = "IDLE"
            barge["cleanliness_status"] = "DIRTY"
            contract = store.freight_contracts.get(a["freight_contract_id"])
            barge["last_cargo_commodity_id"] = contract["commodity_id"] if contract else None
            barge["last_cleaning_certificate_number"] = None
            touch(barge)
    return ok(ser_tow(tow))


@bp.post("/tows/<tow_id>/adjust-load")
def adjust_load(tow_id):
    authenticate(["TowboatDispatcher"])
    body = get_body()
    expected_tow_version = f_int(body, "expected_tow_version")
    tow = fetch(store.tows, tow_id, "ERR_TOW_NOT_FOUND")
    if tow["status"] != "BUILDING":
        raise ApiError("ERR_TOW_INVALID_STATE")
    if expected_tow_version != tow["version"]:
        raise ApiError("ERR_STALE_TOW_VERSION")
    reading = calc.controlling_reading(tow["controlling_gauge_station"])
    if reading is None:
        raise ApiError("ERR_NO_RIVER_STAGE_READING")
    tow["draft_restriction_band"] = reading["draft_restriction_band"]
    tow["allowed_draft_feet"] = reading["max_draft_feet"]
    for a in calc.active_assignments(tow_id):
        if not calc.dec_gt(a["barge_draft_feet"], tow["allowed_draft_feet"]):
            continue
        barge = store.barges.get(a["barge_id"])
        if barge is None:
            continue
        allowance = calc.allowed_tons_for(tow, barge)
        if allowance < a["loaded_tons"]:
            a["loaded_tons"] = allowance
            a["barge_draft_feet"] = calc.barge_draft(barge, a["loaded_tons"])
            touch(a)
    calc.recompute_tow_profile(tow)
    touch(tow)
    return ok(ser_tow(tow))


# ---------------------------------------------------------------------------
# Barge assignments
# ---------------------------------------------------------------------------
@bp.post("/barge-assignments/<barge_assignment_id>/drop")
def drop(barge_assignment_id):
    authenticate(["TowboatDispatcher"])
    a = fetch(store.barge_assignments, barge_assignment_id,
              "ERR_BARGE_ASSIGNMENT_NOT_FOUND")
    if a["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_BARGE_ASSIGNMENT_INVALID_STATE")
    calc.drop_assignment(a)
    return ok(ser_assignment(a))


@bp.post("/barge-assignments/<barge_assignment_id>/record-arrival")
def record_arrival(barge_assignment_id):
    authenticate(["TowboatDispatcher"])
    body = get_body()
    arrived_at = f_dt(body, "arrived_at")
    a = fetch(store.barge_assignments, barge_assignment_id,
              "ERR_BARGE_ASSIGNMENT_NOT_FOUND")
    if a["discharge_status"] != "NOT_ARRIVED" or a["status"] != "LOADED":
        raise ApiError("ERR_BARGE_ASSIGNMENT_INVALID_STATE")
    tow = store.tows.get(a["tow_id"])
    if tow is None or tow["status"] != "ARRIVED":
        raise ApiError("ERR_TOW_INVALID_STATE")
    a["discharge_status"] = "ARRIVED"
    a["arrived_at"] = arrived_at
    touch(a)
    return ok(ser_assignment(a))


@bp.post("/barge-assignments/<barge_assignment_id>/start-unload")
def start_unload(barge_assignment_id):
    authenticate(["TowboatDispatcher"])
    body = get_body()
    unload_started_at = f_dt(body, "unload_started_at")
    a = fetch(store.barge_assignments, barge_assignment_id,
              "ERR_BARGE_ASSIGNMENT_NOT_FOUND")
    if a["discharge_status"] != "ARRIVED":
        raise ApiError("ERR_BARGE_ASSIGNMENT_INVALID_STATE")
    if a["arrived_at"] is not None and unload_started_at < a["arrived_at"]:
        raise ApiError("ERR_UNLOAD_SEQUENCE_INVALID")
    a["discharge_status"] = "UNLOADING"
    a["unload_started_at"] = unload_started_at
    touch(a)
    return ok(ser_assignment(a))


@bp.post("/barge-assignments/<barge_assignment_id>/finish-unload")
def finish_unload(barge_assignment_id):
    authenticate(["TowboatDispatcher"])
    body = get_body()
    unload_finished_at = f_dt(body, "unload_finished_at")
    discharged_tons = f_int(body, "discharged_tons", ge=0)
    a = fetch(store.barge_assignments, barge_assignment_id,
              "ERR_BARGE_ASSIGNMENT_NOT_FOUND")
    if discharged_tons > a["loaded_tons"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'discharged_tons' may not exceed the loaded tonnage.")
    if a["discharge_status"] != "UNLOADING":
        raise ApiError("ERR_BARGE_ASSIGNMENT_INVALID_STATE")
    if a["unload_started_at"] is not None and unload_finished_at < a["unload_started_at"]:
        raise ApiError("ERR_UNLOAD_SEQUENCE_INVALID")
    a["discharge_status"] = "COMPLETED"
    a["unload_finished_at"] = unload_finished_at
    a["discharged_tons"] = discharged_tons
    a["gross_laytime_hours"] = calc.hours_up(unload_finished_at, a["arrived_at"]) \
        if a["arrived_at"] is not None else 0
    a["net_laytime_hours"] = calc.hours_up(unload_finished_at, a["unload_started_at"]) \
        if a["unload_started_at"] is not None else 0
    touch(a)

    contract = store.freight_contracts.get(a["freight_contract_id"])
    if contract is not None and contract["movement_status"] == "IN_TRANSIT":
        siblings = [x for x in calc.contract_assignments(contract["id"])
                    if x["status"] != "DROPPED"]
        if siblings and all(x["discharge_status"] == "COMPLETED" for x in siblings):
            contract["movement_status"] = "DISCHARGED"
            touch(contract)
    return ok(ser_assignment(a))


@bp.get("/barge-assignments/<barge_assignment_id>")
def get_assignment(barge_assignment_id):
    authenticate(ALL_ROLES)
    return ok(ser_assignment(fetch(store.barge_assignments, barge_assignment_id,
                                   "ERR_BARGE_ASSIGNMENT_NOT_FOUND")))


@bp.get("/barge-assignments")
def list_assignments():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.barge_assignments),
                         [("tow_id", "tow_id"), ("barge_id", "barge_id"),
                          ("freight_contract_id", "freight_contract_id"),
                          ("status", "status"),
                          ("discharge_status", "discharge_status")])
    return paged_response(rows, ser_assignment, limit, offset)
