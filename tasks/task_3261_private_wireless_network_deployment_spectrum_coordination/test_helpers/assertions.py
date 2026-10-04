"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def _assert_lightweight_common(data: dict):
    """SliceBinding and MonitoringAlert carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "updated_at must be absent on lightweight resources"
    assert "version" not in data, "version must be absent on lightweight resources"


def assert_enterprise(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["erp_account_code"], str) and data["erp_account_code"]
    assert data["industry_vertical"] in {"CAMPUS", "FACTORY", "VENUE", "LOGISTICS", "ENERGY"}
    assert data["security_posture"] in {"STANDARD", "ELEVATED", "CRITICAL"}
    assert data["status"] in {"ONBOARDING", "ACTIVE", "SUSPENDED", "OFFBOARDED"}
    assert isinstance(data["sla_credit_balance_cents"], int)
    assert isinstance(data["active_site_count"], int)


def assert_site(data: dict):
    _assert_common(data)
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert data["status"] in {
        "PLANNED", "SURVEYED", "DESIGNED", "COORDINATED", "DEPLOYED",
        "OPERATIONAL", "REMEDIATION_REQUIRED", "DECOMMISSIONED",
    }
    assert data["posture"] in {
        "DORMANT", "DESIGNING", "COORDINATING", "DEPLOYING", "OPERATIONAL", "REMEDIATING",
    }
    assert isinstance(data["spectrum_utilization_mhz"], int)
    assert isinstance(data["device_count"], int)


def assert_survey(data: dict):
    _assert_common(data)
    assert data["building_material_class"] in {"OPEN", "WOOD", "CONCRETE", "STEEL", "MIXED"}
    assert data["status"] in {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"}
    assert isinstance(data["measured_rsrp_dbm"], int)
    assert isinstance(data["attenuation_factor_db"], int)


def assert_design(data: dict):
    _assert_common(data)
    assert data["status"] in {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"}
    assert isinstance(data["design_revision"], int) and data["design_revision"] >= 1
    assert data["edge_compute_placement"] in {"NONE", "ON_PREMISE", "NEAR_EDGE", "FAR_EDGE"}


def assert_cell(data: dict):
    _assert_common(data)
    assert data["status"] in {
        "PLANNED", "CONFIGURED", "ON_AIR", "DEGRADED", "OFF_AIR", "DECOMMISSIONED",
    }
    assert 0 <= data["azimuth_degrees"] <= 359


def assert_lease(data: dict):
    _assert_common(data)
    assert data["band_class"] in {
        "LICENSED_C_BAND", "SHARED_CBRS", "UNLICENSED_5GHZ", "UNLICENSED_6GHZ",
    }
    assert data["status"] in {"PENDING", "ACTIVE", "SUSPENDED", "EXPIRED", "CANCELLED"}
    assert isinstance(data["bandwidth_mhz"], int)


def assert_coordination_request(data: dict):
    _assert_common(data)
    assert data["status"] in {
        "DRAFT", "SUBMITTED", "COORDINATING", "APPROVED", "REGISTERED",
        "REJECTED", "WITHDRAWN",
    }
    assert isinstance(data["requested_bandwidth_mhz"], int)


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in {"ACTIVE", "RELEASED", "REVOKED"}
    assert isinstance(data["assigned_bandwidth_mhz"], int)


def assert_device(data: dict):
    _assert_common(data)
    assert data["device_type"] in {"CPE", "SENSOR", "HANDSET", "AGV", "CAMERA", "GATEWAY"}
    assert data["status"] in {"INVENTORY", "PROVISIONING", "ACTIVE", "SUSPENDED", "DECOMMISSIONED"}


def assert_sim_profile(data: dict):
    _assert_common(data)
    assert data["subscription_profile"] in {"STANDARD", "IOT_NBIOT", "IOT_CATM", "PREMIUM_5G"}
    assert data["status"] in {"UNASSIGNED", "BOUND", "ACTIVE", "SUSPENDED", "RETIRED"}
    imsi = data["imsi"]
    assert isinstance(imsi, str) and len(imsi) == 15 and imsi.isdigit()


def assert_slice(data: dict):
    _assert_common(data)
    assert data["slice_type"] in {"EMBB", "URLLC", "MMTC"}
    assert data["status"] in {"DEFINED", "ACTIVATED", "SUSPENDED", "RETIRED"}
    assert isinstance(data["bound_device_count"], int) and data["bound_device_count"] >= 0


def assert_slice_binding(data: dict):
    _assert_lightweight_common(data)


def assert_contract(data: dict):
    _assert_common(data)
    assert data["sla_tier"] in {"STANDARD", "ENHANCED", "MISSION_CRITICAL"}
    assert data["status"] in {"DRAFT", "ACTIVE", "BREACHED", "RENEWED", "TERMINATED"}
    assert data["onsite_support_window"] in {"NEXT_BUSINESS_DAY", "FOUR_HOUR", "TWO_HOUR"}


def assert_alert(data: dict):
    _assert_lightweight_common(data)
    assert data["alert_class"] in {"OUTAGE", "DEGRADATION", "INTERFERENCE", "CAPACITY", "SECURITY"}
    assert data["severity"] in {"INFO", "MINOR", "MAJOR", "CRITICAL"}
    assert data["status"] in {"OPEN", "ACKNOWLEDGED", "MITIGATING", "RESOLVED", "FALSE_ALARM"}


def assert_remediation(data: dict):
    _assert_common(data)
    assert data["status"] in {
        "PROPOSED", "APPROVED", "IN_PROGRESS", "VERIFYING", "COMPLETED", "REOPENED",
    }
    assert isinstance(data["additional_cells_planned"], int)
