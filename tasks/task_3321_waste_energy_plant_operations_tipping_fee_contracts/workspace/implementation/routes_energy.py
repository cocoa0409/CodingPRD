"""Power purchase agreements and energy deliveries."""

from flask import Blueprint, request

from auth import require_role
from db import store
from errors import err_422, err_invalid_state, err_not_found, err_invalid_request
from helpers import (body_json, new_entity, parse_dt, require_fields, success_list,
                     success_obj, to_decimal, to_int, touch)
from calculations import compute_energy_billing, compute_capacity_payment
from serializers import ppa_out, energy_delivery_out

bp = Blueprint("energy", __name__)

ET = ["EnergyTrader"]
READERS = ["EnergyTrader", "PlantOperator", "Regulator"]
READERS_ED = ["EnergyTrader", "Regulator"]


@bp.post("/wte/power-purchase-agreements")
def create_ppa():
    require_role(ET)
    b = body_json()
    require_fields(b, ["counterparty_name", "kind", "energy_rate_cents_per_mwh",
                       "capacity_payment_cents_per_mw_month", "contracted_mw",
                       "term_start", "term_end"])
    name = b["counterparty_name"]
    if not isinstance(name, str) or not name:
        raise err_invalid_request("counterparty_name must be a non-empty string")
    kind = b["kind"]
    if kind not in ("PPA", "MERCHANT"):
        raise err_invalid_request("kind must be PPA or MERCHANT")
    rate = to_int(b["energy_rate_cents_per_mwh"], "energy_rate_cents_per_mwh")
    if rate < 0:
        raise err_invalid_request("energy_rate_cents_per_mwh must be >= 0")
    cap_pay = to_int(b["capacity_payment_cents_per_mw_month"], "capacity_payment_cents_per_mw_month")
    if cap_pay < 0:
        raise err_invalid_request("capacity_payment_cents_per_mw_month must be >= 0")
    if kind == "MERCHANT" and cap_pay != 0:
        raise err_invalid_request("capacity_payment_cents_per_mw_month must be 0 for MERCHANT")
    contracted = to_decimal(b["contracted_mw"], "contracted_mw")
    if contracted <= 0:
        raise err_invalid_request("contracted_mw must be > 0")
    ts = parse_dt(b["term_start"], "term_start")
    te = parse_dt(b["term_end"], "term_end")
    if not te > ts:
        raise err_invalid_request("term_end must be after term_start")
    p = new_entity({
        "counterparty_name": name,
        "kind": kind,
        "energy_rate_cents_per_mwh": rate,
        "capacity_payment_cents_per_mw_month": cap_pay,
        "contracted_mw": contracted,
        "term_start": ts,
        "term_end": te,
        "status": "DRAFT",
    })
    store.ppas[p["id"]] = p
    return success_obj(ppa_out(p), 201)


@bp.get("/wte/power-purchase-agreements")
def list_ppas():
    require_role(READERS)
    items = sorted(store.ppas.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("kind")
    if q is not None:
        items = [p for p in items if p["kind"] == q]
    q = request.args.get("status")
    if q is not None:
        items = [p for p in items if p["status"] == q]
    return success_list([ppa_out(p) for p in items])


@bp.get("/wte/power-purchase-agreements/<pid>")
def get_ppa(pid):
    require_role(READERS)
    p = store.ppas.get(pid)
    if p is None:
        raise err_not_found("ppa not found")
    return success_obj(ppa_out(p))


@bp.post("/wte/power-purchase-agreements/<pid>/activate")
def activate_ppa(pid):
    require_role(ET)
    p = store.ppas.get(pid)
    if p is None:
        raise err_not_found("ppa not found")
    if p["status"] != "DRAFT":
        raise err_invalid_state("ppa is not DRAFT")
    if not p["term_end"] > store.logical_now:
        raise err_invalid_state("ppa term_end is not in the future")
    if p["kind"] == "PPA" and p["capacity_payment_cents_per_mw_month"] <= 0:
        raise err_invalid_state("PPA requires capacity_payment_cents_per_mw_month > 0")
    if p["kind"] == "MERCHANT" and p["capacity_payment_cents_per_mw_month"] != 0:
        raise err_invalid_state("MERCHANT requires capacity_payment_cents_per_mw_month == 0")
    p["status"] = "ACTIVE"
    touch(p)
    return success_obj(ppa_out(p))


@bp.post("/wte/power-purchase-agreements/<pid>/terminate")
def terminate_ppa(pid):
    require_role(ET)
    p = store.ppas.get(pid)
    if p is None:
        raise err_not_found("ppa not found")
    if p["status"] != "ACTIVE":
        raise err_invalid_state("ppa is not ACTIVE")
    p["status"] = "TERMINATED"
    touch(p)
    return success_obj(ppa_out(p))


@bp.post("/wte/energy-deliveries")
def create_energy_delivery():
    require_role(ET)
    b = body_json()
    require_fields(b, ["ppa_id", "period_start", "period_end", "delivered_mwh"])
    p = store.ppas.get(b["ppa_id"])
    if p is None:
        raise err_not_found("ppa not found")
    if p["status"] != "ACTIVE":
        raise err_invalid_state("ppa is not ACTIVE")
    ps = parse_dt(b["period_start"], "period_start")
    pe = parse_dt(b["period_end"], "period_end")
    if not pe > ps:
        raise err_invalid_request("period_end must be after period_start")
    if ps < p["term_start"] or pe > p["term_end"]:
        raise err_422("ERR_PERIOD_OUTSIDE_TERM", "period is outside the ppa term")
    merchant_price = b.get("merchant_price_cents_per_mwh")
    if p["kind"] == "MERCHANT":
        if merchant_price is None:
            raise err_422("ERR_MERCHANT_PRICE_REQUIRED",
                          "merchant_price_cents_per_mwh is required for MERCHANT deliveries")
        merchant_price = to_int(merchant_price, "merchant_price_cents_per_mwh")
    elif merchant_price is not None:
        # Ignored if present for PPA
        merchant_price = to_int(merchant_price, "merchant_price_cents_per_mwh")
    mwh = to_decimal(b["delivered_mwh"], "delivered_mwh")
    if mwh <= 0:
        raise err_invalid_request("delivered_mwh must be > 0")
    e = new_entity({
        "ppa_id": p["id"],
        "period_start": ps,
        "period_end": pe,
        "delivered_mwh": mwh,
        "merchant_price_cents_per_mwh": merchant_price if p["kind"] == "MERCHANT" else None,
        "billed_amount_cents": compute_energy_billing(p, mwh, merchant_price),
        "capacity_payment_cents": compute_capacity_payment(
            p, ps, pe, list(store.boilers.values())),
    })
    store.energy_deliveries[e["id"]] = e
    return success_obj(energy_delivery_out(e), 201)


@bp.get("/wte/energy-deliveries")
def list_energy_deliveries():
    require_role(READERS_ED)
    items = sorted(store.energy_deliveries.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("ppa_id")
    if q is not None:
        items = [e for e in items if e["ppa_id"] == q]
    return success_list([energy_delivery_out(e) for e in items])


@bp.get("/wte/energy-deliveries/<eid>")
def get_energy_delivery(eid):
    require_role(READERS_ED)
    e = store.energy_deliveries.get(eid)
    if e is None:
        raise err_not_found("energy delivery not found")
    return success_obj(energy_delivery_out(e))
