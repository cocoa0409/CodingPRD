"""Bookings: creation, check-in, cancellation, restoration, the completion
attendance cascade, credit restoration and commission accrual."""

from core import (
    CHECKIN_OPEN_MINUTES,
    LATE_CANCEL_WINDOW_MINUTES,
    STRIKE_RESTORE_WINDOW_HOURS,
    STRIKE_REVOCATION_THRESHOLD,
    add_days,
    fail,
    now,
)
from commons import (
    mint,
    refresh_client,
    refresh_session_counters,
    refresh_staff_accrued,
    touch,
)
from store import (
    BENEFIT_NETWORKS,
    BOOKINGS,
    CLASS_PACKS,
    CLASS_SESSIONS,
    CLIENTS,
    COMMISSION_ENTRIES,
    MEMBERSHIPS,
    PAYROLL_PERIODS,
    STAFF_MEMBERS,
    STUDIOS,
    SUBSCRIPTIONS,
    PACK_ZERO_DISCOUNTS,
    next_creation_seq,
)

import calc
import lifecycle


PAYMENT_SOURCES = ("DROP_IN", "MEMBERSHIP", "CLASS_PACK", "BENEFIT_NETWORK")
NON_ADMISSIBLE_CLIENT_STATUS = ("PORTABILITY_HOLD", "PORTED", "ANONYMIZED")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def booking_or_404(booking_id):
    booking = BOOKINGS.get(booking_id)
    if booking is None:
        fail("ERR_BOOKING_NOT_FOUND")
    return booking


def client_or_404(client_id):
    client = CLIENTS.get(client_id)
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    return client


def client_admissible(client):
    if client.get("status") in NON_ADMISSIBLE_CLIENT_STATUS:
        fail("ERR_CLIENT_NOT_ADMISSIBLE")


def commission_bps_for_studio(studio):
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    tier_name = subscription.get("tier") if subscription else None
    from commons import tier_row

    row = tier_row(tier_name)
    return row.get("marketplace_commission_bps", 0) if row else 0


def studio_of_session(session):
    return STUDIOS.get(session.get("studio_id"))


def assert_studio_operating(studio):
    if studio.get("status") in ("SUSPENDED", "CANCELLED"):
        fail("ERR_STUDIO_NOT_OPERATING")
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    if subscription is not None and subscription.get("status") in (
        "SUSPENDED",
        "CANCELLED",
    ):
        fail("ERR_SUBSCRIPTION_INACTIVE")


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


def create_booking(body):
    """Studio-channel booking create (PRD §3.3)."""
    client = client_or_404(body.get("client_id"))
    session = lifecycle.session_or_404(body.get("class_session_id"))

    membership = None
    pack = None
    network = None
    if body.get("membership_id"):
        membership = MEMBERSHIPS.get(body["membership_id"])
        if membership is None:
            fail("ERR_MEMBERSHIP_NOT_FOUND")
    if body.get("class_pack_id"):
        pack = CLASS_PACKS.get(body["class_pack_id"])
        if pack is None:
            fail("ERR_CLASS_PACK_NOT_FOUND")

    payment_source = body.get("payment_source")
    channel = body.get("channel") or "STUDIO"
    if payment_source not in PAYMENT_SOURCES:
        fail("ERR_INVALID_STATE", "Unknown payment_source.", 409)
    if channel == "MARKETPLACE":
        fail("ERR_PAYMENT_SOURCE_NOT_PERMITTED")
    if channel != "STUDIO":
        fail("ERR_INVALID_STATE", "Unknown channel.", 409)

    # PRD §3.2: a studio closure re-derives the posture to CANCELLED, "which is
    # what blocks any further booking attempt on it with ERR_STUDIO_CAPACITY_EXCEEDED".
    if session.get("status") == "CANCELLED_BY_STUDIO":
        fail("ERR_STUDIO_CAPACITY_EXCEEDED")
    if session.get("status") not in ("SCHEDULED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", "The session is not open for booking.", 409)
    if session.get("status") == "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "No new booking may be created on an in-progress session.", 409)

    studio = studio_of_session(session)
    assert_studio_operating(studio)

    # PRD §3.3: a client in PORTABILITY_HOLD/PORTED/ANONYMIZED "may not take new
    # bookings or holds", so that refusal is charged to the client rather than
    # to a capacity posture that happens to be true as well (PRD §2.11).
    client_admissible(client)

    lifecycle.check_client_overlap(
        client["id"], session.get("start_at"), session.get("end_at"), session["id"]
    )

    # capacity / entitlement constraint band
    if session.get("fullness_posture") in ("FULL", "CANCELLED"):
        fail("ERR_STUDIO_CAPACITY_EXCEEDED")
    if payment_source == "MEMBERSHIP":
        if membership is None:
            fail("ERR_MEMBERSHIP_INACTIVE")
        if membership.get("status") != "ACTIVE":
            fail("ERR_MEMBERSHIP_INACTIVE")
    if payment_source == "CLASS_PACK":
        if pack is None:
            fail("ERR_NO_ACTIVE_PACK")
        if pack.get("status") != "ACTIVE" or pack.get("credits_remaining", 0) <= 0:
            fail("ERR_NO_ACTIVE_PACK")
    # referential band (PRD §2.11): the client-admissibility check fires here,
    # ahead of the benefit-network resolution below, and an unresolvable code is
    # reported as the referential ERR_NETWORK_NOT_ACTIVE rather than a 404.
    client_admissible(client)

    if payment_source == "BENEFIT_NETWORK":
        network = BENEFIT_NETWORKS.get(body.get("benefit_network_code"))
        if network is None:
            fail("ERR_NETWORK_NOT_ACTIVE")
        if network.get("status") is False:
            fail("ERR_NETWORK_NOT_ACTIVE")

    return _materialise_booking(
        client=client,
        session=session,
        channel="STUDIO",
        payment_source=payment_source,
        membership=membership,
        pack=pack,
        network=network,
        is_promotional_seat=False,
        promo_redeem=False,
    )


def _materialise_booking(
    client,
    session,
    channel,
    payment_source,
    membership=None,
    pack=None,
    network=None,
    is_promotional_seat=False,
    promo_redeem=False,
):
    studio = studio_of_session(session)
    commission_bps = commission_bps_for_studio(studio)

    provisional = {
        "payment_source": payment_source,
        "channel": channel,
    }
    if is_promotional_seat and promo_redeem:
        gross = calc.promo_price(
            session.get("list_price_cents", 0), session.get("promo_discount_bps", 0)
        )
    elif channel == "MARKETPLACE":
        gross = calc.effective_seat_price(session, "MARKETPLACE", commission_bps)
    else:
        gross = calc.booking_gross(provisional, session, commission_bps, attended=False)

    booking = mint(
        BOOKINGS,
        {
            "studio_id": studio["id"] if studio else session.get("studio_id"),
            "client_id": client["id"],
            "class_session_id": session["id"],
            "channel": channel,
            "payment_source": payment_source,
            "membership_id": membership["id"] if membership else None,
            "class_pack_id": pack["id"] if pack else None,
            "benefit_network_code": network["network_code"] if network else None,
            "booking_fee_cents": 0,
            "fee_status": "NONE",
            "commission_base_cents": gross,
            "benefit_claim_amount_cents": 0,
            "benefit_claim_status": "NOT_APPLICABLE",
            "is_promotional_seat": is_promotional_seat,
            "creation_seq": next_creation_seq(session.get("studio_id")),
            "reminders_sent": 0,
            "status": "RESERVED",
        },
    )

    if payment_source == "CLASS_PACK" and pack is not None:
        _consume_pack_credit(pack, booking)
    if payment_source == "MEMBERSHIP" and membership is not None:
        membership["_credits_remaining"] = max(
            0, membership.get("_credits_remaining", 0) - 1
        )
        touch(membership)

    session["seats_taken"] = session.get("seats_taken", 0) + 1
    touch(session)
    refresh_session_counters(session)
    refresh_client(client)
    return booking


def _consume_pack_credit(pack, booking):
    """The expired grace window grades the first post-expiry consumption at zero
    value; the remaining credits hold their pre-expiry count so the expiry sweep
    can void them."""
    pack["credits_remaining"] = max(0, pack.get("credits_remaining", 0) - 1)
    grace_until = pack.get("pending_expiry_grace_until")
    if grace_until is not None and now() >= pack.get("expires_at"):
        if pack.get("_grace_used", 0) == 0:
            pack["_grace_used"] = 1
            booking["zero_value_credit"] = True
    if pack.get("credits_remaining", 0) <= 0:
        pack["status"] = "DEPLETED"
    touch(pack)


def restore_booking_credit(booking):
    """pack_refund_restoration: the credit a booking consumed comes back."""
    if booking.get("payment_source") == "CLASS_PACK" and booking.get("class_pack_id"):
        pack = CLASS_PACKS.get(booking["class_pack_id"])
        if pack is not None:
            pack["credits_remaining"] = pack.get("credits_remaining", 0) + 1
            if pack.get("status") == "DEPLETED":
                pack["status"] = "ACTIVE"
            touch(pack)
    if booking.get("payment_source") == "MEMBERSHIP" and booking.get("membership_id"):
        membership = MEMBERSHIPS.get(booking["membership_id"])
        if membership is not None:
            membership["_credits_remaining"] = membership.get("_credits_remaining", 0) + 1
            touch(membership)


# ---------------------------------------------------------------------------
# Check-in
# ---------------------------------------------------------------------------


def check_in(booking):
    if booking.get("status") != "RESERVED":
        fail("ERR_BOOKING_NOT_RESERVED")
    session = lifecycle.session_or_404(booking.get("class_session_id"))
    if session.get("status") != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "Check-in is only admitted while the session is in progress.", 409)
    if now() < add_days(session.get("start_at"), 0) - __import__("datetime").timedelta(
        minutes=CHECKIN_OPEN_MINUTES
    ):
        fail("ERR_INVALID_STATE", "The check-in gate has not opened.", 409)
    if now() > session.get("end_at"):
        fail("ERR_INVALID_STATE", "The check-in gate has closed.", 409)
    booking["status"] = "CHECKED_IN"
    touch(booking)
    refresh_session_counters(session)
    return booking


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def cancel_booking(booking):
    if booking.get("status") != "RESERVED":
        fail("ERR_BOOKING_NOT_RESERVED")
    session = lifecycle.session_or_404(booking.get("class_session_id"))
    start_at = session.get("start_at")
    if now() > start_at:
        fail("ERR_CANCEL_WINDOW_CLOSED")

    client = CLIENTS.get(booking.get("client_id"))
    cutoff = start_at - __import__("datetime").timedelta(
        minutes=LATE_CANCEL_WINDOW_MINUTES
    )
    if now() <= cutoff:
        booking["status"] = "CANCELLED"
        booking["booking_fee_cents"] = 0
        booking["fee_status"] = "NONE"
    else:
        prior_late = client.get("late_cancel_count", 0) if client else 0
        fee = calc.cancellation_fee(session, booking, client or {}, prior_late)
        booking["status"] = "LATE_CANCELLED"
        booking["booking_fee_cents"] = fee
        booking["fee_status"] = "CHARGED" if fee > 0 else "NONE"
        if client is not None:
            client["late_cancel_count"] = prior_late + 1
            touch(client)
    restore_booking_credit(booking)
    touch(booking)
    session["seats_taken"] = max(
        0, session.get("seats_taken", 1) - 1
    )
    touch(session)
    refresh_session_counters(session)
    if client is not None:
        refresh_client(client)
    from waitlist import offer_if_capacity

    offer_if_capacity(session)
    return booking


# ---------------------------------------------------------------------------
# No-show restore
# ---------------------------------------------------------------------------


def restore_no_show(booking, reason=None):
    if booking.get("status") != "NO_SHOW":
        fail("ERR_BOOKING_NOT_RESERVED")
    session = lifecycle.session_or_404(booking.get("class_session_id"))
    if now() > session.get("end_at") + __import__("datetime").timedelta(
        hours=STRIKE_RESTORE_WINDOW_HOURS
    ):
        fail("ERR_RESTORE_WINDOW_CLOSED")
    client = CLIENTS.get(booking.get("client_id"))
    if client is not None and client.get("no_show_strike_count", 0) < 1:
        fail("ERR_RESTORE_WINDOW_CLOSED", "The client carries no strike to restore.")
    booking["status"] = "RESERVED"
    booking["fee_status"] = "WAIVED"
    touch(booking)
    if client is not None:
        client["no_show_strike_count"] = max(
            0, client.get("no_show_strike_count", 1) - 1
        )
        touch(client)
        refresh_client(client)
    refresh_session_counters(session)
    return booking


# ---------------------------------------------------------------------------
# Reverse a claimed waitlist seat
# ---------------------------------------------------------------------------


def reverse_claim(booking, reason=None):
    if booking.get("status") != "RESERVED":
        fail("ERR_BOOKING_NOT_RESERVED")
    from store import WAITLIST_ENTRIES

    client = CLIENTS.get(booking.get("client_id"))
    if client is not None and client.get("no_show_strike_count", 0) >= STRIKE_REVOCATION_THRESHOLD:
        fail("ERR_INVALID_STATE", "The client's strike count blocks revocation.", 409)
    session = lifecycle.session_or_404(booking.get("class_session_id"))
    hold = None
    for candidate in WAITLIST_ENTRIES.values():
        if candidate.get("promoted_booking_id") == booking["id"]:
            hold = candidate
            break
    if hold is None or hold.get("status") != "CLAIMED":
        fail("ERR_ENTRY_NOT_OFFERED")
    restore_booking_credit(booking)
    booking["status"] = "CANCELLED"
    booking["fee_status"] = "NONE"
    touch(booking)
    hold["status"] = "ACTIVE"
    hold["position_mode"] = "QUEUED"
    hold["raw_sequence_no"] = max_sequence(session) + 1
    hold["effective_sequence"] = hold["raw_sequence_no"]
    hold["promoted_booking_id"] = None
    touch(hold)
    session["seats_taken"] = max(0, session.get("seats_taken", 1) - 1)
    touch(session)
    refresh_session_counters(session)
    # PRD §3.4 enumerates the reverse-claim side effects and does not include an
    # onward offer: the reverted hold returns to ACTIVE, never straight to
    # OFFERED.
    return booking


def max_sequence(session):
    from store import WAITLIST_ENTRIES

    sequences = [
        w.get("raw_sequence_no", 0)
        for w in WAITLIST_ENTRIES.values()
        if w.get("class_session_id") == session["id"]
    ]
    return max(sequences) if sequences else 0


# ---------------------------------------------------------------------------
# Completion cascade
# ---------------------------------------------------------------------------


def complete_bookings_for_session(session):
    candidates = [
        b
        for b in BOOKINGS.values()
        if b.get("class_session_id") == session["id"]
        and b.get("status") in ("RESERVED", "CHECKED_IN")
    ]
    if not candidates:
        refresh_session_counters(session)
        return

    attended_order = sorted(
        [b for b in candidates if b.get("status") == "CHECKED_IN"],
        key=lambda b: (b.get("creation_seq", 0), str(b.get("created_at")), b["id"]),
    )

    for booking in candidates:
        if booking.get("status") != "RESERVED":
            continue
        client = CLIENTS.get(booking.get("client_id"))
        prior_strikes = client.get("no_show_strike_count", 0) if client else 0
        booking["status"] = "NO_SHOW"
        fee = calc.no_show_fee(
            prior_strikes,
            session.get("list_price_cents", 0),
            booking.get("payment_source"),
        )
        booking["booking_fee_cents"] = fee
        booking["fee_status"] = "CHARGED" if fee > 0 else "NONE"
        touch(booking)
        if client is not None:
            client["no_show_strike_count"] = prior_strikes + 1
            touch(client)
            refresh_client(client)

    for index, booking in enumerate(attended_order):
        booking["status"] = "ATTENDED"
        booking["commission_base_cents"] = calc.booking_gross(
            booking, session, commission_bps_for_studio(studio_of_session(session) or {}), True
        )
        touch(booking)
        if booking.get("payment_source") == "BENEFIT_NETWORK":
            _submit_benefit_claim(booking, session)
        if booking.get("channel") == "MARKETPLACE":
            studio = studio_of_session(session)
            commission_bps = commission_bps_for_studio(studio or {})
            commission = calc.per_booking_commission(
                booking["commission_base_cents"], commission_bps
            )
            booking["studio_gross_cents"] = max(
                0, booking["commission_base_cents"] - commission
            )
        accrue_commission(booking, session, first=(index == 0))

    refresh_session_counters(session)


def _submit_benefit_claim(booking, session):
    network = BENEFIT_NETWORKS.get(booking.get("benefit_network_code"))
    if network is None:
        return
    booking["benefit_claim_amount_cents"] = calc.benefit_claim_amount(
        network, session.get("list_price_cents", 0)
    )
    booking["benefit_claim_status"] = "SUBMITTED"


def accrue_commission(booking, session, first):
    """commission_accrual: one entry per attended booking."""
    studio = studio_of_session(session)
    if studio is None:
        return
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    tier = subscription.get("tier") if subscription else studio.get("subscription_tier")
    staff = STAFF_MEMBERS.get(session.get("instructor_staff_id"))
    if staff is None:
        return
    base = booking.get("commission_base_cents", 0)
    # PRD §3.6: a locked period blocks further accrual until it is reopened
    # ("returns every PAID entry ... and lifts the accrual block"), so a session
    # completing against a locked/closed period accrues no new entry.
    period = PAYROLL_PERIODS.get(session.get("payroll_period_id"))
    if period is not None and period.get("status") != "OPEN":
        return None
    if first:
        rate = calc.teaching_rate(staff, tier)
    else:
        rate = calc.deputy_rate(tier)
    commission = calc.commission_cents(
        base,
        rate,
        tier,
        bonus_eligible=(booking.get("channel") == "MARKETPLACE"),
        payroll_cap_mode=studio.get("payroll_cap_mode", "BONUS_OUTSIDE_CAP"),
    )
    entry = mint(
        COMMISSION_ENTRIES,
        {
            "studio_id": studio["id"],
            "staff_member_id": staff["id"],
            "payroll_period_id": session.get("payroll_period_id"),
            "booking_id": booking["id"],
            "booking_channel": booking.get("channel"),
            "base_amount_cents": base,
            "rate_bps": rate,
            "commission_cents": commission,
            "status": "ACCRUED",
            "reversal_reason": None,
        },
    )
    refresh_staff_accrued(staff)
    period = PAYROLL_PERIODS.get(session.get("payroll_period_id"))
    if period is not None:
        from commons import refresh_payroll_period

        refresh_payroll_period(period)
    return entry


def commission_entries_for_booking(booking_id):
    return [
        e for e in COMMISSION_ENTRIES.values() if e.get("booking_id") == booking_id
    ]


def waiting_holds_for_booking(booking_id):
    from store import WAITLIST_ENTRIES

    return [
        w for w in WAITLIST_ENTRIES.values() if w.get("promoted_booking_id") == booking_id
    ]