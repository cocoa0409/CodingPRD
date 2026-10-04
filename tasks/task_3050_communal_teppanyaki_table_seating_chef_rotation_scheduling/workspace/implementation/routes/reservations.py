"""Reservation endpoints: draft, submit, hold, seat, party-size, close, reopen, no-show."""
from datetime import timedelta

from flask import Blueprint

import constants as C
import db
import helpers as h
import services as svc
from errors import fail
from middleware import guard
from response import ok

bp = Blueprint("reservations", __name__)

READ_ROLES = C.ROLES


def _resolve_party(payload, reservation):
    """Party gate: a RESTRICTED party may not start or join a seating episode."""
    party = db.get("parties", reservation.get("party_id"))
    if party is not None and party.get("status") == "RESTRICTED":
        fail("ERR_PARTY_RESTRICTED")
    return party


@bp.route("/service-floor/reservations", methods=["POST"])
def create_reservation():
    guard(["Host"])
    body = h.payload()
    venue = svc.venue_or_404(h.as_string(body, "venue_id"))
    party = svc.party_or_404(h.as_string(body, "party_id"))
    tier = svc.tier_or_404(h.as_string(body, "tier_id"))
    reservation = db.add("reservations", db.new_row(
        venue_id=venue["id"],
        party_id=party["id"],
        tier_id=tier["id"],
        party_size=h.as_int(body, "party_size", minimum=1),
        scheduled_time=h.as_datetime(body, "scheduled_time"),
        payment_mode=h.as_string(body, "payment_mode", enum=C.PAYMENT_MODES),
        credit_to_apply_cents=h.as_int(body, "credit_to_apply_cents", required=False,
                                       default=0, minimum=0),
        celebration=h.as_string(body, "celebration", required=False, default="NONE",
                                enum=C.CELEBRATIONS),
        invite_code=h.as_string(body, "invite_code", required=False, default=None,
                                allow_empty=True),
        status="DRAFT",
        hold_count=0,
        hold_until=None,
        table_id=None,
        chef_assignment_id=None,
        quote_final_cents=0,
        final_bill_cents=0,
        check_cents=0,
        seat_surcharge_cents=0,
        credit_applied_cents=0,
        celebration_fee_cents=0,
        last_ops_epoch=0,
        current_seating_id=None,
        current_sushi_show_id=None,
        current_grill_show_id=None,
    ))
    svc.stamp_quote(reservation)
    return ok(db.public(db.get("reservations", reservation["id"])), 201)


@bp.route("/service-floor/reservations", methods=["GET"])
def list_reservations():
    guard(READ_ROLES)
    rows = h.filter_rows(
        db.all_of("reservations"),
        venue_id=h.q("venue_id"), party_id=h.q("party_id"), tier_id=h.q("tier_id"),
        table_id=h.q("table_id"), chef_assignment_id=h.q("chef_assignment_id"),
        current_seating_id=h.q("current_seating_id"),
        current_sushi_show_id=h.q("current_sushi_show_id"),
        current_grill_show_id=h.q("current_grill_show_id"), status=h.q("status"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    guard(READ_ROLES)
    reservation = svc.reservation_or_404(reservation_id)
    return ok(db.public(reservation), 200)


@bp.route("/service-floor/reservations/<reservation_id>/events", methods=["POST"])
def reservation_event(reservation_id):
    guard(["Host"])
    reservation = svc.reservation_or_404(reservation_id)
    body = h.payload()
    event_type = h.as_string(body, "event_type")
    if event_type == "SUBMIT":
        return _submit(reservation)
    if event_type == "MARK_NO_SHOW":
        return ok(db.public(svc.mark_no_show(reservation)), 200)
    fail("ERR_INVALID_REQUEST", "Unknown reservation event_type: %s" % event_type)


def _submit(reservation):
    if reservation.get("status") != "DRAFT":
        fail("ERR_INVALID_STATE")
    venue = svc.venue_or_404(reservation["venue_id"])
    _resolve_party(None, reservation)
    if venue.get("status") != "ACTIVE":
        fail("ERR_INVALID_STATE")
    tier = svc.tier_or_404(reservation["tier_id"])
    svc.validate_booking_time(reservation["scheduled_time"])
    if not svc.tier_matches(reservation, tier):
        fail("ERR_TIER_MISMATCH")
    if tier.get("status") != "ACTIVE":
        fail("ERR_TIER_RETIRED")
    reservation = db.touch(reservation, status="REQUESTED",
                           last_ops_epoch=venue.get("ops_epoch", 0))
    svc.stamp_quote(reservation)
    return ok(db.public(db.get("reservations", reservation["id"])), 200)


@bp.route("/service-floor/reservations/<reservation_id>/holds", methods=["POST"])
def grant_hold(reservation_id):
    guard(["Host"])
    reservation = svc.reservation_or_404(reservation_id)
    body = h.payload()
    expected = h.as_int(body, "expected_table_version", required=False)
    named_table_id = h.as_string(body, "table_id", required=False)

    target = None
    if named_table_id is not None:
        target = svc.table_or_404(named_table_id)
        if expected is not None and expected != target.get("version"):
            fail("ERR_STALE_VERSION")
    elif expected is not None:
        passed = [t for t in db.all_of("tables") if t.get("version") == expected]
        if not passed:
            fail("ERR_STALE_VERSION")

    venue = svc.venue_or_404(reservation["venue_id"])
    re_parking = reservation.get("status") == "HELD"

    if reservation.get("status") == "HELD":
        if db.now() < reservation.get("hold_until"):
            fail("ERR_INVALID_STATE")
    elif reservation.get("status") != "REQUESTED":
        fail("ERR_INVALID_STATE")

    # §2.10: "a request that a workflow declares to be guarded by more than one
    # rule is always reported against the highest-priority rule it violates." The
    # venue-freeze safety guard (priority 12) outranks the party-restriction
    # referential guard (priority 22), so it is evaluated first.
    if venue.get("occupancy_freeze"):
        fail("ERR_VENTILATION_FREEZE")

    # Only a party that may start or join a seating episode can hold a grill.
    _resolve_party(None, reservation)

    tier = svc.tier_or_404(reservation["tier_id"])
    if not svc.tier_matches(reservation, tier):
        fail("ERR_TIER_MISMATCH")
    if tier.get("status") != "ACTIVE":
        fail("ERR_TIER_RETIRED")

    # Over-capacity (priority 8) is reported ahead of the hold cap (priority 9),
    # so a request that breaks both surfaces the capacity failure.
    if target is None:
        target = svc.best_table_for(venue["id"], reservation.get("party_size", 0),
                                    reservation)
    if target is None or target.get("venue_id") != venue["id"]:
        fail("ERR_TABLE_OVER_CAPACITY")
    if not _table_eligible_for_hold(target, reservation):
        fail("ERR_TABLE_OVER_CAPACITY")

    if reservation.get("hold_count", 0) >= C.HOLD_MAX_COUNT:
        fail("ERR_HOLD_LIMIT_EXCEEDED")
    _validate_shared_split(reservation)

    window_start = db.now()
    window_end = window_start + timedelta(minutes=C.HOLD_WINDOW_MINUTES)
    if svc.table_maintenance_conflict(target["id"], window_start, window_end):
        fail("ERR_MAINTENANCE_CONFLICT")

    previous_table_id = reservation.get("table_id") if re_parking else None
    reservation = svc.hold_reservation(reservation, target)
    if previous_table_id and previous_table_id != target["id"]:
        # The previously assigned table is released first.
        svc.release_table_if_free(previous_table_id)
    return ok(db.public(reservation), 200)


def _table_eligible_for_hold(table, reservation):
    if table.get("status") not in ("AVAILABLE", "SEATED"):
        return False
    party_size = reservation.get("party_size", 0)
    limit = svc.capacity_limit(table, reservation)
    if party_size > limit:
        return False
    if table.get("guests_seated", 0) + party_size > limit:
        return False
    return True


def _validate_shared_split(reservation):
    code = reservation.get("invite_code")
    if not code:
        return
    clock = db.now()
    for other in db.all_of("reservations"):
        if other.get("id") == reservation.get("id"):
            continue
        if other.get("invite_code") != code:
            continue
        if other.get("status") in ("NO_SHOW", "ABANDONED", "CLOSED"):
            continue
        hold_until = other.get("hold_until")
        if hold_until is None or hold_until <= clock:
            fail("ERR_SHARED_SPLIT_INVALID")
        delta = abs((other.get("scheduled_time") - reservation.get("scheduled_time"))
                    .total_seconds()) / 60.0
        if delta > C.PRIOR_HOLD_GRACE_MINUTES:
            fail("ERR_SHARED_SPLIT_INVALID")


@bp.route("/service-floor/reservations/<reservation_id>/seat", methods=["POST"])
def seat_reservation(reservation_id):
    guard(["Host"])
    reservation = svc.reservation_or_404(reservation_id)
    venue = svc.venue_or_404(reservation["venue_id"])
    _resolve_party(None, reservation)

    if reservation.get("status") != "HELD":
        fail("ERR_INVALID_STATE")
    if venue.get("occupancy_freeze"):
        fail("ERR_VENTILATION_FREEZE")
    hold_until = reservation.get("hold_until")
    if hold_until is not None and db.now() >= hold_until:
        fail("ERR_HOLD_WINDOW_CLOSED")

    party_size = reservation.get("party_size", 0)
    candidates = svc.seatable_tables(venue["id"], party_size, reservation)
    existing = svc.active_seatings_for_reservation(reservation["id"])

    # The booking's own held table is the first choice; a booking whose table
    # has been taken out from under it rolls onto another table that bears the
    # booking's own tier code, and only then any other table that fits.
    tier = svc.tier_for_reservation(reservation)
    booking_tier_code = (tier or {}).get("tier_code")
    table = None
    held_table = db.get("tables", reservation.get("table_id"))
    if held_table is not None and any(c["id"] == held_table["id"] for c in candidates):
        table = held_table
    if table is None:
        same_tier = [c for c in candidates if c.get("tier_code") == booking_tier_code]
        pool = same_tier or candidates
        table = pool[0] if pool else None
    if table is None:
        if held_table is None:
            fail("ERR_INVALID_STATE")
        fail("ERR_TABLE_OVER_CAPACITY")

    for seating in existing:
        if seating.get("table_id") == table["id"]:
            fail("ERR_DUPLICATE_SEATING")

    start = svc.calc.snap_to_grid(db.now())
    tier = svc.tier_for_reservation(reservation)
    expected_vacate = svc.calc.turn_over_window(
        reservation["scheduled_time"], tier, reservation.get("celebration", "NONE"))
    if svc.table_maintenance_conflict(table["id"], start, expected_vacate):
        fail("ERR_MAINTENANCE_CONFLICT")

    chef = svc.select_chef_for(venue["id"], table.get("tier_code"))
    if chef is None:
        fail("ERR_CHEF_ROTATION_EXHAUSTED")

    reservation, _seating = svc.seat_reservation(reservation, table, chef)
    return ok(db.public(db.get("reservations", reservation["id"])), 200)


@bp.route("/service-floor/reservations/<reservation_id>/party-size", methods=["POST"])
def party_size(reservation_id):
    guard(["Host"])
    reservation = svc.reservation_or_404(reservation_id)
    body = h.payload()
    if reservation.get("status") not in ("SEATED", "HELD"):
        fail("ERR_INVALID_STATE")
    new_size = h.as_int(body, "party_size", minimum=1)
    celebration = h.as_string(body, "celebration", required=False)
    venue = svc.venue_or_404(reservation["venue_id"])
    if venue.get("occupancy_freeze"):
        fail("ERR_VENTILATION_FREEZE")
    if celebration is not None and celebration not in C.CELEBRATIONS:
        fail("ERR_INVALID_REQUEST")

    table = db.get("tables", reservation.get("table_id"))
    if table is not None:
        others = sum(s.get("guest_count", 0) for s in svc.active_seatings_at_table(table["id"])
                     if s.get("reservation_id") != reservation["id"])
        limit = svc.capacity_limit(table, reservation)
        if new_size > limit or others + new_size > limit:
            # The booking outgrew its table: re-home it when a larger one is free.
            replacement = None
            if reservation.get("status") == "HELD":
                replacement = svc.best_table_for(venue["id"], new_size, reservation)
            if replacement is None:
                fail("ERR_TABLE_OVER_CAPACITY")
            table = replacement

    changes = {"party_size": new_size, "table_id": table["id"] if table else None}
    if celebration is not None:
        changes["celebration"] = celebration
    reservation = db.touch(reservation, **changes)

    # A seated booking's occupancy carries the new guest count and its surcharge
    # is rebuilt from the new party size.
    if reservation.get("status") == "SEATED":
        for seating in svc.active_seatings_for_reservation(reservation["id"]):
            db.touch(seating, guest_count=new_size)
        tier = svc.tier_for_reservation(reservation)
        if tier is not None:
            db.touch(reservation, seat_surcharge_cents=svc.calc.seat_surcharge(
                new_size, tier.get("base_rate_per_guest_cents", 0)))
        if table is not None:
            svc.recompute_table_guests(table)

    svc.stamp_quote(reservation)
    return ok(db.public(db.get("reservations", reservation["id"])), 200)


@bp.route("/service-floor/reservations/<reservation_id>/close", methods=["POST"])
def close_reservation(reservation_id):
    guard(["Host"])
    reservation = svc.reservation_or_404(reservation_id)
    body = h.payload()
    expected = h.as_int(body, "expected_reservation_version", required=False)
    if expected is not None and expected != reservation.get("version"):
        fail("ERR_STALE_VERSION")
    credit_to_apply = h.as_int(body, "credit_to_apply_cents", required=False, default=0,
                               minimum=0)
    if reservation.get("status") != "SEATED":
        fail("ERR_INVALID_STATE")
    if not svc.active_seatings_for_reservation(reservation["id"]):
        fail("ERR_NO_ACTIVE_SEATING")
    reservation = svc.close_reservation(reservation, credit_to_apply)
    return ok(db.public(db.get("reservations", reservation["id"])), 200)


@bp.route("/service-floor/reservations/<reservation_id>/reopen", methods=["POST"])
def reopen_reservation(reservation_id):
    guard(["Host"])
    reservation = svc.reservation_or_404(reservation_id)
    body = h.payload()
    if reservation.get("status") != "ABANDONED":
        fail("ERR_INVALID_STATE")
    venue = svc.venue_or_404(reservation["venue_id"])
    if venue.get("occupancy_freeze"):
        fail("ERR_VENTILATION_FREEZE")
    if venue.get("status") != "ACTIVE":
        fail("ERR_INVALID_STATE")
    # §3.7: reopening recovers the booking onto the floor, which requires the venue
    # to be ACTIVE and a table satisfying every condition a first hold would — i.e.
    # no booking may still be mid-service (SEATED) at the venue.
    for other in db.all_of("reservations"):
        if other.get("venue_id") == venue["id"] and other.get("status") == "SEATED":
            fail("ERR_INVALID_STATE")
    if reservation.get("hold_count", 0) >= C.HOLD_MAX_COUNT:
        fail("ERR_HOLD_LIMIT_EXCEEDED")

    named = h.as_string(body, "table_id", required=False)
    target = db.get("tables", named) if named else None
    if named and target is None:
        fail("ERR_TABLE_NOT_FOUND")
    if target is None:
        target = svc.best_table_for(venue["id"], reservation.get("party_size", 0))
    if target is None or not _table_eligible_for_hold(target, reservation):
        fail("ERR_TABLE_OVER_CAPACITY")
    window_start = db.now()
    window_end = window_start + timedelta(minutes=C.HOLD_WINDOW_MINUTES)
    if svc.table_maintenance_conflict(target["id"], window_start, window_end):
        fail("ERR_MAINTENANCE_CONFLICT")

    reservation = svc.reopen_reservation(reservation, target)
    return ok(db.public(db.get("reservations", reservation["id"])), 200)