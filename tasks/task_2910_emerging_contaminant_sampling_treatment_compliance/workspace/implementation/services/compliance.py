"""Entry-point derived state: LRAAs, compliance ratio, mixture hazard index,
reduction streak and compliance posture, with the posture-transition cascades
(PRD sections 3.4 and 3.6).
"""

from decimal import Decimal

import constants as C
import db
from db import store, touch
from numeric import divide, q2, q4, dec
from shape import decode_period

ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")


# --------------------------------------------------------------------- helpers
def accepted_results_at(entry_point_id):
    """(result, sample) pairs for every ACCEPTED result at this entry point."""
    pairs = []
    for result in db.sorted_rows("lab_results"):
        if result["status"] != "ACCEPTED":
            continue
        sample = store.samples.get(result["sample_id"])
        if sample is None or sample["entry_point_id"] != entry_point_id:
            continue
        pairs.append((result, sample))
    return pairs


def lraa_window(entry_point_id, contaminant_id):
    """The LRAA input set: ACCEPTED results for this contaminant whose sample is
    ANALYZED, one row per monitoring period, most recent four periods."""
    by_period = {}
    for result, sample in accepted_results_at(entry_point_id):
        if result["contaminant_id"] != contaminant_id:
            continue
        if sample["status"] != "ANALYZED":
            continue
        period = sample["monitoring_period"]
        if period not in by_period:
            by_period[period] = result
    periods = sorted(by_period.keys(), key=decode_period, reverse=True)
    periods = periods[: C.LRAA_WINDOW_QUARTERS]
    return [by_period[period] for period in periods]


def lraa_pair(entry_point_id, contaminant_id):
    """(compliance_lraa, planning_lraa, quarters_used)."""
    rows = lraa_window(entry_point_id, contaminant_id)
    used = len(rows)
    if used == 0:
        return ZERO2, ZERO2, 0
    compliance_sum = sum((row["compliance_value_ng_per_l"] for row in rows), Decimal(0))
    planning_sum = sum((row["planning_value_ng_per_l"] for row in rows), Decimal(0))
    return q2(divide(compliance_sum, used)), q2(divide(planning_sum, used)), used


def _contaminant_ids_with_window(entry_point_id):
    ids = []
    for result, sample in accepted_results_at(entry_point_id):
        if sample["status"] != "ANALYZED":
            continue
        if result["contaminant_id"] not in ids:
            ids.append(result["contaminant_id"])
    return ids


def max_compliance_ratio(entry_point_id):
    best = None
    for contaminant_id in _contaminant_ids_with_window(entry_point_id):
        contaminant = store.contaminants.get(contaminant_id)
        if contaminant is None:
            continue
        compliance, _planning, used = lraa_pair(entry_point_id, contaminant_id)
        if used == 0:
            continue
        ratio = q4(divide(compliance, contaminant["mcl_ng_per_l"]))
        if best is None or ratio > best:
            best = ratio
    if best is None:
        return ZERO4
    return best


def hazard_index(entry_point_id):
    """Accumulates unrounded; rounds exactly once at the end."""
    total = Decimal(0)
    contributors = 0
    for contaminant_id in _contaminant_ids_with_window(entry_point_id):
        contaminant = store.contaminants.get(contaminant_id)
        if contaminant is None or not contaminant["hazard_index_member"]:
            continue
        hbwc = contaminant["hbwc_ng_per_l"]
        if hbwc is None or dec(hbwc) == 0:
            continue
        compliance, _planning, used = lraa_pair(entry_point_id, contaminant_id)
        if used == 0:
            continue
        term = divide(compliance, hbwc)
        if term > C.HAZARD_TERM_CAP:
            term = C.HAZARD_TERM_CAP
        total = total + term
        contributors += 1
    if contributors == 0:
        return ZERO2
    return q2(total)


def consecutive_qualifying_quarters(entry_point_id):
    by_period = {}
    for result, sample in accepted_results_at(entry_point_id):
        by_period.setdefault(sample["monitoring_period"], []).append(result)
    periods = sorted(by_period.keys(), key=decode_period, reverse=True)
    streak = 0
    for period in periods:
        qualifies = True
        for result in by_period[period]:
            contaminant = store.contaminants.get(result["contaminant_id"])
            if contaminant is None:
                continue
            if not (result["compliance_value_ng_per_l"] < contaminant["trigger_level_ng_per_l"]):
                qualifies = False
                break
        if not qualifies:
            break
        streak += 1
    return streak


def accepted_result_count(entry_point_id):
    return len(accepted_results_at(entry_point_id))


def open_violation_count(entry_point_id):
    total = 0
    for determination in store.determinations.values():
        if determination["entry_point_id"] != entry_point_id:
            continue
        if determination["status"] == "ISSUED" and determination["determination"] == "MCL_VIOLATION":
            total += 1
    return total


# ------------------------------------------------------------------- cascades
def derive_posture(ratio, hazard, count):
    if count < 1:
        return "COMPLIANT"
    if ratio > Decimal("1.0") or hazard > C.HAZARD_INDEX_MCL:
        return "VIOLATION_PENDING"
    if ratio >= C.POSTURE_TRIGGER_RATIO:
        return "TRIGGERED"
    return "COMPLIANT"


def open_evaluation_for(entry_point_id):
    for evaluation in db.sorted_rows("evaluations"):
        if evaluation["entry_point_id"] != entry_point_id:
            continue
        if evaluation["status"] in ("SCREENING", "PILOTING"):
            return evaluation
    return None


def create_mandated_evaluation(entry_point):
    return db.insert(
        "evaluations",
        {
            "entry_point_id": entry_point["id"],
            "residuals_budget_cents": C.DEFAULT_RESIDUALS_BUDGET_CENTS,
            "residuals_spent_cents": 0,
            "mandated": True,
            "status": "SCREENING",
            "selected_technology": None,
            "decision_note": None,
        },
    )


def _revoke_reduced_frequency(entry_point):
    if entry_point["monitoring_status"] in ("ANNUAL", "TRIENNIAL"):
        entry_point["monitoring_status"] = "QUARTERLY"


def _auto_deny_pending_reduction(entry_point):
    if entry_point["monitoring_status"] == "REDUCTION_PENDING":
        entry_point["monitoring_status"] = "QUARTERLY"
        entry_point["requested_monitoring_status"] = None


def _apply_posture_transition(entry_point, old, new):
    if old == "COMPLIANT" and new == "TRIGGERED":
        _revoke_reduced_frequency(entry_point)
    elif old == "COMPLIANT" and new == "VIOLATION_PENDING":
        _revoke_reduced_frequency(entry_point)
        if open_evaluation_for(entry_point["id"]) is None:
            create_mandated_evaluation(entry_point)
        _auto_deny_pending_reduction(entry_point)
    elif old == "TRIGGERED" and new == "VIOLATION_PENDING":
        if open_evaluation_for(entry_point["id"]) is None:
            create_mandated_evaluation(entry_point)


def rederive_entry_point(entry_point):
    """Re-derives every LRAA-driven field from primary evidence and runs the
    posture-transition cascades.  Callers are responsible for touching the row."""
    old_posture = entry_point["compliance_posture"]
    entry_point["accepted_result_count"] = accepted_result_count(entry_point["id"])
    entry_point["max_compliance_ratio"] = max_compliance_ratio(entry_point["id"])
    entry_point["hazard_index"] = hazard_index(entry_point["id"])
    entry_point["consecutive_qualifying_quarters"] = consecutive_qualifying_quarters(
        entry_point["id"]
    )
    new_posture = derive_posture(
        entry_point["max_compliance_ratio"],
        entry_point["hazard_index"],
        entry_point["accepted_result_count"],
    )
    entry_point["compliance_posture"] = new_posture
    if new_posture != old_posture:
        _apply_posture_transition(entry_point, old_posture, new_posture)
    return entry_point


def register_invalidation(entry_point):
    """Streak bookkeeping shared by receipt-time rejection and explicit
    invalidation; reaching the threshold suspends monitoring."""
    entry_point["consecutive_invalidated_samples"] = (
        entry_point["consecutive_invalidated_samples"] + 1
    )
    if entry_point["consecutive_invalidated_samples"] >= C.SUSPENSION_INVALIDATION_STREAK:
        if entry_point["monitoring_status"] != "SUSPENDED":
            entry_point["monitoring_status"] = "SUSPENDED"
            entry_point["requested_monitoring_status"] = None


def sample_panel_complete(sample):
    """True when every contaminant on the panel has exactly one ACCEPTED result."""
    for contaminant_id in sample["panel_contaminant_ids"]:
        matches = 0
        for result in store.lab_results.values():
            if result["sample_id"] != sample["id"]:
                continue
            if result["contaminant_id"] != contaminant_id:
                continue
            if result["status"] == "ACCEPTED":
                matches += 1
        if matches != 1:
            return False
    return True
