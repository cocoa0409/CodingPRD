"""Domain assertion helpers.

These wrap the repeated shape checks of the PRD — the envelope of 2.2, the four
common resource properties of 2.5, the money discipline of 2.6, the conserved
collection identity of 2.12 — so that a test body reads as the business rule it
is checking rather than as a pile of dictionary lookups.
"""
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .api_client import canonical_instant
from .constants import API_REQUEST_ID_PREFIX


# --------------------------------------------------------------------------
# Envelope and common resource properties
# --------------------------------------------------------------------------
def assert_envelope_meta(response) -> Dict[str, Any]:
    """The success envelope of PRD 2.2 carries a req_-prefixed request id."""
    body = response.json()
    assert "meta" in body, "response carries no meta object: %s" % body
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), (
        "api_request_id missing or not a string: %s" % meta
    )
    assert meta["api_request_id"].startswith(API_REQUEST_ID_PREFIX), (
        "api_request_id must start with %r, got %r"
        % (API_REQUEST_ID_PREFIX, meta["api_request_id"])
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        "api_request_timestamp is not an ISO 8601 timestamp: %s" % meta
    )
    return meta


def assert_response_type(response, expected: str) -> None:
    """``response_type`` is "object" for a single resource, "array" for a list."""
    body = response.json()
    assert body.get("response_type") == expected, (
        "expected response_type %r, got %r" % (expected, body.get("response_type"))
    )


def assert_common_fields(record: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """PRD 2.5: every persisted resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(record.get("id")), (
        "id is not a bare UUID: %r" % record.get("id")
    )
    assert "_" not in str(record.get("id")), (
        "id must carry no type prefix of any kind: %r" % record.get("id")
    )
    assert is_iso8601_timestamp(record.get("created_at")), (
        "created_at is not an ISO 8601 timestamp: %r" % record.get("created_at")
    )
    assert is_iso8601_timestamp(record.get("updated_at")), (
        "updated_at is not an ISO 8601 timestamp: %r" % record.get("updated_at")
    )
    assert isinstance(record.get("version"), int), (
        "version is not an integer: %r" % record.get("version")
    )
    if expected_version is not None:
        assert record["version"] == expected_version, (
            "expected version %d, got %r" % (expected_version, record["version"])
        )


def assert_created(response, expected_version: int = 1) -> Dict[str, Any]:
    """A creation returns 201 with the created resource and version 1."""
    assert_envelope_meta(response)
    assert_response_type(response, "object")
    data = validate_success(response, expected_status=201)
    assert_common_fields(data, expected_version=expected_version)
    return data


def assert_ok(response) -> Dict[str, Any]:
    """A non-creating success returns 200 with the affected resource."""
    assert_envelope_meta(response)
    return validate_success(response, expected_status=200)


def assert_instant_equals(actual: Optional[str], expected: Optional[str], field: str = "instant") -> None:
    """Compare two ISO 8601 instants as instants, not as strings.

    PRD 2.5 fixes three fractional digits on server-stamped timestamps, so a
    literal written without them still denotes the same instant.
    """
    assert canonical_instant(actual) == canonical_instant(expected), (
        "%s: expected instant %r, got %r" % (field, expected, actual)
    )


def assert_money_is_integer_cents(record: Dict[str, Any], *fields: str) -> None:
    """PRD 2.6: a monetary quantity is an integer number of cents, transported
    as a JSON integer rather than a string or a decimal."""
    for field in fields:
        value = record.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            "%s must be a JSON integer number of cents, got %r (%s)"
            % (field, value, type(value).__name__)
        )


def assert_ratio_four_dp(value: Any, expected: float, field: str = "ratio") -> None:
    """PRD 2.6: the four ratio quantities round to exactly four decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        "%s must be numeric, got %r" % (field, value)
    )
    assert round(float(value), 4) == round(float(expected), 4), (
        "%s: expected %.4f, got %r" % (field, expected, value)
    )
    assert abs(float(value) - round(float(value), 4)) < 1e-9, (
        "%s carries more than four decimal places: %r" % (field, value)
    )


def assert_fields(record: Dict[str, Any], **expected: Any) -> None:
    """Assert a batch of exact field values on one resource."""
    for field, want in expected.items():
        assert field in record, "field %r absent from %s" % (field, sorted(record))
        got = record[field]
        assert got == want, "%s: expected %r, got %r" % (field, want, got)


def assert_null_fields(record: Dict[str, Any], *fields: str) -> None:
    """Assert each named field is present and null."""
    for field in fields:
        assert field in record, "field %r absent from %s" % (field, sorted(record))
        assert record[field] is None, "%s: expected null, got %r" % (field, record[field])


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------
def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    """Every list response carries limit, offset, total_count and has_more."""
    assert meta.get("limit") == limit, "limit: expected %r, got %r" % (limit, meta.get("limit"))
    assert meta.get("offset") == offset, (
        "offset: expected %r, got %r" % (offset, meta.get("offset"))
    )
    assert meta.get("total_count") == total_count, (
        "total_count: expected %r, got %r" % (total_count, meta.get("total_count"))
    )
    assert meta.get("has_more") is has_more, (
        "has_more: expected %r, got %r" % (has_more, meta.get("has_more"))
    )


def assert_ordered_by(records: List[Dict[str, Any]], field: str) -> None:
    """Assert a list is ordered ascending by the named field."""
    values = [record[field] for record in records]
    assert values == sorted(values), "records are not ordered by %s ascending: %r" % (
        field,
        values,
    )


def ids_of(records: Iterable[Dict[str, Any]]) -> List[str]:
    """The ``id`` of every record in a list, in the order returned."""
    return [record["id"] for record in records]


# --------------------------------------------------------------------------
# Rounding discipline (PRD 2.6)
# --------------------------------------------------------------------------
def round_half_up(value, places: int = 0):
    """Round half up: a value exactly on the halfway mark rounds away from zero.

    Returned as an ``int`` for whole-cent results and as a ``float`` rounded to
    ``places`` decimals otherwise.
    """
    from decimal import Decimal, ROUND_HALF_UP

    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(rounded) if places == 0 else float(rounded)


# --------------------------------------------------------------------------
# Assessment arithmetic (PRD 3.3)
# --------------------------------------------------------------------------
def compute_assessment(
    method: str,
    zone: str,
    classification: str,
    revenue_basis: int = 0,
    nights_basis: int = 0,
    adjustment_basis: int = 0,
) -> int:
    """The assessment body of PRD 3.3, independently evaluated.

    The floor comparison inside the percentage branch runs before the ceiling
    comparison, and the output is the capped figure less the adjustment basis,
    floored at zero.
    """
    from .constants import (
        CLASS_MULTIPLIER,
        PERIOD_ASSESSMENT_CEILING_CENTS,
        PER_NIGHT_FLOOR_CENTS,
        PER_OCCUPIED_ROOM_NIGHT_CENTS,
        TIERED_FLAT_FEE_CENTS,
        TIERED_ZONE_FACTOR,
        ZONE_RATE_PCT_OF_ROOM_REVENUE,
    )

    multiplier = CLASS_MULTIPLIER[classification]
    if method == "PCT_OF_ROOM_REVENUE":
        revenue_component = round_half_up(
            revenue_basis * ZONE_RATE_PCT_OF_ROOM_REVENUE[zone] * multiplier
        )
        floor = nights_basis * PER_NIGHT_FLOOR_CENTS
        gross = max(revenue_component, floor)
    elif method == "PER_OCCUPIED_ROOM_NIGHT":
        gross = round_half_up(nights_basis * PER_OCCUPIED_ROOM_NIGHT_CENTS * multiplier)
    elif method == "TIERED_BY_CLASSIFICATION":
        gross = round_half_up(TIERED_FLAT_FEE_CENTS[classification] * TIERED_ZONE_FACTOR[zone])
    else:  # pragma: no cover - the PRD declares exactly three methods
        raise AssertionError("unknown assessment method %r" % method)

    capped = min(gross, PERIOD_ASSESSMENT_CEILING_CENTS)
    return max(capped - adjustment_basis, 0)


def compute_support_pct(numerator: int, denominator: int) -> float:
    """One division and one rounding, at the very end (PRD 2.6, 3.2)."""
    if denominator == 0:
        return 0.0
    return round_half_up(numerator / denominator, 4)


def compute_delinquency_charges(outstanding_cents: int, days_late: int) -> Dict[str, int]:
    """Penalty and interest for one statement, each rounded once (PRD 3.5)."""
    from .constants import DAILY_INTEREST_RATE, PENALTY_RATE

    return {
        "penalty_cents": round_half_up(outstanding_cents * PENALTY_RATE),
        "interest_cents": round_half_up(outstanding_cents * DAILY_INTEREST_RATE * days_late),
    }


def compute_performance(committed_cents: int, verified_room_nights: int) -> Dict[str, Any]:
    """The two-pass performance measurement of PRD 3.8.

    Pass one fixes the efficiency tier from the gross figure alone; pass two
    reads that tier and never reselects it.
    """
    from .constants import (
        BELOW_BENCHMARK_INDEX,
        DMO_COST_SHARE,
        MEETS_BENCHMARK_INDEX,
        PERFORMANCE_BENCHMARK_CENTS,
        TIER_EFFICIENT_MAX_CENTS,
        TIER_MARGINAL_MAX_CENTS,
        TIER_STANDARD_MAX_CENTS,
    )

    if verified_room_nights == 0:
        gross = None
        tier = "TIER_UNPRODUCTIVE"
    else:
        gross = round_half_up(committed_cents / verified_room_nights)
        if gross <= TIER_EFFICIENT_MAX_CENTS:
            tier = "TIER_EFFICIENT"
        elif gross <= TIER_STANDARD_MAX_CENTS:
            tier = "TIER_STANDARD"
        elif gross <= TIER_MARGINAL_MAX_CENTS:
            tier = "TIER_MARGINAL"
        else:
            tier = "TIER_UNPRODUCTIVE"

    dmo_share = round_half_up(committed_cents * DMO_COST_SHARE[tier])
    net_district = committed_cents - dmo_share
    if verified_room_nights == 0:
        net_per_night = None
        index = 0.0
        flag = "UNDERPERFORMING"
    else:
        net_per_night = round_half_up(net_district / verified_room_nights)
        index = round_half_up(PERFORMANCE_BENCHMARK_CENTS / net_per_night, 4)
        if index >= MEETS_BENCHMARK_INDEX:
            flag = "MEETS_BENCHMARK"
        elif index >= BELOW_BENCHMARK_INDEX:
            flag = "BELOW_BENCHMARK"
        else:
            flag = "UNDERPERFORMING"

    return {
        "gross_cost_per_room_night_cents": gross,
        "efficiency_tier": tier,
        "dmo_cost_share_cents": dmo_share,
        "net_district_cost_cents": net_district,
        "net_cost_per_room_night_cents": net_per_night,
        "performance_index": index,
        "performance_flag": flag,
    }


def assert_performance(program: Dict[str, Any], committed_cents: int, verified_room_nights: int) -> None:
    """Assert a closed program's published figures against PRD 3.8."""
    expected = compute_performance(committed_cents, verified_room_nights)
    for field in (
        "gross_cost_per_room_night_cents",
        "efficiency_tier",
        "dmo_cost_share_cents",
        "net_district_cost_cents",
        "net_cost_per_room_night_cents",
        "performance_flag",
    ):
        assert program.get(field) == expected[field], (
            "%s: expected %r, got %r" % (field, expected[field], program.get(field))
        )
    assert_ratio_four_dp(program.get("performance_index"), expected["performance_index"], "performance_index")


# --------------------------------------------------------------------------
# The conserved collection identity (PRD 2.12)
# --------------------------------------------------------------------------
def assert_conserved_collection_identity(
    district: Dict[str, Any], statements: Iterable[Dict[str, Any]]
) -> None:
    """A district's collected_to_date_cents equals the sum, over every one of
    that district's statements, of interest_paid + penalty_paid + principal_paid
    + credit_balance."""
    total = 0
    for statement in statements:
        total += (
            statement["interest_paid_cents"]
            + statement["penalty_paid_cents"]
            + statement["principal_paid_cents"]
            + statement["credit_balance_cents"]
        )
    assert district["collected_to_date_cents"] == total, (
        "collected_to_date_cents %r does not equal the sum of the statement buckets %r"
        % (district["collected_to_date_cents"], total)
    )


def assert_delinquent_charges_identity(
    district: Dict[str, Any], statements: Iterable[Dict[str, Any]]
) -> None:
    """delinquent_charges_cents is the sum over the same statements of
    penalty_cents plus interest_cents (PRD 2.12)."""
    total = sum(s["penalty_cents"] + s["interest_cents"] for s in statements)
    assert district["delinquent_charges_cents"] == total, (
        "delinquent_charges_cents %r does not equal the accumulated per-statement "
        "charges %r" % (district["delinquent_charges_cents"], total)
    )


def assert_waterfall_allocation(
    remittance: Dict[str, Any],
    interest: int,
    penalty: int,
    principal: int,
    credit: int,
) -> None:
    """The four allocations recorded on a remittance row, which always sum to
    exactly amount_cents (PRD 3.4)."""
    assert_fields(
        remittance,
        applied_to_interest_cents=interest,
        applied_to_penalty_cents=penalty,
        applied_to_principal_cents=principal,
        applied_to_credit_cents=credit,
    )
    assert (
        interest + penalty + principal + credit == remittance["amount_cents"]
    ), "the four allocations must sum to amount_cents: %r" % remittance


def assert_statement_money(
    statement: Dict[str, Any],
    effective: Optional[int] = None,
    total_due: Optional[int] = None,
    principal_paid: Optional[int] = None,
    penalty_paid: Optional[int] = None,
    interest_paid: Optional[int] = None,
    credit_balance: Optional[int] = None,
    payment_status: Optional[str] = None,
) -> None:
    """Assert the money buckets and derived payment status of one statement."""
    assert_money_is_integer_cents(
        statement,
        "provisional_assessment_cents",
        "effective_assessment_cents",
        "granted_adjustment_cents",
        "penalty_cents",
        "interest_cents",
        "interest_paid_cents",
        "penalty_paid_cents",
        "principal_paid_cents",
        "credit_balance_cents",
        "total_due_cents",
    )
    checks = {
        "effective_assessment_cents": effective,
        "total_due_cents": total_due,
        "principal_paid_cents": principal_paid,
        "penalty_paid_cents": penalty_paid,
        "interest_paid_cents": interest_paid,
        "credit_balance_cents": credit_balance,
        "payment_status": payment_status,
    }
    assert_fields(statement, **{k: v for k, v in checks.items() if v is not None})
