"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BlockType,
    CapacityActionOrigin,
    CapacityActionStatus,
    CapacityActionType,
    CapabilityClass,
    CauseCategory,
    CongestionComplaintStatus,
    CustomerEquipmentStatus,
    MigrationWaveStatus,
    NodeSplitProjectStatus,
    NodeStatus,
    ProvisioningRequestStatus,
    RefreshCampaignStatus,
    ScoringVariant,
    ServiceGroupPosture,
    SpectrumBlockStatus,
    SpeedTierStatus,
    UpstreamConfig,
    UtilizationMethod,
)


def _assert_common(data: dict, *, mutable: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if mutable:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_franchise_area(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["obligation_homes_required"], int)
    assert isinstance(data["obligation_deadline"], str)
    assert isinstance(data["blackout_windows"], list)
    assert isinstance(data["homes_built_progress"], int)


def assert_optical_node(data: dict):
    _assert_common(data)
    assert isinstance(data["franchise_area_id"], str)
    assert isinstance(data["node_code"], str) and data["node_code"]
    assert isinstance(data["homes_passed"], int)
    assert isinstance(data["downstream_spectrum_mhz"], int)
    assert data["upstream_config"] in {e.value for e in UpstreamConfig}
    assert data["status"] in {e.value for e in NodeStatus}


def assert_spectrum_block(data: dict):
    _assert_common(data)
    assert isinstance(data["optical_node_id"], str)
    assert data["block_type"] in {e.value for e in BlockType}
    assert isinstance(data["mhz"], int)
    assert data["status"] in {e.value for e in SpectrumBlockStatus}
    assert isinstance(data["channels"], int)
    assert isinstance(data["capacity_mbps"], int)


def assert_service_group(data: dict):
    _assert_common(data)
    assert isinstance(data["optical_node_id"], str)
    assert isinstance(data["sg_code"], str) and data["sg_code"]
    assert isinstance(data["homes_passed"], int)
    assert isinstance(data["warn_threshold_pct"], int)
    assert isinstance(data["critical_threshold_pct"], int)
    assert data["utilization_method"] in {e.value for e in UtilizationMethod}
    assert isinstance(data["downstream_capacity_mbps"], int)
    assert isinstance(data["upstream_capacity_mbps"], int)
    assert isinstance(data["provisioned_downstream_mbps"], int)
    assert isinstance(data["current_load_mbps"], int)
    assert isinstance(data["current_utilization_pct"], (int, float))
    assert data["posture"] in {e.value for e in ServiceGroupPosture}


def assert_utilization_sample(data: dict):
    # Append-only record: id + created_at only, NO updated_at/version (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "UtilizationSample must not carry updated_at"
    assert "version" not in data, "UtilizationSample must not carry version"
    assert isinstance(data["service_group_id"], str)
    assert isinstance(data["measured_at"], str)
    assert isinstance(data["downstream_mbps"], int)
    assert isinstance(data["upstream_mbps"], int)


def assert_capacity_action(data: dict):
    _assert_common(data)
    assert isinstance(data["service_group_id"], str)
    assert data["action_type"] in {e.value for e in CapacityActionType}
    assert data["origin"] in {e.value for e in CapacityActionOrigin}
    assert data["status"] in {e.value for e in CapacityActionStatus}


def assert_node_split_project(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity_action_id"], str)
    assert isinstance(data["child_count"], int)
    assert isinstance(data["min_homes_per_child"], int)
    assert isinstance(data["max_homes_per_child"], int)
    assert data["status"] in {e.value for e in NodeSplitProjectStatus}


def assert_migration_wave(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity_action_id"], str)
    assert isinstance(data["wave_code"], str) and data["wave_code"]
    assert isinstance(data["target_cpe_ids"], list)
    assert data["status"] in {e.value for e in MigrationWaveStatus}


def assert_customer_premise(data: dict):
    _assert_common(data)
    assert isinstance(data["service_group_id"], str)
    assert isinstance(data["premise_ref"], str) and data["premise_ref"]
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["provisioned_downstream_mbps"], int)


def assert_customer_equipment(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_premise_id"], str)
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["docsis_version"], str)
    assert data["capability_class"] in {e.value for e in CapabilityClass}
    assert isinstance(data["max_downstream_mbps"], int)
    assert isinstance(data["video_legacy"], bool)
    assert data["status"] in {e.value for e in CustomerEquipmentStatus}


def assert_speed_tier(data: dict):
    _assert_common(data)
    assert isinstance(data["tier_code"], str) and data["tier_code"]
    assert isinstance(data["downstream_mbps"], int)
    assert isinstance(data["upstream_mbps"], int)
    assert data["min_capability_class"] in {e.value for e in CapabilityClass}
    assert data["min_upstream_config"] in {e.value for e in UpstreamConfig}
    assert data["status"] in {e.value for e in SpeedTierStatus}


def assert_provisioning_request(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_premise_id"], str)
    assert isinstance(data["speed_tier_id"], str)
    assert data["status"] in {e.value for e in ProvisioningRequestStatus}


def assert_refresh_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["franchise_area_id"], str)
    assert isinstance(data["campaign_code"], str) and data["campaign_code"]
    assert data["target_capability_class"] in {CapabilityClass.D31.value, CapabilityClass.D40.value}
    assert data["status"] in {e.value for e in RefreshCampaignStatus}
    assert isinstance(data["targeted_count"], int)
    assert isinstance(data["swapped_count"], int)


def assert_congestion_complaint(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_premise_id"], str)
    assert isinstance(data["description"], str)
    for field in ("plant_signal", "home_signal", "destination_signal"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["status"] in {e.value for e in CongestionComplaintStatus}
    assert isinstance(data["reopen_count"], int)
    if data.get("scoring_variant_used") is not None:
        assert data["scoring_variant_used"] in {e.value for e in ScoringVariant}
    if data.get("cause_category") is not None:
        assert data["cause_category"] in {e.value for e in CauseCategory}


def assert_service_group_capacity_invariants(data: dict):
    """Derived-field invariants that must hold on any service-group read."""
    assert data["downstream_capacity_mbps"] >= 0
    assert data["upstream_capacity_mbps"] in (27, 108, 204)
    assert data["current_load_mbps"] >= 0
    assert data["provisioned_downstream_mbps"] >= 0
