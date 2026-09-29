"""Assertions shared across the suite.

Two families live here. The first canonicalises the wire representation of
numbers and instants so that a test compares meaning rather than formatting: an
amount of whole cents, a two-decimal credit balance and a three-fractional-digit
UTC instant each have exactly one canonical form. The second family expresses
invariants the specification states directly, such as the grant ledger identity
of PRD 2.13.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Optional, Sequence

from prd_bench_local_runner.testing import validate_success

# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def validate_unpaginated(response: Any, expected_status: int = 200) -> Any:
    """Validate a success envelope whose ``meta`` carries no pagination block.

    Single-resource reads and writes answer with ``response_type`` ``object``
    and no ``limit``/``offset`` in ``meta``, so the paginated validator cannot be
    used on them.
    """
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == "object", (
        f"Expected response_type 'object', got {body['response_type']!r}"
    )
    return data


def validate_array(response: Any, expected_status: int = 200) -> Any:
    """Validate a success envelope carrying an array payload."""
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == "array", (
        f"Expected response_type 'array', got {body['response_type']!r}"
    )
    assert isinstance(data, list), f"Expected a list payload, got {type(data).__name__}"
    return data


def assert_error_envelope(response: Any) -> None:
    """Assert the response is a well-formed error envelope (PRD 2.2)."""
    body = response.json()
    assert body["response_type"] == "error", (
        f"Expected response_type 'error', got {body['response_type']!r}"
    )
    assert isinstance(body["data"]["error_id"], str)
    assert body["data"]["message"], "Error message must not be empty"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)


# ---------------------------------------------------------------------------
# Numeric canonicalisation
# ---------------------------------------------------------------------------


def _decimal(value: Any) -> Decimal:
    assert value is not None, "Expected a number, got null"
    assert not isinstance(value, bool), "Expected a number, got a boolean"
    return Decimal(str(value))


def quantized(value: Any, places: int) -> Decimal:
    """``value`` as a Decimal rounded half-up to ``places`` decimal places."""
    exponent = Decimal(1).scaleb(-places)
    return _decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """A money field is an integer number of cents (PRD 2.11)."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r} "
        f"({type(actual).__name__})"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_decimal_equals(
    actual: Any, expected: Any, places: int, label: str = "value"
) -> None:
    """Compare two numbers at a fixed decimal width (PRD 2.11)."""
    got = quantized(actual, places)
    want = quantized(expected, places)
    assert got == want, f"{label}: expected {want} at {places}dp, got {got}"


def assert_credit_hours(actual: Any, expected: Any, label: str = "credit hours") -> None:
    """Credit-hour quantities are carried at two decimal places (PRD 2.11)."""
    assert_decimal_equals(actual, expected, 2, label)


def assert_pct(actual: Any, expected: Any, label: str = "percentage") -> None:
    """Accountability percentages are carried at two decimal places (PRD 2.11)."""
    assert_decimal_equals(actual, expected, 2, label)


def assert_rate(actual: Any, expected: Any, label: str = "rate") -> None:
    """Rates are carried at four decimal places (PRD 2.11)."""
    assert_decimal_equals(actual, expected, 4, label)


def assert_alignment_index(actual: Any, expected: Any) -> None:
    """The alignment index is the one four-decimal score (PRD 2.11)."""
    assert_decimal_equals(actual, expected, 4, "alignment_index")


# ---------------------------------------------------------------------------
# Temporal canonicalisation
# ---------------------------------------------------------------------------


def canonical_instant(value: str) -> str:
    """An ISO 8601 UTC instant reduced to ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    The specification renders datetime-typed fields with three fractional digits
    (PRD 2.5), but a client may legitimately have sent the same instant with none
    or with six. Canonicalising both sides of a comparison keeps the assertion
    about the instant rather than about its spelling.
    """
    assert isinstance(value, str), f"Expected an instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif "+" in text[10:]:
        text = text[: text.index("+", 10)]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two UTC instants after canonicalising their fractional digits."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    got = canonical_instant(actual)
    want = canonical_instant(expected)
    assert got == want, f"{label}: expected {want}, got {got}"


def assert_instant_format(value: Any, label: str = "instant") -> None:
    """A datetime field is a UTC instant with three fractional digits (PRD 2.5)."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{label} must end in Z, got {value!r}"
    assert "." in value, f"{label} must carry fractional digits, got {value!r}"
    fractional = value.split(".", 1)[1][:-1]
    assert len(fractional) == 3, (
        f"{label} must carry exactly three fractional digits, got {value!r}"
    )


def assert_date_format(value: Any, label: str = "date") -> None:
    """A date field is a ``YYYY-MM-DD`` calendar date (PRD 2.5)."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{label} must be an ISO calendar date, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Structural helpers
# ---------------------------------------------------------------------------


def assert_fields_present(row: Mapping[str, Any], names: Iterable[str]) -> None:
    """Every named field is present on the row."""
    missing = [name for name in names if name not in row]
    assert not missing, f"Missing declared fields: {missing}"


def assert_fields_absent(row: Mapping[str, Any], names: Iterable[str]) -> None:
    """None of the named fields appear on the row."""
    present = [name for name in names if name in row]
    assert not present, f"Fields must be absent from the representation: {present}"


def assert_version(row: Mapping[str, Any], expected: int, label: str = "version") -> None:
    """The record's ``version`` holds the expected integer (PRD 2.4)."""
    actual = row.get("version")
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_version_bumped_by(before: int, after: int, delta: int, label: str = "version") -> None:
    """The record's ``version`` advanced by exactly ``delta`` (PRD 2.4)."""
    assert after == before + delta, (
        f"{label}: expected {before} + {delta} = {before + delta}, got {after}"
    )


def assert_same_ids(actual: Sequence[Mapping[str, Any]], expected: Iterable[str]) -> None:
    """The rows carry exactly the expected identifiers, order-insensitively."""
    got = sorted(row["id"] for row in actual)
    want = sorted(expected)
    assert got == want, f"Expected ids {want}, got {got}"


def ids_of(rows: Sequence[Mapping[str, Any]]) -> list:
    """The ``id`` of each row, in the order the collection returned them."""
    return [row["id"] for row in rows]


# ---------------------------------------------------------------------------
# Domain invariants stated by the specification
# ---------------------------------------------------------------------------


def assert_ledger(
    grant: Mapping[str, Any],
    direct_cents: int,
    indirect_rate: Any,
    pool_cents: int,
    obligated_cents: int,
    remaining_cents: int,
    admin_obligated_cents: Optional[int] = None,
) -> None:
    """Assert every figure of the six-step obligation ledger (PRD 3.7).

    The conserved quantity of PRD 2.13 — allocation equals obligated plus
    remaining — is checked alongside the individual figures on every call.
    """
    assert_cents(grant["direct_obligated_cents"], direct_cents, "direct_obligated_cents")
    assert_rate(grant["indirect_rate"], indirect_rate, "indirect_rate")
    assert_cents(grant["indirect_pool_cents"], pool_cents, "indirect_pool_cents")
    assert_cents(grant["obligated_cents"], obligated_cents, "obligated_cents")
    assert_cents(grant["remaining_cents"], remaining_cents, "remaining_cents")
    if admin_obligated_cents is not None:
        assert_cents(
            grant["admin_obligated_cents"],
            admin_obligated_cents,
            "admin_obligated_cents",
        )
    assert_ledger_identity(grant)


def assert_ledger_identity(grant: Mapping[str, Any]) -> None:
    """``allocation_cents`` equals ``obligated_cents`` plus ``remaining_cents``."""
    allocation = grant["allocation_cents"]
    obligated = grant["obligated_cents"]
    remaining = grant["remaining_cents"]
    assert allocation == obligated + remaining, (
        f"Ledger identity broken: allocation {allocation} != obligated {obligated} "
        f"+ remaining {remaining}"
    )


def assert_credit_totals(
    program: Mapping[str, Any],
    secondary: Any,
    postsecondary: Any,
    articulated: Any,
) -> None:
    """Assert the program's three stored credit subtotals (PRD 3.1)."""
    assert_credit_hours(
        program["secondary_credit_total"], secondary, "secondary_credit_total"
    )
    assert_credit_hours(
        program["postsecondary_credit_total"], postsecondary, "postsecondary_credit_total"
    )
    assert_credit_hours(
        program["articulated_credit_total"], articulated, "articulated_credit_total"
    )


def assert_cohort_figures(
    indicator: Mapping[str, Any],
    denominator: int,
    numerator: int,
    small_cohort: bool,
) -> None:
    """Assert the cohort membership counts of an indicator (PRD 3.8)."""
    assert indicator["denominator_count"] == denominator, (
        f"denominator_count: expected {denominator}, got {indicator['denominator_count']}"
    )
    assert indicator["numerator_count"] == numerator, (
        f"numerator_count: expected {numerator}, got {indicator['numerator_count']}"
    )
    assert indicator["small_cohort_flag"] is small_cohort, (
        f"small_cohort_flag: expected {small_cohort}, got {indicator['small_cohort_flag']}"
    )


def assert_quorum_figures(
    meeting: Mapping[str, Any],
    eligible: int,
    employer: int,
    quorum_met: bool,
    endorsement_passed: bool,
) -> None:
    """Assert the four figures minutes filing recomputes (PRD 3.3)."""
    assert meeting["eligible_attendee_count"] == eligible, (
        f"eligible_attendee_count: expected {eligible}, "
        f"got {meeting['eligible_attendee_count']}"
    )
    assert meeting["employer_attendee_count"] == employer, (
        f"employer_attendee_count: expected {employer}, "
        f"got {meeting['employer_attendee_count']}"
    )
    assert meeting["quorum_met"] is quorum_met, (
        f"quorum_met: expected {quorum_met}, got {meeting['quorum_met']}"
    )
    assert meeting["endorsement_passed"] is endorsement_passed, (
        f"endorsement_passed: expected {endorsement_passed}, "
        f"got {meeting['endorsement_passed']}"
    )
