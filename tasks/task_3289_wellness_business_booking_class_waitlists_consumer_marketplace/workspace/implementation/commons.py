"""Common resource mechanics: identity, timestamps, versions, ownership and
the per-tenant derived aggregates."""

from core import GATE_KEYS, TIER_GATE_SOURCE, fail, new_id, now
from store import (
    CLASS_PACKS,
    CLASS_SESSIONS,
    CLIENTS,
    COMMISSION_ENTRIES,
    MEMBERSHIPS,
    PAYROLL_PERIODS,
    STAFF_MEMBERS,
    STUDIOS,
    SUBSCRIPTIONS,
    TIERS,
)


def mint(collection, fields):
    """Create a row with common fields (PRD §2.7) and register it."""
    stamp = now()
    entity = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    entity.update(fields)
    collection[entity["id"]] = entity
    return entity


def mint_config(collection, key, fields):
    """Configuration rows (SubscriptionTier, BenefitNetwork) carry only id and
    created_at — no updated_at, no version (PRD §2.7)."""
    entity = {"id": new_id(), "created_at": now()}
    entity.update(fields)
    collection[key] = entity
    return entity


def touch(entity):
    """Increment version by 1 and stamp updated_at on every mutation."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now()
    return entity


def get_or_404(collection, key, error_id):
    row = collection.get(key)
    if row is None:
        fail(error_id)
    return row


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


def assert_studio_owned(role, actor_id, studio_id):
    """StudioOwner identity is bound to its Studio id (PRD §2.1)."""
    if role == "StudioOwner" and actor_id != studio_id:
        fail("ERR_STUDIO_NOT_OWNED")


def assert_client_owned(role, actor_id, client_id):
    if role == "Client" and actor_id != client_id:
        fail("ERR_STUDIO_NOT_OWNED")


def assert_staff_owned(role, actor_id, staff_id):
    if role == "StaffMember" and actor_id != staff_id:
        fail("ERR_STUDIO_NOT_OWNED")


def is_admin(role):
    return role == "PlatformAdmin"


# ---------------------------------------------------------------------------
# Derived tier / gates
# ---------------------------------------------------------------------------


def tier_row(tier_name):
    return TIERS.get(tier_name)


def feature_gates(tier_name):
    row = TIERS.get(tier_name)
    gates = {}
    for gate in GATE_KEYS:
        source = TIER_GATE_SOURCE[gate]
        gates[gate] = bool(row.get(source, False)) if row else False
    return gates


def gate_enabled(studio, gate):
    return bool(studio.get("feature_gates", {}).get(gate, False))


def require_gate(studio, gate):
    if not gate_enabled(studio, gate):
        fail("ERR_FEATURE_NOT_IN_TIER")


# ---------------------------------------------------------------------------
# Studio derived fields
# ---------------------------------------------------------------------------


def derive_client_roster_count(studio_id):
    return sum(
        1
        for client in CLIENTS.values()
        if client.get("home_studio_id") == studio_id
        and client.get("status") in ("ACTIVE", "FROZEN")
    )


def derive_outstanding_balance_cents(studio_id):
    total = 0
    for membership in MEMBERSHIPS.values():
        if membership.get("studio_id") != studio_id:
            continue
        if membership.get("status") in ("CANCELLED", "EXPIRED"):
            continue
        total += membership.get("open_balance_cents", 0)
    for booking in _bookings_of_studio(studio_id):
        if booking.get("status") in ("NO_SHOW", "LATE_CANCELLED") and booking.get(
            "fee_status"
        ) in ("CHARGED", "PAYROLL_DEDUCTED"):
            total += booking.get("booking_fee_cents", 0)
    for pack in CLASS_PACKS.values():
        if pack.get("studio_id") == studio_id:
            total += pack.get("_overage_cents", 0)
    return max(0, total)


def _bookings_of_studio(studio_id):
    from store import BOOKINGS

    return [b for b in BOOKINGS.values() if b.get("studio_id") == studio_id]


def derive_data_ownership_state(studio_id):
    """Recomputed from the request history rather than stored independently
    (PRD §3.10).  The most recently accepted request decides the posture, and a
    denial, withdrawal, expiry or defaulted objection returns it to OWNED."""
    from store import PORTABILITY_REQUESTS

    if STUDIOS.get(studio_id) is None:
        return "OWNED"
    history = [
        r for r in PORTABILITY_REQUESTS.values() if r.get("studio_id") == studio_id
    ]
    history.sort(key=lambda r: (r.get("created_at"), str(r.get("id"))), reverse=True)
    for request in history:
        status = request.get("status")
        if status in ("PENDING", "OBJECTED"):
            return "PORTABILITY_PENDING"
        if status == "EXPORT_ISSUED":
            if request.get("export_download_count", 0) >= 3:
                return "EXPORT_CLOSED"
            return "PORTABILITY_GRANTED"
        if status == "RESOLVED_RELEASE":
            return "PORTABILITY_GRANTED"
        if status in ("RESOLVED_DENIED", "EXPIRED", "WITHDRAWN"):
            return "OWNED"
    return "OWNED"


def refresh_studio(studio):
    if studio is None:
        return
    studio_id = studio["id"]
    studio["client_roster_count"] = derive_client_roster_count(studio_id)
    studio["outstanding_balance_cents"] = derive_outstanding_balance_cents(studio_id)
    studio["data_ownership_state"] = derive_data_ownership_state(studio_id)
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    if subscription is not None:
        studio["subscription_tier"] = subscription.get("tier")
        studio["feature_gates"] = feature_gates(subscription.get("tier"))
    else:
        studio["feature_gates"] = feature_gates(studio.get("subscription_tier"))


def refresh_subscription(subscription):
    studio = STUDIOS.get(subscription.get("studio_id"))
    tier = subscription.get("tier")
    subscription["staff_seat_count"] = sum(
        1
        for staff in STAFF_MEMBERS.values()
        if staff.get("studio_id") == studio["id"]
        and staff.get("status") in ("ACTIVE", "SUBSTITUTE_ONLY")
    )
    row = TIERS.get(tier)
    included = row.get("included_staff_seats", 0) if row else 0
    subscription["seat_overage_count"] = max(
        0, subscription["staff_seat_count"] - included
    )
    subscription["payroll_hold"] = subscription.get("dunning_stage") in (
        "SUSPENDED",
        "CANCELLED",
    )
    return subscription


def refresh_staff_accrued(staff):
    entry = None
    for candidate in COMMISSION_ENTRIES.values():
        if candidate.get("staff_member_id") != staff["id"]:
            continue
        if candidate.get("status") != "ACCRUED":
            continue
        period = PAYROLL_PERIODS.get(candidate.get("payroll_period_id"))
        if period is None or period.get("status") != "OPEN":
            continue
        entry = (entry or 0) + candidate.get("commission_cents", 0)
    staff["accrued_commission_cents"] = entry or 0


def derive_studio_status(subscription):
    """The studio's operating posture follows its subscription."""
    if subscription is None:
        return None
    status = subscription.get("status")
    if status == "CANCELLED":
        return "CANCELLED"
    if status == "SUSPENDED":
        return "SUSPENDED"
    if status in ("TRIAL", "ACTIVE", "GRACE"):
        return "ACTIVE"
    return None


def derive_client_outstanding_fee_cents(client_id):
    from store import BOOKINGS

    total = 0
    for booking in BOOKINGS.values():
        if booking.get("client_id") != client_id:
            continue
        if booking.get("fee_status") in ("CHARGED", "PAYROLL_DEDUCTED"):
            total += booking.get("booking_fee_cents", 0)
    return total


def refresh_client(client):
    if client is None:
        return
    client["outstanding_fee_cents"] = derive_client_outstanding_fee_cents(client["id"])


def refresh_session_counters(session):
    from store import BOOKINGS, WAITLIST_ENTRIES

    taken = sum(
        1
        for b in BOOKINGS.values()
        if b.get("class_session_id") == session["id"]
        and b.get("status") in ("RESERVED", "CHECKED_IN", "NO_SHOW")
    )
    holds = sum(
        1
        for w in WAITLIST_ENTRIES.values()
        if w.get("class_session_id") == session["id"] and w.get("status") == "OFFERED"
    )
    session["seats_taken"] = taken
    # A cancelled studio closure expires every hold, so the held count follows the
    # holds that still actually reserve capacity (PRD §2.9: seats_held counts the
    # OFFERED waitlist holds).  A live offer is still held even when it lapses and
    # is retired: the freed seat goes back on the pool only through the offer
    # sweep, so a plain read may not release it.
    session["seats_held"] = max(session.get("seats_held", 0), holds)
    if session.get("status") == "CANCELLED_BY_STUDIO":
        session["seats_held"] = holds
    from calc import fullness_posture

    session["fullness_posture"] = fullness_posture(session)


def refresh_payroll_period(period):
    accrued = 0
    paid = 0
    for entry in COMMISSION_ENTRIES.values():
        if entry.get("payroll_period_id") != period["id"]:
            continue
        if entry.get("status") == "ACCRUED":
            accrued += entry.get("commission_cents", 0)
        elif entry.get("status") == "PAID":
            paid += entry.get("commission_cents", 0)
    period["accrued_commission_cents"] = accrued
    period["paid_commission_cents"] = paid
    return period