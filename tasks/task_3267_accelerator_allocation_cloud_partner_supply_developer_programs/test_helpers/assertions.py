"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_partner_account(data: dict):
    _assert_common_fields(data, "PartnerAccount")
    assert data["qualification_status"] in (
        "APPLIED", "IN_VALIDATION", "QUALIFIED", "REJECTED"
    ), f"unexpected qualification_status {data['qualification_status']!r}"
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED"), \
        f"unexpected partner status {data['status']!r}"
    assert data["allocation_priority_class"] in (
        "TIER_1", "TIER_2", "TIER_3", "UNQUALIFIED"
    ), f"unexpected allocation_priority_class {data['allocation_priority_class']!r}"
    assert isinstance(data["qualification_attempt_count"], int)
    assert isinstance(data["entitlement_units_held"], int)
    assert isinstance(data["capacity_ledger_net"], int)


def assert_accelerator_product(data: dict):
    _assert_common_fields(data, "AcceleratorProduct")
    assert data["lifecycle_stage"] in (
        "PREVIEW", "GENERAL_AVAILABILITY", "MATURE", "END_OF_LIFE"
    ), f"unexpected lifecycle_stage {data['lifecycle_stage']!r}"
    assert data["product_family"] in (
        "DATACENTER", "WORKSTATION", "EMBEDDED", "CONSUMER"
    )
    assert isinstance(data["supply_ceiling_units"], int)
    assert isinstance(data["allocated_units"], int)
    assert isinstance(data["reserved_evaluation_units"], int)
    assert isinstance(data["available_units"], int)


def assert_supply_node(data: dict):
    _assert_common_fields(data, "SupplyNode")
    assert data["stage"] in ("OPEN", "FRICTION_HOLD", "DRAINING", "BINDING")
    assert data["hotness_tier"] in ("COOL", "WARM", "HOT", "SCALDING")
    assert data["temp_band_ceiling"] in ("COOL", "WARM", "HOT", "SCALDING")
    assert isinstance(data["held_units"], int)


def assert_allocation_hold(data: dict):
    _assert_common_fields(data, "AllocationHold")
    assert data["state"] in ("REQUESTED", "COMMITTED", "CANCELLED", "RECLAIMED", "EXPIRED")
    assert isinstance(data["quantity_units"], int)


def assert_enterprise_subscription(data: dict):
    _assert_common_fields(data, "EnterpriseSubscription")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "RECLAIMED", "EXPIRED")
    assert isinstance(data["seat_count"], int)
    assert isinstance(data["annual_fee_cents"], int)
    assert isinstance(data["billed_fee_cents"], int)
    assert isinstance(data["settled_fee_cents"], int)
    assert isinstance(data["support_credit_units"], int)


def assert_hardware_deployment(data: dict):
    _assert_common_fields(data, "HardwareDeployment")
    assert data["activation_state"] in ("PENDING", "ACTIVATED", "TERMINATED")
    assert isinstance(data["service_ready"], bool)


def assert_demand_forecast(data: dict):
    _assert_common_fields(data, "DemandForecast")
    assert data["tracking_status"] in (
        "DRAFT", "FORECAST_SUBMITTED", "ACTIVE", "COMMITTED", "CANCELLED"
    )
    assert isinstance(data["forfeit_rate"], (int, float))


def assert_developer_membership(data: dict):
    _assert_common_fields(data, "DeveloperProgramMembership")
    assert data["status"] in ("REQUESTED", "UNDER_EVALUATION", "ACTIVE", "LAPSED", "REVOKED")
    assert data["stored_tier"] in ("COMMUNITY", "REGISTERED", "PREFERRED", "ELITE")
    assert data["requested_tier"] in ("COMMUNITY", "REGISTERED", "PREFERRED", "ELITE")


def assert_validation_evidence(data: dict):
    _assert_common_fields(data, "ValidationEvidence")
    assert data["evidence_pack_status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["validation_minutes"], int)


def assert_allocation_epoch(data: dict):
    _assert_common_fields(data, "AllocationEpoch")
    assert data["epoch_status"] in ("OPEN", "CLOSED")
    assert isinstance(data["epoch_index"], int)


# --- domain invariant checkers ---

def assert_product_invariants(data: dict):
    """available_units is the supply ceiling minus the allocated and ring-fenced
    units, floored at zero."""
    expected = max(0, data["supply_ceiling_units"] - data["allocated_units"]
                   - data["reserved_evaluation_units"])
    assert data["available_units"] == expected, (
        f"available_units {data['available_units']} != "
        f"{data['supply_ceiling_units']} - {data['allocated_units']} - "
        f"{data['reserved_evaluation_units']}"
    )


def assert_partner_ledgers_consistent(data: dict):
    """Both conserved quantities are plain integers."""
    assert isinstance(data["capacity_ledger_net"], int)
    assert isinstance(data["entitlement_units_held"], int)
    assert data["entitlement_units_held"] >= 0


def assert_subscription_fee_precision(subscription: dict):
    assert_cost_precision(subscription["annual_fee_cents"], places=0)
    assert_cost_precision(subscription["settled_fee_cents"], places=0)