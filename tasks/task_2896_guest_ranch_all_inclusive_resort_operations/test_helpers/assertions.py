"""Entity assertions and domain invariant checkers."""
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant, instants_equal


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

def assert_identity_fields(data: dict, versioned: bool = True) -> None:
    """Every row carries a UUID id and an ISO-8601 created_at.  Versioned rows
    additionally carry updated_at and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if versioned:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int), "version must be an integer"
        assert data["version"] >= 1, "version starts at 1"


def assert_no_version_fields(data: dict) -> None:
    """Append-only rows carry neither updated_at nor version."""
    assert "updated_at" not in data, "append-only rows must not carry updated_at"
    assert "version" not in data, "append-only rows must not carry version"


def assert_cents(value, field: str) -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer count of cents, got {value!r}"
    )


def assert_instant_equals(actual: Optional[str], expected: Optional[str], field: str) -> None:
    assert instants_equal(actual, expected), (
        f"{field} expected {canonical_instant(expected)}, got {canonical_instant(actual)}"
    )


# --------------------------------------------------------------------------
# per-entity assertions
# --------------------------------------------------------------------------

def assert_season(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["arrival_weekday"] in [
        "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY",
    ]
    assert isinstance(data["season_start_date"], str)
    assert isinstance(data["season_end_date"], str)
    assert isinstance(data["min_stay_nights"], int)
    assert isinstance(data["max_stay_nights"], int)
    assert data["max_stay_nights"] >= data["min_stay_nights"]
    assert 0 < float(data["deposit_pct"]) <= 1
    assert isinstance(data["dining_seat_capacity"], int) and data["dining_seat_capacity"] >= 1
    assert isinstance(data["package_tiers"], list) and len(data["package_tiers"]) >= 1
    for tier in data["package_tiers"]:
        assert isinstance(tier["code"], str) and tier["code"]
        assert_cents(tier["adult_nightly_rate_cents"], "adult_nightly_rate_cents")
        assert 0 <= float(tier["child_discount_pct"]) <= 1
        assert_cents(tier["included_activity_credit_cents"], "included_activity_credit_cents")
    assert data["season_status"] in [
        "PLANNING", "OPEN", "IN_SEASON", "CLOSED", "OFF_SEASON",
    ]
    for money_field in (
        "no_show_penalty_cents",
        "retention_bonus_cents",
        "gross_package_revenue_cents",
        "retention_bonus_liability_cents",
        "net_surplus_cents",
        "capital_reserve_cents",
        "capital_committed_cents",
    ):
        assert_cents(data[money_field], money_field)
    assert isinstance(data["bed_nights_sold"], int)
    assert isinstance(data["in_house_guest_count"], int)


def assert_cabin(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["bed_capacity"], int) and data["bed_capacity"] >= 1
    assert data["cabin_status"] in ["READY", "OCCUPIED", "TURNOVER", "OUT_OF_SERVICE"]
    assert_cents(data["maintenance_capital_cost_cents"], "maintenance_capital_cost_cents")


def assert_guest(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["birth_date"], str)
    assert float(data["weight_lb"]) > 0
    assert isinstance(data["age_years"], int) and data["age_years"] >= 0
    assert data["guest_standing"] in ["GOOD", "RESTRICTED", "SUSPENDED"]
    assert data["waiver_status"] in ["NONE", "SIGNED", "EXPIRED", "REVOKED"]
    assert isinstance(data["equine_statute_ack"], bool)
    for rank_field in ("current_ability_rank", "effective_ability_rank"):
        assert data[rank_field] in [
            "UNASSESSED", "BEGINNER", "NOVICE", "INTERMEDIATE", "ADVANCED",
        ]


def assert_rider_assessment(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["guest_id"])
    assert data["requested_ability"] in ["BEGINNER", "NOVICE", "INTERMEDIATE", "ADVANCED"]
    assert data["assessment_status"] in [
        "PENDING", "EVALUATED", "RE_EVALUATION_REQUESTED", "SUPERSEDED",
    ]
    if data.get("assessed_ability") is not None:
        assert data["assessed_ability"] in [
            "BEGINNER", "NOVICE", "INTERMEDIATE", "ADVANCED",
        ]


def assert_booking(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["cabin_id"])
    assert is_valid_uuid(data["lead_guest_id"])
    assert isinstance(data["package_tier_code"], str) and data["package_tier_code"]
    assert isinstance(data["arrival_date"], str)
    assert isinstance(data["departure_date"], str)
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert isinstance(data["party_members"], list) and len(data["party_members"]) >= 1
    assert data["party_size"] == len(data["party_members"])
    assert data["adult_count"] + data["child_count"] == data["party_size"]
    assert data["booking_status"] in [
        "HELD", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED",
    ]
    assert data["payment_status"] in [
        "AWAITING_DEPOSIT", "DEPOSIT_PAID", "PAID_IN_FULL",
        "PARTIALLY_REFUNDED", "REFUNDED", "FORFEITED",
    ]
    for money_field in (
        "provisional_package_total_cents",
        "deposit_required_cents",
        "deposit_paid_cents",
        "payments_applied_cents",
        "refunded_cents",
        "forfeited_cents",
        "activity_surcharge_total_cents",
        "activity_credit_applied_cents",
        "no_show_penalty_total_cents",
        "gratuity_cents",
        "folio_adjustment_total_cents",
        "realized_subtotal_cents",
        "final_folio_total_cents",
        "folio_balance_cents",
    ):
        assert_cents(data[money_field], money_field)


def assert_horse(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    for rank_field in ("min_rider_ability", "max_rider_ability"):
        assert data[rank_field] in ["BEGINNER", "NOVICE", "INTERMEDIATE", "ADVANCED"]
    assert float(data["weight_limit_lb"]) > 0
    assert data["horse_status"] in [
        "IN_SERVICE", "REST", "LAME", "REHAB", "REVIEW_HOLD", "RETIRED",
    ]
    assert float(data["scheduled_load_hours"]) >= 0
    assert float(data["realized_load_hours"]) >= 0
    assert isinstance(data["consecutive_duty_days"], int) and data["consecutive_duty_days"] >= 0


def assert_horse_health_event(data: dict) -> None:
    """Herd-health records are immutable: id + created_at only, no version."""
    assert_identity_fields(data, versioned=False)
    assert_no_version_fields(data)
    assert is_valid_uuid(data["horse_id"])
    assert data["event_type"] in [
        "LAMENESS", "COLIC", "REST_START", "REHAB_START",
        "VET_CLEARANCE", "FARRIER", "RETIREMENT",
    ]
    assert isinstance(data["observed_on"], str)
    assert data["resulting_horse_status"] in [
        "IN_SERVICE", "REST", "LAME", "REHAB", "REVIEW_HOLD", "RETIRED",
    ]


def assert_activity_slot(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["season_id"])
    assert data["activity_type"] in [
        "TRAIL_RIDE", "ARENA_LESSON", "FLY_FISHING", "HIKE", "KIDS_PROGRAM",
    ]
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert float(data["duration_hours"]) > 0
    assert data["terrain_grade"] in ["MEADOW", "ROLLING", "STEEP", "RIVER_CROSSING"]
    assert data["min_ability_rank"] in [
        "UNASSESSED", "BEGINNER", "NOVICE", "INTERMEDIATE", "ADVANCED",
    ]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert_cents(data["rider_surcharge_cents"], "rider_surcharge_cents")
    assert isinstance(data["mount_required"], bool)
    assert data["slot_status"] in [
        "DRAFT", "OPEN", "HOLD", "RUNNING", "COMPLETED", "CANCELLED",
    ]
    assert data["readiness_posture"] in [
        "FROZEN", "MOUNT_SHORT", "UNDERSTAFFED", "STAFFED_READY",
    ]
    for counter in (
        "confirmed_rider_count",
        "minor_rider_count",
        "mount_assigned_count",
        "assigned_guide_count",
        "required_guide_count",
        "seats_available",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
    assert data["seats_available"] == data["capacity"] - data["confirmed_rider_count"], (
        "seats_available must equal capacity minus confirmed_rider_count"
    )


def assert_guide_assignment(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["slot_id"])
    assert is_valid_uuid(data["staff_member_id"])
    assert data["guide_role"] in ["LEAD", "ASSISTANT", "WRANGLER"]
    assert data["assignment_status"] in ["SCHEDULED", "RELEASED", "COMPLETED"]
    assert float(data["credited_hours"]) >= 0


def assert_activity_reservation(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["slot_id"])
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["guest_id"])
    assert data["reservation_status"] in [
        "CONFIRMED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED",
    ]
    assert data["mount_status"] in [
        "NOT_REQUIRED", "PENDING", "ASSIGNED", "RELEASED", "COMPLETED",
    ]
    assert_cents(data["surcharge_cents"], "surcharge_cents")
    assert_cents(data["surcharge_reversed_cents"], "surcharge_reversed_cents")
    assert isinstance(data["mount_release_count"], int)


def assert_staff_member(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["season_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_type"] in ["WRANGLER", "GUIDE", "KITCHEN", "HOUSEKEEPING"]
    assert isinstance(data["certifications"], list)
    for cert in data["certifications"]:
        assert cert in [
            "WILDERNESS_FIRST_AID", "EQUINE_HANDLER", "FLY_CASTING", "CHILD_PROGRAM",
        ]
    assert isinstance(data["hired_on"], str)
    assert isinstance(data["contract_end_date"], str)
    assert data["employment_status"] in [
        "HIRED", "ACTIVE", "COMPLETED_SEASON", "DEPARTED_EARLY",
    ]
    assert isinstance(data["contract_days"], int) and data["contract_days"] >= 1
    assert isinstance(data["days_worked"], int) and data["days_worked"] >= 0
    assert_cents(data["retention_bonus_projected_cents"], "retention_bonus_projected_cents")
    assert_cents(data["retention_bonus_settled_cents"], "retention_bonus_settled_cents")


def assert_incident_report(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["guest_id"])
    assert data["severity"] in ["MINOR", "SERIOUS", "CRITICAL"]
    assert isinstance(data["equine_activity_statute_notice_given"], bool)
    assert isinstance(data["narrative"], str) and data["narrative"]
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["incident_status"] in [
        "FILED", "CLEARED", "REMEDIATION_REQUIRED", "CLOSED",
    ]
    assert isinstance(data["remediation_completed"], bool)


# --------------------------------------------------------------------------
# domain invariant checkers
# --------------------------------------------------------------------------

def assert_cancellation_split_is_conservative(booking: dict) -> None:
    """refunded_cents + forfeited_cents must always equal deposit_paid_cents."""
    total = booking["refunded_cents"] + booking["forfeited_cents"]
    assert total == booking["deposit_paid_cents"], (
        "refunded_cents + forfeited_cents must equal deposit_paid_cents, "
        f"got {booking['refunded_cents']} + {booking['forfeited_cents']} "
        f"= {total} against deposit_paid_cents {booking['deposit_paid_cents']}"
    )


def assert_folio_waterfall_consistent(booking: dict) -> None:
    """final_folio_total_cents must equal the sum of its waterfall components."""
    expected = (
        booking["realized_subtotal_cents"]
        + booking["activity_surcharge_total_cents"]
        - booking["activity_credit_applied_cents"]
        + booking["no_show_penalty_total_cents"]
        + booking["gratuity_cents"]
        + booking["folio_adjustment_total_cents"]
    )
    assert booking["final_folio_total_cents"] == expected, (
        "final_folio_total_cents must equal realized_subtotal_cents + "
        "activity_surcharge_total_cents - activity_credit_applied_cents + "
        "no_show_penalty_total_cents + gratuity_cents + folio_adjustment_total_cents; "
        f"expected {expected}, got {booking['final_folio_total_cents']}"
    )


def assert_folio_balance_consistent(booking: dict) -> None:
    expected = (
        booking["final_folio_total_cents"]
        - booking["deposit_paid_cents"]
        - booking["payments_applied_cents"]
    )
    assert booking["folio_balance_cents"] == expected, (
        "folio_balance_cents must equal final_folio_total_cents minus "
        f"deposit_paid_cents minus payments_applied_cents; expected {expected}, "
        f"got {booking['folio_balance_cents']}"
    )


def assert_readiness_posture(slot: dict, expected: str) -> None:
    assert slot["readiness_posture"] == expected, (
        f"readiness_posture expected {expected}, got {slot['readiness_posture']} "
        f"(mount_required={slot['mount_required']}, "
        f"mount_assigned_count={slot['mount_assigned_count']}, "
        f"confirmed_rider_count={slot['confirmed_rider_count']}, "
        f"assigned_guide_count={slot['assigned_guide_count']}, "
        f"required_guide_count={slot['required_guide_count']})"
    )


def assert_slot_counters(
    slot: dict,
    confirmed_rider_count: Optional[int] = None,
    minor_rider_count: Optional[int] = None,
    mount_assigned_count: Optional[int] = None,
    assigned_guide_count: Optional[int] = None,
    required_guide_count: Optional[int] = None,
    seats_available: Optional[int] = None,
) -> None:
    expectations = {
        "confirmed_rider_count": confirmed_rider_count,
        "minor_rider_count": minor_rider_count,
        "mount_assigned_count": mount_assigned_count,
        "assigned_guide_count": assigned_guide_count,
        "required_guide_count": required_guide_count,
        "seats_available": seats_available,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert slot[field] == expected, (
                f"{field} expected {expected}, got {slot[field]}"
            )


def assert_horse_load(
    horse: dict,
    scheduled_load_hours: Optional[float] = None,
    realized_load_hours: Optional[float] = None,
    consecutive_duty_days: Optional[int] = None,
) -> None:
    if scheduled_load_hours is not None:
        assert float(horse["scheduled_load_hours"]) == float(scheduled_load_hours), (
            f"scheduled_load_hours expected {scheduled_load_hours}, "
            f"got {horse['scheduled_load_hours']}"
        )
    if realized_load_hours is not None:
        assert float(horse["realized_load_hours"]) == float(realized_load_hours), (
            f"realized_load_hours expected {realized_load_hours}, "
            f"got {horse['realized_load_hours']}"
        )
    if consecutive_duty_days is not None:
        assert horse["consecutive_duty_days"] == consecutive_duty_days, (
            f"consecutive_duty_days expected {consecutive_duty_days}, "
            f"got {horse['consecutive_duty_days']}"
        )
