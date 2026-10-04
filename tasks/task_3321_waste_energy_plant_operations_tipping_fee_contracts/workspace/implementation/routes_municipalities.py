"""Municipalities and host community agreements."""

from flask import Blueprint, request

from auth import require_role
from db import store
from errors import err_422, err_not_found, err_invalid_request
from helpers import (body_json, new_entity, parse_dt, require_fields, success_list,
                     success_obj, to_decimal, to_int)
from serializers import municipality_out, host_agreement_out

bp = Blueprint("municipalities", __name__)

CM = ["ContractsManager"]
READERS_M = ["PlantOperator", "ContractsManager", "EnergyTrader", "EnvironmentalOfficer", "Regulator"]
READERS_H = ["PlantOperator", "ContractsManager", "Regulator"]


@bp.post("/wte/municipalities")
def create_municipality():
    require_role(CM)
    b = body_json()
    require_fields(b, ["legal_name", "population_served"])
    legal_name = b["legal_name"]
    if not isinstance(legal_name, str) or not legal_name:
        raise err_invalid_request("legal_name must be a non-empty string")
    population = to_int(b["population_served"], "population_served")
    if population < 0:
        raise err_invalid_request("population_served must be >= 0")
    is_host = b.get("is_host_community", False)
    if not isinstance(is_host, bool):
        raise err_invalid_request("is_host_community must be a boolean")
    priority = b.get("priority_group", "STANDARD")
    if priority not in ("HOST", "STANDARD"):
        raise err_invalid_request("priority_group must be HOST or STANDARD")
    if priority == "HOST" and not is_host:
        raise err_invalid_request("priority_group HOST requires is_host_community = true")
    m = new_entity({
        "legal_name": legal_name,
        "population_served": population,
        "is_host_community": is_host,
        "priority_group": priority,
    })
    store.municipalities[m["id"]] = m
    return success_obj(municipality_out(m), 201)


@bp.get("/wte/municipalities")
def list_municipalities():
    require_role(READERS_M)
    items = sorted(store.municipalities.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("is_host_community")
    if q is not None:
        want = q.lower() == "true"
        items = [m for m in items if m["is_host_community"] == want]
    return success_list([municipality_out(m) for m in items])


@bp.get("/wte/municipalities/<mid>")
def get_municipality(mid):
    require_role(READERS_M)
    m = store.municipalities.get(mid)
    if m is None:
        raise err_not_found("municipality not found")
    return success_obj(municipality_out(m))


@bp.post("/wte/host-community-agreements")
def create_host_agreement():
    require_role(CM)
    b = body_json()
    require_fields(b, ["municipality_id", "annual_payment_cents", "payment_due_month",
                       "effective_start", "effective_end"])
    m = store.municipalities.get(b["municipality_id"])
    if m is None:
        raise err_not_found("municipality not found")
    payment = to_int(b["annual_payment_cents"], "annual_payment_cents")
    if payment < 0:
        raise err_invalid_request("annual_payment_cents must be >= 0")
    due_month = to_int(b["payment_due_month"], "payment_due_month")
    if due_month < 1 or due_month > 12:
        raise err_invalid_request("payment_due_month must be 1..12")
    eff_start = parse_dt(b["effective_start"], "effective_start")
    eff_end = parse_dt(b["effective_end"], "effective_end")
    if not eff_end > eff_start:
        raise err_invalid_request("effective_end must be after effective_start")
    priority = b.get("local_waste_priority_enabled", True)
    if not isinstance(priority, bool):
        raise err_invalid_request("local_waste_priority_enabled must be a boolean")
    if not m["is_host_community"]:
        raise err_422("ERR_NOT_HOST_COMMUNITY",
                      "municipality is not flagged is_host_community")
    # Closed intervals on both ends: touching endpoints ARE an overlap.
    for h in store.host_agreements.values():
        if h["municipality_id"] == m["id"]:
            if eff_start <= h["effective_end"] and eff_end >= h["effective_start"]:
                raise err_422("ERR_HOST_AGREEMENT_OVERLAP",
                              "host agreement effective window overlaps an existing agreement")
    h = new_entity({
        "municipality_id": m["id"],
        "annual_payment_cents": payment,
        "payment_due_month": due_month,
        "local_waste_priority_enabled": priority,
        "effective_start": eff_start,
        "effective_end": eff_end,
    })
    store.host_agreements[h["id"]] = h
    return success_obj(host_agreement_out(h), 201)


@bp.get("/wte/host-community-agreements")
def list_host_agreements():
    require_role(READERS_H)
    items = sorted(store.host_agreements.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("municipality_id")
    if q is not None:
        items = [h for h in items if h["municipality_id"] == q]
    return success_list([host_agreement_out(h) for h in items])


@bp.get("/wte/host-community-agreements/<hid>")
def get_host_agreement(hid):
    require_role(READERS_H)
    h = store.host_agreements.get(hid)
    if h is None:
        raise err_not_found("host community agreement not found")
    return success_obj(host_agreement_out(h))
