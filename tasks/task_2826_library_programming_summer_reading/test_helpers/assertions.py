"""Domain assertion helpers.

These encode the invariants the PRD states once and every test then relies on:
the common-property set, the append-only reduced property set, money as integer
cents, percentages carrying exactly one decimal, and the three conservation
identities on programs, challenges and inventory lots.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonicalize_instant
from .types import (
    APPEND_ONLY_FIELD_NAMES,
    COMMON_FIELD_NAMES,
    SUPPLY_DRAW_LINE_FIELDS,
)


# --------------------------------------------------------------------------
# Rounding
# --------------------------------------------------------------------------
def round_half_up(value: float, digits: int = 0) -> float:
    """Round half away from zero, the rounding mode the PRD mandates.

    "the product is rounded to a whole number of cents using **round half up** (a
    value of exactly one half of a cent rounds away from zero)."
    """
    quantum = Decimal(1).scaleb(-digits)
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return float(result) if digits else int(result)


def expected_travel_fee_cents(round_trip_miles: int) -> int:
    """The two-band travel reimbursement for a contract's mileage.

    "the first 20 miles of the round trip are not reimbursed at all; mileage above
    20 and up to 60 forms the first billable band and pays 65 cents per mile;
    mileage above 60 forms the second band and pays 45 cents per mile."
    """
    band_one = max(0, min(round_trip_miles, 60) - 20)
    band_two = max(0, round_trip_miles - 60)
    return band_one * 65 + band_two * 45


# --------------------------------------------------------------------------
# Common properties
# --------------------------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every entity but the reading log entry carries all four common properties."""
    for field in COMMON_FIELD_NAMES:
        assert field in entity, f"missing common property '{field}': {entity}"
    assert is_valid_uuid(entity["id"]), (
        f"id must be a server-minted UUID with no prefix, got {entity['id']!r}"
    )
    assert_millisecond_instant(entity["created_at"], "created_at")
    assert_millisecond_instant(entity["updated_at"], "updated_at")
    assert isinstance(entity["version"], int) and entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_fields(entry: Dict[str, Any]) -> None:
    """A reading log entry carries only ``id`` and ``created_at``.

    "A reading log entry is an append-only ledger record: it carries `id` and
    `created_at`" and "it has **no** `updated_at` and **no** `version`, because an
    entry is never mutated."
    """
    for field in APPEND_ONLY_FIELD_NAMES:
        assert field in entry, f"missing property '{field}': {entry}"
    assert is_valid_uuid(entry["id"])
    assert_millisecond_instant(entry["created_at"], "created_at")
    assert "updated_at" not in entry, (
        "an append-only reading log entry must not publish 'updated_at'"
    )
    assert "version" not in entry, (
        "an append-only reading log entry must not publish 'version'"
    )


def assert_millisecond_instant(value: str, label: str = "instant") -> None:
    """An instant is ISO 8601 UTC with exactly three fractional second digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO 8601: {value!r}"
    assert value.endswith("Z"), f"{label} must be rendered in UTC with a Z suffix: {value!r}"
    fractional = value[:-1].split(".")
    assert len(fractional) == 2 and len(fractional[1]) == 3, (
        f"{label} must carry exactly three fractional second digits: {value!r}"
    )


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two instants by the moment they denote, not by their text width."""
    assert canonicalize_instant(actual) == canonicalize_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_date_equals(actual: Optional[str], expected: Optional[str], label: str = "date") -> None:
    """Compare calendar dates, which the PRD carries as plain YYYY-MM-DD text."""
    assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"


# --------------------------------------------------------------------------
# Money and percentages
# --------------------------------------------------------------------------
def assert_money_cents(value: Any, label: str = "money") -> None:
    """Money is an integer number of cents, never a string and never a float.

    "All money in this service is carried as **integer cents** in fields whose
    names end in `_cents`, and every such field is emitted as a JSON number, never
    a string."
    """
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r} ({type(value).__name__})"
    )


def assert_all_money_fields_are_integers(entity: Dict[str, Any]) -> None:
    """Every ``*_cents`` field on the payload is an integer."""
    for key, value in entity.items():
        if key.endswith("_cents") and value is not None:
            assert_money_cents(value, key)


def assert_one_decimal_pct(actual: Any, expected: float, label: str = "percentage") -> None:
    """A published percentage carries exactly one decimal place.

    "The three outcome-measurement percentages — `attendance_attainment_funder_pct`,
    `attendance_attainment_internal_pct` and `survey_response_rate_pct` — carry
    exactly **one** decimal place, also rounded half up."
    """
    assert actual is not None, f"{label} is missing"
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected}, got {actual}"
    )
    rendered = f"{float(actual):.10f}".rstrip("0")
    decimals = rendered.split(".")[1] if "." in rendered else ""
    assert len(decimals) <= 1, (
        f"{label} must carry at most one decimal place, got {actual}"
    )


# --------------------------------------------------------------------------
# Conservation identities
# --------------------------------------------------------------------------
def assert_materials_conservation(program: Dict[str, Any]) -> None:
    """"For a program, `materials_budget_cents` equals `materials_available_cents`
    plus `materials_committed_cents` plus `materials_spent_cents`."
    """
    total = (
        program["materials_available_cents"]
        + program["materials_committed_cents"]
        + program["materials_spent_cents"]
    )
    assert program["materials_budget_cents"] == total, (
        "materials cents identity broken: budget "
        f"{program['materials_budget_cents']} != available "
        f"{program['materials_available_cents']} + committed "
        f"{program['materials_committed_cents']} + spent "
        f"{program['materials_spent_cents']}"
    )


def assert_prize_conservation(challenge: Dict[str, Any]) -> None:
    """"For a reading challenge, `prize_budget_cents` equals
    `prize_available_cents` plus `prize_committed_cents` plus `prize_spent_cents`."
    """
    total = (
        challenge["prize_available_cents"]
        + challenge["prize_committed_cents"]
        + challenge["prize_spent_cents"]
    )
    assert challenge["prize_budget_cents"] == total, (
        "prize cents identity broken: budget "
        f"{challenge['prize_budget_cents']} != available "
        f"{challenge['prize_available_cents']} + committed "
        f"{challenge['prize_committed_cents']} + spent "
        f"{challenge['prize_spent_cents']}"
    )


def assert_lot_conservation(lot: Dict[str, Any]) -> None:
    """"For an inventory lot, `quantity_procured` equals `quantity_available` plus
    `quantity_reserved` plus `quantity_issued`, and `quantity_available` is never
    negative."
    """
    total = (
        lot["quantity_available"] + lot["quantity_reserved"] + lot["quantity_issued"]
    )
    assert lot["quantity_procured"] == total, (
        "lot unit identity broken: procured "
        f"{lot['quantity_procured']} != available {lot['quantity_available']}"
        f" + reserved {lot['quantity_reserved']}"
        f" + issued {lot['quantity_issued']}"
    )


def assert_lot_state(
    lot: Dict[str, Any],
    available: int,
    reserved: int,
    issued: int,
    status: Optional[str] = None,
) -> None:
    """Assert the whole unit split of a lot at once, with the identity."""
    assert lot["quantity_available"] == available, (
        f"quantity_available: expected {available}, got {lot['quantity_available']}"
    )
    assert lot["quantity_reserved"] == reserved, (
        f"quantity_reserved: expected {reserved}, got {lot['quantity_reserved']}"
    )
    assert lot["quantity_issued"] == issued, (
        f"quantity_issued: expected {issued}, got {lot['quantity_issued']}"
    )
    if status is not None:
        assert lot["status"] == status, (
            f"lot status: expected {status}, got {lot['status']}"
        )
    assert_lot_conservation(lot)


# --------------------------------------------------------------------------
# Program posture
# --------------------------------------------------------------------------
def assert_budget_variance_and_posture(
    program: Dict[str, Any], variance: int, posture: str
) -> None:
    """Variance is budget minus encumbrance and the posture follows its sign.

    "`budget_variance_cents` is the budget less the encumbrance, and it may go
    negative" and "`budget_posture` is `OVER_BUDGET` when the variance is strictly
    negative and `WITHIN_BUDGET` otherwise, so a variance of exactly 0 is
    `WITHIN_BUDGET`."
    """
    assert_money_cents(program["budget_variance_cents"], "budget_variance_cents")
    assert program["budget_variance_cents"] == variance, (
        f"budget_variance_cents: expected {variance}, got {program['budget_variance_cents']}"
    )
    assert program["budget_posture"] == posture, (
        f"budget_posture: expected {posture}, got {program['budget_posture']}"
    )
    derived_budget = (
        program["materials_budget_cents"] + program["presenter_fee_budget_cents"]
    )
    encumbrance = (
        program["materials_committed_cents"]
        + program["materials_spent_cents"]
        + program["presenter_fee_committed_cents"]
        + program["presenter_fee_spent_cents"]
    )
    assert program["budget_variance_cents"] == derived_budget - encumbrance, (
        "budget_variance_cents does not equal budget minus encumbrance"
    )
    expected_posture = (
        "OVER_BUDGET" if program["budget_variance_cents"] < 0 else "WITHIN_BUDGET"
    )
    assert program["budget_posture"] == expected_posture


def assert_program_status(
    program: Dict[str, Any],
    operational_status: Optional[str] = None,
    compliance_status: Optional[str] = None,
) -> None:
    """Assert one or both of the program's two independent status dimensions."""
    if operational_status is not None:
        assert program["operational_status"] == operational_status, (
            f"operational_status: expected {operational_status}, "
            f"got {program['operational_status']}"
        )
    if compliance_status is not None:
        assert program["compliance_status"] == compliance_status, (
            f"compliance_status: expected {compliance_status}, "
            f"got {program['compliance_status']}"
        )


# --------------------------------------------------------------------------
# Supply draw lines
# --------------------------------------------------------------------------
def assert_supply_draw_lines(
    program: Dict[str, Any], expected: Sequence[Dict[str, Any]]
) -> None:
    """Compare the draw lines in order, field by field.

    "For each contributing lot one entry is appended to the program's
    `supply_draw_lines`, recording the `lot_id`, the `units` taken, the lot's
    `unit_cost_cents`, a `surcharge_cents`, and a `line_total_cents`."
    """
    lines: List[Dict[str, Any]] = program["supply_draw_lines"]
    assert len(lines) == len(expected), (
        f"expected {len(expected)} supply draw line(s), got {len(lines)}: {lines}"
    )
    for index, (actual_line, expected_line) in enumerate(zip(lines, expected)):
        for field in SUPPLY_DRAW_LINE_FIELDS:
            assert field in actual_line, (
                f"supply draw line {index} is missing '{field}': {actual_line}"
            )
        for field, value in expected_line.items():
            assert actual_line[field] == value, (
                f"supply draw line {index} field '{field}': expected {value}, "
                f"got {actual_line[field]}"
            )
        assert (
            actual_line["line_total_cents"]
            == actual_line["units"] * actual_line["unit_cost_cents"]
            + actual_line["surcharge_cents"]
        ), f"supply draw line {index} total does not equal base plus surcharge"


def assert_award_pricing(
    award: Dict[str, Any],
    units: int,
    unit_cost_cents: int,
    transfer_surcharge_cents: int,
    status: str,
    lot_id: Optional[str] = None,
) -> None:
    """A reserved award's five money fields and its sourcing lot."""
    assert award["units"] == units, f"units: expected {units}, got {award['units']}"
    assert award["unit_cost_cents"] == unit_cost_cents
    assert award["line_cost_cents"] == units * unit_cost_cents, (
        "line_cost_cents must be units times unit_cost_cents"
    )
    assert award["transfer_surcharge_cents"] == transfer_surcharge_cents, (
        f"transfer_surcharge_cents: expected {transfer_surcharge_cents}, "
        f"got {award['transfer_surcharge_cents']}"
    )
    assert (
        award["award_total_cents"]
        == award["line_cost_cents"] + award["transfer_surcharge_cents"]
    ), "award_total_cents must be the line cost plus the transfer surcharge"
    assert award["status"] == status, (
        f"award status: expected {status}, got {award['status']}"
    )
    if lot_id is not None:
        assert award["lot_id"] == lot_id, (
            f"award lot_id: expected {lot_id}, got {award['lot_id']}"
        )


def assert_deferred_award(award: Dict[str, Any]) -> None:
    """A deferred award names no lot and books no money.

    "the award is still created, with `status` of `DEFERRED`, `lot_id` null, and
    `unit_cost_cents`, `line_cost_cents`, `transfer_surcharge_cents` and
    `award_total_cents` all 0."
    """
    assert award["status"] == "DEFERRED", (
        f"expected a DEFERRED award, got {award['status']}"
    )
    assert award["lot_id"] is None, "a deferred award must carry a null lot_id"
    for field in (
        "unit_cost_cents",
        "line_cost_cents",
        "transfer_surcharge_cents",
        "award_total_cents",
    ):
        assert award[field] == 0, f"a deferred award must carry {field} == 0"


# --------------------------------------------------------------------------
# Contract pricing
# --------------------------------------------------------------------------
def assert_contract_fee_breakdown(
    contract: Dict[str, Any],
    agreed_fee_cents: int,
    travel_fee_cents: int,
    escort_fee_cents: int,
    insurance_rider_fee_cents: int,
    weekend_premium_cents: int,
    total_fee_cents: int,
) -> None:
    """Assert the whole pricing ladder and that the parts sum to the total."""
    assert contract["agreed_fee_cents"] == agreed_fee_cents, (
        f"agreed_fee_cents: expected {agreed_fee_cents}, got {contract['agreed_fee_cents']}"
    )
    assert contract["travel_fee_cents"] == travel_fee_cents, (
        f"travel_fee_cents: expected {travel_fee_cents}, got {contract['travel_fee_cents']}"
    )
    assert contract["escort_fee_cents"] == escort_fee_cents, (
        f"escort_fee_cents: expected {escort_fee_cents}, got {contract['escort_fee_cents']}"
    )
    assert contract["insurance_rider_fee_cents"] == insurance_rider_fee_cents, (
        f"insurance_rider_fee_cents: expected {insurance_rider_fee_cents}, "
        f"got {contract['insurance_rider_fee_cents']}"
    )
    assert contract["weekend_premium_cents"] == weekend_premium_cents, (
        f"weekend_premium_cents: expected {weekend_premium_cents}, "
        f"got {contract['weekend_premium_cents']}"
    )
    assert contract["total_fee_cents"] == total_fee_cents, (
        f"total_fee_cents: expected {total_fee_cents}, got {contract['total_fee_cents']}"
    )
    subtotal = (
        agreed_fee_cents
        + travel_fee_cents
        + escort_fee_cents
        + insurance_rider_fee_cents
    )
    assert total_fee_cents == subtotal + weekend_premium_cents, (
        "total_fee_cents must be the pre-premium subtotal plus the weekend premium"
    )


def assert_fresh_contract(contract: Dict[str, Any]) -> None:
    """A newly drafted contract holds no negotiation history and no money."""
    assert contract["status"] == "DRAFT"
    assert contract["negotiation_round"] == 0
    assert contract["offered_fee_cents"] is None
    assert contract["countered_fee_cents"] is None
    assert contract["agreed_fee_cents"] is None
    for field in (
        "travel_fee_cents",
        "escort_fee_cents",
        "insurance_rider_fee_cents",
        "weekend_premium_cents",
        "total_fee_cents",
        "kill_fee_cents",
    ):
        assert contract[field] == 0, f"a fresh contract must carry {field} == 0"
    assert contract["offered_by_user_id"] is None
    assert contract["executed_by_user_id"] is None


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------
def assert_object_envelope(response) -> None:
    """A single-resource read declares ``response_type`` "object"."""
    body = response.json()
    assert body["response_type"] == "object", (
        f"expected response_type 'object', got {body['response_type']!r}"
    )
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must begin with 'req_', got {meta['api_request_id']!r}"
    )
    assert_millisecond_instant(meta["api_request_timestamp"], "api_request_timestamp")


def assert_error_payload_is_minimal(response) -> None:
    """An error body publishes only ``error_id`` and ``message`` under ``data``.

    "The `error_id` is a unique, machine-readable string that identifies the
    specific error." and "The `message` provides a human-readable explanation of
    what went wrong."
    """
    body = response.json()
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"an error payload must carry exactly error_id and message, got {sorted(body['data'])}"
    )
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        "an error envelope's meta must carry only api_request_id and "
        f"api_request_timestamp, got {sorted(meta)}"
    )
