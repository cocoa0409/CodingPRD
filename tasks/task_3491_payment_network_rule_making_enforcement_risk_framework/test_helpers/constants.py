"""Domain thresholds and pure calculation helpers.

Every numeric constant below is taken verbatim from PRD.md (§2.4 logical clock,
§2.6 rounding discipline, §3.4 ballot tally, §3.6 settlement fee, §3.7 return
rates, §3.8 fine schedule, §3.9 attestation due date). The computation helpers
mirror the PRD formulas exactly (integer arithmetic, round-half-up per entry,
integer cross-multiplication for thresholds) so fixtures can target exact
boundaries and assertions can recompute expected values without floats.
"""

import datetime as _dt
from decimal import Decimal, ROUND_HALF_UP

# --- Logical clock (PRD §2.4) -------------------------------------------------

# The server boots with its logical clock at exactly this instant and never
# falls back to wall-clock time.
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Network settlement fee (PRD §3.6) ----------------------------------------

# Raw fee = amount_cents * FEE_NUM / FEE_DEN (five cents per $100,000).
FEE_NUM = 5
FEE_DEN = 10_000_000
MIN_FEE_CENTS = 1
SAME_DAY_SURCHARGE_CENTS = 50

# --- Ballot outcome tally (PRD §3.4) ------------------------------------------

QUORUM_NUM = 1
QUORUM_DEN = 2
APPROVAL_NUM = 2
APPROVAL_DEN = 3

# --- Return-rate thresholds (PRD §3.7) -----------------------------------------

UNAUTH_THRESHOLD_PCT = 10
ADMIN_THRESHOLD_PCT = 20
OVERALL_THRESHOLD_PCT = 25
INQUIRY_RESPONSE_DAYS = 14

# --- Rule pipeline periods (PRD §3.3, §3.4) ------------------------------------

COMMENT_PERIOD_DAYS = 30
BALLOT_PERIOD_DAYS = 14

# --- Account validation lifetime (PRD §3.5) ------------------------------------

VALIDATION_TTL_DAYS = 365

# --- Enforcement fine schedule (PRD §3.8) ---------------------------------------

# Tier bases: $50,000 / $100,000 / $250,000 / $500,000 in cents.
FINE_BASE_BY_TIER_CENTS = (5_000_000, 10_000_000, 25_000_000, 50_000_000)
ESCALATION_TIER_CAP = 3
LATE_GRACE_DAYS = 30
LATE_DAILY_CENTS = 100_000  # $1,000 per calendar day of lateness past grace
STATUTORY_CAP_CENTS = 100_000_000  # $1,000,000 statutory cap
# An UPHELD transition suspends the participant once its cumulative count of
# UPHELD/PAID actions (the one just upheld included) reaches this many.
SUSPENSION_STRIKE_COUNT = 3


# =============================================================================
# Date / clock utilities (logical clock only — never wall-clock)
# =============================================================================


def _split_iso(value):
    """Split an ISO date or datetime string into (date_str, time_str_or_None).

    A trailing "Z" is stripped for parsing and reported via the second
    element's preservation by callers.
    """
    v = value[:-1] if value.endswith("Z") else value
    if "T" in v:
        d, t = v.split("T", 1)
        return d, t
    return v, None


def iso_add_days(value, days):
    """Add calendar days to an ISO date or datetime string.

    Preserves the time component and a trailing "Z" when present.
    Works for "YYYY-MM-DD" and "YYYY-MM-DDTHH:MM:SS[.fff][Z]" inputs.
    """
    date_str, time_str = _split_iso(value)
    new_date = (_dt.date.fromisoformat(date_str) + _dt.timedelta(days=days)).isoformat()
    if time_str is None:
        return new_date
    suffix = "Z" if value.endswith("Z") else ""
    return f"{new_date}T{time_str}{suffix}"


def date_add_days(date_str, days):
    """Add calendar days to a YYYY-MM-DD date string."""
    return (_dt.date.fromisoformat(date_str) + _dt.timedelta(days=days)).isoformat()


def iso_date_of(value):
    """Extract the YYYY-MM-DD date part of an ISO date or datetime string."""
    return _split_iso(value)[0]


def iso_on_date(date_str, time_str="09:00:00"):
    """Build a logical-clock datetime "YYYY-MM-DDTHH:MM:SSZ" from parts."""
    return f"{date_str}T{time_str}Z"


def banking_days_between(start_date, end_date):
    """Count banking days (Mon-Fri, no holiday calendar) in (start_date, end_date].

    This is the PRD §3.7 return-window measure: the count of banking days from
    settled_date to the current logical date. Returns 0 when end <= start.
    """
    start = _dt.date.fromisoformat(iso_date_of(start_date))
    end = _dt.date.fromisoformat(iso_date_of(end_date))
    if end <= start:
        return 0
    count = 0
    day = start
    while day < end:
        day += _dt.timedelta(days=1)
        if day.weekday() < 5:
            count += 1
    return count


def add_banking_days(start_date, n):
    """Return the date n banking days (Mon-Fri) after start_date.

    The latest date on which a return of an entry settled on start_date under a
    return_timeframe_banking_days == n code is still inside the window.
    """
    day = _dt.date.fromisoformat(iso_date_of(start_date))
    remaining = n
    while remaining > 0:
        day += _dt.timedelta(days=1)
        if day.weekday() < 5:
            remaining -= 1
    return day.isoformat()


def compute_validated_until(creation_date):
    """AccountValidation.validated_until = creation date + 365 days (PRD §3.5)."""
    return date_add_days(iso_date_of(creation_date), VALIDATION_TTL_DAYS)


def compute_attestation_due_date(period_year):
    """ComplianceAttestation.due_date = March 1 of period_year + 1 (PRD §3.9)."""
    return f"{period_year + 1}-03-01"


def compute_response_deadline(inquiry_created_at):
    """InquiryCase.response_deadline = creation timestamp + 14 days (PRD §3.7)."""
    return iso_add_days(inquiry_created_at, INQUIRY_RESPONSE_DAYS)


# =============================================================================
# Calculation formulas (mirror the PRD exactly — integer arithmetic only)
# =============================================================================


def round_half_up_cents(numerator, denominator):
    """round_half_up(numerator / denominator) to whole cents, exactly."""
    raw = (Decimal(int(numerator)) * 1) / Decimal(int(denominator))
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_entry_fee_cents(amount_cents, same_day=False):
    """Per-entry network settlement fee (PRD §3.6).

    raw = amount_cents * 5 / 10,000,000, rounded half-up to a whole cent PER
    ENTRY (never summed raw first), with a 1-cent minimum, plus a 50-cent
    surcharge when the entry was flagged same_day.
    """
    fee = max(round_half_up_cents(amount_cents * FEE_NUM, FEE_DEN), MIN_FEE_CENTS)
    if same_day:
        fee += SAME_DAY_SURCHARGE_CENTS
    return fee


def compute_ballot_outcome(eligible_count, yea_count, nay_count, abstain_count):
    """ballot_outcome_tally (PRD §3.4) — exact integer cross-multiplication.

    eligible_count: participants ACTIVE at close time.
    Returns one of "PASSED_QUORUM", "REJECTED_VOTE", "REJECTED_NO_QUORUM".
    """
    cast = yea_count + nay_count + abstain_count
    # quorum: cast >= ceil(eligible * 1/2)  <=>  cast * 2 >= eligible
    if cast * QUORUM_DEN < eligible_count * QUORUM_NUM:
        return "REJECTED_NO_QUORUM"
    non_abstain = yea_count + nay_count
    if non_abstain == 0:
        return "REJECTED_VOTE"
    if yea_count * APPROVAL_DEN >= non_abstain * APPROVAL_NUM:
        return "PASSED_QUORUM"
    return "REJECTED_VOTE"


def is_unauth_breach(forward_count, unauth_return_count):
    """PRD §3.7: true iff forward_count > 0 and unauth * 100 > forward * 10."""
    return forward_count > 0 and unauth_return_count * 100 > forward_count * UNAUTH_THRESHOLD_PCT


def is_admin_breach(forward_count, admin_return_count):
    """PRD §3.7: true iff forward_count > 0 and admin * 100 > forward * 20."""
    return forward_count > 0 and admin_return_count * 100 > forward_count * ADMIN_THRESHOLD_PCT


def is_overall_breach(forward_count, unauth_return_count, admin_return_count, other_return_count):
    """PRD §3.7: true iff forward_count > 0 and total * 100 > forward * 25."""
    total = unauth_return_count + admin_return_count + other_return_count
    return forward_count > 0 and total * 100 > forward_count * OVERALL_THRESHOLD_PCT


def compute_escalation_tier(prior_upheld_or_paid_count):
    """PRD §3.8: min(count of prior UPHELD/PAID actions at creation, 3)."""
    return min(prior_upheld_or_paid_count, ESCALATION_TIER_CAP)


def compute_fine_base_cents(prior_upheld_or_paid_count, participant_type):
    """fine_base_cents at issuance (PRD §3.8).

    BASE_BY_TIER[tier] * multiplier (ODFI 1.0, RDFI 0.5, BOTH 1.5 — all products
    land on whole cents), capped at the $1,000,000 statutory maximum.
    """
    tier = compute_escalation_tier(prior_upheld_or_paid_count)
    base = FINE_BASE_BY_TIER_CENTS[tier]
    if participant_type == "RDFI":
        mult_num, mult_den = 1, 2
    elif participant_type == "BOTH":
        mult_num, mult_den = 3, 2
    else:  # ODFI
        mult_num, mult_den = 1, 1
    return min(base * mult_num // mult_den, STATUTORY_CAP_CENTS)


def compute_fine_total_cents(fine_base_cents, issued_date, paid_date):
    """fine_total_cents computed at the PAID transition (PRD §3.8).

    base + $1,000 per day of lateness beyond the 30-day grace period after
    issued_date (overdue day count floored at zero), capped at $1,000,000.
    """
    days = (
        _dt.date.fromisoformat(iso_date_of(paid_date))
        - _dt.date.fromisoformat(iso_date_of(issued_date))
    ).days
    overdue_days = max(0, days - LATE_GRACE_DAYS)
    return min(fine_base_cents + LATE_DAILY_CENTS * overdue_days, STATUTORY_CAP_CENTS)
