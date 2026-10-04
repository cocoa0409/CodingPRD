"""Entity assertions and domain invariant checkers.

Every entity in this system carries the full common-field set per the PRD's
common-resource-properties section: id (server-minted UUID), created_at and
updated_at (ISO 8601 UTC with three fractional digits), and version.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ActivityFlagStatus,
    ActivitySportType,
    ActivityStatus,
    AthleteStatus,
    BeaconStatus,
    ChallengeGoalType,
    ChallengeJoinMode,
    ChallengeStatus,
    ClubSportType,
    ClubStatus,
    EffortFlagStatus,
    EventStatus,
    ExclusionReason,
    FlagReason,
    FlagStatus,
    HeatmapSportType,
    JoinPolicy,
    MembershipRole,
    MembershipStatus,
    ParticipationStatus,
    PrivacyZoneStatus,
    RsvpStatus,
    SegmentSportType,
    SegmentStatus,
    SubscriptionPlan,
    SubscriptionStatus,
)


def assert_common_fields(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), f"version must be an int, got {data.get('version')!r}"


def _assert_enum_member(value: Any, enum_cls, field: str) -> None:
    valid = {e.value for e in enum_cls}
    assert value in valid, f"{field} must be one of {sorted(valid)}, got {value!r}"


def assert_athlete(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("display_name"), str) and 0 < len(data["display_name"]) <= 60
    assert -90 <= data["home_lat"] <= 90
    assert -180 <= data["home_lng"] <= 180
    assert data["tier"] in ("FREE", "SUMMIT")
    _assert_enum_member(data.get("status"), AthleteStatus, "status")
    assert isinstance(data.get("heatmap_opt_out"), bool)
    assert isinstance(data.get("safety_score"), int)
    assert 0 <= data["safety_score"] <= 100


def assert_subscription(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    _assert_enum_member(data.get("plan"), SubscriptionPlan, "plan")
    assert is_iso8601_timestamp(data.get("started_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    _assert_enum_member(data.get("status"), SubscriptionStatus, "status")


def assert_privacy_zone(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert -90 <= data["center_lat"] <= 90
    assert -180 <= data["center_lng"] <= 180
    assert isinstance(data.get("radius_m"), int)
    assert 200 <= data["radius_m"] <= 2000
    _assert_enum_member(data.get("status"), PrivacyZoneStatus, "status")


def assert_activity(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _assert_enum_member(data.get("sport_type"), ActivitySportType, "sport_type")
    assert is_iso8601_timestamp(data.get("started_at", ""))
    assert isinstance(data.get("duration_s"), int) and data["duration_s"] > 0
    assert data["distance_m"] > 0
    assert isinstance(data.get("track_points"), list) and len(data["track_points"]) >= 2
    _assert_enum_member(data.get("status"), ActivityStatus, "status")
    _assert_enum_member(data.get("flag_status"), ActivityFlagStatus, "flag_status")
    assert isinstance(data.get("auto_hidden"), bool)
    assert isinstance(data.get("obfuscated_track"), list)


def assert_segment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert 3 <= len(data.get("name", "")) <= 80
    _assert_enum_member(data.get("sport_type"), SegmentSportType, "sport_type")
    assert data["distance_m"] > 0
    assert isinstance(data.get("city"), str)
    assert isinstance(data.get("hazard_index"), int) and 0 <= data["hazard_index"] <= 10
    _assert_enum_member(data.get("status"), SegmentStatus, "status")
    assert isinstance(data.get("effort_count"), int) and data["effort_count"] >= 0


def assert_segment_effort(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("activity_id", ""))
    assert is_valid_uuid(data.get("segment_id", ""))
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert isinstance(data.get("elapsed_time_s"), int) and data["elapsed_time_s"] >= 1
    assert data["distance_m"] > 0
    assert data["elevation_gain_m"] >= 0
    assert isinstance(data.get("avg_speed_kmh"), (int, float))
    _assert_enum_member(data.get("flag_status"), EffortFlagStatus, "flag_status")
    reason = data.get("exclusion_reason")
    assert reason is None or reason in {e.value for e in ExclusionReason}
    assert isinstance(data.get("rank_snapshot"), int) and data["rank_snapshot"] >= 1


def assert_flag(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("effort_id", ""))
    assert is_valid_uuid(data.get("reporter_id", ""))
    _assert_enum_member(data.get("reason"), FlagReason, "reason")
    _assert_enum_member(data.get("status"), FlagStatus, "status")


def assert_club(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert 3 <= len(data.get("name", "")) <= 60
    _assert_enum_member(data.get("sport_type"), ClubSportType, "sport_type")
    _assert_enum_member(data.get("join_policy"), JoinPolicy, "join_policy")
    _assert_enum_member(data.get("status"), ClubStatus, "status")


def assert_club_membership(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("club_id", ""))
    assert is_valid_uuid(data.get("athlete_id", ""))
    _assert_enum_member(data.get("role"), MembershipRole, "role")
    _assert_enum_member(data.get("status"), MembershipStatus, "status")


def assert_challenge(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert 3 <= len(data.get("name", "")) <= 80
    _assert_enum_member(data.get("goal_type"), ChallengeGoalType, "goal_type")
    assert data["goal_target"] > 0
    assert isinstance(data.get("start_date"), str)
    assert isinstance(data.get("end_date"), str)
    assert data["end_date"] >= data["start_date"]
    _assert_enum_member(data.get("join_mode"), ChallengeJoinMode, "join_mode")
    _assert_enum_member(data.get("status"), ChallengeStatus, "status")


def assert_challenge_participation(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("challenge_id", ""))
    assert is_valid_uuid(data.get("athlete_id", ""))
    _assert_enum_member(data.get("status"), ParticipationStatus, "status")
    assert data["progress_value"] >= 0
    assert is_iso8601_timestamp(data.get("joined_at", ""))


def assert_virtual_event(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert 3 <= len(data.get("name", "")) <= 80
    assert is_valid_uuid(data.get("segment_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    assert isinstance(data.get("capacity"), int) and 1 <= data["capacity"] <= 500
    _assert_enum_member(data.get("status"), EventStatus, "status")
    assert isinstance(data.get("rsvp_count"), int) and data["rsvp_count"] >= 0


def assert_event_rsvp(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("athlete_id", ""))
    _assert_enum_member(data.get("status"), RsvpStatus, "status")


def assert_safety_contact(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("contact_email"), str) and "@" in data["contact_email"]
    assert 0 < len(data.get("label", "")) <= 40


def assert_beacon_session(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert is_iso8601_timestamp(data.get("started_at", ""))
    loc = data.get("last_location")
    assert loc is None or (isinstance(loc, dict) and "lat" in loc and "lng" in loc)
    _assert_enum_member(data.get("status"), BeaconStatus, "status")


def assert_heatmap_cell(data: Dict[str, Any]) -> None:
    assert isinstance(data.get("city"), str) and data["city"]
    _assert_enum_member(data.get("sport_type"), HeatmapSportType, "sport_type")
    assert isinstance(data.get("contribution_count"), int) and data["contribution_count"] >= 0


def assert_route_plan(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert 1 <= len(data.get("name", "")) <= 80
    assert isinstance(data.get("waypoints"), list) and 2 <= len(data["waypoints"]) <= 50
    assert data["distance_m"] > 0
    assert isinstance(data.get("week_start"), str)
    assert isinstance(data.get("estimated_load_score"), (int, float))


def assert_athlete_invariants(data: Dict[str, Any]) -> None:
    """Safety score stays clamped to [0, 100] after any flag adjudication."""
    assert 0 <= data["safety_score"] <= 100, "safety_score must remain within [0, 100]"


def assert_leaderboard_ranks(rows: List[Dict[str, Any]]) -> None:
    """Leaderboard order: elapsed_time_s ASC, ties broken by created_at ASC,
    with rank_snapshot equal to the one-based position."""
    prev = None
    for i, row in enumerate(rows):
        assert row["rank_snapshot"] == i + 1, (
            f"rank_snapshot must be the 1-based position: expected {i + 1}, got {row['rank_snapshot']}"
        )
        key = (row["elapsed_time_s"], row["created_at"])
        if prev is not None:
            assert key >= prev, "leaderboard must order by (elapsed_time_s, created_at) ascending"
        prev = key
