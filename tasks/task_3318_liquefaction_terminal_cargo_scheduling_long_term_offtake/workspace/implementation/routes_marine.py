"""Berths, vessel nominations/calls, laytime statements."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request

import db
from errors import ok_object, paginate, fail
from util import (auth, require_role, body, req_str, req_int, req_num, req_enum,
                  stamp_new, touch, pub, parse_dt, dt_to_iso, logical_now_iso, is_int)
from services import (spa_of_slot, adp_of_slot, owning_customer_id_of_slot,
                      owning_customer_id_of_call, owning_customer_id_of_statement,
                      check_customer_owner, invoice_amount, berth_window_conflict,
                      hours2, money2, D, LOADING_RATE, BERTH_ALLOWANCE_HOURS,
                      NOR_GRACE_HOURS, CONNECTION_ALLOWANCE_HOURS)

bp = Blueprint("marine", __name__)


# ---- Berths ----

@bp.post("/api/berths")
def create_berth():
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    data = body()
    name = req_str(data, "name")
    loa = req_num(data, "max_loa_m", min_value=0, min_exclusive=True)
    dwt = req_int(data, "max_dwt_t")
    if dwt <= 0:
        fail("ERR_INVALID_REQUEST", "max_dwt_t must be > 0")
    berth = stamp_new({
        "name": name,
        "max_loa_m": loa,
        "max_dwt_t": dwt,
        "status": "IN_SERVICE",
    })
    db.berths[berth["id"]] = berth
    return ok_object(pub(berth), 201)


@bp.get("/api/berths/<bid>")
def get_berth(bid):
    auth()
    berth = db.berths.get(bid)
    if not berth:
        fail("ERR_NOT_FOUND", "berth not found")
    return ok_object(pub(berth))


@bp.get("/api/berths/<bid>/vessel-calls")
def list_berth_calls(bid):
    auth()
    berth = db.berths.get(bid)
    if not berth:
        fail("ERR_NOT_FOUND", "berth not found")
    items = [c for c in db.vessel_calls.values() if c.get("berth_id") == bid]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return paginate([pub(c) for c in items], request.args)


# ---- Vessel nominations (on cargo slots) ----

@bp.post("/api/cargo-slots/<sid>/vessel-nominations")
def nominate_vessel(sid):
    user_id, role = auth()
    require_role(role, ["CustomerRep"])
    slot = db.cargo_slots.get(sid)
    if not slot:
        fail("ERR_NOT_FOUND", "cargo slot not found")
    data = body()
    vessel_name = req_str(data, "vessel_name")
    imo = req_str(data, "imo_number")
    loa = req_num(data, "vessel_loa_m", min_value=0, min_exclusive=True)
    dwt = req_int(data, "vessel_dwt_t")
    if dwt <= 0:
        fail("ERR_INVALID_REQUEST", "vessel_dwt_t must be > 0")
    rate = req_num(data, "demurrage_rate_usd_per_day", min_value=0, min_exclusive=True)
    has_expected = "expected_cargo_slot_version" in data
    expected = data.get("expected_cargo_slot_version")
    if has_expected and not is_int(expected):
        fail("ERR_INVALID_REQUEST", "expected_cargo_slot_version must be an integer")
    spa = spa_of_slot(slot)
    check_customer_owner(user_id, spa["customer_id"])
    adp = adp_of_slot(slot)
    if slot["lift_status"] in ("CANCELLED", "LOADED"):
        fail("ERR_SLOT_INVALID_STATE", "cannot nominate against a CANCELLED or LOADED slot")
    current_call = None
    for c in db.vessel_calls.values():
        if c["cargo_slot_id"] == sid and c["status"] in ("NOMINATED", "ACCEPTED", "NOR_TENDERED", "BERTHED"):
            current_call = c
            break
    if slot["lift_status"] == "SCHEDULED":
        pass
    elif slot["lift_status"] == "VESSEL_NOMINATED" and current_call is not None and current_call["status"] == "NOMINATED":
        pass
    else:
        fail("ERR_SLOT_INVALID_STATE", "slot is not in a nominatable state")
    if adp["status"] not in ("CONFIRMED", "LOCKED"):
        fail("ERR_ADP_INVALID_STATE", "owning ADP is not CONFIRMED or LOCKED")
    if expected is not None and expected != slot["version"]:
        fail("ERR_STALE_VERSION", "expected_cargo_slot_version does not match slot version")
    if current_call is not None:
        current_call["status"] = "SUPERSEDED"
        touch(current_call)
    call = stamp_new({
        "cargo_slot_id": sid,
        "berth_id": None,
        "vessel_name": vessel_name,
        "imo_number": imo,
        "vessel_loa_m": loa,
        "vessel_dwt_t": dwt,
        "demurrage_rate_usd_per_day": rate,
        "status": "NOMINATED",
        "window_start": None,
        "window_end": None,
        "nor_tendered_at": None,
        "berthed_at": None,
        "departed_at": None,
        "_window_start_dt": None,
        "_window_end_dt": None,
        "_nor_dt": None,
        "_berthed_dt": None,
        "_departed_dt": None,
    })
    db.vessel_calls[call["id"]] = call
    slot["lift_status"] = "VESSEL_NOMINATED"
    touch(slot)
    return ok_object(pub(call), 201)


# ---- Vessel calls ----

@bp.get("/api/vessel-calls/<cid>")
def get_vessel_call(cid):
    auth()
    call = db.vessel_calls.get(cid)
    if not call:
        fail("ERR_NOT_FOUND", "vessel call not found")
    return ok_object(pub(call))


@bp.post("/api/vessel-calls/<cid>/accept")
def accept_call(cid):
    user_id, role = auth()
    require_role(role, ["MarineScheduler"])
    call = db.vessel_calls.get(cid)
    if not call:
        fail("ERR_NOT_FOUND", "vessel call not found")
    data = body()
    berth_id = data.get("berth_id")
    if not isinstance(berth_id, str) or not berth_id:
        fail("ERR_INVALID_REQUEST", "berth_id is required")
    ws = parse_dt(data.get("window_start"), "window_start")
    we = parse_dt(data.get("window_end"), "window_end")
    if ws >= we:
        fail("ERR_INVALID_REQUEST", "window_start must be before window_end")
    if call["status"] != "NOMINATED":
        fail("ERR_CALL_INVALID_STATE", "call is not NOMINATED")
    berth = db.berths.get(berth_id)
    if not berth:
        fail("ERR_NOT_FOUND", "berth not found")
    slot = db.cargo_slots[call["cargo_slot_id"]]
    if berth["status"] != "IN_SERVICE":
        fail("ERR_BERTH_NOT_SERVICEABLE", "berth is OUT_OF_SERVICE")
    if call["vessel_loa_m"] > berth["max_loa_m"] or call["vessel_dwt_t"] > berth["max_dwt_t"]:
        fail("ERR_VESSEL_BERTH_INCOMPATIBLE", "vessel exceeds berth limits")
    if ws < slot["_window_start_dt"] or we > slot["_window_end_dt"]:
        fail("ERR_BERTH_WINDOW_OVERLAP", "assigned window lies outside the slot flexibility window")
    if berth_window_conflict(berth_id, ws, we, exclude_call_id=cid):
        fail("ERR_BERTH_WINDOW_OVERLAP", "berth window conflict")
    call["berth_id"] = berth_id
    call["window_start"] = dt_to_iso(ws)
    call["window_end"] = dt_to_iso(we)
    call["_window_start_dt"] = ws
    call["_window_end_dt"] = we
    call["status"] = "ACCEPTED"
    touch(call)
    slot["lift_status"] = "BERTH_ASSIGNED"
    touch(slot)
    return ok_object(pub(call))


@bp.post("/api/vessel-calls/<cid>/tender-nor")
def tender_nor(cid):
    user_id, role = auth()
    require_role(role, ["CustomerRep"])
    call = db.vessel_calls.get(cid)
    if not call:
        fail("ERR_NOT_FOUND", "vessel call not found")
    owner = owning_customer_id_of_call(call)
    check_customer_owner(user_id, owner)
    if call["status"] != "ACCEPTED":
        fail("ERR_CALL_INVALID_STATE", "call is not ACCEPTED")
    call["_nor_dt"] = db.get_clock()
    call["nor_tendered_at"] = logical_now_iso()
    call["status"] = "NOR_TENDERED"
    touch(call)
    return ok_object(pub(call))


@bp.post("/api/vessel-calls/<cid>/berth")
def berth_call(cid):
    user_id, role = auth()
    require_role(role, ["MarineScheduler"])
    call = db.vessel_calls.get(cid)
    if not call:
        fail("ERR_NOT_FOUND", "vessel call not found")
    if call["status"] != "NOR_TENDERED":
        fail("ERR_CALL_INVALID_STATE", "call is not NOR_TENDERED")
    call["_berthed_dt"] = db.get_clock()
    call["berthed_at"] = logical_now_iso()
    call["status"] = "BERTHED"
    touch(call)
    return ok_object(pub(call))


@bp.post("/api/vessel-calls/<cid>/depart")
def depart_call(cid):
    user_id, role = auth()
    require_role(role, ["MarineScheduler"])
    call = db.vessel_calls.get(cid)
    if not call:
        fail("ERR_NOT_FOUND", "vessel call not found")
    if call["status"] != "BERTHED":
        fail("ERR_CALL_INVALID_STATE", "call is not BERTHED")
    call["_departed_dt"] = db.get_clock()
    call["departed_at"] = logical_now_iso()
    call["status"] = "DEPARTED"
    touch(call)
    slot = db.cargo_slots[call["cargo_slot_id"]]
    spa = spa_of_slot(slot)
    slot["lift_status"] = "LOADED"
    slot["provisional_invoice_usd"] = invoice_amount(
        slot["quantity_mmbtu"], spa["fixed_liquefaction_fee_usd_per_mmbtu"],
        spa["commodity_multiplier"], spa["estimated_index_price_usd_per_mmbtu"])
    slot["billing_status"] = "PROVISIONALLY_INVOICED"
    touch(slot)
    return ok_object(pub(call))


# ---- Laytime statements ----

@bp.post("/api/vessel-calls/<cid>/laytime-statements")
def create_statement(cid):
    user_id, role = auth()
    require_role(role, ["MarineScheduler"])
    call = db.vessel_calls.get(cid)
    if not call:
        fail("ERR_NOT_FOUND", "vessel call not found")
    data = body()
    basis = req_enum(data, "billing_basis", {"SOF_BASIS", "PUMP_LOG_BASIS"})
    excluded = data.get("excluded_periods", [])
    if excluded is None:
        excluded = []
    if not isinstance(excluded, list):
        fail("ERR_INVALID_REQUEST", "excluded_periods must be a list")
    pump_hours = data.get("pump_hours", None)
    if pump_hours is not None and (not isinstance(pump_hours, (int, float)) or isinstance(pump_hours, bool)):
        fail("ERR_INVALID_REQUEST", "pump_hours must be a number")
    if basis == "PUMP_LOG_BASIS" and pump_hours is None:
        fail("ERR_INVALID_REQUEST", "pump_hours is required for PUMP_LOG_BASIS")
    if call["status"] != "DEPARTED":
        fail("ERR_CALL_INVALID_STATE", "laytime statement requires a DEPARTED call")

    nor = call["_nor_dt"]
    berthed = call["_berthed_dt"]
    departed = call["_departed_dt"]
    laytime_start = min(nor + timedelta(hours=NOR_GRACE_HOURS), berthed)

    # validate excluded periods within [laytime_start, departed]
    parsed_periods = []
    for p in excluded:
        if not isinstance(p, dict):
            fail("ERR_INVALID_REQUEST", "excluded_periods entries must be objects")
        ps = parse_dt(p.get("start"), "excluded_periods.start")
        pe = parse_dt(p.get("end"), "excluded_periods.end")
        if pe < ps:
            fail("ERR_INVALID_REQUEST", "excluded period end before start")
        if ps < laytime_start or pe > departed:
            fail("ERR_INVALID_REQUEST", "excluded period outside [laytime_start, departed_at]")
        parsed_periods.append({"start": dt_to_iso(ps), "end": dt_to_iso(pe),
                               "reason": p.get("reason"), "_s": ps, "_e": pe})

    slot = db.cargo_slots[call["cargo_slot_id"]]
    allowed = math.ceil(D(slot["quantity_mmbtu"]) / D(LOADING_RATE)) + BERTH_ALLOWANCE_HOURS
    elapsed = hours2(D((departed - laytime_start).total_seconds()) / D(3600))

    # SOF variant: round each excluded period to whole minutes FIRST, then sum
    excluded_minutes = 0
    for p in parsed_periods:
        secs = D((p["_e"] - p["_s"]).total_seconds())
        mins = int((secs / D(60)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        excluded_minutes += mins
    excluded_hours = hours2(D(excluded_minutes) / D(60))
    used_sof = hours2(D(elapsed) - D(excluded_hours))
    dem_sof = money2(max(D(0), D(used_sof) - D(allowed)) / D(24) * D(call["demurrage_rate_usd_per_day"]))

    used_pump = None
    dem_pump = None
    if pump_hours is not None:
        used_pump = hours2(D(pump_hours) + D(CONNECTION_ALLOWANCE_HOURS))
        dem_pump = money2(max(D(0), D(used_pump) - D(allowed)) / D(24) * D(call["demurrage_rate_usd_per_day"]))

    billed = dem_sof if basis == "SOF_BASIS" else dem_pump

    stmt = stamp_new({
        "vessel_call_id": cid,
        "billing_basis": basis,
        "excluded_periods": [{"start": p["start"], "end": p["end"], "reason": p["reason"]} for p in parsed_periods],
        "pump_hours": pump_hours,
        "laytime_start_at": dt_to_iso(laytime_start),
        "allowed_laytime_hours": allowed,
        "elapsed_hours": elapsed,
        "used_laytime_hours_sof": used_sof,
        "used_laytime_hours_pumplog": used_pump,
        "demurrage_amount_sof_usd": dem_sof,
        "demurrage_amount_pumplog_usd": dem_pump,
        "billed_demurrage_usd": billed,
        "adjusted_demurrage_usd": None,
        "status": "SUBMITTED",
    })
    db.laytime_statements[stmt["id"]] = stmt
    return ok_object(pub(stmt), 201)


@bp.get("/api/vessel-calls/<cid>/laytime-statements")
def list_statements(cid):
    auth()
    call = db.vessel_calls.get(cid)
    if not call:
        fail("ERR_NOT_FOUND", "vessel call not found")
    items = [s for s in db.laytime_statements.values() if s["vessel_call_id"] == cid]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return paginate([pub(s) for s in items], request.args)


@bp.get("/api/laytime-statements/<sid>")
def get_statement(sid):
    auth()
    stmt = db.laytime_statements.get(sid)
    if not stmt:
        fail("ERR_NOT_FOUND", "laytime statement not found")
    return ok_object(pub(stmt))


@bp.post("/api/laytime-statements/<sid>/agree")
def agree_statement(sid):
    user_id, role = auth()
    require_role(role, ["CustomerRep"])
    stmt = db.laytime_statements.get(sid)
    if not stmt:
        fail("ERR_NOT_FOUND", "laytime statement not found")
    check_customer_owner(user_id, owning_customer_id_of_statement(stmt))
    if stmt["status"] != "SUBMITTED":
        fail("ERR_STATEMENT_INVALID_STATE", "statement is not SUBMITTED")
    stmt["status"] = "AGREED"
    touch(stmt)
    return ok_object(pub(stmt))


@bp.post("/api/laytime-statements/<sid>/dispute")
def dispute_statement(sid):
    user_id, role = auth()
    require_role(role, ["CustomerRep"])
    stmt = db.laytime_statements.get(sid)
    if not stmt:
        fail("ERR_NOT_FOUND", "laytime statement not found")
    check_customer_owner(user_id, owning_customer_id_of_statement(stmt))
    if stmt["status"] != "SUBMITTED":
        fail("ERR_STATEMENT_INVALID_STATE", "statement is not SUBMITTED")
    stmt["status"] = "DISPUTED"
    touch(stmt)
    return ok_object(pub(stmt))


@bp.post("/api/laytime-statements/<sid>/resolve")
def resolve_statement(sid):
    user_id, role = auth()
    require_role(role, ["CommercialManager"])
    stmt = db.laytime_statements.get(sid)
    if not stmt:
        fail("ERR_NOT_FOUND", "laytime statement not found")
    data = body()
    adjusted = req_num(data, "adjusted_demurrage_amount_usd")
    if stmt["status"] != "DISPUTED":
        fail("ERR_STATEMENT_INVALID_STATE", "statement is not DISPUTED")
    stmt["adjusted_demurrage_usd"] = adjusted
    stmt["status"] = "RESOLVED"
    touch(stmt)
    return ok_object(pub(stmt))
