"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty
database (the harness restarts the server before every test) using only
PRD-declared endpoints. Identity threading: any call on behalf of an
entity-backed role uses make_*_headers(entity_id), never the shared
TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    create_circle_payload,
    create_fix_payload,
    create_member_payload,
    create_minor_member_payload,
    create_place_payload,
    false_alarm_payload,
    grant_consent_payload,
    report_crash_payload,
    verify_dispatch_payload,
)
from .test_users import TEST_USERS, make_admin_headers, make_member_headers, make_owner_headers


def set_clock(iso_utc: str):
    resp = api_client.set_clock({"current_utc": iso_utc}, TEST_USERS["system_headers"])
    get_success_data(resp)


def reset_clock():
    """Return the logical clock to the boot instant (2026-09-01T00:00:00Z)."""
    set_clock("2026-09-01T00:00:00Z")


def run_sweeps():
    resp = api_client.run_sweeps(TEST_USERS["system_headers"])
    return get_success_data(resp)


def create_circle(tier="PROTECT", name="TestFamily", billing_anchor_day=1):
    """Create a circle. Returns (circle, owner_headers). The owner is the
    auto-created OWNER member with consent GRANTED."""
    owner_email = f"{name.lower()}-owner@example.com"
    payload = create_circle_payload(
        name=name,
        subscription_tier=tier,
        billing_anchor_day=billing_anchor_day,
        owner_display_name=f"{name}Owner",
        owner_email=owner_email,
    )
    resp = api_client.create_circle(payload, TEST_USERS["owner_headers"])
    circle = get_success_data(resp, 201)
    owner_headers = make_owner_headers(circle["owner_member_id"])
    return circle, owner_headers


def invite_member(circle, owner_headers, display_name="Member",
                  birthdate="1990-01-01T00:00:00Z", email=None):
    """Invite a member (starts PENDING). Returns the member dict."""
    email = email or f"{display_name.lower()}@example.com"
    resp = api_client.invite_member(
        circle["id"],
        create_member_payload(display_name=display_name, birthdate=birthdate, email=email),
        owner_headers,
    )
    return get_success_data(resp, 201)


def grant_consent_as_owner(circle, owner_headers, member_id, scope="FULL"):
    resp = api_client.grant_consent(
        circle["id"], member_id, grant_consent_payload(scope=scope), owner_headers,
    )
    return get_success_data(resp)


def grant_consent_as_self(circle, member_id, scope="FULL", monetization_opt_in=False):
    resp = api_client.grant_consent(
        circle["id"],
        member_id,
        grant_consent_payload(scope=scope, monetization_opt_in=monetization_opt_in),
        make_member_headers(member_id),
    )
    return get_success_data(resp)


def invite_and_grant_member(circle, owner_headers, display_name="Member",
                            birthdate="1990-01-01T00:00:00Z", email=None):
    """Invite + self-grant consent. Returns the GRANTED member dict."""
    member = invite_member(circle, owner_headers, display_name, birthdate, email)
    grant_consent_as_self(circle, member["id"])
    resp = api_client.get_member(circle["id"], member["id"], make_member_headers(member["id"]))
    return get_success_data(resp)


def invite_and_grant_minor(circle, owner_headers, display_name="Minor",
                           birthdate="2012-01-01T00:00:00Z", email=None):
    """Invite a minor + owner-grant consent. Returns the GRANTED MINOR dict."""
    minor = invite_member(circle, owner_headers, display_name, birthdate, email)
    grant_consent_as_owner(circle, owner_headers, minor["id"])
    resp = api_client.get_member(circle["id"], minor["id"], owner_headers)
    return get_success_data(resp)


def promote_to_admin(circle, owner_headers, member_id):
    resp = api_client.promote_member(circle["id"], member_id, owner_headers)
    return get_success_data(resp)


def invite_grant_promote_admin(circle, owner_headers, display_name="Adm",
                               email=None):
    """Invite an adult, self-grant consent, promote to ADMIN.
    Returns (admin_member, admin_headers)."""
    admin = invite_and_grant_member(circle, owner_headers, display_name, email=email)
    promote_to_admin(circle, owner_headers, admin["id"])
    resp = api_client.get_member(circle["id"], admin["id"], owner_headers)
    admin = get_success_data(resp)
    return admin, make_admin_headers(admin["id"])


def post_fix(circle, member, headers, **fix_overrides):
    """Post a location fix as the given member. Returns the fix dict (2xx)
    or raises on non-2xx."""
    resp = api_client.post_fix(
        circle["id"], member["id"], create_fix_payload(**fix_overrides), headers,
    )
    return get_success_data(resp, 201)


def start_trip(circle, member, headers, recorded_at="2026-09-01T10:00:00Z",
               speed_mps=30.0, lat=37.7, lng=-122.4, battery_pct=90):
    """Post a DRIVING fix that opens a trip. Returns (fix, trip_id).

    The fix response carries the opened trip's id (per the PRD's trip
    continuity rule)."""
    fix = post_fix(
        circle, member, headers,
        recorded_at=recorded_at, lat=lat, lng=lng, speed_mps=speed_mps,
        battery_pct=battery_pct, motion_context="DRIVING",
    )
    # The trip id comes from reading the member's OPEN trip list.
    data, _meta = _list_open_trips(circle, member, headers)
    trip_id = data[0]["id"]
    return fix, trip_id


def _list_open_trips(circle, member, headers):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_trips(
        circle["id"], member["id"], headers, params={"trip_status": "OPEN"},
    )
    return validate_paginated(resp)


def close_trip(circle, member, headers, recorded_at):
    """Close the member's OPEN trip with a non-DRIVING fix."""
    return post_fix(
        circle, member, headers,
        recorded_at=recorded_at, speed_mps=0.0, motion_context="STILL",
    )


def report_crash_for_member(circle, member, headers, trip_id, delta_v=20.0):
    resp = api_client.report_crash(
        circle["id"], member["id"], report_crash_payload(trip_id, delta_v), headers,
    )
    return get_success_data(resp, 201)


def escalate_crash(crash_member_headers, circle, member, trip_id, delta_v=20.0,
                   crash_at="2026-09-01T10:00:00Z", sweep_at="2026-09-01T10:11:00Z"):
    """Report a crash and let its wellness deadline pass. Returns the
    ESCALATED crash dict (with dispatch_id populated)."""
    crash = report_crash_for_member(circle, member, crash_member_headers, trip_id, delta_v)
    set_clock(sweep_at)
    run_sweeps()
    resp = api_client.get_crash(crash["id"], crash_member_headers)
    return get_success_data(resp)


def get_circle_state(circle_id, headers):
    resp = api_client.get_circle(circle_id, headers)
    return get_success_data(resp)


def get_member_state(circle_id, member_id, headers):
    resp = api_client.get_member(circle_id, member_id, headers)
    return get_success_data(resp)
