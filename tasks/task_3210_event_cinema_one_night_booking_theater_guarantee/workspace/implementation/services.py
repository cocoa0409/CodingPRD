"""Cascades, screen synthesis and the catalogue-side workflows.

Holds the pieces shared by every workflow module: the key-revocation cascade,
screen synthesis from a showtime plan, auditorium occupancy validation, and the
lifecycle operations for Distributors, Circuits, Theaters and Titles.

Every cascade in this module is applied atomically inside the request that
triggered it (PRD §2.12) -- nothing is deferred.
"""
from datetime import timedelta

from core import (
    ApiError,
    TITLE_TERMINAL,
    add_hours,
    db,
    dump,
    new_row,
    now,
    touch,
)
from store import (
    booking_lines,
    booking_screenings,
    find,
    get_or_404,
    recompute_booking,
    recompute_circuit,
    recompute_distributor,
    recompute_title,
    screening_keys,
)

IN_FLIGHT_BOOKING_STATES = ("PENDING_APPROVAL", "COUNTERED", "APPROVED")


# ---------------------------------------------------------------------------
# Customer-order-independent small helpers
# ---------------------------------------------------------------------------
def require_not_terminal(row, terminal, error_id="ERR_ALREADY_TERMINAL"):
    if row.get("status") in terminal or row.get("state") in terminal:
        raise ApiError(error_id)


def state_of(row):
    return row.get("status") or row.get("state")


def revoke_screening_keys(screening, reason):
    """Revoke every key bound to a screening; bump the venue's rekey backlog."""
    theater = find("theaters", screening["theater_id"])
    revoked = 0
    for key in screening_keys(screening):
        if key["issuance_status"] == "REVOKED":
            continue
        key["issuance_status"] = "REVOKED"
        key["revocation_reason"] = reason
        touch(key)
        revoked += 1
        if theater is not None:
            theater["pending_rekey_count"] = int(theater.get("pending_rekey_count", 0)) + 1
            touch(theater)
    return revoked


def release_lines(booking, states=("PROPOSED", "COMMITTED")):
    """Move this booking's lines in `states` to RELEASED."""
    for line in booking_lines(booking):
        if line["exhibit_state"] in states:
            line["exhibit_state"] = "RELEASED"
            touch(line)
    recompute_booking(booking)


def kill_screenings(booking, new_state, reason="CONTENT_FAILURE"):
    """Move SCHEDULED screenings to `new_state` and revoke their keys."""
    moved = 0
    for screening in booking_book_screenings(booking):
        if screening["state"] != "SCHEDULED":
            continue
        screening["state"] = new_state
        touch(screening)
        moved += 1
        revoke_screening_keys(screening, reason)
    return moved


def booking_book_screenings(booking):
    return booking_screenings(booking)


def recompute_circuit_for(booking):
    circuit = find("circuits", booking["circuit_id"])
    if circuit is not None:
        recompute_circuit(circuit)
        touch(circuit)


def unwind_booking(booking, screening_state, release_states=("PROPOSED", "COMMITTED")):
    """Cancel a booking: set status, release lines, kill screenings, recompute."""
    booking["status"] = "CANCELLED"
    touch(booking)
    release_lines(booking, release_states)
    kill_screenings(booking, screening_state)
    recompute_circuit_for(booking)
    recompute_booking(booking)
    recompute_title(find("titles", booking["title_id"]))
    return booking


# ---------------------------------------------------------------------------
# Screen synthesis and occupancy
# ---------------------------------------------------------------------------
def plan_candidates(booking):
    """Resolve the showtime plan into concrete (auditorium, start, end) tuples."""
    plan = sorted(booking["showtime_plan"], key=lambda e: e["index"])
    for element in plan:
        date = element["date_utc"]
        start = date + timedelta(minutes=int(element["start_minute_utc"]))
        yield element["auditorium"], start


def synthesize_screenings(booking, line, title):
    """One Screening per showtime-plan element for this line, state SCHEDULED."""
    created = []
    for auditorium, starts_at in plan_candidates(booking):
        ends_at = starts_at + timedelta(minutes=int(title["duration_minutes"]))
        screening = new_row(
            "Screening",
            booking_id=booking["id"],
            theater_id=line["theater_id"],
            auditorium=auditorium,
            starts_at=starts_at,
            ends_at=ends_at,
            state="SCHEDULED",
            is_encore=False,
            reported_attendance=None,
            encore_window_id=None,
        )
        db.screenings[screening["id"]] = screening
        created.append(screening)
    return created


def candidate_intervals(booking, line, title):
    out = []
    for auditorium, starts_at in plan_candidates(booking):
        out.append((auditorium, starts_at, starts_at + timedelta(minutes=int(title["duration_minutes"]))))
    return out


def validate_occupancy(booking, theater_id, intervals, exclude_booking_id=None):
    """Auditorium occupancy: direct overlap (live bookings) and venue buffer.

    `intervals` is a list of (auditorium, starts_at, ends_at) candidates.
    `exclude_booking_id` suppresses the calling booking's own already-persisted
    screenings, which a re-validation of its own plan would otherwise collide
    with.  A brand-new screening attached directly is a separate record, so it
    is validated against every existing scheduled screening.
    """
    theater = get_or_404("theaters", theater_id)
    buffer_minutes = int(theater["showtime_buffer_minutes"])
    existing = [
        s
        for s in db.screenings.values()
        if s["theater_id"] == theater_id
        and s["state"] == "SCHEDULED"
        and not (exclude_booking_id is not None and s["booking_id"] == exclude_booking_id)
    ]

    for _aud, cand_start, cand_end in intervals:
        for other in existing:
            other_booking = find("bookings", other["booking_id"])
            if other_booking is not None and other_booking["status"] in ("ON_SALE", "CONFIRMED"):
                if cand_start < other["ends_at"] and cand_end > other["starts_at"]:
                    raise ApiError("ERR_SCREEN_OVERLAP_CONFLICT")
        for other in existing:
            other_buffered_end = other["ends_at"] + timedelta(minutes=buffer_minutes)
            cand_buffered_end = cand_end + timedelta(minutes=buffer_minutes)
            if cand_start < other_buffered_end and cand_buffered_end > other["starts_at"]:
                raise ApiError("ERR_SCREEN_BUFFER_CONFLICT")


# ---------------------------------------------------------------------------
# Distributor workflows
# ---------------------------------------------------------------------------
def distributor_view(row):
    return dump(row)


def suspend_distributor(row):
    row["status"] = "SUSPENDED"
    touch(row)
    return row


def reactivate_distributor(row):
    row["status"] = "ACTIVE"
    touch(row)
    return row


# ---------------------------------------------------------------------------
# Circuit workflows
# ---------------------------------------------------------------------------
def accredit_circuit(row):
    if int(row["screen_pool_total"]) < 1:
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "ACCREDITED"
    touch(row)
    return row


def suspend_circuit(row):
    if any(
        b["circuit_id"] == row["id"] and b["status"] == "ON_HOLD"
        for b in db.bookings.values()
    ):
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "SUSPENDED"
    touch(row)
    for booking in list(db.bookings.values()):
        if booking["circuit_id"] != row["id"]:
            continue
        if booking["status"] not in ("DRAFT",) + IN_FLIGHT_BOOKING_STATES:
            continue
        booking["status"] = "CANCELLED"
        touch(booking)
        release_lines(booking, ("PROPOSED", "COMMITTED"))
        recompute_booking(booking)
    recompute_circuit(row)
    touch(row)
    return row


# ---------------------------------------------------------------------------
# Theater workflows
# ---------------------------------------------------------------------------
def go_dark(theater):
    theater["status"] = "DARK"
    touch(theater)
    for screening in list(db.screenings.values()):
        if screening["theater_id"] != theater["id"]:
            continue
        if screening["state"] != "SCHEDULED":
            continue
        screening["state"] = "SKIPPED_CANCELLED"
        touch(screening)
        revoke_screening_keys(screening, "CONTENT_FAILURE")
        booking = find("bookings", screening["booking_id"])
        if booking is None:
            continue
        recompute_booking(booking)
        recompute_circuit_for(booking)
    touch(theater)
    return theater


def rekey(theater):
    theater["pending_rekey_count"] = 0
    touch(theater)
    return theater


# ---------------------------------------------------------------------------
# Title workflows
# ---------------------------------------------------------------------------
def cascade_title_in_flight(title):
    """The four-hop cascade shared by withdrawal and rights expiry."""
    cancelled = 0
    for booking in list(db.bookings.values()):
        if booking["title_id"] != title["id"]:
            continue
        if booking["status"] not in IN_FLIGHT_BOOKING_STATES:
            continue
        unwind_booking(booking, "SKIPPED_CANCELLED")
        cancelled += 1
    return cancelled


def evaluate_title_expiry(title):
    """System BOOKABLE/CLEARED -> RIGHTS_EXPIRED observed on any touch."""
    if title is None:
        return False
    if title["status"] not in ("BOOKABLE", "CLEARED"):
        return False
    if now() < title["rights_end_utc"]:
        return False
    title["status"] = "RIGHTS_EXPIRED"
    touch(title)
    cascade_title_in_flight(title)
    recompute_distributor(find("distributors", title["distributor_id"]))
    return True


def touch_title(title):
    evaluate_title_expiry(title)
    return title


def publish_title(title):
    distributor = get_or_404("distributors", title["distributor_id"])
    if now() >= title["rights_end_utc"]:
        raise ApiError("ERR_RIGHTS_EXPIRED")
    if len(title["territory_state_codes"]) == 0:
        raise ApiError("ERR_INVALID_STATE")
    if distributor["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    title["status"] = "BOOKABLE"
    touch(title)
    recompute_distributor(distributor)
    touch(distributor)
    return title


def unpublish_title(title):
    recompute_title(title)
    if int(title["booking_count"]) != 0:
        raise ApiError("ERR_INVALID_STATE")
    title["status"] = "DRAFT"
    touch(title)
    distributor = find("distributors", title["distributor_id"])
    if distributor is not None:
        recompute_distributor(distributor)
        touch(distributor)
    return title


def clear_title(title):
    recompute_title(title)
    if int(title["booking_count"]) < 1:
        raise ApiError("ERR_INVALID_STATE")
    title["status"] = "CLEARED"
    touch(title)
    return title


def reopen_title_bookings(title):
    if now() >= title["rights_end_utc"]:
        raise ApiError("ERR_RIGHTS_EXPIRED")
    title["status"] = "BOOKABLE"
    touch(title)
    distributor = find("distributors", title["distributor_id"])
    if distributor is not None:
        recompute_distributor(distributor)
        touch(distributor)
    return title


def withdraw_title(title):
    for booking in db.bookings.values():
        if booking["title_id"] != title["id"]:
            continue
        if booking["status"] in ("ON_SALE", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE")
    title["status"] = "WITHDRAWN"
    touch(title)
    cascade_title_in_flight(title)
    distributor = find("distributors", title["distributor_id"])
    if distributor is not None:
        recompute_distributor(distributor)
        touch(distributor)
    return title


def archive_title(title):
    recompute_title(title)
    if int(title["booking_count"]) != 0:
        raise ApiError("ERR_INVALID_STATE")
    title["status"] = "ARCHIVED"
    touch(title)
    distributor = find("distributors", title["distributor_id"])
    if distributor is not None:
        recompute_distributor(distributor)
        touch(distributor)
    return title


def title_is_amendable(title):
    if title["status"] in TITLE_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")


def territory_allows(title, theater):
    return theater["state_code"] in (title["territory_state_codes"] or [])


# ---------------------------------------------------------------------------
# Operational sweeps
# ---------------------------------------------------------------------------
def rights_expiry_sweep():
    expired = 0
    cancelled = 0
    for title in list(db.titles.values()):
        if title["status"] not in ("BOOKABLE", "CLEARED"):
            continue
        if now() < title["rights_end_utc"]:
            continue
        before = sum(
            1
            for b in db.bookings.values()
            if b["title_id"] == title["id"] and b["status"] in IN_FLIGHT_BOOKING_STATES
        )
        title["status"] = "RIGHTS_EXPIRED"
        touch(title)
        cascade_title_in_flight(title)
        expired += 1
        cancelled += before
        distributor = find("distributors", title["distributor_id"])
        if distributor is not None:
            recompute_distributor(distributor)
            touch(distributor)
    return expired, cancelled


def delivery_lead_hours(method, is_live):
    lead = {"SATELLITE": 48, "FILE": 24, "BOTH": 48}.get(method, 24)
    if is_live:
        lead += 12
    return lead


def earliest_scheduled_start(booking):
    starts = [
        s["starts_at"]
        for s in booking_screenings(booking)
        if s["state"] == "SCHEDULED"
    ]
    return min(starts) if starts else None


def delivery_ok(booking, delivery, title):
    earliest = earliest_scheduled_start(booking)
    if earliest is None:
        return False
    lead = delivery_lead_hours(delivery["delivery_method"], bool(title["is_live"]))
    return add_hours(delivery["scheduled_delivery_utc"], lead) <= earliest