"""Domain-specific assertion helpers layered over the shared envelope validators."""

from typing import Any, Dict, List, Optional

import pytest
import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

#: Tolerance for a figure the contract rounds to two decimal places.
CENTI_TOLERANCE = 0.005
#: Tolerance for a figure the contract rounds to four decimal places.
MICRO_TOLERANCE = 0.00005
#: Tolerance for a figure the contract rounds to one decimal place.
DECI_TOLERANCE = 0.05


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries a bare UUID identifier, both timestamps and a version."""
    assert is_valid_uuid(row["id"]), f"id must be a bare UUID, got {row['id']!r}"
    assert "_" not in row["id"], f"id must carry no type prefix, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int)
    assert row["version"] >= 1
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_envelope_meta(response: requests.Response, response_type: str = "object") -> dict:
    """Assert the success envelope's shape, including the request identifier prefix."""
    body = response.json()
    assert body["response_type"] == response_type, body["response_type"]
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta["api_request_timestamp"]
    return body


def assert_millisecond_precision(value: str) -> None:
    """A returned instant carries exactly three fractional-second digits."""
    assert value.endswith("Z"), f"expected a UTC instant, got {value!r}"
    assert "." in value, f"expected fractional seconds in {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"expected exactly three fractional digits in {value!r}, got {len(fraction)}"
    )


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Two UTC instants name the same moment, whatever fractional width each carries.

    Returned instants carry three fractional-second digits while the instants supplied
    on requests are written to the second, so the comparison is made on the shared
    second-resolution prefix rather than on the rendered text.
    """
    assert isinstance(actual, str), f"{label}: expected an instant, got {actual!r}"
    assert actual.endswith("Z"), f"{label}: expected a UTC instant, got {actual!r}"
    assert actual.split(".")[0].rstrip("Z") == expected.split(".")[0].rstrip("Z"), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_single_read_omits_pagination(response: requests.Response) -> dict:
    """A single-resource read carries none of the four listing controls."""
    body = response.json()
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in body["meta"], f"single read must omit meta.{key}"
    return body["data"]


def assert_error_envelope_is_minimal(response: requests.Response) -> None:
    """An error envelope's data holds only the identifier and the message."""
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}, body["data"].keys()
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in body["meta"], f"error envelope must omit meta.{key}"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        body["meta"].keys()
    )


def assert_page(
    response: requests.Response,
    expected_rows: int,
    expected_total: int,
    expected_has_more: bool,
) -> List[dict]:
    """Assert a listing's window size, its pre-window total and its continuation flag."""
    rows, meta = validate_paginated(response)
    assert len(rows) == expected_rows, f"expected {expected_rows} rows, got {len(rows)}"
    assert meta["total_count"] == expected_total, (
        f"expected total_count {expected_total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is expected_has_more, (
        f"expected has_more {expected_has_more}, got {meta['has_more']}"
    )
    return rows


def assert_total_count(response: requests.Response, expected_total: int) -> List[dict]:
    """Assert only a listing's pre-window total."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        f"expected total_count {expected_total}, got {meta['total_count']}"
    )
    return rows


def assert_cents(actual: Any, expected: int, label: str = "cents figure") -> None:
    """A cents figure is an exact integer, never a string and never a float."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {type(actual).__name__}: {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_two_dp(actual: Any, expected: float, label: str = "figure") -> None:
    """A figure the contract rounds half up to two decimal places."""
    assert actual == pytest.approx(expected, abs=CENTI_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_four_dp(actual: Any, expected: float, label: str = "figure") -> None:
    """A figure the contract rounds half up to four decimal places."""
    assert actual == pytest.approx(expected, abs=MICRO_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_one_dp(actual: Any, expected: float, label: str = "figure") -> None:
    """A figure the contract rounds half up to one decimal place."""
    assert actual == pytest.approx(expected, abs=DECI_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_turbine_dimensions(
    turbine: Dict[str, Any],
    availability_state: Optional[str] = None,
    curtailment_state: Optional[str] = None,
) -> None:
    """Assert the two independent turbine dimensions separately."""
    if availability_state is not None:
        assert turbine["availability_state"] == availability_state, (
            f"expected availability_state {availability_state}, "
            f"got {turbine['availability_state']}"
        )
    if curtailment_state is not None:
        assert turbine["curtailment_state"] == curtailment_state, (
            f"expected curtailment_state {curtailment_state}, "
            f"got {turbine['curtailment_state']}"
        )


def assert_farm_ledger_conserved(farm: Dict[str, Any]) -> None:
    """The farm's accrued opex equals the sum of its four component buckets."""
    parts = (
        farm["landowner_payable_cents"]
        + farm["road_maintenance_reserve_cents"]
        + farm["community_fund_balance_cents"]
        + farm["maintenance_spend_cents"]
    )
    assert farm["opex_accrued_cents"] == parts, (
        f"opex_accrued_cents {farm['opex_accrued_cents']} != "
        f"landowner_payable {farm['landowner_payable_cents']} + "
        f"road_reserve {farm['road_maintenance_reserve_cents']} + "
        f"community_fund {farm['community_fund_balance_cents']} + "
        f"maintenance_spend {farm['maintenance_spend_cents']}"
    )


def assert_farm_buckets(
    farm: Dict[str, Any],
    opex_accrued_cents: Optional[int] = None,
    landowner_payable_cents: Optional[int] = None,
    road_maintenance_reserve_cents: Optional[int] = None,
    community_fund_balance_cents: Optional[int] = None,
    maintenance_spend_cents: Optional[int] = None,
) -> None:
    """Assert individual farm ledger buckets and always re-check the identity."""
    expectations = {
        "opex_accrued_cents": opex_accrued_cents,
        "landowner_payable_cents": landowner_payable_cents,
        "road_maintenance_reserve_cents": road_maintenance_reserve_cents,
        "community_fund_balance_cents": community_fund_balance_cents,
        "maintenance_spend_cents": maintenance_spend_cents,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert_cents(farm[field], expected, f"farm.{field}")
    assert_farm_ledger_conserved(farm)


def assert_spare_part_units_conserved(part: Dict[str, Any]) -> None:
    """A spare part's accounted total equals on-hand plus reserved plus consumed."""
    parts = part["quantity_on_hand"] + part["quantity_reserved"] + part["quantity_consumed"]
    assert part["total_units_accounted"] == parts, (
        f"total_units_accounted {part['total_units_accounted']} != "
        f"on_hand {part['quantity_on_hand']} + reserved {part['quantity_reserved']} + "
        f"consumed {part['quantity_consumed']}"
    )


def assert_stock_line(
    part: Dict[str, Any],
    on_hand: int,
    reserved: int,
    consumed: int,
    total: int,
    status: Optional[str] = None,
    procurement_flag: Optional[bool] = None,
) -> None:
    """Assert a spare part's full stock line and its derived status."""
    assert part["quantity_on_hand"] == on_hand, (
        f"expected quantity_on_hand {on_hand}, got {part['quantity_on_hand']}"
    )
    assert part["quantity_reserved"] == reserved, (
        f"expected quantity_reserved {reserved}, got {part['quantity_reserved']}"
    )
    assert part["quantity_consumed"] == consumed, (
        f"expected quantity_consumed {consumed}, got {part['quantity_consumed']}"
    )
    assert part["total_units_accounted"] == total, (
        f"expected total_units_accounted {total}, got {part['total_units_accounted']}"
    )
    assert_spare_part_units_conserved(part)
    if status is not None:
        assert part["status"] == status, f"expected status {status}, got {part['status']}"
    if procurement_flag is not None:
        assert part["procurement_flag"] is procurement_flag, (
            f"expected procurement_flag {procurement_flag}, got {part['procurement_flag']}"
        )


def assert_crane_costs(
    crane: Dict[str, Any],
    lift_days: Optional[int] = None,
    standby_days: Optional[int] = None,
    billable_days: Optional[int] = None,
    subtotal_cents: Optional[int] = None,
    volume_credit_cents: Optional[int] = None,
    total_crane_cost_cents: Optional[int] = None,
) -> None:
    """Assert the crane's six repriced cost figures."""
    if lift_days is not None:
        assert crane["lift_days"] == lift_days, (
            f"expected lift_days {lift_days}, got {crane['lift_days']}"
        )
    if standby_days is not None:
        assert crane["standby_days"] == standby_days, (
            f"expected standby_days {standby_days}, got {crane['standby_days']}"
        )
    if billable_days is not None:
        assert crane["billable_days"] == billable_days, (
            f"expected billable_days {billable_days}, got {crane['billable_days']}"
        )
    if subtotal_cents is not None:
        assert_cents(crane["subtotal_cents"], subtotal_cents, "crane.subtotal_cents")
    if volume_credit_cents is not None:
        assert_cents(
            crane["volume_credit_cents"], volume_credit_cents, "crane.volume_credit_cents"
        )
    if total_crane_cost_cents is not None:
        assert_cents(
            crane["total_crane_cost_cents"],
            total_crane_cost_cents,
            "crane.total_crane_cost_cents",
        )
    if subtotal_cents is not None and volume_credit_cents is not None:
        assert crane["total_crane_cost_cents"] == (
            crane["subtotal_cents"] - crane["volume_credit_cents"]
        ), "total_crane_cost_cents must be the subtotal less the volume credit"


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """A rejected request writes nothing, so the row's version must not advance."""
    assert after["version"] == before["version"], (
        f"expected version to stay {before['version']}, got {after['version']}"
    )


def assert_version_advanced_by(
    before: Dict[str, Any], after: Dict[str, Any], steps: int = 1
) -> None:
    """A mutation advances the row's version by exactly the given number of steps."""
    assert after["version"] == before["version"] + steps, (
        f"expected version {before['version'] + steps}, got {after['version']}"
    )


def data_of(response: requests.Response, expected_status: int = 200) -> dict:
    """Validate the envelope and return the resource payload."""
    return validate_success(response, expected_status)


def created(response: requests.Response) -> dict:
    """Validate a creation envelope, which the contract answers with 201."""
    return validate_success(response, 201)
