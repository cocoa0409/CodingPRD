"""Store access, derived-counter recomputation and the logical clock.

The store itself lives in `core` (a module-level singleton that is empty on
every boot).  This module holds the lookup helpers, the recomputation routines
that keep derived counters honest, and the write helpers every route uses.

Derived counters are re-derived from the underlying records on every event that
touches them (PRD §2.6 / §2.10); none is ever decremented in place.
"""
from core import ApiError, db, now, touch  # noqa: F401  (now/touch re-exported)
from core import paginate  # noqa: F401  (re-exported for the route modules)

# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
NOT_FOUND = {
    "distributors": "ERR_DISTRIBUTOR_NOT_FOUND",
    "circuits": "ERR_CIRCUIT_NOT_FOUND",
    "theaters": "ERR_THEATER_NOT_FOUND",
    "titles": "ERR_TITLE_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "booking_lines": "ERR_LINE_NOT_FOUND",
    "screenings": "ERR_SCREENING_NOT_FOUND",
    "encryption_keys": "ERR_KEY_NOT_FOUND",
    "content_deliveries": "ERR_DELIVERY_NOT_FOUND",
    "encore_windows": "ERR_ENCORE_WINDOW_NOT_FOUND",
    "feed_events": "ERR_FEED_EVENT_NOT_FOUND",
    "settlements": "ERR_SETTLEMENT_NOT_FOUND",
}


def get_or_404(collection, ident):
    row = getattr(db, collection).get(ident)
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def find(collection, ident):
    if ident is None:
        return None
    return getattr(db, collection).get(ident)


def all_rows(collection):
    return list(getattr(db, collection).values())


def require_body_ref(collection, ident, error_id=None):
    """Resolve a body FK; a dangling reference is a hard stop (priority 5)."""
    row = find(collection, ident)
    if row is None:
        raise ApiError(error_id or NOT_FOUND[collection])
    return row


# ---------------------------------------------------------------------------
# Child accessors
# ---------------------------------------------------------------------------
def booking_lines(booking):
    rows = [ln for ln in db.booking_lines.values() if ln["booking_id"] == booking["id"]]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def booking_screenings(booking):
    rows = [s for s in db.screenings.values() if s["booking_id"] == booking["id"]]
    return sorted(rows, key=lambda r: (r["starts_at"], r["created_at"], r["_seq"]))


def line_screenings(line):
    rows = [
        s
        for s in db.screenings.values()
        if s["booking_id"] == line["booking_id"] and s["theater_id"] == line["theater_id"]
    ]
    return sorted(rows, key=lambda r: (r["starts_at"], r["created_at"], r["_seq"]))


def screening_keys(screening):
    rows = [k for k in db.encryption_keys.values() if k["screening_id"] == screening["id"]]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def booking_deliveries(booking):
    rows = [d for d in db.content_deliveries.values() if d["booking_id"] == booking["id"]]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def booking_feed_events(booking):
    rows = [f for f in db.feed_events.values() if f["booking_id"] == booking["id"]]
    return sorted(rows, key=lambda r: (r["detected_at_utc"], r["_seq"]))


def booking_settlements(booking):
    rows = [s for s in db.settlements.values() if s["booking_id"] == booking["id"]]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def line_for_screening(screening):
    booking = find("bookings", screening["booking_id"])
    if booking is None:
        return None
    for line in booking_lines(booking):
        if line["theater_id"] == screening["theater_id"]:
            return line
    return None


def theater_of_line(line):
    return find("theaters", line["theater_id"])


# ---------------------------------------------------------------------------
# Recomputation of derived counters (PRD §2.10)
# ---------------------------------------------------------------------------
def recompute_distributor(distributor):
    distributor["bookable_title_count"] = sum(
        1
        for t in db.titles.values()
        if t["distributor_id"] == distributor["id"] and t["status"] == "BOOKABLE"
    )
    return distributor


def recompute_title(title):
    title["booking_count"] = sum(
        1
        for b in db.bookings.values()
        if b["title_id"] == title["id"] and b["status"] != "TERMINAL"
    )
    return title


def recompute_circuit(circuit):
    total = 0
    for booking in db.bookings.values():
        if booking["circuit_id"] != circuit["id"]:
            continue
        if booking["status"] == "TERMINAL":
            continue
        for line in booking_lines(booking):
            if line["exhibit_state"] == "COMMITTED":
                total += int(line["committed_screens"])
    circuit["committed_screens_balance"] = total
    return circuit


def recompute_booking(booking):
    # The booking-level commitment total carries every line that is still on
    # the table -- PROPOSED as well as COMMITTED -- because the negotiation
    # runs against it: submission must see the minimum screen count met and the
    # guarantee ceiling is derived from it while the booking is still DRAFT or
    # PENDING_APPROVAL.  A RELEASED line no longer contributes.
    booking["committed_screens_total"] = sum(
        int(ln["committed_screens"])
        for ln in booking_lines(booking)
        if ln["exhibit_state"] in ("PROPOSED", "COMMITTED")
    )
    booking["pre_sale_tickets"] = booking.get("_pre_sale_ledger_total", 0)
    booking["live_feed_event_count"] = sum(
        1 for f in booking_feed_events(booking) if f["state"] != "VOIDED"
    )
    booking["makegood_credit_cents"] = sum(
        int(ln["credit_issued_cents"]) for ln in booking_lines(booking)
    )
    return booking


def recompute_line(line):
    line["sold_tickets"] = sum(
        int(s["reported_attendance"] or 0)
        for s in line_screenings(line)
        if s["state"] == "SCREENED"
    )
    return line


def recompute_encore_window(window):
    window["encore_screening_count"] = sum(
        1
        for s in db.screenings.values()
        if s.get("encore_window_id") == window["id"]
    )
    return window


def recompute_line_financials(booking, line):
    """Re-derive one line's guarantee allocation share from scratch."""
    from calcs import guarantee_allocation

    guarantee_allocation(booking, booking_lines(booking))
    return line


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
def refresh(*rows):
    """Stamp a mutation: advance version and updated_at."""
    for row in rows:
        if row is not None:
            touch(row)


def advance_booking(booking):
    """Every booking mutation advances the booking's version (PRD §2.6)."""
    touch(booking)


def cascade_release(booking, states=("PROPOSED", "COMMITTED")):
    """Release this booking's lines in the named exhibit states."""
    for line in booking_lines(booking):
        if line["exhibit_state"] in states:
            line["exhibit_state"] = "RELEASED"
            refresh(line)
    recompute_booking(booking)


def screening_states(booking):
    return booking_screenings(booking)


def scheduled_screenings(booking):
    return [s for s in booking_screenings(booking) if s["state"] == "SCHEDULED"]


def non_void_screenings(booking):
    return [s for s in booking_screenings(booking) if s["state"] != "VOID"]


def set_clock(instant):
    """Set the logical clock; it never falls back to wall-clock time."""
    db.clock = instant
    return db.clock


def current_utc_iso():
    from core import fmt_dt

    return fmt_dt(now())


# ---------------------------------------------------------------------------
# Settlements / reporting helpers
# ---------------------------------------------------------------------------
def line_has_reported(line):
    """A line has reported when every one of its screenings is non-SCHEDULED."""
    screenings = line_screenings(line)
    if not screenings:
        return False
    return all(s["state"] != "SCHEDULED" for s in screenings)


def booking_fully_reported(booking):
    lines = booking_lines(booking)
    if not lines:
        return False
    return all(line_has_reported(ln) for ln in lines)


def line_has_ruined_screening(line, feed_event=None):
    """A ruined screening: SKIPPED_INCOMPLETE, or SCHEDULED behind a CONFIRMED event."""
    for screening in line_screenings(line):
        if screening["state"] == "SKIPPED_INCOMPLETE":
            if feed_event is None:
                return True
            if _event_covers(feed_event, screening):
                return True
        elif screening["state"] == "SCHEDULED":
            events = [
                f
                for f in booking_feed_events_by_id(line["booking_id"])
                if f["state"] == "CONFIRMED"
            ]
            for event in events:
                if event["detected_at_utc"] >= screening["starts_at"]:
                    if feed_event is None or event["id"] == feed_event["id"]:
                        return True
    return False


def booking_feed_events_by_id(booking_id):
    rows = [f for f in db.feed_events.values() if f["booking_id"] == booking_id]
    return sorted(rows, key=lambda r: (r["detected_at_utc"], r["_seq"]))


def _event_covers(event, screening):
    if event.get("screening_id"):
        return event["screening_id"] == screening["id"]
    return event["detected_at_utc"] >= screening["starts_at"] and screening["state"] in (
        "SCHEDULED",
        "SCREENED",
        "SKIPPED_INCOMPLETE",
    )


def screenings_affected_by(booking, event):
    """Screenings that had already started at the detection instant."""
    out = []
    for screening in booking_screenings(booking):
        if screening["state"] not in ("SCHEDULED", "SCREENED", "SKIPPED_INCOMPLETE"):
            continue
        if screening["starts_at"] <= event["detected_at_utc"]:
            out.append(screening)
    return out