"""Store resource group, including the production-day sweeps and posture reads."""
from decimal import Decimal

import calc
import services as svc
from errors import fail, invalid
from http_support import (
    Endpoint, as_bool, as_int, as_number, as_string, body, envelope_array,
    opt, query, req,
)
from response import ok_object
from util import parse_dt, to_dec
import views

READ_ROLES = ["PlatformAdmin", "DeliManager", "DeliClerk", "BakeryCoordinator",
              "ScaleOperator"]
WRITE_ROLES = ["PlatformAdmin", "DeliManager"]


def register(app):
    Endpoint(app, "POST", "/deli/stores", WRITE_ROLES, create_store)
    Endpoint(app, "GET", "/deli/stores/<id>", READ_ROLES, get_store)
    Endpoint(app, "GET", "/deli/stores", READ_ROLES, list_stores)
    Endpoint(app, "POST", "/deli/stores/<id>/run-production-day", WRITE_ROLES,
             run_one)
    Endpoint(app, "PATCH", "/deli/run-production-day", WRITE_ROLES, run_chain)
    Endpoint(app, "POST", "/deli/posture-gate", WRITE_ROLES, posture_gate)
    Endpoint(app, "GET", "/deli/posture-report", READ_ROLES, posture_report)


def create_store(store, actor, view_args):
    payload = body()
    store_number = as_string(req(payload, "store_number"), "store_number")
    if any(s["store_number"] == store_number for s in store.stores.values()):
        invalid("store_number must be unique across the chain.")
    name = as_string(req(payload, "name"), "name")
    case_capacity = as_number(req(payload, "deli_case_capacity_lbs"),
                              "deli_case_capacity_lbs")
    hot_capacity = as_number(req(payload, "hot_bar_capacity_lbs"),
                             "hot_bar_capacity_lbs")
    stations = as_int(req(payload, "sub_station_count"), "sub_station_count")
    if case_capacity <= 0:
        invalid("deli_case_capacity_lbs must be greater than 0.")
    if hot_capacity <= 0:
        invalid("hot_bar_capacity_lbs must be greater than 0.")
    if stations < 1:
        invalid("sub_station_count must be at least 1.")
    row = svc.create(store, "stores", {
        "store_number": store_number,
        "name": name,
        "deli_case_capacity_lbs": case_capacity,
        "hot_bar_capacity_lbs": hot_capacity,
        "sub_station_count": stations,
        "haccp_safety_flag": as_bool(opt(payload, "haccp_safety_flag", default=False),
                                     "haccp_safety_flag"),
        "case_on_hand_lbs": Decimal(0),
        "posture": "OPEN",
        "posture_gate_flag": False,
        "posture_reason": "OK",
        "certified_slicer_operator_count": 0,
        "active_price_file_id": None,
        "targeted_promo_id": None,
        "covered_allergen_set": [],
        "available_bread_units": 0,
        "verified_waste_liability_cents": 0,
        "pending_waste_verification_count": 0,
        "ops_run_index": 0,
        "logical_clock_at_last_run": None,
    })
    svc.recompute_store(store, row["id"], bump=False)
    return ok_object(store, views.store(row), 201)


def get_store(store, actor, view_args):
    row = svc.get_store(store, view_args["id"])
    svc.recompute_store(store, row["id"])
    return ok_object(store, views.store(row))


def list_stores(store, actor, view_args):
    rows = svc.all_rows(store, "stores")
    for row in rows:
        svc.recompute_store(store, row["id"])
    posture = query("posture")
    if posture:
        rows = [r for r in rows if r["posture"] == posture]
    return envelope_array(store, rows, views.store)


def run_one(store, actor, view_args):
    store_id = view_args["id"]
    svc.get_store(store, store_id)
    svc.run_production_day(store, [store_id])
    return ok_object(store, views.store(store.stores[store_id]))


def run_chain(store, actor, view_args):
    store_id = query("store_id")
    if store_id is not None:
        svc.get_store(store, store_id)
        scope = [store_id]
    else:
        scope = [s["id"] for s in svc.all_rows(store, "stores")]
    svc.run_production_day(store, scope)
    return envelope_array(store, [store.stores[s] for s in scope], views.store)


def posture_gate(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    row = svc.get_store(store, store_id)
    flag = as_bool(req(payload, "posture_gate_flag"), "posture_gate_flag")
    row["posture_gate_flag"] = flag
    svc.touch(store, row)
    svc.recompute_store(store, store_id, bump=False)
    if flag and store.stores[store_id]["posture"] == "HALT":
        svc.store_halt_cascade(store, store_id)
        svc.recompute_store(store, store_id, bump=False)
    return ok_object(store, views.store(store.stores[store_id]))


def posture_report(store, actor, view_args):
    store_id = query("store_id")
    if store_id is None:
        invalid("store_id is required.")
    row = svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    associates = svc.all_rows(store, "associates")
    certs = svc.all_rows(store, "certifications")
    waste = svc.all_rows(store, "waste_records")
    slicers = svc.all_rows(store, "slicers")
    protection, diffusion = calc.diffusion_index(
        row, associates, certs, waste, slicers, store.now())
    newest = 0
    completed = [
        t for t in svc.all_rows(store, "sub_tickets")
        if t["store_id"] == store_id and t["status"] in ("COMPLETED", "PICKED_UP")
    ]
    completed.sort(key=lambda t: parse_dt(t["completed_at"] or t["created_at"]))
    if completed:
        newest = completed[-1]["lateness_minutes"]
    return ok_object(store, {
        "store_id": store_id,
        "posture": row["posture"],
        "posture_reason": row["posture_reason"],
        "protection_index": protection,
        "diffusion_index": diffusion,
        "newest_completed_ticket_lateness_minutes": newest,
        "certified_slicer_operator_count": row["certified_slicer_operator_count"],
        "case_on_hand_lbs": float(to_dec(row["case_on_hand_lbs"])),
    })