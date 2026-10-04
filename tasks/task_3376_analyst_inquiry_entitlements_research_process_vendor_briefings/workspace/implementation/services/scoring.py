"""Allowance ledger, seat counts, entitlement matrix and utilization scoring.

Sources: PRD 2.6, 2.7, 3.1; SCAFFOLD sections 1.1 (Seat/ClientAccount) and 1.3.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db, set_fields

# --- constants (SCAFFOLD 1.3 research_utilization_score) --------------------
ACTIVATION_WEIGHT = Decimal("40")
USAGE_WEIGHT = Decimal("35")
RETENTION_WEIGHT = Decimal("25")
ACTIVATION_TARGET_RATE = Decimal("0.80")
USAGE_TARGET_RATE = Decimal("0.70")
RETENTION_TARGET_RATE = Decimal("0.95")
AT_RISK_CEILING = Decimal("40")
WATCH_CEILING = Decimal("70")

SEAT_STATUSES = ("PROVISIONED", "ACTIVE", "REVOKED")

# Role -> base entitlement document types (PRD 3.1).
ROLE_ENTITLEMENTS = {
    "EXECUTIVE_VIEWER": ["MARKET_GUIDE"],
    "PRACTITIONER": ["MARKET_GUIDE", "COMPARATIVE_MATRIX", "HYPE_PROFILE"],
    "ARCHITECT": [
        "MARKET_GUIDE",
        "COMPARATIVE_MATRIX",
        "HYPE_PROFILE",
        "CRITICAL_CAPABILITIES",
    ],
    "STRATEGIST": ["MARKET_GUIDE", "COMPARATIVE_MATRIX", "CRITICAL_CAPABILITIES"],
}


def q2(value):
    """Round half up to 2 decimal places."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def as_number(value):
    """Decimal -> JSON number (2dp values round-trip exactly)."""
    return float(value)


def entitlement_types(research_role, overrides):
    types = list(ROLE_ENTITLEMENTS.get(research_role, []))
    for extra in overrides or []:
        if extra not in types:
            types.append(extra)
    return types


def seats_of(account_id):
    return [s for s in db.seats.values() if s.get("client_account_id") == account_id]


def inquiries_of(account_id):
    seat_ids = {s["id"] for s in seats_of(account_id)}
    return [q for q in db.inquiries.values() if q.get("seat_id") in seat_ids]


def seat_counts(account_id):
    counts = {status: 0 for status in SEAT_STATUSES}
    for seat in seats_of(account_id):
        status = seat.get("status")
        if status in counts:
            counts[status] += 1
    return counts


def ledger_units(account_id):
    """consumed / reserved aggregates (PRD 2.6)."""
    consumed = 0
    reserved = 0
    for inquiry in inquiries_of(account_id):
        status = inquiry.get("status")
        if status in ("COMPLETED", "NO_SHOW"):
            consumed += 1
        elif status == "CANCELLED" and inquiry.get("units_consumed") == 1:
            consumed += 1
        elif status in ("SCHEDULED", "IN_PREP"):
            reserved += 1
    return consumed, reserved


def posture_for(score):
    if score < AT_RISK_CEILING:
        return "AT_RISK"
    if score < WATCH_CEILING:
        return "WATCH"
    return "HEALTHY"


def _score(account, active_count, revoked_count, consumed, denominator):
    contracted = account.get("seat_count_contracted", 0)
    if contracted == 0:
        return Decimal("0.00")
    activation = ACTIVATION_WEIGHT * min(
        Decimal("1"),
        Decimal(active_count) / (ACTIVATION_TARGET_RATE * Decimal(contracted)),
    )
    if denominator == 0:
        usage = Decimal("0")
    else:
        usage = USAGE_WEIGHT * min(
            Decimal("1"), Decimal(consumed) / (USAGE_TARGET_RATE * Decimal(denominator))
        )
    retention = RETENTION_WEIGHT * min(
        Decimal("1"),
        (Decimal("1") - Decimal(revoked_count) / Decimal(contracted))
        / RETENTION_TARGET_RATE,
    )
    return q2(activation + usage + retention)


def seat_weighted_score(account):
    counts = seat_counts(account["id"])
    consumed, _ = ledger_units(account["id"])
    return _score(
        account,
        counts["ACTIVE"],
        counts["REVOKED"],
        consumed,
        Decimal(account.get("inquiry_allowance_total", 0)),
    )


def active_weighted_score(account):
    counts = seat_counts(account["id"])
    if counts["ACTIVE"] == 0:
        return Decimal("0.00")
    contracted = account.get("seat_count_contracted", 0)
    if contracted == 0:
        return Decimal("0.00")
    denominator = q2(
        Decimal(account.get("inquiry_allowance_total", 0))
        * Decimal(counts["ACTIVE"])
        / Decimal(contracted)
    )
    consumed, _ = ledger_units(account["id"])
    return _score(account, counts["ACTIVE"], counts["REVOKED"], consumed, denominator)


def apply_derived(account):
    """Recompute counts, both ledger remainders and both utilization variants.

    Returns True when at least one stored value changed (PRD 2.10: a
    recomputation that changes a field refreshes updated_at / version).
    """
    counts = seat_counts(account["id"])
    consumed, reserved = ledger_units(account["id"])
    allowance = account.get("inquiry_allowance_total", 0)
    score = seat_weighted_score(account)
    active_score = active_weighted_score(account)
    changed = set_fields(
        account,
        active_seat_count=counts["ACTIVE"],
        provisioned_seat_count=counts["PROVISIONED"],
        revoked_seat_count=counts["REVOKED"],
        consumed_inquiry_units=consumed,
        reserved_inquiry_units=reserved,
        remaining_consumed_units=allowance - consumed,
        remaining_reserved_units=allowance - consumed - reserved,
        utilization_score=as_number(score),
        utilization_score_active_weighted=as_number(active_score),
        renewal_posture=posture_for(score),
    )
    return changed


def refresh_account(account):
    """apply_derived + version/updated_at bump when something moved."""
    if apply_derived(account):
        db.touch(account)
    return account
