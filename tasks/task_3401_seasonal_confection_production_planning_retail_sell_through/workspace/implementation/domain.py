"""Domain constants, entity getters (404), computed-field recomputes, and
serializers.

Computed totals (program aggregates, warehouse load/posture) are always
derived fresh from the stored entity tables at read time, so they can never
drift from the mutations that produce them.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from db import db
from errors import (
    ApiError,
    ERR_PROGRAM_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_RUN_NOT_FOUND,
    ERR_RETAILER_NOT_FOUND, ERR_COMMITMENT_NOT_FOUND, ERR_SHIPMENT_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND, ERR_WAREHOUSE_NOT_FOUND, ERR_LOT_NOT_FOUND,
    ERR_DISPOSITION_NOT_FOUND, ERR_CONTRACT_NOT_FOUND, ERR_REPORT_NOT_FOUND,
)

# --- calculation constants (SCAFFOLD 1.3 / PRD 3) ---
SHORTFALL_CREDIT_PCT = Decimal("0.10")
TIER_RANK = {"GOLD": 0, "SILVER": 1, "BRONZE": 2}
SEASONAL_LIFT = {
    "VALENTINES": Decimal("1.10"),
    "EASTER": Decimal("1.15"),
    "HALLOWEEN": Decimal("1.25"),
    "CHRISTMAS": Decimal("1.20"),
}
CANNIBALIZATION_FLOOR = Decimal("0.85")
MIN_MARKDOWN_PCT = Decimal("0.10")
MAX_MARKDOWN_PCT = Decimal("0.70")
SUMMER_MONTHS = (6, 7, 8)
CONGESTED_PCT = Decimal("0.85")
CHANGEOVER_HOURS = 8
SECONDARY_RECOVERY_PCT = Decimal("0.25")
MAX_REOPEN = 1

SEASON_CODES = ("VALENTINES", "EASTER", "HALLOWEEN", "CHRISTMAS")
PRODUCT_KINDS = ("SEASONAL", "EVERYDAY")
TIERS = ("GOLD", "SILVER", "BRONZE")
COMMODITIES = ("COCOA", "SUGAR")
CLAIM_REASONS = ("MELT", "BLOOM", "PACKAGING_COMPROMISE")
DISPOSITION_CHANNELS = ("MARKDOWN", "SECONDARY", "DESTRUCTION")

# commitment statuses counted in committed_units_total
COMMITTED_STATUSES = ("CONFIRMED", "ALLOCATED", "SHORTED", "FULFILLING", "FULFILLED")
# statuses counted in allocated_units_total / pool drain
ALLOCATED_STATUSES = ("ALLOCATED", "SHORTED", "FULFILLING", "FULFILLED")
# statuses counted in shipped_units_total
SHIPPED_STATUSES = ("PLANNED", "DELIVERED")


def round_cents(dec_value):
    """Round a Decimal half-up to whole cents (integer result)."""
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(dec_value):
    """Round a Decimal half-up to exactly 4 decimal places."""
    return dec_value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# --- getters (path / body FK existence, 404) --------------------------------

def _get(table, error_id, entity_name):
    def getter(entity_id):
        entity = table.get(entity_id)
        if entity is None:
            raise ApiError(404, error_id, "%s %s does not exist" % (entity_name, entity_id))
        return entity
    return getter


get_program = _get(db.programs, ERR_PROGRAM_NOT_FOUND, "SeasonalProgram")
get_product = _get(db.products, ERR_PRODUCT_NOT_FOUND, "Product")
get_run = _get(db.runs, ERR_RUN_NOT_FOUND, "ProductionRun")
get_retailer = _get(db.retailers, ERR_RETAILER_NOT_FOUND, "RetailerAccount")
get_commitment = _get(db.commitments, ERR_COMMITMENT_NOT_FOUND, "RetailerCommitment")
get_shipment = _get(db.shipments, ERR_SHIPMENT_NOT_FOUND, "Shipment")
get_claim = _get(db.claims, ERR_CLAIM_NOT_FOUND, "HeatClaim")
get_warehouse = _get(db.warehouses, ERR_WAREHOUSE_NOT_FOUND, "Warehouse")
get_lot = _get(db.lots, ERR_LOT_NOT_FOUND, "InventoryLot")
get_disposition = _get(db.dispositions, ERR_DISPOSITION_NOT_FOUND, "DispositionOrder")
get_contract = _get(db.contracts, ERR_CONTRACT_NOT_FOUND, "CommodityContract")
get_report = _get(db.reports, ERR_REPORT_NOT_FOUND, "SellThroughReport")


# --- computed aggregates ------------------------------------------------------

def warehouse_load(warehouse_id):
    """in_use_units / quarantined_units / posture per PRD 2.9.

    Inclusive boundaries: in_use >= capacity -> FULL; in_use >=
    floor(0.85 * capacity) -> CONGESTED; else OPEN.
    """
    in_use = 0
    quarantined = 0
    for lot in db.lots.values():
        if lot["warehouse_id"] != warehouse_id:
            continue
        if lot["status"] in ("AVAILABLE", "QUARANTINED"):
            in_use += lot["units_on_hand"]
        if lot["status"] == "QUARANTINED":
            quarantined += lot["units_on_hand"]
    capacity = db.warehouses[warehouse_id]["capacity_units"]
    threshold = int(math.floor(capacity * 0.85))
    if in_use >= capacity:
        posture = "FULL"
    elif in_use >= threshold:
        posture = "CONGESTED"
    else:
        posture = "OPEN"
    return in_use, quarantined, posture


def program_produced_total(program_id):
    return sum(r["produced_units"] for r in db.runs.values()
               if r["program_id"] == program_id and r["status"] == "COMPLETE")


def program_committed_total(program_id):
    return sum(c["committed_units"] for c in db.commitments.values()
               if c["program_id"] == program_id and c["status"] in COMMITTED_STATUSES)


def program_allocated_total(program_id):
    return sum(c["allocated_units"] for c in db.commitments.values()
               if c["program_id"] == program_id and c["status"] in ALLOCATED_STATUSES)


def program_shipped_total(program_id):
    total = 0
    for s in db.shipments.values():
        if s["status"] not in SHIPPED_STATUSES:
            continue
        commitment = db.commitments.get(s["commitment_id"])
        if commitment is not None and commitment["program_id"] == program_id:
            total += s["units"]
    return total


def program_disposed_total(program_id):
    return sum(d["units"] for d in db.dispositions.values()
               if d["program_id"] == program_id and d["status"] == "EXECUTED")


def produced_units_of_product(product_id):
    return sum(r["produced_units"] for r in db.runs.values()
               if r["product_id"] == product_id and r["status"] == "COMPLETE")


def allocated_units_of_product(product_id):
    return sum(c["allocated_units"] for c in db.commitments.values()
               if c["product_id"] == product_id and c["status"] in ALLOCATED_STATUSES)


def remaining_pool(product_id):
    """program_supply_pool (PRD 3.6): produced minus allocated for the product."""
    return produced_units_of_product(product_id) - allocated_units_of_product(product_id)


def quarantined_units_at(product_id, warehouse_id):
    return sum(l["units_on_hand"] for l in db.lots.values()
               if l["product_id"] == product_id and l["warehouse_id"] == warehouse_id
               and l["status"] == "QUARANTINED")


def delivered_units_of_commitment(commitment_id):
    return sum(s["units"] for s in db.shipments.values()
               if s["commitment_id"] == commitment_id and s["status"] == "DELIVERED")


def lot_draw_order(lots):
    """FEFO draw order: created_at ASC, lot_code ASC."""
    return sorted(lots, key=lambda l: (l["created_at"], l["lot_code"]))


# --- serializers -------------------------------------------------------------

def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_program(p):
    out = _common(p)
    out.update({
        "season_code": p["season_code"],
        "season_year": p["season_year"],
        "commitment_open_on": p["commitment_open_on"],
        "commitment_close_on": p["commitment_close_on"],
        "production_deadline_on": p["production_deadline_on"],
        "ship_window_open_on": p["ship_window_open_on"],
        "ship_window_close_on": p["ship_window_close_on"],
        "on_shelf_on": p["on_shelf_on"],
        "pull_on": p["pull_on"],
        "destroy_by_on": p["destroy_by_on"],
        "retail_price_cents": p["retail_price_cents"],
        "forecast_units": p["forecast_units"],
        "produced_units_total": program_produced_total(p["id"]),
        "committed_units_total": program_committed_total(p["id"]),
        "shipped_units_total": program_shipped_total(p["id"]),
        "disposed_units_total": program_disposed_total(p["id"]),
        "reopen_count": p["reopen_count"],
        "status": p["status"],
    })
    return out


def ser_product(p):
    out = _common(p)
    out.update({
        "program_id": p["program_id"],
        "sku_code": p["sku_code"],
        "kind": p["kind"],
        "molded_shape": p["molded_shape"],
        "brand_protected": p["brand_protected"],
        "requires_temp_control": p["requires_temp_control"],
        "units_per_case": p["units_per_case"],
    })
    return out


def ser_run(r):
    out = _common(r)
    out.update({
        "program_id": r["program_id"],
        "product_id": r["product_id"],
        "line_code": r["line_code"],
        "planned_units": r["planned_units"],
        "produced_units": r["produced_units"],
        "scheduled_start_on": r["scheduled_start_on"],
        "scheduled_end_on": r["scheduled_end_on"],
        "completed_warehouse_id": r["completed_warehouse_id"],
        "status": r["status"],
    })
    return out


def ser_retailer(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "region": r["region"],
        "tier": r["tier"],
        "max_seasonal_units": r["max_seasonal_units"],
        "everyday_baseline_weekly_units": r["everyday_baseline_weekly_units"],
        "credit_balance_cents": r["credit_balance_cents"],
    })
    return out


def ser_commitment(c):
    out = _common(c)
    out.update({
        "program_id": c["program_id"],
        "retailer_id": c["retailer_id"],
        "product_id": c["product_id"],
        "committed_units": c["committed_units"],
        "allocated_units": c["allocated_units"],
        "reorder_units": c["reorder_units"],
        "reorder_used": c["reorder_used"],
        "revision": c["revision"],
        "supersedes_commitment_id": c["supersedes_commitment_id"],
        "ship_window_open_on": c["ship_window_open_on"],
        "ship_window_close_on": c["ship_window_close_on"],
        "status": c["status"],
    })
    return out


def ser_shipment(s):
    out = _common(s)
    out.update({
        "commitment_id": s["commitment_id"],
        "warehouse_id": s["warehouse_id"],
        "units": s["units"],
        "ship_on": s["ship_on"],
        "temp_controlled": s["temp_controlled"],
        "temp_control_declined_by_retailer": s["temp_control_declined_by_retailer"],
        "delivered_on": s["delivered_on"],
        "status": s["status"],
    })
    return out


def ser_claim(c):
    out = _common(c)
    out.update({
        "shipment_id": c["shipment_id"],
        "claimed_units": c["claimed_units"],
        "reason": c["reason"],
        "evidence_note": c["evidence_note"],
        "auto_approve": c["auto_approve"],
        "credit_cents": c["credit_cents"],
        "status": c["status"],
    })
    return out


def ser_warehouse(w):
    in_use, quarantined, posture = warehouse_load(w["id"])
    out = _common(w)
    out.update({
        "name": w["name"],
        "temp_controlled": w["temp_controlled"],
        "capacity_units": w["capacity_units"],
        "in_use_units": in_use,
        "quarantined_units": quarantined,
        "posture": posture,
    })
    return out


def ser_lot(l):
    out = _common(l)
    out.update({
        "product_id": l["product_id"],
        "warehouse_id": l["warehouse_id"],
        "production_run_id": l["production_run_id"],
        "lot_code": l["lot_code"],
        "units_on_hand": l["units_on_hand"],
        "status": l["status"],
    })
    return out


def ser_disposition(d):
    out = _common(d)
    out.update({
        "program_id": d["program_id"],
        "product_id": d["product_id"],
        "warehouse_id": d["warehouse_id"],
        "units": d["units"],
        "channel": d["channel"],
        "markdown_pct": d["markdown_pct"],
        "proposed_by_user_id": d["proposed_by_user_id"],
        "approved_by_user_id": d["approved_by_user_id"],
        "recovered_value_cents": d["recovered_value_cents"],
        "status": d["status"],
    })
    return out


def ser_contract(c):
    out = _common(c)
    out.update({
        "program_id": c["program_id"],
        "commodity": c["commodity"],
        "quantity_units": c["quantity_units"],
        "contract_price_cents_per_unit": c["contract_price_cents_per_unit"],
        "hedged_quantity_units": c["hedged_quantity_units"],
        "hedge_price_cents_per_unit": c["hedge_price_cents_per_unit"],
        "spot_price_cents_per_unit": c["spot_price_cents_per_unit"],
        "provisional_spend_cents": c["provisional_spend_cents"],
        "effective_spend_cents": c["effective_spend_cents"],
        "status": c["status"],
    })
    return out


def ser_report(r):
    out = _common(r)
    out.update({
        "retailer_id": r["retailer_id"],
        "program_id": r["program_id"],
        "week_of_on": r["week_of_on"],
        "seasonal_units_sold": r["seasonal_units_sold"],
        "seasonal_units_on_hand": r["seasonal_units_on_hand"],
        "everyday_units_sold": r["everyday_units_sold"],
        "cannibalization_raw": r["cannibalization_raw"],
        "cannibalization_adjusted": r["cannibalization_adjusted"],
    })
    return out
