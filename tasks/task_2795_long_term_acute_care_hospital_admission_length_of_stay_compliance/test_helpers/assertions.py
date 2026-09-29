"""
Domain assertions.

These wrap the checks that recur across many tests: that a record carries the four
common properties (or, for the two immutable entities, only the two it should), that a
money field is an exact integer number of cents, that a percentage carries two decimals,
that two timestamps denote the same instant however many fractional digits each side
printed, and that a period's ledger matches a full recompute.

Every helper raises AssertionError naming the field and both values, because a failure
two hundred lines into a cascade scenario is only useful if it says which number moved.
"""

import math
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_ts
from .constants import (
    ANSWERED_QUERY_CREDIT,
    BASE_REFERRAL_THRESHOLD_PCT,
    FIXED_LOSS_AMOUNT_CENTS,
    HIGH_BAND_MIN,
    LOS_EXCESS_WEIGHT,
    MISSING_DISCIPLINE_WEIGHT,
    MODERATE_BAND_MIN,
    OUTLIER_MARGINAL_COST_FACTOR,
    RISK_SCORE_MAX,
    RISK_SCORE_MIN,
    SITE_NEUTRAL_WEIGHT,
    SSO_ALOS_FRACTION,
    SSO_WEIGHT,
    WEANING_GAP_WEIGHT,
)
from .types import COMMON_FIELDS, IMMUTABLE_COMMON_FIELDS, expected_keys

Json = Dict[str, Any]


# ── The common properties ────────────────────────────
def assert_common_fields(record: Json, expected_version: Optional[int] = None) -> None:
    """A mutable record carries an id, two timestamps and an integer version."""
    assert is_valid_uuid(record.get("id")), "id is not a UUID: {!r}".format(record.get("id"))
    assert is_iso8601_timestamp(
        record.get("created_at")
    ), "created_at is not ISO 8601: {!r}".format(record.get("created_at"))
    assert is_iso8601_timestamp(
        record.get("updated_at")
    ), "updated_at is not ISO 8601: {!r}".format(record.get("updated_at"))
    version = record.get("version")
    assert isinstance(version, int) and not isinstance(
        version, bool
    ), "version is not an integer: {!r}".format(version)
    if expected_version is not None:
        assert version == expected_version, "version {} != expected {}".format(
            version, expected_version
        )


def assert_created_record(record: Json) -> None:
    """A freshly created mutable record opens at version 1 with equal timestamps."""
    assert_common_fields(record, expected_version=1)
    assert canonical_ts(record["created_at"]) == canonical_ts(
        record["updated_at"]
    ), "created_at {} and updated_at {} differ on a new record".format(
        record["created_at"], record["updated_at"]
    )


def assert_immutable_record(record: Json) -> None:
    """An immutable record carries only an id and a creation stamp.

    `updated_at` and `version` are absent altogether on these entities, not present and
    null, so this checks for the keys rather than for their values.
    """
    assert is_valid_uuid(record.get("id")), "id is not a UUID: {!r}".format(record.get("id"))
    assert is_iso8601_timestamp(
        record.get("created_at")
    ), "created_at is not ISO 8601: {!r}".format(record.get("created_at"))
    assert "updated_at" not in record, "an immutable record exposed updated_at"
    assert "version" not in record, "an immutable record exposed version"


def assert_exact_keys(record: Json, entity: str) -> None:
    """A read exposes exactly the declared field set of this entity, no more and no less."""
    expected = set(expected_keys(entity))
    actual = set(record.keys())
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    assert not missing, "{} response is missing {}".format(entity, missing)
    assert not extra, "{} response carries undeclared keys {}".format(entity, extra)


def assert_version_is(record: Json, expected: int) -> None:
    assert record.get("version") == expected, "version {} != expected {}".format(
        record.get("version"), expected
    )


# ── Timestamps and the whole-day calendar ────────────
def assert_instant_equals(
    actual: Optional[str], expected: Optional[str], field: str = "timestamp"
) -> None:
    """Compare two ISO 8601 instants at second precision, ignoring digit width."""
    assert canonical_ts(actual) == canonical_ts(
        expected
    ), "{}: {!r} does not denote the same instant as {!r}".format(field, actual, expected)


def assert_stamped_from_clock(record: Json, field: str, clock_reading: str) -> None:
    """A stamped field took its value from the logical clock, not from wall time."""
    assert record.get(field) is not None, "{} was not stamped".format(field)
    assert_instant_equals(record[field], clock_reading, field)


def assert_unset(record: Json, *fields: str) -> None:
    """The named fields are present as null, or absent altogether."""
    for field in fields:
        assert record.get(field) is None, "{} should be unset but is {!r}".format(
            field, record.get(field)
        )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any fractional-second width."""
    text = value.strip().replace("z", "Z")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def day_count(start: str, end: str) -> int:
    """The specification's whole-day count: the difference of the two UTC calendar dates.

    The later day is not counted, so a discharge on the admission date is zero days.
    """
    return (parse_instant(end).date() - parse_instant(start).date()).days


def shift_hours(instant: str, hours: float) -> str:
    """The instant moved by a number of hours, printed with millisecond precision."""
    moved = parse_instant(instant) + timedelta(hours=hours)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(moved.microsecond // 1000)


def shift_seconds(instant: str, seconds: int) -> str:
    """The instant moved by a number of seconds, printed with millisecond precision."""
    return shift_hours(instant, seconds / 3600.0)


def shift_days(instant: str, days: int) -> str:
    """The instant moved by a whole number of days."""
    return shift_hours(instant, days * 24)


# ── Numbers ──────────────────────────────────────────
def round_half_up(value: Any, decimals: int = 0) -> Decimal:
    """The rounding discipline the specification uses everywhere: half away from zero."""
    quantum = Decimal(1).scaleb(-decimals)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def round_half_up_int(value: Any) -> int:
    """Half-up rounding to a whole number, which is how every cents figure lands."""
    return int(round_half_up(value, 0))


def assert_cents(record: Json, field: str, expected: int) -> None:
    """A money field is an exact integer number of whole cents."""
    actual = record.get(field)
    assert isinstance(actual, int) and not isinstance(
        actual, bool
    ), "{} is not an integer number of cents: {!r}".format(field, actual)
    assert actual == expected, "{} = {} cents, expected {} cents".format(
        field, actual, expected
    )


def assert_pct(record: Json, field: str, expected: float) -> None:
    """A percentage field equals the expected figure at two decimals."""
    actual = record.get(field)
    assert actual is not None, "{} is missing".format(field)
    assert round_half_up(actual, 2) == round_half_up(
        expected, 2
    ), "{} = {}, expected {}".format(field, actual, expected)


def assert_vent_hours(record: Json, field: str, expected: float) -> None:
    """A ventilator-hour field equals the expected figure at one decimal."""
    actual = record.get(field)
    assert actual is not None, "{} is missing".format(field)
    assert round_half_up(actual, 1) == round_half_up(
        expected, 1
    ), "{} = {}, expected {}".format(field, actual, expected)


def assert_integer_field(record: Json, field: str, expected: int) -> None:
    actual = record.get(field)
    assert isinstance(actual, int) and not isinstance(
        actual, bool
    ), "{} is not an integer: {!r}".format(field, actual)
    assert actual == expected, "{} = {}, expected {}".format(field, actual, expected)


# ── Derived figures the specification pins ───────────
def sso_threshold_days(alos_days: int) -> int:
    """floor(0.8333333333333334 x alos_days), the short-stay outlier threshold."""
    return int(math.floor(SSO_ALOS_FRACTION * alos_days))


def full_standard_amount_cents(standard_federal_rate_cents: int, relative_weight: float) -> int:
    """The full MS-LTC-DRG amount: the federal rate times the weight, rounded half up."""
    return round_half_up_int(
        Decimal(str(standard_federal_rate_cents)) * Decimal(str(relative_weight))
    )


def outlier_payment_cents(base_payment_cents: int, estimated_cost_cents: Optional[int]) -> int:
    """The high-cost add-on, in the pinned order: threshold, then excess, then one rounding.

    The fixed-loss amount is added to the base payment to form the threshold, and the
    threshold deliberately excludes the add-on it is about to produce.
    """
    cost = 0 if estimated_cost_cents is None else estimated_cost_cents
    threshold = base_payment_cents + FIXED_LOSS_AMOUNT_CENTS
    excess = cost - threshold
    if excess <= 0:
        return 0
    return round_half_up_int(Decimal(str(OUTLIER_MARGINAL_COST_FACTOR)) * Decimal(excess))


def discharge_payment_pct(base_payment_cents: int, full_standard_cents: int) -> Decimal:
    """The base payment as a percentage of the full amount, at two decimals, outlier excluded."""
    return round_half_up(
        Decimal(base_payment_cents) * Decimal(100) / Decimal(full_standard_cents), 2
    )


def raw_risk_score(
    missing_discipline_count: int,
    weaning_gap: int,
    sso_flag: int,
    site_neutral_flag: int,
    los_excess_days: int,
) -> Decimal:
    """The weighted sum before rounding and clamping."""
    return (
        Decimal(MISSING_DISCIPLINE_WEIGHT) * Decimal(missing_discipline_count)
        + Decimal(WEANING_GAP_WEIGHT) * Decimal(weaning_gap)
        + Decimal(SSO_WEIGHT) * Decimal(sso_flag)
        + Decimal(SITE_NEUTRAL_WEIGHT) * Decimal(site_neutral_flag)
        + Decimal(str(LOS_EXCESS_WEIGHT)) * Decimal(los_excess_days)
    )


def clamped_score(raw: Any) -> int:
    """A raw score rounded half up and clamped into the closed range 0 to 100."""
    return max(RISK_SCORE_MIN, min(RISK_SCORE_MAX, round_half_up_int(raw)))


def query_adjusted_score(raw: Any, answered_query_count: int) -> int:
    """The same raw score less the per-answered-query credit, rounded and clamped."""
    return clamped_score(Decimal(str(raw)) - Decimal(ANSWERED_QUERY_CREDIT) * Decimal(answered_query_count))


def risk_band_for(score: int) -> str:
    """HIGH at 70 and above, MODERATE at 40 and above, LOW below that."""
    if score >= HIGH_BAND_MIN:
        return "HIGH"
    if score >= MODERATE_BAND_MIN:
        return "MODERATE"
    return "LOW"


def expected_share_pct(admissions_in_period: int, total_admissions: int) -> Decimal:
    """The referral share: the hospital's admissions over the period's, as a percentage.

    A period with no admissions yields 0.00 rather than a division by zero.
    """
    if total_admissions == 0:
        return round_half_up(0, 2)
    return round_half_up(
        Decimal(admissions_in_period) * Decimal(100) / Decimal(total_admissions), 2
    )


# ── Composite record assertions ──────────────────────
def assert_stay_dimensions(stay: Json, clinical_status: str, payment_review_status: str) -> None:
    """The clinical story and the money story of a stay, asserted together."""
    assert stay.get("clinical_status") == clinical_status, (
        "clinical_status = {!r}, expected {!r}".format(
            stay.get("clinical_status"), clinical_status
        )
    )
    assert stay.get("payment_review_status") == payment_review_status, (
        "payment_review_status = {!r}, expected {!r}".format(
            stay.get("payment_review_status"), payment_review_status
        )
    )


def assert_hospital_posture(
    hospital: Json,
    admissions_in_period: int,
    share_pct: float,
    monitoring_state: str,
) -> None:
    """A referring hospital's three live referral-mix figures at once."""
    assert_integer_field(hospital, "admissions_in_period", admissions_in_period)
    assert_pct(hospital, "share_pct", share_pct)
    assert hospital.get("monitoring_state") == monitoring_state, (
        "monitoring_state = {!r}, expected {!r}".format(
            hospital.get("monitoring_state"), monitoring_state
        )
    )


def assert_period_ledger(
    period: Json, total_payment_cents: int, final_determination_count: int
) -> None:
    """The period's money ledger and its finalized-determination count together."""
    assert_cents(period, "total_payment_cents", total_payment_cents)
    assert_integer_field(period, "final_determination_count", final_determination_count)


def assert_counters_reconcile(period: Json, hospitals: Sequence[Json]) -> None:
    """The hospitals' admission counters sum to the period's total admissions."""
    summed = sum(h["admissions_in_period"] for h in hospitals)
    assert summed == period["total_admissions"], (
        "hospital admissions sum to {} but the period reports total_admissions {}".format(
            summed, period["total_admissions"]
        )
    )


# ── Listings ─────────────────────────────────────────
def assert_ascending_created_at(records: Sequence[Json]) -> None:
    """A listing comes back oldest first."""
    stamps = [canonical_ts(r["created_at"]) for r in records]
    assert stamps == sorted(stamps), "created_at values are not ascending: {}".format(stamps)


def assert_descending_created_at(records: Sequence[Json]) -> None:
    """The one documented exception: a stay's determinations come back newest first."""
    stamps = [canonical_ts(r["created_at"]) for r in records]
    assert stamps == sorted(stamps, reverse=True), (
        "created_at values are not descending: {}".format(stamps)
    )


def ids_of(records: Sequence[Json]) -> List[str]:
    return [r["id"] for r in records]


def assert_ids_equal(records: Sequence[Json], expected_ids: Sequence[str]) -> None:
    """A filtered listing returned exactly these records, in this order."""
    actual = ids_of(records)
    assert actual == list(expected_ids), "listing returned {}, expected {}".format(
        actual, list(expected_ids)
    )


def assert_contains_only(records: Sequence[Json], expected_ids: Sequence[str]) -> None:
    """A filtered listing returned exactly this set of records, order aside."""
    actual = set(ids_of(records))
    assert actual == set(expected_ids), "listing returned {}, expected {}".format(
        sorted(actual), sorted(set(expected_ids))
    )


def assert_pagination_meta(
    meta: Json, total: int, limit: int, offset: int, has_more: bool
) -> None:
    """All four pagination fields of a list response.

    The count of matching records before pagination is named `total_count`; the shorter
    `total` is accepted as well so a caller that already normalised the envelope still
    works.
    """
    actual_total = meta.get("total_count", meta.get("total"))
    assert actual_total == total, "meta.total_count = {!r}, expected {}".format(
        actual_total, total
    )
    assert meta.get("limit") == limit, "meta.limit = {!r}, expected {}".format(
        meta.get("limit"), limit
    )
    assert meta.get("offset") == offset, "meta.offset = {!r}, expected {}".format(
        meta.get("offset"), offset
    )
    assert meta.get("has_more") is has_more, "meta.has_more = {!r}, expected {}".format(
        meta.get("has_more"), has_more
    )
