"""Pipelines, day schedules, nominations; cancellations settlement, feed-gas resales."""
from flask import Blueprint, request

import db
from errors import ok_object, paginate, fail
from util import (auth, require_role, body, req_str, req_int, req_num,
                  stamp_new, touch, pub, parse_date)
from services import (recompute_schedule_totals, prorate, money2, D, dec2,
                      HANDLING_FEE_PCT, PIPELINE_TARIFF)

bp = Blueprint("gas", __name__)


# ---- Pipelines ----

@bp.post("/api/pipelines")
def create_pipeline():
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    data = body()
    name = req_str(data, "name")
    cap = req_int(data, "daily_capacity_mmbtu")
    if cap <= 0:
        fail("ERR_INVALID_REQUEST", "daily_capacity_mmbtu must be > 0")
    pipe = stamp_new({
        "name": name,
        "daily_capacity_mmbtu": cap,
        "status": "IN_SERVICE",
    })
    db.pipelines[pipe["id"]] = pipe
    return ok_object(pub(pipe), 201)


@bp.get("/api/pipelines/<pid>")
def get_pipeline(pid):
    auth()
    pipe = db.pipelines.get(pid)
    if not pipe:
        fail("ERR_NOT_FOUND", "pipeline not found")
    return ok_object(pub(pipe))


@bp.post("/api/pipelines/<pid>/day-schedules")
def create_day_schedule(pid):
    user_id, role = auth()
    require_role(role, ["GasScheduler"])
    pipe = db.pipelines.get(pid)
    if not pipe:
        fail("ERR_NOT_FOUND", "pipeline not found")
    data = body()
    gas_day = parse_date(data.get("gas_day"), "gas_day")
    capacity = req_int(data, "capacity_mmbtu")
    if capacity <= 0:
        fail("ERR_INVALID_REQUEST", "capacity_mmbtu must be > 0")
    if capacity > pipe["daily_capacity_mmbtu"]:
        fail("ERR_SCHEDULE_CAPACITY_EXCEEDED", "capacity exceeds pipeline daily capacity")
    for s in db.day_schedules.values():
        if s["pipeline_id"] == pid and s["gas_day"] == data["gas_day"]:
            fail("ERR_SCHEDULE_CAPACITY_EXCEEDED", "gas_day already scheduled on this pipeline")
    sched = stamp_new({
        "pipeline_id": pid,
        "gas_day": data["gas_day"],
        "capacity_mmbtu": capacity,
        "status": "OPEN",
        "total_nominated_mmbtu": 0,
        "total_confirmed_mmbtu": 0,
        "total_cut_mmbtu": 0,
        "_gas_day": gas_day,
    })
    db.day_schedules[sched["id"]] = sched
    return ok_object(pub(sched), 201)


@bp.get("/api/pipelines/<pid>/day-schedules")
def list_day_schedules(pid):
    auth()
    pipe = db.pipelines.get(pid)
    if not pipe:
        fail("ERR_NOT_FOUND", "pipeline not found")
    items = [s for s in db.day_schedules.values() if s["pipeline_id"] == pid]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return paginate([pub(s) for s in items], request.args)


@bp.get("/api/pipeline-day-schedules/<sid>")
def get_day_schedule(sid):
    auth()
    sched = db.day_schedules.get(sid)
    if not sched:
        fail("ERR_NOT_FOUND", "day schedule not found")
    return ok_object(pub(sched))


@bp.post("/api/pipeline-day-schedules/<sid>/close")
def close_day_schedule(sid):
    user_id, role = auth()
    require_role(role, ["GasScheduler"])
    sched = db.day_schedules.get(sid)
    if not sched:
        fail("ERR_NOT_FOUND", "day schedule not found")
    if sched["status"] != "OPEN":
        fail("ERR_SCHEDULE_INVALID_STATE", "schedule is not OPEN")
    prorate(sched)
    sched["status"] = "CLOSED"
    recompute_schedule_totals(sched)
    touch(sched)
    return ok_object(pub(sched))


@bp.post("/api/pipeline-day-schedules/<sid>/nominations")
def create_nomination(sid):
    user_id, role = auth()
    require_role(role, ["GasScheduler", "CustomerRep"])
    sched = db.day_schedules.get(sid)
    if not sched:
        fail("ERR_NOT_FOUND", "day schedule not found")
    data = body()
    cargo_slot_id = data.get("cargo_slot_id")
    if not isinstance(cargo_slot_id, str) or not cargo_slot_id:
        fail("ERR_INVALID_REQUEST", "cargo_slot_id is required")
    nominated = req_int(data, "nominated_mmbtu")
    slot = db.cargo_slots.get(cargo_slot_id)
    if not slot:
        fail("ERR_NOT_FOUND", "cargo_slot_id does not exist")
    if role == "CustomerRep":
        from services import owning_customer_id_of_slot, check_customer_owner
        check_customer_owner(user_id, owning_customer_id_of_slot(slot))
    if sched["status"] != "OPEN":
        fail("ERR_SCHEDULE_INVALID_STATE", "schedule is CLOSED")
    pipe = db.pipelines[sched["pipeline_id"]]
    if pipe["status"] != "IN_SERVICE":
        fail("ERR_PIPELINE_NOT_SERVICEABLE", "pipeline is in OUTAGE")
    if nominated <= 0 or nominated > slot["scheduled_feed_gas_mmbtu"]:
        fail("ERR_NOMINATION_QUANTITY_MISMATCH", "nominated_mmbtu out of bounds")
    nom = stamp_new({
        "pipeline_day_schedule_id": sid,
        "cargo_slot_id": cargo_slot_id,
        "nominated_mmbtu": nominated,
        "confirmed_mmbtu": 0,
        "cut_mmbtu": 0,
        "status": "SUBMITTED",
    })
    db.nominations[nom["id"]] = nom
    recompute_schedule_totals(sched)
    touch(sched)
    return ok_object(pub(nom), 201)


@bp.get("/api/pipeline-day-schedules/<sid>/nominations")
def list_nominations(sid):
    auth()
    sched = db.day_schedules.get(sid)
    if not sched:
        fail("ERR_NOT_FOUND", "day schedule not found")
    items = [n for n in db.nominations.values() if n["pipeline_day_schedule_id"] == sid]
    items.sort(key=lambda n: (n["created_at"], n["id"]))
    return paginate([pub(n) for n in items], request.args)


@bp.get("/api/feed-gas-nominations/<nid>")
def get_nomination(nid):
    auth()
    nom = db.nominations.get(nid)
    if not nom:
        fail("ERR_NOT_FOUND", "nomination not found")
    return ok_object(pub(nom))


@bp.post("/api/feed-gas-nominations/<nid>/reconcile")
def reconcile_nomination(nid):
    user_id, role = auth()
    require_role(role, ["GasScheduler"])
    nom = db.nominations.get(nid)
    if not nom:
        fail("ERR_NOT_FOUND", "nomination not found")
    if nom["status"] != "CONFIRMED":
        fail("ERR_NOMINATION_INVALID_STATE", "nomination is not CONFIRMED")
    sched = db.day_schedules[nom["pipeline_day_schedule_id"]]
    if sched["status"] != "CLOSED":
        fail("ERR_PIPELINE_NOT_SERVICEABLE", "schedule is not CLOSED")
    nom["status"] = "RECONCILED"
    touch(nom)
    return ok_object(pub(nom))


# ---- Cancellations / resales ----

@bp.get("/api/cargo-cancellations/<cid>")
def get_cancellation(cid):
    auth()
    c = db.cancellations.get(cid)
    if not c:
        fail("ERR_NOT_FOUND", "cancellation not found")
    return ok_object(pub(c))


@bp.post("/api/cargo-cancellations/<cid>/settle")
def settle_cancellation(cid):
    user_id, role = auth()
    require_role(role, ["CommercialManager"])
    c = db.cancellations.get(cid)
    if not c:
        fail("ERR_NOT_FOUND", "cancellation not found")
    if c["status"] != "REGISTERED":
        fail("ERR_CANCELLATION_INVALID_STATE", "cancellation is not REGISTERED")
    resales = [r for r in db.resales.values() if r["cargo_cancellation_id"] == cid]
    for r in resales:
        if r["status"] == "OFFERED":
            r["status"] = "UNSOLD"
            touch(r)
    sold = [r for r in resales if r["status"] == "SOLD"]
    fixed_fee = D(c["fixed_fee_due_usd"])
    gross = sum(D(r["gross_proceeds_usd"]) for r in sold)
    handling = dec2(HANDLING_FEE_PCT * fixed_fee)
    tariff = dec2(PIPELINE_TARIFF * sum(D(r["offered_volume_mmbtu"]) for r in sold))
    credit = min(fixed_fee, max(D(0), gross - handling - tariff))
    net = dec2(fixed_fee - credit)
    c["resale_credit_usd"] = float(credit)
    c["net_due_usd"] = float(net)
    c["status"] = "SETTLED"
    touch(c)
    slot = db.cargo_slots[c["cargo_slot_id"]]
    if slot["billing_status"] == "UNBILLED":
        slot["billing_status"] = "FINAL_INVOICED"
        touch(slot)
    return ok_object(pub(c))


@bp.post("/api/cargo-cancellations/<cid>/resales")
def create_resale(cid):
    user_id, role = auth()
    require_role(role, ["GasScheduler"])
    c = db.cancellations.get(cid)
    if not c:
        fail("ERR_NOT_FOUND", "cancellation not found")
    data = body()
    volume = req_int(data, "offered_volume_mmbtu")
    if c["status"] != "REGISTERED":
        fail("ERR_CANCELLATION_INVALID_STATE", "cancellation is not REGISTERED")
    slot = db.cargo_slots[c["cargo_slot_id"]]
    already = sum(r["offered_volume_mmbtu"] for r in db.resales.values()
                  if r["cargo_cancellation_id"] == cid and r["status"] != "UNSOLD")
    if volume <= 0 or already + volume > slot["scheduled_feed_gas_mmbtu"]:
        fail("ERR_RESALE_VOLUME_EXCEEDED", "offered volume exceeds cancelled feed gas")
    resale = stamp_new({
        "cargo_cancellation_id": cid,
        "offered_volume_mmbtu": volume,
        "status": "OFFERED",
        "sale_price_usd_per_mmbtu": None,
        "gross_proceeds_usd": None,
    })
    db.resales[resale["id"]] = resale
    return ok_object(pub(resale), 201)


@bp.get("/api/cargo-cancellations/<cid>/resales")
def list_resales(cid):
    auth()
    c = db.cancellations.get(cid)
    if not c:
        fail("ERR_NOT_FOUND", "cancellation not found")
    items = [r for r in db.resales.values() if r["cargo_cancellation_id"] == cid]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return paginate([pub(r) for r in items], request.args)


@bp.post("/api/feed-gas-resales/<rid>/sell")
def sell_resale(rid):
    user_id, role = auth()
    require_role(role, ["GasScheduler"])
    resale = db.resales.get(rid)
    if not resale:
        fail("ERR_NOT_FOUND", "resale not found")
    data = body()
    price = req_num(data, "sale_price_usd_per_mmbtu", min_value=0, min_exclusive=True)
    if resale["status"] != "OFFERED":
        fail("ERR_RESALE_INVALID_STATE", "resale is not OFFERED")
    resale["sale_price_usd_per_mmbtu"] = price
    resale["gross_proceeds_usd"] = money2(D(resale["offered_volume_mmbtu"]) * D(price))
    resale["status"] = "SOLD"
    touch(resale)
    return ok_object(pub(resale))
