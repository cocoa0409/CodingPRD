"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ─── Enumerations the PRD pins, used for membership assertions ─────────────

FACILITY_TYPES = ["P_AND_DC", "S_AND_DC", "NDC", "ANEX"]
REGION_CLASSES = ["CONTIGUOUS", "NON_CONTIGUOUS"]
FACILITY_STATUSES = ["ACTIVE", "DECOMMISSIONED"]
OCCUPANCY_STATUSES = ["UNDER_CONSTRUCTION", "OCCUPIED", "VACANT", "SEASONAL",
                      "DISCONTINUED"]
POINT_KINDS = ["RESIDENTIAL", "BUSINESS", "CENTRALIZED", "PO_BOX"]
DELIVERY_RESTRICTIONS = ["NONE", "BUSINESS_ONLY_HOURS", "GATED_CODE_ON_FILE",
                         "NO_SECURE_LOCATION"]
CARRIER_CLASSES = ["REGULAR", "CITY_ASSISTANT", "RURAL", "AUXILIARY"]
CARRIER_STATUSES = ["AVAILABLE", "ON_ROUTE", "DETAILED", "INACTIVE"]
ROUTE_TYPES = ["CITY", "RURAL", "HIGHWAY_CONTRACT"]
ROUTE_STATUSES = ["STANDARD", "UNDER_EVALUATION", "UNDER_ADJUSTMENT", "SUSPENDED"]
DELIVERY_ORDER_GROUPS = ["PARK_LOOP", "MOUNTED", "WALKING", "DISMOUNT"]
EVALUATION_KINDS = ["FULL_COUNT", "MINI_SURVEY", "SPECIAL_INSPECTION"]
CONSULTATION_OUTCOMES = ["PENDING", "CONCURRED", "DISPUTED", "WAIVED"]
EVALUATION_STATUSES = ["INITIATED", "DATA_COLLECTION", "CONSULTATION_SCHEDULED",
                       "CONSULTED", "CLOSED_ADOPTED", "CLOSED_REJECTED"]
ADJUSTMENT_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "EFFECTIVE",
                       "WITHDRAWN"]
AUXILIARY_STATUSES = ["REQUESTED", "APPROVED", "ACTIVE", "COMPLETED", "CURTAILED",
                      "DENIED"]
MOVE_KINDS = ["INDIVIDUAL", "FAMILY", "BUSINESS"]
MOVE_TYPES = ["PERMANENT", "TEMPORARY"]
FORWARDING_STATUSES = ["PENDING", "ACTIVE", "SUSPENDED", "EXPIRED", "CANCELLED"]
VALIDATION_STATUSES = ["UNVERIFIED", "VERIFIED", "REJECTED"]
HOLD_DISPOSITIONS = ["ACCUMULATE_DELIVER_ON_END", "CARRIER_PICKUP"]
HOLD_STATUSES = ["SCHEDULED", "ACTIVE", "EXPIRED", "COMPLETED", "CANCELLED"]
MAIL_CLASSES = ["FIRST_CLASS", "PRIORITY", "GROUND_ADVANTAGE", "PERIODICALS",
                "MARKETING"]
RULE_STATUSES = ["SCHEDULED", "ACTIVE", "RETIRED"]
VARIANTS_USED = ["CONTIGUOUS", "NON_CONTIGUOUS"]
SCAN_CODES = ["DELIVERED", "ATTEMPTED_NO_ACCESS", "VACANT_CONFIRMED", "FORWARDED",
              "HELD_AT_OFFICE", "REFUSED"]
INQUIRY_KINDS = ["MISSING_MAIL", "LATE_DELIVERY", "WRONG_DELIVERY",
                 "HOLD_NOT_HONORED", "FORWARD_NOT_RECEIVED"]
INQUIRY_CHANNELS = ["PHONE", "WEB", "WALK_IN"]
INQUIRY_STATUSES = ["OPEN", "INVESTIGATING", "RESOLVED", "RESOLVED_FINAL",
                    "CLOSED_ABANDONED"]
RESOLUTION_CODES = ["FOUND_AND_DELIVERED", "SENDER_CONTACTED", "FORWARD_CONFIRMED",
                    "NO_ERROR_FOUND"]


# ─── Shared envelope-level helpers ─────────────────────────────────────────

def _assert_identity(data: dict):
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"


def _assert_mutable(data: dict):
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


# ─── Per-entity assertions ─────────────────────────────────────────────────

def assert_processing_facility(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert isinstance(data["facility_code"], str) and len(data["facility_code"]) == 3
    assert data["facility_type"] in FACILITY_TYPES
    assert data["region_class"] in REGION_CLASSES
    assert isinstance(data["dispatch_cutoff_local"], str)
    assert isinstance(data["operating_days"], list) and len(data["operating_days"]) > 0
    assert data["status"] in FACILITY_STATUSES


def assert_delivery_unit(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert isinstance(data["unit_code"], str) and len(data["unit_code"]) > 0
    assert isinstance(data["office_name"], str)
    assert is_valid_uuid(data["delivery_office_facility_id"])
    assert isinstance(data["case_slot_count_per_route"], int)
    assert data["universal_service_obligation"] is True
    assert isinstance(data["scan_compliance_target"], (int, float))
    assert isinstance(data["active_route_count"], int)


def assert_delivery_point(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data["delivery_unit_id"])
    assert isinstance(data["address_line1"], str)
    assert isinstance(data["city"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["zip11"], str) and len(data["zip11"]) == 11
    assert data["point_kind"] in POINT_KINDS
    assert data["occupancy_status"] in OCCUPANCY_STATUSES
    assert isinstance(data["vacancy_days"], int)
    assert isinstance(data["is_deliverable"], bool)
    assert data["delivery_restriction"] in DELIVERY_RESTRICTIONS


def assert_carrier(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data["delivery_unit_id"])
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["full_name"], str)
    assert data["carrier_class"] in CARRIER_CLASSES
    assert data["status"] in CARRIER_STATUSES


def assert_carrier_route(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data["delivery_unit_id"])
    assert isinstance(data["route_code"], str)
    assert is_valid_uuid(data["assigned_carrier_id"])
    assert data["route_type"] in ROUTE_TYPES
    assert data["status"] in ROUTE_STATUSES
    assert data["base_evaluated_minutes"] == 480
    assert isinstance(data["current_evaluated_minutes"], int)
    assert isinstance(data["active_delivery_point_count"], int)
    assert isinstance(data["auxiliary_relief_minutes"], int)


def assert_sequence_entry(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data["carrier_route_id"])
    assert is_valid_uuid(data["delivery_point_id"])
    assert isinstance(data["line_of_travel_order"], int) and data["line_of_travel_order"] >= 1
    assert isinstance(data["case_slot_letters"], int)
    assert isinstance(data["case_slot_flats"], int)
    assert data["delivery_order_group"] in DELIVERY_ORDER_GROUPS


def assert_route_evaluation(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data["carrier_route_id"])
    assert data["evaluation_kind"] in EVALUATION_KINDS
    assert isinstance(data["count_week_start"], str)
    assert data["consultation_outcome"] in CONSULTATION_OUTCOMES
    assert data["status"] in EVALUATION_STATUSES
    assert isinstance(data["recollection_used"], bool)


def assert_route_adjustment(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data["route_evaluation_id"])
    assert isinstance(data["proposed_evaluated_minutes"], int)
    assert isinstance(data["points_transferred_out"], list)
    assert data["status"] in ADJUSTMENT_STATUSES
    assert isinstance(data["effective_date"], str)


def assert_auxiliary_assignment(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data["carrier_route_id"])
    assert is_valid_uuid(data["helper_carrier_id"])
    assert isinstance(data["service_date"], str)
    assert isinstance(data["projected_overrun_minutes"], int)
    assert isinstance(data["seasonal_surge_flag"], bool)
    assert data["status"] in AUXILIARY_STATUSES


def assert_change_of_address(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data["delivery_unit_id"])
    assert is_valid_uuid(data["old_delivery_point_id"])
    assert isinstance(data["new_address_line1"], str)
    assert isinstance(data["new_city"], str)
    assert isinstance(data["new_state_code"], str)
    assert isinstance(data["new_zip11"], str)
    assert data["move_kind"] in MOVE_KINDS
    assert data["move_type"] in MOVE_TYPES
    assert isinstance(data["begin_date"], str)
    assert data["forwarding_status"] in FORWARDING_STATUSES
    assert data["validation_status"] in VALIDATION_STATUSES


def assert_hold_mail(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data["delivery_unit_id"])
    assert is_valid_uuid(data["delivery_point_id"])
    assert isinstance(data["hold_start_date"], str)
    assert isinstance(data["hold_end_date"], str)
    assert data["disposition"] in HOLD_DISPOSITIONS
    assert data["status"] in HOLD_STATUSES


def assert_service_standard_rule(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data["origin_facility_id"])
    assert is_valid_uuid(data["dest_facility_id"])
    assert data["mail_class"] in MAIL_CLASSES
    assert isinstance(data["service_days"], int)
    assert isinstance(data["non_contiguous_extra_days"], int)
    assert isinstance(data["effective_from"], str)
    assert data["status"] in RULE_STATUSES


def assert_service_standard_query(data: dict):
    """Append-only computed read: only id + created_at among the common fields."""
    _assert_identity(data)
    assert "version" not in data, "computed-read rows carry no version"
    assert "updated_at" not in data, "computed-read rows carry no updated_at"
    assert is_valid_uuid(data["origin_facility_id"])
    assert is_valid_uuid(data["dest_facility_id"])
    assert data["mail_class"] in MAIL_CLASSES
    assert isinstance(data["acceptance_date"], str)
    assert isinstance(data["acceptance_time_local"], str)
    assert isinstance(data["committed_delivery_date"], str)
    assert isinstance(data["committed_service_days"], int)
    assert data["variant_used"] in VARIANTS_USED


def assert_delivery_scan_event(data: dict):
    """Append-only scan record: only id + created_at among the common fields."""
    _assert_identity(data)
    assert "version" not in data, "append-only scan rows carry no version"
    assert "updated_at" not in data, "append-only scan rows carry no updated_at"
    assert is_valid_uuid(data["carrier_route_id"])
    assert is_valid_uuid(data["delivery_point_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert data["scan_code"] in SCAN_CODES
    assert isinstance(data["scan_datetime"], str)
    assert isinstance(data["gps_within_geofence"], bool)
    assert isinstance(data["is_compliant"], bool)


def assert_customer_inquiry(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data["delivery_unit_id"])
    assert is_valid_uuid(data["delivery_point_id"])
    assert data["inquiry_kind"] in INQUIRY_KINDS
    assert data["opened_by_channel"] in INQUIRY_CHANNELS
    assert data["status"] in INQUIRY_STATUSES
    assert isinstance(data["reopened_count"], int)
