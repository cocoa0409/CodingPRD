"""Logical clock and put-or-pay settlement runs."""

from decimal import Decimal

from flask import Blueprint

from auth import require_role
from db import store
from errors import err_invalid_state, err_not_found
from helpers import (body_json, iso_now_logical, new_entity, num_out, parse_dt,
                     require_fields, round3, round_cents, success_obj, touch)
from calculations import month_period, annual_period, MONTHS_PER_YEAR
from serializers import _fmt_dt

bp = Blueprint("clock_settlements", __name__)


def _advance_system_transitions():
    """Fire clock-driven system transitions: agreement and PPA expiry."""
    now = store.logical_now
    for a in store.agreements.values():
        if a["state"] == "ACTIVE" and now >= a["term_end"]:
            a["state"] = "EXPIRED"
            touch(a)
    for p in store.ppas.values():
        if p["status"] == "ACTIVE" and now >= p["term_end"]:
            p["status"] = "EXPIRED"
            touch(p)


@bp.post("/wte/_clock/set_current_utc")
def set_clock():
    require_role(["Regulator"])
    b = body_json()
    require_fields(b, ["to_iso8601"])
    store.logical_now = parse_dt(b["to_iso8601"], "to_iso8601")
    _advance_system_transitions()
    return success_obj({"current_utc": iso_now_logical(store)})


@bp.post("/wte/settlements/put-or-pay/run")
def run_put_or_pay():
    require_role(["ContractsManager"])
    b = body_json()
    require_fields(b, ["agreement_id"])
    a = store.agreements.get(b["agreement_id"])
    if a is None:
        raise err_not_found("agreement not found")
    if a["state"] not in ("ACTIVE", "EXPIRED"):
        raise err_invalid_state("agreement must be ACTIVE or EXPIRED")
    cadence = a["put_or_pay_settlement_cadence"]
    now = store.logical_now
    if cadence == "MONTHLY":
        period_start, period_end = month_period(now)
        guarantee = a["guaranteed_annual_tonnage"] / Decimal(MONTHS_PER_YEAR)
    else:
        period_start, period_end = annual_period(a, now)
        guarantee = a["guaranteed_annual_tonnage"]
    delivered = sum(
        (d["tonnes"] for d in store.deliveries.values()
         if d["agreement_id"] == a["id"] and d["status"] == "ACCEPTED"
         and period_start <= d["delivered_at"] < period_end), Decimal("0"))
    delivered = round3(delivered)
    period_key = (_fmt_dt(period_start), _fmt_dt(period_end))
    # Already billed: latest record per period, over periods strictly before this one
    already_billed_cents = 0
    if cadence == "MONTHLY":
        latest_per_period = {}
        for rec in store.put_or_pay_settlements.values():
            if rec["agreement_id"] != a["id"]:
                continue
            key = (rec["period_start"], rec["period_end"])
            if key < period_key:
                latest_per_period[key] = rec  # later inserts overwrite (latest run wins)
        already_billed_cents = sum(r["shortfall_cents"] for r in latest_per_period.values())
    rate = a["tipping_fee_per_tonne_cents"]
    if cadence == "MONTHLY" and rate > 0:
        billed_tonnes_equiv = Decimal(already_billed_cents) / Decimal(rate)
    else:
        billed_tonnes_equiv = Decimal("0")
    shortfall_tonnes = guarantee - delivered - billed_tonnes_equiv
    if shortfall_tonnes < 0:
        shortfall_tonnes = Decimal("0")
    shortfall_tonnes = round3(shortfall_tonnes)
    shortfall_cents = round_cents(shortfall_tonnes * Decimal(rate))
    # Record the settlement; supersede any earlier record for the same period
    for rid, rec in list(store.put_or_pay_settlements.items()):
        if rec["agreement_id"] == a["id"] and (rec["period_start"], rec["period_end"]) == period_key:
            del store.put_or_pay_settlements[rid]
    rec = new_entity({
        "agreement_id": a["id"],
        "period_start": period_key[0],
        "period_end": period_key[1],
        "shortfall_cents": shortfall_cents,
    })
    store.put_or_pay_settlements[rec["id"]] = rec
    return success_obj({
        "agreement_id": a["id"],
        "period_start": period_key[0],
        "period_end": period_key[1],
        "cadence": cadence,
        "guarantee_tonnes": num_out(round3(guarantee)),
        "delivered_base_tonnes": num_out(delivered),
        "shortfall_tonnes": num_out(shortfall_tonnes),
        "shortfall_cents": shortfall_cents,
        "already_billed_cents": already_billed_cents,
    })
