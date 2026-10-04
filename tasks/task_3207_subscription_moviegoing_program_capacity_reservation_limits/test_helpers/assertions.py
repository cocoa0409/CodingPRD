"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only entity must not carry updated_at"
    assert "version" not in data, "append-only entity must not carry version"


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ["REGISTERED", "ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["loyalty_points_balance"], int)
    assert isinstance(data["no_show_strikes_active"], int)
    assert data["no_show_strikes_active"] >= 0


def assert_subscription_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["tier"] in ["BASIC", "PLUS", "PREMIER"]
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["weekly_reservation_quota"], int)
    assert isinstance(data["max_rollover_credits"], int)
    assert isinstance(data["premium_format_allowed"], bool)
    assert isinstance(data["max_future_reservations"], int)
    assert isinstance(data["loyalty_points_multiplier_pct"], int)
    assert isinstance(data["concession_discount_pct"], int)
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETIRED"]


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in ["ACTIVE", "PAUSED", "CANCELLED", "REJOIN_LOCKED"]
    assert isinstance(data["cycle_anchor_date"], str) and data["cycle_anchor_date"]
    assert isinstance(data["pause_count_in_cycle"], int)


def assert_credit_bucket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert isinstance(data["week_index"], int) and data["week_index"] >= 0
    assert isinstance(data["base_granted"], int)
    assert isinstance(data["rollover_in"], int)
    assert isinstance(data["credits_used"], int)
    assert data["posture"] in ["OPEN", "EXHAUSTED", "EXPIRED"]


def assert_theater(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["timezone"], str) and data["timezone"]
    assert data["status"] in ["OPERATING", "DARK"]


def assert_auditorium(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["theater_id"])
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["seat_count"], int) and data["seat_count"] > 0
    assert isinstance(data["supported_formats"], list)
    for fmt in data["supported_formats"]:
        assert fmt in ["STANDARD", "IMAX", "DOLBY", "THREE_D"]


def assert_showtime(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["auditorium_id"])
    assert isinstance(data["film_title"], str) and data["film_title"]
    assert isinstance(data["studio_code"], str) and data["studio_code"]
    assert data["format"] in ["STANDARD", "IMAX", "DOLBY", "THREE_D"]
    assert isinstance(data["runtime_minutes"], int)
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["premium_surcharge_cents"], int)
    assert isinstance(data["opening_weekend"], bool)
    assert isinstance(data["seats_held_subscription"], int)
    assert isinstance(data["seats_held_paid"], int)
    assert data["status"] in ["SCHEDULED", "ON_SALE", "LOCKED", "COMPLETED", "CANCELLED"]


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["subscription_id"])
    assert is_valid_uuid(data["showtime_id"])
    assert data["status"] in ["HELD", "CONFIRMED", "CANCELLED", "NO_SHOW",
                              "CHECKED_IN", "EXPIRED"]


def assert_no_show_strike(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["reservation_id"])
    assert data["status"] in ["ACTIVE", "EXPIRED", "REVERSED"]


def assert_loyalty_ledger_entry(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["kind"] in ["EARN_CONCESSION", "EARN_ADMISSION", "REDEEM",
                            "EXPIRE", "ADJUST"]
    assert isinstance(data["points"], int)


def assert_concession_purchase(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["theater_id"])
    assert isinstance(data["pre_discount_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["charged_cents"], int)
    assert isinstance(data["points_earned"], int)


def assert_settlement_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["theater_id"])
    assert isinstance(data["studio_code"], str) and data["studio_code"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACKNOWLEDGED", "DISPUTED"]
    assert isinstance(data["total_admissions"], int)
    assert isinstance(data["total_subscription_admissions"], int)
    assert isinstance(data["total_gross_cents"], int)


def assert_settlement_line(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["report_id"])
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["showtime_id"])
    assert data["line_kind"] in ["SUBSCRIPTION", "PAID"]
    assert isinstance(data["reported_value_cents"], int)


def assert_bucket_credit_invariant(bucket: dict):
    """credits_available == base_granted + rollover_in - credits_used, never negative."""
    expected = bucket["base_granted"] + bucket["rollover_in"] - bucket["credits_used"]
    assert bucket["credits_available"] == expected, (
        f"credits_available {bucket['credits_available']} != "
        f"{bucket['base_granted']} + {bucket['rollover_in']} - {bucket['credits_used']}"
    )
    assert bucket["credits_available"] >= 0, "credits_available must never be negative"


def assert_showtime_seat_invariant(showtime: dict, seat_count: int):
    """seats_held_subscription + seats_held_paid + seats_available == seat_count."""
    total = (showtime["seats_held_subscription"] + showtime["seats_held_paid"]
             + showtime["seats_available"])
    assert total == seat_count, (
        f"seat invariant violated: {showtime['seats_held_subscription']} + "
        f"{showtime['seats_held_paid']} + {showtime['seats_available']} != {seat_count}"
    )
