"""Derived-field refreshers and the two conservation ledgers of PRD 2.8.

These helpers only write fields; the caller decides which rows get their
`version` increased, because the PRD pins that per operation.
"""

from decimal import Decimal

import calc
from calc import dec
from store import db, rows, touch


# ---------------------------------------------------------------------------
# Ledger 1 - raw material units (PRD 2.8)
# ---------------------------------------------------------------------------

def material_lot_quantities(lot):
    consumed = Decimal(0)
    for component in rows(db.lot_components):
        if component["material_lot_id"] == lot["id"] and component["status"] == "CONSUMED":
            consumed += dec(component["quantity_used"])
    lot["consumed_quantity_units"] = consumed
    if lot["qualification_status"] in ("REJECTED", "QUARANTINED"):
        lot["available_quantity_units"] = Decimal("0")
    else:
        lot["available_quantity_units"] = dec(lot["received_quantity_units"]) - consumed


def material_lot_score(lot):
    spec = db.material_specifications[lot["material_specification_id"]]
    if spec["acceptance_mode"] != "WEIGHTED_SCORE":
        lot["acceptance_score"] = None
        return
    score, _zero = calc.acceptance_score(spec, lot["id"])
    lot["acceptance_score"] = score


def material_lot_retest_count(lot):
    lot["retest_count"] = len([r for r in calc.material_results(lot["id"])
                               if r["is_retest"]])


# ---------------------------------------------------------------------------
# Ledger 2 - finished-goods units (PRD 2.8)
# ---------------------------------------------------------------------------

def reagent_lot_units(lot):
    allocated = 0
    shipped = 0
    quarantined = 0
    for allocation in calc.allocation_rows(reagent_lot_id=lot["id"]):
        if allocation["status"] == "RESERVED":
            allocated += allocation["allocated_units"]
        elif allocation["status"] in ("SHIPPED", "DELIVERED"):
            shipped += allocation["allocated_units"]
        elif allocation["status"] == "QUARANTINED":
            quarantined += allocation["allocated_units"]
    lot["allocated_units"] = allocated
    lot["shipped_units"] = shipped
    lot["quarantined_units"] = quarantined
    if lot["disposition_status"] == "REJECTED":
        lot["available_units"] = 0
    else:
        lot["available_units"] = (lot["filled_units"] - allocated - shipped
                                  - quarantined)


def order_rollup(order):
    total = 0
    for allocation in calc.allocation_rows(distribution_order_id=order["id"]):
        if allocation["status"] in ("RESERVED", "SHIPPED", "DELIVERED"):
            total += allocation["allocated_units"]
    order["allocated_units"] = total
    order["shortfall_units"] = max(0, order["requested_units"] - total)


# ---------------------------------------------------------------------------
# Environmental monitoring (PRD 3.4)
# ---------------------------------------------------------------------------

def fill_run_environment(run):
    samples = calc.run_samples(run["id"])
    run["minor_excursion_count"] = len([s for s in samples
                                        if s["excursion_grade"] == "MINOR"])
    run["major_excursion_count"] = len([s for s in samples
                                        if s["excursion_grade"] == "MAJOR"])
    bulk = [dec(s["result_value"]) for s in samples
            if s["sample_type"] == "BIOBURDEN_BULK"]
    run["bioburden_cfu_per_ml"] = max(bulk) if bulk else None
    run["environmental_state"] = calc.environmental_state(
        run["minor_excursion_count"], run["major_excursion_count"])


def reagent_lot_monitoring(lot):
    excursions = 0
    bulk = []
    for run in calc.lot_runs(lot["id"]):
        for sample in calc.run_samples(run["id"]):
            if sample["excursion"]:
                excursions += 1
            if sample["sample_type"] == "BIOBURDEN_BULK":
                bulk.append(dec(sample["result_value"]))
    lot["em_excursion_count"] = excursions
    lot["bioburden_cfu_per_ml"] = max(bulk) if bulk else None


# ---------------------------------------------------------------------------
# Release roll-ups, bridging and stability
# ---------------------------------------------------------------------------

def reagent_lot_release_bias(lot):
    product = db.product_specifications[lot["product_specification_id"]]
    maximum, total = calc.release_bias_rollups(product, lot["id"])
    lot["release_bias_max_pct"] = maximum
    lot["release_bias_sum_pct"] = total


def reagent_lot_bridging_required(lot):
    lot["bridging_required"] = calc.bridging_required(lot)


def bridging_study_figures(study):
    """Returns True when a figure actually changed."""
    mean_bias, max_bias, verdict = calc.bridging_equivalence(study)
    changed = (study.get("mean_bias_pct") != mean_bias
               or study.get("max_bias_pct") != max_bias
               or study.get("equivalence_verdict") != verdict)
    study["mean_bias_pct"] = mean_bias
    study["max_bias_pct"] = max_bias
    study["equivalence_verdict"] = verdict
    return changed


def bridging_studies_touching_lot(reagent_lot_id):
    """Re-derive every bridging study linked to this lot (PRD 3.5/3.7)."""
    for study in rows(db.bridging_studies):
        if reagent_lot_id not in (study["predicate_lot_id"], study["candidate_lot_id"]):
            continue
        if bridging_study_figures(study):
            touch(study)


def stability_study_figures(study):
    study["timepoint_count"] = len(calc.stability_results(study["id"]))
    study["last_conforming_month"] = calc.last_conforming_month(study)


# ---------------------------------------------------------------------------
# Cold chain (PRD 3.9)
# ---------------------------------------------------------------------------

def allocation_cold_chain(allocation):
    events = [e for e in rows(db.cold_chain_events)
              if e["allocation_id"] == allocation["id"]]
    total = Decimal(0)
    temps = []
    for event in events:
        total += dec(event["excursion_minutes"])
        temps.append(dec(event["max_temp_c"]))
    allocation["cumulative_excursion_minutes"] = calc.rhu(total, 2)
    allocation["max_excursion_temp_c"] = calc.rhu(max(temps), 1) if temps else None
    allocation["cold_chain_status"] = calc.cold_chain_verdict(
        allocation["cumulative_excursion_minutes"],
        allocation["max_excursion_temp_c"])
