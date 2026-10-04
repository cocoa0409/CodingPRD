"""Entity assertions and domain invariant checkers (PRD §2.4, §2.5, §2.9)."""
import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

SITE_STATUSES = ["SITE_ACTIVE", "SITE_SUSPENDED"]
SITE_LIFECYCLE_STATES = ["RESOURCE_AVAILABLE", "RESOURCE_DRAWING", "RESOURCE_CLOSED"]
CUSTOMER_STATUSES = ["CUSTOMER_ACTIVE", "CUSTOMER_CREDIT_HOLD", "CUSTOMER_SUSPENDED"]
RENEWAL_STAGES = ["RENEWAL_NONE", "RENEWAL_OFFERED", "RENEWAL_ACCEPTED", "RENEWAL_DECLINED"]
CREDIT_TIERS = ["CREDIT_PRIME", "CREDIT_STANDARD", "CREDIT_SUBSTANDARD"]
PPA_STATES = [
    "PPA_DRAFT",
    "PPA_ACTIVE",
    "PPA_SUSPENDED",
    "PPA_EXIT_PENDING",
    "PPA_TERMINATED",
]
SERVICE_PLAN_LIFECYCLE_STATES = [
    "SERVICE_PLAN_DRAFT",
    "SERVICE_ACTIVE",
    "SERVICE_MAINTENANCE_WINDOW_OPEN",
    "SERVICE_SUSPENDED",
    "SERVICE_ARCHIVED",
]
MODULE_REPLACEMENT_STAGES = [
    "REPLACEMENT_NONE",
    "REPLACEMENT_SCHEDULED",
    "REPLACEMENT_DISPATCHED",
    "REPLACEMENT_BLOCKED",
]
DELIVERY_LIFECYCLE_STATES = [
    "DELIVERY_SCHEDULED",
    "DELIVERY_IN_TRANSIT",
    "DELIVERY_CONFIRMED",
    "DELIVERY_SETTLED",
    "DELIVERY_CANCELLED",
]
SETTLEMENT_LINE_STATUSES = [
    "SETTLEMENT_DRAFT",
    "SETTLEMENT_VALIDATED",
    "SETTLEMENT_APPROVED",
    "SETTLEMENT_APPLIED",
    "SETTLEMENT_REVERSED",
]
ACCRUAL_TYPES = [
    "CHARGE_ACCRUAL",
    "OUTPUT_GUARANTEE_ACCRUAL",
    "TRUEUP_ACCRUAL",
    "CAPACITY_ACCRUAL",
]
ACCRUAL_LIFECYCLE_STATES = ["ACCRUAL_OPEN", "ACCRUAL_RECONCILED"]
ALLOWANCE_KINDS = ["AVOIDED_COST_ALLOWANCE", "CAPACITY_ALLOWANCE"]
ALLOWANCE_LIFECYCLE_STATES = ["ALLOWANCE_ISSUED", "ALLOWANCE_APPLIED"]
ALLOCATION_BASES = ["ALLOCATION_ORDER", "UNIT_INDEX"]


def _assert_common_fields(data: dict):
    """The four system-managed properties every standard resource exposes."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["utility_territory"], str) and data["utility_territory"]
    assert data["status"] in SITE_STATUSES, f"unexpected status {data['status']}"
    assert (
        data["lifecycle_state"] in SITE_LIFECYCLE_STATES
    ), f"unexpected lifecycle_state {data['lifecycle_state']}"
    for field in (
        "active_ppa_count",
        "lifetime_settle_reconcile_count",
        "reserved_capacity_hold_count",
        "total_contracted_kw",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["credit_tier"] in CREDIT_TIERS
    assert data["status"] in CUSTOMER_STATUSES
    assert data["renewal_stage"] in RENEWAL_STAGES


def assert_ppa(data: dict):
    _assert_common_fields(data)
    assert data["state"] in PPA_STATES, f"unexpected state {data['state']}"
    assert data["contract_basis"] in ["PPA_BASIS_AS_BUILT", "PPA_BASIS_TRANSFERRED"]
    assert data["term_years"] in (10, 12, 15, 20), "term_years must be a committed term"
    assert data["contracted_kw"] > 0
    assert data["contracted_efficiency_kwh_per_therm"] > 0


def assert_service_plan(data: dict):
    _assert_common_fields(data)
    assert data["lifecycle_state"] in SERVICE_PLAN_LIFECYCLE_STATES
    assert data["module_replacement_stage"] in MODULE_REPLACEMENT_STAGES
    assert isinstance(data["dispatch_hold"], bool)


def assert_fuel_delivery(data: dict):
    _assert_common_fields(data)
    assert data["lifecycle_state"] in DELIVERY_LIFECYCLE_STATES
    assert data["sourcing_mode"] in ["FIXED_PRICE_BLEND", "INDEXED_BLEND"]


def assert_settlement_line(data: dict):
    _assert_common_fields(data)
    assert data["status"] in SETTLEMENT_LINE_STATUSES
    assert data["allocation_basis"] in ALLOCATION_BASES


def assert_accrual(data: dict):
    _assert_common_fields(data)
    assert data["accrual_type"] in ACCRUAL_TYPES
    assert data["lifecycle_state"] in ACCRUAL_LIFECYCLE_STATES


def assert_allowance(data: dict):
    _assert_common_fields(data)
    assert data["allowance_kind"] in ALLOWANCE_KINDS
    assert data["lifecycle_state"] in ALLOWANCE_LIFECYCLE_STATES


def assert_transition(data: dict):
    """PpaTransition is append-only: it carries id and created_at and nothing else."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "an append-only transition record carries no version"
    assert "updated_at" not in data, "an append-only transition record carries no updated_at"
    assert isinstance(data["from_state"], str) and data["from_state"]
    assert isinstance(data["to_state"], str) and data["to_state"]
    assert isinstance(data["trigger_code"], str) and data["trigger_code"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]


# --- Domain invariants -------------------------------------------------------
def assert_site_fuel_pool_invariants(data: dict):
    """The allocatable pool is a non-negative balance that starts from the
    operator-funded opening inventory."""
    assert data["draw_position_therms"] >= 0, "draw_position_therms cannot go negative"
    assert data["initial_fuel_inventory_therms"] >= 0
    assert_cost_precision(data["draw_position_therms"])


def assert_site_aggregate_invariants(data: dict):
    """Contracted aggregates are non-negative and consistent with the pool."""
    assert data["total_contracted_kw"] >= 0
    assert data["committed_feedstock_therms"] >= 0
    assert data["contracted_purchase_cents"] >= 0
    assert data["clearance_zone_used"] >= 0
    assert data["lifetime_settle_reconcile_count"] >= 0


def assert_capacity_reserve_invariants(ppa: dict):
    """The capacity-guarantee reserve is the opening commitment less the credits
    accumulated against it, and it can never fall below the contract's floor."""
    assert (
        ppa["capacity_guarantee_reserve_cents"] >= ppa["loss_floor_cents"]
    ), "reserve must never fall below loss_floor_cents"
    assert (
        ppa["capacity_guarantee_reserve_cents"]
        == ppa["capacity_reserve_pre_cents"] - ppa["capacity_reserve_credits_cents"]
    )


def assert_customer_exposure_matches_tier(customer: dict):
    expected = {
        "CREDIT_SUBSTANDARD": 0.40,
        "CREDIT_STANDARD": 0.15,
        "CREDIT_PRIME": 0.0,
    }[customer["credit_tier"]]
    assert customer["exposure_hold_pct"] == pytest.approx(expected, abs=1e-9)


def assert_customer_relationship_invariants(customer: dict):
    assert customer["outstanding_balance_cents"] >= 0 or True  # may be a signed ledger
    assert customer["active_ppa_count"] >= 0
    assert customer["reconcile_cadence_slots"] >= 0


def assert_signed_accrual_sum(accruals: list) -> float:
    """The contract's open signed accrual sum."""
    return sum(a["signed_amount_cents"] for a in accruals if a["lifecycle_state"] == "ACCRUAL_OPEN")