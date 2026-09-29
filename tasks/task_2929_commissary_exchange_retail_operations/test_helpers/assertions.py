"""Domain assertions and the arithmetic the PRD pins down.

The rounding helpers here are deliberately re-implementations of the rules
stated in PRD 2.6 so that a test can state an expected figure as a computation
rather than as a magic number where that reads more clearly. Where an instance
pins an exact cent figure, the test asserts that literal instead.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    CONTINGENCY_BP_LARGE,
    CONTINGENCY_BP_MEDIUM,
    CONTINGENCY_BP_SMALL,
    CONTINGENCY_TIER_MEDIUM_MAX_EXCLUSIVE_CENTS,
    CONTINGENCY_TIER_SMALL_MAX_EXCLUSIVE_CENTS,
    FREIGHT_RATE_CENTS_PER_KG,
    PATRON_SHIPPING_SHARE_BP,
    POSTURE_CONSTRAINED_MIN_CENTS,
    POSTURE_UNRESTRICTED_MIN_CENTS,
    SHIPPING_ALLOWANCE_CAP_CENTS,
)

# ---------------------------------------------------------------------------
# Arithmetic (PRD 2.6)
# ---------------------------------------------------------------------------


def apply_bp(amount_cents: int, rate_bp: int) -> int:
    """Apply a basis-point rate to a cent amount, rounding an exact half up.

    "a non-negative rational result is rounded to the nearest whole cent, and an
    exact half is rounded away from zero".
    """
    assert amount_cents >= 0, "the pinned rounding rule is stated for non-negative results"
    numerator = amount_cents * rate_bp
    return (numerator * 2 + 10000) // 20000


def billable_kilograms(unit_weight_grams: int, quantity: int) -> int:
    """Grams to whole kilograms, rounded up whenever there is any remainder."""
    grams = unit_weight_grams * quantity
    return -(-grams // 1000)


def freight_cents(region: str, billable_kg: int) -> int:
    """Gross freight for a region and a billable weight."""
    return FREIGHT_RATE_CENTS_PER_KG[region] * billable_kg


def patron_share_cents(gross_ship_cents: int) -> int:
    """The patron's quarter of the freight, rounded by the pinned rule."""
    return apply_bp(gross_ship_cents, PATRON_SHIPPING_SHARE_BP)


def shipping_allowance_cents(gross_ship_cents: int, share_cents: int) -> int:
    """The capped, never-negative taxpayer subsidy."""
    return min(SHIPPING_ALLOWANCE_CAP_CENTS, max(0, gross_ship_cents - share_cents))


def contingency_bp_for(requested_amount_cents: int) -> int:
    """The contingency tier, selected from the contingency-free request amount."""
    if requested_amount_cents < CONTINGENCY_TIER_SMALL_MAX_EXCLUSIVE_CENTS:
        return CONTINGENCY_BP_SMALL
    if requested_amount_cents < CONTINGENCY_TIER_MEDIUM_MAX_EXCLUSIVE_CENTS:
        return CONTINGENCY_BP_MEDIUM
    return CONTINGENCY_BP_LARGE


def obligation_for(requested_amount_cents: int) -> int:
    """Request amount plus its rounded contingency."""
    rate = contingency_bp_for(requested_amount_cents)
    return requested_amount_cents + apply_bp(requested_amount_cents, rate)


def posture_for(available_surcharge_cents: int) -> str:
    """The store's spending posture derived from its available surcharge."""
    if available_surcharge_cents >= POSTURE_UNRESTRICTED_MIN_CENTS:
        return "UNRESTRICTED"
    if available_surcharge_cents >= POSTURE_CONSTRAINED_MIN_CENTS:
        return "CONSTRAINED"
    return "FROZEN"


def risk_score(restricted_units: int, strike_count: int) -> int:
    """12 points per restricted unit plus 25 per strike, capped at 100."""
    return min(100, 12 * restricted_units + 25 * strike_count)


# ---------------------------------------------------------------------------
# Shape assertions
# ---------------------------------------------------------------------------


def assert_identity(record: Dict[str, Any]) -> None:
    """Every persisted record carries a bare-UUID id and a created_at instant."""
    assert is_valid_uuid(record["id"]), f"id must be a bare UUID, got {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp, got {record['created_at']!r}"
    )


def assert_versioned(record: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A record that carries updated_at and version, optionally at a known version."""
    assert_identity(record)
    assert is_iso8601_timestamp(record["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {record['updated_at']!r}"
    )
    assert isinstance(record["version"], int), "version must be an integer"
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_append_only(record: Dict[str, Any]) -> None:
    """An append-only record: id and created_at only, with no updated_at or version."""
    assert_identity(record)
    assert "updated_at" not in record, "an append-only record carries no updated_at"
    assert "version" not in record, "an append-only record carries no version"


def assert_fields(record: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert a batch of field values, reporting every mismatch at once."""
    problems: List[str] = []
    for key, value in expected.items():
        assert key in record, f"missing field {key!r} in {sorted(record)}"
        if record[key] != value:
            problems.append(f"{key}: expected {value!r}, got {record[key]!r}")
    assert not problems, "; ".join(problems)


def assert_instant_equals(actual: Optional[str], expected: Optional[str]) -> None:
    """Compare two instants without caring about sub-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"expected instant {expected!r}, got {actual!r}"
    )


def assert_money_integer(record: Dict[str, Any], *field_names: str) -> None:
    """Money fields are integer cents, never strings and never floats."""
    for name in field_names:
        value = record[name]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{name} must be an integer number of cents, got {value!r}"
        )


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------


def assert_store(store: Dict[str, Any], **expected: Any) -> None:
    """A store record with its four derived fund figures and its posture."""
    assert_versioned(store)
    assert_money_integer(
        store,
        "surcharge_fund_balance_cents",
        "surcharge_obligated_cents",
        "dividend_fund_balance_cents",
        "shipping_allowance_committed_cents",
    )
    available = store["surcharge_fund_balance_cents"] - store["surcharge_obligated_cents"]
    assert store["fund_posture"] == posture_for(available), (
        f"fund_posture {store['fund_posture']!r} disagrees with an available "
        f"surcharge of {available}"
    )
    if expected:
        assert_fields(store, expected)


def assert_patron(patron: Dict[str, Any], **expected: Any) -> None:
    """A patron record with both risk scores and both status dimensions."""
    assert_versioned(patron)
    for name in (
        "resale_risk_score",
        "recent_sales_risk_score",
        "restricted_units_30d",
        "flagged_sale_count_30d",
        "manual_strike_count",
    ):
        assert isinstance(patron[name], int), f"{name} must be an integer"
    assert 0 <= patron["resale_risk_score"] <= 100, "the score is capped at 100"
    assert 0 <= patron["recent_sales_risk_score"] <= 100, "the score is capped at 100"
    if expected:
        assert_fields(patron, expected)


def assert_delegation(delegation: Dict[str, Any], **expected: Any) -> None:
    """A shopper delegation record."""
    assert_versioned(delegation)
    if expected:
        assert_fields(delegation, expected)


def assert_product(product: Dict[str, Any], **expected: Any) -> None:
    """A worldwide item file record."""
    assert_versioned(product)
    assert_money_integer(product, "unit_cost_cents")
    if expected:
        assert_fields(product, expected)


def assert_assortment(assortment: Dict[str, Any], **expected: Any) -> None:
    """A shelf allocation record."""
    assert_versioned(assortment)
    assert_money_integer(assortment, "overseas_shipping_allowance_cents")
    if expected:
        assert_fields(assortment, expected)


def assert_sale(sale: Dict[str, Any], **expected: Any) -> None:
    """A visit record: both state axes plus every computed money field."""
    assert_versioned(sale)
    assert_money_integer(
        sale,
        "merchandise_cents",
        "markup_total_cents",
        "surcharge_total_cents",
        "tax_cents",
        "total_due_cents",
        "provisional_allowance_cents",
        "subsidized_shipping_cents",
    )
    assert sale["tax_cents"] == 0, "commissary and exchange sales are tax-free"
    assert sale["total_due_cents"] == (
        sale["merchandise_cents"]
        + sale["markup_total_cents"]
        + sale["surcharge_total_cents"]
        + sale["tax_cents"]
    ), "total_due_cents must be the sum of the four components"
    if expected:
        assert_fields(sale, expected)


def assert_sale_line(line: Dict[str, Any], **expected: Any) -> None:
    """A priced sale line: append-only, so no updated_at and no version."""
    assert_append_only(line)
    assert_money_integer(
        line,
        "unit_price_cents",
        "extended_cents",
        "line_markup_cents",
        "line_surcharge_cents",
        "line_allowance_cents",
        "line_shipping_allowance_cents",
    )
    assert line["extended_cents"] == line["unit_price_cents"] * line["quantity"], (
        "extended_cents must be the unit price times the quantity"
    )
    if expected:
        assert_fields(line, expected)


def assert_ledger_entry(entry: Dict[str, Any], **expected: Any) -> None:
    """A fund ledger entry: append-only, signed amount, stamped period index."""
    assert_append_only(entry)
    assert_money_integer(entry, "amount_cents", "balance_after_cents")
    assert isinstance(entry["period_close_index"], int), "period_close_index must be an integer"
    if expected:
        assert_fields(entry, expected)


def assert_capital_project(project: Dict[str, Any], **expected: Any) -> None:
    """A capital project with its computed contingency and obligation."""
    assert_versioned(project)
    assert_money_integer(
        project, "requested_amount_cents", "contingency_cents", "obligation_cents"
    )
    assert project["contingency_bp"] == contingency_bp_for(project["requested_amount_cents"]), (
        "the tier is selected from the contingency-free request amount"
    )
    assert project["obligation_cents"] == (
        project["requested_amount_cents"] + project["contingency_cents"]
    ), "obligation_cents must be the request amount plus its contingency"
    if expected:
        assert_fields(project, expected)


def assert_mwr_program(program: Dict[str, Any], **expected: Any) -> None:
    """An MWR programme with its derived year-to-date funding."""
    assert_versioned(program)
    assert_money_integer(program, "funding_ceiling_cents", "ytd_funded_cents")
    if expected:
        assert_fields(program, expected)


def assert_special_order(order: Dict[str, Any], **expected: Any) -> None:
    """A special order with its shipping computation."""
    assert_versioned(order)
    assert_money_integer(
        order, "gross_ship_cents", "patron_share_cents", "shipping_allowance_cents"
    )
    assert isinstance(order["billable_weight_kg"], int), "billable_weight_kg must be an integer"
    if expected:
        assert_fields(order, expected)


# ---------------------------------------------------------------------------
# Collection assertions
# ---------------------------------------------------------------------------


def assert_ids_in_order(records: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """The listed records are exactly these ids, in exactly this order."""
    actual = [record["id"] for record in records]
    assert actual == list(expected_ids), f"expected order {list(expected_ids)}, got {actual}"


def assert_created_at_ascending(records: Iterable[Dict[str, Any]]) -> None:
    """A default-ordered list runs created_at ascending."""
    stamps = [canonical_instant(record["created_at"]) for record in records]
    assert stamps == sorted(stamps), f"expected created_at ascending, got {stamps}"


def assert_total_count(meta: Dict[str, Any], expected: int) -> None:
    """The count of matching records before paging."""
    assert meta["total_count"] == expected, (
        f"expected total_count {expected}, got {meta['total_count']}"
    )
