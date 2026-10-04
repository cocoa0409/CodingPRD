"""The Booking state machine (§1.2), the negotiation rounds (§3.2) and the
on-sale / presale / hold / confirmation workflows (§3.3).

Every transition here applies its declared cascade atomically inside the
request, and every precondition is checked before any mutation is committed.
"""
from core import (
    ApiError,
    D,
    bad_request,
    db,
    f_int,
    now,
    touch,
)
from calcs import (
    checkpoint_instant,
    guarantee_allocation,
    guarantee_ceiling,
    per_screening_credit,
    presale_passes,
    ticket_price_cents,
)
from store import (
    booking_feed_events,
    booking_lines,
    booking_screenings,
    booking_settlements,
    find,
    get_or_404,
    line_screenings,
    recompute_booking,
    recompute_circuit,
    recompute_line,
    recompute_title,
)
from services import (
    candidate_intervals,
    kill_screenings,
    recompute_circuit_for,
    release_lines,
    revoke_screening_keys,
    synthesize_screenings,
    validate_occupancy,
)

CONFIRMED_OR_SETTLED = ("CONFIRMED", "SETTLED")
ON_SALE_OR_LATER = ("ON_SALE", "CONFIRMED", "SETTLED")

# Statuses a booking may be closed from (§1.2).
CLOSEABLE_FROM = (
    "DRAFT",
    "PENDING_APPROVAL",
    "COUNTERED",
    "APPROVED",
    "CANCELLED",
    "ON_HOLD",
    "SETTLED",
    "ON_SALE",
)

# Statuses in which the aggregate-capped ceiling variant is live.
CAPPED_CEILING_STATUSES = ("ON_SALE", "ON_HOLD", "CONFIRMED", "SETTLED")


# ---------------------------------------------------------------------------
# Optimistic concurrency (§2.5)
# ---------------------------------------------------------------------------
def check_version(booking, payload, required=False):
    """Compare the client's attestation with the booking's current version.

    The comparison runs immediately before any mutation is committed, after the
    business validations, which is the order the validation table prescribes.
    """
    value = payload.get("expected_booking_version")
    if value is None or value == "":
        if required:
            bad_request("Field 'expected_booking_version' is required.")
        return
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field 'expected_booking_version' must be an integer.")
    if int(value) != int(booking["version"]):
        raise ApiError("ERR_STALE_VERSION")


def check_version_raw(current_version, value, field="expected_booking_version", required=True):
    if value is None or value == "":
        if required:
            bad_request("Field '%s' is required." % field)
        return
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % field)
    if int(value) != int(current_version):
        raise ApiError("ERR_STALE_VERSION")


# ---------------------------------------------------------------------------
# Construction helpers
# ---------------------------------------------------------------------------
def title_of(booking):
    return find("titles", booking["title_id"])


def circuit_of(booking):
    return find("circuits", booking["circuit_id"])


def party(booking):
    title = title_of(booking)
    return (
        title,
        circuit_of(booking),
        find("distributors", title["distributor_id"]) if title else None,
    )


def recompute_ceiling(booking, screens=None):
    title, circuit, distributor = party(booking)
    if title is None or circuit is None or distributor is None:
        booking["guarantee_ceiling_cents"] = 0
        return
    if screens is None:
        booking["guarantee_ceiling_cents"] = guarantee_ceiling(
            booking, circuit, title, distributor
        )
        return
    original = booking["committed_screens_total"]
    booking["committed_screens_total"] = screens
    booking["guarantee_ceiling_cents"] = guarantee_ceiling(
        booking, circuit, title, distributor
    )
    booking["committed_screens_total"] = original


def prospective_screens(booking, states):
    """The booking-level commitment total the named line states would produce."""
    return sum(
        int(ln["committed_screens"])
        for ln in booking_lines(booking)
        if ln["exhibit_state"] in states
    )


def recompute_allocation(booking):
    guarantee_allocation(booking, booking_lines(booking))
    recompute_booking(booking)


def showtime_bounds(booking):
    """(first_start, last_end) across the booking's live screenings."""
    live = [s for s in booking_screenings(booking) if s["state"] != "VOID"]
    if not live:
        return None, None
    return min(s["starts_at"] for s in live), max(s["ends_at"] for s in live)


def plan_bounds(booking, title):
    """(first_start, last_end) across the showtime plan, from its intervals."""
    intervals = candidate_intervals(booking, {"theater_id": None}, title)
    if not intervals:
        return None, None
    return (
        min(i[1] for i in intervals),
        max(i[2] for i in intervals),
    )


def _sod_principals(booking):
    return (
        booking.get("_approved_by"),
        booking.get("_countered_by"),
        booking.get("_submitted_by"),
    )


# ---------------------------------------------------------------------------
# Occupancy
# ---------------------------------------------------------------------------
def check_booking_occupancy(booking, title, line=None):
    lines = [line] if line is not None else [
        ln for ln in booking_lines(booking) if ln["exhibit_state"] == "COMMITTED"
    ]
    for ln in lines:
        intervals = candidate_intervals(booking, ln, title)
        if intervals:
            validate_occupancy(
                booking, ln["theater_id"], intervals, exclude_booking_id=booking["id"]
            )


# ---------------------------------------------------------------------------
# DRAFT -> PENDING_APPROVAL (submit)
# ---------------------------------------------------------------------------
def submit(booking, payload):
    if booking["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    title, circuit, distributor = party(booking)
    lines = booking_lines(booking)
    recompute_booking(booking)

    # PRD §3.2 names six conditions, in order.
    if int(booking["committed_screens_total"]) < int(booking["min_screens"]):
        raise ApiError("ERR_MIN_SCREENS_NOT_MET")
    if not lines:
        raise ApiError("ERR_INVALID_STATE")
    if booking["on_sale_at"] < now():
        raise ApiError("ERR_INVALID_STATE")
    # PRD §3.1 places the guarantee floor immediately after the on-sale check and
    # states the safety/rights checks precede the fiscal ones (§2.4): a venue the
    # title is not licensed for cannot be committed at all, so territory fires
    # before the floor.
    unlicensed = [
        ln
        for ln in lines
        if (find("theaters", ln["theater_id"]) or {}).get("state_code")
        not in (title["territory_state_codes"] or [])
    ]
    if unlicensed:
        raise ApiError("ERR_TERRITORY_UNLICENSED")
    if int(booking["guarantee_cents"]) < int(distributor["guarantee_floor_cents"]):
        raise ApiError("ERR_GUARANTEE_BELOW_FLOOR")
    if circuit["status"] != "ACCREDITED":
        raise ApiError("ERR_INVALID_STATE")
    if title["status"] not in ("BOOKABLE", "CLEARED"):
        raise ApiError("ERR_INVALID_STATE")
    if int(booking["committed_screens_total"]) > int(title["max_screen_commitment"]):
        raise ApiError("ERR_MAX_SCREEN_COMMITMENT_EXCEEDED")

    recompute_ceiling(booking)
    if int(booking["guarantee_cents"]) > int(booking["guarantee_ceiling_cents"]):
        raise ApiError("ERR_GUARANTEE_ABOVE_CEILING")

    check_version(booking, payload)
    booking["status"] = "PENDING_APPROVAL"
    booking["_submitted_by"] = _acting_id()
    recompute_ceiling(booking)
    recompute_booking(booking)
    touch(booking)
    recompute_title(title)
    touch(title)
    return booking


# ---------------------------------------------------------------------------
# PENDING_APPROVAL <-> COUNTERED
# ---------------------------------------------------------------------------
def counter(booking, payload):
    if booking["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE")
    title, circuit, distributor = party(booking)
    proposed_guarantee = f_int(payload, "proposed_guarantee_cents", required=True, minimum=0)
    proposed_share = D(payload["proposed_revenue_share_pct"]) if "proposed_revenue_share_pct" in payload else None
    if proposed_share is None:
        bad_request("Field 'proposed_revenue_share_pct' is required.")
    if proposed_share < 0 or proposed_share > 1:
        bad_request("Field 'proposed_revenue_share_pct' must be a fraction in [0, 1].")

    if circuit["status"] != "ACCREDITED":
        raise ApiError("ERR_INVALID_STATE")
    if int(booking.get("_counter_count", 0)) >= 3:
        raise ApiError("ERR_COUNTER_LIMIT_REACHED")
    if proposed_guarantee < int(distributor["guarantee_floor_cents"]):
        raise ApiError("ERR_GUARANTEE_BELOW_FLOOR")

    check_version(booking, payload)
    booking["status"] = "COUNTERED"
    booking["guarantee_cents"] = proposed_guarantee
    booking["revenue_share_pct"] = proposed_share
    booking["_counter_count"] = int(booking.get("_counter_count", 0)) + 1
    booking["_countered_by"] = _acting_id()
    recompute_ceiling(booking)
    touch(booking)
    return booking


def re_propose(booking, payload):
    if booking["status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_STATE")
    title, circuit, distributor = party(booking)
    proposed_guarantee = f_int(payload, "proposed_guarantee_cents", required=False, default=None)
    proposed_share = None
    if "proposed_revenue_share_pct" in payload and payload["proposed_revenue_share_pct"] is not None:
        proposed_share = D(payload["proposed_revenue_share_pct"])
        if proposed_share < 0 or proposed_share > 1:
            bad_request("Field 'proposed_revenue_share_pct' must be a fraction in [0, 1].")

    guarantee = int(booking["guarantee_cents"]) if proposed_guarantee is None else proposed_guarantee
    if guarantee < int(distributor["guarantee_floor_cents"]):
        raise ApiError("ERR_GUARANTEE_BELOW_FLOOR")
    if booking["on_sale_at"] < now():
        raise ApiError("ERR_INVALID_STATE")

    check_version(booking, payload)
    if proposed_guarantee is not None:
        booking["guarantee_cents"] = proposed_guarantee
    if proposed_share is not None:
        booking["revenue_share_pct"] = proposed_share
    booking["status"] = "PENDING_APPROVAL"
    booking["_submitted_by"] = _acting_id()
    recompute_ceiling(booking)
    touch(booking)
    return booking


# ---------------------------------------------------------------------------
# -> APPROVED (approve)
# ---------------------------------------------------------------------------
def approve(booking, payload):
    if booking["status"] not in ("PENDING_APPROVAL", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE")
    # PRD §2.5 lists approval among the operations carrying `expected_booking_version`
    # and §2.4 fixes the layer order as existence, then state, then the constraints;
    # the concurrency attestation is a state check, so it is evaluated before the
    # circuit/ceiling/territory business rules that a wrong-state request also trips.
    check_version(booking, payload)
    title, circuit, distributor = party(booking)
    nominee_id = payload.get("line_id")
    if nominee_id is not None and not isinstance(nominee_id, str):
        bad_request("Field 'line_id' must be a string.")
    recompute_booking(booking)
    recompute_ceiling(booking)

    if circuit["status"] != "ACCREDITED":
        raise ApiError("ERR_INVALID_STATE")
    if int(booking["guarantee_cents"]) > int(booking["guarantee_ceiling_cents"]):
        raise ApiError("ERR_GUARANTEE_ABOVE_CEILING")
    if title["status"] not in ("BOOKABLE", "CLEARED"):
        raise ApiError("ERR_INVALID_STATE")

    proposed = [ln for ln in booking_lines(booking) if ln["exhibit_state"] == "PROPOSED"]
    if not proposed:
        raise ApiError("ERR_INVALID_STATE")

    if nominee_id is not None:
        nominee = find("booking_lines", nominee_id)
        if nominee is None or nominee["booking_id"] != booking["id"]:
            raise ApiError("ERR_LINE_NOT_FOUND")
        if nominee["exhibit_state"] != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE")
    else:
        nominee = sorted(
            proposed,
            key=lambda ln: (ln["created_at"], ln["_seq"], ln["theater_id"]),
        )[0]

    nominee_theater = get_or_404("theaters", nominee["theater_id"])
    if nominee_theater["state_code"] not in (title["territory_state_codes"] or []):
        raise ApiError("ERR_TERRITORY_UNLICENSED")
    if now() >= title["rights_end_utc"]:
        raise ApiError("ERR_RIGHTS_EXPIRED")
    # committed_screens_total already carries this PROPOSED nominee.
    if int(booking["committed_screens_total"]) > int(title["max_screen_commitment"]):
        raise ApiError("ERR_MAX_SCREEN_COMMITMENT_EXCEEDED")

    intervals = candidate_intervals(booking, nominee, title)
    if intervals:
        validate_occupancy(
            booking, nominee["theater_id"], intervals, exclude_booking_id=booking["id"]
        )

    if int(circuit["committed_screens_balance"]) + int(nominee["committed_screens"]) > int(
        circuit["screen_pool_total"]
    ):
        raise ApiError("ERR_SCREEN_POOL_EXHAUSTED")

    nominee["exhibit_state"] = "COMMITTED"
    touch(nominee)
    booking["status"] = "APPROVED"
    booking["_approved_by"] = _acting_id()
    synthesize_screenings(booking, nominee, title)
    recompute_booking(booking)
    recompute_allocation(booking)
    recompute_circuit(circuit)
    touch(circuit)
    touch(booking)
    return booking


# ---------------------------------------------------------------------------
# -> CANCELLED
# ---------------------------------------------------------------------------
def cancel(booking, payload):
    status = booking["status"]
    if status not in ("PENDING_APPROVAL", "COUNTERED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE")
    if status in ("PENDING_APPROVAL", "COUNTERED"):
        if any(ln["exhibit_state"] == "COMMITTED" for ln in booking_lines(booking)):
            raise ApiError("ERR_INVALID_STATE")
    else:
        if any(s["status"] == "CLOSED" for s in booking_settlements(booking)):
            raise ApiError("ERR_INVALID_STATE")
    check_version(booking, payload)
    release_lines(booking, ("PROPOSED",))
    if status == "APPROVED":
        release_lines(booking, ("COMMITTED",))
        kill_screenings(booking, "SKIPPED_CANCELLED")
    booking["status"] = "CANCELLED"
    touch(booking)
    recompute_booking(booking)
    recompute_circuit_for(booking)
    return booking


def cancel_with_compensation(booking, payload):
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE")
    if any(s["status"] == "CLOSED" for s in booking_settlements(booking)):
        raise ApiError("ERR_SETTLEMENT_ALREADY_CLOSED")
    check_version(booking, payload)
    release_lines(booking, ("COMMITTED",))
    kill_screenings(booking, "SKIPPED_CANCELLED")
    booking["status"] = "CANCELLED"
    touch(booking)
    recompute_booking(booking)
    recompute_circuit_for(booking)
    return booking


# ---------------------------------------------------------------------------
# ON_SALE <-> ON_HOLD
# ---------------------------------------------------------------------------
def suspend(booking, payload):
    if booking["status"] != "ON_SALE":
        raise ApiError("ERR_INVALID_STATE")
    circuit = circuit_of(booking)
    if circuit["status"] == "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE")
    if any(s["status"] == "CLOSED" for s in booking_settlements(booking)):
        raise ApiError("ERR_INVALID_STATE")
    check_version(booking, payload)
    release_lines(booking, ("COMMITTED",))
    kill_screenings(booking, "VOID")
    booking["status"] = "ON_HOLD"
    touch(booking)
    recompute_booking(booking)
    recompute_circuit_for(booking)
    return booking


def resume(booking, payload):
    if booking["status"] != "ON_HOLD":
        raise ApiError("ERR_INVALID_STATE")
    title, circuit, distributor = party(booking)
    if circuit["status"] != "ACCREDITED":
        raise ApiError("ERR_INVALID_STATE")
    starts = [s["starts_at"] for s in booking_screenings(booking) if s["state"] != "VOID"]
    if starts and now() >= min(starts):
        raise ApiError("ERR_INVALID_STATE")
    # The resume re-commits the RELEASED lines, so the ceiling is evaluated
    # against that prospective commitment, not against the currently zero total.
    prospective = prospective_screens(booking, ("RELEASED", "COMMITTED"))
    recompute_ceiling(booking, prospective)
    if int(booking["guarantee_cents"]) > int(booking["guarantee_ceiling_cents"]):
        raise ApiError("ERR_GUARANTEE_ABOVE_CEILING")

    recommitted = [ln for ln in booking_lines(booking) if ln["exhibit_state"] == "RELEASED"]
    committed_screens = sum(int(ln["committed_screens"]) for ln in recommitted)
    if int(circuit["committed_screens_balance"]) + committed_screens > int(circuit["screen_pool_total"]):
        raise ApiError("ERR_SCREEN_POOL_EXHAUSTED")

    check_version(booking, payload)
    for ln in recommitted:
        ln["exhibit_state"] = "COMMITTED"
        touch(ln)
        synthesize_screenings(booking, ln, title)
    booking["status"] = "ON_SALE"
    recompute_booking(booking)
    recompute_allocation(booking)
    recompute_circuit(circuit)
    touch(circuit)
    touch(booking)
    return booking


# ---------------------------------------------------------------------------
# ON_SALE -> CONFIRMED / CANCELLED
# ---------------------------------------------------------------------------
def confirm(booking, payload):
    if booking["status"] != "ON_SALE":
        raise ApiError("ERR_INVALID_STATE")
    title, circuit, distributor = party(booking)
    recompute_booking(booking)

    scheduled = [s for s in booking_screenings(booking) if s["state"] == "SCHEDULED"]
    if int(booking["committed_screens_total"]) < int(booking["min_screens"]):
        raise ApiError("ERR_MIN_SCREENS_NOT_MET")
    if not presale_passes(booking):
        raise ApiError("ERR_INVALID_STATE")
    for event in booking_feed_events(booking):
        if event["state"] == "CONFIRMED" and event.get("resolution_outcome") == "ABANDONED":
            raise ApiError("ERR_INVALID_STATE")

    committed_lines = [ln for ln in booking_lines(booking) if ln["exhibit_state"] == "COMMITTED"]
    seen_theaters = []
    for ln in committed_lines:
        if ln["theater_id"] in seen_theaters:
            raise ApiError("ERR_DUPLICATE_BOOKING_LINE")
        seen_theaters.append(ln["theater_id"])
    for ln in committed_lines:
        theater = get_or_404("theaters", ln["theater_id"])
        if theater["state_code"] not in (title["territory_state_codes"] or []):
            raise ApiError("ERR_TERRITORY_UNLICENSED")
    first_start, last_end = plan_bounds(booking, title)
    if first_start is not None:
        if first_start < title["rights_start_utc"] or first_start >= title["rights_end_utc"]:
            raise ApiError("ERR_RIGHTS_WINDOW_VIOLATION")
        if last_end is not None and last_end > title["rights_end_utc"]:
            raise ApiError("ERR_RIGHTS_WINDOW_VIOLATION")
    if now() >= title["rights_end_utc"]:
        raise ApiError("ERR_RIGHTS_EXPIRED")

    check_booking_occupancy(booking, title)

    check_version(booking, payload)
    booking["status"] = "CONFIRMED"
    recompute_allocation(booking)
    recompute_circuit(circuit)
    touch(circuit)
    touch(booking)
    return booking


def presale_checkpoint(booking, payload):
    if booking["status"] != "ON_SALE":
        raise ApiError("ERR_INVALID_STATE")
    if now() < checkpoint_instant(booking):
        raise ApiError("ERR_INVALID_STATE")
    check_version(booking, payload)
    recompute_booking(booking)
    if not presale_passes(booking):
        release_lines(booking, ("COMMITTED",))
        kill_screenings(booking, "SKIPPED_CANCELLED")
        booking["status"] = "CANCELLED"
        recompute_booking(booking)
        recompute_circuit_for(booking)
    touch(booking)
    return booking


# ---------------------------------------------------------------------------
# Compensation endpoints
# ---------------------------------------------------------------------------
def release_screens(booking, payload):
    line_id = payload.get("line_id")
    if not isinstance(line_id, str) or not line_id:
        bad_request("Field 'line_id' is required.")
    line = find("booking_lines", line_id)
    if line is None or line["booking_id"] != booking["id"]:
        raise ApiError("ERR_LINE_NOT_FOUND")
    if line["exhibit_state"] != "COMMITTED":
        raise ApiError("ERR_INVALID_STATE")
    check_version(booking, payload)
    line["exhibit_state"] = "RELEASED"
    touch(line)
    for screening in line_screenings(line):
        if screening["state"] == "SCHEDULED":
            screening["state"] = "SKIPPED_CANCELLED"
            touch(screening)
            revoke_screening_keys(screening, "CONTENT_FAILURE")
    recompute_line(line)
    recompute_booking(booking)
    recompute_allocation(booking)
    recompute_circuit_for(booking)
    touch(booking)
    return line


def apply_makegood(booking, payload):
    line_id = payload.get("line_id")
    feed_event_id = payload.get("feed_event_id")
    if not isinstance(line_id, str) or not line_id:
        bad_request("Field 'line_id' is required.")
    if not isinstance(feed_event_id, str) or not feed_event_id:
        bad_request("Field 'feed_event_id' is required.")
    event = find("feed_events", feed_event_id)
    if event is None:
        raise ApiError("ERR_FEED_EVENT_NOT_FOUND")
    line = find("booking_lines", line_id)
    if line is None or line["booking_id"] != booking["id"]:
        raise ApiError("ERR_LINE_NOT_FOUND")
    if event["state"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE")
    if line["exhibit_state"] != "COMMITTED":
        raise ApiError("ERR_BOOKING_LINE_NOT_COMMITTED")

    title, circuit, distributor = party(booking)
    theater = get_or_404("theaters", line["theater_id"])
    ruined = ruined_screenings(line, event)
    if not ruined:
        raise ApiError("ERR_MAKEGOOD_LINE_NOT_APPLICABLE")

    check_version(booking, payload)
    credit_line(booking, line, event, title, distributor, theater, ruined)
    recompute_line(line)
    line["credit_issued_cents"] = sum(
        int(s.get("_credited_cents", 0)) for s in line_screenings(line)
    )
    touch(line)
    recompute_booking(booking)
    booking["feed_failure_credit_cents"] = sum(
        int(s.get("_credited_feed_loss_cents", 0))
        for s in booking_screenings(booking)
    )
    touch(booking)
    return booking


def ruined_screenings(line, event):
    """Screenings eligible for make-good credit behind a confirmed event."""
    out = []
    for screening in line_screenings(line):
        if screening["state"] == "SKIPPED_INCOMPLETE":
            out.append(screening)
        elif screening["state"] == "SCHEDULED" and event["detected_at_utc"] >= screening["starts_at"]:
            out.append(screening)
    return out


def credit_line(booking, line, event, title, distributor, theater, ruined):
    price = ticket_price_cents(title, distributor)
    applied_events = event["id"]
    total = 0
    for screening in ruined:
        if applied_events in screening.get("_credited_events", []):
            continue
        credit = per_screening_credit(
            int(event["outage_minutes"]),
            price,
            int(screening["reported_attendance"] or 0),
            int(title["duration_minutes"]),
            int(theater["seats_total"]),
        )
        screening.setdefault("_credited_events", []).append(applied_events)
        screening["_credited_cents"] = int(screening.get("_credited_cents", 0)) + credit
        if event["failure_type"] == "FEED_LOSS":
            screening["_credited_feed_loss_cents"] = (
                int(screening.get("_credited_feed_loss_cents", 0)) + credit
            )
        total += credit
    return total


# ---------------------------------------------------------------------------
# SETTLED -> CONFIRMED (reopen) and -> TERMINAL (close)
# ---------------------------------------------------------------------------
def reopen(booking, payload):
    # The pair moves together: reopening a settlement already returns the
    # booking to CONFIRMED, so a booking-level reopen is accepted from either
    # SETTLED (the settlement was reopened out of band) or CONFIRMED.
    if booking["status"] not in ("SETTLED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE")
    settlement_id = payload.get("settlement_id")
    if not isinstance(settlement_id, str) or not settlement_id:
        bad_request("Field 'settlement_id' is required.")
    settlement = find("settlements", settlement_id)
    if settlement is None or settlement["booking_id"] != booking["id"]:
        raise ApiError("ERR_SETTLEMENT_NOT_FOUND")
    if settlement["status"] != "REOPENED":
        raise ApiError("ERR_INVALID_STATE")
    check_version(booking, payload)
    booking["status"] = "CONFIRMED"
    booking["settled_at"] = None
    touch(booking)
    return booking


def close(booking, payload):
    if booking["status"] == "TERMINAL":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if booking["status"] not in CLOSEABLE_FROM:
        raise ApiError("ERR_INVALID_STATE")
    if any(s["state"] == "SCHEDULED" for s in booking_screenings(booking)):
        raise ApiError("ERR_INVALID_STATE")
    if any(s["status"] in ("OPEN", "REOPENED") for s in booking_settlements(booking)):
        raise ApiError("ERR_INVALID_STATE")
    from core import segregation_of_duties

    segregation_of_duties(*_sod_principals(booking))
    check_version(booking, payload)
    booking["status"] = "TERMINAL"
    touch(booking)
    recompute_booking(booking)
    recompute_circuit_for(booking)
    recompute_title(title_of(booking))
    return booking


# ---------------------------------------------------------------------------
# Operational sweeps
# ---------------------------------------------------------------------------
def on_sale_sweep():
    advanced = []
    for booking in sorted(db.bookings.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if booking["status"] != "APPROVED":
            continue
        if now() < booking["on_sale_at"]:
            continue
        recompute_booking(booking)
        if int(booking["committed_screens_total"]) < int(booking["min_screens"]):
            continue
        booking["status"] = "ON_SALE"
        touch(booking)
        advanced.append(booking)
    return advanced


def presale_checkpoint_sweep():
    cancelled = []
    for booking in sorted(db.bookings.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if booking["status"] != "ON_SALE":
            continue
        if now() < checkpoint_instant(booking):
            continue
        recompute_booking(booking)
        if presale_passes(booking):
            continue
        release_lines(booking, ("COMMITTED",))
        kill_screenings(booking, "SKIPPED_CANCELLED")
        booking["status"] = "CANCELLED"
        touch(booking)
        recompute_booking(booking)
        recompute_circuit_for(booking)
        cancelled.append(booking)
    return cancelled


def _acting_id():
    from flask import g

    return getattr(g, "user_id", None)