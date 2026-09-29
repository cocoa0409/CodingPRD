"""Entity assertions and domain invariant checkers.

Numeric comparisons go through `assert_cents` / `assert_ratio_4dp` /
`assert_multiple_1dp` so that a server returning `0.05` where the PRD pins
`0.0500`, or a JSON number where the test wrote a Decimal, still compares by
value. Instant comparisons go through `canonical_instant` so that a differing
count of fractional digits never turns into a false failure.
"""
from decimal import Decimal
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .types import (
    AccountTransferStatus,
    AccountVerificationStatus,
    AttributedTo,
    AttritionEventType,
    BillingFrequency,
    BillingSource,
    BuyerLicenseStatus,
    BuyerQualificationStatus,
    ChemicalBillingMethod,
    ClawbackStatus,
    DealStatus,
    EscrowStatus,
    FinancingType,
    LicenseTransferStatus,
    ListingStatus,
    PermitType,
    RemedyBasis,
    RouteDay,
    SellerStatus,
    SettlementStatus,
    ValuationBasis,
    VerificationPosture,
)


# ---------------------------------------------------------------------------
# Primitive comparisons
# ---------------------------------------------------------------------------

def as_decimal(value: Any) -> Decimal:
    """Coerce a JSON number or numeric string to Decimal for exact comparison."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """A monetary amount is an integer number of cents equal to `expected`."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"Expected {label} of {expected} cents, got {actual}"


def assert_non_negative_cents(actual: Any, label: str = "amount") -> None:
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual >= 0, f"{label} must be at least zero, got {actual}"


def assert_ratio_4dp(actual: Any, expected: str, label: str = "ratio") -> None:
    """A ratio pinned to four decimal places compares equal by value."""
    assert as_decimal(actual) == Decimal(expected), (
        f"Expected {label} of {expected}, got {actual}"
    )


def assert_multiple_1dp(actual: Any, expected: str, label: str = "multiple") -> None:
    """A multiple pinned to one decimal place compares equal by value."""
    assert as_decimal(actual) == Decimal(expected), (
        f"Expected {label} of {expected}, got {actual}"
    )


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Two ISO-8601 UTC instants name the same second."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label} of {expected}, got {actual}"
    )


def assert_common_fields(data: Dict[str, Any], label: str = "resource") -> None:
    """`id`, `created_at`, `updated_at` and `version` of a versioned resource."""
    assert is_valid_uuid(data.get("id", "")), f"{label} id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label} created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label} updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label} version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_ledger_fields(data: Dict[str, Any], label: str = "ledger record") -> None:
    """An append-only ledger record carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"{label} id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label} created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_state_license_profile(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "StateLicenseProfile")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper()
    assert isinstance(data["required_permit_types"], list) and data["required_permit_types"]
    for permit in data["required_permit_types"]:
        assert permit in [p.value for p in PermitType], f"unknown permit type {permit!r}"
    assert isinstance(data["reciprocity_states"], list)
    assert isinstance(data["transfer_processing_days"], int)
    assert 1 <= data["transfer_processing_days"] <= 180
    assert isinstance(data["cooling_off_days"], int)
    assert 0 <= data["cooling_off_days"] <= 180
    assert isinstance(data["provisional_operation_allowed"], bool)


def assert_seller(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Seller")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["license_number"], str) and 1 <= len(data["license_number"]) <= 40
    assert data["status"] in [s.value for s in SellerStatus]


def assert_buyer(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Buyer")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert data["license_status"] in [s.value for s in BuyerLicenseStatus]
    assert data["qualification_status"] in [s.value for s in BuyerQualificationStatus]
    assert_non_negative_cents(data["prequalified_amount_cents"], "prequalified_amount_cents")


def assert_route_listing(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "RouteListing")
    assert is_valid_uuid(data["seller_id"])
    assert isinstance(data["region_code"], str) and 1 <= len(data["region_code"]) <= 20
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["status"] in [s.value for s in ListingStatus]
    assert isinstance(data["asking_price_cents"], int) and data["asking_price_cents"] >= 1
    assert isinstance(data["listed_mrr_cents"], int) and data["listed_mrr_cents"] >= 1
    assert isinstance(data["listed_account_count"], int) and data["listed_account_count"] >= 1
    assert data["exclusive_start_date"] < data["exclusive_end_date"]
    for field in (
        "claimed_recurring_mrr_cents",
        "claimed_repair_mrr_cents",
        "claimed_account_count",
        "verified_recurring_mrr_cents",
        "verified_repair_mrr_cents",
        "verified_account_count",
        "introductions_completed_count",
    ):
        assert_non_negative_cents(data[field], field)
    assert data["verification_posture"] in [p.value for p in VerificationPosture]


def assert_service_account(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ServiceAccount")
    assert is_valid_uuid(data["listing_id"])
    assert isinstance(data["customer_ref"], str) and 1 <= len(data["customer_ref"]) <= 60
    assert data["route_day"] in [d.value for d in RouteDay]
    assert isinstance(data["monthly_service_fee_cents"], int) and data["monthly_service_fee_cents"] >= 1
    assert_non_negative_cents(data["avg_monthly_chemical_cents"], "avg_monthly_chemical_cents")
    assert_non_negative_cents(data["avg_monthly_repair_cents"], "avg_monthly_repair_cents")
    assert data["chemical_billing_method"] in [m.value for m in ChemicalBillingMethod]
    assert data["billing_frequency"] in [f.value for f in BillingFrequency]
    assert_non_negative_cents(data["claimed_recurring_mrr_cents"], "claimed_recurring_mrr_cents")
    assert isinstance(data["account_age_months"], int) and data["account_age_months"] >= 0
    assert data["verification_status"] in [s.value for s in AccountVerificationStatus]
    assert data["transfer_status"] in [s.value for s in AccountTransferStatus]


def assert_route_valuation(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "RouteValuation")
    assert is_valid_uuid(data["listing_id"])
    assert data["basis"] in [b.value for b in ValuationBasis]
    assert_non_negative_cents(data["recurring_mrr_cents"], "recurring_mrr_cents")
    assert_non_negative_cents(data["repair_mrr_cents"], "repair_mrr_cents")
    assert isinstance(data["account_count"], int) and data["account_count"] >= 1
    assert isinstance(data["weighted_avg_account_age_months"], int)
    assert Decimal("6.0") <= as_decimal(data["effective_multiple"]) <= Decimal("12.0")
    assert_non_negative_cents(data["recurring_component_cents"], "recurring_component_cents")
    assert_non_negative_cents(data["repair_component_cents"], "repair_component_cents")
    assert data["valuation_cents"] == data["recurring_component_cents"] + data["repair_component_cents"], (
        "valuation_cents must be the sum of the two independently rounded components"
    )
    assert isinstance(data["is_superseded"], bool)
    assert is_iso8601_timestamp(data["computed_from_clock_utc"])


def assert_deal(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Deal")
    assert is_valid_uuid(data["listing_id"])
    assert is_valid_uuid(data["buyer_id"])
    assert data["status"] in [s.value for s in DealStatus]
    assert data["financing_type"] in [t.value for t in FinancingType]
    assert isinstance(data["offer_round"], int) and data["offer_round"] >= 1
    assert_non_negative_cents(data["current_offer_price_cents"], "current_offer_price_cents")
    assert_non_negative_cents(data["down_payment_cents"], "down_payment_cents")
    assert_non_negative_cents(data["note_principal_cents"], "note_principal_cents")
    assert data["clawback_status"] in [s.value for s in ClawbackStatus]


def assert_escrow_account(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "EscrowAccount")
    assert is_valid_uuid(data["deal_id"])
    assert data["status"] in [s.value for s in EscrowStatus]
    for field in (
        "target_amount_cents",
        "holdback_amount_cents",
        "funded_amount_cents",
        "undisbursed_balance_cents",
        "holdback_balance_cents",
        "disbursed_to_broker_cents",
        "disbursed_to_seller_cents",
        "disbursed_to_buyer_cents",
    ):
        assert_non_negative_cents(data[field], field)
    assert isinstance(data["deposits_blocked"], bool)
    assert isinstance(data["holdback_release_blocked"], bool)
    assert_escrow_cash_conservation(data)


def assert_license_transfer(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "LicenseTransfer")
    assert is_valid_uuid(data["deal_id"])
    assert is_valid_uuid(data["state_profile_id"])
    assert data["status"] in [s.value for s in LicenseTransferStatus]
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_clawback_settlement(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ClawbackSettlement")
    assert is_valid_uuid(data["deal_id"])
    assert data["remedy_basis"] in [b.value for b in RemedyBasis]
    assert data["status"] in [s.value for s in SettlementStatus]
    assert is_iso8601_timestamp(data["computed_from_clock_utc"])
    assert_settlement_waterfall(data)


def assert_billing_history_record(data: Dict[str, Any]) -> None:
    assert_ledger_fields(data, "BillingHistoryRecord")
    assert is_valid_uuid(data["account_id"])
    assert len(data["period_month"]) == 7 and data["period_month"][4] == "-"
    for field in ("billed_service_cents", "billed_chemical_cents",
                  "billed_repair_cents", "collected_cents"):
        assert_non_negative_cents(data[field], field)
    billed_total = (data["billed_service_cents"] + data["billed_chemical_cents"]
                    + data["billed_repair_cents"])
    assert data["collected_cents"] <= billed_total, (
        "collected_cents may not exceed the sum of the three billed amounts"
    )
    assert data["source"] in [s.value for s in BillingSource]
    assert_non_negative_cents(data["recurring_collected_cents"], "recurring_collected_cents")
    assert_non_negative_cents(data["repair_collected_cents"], "repair_collected_cents")


def assert_attrition_event(data: Dict[str, Any]) -> None:
    assert_ledger_fields(data, "AttritionEvent")
    assert is_valid_uuid(data["deal_id"])
    assert is_valid_uuid(data["account_id"])
    assert data["event_type"] in [t.value for t in AttritionEventType]
    assert data["attributed_to"] in [a.value for a in AttributedTo]
    assert isinstance(data["mrr_delta_cents"], int) and data["mrr_delta_cents"] != 0
    if data["event_type"] in ("CANCELLED", "DOWNGRADED"):
        assert data["mrr_delta_cents"] < 0, "a loss event carries a negative mrr_delta_cents"
    else:
        assert data["mrr_delta_cents"] > 0, "a RECOVERED event carries a positive mrr_delta_cents"


# ---------------------------------------------------------------------------
# Conserved quantities (PRD §2.10) and pinned waterfalls
# ---------------------------------------------------------------------------

def assert_escrow_cash_conservation(escrow: Dict[str, Any]) -> None:
    """`funded_amount_cents` equals everything assigned out plus everything held."""
    assigned = (
        escrow["disbursed_to_broker_cents"]
        + escrow["disbursed_to_seller_cents"]
        + escrow["disbursed_to_buyer_cents"]
        + escrow["holdback_balance_cents"]
        + escrow["undisbursed_balance_cents"]
    )
    assert escrow["funded_amount_cents"] == assigned, (
        "escrow cash identity violated: funded_amount_cents="
        f"{escrow['funded_amount_cents']} but the buckets sum to {assigned}"
    )


def assert_retention_mrr_conservation(deal: Dict[str, Any]) -> None:
    """`retained_mrr_cents` plus `attrited_mrr_cents` equals `guaranteed_mrr_cents`."""
    assert deal.get("guaranteed_mrr_cents") is not None, (
        "retention identity only holds on a closed deal"
    )
    total = deal["retained_mrr_cents"] + deal["attrited_mrr_cents"]
    assert total == deal["guaranteed_mrr_cents"], (
        "retention MRR identity violated: retained+attrited="
        f"{total} but guaranteed_mrr_cents={deal['guaranteed_mrr_cents']}"
    )


def assert_listing_claimed_mrr_conservation(listing: Dict[str, Any], accounts) -> None:
    """The listing roll-up equals the sum over its non-EXCLUDED accounts."""
    expected = sum(
        a["claimed_recurring_mrr_cents"] for a in accounts
        if a["verification_status"] != "EXCLUDED"
    )
    assert listing["claimed_recurring_mrr_cents"] == expected, (
        "listing claimed-MRR identity violated: roll-up="
        f"{listing['claimed_recurring_mrr_cents']} but the included accounts sum to {expected}"
    )


def assert_settlement_waterfall(settlement: Dict[str, Any]) -> None:
    """The three sourcing buckets partition `adjustment_cents` exactly."""
    sourced = (
        settlement["from_holdback_cents"]
        + settlement["from_note_principal_cents"]
        + settlement["seller_direct_due_cents"]
    )
    assert sourced == settlement["adjustment_cents"], (
        "settlement sourcing waterfall must partition adjustment_cents exactly: "
        f"buckets sum to {sourced} but adjustment_cents={settlement['adjustment_cents']}"
    )


def assert_version_bumped_by(before: Dict[str, Any], after: Dict[str, Any],
                             expected_delta: int, label: str = "resource") -> None:
    """`version` increases by exactly `expected_delta` across an operation."""
    actual = after["version"] - before["version"]
    assert actual == expected_delta, (
        f"Expected {label} version to advance by {expected_delta} "
        f"(from {before['version']}), it advanced by {actual}"
    )


def assert_fresh_account_nulls(account: Dict[str, Any]) -> None:
    """A brand-new stop starts with every later-workflow field unset."""
    assert account["verification_status"] == "UNVERIFIED"
    assert account["transfer_status"] == "PENDING"
    for field in (
        "deal_id",
        "replaced_account_id",
        "verified_recurring_mrr_cents",
        "verified_repair_mrr_cents",
        "verification_variance",
        "introduction_sequence_no",
        "introduced_on",
        "current_mrr_cents",
        "exclusion_reason_code",
    ):
        assert account.get(field) is None, f"a fresh stop must leave {field} null"


def assert_fresh_deal_nulls(deal: Dict[str, Any]) -> None:
    """An opened deal starts at OFFER_SUBMITTED with its closing figures unset."""
    assert deal["status"] == "OFFER_SUBMITTED"
    assert deal["offer_round"] == 1
    assert deal["clawback_status"] == "NOT_APPLICABLE"
    for field in (
        "lender_name",
        "approved_amount_cents",
        "accepted_on",
        "closed_at_utc",
        "guarantee_start_utc",
        "guarantee_end_utc",
        "replacement_deadline_utc",
        "holdback_release_utc",
        "effective_multiple_at_close",
        "commission_cents",
        "holdback_cents",
        "escrow_target_amount_cents",
        "clawback_cap_cents",
        "guaranteed_mrr_cents",
        "retained_mrr_cents",
        "allowance_mrr_cents",
        "non_solicitation_executed_on",
        "non_solicitation_end_date",
        "repricing_reason_code",
        "termination_reason_code",
    ):
        assert deal.get(field) is None, f"an opened deal must leave {field} null"
    assert_cents(deal["attrited_mrr_cents"], 0, "attrited_mrr_cents")
    assert_cents(deal["replacement_mrr_cents"], 0, "replacement_mrr_cents")
    assert_cents(deal["net_attrition_mrr_cents"], 0, "net_attrition_mrr_cents")
    assert_ratio_4dp(deal["attrition_pct"], "0.0000", "attrition_pct")


def assert_fresh_escrow_zeroed(escrow: Dict[str, Any]) -> None:
    """The escrow acceptance fans out starts OPEN with every cash counter at zero."""
    assert escrow["status"] == "OPEN"
    for field in (
        "funded_amount_cents",
        "undisbursed_balance_cents",
        "holdback_balance_cents",
        "disbursed_to_broker_cents",
        "disbursed_to_seller_cents",
        "disbursed_to_buyer_cents",
    ):
        assert_cents(escrow[field], 0, field)
    assert escrow["funded_by_user_id"] is None
    assert escrow["scheduled_holdback_release_utc"] is None
    assert escrow["deposits_blocked"] is False
    assert escrow["holdback_release_blocked"] is False


def assert_fresh_license_transfer(transfer: Dict[str, Any]) -> None:
    """A fanned-out permit row starts NOT_STARTED with no filing history."""
    assert transfer["status"] == "NOT_STARTED"
    assert transfer["attempt_count"] == 0
    for field in ("applied_on", "processing_window_end", "decided_on",
                  "denial_reason_code", "waiver_basis"):
        assert transfer.get(field) is None, f"a fanned-out permit must leave {field} null"
