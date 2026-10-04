"""Calculation rules — SCAFFOLD §1.3 / PRD §3.2, §3.4, §3.7, §3.9.

Constants (verbatim from the scaffold):
  FT_UG=12.0 HT_UG=6.0 FT_GR=9.0 HT_GR=4.5 CENSUS_OFFSET_DAYS=14
  MAX_CREDIT_HOURS=30 WITHDRAWAL_GRACE_DAYS=180
  DEGREE_BASE_FEE_CENTS=2599 ENROLLMENT_BASE_FEE_CENTS=1599 TRANSCRIPT_FEE_CENTS=0
  RUSH_SURCHARGE_BPS=3333 PREFERRED_DISCOUNT_BPS=2000 QUOTE_TTL_HOURS=48
  ARTIFACT_TTL_HOURS=72 MAX_ACTIVE_TRANSCRIPTS=2 VOLUME_TIER_THRESHOLD=3
  K_ANONYMITY_MIN=10 COMPLETION_LAG_DAYS=730 GRACE_PERIOD_DAYS=14
  STANDING_LOOKBACK_PERIODS=3
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db

FT_UG = Decimal("12.0")
HT_UG = Decimal("6.0")
FT_GR = Decimal("9.0")
HT_GR = Decimal("4.5")
CENSUS_OFFSET_DAYS = 14
MAX_CREDIT_HOURS = 30
WITHDRAWAL_GRACE_DAYS = 180
GRACE_PERIOD_DAYS = 14
STANDING_LOOKBACK_PERIODS = 3
K_ANONYMITY_MIN = 10
COMPLETION_LAG_DAYS = 730
QUOTE_TTL_HOURS = 48
ARTIFACT_TTL_HOURS = 72
MAX_ACTIVE_TRANSCRIPTS = 2
VOLUME_TIER_THRESHOLD = 3
DEGREE_BASE_FEE_CENTS = 2599
ENROLLMENT_BASE_FEE_CENTS = 1599
TRANSCRIPT_FEE_CENTS = 0
RUSH_SURCHARGE_BPS = 3333
PREFERRED_DISCOUNT_BPS = 2000


# ---------------------------------------------------------------------------
# enrollment_status_determination (two variants) + deferment_determination
# ---------------------------------------------------------------------------
def credit_band(career_level, credits):
    if career_level == "UNDERGRAD":
        if credits >= FT_UG:
            return "FULL_TIME"
        if credits >= HT_UG:
            return "HALF_TIME"
        return "LESS_THAN_HALF_TIME"
    # GRADUATE
    if credits >= FT_GR:
        return "FULL_TIME"
    if credits >= HT_GR:
        return "HALF_TIME"
    return "LESS_THAN_HALF_TIME"


def report_status(withdrawal_date, as_of, career_level, credits):
    """as_of_report variant: withdrawal counts once withdrawal_date <= D."""
    if withdrawal_date is not None and withdrawal_date <= as_of:
        return "WITHDRAWN"
    return credit_band(career_level, credits)


def census_status(withdrawal_date, term_start, career_level, credits):
    """as_of_census variant: withdrawal counts only when <= term_start + 14d."""
    census_date = term_start + timedelta(days=CENSUS_OFFSET_DAYS)
    if withdrawal_date is not None and withdrawal_date <= census_date:
        return "WITHDRAWN"
    return credit_band(career_level, credits)


def deferment_status(status_code, withdrawal_date, as_of):
    """Returns (deferment_status, grace_end_date_or_None)."""
    if status_code in ("FULL_TIME", "HALF_TIME"):
        return "DEFERMENT_ELIGIBLE", None
    if status_code == "LESS_THAN_HALF_TIME":
        return "DEFERMENT_INELIGIBLE", None
    if status_code == "WITHDRAWN":
        grace_end = withdrawal_date + timedelta(days=WITHDRAWAL_GRACE_DAYS)
        if as_of < grace_end:
            return "WITHDRAWN_GRACE", grace_end
        return "REPAYMENT_DUE", None
    return "NONE", None


def recompute_entry(entry, as_of):
    """Recompute status_code, census_status_code, deferment_status in place."""
    credits = Decimal(str(entry["credit_hours"]))
    sc = report_status(entry["withdrawal_date"], as_of, entry["career_level"], credits)
    cc = census_status(entry["withdrawal_date"], entry["term_start"], entry["career_level"], credits)
    ds, _grace = deferment_status(sc, entry["withdrawal_date"], as_of)
    entry["status_code"] = sc
    entry["census_status_code"] = cc
    entry["deferment_status"] = ds


# ---------------------------------------------------------------------------
# verification_fee_quote + requester_volume_tier (pinned evaluation order)
# ---------------------------------------------------------------------------
def _round_cents(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fee_quote(product_type, tier, rush):
    base = {
        "DEGREE": DEGREE_BASE_FEE_CENTS,
        "ENROLLMENT": ENROLLMENT_BASE_FEE_CENTS,
        "TRANSCRIPT": TRANSCRIPT_FEE_CENTS,
    }[product_type]
    discount_bps = PREFERRED_DISCOUNT_BPS if tier == "PREFERRED" else 0
    # step 1: round the discounted base FIRST
    discounted_base = _round_cents(Decimal(base) * Decimal(10000 - discount_bps) / Decimal(10000))
    # step 2: rush surcharge on the ROUNDED discounted base, rounded again
    rush_component = (
        _round_cents(Decimal(discounted_base) * Decimal(RUSH_SURCHARGE_BPS) / Decimal(10000))
        if rush
        else 0
    )
    # step 3: sum of already-rounded components
    return discounted_base + rush_component


def _quarter_bounds(now):
    q_start_month = 3 * ((now.month - 1) // 3) + 1
    q_start = datetime(now.year, q_start_month, 1, tzinfo=timezone.utc)
    if q_start_month == 10:
        q_end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        q_end = datetime(now.year, q_start_month + 3, 1, tzinfo=timezone.utc)
    return q_start, q_end


def volume_tier(requester_id, now):
    """PREFERRED iff >= 3 RELEASED requests in the current calendar quarter,
    released strictly before now, excluding the request being quoted."""
    if requester_id is None:
        return "STANDARD"
    q_start, q_end = _quarter_bounds(now)
    count = 0
    for r in db.store.requests.values():
        if (
            r["requester_id"] == requester_id
            and r["status"] == "RELEASED"
            and r["released_at"] is not None
            and q_start <= r["released_at"] < q_end
            and r["released_at"] < now
        ):
            count += 1
    return "PREFERRED" if count >= VOLUME_TIER_THRESHOLD else "STANDARD"


# ---------------------------------------------------------------------------
# compliance_standing — latest 3 CLOSED periods (due DESC, created ASC ties)
# ---------------------------------------------------------------------------
def compliance_standing(institution_id):
    closed = [
        p
        for p in db.store.periods.values()
        if p["institution_id"] == institution_id and p["status"] == "CLOSED"
    ]
    closed.sort(key=lambda p: p["_seq"])  # created_at ASC tiebreak
    closed.sort(key=lambda p: p["submission_due_at"], reverse=True)  # stable
    outcomes = [p["outcome"] for p in closed[:STANDING_LOOKBACK_PERIODS]]
    if "DELINQUENT" in outcomes:
        return "NON_COMPLIANT"
    if "LATE" in outcomes:
        return "WATCH"
    return "COMPLIANT"


# ---------------------------------------------------------------------------
# Privacy directive gating (PRD §3.8): ACTIVE and window covering now
# ---------------------------------------------------------------------------
def directive_active(directive, now):
    return (
        directive["status"] == "ACTIVE"
        and directive["effective_from"] <= now
        and (directive["effective_to"] is None or now < directive["effective_to"])
    )


def has_active_directive(student_id, directive_type, now):
    for d in db.store.directives.values():
        if d["student_id"] == student_id and d["directive_type"] == directive_type and directive_active(d, now):
            return True
    return False


# ---------------------------------------------------------------------------
# research_cohort_metrics (PRD §3.9) — pinned evaluation order
# ---------------------------------------------------------------------------
def round4(numerator, denominator):
    if denominator == 0:
        return 0.0
    return float((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
