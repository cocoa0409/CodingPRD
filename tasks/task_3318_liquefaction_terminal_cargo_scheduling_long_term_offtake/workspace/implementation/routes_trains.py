"""Trains, turnarounds, terminal-wide cascades."""
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request

import db
from errors import ok_object, paginate, fail
from util import (auth, require_role, body, req_str, req_int, req_num, req_bool,
                  stamp_new, touch, pub, parse_date)
from services import recompute_adp_quantities, prorate, recompute_schedule_totals
import services

bp = Blueprint("trains", __name__)


@bp.post("/api/trains")
def create_train():
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    data = body()
    name = req_str(data, "name")
    cap = req_num(data, "design_capacity_mtpa", min_value=0, min_exclusive=True)
    daily = req_int(data, "daily_capacity_mmbtu")
    if daily <= 0:
        fail("ERR_INVALID_REQUEST", "daily_capacity_mmbtu must be > 0")
    required = req_int(data, "commissioning_cargoes_required", min_value=0)
    train = stamp_new({
        "name": name,
        "design_capacity_mtpa": cap,
        "daily_capacity_mmbtu": daily,
        "commissioning_cargoes_required": required,
        "commissioning_cargoes_completed": 0,
        "cod_date": None,
        "status": "CONSTRUCTION",
    })
    db.trains[train["id"]] = train
    return ok_object(pub(train), 201)


@bp.get("/api/trains/<tid>")
def get_train(tid):
    auth()
    train = db.trains.get(tid)
    if not train:
        fail("ERR_NOT_FOUND", "train not found")
    return ok_object(pub(train))


@bp.post("/api/trains/<tid>/begin-commissioning")
def begin_commissioning(tid):
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    train = db.trains.get(tid)
    if not train:
        fail("ERR_NOT_FOUND", "train not found")
    if train["status"] != "CONSTRUCTION":
        fail("ERR_TRAIN_INVALID_STATE", "train is not in CONSTRUCTION")
    train["status"] = "COMMISSIONING"
    touch(train)
    return ok_object(pub(train))


@bp.post("/api/trains/<tid>/record-commissioning-cargo")
def record_commissioning_cargo(tid):
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    train = db.trains.get(tid)
    if not train:
        fail("ERR_NOT_FOUND", "train not found")
    data = body()
    req_num(data, "proceeds_usd")  # carried, not stored on the train
    if train["status"] != "COMMISSIONING":
        fail("ERR_TRAIN_INVALID_STATE", "train is not in COMMISSIONING")
    train["commissioning_cargoes_completed"] += 1
    touch(train)
    return ok_object(pub(train))


@bp.post("/api/trains/<tid>/declare-cod")
def declare_cod(tid):
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    train = db.trains.get(tid)
    if not train:
        fail("ERR_NOT_FOUND", "train not found")
    data = body()
    cod_date = data.get("cod_date")
    if not isinstance(cod_date, str):
        fail("ERR_INVALID_REQUEST", "cod_date is required")
    parse_date(cod_date, "cod_date")
    perf = req_bool(data, "performance_test_passed")
    if train["status"] != "COMMISSIONING":
        fail("ERR_TRAIN_INVALID_STATE", "train is not in COMMISSIONING")
    if train["commissioning_cargoes_completed"] < train["commissioning_cargoes_required"] or not perf:
        fail("ERR_COMMISSIONING_INCOMPLETE", "commissioning cargoes incomplete or performance test not passed")
    train["status"] = "COMMERCIAL_OPERATION"
    train["cod_date"] = cod_date
    touch(train)
    return ok_object(pub(train))


# ---- Turnarounds ----

def _turnaround_overlap(train_id, start, end, exclude_id=None):
    for t in db.turnarounds.values():
        if t["train_id"] != train_id or t["status"] == "CANCELLED":
            continue
        if exclude_id and t["id"] == exclude_id:
            continue
        # closed intervals; touching dates count as overlap
        if start <= t["_end_date"] and end >= t["_start_date"]:
            return True
    return False


@bp.post("/api/trains/<tid>/turnarounds")
def propose_turnaround(tid):
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    train = db.trains.get(tid)
    if not train:
        fail("ERR_NOT_FOUND", "train not found")
    data = body()
    start = parse_date(data.get("planned_start_date"), "planned_start_date")
    end = parse_date(data.get("planned_end_date"), "planned_end_date")
    if end < start:
        fail("ERR_INVALID_REQUEST", "planned_end_date must be on or after planned_start_date")
    if _turnaround_overlap(tid, start, end):
        fail("ERR_TURNAROUND_OVERLAP", "turnaround interval overlaps an existing turnaround")
    ta = stamp_new({
        "train_id": tid,
        "planned_start_date": data["planned_start_date"],
        "planned_end_date": data["planned_end_date"],
        "status": "PROPOSED",
        "proposed_by_user_id": user_id,
        "approved_by_user_id": None,
        "lost_production_mmbtu": None,
        "shifted_cargo_slot_count": None,
        "_start_date": start,
        "_end_date": end,
    })
    db.turnarounds[ta["id"]] = ta
    return ok_object(pub(ta), 201)


@bp.get("/api/trains/<tid>/turnarounds")
def list_turnarounds(tid):
    auth()
    train = db.trains.get(tid)
    if not train:
        fail("ERR_NOT_FOUND", "train not found")
    items = [t for t in db.turnarounds.values() if t["train_id"] == tid]
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    return paginate([pub(t) for t in items], request.args)


@bp.get("/api/turnarounds/<taid>")
def get_turnaround(taid):
    auth()
    ta = db.turnarounds.get(taid)
    if not ta:
        fail("ERR_NOT_FOUND", "turnaround not found")
    return ok_object(pub(ta))


@bp.post("/api/turnarounds/<taid>/approve")
def approve_turnaround(taid):
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    ta = db.turnarounds.get(taid)
    if not ta:
        fail("ERR_NOT_FOUND", "turnaround not found")
    if ta["status"] != "PROPOSED":
        fail("ERR_TURNAROUND_INVALID_STATE", "turnaround is not PROPOSED")
    if _turnaround_overlap(ta["train_id"], ta["_start_date"], ta["_end_date"], exclude_id=ta["id"]):
        fail("ERR_TURNAROUND_OVERLAP", "turnaround interval overlaps an existing turnaround")
    if user_id == ta["proposed_by_user_id"]:
        fail("ERR_TURNAROUND_SOD_VIOLATION", "approver must differ from proposer")
    train = db.trains[ta["train_id"]]
    length_days = (ta["_end_date"] - ta["_start_date"]).days + 1
    ta["approved_by_user_id"] = user_id
    ta["lost_production_mmbtu"] = length_days * train["daily_capacity_mmbtu"]
    ta["status"] = "APPROVED"
    touch(ta)
    return ok_object(pub(ta))


@bp.post("/api/turnarounds/<taid>/begin")
def begin_turnaround(taid):
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    ta = db.turnarounds.get(taid)
    if not ta:
        fail("ERR_NOT_FOUND", "turnaround not found")
    if ta["status"] != "APPROVED":
        fail("ERR_TURNAROUND_INVALID_STATE", "turnaround is not APPROVED")
    train = db.trains[ta["train_id"]]
    if train["status"] != "COMMERCIAL_OPERATION":
        fail("ERR_TRAIN_INVALID_STATE", "train is not in COMMERCIAL_OPERATION")
    today = db.get_clock().date()
    if today < ta["_start_date"]:
        fail("ERR_TURNAROUND_INVALID_STATE", "turnaround cannot begin before planned_start_date")

    length_days = (ta["_end_date"] - ta["_start_date"]).days + 1
    shift = timedelta(days=length_days)
    # closed interval [start 00:00, end+1day 00:00)
    iv_start = datetime(ta["_start_date"].year, ta["_start_date"].month, ta["_start_date"].day, tzinfo=timezone.utc)
    iv_end = datetime(ta["_end_date"].year, ta["_end_date"].month, ta["_end_date"].day, tzinfo=timezone.utc) + timedelta(days=1)

    shifted = 0
    affected_adps = {}
    for slot in list(db.cargo_slots.values()):
        if slot["lift_status"] not in ("SCHEDULED", "VESSEL_NOMINATED"):
            continue
        ws = slot["_window_start_dt"]
        we = slot["_window_end_dt"]
        if ws < iv_end and we > iv_start:
            slot["_window_start_dt"] = ws + shift
            slot["_window_end_dt"] = we + shift
            from util import dt_to_iso
            slot["window_start"] = dt_to_iso(slot["_window_start_dt"])
            slot["window_end"] = dt_to_iso(slot["_window_end_dt"])
            # passes through RESCHEDULED and immediately back to SCHEDULED
            slot["lift_status"] = "SCHEDULED"
            touch(slot)
            shifted += 1
            adp = db.adps.get(slot["adp_id"])
            if adp is not None:
                affected_adps[adp["id"]] = adp
    for adp in affected_adps.values():
        recompute_adp_quantities(adp)

    train["status"] = "TURNAROUND"
    touch(train)
    for berth in db.berths.values():
        if berth["status"] != "OUT_OF_SERVICE":
            berth["status"] = "OUT_OF_SERVICE"
            touch(berth)
    for pipe in db.pipelines.values():
        if pipe["status"] != "OUTAGE":
            pipe["status"] = "OUTAGE"
            touch(pipe)
    ta["shifted_cargo_slot_count"] = shifted
    ta["status"] = "IN_PROGRESS"
    touch(ta)
    return ok_object(pub(ta))


@bp.post("/api/turnarounds/<taid>/complete")
def complete_turnaround(taid):
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    ta = db.turnarounds.get(taid)
    if not ta:
        fail("ERR_NOT_FOUND", "turnaround not found")
    if ta["status"] != "IN_PROGRESS":
        fail("ERR_TURNAROUND_INVALID_STATE", "turnaround is not IN_PROGRESS")
    train = db.trains[ta["train_id"]]
    if train["status"] != "TURNAROUND":
        fail("ERR_TRAIN_INVALID_STATE", "train is not in TURNAROUND")
    ta["status"] = "COMPLETED"
    touch(ta)
    train["status"] = "COMMERCIAL_OPERATION"
    touch(train)
    if not any(t["status"] == "IN_PROGRESS" for t in db.turnarounds.values()):
        for berth in db.berths.values():
            if berth["status"] != "IN_SERVICE":
                berth["status"] = "IN_SERVICE"
                touch(berth)
        for pipe in db.pipelines.values():
            if pipe["status"] != "IN_SERVICE":
                pipe["status"] = "IN_SERVICE"
                touch(pipe)
    return ok_object(pub(ta))
