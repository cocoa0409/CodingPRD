"""Recomputed ledgers and the three deep cascades (PRD 2.8, 2.11, 3.1, 3.3, 3.8, 3.9).

Nothing here is patched incrementally: the property conducive ledger and the
bond money components are always recomputed from the rows that define them.
"""

from decimal import Decimal

import calc
from clock import clock, plus_days
from store import (bonds_of, claims_of, db, findings_of, inspections_of,
                   renewals_of, reports_of, stations_of, touch)

ZERO = calc.ZERO


# --------------------------------------------------------------------------
# Property conducive-condition ledger (PRD 3.1)
# --------------------------------------------------------------------------

def latest_signed_graph(property_id):
    """The property's GRAPHED graph with the greatest graph_completed_at.

    Ties break on the greater sequence_no, which makes the choice total.
    """
    graphed = [i for i in inspections_of(property_id)
               if i["status"] == "GRAPHED" and i["graph_completed_at"] is not None]
    if not graphed:
        return None
    return max(graphed, key=lambda i: (i["graph_completed_at"], i["sequence_no"]))


def bond_of_record(property_id):
    """The single bond on the property whose status is ACTIVE or LAPSED."""
    for bond in bonds_of(property_id):
        if bond["status"] in ("ACTIVE", "LAPSED"):
            return bond
    return None


def distinct_conducive_codes(inspection):
    if inspection is None:
        return set()
    return set(f["conducive_code"] for f in findings_of(inspection["id"])
               if f["finding_type"] == "CONDUCIVE_CONDITION" and f["conducive_code"] != "NONE")


def recompute_property_ledger(prop):
    """Recompute the four counters and active_infestation_on_record from scratch."""
    graph = latest_signed_graph(prop["id"])
    codes = distinct_conducive_codes(graph)
    total = len(codes)
    bond = bond_of_record(prop["id"])
    if bond is None:
        waived = 0
    else:
        waived = len(codes & set(bond["conducive_waiver_codes"]))
    infestation = bool(graph is not None and graph["active_infestation_found"])
    changed = (prop["total_conducive_condition_count"] != total
               or prop["waived_conducive_condition_count"] != waived
               or prop["open_conducive_condition_count"] != total - waived
               or prop["active_infestation_on_record"] != infestation)
    prop["total_conducive_condition_count"] = total
    prop["waived_conducive_condition_count"] = waived
    prop["open_conducive_condition_count"] = total - waived
    prop["active_infestation_on_record"] = infestation
    if changed:
        touch(prop)
    return prop


# --------------------------------------------------------------------------
# Inspection rollups (PRD 3.3)
# --------------------------------------------------------------------------

def recompute_inspection_rollups(inspection):
    rows = findings_of(inspection["id"])
    inspection["findings_count"] = len(rows)
    inspection["conducive_condition_count"] = len(
        [f for f in rows if f["finding_type"] == "CONDUCIVE_CONDITION"])
    inspection["active_infestation_found"] = any(
        f["finding_type"] == "ACTIVE_INFESTATION" for f in rows)
    inspection["damage_estimate_total_usd"] = calc.r2(
        sum((f["damage_estimate_usd"] for f in rows if f["finding_type"] == "DAMAGE"), ZERO))
    return inspection


# --------------------------------------------------------------------------
# Bond money conservation (PRD 2.8)
# --------------------------------------------------------------------------

def recompute_bond_money(bond):
    """Re-establish repair_liability_cap == paid + reserved + remaining."""
    rows = claims_of(bond["id"])
    paid = calc.r2(sum((c["approved_payout_usd"] for c in rows
                        if c["status"] == "APPROVED_REPAIR"), ZERO))
    reserved = calc.r2(sum((c["projected_payout_usd"] for c in rows
                            if c["status"] == "UNDER_ADJUDICATION"), ZERO))
    bond["claims_paid_to_date_usd"] = paid
    bond["reserved_claim_amount_usd"] = reserved
    bond["remaining_repair_cap_usd"] = calc.r2(
        bond["repair_liability_cap_usd"] - paid - reserved)
    return bond


# --------------------------------------------------------------------------
# Supersession chain (PRD 3.3) - three hops
# --------------------------------------------------------------------------

def supersede_graph(prior):
    """hop 1 graph -> SUPERSEDED, hop 2 its reports -> VOID, hop 3 ledger."""
    prior["status"] = "SUPERSEDED"
    touch(prior)
    for report in reports_of(prior["id"]):
        if report["status"] in ("DRAFT", "ISSUED", "AMENDED"):
            report["status"] = "VOID"
            touch(report)
    prop = db.properties.get(prior["property_id"])
    if prop is not None:
        recompute_property_ledger(prop)


# --------------------------------------------------------------------------
# Station escalation chain (PRD 3.9) - three hops
# --------------------------------------------------------------------------

def escalation_cascade(station, plan):
    """hop 2: the plan counts the escalation; hop 3: the bond goes on watch."""
    plan["escalated_station_count"] = plan["escalated_station_count"] + 1
    flipped = False
    threshold = calc.plan_escalation_threshold(plan["target_station_count"])
    if not plan["retreat_required"] and plan["escalated_station_count"] >= threshold:
        plan["retreat_required"] = True
        flipped = True
    touch(plan)
    if not flipped:
        return
    for bond in db.bonds.values():
        if bond["treatment_plan_id"] == plan["id"] and bond["status"] == "ACTIVE":
            bond["coverage_watch"] = True
            bond["retreat_required"] = True
            touch(bond)


# --------------------------------------------------------------------------
# Bond lapse chain (PRD 3.8) - three hops
# --------------------------------------------------------------------------

def lapse_bond(bond):
    """hop 1 bond -> LAPSED, hop 2 renewals VOID + claims DENIED, hop 3 release."""
    bond["status"] = "LAPSED"
    bond["lapse_date"] = plus_days(bond["current_term_end"], calc.GRACE_DAYS)
    for renewal in renewals_of(bond["id"]):
        if renewal["status"] == "PENDING":
            renewal["status"] = "VOID"
            touch(renewal)
    released = False
    for claim in claims_of(bond["id"]):
        if claim["status"] in ("SUBMITTED", "UNDER_ADJUDICATION"):
            was_reserved = claim["status"] == "UNDER_ADJUDICATION"
            claim["status"] = "DENIED"
            claim["denial_reason_code"] = "BOND_LAPSED"
            claim["approved_payout_usd"] = ZERO
            touch(claim)
            if was_reserved:
                released = True
    if released:
        recompute_bond_money(bond)
    touch(bond)
    return bond


def terminate_bond(bond):
    """hop 1 bond -> TERMINATED, hop 2 stations REMOVED + property waivers unwound."""
    bond["status"] = "TERMINATED"
    for station in stations_of(bond["treatment_plan_id"]):
        if station["status"] in ("INSTALLED", "ACTIVE_HIT", "ESCALATED"):
            station["status"] = "REMOVED"
            touch(station)
    touch(bond)
    prop = db.properties.get(bond["property_id"])
    if prop is not None:
        recompute_property_ledger(prop)
    return bond


# --------------------------------------------------------------------------
# Bond term windows (PRD 3.7, 3.8)
# --------------------------------------------------------------------------

def set_term_windows(bond, term_start, term_end):
    bond["current_term_start"] = term_start
    bond["current_term_end"] = term_end
    bond["renewal_window_opens_on"] = plus_days(term_end, -calc.RENEWAL_WINDOW_DAYS)
    return bond


def roll_term_forward(bond):
    previous_end = bond["current_term_end"]
    set_term_windows(bond, previous_end, plus_days(previous_end, calc.TERM_DAYS))
    bond["term_index"] = bond["term_index"] + 1
    return bond


def renewal_window_open(bond):
    today = clock.today()
    opens = bond["renewal_window_opens_on"]
    closes = plus_days(bond["current_term_end"], calc.GRACE_DAYS)
    return opens <= today <= closes


def past_due_days(bond):
    delta = (clock.today() - bond["current_term_end"]).days
    return max(0, delta)


def money(value):
    return Decimal(value)
