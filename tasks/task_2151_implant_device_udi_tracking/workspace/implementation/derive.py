"""Derived counters, conserved quantities and the custody/billing setters.

Every recomputation here mutates the row it owns, so it refreshes that row's
updated_at and advances its version (PRD 2.4 / 2.12).
"""
from calc import CONSUMED_CUSTODY, ON_HAND_CUSTODY
from graph import (
    actions_of_vendor,
    catalog_of_unit,
    charges_of_record,
    lot_of,
    records_of_case,
    records_of_patient,
    submissions_of_record,
    notifications_of_action,
    units_of_catalog,
    units_of_lot,
    vendor_of_unit,
)
from store import db, touch

CONSIDERED_RECORD_EXCLUSIONS = ("VOIDED", "EXPLANTED")


# ----------------------------------------------------------------- C7
def lot_unit_conservation(lot):
    """C7 — received_qty / on_hand_qty / consumed_qty plus auto-depletion."""
    if lot is None:
        return
    units = units_of_lot(lot["id"])
    lot["received_qty"] = len(units)
    lot["on_hand_qty"] = len([u for u in units if u["custody_state"] in ON_HAND_CUSTODY])
    lot["consumed_qty"] = len([u for u in units if u["custody_state"] in CONSUMED_CUSTODY])
    if lot["status"] == "AVAILABLE" and lot["received_qty"] >= 1 and lot["on_hand_qty"] == 0:
        lot["status"] = "DEPLETED"
    touch(lot)


def recompute_catalog_available(item):
    if item is None:
        return
    item["on_hand_available_qty"] = len(
        [u for u in units_of_catalog(item["id"]) if u["custody_state"] == "AVAILABLE"]
    )
    touch(item)


# ----------------------------------------------------------------- C6
def vendor_open_consignment_liability(vendor):
    if vendor is None:
        return
    total = 0
    for unit in db.device_units.values():
        item = catalog_of_unit(unit)
        if item is None or item.get("vendor_id") != vendor["id"]:
            continue
        if unit.get("billing_state") in ("BILLABLE", "INVOICED"):
            total += int(unit.get("contract_price_cents") or 0)
    vendor["open_consignment_liability_cents"] = total
    touch(vendor)


def recompute_vendor_recall_open(vendor):
    if vendor is None:
        return
    vendor["recall_open_count"] = len(
        [a for a in actions_of_vendor(vendor["id"]) if a["status"] in ("PUBLISHED", "IN_REMEDIATION")]
    )
    touch(vendor)


def recompute_notification_open_count(action):
    if action is None:
        return
    action["notification_open_count"] = len(
        [n for n in notifications_of_action(action["id"]) if n["status"] == "PENDING"]
    )
    touch(action)


def recompute_patient_implant_count(patient):
    if patient is None:
        return
    patient["implant_count"] = len(
        [
            r
            for r in records_of_patient(patient["id"])
            if r["status"] in ("DOCUMENTED", "VERIFIED", "AMENDED", "EXPLANTED")
        ]
    )
    touch(patient)


# --------------------------------------------------------- charge helpers
def effective_charge_cents(charge):
    final = charge.get("final_charge_cents")
    if final is not None:
        return int(final)
    return int(charge.get("provisional_charge_cents") or 0)


def recompute_case_totals(case):
    """implant_record_count and total_posted_charge_cents (PRD 3.6 step 6)."""
    if case is None:
        return
    records = records_of_case(case["id"])
    case["implant_record_count"] = len([r for r in records if r["status"] != "VOIDED"])
    total = 0
    for record in records:
        for charge in charges_of_record(record["id"]):
            if charge["status"] in ("POSTED", "CORRECTION_REQUIRED", "FINALIZED"):
                total += effective_charge_cents(charge)
    case["total_posted_charge_cents"] = total
    touch(case)


def considered_records(case):
    return [
        r for r in records_of_case(case["id"]) if r["status"] not in CONSIDERED_RECORD_EXCLUSIONS
    ]


# ----------------------------------------------------------------- C10
def compute_readiness(case):
    """C10 — first match wins, evaluated strictly top to bottom."""
    if case["status"] in ("SCHEDULED", "IN_PROGRESS") and case.get("blocked_reservation_count", 0) > 0:
        return "BLOCKED_RESERVATION"
    records = considered_records(case)
    if any(r["status"] in ("DOCUMENTED", "AMENDED") for r in records):
        return "BLOCKED_DOCUMENTATION"
    for record in records:
        if any(s["status"] in ("REQUIRED", "REJECTED") for s in submissions_of_record(record["id"])):
            return "BLOCKED_REGISTRY"
    for record in records:
        if any(
            c["status"] in ("DRAFT", "POSTED", "CORRECTION_REQUIRED")
            for c in charges_of_record(record["id"])
        ):
            return "BLOCKED_CHARGE"
    return "READY"


def case_close_readiness(case):
    if case is None:
        return
    case["readiness_status"] = compute_readiness(case)
    touch(case)


def readiness_counters(case):
    records = considered_records(case)
    unverified = len([r for r in records if r["status"] in ("DOCUMENTED", "AMENDED")])
    outstanding = 0
    unfinalized = 0
    for record in records:
        outstanding += len(
            [s for s in submissions_of_record(record["id"]) if s["status"] in ("REQUIRED", "REJECTED")]
        )
        unfinalized += len(
            [
                c
                for c in charges_of_record(record["id"])
                if c["status"] in ("DRAFT", "POSTED", "CORRECTION_REQUIRED")
            ]
        )
    return unverified, outstanding, unfinalized


# ------------------------------------------------------- state dimensions
def set_custody(unit, new_state):
    """Move the physical dimension and run the conservation cascade."""
    unit["custody_state"] = new_state
    touch(unit)
    lot = lot_of(unit)
    lot_unit_conservation(lot)
    recompute_catalog_available(catalog_of_unit(unit))


def set_billing(unit, new_state):
    """Move the financial dimension and re-derive the vendor liability."""
    unit["billing_state"] = new_state
    touch(unit)
    vendor_open_consignment_liability(vendor_of_unit(unit))


def detach_reservation(unit, blocked=False):
    """Clear a reservation; a forced detachment blocks the case."""
    case_id = unit.get("reserved_case_id")
    unit["reserved_case_id"] = None
    touch(unit)
    case = db.cases.get(case_id) if case_id else None
    if case is not None:
        if blocked:
            case["blocked_reservation_count"] = case.get("blocked_reservation_count", 0) + 1
            touch(case)
        case_close_readiness(case)
    return case
