"""Class templates, class sessions, payroll periods and the tenancy cascade."""

from datetime import timedelta

from core import (
    MIN_PAYROLL_PERIOD_DAYS,
    PAYROLL_REOPEN_WINDOW_DAYS,
    PROMO_DEFAULT_VALIDITY_DAYS,
    PROMO_MAX_DISCOUNT_BPS,
    PROMO_MIN_DISCOUNT_BPS,
    add_days,
    fail,
    now,
    parse_dt,
)
from commons import (
    mint,
    refresh_payroll_period,
    refresh_session_counters,
    tier_row,
    touch,
)
from store import (
    CLASS_SESSIONS,
    CLASS_TEMPLATES,
    PAYROLL_PERIODS,
    STAFF_MEMBERS,
    STUDIOS,
    SUBSCRIPTIONS,
)

import calc


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def session_or_404(session_id):
    session = CLASS_SESSIONS.get(session_id)
    if session is None:
        fail("ERR_CLASS_SESSION_NOT_FOUND")
    return session


def studio_or_404(studio_id):
    studio = STUDIOS.get(studio_id)
    if studio is None:
        fail("ERR_STUDIO_NOT_FOUND")
    return studio


def template_or_404(template_id):
    template = CLASS_TEMPLATES.get(template_id)
    if template is None:
        fail("ERR_INVALID_STATE", "The class template does not exist.", 404)
    return template


def payroll_period_or_404(period_id):
    period = PAYROLL_PERIODS.get(period_id)
    if period is None:
        fail("ERR_PAYROLL_PERIOD_NOT_FOUND")
    return period


def studio_for_session(session):
    return STUDIOS.get(session.get("studio_id"))


def subscription_for_studio(studio):
    if studio is None:
        return None
    return SUBSCRIPTIONS.get(studio.get("subscription_id"))


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def commission_bps_for(studio):
    subscription = subscription_for_studio(studio)
    tier_name = subscription.get("tier") if subscription else None
    row = tier_row(tier_name)
    return row.get("marketplace_commission_bps", 0) if row else 0


def repricing(session, studio):
    template = CLASS_TEMPLATES.get(session.get("class_template_id"))
    if template is None or studio is None:
        return
    session["list_price_cents"] = calc.session_list_price(
        template.get("base_price_cents", 0),
        template.get("is_off_peak", False),
        studio.get("subscription_tier"),
    )
    session["marketplace_price_cents"] = calc.marketplace_price(
        session["list_price_cents"], commission_bps_for(studio)
    )


def derive_promo_fields(session, fields, template):
    """Granting promotional seats on an off-peak format opens the promotion;
    with no allocation supplied the state stays NONE."""
    allocated = fields.get("promo_seats_allocated")
    if allocated in (None, ""):
        session["promo_seats_allocated"] = 0
        session["promo_seats_used"] = session.get("promo_seats_used", 0)
        session["promo_discount_bps"] = 0
        session["promo_valid_from"] = None
        session["promo_valid_to"] = None
        session["promo_offer_state"] = "NONE"
        return
    allocated = int(allocated)
    discount = int(fields.get("promo_discount_bps") or 0)
    session["promo_seats_allocated"] = allocated
    session["promo_seats_used"] = session.get("promo_seats_used", 0)
    session["promo_discount_bps"] = discount
    session["promo_valid_from"] = parse_dt(fields.get("promo_valid_from")) or now()
    valid_to = parse_dt(fields.get("promo_valid_to"))
    if valid_to is None:
        valid_to = add_days(now(), PROMO_DEFAULT_VALIDITY_DAYS)
    session["promo_valid_to"] = valid_to
    session["promo_offer_state"] = "ACTIVE" if template.get("is_off_peak") else "NONE"


# ---------------------------------------------------------------------------
# Payroll period coverage
# ---------------------------------------------------------------------------


def period_covering(studio_id, instant):
    matches = [
        p
        for p in PAYROLL_PERIODS.values()
        if p.get("studio_id") == studio_id
        and p.get("start_date") is not None
        and p.get("end_date") is not None
        and p["start_date"] <= instant <= p["end_date"]
    ]
    if not matches:
        fail("ERR_PAYROLL_PERIOD_GAP")
    matches.sort(key=lambda p: p.get("start_date"))
    return matches[0]


def check_period_disjoint(studio_id, start, end, exclude_id=None):
    if (end - start).days + 1 < MIN_PAYROLL_PERIOD_DAYS:
        fail("ERR_PAYROLL_PERIOD_OVERLAP")
    for period in PAYROLL_PERIODS.values():
        if period.get("studio_id") != studio_id:
            continue
        if exclude_id and period["id"] == exclude_id:
            continue
        if start <= period.get("end_date") and period.get("start_date") <= end:
            fail("ERR_PAYROLL_PERIOD_OVERLAP")


# ---------------------------------------------------------------------------
# Room interval rules
# ---------------------------------------------------------------------------


def check_buffer_then_room(
    studio_id, room_code, start_at, end_at, buffer_minutes, exclude_id=None
):
    """Guard band first, then the true half-open collision."""
    guard_band = []
    collisions = []
    for other in CLASS_SESSIONS.values():
        if other.get("id") == exclude_id:
            continue
        if other.get("studio_id") != studio_id:
            continue
        if other.get("room_code") != room_code:
            continue
        if other.get("status") == "CANCELLED_BY_STUDIO":
            continue
        other_template = CLASS_TEMPLATES.get(other.get("class_template_id"))
        if other_template is None:
            continue
        o_start = other.get("start_at")
        o_end = other.get("end_at")
        if o_start is None or o_end is None:
            continue
        if start_at < o_end and o_start < end_at:
            collisions.append(other)
            continue
        gap = max(buffer_minutes, other_template.get("buffer_minutes", 0))
        if gap <= 0:
            continue
        if end_at <= o_start:
            distance = (o_start - end_at).total_seconds() / 60.0
        else:
            distance = (start_at - o_end).total_seconds() / 60.0
        # PRD §3.2: the buffer binds sessions that are "close but not colliding".
        # Adjacency (distance 0) is decided by the half-open room rule, which
        # admits a session starting exactly when another ends; the changeover
        # band therefore applies only to a strictly positive sub-buffer gap.
        if 0 < distance < gap:
            guard_band.append(other)
    if guard_band:
        fail("ERR_BUFFER_INSUFFICIENT")
    if collisions:
        fail("ERR_ROOM_OVERLAP")


def check_client_overlap(client_id, start_at, end_at, exclude_session_id=None):
    from store import BOOKINGS, WAITLIST_ENTRIES

    for booking in BOOKINGS.values():
        if booking.get("client_id") != client_id:
            continue
        if booking.get("status") not in ("RESERVED", "CHECKED_IN"):
            continue
        other = CLASS_SESSIONS.get(booking.get("class_session_id"))
        if other is None or other["id"] == exclude_session_id:
            continue
        if other.get("status") == "CANCELLED_BY_STUDIO":
            continue
        if start_at < other.get("end_at") and other.get("start_at") < end_at:
            fail("ERR_CLIENT_SCHEDULE_OVERLAP")
    for hold in WAITLIST_ENTRIES.values():
        if hold.get("client_id") != client_id:
            continue
        if hold.get("status") not in ("ACTIVE", "STANDBY", "OFFERED"):
            continue
        other = CLASS_SESSIONS.get(hold.get("class_session_id"))
        if other is None or other["id"] == exclude_session_id:
            continue
        if other.get("status") == "CANCELLED_BY_STUDIO":
            continue
        if start_at < other.get("end_at") and other.get("start_at") < end_at:
            fail("ERR_CLIENT_SCHEDULE_OVERLAP")


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def assert_session_operating(studio):
    """Tenant posture gate for scheduling and roster operations (priority 5)."""
    if studio is None:
        return
    if studio.get("status") in ("SUSPENDED", "CANCELLED"):
        fail("ERR_STUDIO_NOT_OPERATING")
    subscription = subscription_for_studio(studio)
    if subscription is not None and subscription.get("status") in (
        "SUSPENDED",
        "CANCELLED",
    ):
        fail("ERR_SUBSCRIPTION_INACTIVE")


def create_session(body):
    studio = studio_or_404(body.get("studio_id"))
    assert_session_operating(studio)

    template = CLASS_TEMPLATES.get(body.get("class_template_id"))
    if template is None:
        fail("ERR_INVALID_STATE", "The class template does not exist.", 404)
    if template.get("studio_id") != studio["id"]:
        fail("ERR_INVALID_STATE", "The class template belongs to another studio.", 404)

    instructor = STAFF_MEMBERS.get(body.get("instructor_staff_id"))
    if instructor is None:
        fail("ERR_STAFF_MEMBER_NOT_FOUND")
    if instructor.get("status") == "SUBSTITUTE_ONLY":
        fail("ERR_INSTRUCTOR_NOT_ELIGIBLE")

    start_at = parse_dt(body.get("start_at"))
    end_at = start_at + timedelta(minutes=template.get("duration_minutes", 0))

    capacity = body.get("capacity")
    if capacity in (None, ""):
        capacity = template.get("default_capacity", 1)
    capacity = int(capacity)
    if capacity < 1:
        fail("ERR_INVALID_STATE", "capacity must be at least 1.", 409)

    check_buffer_then_room(
        studio["id"],
        body.get("room_code"),
        start_at,
        end_at,
        template.get("buffer_minutes", 0),
    )

    period = period_covering(studio["id"], start_at)

    session = mint(
        CLASS_SESSIONS,
        {
            "studio_id": studio["id"],
            "class_template_id": template["id"],
            "instructor_staff_id": instructor["id"],
            "room_code": body.get("room_code"),
            "start_at": start_at,
            "end_at": end_at,
            "capacity": capacity,
            "seats_taken": 0,
            "seats_held": 0,
            "fullness_posture": "OPEN",
            "list_price_cents": 0,
            "marketplace_price_cents": 0,
            "price_version": 1,
            "promo_seats_allocated": 0,
            "promo_seats_used": 0,
            "promo_discount_bps": 0,
            "promo_valid_from": None,
            "promo_valid_to": None,
            "promo_offer_state": "NONE",
            "promo_cascade_class_session_id": None,
            "payroll_period_id": period["id"],
            "status": "SCHEDULED",
        },
    )
    derive_promo_fields(session, body, template)
    repricing(session, studio)
    refresh_session_counters(session)
    subscription = subscription_for_studio(studio)
    if subscription is not None:
        touch(subscription)
    return session


def update_session(session, body):
    if session.get("status") != "SCHEDULED":
        fail("ERR_SESSION_NOT_SCHEDULED")
    studio = studio_or_404(session.get("studio_id"))
    template = CLASS_TEMPLATES.get(session.get("class_template_id"))
    template_buffer = template.get("buffer_minutes", 0) if template else 0
    price_affecting = False

    if "room_code" in body and body.get("room_code") != session.get("room_code"):
        check_buffer_then_room(
            session["studio_id"],
            body.get("room_code"),
            session["start_at"],
            session["end_at"],
            template_buffer,
            exclude_id=session["id"],
        )
        session["room_code"] = body.get("room_code")

    if body.get("instructor_staff_id"):
        instructor = STAFF_MEMBERS.get(body["instructor_staff_id"])
        if instructor is None:
            fail("ERR_STAFF_MEMBER_NOT_FOUND")
        if instructor.get("status") == "SUBSTITUTE_ONLY":
            fail("ERR_INSTRUCTOR_NOT_ELIGIBLE")
        session["instructor_staff_id"] = instructor["id"]

    if body.get("capacity") is not None:
        new_capacity = int(body["capacity"])
        occupied = session.get("seats_taken", 0) + session.get("seats_held", 0)
        if new_capacity < occupied:
            fail("ERR_STUDIO_CAPACITY_EXCEEDED")
        raised = new_capacity > session.get("capacity", 0)
        session["capacity"] = new_capacity
        if raised:
            offer_seats(session)

    promo_keys = (
        "promo_seats_allocated",
        "promo_discount_bps",
        "promo_valid_from",
        "promo_valid_to",
    )
    if any(key in body for key in promo_keys):
        merged = {
            "promo_seats_allocated": body.get(
                "promo_seats_allocated", session.get("promo_seats_allocated", 0)
            ),
            "promo_discount_bps": body.get(
                "promo_discount_bps", session.get("promo_discount_bps", 0)
            ),
            "promo_valid_from": body.get(
                "promo_valid_from", session.get("promo_valid_from")
            ),
            "promo_valid_to": body.get("promo_valid_to", session.get("promo_valid_to")),
        }
        discount = int(merged.get("promo_discount_bps") or 0)
        if discount and not (PROMO_MIN_DISCOUNT_BPS <= discount <= PROMO_MAX_DISCOUNT_BPS):
            fail("ERR_INVALID_STATE", "promo_discount_bps is out of range.", 409)
        if template is not None:
            derive_promo_fields(session, merged, template)
        price_affecting = True

    if price_affecting:
        session["price_version"] = session.get("price_version", 1) + 1
    repricing(session, studio)
    touch(session)
    refresh_session_counters(session)
    return session


def offer_seats(session):
    from waitlist import offer_if_capacity

    offer_if_capacity(session)


def cancel_session(session):
    """Studio-side cancellation: release bookings (never fee-charged), restore
    their credits, expire every hold, posture CANCELLED."""
    from store import BOOKINGS, WAITLIST_ENTRIES
    from bookings import restore_booking_credit

    session["status"] = "CANCELLED_BY_STUDIO"
    for booking in BOOKINGS.values():
        if booking.get("class_session_id") != session["id"]:
            continue
        if booking.get("status") in ("RESERVED", "CHECKED_IN"):
            restore_booking_credit(booking)
            booking["status"] = "CANCELLED"
            booking["fee_status"] = "NONE"
            booking["booking_fee_cents"] = 0
            # A booking that never attended carries no attended revenue.
            booking["commission_base_cents"] = 0
            touch(booking)
    for hold in WAITLIST_ENTRIES.values():
        if hold.get("class_session_id") != session["id"]:
            continue
        if hold.get("status") in ("ACTIVE", "STANDBY", "OFFERED"):
            hold["status"] = "EXPIRED"
            touch(hold)
    refresh_session_counters(session)
    session["fullness_posture"] = "CANCELLED"
    touch(session)
    return session


def complete_session(session):
    from core import set_clock
    from bookings import complete_bookings_for_session

    if session.get("end_at") is not None and session["end_at"] > now():
        set_clock(session["end_at"])
    if session.get("status") == "SCHEDULED":
        session["status"] = "IN_PROGRESS"
    complete_bookings_for_session(session)
    session["status"] = "COMPLETED"
    refresh_session_counters(session)
    touch(session)
    run_due_transitions()
    return session


def advance_sessions_to_clock():
    from bookings import complete_bookings_for_session

    for session in ordered_sessions():
        if session.get("status") == "SCHEDULED" and session.get("start_at") <= now():
            session["status"] = "IN_PROGRESS"
            touch(session)
        if session.get("status") == "IN_PROGRESS" and session.get("end_at") <= now():
            complete_bookings_for_session(session)
            session["status"] = "COMPLETED"
            refresh_session_counters(session)
            touch(session)


def ordered_sessions():
    return sorted(
        CLASS_SESSIONS.values(), key=lambda s: (s.get("created_at"), s.get("id"))
    )


def run_due_transitions():
    """Every system transition whose moment has passed, in the declared order."""
    from subscriptions import subscription_clock_transitions
    from memberships import membership_clock_transitions
    from portability import portability_clock_transitions

    subscription_clock_transitions()
    advance_sessions_to_clock()
    membership_clock_transitions()
    portability_clock_transitions()
    payroll_clock_transitions()


def payroll_clock_transitions():
    for period in PAYROLL_PERIODS.values():
        if period.get("status") == "LOCKED" and now() > add_days(
            period.get("end_date"), PAYROLL_REOPEN_WINDOW_DAYS
        ):
            period["status"] = "CLOSED"
            touch(period)
        refresh_payroll_period(period)


def close_studio(studio):
    """Tenancy-level cascade (PRD §3.2)."""
    from store import MEMBERSHIPS

    for session in ordered_sessions():
        if session.get("studio_id") != studio["id"]:
            continue
        if session.get("status") in ("SCHEDULED", "IN_PROGRESS"):
            cancel_session(session)
    for session in CLASS_SESSIONS.values():
        if session.get("studio_id") != studio["id"]:
            continue
        if session.get("promo_offer_state") in ("SCHEDULED", "ACTIVE"):
            session["promo_offer_state"] = "WITHDRAWN"
            touch(session)
    for membership in MEMBERSHIPS.values():
        if membership.get("studio_id") != studio["id"]:
            continue
        if membership.get("status") in ("ACTIVE", "FROZEN", "PAST_DUE", "LAPSED"):
            membership["status"] = "CANCELLED"
            touch(membership)
    studio["status"] = "CANCELLED"
    touch(studio)
    return studio