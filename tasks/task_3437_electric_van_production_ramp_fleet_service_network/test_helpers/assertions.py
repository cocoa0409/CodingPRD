"""Entity assertions and domain invariant checkers.

Each assert_<entity>(data) validates the common system properties (UUID id,
ISO 8601 created_at/updated_at, integer version) plus the entity's field set
and enum memberships exactly as the PRD declares them.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    PACK_KWH_VALUES,
    AccountTier,
    BatteryEolStatus,
    BatteryModuleStatus,
    CampaignResult,
    CampaignStatus,
    ChargingProjectStatus,
    ComponentClass,
    DeliveryMethod,
    ProRating,
    ReadinessTier,
    ServiceVisitStatus,
    TelematicsTier,
    TelematicsTierScope,
    VehicleDeliveryStatus,
    VehicleOrderStatus,
    VehicleTelematicsStatus,
    VisitPurpose,
    WarrantyClaimStatus,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_fleet_customer(data: dict):
    _assert_common(data, "FleetCustomer")
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["account_tier"] in _enum_values(AccountTier)


def assert_depot(data: dict):
    _assert_common(data, "Depot")
    assert is_valid_uuid(data.get("fleet_customer_id", "")), "fleet_customer_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["total_capacity_kw"], (int, float)) and data["total_capacity_kw"] > 0
    assert isinstance(data["committed_capacity_kw"], (int, float))


def assert_charging_project(data: dict):
    _assert_common(data, "ChargingProject")
    assert is_valid_uuid(data.get("depot_id", "")), "depot_id must be a UUID"
    assert isinstance(data["requested_capacity_kw"], (int, float)) and data["requested_capacity_kw"] > 0
    assert is_iso8601_timestamp(data.get("install_window_start", ""))
    assert is_iso8601_timestamp(data.get("install_window_end", ""))
    assert isinstance(data["crew_count"], int) and data["crew_count"] >= 1
    assert data["status"] in _enum_values(ChargingProjectStatus)
    assert data.get("utility_denial_reason") is None or isinstance(data["utility_denial_reason"], str)
    assert data.get("commissioned_capacity_kw") is None or isinstance(
        data["commissioned_capacity_kw"], (int, float)
    )


def assert_supplier(data: dict):
    _assert_common(data, "Supplier")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["readiness_tier"] in _enum_values(ReadinessTier)
    assert data.get("last_on_time_pct") is None or isinstance(data["last_on_time_pct"], (int, float))
    assert data.get("last_first_pass_yield_pct") is None or isinstance(data["last_first_pass_yield_pct"], (int, float))
    assert data.get("open_corrective_actions") is None or isinstance(data["open_corrective_actions"], int)
    assert isinstance(data.get("created_by_user_id"), str) and data["created_by_user_id"]


def assert_battery_module(data: dict):
    _assert_common(data, "BatteryModule")
    assert is_valid_uuid(data.get("supplier_id", "")), "supplier_id must be a UUID"
    assert isinstance(data["module_serial"], str) and data["module_serial"]
    assert data["pack_kwh"] in PACK_KWH_VALUES
    assert data["quality_status"] in _enum_values(BatteryModuleStatus)
    assert isinstance(data["failure_count"], int) and data["failure_count"] >= 0
    assert isinstance(data.get("registered_by_user_id"), str) and data["registered_by_user_id"]
    assert data.get("last_inspector_user_id") is None or isinstance(data["last_inspector_user_id"], str)


def assert_vehicle_order(data: dict):
    _assert_common(data, "VehicleOrder")
    assert is_valid_uuid(data.get("fleet_customer_id", "")), "fleet_customer_id must be a UUID"
    assert is_valid_uuid(data.get("depot_id", "")), "depot_id must be a UUID"
    assert is_valid_uuid(data.get("battery_supplier_id", "")), "battery_supplier_id must be a UUID"
    assert isinstance(data["quantity"], int) and 1 <= data["quantity"] <= 500
    assert data["battery_pack_kwh"] in PACK_KWH_VALUES
    assert data["telematics_tier"] in _enum_values(TelematicsTier)
    assert data["delivery_method"] in _enum_values(DeliveryMethod)
    assert isinstance(data["requires_depot_charging"], bool)
    assert data["status"] in _enum_values(VehicleOrderStatus)
    assert data.get("exemption_document_ref") is None or isinstance(data["exemption_document_ref"], str)
    assert data.get("promised_delivery_date") is None or isinstance(data["promised_delivery_date"], str)
    assert isinstance(data["supply_risk_flag"], bool)
    assert isinstance(data["registered_count"], int) and data["registered_count"] >= 0
    assert isinstance(data["hold_count"], int) and data["hold_count"] >= 0


def assert_vehicle(data: dict):
    _assert_common(data, "Vehicle")
    assert is_valid_uuid(data.get("vehicle_order_id", "")), "vehicle_order_id must be a UUID"
    assert is_valid_uuid(data.get("battery_module_id", "")), "battery_module_id must be a UUID"
    assert isinstance(data["vin"], str) and data["vin"]
    assert data["delivery_status"] in _enum_values(VehicleDeliveryStatus)
    assert data["telematics_status"] in _enum_values(VehicleTelematicsStatus)
    assert isinstance(data["software_version"], str) and data["software_version"]
    assert isinstance(data["software_hold"], bool)
    assert isinstance(data["current_soh_pct"], (int, float))
    assert data["battery_eol_status"] in _enum_values(BatteryEolStatus)
    assert data.get("eol_valuation_refurbish_cents") is None or isinstance(
        data["eol_valuation_refurbish_cents"], int
    )
    assert data.get("eol_valuation_recovery_cents") is None or isinstance(
        data["eol_valuation_recovery_cents"], int
    )
    assert data.get("last_battery_report_at") is None or is_iso8601_timestamp(
        data["last_battery_report_at"]
    )


def assert_service_center(data: dict):
    _assert_common(data, "ServiceCenter")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["bay_count"], int) and data["bay_count"] >= 1


def assert_mobile_van(data: dict):
    _assert_common(data, "MobileVan")
    assert is_valid_uuid(data.get("service_center_id", "")), "service_center_id must be a UUID"
    assert isinstance(data["van_code"], str) and data["van_code"]


def assert_service_visit(data: dict):
    _assert_common(data, "ServiceVisit")
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a UUID"
    has_center = data.get("service_center_id") is not None
    has_van = data.get("mobile_van_id") is not None
    assert has_center != has_van, "exactly one of service_center_id / mobile_van_id must be set"
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["purpose"] in _enum_values(VisitPurpose)
    assert isinstance(data["parts_lines"], list)
    for line in data["parts_lines"]:
        assert isinstance(line["sku"], str) and line["sku"]
        assert isinstance(line["qty"], int) and line["qty"] > 0
    assert data["status"] in _enum_values(ServiceVisitStatus)
    assert data.get("completed_by_user_id") is None or isinstance(data["completed_by_user_id"], str)


def assert_parts_stock(data: dict):
    _assert_common(data, "PartsStock")
    assert is_valid_uuid(data.get("service_center_id", "")), "service_center_id must be a UUID"
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["reorder_threshold"], int) and data["reorder_threshold"] >= 0
    for field in ("on_hand_qty", "reserved_qty", "consumed_total_qty", "received_total_qty"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be an integer >= 0"
    assert isinstance(data["restock_needed"], bool)


def assert_software_campaign(data: dict):
    _assert_common(data, "SoftwareCampaign")
    assert isinstance(data["target_version"], str) and data["target_version"]
    assert data["telematics_tier_scope"] in _enum_values(TelematicsTierScope)
    assert data["status"] in _enum_values(CampaignStatus)
    assert data.get("paused_from") is None or data["paused_from"] in (
        CampaignStatus.CANARY.value,
        CampaignStatus.EXPANDED.value,
        CampaignStatus.GENERAL.value,
    )
    assert isinstance(data["results"], list)
    for entry in data["results"]:
        assert is_valid_uuid(entry.get("vehicle_id", "")), "results[].vehicle_id must be a UUID"
        assert entry["result"] in _enum_values(CampaignResult)
        assert is_iso8601_timestamp(entry.get("reported_at", ""))
    assert isinstance(data["succeeded_count"], int) and data["succeeded_count"] >= 0
    assert isinstance(data["failed_count"], int) and data["failed_count"] >= 0


def assert_uptime_contract(data: dict):
    _assert_common(data, "UptimeContract")
    assert is_valid_uuid(data.get("fleet_customer_id", "")), "fleet_customer_id must be a UUID"
    assert isinstance(data["committed_uptime_pct"], (int, float))
    assert 0 < data["committed_uptime_pct"] <= 100
    assert isinstance(data["monthly_service_fee_cents"], int) and data["monthly_service_fee_cents"] > 0
    assert data["pro_rating"] in _enum_values(ProRating)
    assert isinstance(data["measurement_start_date"], str) and data["measurement_start_date"]
    assert isinstance(data["downtime_events"], list)
    for event in data["downtime_events"]:
        assert is_valid_uuid(event.get("vehicle_id", "")), "downtime_events[].vehicle_id must be a UUID"
        assert is_iso8601_timestamp(event.get("started_at", ""))
        assert event.get("ended_at") is None or is_iso8601_timestamp(event["ended_at"])
    assert data.get("last_closed_month") is None or isinstance(data["last_closed_month"], str)
    assert data.get("last_uptime_pct") is None or isinstance(data["last_uptime_pct"], (int, float))
    assert data.get("last_credit_cents") is None or isinstance(data["last_credit_cents"], int)
    assert isinstance(data["lifetime_credit_cents"], int) and data["lifetime_credit_cents"] >= 0


def assert_warranty_claim(data: dict):
    _assert_common(data, "WarrantyClaim")
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a UUID"
    assert data.get("service_visit_id") is None or is_valid_uuid(data["service_visit_id"])
    assert isinstance(data["claim_lines"], list) and len(data["claim_lines"]) >= 1
    for line in data["claim_lines"]:
        assert line["component_class"] in _enum_values(ComponentClass)
        assert isinstance(line["part_cost_cents"], int) and line["part_cost_cents"] >= 0
        assert isinstance(line["labor_hours"], (int, float)) and line["labor_hours"] >= 0
    assert data["status"] in _enum_values(WarrantyClaimStatus)
    assert data.get("diagnosed_by_user_id") is None or isinstance(data["diagnosed_by_user_id"], str)
    assert data.get("diagnosis_notes") is None or isinstance(data["diagnosis_notes"], str)
    assert data.get("adjudicated_by_user_id") is None or isinstance(data["adjudicated_by_user_id"], str)
    assert data.get("settlement_cents") is None or isinstance(data["settlement_cents"], int)
    assert data.get("denial_reason") is None or isinstance(data["denial_reason"], str)


# =============================================================================
# Domain invariant checkers
# =============================================================================

def assert_parts_stock_invariants(data: dict):
    """PRD section 3.8 invariants, checked after any stock mutation:
    reserved units are a subset view of on-hand stock; the conservation
    identity received_total_qty == on_hand_qty + consumed_total_qty holds;
    restock_needed is true exactly when on_hand_qty falls strictly below
    reorder_threshold.
    """
    assert 0 <= data["reserved_qty"] <= data["on_hand_qty"], (
        "reserved_qty must be a subset of on_hand_qty"
    )
    assert data["received_total_qty"] == data["on_hand_qty"] + data["consumed_total_qty"], (
        f"parts conservation violated: received {data['received_total_qty']} != "
        f"on_hand {data['on_hand_qty']} + consumed {data['consumed_total_qty']}"
    )
    assert data["restock_needed"] == (data["on_hand_qty"] < data["reorder_threshold"]), (
        f"restock_needed {data['restock_needed']} inconsistent with on_hand "
        f"{data['on_hand_qty']} vs threshold {data['reorder_threshold']} (strict below)"
    )


def assert_depot_invariants(data: dict):
    """committed_capacity_kw never negative and never above the service total —
    the headroom rule rejects any create that would exceed it."""
    assert data["committed_capacity_kw"] >= 0
    assert data["committed_capacity_kw"] <= data["total_capacity_kw"], (
        f"committed {data['committed_capacity_kw']} exceeds total {data['total_capacity_kw']}"
    )


def assert_campaign_counters(data: dict):
    """succeeded_count / failed_count are derived from the results array."""
    successes = sum(1 for e in data["results"] if e["result"] == CampaignResult.SUCCESS.value)
    failures = sum(1 for e in data["results"] if e["result"] == CampaignResult.FAILED.value)
    assert data["succeeded_count"] == successes, (
        f"succeeded_count {data['succeeded_count']} != {successes} SUCCESS entries"
    )
    assert data["failed_count"] == failures, (
        f"failed_count {data['failed_count']} != {failures} FAILED entries"
    )
    vehicle_ids = [e["vehicle_id"] for e in data["results"]]
    assert len(vehicle_ids) == len(set(vehicle_ids)), "one result per vehicle per campaign"


def assert_fresh_vehicle_defaults(data: dict):
    """A freshly registered vehicle carries the PRD section 3.6 system defaults."""
    assert data["delivery_status"] == VehicleDeliveryStatus.ASSEMBLED.value
    assert data["telematics_status"] == VehicleTelematicsStatus.OFFLINE.value
    assert data["software_version"] == "1.0.0"
    assert data["software_hold"] is False
    assert data["current_soh_pct"] == 100.0
    assert data["battery_eol_status"] == BatteryEolStatus.NONE.value
    assert data["eol_valuation_refurbish_cents"] is None
    assert data["eol_valuation_recovery_cents"] is None
    assert data["last_battery_report_at"] is None
