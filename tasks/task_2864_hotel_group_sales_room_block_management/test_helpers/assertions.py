"""Per-entity and per-invariant assertions.

Every helper here restates a rule the PRD states, so a failure message names
the contract clause that was broken rather than a bare value mismatch.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant

# --------------------------------------------------------------------------
# Generic building blocks
# --------------------------------------------------------------------------

_MINTED_INSTANT_LEN = len("2026-08-01T00:00:00.000Z")


def round_half_up(value: Any) -> int:
    """Round to whole cents the way PRD 2.6 mandates.

    "Wherever a monetary result must be rounded, the method is round half up:
    a value exactly on the half-cent boundary rounds away from zero."
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def assert_fields(data: Dict[str, Any], entity: str, **expected: Any) -> None:
    """Compare the named properties of a resource body one by one.

    Percentage-typed properties are JSON fractions rather than whole cents
    (PRD 2.6), so a float expectation is compared within a tolerance far
    tighter than any rate the domain distinguishes.
    """
    for field, want in expected.items():
        assert field in data, f"{entity} response is missing '{field}': {data}"
        got = data[field]
        if isinstance(want, float) and isinstance(got, (int, float)):
            assert abs(float(got) - want) < 1e-9, (
                f"{entity}.{field}: expected {want!r}, got {got!r}"
            )
            continue
        assert got == want, (
            f"{entity}.{field}: expected {want!r}, got {got!r}"
        )


def assert_money_fields_are_integers(data: Dict[str, Any], entity: str) -> None:
    """PRD 2.6: "Every field whose name ends in _cents is an integer"."""
    for field, value in data.items():
        if field.endswith("_cents") and value is not None:
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{entity}.{field} must be a whole-cent JSON integer, got {value!r}"
            )


def assert_minted_instant(value: Optional[str], field: str = "instant") -> None:
    """PRD 2.5 / 2.4: server-minted instants carry three fractional digits."""
    assert isinstance(value, str), f"{field} must be an ISO 8601 string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} is not ISO 8601 UTC: {value!r}"
    assert len(value) == _MINTED_INSTANT_LEN and value.endswith("Z") and "." in value, (
        f"{field} must be rendered with three fractional digits, got {value!r}"
    )
    assert len(value.split(".")[1]) == 4, (
        f"{field} must carry exactly three fractional digits, got {value!r}"
    )


def assert_instant_equals(actual: Optional[str], expected: str, field: str) -> None:
    """Compare two instants irrespective of fractional-digit width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field}: expected instant {expected!r}, got {actual!r}"
    )


def assert_common_resource_properties(data: Dict[str, Any], entity: str) -> None:
    """PRD 2.5: id / created_at / updated_at / version on every resource."""
    assert is_valid_uuid(data.get("id")), (
        f"{entity}.id must be a server-minted UUID with no type prefix, "
        f"got {data.get('id')!r}"
    )
    assert_minted_instant(data.get("created_at"), f"{entity}.created_at")
    assert_minted_instant(data.get("updated_at"), f"{entity}.updated_at")
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{entity}.version must be an integer starting at 1, got {version!r}"
    )
    assert_money_fields_are_integers(data, entity)


def assert_error_envelope(body: Dict[str, Any]) -> None:
    """PRD 2.2: the error envelope carries only meta, response_type and data."""
    assert body.get("response_type") == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        "error envelope must carry meta.api_request_id"
    )
    assert isinstance(meta.get("api_request_timestamp"), str), (
        "error envelope must carry meta.api_request_timestamp"
    )
    payload = body.get("data") or {}
    assert set(payload.keys()) <= {"error_id", "message"}, (
        f"error data must carry only error_id and message, got {sorted(payload)}"
    )
    assert payload.get("message", "").strip(), "error message must be non-empty"


def assert_no_pagination_meta(body: Dict[str, Any]) -> None:
    """PRD 2.2: pagination fields are included for list endpoints only."""
    meta = body.get("meta") or {}
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, (
            f"a single-object read must not carry meta.{field}: {meta}"
        )


def assert_pagination_meta(
    meta: Dict[str, Any],
    *,
    total_count: int,
    has_more: bool,
    limit: int,
    offset: int,
) -> None:
    """PRD 2.3: every list response carries the four pagination figures."""
    assert_fields(
        meta, "meta",
        total_count=total_count, has_more=has_more, limit=limit, offset=offset,
    )


def assert_ascending(values: Iterable[Any], label: str) -> None:
    items = list(values)
    assert items == sorted(items), f"{label} must be ordered ascending, got {items}"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------


def assert_group_account(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "GroupAccount")
    assert_fields(data, "GroupAccount", **expected)


def assert_inventory_day(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "InventoryDay")
    assert_fields(data, "InventoryDay", **expected)


def assert_concession_package(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "ConcessionPackage")
    assert_fields(data, "ConcessionPackage", **expected)


def assert_lead(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "Lead")
    assert_fields(data, "Lead", **expected)


def assert_displacement_analysis(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "DisplacementAnalysis")
    assert_fields(data, "DisplacementAnalysis", **expected)


def assert_rate_quote(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "RateQuote")
    assert_fields(data, "RateQuote", **expected)


def assert_group_contract(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "GroupContract")
    assert_fields(data, "GroupContract", **expected)


def assert_room_block(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "RoomBlock")
    assert_fields(data, "RoomBlock", **expected)


def assert_block_night(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "BlockNight")
    assert_fields(data, "BlockNight", **expected)


def assert_reservation(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "Reservation")
    assert_fields(data, "Reservation", **expected)


def assert_ancillary_charge(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "AncillaryCharge")
    assert_fields(data, "AncillaryCharge", **expected)


def assert_reconciliation(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "Reconciliation")
    assert_fields(data, "Reconciliation", **expected)


def assert_function_space_hold(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_resource_properties(data, "FunctionSpaceHold")
    assert_fields(data, "FunctionSpaceHold", **expected)


def assert_pickup_summary(data: Dict[str, Any], **expected: Any) -> None:
    assert_money_fields_are_integers(data, "PickupSummary")
    assert_fields(data, "PickupSummary", **expected)


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------


def assert_night_conservation(night: Dict[str, Any]) -> None:
    """PRD 3.6: the conserved quantity of a night.

    "allotted rooms are always exactly the sum of sub-allocated, picked up,
    released and open rooms".
    """
    total = (
        night["rooms_sub_allocated"]
        + night["rooms_picked_up"]
        + night["rooms_released"]
        + night["rooms_open"]
    )
    assert night["rooms_allotted"] == total, (
        f"night {night.get('stay_date')} breaks room conservation: "
        f"allotted {night['rooms_allotted']} != sub {night['rooms_sub_allocated']} "
        f"+ picked {night['rooms_picked_up']} + released {night['rooms_released']} "
        f"+ open {night['rooms_open']}"
    )


def assert_nights_conserved(nights: List[Dict[str, Any]]) -> None:
    for night in nights:
        assert_night_conservation(night)


def assert_receivable_identity(contract: Dict[str, Any]) -> None:
    """PRD 3.8: receivable_total_cents is a conserved ledger identity.

    "receivable_total_cents is then ancillary_posted_cents plus the
    contract's assessed_damages_cents less its rebate_paid_cents."
    """
    expected = (
        contract["ancillary_posted_cents"]
        + contract["assessed_damages_cents"]
        - contract["rebate_paid_cents"]
    )
    assert contract["receivable_total_cents"] == expected, (
        f"receivable_total_cents {contract['receivable_total_cents']} does not equal "
        f"posted {contract['ancillary_posted_cents']} + damages "
        f"{contract['assessed_damages_cents']} - rebate "
        f"{contract['rebate_paid_cents']}"
    )


def assert_waterfall_identities(recon: Dict[str, Any]) -> None:
    """PRD 3.9: the six waterfall steps each consume the previous output."""
    assert recon["gross_settlement_cents"] == (
        recon["attrition_damages_cents"] + recon["ancillary_net_cents"]
    ), "step 1: gross_settlement_cents must be damages plus ancillary net"
    assert recon["net_before_incentive_cents"] == (
        recon["gross_settlement_cents"] - recon["rebate_payable_cents"]
    ), "step 3: net_before_incentive_cents must be gross less the rebate payable"
    assert recon["total_settlement_cents"] == (
        recon["net_before_incentive_cents"] - recon["rebooking_incentive_cents"]
    ), "step 6: total_settlement_cents must be net_before_incentive less the incentive"


def assert_version_advanced(before: int, after: int, rows: int = 1) -> None:
    """PRD 2.5: version "increments by exactly 1 on every mutation"."""
    assert after == before + rows, (
        f"expected version {before} + {rows}, got {after}"
    )
