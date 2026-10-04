"""Composite setup helpers.

Every interesting rule requires the system to be in a specific state that
takes several API calls to reach; these helpers encapsulate those chains so
tests stay focused on assertions. Setup calls use the lenient
``get_success_data`` so a setup failure surfaces as a clear "Setup failed"
error instead of a confusing validation assertion.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    check_payload,
    event_payload,
    fantasy_contest_payload,
    fantasy_entry_payload,
    guest_payload,
    license_payload,
    order_line_payload,
    promo_rule_payload,
    screen_assignment_payload,
    shift_payload,
    staffing_plan_payload,
    trivia_session_payload,
    venue_payload,
    waitlist_payload,
    zone_payload,
)
from .test_users import (
    HOST_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    SCHEDULER_HEADERS,
    SERVER_HEADERS,
    VENUE_MANAGER_HEADERS,
)


# ── Logical clock ────────────────────────────────────────────────────────────


def advance_clock(to_iso8601: str) -> None:
    get_success_data(
        api_client.set_clock(to_iso8601, PLATFORM_ADMIN_HEADERS)
    )


# ── Single-resource creators ─────────────────────────────────────────────────


def create_venue(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_venue(venue_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def create_guest(venue_id: str, name: str = "Alex", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_guest(
            guest_payload(venue_id=venue_id, name=name, **overrides), HOST_HEADERS
        )
    )


def create_event(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_event(event_payload(**overrides), SCHEDULER_HEADERS)
    )


def create_zone(venue_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_zone(
            venue_id, zone_payload(**overrides), VENUE_MANAGER_HEADERS
        )
    )


def create_and_activate_license(
    venue_id: str,
    league: str = "NCAA",
    blackout_radius_miles: Optional[int] = 75,
    **overrides,
) -> Dict[str, Any]:
    license_data = get_success_data(
        api_client.create_license(
            venue_id,
            license_payload(
                league=league, blackout_radius_miles=blackout_radius_miles, **overrides
            ),
            VENUE_MANAGER_HEADERS,
        )
    )
    return get_success_data(
        api_client.activate_license(license_data["id"], VENUE_MANAGER_HEADERS)
    )


def create_screen_assignment(
    zone_id: str, event_id: str, screen_id: str = "S1", audio_enabled: bool = True
) -> Dict[str, Any]:
    # PRD §3.2: "Screen assignment ... verify that the league's license is
    # `ACTIVE` before proceeding".  Ensure the venue holds an ACTIVE license
    # for the event's league before assigning; the radius is pinned to 0
    # miles so the license satisfies the gate without imposing a blackout
    # radius on markets outside the event's own home market.
    zone = get_success_data(
        api_client.get_zone(zone_id, VENUE_MANAGER_HEADERS)
    )
    event = get_success_data(
        api_client.get_event(event_id, SCHEDULER_HEADERS)
    )
    league = event["league"]
    existing = get_success_data(
        api_client.list_venue_licenses(zone["venue_id"], VENUE_MANAGER_HEADERS)
    )
    if not any(
        lic["league"] == league and lic["status"] == "ACTIVE" for lic in existing
    ):
        radius = 75 if league == "NCAA" else 0
        create_and_activate_license(
            zone["venue_id"], league=league, blackout_radius_miles=radius
        )
    return get_success_data(
        api_client.create_screen_assignment(
            zone_id,
            screen_assignment_payload(
                event_id=event_id, screen_id=screen_id, audio_enabled=audio_enabled
            ),
            VENUE_MANAGER_HEADERS,
        )
    )


# ── Zone / event composites ──────────────────────────────────────────────────


def create_zone_with_assignment(
    capacity_seats: int = 200,
    expected_attendance: int = 5000,
    event_overrides: Optional[Dict[str, Any]] = None,
    venue_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Venue + zone (screen S1) + one BASE event + a screen assignment."""
    venue_kwargs = dict(venue_overrides or {})
    venue = create_venue(capacity_seats=capacity_seats, **venue_kwargs)
    zone = create_zone(venue["id"])
    event_kwargs = dict(event_overrides or {})
    event = create_event(expected_attendance=expected_attendance, **event_kwargs)
    assignment = create_screen_assignment(zone["id"], event["id"])
    return {
        "venue": venue,
        "zone": zone,
        "event": event,
        "assignment": assignment,
    }


# ── Waitlist composites ──────────────────────────────────────────────────────


def join_waitlist(venue_id: str, guest_id: str, party_size: int = 4) -> Dict[str, Any]:
    return get_success_data(
        api_client.join_waitlist(
            waitlist_payload(
                venue_id=venue_id, guest_id=guest_id, party_size=party_size
            ),
            HOST_HEADERS,
        )
    )


def call_waitlist_entry(entry_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.call_waitlist_entry(entry_id, HOST_HEADERS))


def create_guest_with_no_shows(venue_id: str, count: int, name: str = "Alex") -> Dict[str, Any]:
    """Create a guest and accumulate exactly `count` no-shows via burnt holds.

    Uses sequential 16-minute clock advances starting from the default logical
    clock start (2026-09-01T00:00:00Z), 20 minutes apart to stay clear of any
    boundary overlap.
    """
    guest = create_guest(venue_id, name=name)
    clock_time = "2026-09-01T00:00:00Z"
    for _ in range(count):
        clock_time = _add_minutes(clock_time, 20)
        entry = join_waitlist(venue_id, guest["id"])
        call_waitlist_entry(entry["id"])
        advance_clock(_add_minutes(clock_time, 16))
        get_success_data(api_client.cancel_waitlist_entry(entry["id"], HOST_HEADERS))
        clock_time = _add_minutes(clock_time, 16)
    return get_guest(guest["id"])


def get_guest(guest_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_guest(guest_id, HOST_HEADERS))


def _add_minutes(iso: str, minutes: int) -> str:
    from datetime import datetime, timedelta, timezone

    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (dt + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Check composites ─────────────────────────────────────────────────────────


def create_open_check(venue_id: str, guest_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_check(
            check_payload(venue_id=venue_id, guest_id=guest_id, **overrides),
            SERVER_HEADERS,
        )
    )


def add_order_line(check_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.add_order_line(check_id, order_line_payload(**overrides), SERVER_HEADERS)
    )


def create_open_check_with_lines(
    venue_id: str, guest_id: str, line_portion_counts: List[int]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Open check with one TRADITIONAL order line per portion count."""
    check = create_open_check(venue_id, guest_id)
    lines = [
        add_order_line(check["id"], portion_count=count)
        for count in line_portion_counts
    ]
    return check, lines


# ── Promo rules ──────────────────────────────────────────────────────────────


def create_promo_rule(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_promo_rule(promo_rule_payload(**overrides), VENUE_MANAGER_HEADERS)
    )


# ── Staffing composites ──────────────────────────────────────────────────────


def create_staffing_plan(venue_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_staffing_plan(
            venue_id, staffing_plan_payload(**overrides), VENUE_MANAGER_HEADERS
        )
    )


def add_shift(plan_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.add_shift(plan_id, shift_payload(**overrides), VENUE_MANAGER_HEADERS)
    )


def create_publishable_plan(venue_id: str, expected_covers: int = 3600) -> Dict[str, Any]:
    """DRAFT plan with one future FOH shift that yields positive requirements."""
    plan = create_staffing_plan(venue_id)
    add_shift(plan["id"], expected_covers=expected_covers)
    return get_success_data(
        api_client.get_staffing_plan(plan["id"], VENUE_MANAGER_HEADERS)
    )


# ── Trivia composites ────────────────────────────────────────────────────────


def create_trivia_entry_scenario(venue_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Venue + OPEN trivia session + guest + registered entry."""
    venue = create_venue(**(venue_overrides or {}))
    session = get_success_data(
        api_client.create_trivia_session(
            venue["id"], trivia_session_payload(), HOST_HEADERS
        )
    )
    guest = create_guest(venue["id"])
    entry = get_success_data(
        api_client.create_trivia_entry(
            session["id"], {"guest_id": guest["id"]}, HOST_HEADERS
        )
    )
    return {"venue": venue, "session": session, "guest": guest, "entry": entry}


# ── Fantasy composites ───────────────────────────────────────────────────────


def create_fantasy_contest(venue_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_fantasy_contest(
            venue_id, fantasy_contest_payload(**overrides), VENUE_MANAGER_HEADERS
        )
    )


def create_locked_contest_with_entries(
    venue_id: str,
    guest_ids: List[str],
    **contest_overrides,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create → open → register one entry per guest → lock.

    Returns the freshly locked contest (whose version is the one a settle call
    must cite) and the registered entries.
    """
    contest = create_fantasy_contest(venue_id, **contest_overrides)
    get_success_data(api_client.open_fantasy_contest(contest["id"], VENUE_MANAGER_HEADERS))
    entries = [
        get_success_data(
            api_client.create_fantasy_entry(
                contest["id"],
                fantasy_entry_payload(guest_id=guest_id),
                HOST_HEADERS,
            )
        )
        for guest_id in guest_ids
    ]
    locked = get_success_data(
        api_client.lock_fantasy_contest(contest["id"], VENUE_MANAGER_HEADERS)
    )
    return locked, entries
