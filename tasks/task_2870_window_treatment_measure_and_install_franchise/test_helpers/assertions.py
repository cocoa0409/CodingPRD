"""Domain assertions for the franchise API.

Instants are always compared by *parsing* both sides, never by string equality, so
that a server rendering `2026-08-01T00:00:00Z` and one rendering
`2026-08-01T00:00:00.000Z` are treated as the same instant. Where the PRD pins the
rendering itself — "an ISO 8601 UTC instant rendered with exactly three
fractional-second digits" — that is asserted separately and explicitly.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional, Sequence

from prd_bench_local_runner.testing import is_valid_uuid

from .constants import EIGHTH_IN
from .types import Json

# ─── Instants ─────────────────────────────────────────────────────────────────


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any fractional-second width."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z") or "+" in text, f"instant must be UTC: {value!r}"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two instants denote the same moment, whatever their rendering."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_millis_format(value: str, label: str = "timestamp") -> None:
    """Assert the rendering carries exactly three fractional-second digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert len(value) == 24 and value.endswith("Z") and value[19] == ".", (
        f"{label} must be rendered with exactly three fractional digits "
        f"(for example 2026-08-01T00:00:00.000Z), got {value!r}"
    )
    assert value[20:23].isdigit(), (
        f"{label} must carry three fractional digits, got {value!r}"
    )
    parse_instant(value)


def instant_plus(value: str, **delta: Any) -> str:
    """Return an instant offset from another, rendered with three fractional digits."""
    moment = parse_instant(value) + timedelta(**delta)
    return render_instant(moment)


def render_instant(moment: datetime) -> str:
    """Render a datetime the way the API renders instants."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{moment.microsecond // 1000:03d}Z"
    )


def assert_date_string(value: str, label: str = "date") -> None:
    """Assert a whole UTC calendar date rendered as YYYY-MM-DD."""
    assert isinstance(value, str) and len(value) == 10, (
        f"{label} must be a YYYY-MM-DD string, got {value!r}"
    )
    datetime.strptime(value, "%Y-%m-%d")


# ─── Money and inches ─────────────────────────────────────────────────────────


def round_half_up_cents(amount: Any) -> int:
    """Round a derived monetary figure half up to a whole cent."""
    return int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def royalty_on(basis_cents: int, royalty_rate_pct: float) -> int:
    """The royalty on a basis: basis multiplied by the rate, rounded half up."""
    return round_half_up_cents(Decimal(str(basis_cents)) * Decimal(str(royalty_rate_pct)))


def assert_money_field(row: Json, field: str, expected: Optional[int] = None) -> int:
    """Assert a `_cents` field is a JSON integer, and optionally its value."""
    value = row.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a JSON integer number of cents, got {value!r}"
    )
    if expected is not None:
        assert value == expected, f"{field}: expected {expected}, got {value}"
    return value


def assert_money_fields(row: Json, **expected: int) -> None:
    """Assert several monetary fields at once."""
    for field, value in expected.items():
        assert_money_field(row, field, value)


def assert_eighth_multiple(value: Any, label: str = "ordered dimension") -> None:
    """Assert a finished order dimension is an exact multiple of one eighth."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    scaled = Decimal(str(value)) / Decimal(str(EIGHTH_IN))
    assert scaled == scaled.to_integral_value(), (
        f"{label} {value} is not an exact multiple of 0.125"
    )


def assert_inches_equal(actual: Any, expected: float, label: str = "inches") -> None:
    """Assert an inch measurement equals an expected value at three decimals."""
    assert actual is not None, f"{label} is missing"
    assert Decimal(str(actual)).quantize(Decimal("0.001")) == Decimal(
        str(expected)
    ).quantize(Decimal("0.001")), f"{label}: expected {expected}, got {actual}"


def assert_decimal_places(value: Any, places: int, label: str = "value") -> None:
    """Assert a decimal carries at most the stated number of decimal places."""
    exponent = Decimal(str(value)).normalize().as_tuple().exponent
    assert isinstance(exponent, int) and -exponent <= places, (
        f"{label} {value} carries more than {places} decimal places"
    )


# ─── Identity, timestamps and versioning ──────────────────────────────────────


def assert_identity(row: Json, label: str = "resource") -> None:
    """Assert the server-minted id and creation stamp every resource carries."""
    assert is_valid_uuid(row.get("id")), (
        f"{label}.id must be a server-generated UUID with no type prefix, "
        f"got {row.get('id')!r}"
    )
    assert_instant_millis_format(row.get("created_at"), f"{label}.created_at")


def assert_versioned_resource(row: Json, label: str = "resource",
                              version: Optional[int] = None) -> None:
    """Assert a resource carrying `updated_at` and `version` alongside its identity."""
    assert_identity(row, label)
    assert_instant_millis_format(row.get("updated_at"), f"{label}.updated_at")
    assert isinstance(row.get("version"), int), (
        f"{label}.version must be an integer, got {row.get('version')!r}"
    )
    if version is not None:
        assert row["version"] == version, (
            f"{label}.version: expected {version}, got {row['version']}"
        )


def assert_immutable_ledger_row(row: Json) -> None:
    """A ledger row carries only `id` and `created_at` — no `updated_at`, no `version`."""
    assert_identity(row, "ledger entry")
    assert "updated_at" not in row, (
        "a ledger row is immutable once written, so `updated_at` must not appear "
        "in its response body"
    )
    assert "version" not in row, (
        "a ledger row is immutable once written, so `version` must not appear "
        "in its response body"
    )


def assert_version_advanced(newer: Json, older: Json, label: str = "resource") -> None:
    """Assert a row's version strictly increased across a mutation."""
    assert newer["version"] > older["version"], (
        f"{label}.version did not advance: {older['version']} -> {newer['version']}"
    )


def assert_version_unchanged(newer: Json, older: Json,
                             label: str = "resource") -> None:
    """Assert a refused or unrelated request left a row's version alone."""
    assert newer["version"] == older["version"], (
        f"{label}.version moved when it should not have: "
        f"{older['version']} -> {newer['version']}"
    )


# ─── Pagination ───────────────────────────────────────────────────────────────


def assert_page_meta(meta: Json, total_count: Optional[int] = None,
                     has_more: Optional[bool] = None,
                     limit: Optional[int] = None,
                     offset: Optional[int] = None) -> None:
    """Assert the pagination block echoed back on a list response."""
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, (
            f"limit: expected {limit}, got {meta['limit']}"
        )
    if offset is not None:
        assert meta["offset"] == offset, (
            f"offset: expected {offset}, got {meta['offset']}"
        )


def ids_of(rows: Iterable[Json]) -> list:
    """The `id` of every row in a list response, in the order returned."""
    return [row["id"] for row in rows]


def assert_created_at_ascending(rows: Sequence[Json]) -> None:
    """Assert list results are ordered by `created_at` ascending — oldest row first."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), (
        f"rows are not ordered by created_at ascending: "
        f"{[row['created_at'] for row in rows]}"
    )


def assert_ledger_order(rows: Sequence[Json]) -> None:
    """Assert the ledger listing is ordered by `occurred_at` then `created_at`."""
    keys = [(parse_instant(r["occurred_at"]), parse_instant(r["created_at"]))
            for r in rows]
    assert keys == sorted(keys), (
        "the territory ledger listing must be ordered by occurred_at ascending "
        "and fall back to created_at ascending"
    )


# ─── Ledger rows ──────────────────────────────────────────────────────────────


def assert_ledger_entry(row: Json, entry_type: str, amount_cents: int,
                        basis_cents: int, memo: str,
                        source_entity_type: str,
                        source_entity_id: Optional[str] = None,
                        territory_id: Optional[str] = None,
                        occurred_at: Optional[str] = None) -> None:
    """Assert every stored field of one accrual row."""
    assert row["entry_type"] == entry_type, (
        f"entry_type: expected {entry_type}, got {row['entry_type']}"
    )
    assert_money_field(row, "amount_cents", amount_cents)
    assert_money_field(row, "basis_cents", basis_cents)
    assert row["memo"] == memo, f"memo: expected {memo}, got {row['memo']}"
    assert row["source_entity_type"] == source_entity_type, (
        f"source_entity_type: expected {source_entity_type}, "
        f"got {row['source_entity_type']}"
    )
    if source_entity_id is not None:
        assert row["source_entity_id"] == source_entity_id, (
            "source_entity_id must hold the id of the row that caused the accrual"
        )
    if territory_id is not None:
        assert row["territory_id"] == territory_id
    if occurred_at is not None:
        assert_instant_equals(row["occurred_at"], occurred_at,
                              "ledger entry occurred_at")
    assert_immutable_ledger_row(row)


def assert_reversal_sign(row: Json) -> None:
    """`ROYALTY_REVERSAL` rows always carry a negative amount; others positive."""
    if row["entry_type"] == "ROYALTY_REVERSAL":
        assert row["amount_cents"] < 0, (
            "a ROYALTY_REVERSAL row always carries a negative amount"
        )
    else:
        assert row["amount_cents"] > 0, (
            f"{row['entry_type']} always carries a positive amount"
        )


# ─── Domain invariants ────────────────────────────────────────────────────────


def assert_kit_conservation(territory: Json, total_kit_rows: int) -> None:
    """`available_kit_count` + `on_loan_kit_count` + `lost_kit_count` == kit rows."""
    total = (territory["available_kit_count"] + territory["on_loan_kit_count"]
             + territory["lost_kit_count"])
    assert total == total_kit_rows, (
        f"kit conservation broken: {territory['available_kit_count']} available + "
        f"{territory['on_loan_kit_count']} on loan + "
        f"{territory['lost_kit_count']} lost != {total_kit_rows} kit rows"
    )


def assert_remake_buckets_sum(order: Json) -> None:
    """The three absorption buckets always sum exactly to `remake_cost_cents`."""
    total = (order["vendor_absorbed_cents"] + order["territory_absorbed_cents"]
             + order["customer_absorbed_cents"])
    assert total == order["remake_cost_cents"], (
        f"absorption buckets {order['vendor_absorbed_cents']}/"
        f"{order['territory_absorbed_cents']}/{order['customer_absorbed_cents']} "
        f"do not sum to remake_cost_cents {order['remake_cost_cents']}"
    )


def assert_all_distinct(values: Sequence[Any], label: str = "values") -> None:
    """Assert no value in a sequence repeats."""
    assert len(set(values)) == len(values), (
        f"{label} are not pairwise distinct: {list(values)}"
    )


def assert_no_such_field(row: Json, *fields: str) -> None:
    """Assert fields the specification does not place on a resource are absent."""
    for field in fields:
        assert field not in row, f"unexpected field {field!r} on the resource"
