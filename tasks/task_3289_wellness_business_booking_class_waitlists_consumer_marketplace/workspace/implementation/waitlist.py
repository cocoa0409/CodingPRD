"""Waitlist holds, standby positions, offer ordering and the re-offer cascade."""

from datetime import timedelta

from core import (
    OFFER_WINDOW_MINUTES,
    STANDBY_CONFIRM_WINDOW_MINUTES,
    STRIKE_OFFER_BLOCK_THRESHOLD,
    fail,
    now,
)
from commons import mint, refresh_session_counters, require_gate, touch
from store import (
    CLASS_SESSIONS,
    CLIENTS,
    STAFF_MEMBERS,
    STUDIOS,
    WAITLIST_ENTRIES,
)

import calc


TWO_ONE = timedelta(minutes=OFFER_WINDOW_MINUTES)

NON_ADMISSIBLE = ("PORTABILITY_HOLD", "PORTED", "ANONYMIZED")


def entry_or_404(entry_id):
    entry = WAITLIST_ENTRIES.get(entry_id)
    if entry is None:
        fail("ERR_WAITLIST_ENTRY_NOT_FOUND")
    return entry


def max_sequence(session):
    sequences = [
        w.get("raw_sequence_no", 0)
        for w in WAITLIST_ENTRIES.values()
        if w.get("class_session_id") == session["id"]
    ]
    return max(sequences) if sequences else 0


def effective_sequence(raw, position_mode):
    return min(raw, 0) if position_mode == "STANDBY_ANY" else raw


def rank_key(entry):
    """ascending (effective_sequence, created_at, joined_at); the UUID is never
    a tie-break."""
    return (
        entry.get("effective_sequence", 0),
        entry.get("created_at"),
        entry.get("joined_at"),
    )


def candidate_pool(session):
    pool = []
    for entry in WAITLIST_ENTRIES.values():
        if entry.get("class_session_id") != session["id"]:
            continue
        if entry.get("status") not in ("ACTIVE", "STANDBY"):
            continue
        if entry.get("joined_at") is not None and entry["joined_at"] > now():
            continue
        client = CLIENTS.get(entry.get("client_id"))
        if client is None:
            continue
        if client.get("status") in NON_ADMISSIBLE:
            continue
        if client.get("no_show_strike_count", 0) >= STRIKE_OFFER_BLOCK_THRESHOLD:
            continue
        if session.get("status") not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        pool.append(entry)
    pool.sort(key=rank_key)
    return pool


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------


def create_entry(session, client, position_mode):
    studio = STUDIOS.get(session.get("studio_id"))
    if studio is not None:
        require_gate(studio, "waitlist_auto_promotion")
    if position_mode not in ("QUEUED", "STANDBY_ANY"):
        fail("ERR_INVALID_STATE", "Unknown position_mode.", 409)
    if client.get("status") in NON_ADMISSIBLE:
        fail("ERR_CLIENT_NOT_ADMISSIBLE")

    from lifecycle import check_client_overlap

    check_client_overlap(
        client["id"], session.get("start_at"), session.get("end_at"), session["id"]
    )

    raw = max_sequence(session) + 1
    status = "ACTIVE" if position_mode == "QUEUED" else "STANDBY"
    entry = mint(
        WAITLIST_ENTRIES,
        {
            "studio_id": session.get("studio_id"),
            "class_session_id": session["id"],
            "client_id": client["id"],
            "joined_at": now(),
            "offer_expires_at": None,
            "status": status,
            "position_mode": position_mode,
            "raw_sequence_no": raw,
            "effective_sequence": effective_sequence(raw, position_mode),
            "promoted_booking_id": None,
        },
    )
    # a hold joined while the session is not yet full reserves no seat
    refresh_session_counters(session)
    return entry


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------


def occupied(session):
    return session.get("seats_taken", 0) + session.get("seats_held", 0)


def offer_if_capacity(session):
    """Offer free seats to the ranking order, one at a time."""
    offered = []
    while session.get("status") in ("SCHEDULED", "IN_PROGRESS"):
        if occupied(session) >= session.get("capacity", 0):
            break
        pool = candidate_pool(session)
        if not pool:
            break
        entry = pool[0]
        entry["status"] = "OFFERED"
        entry["offer_expires_at"] = now() + TWO_ONE
        touch(entry)
        session["seats_held"] = session.get("seats_held", 0) + 1
        offered.append(entry)
    if offered:
        touch(session)
        refresh_session_counters(session)
    return offered


def offer_onward(session):
    """The seat freed by an expired/cancelled offer is offered to the next hold
    (cascade depth 2), or the hold decrements when nobody remains."""
    session["seats_held"] = max(0, session.get("seats_held", 0) - 1)
    pool = candidate_pool(session)
    if pool and occupied(session) < session.get("capacity", 0):
        entry = pool[0]
        entry["status"] = "OFFERED"
        entry["offer_expires_at"] = now() + TWO_ONE
        touch(entry)
        session["seats_held"] = session.get("seats_held", 0) + 1
    touch(session)
    refresh_session_counters(session)


def expire_entry(entry):
    session = CLASS_SESSIONS.get(entry.get("class_session_id"))
    entry["status"] = "EXPIRED"
    touch(entry)
    if session is not None and entry.get("status") == "EXPIRED":
        offer_onward(session)


def sweep_lapsed_offers(studio_id=None):
    """Expire every offer whose window has passed and offer each freed seat
    onward with a fresh window."""
    expired = []
    offered = []
    for entry in list(WAITLIST_ENTRIES.values()):
        if entry.get("status") != "OFFERED":
            continue
        if studio_id is not None and entry.get("studio_id") != studio_id:
            continue
        expires = entry.get("offer_expires_at")
        if expires is None or not (expires < now()):
            continue
        session = CLASS_SESSIONS.get(entry.get("class_session_id"))
        entry["status"] = "EXPIRED"
        touch(entry)
        expired.append(entry)
        if session is not None:
            session["seats_held"] = max(0, session.get("seats_held", 0) - 1)
            pool = candidate_pool(session)
            if pool and occupied(session) < session.get("capacity", 0):
                nxt = pool[0]
                nxt["status"] = "OFFERED"
                nxt["offer_expires_at"] = now() + TWO_ONE
                touch(nxt)
                session["seats_held"] = session.get("seats_held", 0) + 1
                offered.append(nxt)
            touch(session)
            refresh_session_counters(session)
    return expired, offered


def sweep_lapsed_offers_all():
    return sweep_lapsed_offers(None)


def materialise_lapsed_offers(session):
    """A read of a session or its holds reflects any offer whose window has
    already passed: the hold moves from OFFERED to EXPIRED and its freed seat is
    offered onward (PRD §3.4).  The server has no background scheduler, so a due
    lapse becomes visible when the row is next observed; the explicit sweep
    endpoint remains the operation that collects and reports them."""
    if session is None:
        return
    for entry in list(WAITLIST_ENTRIES.values()):
        if entry.get("class_session_id") != session["id"]:
            continue
        if entry.get("status") != "OFFERED":
            continue
        expires = entry.get("offer_expires_at")
        if expires is None or not (expires < now()):
            continue
        expire_entry(entry)


# ---------------------------------------------------------------------------
# Claim / cancel / confirm
# ---------------------------------------------------------------------------


def claim(entry, body):
    if entry.get("status") != "OFFERED":
        if entry.get("status") in ("CLAIMED", "EXPIRED", "CANCELLED"):
            fail("ERR_WAITLIST_TERMINAL")
        fail("ERR_ENTRY_NOT_OFFERED")
    expires = entry.get("offer_expires_at")
    if expires is not None and now() > expires:
        fail("ERR_ENTRY_NOT_OFFERED", "The offer window has lapsed.", 409)
    client = CLIENTS.get(entry.get("client_id"))
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    if client.get("status") not in ("ACTIVE", "FROZEN"):
        fail("ERR_CLIENT_NOT_ADMISSIBLE")
    session = entry.get("class_session_id")
    session = CLASS_SESSIONS.get(session)
    if session is None:
        fail("ERR_CLASS_SESSION_NOT_FOUND")

    from bookings import _materialise_booking

    payment_source = body.get("payment_source") or "DROP_IN"
    if payment_source not in ("DROP_IN", "MEMBERSHIP", "CLASS_PACK"):
        fail("ERR_PAYMENT_SOURCE_NOT_PERMITTED")
    membership = None
    pack = None
    if body.get("membership_id"):
        from store import MEMBERSHIPS

        membership = MEMBERSHIPS.get(body["membership_id"])
        if membership is None:
            fail("ERR_MEMBERSHIP_NOT_FOUND")
        if membership.get("status") != "ACTIVE":
            fail("ERR_MEMBERSHIP_INACTIVE")
    if body.get("class_pack_id"):
        from store import CLASS_PACKS

        pack = CLASS_PACKS.get(body["class_pack_id"])
        if pack is None:
            fail("ERR_CLASS_PACK_NOT_FOUND")
        if pack.get("status") != "ACTIVE" or pack.get("credits_remaining", 0) <= 0:
            fail("ERR_NO_ACTIVE_PACK")

    if session.get("status") == "CANCELLED_BY_STUDIO":
        fail("ERR_STUDIO_CAPACITY_EXCEEDED")

    booking = _materialise_booking(
        client=client,
        session=session,
        channel="STUDIO",
        payment_source=payment_source,
        membership=membership,
        pack=pack,
        is_promotional_seat=False,
        promo_redeem=False,
    )
    # the claimed seat moves from held to taken
    entry["status"] = "CLAIMED"
    entry["promoted_booking_id"] = booking["id"]
    touch(entry)
    session["seats_held"] = max(0, session.get("seats_held", 0) - 1)
    touch(session)
    refresh_session_counters(session)
    if session.get("capacity", 0) - occupied(session) > 0:
        offer_if_capacity(session)
    return booking


def cancel_entry(entry):
    status = entry.get("status")
    if status in ("CLAIMED", "EXPIRED", "CANCELLED"):
        fail("ERR_WAITLIST_TERMINAL")
    session = CLASS_SESSIONS.get(entry.get("class_session_id"))
    entry["status"] = "CANCELLED"
    touch(entry)
    if status == "OFFERED" and session is not None:
        offer_onward(session)
    else:
        if session is not None:
            refresh_session_counters(session)
    return entry


def confirm_position(entry):
    status = entry.get("status")
    if status in ("CLAIMED", "EXPIRED", "CANCELLED"):
        fail("ERR_WAITLIST_TERMINAL")
    if status != "STANDBY":
        fail("ERR_INVALID_STATE", "Only a standby hold may confirm a numbered position.", 409)
    joined = entry.get("joined_at")
    if joined is not None and now() > joined + timedelta(
        minutes=STANDBY_CONFIRM_WINDOW_MINUTES
    ):
        fail("ERR_INVALID_STATE", "The standby confirmation window has lapsed.", 409)
    entry["status"] = "ACTIVE"
    entry["position_mode"] = "QUEUED"
    entry["effective_sequence"] = entry.get("raw_sequence_no", 0)
    touch(entry)
    return entry


# ---------------------------------------------------------------------------
# Displacement
# ---------------------------------------------------------------------------


def demote_highest_booking(session):
    """A priority hold pushed the session past capacity: the highest-sequence
    RESERVED booking is demoted onto the waitlist."""
    from store import BOOKINGS

    reserved = [
        b
        for b in BOOKINGS.values()
        if b.get("class_session_id") == session["id"] and b.get("status") == "RESERVED"
    ]
    if not reserved:
        return None
    reserved.sort(key=lambda b: b.get("creation_seq", 0))
    booking = reserved[-1]
    from bookings import restore_booking_credit

    restore_booking_credit(booking)
    booking["status"] = "WAITLISTED"
    touch(booking)
    raw = max_sequence(session) + 1
    entry = mint(
        WAITLIST_ENTRIES,
        {
            "studio_id": session.get("studio_id"),
            "class_session_id": session["id"],
            "client_id": booking.get("client_id"),
            "joined_at": now(),
            "offer_expires_at": None,
            "status": "ACTIVE",
            "position_mode": "QUEUED",
            "raw_sequence_no": raw,
            "effective_sequence": raw,
            "promoted_booking_id": None,
        },
    )
    session["seats_taken"] = max(0, session.get("seats_taken", 1) - 1)
    refresh_session_counters(session)
    return entry