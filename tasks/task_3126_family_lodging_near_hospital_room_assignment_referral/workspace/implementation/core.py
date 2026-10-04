"""Core business logic: scoring, ranking, room selection, cascades, sweeps."""
from datetime import timedelta

from decimal import Decimal, ROUND_HALF_UP

import store

# ---------------------------------------------------------------------------
# Priority scoring (PRD §2.8)
# ---------------------------------------------------------------------------

_ACUITY_MULT = {"LOW": 1.0, "MODERATE": 1.25, "HIGH": 1.5, "CRITICAL": 2.0}


def compute_score(distance_miles, acuity, expected_nights):
    dist = float(distance_miles)
    if 50 <= dist < 100:
        band = 40.0
    elif 100 <= dist < 250:
        band = 60.0
    elif dist >= 250:
        band = 80.0
    else:
        band = 0.0
    mult = _ACUITY_MULT[acuity]
    stay_factor = min(30, expected_nights) / 30
    raw = band * mult + 20.0 * stay_factor
    raw = min(100.0, raw)
    score = Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(score)


# ---------------------------------------------------------------------------
# Referral helpers
# ---------------------------------------------------------------------------


def referral_chain_revocation(referral):
    """Hops 1-3 of the revocation/expiry cascade (PRD §3.2). Returns the list
    of rooms freed by offer rescission so callers can re-offer them."""
    freed_rooms = []
    now_dt = store.now()
    for req in store.db["stay_requests"].values():
        if (
            req["referral_id"] == referral["id"]
            and req["verification_status"] == "VERIFICATION_OK"
        ):
            req["verification_status"] = "VERIFICATION_FAILED"
            bump(req)
            if req["assignment_status"] == "OFFERED" and req["offered_room_id"]:
                freed_rooms.append(req["offered_room_id"])
                req["assignment_status"] = "WAITLISTED"
                req["offered_room_id"] = None
                req["offer_expires_at"] = None
                req["waitlisted_since"] = store.now_iso()
                bump(req)
    _ = now_dt
    # Independently: ACTIVE stays chained to this referral -> UNDER_REVIEW
    for stay in store.db["stays"].values():
        if stay["status"] != "ACTIVE":
            continue
        req = store.db["stay_requests"].get(stay["stay_request_id"])
        if req and req["referral_id"] == referral["id"]:
            stay["status"] = "UNDER_REVIEW"
            stay["review_reason"] = "REFERRAL_REVOKED"
            bump(stay)
    return freed_rooms


# ---------------------------------------------------------------------------
# Waitlist ranking + room selector (PRD §2.9)
# ---------------------------------------------------------------------------


def eligible_waitlisted(house_id):
    return [
        req
        for req in store.db["stay_requests"].values()
        if req["house_id"] == house_id
        and req["assignment_status"] == "WAITLISTED"
        and req["verification_status"] == "VERIFICATION_OK"
    ]


def rank_waitlist(candidates):
    return sorted(
        candidates,
        key=lambda r: (-(r["verified_score"] or 0.0), r["waitlisted_since"] or "", r["_seq"]),
    )


def reserved_room_ids():
    return {
        req["offered_room_id"]
        for req in store.db["stay_requests"].values()
        if req["assignment_status"] == "OFFERED" and req["offered_room_id"]
    }


def eligible_rooms(house_id, exclude_room_id=None):
    reserved = reserved_room_ids()
    return [
        r
        for r in store.db["rooms"].values()
        if r["house_id"] == house_id
        and r["status"] == "AVAILABLE"
        and not r["occupied"]
        and r["id"] not in reserved
        and (exclude_room_id is None or r["id"] != exclude_room_id)
    ]


def select_room(rooms):
    if not rooms:
        return None
    return sorted(rooms, key=lambda r: (r["bed_count"], r["room_number"]))[0]


def promote_one(house_id, prefer_room_id=None, exclude_room_ids=None):
    """Promote the highest-ranked eligible waitlisted request at a house into
    one room. When prefer_room_id is given and still free, that room is used
    (check-out cascade: the freed room is offered); otherwise room_selector
    applies. Returns the promoted request or None."""
    candidates = eligible_waitlisted(house_id)
    if not candidates:
        return None
    ranked = rank_waitlist(candidates)
    exclude = set(exclude_room_ids or [])
    for req in ranked:
        room = None
        if prefer_room_id and prefer_room_id not in exclude:
            cand = store.db["rooms"].get(prefer_room_id)
            if (
                cand
                and cand["house_id"] == house_id
                and cand["status"] == "AVAILABLE"
                and not cand["occupied"]
                and cand["id"] not in reserved_room_ids()
            ):
                room = cand
        if room is None:
            rooms = [
                r
                for r in eligible_rooms(house_id)
                if r["id"] not in exclude
            ]
            room = select_room(rooms)
        if room is None:
            continue
        req["assignment_status"] = "OFFERED"
        req["offered_room_id"] = room["id"]
        req["offer_expires_at"] = store.iso(store.now() + timedelta(hours=48))
        bump(req)
        return req
    return None


def reoffer_freed_rooms(house_id, freed_room_ids):
    """Hop 3: re-offer each room freed by a revocation cascade."""
    for room_id in freed_room_ids:
        promote_one(house_id, prefer_room_id=room_id)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------


def bump(rec):
    """Refresh updated_at and increment version on a mutable record."""
    rec["updated_at"] = store.now_iso()
    rec["version"] = rec.get("version", 0) + 1


def touch_only(rec):
    rec["updated_at"] = store.now_iso()


def new_record(extra=None, with_common=True):
    rec = {}
    if with_common:
        rec["id"] = store.new_id()
        rec["created_at"] = store.now_iso()
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
        rec["_seq"] = store.next_seq()
    if extra:
        rec.update(extra)
    return rec
