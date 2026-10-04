"""Cross-entity domain logic: derived fields, cascades, settlement, capacity,
shortage allocation, and serializers.

Version/updated_at policy (PRD section 2.4): every mutation of a resource —
including system cascades, derived-field reconciliation, and automatic sweep
transitions — refreshes updated_at and increments version by exactly one. A
single logical change to an entity is one increment, even if several of its
fields change together.
"""

from datetime import timedelta
from decimal import Decimal

import calcs
from constants import (
    FILL_RATE_FLOOR_PCT,
    FULFILL_THRESHOLD,
    PLANT_WEEK_CAPACITY_CASES,
    TIER_ORDER,
)
from db import clock_now, next_seq, store
from errors import ApiError
from util import fmt_ts, json_number, new_id, round_half_up


# ------------------------------------------------------------------ helpers

def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = clock_now()


def new_entity():
    now = clock_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def new_batch(source_lot_id, source_run_id, stream, routing, weight_cwt):
    """ByproductBatch: immutable, system-created; only id and created_at (PRD 2.4)."""
    b = {
        "id": new_id(),
        "created_at": clock_now(),
        "_seq": next_seq(),
        "source_lot_id": source_lot_id,
        "source_run_id": source_run_id,
        "stream": stream,
        "routing": routing,
        "weight_cwt": weight_cwt,
        "unit_revenue_cents_per_cwt": calcs.byproduct_unit_revenue(routing),
        "total_revenue_cents": calcs.byproduct_total_revenue(weight_cwt, routing),
    }
    store.batches[b["id"]] = b
    return b


def _get(table, rid, error_id, name):
    ent = table.get(rid) if isinstance(rid, str) else None
    if ent is None:
        raise ApiError(error_id, f"{name} not found", 404)
    return ent


def get_grower_or_404(rid):
    return _get(store.growers, rid, "ERR_GROWER_NOT_FOUND", "Grower")


def get_contract_or_404(rid):
    return _get(store.contracts, rid, "ERR_CONTRACT_NOT_FOUND", "Crop contract")


def get_lot_or_404(rid):
    return _get(store.lots, rid, "ERR_LOT_NOT_FOUND", "Potato lot")


def get_facility_or_404(rid):
    return _get(store.facilities, rid, "ERR_FACILITY_NOT_FOUND", "Storage facility")


def get_line_or_404(rid):
    return _get(store.lines, rid, "ERR_LINE_NOT_FOUND", "Processing line")


def get_spec_or_404(rid):
    return _get(store.specs, rid, "ERR_SPEC_NOT_FOUND", "Cut specification")


def get_chain_or_404(rid):
    return _get(store.chains, rid, "ERR_CHAIN_NOT_FOUND", "Customer chain")


def get_agreement_or_404(rid):
    return _get(store.agreements, rid, "ERR_AGREEMENT_NOT_FOUND", "Supply agreement")


def get_run_or_404(rid):
    return _get(store.runs, rid, "ERR_RUN_NOT_FOUND", "Production run")


def get_shipment_or_404(rid):
    return _get(store.shipments, rid, "ERR_SHIPMENT_NOT_FOUND", "Shipment")


def get_shortage_event_or_404(rid):
    return _get(store.shortage_events, rid, "ERR_SHORTAGE_EVENT_NOT_FOUND", "Shortage event")


def get_batch_or_404(rid):
    return _get(store.batches, rid, "ERR_BATCH_NOT_FOUND", "Byproduct batch")


# ------------------------------------------------------------ derived fields

def current_stock_cwt(facility):
    """Sum of net_weight_cwt over the facility's IN_STORAGE lots."""
    total = Decimal(0)
    for lot in store.lots.values():
        if lot["facility_id"] == facility["id"] and lot["status"] == "IN_STORAGE":
            total += lot["net_weight_cwt"]
    return total


def delivered_volume_cwt(contract):
    """Sum of net_weight_cwt over the contract's CONTRACTED lots, any status."""
    total = Decimal(0)
    for lot in store.lots.values():
        if lot.get("contract_id") == contract["id"] and lot["origin"] == "CONTRACTED":
            total += lot["net_weight_cwt"]
    return total


def lifetime_released_cases(agreement):
    return sum(
        r["actual_cases"] or 0
        for r in store.runs.values()
        if r["agreement_id"] == agreement["id"] and r["status"] == "RELEASED"
    )


def lifetime_shipped_cases(agreement):
    return sum(
        s["cases_shipped"]
        for s in store.shipments.values()
        if s["agreement_id"] == agreement["id"] and s["status"] in ("IN_TRANSIT", "DELIVERED")
    )


def released_unshipped_cases(agreement):
    return lifetime_released_cases(agreement) - lifetime_shipped_cases(agreement)


def compute_fill_rate_pct(chain_id):
    """Terminal shipments only (DELIVERED / REJECTED_ON_ARRIVAL); None while the
    denominator is zero."""
    ag_ids = {a["id"] for a in store.agreements.values() if a["customer_id"] == chain_id}
    delivered = 0
    rejected = 0
    for s in store.shipments.values():
        if s["agreement_id"] not in ag_ids:
            continue
        if s["status"] == "DELIVERED":
            delivered += s["cases_shipped"]
        elif s["status"] == "REJECTED_ON_ARRIVAL":
            rejected += s["cases_shipped"]
    return calcs.fill_rate_pct(delivered, rejected)


def pool_remaining():
    reserved = sum(
        a["weekly_contracted_cases"]
        for a in store.agreements.values()
        if a["status"] == "ACTIVE"
    )
    return PLANT_WEEK_CAPACITY_CASES - reserved


# --------------------------------------------------------- contract lifecycle

def settle_contract(contract):
    """contract_final_settlement: pinned evaluation order (PRD 3.1). Writes
    final_payment_cents on every CONTRACTED lot (0 for DISPOSED) and
    settlement_amount_cents on the contract (plain sum of rounded lots)."""
    base = contract["base_price_per_cwt_cents"]
    lots = [
        lot
        for lot in store.lots.values()
        if lot.get("contract_id") == contract["id"] and lot["origin"] == "CONTRACTED"
    ]
    lots.sort(key=lambda l: (l["created_at"], l["_seq"]))
    total = 0
    now = clock_now()
    for lot in lots:
        if lot["status"] == "DISPOSED":
            lot["final_payment_cents"] = 0
        else:
            elapsed = (now - lot["created_at"]).total_seconds()
            days = max(0, int(elapsed // 86400))
            facility = store.facilities[lot["facility_id"]]
            loss = calcs.storage_loss_pct(days, facility["posture"])
            shrinkage = calcs.shrinkage_cwt(lot["net_weight_cwt"], loss)
            final_net = lot["net_weight_cwt"] - shrinkage
            final_grade = lot["grade"]
            if calcs.loss_exceeds_downgrade_threshold(loss):
                final_grade = calcs.downgrade_tier(final_grade)
            lot["final_payment_cents"] = calcs.final_payment(final_net, base, final_grade)
        touch(lot)
        total += lot["final_payment_cents"]
    contract["settlement_amount_cents"] = total


def maybe_auto_fulfill(contract):
    """Automatic ACTIVE -> FULFILLED when delivered volume reaches >= 98% of
    contracted_volume_cwt (threshold rounded half-up to 1dp)."""
    if contract["status"] != "ACTIVE":
        return
    threshold = round_half_up(Decimal(FULFILL_THRESHOLD) * contract["contracted_volume_cwt"], 1)
    if delivered_volume_cwt(contract) >= threshold:
        contract["status"] = "FULFILLED"
        settle_contract(contract)
        touch(contract)


# ------------------------------------------------------------- credit cascade

def cascade_credit_hold(chain):
    """Chain GOOD_STANDING -> ON_HOLD: agreements ACTIVE -> SUSPENDED, their
    SCHEDULED runs -> CANCELLED, those runs' ALLOCATED lots -> IN_STORAGE."""
    chain["credit_status"] = "ON_HOLD"
    touch(chain)
    for ag in store.agreements.values():
        if ag["customer_id"] != chain["id"] or ag["status"] != "ACTIVE":
            continue
        ag["status"] = "SUSPENDED"
        touch(ag)
        for run in store.runs.values():
            if run["agreement_id"] != ag["id"] or run["status"] != "SCHEDULED":
                continue
            run["status"] = "CANCELLED"
            touch(run)
            for lot_id in run["input_lot_ids"]:
                lot = store.lots[lot_id]
                if lot["status"] == "ALLOCATED":
                    lot["status"] = "IN_STORAGE"
                    touch(lot)
                    touch(store.facilities[lot["facility_id"]])


def cascade_credit_resume(chain):
    """Chain ON_HOLD -> GOOD_STANDING: every SUSPENDED agreement -> ACTIVE,
    re-reserving weekly cases. Atomic: caller must have pre-checked capacity;
    cancelled runs and deallocated lots are not resurrected."""
    chain["credit_status"] = "GOOD_STANDING"
    touch(chain)
    for ag in store.agreements.values():
        if ag["customer_id"] == chain["id"] and ag["status"] == "SUSPENDED":
            ag["status"] = "ACTIVE"
            touch(ag)


# --------------------------------------------------------------- clock sweep

def clock_sweep(now):
    """Every ACTIVE agreement whose term_end is at or before the new clock
    transitions to COMPLETED, releasing its reserved weekly cases."""
    for ag in store.agreements.values():
        if ag["status"] == "ACTIVE" and ag["term_end"] <= now:
            ag["status"] = "COMPLETED"
            touch(ag)


# --------------------------------------------------------- spec revision flag

def spec_revision_cascade(spec, pre_revision_version):
    """LOCKED spec -> REVISION_REQUESTED flags every ACTIVE agreement pinned to
    the spec's pre-revision version as spec_stale."""
    for ag in store.agreements.values():
        if (
            ag["spec_id"] == spec["id"]
            and ag["status"] == "ACTIVE"
            and ag["pinned_spec_version"] == pre_revision_version
        ):
            if not ag["spec_stale"]:
                ag["spec_stale"] = True
                touch(ag)


# ------------------------------------------------------------- fill-rate loop

def apply_fill_rate_update(chain, old_fill):
    """After a shipment reaches a terminal state: recompute the chain's
    fill_rate_pct (touching the chain if it changed); >= floor clears
    under_sla_review across the chain's agreements, < floor sets it on every
    ACTIVE agreement of the chain."""
    new_fill = compute_fill_rate_pct(chain["id"])
    if new_fill != old_fill:
        touch(chain)
    if new_fill is None:
        return
    if new_fill >= Decimal(FILL_RATE_FLOOR_PCT):
        for ag in store.agreements.values():
            if ag["customer_id"] == chain["id"] and ag["under_sla_review"]:
                ag["under_sla_review"] = False
                touch(ag)
    else:
        for ag in store.agreements.values():
            if (
                ag["customer_id"] == chain["id"]
                and ag["status"] == "ACTIVE"
                and not ag["under_sla_review"]
            ):
                ag["under_sla_review"] = True
                touch(ag)


# -------------------------------------------------------- shortage allocation

def execute_allocation(event):
    """shortage_allocation over all ACTIVE agreements; writes each participant's
    current_week_allocation_cases and the event's allocation_results in
    computation order, then EXECUTED."""
    participants = [a for a in store.agreements.values() if a["status"] == "ACTIVE"]
    pool = event["available_week_cases"]
    results = []
    if event["response_mode"] == "PRO_RATA":
        participants.sort(key=lambda a: (a["created_at"], a["_seq"]))
        total_weekly = sum(a["weekly_contracted_cases"] for a in participants)
        for ag in participants:
            share = (pool * ag["weekly_contracted_cases"]) // total_weekly
            alloc = min(ag["weekly_contracted_cases"], share)
            results.append({"agreement_id": ag["id"], "allocated_cases": alloc})
    else:  # PRIORITY_WATERFALL
        def waterfall_key(ag):
            chain = store.chains[ag["customer_id"]]
            return (TIER_ORDER[chain["priority_tier"]], ag["created_at"], ag["_seq"])

        participants.sort(key=waterfall_key)
        remaining = pool
        for ag in participants:
            if remaining == 0:
                break
            alloc = min(ag["weekly_contracted_cases"], remaining)
            remaining -= alloc
            results.append({"agreement_id": ag["id"], "allocated_cases": alloc})
    for entry in results:
        ag = store.agreements[entry["agreement_id"]]
        if ag["current_week_allocation_cases"] != entry["allocated_cases"]:
            ag["current_week_allocation_cases"] = entry["allocated_cases"]
            touch(ag)
    event["allocation_results"] = results
    event["status"] = "EXECUTED"
    touch(event)


# --------------------------------------------------------------- serializers

def grower_view(g):
    return {
        "id": g["id"],
        "grower_code": g["grower_code"],
        "legal_name": g["legal_name"],
        "region": g["region"],
        "created_at": fmt_ts(g["created_at"]),
        "updated_at": fmt_ts(g["updated_at"]),
        "version": g["version"],
    }


def _pending_amendment_view(pa):
    if pa is None:
        return None
    return {
        "contracted_acres": json_number(pa["contracted_acres"]),
        "expected_yield_cwt_per_acre": json_number(pa["expected_yield_cwt_per_acre"]),
        "base_price_per_cwt_cents": pa["base_price_per_cwt_cents"],
        "delivery_window_start": fmt_ts(pa["delivery_window_start"]),
        "delivery_window_end": fmt_ts(pa["delivery_window_end"]),
    }


def contract_view(c):
    return {
        "id": c["id"],
        "grower_id": c["grower_id"],
        "variety": c["variety"],
        "contracted_acres": json_number(c["contracted_acres"]),
        "expected_yield_cwt_per_acre": json_number(c["expected_yield_cwt_per_acre"]),
        "contracted_volume_cwt": json_number(c["contracted_volume_cwt"]),
        "base_price_per_cwt_cents": c["base_price_per_cwt_cents"],
        "delivery_window_start": fmt_ts(c["delivery_window_start"]),
        "delivery_window_end": fmt_ts(c["delivery_window_end"]),
        "pending_amendment": _pending_amendment_view(c["pending_amendment"]),
        "delivered_volume_cwt": json_number(delivered_volume_cwt(c)),
        "settlement_amount_cents": c["settlement_amount_cents"],
        "status": c["status"],
        "created_at": fmt_ts(c["created_at"]),
        "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


def lot_view(lot):
    return {
        "id": lot["id"],
        "contract_id": lot["contract_id"],
        "shortage_event_id": lot["shortage_event_id"],
        "facility_id": lot["facility_id"],
        "origin": lot["origin"],
        "variety": lot["variety"],
        "gross_weight_cwt": lot["gross_weight_cwt"],
        "tare_weight_cwt": lot["tare_weight_cwt"],
        "net_weight_cwt": json_number(lot["net_weight_cwt"]),
        "defect_pct": lot["defect_pct"],
        "specific_gravity": lot["specific_gravity"],
        "sugar_end_rating": lot["sugar_end_rating"],
        "grade": lot["grade"],
        "provisional_payment_cents": lot["provisional_payment_cents"],
        "final_payment_cents": lot["final_payment_cents"],
        "status": lot["status"],
        "disposition": lot["disposition"],
        "created_at": fmt_ts(lot["created_at"]),
        "updated_at": fmt_ts(lot["updated_at"]),
        "version": lot["version"],
    }


def _reading_view(r):
    return {
        "recorded_at": fmt_ts(r["recorded_at"]),
        "temperature_f": r["temperature_f"],
        "humidity_pct": r["humidity_pct"],
        "co2_pct": r["co2_pct"],
        "sprout_index": r["sprout_index"],
        "disease_incidence_pct": r["disease_incidence_pct"],
    }


def facility_view(f):
    return {
        "id": f["id"],
        "facility_code": f["facility_code"],
        "capacity_cwt": f["capacity_cwt"],
        "target_temp_f": f["target_temp_f"],
        "target_co2_pct": f["target_co2_pct"],
        "current_stock_cwt": json_number(current_stock_cwt(f)),
        "posture": f["posture"],
        "recent_readings": [_reading_view(r) for r in f["recent_readings"]],
        "created_at": fmt_ts(f["created_at"]),
        "updated_at": fmt_ts(f["updated_at"]),
        "version": f["version"],
    }


def line_view(line):
    return {
        "id": line["id"],
        "line_code": line["line_code"],
        "supported_cut_families": list(line["supported_cut_families"]),
        "rated_throughput_cases_per_hour": line["rated_throughput_cases_per_hour"],
        "created_at": fmt_ts(line["created_at"]),
        "updated_at": fmt_ts(line["updated_at"]),
        "version": line["version"],
    }


def spec_view(s):
    return {
        "id": s["id"],
        "customer_id": s["customer_id"],
        "spec_code": s["spec_code"],
        "cut_family": s["cut_family"],
        "cut_size_mm": json_number(s["cut_size_mm"]),
        "coating_type": s["coating_type"],
        "target_color_units": json_number(s["target_color_units"]),
        "max_cook_time_sec": s["max_cook_time_sec"],
        "sensory_panel_required": s["sensory_panel_required"],
        "panel_score": json_number(s["panel_score"]) if s["panel_score"] is not None else None,
        "ever_locked": s["ever_locked"],
        "status": s["status"],
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def chain_view(c):
    fill = compute_fill_rate_pct(c["id"])
    return {
        "id": c["id"],
        "chain_code": c["chain_code"],
        "legal_name": c["legal_name"],
        "priority_tier": c["priority_tier"],
        "credit_status": c["credit_status"],
        "fill_rate_pct": json_number(fill) if fill is not None else None,
        "created_at": fmt_ts(c["created_at"]),
        "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


def agreement_view(a):
    released = lifetime_released_cases(a)
    shipped = lifetime_shipped_cases(a)
    return {
        "id": a["id"],
        "customer_id": a["customer_id"],
        "spec_id": a["spec_id"],
        "weekly_contracted_cases": a["weekly_contracted_cases"],
        "price_per_case_cents": a["price_per_case_cents"],
        "term_start": fmt_ts(a["term_start"]),
        "term_end": fmt_ts(a["term_end"]),
        "pinned_spec_version": a["pinned_spec_version"],
        "spec_stale": a["spec_stale"],
        "under_sla_review": a["under_sla_review"],
        "current_week_allocation_cases": a["current_week_allocation_cases"],
        "lifetime_released_cases": released,
        "lifetime_shipped_cases": shipped,
        "released_unshipped_cases": released - shipped,
        "status": a["status"],
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def run_view(r):
    return {
        "id": r["id"],
        "line_id": r["line_id"],
        "spec_id": r["spec_id"],
        "agreement_id": r["agreement_id"],
        "input_lot_ids": list(r["input_lot_ids"]),
        "scheduled_start": fmt_ts(r["scheduled_start"]),
        "scheduled_end": fmt_ts(r["scheduled_end"]),
        "cut_family": r["cut_family"],
        "total_input_cwt": json_number(r["total_input_cwt"]),
        "actual_cases": r["actual_cases"],
        "rework_count": r["rework_count"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def batch_view(b):
    return {
        "id": b["id"],
        "source_lot_id": b["source_lot_id"],
        "source_run_id": b["source_run_id"],
        "stream": b["stream"],
        "routing": b["routing"],
        "weight_cwt": json_number(b["weight_cwt"]),
        "unit_revenue_cents_per_cwt": b["unit_revenue_cents_per_cwt"],
        "total_revenue_cents": b["total_revenue_cents"],
        "created_at": fmt_ts(b["created_at"]),
    }


def shipment_view(s):
    return {
        "id": s["id"],
        "agreement_id": s["agreement_id"],
        "carrier_name": s["carrier_name"],
        "trailer_setpoint_f": s["trailer_setpoint_f"],
        "route_type": s["route_type"],
        "lines": [dict(line) for line in s["lines"]],
        "cases_shipped": s["cases_shipped"],
        "max_transit_temp_f": s["max_transit_temp_f"],
        "minutes_above_setpoint": s["minutes_above_setpoint"],
        "excursion_flag": s["excursion_flag"],
        "invoice_cents": s["invoice_cents"],
        "credit_memo_cents": s["credit_memo_cents"],
        "status": s["status"],
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def shortage_event_view(e):
    return {
        "id": e["id"],
        "scope_variety": e["scope_variety"],
        "declared_deficit_cwt": json_number(e["declared_deficit_cwt"]),
        "available_week_cases": e["available_week_cases"],
        "response_mode": e["response_mode"],
        "status": e["status"],
        "allocation_results": e["allocation_results"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }
