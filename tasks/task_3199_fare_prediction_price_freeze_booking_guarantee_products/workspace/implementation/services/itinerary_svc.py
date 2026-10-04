"""Itinerary lifecycle, watch subscriptions and booking/cancellation."""

from datetime import timedelta

from db import iso, DB, days_later, new_row, public, touch
from errors import fail
from middleware import as_int, as_str, as_ts
from services import calc
from services.routes_svc import (
    derive_itinerary, derive_route, freeze_locks, itinerary_or_404,
    rebalance_freeze, rebalance_route, region_postal_rederive, route_base_fare,
    route_or_404,
)

WATCH_STATUSES = ("ARMED", "NOTIFIED", "WAIT", "BUY_NOW", "CONFIRMED", "EXPIRED")


def create_itinerary(data):
    route = route_or_404(as_str(data, "route_id"))
    departure_date = as_ts(data, "departure_date")
    traveler_user_id = as_str(data, "traveler_user_id")

    itinerary = new_row(
        route_id=route["id"],
        departure_date=iso(departure_date),
        _departure_dt=departure_date,
        traveler_user_id=traveler_user_id,
        booking_date=DB.clock.stamp(),
        listed_fare_cents=0,
        last_observed_fare_cents=0,
        demand_curve_price_cents=0,
        each_day_disruption_fare_cents=0,
        fare_tier_ceiling_cents=0,
        observed_fares_cents=[],
        travel_status="PLANNED",
        watch_armed=False,
        guarantee_locked=False,
        _booking_hold_expires_at=None,
        booking_hold_expires_at=None,
    )
    DB.insert("itineraries", itinerary)
    derive_itinerary(itinerary)
    return itinerary


def observation_at_or_before(itinerary_id, instant):
    from services.routes_svc import observations_of
    obs = [o for o in observations_of(itinerary_id) if o["_observed_dt"] <= instant]
    if not obs:
        return None
    return obs[-1]


# --------------------------------------------------------------------------
# Watch subscriptions
# --------------------------------------------------------------------------

def arm_watch(itinerary_id, data):
    itinerary = itinerary_or_404(itinerary_id)
    expected = as_int(data, "expected_itinerary_version")

    if int(itinerary["version"]) != expected:
        fail("ERR_STALE_VERSION",
             "expected_itinerary_version does not match the itinerary version")
    if itinerary["travel_status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "a watch may only be armed on a PLANNED itinerary")
    route = route_or_404(itinerary["route_id"])
    if not route["curve_published"]:
        fail("ERR_CURVE_UNPUBLISHED", "the route has no published demand curve")

    watch = new_row(
        itinerary_id=itinerary["id"],
        armed_at=DB.clock.stamp(),
        expires_at=itinerary["departure_date"],
        notification_status="ARMED",
        notification_attempt_count=0,
        last_notified_fare_cents=0,
        last_notified_at=None,
        cooldown_until=None,
        cooldown_suppressed=False,
        buy_now_warranty_applied=False,
        locked_fare_cents=0,
        _buy_now_fare_cents=None,
        _expires_dt=itinerary["_departure_dt"],
    )
    DB.insert("watch_subscriptions", watch)

    itinerary["travel_status"] = "WATCHING"
    itinerary["watch_armed"] = True
    touch(itinerary)
    # The created resource is the watch subscription, not the parent itinerary
    # (PRD §2.2).
    return watch


def watch_or_404(watch_id):
    watch = DB.watch_subscriptions.get(watch_id)
    if watch is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no watch subscription %s" % watch_id)
    return watch


def evaluate_watch(watch, forced=None):
    """cost_of_waiting_evaluation + the cooldown half of the notification rule.

    Implements the WatchSubscription machine exactly as declared: ARMED →
    NOTIFIED on the first receipt, NOTIFIED → WAIT when the applied
    recommendation is a wait, WAIT → NOTIFIED on any later delivered
    recommendation (the cyclic return arc), NOTIFIED → NOTIFIED when the pass is
    cooldown-suppressed, and the system-driven ARMED → BUY_NOW escape clause
    when the route has closed. A NOTIFIED receipt is a delivery with no
    satisfying notification, so it opens the six-hour cooldown; a WAIT receipt
    is the applied recommendation itself.

    Returns the applied recommendation string.
    """
    itinerary = DB.itineraries[watch["itinerary_id"]]
    now = DB.clock.now()
    status = watch["notification_status"]

    # The system-fired BUY_NOW escape clause (PRD §3.2): a route that has moved
    # to RESTRICTED or CLOSED while the itinerary is still PLANNED/WATCHING
    # pushes the watcher to buy at the last observed fare. It is an ARMED →
    # BUY_NOW arc, distinct from a delivered recommendation.
    route = DB.routes.get(itinerary["route_id"])
    breaching = (forced is None and route is not None
                 and route["posture"] in ("RESTRICTED", "CLOSED")
                 and itinerary["travel_status"] in ("PLANNED", "WATCHING"))
    if breaching:
        watch["notification_status"] = "BUY_NOW"
        watch["buy_now_warranty_applied"] = True
        watch["last_notified_fare_cents"] = int(
            itinerary.get("last_observed_fare_cents") or 0)
        watch["last_notified_at"] = DB.clock.stamp()
        _open_hold(watch, itinerary)
        touch(watch)
        return "BUY_NOW"

    recommendation = forced if forced is not None else calc.cost_of_waiting(
        itinerary, watch, now)

    # Cooldown suppression: any pass at or before `cooldown_until` is computed
    # but not delivered, and a suppressed pass never advances the machine.
    cooldown_until = watch.get("_cooldown_until")
    if status in ("NOTIFIED", "WAIT"):
        if cooldown_until is not None and now <= cooldown_until:
            watch["cooldown_suppressed"] = True
            watch["notification_attempt_count"] = int(
                watch["notification_attempt_count"]) + 1
            touch(watch)
            return recommendation

    watch["cooldown_suppressed"] = False
    watch["notification_attempt_count"] = int(watch["notification_attempt_count"]) + 1

    if status == "WAIT":
        # WAIT → NOTIFIED: the cyclic return arc, taken on any delivered
        # recommendation. The receipt opens a fresh cooldown of its own.
        watch["notification_status"] = "NOTIFIED"
        watch["last_notified_at"] = DB.clock.stamp()
        watch["cooldown_until"] = iso(now + timedelta(hours=calc.COOLDOWN_HOURS))
        watch["_cooldown_until"] = now + timedelta(hours=calc.COOLDOWN_HOURS)
    elif status == "NOTIFIED" and recommendation == "WAIT":
        # NOTIFIED → WAIT: the applied recommendation is a wait. The delivery
        # opens a fresh cooldown of its own.
        watch["notification_status"] = "WAIT"
        watch["last_notified_at"] = DB.clock.stamp()
        watch["cooldown_until"] = iso(now + timedelta(hours=calc.COOLDOWN_HOURS))
        watch["_cooldown_until"] = now + timedelta(hours=calc.COOLDOWN_HOURS)
        itinerary["travel_status"] = "WATCHING"
        itinerary["watch_armed"] = True
        touch(itinerary)
    else:
        # ARMED → NOTIFIED, or NOTIFIED → NOTIFIED: a delivered receipt with no
        # satisfying notification. The first notification of a fresh watch is
        # never suppressed, and it opens the six-hour cooldown window.
        watch["notification_status"] = "NOTIFIED"
        watch["buy_now_warranty_applied"] = False
        watch["last_notified_at"] = DB.clock.stamp()
        watch["cooldown_until"] = iso(now + timedelta(hours=calc.COOLDOWN_HOURS))
        watch["_cooldown_until"] = now + timedelta(hours=calc.COOLDOWN_HOURS)

    touch(watch)
    return recommendation


def recompute_warranty(watch, itinerary):
    """The BUY_NOW warranty accumulates the MINIMUM fare seen across the
    24-hour holding window (PRD §3.2: the observed fare is recorded both at
    BUY_NOW and again at the end of the window, and the lock value is the
    minimum of the two)."""
    fare = int(itinerary.get("last_observed_fare_cents") or 0)
    if fare <= 0:
        return watch
    current = watch.get("_buy_now_fare_cents")
    if current is None or fare < int(current):
        watch["_buy_now_fare_cents"] = fare
    watch["locked_fare_cents"] = int(watch["_buy_now_fare_cents"])
    return watch


def _open_hold(watch, itinerary):
    instant = DB.clock.now() + timedelta(hours=calc.BUY_NOW_WINDOW_HOURS)
    itinerary["booking_hold_expires_at"] = iso(instant)
    itinerary["_booking_hold_expires_at"] = instant
    touch(itinerary)


def notify(watch_id, data):
    watch = watch_or_404(watch_id)
    itinerary = DB.itineraries[watch["itinerary_id"]]
    now = DB.clock.now()

    if watch["notification_status"] not in ("ARMED", "NOTIFIED", "WAIT"):
        fail("ERR_INVALID_STATE",
             "a watch in %s admits no notification" % watch["notification_status"])

    # Timing gate (PRD §2.6): a notification may not be evaluated for a watch
    # whose `expires_at` has passed, or for an itinerary that has departed.
    if now > watch["_expires_dt"]:
        watch["notification_status"] = "EXPIRED"
        itinerary["travel_status"] = "PLANNED"
        itinerary["watch_armed"] = False
        touch(itinerary)
        touch(watch)
        fail("ERR_WATCH_EXPIRED", "the watch has passed its expires_at")
    if itinerary["_departure_dt"] <= now and itinerary["travel_status"] != "BOOKED":
        fail("ERR_WATCH_EXPIRED", "the watched itinerary has already departed")

    evaluate_watch(watch)
    return watch


def confirm_watch(watch_id, data):
    watch = watch_or_404(watch_id)
    itinerary = DB.itineraries[watch["itinerary_id"]]
    now = DB.clock.now()

    if watch["notification_status"] not in ("BUY_NOW", "NOTIFIED"):
        fail("ERR_INVALID_STATE",
             "a watch in %s admits no confirmation" % watch["notification_status"])

    if watch["notification_status"] == "BUY_NOW":
        cooldown = watch.get("_cooldown_until")
        if cooldown is not None:
            limit = cooldown.replace()
            from datetime import timedelta
            limit = cooldown + timedelta(hours=calc.BUY_NOW_WINDOW_HOURS)
            if now > limit:
                fail("ERR_NOTIFICATION_SUPPRESSED", "the BUY_NOW warranty window has closed")
        else:
            hold = itinerary.get("_booking_hold_expires_at")
            if hold is None or now > hold:
                fail("ERR_NOTIFICATION_SUPPRESSED", "the booking hold has expired")
    else:
        if int(watch.get("last_notified_fare_cents") or 0) <= 0:
            fail("ERR_INVALID_STATE",
                 "no satisfying BUY_NOW notification has been delivered")

    # Warranty closure: the lock value is the minimum of the BUY_NOW fare and
    # the fare observed at the end of the 24-hour holding window.
    recompute_warranty(watch, itinerary)

    book_itinerary(itinerary, via_watch=True)
    watch["notification_status"] = "CONFIRMED"
    itinerary["watch_armed"] = False
    touch(itinerary)
    touch(watch)
    return watch


# --------------------------------------------------------------------------
# Booking and cancellation
# --------------------------------------------------------------------------

def book_itinerary(itinerary, via_watch=False):
    """Close the itinerary at the current listed fare.

    A bare booking demands PLANNED alone (PRD §3.10). The watch machine's
    BUY_NOW -> CONFIRMED arc books an itinerary that is still WATCHING, which is
    exactly the arc that resolves an armed watch, so `via_watch` admits it.
    """
    route = DB.routes[itinerary["route_id"]]
    admissible = ("PLANNED", "WATCHING") if via_watch else ("PLANNED",)
    if itinerary["travel_status"] not in admissible:
        fail("ERR_ITINERARY_NOT_PLANNED",
             "an itinerary must be PLANNED before it can be booked")
    if int(route["seats_left"]) < 1:
        fail("ERR_NO_SEATS_LEFT", "the route has no sellable seats left")

    itinerary["travel_status"] = "BOOKED"
    itinerary["listed_fare_cents"] = int(route["base_fare_cents"])
    route["seats_left"] = int(route["seats_left"]) - 1
    itinerary["watch_armed"] = False

    for watch in DB.all("watch_subscriptions"):
        if watch["itinerary_id"] == itinerary["id"] and watch["notification_status"] in (
                "ARMED", "NOTIFIED", "WAIT", "BUY_NOW"):
            watch["notification_status"] = "CONFIRMED"
            touch(watch)

    for freeze in DB.all("price_freezes"):
        if freeze["itinerary_id"] == itinerary["id"] and freeze["status"] == "FROZEN":
            convert_freeze(freeze, itinerary, route)

    itinerary["guarantee_locked"] = freeze_locks(itinerary["id"])
    touch(itinerary)
    return itinerary


def book(itinerary_id, data):
    itinerary = itinerary_or_404(itinerary_id)
    if "expected_itinerary_version" in data and data["expected_itinerary_version"] is not None:
        expected = as_int(data, "expected_itinerary_version")
        if expected != int(itinerary["version"]):
            fail("ERR_STALE_VERSION",
                 "expected_itinerary_version does not match the itinerary version")
    return book_itinerary(itinerary)


def cancel_itinerary(itinerary_id, data):
    itinerary = itinerary_or_404(itinerary_id)
    if itinerary["travel_status"] not in ("PLANNED", "WATCHING"):
        fail("ERR_INVALID_STATE",
             "only a PLANNED or WATCHING itinerary can be cancelled")

    itinerary["travel_status"] = "CANCELLED"
    itinerary["watch_armed"] = False

    for watch in DB.all("watch_subscriptions"):
        if watch["itinerary_id"] == itinerary["id"] and watch["notification_status"] in (
                "ARMED", "NOTIFIED", "WAIT", "BUY_NOW"):
            watch["notification_status"] = "EXPIRED"
            touch(watch)

    route = DB.routes[itinerary["route_id"]]
    for freeze in DB.all("price_freezes"):
        if freeze["itinerary_id"] != itinerary["id"]:
            continue
        if freeze["status"] in ("DRAFT", "HELD", "FROZEN"):
            cancel_freeze_internal(freeze, itinerary, route, exempt=False)

    itinerary["guarantee_locked"] = False
    touch(itinerary)
    rebalance_route(route)
    return itinerary


# --------------------------------------------------------------------------
# Freeze cascades called from the itinerary side
# --------------------------------------------------------------------------

def convert_freeze(freeze, itinerary, route):
    from services.freeze_svc import convert_internal
    return convert_internal(freeze, itinerary, route)


def cancel_freeze_internal(freeze, itinerary, route, exempt):
    from services.freeze_svc import cancel_internal
    return cancel_internal(freeze, itinerary, route, exempt=exempt)


# --------------------------------------------------------------------------
# Network lapse sweep
# --------------------------------------------------------------------------

def lapse_watches():
    now = DB.clock.now()
    for watch in DB.all("watch_subscriptions"):
        if watch["notification_status"] in ("ARMED", "NOTIFIED", "WAIT", "BUY_NOW"):
            if watch["_expires_dt"] is not None and now > watch["_expires_dt"]:
                watch["notification_status"] = "EXPIRED"
                itinerary = DB.itineraries[watch["itinerary_id"]]
                itinerary["travel_status"] = "PLANNED"
                itinerary["watch_armed"] = False
                touch(itinerary)
                touch(watch)