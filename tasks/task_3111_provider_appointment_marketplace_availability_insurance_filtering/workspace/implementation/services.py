"""Business logic: state transitions, cascades, booking, billing, reliability, audits."""

from datetime import timedelta
from decimal import Decimal

from core import (
    DB, ApiError, rescore, recompute_bookable, recompute_practice_providers,
    round_half_up_cents, new_resource, touch, parse_iso, fmt_iso,
)

FEE_PCT = Decimal("0.15")
PROCESSING_PCT = Decimal("0.029")
PROCESSING_FLAT_CENTS = 30
NO_SHOW_MAGNITUDE = 25
LATE_CANCEL_MAGNITUDE = 15
GATE_THRESHOLD = 50
ATTRIBUTION_WINDOW_DAYS = 90
SAMPLE_CAP = 20
WARN_THRESHOLD = 0.05
CRITICAL_THRESHOLD = 0.20


# ---------------------------------------------------------------------------
# Provider suspension / delist cascades
# ---------------------------------------------------------------------------

def close_future_open_slots(provider_id, reason):
    now = DB.clock.now()
    for slot in DB.slots.values():
        if (
            slot["provider_id"] == provider_id
            and slot["status"] == "OPEN"
            and parse_iso(slot["start_at"]) > now
        ):
            slot["status"] = "CLOSED"
            slot["close_reason"] = reason
            touch(slot)


def provider_suspend_cascade(provider):
    """ACTIVE -> SUSPENDED with slot cascade (used by endpoint and auto-suspension)."""
    provider["status"] = "SUSPENDED"
    close_future_open_slots(provider["id"], "PROVIDER_SUSPENDED")
    recompute_bookable(provider)
    touch(provider)


def provider_delist_cascade(provider):
    """-> DELISTED with slot cascade (used by endpoint and practice-delist cascade)."""
    provider["status"] = "DELISTED"
    close_future_open_slots(provider["id"], "PROVIDER_SUSPENDED")
    recompute_bookable(provider)
    touch(provider)


def practice_delist_cascade(practice):
    practice["status"] = "DELISTED"
    touch(practice)
    for provider in DB.providers.values():
        if provider["practice_id"] == practice["id"] and provider["status"] in ("ACTIVE", "SUSPENDED"):
            provider_delist_cascade(provider)
    recompute_practice_providers(practice["id"])


# ---------------------------------------------------------------------------
# Reliability-gate cascade
# ---------------------------------------------------------------------------

def reliability_gate_cascade(patient, exclude_booking_id=None):
    """Cancel every other CONFIRMED future booking when score < 50."""
    if patient["reliability_score"] >= GATE_THRESHOLD:
        return
    now = DB.clock.now()
    for booking in DB.bookings.values():
        if (
            booking["patient_id"] == patient["id"]
            and booking["id"] != exclude_booking_id
            and booking["status"] == "CONFIRMED"
            and parse_iso(booking["start_at"]) > now
        ):
            booking["status"] = "CANCELLED"
            booking["cancel_reason"] = "RELIABILITY_GATE"
            touch(booking)
            slot = DB.slots.get(booking["slot_id"])
            if slot is not None and slot["status"] == "BOOKED":
                slot["status"] = "OPEN"
                slot["current_booking_id"] = None
                touch(slot)


# ---------------------------------------------------------------------------
# Slot overlap
# ---------------------------------------------------------------------------

def slot_overlaps(provider_id, start_dt, end_dt):
    for slot in DB.slots.values():
        if slot["provider_id"] != provider_id:
            continue
        if slot["status"] not in ("OPEN", "BOOKED"):
            continue
        s = parse_iso(slot["start_at"])
        e = parse_iso(slot["end_at"])
        if start_dt < e and s < end_dt:
            return True
    return False


# ---------------------------------------------------------------------------
# Insurance acceptance
# ---------------------------------------------------------------------------

def plan_accepted(provider_id, plan_id):
    now = DB.clock.now()
    for att in DB.attestations.values():
        if (
            att["provider_id"] == provider_id
            and att["plan_id"] == plan_id
            and att["status"] == "VERIFIED"
            and parse_iso(att["effective_from"]) <= now < parse_iso(att["effective_to"])
        ):
            return True
    return False


def select_verified_attestation(provider_id, plan_id):
    """Earliest created_at VERIFIED attestation for (provider, plan), regardless of window."""
    candidates = [
        a for a in DB.attestations.values()
        if a["provider_id"] == provider_id and a["plan_id"] == plan_id and a["status"] == "VERIFIED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["_created_at_dt"], a["_seq"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------

def compute_attribution(patient_id, practice_id, provider_id, booking_created_dt):
    window_start = booking_created_dt - timedelta(days=ATTRIBUTION_WINDOW_DAYS)
    for ev in DB.contact_events.values():
        if ev["patient_id"] != patient_id:
            continue
        if ev["practice_id"] != practice_id and ev.get("provider_id") != provider_id:
            continue
        contacted = parse_iso(ev["contacted_at"])
        if window_start <= contacted < booking_created_dt:
            return "ORGANIC"
    return "ATTRIBUTED"


# ---------------------------------------------------------------------------
# Fee split
# ---------------------------------------------------------------------------

def create_charge(booking, practice):
    gross = booking["booked_copay_cents"]
    fee = round_half_up_cents(Decimal(gross) * FEE_PCT)
    processing = round_half_up_cents(Decimal(gross) * PROCESSING_PCT) + PROCESSING_FLAT_CENTS
    net = gross - fee - processing
    charge = new_resource(DB.next_seq(), common=True)
    charge.update({
        "booking_id": booking["id"],
        "practice_id": booking["practice_id"],
        "invoice_id": None,
        "gross_cents": gross,
        "marketplace_fee_cents": fee,
        "processing_cents": processing,
        "net_to_practice_cents": net,
        "status": "BILLABLE",
    })
    DB.charges[charge["id"]] = charge
    return charge


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def append_ledger(invoice_id, entry_type, amount_cents, charge_id=None, note=None):
    entry = new_resource(DB.next_seq(), common=False)
    entry.update({
        "invoice_id": invoice_id,
        "charge_id": charge_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "note": note,
    })
    DB.ledger_entries[entry["id"]] = entry
    return entry


def recompute_amount_due(invoice):
    total = sum(
        e["amount_cents"] for e in DB.ledger_entries.values() if e["invoice_id"] == invoice["id"]
    )
    invoice["amount_due_cents"] = total
    return total


# ---------------------------------------------------------------------------
# Invoice generation (sweep)
# ---------------------------------------------------------------------------

def period_bounds(period):
    """period 'YYYY-MM' -> (start_dt inclusive, end_dt exclusive) in UTC."""
    year, month = int(period[:4]), int(period[5:7])
    start = parse_iso(f"{year:04d}-{month:02d}-01T00:00:00Z")
    if month == 12:
        end = parse_iso(f"{year + 1:04d}-01-01T00:00:00Z")
    else:
        end = parse_iso(f"{year:04d}-{month + 1:02d}-01T00:00:00Z")
    return start, end


def generate_invoice(practice, period):
    invoice = new_resource(DB.next_seq(), common=True)
    invoice.update({
        "practice_id": practice["id"],
        "period": period,
        "charge_count": 0,
        "fee_total_cents": 0,
        "discount_tier": 0,
        "discount_cents": 0,
        "amount_due_cents": 0,
        "payout_provisional_cents": 0,
        "payout_final_cents": 0,
        "status": "ISSUED",
    })
    DB.invoices[invoice["id"]] = invoice

    if practice["billing_mode"] == "SUBSCRIPTION":
        append_ledger(invoice["id"], "SUBSCRIPTION_FEE", practice["subscription_fee_cents"])
        recompute_amount_due(invoice)
        return invoice

    start, end = period_bounds(period)
    swept = []
    for charge in DB.charges.values():
        if charge["practice_id"] != practice["id"] or charge["status"] != "BILLABLE":
            continue
        booking = DB.bookings.get(charge["booking_id"])
        if booking is None:
            continue
        created = parse_iso(booking["created_at"])
        if start <= created < end:
            swept.append(charge)
    swept.sort(key=lambda c: (c["_created_at_dt"], c["_seq"]))

    charge_count = len(swept)
    fee_total = sum(c["marketplace_fee_cents"] for c in swept)
    if charge_count >= 21:
        tier = 0.20
    elif charge_count >= 11:
        tier = 0.10
    else:
        tier = 0.00
    discount = round_half_up_cents(Decimal(fee_total) * Decimal(str(tier)))

    for charge in swept:
        charge["status"] = "INVOICED"
        charge["invoice_id"] = invoice["id"]
        touch(charge)
        append_ledger(invoice["id"], "CHARGE_FEE", charge["marketplace_fee_cents"], charge_id=charge["id"])
    if discount > 0:
        append_ledger(invoice["id"], "TIER_DISCOUNT", -discount)

    invoice["charge_count"] = charge_count
    invoice["fee_total_cents"] = fee_total
    invoice["discount_tier"] = tier
    invoice["discount_cents"] = discount
    recompute_amount_due(invoice)

    provisional = sum(c["net_to_practice_cents"] for c in swept)
    gross_total = sum(c["gross_cents"] for c in swept)
    processing_total = sum(c["processing_cents"] for c in swept)
    invoice["payout_provisional_cents"] = provisional
    invoice["payout_final_cents"] = gross_total - invoice["amount_due_cents"] - processing_total
    return invoice


# ---------------------------------------------------------------------------
# Audit sweep
# ---------------------------------------------------------------------------

def run_audit(case):
    provider_id = case["provider_id"]
    now = DB.clock.now()

    slots = sorted(
        [s for s in DB.slots.values() if s["provider_id"] == provider_id],
        key=lambda s: (s["_created_at_dt"], s["_seq"]),
    )
    atts = sorted(
        [a for a in DB.attestations.values() if a["provider_id"] == provider_id],
        key=lambda a: (a["_created_at_dt"], a["_seq"]),
    )

    scope = case["scope"]
    if scope == "AVAILABILITY":
        items = [("slot", s) for s in slots]
    elif scope == "INSURANCE":
        items = [("attestation", a) for a in atts]
    else:  # FULL
        items = [("slot", s) for s in slots] + [("attestation", a) for a in atts]
    items = items[:SAMPLE_CAP]

    findings = []
    for kind, rec in items:
        if kind == "slot":
            if rec["status"] == "OPEN" and parse_iso(rec["start_at"]) < now:
                findings.append({
                    "finding_index": len(findings),
                    "finding_type": "TIME_TRAVEL_SLOT",
                    "ref_id": rec["id"],
                    "resolved": False,
                })
        else:
            if rec["status"] == "VERIFIED" and parse_iso(rec["effective_to"]) <= now:
                findings.append({
                    "finding_index": len(findings),
                    "finding_type": "INSURANCE_STALE",
                    "ref_id": rec["id"],
                    "resolved": False,
                })

    sampled = len(items)
    mismatch = len(findings)
    rate = mismatch / max(1, sampled)
    if rate > CRITICAL_THRESHOLD:
        severity = "CRITICAL"
    elif rate > WARN_THRESHOLD:
        severity = "WARN"
    else:
        severity = "CLEAN"

    # remediation sweep
    for f in findings:
        if f["finding_type"] == "TIME_TRAVEL_SLOT":
            slot = DB.slots.get(f["ref_id"])
            if slot is not None and slot["status"] == "OPEN":
                slot["status"] = "CLOSED"
                slot["close_reason"] = "AUDIT_SWEEP"
                touch(slot)
        else:
            att = DB.attestations.get(f["ref_id"])
            if att is not None and att["status"] == "VERIFIED":
                att["status"] = "EXPIRED"
                touch(att)

    case["sampled_count"] = sampled
    case["mismatch_count"] = mismatch
    case["mismatch_rate"] = rate
    case["severity"] = severity
    case["findings"] = findings
    case["status"] = "CLOSED_CLEAN" if mismatch == 0 else "FINDINGS_OPEN"
    touch(case)
    return case


# ---------------------------------------------------------------------------
# Epoch run
# ---------------------------------------------------------------------------

def run_epoch():
    DB.epoch += 1
    patients_updated = 0
    for patient in DB.patients.values():
        if patient["strikes"]:
            before = (patient["reliability_score"], patient["provisional_score"])
            rescore(patient)
            after = (patient["reliability_score"], patient["provisional_score"])
            if before != after:
                patients_updated += 1
    now = DB.clock.now()
    for att in DB.attestations.values():
        if att["status"] == "VERIFIED" and parse_iso(att["effective_to"]) <= now:
            att["status"] = "EXPIRED"
            touch(att)
    # decayed_strikes: strikes that fell out of the window with this advance
    window_edge = DB.epoch - 3
    decayed = 0
    for patient in DB.patients.values():
        for s in patient["strikes"]:
            if s["epoch"] == window_edge - 1:
                decayed += 1
    return DB.epoch, decayed, patients_updated
