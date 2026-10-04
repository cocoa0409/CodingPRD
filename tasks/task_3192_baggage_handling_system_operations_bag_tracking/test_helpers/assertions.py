"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

HANDLED_ENTITY_KEYS = (
    "id", "created_at", "updated_at", "version",
)


def _assert_common_fields(data: dict, label: str):
    """Every principal resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be a positive integer"


def assert_station(data: dict):
    _assert_common_fields(data, "Station")
    assert data["posture"] in ("OPEN", "CONGESTED", "SUSPENDED")
    assert isinstance(data["outage_active"], bool)
    assert isinstance(data["active_bag_count"], int) and data["active_bag_count"] >= 0
    assert isinstance(data["manual_queue_depth"], int) and data["manual_queue_depth"] >= 0
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0


def assert_station_ledger(data: dict) -> dict:
    """The two ledger halves partition the report set (PRD §2.14)."""
    assert data["open_liability_cents"] >= 0
    assert data["settled_liability_cents"] >= 0
    return data


def assert_airline(data: dict):
    _assert_common_fields(data, "Airline")
    assert isinstance(data["code"], str) and len(data["code"]) == 2
    assert isinstance(data["interline_agreement_active"], bool)
    assert isinstance(data["compensation_cap_cents"], int)


def assert_flight(data: dict):
    _assert_common_fields(data, "Flight")
    assert data["status"] in ("SCHEDULED", "SORT_OPEN", "BOARDING", "DEPARTED", "CANCELLED")
    assert isinstance(data["makeup_ready"], bool)
    assert isinstance(data["loaded_bag_count"], int)


def assert_makeup_area(data: dict):
    _assert_common_fields(data, "MakeupArea")
    assert data["status"] in ("ACTIVE", "CLOSED")
    assert data["occupied_slots"] >= 0
    assert data["released_slots"] >= 0
    assert data["free_slots"] == data["capacity_slots"] - data["occupied_slots"], \
        "free_slots is capacity_slots minus occupied_slots"


def assert_screening_lane(data: dict):
    _assert_common_fields(data, "ScreeningLane")
    assert data["status"] in ("ACTIVE", "OFFLINE")


def assert_bag(data: dict):
    _assert_common_fields(data, "Bag")
    assert data["custody_status"] in (
        "ACCEPTED", "SCREENING", "SORTED", "IN_MAKEUP",
        "LOADED", "DELIVERED", "HELD", "OFFLOADED",
    )
    assert data["screening_status"] in (
        "PENDING", "IN_LINE", "CLEARED", "ALARMED", "IN_INSPECTION", "FAILED",
    )
    assert data["routing_class"] in ("STANDARD", "MANUAL", "BULK_HOLD")
    assert data["itinerary_type"] in ("DOMESTIC", "INTERNATIONAL", "INTERLINE")
    assert isinstance(data["linear_in"], (int, float))
    assert isinstance(data["duplicate_flag"], bool)
    assert isinstance(data["rush_declared"], bool)


def assert_bag_charge_invariant(data: dict):
    """A bag's charges are never negative integers of cents."""
    assert data["handling_charge_cents"] >= 0
    assert data["excess_weight_fee_cents"] >= 0


def assert_scan(data: dict):
    _assert_common_fields(data, "BagScan")
    assert data["scan_point"] in (
        "INDUCTION", "SCREENING", "SORTATION", "MAKEUP", "LOAD", "DELIVERY",
    )
    assert data["scan_source"] in ("AUTOMATED", "MANUAL")
    assert data["result"] in ("OK", "REJECT")


def assert_screening_event(data: dict):
    _assert_common_fields(data, "ScreeningEvent")
    assert data["status"] in ("IN_PROGRESS", "CLEARED", "ALARMED", "FAILED")
    assert is_iso8601_timestamp(data["start_utc"])


def assert_inspection_task(data: dict):
    _assert_common_fields(data, "ManualInspectionTask")
    assert data["status"] in ("QUEUED", "IN_PROGRESS", "RESOLVED", "ESCALATED")
    assert isinstance(data["queue_position"], int) and data["queue_position"] >= 1


def assert_connection(data: dict):
    _assert_common_fields(data, "Connection")
    assert data["status"] in (
        "PENDING", "CONFIRMED", "RUSH", "MISSED", "REACCOMMODATED",
    )
    assert isinstance(data["connect_slack_minutes"], int)


def assert_special_item(data: dict):
    _assert_common_fields(data, "SpecialItem")
    assert data["item_type"] in (
        "OVERSIZE", "FRAGILE", "SPORTS_EQUIPMENT", "MOBILITY_DEVICE",
    )
    assert isinstance(data["requires_manual_screening"], bool)
    assert isinstance(data["liability_cap_cents"], int)


def assert_report(data: dict):
    _assert_common_fields(data, "MishandledReport")
    assert data["status"] in (
        "REPORTED", "INVESTIGATING", "DELIVERY_ARRANGED", "DELIVERED",
        "COMPENSATED", "REOPENED", "CLOSED",
    )
    assert data["claim_status"] in ("NONE", "FILED", "APPROVED", "SETTLED", "DENIED")
    assert isinstance(data["final_liability_cents"], int)
    assert isinstance(data["compensation_settled_cents"], int)


def assert_report_liability_floor(data: dict):
    """final_liability_cents is never negative."""
    assert data["final_liability_cents"] >= 0


def assert_claim(data: dict):
    _assert_common_fields(data, "Claim")
    assert data["decision"] in ("PENDING", "APPROVED", "DENIED")


def assert_delivery(data: dict):
    _assert_common_fields(data, "Delivery")
    assert data["status"] in (
        "PENDING", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED", "COMPENSATED",
    )
    assert data["method"] in (
        "COURIER", "PASSENGER_PICKUP", "FORWARD_ON_NEXT_FLIGHT",
    )
    assert isinstance(data["proof_required"], bool)


def assert_tracking_bundle(data: dict):
    """Passenger tracking lookup payload (PRD §3.7)."""
    assert isinstance(data["tag_number"], str)
    assert data["custody_status"] in (
        "ACCEPTED", "SCREENING", "SORTED", "IN_MAKEUP",
        "LOADED", "DELIVERED", "HELD", "OFFLOADED",
    )
    assert isinstance(data["onboard"], bool)
    assert isinstance(data["open_reports"], int)
    assert isinstance(data["scan_trail"], list)


def assert_scan_trail_ordered(scan_trail: list):
    """The scan trail is ordered by scan_utc ascending (PRD §3.7)."""
    stamps = [row["scan_utc"] for row in scan_trail]
    assert stamps == sorted(stamps), "scan_trail must be ordered by scan_utc ascending"