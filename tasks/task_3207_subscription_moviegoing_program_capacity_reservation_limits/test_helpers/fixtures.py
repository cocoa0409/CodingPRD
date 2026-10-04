"""Composite setup helpers for the Subscription Moviegoing test suite.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so the DB is
empty at test start). Setup calls use get_success_data() so failures surface
as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from .factories import (
    create_member_payload,
    create_plan_payload,
    create_theater_payload,
    create_auditorium_payload,
    create_showtime_payload,
    create_reservation_payload,
    create_concession_purchase_payload,
    create_settlement_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
SERVICES = TEST_USERS["member_services_headers"]
STAFF = TEST_USERS["theater_staff_headers"]
STUDIO = TEST_USERS["studio_rep_headers"]

DEFAULT_TIMEZONE = "America/Chicago"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_DEFAULT):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Plans / members / subscriptions
# ---------------------------------------------------------------------------

def create_published_plan(**overrides):
    """Create a SubscriptionPlan and publish it. Returns the plan dict."""
    plan = get_success_data(api_client.create_plan(create_plan_payload(**overrides), ADMIN))
    get_success_data(api_client.publish_plan(plan["id"], ADMIN))
    plan["status"] = "PUBLISHED"
    return plan


def create_active_member(**overrides):
    """Register + activate a member. Returns the member dict."""
    member = get_success_data(api_client.create_member(create_member_payload(**overrides), SERVICES))
    get_success_data(api_client.activate_member(member["id"], SERVICES))
    member["status"] = "ACTIVE"
    return member


def enroll_member(member_id: str, plan_id: str):
    """Enroll an ACTIVE member in a PUBLISHED plan (agent-assisted). Returns Subscription."""
    return get_success_data(
        api_client.enroll_subscription(member_id, {"plan_id": plan_id}, SERVICES))


def setup_member_with_subscription(plan_overrides=None, member_overrides=None):
    """ACTIVE member + ACTIVE subscription. Returns (member, subscription)."""
    plan = create_published_plan(**(plan_overrides or {}))
    member = create_active_member(**(member_overrides or {}))
    subscription = enroll_member(member["id"], plan["id"])
    return member, subscription


# ---------------------------------------------------------------------------
# Theater / auditorium / showtime
# ---------------------------------------------------------------------------

def create_theater_with_auditorium(seat_count=10, formats=("STANDARD",), **overrides):
    """OPERATING theater + one auditorium. Returns (theater, auditorium)."""
    theater = get_success_data(api_client.create_theater(create_theater_payload(**overrides), ADMIN))
    auditorium = get_success_data(api_client.create_auditorium(
        theater["id"],
        create_auditorium_payload(seat_count=seat_count, supported_formats=list(formats)),
        ADMIN,
    ))
    return theater, auditorium


def create_on_sale_showtime(auditorium_id: str, **overrides):
    """Create a showtime and open sales. Returns the ON_SALE showtime dict."""
    showtime = get_success_data(
        api_client.create_showtime(create_showtime_payload(auditorium_id, **overrides), ADMIN))
    showtime = get_success_data(api_client.open_showtime_sales(showtime["id"], ADMIN))
    return showtime


def setup_theater_with_on_sale_showtime(seat_count=10, formats=("STANDARD",),
                                        showtime_overrides=None):
    """(theater, auditorium, ON_SALE showtime)."""
    theater, auditorium = create_theater_with_auditorium(seat_count=seat_count, formats=formats)
    showtime = create_on_sale_showtime(auditorium["id"], **(showtime_overrides or {}))
    return theater, auditorium, showtime


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

def create_held_reservation(member: dict, subscription: dict, showtime: dict):
    """Create a HELD reservation as the member. Returns the reservation dict."""
    return get_success_data(api_client.create_reservation(
        create_reservation_payload(
            subscription["id"], showtime["id"], showtime["version"]),
        make_member_headers(member["id"]),
    ))


def create_confirmed_reservation(member: dict, subscription: dict, showtime: dict):
    """Create a HELD reservation and confirm it. Returns the reservation dict."""
    reservation = create_held_reservation(member, subscription, showtime)
    return get_success_data(api_client.confirm_reservation(
        reservation["id"], make_member_headers(member["id"])))


def current_showtime(showtime_id: str):
    """Re-read a showtime (fresh version for the next OCC-guarded write)."""
    return get_success_data(api_client.get_showtime(showtime_id, ADMIN))


def create_checked_in_reservation(member: dict, subscription: dict, showtime: dict,
                                  checkin_clock: str):
    """Confirm a reservation, advance the clock into the check-in window,
    and check in as TheaterStaff. Returns the CHECKED_IN reservation."""
    reservation = create_confirmed_reservation(member, subscription, showtime)
    set_clock(checkin_clock)
    return get_success_data(api_client.check_in_reservation(reservation["id"], STAFF))


def setup_checked_in_scenario(studio_code="WB", starts_at="2026-09-02T19:00:00Z",
                              checkin_clock="2026-09-02T19:05:00Z",
                              period_start="2026-09-02T00:00:00Z",
                              period_end="2026-09-03T00:00:00Z",
                              plan_overrides=None, showtime_overrides=None):
    """Full pipeline: plan, ACTIVE member + subscription, ON_SALE showtime,
    CHECKED_IN reservation, and a DRAFT settlement report for the period.
    Returns dict with keys: theater, auditorium, showtime, member,
    subscription, reservation, report."""
    set_clock()
    plan = create_published_plan(**(plan_overrides or {}))
    theater, auditorium = create_theater_with_auditorium()
    showtime_kwargs = {"studio_code": studio_code, "starts_at": starts_at}
    showtime_kwargs.update(showtime_overrides or {})
    showtime = create_on_sale_showtime(auditorium["id"], **showtime_kwargs)
    member = create_active_member()
    subscription = enroll_member(member["id"], plan["id"])
    reservation = create_checked_in_reservation(member, subscription, showtime, checkin_clock)
    report = get_success_data(api_client.create_settlement_report(
        theater["id"],
        create_settlement_report_payload(
            studio_code=studio_code, period_start=period_start, period_end=period_end),
        STAFF,
    ))
    return {
        "plan": plan,
        "theater": theater,
        "auditorium": auditorium,
        "showtime": showtime,
        "member": member,
        "subscription": subscription,
        "reservation": reservation,
        "report": report,
    }


def setup_no_show_scenario(plan_overrides=None, starts_at="2026-09-02T19:00:00Z",
                           sweep_clock="2026-09-03T12:00:00Z",
                           studio_code="WB"):
    """CONFIRMED reservation swept to NO_SHOW by the clock. Returns dict with
    theater, showtime, member, subscription, reservation."""
    set_clock()
    plan = create_published_plan(**(plan_overrides or {}))
    theater, auditorium = create_theater_with_auditorium()
    showtime = create_on_sale_showtime(
        auditorium["id"], studio_code=studio_code, starts_at=starts_at)
    member = create_active_member()
    subscription = enroll_member(member["id"], plan["id"])
    reservation = create_confirmed_reservation(member, subscription, showtime)
    set_clock(sweep_clock)
    reservation = get_success_data(
        api_client.get_reservation(reservation["id"], SERVICES))
    return {
        "plan": plan,
        "theater": theater,
        "auditorium": auditorium,
        "showtime": showtime,
        "member": member,
        "subscription": subscription,
        "reservation": reservation,
    }


# ---------------------------------------------------------------------------
# Concessions
# ---------------------------------------------------------------------------

def record_concession_purchase(member: dict, theater_id: str, pre_discount_cents: int):
    """Record a concession purchase as the member. Returns the purchase dict."""
    return get_success_data(api_client.create_concession_purchase(
        create_concession_purchase_payload(
            member["id"], theater_id, pre_discount_cents=pre_discount_cents),
        make_member_headers(member["id"]),
    ))


# ---------------------------------------------------------------------------
# No-show strike accumulation
# ---------------------------------------------------------------------------

def earn_no_show_strike(member: dict, subscription: dict, auditorium_id: str,
                        starts_at: str, sweep_clock: str, **showtime_overrides):
    """Create a showtime, confirm a reservation on it, never check in, and
    advance the clock past the no-show sweep. Returns the strike-bearing
    reservation dict (NO_SHOW)."""
    showtime = create_on_sale_showtime(auditorium_id, starts_at=starts_at,
                                       **showtime_overrides)
    reservation = create_confirmed_reservation(member, subscription, showtime)
    set_clock(sweep_clock)
    return get_success_data(api_client.get_reservation(reservation["id"], SERVICES))
