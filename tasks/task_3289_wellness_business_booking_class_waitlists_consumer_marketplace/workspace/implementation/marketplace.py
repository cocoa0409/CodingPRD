"""The consumer marketplace: listing, marketplace pricing and platform
commission settlement."""

from core import MARKETPLACE_MIN_COMMISSION_CENTS, fail, now
from commons import require_gate, touch
from store import (
    BENEFIT_NETWORKS,
    BOOKINGS,
    CLASS_SESSIONS,
    CLASS_TEMPLATES,
    CLIENTS,
    STUDIOS,
    SUBSCRIPTIONS,
)

import calc
import lifecycle


def commission_bps_for(studio):
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    tier_name = subscription.get("tier") if subscription else None
    from commons import tier_row

    row = tier_row(tier_name)
    return row.get("marketplace_commission_bps", 0) if row else 0


def listing_visible(session):
    studio = STUDIOS.get(session.get("studio_id"))
    if studio is None or studio.get("status") not in ("ACTIVE", "TRIAL"):
        return False
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    tier_name = subscription.get("tier") if subscription else None
    from commons import tier_row

    row = tier_row(tier_name)
    if row is None or not row.get("marketplace_listing_enabled"):
        return False
    return True


def marketplace_view(session):
    studio = STUDIOS.get(session.get("studio_id"))
    commission_bps = commission_bps_for(studio) if studio else 0
    view = dict(session)
    view["fullness_posture"] = calc.fullness_posture(session, marketplace_basis=True)
    view["marketplace_price_cents"] = calc.marketplace_price(
        session.get("list_price_cents", 0), commission_bps
    )
    view["promo_price_cents"] = calc.promo_price(
        session.get("list_price_cents", 0), session.get("promo_discount_bps", 0)
    )
    return view


def browse(sessions):
    return [s for s in sessions if listing_visible(s)]


def single_class(session_id):
    session = CLASS_SESSIONS.get(session_id)
    if session is None:
        fail("ERR_CLASS_SESSION_NOT_FOUND")
    if not listing_visible(session):
        fail("ERR_FEATURE_NOT_IN_TIER", "This session is not listed on the marketplace.")
    return marketplace_view(session)


def create_marketplace_booking(body):
    from bookings import client_or_404, _materialise_booking

    client = client_or_404(body.get("client_id"))
    session = lifecycle.session_or_404(body.get("class_session_id"))
    studio = STUDIOS.get(session.get("studio_id"))
    if studio is None:
        fail("ERR_STUDIO_NOT_FOUND")
    require_gate(studio, "marketplace_listing")
    if studio.get("status") not in ("ACTIVE", "TRIAL"):
        fail("ERR_STUDIO_NOT_OPERATING")
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    if subscription is not None and subscription.get("status") in ("SUSPENDED", "CANCELLED"):
        fail("ERR_SUBSCRIPTION_INACTIVE")

    if session.get("status") == "CANCELLED_BY_STUDIO":
        fail("ERR_STUDIO_CAPACITY_EXCEEDED")
    if session.get("status") not in ("SCHEDULED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", "The session is not open for booking.", 409)
    if session.get("status") == "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "No new booking may be created on an in-progress session.", 409)

    lifecycle.check_client_overlap(
        client["id"], session.get("start_at"), session.get("end_at"), session["id"]
    )

    catalogue_view = marketplace_view(session)
    if catalogue_view.get("fullness_posture") in ("FULL", "CANCELLED"):
        fail("ERR_STUDIO_CAPACITY_EXCEEDED")

    promo_redeem = body.get("promo_redeem")
    promo_redeem = True if promo_redeem in (True, "true") else False
    if promo_redeem:
        if session.get("promo_offer_state") != "ACTIVE":
            fail("ERR_ALLOCATION_EXHAUSTED")
        if session.get("promo_seats_used", 0) >= session.get("promo_seats_allocated", 0):
            fail("ERR_ALLOCATION_EXHAUSTED")

    booking = _materialise_booking(
        client=client,
        session=session,
        channel="MARKETPLACE",
        payment_source="DROP_IN",
        is_promotional_seat=promo_redeem,
        promo_redeem=promo_redeem,
    )
    if promo_redeem:
        session["promo_seats_used"] = session.get("promo_seats_used", 0) + 1
        if session["promo_seats_used"] >= session.get("promo_seats_allocated", 0):
            session["promo_offer_state"] = "EXHAUSTED"
        touch(session)
    return booking


def settlement(studio_id):
    studio = STUDIOS.get(studio_id)
    if studio is None:
        fail("ERR_STUDIO_NOT_FOUND")
    commission_bps = commission_bps_for(studio)
    rows = [
        b
        for b in BOOKINGS.values()
        if b.get("studio_id") == studio_id
        and b.get("channel") == "MARKETPLACE"
        and b.get("status") not in ("CANCELLED", "LATE_CANCELLED", "WAITLISTED")
    ]
    rows.sort(key=lambda b: (b.get("created_at"), b.get("creation_seq", 0)))
    accumulated, per_row = calc.settlement_pair(rows, commission_bps)
    return {
        "marketplace_commission_cents": accumulated,
        "per_booking_commission_cents": per_row,
        "booking_count": len(rows),
    }


def recompute_marketplace_gross(booking, session):
    studio = STUDIOS.get(session.get("studio_id"))
    commission_bps = commission_bps_for(studio) if studio else 0
    if booking.get("is_promotional_seat"):
        gross = calc.promo_price(
            session.get("list_price_cents", 0), session.get("promo_discount_bps", 0)
        )
    else:
        gross = calc.marketplace_price(session.get("list_price_cents", 0), commission_bps)
    booking["commission_base_cents"] = gross
    return gross