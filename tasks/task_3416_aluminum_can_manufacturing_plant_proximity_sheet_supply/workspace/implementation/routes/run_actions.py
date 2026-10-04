"""Production run transitions: start, complete, settle, cancel, void."""
from decimal import Decimal
from flask import Blueprint

from db import store, touch, clock_year
from errors import (ApiError, ERR_INVALID_STATE, ERR_AGREEMENT_NOT_ACTIVE,
                    ERR_LINE_QUALITY_HOLD, ERR_INDEX_NOT_PUBLISHED)
from middleware import actor, require_role
from response import ok_object
from routes.runs import get_run_or_404
from services import calc
from services.serialize import run_public
from validation import body_json, req_int

bp = Blueprint("run_actions", __name__)


def _D(v):
    return Decimal(str(v))


@bp.post("/production-runs/<rid>/start")
def start_run(rid):
    _, role = actor()
    require_role(role, ["LineScheduler"])
    run = get_run_or_404(rid)
    if run["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a SCHEDULED run can be started.")
    agr = store["agreements"][run["agreement_id"]]
    if agr["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE[0], ERR_AGREEMENT_NOT_ACTIVE[1],
                       "Run start requires the agreement to be ACTIVE.")
    line = store["lines"][run["line_id"]]
    if line["operational_status"] != "RUNNING":
        raise ApiError(ERR_LINE_QUALITY_HOLD[0], ERR_LINE_QUALITY_HOLD[1],
                       "Line is in QUALITY_HOLD; run start is blocked.")
    run["status"] = "IN_PROGRESS"
    touch(run)
    return ok_object(run_public(run))


@bp.post("/production-runs/<rid>/complete")
def complete_run(rid):
    _, role = actor()
    require_role(role, ["LineScheduler"])
    data = body_json()
    produced_qty = req_int(data, "produced_qty", minimum=0)
    spoiled_qty = req_int(data, "spoiled_qty", minimum=0)
    run = get_run_or_404(rid)
    if run["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only an IN_PROGRESS run can be completed.")
    # Provisional pricing reads the index one month before the delivery month.
    period = calc.delivery_period(run["window_end"])
    idx = calc.find_index(calc.prior_month_period(period))
    if idx is None:
        raise ApiError(ERR_INDEX_NOT_PUBLISHED[0], ERR_INDEX_NOT_PUBLISHED[1],
                       "No published metal price index for the provisional month.")
    agr = store["agreements"][run["agreement_id"]]
    fmt = store["formats"][run["format_id"]]
    line = store["lines"][run["line_id"]]
    sheet_lbs = float(_D(produced_qty + spoiled_qty) / _D(1000) * _D(fmt["metal_lbs_per_1000_units"]))
    effective = calc.effective_spoilage_pct(produced_qty, spoiled_qty)
    prev = calc.previous_run(run["line_id"], run["_window_start_dt"], exclude_id=run["id"])
    changeover = prev is not None and prev["graphics_code"] != run["graphics_code"]
    expected = calc.expected_spoilage_pct(line, fmt, changeover)
    price = calc.can_unit_price(agr, fmt, idx["index_cents_per_lb"],
                                ytd_basis=agr["ytd_settled_units"])
    run["produced_qty"] = produced_qty
    run["spoiled_qty"] = spoiled_qty
    run["sheet_lbs_consumed"] = sheet_lbs
    run["effective_spoilage_pct"] = float(effective)
    run["spoilage_flag"] = bool(effective > expected)
    run["provisional_unit_price_cents_per_1000"] = float(price)
    run["status"] = "COMPLETED"
    run["_completion_year"] = clock_year()
    touch(run)
    plant = store["plants"][line["plant_id"]]
    plant["warehouse_on_hand_units"] += produced_qty
    plant["_metal_events"].append({"year": clock_year(), "lbs": sheet_lbs})
    touch(plant)
    return ok_object(run_public(run))


@bp.post("/production-runs/<rid>/settle")
def settle_run(rid):
    _, role = actor()
    require_role(role, ["PlantManager"])
    run = get_run_or_404(rid)
    if run["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a COMPLETED run can be settled.")
    # Final pricing reads the delivery-month index itself.
    period = calc.delivery_period(run["window_end"])
    idx = calc.find_index(period)
    if idx is None:
        raise ApiError(ERR_INDEX_NOT_PUBLISHED[0], ERR_INDEX_NOT_PUBLISHED[1],
                       "No published metal price index for the delivery month.")
    agr = store["agreements"][run["agreement_id"]]
    fmt = store["formats"][run["format_id"]]
    ytd_before = agr["ytd_settled_units"]
    tier_before = "REBATE" if ytd_before >= agr["committed_annual_units"] else "STANDARD"
    final_price = calc.can_unit_price(agr, fmt, idx["index_cents_per_lb"], ytd_basis=ytd_before)
    settled_amount = calc.run_invoice_amount(final_price, run["produced_qty"])
    run["final_unit_price_cents_per_1000"] = float(final_price)
    run["settled_amount_cents"] = float(settled_amount)
    run["status"] = "SETTLED"
    touch(run)
    # Cascade: run -> agreement ledger
    agr["ytd_settled_units"] = ytd_before + run["produced_qty"]
    agr["delivered_revenue_cents"] = float(_D(agr["delivered_revenue_cents"]) + settled_amount)
    # Cascade: run -> format amortization
    fmt["delivered_units"] += run["produced_qty"]
    touch(fmt)
    # Cascade: agreement tier -> sibling SETTLED runs (true-up on flip)
    tier_after = "REBATE" if agr["ytd_settled_units"] >= agr["committed_annual_units"] else "STANDARD"
    if tier_before == "STANDARD" and tier_after == "REBATE":
        total_delta = Decimal("0")
        for s in store["runs"].values():
            if s["agreement_id"] != agr["id"] or s["status"] != "SETTLED" or s["id"] == run["id"]:
                continue
            s_fmt = store["formats"][s["format_id"]]
            delta = calc.tier_true_up_delta(agr, s, s_fmt)
            s["tier_delta_cents"] = float(delta)
            touch(s)
            total_delta += delta
        agr["delivered_revenue_cents"] = float(_D(agr["delivered_revenue_cents"]) + total_delta)
    touch(agr)
    return ok_object(run_public(run))


@bp.post("/production-runs/<rid>/cancel")
def cancel_run(rid):
    _, role = actor()
    require_role(role, ["LineScheduler"])
    run = get_run_or_404(rid)
    if run["status"] not in ("SCHEDULED", "HELD"):
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a SCHEDULED or HELD run can be cancelled.")
    was_held = run["status"] == "HELD"
    run["status"] = "CANCELLED"
    touch(run)
    if was_held:
        # Re-evaluate the line hold: QUALITY_HOLD stands while any ESCALATED
        # incident remains on a run of the line.
        line = store["lines"][run["line_id"]]
        still_held = any(
            i["line_id"] == line["id"] and i["status"] == "ESCALATED"
            for i in store["incidents"].values()
        )
        if not still_held and line["operational_status"] != "RUNNING":
            line["operational_status"] = "RUNNING"
            touch(line)
    return ok_object(run_public(run))


@bp.post("/production-runs/<rid>/void")
def void_run(rid):
    _, role = actor()
    require_role(role, ["LineScheduler"])
    run = get_run_or_404(rid)
    if run["status"] not in ("COMPLETED", "SETTLED"):
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a COMPLETED or SETTLED run can be voided.")
    was_settled = run["status"] == "SETTLED"
    run["status"] = "VOIDED"
    touch(run)
    line = store["lines"][run["line_id"]]
    plant = store["plants"][line["plant_id"]]
    plant["warehouse_on_hand_units"] -= run["produced_qty"]
    plant["_metal_events"].append({"year": run["_completion_year"], "lbs": -run["sheet_lbs_consumed"]})
    touch(plant)
    if was_settled:
        agr = store["agreements"][run["agreement_id"]]
        fmt = store["formats"][run["format_id"]]
        ytd_before = agr["ytd_settled_units"]
        tier_before = "REBATE" if ytd_before >= agr["committed_annual_units"] else "STANDARD"
        # Compensating reversal of the agreement ledger
        agr["ytd_settled_units"] = ytd_before - run["produced_qty"]
        agr["delivered_revenue_cents"] = float(
            _D(agr["delivered_revenue_cents"])
            - (_D(run["settled_amount_cents"]) + _D(run["tier_delta_cents"]))
        )
        fmt["delivered_units"] -= run["produced_qty"]
        touch(fmt)
        # Tier re-evaluation: on REBATE -> STANDARD flip, remaining SETTLED
        # runs lose their true-up credits.
        tier_after = "REBATE" if agr["ytd_settled_units"] >= agr["committed_annual_units"] else "STANDARD"
        if tier_before == "REBATE" and tier_after == "STANDARD":
            total_delta = Decimal("0")
            remaining = [
                s for s in store["runs"].values()
                if s["agreement_id"] == agr["id"] and s["status"] == "SETTLED"
            ]
            for s in remaining:
                total_delta += _D(s["tier_delta_cents"])
            agr["delivered_revenue_cents"] = float(_D(agr["delivered_revenue_cents"]) - total_delta)
            for s in remaining:
                s["tier_delta_cents"] = 0
                touch(s)
        touch(agr)
    return ok_object(run_public(run))
