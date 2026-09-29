"""Derived (source: computed) figures and the resource serialisers.

Every roll-up in this file is state-filtered and evaluated immediately, so a
read always reflects every mutation that preceded it (PRD 2.10).  Version
bumps are NOT performed here — they are applied explicitly at the exact
places the specification enumerates them.
"""

from decimal import Decimal

import calc
import store
from common import D, ZERO, dec_out, fmt_dt, fmt_ms, r2, r3

# --------------------------------------------------------------------------
# Vineyard
# --------------------------------------------------------------------------

LIVE_BLOCK_STATES = ("ESTABLISHING", "BEARING")


def vineyard_blocks(vineyard_id):
    return [b for b in store.blocks.values() if b["vineyard_id"] == vineyard_id]


def vineyard_aggregates(vineyard):
    live = [b for b in vineyard_blocks(vineyard["id"])
            if b["farming_status"] in LIVE_BLOCK_STATES]
    acres = ZERO
    for block in live:
        acres += block["acres"]
    return len(live), r2(acres)


def serialize_vineyard(vineyard):
    block_count, managed_acres = vineyard_aggregates(vineyard)
    out = store.base_fields(vineyard)
    out.update({
        "name": vineyard["name"],
        "owner_legal_name": vineyard["owner_legal_name"],
        "ava_region": vineyard["ava_region"],
        "client_contact_email": vineyard["client_contact_email"],
        "block_count": block_count,
        "managed_acres": dec_out(managed_acres),
    })
    return out


# --------------------------------------------------------------------------
# Block — compliance clearances, water total and harvest ledger
# --------------------------------------------------------------------------


def block_sprays(block_id):
    return [s for s in store.spray_records.values() if s["block_id"] == block_id]


def block_clearances(block):
    """Maximum over APPLIED and VERIFIED spray records; null when empty."""
    rei = None
    phi = None
    for spray in block_sprays(block["id"]):
        if spray["spray_status"] not in ("APPLIED", "VERIFIED"):
            continue
        if spray["rei_clear_at"] is not None and (rei is None or spray["rei_clear_at"] > rei):
            rei = spray["rei_clear_at"]
        if spray["phi_clear_at"] is not None and (phi is None or spray["phi_clear_at"] > phi):
            phi = spray["phi_clear_at"]
    return rei, phi


def compliance_posture(block):
    rei, phi = block_clearances(block)
    now = store.now_utc()
    if rei is not None and now < rei:
        return "REENTRY_RESTRICTED"
    if phi is not None and now < phi:
        return "PHI_RESTRICTED"
    return "CLEAR"


def season_applied_inches(block_id):
    total = ZERO
    for event in store.irrigation_events.values():
        if event["block_id"] == block_id and event["irrigation_status"] == "APPLIED":
            total += event["applied_inches"]
    return r3(total)


def block_estimates(block_id):
    return [e for e in store.yield_estimates.values() if e["block_id"] == block_id]


def governing_estimate(block_id):
    """Latest sample_date, tie-broken by latest created_at (never id)."""
    candidates = block_estimates(block_id)
    if not candidates:
        return None
    return max(candidates, key=lambda e: (e["sample_date"], e["created_at"], e["_seq"]))


def block_loads(block_id):
    return [l for l in store.harvest_loads.values() if l["block_id"] == block_id]


def block_harvest_ledger(block):
    governing = governing_estimate(block["id"])
    governing_tons = governing["estimated_tons"] if governing else Decimal("0.00")
    committed = ZERO
    received = ZERO
    for load in block_loads(block["id"]):
        if load["load_status"] in ("PLANNED", "IN_TRANSIT"):
            committed += load["estimated_tons"]
        elif load["load_status"] == "RECEIVED":
            received += load["net_tons"]
    committed = r2(committed)
    received = r2(received)
    remaining = r2(governing_tons - committed - received)
    if governing is None:
        posture = "NOT_ESTIMATED"
    elif remaining <= ZERO:
        posture = "COMPLETE"
    else:
        posture = "OPEN"
    return {
        "governing_estimate_tons": r2(governing_tons),
        "committed_harvest_tons": committed,
        "received_tons": received,
        "remaining_estimated_tons": remaining,
        "harvest_posture": posture,
    }


def serialize_block(block):
    rei, phi = block_clearances(block)
    ledger = block_harvest_ledger(block)
    out = store.base_fields(block)
    out.update({
        "vineyard_id": block["vineyard_id"],
        "contract_id": block["contract_id"],
        "replaces_block_id": block["replaces_block_id"],
        "block_code": block["block_code"],
        "variety": block["variety"],
        "clone": block["clone"],
        "rootstock": block["rootstock"],
        "trellis_system": block["trellis_system"],
        "planting_year": block["planting_year"],
        "vine_spacing_ft": dec_out(block["vine_spacing_ft"]),
        "row_spacing_ft": dec_out(block["row_spacing_ft"]),
        "acres": dec_out(block["acres"]),
        "contracted_acres": dec_out(block["contracted_acres"]),
        "per_acre_fee_override": dec_out(block["per_acre_fee_override"]),
        "vines_per_acre": block["vines_per_acre"],
        "vine_count": block["vine_count"],
        "farming_status": block["farming_status"],
        "rei_clear_at": fmt_dt(rei),
        "phi_clear_at": fmt_dt(phi),
        "compliance_posture": compliance_posture(block),
        "season_applied_inches": dec_out(season_applied_inches(block["id"])),
        "governing_estimate_tons": dec_out(ledger["governing_estimate_tons"]),
        "committed_harvest_tons": dec_out(ledger["committed_harvest_tons"]),
        "received_tons": dec_out(ledger["received_tons"]),
        "remaining_estimated_tons": dec_out(ledger["remaining_estimated_tons"]),
        "harvest_posture": ledger["harvest_posture"],
    })
    return out


# --------------------------------------------------------------------------
# CustomFarmingContract
# --------------------------------------------------------------------------


def contract_blocks(contract_id):
    return [b for b in store.blocks.values() if b["contract_id"] == contract_id]


def management_fee_base(contract):
    """Enrolled blocks stay in the sum even once REMOVED."""
    total = ZERO
    for block in contract_blocks(contract["id"]):
        rate = block["per_acre_fee_override"]
        if rate is None:
            rate = contract["per_acre_annual_fee"]
        acres = block["contracted_acres"]
        if acres is None:
            acres = ZERO
        total += rate * acres
    return r2(total)


def contract_aggregates(contract):
    enrolled = contract_blocks(contract["id"])
    acres = ZERO
    for block in enrolled:
        if block["contracted_acres"] is not None:
            acres += block["contracted_acres"]
    incentive = ZERO
    enrolled_ids = set(b["id"] for b in enrolled)
    for load in store.harvest_loads.values():
        if load["block_id"] in enrolled_ids and load["load_status"] == "RECEIVED":
            if load["quality_incentive_amount"] is not None:
                incentive += load["quality_incentive_amount"]
    incentive = r2(incentive)
    fee_base = management_fee_base(contract)
    return {
        "enrolled_block_count": len(enrolled),
        "total_contracted_acres": r2(acres),
        "accrued_quality_incentive": incentive,
        "projected_total_billable": r2(fee_base + incentive),
        "management_fee_base": fee_base,
    }


def serialize_contract(contract):
    agg = contract_aggregates(contract)
    out = store.base_fields(contract)
    out.update({
        "vineyard_id": contract["vineyard_id"],
        "per_acre_annual_fee": dec_out(contract["per_acre_annual_fee"]),
        "cost_pass_through_pct": dec_out(contract["cost_pass_through_pct"]),
        "quality_incentive_per_ton": dec_out(contract["quality_incentive_per_ton"]),
        "quality_brix_threshold": dec_out(contract["quality_brix_threshold"]),
        "period_overhead_pool": dec_out(contract["period_overhead_pool"]),
        "period_start": contract["period_start"],
        "period_end": contract["period_end"],
        "contract_status": contract["contract_status"],
        "client_signature_name": contract["client_signature_name"],
        "enrolled_block_count": agg["enrolled_block_count"],
        "total_contracted_acres": dec_out(agg["total_contracted_acres"]),
        "accrued_quality_incentive": dec_out(agg["accrued_quality_incentive"]),
        "projected_total_billable": dec_out(agg["projected_total_billable"]),
        "settled_period_count": contract["settled_period_count"],
        "last_settlement_total": dec_out(contract["last_settlement_total"]),
    })
    return out


# --------------------------------------------------------------------------
# FarmingPlan ledger
# --------------------------------------------------------------------------


def plan_committed_cost(plan_id):
    labor = ZERO
    for order in store.work_orders.values():
        if order["farming_plan_id"] != plan_id:
            continue
        status = order["execution_status"]
        if status in ("SCHEDULED", "IN_PROGRESS"):
            labor += order["estimated_labor_cost"]
        elif status == "COMPLETED":
            labor += order["actual_labor_cost"]
        elif status == "CANCELLED":
            if order["actual_labor_cost"] is not None:
                labor += order["actual_labor_cost"]
    materials = ZERO
    for spray in store.spray_records.values():
        if spray["farming_plan_id"] == plan_id and spray["spray_status"] in ("APPLIED", "VERIFIED"):
            materials += spray["material_cost"]
    water = ZERO
    for event in store.irrigation_events.values():
        if event["farming_plan_id"] == plan_id and event["irrigation_status"] == "APPLIED":
            water += event["water_cost"]
    return r2(labor + materials + water)


def plan_ledger(plan):
    committed = plan_committed_cost(plan["id"])
    total = plan["total_budget"]
    return {
        "committed_cost": committed,
        "remaining_budget": r2(total - committed),
        "budget_posture": calc.budget_posture(total, committed),
    }


def serialize_plan(plan):
    ledger = plan_ledger(plan)
    out = store.base_fields(plan)
    out.update({
        "block_id": plan["block_id"],
        "plan_year": plan["plan_year"],
        "quality_target": plan["quality_target"],
        "pruning_budget_per_acre": dec_out(plan["pruning_budget_per_acre"]),
        "canopy_budget_per_acre": dec_out(plan["canopy_budget_per_acre"]),
        "irrigation_budget_per_acre": dec_out(plan["irrigation_budget_per_acre"]),
        "pest_budget_per_acre": dec_out(plan["pest_budget_per_acre"]),
        "seasonal_water_cap_inches": dec_out(plan["seasonal_water_cap_inches"]),
        "plan_status": plan["plan_status"],
        "revision_count": plan["revision_count"],
        "submitted_by_user_id": plan["submitted_by_user_id"],
        "approved_by_user_id": plan["approved_by_user_id"],
        "total_budget": dec_out(plan["total_budget"]),
        "committed_cost": dec_out(ledger["committed_cost"]),
        "remaining_budget": dec_out(ledger["remaining_budget"]),
        "budget_posture": ledger["budget_posture"],
    })
    return out


# --------------------------------------------------------------------------
# LaborCrew
# --------------------------------------------------------------------------


def scheduled_work_order_count(crew_id):
    return len([
        o for o in store.work_orders.values()
        if o["crew_id"] == crew_id and o["execution_status"] in ("SCHEDULED", "IN_PROGRESS")
    ])


def serialize_crew(crew):
    out = store.base_fields(crew)
    out.update({
        "crew_name": crew["crew_name"],
        "pay_structure": crew["pay_structure"],
        "crew_size": crew["crew_size"],
        "base_hourly_rate": dec_out(crew["base_hourly_rate"]),
        "piece_rate_per_vine": dec_out(crew["piece_rate_per_vine"]),
        "vines_per_hour_standard": dec_out(crew["vines_per_hour_standard"]),
        "task_capabilities": list(crew["task_capabilities"]),
        "pest_certified": crew["pest_certified"],
        "crew_status": crew["crew_status"],
        "scheduled_work_order_count": scheduled_work_order_count(crew["id"]),
    })
    return out


# --------------------------------------------------------------------------
# WorkOrder
# --------------------------------------------------------------------------


def serialize_work_order(order):
    out = store.base_fields(order)
    out.update({
        "block_id": order["block_id"],
        "farming_plan_id": order["farming_plan_id"],
        "crew_id": order["crew_id"],
        "task_type": order["task_type"],
        "scheduled_start": order["scheduled_start"],
        "scheduled_end": order["scheduled_end"],
        "planned_vines": order["planned_vines"],
        "planned_hours": dec_out(order["planned_hours"]),
        "actual_vines": order["actual_vines"],
        "actual_hours": dec_out(order["actual_hours"]),
        "execution_status": order["execution_status"],
        "payroll_status": order["payroll_status"],
        "estimated_labor_cost": dec_out(order["estimated_labor_cost"]),
        "actual_labor_cost": dec_out(order["actual_labor_cost"]),
        "cancel_reason": order["cancel_reason"],
        "started_at": fmt_dt(order["started_at"]),
        "completed_at": fmt_dt(order["completed_at"]),
    })
    return out


# --------------------------------------------------------------------------
# IrrigationEvent
# --------------------------------------------------------------------------


def serialize_irrigation(event):
    out = store.base_fields(event)
    out.update({
        "block_id": event["block_id"],
        "farming_plan_id": event["farming_plan_id"],
        "scheduled_start": event["scheduled_start"],
        "scheduled_end": event["scheduled_end"],
        "et0_inches": dec_out(event["et0_inches"]),
        "crop_coefficient": dec_out(event["crop_coefficient"]),
        "soil_moisture_pct": dec_out(event["soil_moisture_pct"]),
        "field_capacity_pct": dec_out(event["field_capacity_pct"]),
        "root_zone_depth_in": dec_out(event["root_zone_depth_in"]),
        "effective_rain_inches": dec_out(event["effective_rain_inches"]),
        "water_unit_cost_per_acre_inch": dec_out(event["water_unit_cost_per_acre_inch"]),
        "deficit_factor": dec_out(event["deficit_factor"]),
        "et_demand_inches": dec_out(event["et_demand_inches"]),
        "target_inches": dec_out(event["target_inches"]),
        "soil_shortfall_inches": dec_out(event["soil_shortfall_inches"]),
        "refill_inches": dec_out(event["refill_inches"]),
        "gross_requirement_inches": dec_out(event["gross_requirement_inches"]),
        "seasonal_allowance_inches": dec_out(event["seasonal_allowance_inches"]),
        "recommended_inches": dec_out(event["recommended_inches"]),
        "applied_inches": dec_out(event["applied_inches"]),
        "water_cost": dec_out(event["water_cost"]),
        "irrigation_status": event["irrigation_status"],
        "applied_at": fmt_dt(event["applied_at"]),
    })
    return out


# --------------------------------------------------------------------------
# PestObservation / YieldEstimate — event records: id + created_at only,
# no updated_at and no version key at all.
# --------------------------------------------------------------------------


def serialize_observation(obs):
    return {
        "id": obs["id"],
        "created_at": fmt_ms(obs["created_at"]),
        "block_id": obs["block_id"],
        "pest_code": obs["pest_code"],
        "incidence_pct": dec_out(obs["incidence_pct"]),
        "severity_index": obs["severity_index"],
        "scouting_note": obs["scouting_note"],
        "observed_at": fmt_dt(obs["observed_at"]),
        "scout_user_id": obs["scout_user_id"],
        "action_threshold_pct": dec_out(obs["action_threshold_pct"]),
        "exceeds_threshold": obs["exceeds_threshold"],
    }


def serialize_estimate(est):
    return {
        "id": est["id"],
        "created_at": fmt_ms(est["created_at"]),
        "block_id": est["block_id"],
        "method": est["method"],
        "sample_date": est["sample_date"],
        "avg_clusters_per_vine": dec_out(est["avg_clusters_per_vine"]),
        "avg_cluster_weight_lb": dec_out(est["avg_cluster_weight_lb"]),
        "berries_per_cluster": est["berries_per_cluster"],
        "avg_berry_weight_g": dec_out(est["avg_berry_weight_g"]),
        "days_to_harvest": est["days_to_harvest"],
        "vine_count_at_estimate": est["vine_count_at_estimate"],
        "estimated_tons": dec_out(est["estimated_tons"]),
        "estimated_tons_per_acre": dec_out(est["estimated_tons_per_acre"]),
    }


# --------------------------------------------------------------------------
# SprayRecord
# --------------------------------------------------------------------------


def serialize_spray(spray):
    out = store.base_fields(spray)
    out.update({
        "block_id": spray["block_id"],
        "farming_plan_id": spray["farming_plan_id"],
        "pest_observation_id": spray["pest_observation_id"],
        "product_name": spray["product_name"],
        "active_ingredient": spray["active_ingredient"],
        "rei_hours": spray["rei_hours"],
        "phi_days": spray["phi_days"],
        "rate_per_acre": dec_out(spray["rate_per_acre"]),
        "material_cost": dec_out(spray["material_cost"]),
        "spray_status": spray["spray_status"],
        "recommended_by_user_id": spray["recommended_by_user_id"],
        "applied_by_user_id": spray["applied_by_user_id"],
        "verified_by_user_id": spray["verified_by_user_id"],
        "applicator_license_no": spray["applicator_license_no"],
        "wind_speed_mph": dec_out(spray["wind_speed_mph"]),
        "applied_at": fmt_dt(spray["applied_at"]),
        "rei_clear_at": fmt_dt(spray["rei_clear_at"]),
        "phi_clear_at": fmt_dt(spray["phi_clear_at"]),
    })
    return out


# --------------------------------------------------------------------------
# WineryDeliveryWindow
# --------------------------------------------------------------------------


def window_committed_tons(window_id):
    total = ZERO
    for load in store.harvest_loads.values():
        if load["delivery_window_id"] == window_id and load["load_status"] in ("PLANNED", "IN_TRANSIT"):
            total += load["estimated_tons"]
    return r2(total)


def serialize_window(window):
    committed = window_committed_tons(window["id"])
    out = store.base_fields(window)
    out.update({
        "winery_name": window["winery_name"],
        "window_start": window["window_start"],
        "window_end": window["window_end"],
        "capacity_tons": dec_out(window["capacity_tons"]),
        "committed_tons": dec_out(committed),
        "remaining_tons": dec_out(r2(window["capacity_tons"] - committed)),
        "window_posture": calc.window_posture(committed, window["capacity_tons"]),
    })
    return out


# --------------------------------------------------------------------------
# HarvestLoad
# --------------------------------------------------------------------------


def serialize_load(load):
    out = store.base_fields(load)
    out.update({
        "block_id": load["block_id"],
        "crew_id": load["crew_id"],
        "delivery_window_id": load["delivery_window_id"],
        "estimated_tons": dec_out(load["estimated_tons"]),
        "delivery_eta": load["delivery_eta"],
        "load_status": load["load_status"],
        "gross_tons_at_dispatch": dec_out(load["gross_tons_at_dispatch"]),
        "dispatched_at": fmt_dt(load["dispatched_at"]),
        "gross_tons": dec_out(load["gross_tons"]),
        "tare_tons": dec_out(load["tare_tons"]),
        "mog_deduct_pct": dec_out(load["mog_deduct_pct"]),
        "brix_at_receipt": dec_out(load["brix_at_receipt"]),
        "net_tons": dec_out(load["net_tons"]),
        "quality_incentive_amount": dec_out(load["quality_incentive_amount"]),
        "received_at": fmt_dt(load["received_at"]),
        "rejected_at": fmt_dt(load["rejected_at"]),
        "rejection_reason": load["rejection_reason"],
    })
    return out
