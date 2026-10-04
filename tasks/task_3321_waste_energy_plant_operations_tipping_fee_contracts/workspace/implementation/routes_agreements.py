"""Waste supply agreements: create (incl. amendments with OCC), activate,
terminate, list/get."""

from flask import Blueprint, request

from auth import require_role
from db import store
from errors import err_invalid_state, err_not_found, err_invalid_request, err_stale_version
from helpers import (body_json, new_entity, parse_dt, require_fields, success_list,
                     success_obj, to_decimal, to_int, touch)
from serializers import agreement_out

bp = Blueprint("agreements", __name__)

CM = ["ContractsManager"]
READERS = ["PlantOperator", "ContractsManager", "Regulator"]


def recompute_cumulative(agreement):
    from decimal import Decimal
    total = sum(
        (d["tonnes"] for d in store.deliveries.values()
         if d["agreement_id"] == agreement["id"] and d["status"] == "ACCEPTED"),
        Decimal("0"))
    agreement["cumulative_delivered_tonnes"] = total


@bp.post("/wte/waste-supply-agreements")
def create_agreement():
    require_role(CM)
    b = body_json()
    require_fields(b, ["municipality_id", "term_start", "term_end",
                       "guaranteed_annual_tonnage", "tipping_fee_per_tonne_cents"])
    m = store.municipalities.get(b["municipality_id"])
    if m is None:
        raise err_not_found("municipality not found")
    base = None
    amend_id = b.get("amendment_of_agreement_id")
    if amend_id is not None:
        base = store.agreements.get(amend_id)
        if base is None:
            raise err_not_found("base agreement not found")
        if base["state"] != "ACTIVE":
            raise err_invalid_state("base agreement is not ACTIVE")
        # OCC guard (priority 22) — runs before field-shape checks
        expected = b.get("expected_base_agreement_version")
        if expected is None or expected != base["version"]:
            raise err_stale_version("expected_base_agreement_version does not match base agreement version")
    term_start = parse_dt(b["term_start"], "term_start")
    term_end = parse_dt(b["term_end"], "term_end")
    if not term_end > term_start:
        raise err_invalid_request("term_end must be after term_start")
    tonnage = to_decimal(b["guaranteed_annual_tonnage"], "guaranteed_annual_tonnage")
    if tonnage <= 0:
        raise err_invalid_request("guaranteed_annual_tonnage must be > 0")
    fee = to_int(b["tipping_fee_per_tonne_cents"], "tipping_fee_per_tonne_cents")
    if fee < 0:
        raise err_invalid_request("tipping_fee_per_tonne_cents must be >= 0")
    cadence = b.get("put_or_pay_settlement_cadence", "ANNUAL")
    if cadence not in ("ANNUAL", "MONTHLY"):
        raise err_invalid_request("put_or_pay_settlement_cadence must be ANNUAL or MONTHLY")
    from decimal import Decimal
    a = new_entity({
        "municipality_id": m["id"],
        "term_start": term_start,
        "term_end": term_end,
        "guaranteed_annual_tonnage": tonnage,
        "tipping_fee_per_tonne_cents": fee,
        "put_or_pay_settlement_cadence": cadence,
        "state": "ACTIVE" if base is not None else "DRAFT",
        "amendment_of_agreement_id": amend_id,
        "cumulative_delivered_tonnes": Decimal("0"),
    })
    store.agreements[a["id"]] = a
    if base is not None:
        base["guaranteed_annual_tonnage"] = tonnage
        base["tipping_fee_per_tonne_cents"] = fee
        touch(base)
    return success_obj(agreement_out(a), 201)


@bp.get("/wte/waste-supply-agreements")
def list_agreements():
    require_role(READERS)
    items = sorted(store.agreements.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("municipality_id")
    if q is not None:
        items = [a for a in items if a["municipality_id"] == q]
    q = request.args.get("state")
    if q is not None:
        items = [a for a in items if a["state"] == q]
    q = request.args.get("amendment_of_agreement_id")
    if q is not None:
        items = [a for a in items if a["amendment_of_agreement_id"] == q]
    return success_list([agreement_out(a) for a in items])


@bp.get("/wte/waste-supply-agreements/<aid>")
def get_agreement(aid):
    require_role(READERS)
    a = store.agreements.get(aid)
    if a is None:
        raise err_not_found("agreement not found")
    return success_obj(agreement_out(a))


@bp.post("/wte/waste-supply-agreements/<aid>/activate")
def activate_agreement(aid):
    require_role(CM)
    a = store.agreements.get(aid)
    if a is None:
        raise err_not_found("agreement not found")
    if a["state"] != "DRAFT":
        raise err_invalid_state("agreement is not DRAFT")
    if not a["term_end"] > store.logical_now:
        raise err_invalid_state("agreement term_end is not in the future")
    if a["guaranteed_annual_tonnage"] <= 0:
        raise err_invalid_state("guaranteed_annual_tonnage must be > 0")
    a["state"] = "ACTIVE"
    touch(a)
    return success_obj(agreement_out(a))


@bp.post("/wte/waste-supply-agreements/<aid>/terminate")
def terminate_agreement(aid):
    require_role(CM)
    a = store.agreements.get(aid)
    if a is None:
        raise err_not_found("agreement not found")
    if a["state"] != "ACTIVE":
        raise err_invalid_state("agreement is not ACTIVE")
    # Cascade: SCHEDULED deliveries -> DIVERTED (diversion_outage_id stays null)
    for d in store.deliveries.values():
        if d["agreement_id"] == a["id"] and d["status"] == "SCHEDULED":
            d["status"] = "DIVERTED"
            d["diversion_outage_id"] = None
            touch(d)
    a["state"] = "TERMINATED"
    recompute_cumulative(a)
    touch(a)
    return success_obj(agreement_out(a))
