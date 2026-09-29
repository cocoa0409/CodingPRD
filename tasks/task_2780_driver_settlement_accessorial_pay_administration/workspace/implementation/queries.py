"""Derived-field computation (PRD section 2.11).

Every derived field is computed from the live store at the moment it is read,
so a response can never show a stale derived value.
"""
import constants
import db


# --- pay packages -----------------------------------------------------------
def components_of(pay_package_id):
    rows = [c for c in db.pay_components.values() if c["pay_package_id"] == pay_package_id]
    return sorted(rows, key=lambda c: (c["sequence"], c["_seq"]))


def component_count(pay_package_id):
    return len([c for c in db.pay_components.values() if c["pay_package_id"] == pay_package_id])


def components_by_type(pay_package_id):
    return {c["component_type"]: c for c in components_of(pay_package_id)}


# --- escrow -----------------------------------------------------------------
def escrow_entries_of(driver_id):
    rows = [t for t in db.escrow_transactions.values() if t["driver_id"] == driver_id]
    return sorted(rows, key=lambda t: (t["created_at"], t["_seq"]))


def escrow_balance(driver_id):
    return sum(t["amount_cents"] for t in db.escrow_transactions.values() if t["driver_id"] == driver_id)


# --- retro corrections ------------------------------------------------------
def corrections_of(driver_id, status=None):
    rows = [
        c
        for c in db.retro_corrections.values()
        if c["driver_id"] == driver_id and (status is None or c["status"] == status)
    ]
    return sorted(rows, key=lambda c: (c["created_at"], c["_seq"]))


def pending_retro_correction_cents(driver_id):
    return sum(c["delta_gross_cents"] for c in corrections_of(driver_id, "PENDING"))


def settlement_hold(driver_id):
    return abs(pending_retro_correction_cents(driver_id)) > constants.RETRO_HOLD_THRESHOLD_CENTS


# --- settlements ------------------------------------------------------------
def settlements_of(driver_id):
    rows = [s for s in db.settlements.values() if s["driver_id"] == driver_id]
    return sorted(rows, key=lambda s: (s["created_at"], s["_seq"]))


def ytd_totals(driver_id):
    gross = 0
    taxable = 0
    per_diem = 0
    for settlement in db.settlements.values():
        if settlement["driver_id"] != driver_id:
            continue
        if settlement["status"] not in ("APPROVED", "PAID"):
            continue
        gross += settlement.get("gross_pay_cents", 0) or 0
        taxable += settlement.get("taxable_wages_cents", 0) or 0
        per_diem += settlement.get("per_diem_non_taxable_cents", 0) or 0
    return gross, taxable, per_diem


def lines_of(settlement_id):
    rows = [l for l in db.settlement_lines.values() if l["settlement_id"] == settlement_id]
    return sorted(rows, key=lambda l: (l["sequence"], l["_seq"]))


def max_line_sequence(settlement_id):
    rows = lines_of(settlement_id)
    if not rows:
        return 0
    return max(l["sequence"] for l in rows)


def line_total(settlement_id, line_types):
    return sum(
        l["amount_cents"] for l in db.settlement_lines.values()
        if l["settlement_id"] == settlement_id and l["line_type"] in line_types
    )


# --- advances ---------------------------------------------------------------
def advance_recovered_cents(advance_id):
    total = 0
    for line in db.settlement_lines.values():
        if line["line_type"] != "ADVANCE_RECOVERY":
            continue
        if line["reference_id"] != advance_id:
            continue
        settlement = db.settlements.get(line["settlement_id"])
        if settlement is None:
            continue
        if settlement["status"] in ("PREPARED", "APPROVED", "PAID"):
            total += line["amount_cents"]
    return total


def advance_outstanding_cents(advance):
    if advance["status"] == "CANCELLED":
        return 0
    return advance["amount_cents"] - advance_recovered_cents(advance["id"])


def driver_advance_outstanding_cents(driver_id):
    total = 0
    for advance in db.advances.values():
        if advance["driver_id"] != driver_id:
            continue
        if advance["status"] not in ("ISSUED", "RECOVERING"):
            continue
        total += advance_outstanding_cents(advance)
    return total


def advances_for_waterfall(driver_id):
    """CASH_ADVANCE bucket first, then FUEL_CARD, each created_at ascending."""
    rows = [
        a
        for a in db.advances.values()
        if a["driver_id"] == driver_id and a["status"] in ("ISSUED", "RECOVERING")
    ]
    bucket_order = {"CASH_ADVANCE": 0, "FUEL_CARD": 1}
    return sorted(
        rows,
        key=lambda a: (bucket_order.get(a["advance_type"], 9), a["created_at"], a["_seq"]),
    )


# --- loads / claims / disputes ----------------------------------------------
def loads_of(driver_id):
    rows = [l for l in db.loads.values() if l["driver_id"] == driver_id]
    return sorted(rows, key=lambda l: (l["created_at"], l["_seq"]))


def claims_of_load(load_id):
    rows = [c for c in db.accessorial_claims.values() if c["load_id"] == load_id]
    return sorted(rows, key=lambda c: (c["created_at"], c["_seq"]))


def claims_of_driver(driver_id):
    rows = [c for c in db.accessorial_claims.values() if c["driver_id"] == driver_id]
    return sorted(rows, key=lambda c: (c["created_at"], c["_seq"]))


def upheld_mileage_dispute(load_id):
    """The most recently upheld MILEAGE dispute on this load, if any."""
    rows = [
        d
        for d in db.disputes.values()
        if d.get("load_id") == load_id
        and d["dispute_kind"] == "MILEAGE"
        and d["status"] == "UPHELD"
    ]
    if not rows:
        return None
    return sorted(rows, key=lambda d: (d["created_at"], d["_seq"]))[-1]
