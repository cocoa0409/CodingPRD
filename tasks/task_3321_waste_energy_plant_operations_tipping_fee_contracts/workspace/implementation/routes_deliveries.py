"""Waste deliveries: schedule, edit, receive (tip-floor allocation), accept
(OCC + fee), reject, divert."""

from decimal import Decimal

from flask import Blueprint, request

from auth import require_role
from db import store
from errors import err_422, err_invalid_state, err_not_found, err_invalid_request, err_stale_version
from helpers import (body_json, new_entity, parse_dt, require_fields, success_list,
                     success_obj, to_decimal, touch)
from calculations import compute_tipping_fee, outage_length_days, DAILY_CAPACITY_TONNES
from routes_agreements import recompute_cumulative
from serializers import delivery_out

bp = Blueprint("deliveries", __name__)

PO = ["PlantOperator"]
READERS = ["PlantOperator", "ContractsManager", "Regulator"]
LIST_READERS = ["PlantOperator", "ContractsManager", "EnvironmentalOfficer", "Regulator"]


def _projected_fee(d):
    if d["status"] == "SCHEDULED":
        a = store.agreements.get(d["agreement_id"])
        if a is not None:
            return compute_tipping_fee(d["tonnes"], a["tipping_fee_per_tonne_cents"])
    return None


@bp.post("/wte/waste-deliveries")
def create_delivery():
    require_role(PO)
    b = body_json()
    require_fields(b, ["agreement_id", "manifest_ref", "tonnes",
                       "heating_value_mj_per_kg", "delivered_at"])
    a = store.agreements.get(b["agreement_id"])
    if a is None:
        raise err_not_found("agreement not found")
    manifest = b["manifest_ref"]
    if not isinstance(manifest, str) or not manifest:
        raise err_invalid_request("manifest_ref must be a non-empty string")
    for d in store.deliveries.values():
        if d["manifest_ref"] == manifest:
            raise err_422("ERR_DUPLICATE_MANIFEST", "manifest_ref already used")
    tonnes = to_decimal(b["tonnes"], "tonnes")
    if tonnes <= 0:
        raise err_invalid_request("tonnes must be > 0")
    hv = to_decimal(b["heating_value_mj_per_kg"], "heating_value_mj_per_kg")
    if hv <= 0:
        raise err_invalid_request("heating_value_mj_per_kg must be > 0")
    delivered_at = parse_dt(b["delivered_at"], "delivered_at")
    d = new_entity({
        "agreement_id": a["id"],
        "manifest_ref": manifest,
        "tonnes": tonnes,
        "heating_value_mj_per_kg": hv,
        "delivered_at": delivered_at,
        "status": "SCHEDULED",
        "tipping_fee_cents": None,
        "diversion_outage_id": None,
        "reject_reason": None,
    })
    store.deliveries[d["id"]] = d
    return success_obj(delivery_out(d, _projected_fee(d)), 201)


@bp.get("/wte/waste-deliveries")
def list_deliveries():
    require_role(LIST_READERS)
    items = sorted(store.deliveries.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("agreement_id")
    if q is not None:
        items = [d for d in items if d["agreement_id"] == q]
    q = request.args.get("status")
    if q is not None:
        items = [d for d in items if d["status"] == q]
    q = request.args.get("diversion_outage_id")
    if q is not None:
        items = [d for d in items if d["diversion_outage_id"] == q]
    return success_list([delivery_out(d, _projected_fee(d)) for d in items])


@bp.get("/wte/waste-deliveries/<did>")
def get_delivery(did):
    require_role(READERS)
    d = store.deliveries.get(did)
    if d is None:
        raise err_not_found("delivery not found")
    return success_obj(delivery_out(d, _projected_fee(d)))


@bp.put("/wte/waste-deliveries/<did>")
def update_delivery(did):
    require_role(PO)
    d = store.deliveries.get(did)
    if d is None:
        raise err_not_found("delivery not found")
    if d["status"] != "SCHEDULED":
        raise err_invalid_state("only SCHEDULED deliveries may be edited")
    b = body_json()
    if "tonnes" in b:
        t = to_decimal(b["tonnes"], "tonnes")
        if t <= 0:
            raise err_invalid_request("tonnes must be > 0")
        d["tonnes"] = t
    if "heating_value_mj_per_kg" in b:
        hv = to_decimal(b["heating_value_mj_per_kg"], "heating_value_mj_per_kg")
        if hv <= 0:
            raise err_invalid_request("heating_value_mj_per_kg must be > 0")
        d["heating_value_mj_per_kg"] = hv
    if "delivered_at" in b:
        d["delivered_at"] = parse_dt(b["delivered_at"], "delivered_at")
    touch(d)
    return success_obj(delivery_out(d, _projected_fee(d)))


def _host_priority_applies(d):
    """True when the delivery's municipality holds an in-window host agreement
    with local_waste_priority_enabled == true."""
    a = store.agreements.get(d["agreement_id"])
    if a is None:
        return False
    now = store.logical_now
    for h in store.host_agreements.values():
        if (h["municipality_id"] == a["municipality_id"]
                and h["local_waste_priority_enabled"]
                and h["effective_start"] <= now <= h["effective_end"]):
            return True
    return False


@bp.post("/wte/waste-deliveries/<did>/receive")
def receive_delivery(did):
    require_role(PO)
    d = store.deliveries.get(did)
    if d is None:
        raise err_not_found("delivery not found")
    if d["status"] != "SCHEDULED":
        raise err_invalid_state("delivery is not SCHEDULED")
    a = store.agreements.get(d["agreement_id"])
    if a is None or a["state"] != "ACTIVE":
        raise err_invalid_state("agreement is not ACTIVE")
    day = d["delivered_at"].strftime("%Y-%m-%d")
    day_load = sum(
        (x["tonnes"] for x in store.deliveries.values()
         if x["id"] != d["id"]
         and x["delivered_at"].strftime("%Y-%m-%d") == day
         and x["status"] in ("SCHEDULED", "RECEIVED")), Decimal("0"))
    if day_load + d["tonnes"] > DAILY_CAPACITY_TONNES:
        if not _host_priority_applies(d):
            raise err_422("ERR_PRIORITY_NOT_AVAILABLE",
                          "daily tip-floor allocation exhausted and no host priority applies")
    d["status"] = "RECEIVED"
    touch(d)
    return success_obj(delivery_out(d, _projected_fee(d)))


@bp.post("/wte/waste-deliveries/<did>/accept")
def accept_delivery(did):
    require_role(PO)
    d = store.deliveries.get(did)
    if d is None:
        raise err_not_found("delivery not found")
    if d["status"] != "RECEIVED":
        raise err_invalid_state("delivery is not RECEIVED")
    a = store.agreements.get(d["agreement_id"])
    if a is None or a["state"] != "ACTIVE":
        raise err_invalid_state("agreement is not ACTIVE")
    if not any(b["status"] in ("ONLINE", "DERATED") for b in store.boilers.values()):
        raise err_422("ERR_NO_BOILER_AVAILABLE", "no boiler in ONLINE or DERATED status")
    b = body_json()
    expected = b.get("expected_agreement_version")
    if expected is None or expected != a["version"]:
        raise err_stale_version("expected_agreement_version does not match agreement version")
    d["tipping_fee_cents"] = compute_tipping_fee(d["tonnes"], a["tipping_fee_per_tonne_cents"])
    d["status"] = "ACCEPTED"
    touch(d)
    a["cumulative_delivered_tonnes"] = a["cumulative_delivered_tonnes"] + d["tonnes"]
    touch(a)
    return success_obj(delivery_out(d, _projected_fee(d)))


@bp.post("/wte/waste-deliveries/<did>/reject")
def reject_delivery(did):
    require_role(PO)
    d = store.deliveries.get(did)
    if d is None:
        raise err_not_found("delivery not found")
    if d["status"] != "RECEIVED":
        raise err_invalid_state("delivery is not RECEIVED")
    b = body_json()
    reason = b.get("reject_reason")
    if reason is None or (isinstance(reason, str) and not reason):
        raise err_invalid_request("reject_reason is required")
    d["reject_reason"] = reason
    d["status"] = "REJECTED"
    touch(d)
    return success_obj(delivery_out(d, _projected_fee(d)))


@bp.post("/wte/waste-deliveries/<did>/divert")
def divert_delivery(did):
    require_role(PO)
    d = store.deliveries.get(did)
    if d is None:
        raise err_not_found("delivery not found")
    if d["status"] != "SCHEDULED":
        raise err_invalid_state("delivery is not SCHEDULED")
    b = body_json()
    outage_id = b.get("outage_id")
    if outage_id is None:
        raise err_invalid_request("outage_id is required")
    o = store.outages.get(outage_id)
    if o is None:
        raise err_not_found("outage not found")
    plan = None
    for p in store.diversion_plans.values():
        if p["outage_id"] == o["id"] and p["approved"]:
            plan = p
            break
    if o["status"] != "ACTIVE" or plan is None:
        raise err_422("ERR_DIVERSION_CAPACITY_EXCEEDED",
                      "outage is not ACTIVE or has no approved diversion plan")
    diverted = sum(
        (x["tonnes"] for x in store.deliveries.values()
         if x["diversion_outage_id"] == o["id"] and x["status"] == "DIVERTED"),
        Decimal("0"))
    cap = plan["max_diversion_tpd"] * Decimal(outage_length_days(o))
    if diverted + d["tonnes"] > cap:
        raise err_422("ERR_DIVERSION_CAPACITY_EXCEEDED",
                      "diversion capacity exceeded for this outage")
    # Mark the eligible leg with the largest planned_tonnes (tie: created_at ASC)
    legs = [lg for lg in store.diversion_legs.values()
            if lg["diversion_plan_id"] == plan["id"] and not lg["executed"]]
    if legs:
        legs.sort(key=lambda lg: (lg["created_at"], lg["id"]))
        best = max(legs, key=lambda lg: lg["planned_tonnes"])
        best["executed"] = True
        touch(best)
    d["status"] = "DIVERTED"
    d["diversion_outage_id"] = o["id"]
    touch(d)
    return success_obj(delivery_out(d, _projected_fee(d)))
