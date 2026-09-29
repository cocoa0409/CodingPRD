"""Domain assertion helpers.

VALIDATOR CONVENTION -- decided once, used everywhere:
`validate_success(response, expected_status)` from the shared framework already
returns the INNER `data` payload, not the whole envelope. Every helper and every
test in this suite therefore treats its return value as the resource object and
never indexes `["data"]` on it again.

TIMESTAMP CONVENTION: PRD §2.4 renders instants "with three fractional digits".
Server-formatted instants are never compared by raw string equality; they are
canonicalised through `canonical_instant` first, so a server that emits
`2026-08-01T00:00:00Z`, `2026-08-01T00:00:00.0Z` or `2026-08-01T00:00:00.000Z`
compares equal.
"""

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .constants import (
    DP_DURATION,
    DP_MONEY,
    DP_PCT,
    DP_RATE,
    DP_UTILIZATION,
    DP_VARIANCE_PCT,
    DP_VOLUME,
    TOL_DURATION,
    TOL_MONEY,
    TOL_PCT,
    TOL_RATE,
    TOL_UTILIZATION,
    TOL_VARIANCE_PCT,
    TOL_VOLUME,
)

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$"
)


# ─── Instants ──────────────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant of any sub-second width."""
    assert isinstance(value, str), f"Expected an instant string, got {value!r}"
    m = _INSTANT_RE.match(value)
    assert m, f"Not an ISO 8601 UTC instant: {value!r}"
    frac = (m.group(5) or "0").ljust(6, "0")[:6]
    base = datetime(
        int(m.group(1)[0:4]),
        int(m.group(1)[5:7]),
        int(m.group(1)[8:10]),
        int(m.group(2)),
        int(m.group(3)),
        int(m.group(4)),
        int(frac),
        tzinfo=timezone.utc,
    )
    return base


def canonical_instant(value: str) -> str:
    """Render any accepted instant spelling as `YYYY-MM-DDTHH:MM:SS.mmmZ`."""
    dt = parse_instant(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def assert_instant_equals(actual: Optional[str], expected: str) -> None:
    """Compare two instants on canonical form rather than raw text."""
    assert actual is not None, f"Expected instant {expected}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Instant mismatch: expected {canonical_instant(expected)}, "
        f"got {canonical_instant(actual)} (raw {actual!r})"
    )


def assert_instant_plus_days(actual: str, origin: str, days: int) -> None:
    """Assert `actual` is exactly `origin` plus `days` days."""
    expected = parse_instant(origin) + timedelta(days=days)
    assert_instant_equals(
        actual, expected.strftime("%Y-%m-%dT%H:%M:%S.") + f"{expected.microsecond // 1000:03d}Z"
    )


def shift_instant(origin: str, **delta) -> str:
    """Return `origin` shifted by a timedelta, rendered in canonical form."""
    dt = parse_instant(origin) + timedelta(**delta)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def assert_iso_date(value: str) -> None:
    assert isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", value), (
        f"Not a YYYY-MM-DD calendar date: {value!r}"
    )


# ─── Numbers and precision ─────────────────────────────────────────────────

def _decimal_places(value: float) -> int:
    text = repr(float(value))
    if "e" in text or "E" in text:
        return 0
    if "." not in text:
        return 0
    return len(text.split(".")[1].rstrip("0"))


def assert_number(value: Any, field: str) -> float:
    """Assert a quantity arrived as a JSON number, never as a string."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {type(value).__name__} {value!r}"
    )
    return float(value)


def assert_decimal_places(value: Any, places: int, field: str) -> None:
    """Assert a numeric field carries at most `places` decimal places."""
    number = assert_number(value, field)
    assert _decimal_places(number) <= places, (
        f"{field} carries more than {places} decimal places: {number!r}"
    )


def assert_volume(actual: Any, expected: float, field: str = "volume") -> None:
    """3-decimal physical gas volume."""
    assert_decimal_places(actual, DP_VOLUME, field)
    assert float(actual) == pytest.approx(expected, abs=TOL_VOLUME), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_money(actual: Any, expected: float, field: str = "amount_usd") -> None:
    """2-decimal money, emitted as a JSON number."""
    assert_decimal_places(actual, DP_MONEY, field)
    assert float(actual) == pytest.approx(expected, abs=TOL_MONEY), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_rate(actual: Any, expected: float, field: str = "rate") -> None:
    """4-decimal per-dekatherm price."""
    assert_decimal_places(actual, DP_RATE, field)
    assert float(actual) == pytest.approx(expected, abs=TOL_RATE), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_pct(actual: Any, expected: float, field: str = "inventory_pct") -> None:
    """2-decimal percentage."""
    assert_decimal_places(actual, DP_PCT, field)
    assert float(actual) == pytest.approx(expected, abs=TOL_PCT), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_variance_pct(actual: Any, expected: float) -> None:
    """4-decimal variance percentage."""
    assert_decimal_places(actual, DP_VARIANCE_PCT, "variance_pct")
    assert float(actual) == pytest.approx(expected, abs=TOL_VARIANCE_PCT), (
        f"variance_pct: expected {expected}, got {actual}"
    )


def assert_utilization(actual: Any, expected: float) -> None:
    """6-decimal utilization ratio."""
    assert_decimal_places(actual, DP_UTILIZATION, "utilization_ratio")
    assert float(actual) == pytest.approx(expected, abs=TOL_UTILIZATION), (
        f"utilization_ratio: expected {expected}, got {actual}"
    )


def assert_duration_hours(actual: Any, expected: float) -> None:
    """4-decimal window length in hours."""
    assert_decimal_places(actual, DP_DURATION, "duration_hours")
    assert float(actual) == pytest.approx(expected, abs=TOL_DURATION), (
        f"duration_hours: expected {expected}, got {actual}"
    )


def assert_whole_dth(actual: Any, expected: int, field: str) -> None:
    """A whole-dekatherm integer quantity."""
    number = assert_number(actual, field)
    assert float(number).is_integer(), f"{field} must be a whole dekatherm, got {actual!r}"
    assert int(number) == expected, f"{field}: expected {expected}, got {actual}"


def round_half_up(value: float, places: int) -> float:
    """PRD §2.5 rounding: half away from zero at the stated decimal place."""
    factor = 10 ** places
    scaled = value * factor
    if scaled >= 0:
        return math.floor(scaled + 0.5) / factor
    return -math.floor(-scaled + 0.5) / factor


def truncate_toward_zero(value: float) -> int:
    """PRD §2.5: the allocation waterfall truncates toward zero."""
    return int(value)


# ─── Envelope shape ────────────────────────────────────────────────────────

def assert_common_fields(record: Dict[str, Any]) -> None:
    """PRD §2.4 common properties on a mutable record."""
    assert is_valid_uuid(record.get("id")), (
        f"id must be a server-minted UUID with no type prefix, got {record.get('id')!r}"
    )
    assert_timestamp_format(record["created_at"])
    assert_timestamp_format(record["updated_at"])
    assert isinstance(record.get("version"), int), "version must be an integer"
    assert record["version"] >= 1, "version begins at 1 on creation"


def assert_append_only_fields(record: Dict[str, Any]) -> None:
    """PRD §2.4: a ledger entry "carries only `id` and `created_at`; it has
    neither `updated_at` nor `version`, and those keys must be absent"."""
    assert is_valid_uuid(record.get("id")), f"id must be a UUID, got {record.get('id')!r}"
    assert_timestamp_format(record["created_at"])
    assert "updated_at" not in record, "updated_at must be absent from a ledger entry"
    assert "version" not in record, "version must be absent from a ledger entry"


def assert_envelope_meta(response) -> Dict[str, Any]:
    """PRD §2.2: `api_request_id` starts with `req_` and the timestamp carries
    three fractional digits."""
    body = response.json()
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    stamp = meta["api_request_timestamp"]
    assert is_iso8601_timestamp(stamp), f"Bad api_request_timestamp: {stamp!r}"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", stamp), (
        f"api_request_timestamp must carry three fractional digits, got {stamp!r}"
    )
    return meta


def assert_error_envelope(response, expected_error_id: str) -> Dict[str, Any]:
    """Assert an error envelope carrying the expected identifier, its catalogue
    status, and the required meta fields."""
    data = validate_error(response, expected_error_id)
    assert_envelope_meta(response)
    return data


def assert_created(response) -> Dict[str, Any]:
    """A create returns 201 and carries the created record in `data`."""
    data = validate_success(response, 201)
    assert response.json()["response_type"] == "object"
    return data


def assert_ok(response) -> Dict[str, Any]:
    """Every non-create success returns 200 with the affected record."""
    return validate_success(response, 200)


def assert_list(response, expected_ids: Optional[List[str]] = None):
    """Validate a list envelope and optionally pin its exact id ordering."""
    rows, meta = validate_paginated(response)
    if expected_ids is not None:
        assert [r["id"] for r in rows] == expected_ids, (
            f"List order mismatch: expected {expected_ids}, got {[r['id'] for r in rows]}"
        )
    return rows, meta


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    """PRD §2.4/§2.2: "all lists are ordered by `created_at` ascending"."""
    stamps = [parse_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), f"Rows are not in created_at ASC order: {stamps}"


# ─── Domain records ────────────────────────────────────────────────────────

def assert_field_derived_block(
    field: Dict[str, Any],
    *,
    working_gas: Optional[float] = None,
    inventory_pct: Optional[float] = None,
    pressure: Optional[int] = None,
    tier: Optional[str] = None,
    injection_rate: Optional[int] = None,
    withdrawal_rate: Optional[int] = None,
    wells_in_service: Optional[int] = None,
    posture: Optional[str] = None,
) -> None:
    """Assert any subset of the reservoir's server-derived block in one call."""
    if working_gas is not None:
        assert_volume(field["working_gas_inventory_dth"], working_gas,
                      "working_gas_inventory_dth")
    if inventory_pct is not None:
        assert_pct(field["inventory_pct"], inventory_pct, "inventory_pct")
    if pressure is not None:
        assert field["current_pressure_psig"] == pressure, (
            f"current_pressure_psig: expected {pressure}, "
            f"got {field['current_pressure_psig']}"
        )
    if tier is not None:
        assert field["deliverability_tier"] == tier, (
            f"deliverability_tier: expected {tier}, got {field['deliverability_tier']}"
        )
    if injection_rate is not None:
        assert field["max_injection_rate_dth_per_day"] == injection_rate, (
            f"max_injection_rate_dth_per_day: expected {injection_rate}, "
            f"got {field['max_injection_rate_dth_per_day']}"
        )
    if withdrawal_rate is not None:
        assert field["max_withdrawal_rate_dth_per_day"] == withdrawal_rate, (
            f"max_withdrawal_rate_dth_per_day: expected {withdrawal_rate}, "
            f"got {field['max_withdrawal_rate_dth_per_day']}"
        )
    if wells_in_service is not None:
        assert field["wells_in_service_count"] == wells_in_service, (
            f"wells_in_service_count: expected {wells_in_service}, "
            f"got {field['wells_in_service_count']}"
        )
    if posture is not None:
        assert field["field_posture"] == posture, (
            f"field_posture: expected {posture}, got {field['field_posture']}"
        )


def assert_ticket_charges(
    ticket: Dict[str, Any],
    *,
    fuel_retention: float,
    net_volume: float,
    commodity: float,
    discount: float,
    fuel_charge: float,
    total: float,
) -> None:
    """Assert the six pinned figures of the ticket charge breakdown."""
    assert_volume(ticket["fuel_retention_dth"], fuel_retention, "fuel_retention_dth")
    assert_volume(ticket["net_volume_dth"], net_volume, "net_volume_dth")
    assert_money(ticket["commodity_charge_usd"], commodity, "commodity_charge_usd")
    assert_money(ticket["volume_discount_usd"], discount, "volume_discount_usd")
    assert_money(ticket["fuel_charge_usd"], fuel_charge, "fuel_charge_usd")
    assert_money(ticket["total_charge_usd"], total, "total_charge_usd")


def assert_ticket_charges_unpriced(ticket: Dict[str, Any]) -> None:
    """A ticket that has not been confirmed carries every charge field null."""
    for field in (
        "fuel_retention_dth",
        "net_volume_dth",
        "commodity_charge_usd",
        "volume_discount_usd",
        "fuel_charge_usd",
        "total_charge_usd",
        "confirmed_at",
    ):
        assert ticket[field] is None, f"{field} must be null on an unconfirmed ticket"


def assert_ledger_entry(
    entry: Dict[str, Any],
    *,
    entry_type: str,
    volume_dth: Optional[float] = None,
    amount_usd: Optional[float] = None,
    gas_day: Optional[str] = "__unset__",
) -> None:
    """Assert one append-only balancing ledger row."""
    assert_append_only_fields(entry)
    assert entry["entry_type"] == entry_type, (
        f"entry_type: expected {entry_type}, got {entry['entry_type']}"
    )
    if volume_dth is not None:
        assert_volume(entry["volume_dth"], volume_dth, "volume_dth")
    if amount_usd is not None:
        assert_money(entry["amount_usd"], amount_usd, "amount_usd")
    if gas_day != "__unset__":
        assert entry["gas_day"] == gas_day, (
            f"gas_day: expected {gas_day}, got {entry['gas_day']}"
        )


def assert_version_bumped_by(new_version: int, old_version: int, delta: int) -> None:
    """Assert a record's version moved by exactly `delta`."""
    assert new_version == old_version + delta, (
        f"Expected version {old_version} + {delta} = {old_version + delta}, "
        f"got {new_version}"
    )
