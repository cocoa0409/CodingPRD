"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_customer_account(data):
    _assert_common_fields(data, "CustomerAccount")
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert data["account_tier"] in ("STANDARD", "PREMIER", "FEDERAL")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert isinstance(data["recovery_credit_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_account_program(data):
    _assert_common_fields(data, "AccountProgram")
    assert isinstance(data["account_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["locked"], bool)
    assert isinstance(data["asset_tag_prefix"], str)
    assert isinstance(data["custom_image_ref"], str)
    assert data["status"] in ("OPEN", "LOCKED", "RETIRED")


def assert_chassis_model(data):
    _assert_common_fields(data, "ChassisModel")
    assert isinstance(data["model_code"], str)
    assert data["category"] in ("LAPTOP", "DESKTOP", "SERVER", "WORKSTATION")
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["build_duration_hours"], int)
    assert data["status"] in ("CATALOG", "EOL")


def assert_component(data):
    _assert_common_fields(data, "Component")
    assert isinstance(data["sku"], str)
    assert data["kind"] in (
        "CPU", "MEMORY", "STORAGE", "GPU", "NIC", "PSU", "WIFI", "DISPLAY", "OS_IMAGE",
    )
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["lead_time_days"], int)
    assert isinstance(data["stock_on_hand"], int)
    assert isinstance(data["reserved_units"], int)
    assert isinstance(data["available_units"], int)
    assert isinstance(data["revision"], str)
    assert data["status"] in ("ACTIVE", "EOL")


def assert_component_pool_invariant(data):
    """available_units == stock_on_hand - reserved_units must always hold."""
    assert data["available_units"] == data["stock_on_hand"] - data["reserved_units"], (
        f"Pool invariant violated: available_units {data['available_units']} != "
        f"stock_on_hand {data['stock_on_hand']} - reserved_units {data['reserved_units']}"
    )


def assert_compatibility_rule(data):
    # Immutable record: id + created_at only; no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "CompatibilityRule.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "CompatibilityRule must not carry version"
    assert "updated_at" not in data, "CompatibilityRule must not carry updated_at"
    assert data["rule_type"] in ("ALLOWED", "REQUIRES", "EXCLUDES", "MIN_QTY")


def assert_configuration_template(data):
    _assert_common_fields(data, "ConfigurationTemplate")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["chassis_model_id"], str)
    assert isinstance(data["pinned_components"], list)
    assert data["status"] in ("DRAFT", "PUBLISHED", "LOCKED", "RETIRED")


def assert_configuration(data):
    _assert_common_fields(data, "Configuration")
    assert isinstance(data["account_id"], str)
    assert isinstance(data["chassis_model_id"], str)
    assert isinstance(data["component_selections"], list)
    assert isinstance(data["compatibility_ok"], bool)
    assert data["status"] in ("DRAFT", "VALIDATED", "LOCKED", "SUPERSEDED")


def assert_order(data):
    _assert_common_fields(data, "Order")
    assert isinstance(data["account_id"], str)
    assert isinstance(data["po_number"], str)
    assert data["build_status"] in (
        "DRAFT", "SUBMITTED", "ALLOCATED", "IN_PRODUCTION", "BUILT", "ON_HOLD", "CANCELLED",
    )
    assert data["ship_status"] in (
        "PENDING", "STAGED", "PARTIALLY_SHIPPED", "SHIPPED", "DELIVERED",
    )


def assert_order_line(data):
    _assert_common_fields(data, "OrderLine")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["configuration_id"], str)
    assert isinstance(data["qty"], int)
    assert data["ship_to_mode"] in ("SINGLE_ADDRESS", "DROP_SHIP_EMPLOYEES")
    assert data["status"] in ("OPEN", "FULFILLED", "CANCELLED")


def assert_build_job(data):
    _assert_common_fields(data, "BuildJob")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["qty"], int)
    assert data["status"] in (
        "QUEUED", "ALLOCATED", "BUILDING", "COMPLETE", "SHORTAGE_BLOCKED", "CANCELLED",
    )


def assert_substitution_request(data):
    _assert_common_fields(data, "SubstitutionRequest")
    assert isinstance(data["build_job_id"], str)
    assert isinstance(data["original_component_id"], str)
    assert isinstance(data["proposed_component_id"], str)
    assert isinstance(data["price_delta_cents"], int)
    assert isinstance(data["round"], int)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "SUPERSEDED")


def assert_deployment_wave(data):
    _assert_common_fields(data, "DeploymentWave")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["wave_label"], str)
    assert isinstance(data["ship_window_start"], str)
    assert isinstance(data["ship_window_end"], str)
    assert isinstance(data["destinations"], list)
    assert data["status"] in ("PLANNED", "RELEASED", "SHIPPED", "RECEIVED", "CANCELLED")


def assert_asset(data):
    _assert_common_fields(data, "Asset")
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["status"] in (
        "STAGED", "IN_TRANSIT", "DELIVERED", "RECOVERY_REQUESTED", "RECOVERED",
    )


def assert_support_entitlement(data):
    _assert_common_fields(data, "SupportEntitlement")
    assert isinstance(data["order_line_id"], str)
    assert data["tier"] in ("BASIC", "NBD", "ONSITE_4H")
    assert isinstance(data["coverage_start"], str)
    assert isinstance(data["coverage_end"], str)
    assert isinstance(data["parts_stocking_required"], bool)
    assert data["status"] in ("ACTIVE", "EXPIRED", "CANCELLED")


def assert_recovery_request(data):
    _assert_common_fields(data, "AssetRecoveryRequest")
    assert isinstance(data["account_id"], str)
    assert isinstance(data["asset_id"], str)
    assert data["program_kind"] in ("RECYCLE", "RESALE_CREDIT")
    assert data["status"] in (
        "INITIATED", "LABEL_ISSUED", "RECEIVED", "CREDITED", "RECYCLED", "CANCELLED",
    )
