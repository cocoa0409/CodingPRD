"""Domain assertions over entity bodies.

The helpers keep two rules in one place:

* money and rate fields must arrive as JSON numbers, never as strings;
* instant fields are compared after sub-second canonicalisation, so a differing
  fractional width cannot masquerade as a wrong timestamp.
"""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import BPS_DENOMINATOR

# ------------------------------------------------------------ field shapes


def assert_money(entity: Dict[str, Any], field: str, expected: Optional[int] = None) -> None:
    """Assert a money field is an integer count of cents, optionally equal to a value."""
    assert field in entity, f"missing money field {field!r} in {sorted(entity)}"
    value = entity[field]
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a JSON integer number of cents, got {value!r}"
    )
    if expected is not None:
        assert value == expected, f"{field}: expected {expected} cents, got {value}"


def assert_bps(entity: Dict[str, Any], field: str, expected: Optional[int] = None) -> None:
    """Assert a rate field is an integer count of basis points."""
    assert field in entity, f"missing rate field {field!r} in {sorted(entity)}"
    value = entity[field]
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a JSON integer number of basis points, got {value!r}"
    )
    assert 0 <= value <= BPS_DENOMINATOR or field.endswith("_per_year"), (
        f"{field} out of basis-point range: {value}"
    )
    if expected is not None:
        assert value == expected, f"{field}: expected {expected} bps, got {value}"


def assert_instant(entity: Dict[str, Any], field: str, expected: Optional[str] = None) -> None:
    """Assert an instant field is a well-formed ISO-8601 UTC instant."""
    value = entity.get(field)
    assert is_iso8601_timestamp(value), f"{field} is not an ISO-8601 UTC instant: {value!r}"
    if expected is not None:
        assert canonical_instant(value) == canonical_instant(expected), (
            f"{field}: expected {expected}, got {value}"
        )


def assert_calendar_date(entity: Dict[str, Any], field: str, expected: Optional[str] = None) -> None:
    """Assert a calendar-date field is a bare YYYY-MM-DD string with no time part."""
    value = entity.get(field)
    assert isinstance(value, str), f"{field} must be a string date, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be a plain YYYY-MM-DD calendar date, got {value!r}"
    )
    if expected is not None:
        assert value == expected, f"{field}: expected {expected}, got {value}"


def assert_instants_equal(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two instants ignoring sub-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


# --------------------------------------------------------- common fields


def assert_common_fields(entity: Dict[str, Any]) -> None:
    """Assert the four properties every entity but the verification check carries."""
    assert is_valid_uuid(entity.get("id")), f"id is not a UUID: {entity.get('id')!r}"
    assert_instant(entity, "created_at")
    assert_instant(entity, "updated_at")
    version = entity.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"version must be an integer starting at 1, got {version!r}"
    )


def assert_event_row_fields(entity: Dict[str, Any]) -> None:
    """Assert the reduced property set of an immutable event row.

    A verification check is the single entity that carries an identifier and a
    creation instant only: it has no update instant and no version because it is
    never modified after insertion.
    """
    assert is_valid_uuid(entity.get("id")), f"id is not a UUID: {entity.get('id')!r}"
    assert_instant(entity, "created_at")
    assert "updated_at" not in entity, "an immutable event row must not carry updated_at"
    assert "version" not in entity, "an immutable event row must not carry version"


# --------------------------------------------------------------- entities


def assert_parcel_decomposition(
    parcel: Dict[str, Any],
    assessed_value_cents: int,
    exempt_value_cents: int,
    taxable_value_cents: int,
    exemption_status: str,
) -> None:
    """Assert a parcel's four-part valuation and its posture, including the identity."""
    assert_money(parcel, "assessed_value_cents", assessed_value_cents)
    assert_money(parcel, "exempt_value_cents", exempt_value_cents)
    assert_money(parcel, "taxable_value_cents", taxable_value_cents)
    assert parcel["exempt_value_cents"] + parcel["taxable_value_cents"] == parcel[
        "assessed_value_cents"
    ], (
        "exempt plus taxable must equal assessed: "
        f"{parcel['exempt_value_cents']} + {parcel['taxable_value_cents']} != "
        f"{parcel['assessed_value_cents']}"
    )
    assert parcel.get("exemption_status") == exemption_status, (
        f"exemption_status: expected {exemption_status}, got {parcel.get('exemption_status')}"
    )


def assert_grant(
    grant: Dict[str, Any],
    benefit_status: Optional[str] = None,
    benefit_amount_cents: Optional[int] = None,
    applied_exempt_value_cents: Optional[int] = None,
    relief_multiplier_bps: Optional[int] = None,
    suspension_reason: Optional[str] = "__unset__",
    frozen_value_cents: Optional[int] = "__unset__",
    portable_balance_cents: Optional[int] = "__unset__",
) -> None:
    """Assert the fields of an exemption grant that a test names explicitly."""
    if benefit_status is not None:
        assert grant.get("benefit_status") == benefit_status, (
            f"benefit_status: expected {benefit_status}, got {grant.get('benefit_status')}"
        )
    if benefit_amount_cents is not None:
        assert_money(grant, "benefit_amount_cents", benefit_amount_cents)
    if applied_exempt_value_cents is not None:
        assert_money(grant, "applied_exempt_value_cents", applied_exempt_value_cents)
    if relief_multiplier_bps is not None:
        assert_bps(grant, "relief_multiplier_bps", relief_multiplier_bps)
    if suspension_reason != "__unset__":
        assert grant.get("suspension_reason") == suspension_reason, (
            f"suspension_reason: expected {suspension_reason}, "
            f"got {grant.get('suspension_reason')}"
        )
    if frozen_value_cents != "__unset__":
        if frozen_value_cents is None:
            assert grant.get("frozen_value_cents") is None, (
                f"frozen_value_cents must be null, got {grant.get('frozen_value_cents')}"
            )
        else:
            assert_money(grant, "frozen_value_cents", frozen_value_cents)
    if portable_balance_cents != "__unset__":
        if portable_balance_cents is None:
            assert grant.get("portable_balance_cents") is None, (
                "portable_balance_cents must be null, got "
                f"{grant.get('portable_balance_cents')}"
            )
        else:
            assert_money(grant, "portable_balance_cents", portable_balance_cents)


def assert_taxpayer_ledger(
    account: Dict[str, Any],
    lifetime_refund_cents: Optional[int] = None,
    lifetime_recovery_collected_cents: Optional[int] = None,
    net_relief_cents: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    """Assert the taxpayer money ledger, including the derived net relief identity."""
    if lifetime_refund_cents is not None:
        assert_money(account, "lifetime_refund_cents", lifetime_refund_cents)
    if lifetime_recovery_collected_cents is not None:
        assert_money(
            account, "lifetime_recovery_collected_cents", lifetime_recovery_collected_cents
        )
    if net_relief_cents is not None:
        assert account.get("net_relief_cents") == net_relief_cents, (
            f"net_relief_cents: expected {net_relief_cents}, "
            f"got {account.get('net_relief_cents')}"
        )
    assert (
        account["net_relief_cents"]
        == account["lifetime_refund_cents"] - account["lifetime_recovery_collected_cents"]
    ), (
        "net relief must equal lifetime refunds less lifetime recoveries: "
        f"{account['net_relief_cents']} != {account['lifetime_refund_cents']} - "
        f"{account['lifetime_recovery_collected_cents']}"
    )
    if status is not None:
        assert account.get("status") == status, (
            f"account status: expected {status}, got {account.get('status')}"
        )


def assert_recovery_assessment(
    case: Dict[str, Any],
    back_tax_cents: Optional[int] = None,
    penalty_cents: Optional[int] = None,
    interest_cents: Optional[int] = None,
    total_assessed_cents: Optional[int] = None,
    recovery_paid_cents: Optional[int] = None,
) -> None:
    """Assert a fraud case's frozen recovery ledger and its summation identity."""
    if back_tax_cents is not None:
        assert_money(case, "back_tax_cents", back_tax_cents)
    if penalty_cents is not None:
        assert_money(case, "penalty_cents", penalty_cents)
    if interest_cents is not None:
        assert_money(case, "interest_cents", interest_cents)
    if total_assessed_cents is not None:
        assert_money(case, "total_assessed_cents", total_assessed_cents)
    assert (
        case["total_assessed_cents"]
        == case["back_tax_cents"] + case["penalty_cents"] + case["interest_cents"]
    ), (
        "total assessed must equal back tax plus penalty plus interest: "
        f"{case['total_assessed_cents']} != {case['back_tax_cents']} + "
        f"{case['penalty_cents']} + {case['interest_cents']}"
    )
    if recovery_paid_cents is not None:
        assert_money(case, "recovery_paid_cents", recovery_paid_cents)


def assert_claim_amounts(
    claim: Dict[str, Any],
    gross_refund_cents: Optional[int] = None,
    offset_applied_cents: Optional[int] = None,
    net_refund_cents: Optional[int] = None,
    refund_interest_cents: Optional[int] = None,
    total_payable_cents: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    """Assert a retroactive claim's money fields and the payable summation."""
    if gross_refund_cents is not None:
        assert_money(claim, "gross_refund_cents", gross_refund_cents)
    if offset_applied_cents is not None:
        assert_money(claim, "offset_applied_cents", offset_applied_cents)
    if net_refund_cents is not None:
        assert_money(claim, "net_refund_cents", net_refund_cents)
    if refund_interest_cents is not None:
        assert_money(claim, "refund_interest_cents", refund_interest_cents)
    if total_payable_cents is not None:
        assert_money(claim, "total_payable_cents", total_payable_cents)
        assert (
            claim["total_payable_cents"]
            == claim["net_refund_cents"] + claim["refund_interest_cents"]
        ), (
            "total payable must equal net refund plus refund interest: "
            f"{claim['total_payable_cents']} != {claim['net_refund_cents']} + "
            f"{claim['refund_interest_cents']}"
        )
    if status is not None:
        assert claim.get("status") == status, (
            f"claim status: expected {status}, got {claim.get('status')}"
        )


# ------------------------------------------------------------ collections


def ids_of(rows: Iterable[Dict[str, Any]]) -> list:
    """The identifiers of a collection page, in the order the page returned them."""
    return [row["id"] for row in rows]


def assert_page_ids(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """Assert a page holds exactly the expected identifiers in the expected order."""
    actual = ids_of(rows)
    expected = list(expected_ids)
    assert actual == expected, f"page identifiers: expected {expected}, got {actual}"


def assert_ascending_by_created_at(rows: Iterable[Dict[str, Any]]) -> None:
    """Assert a page is ordered by creation instant, oldest first."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"page is not ordered by created_at ascending: {stamps}"
