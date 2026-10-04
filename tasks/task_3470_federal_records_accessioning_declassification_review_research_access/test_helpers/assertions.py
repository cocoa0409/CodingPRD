"""Entity assertions and domain expected-value calculators.

The ``assert_<entity>(data)`` functions check envelope-independent field shape:
identity fields, timestamps, PRD-exact field names, and enum membership.  The
``expected_*`` calculators encode the PRD's arithmetic exactly once, so tests
compare server output against an independent recomputation rather than a
hand-typed number.  ``expected_fee_cents`` follows the canonical PRD §3.8
order: per-tier academic discount with round-half-up, sum, then the rush
multiplier with round-half-up.
"""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as C


# ─── Common-field assertions (PRD §2.5) ──────────────────────────────────────
def assert_common_fields(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_agency(data):
    assert_common_fields(data)
    assert isinstance(data["agency_code"], str) and data["agency_code"]
    assert isinstance(data["name"], str) and data["name"]


def assert_schedule(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("agency_id", ""))
    assert isinstance(data["schedule_number"], str) and data["schedule_number"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["records_domain"] in C.RECORDS_DOMAINS
    assert data["disposition"] in C.DISPOSITIONS
    if data["disposition"] == "PERMANENT":
        lag = data["transfer_lag_years"]
        assert isinstance(lag, int) and C.TRANSFER_LAG_YEARS_MIN <= lag <= C.TRANSFER_LAG_YEARS_MAX
    assert data["classification_default"] in C.CLASSIFICATION_LEVELS
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPRAISED", "APPROVED", "RETURNED"]


def assert_transfer(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("schedule_id", ""))
    assert is_valid_uuid(data.get("agency_id", ""))
    assert data["transfer_method"] in C.TRANSFER_METHODS
    assert data["metadata_standard"] in C.METADATA_STANDARDS
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 1
    assert isinstance(data.get("records_cutoff_date"), str)
    assert data["status"] in ["INITIATED", "VALIDATED", "DEFICIENT", "ACCESSIONED", "WITHDRAWN"]
    assert isinstance(data.get("submitted_metadata_elements", []), list)
    assert isinstance(data.get("last_missing_elements", []), list)


def assert_collection(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("transfer_id", ""))
    assert is_valid_uuid(data.get("schedule_id", ""))
    assert is_valid_uuid(data.get("agency_id", ""))
    assert data["records_domain"] in C.RECORDS_DOMAINS
    assert data["classification_level"] in C.CLASSIFICATION_LEVELS
    assert isinstance(data["units_total"], int) and data["units_total"] >= 1
    assert data["processing_status"] in ["UNPROCESSED", "PROCESSING", "DESCRIBED", "PUBLISHED"]
    assert data["restriction_posture"] in [
        "PUBLIC", "CLASSIFIED_REVIEW_REQUIRED", "PRESIDENTIAL_HOLD",
    ]
    assert isinstance(data["backlog_score"], int)
    assert isinstance(data["pull_count_total"], int) and data["pull_count_total"] >= 0
    assert isinstance(data["repro_pages_fulfilled"], int) and data["repro_pages_fulfilled"] >= 0
    assert isinstance(data["foia_release_count"], int) and data["foia_release_count"] >= 0
    assert data["digitization_status"] in ["NOT_REQUESTED", "QUEUED", "DIGITIZED"]
    assert data["declass_outcome"] in ["NONE", "DECLASSIFIED", "PARTIAL", "EXEMPT_RETAINED"]


def assert_declass_review(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("collection_id", ""))
    assert data["review_type"] in ["SYSTEMATIC", "MANDATORY"]
    assert data["status"] in ["OPEN", "IN_PROGRESS", "COMPLETED"]
    if data["review_type"] == "MANDATORY":
        assert is_valid_uuid(data.get("requester_researcher_id", ""))
    assert isinstance(data.get("exemption_codes", []), list)


def assert_equity_referral(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("review_id", ""))
    assert is_valid_uuid(data.get("agency_id", ""))
    assert is_iso8601_timestamp(data.get("sent_at", ""))
    assert is_iso8601_timestamp(data.get("response_due_at", ""))
    assert data["status"] in ["SENT", "RESPONDED"]


def assert_researcher(data):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["affiliation"] in C.AFFILIATIONS
    assert isinstance(data["id_document"], str) and data["id_document"]
    assert data["status"] in ["PENDING", "ACTIVE", "SUSPENDED", "EXPIRED"]


def assert_pull_request(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("researcher_id", ""))
    assert is_valid_uuid(data.get("collection_id", ""))
    assert isinstance(data["unit_start"], int) and data["unit_start"] >= 1
    assert isinstance(data["unit_end"], int) and data["unit_end"] >= data["unit_start"]
    assert isinstance(data.get("visit_date"), str)
    assert data["status"] in ["REQUESTED", "PULLED", "RETURNED", "CANCELLED"]
    assert isinstance(data.get("due_back_at"), str)
    assert isinstance(data.get("late_return", False), bool)


def assert_reproduction_request(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("researcher_id", ""))
    assert is_valid_uuid(data.get("collection_id", ""))
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1
    assert data["format"] in C.REPRO_FORMATS
    assert isinstance(data.get("rush", False), bool)
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in ["QUOTED", "PAID", "FULFILLED", "CANCELLED"]


def assert_foia_request(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("researcher_id", ""))
    assert is_valid_uuid(data.get("collection_id", ""))
    assert isinstance(data["description_of_records"], str) and data["description_of_records"]
    assert data["status"] in [
        "RECEIVED", "IN_REVIEW", "GRANTED", "PARTIAL_GRANT", "DENIED",
        "APPEALED", "APPEAL_GRANTED", "APPEAL_UPHELD", "CLOSED",
    ]
    assert isinstance(data.get("claimed_exemptions", []), list)
    for code in data.get("claimed_exemptions", []):
        assert code in C.FOIA_EXEMPTION_CODES
    assert isinstance(data.get("remand_count", 0), int) and data.get("remand_count", 0) >= 0


def assert_presidential_restriction(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("collection_id", ""))
    assert data["category"] in C.RESTRICTION_CATEGORIES
    assert data["status"] in ["IMPOSED", "NOTIFIED", "RELEASED"]


# ─── Timestamp comparison helpers ────────────────────────────────────────────
_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value):
    """Render an ISO 8601 UTC instant with exactly three fractional digits.

    PRD §2.2 promises timestamps with three fractional digits; expected
    instants are normalised through this before comparison so a server
    rendering the same instant at a different fractional width compares on
    value rather than on spelling.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:6]
    frac = (frac + "000")[:3]
    tz = match.group("tz")
    if tz in ("Z", "z"):
        suffix = "Z"
    else:
        suffix = tz.replace(":", "")
        suffix = "{0}:{1}".format(suffix[:3], suffix[3:])
    return "{0}T{1}.{2}{3}".format(
        match.group("date"), match.group("time"), frac, suffix
    )


def same_instant(left, right):
    """True when two ISO 8601 renderings denote the same UTC instant."""
    return canonical_instant(left) == canonical_instant(right)


# ─── Domain expected-value calculators (PRD §2.9, §3.3, §3.4, §3.8) ──────────
def expected_records_age_years(clock_iso, cutoff_iso):
    """Whole-year age under the PRD §2.9 anniversary rule.

    Age = clock.year - cutoff.year, minus one when the clock's month-day has
    not yet reached the cutoff's month-day.  A February 29 cutoff observes its
    anniversary on February 28 in non-leap clock years.
    """
    clock_d = date.fromisoformat(clock_iso[:10])
    cutoff_d = date.fromisoformat(cutoff_iso[:10])
    cutoff_month, cutoff_day = cutoff_d.month, cutoff_d.day
    if cutoff_month == 2 and cutoff_day == 29 and not _is_leap(clock_d.year):
        cutoff_day = 28
    years = clock_d.year - cutoff_d.year
    if (clock_d.month, clock_d.day) < (cutoff_month, cutoff_day):
        years -= 1
    return years


def _is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def expected_fee_cents(page_count, affiliation, rush=False):
    """PRD §3.8 fee in integer cents, canonical order.

    Per tier: subtotal = pages_in_tier * tier rate.  For ACADEMIC, each tier's
    subtotal is multiplied by 0.85 and rounded half up BEFORE summing; the
    discounted tiers are summed; then a rush request multiplies the sum by 1.5
    with round half up.  No other affiliation discounts; format selects no
    rate.
    """
    tier1_pages = min(page_count, C.FEE_TIER1_PAGES)
    tier2_pages = min(max(page_count - C.FEE_TIER1_PAGES, 0), C.FEE_TIER2_PAGES)
    tier3_pages = max(page_count - C.FEE_TIER1_PAGES - C.FEE_TIER2_PAGES, 0)
    tier_cents = [
        tier1_pages * C.FEE_TIER1_RATE_CENTS,
        tier2_pages * C.FEE_TIER2_RATE_CENTS,
        tier3_pages * C.FEE_TIER3_RATE_CENTS,
    ]
    if affiliation == "ACADEMIC":
        rate = Decimal(str(C.ACADEMIC_DISCOUNT_RATE))
        discounted = sum(
            int((Decimal(t) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            for t in tier_cents
        )
    else:
        discounted = sum(tier_cents)
    if rush:
        mult = Decimal(str(C.RUSH_MULTIPLIER))
        return int(
            (Decimal(discounted) * mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    return discounted


def expected_backlog_score(clock_iso, records_cutoff_date, classification_level, records_domain):
    """PRD §3.3 backlog score snapshot at accession."""
    age = expected_records_age_years(clock_iso, records_cutoff_date)
    return (
        C.BACKLOG_AGE_POINTS_PER_YEAR * min(age, C.BACKLOG_AGE_CAP_YEARS)
        + C.BACKLOG_CLASSIFICATION_WEIGHTS[classification_level]
        + (C.BACKLOG_PRESIDENTIAL_BONUS if records_domain == "PRESIDENTIAL" else 0)
    )


def expected_digitization_priority(
    clock_iso,
    records_cutoff_date,
    pull_count_total=0,
    repro_pages_fulfilled=0,
    foia_release_count=0,
    declass_outcome="NONE",
):
    """PRD §3.4 demand-weighted digitization priority."""
    age = expected_records_age_years(clock_iso, records_cutoff_date)
    return (
        C.DIGI_AGE_POINTS_PER_YEAR * min(age, C.DIGI_AGE_CAP_YEARS)
        + C.DIGI_PULL_POINTS * min(pull_count_total, C.DIGI_PULL_CAP)
        + C.DIGI_FOIA_POINTS * min(foia_release_count, C.DIGI_FOIA_CAP)
        + min(repro_pages_fulfilled, C.DIGI_REPRO_PAGES_CAP) // C.DIGI_REPRO_PAGES_DIVISOR
        + (C.DIGI_DECLASSIFIED_BONUS if declass_outcome == "DECLASSIFIED" else 0)
    )


def expected_restriction_posture(classification_level, has_live_presidential_restriction=False):
    """PRD §2.8 derivation order: live restriction, then classification, else PUBLIC."""
    if has_live_presidential_restriction:
        return "PRESIDENTIAL_HOLD"
    if classification_level != "NONE":
        return "CLASSIFIED_REVIEW_REQUIRED"
    return "PUBLIC"
