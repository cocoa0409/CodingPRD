"""Reusable assertions for the shapes and invariants the PRD declares.

Timestamps are always compared through canonical_instant(): PRD §2.4 renders
stored instants with exactly three fractional-second digits, but a caller may
supply an instant with a different sub-second width, so equality of *instants*
is checked rather than equality of raw strings.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import DEFAULT_PAGE_LIMIT


# --------------------------------------------------------------------------
# Enum helpers
# --------------------------------------------------------------------------
def enum_values(enum_cls) -> List[str]:
    return [member.value for member in enum_cls]


def assert_in_enum(value: Any, enum_cls, field: str = "value") -> None:
    allowed = enum_values(enum_cls)
    assert value in allowed, f"{field}={value!r} is not one of {allowed}"


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------
def canonical_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime.

    Accepts a trailing ``Z`` or an explicit offset and any sub-second width, so
    two renderings of the same instant compare equal.
    """
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, field: str = "timestamp") -> None:
    """Compare two ISO 8601 instants by value, not by rendering."""
    assert actual is not None, f"{field} is missing"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field}: expected instant {expected}, got {actual}"
    )


def assert_three_fraction_digits(value: str, field: str = "timestamp") -> None:
    """PRD §2.4: stored instants render with exactly three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field}={value!r} is not an ISO 8601 UTC instant"
    assert value.endswith("Z"), f"{field}={value!r} must be rendered as UTC with a Z suffix"
    fraction = value[:-1].split(".")
    assert len(fraction) == 2 and len(fraction[1]) == 3, (
        f"{field}={value!r} must carry exactly three fractional-second digits"
    )


def iso(moment: datetime) -> str:
    """Render a datetime the way the service does: three fractional digits, Z."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def shift(instant: str, **delta) -> str:
    """An instant offset from another one, rendered in the stored format."""
    return iso(canonical_instant(instant) + timedelta(**delta))


# --------------------------------------------------------------------------
# Common fields
# --------------------------------------------------------------------------
def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """PRD §2.4: id, created_at, updated_at and an integer version from 1."""
    assert is_valid_uuid(row["id"]), f"id={row['id']!r} is not a UUID"
    assert_three_fraction_digits(row["created_at"], "created_at")
    assert_three_fraction_digits(row["updated_at"], "updated_at")
    assert isinstance(row["version"], int) and not isinstance(row["version"], bool), (
        f"version must be an integer, got {row['version']!r}"
    )
    assert row["version"] >= 1, f"version must start at 1, got {row['version']}"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_immutable_evidence_fields(row: Dict[str, Any]) -> None:
    """PRD §2.4: a MetricSnapshot and a HealthEvaluation carry only id and
    created_at; updated_at and version are absent entirely."""
    assert is_valid_uuid(row["id"]), f"id={row['id']!r} is not a UUID"
    assert_three_fraction_digits(row["created_at"], "created_at")
    assert "updated_at" not in row, "updated_at must be absent from an evidence record"
    assert "version" not in row, "version must be absent from an evidence record"


def assert_version_bumped(before: Dict[str, Any], after: Dict[str, Any],
                          by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version']} + {by}, got {after['version']}"
    )


# --------------------------------------------------------------------------
# Envelope and pagination
# --------------------------------------------------------------------------
def assert_meta(meta: Dict[str, Any], total_count: Optional[int] = None,
                has_more: Optional[bool] = None, limit: Optional[int] = None,
                offset: Optional[int] = None) -> None:
    """PRD §2.3: every list response carries limit, offset, total_count and
    has_more inside meta."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"pagination meta is missing {key}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
    expected_limit = DEFAULT_PAGE_LIMIT if limit is None else limit
    assert meta["limit"] == expected_limit, (
        f"expected limit {expected_limit}, got {meta['limit']}"
    )
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"


def assert_ids_in_order(rows: Iterable[Dict[str, Any]], expected_ids: List[str],
                        label: str = "rows") -> None:
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"{label}: expected order {expected_ids}, got {actual}"


# --------------------------------------------------------------------------
# Numeric precision
# --------------------------------------------------------------------------
def _decimal(value: Any, field: str) -> Decimal:
    assert not isinstance(value, str), (
        f"{field} must be a JSON number, not the string {value!r}"
    )
    assert value is not None, f"{field} is missing"
    return Decimal(str(value))


def assert_rate(value: Any, expected: str, field: str = "rate") -> None:
    """PRD §2.6: rates are stored to exactly 4 decimal places, rounded half-up."""
    actual = _decimal(value, field)
    assert actual == Decimal(expected), f"{field}: expected {expected}, got {value}"
    assert -actual.as_tuple().exponent <= 4, (
        f"{field}={value} carries more than four decimal places"
    )


def assert_points(value: Any, expected: str, field: str = "points") -> None:
    """PRD §2.6: points and scores are stored to exactly 2 decimal places."""
    actual = _decimal(value, field)
    assert actual == Decimal(expected), f"{field}: expected {expected}, got {value}"
    assert -actual.as_tuple().exponent <= 2, (
        f"{field}={value} carries more than two decimal places"
    )


def assert_cents(value: Any, expected: int, field: str = "amount_cents") -> None:
    """PRD §2.6: money is integer cents and may never be negative."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )
    assert value >= 0, f"{field} may never be negative, got {value}"
    assert value == expected, f"{field}: expected {expected}, got {value}"


def round_half_up(value: Decimal, places: int) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_funds_identity(seller: Dict[str, Any]) -> None:
    """PRD §2.6: available_balance_cents plus held_balance_cents equals
    lifetime_credited_cents minus lifetime_debited_cents."""
    available = seller["available_balance_cents"]
    held = seller["held_balance_cents"]
    credited = seller["lifetime_credited_cents"]
    debited = seller["lifetime_debited_cents"]
    for field, amount in (
        ("available_balance_cents", available),
        ("held_balance_cents", held),
        ("lifetime_credited_cents", credited),
        ("lifetime_debited_cents", debited),
    ):
        assert isinstance(amount, int) and not isinstance(amount, bool), (
            f"{field} must be an integer, got {amount!r}"
        )
        assert amount >= 0, f"{field} may never be negative, got {amount}"
    assert available + held == credited - debited, (
        f"funds identity broken: {available} + {held} != {credited} - {debited}"
    )


def assert_funds(seller: Dict[str, Any], available: Optional[int] = None,
                 held: Optional[int] = None, credited: Optional[int] = None,
                 debited: Optional[int] = None) -> None:
    if available is not None:
        assert_cents(seller["available_balance_cents"], available, "available_balance_cents")
    if held is not None:
        assert_cents(seller["held_balance_cents"], held, "held_balance_cents")
    if credited is not None:
        assert_cents(seller["lifetime_credited_cents"], credited, "lifetime_credited_cents")
    if debited is not None:
        assert_cents(seller["lifetime_debited_cents"], debited, "lifetime_debited_cents")
    assert_funds_identity(seller)


def assert_posture(seller: Dict[str, Any], enforcement_state: Optional[str] = None,
                   disbursement_state: Optional[str] = None,
                   severity_points_balance: Optional[str] = None) -> None:
    """PRD §2.5: the two posture dimensions are stored separately."""
    if enforcement_state is not None:
        assert seller["enforcement_state"] == enforcement_state, (
            f"expected enforcement_state {enforcement_state}, got {seller['enforcement_state']}"
        )
    if disbursement_state is not None:
        assert seller["disbursement_state"] == disbursement_state, (
            f"expected disbursement_state {disbursement_state}, "
            f"got {seller['disbursement_state']}"
        )
    if severity_points_balance is not None:
        assert_points(
            seller["severity_points_balance"], severity_points_balance,
            "severity_points_balance",
        )


def assert_notice(notice: Dict[str, Any], template_code: str,
                  related_entity_type: Optional[str] = None,
                  related_entity_id: Optional[str] = None,
                  state: Optional[str] = None) -> None:
    """PRD §2.11: a notice names itself with template_code and points at its row
    with the untyped related_entity_type / related_entity_id pair."""
    assert notice["template_code"] == template_code, (
        f"expected template_code {template_code}, got {notice['template_code']}"
    )
    if related_entity_type is not None:
        assert notice["related_entity_type"] == related_entity_type, (
            f"expected related_entity_type {related_entity_type}, "
            f"got {notice['related_entity_type']}"
        )
    if related_entity_id is not None:
        assert notice["related_entity_id"] == related_entity_id, (
            f"expected related_entity_id {related_entity_id}, "
            f"got {notice['related_entity_id']}"
        )
    if state is not None:
        assert notice["state"] == state, f"expected state {state}, got {notice['state']}"


def find_notice(notices: List[Dict[str, Any]], template_code: str,
                related_entity_id: Optional[str] = None) -> Dict[str, Any]:
    for notice in notices:
        if notice["template_code"] != template_code:
            continue
        if related_entity_id is not None and notice["related_entity_id"] != related_entity_id:
            continue
        return notice
    raise AssertionError(
        f"no {template_code} notice for {related_entity_id} in "
        f"{[(n['template_code'], n['related_entity_id']) for n in notices]}"
    )


def notices_for(notices: List[Dict[str, Any]], template_code: str) -> List[Dict[str, Any]]:
    return [n for n in notices if n["template_code"] == template_code]


def assert_nulls(row: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert row.get(field, None) is None, f"expected {field} to be null, got {row.get(field)!r}"
