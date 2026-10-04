"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database,
using only endpoints declared in the product requirements.  Setup calls use the
lenient ``get_success_data`` validator so a broken prerequisite surfaces as a
clear "Setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID, get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_JUNE_1, JUNE_PERIOD, TEST_DEFAULTS, TIER_PAYLOADS,
)
from .factories import (
    create_class_session_payload, create_class_template_payload,
    create_client_payload, create_membership_payload,
    create_payroll_period_payload, create_staff_member_payload,
    create_studio_payload,
)
from .test_users import (
    TEST_USERS, make_client_headers, make_operator_headers,
    make_platform_admin_headers, make_staff_member_headers,
    make_studio_owner_headers,
)

OPERATOR = TEST_USERS["operator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


class SetupFailure(AssertionError):
    """Raised when a prerequisite call does not succeed."""


def _ok(response, what: str) -> dict:
    try:
        return get_success_data(response)
    except Exception as exc:  # noqa: BLE001 - surface the failing step clearly
        raise SetupFailure(f"Setup failed: {what} -> {exc}") from exc


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def set_clock(current_utc: str):
    return _ok(api_client.set_current_utc({"current_utc": current_utc}, OPERATOR),
               f"set clock to {current_utc}")


def ensure_tier(tier: str) -> dict:
    """Define (or replace) a platform tier row and return it."""
    return _ok(api_client.create_subscription_tier(TIER_PAYLOADS[tier], ADMIN),
               f"define {tier} tier")


def create_studio(tier: str = "GROWTH", **overrides) -> dict:
    """Sign up a studio. Returns the Studio row (which carries subscription_id)."""
    payload = create_studio_payload(tier=tier, **overrides)
    return _ok(api_client.create_studio(payload, ANONYMOUS), "sign up studio")


def studio_and_subscription(tier: str = "GROWTH", **overrides):
    """Return (studio, subscription, owner_headers) for a freshly signed-up studio."""
    studio = create_studio(tier=tier, **overrides)
    owner = make_studio_owner_headers(studio["id"])
    sub = _ok(api_client.get_subscription(studio["subscription_id"], ADMIN),
              "read subscription")
    return studio, sub, owner


def create_payroll_period(studio_id: str, owner, period_index: int = 1,
                          start_date: str = JUNE_PERIOD[0],
                          end_date: str = JUNE_PERIOD[1]) -> dict:
    payload = create_payroll_period_payload(
        studio_id=studio_id, period_index=period_index,
        start_date=start_date, end_date=end_date)
    return _ok(api_client.create_payroll_period(payload, owner), "create payroll period")


def create_template(studio_id: str, owner, **overrides) -> dict:
    payload = create_class_template_payload(studio_id=studio_id, **overrides)
    return _ok(api_client.create_class_template(payload, owner), "create class template")


def create_staff(studio_id: str, owner, template_id=None, **overrides) -> dict:
    payload = create_staff_member_payload(studio_id=studio_id, **overrides)
    if template_id is not None:
        payload.setdefault("primary_class_template_id", template_id)
        payload.setdefault("substitute_class_template_ids", [template_id])
    return _ok(api_client.create_staff_member(payload, owner), "create staff member")


def create_client(studio_id: str, **overrides) -> dict:
    payload = create_client_payload(home_studio_id=studio_id, **overrides)
    return _ok(api_client.create_client(payload, TEST_USERS["client_headers"]),
               "create client")


def current_subscription_version(studio_id: str) -> int:
    """The studio's subscription version as observed just before the guarded
    write.  PRD §2.8 requires ``expected_subscription_version`` to carry the
    value the caller *last observed*, so a setup helper that schedules a second
    session must re-read the row rather than reuse the value captured at
    signup."""
    studio = _ok(api_client.get_studio(studio_id, ADMIN), "read studio")
    sub = _ok(api_client.get_subscription(studio["subscription_id"], ADMIN),
              "read subscription")
    return sub["version"]


def create_session(studio_id: str, owner, template_id: str, staff_id: str,
                   subscription_version=None, **overrides) -> dict:
    # PRD §2.8: expected_subscription_version carries the value the caller last
    # observed.  Scheduling itself advances the subscription's version, so a
    # helper that schedules more than one session must re-observe the row before
    # each write rather than replay the version captured at signup.
    subscription_version = current_subscription_version(studio_id)
    payload = create_class_session_payload(
        studio_id=studio_id, class_template_id=template_id,
        instructor_staff_id=staff_id,
        expected_subscription_version=subscription_version, **overrides)
    return _ok(api_client.create_class_session(payload, owner), "create class session")


def book(client_id: str, session_id: str, **overrides) -> dict:
    payload = {"client_id": client_id, "class_session_id": session_id,
               "channel": "STUDIO", "payment_source": "DROP_IN"}
    payload.update(overrides)
    return _ok(api_client.create_booking(payload, make_client_headers(client_id)),
               "create booking")


def join_waitlist(client_id: str, session_id: str, position_mode: str = "QUEUED") -> dict:
    payload = {"class_session_id": session_id, "client_id": client_id,
               "position_mode": position_mode}
    return _ok(api_client.join_waitlist(payload, make_client_headers(client_id)),
               "join waitlist")


def sell_pack(studio_id: str, owner, client: dict, pack_size: int = 5,
              purchased_at: str = CLOCK_JUNE_1, expiry_scheme: str = "NONE",
              client_version=None) -> dict:
    payload = {
        "studio_id": studio_id, "client_id": client["id"], "pack_size": pack_size,
        "purchased_at": purchased_at, "expiry_scheme": expiry_scheme,
        "expected_client_version": client["version"] if client_version is None else client_version,
    }
    return _ok(api_client.create_class_pack(payload, owner), "sell class pack")


def create_membership(studio_id: str, owner, client_id: str, **overrides) -> dict:
    payload = create_membership_payload(studio_id=studio_id, client_id=client_id,
                                        **overrides)
    return _ok(api_client.create_membership(payload, owner), "create membership")


def inject_history(client_id: str, no_show_strike_count: int, late_cancel_count: int = 0):
    return _ok(api_client.inject_client_history(
        {"client_id": client_id, "no_show_strike_count": no_show_strike_count,
         "late_cancel_count": late_cancel_count}, OPERATOR), "inject client history")


def inject_entitlement(client_id: str, studio_id: str, kind: str, credits: int,
                       expires_at=None):
    payload = {"client_id": client_id, "studio_id": studio_id, "kind": kind,
               "credits": credits}
    if expires_at is not None:
        payload["expires_at"] = expires_at
    return _ok(api_client.inject_client_entitlement(payload, OPERATOR),
               "inject client entitlement")


# ---------------------------------------------------------------------------
# Tier 1 — state progression
# ---------------------------------------------------------------------------

def create_studio_and_activate(tier: str = "GROWTH", **overrides) -> dict:
    """Sign up a studio and settle its first renewal so the tenant is ACTIVE.

    Returns a dict with the studio, its subscription, the owner headers and the
    subscription version as of the last write.
    """
    ensure_tier(tier)
    set_clock(CLOCK_JUNE_1)
    studio = create_studio(tier=tier, **overrides)
    owner = make_studio_owner_headers(studio["id"])
    sub = _ok(api_client.get_subscription(studio["subscription_id"], ADMIN),
              "read subscription")
    renewed = _ok(api_client.advance_renewal(
        studio["subscription_id"],
        {"advance_clock": True, "advance_days": 30, "outcome": "SUCCEEDED",
         "expected_subscription_version": sub["version"]},
        owner), "activate subscription")
    return {"studio": studio, "subscription": renewed, "owner": owner,
            "subscription_version": renewed["version"]}


def drive_studio_to_suspended(studio: dict, owner) -> dict:
    """Suspend the studio's subscription and return the new subscription row."""
    sub = _ok(api_client.get_subscription(studio["subscription_id"], ADMIN),
              "read subscription")
    return _ok(api_client.suspend_subscription(
        studio["subscription_id"],
        {"reason": "non-payment", "expected_subscription_version": sub["version"]},
        owner), "suspend subscription")


def drive_studio_to_cancelled(studio: dict, owner) -> dict:
    sub = _ok(api_client.get_subscription(studio["subscription_id"], ADMIN),
              "read subscription")
    return _ok(api_client.cancel_subscription(
        studio["subscription_id"],
        {"expected_subscription_version": sub["version"]}, owner),
        "cancel subscription")


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------

def setup_studio_roster(tier: str = "GROWTH", activate: bool = False,
                        with_period: bool = True, with_template: bool = True,
                        with_instructor: bool = True, capacity: int = 2,
                        start_at: str = "2026-06-20T17:00:00Z",
                        room_code: str = "ROOM-A", **template_overrides):
    """The most common preamble: a studio, a payroll period, a class format, an
    instructor and one scheduled session.

    Returns a dict of every created row plus the owner headers.
    """
    ensure_tier(tier)
    set_clock(CLOCK_JUNE_1)
    studio = create_studio(tier=tier)
    owner = make_studio_owner_headers(studio["id"])
    sub = _ok(api_client.get_subscription(studio["subscription_id"], ADMIN),
              "read subscription")
    if activate:
        sub = _ok(api_client.advance_renewal(
            studio["subscription_id"],
            {"advance_clock": True, "advance_days": 30, "outcome": "SUCCEEDED",
             "expected_subscription_version": sub["version"]}, owner),
            "activate subscription")

    period = create_payroll_period(studio["id"], owner) if with_period else None
    template = create_template(studio["id"], owner, **template_overrides) \
        if with_template else None
    instructor = create_staff(studio["id"], owner,
                              template_id=template["id"] if template else None) \
        if with_instructor else None
    session = None
    if with_template and with_instructor:
        session = create_session(studio["id"], owner, template["id"],
                                 instructor["id"], sub["version"],
                                 capacity=capacity, start_at=start_at,
                                 room_code=room_code)
    return {"studio": studio, "owner": owner, "subscription": sub,
            "subscription_version": current_subscription_version(studio["id"]),
            "period": period,
            "template": template, "instructor": instructor, "session": session}


def setup_client_with_session(tier: str = "GROWTH", capacity: int = 2,
                              start_at: str = "2026-06-20T17:00:00Z",
                              room_code: str = "ROOM-A", book_seat: bool = False,
                              **template_overrides):
    """Roster setup plus one client, optionally booked onto the session."""
    ctx = setup_studio_roster(tier=tier, capacity=capacity, start_at=start_at,
                              room_code=room_code, **template_overrides)
    client = create_client(ctx["studio"]["id"])
    booking = None
    if book_seat:
        booking = book(client["id"], ctx["session"]["id"])
    ctx.update({"client": client, "booking": booking})
    return ctx


def setup_boundary_session(tier: str = "GROWTH", capacity: int = 1,
                           start_at: str = "2026-06-20T17:00:00Z",
                           room_code: str = "ROOM-A", **template_overrides):
    """Roster setup with a single-seat session — the waitlist boundary shape."""
    return setup_studio_roster(tier=tier, capacity=capacity, start_at=start_at,
                               room_code=room_code, **template_overrides)


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_and_complete_session(ctx: dict, attend: bool = False,
                                session_key: str = "session") -> dict:
    """Drive a session to COMPLETED, optionally checking the first booking in
    first so the ATTENDED leg (and its commission entry) fires."""
    session = ctx[session_key]
    owner = ctx["owner"]
    if attend:
        bookings = _ok(api_client.list_session_bookings(session["id"], owner),
                       "list session bookings")
        rows = bookings if isinstance(bookings, list) else bookings.get("data", [])
        for row in rows:
            if row["status"] == "RESERVED":
                _ok(api_client.check_in_booking(
                    row["id"], make_client_headers(row["client_id"])),
                    "check in booking")
    return _ok(api_client.complete_class_session(session["id"], ADMIN),
               "complete class session")


def setup_checkin_ready_session(clock_at: str = "2026-06-20T12:00:00Z",
                                tier: str = "GROWTH"):
    """A booked client and a session the check-in gate will consider."""
    ctx = setup_client_with_session(tier=tier, book_seat=True)
    set_clock(clock_at)
    return ctx


def setup_in_progress_session(clock_at: str = "2026-06-20T17:00:00Z",
                              tier: str = "GROWTH", capacity: int = 2,
                              **template_overrides):
    """A booked client and a session driven to IN_PROGRESS by the clock."""
    ctx = setup_studio_roster(tier=tier, capacity=capacity,
                              **template_overrides)
    client = create_client(ctx["studio"]["id"])
    booking = book(client["id"], ctx["session"]["id"])
    set_clock(clock_at)
    fresh = _ok(api_client.get_class_session(ctx["session"]["id"], ctx["owner"]),
                "read session")
    ctx.update({"client": client, "booking": booking, "session": fresh})
    return ctx


def setup_attended_session(tier: str = "GROWTH", capacity: int = 2,
                           commission_rate_bps: int = 0,
                           **template_overrides):
    """Session completed with one ATTENDED booking, so a commission entry exists."""
    ctx = setup_studio_roster(tier=tier, capacity=capacity,
                              **template_overrides)
    if commission_rate_bps:
        ctx["instructor"] = _ok(api_client.create_staff_member(
            create_staff_member_payload(
                studio_id=ctx["studio"]["id"], full_name=TEST_DEFAULTS["INSTRUCTOR_NAME"],
                staff_role="INSTRUCTOR",
                primary_class_template_id=ctx["template"]["id"],
                substitute_class_template_ids=[ctx["template"]["id"]],
                commission_rate_bps=commission_rate_bps), ctx["owner"]),
            "create rate-pinned instructor")
        ctx["session"] = create_session(
            ctx["studio"]["id"], ctx["owner"], ctx["template"]["id"],
            ctx["instructor"]["id"], ctx["subscription_version"],
            capacity=capacity, start_at="2026-06-20T17:00:00Z")
    client = create_client(ctx["studio"]["id"])
    booking = book(client["id"], ctx["session"]["id"])
    set_clock("2026-06-20T17:00:00Z")
    _ok(api_client.check_in_booking(booking["id"], make_client_headers(client["id"])),
        "check in booking")
    _ok(api_client.complete_class_session(ctx["session"]["id"], ADMIN),
        "complete session")
    ctx.update({"client": client, "booking": booking})
    return ctx


def setup_two_sessions_same_day(tier: str = "GROWTH"):
    """Two sessions on one day, the second starting 20 minutes after the first."""
    ctx = setup_studio_roster(tier=tier, capacity=2, room_code="ROOM-A",
                              start_at="2026-06-20T17:00:00Z")
    second = create_session(ctx["studio"]["id"], ctx["owner"],
                            ctx["template"]["id"], ctx["instructor"]["id"],
                            ctx["subscription_version"], capacity=2,
                            room_code="ROOM-B", start_at="2026-06-20T17:20:00Z")
    ctx["second_session"] = second
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_full_session_with_waitlists(strikes_a: int = 0, strikes_b: int = 0,
                                      mode_a: str = "QUEUED",
                                      mode_b: str = "QUEUED",
                                      hold_count: int = 2,
                                      tier: str = "GROWTH"):
    """A capacity-1 session occupied by a booking, with ``hold_count`` holds.

    Returns the context plus ``client_a``/``client_b`` hold rows so the offer
    ordering can be observed.  ``hold_count=1`` is the shape PRD §3.4's
    "if no ACTIVE hold remains" branch needs: with a second hold present the
    freed seat is legitimately offered onward instead of released.
    """
    ctx = setup_studio_roster(tier=tier, capacity=1,
                              start_at="2026-06-20T17:00:00Z")
    holder = create_client(ctx["studio"]["id"],
                           display_name=TEST_DEFAULTS["CLIENT_NAME"],
                           email=TEST_DEFAULTS["CLIENT_EMAIL"])
    client_a = create_client(ctx["studio"]["id"],
                             display_name=TEST_DEFAULTS["SECOND_CLIENT_NAME"],
                             email=TEST_DEFAULTS["SECOND_CLIENT_EMAIL"])
    client_b = None
    hold_b = None
    if hold_count > 1:
        client_b = create_client(ctx["studio"]["id"], display_name="Cleo Ruiz",
                                 email="cleo@example.com")
    if strikes_a:
        inject_history(client_a["id"], strikes_a)
    if strikes_b and client_b is not None:
        inject_history(client_b["id"], strikes_b)
    seat_booking = book(holder["id"], ctx["session"]["id"])
    hold_a = join_waitlist(client_a["id"], ctx["session"]["id"], mode_a)
    if client_b is not None:
        hold_b = join_waitlist(client_b["id"], ctx["session"]["id"], mode_b)
    ctx.update({"holder": holder, "seat_booking": seat_booking,
                "client_a": client_a, "client_b": client_b,
                "hold_a": hold_a, "hold_b": hold_b})
    return ctx


def setup_studio_near_promo_boundary(tier: str = "GROWTH"):
    """An off-peak session carrying a promotional allocation."""
    ctx = setup_studio_roster(tier=tier, capacity=2, start_at="2026-06-20T17:00:00Z")
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — finalisation / terminal state
# ---------------------------------------------------------------------------

def setup_portability_granted(tier: str = "GROWTH", release: bool = True):
    """A portability request filed by a client with a clear balance, optionally
    already released by the studio."""
    ensure_tier(tier)
    set_clock(CLOCK_JUNE_1)
    studio = create_studio(tier=tier)
    owner = make_studio_owner_headers(studio["id"])
    client = create_client(studio["id"], home_state_code="CA")
    request = _ok(api_client.create_portability_request(
        {"studio_id": studio["id"], "requesting_client_id": client["id"],
         "dispute_reason": "relocating"}, make_client_headers(client["id"])),
        "file portability request")
    released = None
    if release:
        released = _ok(api_client.resolve_portability_release(
            request["id"],
            {"include_booking_history": True, "include_financial_history": False},
            owner), "release portability request")
    return {"studio": studio, "owner": owner, "client": client,
            "request": released or request}


def setup_closed_payroll_period(tier: str = "GROWTH"):
    """Session with an ATTENDED booking, then the period locked and sealed."""
    ctx = setup_attended_session(tier=tier)
    period = _ok(api_client.get_payroll_period(ctx["period"]["id"], ctx["owner"]),
                 "read payroll period")
    locked = _ok(api_client.close_payroll_period(
        ctx["period"]["id"],
        {"expected_payroll_period_version": period["version"]}, ctx["owner"]),
        "close payroll period")
    ctx["period"] = locked
    return ctx


def nonexistent_id() -> str:
    """A syntactically valid but unallocated UUID."""
    return NON_EXISTENT_UUID