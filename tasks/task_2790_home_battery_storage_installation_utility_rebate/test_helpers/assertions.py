"""
Domain assertions.

These wrap the checks that recur across many tests: that a record carries the four
common properties, that a program's three cents buckets still add up to its total
budget, that a rounded quantity has the right number of decimals, and that two
timestamps denote the same instant regardless of how many fractional digits each side
chose to print.

Every helper raises AssertionError with a message that names the field and both
values, because a failure two hundred lines into a cascade scenario is only useful if
it says which number moved.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_ts
from .constants import BP_DENOMINATOR

Json = Dict[str, Any]


# ── Common properties ────────────────────────────────
def assert_common_fields(record: Json, expected_version: Optional[int] = None) -> None:
    """Every record carries an id, two timestamps and an integer version."""
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
    """A freshly created record opens at version 1 with equal timestamps."""
    assert_common_fields(record, expected_version=1)
    assert canonical_ts(record["created_at"]) == canonical_ts(
        record["updated_at"]
    ), "created_at {} and updated_at {} differ on a new record".format(
        record["created_at"], record["updated_at"]
    )


# ── Timestamps ───────────────────────────────────────
def assert_instant_equals(actual: Optional[str], expected: Optional[str], field: str = "timestamp") -> None:
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


# ── Numbers ──────────────────────────────────────────
def round_half_up(value: Any, decimals: int) -> Decimal:
    """The rounding discipline the specification uses everywhere: half away from zero."""
    quantum = Decimal(1).scaleb(-decimals)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def apply_bp(amount: Any, basis_points: int) -> Decimal:
    """Multiply by a basis-point figure and divide by 10000, without rounding."""
    return Decimal(str(amount)) * Decimal(basis_points) / Decimal(BP_DENOMINATOR)


def assert_decimals_at_most(value: Any, decimals: int, field: str) -> None:
    """A rounded quantity never carries more fractional digits than declared."""
    assert value is not None, "{} is missing".format(field)
    exponent = -Decimal(str(value)).as_tuple().exponent
    assert exponent <= decimals, "{} = {} carries more than {} decimals".format(
        field, value, decimals
    )


def assert_cents(record: Json, field: str, expected: int) -> None:
    """A cents field is an exact integer number of cents."""
    actual = record.get(field)
    assert isinstance(actual, int) and not isinstance(
        actual, bool
    ), "{} is not an integer number of cents: {!r}".format(field, actual)
    assert actual == expected, "{} = {} cents, expected {} cents".format(
        field, actual, expected
    )


def assert_quantity(record: Json, field: str, expected: float, decimals: int = 2) -> None:
    """A kilowatt or kilowatt-hour field equals the expected rounded figure."""
    actual = record.get(field)
    assert actual is not None, "{} is missing".format(field)
    assert round_half_up(actual, decimals) == round_half_up(
        expected, decimals
    ), "{} = {}, expected {}".format(field, actual, expected)
    assert_decimals_at_most(actual, decimals, field)


# ── The three-bucket program ledger ──────────────────
def assert_program_ledger(
    program: Json, remaining: int, reserved: int, paid: int
) -> None:
    """All three buckets at once, plus the invariant that they sum to the budget."""
    assert_cents(program, "remaining_budget_cents", remaining)
    assert_cents(program, "reserved_budget_cents", reserved)
    assert_cents(program, "paid_budget_cents", paid)
    total = program["total_budget_cents"]
    assert remaining + reserved + paid == total, (
        "buckets {} + {} + {} = {} do not sum to total_budget_cents {}".format(
            remaining, reserved, paid, remaining + reserved + paid, total
        )
    )


def assert_ledger_conserved(program: Json) -> None:
    """The three buckets sum to the total budget, whatever the individual figures."""
    total = program["total_budget_cents"]
    summed = (
        program["remaining_budget_cents"]
        + program["reserved_budget_cents"]
        + program["paid_budget_cents"]
    )
    assert summed == total, "buckets sum to {} but total_budget_cents is {}".format(
        summed, total
    )


# ── Two-dimension status ─────────────────────────────
def assert_status_pair(system: Json, build_status: str, grid_status: str) -> None:
    """The build story and the utility story, asserted together."""
    assert system.get("build_status") == build_status, (
        "build_status = {!r}, expected {!r}".format(system.get("build_status"), build_status)
    )
    assert system.get("grid_status") == grid_status, (
        "grid_status = {!r}, expected {!r}".format(system.get("grid_status"), grid_status)
    )


# ── Ordering and listings ────────────────────────────
def assert_ascending_created_at(records: Sequence[Json]) -> None:
    """A listing comes back oldest first."""
    stamps = [canonical_ts(r["created_at"]) for r in records]
    assert stamps == sorted(stamps), "created_at values are not ascending: {}".format(stamps)


def ids_of(records: Sequence[Json]) -> List[str]:
    return [r["id"] for r in records]


def assert_ids_equal(records: Sequence[Json], expected_ids: Sequence[str]) -> None:
    """A filtered listing returned exactly these records, in this order."""
    actual = ids_of(records)
    assert actual == list(expected_ids), "listing returned {} , expected {}".format(
        actual, list(expected_ids)
    )


def assert_contains_only(records: Sequence[Json], expected_ids: Sequence[str]) -> None:
    """A filtered listing returned exactly this set of records, order aside."""
    actual = set(ids_of(records))
    assert actual == set(expected_ids), "listing returned {} , expected {}".format(
        sorted(actual), sorted(set(expected_ids))
    )
