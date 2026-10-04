"""Per-entity shape assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CheckKind,
    CheckStatus,
    EventKind,
    EventStatus,
    FantasyContestStatus,
    League,
    LicenseStatus,
    OrderLineKind,
    OrderLineStatus,
    ShiftRole,
    StaffingPlanStatus,
    TriviaSessionStatus,
    WaitlistStatus,
    ZonePosture,
)


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def _assert_leaf_fields(data: dict, label: str):
    """Immutable-leaf records carry only id and created_at among common fields."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )


def assert_venue(data: dict):
    _assert_common_fields(data, "venue")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["market_zip"], str) and data["market_zip"]
    assert isinstance(data["capacity_seats"], int)
    assert isinstance(data["wing_cost_cents_per_lb"], int)
    assert isinstance(data["volatility_score"], (int, float))
    assert data["volatility_score"] >= 0


def assert_event(data: dict):
    _assert_common_fields(data, "event")
    assert data["kind"] in [k.value for k in EventKind]
    assert data["league"] in [l.value for l in League]
    assert data["status"] in [s.value for s in EventStatus]
    assert isinstance(data["expected_attendance"], int)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])


def assert_license(data: dict):
    _assert_common_fields(data, "license")
    assert data["league"] in [l.value for l in League]
    assert data["status"] in [s.value for s in LicenseStatus]
    assert isinstance(data["fee_per_head_cents"], int)


def assert_zone(data: dict):
    _assert_common_fields(data, "zone")
    assert isinstance(data["screen_ids"], list)
    assert data["posture"] in [p.value for p in ZonePosture]
    if data.get("primary_event_id") is not None:
        assert is_valid_uuid(data["primary_event_id"])


def assert_screen_assignment(data: dict):
    _assert_leaf_fields(data, "screen_assignment")
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["event_id"])
    assert isinstance(data["screen_id"], str) and data["screen_id"]
    assert isinstance(data["audio_enabled"], bool)


def assert_guest(data: dict):
    _assert_common_fields(data, "guest")
    assert isinstance(data["no_show_count"], int)
    assert data["no_show_count"] >= 0


def assert_waitlist_entry(data: dict):
    _assert_common_fields(data, "waitlist_entry")
    assert data["status"] in [s.value for s in WaitlistStatus]
    assert isinstance(data["party_size"], int)
    assert data["party_size"] > 0


def assert_check(data: dict):
    _assert_common_fields(data, "check")
    assert data["kind"] in [k.value for k in CheckKind]
    assert data["status"] in [s.value for s in CheckStatus]
    for field in ("subtotal_cents", "tax_cents", "total_cents"):
        assert isinstance(data[field], int), f"check.{field} must be integer cents"
        assert data[field] >= 0


def assert_order_line(data: dict):
    _assert_common_fields(data, "order_line")
    assert data["kind"] in [k.value for k in OrderLineKind]
    assert data["status"] in [s.value for s in OrderLineStatus]
    assert isinstance(data["portion_count"], int) and data["portion_count"] > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_promo_rule(data: dict):
    _assert_common_fields(data, "promo_rule")
    assert data["day_of_week"] in range(7)
    assert data["wing_kind"] in [k.value for k in OrderLineKind]
    assert data["promo_price_cents_per_10"] > 0
    assert data["portion_size"] == 10


def assert_staffing_plan(data: dict):
    _assert_common_fields(data, "staffing_plan")
    assert data["status"] in [s.value for s in StaffingPlanStatus]
    assert isinstance(data["foh_required"], int) and data["foh_required"] >= 0
    assert isinstance(data["boh_required"], int) and data["boh_required"] >= 0


def assert_shift(data: dict):
    _assert_leaf_fields(data, "shift")
    assert data["role"] in [r.value for r in ShiftRole]
    assert isinstance(data["headcount"], int)
    assert isinstance(data["expected_covers"], int)
    assert is_iso8601_timestamp(data["start_time"])
    assert is_iso8601_timestamp(data["end_time"])


def assert_trivia_session(data: dict):
    _assert_common_fields(data, "trivia_session")
    assert data["status"] in [s.value for s in TriviaSessionStatus]


def assert_trivia_entry(data: dict):
    _assert_leaf_fields(data, "trivia_entry")
    for field in ("points", "correct_count", "consecutive_correct"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_fantasy_contest(data: dict):
    _assert_common_fields(data, "fantasy_contest")
    assert data["status"] in [s.value for s in FantasyContestStatus]
    assert isinstance(data["entry_fee_cents"], int)
    assert isinstance(data["prize_structure"], list) and data["prize_structure"]


def assert_fantasy_entry(data: dict):
    _assert_leaf_fields(data, "fantasy_entry")
    assert is_valid_uuid(data["contest_id"])
    assert is_valid_uuid(data["guest_id"])
    assert isinstance(data["prize_cents"], int)


def assert_ppv_event(data: dict):
    _assert_common_fields(data, "ppv_event")
    assert is_valid_uuid(data["event_id"])
    assert isinstance(data["commercial_fee_cents"], int)
    assert isinstance(data["cover_charge_cents"], int)


def assert_check_invariants(data: dict):
    """Check arithmetic invariants that hold at any moment."""
    if data["status"] == "SETTLED":
        assert data["total_cents"] >= data["subtotal_cents"], (
            "settled total must be at least the subtotal (tax and cover are non-negative)"
        )
    if data["status"] == "VOIDED":
        assert data["subtotal_cents"] == 0, "voiding zeroes subtotal_cents"
        assert data["tax_cents"] == 0, "voiding zeroes tax_cents"
        assert data["total_cents"] == 0, "voiding zeroes total_cents"
