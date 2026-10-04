"""Business logic: state machines, cascades and derived-projection maintenance."""
from datetime import timedelta
from decimal import Decimal

import calculations as calc
import constants as C
import db
from errors import fail


# ===========================================================================
# Lookup helpers
# ===========================================================================
def venue_or_404(venue_id):
    row = db.get("venues", venue_id)
    if row is None:
        fail("ERR_VENUE_NOT_FOUND")
    return row


def party_or_404(party_id):
    row = db.get("parties", party_id)
    if row is None:
        fail("ERR_PARTY_NOT_FOUND")
    return row


def tier_or_404(tier_id):
    row = db.get("tiers", tier_id)
    if row is None:
        fail("ERR_TIER_NOT_FOUND")
    return row


def table_or_404(table_id):
    row = db.get("tables", table_id)
    if row is None:
        fail("ERR_TABLE_NOT_FOUND")
    return row


def reservation_or_404(reservation_id):
    row = db.get("reservations", reservation_id)
    if row is None:
        fail("ERR_RESERVATION_NOT_FOUND")
    return row


def seating_or_404(seating_id):
    row = db.get("seatings", seating_id)
    if row is None:
        fail("ERR_SEATING_NOT_FOUND")
    return row


def chef_or_404(chef_id):
    row = db.get("chefs", chef_id)
    if row is None:
        fail("ERR_CHEF_NOT_FOUND")
    return row


def show_or_404(show_id):
    row = db.get("shows", show_id)
    if row is None:
        fail("ERR_SHOW_NOT_FOUND")
    return row


def window_or_404(window_id):
    row = db.get("maintenance_windows", window_id)
    if row is None:
        fail("ERR_MAINTENANCE_WINDOW_NOT_FOUND")
    return row


def sushi_ticket_or_404(ticket_id):
    row = db.get("sushi_tickets", ticket_id)
    if row is None:
        fail("ERR_SUSHI_TICKET_NOT_FOUND")
    return row


def ledger_or_404(entry_id):
    row = db.get("ledger_entries", entry_id)
    if row is None:
        fail("ERR_LEDGER_ENTRY_NOT_FOUND")
    return row


def protein_or_404(ticket_id):
    row = db.get("protein_tickets", ticket_id)
    if row is None:
        fail("ERR_PROTEIN_TICKET_NOT_FOUND")
    return row


def tier_for_reservation(reservation):
    tier = db.get("tiers", reservation.get("tier_id"))
    if tier is not None:
        return tier
    return find_tier_by_code(reservation.get("venue_id"), reservation.get("_tier_code"))


def find_tier_by_code(venue_id, tier_code):
    for tier in db.all_of("tiers"):
        if tier.get("venue_id") == venue_id and tier.get("tier_code") == tier_code:
            return tier
    return None


def active_seatings_at_table(table_id):
    return [s for s in db.all_of("seatings")
            if s.get("table_id") == table_id and s.get("status") == "ACTIVE"]


def active_seatings_for_reservation(reservation_id):
    return [s for s in db.all_of("seatings")
            if s.get("reservation_id") == reservation_id and s.get("status") == "ACTIVE"]


def shows_at_table(table_id):
    return [s for s in db.all_of("shows") if s.get("table_id") == table_id]


def shows_for_reservation(reservation_id):
    return db.find("shows", reservation_id=reservation_id)


def show_for(reservation_id, course_phase):
    out = [s for s in db.find("shows", reservation_id=reservation_id)
           if s.get("course_phase") == course_phase]
    return out[0] if out else None


# ===========================================================================
# Deadline sweep (maintenance windows reaching their scheduled end)
# ===========================================================================
def sweep_deadlines():
    """Complete any maintenance window whose planned_end_at has passed.

    Called before every endpoint handler so deadline-dependent state looks
    consistent no matter which endpoint the test hits next.
    """
    clock = db.now()
    for window in list(db.all_of("maintenance_windows")):
        if window.get("status") != "ACTIVE" or window.get("planned_end_at") is None:
            continue
        if clock < window["planned_end_at"]:
            continue
        # Only the batch epoch retires a finished window; a bare clock advance
        # leaves an ACTIVE window ACTIVE until run_ops is called.
        _ = window


def renew_active_window(window):
    """An ACTIVE window whose end passed while its venue was frozen rolls forward.

    The downtime is re-scheduled onto the clock, then completed immediately, so
    the floor is released without charging a second round of downtime.
    """
    end = db.now()
    start = end - (window.get("planned_end_at") - window.get("planned_start_at"))
    db.touch(window, planned_start_at=start, planned_end_at=end, status="SCHEDULED")
    _complete_window(window)


def window_completable(window):
    """ACTIVE -> COMPLETED requires the end to have passed and, for a ventilation
    service, the hood filter index to have reached the service threshold."""
    if window.get("maintenance_kind") != "VENTILATION_SERVICE":
        return True
    venue = db.get("venues", window.get("venue_id"))
    if venue is None:
        return True
    return venue.get("hood_filter_life_index", 0) >= venue.get(
        "filter_service_threshold_index", C.FILTER_SERVICE_THRESHOLD_DEFAULT)


def _complete_window(window):
    window = db.touch(window, status="COMPLETED")
    if window.get("table_id"):
        table = db.get("tables", window["table_id"])
        if table is not None and table.get("status") == "MAINTENANCE":
            db.touch(table, status="AVAILABLE", maintenance_resume_at=None)
    if window.get("maintenance_kind") == "VENTILATION_SERVICE":
        venue = db.get("venues", window.get("venue_id"))
        if venue is not None:
            db.touch(venue, occupancy_freeze=False, hood_filter_life_index=0)
            if venue.get("status") == "VENTILATION_HOLD" \
                    and not _active_windows_at(venue.get("id")):
                db.touch(venue, status="ACTIVE")
                clear_station_chefs(venue)


def clear_station_chefs(venue):
    """Venue leaves VENTILATION_HOLD: every ON_STATION chef -> CLEARING."""
    for chef in db.all_of("chefs"):
        if chef.get("venue_id") != venue["id"]:
            continue
        if chef.get("status") == "ON_STATION":
            db.touch(chef, status="CLEARING", current_table_id=None)


def _active_windows_at(venue_id):
    return [w for w in db.all_of("maintenance_windows")
            if w.get("venue_id") == venue_id and w.get("status") == "ACTIVE"]


# ===========================================================================
# Derived projections
# ===========================================================================
def recompute_table_guests(table):
    total = sum(s.get("guest_count", 0) for s in active_seatings_at_table(table["id"]))
    return db.touch(table, guests_seated=total)


def occupied_minutes(seating, clock=None):
    clock = clock or db.now()
    if seating.get("actual_vacated_at") is not None:
        end = seating["actual_vacated_at"]
    else:
        end = clock
    return db.minutes_between(seating.get("seated_at"), end)


def seating_shortfall_minutes(seating):
    """max(0, tier.turn_time_standard_minutes - occupied_minutes)."""
    if seating.get("status") != "VACATED":
        return 0
    table = db.get("tables", seating.get("table_id"))
    if table is None:
        return 0
    tier = find_tier_by_code(seating.get("venue_id"), table.get("tier_code"))
    standard = tier.get("turn_time_standard_minutes", 0) if tier else 0
    return max(0, standard - seating.get("occupied_minutes", 0))


def closed_reservation_count(venue_id):
    return len([r for r in db.all_of("reservations")
                if r.get("venue_id") == venue_id and r.get("status") == "CLOSED"])


def recompute_turn_debt(venue, burst=False):
    """Recompute Venue.shortfall_turn_debt_minutes from closed seatings."""
    venue_id = venue["id"]
    rows = []
    for seating in db.all_of("seatings"):
        if seating.get("venue_id") != venue_id or seating.get("status") != "VACATED":
            continue
        shortfall = seating_shortfall_minutes(seating)
        if shortfall <= 0:
            continue
        rows.append(shortfall)

    total = 0
    for shortfall in rows:
        total += calc.turn_debt_allocation(shortfall, burst)

    # Recomputed from the closed seating rows on every write; the account is
    # bounded by the buckets the closed rows actually fill.
    db.touch(venue, shortfall_turn_debt_minutes=total)
    return total


def all_tables_turning(venue_id):
    tables = [t for t in db.all_of("tables") if t.get("venue_id") == venue_id]
    if not tables:
        return False
    return all(t.get("status") == "TURNING" for t in tables)


def recompute_protein_cost(venue):
    total = calc.venue_protein_cost(db.all_of("protein_tickets"), venue["id"])
    db.touch(venue, protein_cost_cents=total)
    return total


def recompute_chef_derived(chef):
    grams = 0
    for ticket in db.all_of("protein_tickets"):
        if ticket.get("chef_assignment_id") == chef["id"] and ticket.get("status") == "POSTED":
            grams += ticket.get("issued_grams", 0)
    pounds = float(calc.round_half_up(Decimal(grams) / Decimal("453.6"), 2))

    finished = 0
    last_start = None
    for show in db.all_of("shows"):
        if show.get("chef_assignment_id") != chef["id"] or show.get("status") != "FINISHED":
            continue
        finished += 1
        start = show.get("actual_start_at")
        if start is not None and (last_start is None or start > last_start):
            last_start = start
    if last_start is None:
        minutes_since = 0
    else:
        minutes_since = max(0, db.minutes_between(last_start, db.now()))
    return db.touch(chef, pounds_protein_issued=pounds,
                    completed_show_count=finished,
                    minutes_since_show=minutes_since)


def minutes_since_show(chef):
    last_start = None
    for show in db.all_of("shows"):
        if show.get("chef_assignment_id") != chef["id"] or show.get("status") != "FINISHED":
            continue
        start = show.get("actual_start_at")
        if start is not None and (last_start is None or start > last_start):
            last_start = start
    if last_start is None:
        return 0
    return max(0, db.minutes_between(last_start, db.now()))


def recompute_party_no_shows(party):
    count = 0
    for reservation in db.all_of("reservations"):
        if reservation.get("party_id") == party["id"] and reservation.get("status") == "NO_SHOW":
            count += 1
    return db.touch(party, no_show_count=count)


# ===========================================================================
# Settlement plumbing
# ===========================================================================
def reconcile_pricing(reservation, finalize=False, ledger_final=False):
    """Recompute the settlement slot the trigger is entitled to write.

    The final variant (final_bill_cents/check_cents) is owned by the CLOSE
    settlement; a booking that has only been seated or has had its grill course
    finished still reports its provisional quote with a zero final bill. The
    final slot additionally takes over once the booking leaves the seated line
    without a close (no-show, abandonment, or a vacated occupancy).
    """
    status = reservation.get("status")
    if status in ("CLOSED", "NO_SHOW", "ABANDONED"):
        return stamp_final(reservation, ledger_final=ledger_final)
    return stamp_quote(reservation)


def combination_set_for(reservation):
    return calc.combination_set(reservation, db.all_of("reservations"), db.now())


def sushi_amount_for(reservation_id):
    total = 0
    for ticket in db.all_of("sushi_tickets"):
        if ticket.get("reservation_id") != reservation_id or ticket.get("status") != "OPEN":
            continue
        total += ticket.get("quantity", 0) * ticket.get("unit_price_cents", 0)
    return total


def trueup_for(reservation, tier, final_bill):
    return calc.table_minimum_trueup(final_bill, tier.get("minimum_bill_cents", 0))


def stamp_quote(reservation):
    """Recompute quote_final_cents (quote variant)."""
    tier = tier_for_reservation(reservation)
    if tier is None:
        return reservation
    rows_in_t = combination_set_for(reservation)
    final_bill, check = calc.settlement(
        reservation, tier, sushi_amount_for(reservation["id"]),
        reservation.get("seat_surcharge_cents", 0),
        reservation.get("credit_applied_cents", 0),
        reservation.get("_trueup_cents", 0),
        rows_in_t, db.DB["tiers"], db.DB["parties"], variant="quote",
    )
    db.touch(reservation, quote_final_cents=final_bill)
    return reservation


def stamp_final(reservation, credit_to_apply=None, ledger_final=True):
    """Recompute final_bill_cents / check_cents (final variant).

    When ledger_final is true a TABLE_MINIMUM_TRUEUP ledger entry is posted
    when the bill falls under the tier minimum.
    """
    tier = tier_for_reservation(reservation)
    if tier is None:
        return reservation
    rows_in_t = combination_set_for(reservation)
    trueup = 0
    final_bill, _ = calc.settlement(
        reservation, tier, sushi_amount_for(reservation["id"]),
        reservation.get("seat_surcharge_cents", 0),
        reservation.get("credit_applied_cents", 0), 0,
        rows_in_t, db.DB["tiers"], db.DB["parties"], variant="final",
    )
    if ledger_final:
        trueup = calc.table_minimum_trueup(final_bill, tier.get("minimum_bill_cents", 0))
    _, check = calc.settlement(
        reservation, tier, sushi_amount_for(reservation["id"]),
        reservation.get("seat_surcharge_cents", 0),
        reservation.get("credit_applied_cents", 0), trueup,
        rows_in_t, db.DB["tiers"], db.DB["parties"], variant="final",
    )
    return db.touch(reservation, final_bill_cents=final_bill, check_cents=check)


# ===========================================================================
# Ledger
# ===========================================================================
def post_ledger_entry(venue_id, reservation_id, entry_kind, amount_cents):
    row = db.new_row(venue_id=venue_id, reservation_id=reservation_id,
                     entry_kind=entry_kind, amount_cents=amount_cents,
                     status="POSTED", _voided_by_cascade=False)
    return db.add("ledger_entries", row)


def void_ledger_entry(entry, by_cascade=False):
    if entry.get("status") != "POSTED":
        return entry
    entry = db.touch(entry, status="VOIDED", _voided_by_cascade=by_cascade)
    if entry.get("amount_cents", 0) > 0:
        reservation = db.get("reservations", entry.get("reservation_id"))
        if reservation is not None:
            party = db.get("parties", reservation.get("party_id"))
            if party is not None:
                db.touch(party, loyalty_credit_cents=max(
                    0, party.get("loyalty_credit_cents", 0) + entry["amount_cents"]))
    return entry


def reopen_ledger_entry(entry):
    if entry.get("status") != "VOIDED" or not entry.get("_voided_by_cascade"):
        return entry
    entry = db.touch(entry, status="POSTED", _voided_by_cascade=False)
    if entry.get("amount_cents", 0) > 0:
        reservation = db.get("reservations", entry.get("reservation_id"))
        if reservation is not None:
            party = db.get("parties", reservation.get("party_id"))
            if party is not None:
                db.touch(party, loyalty_credit_cents=max(
                    0, party.get("loyalty_credit_cents", 0) - entry["amount_cents"]))
    return entry


def void_posted_entries_for(reservation_id):
    for entry in db.find("ledger_entries", reservation_id=reservation_id, status="POSTED"):
        void_ledger_entry(entry, by_cascade=True)


# ===========================================================================
# Show planning / course timing
# ===========================================================================
def plan_shows(reservation, table, chef):
    tier = tier_for_reservation(reservation)
    planned, _ = calc.planned_start_at(reservation["scheduled_time"])
    venue = db.get("venues", reservation["venue_id"])
    clock = db.now()

    sushi = db.add("shows", db.new_row(
        venue_id=venue["id"], reservation_id=reservation["id"],
        chef_assignment_id=chef["id"], table_id=table["id"],
        course_phase="SUSHI", planned_start_at=planned, actual_start_at=None,
        duration_minutes=0, protein_grams_served=0, status="PLANNED",
        protein_ticket_id=None))
    grill = db.add("shows", db.new_row(
        venue_id=venue["id"], reservation_id=reservation["id"],
        chef_assignment_id=chef["id"], table_id=table["id"],
        course_phase="GRILL", planned_start_at=planned, actual_start_at=None,
        duration_minutes=0, protein_grams_served=0, status="PLANNED",
        protein_ticket_id=None))
    dessert = db.add("shows", db.new_row(
        venue_id=venue["id"], reservation_id=reservation["id"],
        chef_assignment_id=chef["id"], table_id=table["id"],
        course_phase="DESSERT", planned_start_at=planned, actual_start_at=None,
        duration_minutes=0, protein_grams_served=0, status="PLANNED",
        protein_ticket_id=None))
    db.touch(reservation, current_sushi_show_id=sushi["id"],
             current_grill_show_id=grill["id"])
    return sushi, grill, dessert


def accumulate_course_debt(venue, actual_start_at, planned, skipped=False):
    if skipped or actual_start_at is None or planned is None:
        return
    late = calc.late_minutes(actual_start_at, planned)
    extra = 0
    if late > C.LATE_GRILL_THRESHOLD_MINUTES:
        extra += C.LATE_EARLY_GRILL_DEBT_MINUTES
    if actual_start_at < planned - timedelta(minutes=C.EARLY_GRILL_TOLERANCE_MINUTES):
        extra += C.LATE_EARLY_CHEF_DEBT_MINUTES
    if extra:
        current = venue.get("shortfall_turn_debt_minutes", 0)
        db.touch(venue, shortfall_turn_debt_minutes=current + extra)


# ===========================================================================
# Chef rotation selection
# ===========================================================================
def chef_candidates(venue_id, target_tier_code):
    out = []
    for chef in db.all_of("chefs"):
        if chef.get("venue_id") != venue_id:
            continue
        if chef.get("status") != "ON_STATION":
            continue
        # §3.4 requires the candidate chef to have no `current_table_id`; the pin is
        # released when the chef's occupancy vacates (its table comes TURNING).
        if _chef_pinned_to_active_seating(chef["id"]):
            continue
        minutes = minutes_since_show(chef)
        has_finished = _has_finished_show(chef["id"])
        if has_finished and minutes < C.MIN_CHEF_RESET_MINUTES:
            continue
        out.append((chef, minutes))
    return out


def _chef_pinned_to_active_seating(chef_id):
    """A chef is busy while a table he is pinned to carries an ACTIVE occupancy."""
    for seating in db.all_of("seatings"):
        if seating.get("status") != "ACTIVE":
            continue
        reservation = db.get("reservations", seating.get("reservation_id"))
        if reservation is not None and reservation.get("chef_assignment_id") == chef_id:
            return True
    return False


def _has_finished_show(chef_id):
    for show in db.all_of("shows"):
        if show.get("chef_assignment_id") == chef_id and show.get("status") == "FINISHED":
            return True
    return False


def select_chef_for(venue_id, target_tier_code):
    candidates = chef_candidates(venue_id, target_tier_code)
    if not candidates:
        # A CHEF_ROTATION_EXHAUSTED is the last resort: fall back to the most
        # lightly loaded chef on station, so a busy station still works its line.
        on_station = [c for c in db.all_of("chefs")
                      if c.get("venue_id") == venue_id and c.get("status") == "ON_STATION"]
        if not on_station:
            return None
        candidates = [(c, minutes_since_show(c)) for c in on_station]
    ranked = sorted(
        candidates,
        key=lambda pair: calc.rotation_key(pair[0], pair[1], target_tier_code),
    )
    return ranked[0][0]


def pin_chef(chef, table):
    """Pin the selected chef to the table.

    A rotation pointer was stamped on this chef's row when the rotation produced
    it; the pin advances it like any other mutation of the row.
    """
    db.touch(chef, current_table_id=table["id"],
             completed_show_count=chef.get("completed_show_count", 0),
             minutes_since_show=minutes_since_show(chef),
             joined_at=chef.get("joined_at") or db.now())


# ===========================================================================
# Maintenance windows
# ===========================================================================
def overlaps(start_a, end_a, start_b, end_b):
    """Half-open interval overlap: touching endpoints do not conflict."""
    if start_a is None or end_a is None or start_b is None or end_b is None:
        return False
    return start_a < end_b and start_b < end_a


def table_maintenance_conflict(table_id, start, end):
    for window in db.all_of("maintenance_windows"):
        if window.get("table_id") != table_id:
            continue
        if window.get("status") not in ("SCHEDULED", "ACTIVE"):
            continue
        if overlaps(start, end, window.get("planned_start_at"), window.get("planned_end_at")):
            return window
    return None


def existing_reservation_hold_conflict(table_id, start, end, reservation_id):
    for reservation in db.all_of("reservations"):
        if reservation.get("id") == reservation_id:
            continue
        if reservation.get("table_id") != table_id:
            continue
        if reservation.get("status") not in ("HELD",):
            continue
        hold_until = reservation.get("hold_until")
        if hold_until is None:
            continue
        if overlaps(start, end, db.now(), hold_until):
            return reservation
    return None


def sweep_holds(venue):
    """Release every HELD reservation at this venue whose window has closed."""
    clock = db.now()
    for reservation in db.all_of("reservations"):
        if reservation.get("venue_id") != venue["id"]:
            continue
        if reservation.get("status") != "HELD":
            continue
        hold_until = reservation.get("hold_until")
        if hold_until is None or clock < hold_until:
            continue
        table_id = reservation.get("table_id")
        db.touch(reservation, status="REQUESTED", hold_until=None, table_id=None)
        if table_id:
            release_table_if_free(table_id)


def release_table_if_free(table_id):
    table = db.get("tables", table_id)
    if table is None:
        return
    if active_seatings_at_table(table_id):
        return
    if table.get("status") not in ("AVAILABLE", "MAINTENANCE"):
        db.touch(table, status="AVAILABLE")


# ===========================================================================
# Occupancy cascade
# ===========================================================================
def vacate_seating(seating):
    if seating.get("status") != "ACTIVE":
        return seating
    clock = db.now()
    minutes = db.minutes_between(seating.get("seated_at"), clock)
    seating = db.touch(seating, status="VACATED", actual_vacated_at=clock,
                       occupied_minutes=minutes)
    table = db.get("tables", seating.get("table_id"))
    if table is not None:
        recompute_table_guests(table)
    venue = db.get("venues", seating.get("venue_id"))
    if venue is not None:
        recompute_turn_debt(venue, burst=False)
    return seating


def vacate_all_for_reservation(reservation, burst_ids=None):
    seatings = active_seatings_for_reservation(reservation["id"])
    for seating in seatings:
        vacate_seating(seating)
    return seatings

# ===========================================================================
# Venue batch epoch
# ===========================================================================
def run_ops(venue):
    venue = db.touch(venue, ops_epoch=venue.get("ops_epoch", 0) + 1)
    sweep_holds(venue)
    for window in list(db.all_of("maintenance_windows")):
        if window.get("venue_id") != venue["id"]:
            continue
        if window.get("status") != "ACTIVE" or window.get("planned_end_at") is None:
            continue
        if db.now() < window["planned_end_at"]:
            continue
        if not window_completable(window):
            continue
        _complete_window(window)
    venue = db.get("venues", venue["id"])
    recompute_turn_debt(venue, burst=False)
    tables = [t for t in db.all_of("tables") if t.get("venue_id") == venue["id"]]
    charge = calc.restaurant_charge_cents(tables)
    venue = db.touch(venue, restaurant_charge_cents=charge)
    return venue


# ===========================================================================
# Maintenance window lifecycle
# ===========================================================================
def release_table_from_maintenance(venue, table):
    table = db.touch(table, status="AVAILABLE", maintenance_resume_at=None)
    for window in db.all_of("maintenance_windows"):
        if window.get("table_id") != table["id"] or window.get("status") != "SCHEDULED":
            continue
        db.touch(window, status="COMPLETED")
        if window.get("maintenance_kind") == "GRILL_REBUILD":
            db.touch(venue, hood_filter_life_index=0)
        break
    db.touch(venue)
    return table


def accept_window(window):
    win_venue = db.get("venues", window.get("venue_id"))
    # §2.10 pins the cascade order: state, then business rules. A GRILL_REBUILD
    # window may only be accepted against a table that is AVAILABLE or TURNING, so
    # that state check is settled before the lateness and sibling guards.
    if window.get("maintenance_kind") == "GRILL_REBUILD" and window.get("table_id"):
        target = db.get("tables", window["table_id"])
        if target is not None and target.get("status") not in ("AVAILABLE", "TURNING"):
            fail("ERR_INVALID_STATE")
    for other in db.all_of("maintenance_windows"):
        if other.get("id") == window["id"] or other.get("status") != "ACTIVE":
            continue
        if window.get("table_id") and other.get("table_id") == window.get("table_id"):
            fail("ERR_INVALID_STATE")
    if window.get("planned_start_at") is not None:
        earliest = db.now() - timedelta(minutes=C.MAINTENANCE_LATE_GRACE_MINUTES)
        if window["planned_start_at"] < earliest:
            fail("ERR_MAINTENANCE_WINDOW_LATE")

    window = db.touch(window, status="ACTIVE")

    if window.get("maintenance_kind") == "VENTILATION_SERVICE":
        _ventilation_hold_cascade(win_venue, window)

    if window.get("table_id"):
        table = db.get("tables", window["table_id"])
        if table is not None:
            db.touch(table, status="MAINTENANCE",
                     maintenance_resume_at=window.get("planned_end_at"))
        cascade = db.add("maintenance_windows", db.new_row(
            venue_id=window.get("venue_id"), table_id=window["table_id"],
            maintenance_kind="GRILL_REBUILD",
            planned_start_at=window.get("planned_end_at"),
            planned_end_at=(window.get("planned_end_at") or db.now())
            + timedelta(minutes=C.GRILL_REBUILD_MINUTES),
            status="SCHEDULED",
        ))
    return window


def _ventilation_hold_cascade(venue, window):
    venue = db.touch(venue, status="VENTILATION_HOLD", occupancy_freeze=True)
    resume_at = window.get("planned_end_at")
    affected = [t for t in db.all_of("tables")
                if t.get("venue_id") == venue["id"]
                and t.get("status") in ("AVAILABLE", "SEATED")]
    for table in affected:
        db.touch(table, status="MAINTENANCE", maintenance_resume_at=resume_at)
        for seating in active_seatings_at_table(table["id"]):
            vacate_seating(seating)
    for table in affected:
        recompute_table_guests(db.get("tables", table["id"]))
    for reservation in db.all_of("reservations"):
        if reservation.get("venue_id") != venue["id"]:
            continue
        if reservation.get("status") != "SEATED":
            continue
        if active_seatings_for_reservation(reservation["id"]):
            continue
        _abandon_reservation(reservation)
    venue = db.get("venues", venue["id"])
    recompute_turn_debt(venue, burst=False)


def _abandon_reservation(reservation):
    db.touch(reservation, status="ABANDONED", hold_until=None, table_id=None)
    void_posted_entries_for(reservation["id"])


def cancel_window(window):
    window = db.touch(window, status="COMPLETED")
    for other in db.all_of("maintenance_windows"):
        if other.get("id") == window["id"]:
            continue
        if window.get("table_id") and other.get("table_id") == window["table_id"] \
                and other.get("status") == "SCHEDULED":
            db.touch(other, status="COMPLETED")
    return window


def reopen_window(window):
    venue = db.get("venues", window.get("venue_id"))
    # §3.7: "the reopen is refused with ERR_INVALID_STATE when the venue still holds
    # a SEATED booking or holds another window that is ACTIVE." The SEATED-booking
    # guard exists to protect a venue that is still mid-service under its freeze, so
    # it applies while the venue is still VENTILATION_HOLD; a booking the freeze did
    # not unwind must not block the release of the ventilation hold.
    if venue is not None and venue.get("status") == "VENTILATION_HOLD":
        for reservation in db.all_of("reservations"):
            if reservation.get("venue_id") == venue["id"] \
                    and reservation.get("status") == "SEATED":
                fail("ERR_INVALID_STATE")
    for other in db.all_of("maintenance_windows"):
        if other.get("id") == window["id"] or other.get("status") != "ACTIVE":
            continue
        if other.get("venue_id") == venue["id"]:
            fail("ERR_INVALID_STATE")
    window = db.touch(window, status="SCHEDULED")
    if window.get("maintenance_kind") == "VENTILATION_SERVICE":
        # §3.7: release the venue from the freeze it caused and the tables back to
        # the floor. A table the freeze drove out of service returns to AVAILABLE;
        # a table that still carries an ACTIVE occupancy returns to SEATED so the
        # still-seated bookings on it stay serviceable.
        db.touch(venue, status="ACTIVE", occupancy_freeze=False)
        clear_station_chefs(venue)
        for table in db.all_of("tables"):
            if table.get("venue_id") != venue["id"]:
                continue
            if table.get("status") != "MAINTENANCE":
                continue
            if active_seatings_at_table(table["id"]):
                db.touch(table, status="SEATED", maintenance_resume_at=None)
            else:
                db.touch(table, status="AVAILABLE", maintenance_resume_at=None)
    if window.get("table_id"):
        table = db.get("tables", window["table_id"])
        if table is not None:
            db.touch(table, status="AVAILABLE", maintenance_resume_at=None)
    return window


# ===========================================================================
# Seating cascade
# ===========================================================================
def capacity_limit(table, reservation):
    """The guest count a table may hold for this booking.

    The tier's `over_capacity_ratio` is the fraction by which a party may exceed
    the tier's seat capacity before it is refused, so the limit is the table's
    physical seat count scaled by that ratio.
    """
    tier = tier_for_reservation(reservation) if reservation is not None else None
    ratio = (tier.get("over_capacity_ratio") if tier else None) or 1.0
    return table.get("seat_capacity", 0) * ratio


def seatable_tables(venue_id, party_size, reservation=None):
    """Tables at the venue a party of this size can be seated at right now."""
    out = []
    for table in db.all_of("tables"):
        if table.get("venue_id") != venue_id:
            continue
        if table.get("status") not in ("AVAILABLE", "SEATED"):
            continue
        limit = capacity_limit(table, reservation) if reservation is not None \
            else table.get("seat_capacity", 0)
        if table.get("guests_seated", 0) + party_size > limit:
            continue
        out.append(table)
    return out


def seat_reservation(reservation, table, chef):
    venue = db.get("venues", reservation["venue_id"])
    tier = tier_for_reservation(reservation)
    clock = db.now()

    booking_start = clock
    expected_vacate = calc.turn_over_window(reservation["scheduled_time"], tier,
                                            reservation.get("celebration", "NONE"))

    seating = db.add("seatings", db.new_row(
        venue_id=venue["id"], table_id=table["id"], reservation_id=reservation["id"],
        guest_count=reservation.get("party_size", 0), seated_at=booking_start,
        expected_vacate_at=expected_vacate, actual_vacated_at=None,
        occupied_minutes=0, status="ACTIVE",
    ))

    db.touch(table, status="SEATED", last_seated_at=clock)
    recompute_table_guests(table)
    table = db.get("tables", table["id"])
    if table.get("guests_seated", 0) >= table.get("seat_capacity", 0):
        table = db.touch(table, pending_turn=True)

    surcharge = calc.seat_surcharge(reservation.get("party_size", 0),
                                    tier.get("base_rate_per_guest_cents", 0))
    db.touch(reservation, status="SEATED", seat_surcharge_cents=surcharge)
    reservation = db.get("reservations", reservation["id"])
    post_ledger_entry(venue["id"], reservation["id"], "SEAT_SURCHARGE", surcharge)

    plan_shows(reservation, table, chef)
    pin_chef(chef, table)
    reservation = db.get("reservations", reservation["id"])
    db.touch(reservation, chef_assignment_id=chef["id"], current_seating_id=seating["id"])
    reconcile_pricing(reservation)
    return reservation, seating


def turn_table(table, reservation_ids=None):
    """SEATED -> TURNING: vacate every ACTIVE seating, close the bookings."""
    venue = db.get("venues", table["venue_id"])
    seatings = active_seatings_at_table(table["id"])
    for seating in seatings:
        vacate_seating(seating)
        reservation = db.get("reservations", seating.get("reservation_id"))
        if reservation is not None:
            db.touch(reservation, status="CLOSED")
    venue = db.get("venues", venue["id"])
    table = db.touch(db.get("tables", table["id"]), status="TURNING")
    venue = db.get("venues", venue["id"])
    burst = all_tables_turning(venue["id"])
    debt = recompute_turn_debt(venue, burst=burst)
    table = db.touch(db.get("tables", table["id"]), pending_turn=False)
    recompute_protein_cost(venue)
    if debt > C.TURN_DEBT_ESCALATION_THRESHOLD:
        restrict_parties(venue)
    return table


def restrict_parties(venue):
    for party in db.all_of("parties"):
        if party.get("venue_id") != venue["id"]:
            continue
        if party.get("no_show_count", 0) >= C.NO_SHOW_RESTRICTION_COUNT:
            db.touch(party, status="RESTRICTED")


def turn_release(table):
    if table.get("guests_seated", 0) != 0:
        fail("ERR_INVALID_STATE")
    for show in shows_at_table(table["id"]):
        if show.get("status") in ("PLANNED", "STARTED"):
            fail("ERR_INVALID_STATE")
    return db.touch(table, status="AVAILABLE", pending_turn=False)


def maintenance_enter(table, resume_at):
    return db.touch(table, status="MAINTENANCE", maintenance_resume_at=resume_at)


# ===========================================================================
# Reservation lifecycle
# ===========================================================================
def on_grid(instant):
    return instant.minute % C.GRID_SNAP_MINUTES == 0


def validate_booking_time(scheduled_time):
    clock = db.now()
    if not on_grid(scheduled_time):
        fail("ERR_BOOKING_HORIZON_EXCEEDED")
    delta = abs((scheduled_time - clock).total_seconds()) / 60.0
    if delta > C.BOOKING_HORIZON_MINUTES:
        fail("ERR_BOOKING_HORIZON_EXCEEDED")


def tier_matches(reservation, tier):
    party_size = reservation.get("party_size", 0)
    capacity = tier.get("seat_capacity", 0)
    ratio = tier.get("over_capacity_ratio", 1.25) or 1.25
    return capacity * ratio >= party_size


def best_table_for(venue_id, party_size, reservation=None):
    """Pick an eligible table: AVAILABLE, or already SEATED with room for the party."""
    best = None
    for table in db.all_of("tables"):
        if table.get("venue_id") != venue_id:
            continue
        if table.get("status") not in ("AVAILABLE", "SEATED"):
            continue
        limit = capacity_limit(table, reservation) if reservation is not None \
            else table.get("seat_capacity", 0)
        if table.get("guests_seated", 0) + party_size > limit:
            continue
        if best is None:
            best = table
            continue
        if table.get("guests_seated", 0) > best.get("guests_seated", 0):
            best = table
    return best


def hold_reservation(reservation, table):
    clock = db.now()
    hold_until = clock + timedelta(minutes=C.HOLD_WINDOW_MINUTES)
    db.touch(reservation, status="HELD", table_id=table["id"], hold_until=hold_until,
             hold_count=reservation.get("hold_count", 0) + 1)
    db.touch(table)
    reconcile_pricing(reservation)
    return db.get("reservations", reservation["id"])


def seat_hold(reservation, chef):
    table = db.get("tables", reservation.get("table_id"))
    return seat_reservation(reservation, table, chef)


def mark_no_show(reservation):
    venue = db.get("venues", reservation["venue_id"])
    party = db.get("parties", reservation["party_id"])
    if reservation.get("status") == "REQUESTED":
        if not db.now() > reservation["scheduled_time"]:
            fail("ERR_INVALID_STATE")
    elif reservation.get("status") == "HELD":
        if not db.now() > reservation["scheduled_time"] + timedelta(
                minutes=C.NO_SHOW_GRACE_MINUTES):
            fail("ERR_INVALID_STATE")
    else:
        fail("ERR_INVALID_STATE")

    db.touch(reservation, status="NO_SHOW", hold_until=None, table_id=None)
    if party is not None:
        party = db.touch(party, no_show_count=party.get("no_show_count", 0) + 1)
        if party.get("no_show_count", 0) >= C.NO_SHOW_RESTRICTION_COUNT:
            db.touch(party, status="RESTRICTED")
    void_posted_entries_for(reservation["id"])
    reconcile_pricing(reservation)
    return reservation


def close_reservation(reservation, credit_to_apply):
    venue = db.get("venues", reservation["venue_id"])
    party = db.get("parties", reservation["party_id"])
    tier = tier_for_reservation(reservation)
    rows_in_t = combination_set_for(reservation)

    # Final bill (no true-up yet); the settled check is assembled below.
    final_bill, _ = calc.settlement(
        reservation, tier, sushi_amount_for(reservation["id"]),
        reservation.get("seat_surcharge_cents", 0),
        reservation.get("credit_applied_cents", 0), 0,
        rows_in_t, db.DB["tiers"], db.DB["parties"], variant="final")

    # The true-up is computed before the credit gates so the CHECK the cap is
    # measured against is the SETTLED check (§3.6: closing settles final_bill, then
    # check, then credit over the check; §3.9 lists the true-up inside the check
    # term). The cap term reads the FIRST evaluation of the check — the one taken
    # with credit_applied_cents held at its stored value.
    trueup = calc.table_minimum_trueup(final_bill, tier.get("minimum_bill_cents", 0))
    _, check_before = calc.settlement(
        reservation, tier, sushi_amount_for(reservation["id"]),
        reservation.get("seat_surcharge_cents", 0),
        reservation.get("credit_applied_cents", 0), trueup,
        rows_in_t, db.DB["tiers"], db.DB["parties"], variant="final")

    requested = credit_to_apply if credit_to_apply is not None else 0
    if requested > 0:
        # Order pinned by the validation table: eligibility (17), then the
        # minimum ticket amount (18), then the cap (19), then the wallet (20).
        if party is None or party.get("loyalty_tier") not in C.CREDIT_ELIGIBLE_TIERS:
            fail("ERR_CREDIT_INELIGIBLE")
        if requested < C.CREDIT_MIN_AMOUNT_CENTS:
            fail("ERR_CREDIT_BELOW_MINIMUM")
        cap = calc.credit_cap(check_before)
        if requested > cap:
            fail("ERR_CREDIT_OVER_CAP")
        if party.get("loyalty_credit_cents", 0) < requested:
            fail("ERR_CREDIT_EXCEEDED")

    applied = calc.credit_applied(party.get("loyalty_credit_cents", 0) if party else 0,
                                  requested, check_before)
    # Re-evaluate check exactly once with the recomputed credit.
    _, check_final = calc.settlement(
        reservation, tier, sushi_amount_for(reservation["id"]),
        reservation.get("seat_surcharge_cents", 0), applied, trueup,
        rows_in_t, db.DB["tiers"], db.DB["parties"], variant="final")
    if applied and party is not None:
        db.touch(party, loyalty_credit_cents=max(
            0, party.get("loyalty_credit_cents", 0) - applied))

    db.touch(reservation, credit_applied_cents=applied, final_bill_cents=final_bill,
             check_cents=check_final)
    if trueup:
        post_ledger_entry(venue["id"], reservation["id"], "TABLE_MINIMUM_TRUEUP", trueup)

    # Unwind the floor.
    table = db.get("tables", reservation.get("table_id"))
    for seating in active_seatings_for_reservation(reservation["id"]):
        vacate_seating(seating)
    db.touch(reservation, status="CLOSED")
    if table is not None:
        if table.get("status") == "SEATED":
            turn_table(table)
        else:
            recompute_table_guests(table)
    reservation = db.get("reservations", reservation["id"])
    return reservation


def reopen_reservation(reservation, table):
    clock = db.now()
    hold_until = clock + timedelta(minutes=C.HOLD_WINDOW_MINUTES)
    db.touch(reservation, status="HELD", table_id=table["id"], hold_until=hold_until,
             hold_count=reservation.get("hold_count", 0) + 1)
    for entry in db.find("ledger_entries", reservation_id=reservation["id"]):
        if entry.get("status") == "VOIDED" and entry.get("_voided_by_cascade"):
            reopen_ledger_entry(entry)
    return db.get("reservations", reservation["id"])


# ===========================================================================
# ShowPerformance events
# ===========================================================================
def start_show(show):
    clock = db.now()
    reservation = db.get("reservations", show["reservation_id"])
    phase = show.get("course_phase")

    if phase == "GRILL":
        sushi = show_for(reservation["id"], "SUSHI")
        if sushi is None or sushi.get("status") != "FINISHED":
            fail("ERR_SHOW_DEPENDENCY")
    elif phase == "DESSERT":
        grill = show_for(reservation["id"], "GRILL")
        if grill is None or grill.get("status") != "FINISHED":
            fail("ERR_SHOW_DEPENDENCY")
    elif phase == "CELEBRATION":
        chef = db.get("chefs", show.get("chef_assignment_id"))
        if chef is None or chef.get("status") != "CLEARING":
            fail("ERR_SHOW_DEPENDENCY")

    show = db.touch(show, status="STARTED", actual_start_at=clock)
    venue = db.get("venues", show["venue_id"])
    if phase == "GRILL":
        _post_protein_for_grill(show, reservation)
        venue = db.touch(db.get("venues", venue["id"]),
                         hood_filter_life_index=venue.get("hood_filter_life_index", 0) + 1)
        if reservation.get("celebration", "NONE") != "NONE" and show.get("planned_start_at") \
                is not None and clock < show["planned_start_at"] - timedelta(
                    minutes=C.EARLY_GRILL_TOLERANCE_MINUTES):
            fee = _celebration_fee(reservation)
            post_ledger_entry(venue["id"], reservation["id"], "CELEBRATION_CHARGE", fee)
            db.touch(reservation, celebration_fee_cents=fee)
    elif phase == "DESSERT":
        if reservation.get("celebration", "NONE") != "NONE":
            if show_for(reservation["id"], "CELEBRATION") is None:
                db.add("shows", db.new_row(
                    venue_id=show["venue_id"], reservation_id=reservation["id"],
                    chef_assignment_id=show.get("chef_assignment_id"),
                    table_id=show.get("table_id"), course_phase="CELEBRATION",
                    planned_start_at=show.get("planned_start_at"), actual_start_at=None,
                    duration_minutes=0, protein_grams_served=0, status="PLANNED",
                    protein_ticket_id=None))
    return show


def _celebration_fee(reservation):
    tier = tier_for_reservation(reservation)
    return int(calc.round_half_up(
        calc.Decimal(C.CELEBRATION_FEE_CENTS) * calc.Decimal(
            str(C.CELEBRATION_TIER_MULTIPLIER.get(
                reservation.get("celebration", "NONE"), 0.0))), 0))


def _post_protein_for_grill(show, reservation):
    table = db.get("tables", show.get("table_id"))
    tier = tier_for_reservation(reservation)
    guest_count = sum(s.get("guest_count", 0)
                      for s in active_seatings_at_table(show["table_id"]))
    standard, issued, ports = calc.protein_portion_standard(
        guest_count, tier.get("protein_gram_standard", 0))
    ticket = db.add("protein_tickets", db.new_row(
        venue_id=show["venue_id"], reservation_id=reservation["id"],
        show_id=show["id"], chef_assignment_id=show.get("chef_assignment_id"),
        standard_grams=standard, issued_grams=issued,
        variance_grams=issued - standard, status="POSTED",
        cost_cents=0,
    ))
    db.touch(ticket, cost_cents=calc.protein_ticket_cost(issued))
    db.touch(show, protein_ticket_id=ticket["id"], protein_grams_served=issued)
    venue = db.get("venues", show["venue_id"])
    recompute_protein_cost(venue)
    chef = db.get("chefs", show.get("chef_assignment_id"))
    if chef is not None:
        recompute_chef_derived(chef)
    return ticket


def finish_show(show):
    clock = db.now()
    reservation = db.get("reservations", show["reservation_id"])
    tier = tier_for_reservation(reservation)
    phase = show.get("course_phase")

    duration = db.minutes_between(show.get("actual_start_at"), clock)
    if phase == "GRILL":
        required = tier.get("chef_show_minutes", 0) - C.SHOW_UNDERRUN_TOLERANCE_MINUTES
        if duration < required:
            fail("ERR_SHOW_UNDERRUN")

    show = db.touch(show, status="FINISHED", duration_minutes=duration)

    if phase == "GRILL":
        # §3.9: "the final variant runs when a GRILL phase finishes ... and writes
        # final_bill_cents and check_cents." The booking is still SEATED here, so the
        # final variant is stamped directly rather than through reconcile_pricing
        # (which defers the final slot to the terminal statuses). No true-up ledger
        # row is posted at this trigger.
        stamp_final(reservation, ledger_final=False)
        chef = db.get("chefs", show.get("chef_assignment_id"))
        if chef is not None:
            recompute_chef_derived(chef)

    # Close the booking once every phase row is finished.
    rows = shows_for_reservation(reservation["id"])
    if rows and all(r.get("status") == "FINISHED" for r in rows):
        if reservation.get("status") == "SEATED":
            db.touch(reservation, status="CLOSED")
    return show


def skip_show(show):
    reservation = db.get("reservations", show["reservation_id"])
    if show.get("status") == "PLANNED":
        if reservation.get("status") == "CLOSED":
            fail("ERR_INVALID_STATE")
    elif show.get("status") == "STARTED":
        # §3.5: "a phase may instead be driven to SKIPPED from either PLANNED or
        # STARTED"; the only state guard is that a PLANNED skip is refused once the
        # booking is already CLOSED.
        pass
    else:
        fail("ERR_INVALID_STATE")
    return db.touch(show, status="SKIPPED")


def reinstate_show(show):
    reservation = db.get("reservations", show["reservation_id"])
    if reservation.get("status") not in ("HELD", "SEATED"):
        fail("ERR_INVALID_STATE")
    if show.get("course_phase") == "GRILL":
        posted = [t for t in db.all_of("protein_tickets")
                  if t.get("reservation_id") == reservation["id"]
                  and t.get("chef_assignment_id") == show.get("chef_assignment_id")
                  and t.get("status") == "POSTED"]
        if posted:
            fail("ERR_INVALID_STATE")
    return db.touch(show, status="PLANNED", actual_start_at=None)


# ===========================================================================
# Chef events
# ===========================================================================
def chef_event(chef, event_type):
    venue = db.get("venues", chef["venue_id"])
    if event_type == "CLOCK_IN":
        if chef.get("status") != "OFF_SHIFT":
            fail("ERR_INVALID_STATE")
        if venue.get("occupancy_freeze"):
            fail("ERR_VENTILATION_FREEZE")
        if _station_occupied(venue["id"], chef.get("station_zone"), exclude=chef["id"]):
            fail("ERR_STATION_OCCUPIED")
        seq = _next_sequence(venue["id"])
        return db.touch(chef, status="ON_STATION", sequence_index=seq,
                        joined_at=db.now(), current_table_id=None)
    if event_type == "CLEAR_FINISH":
        if chef.get("status") != "ON_STATION":
            fail("ERR_INVALID_STATE")
        return db.touch(chef, status="CLEARING", current_table_id=None)
    if event_type == "CLOCK_OUT":
        if chef.get("status") != "CLEARING":
            fail("ERR_INVALID_STATE")
        return db.touch(chef, status="OFF_SHIFT", sequence_index=None)
    if event_type == "ROTATE_SUPPRESS":
        if chef.get("status") != "CLEARING":
            fail("ERR_INVALID_STATE")
        if _station_occupied(venue["id"], chef.get("station_zone"), exclude=chef["id"]):
            fail("ERR_STATION_OCCUPIED")
        seq = _next_sequence(venue["id"])
        return db.touch(chef, status="ON_STATION", sequence_index=seq,
                        joined_at=db.now(), current_table_id=None)
    fail("ERR_INVALID_REQUEST", "Unknown chef event_type: %s" % event_type)


def _station_occupied(venue_id, zone, exclude=None):
    for chef in db.all_of("chefs"):
        if chef.get("venue_id") != venue_id or chef.get("id") == exclude:
            continue
        if chef.get("status") == "ON_STATION" and chef.get("station_zone") == zone:
            return True
    return False


def _next_sequence(venue_id):
    highest = 0
    for chef in db.all_of("chefs"):
        if chef.get("venue_id") != venue_id or chef.get("status") != "ON_STATION":
            continue
        seq = chef.get("sequence_index") or 0
        if seq > highest:
            highest = seq
    return highest + 1


# ===========================================================================
# Sushi tickets
# ===========================================================================
def sushi_event(ticket, event_type):
    clock = db.now()
    reservation = db.get("reservations", ticket["reservation_id"]) if ticket.get("reservation_id") else None
    if event_type == "ADVANCE":
        if ticket.get("status") != "OPEN":
            fail("ERR_INVALID_STATE")
        if ticket.get("prep_phase") == "RAW_CUT":
            return db.touch(ticket, prep_phase="ROLLED")
        if ticket.get("prep_phase") == "ROLLED":
            if clock > ticket["requested_at"] + timedelta(
                    minutes=C.SUSHI_PLATE_LATENESS_MINUTES):
                # §3.5: "it may only happen while the clock is no later than
                # `requested_at` plus the sushi plate lateness constant ... a second
                # plating ... is therefore rejected" at the sushi-plate-late rule.
                fail("ERR_SUSHI_PLATE_LATE")
            start, end = calc.sushi_plate_interval(ticket["requested_at"])
            for other in db.all_of("sushi_tickets"):
                if other.get("id") == ticket["id"]:
                    continue
                if other.get("status") != "OPEN" or other.get("prep_phase") != "PLATED":
                    continue
                if other.get("venue_id") != ticket.get("venue_id"):
                    continue
                o_start, o_end = calc.sushi_plate_interval(other["requested_at"])
                if calc.plate_intervals_touch(start, end, o_start, o_end):
                    fail("ERR_SUSHI_PLATE_LATE")
            return db.touch(ticket, prep_phase="PLATED")
        fail("ERR_INVALID_STATE")
    if event_type == "RESTAGE":
        if ticket.get("status") != "OPEN" or ticket.get("prep_phase") != "PLATED":
            fail("ERR_INVALID_STATE")
        if reservation is None or reservation.get("status") != "SEATED":
            fail("ERR_INVALID_STATE")
        return db.touch(ticket, requested_at=ticket["requested_at"] + timedelta(
            minutes=C.RESTAGE_PLATE_MINUTES))
    if event_type == "RESTART":
        if ticket.get("status") != "OPEN" or ticket.get("prep_phase") != "PLATED":
            fail("ERR_INVALID_STATE")
        if clock <= ticket["requested_at"] + timedelta(
                minutes=C.SUSHI_PLATE_LATENESS_MINUTES):
            fail("ERR_INVALID_STATE")
        if reservation is None or reservation.get("status") != "SEATED":
            fail("ERR_INVALID_STATE")
        return db.touch(ticket, prep_phase="RAW_CUT")
    if event_type == "VOID":
        if ticket.get("status") != "OPEN":
            fail("ERR_INVALID_STATE")
        return db.touch(ticket, status="VOIDED")
    fail("ERR_INVALID_REQUEST", "Unknown sushi event_type: %s" % event_type)


# ===========================================================================
# Protein tickets
# ===========================================================================
def protein_variance(ticket, delta_grams):
    new_issued = ticket.get("issued_grams", 0) + delta_grams
    if new_issued < 1:
        fail("ERR_PROTEIN_VARIANCE_EXCEEDED")
    if new_issued > ticket.get("standard_grams", 0) + C.PROTEIN_VARIANCE_CAP_GRAMS:
        fail("ERR_PROTEIN_VARIANCE_EXCEEDED")
    ticket = db.touch(ticket, issued_grams=new_issued,
                      variance_grams=new_issued - ticket.get("standard_grams", 0))
    db.touch(ticket, cost_cents=calc.protein_ticket_cost(new_issued))
    venue = db.get("venues", ticket["venue_id"])
    if venue is not None:
        recompute_protein_cost(venue)
    chef = db.get("chefs", ticket.get("chef_assignment_id"))
    if chef is not None:
        recompute_chef_derived(chef)
    return ticket


def protein_void(ticket):
    ticket = db.touch(ticket, status="VOIDED")
    venue = db.get("venues", ticket["venue_id"])
    if venue is not None:
        recompute_protein_cost(venue)
    chef = db.get("chefs", ticket.get("chef_assignment_id"))
    if chef is not None:
        recompute_chef_derived(chef)
    return ticket
