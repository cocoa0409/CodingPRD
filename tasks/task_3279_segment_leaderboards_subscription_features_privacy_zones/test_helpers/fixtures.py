"""Composite setup helpers.

The harness restarts the API server before every test, so every helper builds
its preconditions from scratch through the public API. Setup calls use
``get_success_data`` so a setup failure surfaces as a clear "Setup failed"
error rather than a confusing assertion failure deep in a test.

Header discipline: the Athlete role is entity-backed, so every ownership-gated
call uses ``make_athlete_headers(entity_id)`` for the athlete that owns the
resource — never a shared constant.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .factories import (
    create_activity_payload,
    create_athlete_payload,
    create_challenge_payload,
    create_club_payload,
    create_event_payload,
    create_privacy_zone_payload,
    create_route_plan_payload,
    create_safety_contact_payload,
    create_segment_payload,
    create_subscription_payload,
)
from .test_users import make_athlete_headers, make_moderator_headers, make_platform_admin_headers


# ── Tier 1: single-entity creation ─────────────────────────────────────────


def create_athlete(api: ApiClient, **overrides) -> Dict[str, Any]:
    """Register an athlete and return the created record."""
    resp = api.create_athlete(create_athlete_payload(**overrides), make_platform_admin_headers())
    data = get_success_data(resp)
    assert data, "Setup failed: create_athlete"
    return data


def create_subscription(api: ApiClient, athlete_id: str, **overrides) -> Dict[str, Any]:
    resp = api.create_subscription(athlete_id, create_subscription_payload(**overrides), make_athlete_headers(athlete_id))
    data = get_success_data(resp)
    assert data, "Setup failed: create_subscription"
    return data


def create_privacy_zone(api: ApiClient, athlete_id: str, **overrides) -> Dict[str, Any]:
    resp = api.create_privacy_zone(athlete_id, create_privacy_zone_payload(**overrides), make_athlete_headers(athlete_id))
    data = get_success_data(resp)
    assert data, "Setup failed: create_privacy_zone"
    return data


def upload_activity(api: ApiClient, athlete_id: str, **overrides) -> Dict[str, Any]:
    """Upload an activity for an athlete; returns the activity record.

    No assertion on the resulting status: tests control whether the upload
    completes or is reconciled as a duplicate via the payload they pass.
    """
    resp = api.upload_activity(athlete_id, create_activity_payload(**overrides), make_athlete_headers(athlete_id))
    data = get_success_data(resp)
    assert data, "Setup failed: upload_activity"
    return data


def create_segment(api: ApiClient, creator_id: str, **overrides) -> Dict[str, Any]:
    resp = api.create_segment(create_segment_payload(creator_id, **overrides), make_athlete_headers(creator_id))
    data = get_success_data(resp)
    assert data, "Setup failed: create_segment"
    return data


def create_active_segment(api: ApiClient, creator_id: str, **overrides) -> Dict[str, Any]:
    """Create a segment and activate it (DRAFT -> ACTIVE)."""
    segment = create_segment(api, creator_id, **overrides)
    resp = api.activate_segment(segment["id"], make_athlete_headers(creator_id))
    data = get_success_data(resp)
    assert data, "Setup failed: activate_segment"
    return data


def create_club(api: ApiClient, owner_id: str, **overrides) -> Dict[str, Any]:
    """Create a club; the founder automatically holds an ACTIVE ADMIN membership."""
    resp = api.create_club(create_club_payload(owner_id, **overrides), make_athlete_headers(owner_id))
    data = get_success_data(resp)
    assert data, "Setup failed: create_club"
    return data


def join_club(api: ApiClient, club_id: str, athlete_id: str) -> Dict[str, Any]:
    resp = api.join_club(club_id, {"athlete_id": athlete_id}, make_athlete_headers(athlete_id))
    data = get_success_data(resp)
    assert data, "Setup failed: join_club"
    return data


def create_challenge(api: ApiClient, club_id: str, admin_id: str, **overrides) -> Dict[str, Any]:
    resp = api.create_challenge(club_id, create_challenge_payload(**overrides), make_athlete_headers(admin_id))
    data = get_success_data(resp)
    assert data, "Setup failed: create_challenge"
    return data


def create_active_challenge(api: ApiClient, club_id: str, admin_id: str, **overrides) -> Dict[str, Any]:
    """Create a challenge and start it (DRAFT -> ACTIVE)."""
    challenge = create_challenge(api, club_id, admin_id, **overrides)
    resp = api.start_challenge(club_id, challenge["id"], make_athlete_headers(admin_id))
    data = get_success_data(resp)
    assert data, "Setup failed: start_challenge"
    return data


def join_challenge(api: ApiClient, challenge_id: str, athlete_id: str) -> Dict[str, Any]:
    resp = api.join_challenge(challenge_id, {"athlete_id": athlete_id}, make_athlete_headers(athlete_id))
    data = get_success_data(resp)
    assert data, "Setup failed: join_challenge"
    return data


def create_event(api: ApiClient, club_id: str, admin_id: str, segment_id: str, **overrides) -> Dict[str, Any]:
    resp = api.create_event(club_id, create_event_payload(segment_id, **overrides), make_athlete_headers(admin_id))
    data = get_success_data(resp)
    assert data, "Setup failed: create_event"
    return data


def create_rsvp(api: ApiClient, event_id: str, athlete_id: str) -> Dict[str, Any]:
    resp = api.create_rsvp(event_id, {"athlete_id": athlete_id}, make_athlete_headers(athlete_id))
    data = get_success_data(resp)
    assert data, "Setup failed: create_rsvp"
    return data


def create_safety_contact(api: ApiClient, athlete_id: str, **overrides) -> Dict[str, Any]:
    resp = api.create_safety_contact(athlete_id, create_safety_contact_payload(**overrides), make_athlete_headers(athlete_id))
    data = get_success_data(resp)
    assert data, "Setup failed: create_safety_contact"
    return data


def create_route_plan(api: ApiClient, athlete_id: str, **overrides) -> Dict[str, Any]:
    resp = api.create_route_plan(athlete_id, create_route_plan_payload(**overrides), make_athlete_headers(athlete_id))
    data = get_success_data(resp)
    assert data, "Setup failed: create_route_plan"
    return data


def set_clock(api: ApiClient, to_iso8601: str) -> None:
    resp = api.set_clock(to_iso8601, make_platform_admin_headers())
    data = get_success_data(resp)
    assert data, "Setup failed: set_clock"


# ── Tier 2: composite structures ───────────────────────────────────────────


def create_activity_with_effort(
    api: ApiClient,
    segment: Dict[str, Any],
    athlete_id: str,
    elapsed_time_s: int = 100,
    sport_type: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """Upload an activity whose track covers the segment's endpoints and whose
    effort_hints author a deterministic effort on that segment.

    Returns {"activity": ..., "effort": ...}.
    """
    sport = sport_type or segment["sport_type"]
    activity = upload_activity(
        api,
        athlete_id,
        sport_type=sport,
        duration_s=overrides.pop("duration_s", max(elapsed_time_s, 1)),
        distance_m=overrides.pop("distance_m", segment["distance_m"]),
        track_points=[
            {"lat": segment["start_lat"], "lng": segment["start_lng"], "t_offset_s": 0},
            {"lat": segment["end_lat"], "lng": segment["end_lng"], "t_offset_s": max(elapsed_time_s, 1)},
        ],
        start_lat=segment["start_lat"],
        start_lng=segment["start_lng"],
        end_lat=segment["end_lat"],
        end_lng=segment["end_lng"],
        effort_hints=[{"segment_id": segment["id"], "elapsed_time_s": elapsed_time_s, "elevation_gain_m": 0}],
        **overrides,
    )
    resp = api.list_efforts(make_athlete_headers(athlete_id), params={"activity_id": activity["id"]})
    efforts = get_success_data(resp)
    assert isinstance(efforts, list) and len(efforts) == 1, (
        f"Setup failed: expected exactly one effort for activity {activity['id']}, got {efforts!r}"
    )
    return {"activity": activity, "effort": efforts[0]}


def setup_club_with_member(api: ApiClient, join_policy: str = "OPEN") -> Dict[str, Any]:
    """Club owner + one joined member. Returns {"owner", "member", "club", "membership"}."""
    owner = create_athlete(api)
    member = create_athlete(api)
    club = create_club(api, owner["id"], join_policy=join_policy)
    membership = join_club(api, club["id"], member["id"])
    return {"owner": owner, "member": member, "club": club, "membership": membership}


def setup_active_challenge_scenario(api: ApiClient, **challenge_overrides) -> Dict[str, Any]:
    """OPEN club + ACTIVE member + ACTIVE challenge + JOINED participation.

    Returns {"owner", "member", "club", "challenge", "participation"}.
    """
    world = setup_club_with_member(api, join_policy="OPEN")
    challenge = create_active_challenge(api, world["club"]["id"], world["owner"]["id"], **challenge_overrides)
    participation = join_challenge(api, challenge["id"], world["member"]["id"])
    return {**world, "challenge": challenge, "participation": participation}


def setup_event_scenario(api: ApiClient, capacity: int = 5, scheduled_at: str = "2026-09-06T09:00:00Z") -> Dict[str, Any]:
    """Club with owner + ACTIVE member + ACTIVE segment + PUBLISHED event.

    Returns {"owner", "member", "club", "segment", "event"}.
    """
    world = setup_club_with_member(api, join_policy="OPEN")
    segment = create_active_segment(api, world["owner"]["id"], sport_type="RIDE")
    event = create_event(api, world["club"]["id"], world["owner"]["id"], segment["id"], capacity=capacity, scheduled_at=scheduled_at)
    return {**world, "segment": segment, "event": event}


# ── Tier 3: moderation shortcuts ───────────────────────────────────────────


def flag_effort(api: ApiClient, effort_id: str, reporter_id: str, reason: str = "IMPOSSIBLE_TIME") -> Dict[str, Any]:
    resp = api.create_flag(effort_id, {"reporter_id": reporter_id, "reason": reason}, make_athlete_headers(reporter_id))
    data = get_success_data(resp)
    assert data, "Setup failed: flag_effort"
    return data


def uphold_flag(api: ApiClient, flag_id: str) -> Dict[str, Any]:
    resp = api.uphold_flag(flag_id, make_moderator_headers())
    data = get_success_data(resp)
    assert data, "Setup failed: uphold_flag"
    return data


def reject_flag(api: ApiClient, flag_id: str) -> Dict[str, Any]:
    resp = api.reject_flag(flag_id, make_moderator_headers())
    data = get_success_data(resp)
    assert data, "Setup failed: reject_flag"
    return data


# ── Tier 4: accumulation / threshold targeting ─────────────────────────────


def upload_heatmap_ride(api: ApiClient, segment: Dict[str, Any], athlete_id: str, **overrides) -> Dict[str, Any]:
    """Upload one RIDE activity matching the given segment (contributes one to
    the segment's (city, RIDE) heat map cell)."""
    return upload_activity(
        api,
        athlete_id,
        sport_type="RIDE",
        duration_s=300,
        distance_m=segment["distance_m"],
        track_points=[
            {"lat": segment["start_lat"], "lng": segment["start_lng"], "t_offset_s": 0},
            {"lat": segment["end_lat"], "lng": segment["end_lng"], "t_offset_s": 300},
        ],
        start_lat=segment["start_lat"],
        start_lng=segment["start_lng"],
        end_lat=segment["end_lat"],
        end_lng=segment["end_lng"],
        **overrides,
    )


def setup_subscribed_athlete(api: ApiClient, **athlete_overrides) -> Dict[str, Any]:
    """Athlete with an ACTIVE subscription. Returns {"athlete", "subscription"}."""
    athlete = create_athlete(api, **athlete_overrides)
    subscription = create_subscription(api, athlete["id"])
    return {"athlete": athlete, "subscription": subscription}


def setup_beacon_ready_athlete(api: ApiClient, **athlete_overrides) -> Dict[str, Any]:
    """Athlete with an ACTIVE subscription and one safety contact — all beacon
    preconditions satisfied. Returns {"athlete", "subscription", "contact"}."""
    world = setup_subscribed_athlete(api, **athlete_overrides)
    contact = create_safety_contact(api, world["athlete"]["id"])
    return {**world, "contact": contact}


# ── Tier 5: erasure-ready world ────────────────────────────────────────────


def setup_erasable_athlete(api: ApiClient) -> Dict[str, Any]:
    """An athlete with a footprint to erase: one COMPLETED activity with an
    ELIGIBLE effort on a segment owned by a second athlete, and an ACTIVE
    membership in the second athlete's club.

    Returns {"athlete", "other", "segment", "activity", "effort", "club", "membership"}.
    """
    other = create_athlete(api)
    athlete = create_athlete(api)
    segment = create_active_segment(api, other["id"], sport_type="RUN")
    pair = create_activity_with_effort(api, segment, athlete["id"], elapsed_time_s=100)
    club = create_club(api, other["id"], sport_type="RUN", join_policy="OPEN")
    membership = join_club(api, club["id"], athlete["id"])
    return {
        "athlete": athlete,
        "other": other,
        "segment": segment,
        "activity": pair["activity"],
        "effort": pair["effort"],
        "club": club,
        "membership": membership,
    }
