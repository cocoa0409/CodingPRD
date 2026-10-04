"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["phone"], str) and len(data["phone"]) > 0
    assert data["account_status"] in ["ACTIVE", "LOCKED", "CLOSED"]


def assert_device(data: dict):
    _assert_common(data, "Device")
    assert is_valid_uuid(data.get("customer_id", "")), "Device.customer_id must be a UUID"
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert isinstance(data["model_code"], str) and len(data["model_code"]) > 0
    assert isinstance(data["activation_lock_enabled"], bool)
    assert isinstance(data["proof_of_purchase_on_file"], bool)
    assert isinstance(data["purchase_date"], str)
    assert data["device_status"] in ["ACTIVE", "IN_SERVICE", "RETIRED"]


def assert_coverage_plan(data: dict):
    _assert_common(data, "CoveragePlan")
    assert is_valid_uuid(data.get("device_id", "")), "CoveragePlan.device_id must be a UUID"
    assert data["plan_type"] in ["LIMITED_WARRANTY", "APPLECARE_PLUS", "OUT_OF_WARRANTY"]
    assert isinstance(data["accidental_damage_incidents_used"], int)
    assert data["accidental_damage_incidents_used"] >= 0
    assert isinstance(data["accidental_damage_incident_limit"], int)
    assert data["accidental_damage_incident_limit"] >= 0
    assert isinstance(data["service_fee_cents"], int)
    assert data["service_fee_cents"] >= 0
    assert data["coverage_status"] in ["ACTIVE", "EXPIRED", "EXHAUSTED", "CANCELLED"]


def assert_service_location(data: dict):
    _assert_common(data, "ServiceLocation")
    assert isinstance(data["location_code"], str) and len(data["location_code"]) > 0
    assert data["location_type"] in ["RETAIL_STORE", "AUTHORIZED_PROVIDER", "MAIL_IN_DEPOT"]
    assert isinstance(data["address"], str)
    assert isinstance(data["supports_same_day_repair"], bool)
    assert isinstance(data["supports_express_replacement"], bool)
    assert isinstance(data["diagnostic_slot_duration_minutes"], int)
    assert data["location_status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]


def assert_technician(data: dict):
    _assert_common(data, "Technician")
    assert is_valid_uuid(data.get("location_id", "")), "Technician.location_id must be a UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["certification_level"] in ["BASIC", "ADVANCED", "EXPERT"]
    assert isinstance(data["is_active"], bool)


def assert_part(data: dict):
    _assert_common(data, "Part")
    assert isinstance(data["part_number"], str) and len(data["part_number"]) > 0
    assert isinstance(data["model_code"], str) and len(data["model_code"]) > 0
    assert data["part_category"] in [
        "DISPLAY", "BATTERY", "LOGIC_BOARD", "CAMERA", "ENCLOSURE", "OTHER",
    ]
    assert isinstance(data["is_whole_unit_replacement"], bool)
    assert data["part_status"] in ["ACTIVE", "DISCONTINUED", "RECALLED"]


def assert_part_inventory(data: dict):
    _assert_common(data, "PartInventory")
    assert is_valid_uuid(data.get("location_id", ""))
    assert is_valid_uuid(data.get("part_id", ""))
    for field in ("on_hand_quantity", "reserved_quantity", "express_replacement_quantity"):
        assert isinstance(data[field], int), f"PartInventory.{field} must be int"
        assert data[field] >= 0, f"PartInventory.{field} must be non-negative"


def assert_part_inventory_invariants(data: dict):
    """The three stored counters are non-negative and available_quantity is
    computed on read as on-hand minus reserved minus express-replacement."""
    assert_part_inventory(data)
    expected_available = (
        data["on_hand_quantity"]
        - data["reserved_quantity"]
        - data["express_replacement_quantity"]
    )
    if "available_quantity" in data:
        assert data["available_quantity"] == expected_available, (
            f"available_quantity must equal on_hand - reserved - express_replacement "
            f"({expected_available}), got {data['available_quantity']}"
        )


def assert_appointment(data: dict):
    _assert_common(data, "Appointment")
    for field in ("customer_id", "device_id", "location_id", "technician_id"):
        assert is_valid_uuid(data.get(field, "")), f"Appointment.{field} must be a UUID"
    assert isinstance(data["slot_start"], str)
    assert isinstance(data["slot_end"], str)
    assert data["issue_category"] in [
        "SCREEN_DAMAGE", "BATTERY", "WATER_DAMAGE", "SOFTWARE", "HARDWARE_OTHER",
    ]
    assert data["appointment_status"] in [
        "SCHEDULED", "CHECKED_IN", "IN_DIAGNOSIS", "COMPLETED", "CANCELLED", "NO_SHOW",
    ]


def assert_repair_order(data: dict):
    _assert_common(data, "RepairOrder")
    for field in ("appointment_id", "device_id", "customer_id", "origin_location_id"):
        assert is_valid_uuid(data.get(field, "")), f"RepairOrder.{field} must be a UUID"
    assert data["issue_category"] in [
        "SCREEN_DAMAGE", "BATTERY", "WATER_DAMAGE", "SOFTWARE", "HARDWARE_OTHER",
    ]
    assert isinstance(data["is_accidental_damage"], bool)
    assert isinstance(data["quoted_price_cents"], int)
    assert data["quoted_price_cents"] >= 0, "No price may be negative"
    assert isinstance(data["data_backup_acknowledged"], bool)
    assert isinstance(data["privacy_wipe_consent"], bool)
    assert isinstance(data["repeat_repair_count"], int)
    assert data["repeat_repair_count"] >= 0
    assert data["repair_status"] in [
        "TRIAGED", "PARTS_ALLOCATED", "IN_PROGRESS", "QUALITY_CHECK",
        "READY_FOR_PICKUP", "SHIPPED_TO_DEPOT", "IN_TRANSIT_BACK",
        "COMPLETED", "CANCELLED", "ESCALATED_REPEAT",
    ]


def assert_part_allocation(data: dict):
    _assert_common(data, "PartAllocation")
    for field in ("repair_order_id", "part_id", "location_id"):
        assert is_valid_uuid(data.get(field, "")), f"PartAllocation.{field} must be a UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["allocation_status"] in ["RESERVED", "CONSUMED", "RELEASED", "BACKORDERED"]


def assert_coverage_entitlement(data: dict):
    _assert_common(data, "CoverageEntitlement")
    assert is_valid_uuid(data.get("repair_order_id", ""))
    assert is_valid_uuid(data.get("coverage_plan_id", ""))
    assert data["entitlement_status"] in [
        "PENDING_VERIFICATION", "ENTITLED", "PARTIALLY_ENTITLED",
        "NOT_ENTITLED", "WAIVED",
    ]
    assert isinstance(data["quoted_price_cents"], int)
    assert data["quoted_price_cents"] >= 0, "No price may be negative"
    assert isinstance(data["incident_counted"], bool)


def assert_quality_follow_up(data: dict):
    _assert_common(data, "QualityFollowUp")
    assert is_valid_uuid(data.get("repair_order_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["follow_up_status"] in [
        "OPEN", "RESOLVED_SATISFIED", "RESOLVED_REPEAT_REPAIR", "ESCALATED",
    ]
    assert is_iso8601_timestamp(data.get("opened_at", "")), "opened_at must be ISO 8601"


def assert_security_verification(data: dict):
    _assert_common(data, "SecurityVerification")
    assert is_valid_uuid(data.get("repair_order_id", ""))
    assert data["verification_type"] in [
        "ACTIVATION_LOCK_REMOVAL", "OWNERSHIP_PROOF", "ACCOUNT_UNLOCK",
    ]
    assert data["verification_status"] in ["PENDING", "VERIFIED", "FAILED", "EXPIRED"]


def assert_repair_shipment(data: dict):
    _assert_common(data, "RepairShipment")
    for field in ("repair_order_id", "from_location_id", "to_location_id"):
        assert is_valid_uuid(data.get(field, "")), f"RepairShipment.{field} must be a UUID"
    assert data["shipment_type"] in [
        "CUSTOMER_TO_DEPOT", "DEPOT_TO_CUSTOMER", "STORE_TO_DEPOT", "DEPOT_TO_STORE",
    ]
    assert data["shipment_status"] in [
        "LABEL_CREATED", "IN_TRANSIT", "RECEIVED", "DELIVERED", "LOST",
    ]
    assert isinstance(data["tracking_number"], str) and len(data["tracking_number"]) > 0
