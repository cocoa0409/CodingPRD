"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_resort(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Resort.id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["park_capacity_occupancy_units"] >= 1
    assert 0 <= data["day_pass_cap_units"] <= data["park_capacity_occupancy_units"]
    assert data["pool_posture"] in ["OPEN", "CLOSED"]
    assert isinstance(data["ops_run_index"], int)
    assert isinstance(data["manager_override_used"], bool)
    assert isinstance(data["managers"], list)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_room_type(data: dict):
    assert is_valid_uuid(data.get("id", "")), "RoomType.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_reservation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Reservation.id must be a valid UUID"
    assert data["booking_status"] in ["RESERVED", "CHECKED_OUT", "CANCELLED"]
    assert data["stay_status"] in ["NOT_STARTED", "IN_HOUSE", "DEPARTED"]
    assert data["guest_count"] >= 1
    assert data["waterpark_included_units"] == data["guest_count"]
    assert isinstance(data["package_rate_total_cents"], int)
    assert isinstance(data["package_rate_withheld_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_day_pass(data: dict):
    assert is_valid_uuid(data.get("id", "")), "DayPass.id must be a valid UUID"
    assert data["day_pass_status"] in ["RESERVED", "ADMITTED", "VOID", "EXPIRED"]
    assert data["units_requested"] >= 1
    assert isinstance(data["price_total_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_wristband(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Wristband.id must be a valid UUID"
    assert data["holder_type"] in ["RESERVATION_GUEST", "DAY_PASS_GUEST", "GROUP_MEMBER"]
    assert data["wristband_status"] in ["ISSUED", "ACTIVE", "REVOKED", "EXPIRED", "REISSUED"]
    assert data["access_status"] in ["PENDING", "GRANTED", "DENIED"]
    assert isinstance(data["room_charge_enabled"], bool)
    assert data["arcade_credit_spent_cents"] >= 0
    assert data["arcade_credit_remaining_cents"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_attraction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Attraction.id must be a valid UUID"
    assert data["required_certification"] in ["LIFEGUARD", "NONE"]
    assert data["attraction_status"] in ["OPEN", "LIMITED", "CLOSED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_lifeguard_shift(data: dict):
    assert is_valid_uuid(data.get("id", "")), "LifeguardShift.id must be a valid UUID"
    assert data["certification_code"] in ["LIFEGUARD", "NONE"]
    assert data["shift_status"] in ["SCHEDULED", "ON_DUTY", "ROTATED", "COMPLETED"]
    assert data["end_minute"] > data["start_minute"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_water_quality_log(data: dict):
    assert is_valid_uuid(data.get("id", "")), "WaterQualityLog.id must be a valid UUID"
    assert data["log_status"] in ["PASS", "FAIL"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_admission_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "AdmissionEvent.id must be a valid UUID"
    assert data["direction"] in ["IN", "OUT"]
    assert data["event_status"] in ["ACCEPTED", "REJECTED"]
    assert isinstance(data["units_delta"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_cabana(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Cabana.id must be a valid UUID"
    assert data["cabana_kind"] in ["CABANA", "PARTY_ROOM"]
    assert data["cabana_status"] in ["AVAILABLE", "HELD", "BOOKED", "RELEASED"]
    assert data["capacity_units"] >= 1
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_cabana_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "CabanaBooking.id must be a valid UUID"
    assert data["cabana_booking_status"] in [
        "HELD", "BOOKED", "CANCELLED", "EXPIRED", "COMPLETED"
    ]
    assert isinstance(data["members"], list)
    assert data["member_units"] >= 1
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_group_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "GroupBooking.id must be a valid UUID"
    assert data["group_kind"] in ["BIRTHDAY", "SCHOOL", "FAMILY_REUNION", "CORPORATE"]
    assert data["group_status"] in ["PENDING_DEPOSIT", "CONFIRMED", "CANCELLED"]
    assert data["member_count"] >= 1
    assert data["deposit_paid_cents"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_group_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "GroupMember.id must be a valid UUID"
    assert isinstance(data["checked_in"], bool)
    assert data["member_units"] >= 1
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_activity_session(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ActivitySession.id must be a valid UUID"
    assert data["tier_code"] in ["STANDARD", "PREMIUM", "VIP"]
    assert data["capacity_units"] >= 1
    assert data["opt_in_gate"] in ["ADMIT", "HOLD"]
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_activity_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ActivityBooking.id must be a valid UUID"
    assert data["activity_booking_status"] in ["PENDING_PAYMENT", "CONFIRMED", "CANCELLED"]
    assert data["attendees"] >= 1
    assert isinstance(data["activity_rate_total_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_arcade_credit_grant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ArcadeCreditGrant.id must be a valid UUID"
    assert data["grant_status"] in ["PENDING", "SUCCEEDED", "DECLINED"]
    assert data["amount_cents"] >= 1
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_wristband_credit_invariants(data: dict):
    """The drawn and remaining arcade balances must reconcile with the ceiling."""
    drawn = data["arcade_credit_spent_cents"]
    remaining = data["arcade_credit_remaining_cents"]
    limit = data["arcade_credit_limit_cents"]
    assert remaining >= 0, "remaining credit is floored at 0 and never negative"
    assert drawn + remaining == max(limit, drawn), (
        f"drawn {drawn} + remaining {remaining} must reconcile against ceiling {limit}"
    )