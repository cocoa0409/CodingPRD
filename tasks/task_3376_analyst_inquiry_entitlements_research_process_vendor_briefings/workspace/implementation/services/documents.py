"""Document / inclusion derived state: scores, deadlines, licence fees.

Sources: PRD 2.8, 2.9, 3.5, 3.6, 3.7; SCAFFOLD section 1.3.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db, set_fields
from timeutil import fact_check_due, parse_dt
from services.scoring import q2

# --- licence arithmetic constants (SCAFFOLD 1.3 reprint_license_fee) --------
TIER_BASE_FEE_CENTS = {"NONE": 0, "STANDARD": 250000, "PREMIUM": 600000}
INCLUDED_COPIES = {"NONE": 0, "STANDARD": 500, "PREMIUM": 2000}
OVERAGE_PER_COPY_CENTS = {"NONE": 0, "STANDARD": 900, "PREMIUM": 700}
USE_MULTIPLIER = {
    "NO_USE": Decimal("0.00"),
    "INTERNAL_ONLY": Decimal("0.50"),
    "SOCIAL_SNIPPET": Decimal("0.75"),
    "FULL_REPRINT": Decimal("1.00"),
}
VOLUME_DISCOUNT_HIGH = Decimal("0.15")
VOLUME_DISCOUNT_LOW = Decimal("0.10")
VOLUME_DISCOUNT_LOW_FLOOR_CENTS = 500000
VOLUME_DISCOUNT_HIGH_FLOOR_CENTS = 1000000

LATE_FACT_CHECK_PENALTY = Decimal("0.25")
SCORE_FLOOR = Decimal("0.00")
INCLUSION_SCORE_FLOOR = Decimal("2.50")

OPEN_FACT_CHECK_STATUSES = ("REQUESTED", "VENDOR_RESPONDED", "DISPUTED")
PLACED_STATUSES = ("INCLUDED", "APPEAL_UPHELD")


# --- weighted evaluation score ---------------------------------------------
def weights_sum_ok(rows):
    total = Decimal("0")
    for row in rows:
        total += Decimal(str(row.get("weight_pct")))
    if total == Decimal("1.00"):
        return True
    return abs(total - Decimal("1.00")) < Decimal("0.000000001")


def weighted_total_score(rows):
    """Pinned order: round each dimension, then sum, then round the sum."""
    total = Decimal("0.00")
    for row in rows:
        points = q2(Decimal(str(row.get("weight_pct"))) * Decimal(str(row.get("raw_score"))))
        total += points
    return q2(total)


def reprint_fee_cents(inclusion):
    tier = inclusion.get("reprint_tier", "NONE")
    if tier == "NONE":
        return 0
    used = inclusion.get("reprint_copies_used", 0) or 0
    overage_copies = max(0, used - INCLUDED_COPIES.get(tier, 0))
    pre_discount = TIER_BASE_FEE_CENTS.get(tier, 0) + overage_copies * OVERAGE_PER_COPY_CENTS.get(tier, 0)
    if pre_discount >= VOLUME_DISCOUNT_HIGH_FLOOR_CENTS:
        discount = VOLUME_DISCOUNT_HIGH
    elif pre_discount >= VOLUME_DISCOUNT_LOW_FLOOR_CENTS:
        discount = VOLUME_DISCOUNT_LOW
    else:
        discount = Decimal("0")
    multiplier = USE_MULTIPLIER.get(inclusion.get("permitted_marketing_use", "NO_USE"), Decimal("0"))
    fee = Decimal(pre_discount) * (Decimal("1") - discount) * multiplier
    return int(fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def refresh_reprint_fee(inclusion):
    return set_fields(inclusion, reprint_fee_cents=reprint_fee_cents(inclusion))


# --- inclusion collections --------------------------------------------------
def inclusions_of(document_id):
    return [i for i in db.inclusions.values() if i.get("document_id") == document_id]


def recompute_fact_check_open_count(document):
    count = sum(
        1
        for inc in inclusions_of(document["id"])
        if inc.get("fact_check_status") in OPEN_FACT_CHECK_STATUSES
    )
    return set_fields(document, fact_check_open_count=count)


def recompute_included_vendor_count(document):
    count = sum(
        1 for inc in inclusions_of(document["id"]) if inc.get("inclusion_status") in PLACED_STATUSES
    )
    return set_fields(document, included_vendor_count=count)


# --- fact-check rounds ------------------------------------------------------
def open_fact_check_round(inclusion):
    """NOT_STARTED/anything -> REQUESTED with a fresh deadline (PRD 2.8)."""
    inclusion["fact_check_status"] = "REQUESTED"
    inclusion["fact_check_requested_at"] = db.now()
    inclusion["fact_check_round"] = inclusion.get("fact_check_round", 0) + 1
    inclusion["fact_check_due_utc"] = fact_check_due(db.now())


def fact_check_is_open(inclusion):
    return inclusion.get("fact_check_status") in OPEN_FACT_CHECK_STATUSES


def document_is_published(document):
    return document.get("editorial_status") == "PUBLISHED"


def lead_analyst_conflicted(document, vendor_id):
    analyst = db.analysts.get(document.get("lead_analyst_id"))
    if not analyst:
        return False
    return vendor_id in (analyst.get("conflicted_vendor_ids") or [])


def evaluate_inclusion_lapse(inclusion):
    """REQUESTED -> LAPSED once the clock is strictly past the deadline."""
    if inclusion.get("fact_check_status") != "REQUESTED":
        return False
    due = due_of(inclusion)
    if due is None:
        return False
    if db.now() > due:
        set_fields(inclusion, fact_check_status="LAPSED", fact_check_late=True)
        db.touch(inclusion)
        document = db.documents.get(inclusion.get("document_id"))
        if document is not None:
            if recompute_fact_check_open_count(document):
                db.touch(document)
        return True
    return False


def due_of(inclusion):
    value = inclusion.get("fact_check_due_utc")
    return parse_dt(value) if isinstance(value, str) else value
