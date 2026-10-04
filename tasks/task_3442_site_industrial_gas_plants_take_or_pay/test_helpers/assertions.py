"""Entity assertions and domain invariant checkers.

Structural assertions only: presence, type, and enum membership of fields the
PRD fixes on each resource, plus the common-field contract of PRD section 2.5
(id / created_at / updated_at / version on primary resources; TelemetryReading
carries only id and created_at — updated_at and version are absent entirely).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CertificateResult,
    ConnectionPurpose,
    ConnectionStatus,
    ContractStatus,
    CreditStanding,
    CustomerSegment,
    DeliveryTrigger,
    EvaluationStatus,
    PlantStatus,
    Product,
    QualityStatus,
    SettlementStatus,
    SettlementVariant,
    SupplyMode,
    TankStatus,
    TransportStatus,
    TurnaroundStatus,
)


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict, entity_label: str = "resource"):
    """PRD section 2.5: primary resources share id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_customer(data: dict):
    assert_common_fields(data, "Customer")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["segment"] in _enum_values(CustomerSegment)
    assert data["credit_standing"] in _enum_values(CreditStanding)
    assert isinstance(data["blackout_windows"], list)


def assert_evaluation(data: dict):
    assert_common_fields(data, "SupplyModeEvaluation")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["site_label"], str)
    assert isinstance(data["demand_avg_nm3h"], (int, float))
    assert isinstance(data["demand_peak_nm3h"], (int, float))
    assert isinstance(data["required_purity_percent"], (int, float))
    assert data["required_product"] in _enum_values(Product)
    assert isinstance(data["pipeline_available"], bool)
    assert data["recommended_mode"] in _enum_values(SupplyMode)
    assert data["status"] in _enum_values(EvaluationStatus)


def assert_contract(data: dict):
    assert_common_fields(data, "SupplyContract")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["evaluation_id"], str)
    assert data["mode"] in _enum_values(SupplyMode)
    assert data["product"] in _enum_values(Product)
    assert isinstance(data["site_label"], str)
    assert isinstance(data["term_months"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["min_monthly_volume_nm3"], int)
    assert isinstance(data["unit_price_cents_per_nm3"], int)
    assert isinstance(data["monthly_facility_fee_cents"], int)
    assert isinstance(data["facility_fee_escalation_pct_annual"], (int, float))
    assert isinstance(data["base_power_index"], (int, float))
    assert isinstance(data["power_kwh_per_nm3"], (int, float))
    assert isinstance(data["makeup_credit_cap_pct"], (int, float))
    assert isinstance(data["makeup_credit_balance_cents"], int)
    assert isinstance(data["failover_active"], bool)
    assert data["status"] in _enum_values(ContractStatus)


def assert_plant(data: dict):
    assert_common_fields(data, "OnsitePlant")
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["nameplate_capacity_nm3h"], int)
    assert isinstance(data["capital_cost_cents"], int)
    assert isinstance(data["power_kwh_per_nm3"], (int, float))
    assert data["status"] in _enum_values(PlantStatus)
    assert isinstance(data["effective_capacity_nm3h"], int)


def assert_network(data: dict):
    assert_common_fields(data, "PipelineNetwork")
    assert isinstance(data["name"], str)
    assert isinstance(data["nameplate_capacity_nm3h"], int)
    assert isinstance(data["reserved_capacity_nm3h"], int)
    assert isinstance(data["available_capacity_nm3h"], int)


def assert_connection(data: dict):
    assert_common_fields(data, "PipelineConnection")
    assert isinstance(data["network_id"], str)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["reserved_flow_nm3h"], int)
    assert data["purpose"] in _enum_values(ConnectionPurpose)
    assert data["status"] in _enum_values(ConnectionStatus)


def assert_tank(data: dict):
    assert_common_fields(data, "StorageTank")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["site_label"], str)
    assert data["product"] in _enum_values(Product)
    assert isinstance(data["capacity_liters"], int)
    assert isinstance(data["reorder_point_liters"], int)
    assert isinstance(data["safety_stock_liters"], int)
    assert isinstance(data["required_purity_percent"], (int, float))
    assert isinstance(data["max_impurity_ppm"], int)
    assert data["current_level_liters"] is None or isinstance(data["current_level_liters"], int)
    assert data["last_reading_at"] is None or isinstance(data["last_reading_at"], str)
    assert data["burn_rate_instant_lph"] is None or isinstance(data["burn_rate_instant_lph"], (int, float))
    assert data["burn_rate_wma_lph"] is None or isinstance(data["burn_rate_wma_lph"], (int, float))
    assert data["projected_runout_instant_at"] is None or isinstance(data["projected_runout_instant_at"], str)
    assert data["projected_runout_wma_at"] is None or isinstance(data["projected_runout_wma_at"], str)
    assert data["status"] in _enum_values(TankStatus)


def assert_telemetry_reading(data: dict):
    """Append-only measurement (PRD section 2.5): id + created_at only;
    updated_at and version are absent entirely."""
    assert is_valid_uuid(data.get("id", "")), "TelemetryReading.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "TelemetryReading.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, "TelemetryReading must not carry updated_at"
    assert "version" not in data, "TelemetryReading must not carry version"
    assert isinstance(data["tank_id"], str)
    assert isinstance(data["measured_at"], str)
    assert isinstance(data["level_liters"], int)


def assert_delivery(data: dict):
    assert_common_fields(data, "Delivery")
    assert isinstance(data["tank_id"], str)
    assert isinstance(data["customer_id"], str)
    assert data["product"] in _enum_values(Product)
    assert isinstance(data["quantity_liters"], int)
    assert data["triggered_by"] in _enum_values(DeliveryTrigger)
    assert isinstance(data["route_date"], str)
    assert isinstance(data["route_code"], str)
    assert isinstance(data["stop_sequence"], int)
    assert isinstance(data["required_purity_percent"], (int, float))
    assert isinstance(data["max_impurity_ppm"], int)
    assert data["transport_status"] in _enum_values(TransportStatus)
    assert data["quality_status"] in _enum_values(QualityStatus)
    assert data["delivered_quantity_liters"] is None or isinstance(data["delivered_quantity_liters"], int)
    assert data["confirmed_at"] is None or isinstance(data["confirmed_at"], str)


def assert_quality_certificate(data: dict):
    assert_common_fields(data, "QualityCertificate")
    assert isinstance(data["delivery_id"], str)
    assert isinstance(data["sampled_at"], str)
    assert isinstance(data["measured_purity_percent"], (int, float))
    assert isinstance(data["measured_impurity_ppm"], int)
    assert isinstance(data["analyst_user_id"], str)
    assert data["certifier_user_id"] is None or isinstance(data["certifier_user_id"], str)
    assert data["result"] in _enum_values(CertificateResult)
    assert data["decided_at"] is None or isinstance(data["decided_at"], str)


def assert_turnaround(data: dict):
    assert_common_fields(data, "Turnaround")
    assert isinstance(data["plant_id"], str)
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert isinstance(data["scope"], str)
    assert isinstance(data["proposal_round"], int) and data["proposal_round"] >= 1
    assert data["status"] in _enum_values(TurnaroundStatus)


def assert_settlement(data: dict):
    assert_common_fields(data, "SettlementStatement")
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["period_month"], str)
    assert data["variant"] in _enum_values(SettlementVariant)
    assert isinstance(data["months_elapsed"], int)
    assert isinstance(data["escalation_multiplier"], (int, float))
    assert isinstance(data["billable_volume_nm3"], int)
    assert isinstance(data["volume_charge_cents"], int)
    assert isinstance(data["power_passthrough_cents"], int)
    assert isinstance(data["facility_fee_cents"], int)
    assert isinstance(data["capital_recovery_cents"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["shortfall_volume_nm3"], int)
    assert isinstance(data["makeup_credit_granted_cents"], int)
    assert isinstance(data["makeup_credit_applied_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert data["status"] in _enum_values(SettlementStatus)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_network_capacity_invariant(network: dict):
    """PRD section 3.4: reserved + available always sum back to the nameplate."""
    assert network["reserved_capacity_nm3h"] + network["available_capacity_nm3h"] == network[
        "nameplate_capacity_nm3h"
    ], (
        f"capacity invariant broken: {network['reserved_capacity_nm3h']} + "
        f"{network['available_capacity_nm3h']} != {network['nameplate_capacity_nm3h']}"
    )


def assert_makeup_ledger_invariant(grants: list, applications: list, balance: int):
    """PRD section 3.8: sum of all FINAL grants equals sum of all applications
    plus the contract's current bank balance — nothing created, nothing lost."""
    assert sum(grants) == sum(applications) + balance, (
        f"makeup ledger invariant broken: grants {sum(grants)} != "
        f"applications {sum(applications)} + balance {balance}"
    )


__all__ = [
    "assert_common_fields",
    "assert_customer",
    "assert_evaluation",
    "assert_contract",
    "assert_plant",
    "assert_network",
    "assert_connection",
    "assert_tank",
    "assert_telemetry_reading",
    "assert_delivery",
    "assert_quality_certificate",
    "assert_turnaround",
    "assert_settlement",
    "assert_network_capacity_invariant",
    "assert_makeup_ledger_invariant",
]
