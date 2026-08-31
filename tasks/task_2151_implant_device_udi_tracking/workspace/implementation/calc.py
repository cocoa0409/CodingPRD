"""Calculation rules C1-C9 (PRD 3.4-3.11).  All money is integer cents.

`round_half_up` rounds a Decimal to a whole cent with ties away from zero.
Rounding ORDER is pinned everywhere it could plausibly be reordered.
"""
from decimal import Decimal, ROUND_HALF_UP

from graph import (
    catalog_of_unit,
    lot_of,
    record_of_submission,
    units_of_catalog,
)
from store import clock_dt, db, expiry_instant, ordered, parse_iso

# ------------------------------------------------------------------ constants
MARKUP_TIER_1_UPPER_CENTS = 50000
MARKUP_TIER_2_UPPER_CENTS = 250000
MARKUP_TIER_3_UPPER_CENTS = 1000000
MARKUP_PCT_TIER_1 = Decimal("0.60")
MARKUP_PCT_TIER_2 = Decimal("0.45")
MARKUP_PCT_TIER_3 = Decimal("0.32")
MARKUP_PCT_TIER_4 = Decimal("0.22")
HIGH_COST_MARKUP_CAP_CENTS = 750000
HIGH_COST_VARIANCE_THRESHOLD_CENTS = 25000

BPS_SCALE = 10000

VERIFY_TURNAROUND_HOURS = 72
RECALLED_LOT_PENALTY = 20
REGISTRY_MIN_COMPLETENESS_SCORE = 80
REGISTRY_DEADLINE_DAYS = 30

CLASS_NOTICE_DAYS = {"CLASS_I": 7, "CLASS_II": 30, "CLASS_III": 90}
NOTIFICATION_ESCALATION_LIMIT = 2

CREDIT_TIER_1_UPPER_CENTS = 500000
CREDIT_TIER_2_UPPER_CENTS = 2500000
CREDIT_CAP_PCT_TIER_1 = Decimal("0.20")
CREDIT_CAP_PCT_TIER_2 = Decimal("0.35")
CREDIT_CAP_PCT_TIER_3 = Decimal("0.50")

RETURN_TIER_1_DAYS = 30
RETURN_TIER_2_DAYS = 180
RETURN_PCT_TIER_1 = Decimal("1.00")
RETURN_PCT_TIER_2 = Decimal("0.75")
RETURN_PCT_TIER_3 = Decimal("0.50")

ROTATION_WINDOW_DAYS = 45
PATIENT_RECOVERY_BUFFER_MINUTES = 120

# custody buckets (PRD 2.11) — the ten states partition into exactly two
ON_HAND_CUSTODY = ("QUARANTINED", "AVAILABLE", "RESERVED", "RECALL_HOLD")
CONSUMED_CUSTODY = (
    "IMPLANTED",
    "EXPLANTED",
    "WASTED",
    "EXPIRED",
    "RETURNED_TO_VENDOR",
    "DISPOSED",
)


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------- C1
def markup_pct(base_cents):
    if base_cents < MARKUP_TIER_1_UPPER_CENTS:
        return MARKUP_PCT_TIER_1
    if base_cents < MARKUP_TIER_2_UPPER_CENTS:
        return MARKUP_PCT_TIER_2
    if base_cents < MARKUP_TIER_3_UPPER_CENTS:
        return MARKUP_PCT_TIER_3
    return MARKUP_PCT_TIER_4


def implant_charge_amount(base_cents, quantity, category):
    """C1 — the shared four-step pricing ladder.

    The per-unit amount is rounded to a whole cent FIRST and only then
    multiplied by quantity; the high-cost cap is applied AFTER that multiply.
    """
    pct = markup_pct(base_cents)
    unit_cents = round_half_up(Decimal(base_cents) * (Decimal(1) + pct))
    line_cents = unit_cents * quantity
    if category == "HIGH_COST_IMPLANT":
        line_cents = min(line_cents, base_cents + HIGH_COST_MARKUP_CAP_CENTS)
    return line_cents


# --------------------------------------------------------------------- C2
def consignment_expected_total(invoice, agreement):
    """C2 — expected total, variance and basis points at invoice match."""
    variant = agreement["reconciliation_method"]
    invoice_units = ordered(
        [u for u in db.device_units.values() if u.get("vendor_invoice_id") == invoice["id"]]
    )

    if variant == "UNIT_MATCH":
        expected = sum(int(u.get("contract_price_cents") or 0) for u in invoice_units)
    else:
        expected = 0
        seen = []
        for unit in invoice_units:
            item = catalog_of_unit(unit)
            if item is not None and item["id"] not in [i["id"] for i in seen]:
                seen.append(item)
        period_start = parse_iso(agreement["period_start_utc"])
        period_end = parse_iso(agreement["period_end_utc"])
        for item in ordered(seen):
            pool = []
            for candidate in units_of_catalog(item["id"]):
                if candidate.get("consignment_agreement_id") != invoice["consignment_agreement_id"]:
                    continue
                if candidate.get("billing_state") not in ("BILLABLE", "INVOICED", "RECONCILED"):
                    continue
                implanted = parse_iso(candidate.get("implanted_at_utc"))
                if implanted is None:
                    continue
                if period_start is not None and implanted < period_start:
                    continue
                if period_end is not None and implanted > period_end:
                    continue
                pool.append(candidate)
            n_on_invoice = len(
                [u for u in invoice_units if (catalog_of_unit(u) or {}).get("id") == item["id"]]
            )
            if not pool:
                continue
            total = sum(int(u.get("contract_price_cents") or 0) for u in pool)
            avg_cents = round_half_up(Decimal(total) / Decimal(len(pool)))
            expected += avg_cents * n_on_invoice

    variance = int(invoice["submitted_total_cents"]) - expected
    if expected == 0:
        variance_bps = 0 if variance == 0 else BPS_SCALE * 1000
    else:
        variance_bps = round_half_up(
            (Decimal(abs(variance)) * Decimal(BPS_SCALE)) / Decimal(expected)
        )
    return expected, variance, variance_bps, variant


# --------------------------------------------------------------------- C3
def registry_completeness_score(submission):
    """C3 — recomputed from live data on every read and every submit attempt."""
    record = record_of_submission(submission)
    if record is None:
        return 0
    patient = db.patients.get(record.get("patient_id"))
    unit = db.device_units.get(record.get("device_unit_id"))
    lot = lot_of(unit) if unit else None

    score = 0
    di_ok = bool((record.get("udi_di") or "").strip())
    pi_ok = bool((record.get("udi_pi_serial") or "").strip())
    if di_ok and pi_ok:
        score += 30
    elif di_ok or pi_ok:
        score += 15

    if patient is not None and patient.get("registry_consent") == "GRANTED":
        score += 25

    site_ok = bool((record.get("anatomic_site") or "").strip())
    if site_ok and record.get("laterality") != "NOT_APPLICABLE":
        score += 20

    documented = parse_iso(record.get("documented_at_utc"))
    verified = parse_iso(record.get("verified_at_utc"))
    if documented is not None and verified is not None:
        turnaround_hours = int((verified - documented).total_seconds() // 3600)
        if turnaround_hours <= VERIFY_TURNAROUND_HOURS:
            score += 15

    if lot is not None and lot.get("expiration_date"):
        score += 10

    penalty = RECALLED_LOT_PENALTY if (lot is not None and lot.get("status") == "RECALLED") else 0
    return max(0, min(100, score - penalty))


# --------------------------------------------------------------------- C4
def fefo_unit_selection(catalog_item_id, case):
    """C4 — first-expiring-first-out server-side pick.  None when the pool is empty."""
    scheduled_end = parse_iso(case["scheduled_end_utc"])
    candidates = []
    for unit in db.device_units.values():
        if unit.get("custody_state") != "AVAILABLE":
            continue
        if unit.get("reserved_case_id") is not None:
            continue
        lot = lot_of(unit)
        if lot is None or lot.get("status") != "AVAILABLE":
            continue
        if lot.get("catalog_item_id") != catalog_item_id:
            continue
        instant = expiry_instant(lot.get("expiration_date"))
        if instant is None or scheduled_end is None or not instant > scheduled_end:
            continue
        candidates.append(unit)

    if not candidates:
        return None

    def rank(unit):
        lot = lot_of(unit)
        received = parse_iso(lot.get("received_at_utc")) if lot else None
        return (
            lot.get("expiration_date") if lot else "",
            received.timestamp() if received else 0.0,
            unit["created_at"],
            unit["_seq"],
        )

    candidates.sort(key=rank)
    return candidates[0]


# --------------------------------------------------------------------- C5
def unit_in_action_scope(unit, action):
    lot = lot_of(unit)
    if lot is None or lot.get("catalog_item_id") != action.get("catalog_item_id"):
        return False
    scope = action.get("scope_type")
    if scope == "CATALOG":
        return True
    if scope == "LOT":
        return lot.get("lot_number") in (action.get("lot_numbers") or [])
    low = action.get("serial_low")
    high = action.get("serial_high")
    serial = unit.get("udi_serial") or ""
    return low is not None and high is not None and low <= serial <= high


def lot_in_action_scope(lot, action):
    if lot.get("catalog_item_id") != action.get("catalog_item_id"):
        return False
    scope = action.get("scope_type")
    if scope == "CATALOG":
        return True
    if scope == "LOT":
        return lot.get("lot_number") in (action.get("lot_numbers") or [])
    for unit in db.device_units.values():
        if unit.get("lot_id") == lot["id"] and unit_in_action_scope(unit, action):
            return True
    return False


def recall_exposure_cohort(action):
    """C5 — the on-hand cohort and the distinct implanted records in scope."""
    in_scope = [u for u in ordered(db.device_units.values()) if unit_in_action_scope(u, action)]
    on_hand = [u for u in in_scope if u.get("custody_state") in ("QUARANTINED", "AVAILABLE", "RESERVED")]
    implanted_units = {
        u["id"] for u in in_scope if u.get("custody_state") in ("IMPLANTED", "EXPLANTED")
    }
    records = [
        r
        for r in ordered(db.implant_records.values())
        if r.get("device_unit_id") in implanted_units
        and r.get("status") in ("DOCUMENTED", "VERIFIED", "AMENDED", "EXPLANTED")
    ]
    return {
        "in_scope_units": in_scope,
        "on_hand_units": on_hand,
        "implanted_records": records,
        "on_hand_cohort_size": len(on_hand),
        "implanted_cohort_size": len(records),
    }


# --------------------------------------------------------------------- C8
def net_consignment_settlement(invoice):
    """C8 — the settlement waterfall.  The tier is keyed on gross_due only."""
    gross_due = int(invoice.get("expected_total_cents") or 0)
    credit_pool = 0
    for unit in db.device_units.values():
        if unit.get("consignment_agreement_id") != invoice.get("consignment_agreement_id"):
            continue
        if unit.get("billing_state") != "CREDIT_PENDING":
            continue
        credit_pool += int(unit.get("contract_price_cents") or 0)

    if gross_due < CREDIT_TIER_1_UPPER_CENTS:
        cap_pct = CREDIT_CAP_PCT_TIER_1
    elif gross_due < CREDIT_TIER_2_UPPER_CENTS:
        cap_pct = CREDIT_CAP_PCT_TIER_2
    else:
        cap_pct = CREDIT_CAP_PCT_TIER_3

    credit_applied = min(credit_pool, round_half_up(Decimal(gross_due) * cap_pct))
    net_payable = gross_due - credit_applied
    return credit_applied, net_payable


# --------------------------------------------------------------------- C9
def explant_return_credit(unit):
    """C9 — the expected vendor credit, degrading with time in the body."""
    implanted = parse_iso(unit.get("implanted_at_utc"))
    now = clock_dt()
    if implanted is None:
        days = 0
    else:
        days = int((now - implanted).total_seconds() // 86400)
    if days <= RETURN_TIER_1_DAYS:
        pct = RETURN_PCT_TIER_1
    elif days <= RETURN_TIER_2_DAYS:
        pct = RETURN_PCT_TIER_2
    else:
        pct = RETURN_PCT_TIER_3
    basis = unit.get("contract_price_cents")
    basis = int(basis) if basis is not None else 0
    return round_half_up(Decimal(basis) * pct)
