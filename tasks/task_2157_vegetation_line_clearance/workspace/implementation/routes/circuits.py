"""Circuit, reliability and outage-record endpoints."""
from flask import Blueprint, request

import constants as C
import envelope
import services
import store
import validate as V
from auth import ALL_ROLES, endpoint
from errors import ApiError

bp = Blueprint("circuits", __name__)


@bp.post("/vm/circuits")
@endpoint(["UtilityForester"])
def create_circuit():
    data = V.body()
    circuit_code = V.as_string(data, "circuit_code", min_len=3, max_len=32)
    voltage_class = V.as_enum(data, "voltage_class", C.VOLTAGE_CLASSES)
    growth_zone = V.as_enum(data, "growth_zone", C.GROWTH_ZONES)
    customer_count = V.as_integer(data, "customer_count", minimum=0)
    last_trim = V.as_date(data, "last_trim_completed_on")
    V.unique(store.circuits, "circuit_code", circuit_code)

    rec = store.new_record()
    rec.update({
        "circuit_code": circuit_code,
        "voltage_class": voltage_class,
        "growth_zone": growth_zone,
        "customer_count": customer_count,
        "last_trim_completed_on": last_trim,
        "prescription_id": None,
        "cycle_months": None,
        "next_trim_due_on": None,
        "tree_caused_outage_count_36mo": 0,
        "reliability_index_36mo": 0.00,
        "reliability_index_ytd": 0.00,
        "reliability_tier": "TIER_NORMAL",
        "trim_status": "NOT_SCHEDULED",
    })
    prescription = services.resolve_prescription_for(rec)
    rec["prescription_id"] = prescription["id"]
    services.apply_cycle(rec, bump=False)
    store.circuits[rec["id"]] = rec
    return envelope.created(store.public(rec))


@bp.post("/vm/circuits/<cid>/resolve-prescription")
@endpoint(["UtilityForester"])
def resolve_prescription(cid):
    rec = V.find(store.circuits, cid, "ERR_CIRCUIT_NOT_FOUND")
    prescription = services.resolve_prescription_for(rec)
    rec["prescription_id"] = prescription["id"]
    services.apply_cycle(rec, bump=False)
    store.touch(rec)
    return envelope.ok(store.public(rec))


@bp.get("/vm/circuits/<cid>")
@endpoint(ALL_ROLES)
def get_circuit(cid):
    rec = V.find(store.circuits, cid, "ERR_CIRCUIT_NOT_FOUND")
    return envelope.ok(store.public(rec))


@bp.get("/vm/circuits")
@endpoint(ALL_ROLES)
def list_circuits():
    return envelope.list_response(list(store.circuits.values()), {
        "prescription_id": request.args.get("prescription_id"),
        "voltage_class": request.args.get("voltage_class"),
        "growth_zone": request.args.get("growth_zone"),
        "trim_status": request.args.get("trim_status"),
        "reliability_tier": request.args.get("reliability_tier"),
    })


@bp.get("/vm/circuits/<cid>/reliability")
@endpoint(ALL_ROLES)
def circuit_reliability(cid):
    rec = V.find(store.circuits, cid, "ERR_CIRCUIT_NOT_FOUND")
    index_36, index_ytd, _count, _tier = services.recompute_reliability(rec, write=False)
    return envelope.ok({
        "circuit_id": rec["id"],
        "rolling_36_month_index": index_36,
        "program_year_to_date_index": index_ytd,
        "tree_caused_outage_count_36mo": rec.get("tree_caused_outage_count_36mo"),
        "reliability_tier": rec.get("reliability_tier"),
        "cycle_months": rec.get("cycle_months"),
        "next_trim_due_on": rec.get("next_trim_due_on"),
    })


# ---------------------------------------------------------------- outages
@bp.post("/vm/outage-records")
@endpoint(["UtilityForester"])
def create_outage():
    data = V.body()
    circuit = V.body_fk(data, "circuit_id", store.circuits, "ERR_CIRCUIT_NOT_FOUND")
    work_order = V.body_fk(data, "work_order_id", store.work_orders,
                           "ERR_WORK_ORDER_NOT_FOUND")
    if circuit is None:
        V.require(data, "circuit_id")
    outage_at = V.as_datetime(data, "outage_at")
    cause_code = V.as_enum(data, "cause_code", C.CAUSE_CODES)
    customers_affected = V.as_integer(data, "customers_affected", minimum=0)
    customer_minutes = V.as_number(data, "customer_minutes", minimum=0)

    if cause_code == "NON_TREE" and work_order is not None:
        raise ApiError("ERR_OUTAGE_CAUSE_INVALID",
                       "a NON_TREE outage may not carry a work_order_id")
    if work_order is not None:
        plan = services.plan_of_order(work_order)
        if plan is None or plan.get("circuit_id") != circuit["id"]:
            raise ApiError("ERR_OUTAGE_CAUSE_INVALID",
                           "the attributed span belongs to a different circuit")

    rec = store.new_record(common=False)
    rec.update({
        "circuit_id": circuit["id"],
        "work_order_id": work_order["id"] if work_order else None,
        "outage_at": store.iso(outage_at),
        "cause_code": cause_code,
        "customers_affected": customers_affected,
        "customer_minutes": customer_minutes,
    })
    store.outage_records[rec["id"]] = rec

    previous_tier = circuit.get("reliability_tier")
    services.recompute_reliability(circuit, write=True)
    if circuit.get("reliability_tier") != previous_tier:
        services.apply_cycle(circuit, bump=False)
    store.touch(circuit)
    return envelope.created(store.public(rec))


@bp.get("/vm/outage-records/<oid>")
@endpoint(ALL_ROLES)
def get_outage(oid):
    rec = V.find(store.outage_records, oid, "ERR_OUTAGE_RECORD_NOT_FOUND")
    return envelope.ok(store.public(rec))


@bp.get("/vm/outage-records")
@endpoint(ALL_ROLES)
def list_outages():
    return envelope.list_response(list(store.outage_records.values()), {
        "circuit_id": request.args.get("circuit_id"),
        "work_order_id": request.args.get("work_order_id"),
        "cause_code": request.args.get("cause_code"),
    })
