"""Grower-lot risk scoring: the PREHARVEST and TRAILING variants."""

import db
from util import clamp_int

WATER_SOURCE_PENALTY = 25
ANIMAL_ADJACENCY_PENALTY = 15
PRESUMPTIVE_TEST_PENALTY = 20
PRIOR_REJECT_PENALTY_PER_LOAD = 5
PRIOR_REJECT_PENALTY_CAP = 20
OUT_OF_SPEC_RECEIPT_PENALTY = 10
ENV_POSITIVE_RUN_PENALTY = 12
RISK_SUSPEND_THRESHOLD = 50
ENV_POSITIVE_HOLD_REASONS = ("ENVIRONMENTAL_POSITIVE", "RECALL")


def receipts_of(lot_id):
    return [r for r in db.rows("raw_receipts") if r["grower_lot_id"] == lot_id]


def out_of_spec_count(lot_id):
    return len(
        [
            r
            for r in receipts_of(lot_id)
            if r["temp_grade"] == "OUT_OF_SPEC" and r["status"] != "REJECTED"
        ]
    )


def runs_consuming(lot_id):
    """Distinct runs holding an ACTIVE consumption against one of the lot's loads."""
    receipt_ids = set(r["id"] for r in receipts_of(lot_id))
    run_ids = []
    for c in db.rows("lot_consumptions"):
        if c["status"] != "ACTIVE":
            continue
        if c["raw_receipt_id"] not in receipt_ids:
            continue
        if c["process_run_id"] not in run_ids:
            run_ids.append(c["process_run_id"])
    return run_ids


def env_positive_run_count(lot_id):
    count = 0
    for run_id in runs_consuming(lot_id):
        holds = [
            h
            for h in db.rows("hold_records")
            if h["process_run_id"] == run_id
            and h["reason"] in ENV_POSITIVE_HOLD_REASONS
        ]
        if holds:
            count += 1
    return count


def preharvest_score(lot):
    score = 100
    if lot["water_source"] == "SURFACE":
        score -= WATER_SOURCE_PENALTY
    if lot["adjacent_animal_operation"]:
        score -= ANIMAL_ADJACENCY_PENALTY
    if lot["preharvest_test_result"] == "PRESUMPTIVE":
        score -= PRESUMPTIVE_TEST_PENALTY
    score -= min(
        PRIOR_REJECT_PENALTY_CAP,
        PRIOR_REJECT_PENALTY_PER_LOAD * lot["prior_rejected_receipt_count"],
    )
    return clamp_int(score, 0, 100)


def refresh_counters(lot):
    changed = False
    oos = out_of_spec_count(lot["id"])
    env = env_positive_run_count(lot["id"])
    if lot["out_of_spec_receipt_count"] != oos:
        lot["out_of_spec_receipt_count"] = oos
        changed = True
    if lot["env_positive_run_count"] != env:
        lot["env_positive_run_count"] = env
        changed = True
    return changed


def recompute_trailing(lot):
    """Refresh the counters, re-derive the trailing score, suspend when it falls."""
    changed = refresh_counters(lot)
    if lot["preharvest_risk_score"] is not None:
        trailing = clamp_int(
            lot["preharvest_risk_score"]
            - OUT_OF_SPEC_RECEIPT_PENALTY * lot["out_of_spec_receipt_count"]
            - ENV_POSITIVE_RUN_PENALTY * lot["env_positive_run_count"],
            0,
            100,
        )
        if lot["trailing_risk_score"] != trailing:
            lot["trailing_risk_score"] = trailing
            changed = True
        if lot["status"] == "APPROVED" and trailing < RISK_SUSPEND_THRESHOLD:
            lot["status"] = "SUSPENDED"
            changed = True
    if changed:
        db.touch(lot)
    return changed


def lots_consumed_by_run(run_id):
    """Every grower lot behind an ACTIVE consumption of this run, in consumption order."""
    lots = []
    for c in db.rows("lot_consumptions"):
        if c["process_run_id"] != run_id or c["status"] != "ACTIVE":
            continue
        receipt = db.find("raw_receipts", c["raw_receipt_id"])
        if receipt is None:
            continue
        lot = db.find("grower_lots", receipt["grower_lot_id"])
        if lot is not None and lot not in lots:
            lots.append(lot)
    return lots
