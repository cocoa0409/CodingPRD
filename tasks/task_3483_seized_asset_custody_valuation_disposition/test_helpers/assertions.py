"""Entity assertions and domain invariant checkers.

Structural checks only — field presence, types, enum membership, nullability —
so they hold for every lawful response. Pinning exact values is the tests' job.

``validate_created`` is the explicit-201 success path for create endpoints;
action and read endpoints use ``validate_success(response, 200)`` directly with
the status stated at the call site.
"""

from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

# ─── Enum domains (PRD §3) ───────────────────────────────────────────────────

_FORFEITURE_TYPES = ("CIVIL", "CRIMINAL", "ADMINISTRATIVE")
_CASE_STATUSES = ("OPEN", "FORFEITURE_PENDING", "FORFEITED", "DISMISSED")
_ASSET_TYPES = (
    "REAL_PROPERTY", "BUSINESS", "VEHICLE", "VESSEL", "AIRCRAFT",
    "PERSONAL_PROPERTY", "FINANCIAL_INSTRUMENT",
)
_CONDITION_GRADES = ("EXCELLENT", "GOOD", "FAIR", "POOR", "SALVAGE")
_CUSTODY_STATES = (
    "INTAKE", "SECURED", "IN_STORAGE", "IN_MAINTENANCE",
    "RELEASED_FOR_SALE", "RELEASED_FOR_RETURN", "TRANSFERRED_OUT",
)
_LEGAL_STATES = (
    "SEIZED", "VALUATION_PENDING", "VALUED", "DISPOSITION_REVIEW", "RETAINED",
    "SALE_AUTHORIZED", "SOLD", "RETURN_PENDING", "RETURNED", "DISPUTED",
    "RESOLVED",
)
_RETENTION_DECISIONS = ("PENDING", "RETAIN", "SELL")
_LOCATION_KINDS = ("STORAGE", "MAINTENANCE_SHOP", "CLAIMANT_PREMISES", "OTHER")
_TRANSFER_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")
_VALUATION_METHODS = (
    "CERTIFIED_APPRAISAL", "MARKET_COMPARABLE", "BLUE_BOOK", "INCOME_APPROACH",
)
_VALUATION_STATUSES = ("SUBMITTED", "ACCEPTED", "REJECTED")
_ENTRY_KINDS = ("COST", "REVENUE_OFFSET", "REVERSAL")
_EXPENSE_TYPES = (
    "STORAGE", "MAINTENANCE", "MANAGEMENT_FEE", "INSURANCE", "SECURITY",
    "UTILITIES", "STORAGE_ACCRUAL",
)
_EXPENSE_SOURCES = ("MANUAL", "SYSTEM_ACCRUAL")
_ISR_STATUSES = ("PENDING", "APPROVED", "DENIED")
_INTEREST_KINDS = (
    "LIEN_MORTGAGE", "LIEN_TAX", "LIEN_JUDGMENT", "LIEN_MECHANIC",
    "INNOCENT_OWNER",
)
_INTEREST_STATUSES = (
    "FILED", "VERIFIED", "GRANTED", "DENIED", "APPEALED", "SATISFIED",
)
_SALE_METHODS = ("PUBLIC_AUCTION", "CONTRACTED_SELLER")
_SALE_STATUSES = (
    "OPEN_FOR_BIDS", "CLOSED_PENDING_SETTLEMENT", "SETTLED", "NO_SALE",
    "CANCELLED",
)
_DISTRIBUTION_KINDS = ("EQUITABLE_SHARE", "LIEN_PAYMENT", "COST_REIMBURSEMENT")
_USAGE_RESTRICTIONS = ("OVERTIME", "TRAINING", "EQUIPMENT", "COMMUNITY_PROGRAM")
_DISTRIBUTION_STATUSES = ("PENDING", "PAID", "VOIDED")


# ─── Success wrappers ────────────────────────────────────────────────────────

def validate_created(response) -> dict:
    """Create endpoints return 201 (PRD §4). Always explicit — never a bare
    200-only default."""
    return validate_success(response, 201)


def validate_action(response) -> dict:
    """State-transition and read endpoints return 200 (PRD §4)."""
    return validate_success(response, 200)


# ─── Shared system-managed properties (PRD §2.5) ─────────────────────────────

def assert_common_fields(data: dict) -> None:
    """All nine resource types carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def _assert_optional_timestamp(data: dict, field: str) -> None:
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601 UTC, got {value!r}"
    )


def _assert_optional_int(data: dict, field: str) -> None:
    value = data.get(field)
    assert value is None or isinstance(value, int), (
        f"{field} must be null or an integer, got {value!r}"
    )


# ─── Per-entity assertions ───────────────────────────────────────────────────

def assert_seizure_case(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["case_number"], str) and data["case_number"].strip()
    assert isinstance(data["judicial_district"], str)
    assert data["forfeiture_type"] in _FORFEITURE_TYPES
    assert isinstance(data["lead_agency_code"], str)
    assert data["status"] in _CASE_STATUSES
    _assert_optional_timestamp(data, "forfeited_at")
    for field in (
        "gross_proceeds_cents", "auction_fees_cents", "lien_payments_cents",
        "cost_reimbursements_cents", "sharing_pool_gross_basis_cents",
        "sharing_pool_net_basis_cents", "equitable_shares_paid_cents",
        "available_proceeds_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_case_pool_invariants(data: dict) -> None:
    """PRD §3.6/§3.7: available == net basis - paid shares, and the gross basis
    equals the net basis plus lien payments plus cost reimbursements."""
    assert data["available_proceeds_cents"] == (
        data["sharing_pool_net_basis_cents"] - data["equitable_shares_paid_cents"]
    ), (
        f"available_proceeds_cents {data['available_proceeds_cents']} != "
        f"net {data['sharing_pool_net_basis_cents']} - paid "
        f"{data['equitable_shares_paid_cents']}"
    )
    assert data["sharing_pool_gross_basis_cents"] == (
        data["sharing_pool_net_basis_cents"]
        + data["lien_payments_cents"]
        + data["cost_reimbursements_cents"]
    ), (
        "gross basis must equal net basis plus lien payments plus cost "
        "reimbursements"
    )


def assert_asset(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["seizure_case_id"], str)
    assert data["asset_type"] in _ASSET_TYPES
    assert isinstance(data["description"], str)
    assert is_iso8601_timestamp(data["seized_on"])
    assert data["seizure_condition_grade"] in _CONDITION_GRADES
    assert data["current_condition_grade"] in _CONDITION_GRADES
    _assert_optional_int(data, "appraised_value_cents")
    _assert_optional_timestamp(data, "appraised_at")
    assert isinstance(data["accumulated_net_holding_cost_cents"], int)
    assert data["custody_state"] in _CUSTODY_STATES
    assert data["legal_state"] in _LEGAL_STATES
    assert data["retention_decision"] in _RETENTION_DECISIONS
    _assert_optional_int(data, "provisional_net_retention_value_cents")
    _assert_optional_int(data, "final_net_retention_value_cents")
    _assert_optional_timestamp(data, "returned_at")
    _assert_optional_int(data, "computed_depreciation_cents")
    _assert_optional_int(data, "dispute_claimed_depreciation_cents")
    _assert_optional_int(data, "final_depreciation_cents")


def assert_holding_cost_non_negative(data: dict) -> None:
    """The accumulator floor (PRD §3.4): never driven below zero."""
    assert data["accumulated_net_holding_cost_cents"] >= 0, (
        "accumulated_net_holding_cost_cents may never go below zero"
    )


def assert_custody_transfer(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["asset_id"], str)
    assert isinstance(data["from_location_ref"], str)
    assert isinstance(data["to_location_ref"], str)
    assert data["to_location_kind"] in _LOCATION_KINDS
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in _TRANSFER_STATUSES
    condition = data.get("condition_on_arrival")
    assert condition is None or condition in _CONDITION_GRADES


def assert_valuation(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["asset_id"], str)
    assert data["method"] in _VALUATION_METHODS
    _assert_optional_int(data, "raw_value_cents")
    grade = data.get("assessed_condition_grade")
    assert grade is None or grade in _CONDITION_GRADES
    revenues = data.get("annual_net_revenues_cents")
    assert revenues is None or (
        isinstance(revenues, list)
        and len(revenues) == 3
        and all(isinstance(r, int) for r in revenues)
    ), "annual_net_revenues_cents must be null or exactly three integers"
    assert isinstance(data["adjusted_value_cents"], int)
    assert data["status"] in _VALUATION_STATUSES
    assert isinstance(data["submitted_by_user_id"], str)


def assert_expense_entry(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["asset_id"], str)
    assert data["entry_kind"] in _ENTRY_KINDS
    assert data["expense_type"] in _EXPENSE_TYPES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["incurred_on"])
    assert data["source"] in _EXPENSE_SOURCES
    assert isinstance(data["posted_by_user_id"], str)


def assert_interlocutory_sale_request(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["asset_id"], str)
    assert isinstance(data["justification"], str)
    assert isinstance(data["requested_by_user_id"], str)
    assert data["status"] in _ISR_STATUSES
    adjudicator = data.get("adjudicated_by_user_id")
    assert adjudicator is None or isinstance(adjudicator, str)
    assert isinstance(data["accumulated_costs_snapshot_cents"], int)
    assert isinstance(data["projected_burden_cents"], int)
    assert isinstance(data["appraised_value_snapshot_cents"], int)


def assert_third_party_interest(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["asset_id"], str)
    assert data["kind"] in _INTEREST_KINDS
    assert isinstance(data["petitioner_ref"], str)
    lienholder = data.get("lienholder_name")
    assert lienholder is None or isinstance(lienholder, str)
    _assert_optional_int(data, "amount_cents")
    _assert_optional_int(data, "priority_position")
    assert data["status"] in _INTEREST_STATUSES
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0
    _assert_optional_int(data, "satisfied_amount_cents")
    adjudicator = data.get("adjudicated_by_user_id")
    assert adjudicator is None or isinstance(adjudicator, str)


def assert_sale_event(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["asset_id"], str)
    assert data["sale_method"] in _SALE_METHODS
    assert isinstance(data["auctioneer_ref"], str)
    assert is_iso8601_timestamp(data["slot_start"])
    assert is_iso8601_timestamp(data["slot_end"])
    assert isinstance(data["reserve_price_cents"], int)
    _assert_optional_int(data, "winning_bid_cents")
    _assert_optional_int(data, "gross_proceeds_cents")
    _assert_optional_int(data, "auction_fee_cents")
    _assert_optional_int(data, "net_proceeds_cents")
    assert data["status"] in _SALE_STATUSES


def assert_distribution(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["seizure_case_id"], str)
    assert data["distribution_kind"] in _DISTRIBUTION_KINDS
    assert isinstance(data["payee_ref"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    restriction: Optional[str] = data.get("usage_restriction")
    assert restriction is None or restriction in _USAGE_RESTRICTIONS
    assert data["status"] in _DISTRIBUTION_STATUSES
    assert isinstance(data["created_by_user_id"], str)
    approver = data.get("approved_by_user_id")
    assert approver is None or isinstance(approver, str)


__all__ = [
    "validate_created",
    "validate_action",
    "assert_common_fields",
    "assert_seizure_case",
    "assert_case_pool_invariants",
    "assert_asset",
    "assert_holding_cost_non_negative",
    "assert_custody_transfer",
    "assert_valuation",
    "assert_expense_entry",
    "assert_interlocutory_sale_request",
    "assert_third_party_interest",
    "assert_sale_event",
    "assert_distribution",
]
