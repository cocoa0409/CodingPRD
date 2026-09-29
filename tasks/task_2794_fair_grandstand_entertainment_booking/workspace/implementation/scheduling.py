"""Calendar and stage-occupation gates (PRD sections 3.2, 3.6, 3.9).

The gates are evaluated in the pinned order curfew, stage slot, radius clause,
genre adjacency, per-day capacity; each helper here answers one of them.
"""

from datetime import timedelta

import ledgers
from db import date_at_time, db, day_delta, parse_hhmm, parse_ts
from errors import ApiError

HELD_OFFER_STATUSES = ("SENT", "COUNTERED")
ADJACENCY_OFFER_STATUSES = ("SENT", "COUNTERED", "ACCEPTED")
RADIUS_OFFER_STATUSES = ("SENT", "COUNTERED", "ACCEPTED")
LIVE_BOOKING_STATUSES = ("DATE_HELD", "ANNOUNCED", "PERFORMED")

GENRE_ADJACENCY_GAP_DAYS = 1


def window_is_well_formed(show_date, load_in_start_utc, load_out_end_utc):
    """load_out strictly after load_in, and load_in at or after the date's midnight."""
    start = parse_ts(load_in_start_utc)
    end = parse_ts(load_out_end_utc)
    midnight = date_at_time(show_date, 0, 0)
    if start is None or end is None or midnight is None:
        return False
    if not (end > start):
        return False
    if start < midnight:
        return False
    return True


def date_inside_run(edition, date_text):
    return edition["run_start_date"] <= date_text <= edition["run_end_date"]


def check_curfew(edition, show_date, load_out_end_utc):
    """The occupation must end at or before the performance date's curfew instant."""
    hhmm = parse_hhmm(edition.get("curfew_utc_time") or "23:30")
    curfew = date_at_time(show_date, hhmm[0], hhmm[1])
    end = parse_ts(load_out_end_utc)
    if end > curfew:
        raise ApiError("ERR_CURFEW_VIOLATION")


# ---------------------------------------------------------------------------
# candidate sets
# ---------------------------------------------------------------------------

def _stage_holds(stage_id, exclude_offer_id, exclude_booking_id, offer_statuses):
    """Every competing occupation of one stage as (show_date, load_in, load_out, offer)."""
    holds = []
    for offer in db.offers.values():
        if offer.get("target_stage_id") != stage_id:
            continue
        if offer.get("status") not in offer_statuses:
            continue
        if exclude_offer_id is not None and offer["id"] == exclude_offer_id:
            continue
        holds.append(
            {
                "show_date": offer.get("target_show_date"),
                "load_in_start_utc": offer.get("load_in_start_utc"),
                "load_out_end_utc": offer.get("load_out_end_utc"),
                "offer": offer,
            }
        )
    for booking in db.bookings.values():
        if booking.get("stage_id") != stage_id:
            continue
        if booking.get("booking_status") not in LIVE_BOOKING_STATUSES:
            continue
        if exclude_booking_id is not None and booking["id"] == exclude_booking_id:
            continue
        holds.append(
            {
                "show_date": booking.get("show_date"),
                "load_in_start_utc": booking.get("load_in_start_utc"),
                "load_out_end_utc": booking.get("load_out_end_utc"),
                "offer": db.offers.get(booking.get("offer_id")),
            }
        )
    return holds


def check_stage_slot(stage, load_in_start_utc, load_out_end_utc,
                     exclude_offer_id=None, exclude_booking_id=None):
    """Buffered stage-slot exclusivity; a gap of exactly the buffer is permitted."""
    buffer_minutes = int(stage.get("changeover_buffer_minutes", 0) or 0)
    buffer = timedelta(minutes=buffer_minutes)
    cand_in = parse_ts(load_in_start_utc)
    cand_out = parse_ts(load_out_end_utc)
    for hold in _stage_holds(stage["id"], exclude_offer_id, exclude_booking_id, HELD_OFFER_STATUSES):
        other_in = parse_ts(hold["load_in_start_utc"])
        other_out = parse_ts(hold["load_out_end_utc"])
        if other_in is None or other_out is None:
            continue
        if cand_in < (other_out + buffer) and other_in < (cand_out + buffer):
            raise ApiError("ERR_STAGE_SLOT_CONFLICT")


def check_radius(artist_id, show_date, exclude_offer_id=None):
    """Another live offer for the same artist whose own radius window covers this date."""
    for offer in db.offers.values():
        if offer.get("artist_id") != artist_id:
            continue
        if offer.get("status") not in RADIUS_OFFER_STATUSES:
            continue
        if offer.get("radius_waiver_granted"):
            continue
        if exclude_offer_id is not None and offer["id"] == exclude_offer_id:
            continue
        other_date = offer.get("target_show_date")
        if other_date is None:
            continue
        delta = day_delta(other_date, show_date)
        if delta is None:
            continue
        before = int(offer.get("radius_days_before", 0) or 0)
        after = int(offer.get("radius_days_after", 0) or 0)
        if -before <= delta <= after:
            raise ApiError("ERR_RADIUS_CLAUSE_CONFLICT")


def check_genre_adjacency(stage, show_date, genre, exclude_offer_id=None, exclude_booking_id=None):
    """No other show of the same genre within one calendar day on the same stage."""
    if genre is None:
        return
    for hold in _stage_holds(stage["id"], exclude_offer_id, exclude_booking_id,
                             ADJACENCY_OFFER_STATUSES):
        offer = hold.get("offer")
        if offer is None:
            continue
        artist = db.artists.get(offer.get("artist_id"))
        if artist is None or artist.get("genre") != genre:
            continue
        delta = day_delta(hold.get("show_date"), show_date)
        if delta is None:
            continue
        if abs(delta) <= GENRE_ADJACENCY_GAP_DAYS:
            raise ApiError("ERR_GENRE_ADJACENCY_CONFLICT")


def check_day_capacity(edition, show_date, exclude_offer_id=None, exclude_booking_id=None):
    """Per-day aggregate capacity across every stage of the edition."""
    stage_ids = set(s["id"] for s in db.stages.values() if s.get("fair_edition_id") == edition["id"])
    count = 0
    for offer in db.offers.values():
        if offer.get("status") not in HELD_OFFER_STATUSES:
            continue
        if offer.get("fair_edition_id") != edition["id"]:
            continue
        if exclude_offer_id is not None and offer["id"] == exclude_offer_id:
            continue
        if offer.get("target_show_date") == show_date:
            count += 1
    for booking in db.bookings.values():
        if booking.get("booking_status") not in LIVE_BOOKING_STATUSES:
            continue
        if booking.get("stage_id") not in stage_ids:
            continue
        if exclude_booking_id is not None and booking["id"] == exclude_booking_id:
            continue
        if booking.get("show_date") == show_date:
            count += 1
    if (count + 1) > int(edition.get("max_shows_per_day", 1) or 1):
        raise ApiError("ERR_DAY_SLOT_CAPACITY_EXCEEDED")


def check_scheduling_for_booking(booking, edition, stage, show_date, load_in_start_utc,
                                 load_out_end_utc, include_radius=True):
    """The four conflict gates re-evaluated for a booking at new coordinates."""
    offer = ledgers.offer_of_booking(booking)
    artist = ledgers.artist_of_booking(booking)
    exclude_offer_id = offer["id"] if offer is not None else None
    check_stage_slot(
        stage,
        load_in_start_utc,
        load_out_end_utc,
        exclude_offer_id=exclude_offer_id,
        exclude_booking_id=booking["id"],
    )
    if include_radius and artist is not None:
        check_radius(artist["id"], show_date, exclude_offer_id=exclude_offer_id)
    check_genre_adjacency(
        stage,
        show_date,
        artist.get("genre") if artist is not None else None,
        exclude_offer_id=exclude_offer_id,
        exclude_booking_id=booking["id"],
    )
    check_day_capacity(
        edition,
        show_date,
        exclude_offer_id=exclude_offer_id,
        exclude_booking_id=booking["id"],
    )
