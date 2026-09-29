"""Domain assertions and reference arithmetic.

Timestamps returned by the API are canonicalised here before any comparison,
so a difference in fractional-second width or trailing-zero style can never
masquerade as a business defect (PRD §2.4 fixes the format at exactly three
fractional digits).

Percentages are compared on their scaled integer form, exactly as PRD §2.5
requires: "Comparisons involving percentages are performed on their scaled
integer form (the percentage multiplied by one hundred and rounded half up) so
that no floating-point tolerance is ever required or permitted."
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CERTIFIED_DESTRUCTION_FEE_CENTS,
    GRADE_MULTIPLIERS,
    HANDLING_SHARE_PCT,
    LABOR_RATE_CENTS_PER_MINUTE,
    LATENESS_BAND_30_DAYS,
    LATENESS_BAND_60_DAYS,
    LATENESS_BAND_NONE,
    REASON_PENALTIES,
    REFURB_OVERHEAD_MULTIPLIER,
    RESTOCKING_BASE_BY_REASON,
    RESTOCKING_FEE_PCT_CAP,
    RESTOCKING_FEE_PCT_FLOOR,
    RESTOCKING_GRADE_ADJUSTMENT,
    RESTOCKING_SERVICE_LEVEL_ADJUSTMENT,
)

# ─── Rounding and money ─────────────────────────────────────────────────


def round_half_up(value) -> int:
    """Round to a whole cent, half away from zero (PRD §2.5)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def scaled_pct(value) -> int:
    """The percentage's scaled integer form: value x 100, rounded half up."""
    return round_half_up(Decimal(str(value)) * 100)


def assert_money(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a monetary field is an integer count of cents equal to expected."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer count of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_pct_equals(actual: Any, expected, label: str = "percentage") -> None:
    """Compare two percentages on their scaled integer form."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert scaled_pct(actual) == scaled_pct(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_index_pct_equals(actual: Any, expected, label: str = "price_index_pct"):
    """Compare four-decimal percentages on their scaled integer form."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    scale = lambda v: round_half_up(Decimal(str(v)) * 10000)  # noqa: E731
    assert scale(actual) == scale(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


# ─── Instants ───────────────────────────────────────────────────────────


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, tolerating any fractional-second width."""
    assert isinstance(value, str), f"expected an ISO-8601 instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_instant(value: str) -> str:
    """Render an instant as an ISO-8601 UTC instant with three fractional digits."""
    moment = parse_instant(value)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two instants after canonicalising both to millisecond precision."""
    assert isinstance(actual, str), f"{label} must be a string instant, got {actual!r}"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {canonical_instant(expected)}, "
        f"got {canonical_instant(actual)}"
    )


def assert_instant_format(actual: Any, label: str = "instant") -> None:
    """Assert the stored format is an ISO-8601 UTC instant with three digits."""
    assert isinstance(actual, str), f"{label} must be a string instant, got {actual!r}"
    assert is_iso8601_timestamp(actual), f"{label} is not ISO-8601 UTC: {actual!r}"
    assert actual.endswith("Z"), f"{label} must be a UTC instant: {actual!r}"
    assert len(actual) == 24, (
        f"{label} must carry exactly three fractional digits: {actual!r}"
    )


def plus_hours(instant: str, hours: int) -> str:
    """The instant advanced by whole hours, canonicalised."""
    return canonical_instant(
        (parse_instant(instant) + timedelta(hours=hours)).isoformat().replace(
            "+00:00", "Z"
        )
    )


def plus_millis(instant: str, millis: int) -> str:
    """The instant advanced (or rewound) by milliseconds, canonicalised."""
    moved = parse_instant(instant) + timedelta(milliseconds=millis)
    return canonical_instant(moved.isoformat().replace("+00:00", "Z"))


def plus_days(instant: str, days: int) -> str:
    """The instant advanced by whole days, canonicalised."""
    moved = parse_instant(instant) + timedelta(days=days)
    return canonical_instant(moved.isoformat().replace("+00:00", "Z"))


# ─── Resource identity shapes (PRD §2.4) ────────────────────────────────


def assert_versioned_resource(entity: Dict[str, Any], label: str = "resource") -> None:
    """Assert one of the ten mutable resource types carries its identity fields."""
    assert is_valid_uuid(entity.get("id", "")), (
        f"{label}.id must be a UUID string, got {entity.get('id')!r}"
    )
    assert_instant_format(entity.get("created_at"), f"{label}.created_at")
    assert_instant_format(entity.get("updated_at"), f"{label}.updated_at")
    assert isinstance(entity.get("version"), int), (
        f"{label}.version must be an integer, got {entity.get('version')!r}"
    )
    assert entity["version"] >= 1, f"{label}.version must start at 1"


def assert_append_only_resource(
    entity: Dict[str, Any], label: str = "record"
) -> None:
    """Assert one of the four append-only types carries neither updated_at nor version."""
    assert is_valid_uuid(entity.get("id", "")), (
        f"{label}.id must be a UUID string, got {entity.get('id')!r}"
    )
    assert_instant_format(entity.get("created_at"), f"{label}.created_at")
    assert "updated_at" not in entity, (
        f"{label} is append-only and must not carry updated_at"
    )
    assert "version" not in entity, (
        f"{label} is append-only and must not carry version"
    )


def assert_page_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    """Assert all four pagination fields of a list response (PRD §2.3)."""
    assert meta["limit"] == limit, (
        f"meta.limit: expected {limit}, got {meta['limit']}"
    )
    assert meta["offset"] == offset, (
        f"meta.offset: expected {offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == total_count, (
        f"meta.total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more: expected {has_more}, got {meta['has_more']}"
    )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Assert the success envelope's meta fields (PRD §2.2)."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta["api_request_timestamp"], "api_request_timestamp")


# ─── Return line state assertions (PRD §2.9) ────────────────────────────


def assert_line_states(
    line: Dict[str, Any],
    disposition_state: Optional[str] = None,
    financial_state: Optional[str] = None,
    disposition: Optional[str] = None,
    condition_grade: Optional[str] = None,
) -> None:
    """Assert whichever of the line's two state dimensions the caller pinned."""
    if disposition_state is not None:
        assert line["disposition_state"] == disposition_state, (
            f"disposition_state: expected {disposition_state}, "
            f"got {line['disposition_state']}"
        )
    if financial_state is not None:
        assert line["financial_state"] == financial_state, (
            f"financial_state: expected {financial_state}, "
            f"got {line['financial_state']}"
        )
    if disposition is not None:
        assert line["disposition"] == disposition, (
            f"disposition: expected {disposition}, got {line['disposition']}"
        )
    if condition_grade is not None:
        assert line["condition_grade"] == condition_grade, (
            f"condition_grade: expected {condition_grade}, "
            f"got {line['condition_grade']}"
        )


def assert_unit_buckets(
    entity: Dict[str, Any],
    received: int,
    in_process: int,
    reserved: int,
    dispositioned: int,
) -> None:
    """Assert all four unit-conservation buckets at once (PRD §3.8)."""
    assert entity["units_received"] == received, (
        f"units_received: expected {received}, got {entity['units_received']}"
    )
    assert entity["units_in_process"] == in_process, (
        f"units_in_process: expected {in_process}, got {entity['units_in_process']}"
    )
    assert entity["units_reserved_for_disposition"] == reserved, (
        f"units_reserved_for_disposition: expected {reserved}, "
        f"got {entity['units_reserved_for_disposition']}"
    )
    assert entity["units_dispositioned"] == dispositioned, (
        f"units_dispositioned: expected {dispositioned}, "
        f"got {entity['units_dispositioned']}"
    )
    assert entity["units_received"] == (
        entity["units_in_process"]
        + entity["units_reserved_for_disposition"]
        + entity["units_dispositioned"]
    ), "units_received must equal the sum of the other three buckets"


def assert_conservation_flags(report: Dict[str, Any]) -> None:
    """Assert both audit-report conservation proofs are true (PRD §3.8)."""
    assert report["unit_conservation_ok"] is True, (
        "unit_conservation_ok must be true"
    )
    assert report["money_conservation_ok"] is True, (
        "money_conservation_ok must be true"
    )


def entries_of_type(entries: List[Dict[str, Any]], entry_type: str) -> List[Dict]:
    """The ledger entries of one type, in the order returned."""
    return [e for e in entries if e["entry_type"] == entry_type]


def sole_entry_of_type(
    entries: List[Dict[str, Any]], entry_type: str
) -> Dict[str, Any]:
    """The single ledger entry of one type; fails when there is not exactly one."""
    matches = entries_of_type(entries, entry_type)
    assert len(matches) == 1, (
        f"expected exactly one {entry_type} entry, got {len(matches)}"
    )
    return matches[0]


# ─── Reference arithmetic (PRD §3.4, §3.5, §3.6, §3.8) ──────────────────


def expected_recovery_value(
    declared_value_cents: int, condition_grade: str, reason_code: str, quantity: int
) -> int:
    """Provisional recovery: the per-unit estimate is rounded before x quantity."""
    per_unit = round_half_up(
        Decimal(str(declared_value_cents))
        * Decimal(str(GRADE_MULTIPLIERS[condition_grade]))
        * (Decimal("1") - Decimal(str(REASON_PENALTIES[reason_code])))
    )
    return per_unit * quantity


def expected_lateness_band(days_since_order: int):
    """The single mutually exclusive lateness band for a day count."""
    if days_since_order > 60:
        return LATENESS_BAND_60_DAYS
    if days_since_order > 30:
        return LATENESS_BAND_30_DAYS
    return LATENESS_BAND_NONE


def expected_restocking_fee_pct(
    reason_code: str, service_level: str, condition_grade: str, days_since_order: int
) -> float:
    """The four terms summed, then the sum floored at 0.00 and capped at 0.50."""
    total = (
        Decimal(str(RESTOCKING_BASE_BY_REASON[reason_code]))
        + Decimal(str(RESTOCKING_SERVICE_LEVEL_ADJUSTMENT[service_level]))
        + Decimal(str(RESTOCKING_GRADE_ADJUSTMENT[condition_grade]))
        + Decimal(str(expected_lateness_band(days_since_order)))
    )
    total = max(Decimal(str(RESTOCKING_FEE_PCT_FLOOR)), total)
    total = min(Decimal(str(RESTOCKING_FEE_PCT_CAP)), total)
    return float(total)


def expected_refund_amounts(
    declared_value_cents: int,
    quantity: int,
    reason_code: str,
    service_level: str,
    condition_grade: str,
    days_since_order: int,
) -> Dict[str, Any]:
    """Gross, fee percentage, fee cents and net for one refund release."""
    gross = declared_value_cents * quantity
    pct = expected_restocking_fee_pct(
        reason_code, service_level, condition_grade, days_since_order
    )
    fee = round_half_up(Decimal(str(gross)) * Decimal(str(pct)))
    return {
        "gross_refund_cents": gross,
        "restocking_fee_pct": pct,
        "restocking_fee_cents": fee,
        "net_refund_cents": gross - fee,
    }


def expected_refurb_total_cost(
    labor_minutes_total: int, parts_cost_cents: int, packaging_cost_cents: int
) -> int:
    """Direct cost x 1.15, rounded half up once over the whole work order."""
    direct = (
        labor_minutes_total * LABOR_RATE_CENTS_PER_MINUTE
        + parts_cost_cents
        + packaging_cost_cents
    )
    return round_half_up(Decimal(str(direct)) * Decimal(str(REFURB_OVERHEAD_MULTIPLIER)))


def expected_recovery_credit(net_recovery_cents: int) -> int:
    """Net recovery less the center's 7.5 percent handling share."""
    share = round_half_up(
        Decimal(str(net_recovery_cents)) * Decimal(str(HANDLING_SHARE_PCT))
    )
    return net_recovery_cents - share


def expected_destruction_write_off(declared_value_cents: int, quantity: int) -> int:
    """Declared value plus the certified-destruction fee, per unit, negated."""
    return -((declared_value_cents + CERTIFIED_DESTRUCTION_FEE_CENTS) * quantity)


def expected_donation_write_off(declared_value_cents: int, quantity: int) -> int:
    """Declared value per unit, negated."""
    return -(declared_value_cents * quantity)
