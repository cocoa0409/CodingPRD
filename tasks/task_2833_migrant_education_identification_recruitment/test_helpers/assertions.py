"""Domain assertion helpers.

Two conventions from the specification drive most of what follows. Hours and credits are
"carried to exactly 2 decimal places and rounded half up", so numeric comparisons go
through ``Decimal`` rather than binary floating point. Instant-valued fields carry
"exactly three fractional-second digits", so instants are canonicalised before they are
compared against a literal written without a fraction.
"""

import re
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ELIGIBILITY_WINDOW_MONTHS,
    PFS_SCORE_THRESHOLD,
)
from .types import JsonObject

TWO_PLACES = Decimal("0.01")

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ----------------------------------------------------------------- numeric helpers
def to_decimal(value) -> Decimal:
    """Coerce a JSON number (or a numeric string) to an exact ``Decimal``."""
    assert value is not None, "expected a numeric value, got null"
    return Decimal(str(value))


def quantize_money(value) -> Decimal:
    """Round a value half up to the two decimals every hour and credit field carries."""
    return to_decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def assert_decimal_equals(actual, expected, label: str = "value") -> None:
    """Assert a two-decimal quantity equals an expected amount exactly."""
    got = quantize_money(actual)
    want = quantize_money(expected)
    assert got == want, "%s: expected %s, got %s" % (label, want, got)


def assert_two_decimals(value, label: str = "value") -> None:
    """Assert the rendered value carries no more than two decimal places."""
    text = str(value)
    if "." in text:
        fraction = text.split(".", 1)[1]
        assert len(fraction) <= 2, "%s: expected two decimals, got %s" % (label, text)


def assert_int_equals(actual, expected, label: str = "value") -> None:
    assert actual == expected, "%s: expected %r, got %r" % (label, expected, actual)


# ------------------------------------------------------------------- identity helpers
def assert_is_uuid(value, label: str = "id") -> None:
    """Assert an identifier is a server-minted UUID with no type prefix."""
    assert is_valid_uuid(value), "%s: expected a bare UUID, got %r" % (label, value)


def assert_created_and_updated_present(row: JsonObject, label: str = "row") -> None:
    """Most resources carry id, created_at, updated_at and version."""
    assert_is_uuid(row.get("id"), label + ".id")
    assert_instant_format(row.get("created_at"), label + ".created_at")
    assert_instant_format(row.get("updated_at"), label + ".updated_at")
    assert isinstance(row.get("version"), int), "%s.version must be an integer" % label


def assert_immutable_row_shape(row: JsonObject, label: str = "row") -> None:
    """Interview records and delivered sessions expose id and created_at only."""
    assert_is_uuid(row.get("id"), label + ".id")
    assert_instant_format(row.get("created_at"), label + ".created_at")
    assert "updated_at" not in row, "%s must not expose updated_at" % label
    assert "version" not in row, "%s must not expose version" % label


# ------------------------------------------------------------------ instant helpers
def assert_instant_format(value, label: str = "timestamp") -> None:
    """Assert an ISO 8601 UTC instant with fractional seconds."""
    assert value is not None, "%s: expected an instant, got null" % label
    assert is_iso8601_timestamp(value), "%s: not an ISO 8601 UTC instant: %r" % (
        label,
        value,
    )


def normalize_instant(value: str) -> str:
    """Canonicalise an instant to millisecond width so widths compare equal."""
    match = _INSTANT_RE.match(str(value))
    assert match, "not an ISO 8601 UTC instant: %r" % value
    year, month, day, hour, minute, second, fraction = match.groups()
    millis = (fraction or "").ljust(3, "0")[:3]
    return "%s-%s-%sT%s:%s:%s.%sZ" % (year, month, day, hour, minute, second, millis)


def assert_instant_equals(actual, expected, label: str = "timestamp") -> None:
    """Compare two instants irrespective of how many fractional digits each carries."""
    assert actual is not None, "%s: expected %s, got null" % (label, expected)
    got = normalize_instant(actual)
    want = normalize_instant(expected)
    assert got == want, "%s: expected %s, got %s" % (label, want, got)


def instant_date(value: str) -> str:
    """The calendar date in UTC of an instant -- the specification's clock date."""
    return normalize_instant(value)[:10]


# --------------------------------------------------------------------- date helpers
def assert_date_format(value, label: str = "date") -> None:
    assert value is not None, "%s: expected a calendar date, got null" % label
    assert _DATE_RE.match(str(value)), "%s: not an ISO 8601 date: %r" % (label, value)


def assert_date_equals(actual, expected, label: str = "date") -> None:
    assert actual == expected, "%s: expected %s, got %r" % (label, expected, actual)


def assert_is_null(value, label: str = "field") -> None:
    assert value is None, "%s: expected null, got %r" % (label, value)


# ------------------------------------------------------------------ version helpers
def assert_version(row: JsonObject, expected: int, label: str = "row") -> None:
    assert row.get("version") == expected, "%s.version: expected %d, got %r" % (
        label,
        expected,
        row.get("version"),
    )


def assert_version_unchanged(row: JsonObject, previous: int, label: str = "row") -> None:
    assert row.get("version") == previous, (
        "%s.version moved from %r although the write was rejected (now %r)"
        % (label, previous, row.get("version"))
    )


def assert_version_advanced_by(
    row: JsonObject, previous: int, delta: int, label: str = "row"
) -> None:
    assert row.get("version") == previous + delta, (
        "%s.version: expected %d after advancing by %d, got %r"
        % (label, previous + delta, delta, row.get("version"))
    )


# ----------------------------------------------------------- priority-score helpers
def expected_pfs_flag(score: int) -> bool:
    """The flag is true exactly when the score reaches the inclusive threshold."""
    return score >= PFS_SCORE_THRESHOLD


def assert_pfs_triple(
    row: JsonObject, variant: str, score: int, flag: bool, label: str = "student"
) -> None:
    """Assert the three persisted priority fields together."""
    assert_int_equals(row.get("pfs_variant"), variant, label + ".pfs_variant")
    assert_int_equals(row.get("pfs_score"), score, label + ".pfs_score")
    assert_int_equals(row.get("pfs_flag"), flag, label + ".pfs_flag")


def assert_assessment_components(assessment: JsonObject, **expected) -> None:
    """Assert any subset of the computed read's intermediate terms."""
    for key, want in expected.items():
        assert key in assessment, "the assessment omitted %s" % key
        assert assessment[key] == want, "assessment.%s: expected %r, got %r" % (
            key,
            want,
            assessment[key],
        )


# ------------------------------------------------------------- ledger helpers
def assert_student_ledgers(
    student: JsonObject,
    hours=None,
    transferred=None,
    locally=None,
    awarded=None,
) -> None:
    """Assert whichever of the child's four derived ledger figures matter."""
    if hours is not None:
        assert_decimal_equals(
            student.get("total_service_hours_ledger"),
            hours,
            "student.total_service_hours_ledger",
        )
    if transferred is not None:
        assert_decimal_equals(
            student.get("transferred_credits_count"),
            transferred,
            "student.transferred_credits_count",
        )
    if locally is not None:
        assert_decimal_equals(
            student.get("locally_accrued_credits"),
            locally,
            "student.locally_accrued_credits",
        )
    if awarded is not None:
        assert_decimal_equals(
            student.get("total_awarded_credits"),
            awarded,
            "student.total_awarded_credits",
        )


def assert_plan_allocation(
    plan: JsonObject, tier: str, allocated, label: str = "plan"
) -> None:
    """A plan's tier, allocated hours and the expected hours that mirror them."""
    assert_int_equals(plan.get("priority_tier"), tier, label + ".priority_tier")
    assert_decimal_equals(plan.get("allocated_hours"), allocated, label + ".allocated_hours")
    assert_decimal_equals(
        plan.get("expected_service_hours"), allocated, label + ".expected_service_hours"
    )


# ------------------------------------------------------------- pagination helpers
def assert_row_count(rows, expected: int, label: str = "list") -> None:
    assert len(rows) == expected, "%s: expected %d row(s), got %d" % (
        label,
        expected,
        len(rows),
    )


def assert_meta_page(meta: JsonObject, limit=None, offset=None, total=None, has_more=None):
    if limit is not None:
        assert_int_equals(meta.get("limit"), limit, "meta.limit")
    if offset is not None:
        assert_int_equals(meta.get("offset"), offset, "meta.offset")
    if total is not None:
        assert_int_equals(meta.get("total_count"), total, "meta.total_count")
    if has_more is not None:
        assert_int_equals(meta.get("has_more"), has_more, "meta.has_more")


def ids_of(rows) -> list:
    return [row["id"] for row in rows]


def find_row(rows, row_id):
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None


# ------------------------------------------------------------- date arithmetic aid
def add_months_minus_one_day(date_text: str, months: int = ELIGIBILITY_WINDOW_MONTHS) -> str:
    """The specification's window construction: add calendar months, then step back a day.

    Adding months keeps the day of the month, and when the target month has no such day
    the result is the last day of the target month.
    """
    import calendar
    import datetime

    year, month, day = (int(part) for part in date_text.split("-"))
    total = (year * 12 + (month - 1)) + months
    target_year, target_month = divmod(total, 12)
    target_month += 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    anchored = datetime.date(target_year, target_month, min(day, last_day))
    return (anchored - datetime.timedelta(days=1)).isoformat()


def add_days(date_text: str, days: int) -> str:
    import datetime

    year, month, day = (int(part) for part in date_text.split("-"))
    return (datetime.date(year, month, day) + datetime.timedelta(days=days)).isoformat()


# ------------------------------------------------------------------ envelope helpers
def assert_success_envelope(response, response_type: str, label: str = "response") -> dict:
    """Assert the standard success envelope and return the whole parsed body.

    The `api_request_id` "is a server-generated unique identifier for the request that
    starts with `req_`", the `api_request_timestamp` is a server-generated instant, and
    `response_type` "is either "object" for a single resource or "array" for a list".
    """
    body = response.json()
    meta = body.get("meta", {})
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        "%s: meta.api_request_id must start with req_, got %r" % (label, request_id)
    )
    assert_instant_format(meta.get("api_request_timestamp"), label + ".api_request_timestamp")
    assert_int_equals(body.get("response_type"), response_type, label + ".response_type")
    return body


def assert_error_envelope(response, error_id: str, label: str = "response") -> dict:
    """Assert the standard error envelope, including that meta carries only two keys."""
    body = response.json()
    meta = body.get("meta", {})
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        "%s: meta.api_request_id must start with req_, got %r" % (label, request_id)
    )
    assert_instant_format(meta.get("api_request_timestamp"), label + ".api_request_timestamp")
    assert sorted(meta.keys()) == ["api_request_id", "api_request_timestamp"], (
        "%s: error meta must carry only the two request fields, got %r"
        % (label, sorted(meta.keys()))
    )
    assert_int_equals(body.get("response_type"), "error", label + ".response_type")
    data = body.get("data", {})
    assert_int_equals(data.get("error_id"), error_id, label + ".error_id")
    message = data.get("message")
    assert isinstance(message, str) and message.strip(), (
        "%s: expected a human-readable message, got %r" % (label, message)
    )
    return body
