"""Attraction sessions, tickets, dynamic pricing, and the waitlist."""
import test_helpers.fixtures as fx
from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, get_success_data,
    assert_ticket, assert_same_instant,
)

ADMIN = fx.ADMIN
BOXOFFICE = fx.BOXOFFICE


def test_ticket_individual_created_confirmed_initial_state(api):
    """PRD section 3.7: "An `INDIVIDUAL` ticket is created `CONFIRMED` when the
    session has room" and "The ticket's `units` are derived: 1 for an
    `INDIVIDUAL`". Price: "below the low-tier ceiling `LOW_TIER_CEIL` of 0.5 the
    factor is the low multiplier `LOW_MULT`, 0.9" and "The day factor is
    `WEEKEND_MULT`, 1.15, when `session_date` falls on a Saturday or Sunday" —
    Saturday 2026-10-17: round_half_up(2000 x 0.9 x 1.0 x 1.15) = 2070.

    Design: Corner/state_machines/ticket_individual_created_confirmed_initial_state
    """
    fx.reset_clock()
    session = fx.create_session()
    resp = fx.book_individual(session["id"])
    data = validate_success(resp, 201)
    assert_ticket(data)
    assert data["status"] == "CONFIRMED"
    assert data["units"] == 1
    assert data["price_cents"] == 2070
    assert fx.get_session(session["id"])["booked_units"] == 1


def test_ticket_create_group_missing_school_name_returns_invalid_request(api):
    """PRD section 3.7: "For a `GROUP` booking, `group_size` and `school_name`
    are both required; for `INDIVIDUAL` both must be omitted —
    conditional-field violations are `ERR_INVALID_REQUEST`."

    Design: Corner/entities/ticket_create_group_missing_school_name_returns_invalid_request
    """
    fx.reset_clock()
    session = fx.create_session()
    resp = api_client.create_ticket(
        {"session_id": session["id"], "kind": "GROUP", "group_size": 20}, BOXOFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400
    ok = fx.book_individual(session["id"])
    data = validate_success(ok, 201)
    assert data["units"] == 1


def test_group_over_max_returns_group_too_large(api):
    """PRD section 3.7: "A `group_size` must be at least 10 and at most 100;
    above 100 the booking is rejected with `ERR_GROUP_TOO_LARGE` (HTTP 422)."

    Design: Corner/errors/group_over_max_returns_group_too_large
    """
    fx.reset_clock()
    session = fx.create_session(capacity_units=150)
    resp = fx.book_group(session["id"], 101, "Jefferson High")
    validate_error(resp, ApiErrorId.ERR_GROUP_TOO_LARGE)
    assert resp.status_code == 422
    ok = fx.book_group(session["id"], 100, "Lincoln Elementary")
    data = validate_success(ok, 201)
    assert data["status"] == "CONFIRMED"
    assert fx.get_session(session["id"])["booked_units"] == 100


def test_ticket_check_in_happy_path_on_session_date(api):
    """PRD section 3.7: "`CHECK_IN` requires the ticket `CONFIRMED`, the session
    still `SCHEDULED` — else `ERR_SESSION_CLOSED` — and the logical clock inside
    the session's live window, from its start through its end on the session
    date" and "A successful check-in stamps `checked_in_at` with the logical
    clock and moves the ticket to `CHECKED_IN`."

    Design: Corner/state_machines/ticket_check_in_happy_path_on_session_date
    """
    fx.reset_clock()
    session = fx.create_session()
    ticket = fx.book_individual_ok(session["id"])
    fx.set_clock("2026-10-17T10:30:00Z")  # inside the 600..720-minute window
    resp = api_client.ticket_decision(ticket["id"], {"action": "CHECK_IN"}, BOXOFFICE)
    data = validate_success(resp, 200)
    assert data["status"] == "CHECKED_IN"
    assert_same_instant(data["checked_in_at"], "2026-10-17T10:30:00Z", "checked_in_at")
    assert fx.get_session(session["id"])["booked_units"] == 1


def test_ticket_refund_then_second_refund_is_rejected(api):
    """PRD section 3.7: "`REFUND` requires a `CONFIRMED` ticket and a logical
    clock earlier than the session start" and "Any decision attempted from a
    ticket state that does not permit it is `ERR_TICKET_STATE`; the terminal
    ticket states are `CHECKED_IN`, `REFUNDED`, `CANCELLED`, and `NO_SHOW`."

    Design: Corner/state_machines/ticket_refund_then_second_refund_is_rejected
    """
    fx.reset_clock()
    session = fx.create_session()
    ticket = fx.book_individual_ok(session["id"])
    first = api_client.ticket_decision(ticket["id"], {"action": "REFUND"}, BOXOFFICE)
    data = validate_success(first, 200)
    assert data["status"] == "REFUNDED"
    second = api_client.ticket_decision(ticket["id"], {"action": "REFUND"}, BOXOFFICE)
    validate_error(second, ApiErrorId.ERR_TICKET_STATE)
    assert second.status_code == 409
    assert fx.get_session(session["id"])["booked_units"] == 0  # freed exactly once


def test_waitlisted_group_cancel(api):
    """PRD section 3.7: "`CANCEL` moves a `WAITLISTED` ticket to `CANCELLED`."
    — a cancelled waitlist entry consumes no capacity and is never promoted
    afterwards.

    Design: Corner/state_machines/waitlisted_group_cancel
    """
    fx.reset_clock()
    session = fx.create_session(venue="Hall D", date="2026-10-19T00:00:00Z",
                                capacity_units=50)
    g1 = fx.book_group_ok(session["id"], 50, "Lincoln Elementary")
    g2 = fx.book_group_ok(session["id"], 10, "Jefferson High")
    assert g2["status"] == "WAITLISTED"
    cancelled = fx.ticket_decision_ok(g2["id"], "CANCEL")
    assert cancelled["status"] == "CANCELLED"
    fx.ticket_decision_ok(g1["id"], "REFUND")
    after = fx.find_ticket(session["id"], g2["id"])
    assert after["status"] == "CANCELLED"
    assert fx.get_session(session["id"])["booked_units"] == 0


def test_session_close_epoch_marks_confirmed_tickets_no_show(api):
    """PRD section 3.7: "When the logical clock is at or past the session's end
    — its `session_date` at `start_minute` plus `duration_minutes` — the session
    moves from `SCHEDULED` to `CLOSED`, each of its still-`CONFIRMED` tickets
    becomes `NO_SHOW`, each `WAITLISTED` ticket becomes `CANCELLED`, and
    `booked_units` recomputes to 0."

    Design: Corner/state_machines/session_close_epoch_marks_confirmed_tickets_no_show
    """
    fx.reset_clock()
    session = fx.create_session()
    t1 = fx.book_individual_ok(session["id"])
    g1 = fx.book_group_ok(session["id"], 10, "Lincoln Elementary")
    g2 = fx.book_group_ok(session["id"], 90, "Jefferson High")
    assert g2["status"] == "WAITLISTED"
    fx.set_clock("2026-10-18T00:00:00Z")
    tally = fx.run_epoch()
    assert tally["sessions_closed"] == 1
    assert fx.get_session(session["id"])["status"] == "CLOSED"
    assert fx.get_session(session["id"])["booked_units"] == 0
    assert fx.find_ticket(session["id"], t1["id"])["status"] == "NO_SHOW"
    assert fx.find_ticket(session["id"], g1["id"])["status"] == "NO_SHOW"
    assert fx.find_ticket(session["id"], g2["id"])["status"] == "CANCELLED"


def test_waitlist_promotion_head_of_line_blocking(api):
    """PRD section 3.7: "the session's `WAITLISTED` tickets are walked in
    `created_at` ascending, `waitlist_seq` ascending order, and the head of the
    line is promoted while its `units` fit the freed capacity. The blocking is
    strict head-of-line — a head whose group does not fit stops the walk
    entirely, and no later waitlisted ticket is ever skipped ahead of it."

    Design: Corner/complexity_layers/waitlist_promotion_head_of_line_blocking
    """
    fx.reset_clock()
    session = fx.create_session(venue="Hall E", date="2026-10-19T00:00:00Z",
                                capacity_units=50)
    g1 = fx.book_group_ok(session["id"], 30, "Lincoln Elementary")
    g4 = fx.book_group_ok(session["id"], 20, "Washington Primary")
    assert g1["status"] == "CONFIRMED" and g4["status"] == "CONFIRMED"
    g2 = fx.book_group_ok(session["id"], 45, "Roosevelt Middle")   # older waitlist entry
    g3 = fx.book_group_ok(session["id"], 10, "Jefferson High")     # newer waitlist entry
    assert g2["status"] == "WAITLISTED" and g3["status"] == "WAITLISTED"
    fx.ticket_decision_ok(g4["id"], "REFUND")  # frees 20 units
    assert fx.find_ticket(session["id"], g2["id"])["status"] == "WAITLISTED"  # head blocks
    assert fx.find_ticket(session["id"], g3["id"])["status"] == "WAITLISTED"  # no skipping
    assert fx.get_session(session["id"])["booked_units"] == 30


def test_version_increments_on_every_mutation(api):
    """PRD section 2.5: "`version` (integer): starts at 1 when the resource is
    created and increments by exactly 1 on every mutation. Every mutation
    counts, including system-driven ones".

    Design: Corner/complexity_layers/version_increments_on_every_mutation
    """
    fx.reset_clock()
    session = fx.create_session()
    ticket = fx.book_individual_ok(session["id"])
    assert ticket["version"] == 1
    refunded = fx.ticket_decision_ok(ticket["id"], "REFUND")
    assert refunded["version"] == 2
    session_now = fx.get_session(session["id"])
    # create (1) -> booking cascade (2) -> refund cascade (3)
    assert session_now["version"] == 3
    assert session_now["booked_units"] == 0


def test_tickets_subresource_filters_by_kind_and_session(api):
    """PRD section 3.7: "a session's tickets can be listed with optional
    `status` and `kind` filters."

    Design: Corner/endpoints/tickets_subresource_filters_by_kind_and_session
    """
    fx.reset_clock()
    ses_a = fx.create_session()
    ses_b = fx.create_session(venue="Hall B", date="2026-10-19T00:00:00Z")
    fx.book_individual_ok(ses_a["id"])
    group = fx.book_group_ok(ses_a["id"], 10, "Lincoln Elementary")
    fx.book_individual_ok(ses_b["id"])
    filtered = fx.list_session_tickets(ses_a["id"], params={"kind": "GROUP"})
    assert len(filtered) == 1
    assert filtered[0]["id"] == group["id"]
    assert len(fx.list_session_tickets(ses_a["id"])) == 2
    assert len(fx.list_session_tickets(ses_b["id"])) == 1


def test_charter_session_uses_flat_pricing_variant(api):
    """PRD section 3.7: "On a charter session — `is_charter` true — the formula
    flattens to the school buyout rate: the capacity factor is fixed at 1.0 and
    the group factor for a `GROUP` booking is a flat `CHARTER_GROUP_MULT` of
    0.80, while the day factor still applies." — Saturday individual:
    round_half_up(2000 x 1.0 x 1.0 x 1.15) = 2300; Monday group of 30: unit
    round_half_up(2000 x 1.0 x 0.80 x 1.0) = 1600, times 30 = 48000.

    Design: Corner/calculations/charter_session_uses_flat_pricing_variant
    """
    fx.reset_clock()
    ses_f = fx.create_session(venue="Hall F", date="2026-10-24T00:00:00Z",
                              capacity_units=100, is_charter=True)
    ses_g = fx.create_session(venue="Hall G", date="2026-10-26T00:00:00Z",
                              capacity_units=200, is_charter=True)
    t = fx.book_individual_ok(ses_f["id"])
    assert t["price_cents"] == 2300  # capacity tier bypassed, weekend kept
    g = fx.book_group_ok(ses_g["id"], 30, "Lincoln Elementary")
    assert g["price_cents"] == 48000  # 1600 x 30
    assert t["price_cents"] != 2070   # STANDARD variant would give 2070


def test_session_booked_exactly_at_capacity_accepts_last_rejects_next(api):
    """PRD section 3.7: "An `INDIVIDUAL` ticket is created `CONFIRMED` when the
    session has room — that is, when adding its one unit to `booked_units` would
    not exceed `capacity_units`, with equality still fitting — and is otherwise
    rejected outright with `ERR_SESSION_FULL` (HTTP 409)". Booked 30 + group of
    20 lands exactly on 50; the 51st unit is refused.

    Design: Difficulty/boundary_precision_check/session_booked_exactly_at_capacity_accepts_last_and_rejects_next
    """
    fx.reset_clock()
    session = fx.create_session(venue="Hall D", date="2026-10-19T00:00:00Z",
                                capacity_units=50)
    fx.book_group_ok(session["id"], 30, "Lincoln Elementary")
    g2 = fx.book_group_ok(session["id"], 20, "Roosevelt Middle")
    assert g2["status"] == "CONFIRMED"  # 30 + 20 == capacity: equality fits
    assert fx.get_session(session["id"])["booked_units"] == 50
    resp = fx.book_individual(session["id"])
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL)
    assert resp.status_code == 409


def test_oversized_group_at_full_capacity_waitlists_instead(api):
    """PRD section 3.7: "A `GROUP` booking is created `CONFIRMED` when the whole
    group fits, and is otherwise created directly in `WAITLISTED`: no partial
    seating, and no capacity consumed while waiting."

    Design: Difficulty/boundary_precision_check/session_booked_exactly_at_capacity_accepts_last_and_rejects_next
    """
    fx.reset_clock()
    session = fx.create_session(venue="Hall D", date="2026-10-19T00:00:00Z",
                                capacity_units=50)
    fx.book_group_ok(session["id"], 30, "Lincoln Elementary")
    fx.book_group_ok(session["id"], 20, "Roosevelt Middle")
    g3 = fx.book_group_ok(session["id"], 10, "Jefferson High")
    assert g3["status"] == "WAITLISTED"
    assert fx.get_session(session["id"])["booked_units"] == 50  # unchanged


def test_ticket_booking_on_closed_session_returns_session_closed(api):
    """PRD section 3.7: "The session must still be `SCHEDULED`, else
    `ERR_SESSION_CLOSED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ticket_booking_requires_session_still_scheduled
    """
    fx.reset_clock()
    session = fx.create_session()
    fx.set_clock("2026-10-18T00:00:00Z")
    fx.run_epoch()
    resp = fx.book_individual(session["id"])
    validate_error(resp, ApiErrorId.ERR_SESSION_CLOSED)
    assert resp.status_code == 409


def test_closed_session_has_no_tickets_and_zero_booked(api):
    """PRD section 3.7: "the session moves from `SCHEDULED` to `CLOSED`, each of
    its still-`CONFIRMED` tickets becomes `NO_SHOW`, each `WAITLISTED`
    ticket becomes `CANCELLED`, and `booked_units` recomputes to 0" — the
    rejected booking leaves no trace.

    Design: Difficulty/cross_entity_state_dependency/ticket_booking_requires_session_still_scheduled
    """
    fx.reset_clock()
    session = fx.create_session()
    fx.set_clock("2026-10-18T00:00:00Z")
    fx.run_epoch()
    resp = fx.book_individual(session["id"])
    validate_error(resp, ApiErrorId.ERR_SESSION_CLOSED)
    closed = fx.get_session(session["id"])
    assert closed["status"] == "CLOSED"
    assert closed["booked_units"] == 0
    assert fx.list_session_tickets(session["id"]) == []


def test_checkin_refunded_ticket_on_closed_session_returns_ticket_state(api):
    """PRD section 2.8: "The stages are evaluated in the order below, the first
    failure wins" — the ticket's own state gate (stage 6, `ERR_TICKET_STATE`)
    precedes the session's linked-entity check (stage 10, `ERR_SESSION_CLOSED`).
    PRD section 3.7: "Any decision attempted from a ticket state that does not
    permit it is `ERR_TICKET_STATE`".

    Design: Difficulty/priority_pair_validation_conflict/ticket_checkin_state_beats_session_closed
    """
    fx.reset_clock()
    session = fx.create_session(capacity_units=10)
    ticket = fx.book_individual_ok(session["id"])
    fx.ticket_decision_ok(ticket["id"], "REFUND")  # clock still 2026-09-01
    fx.set_clock("2026-10-18T00:00:00Z")
    fx.run_epoch()  # closes the session
    resp = api_client.ticket_decision(ticket["id"], {"action": "CHECK_IN"}, BOXOFFICE)
    validate_error(resp, ApiErrorId.ERR_TICKET_STATE)
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] != "ERR_SESSION_CLOSED"


def test_checkin_no_show_ticket_on_closed_session_returns_ticket_state(api):
    """PRD section 3.7: a session close moves "still-`CONFIRMED` tickets" to
    `NO_SHOW`, and "Any decision attempted from a ticket state that does not
    permit it is `ERR_TICKET_STATE`" — the ticket state gate (stage 6) fires
    before the session referential check (stage 10) per section 2.8.

    Design: Difficulty/priority_pair_validation_conflict/ticket_checkin_state_beats_session_closed
    """
    fx.reset_clock()
    session = fx.create_session(capacity_units=10)
    ticket = fx.book_individual_ok(session["id"])
    fx.set_clock("2026-10-18T00:00:00Z")
    fx.run_epoch()
    assert fx.find_ticket(session["id"], ticket["id"])["status"] == "NO_SHOW"
    resp = api_client.ticket_decision(ticket["id"], {"action": "CHECK_IN"}, BOXOFFICE)
    validate_error(resp, ApiErrorId.ERR_TICKET_STATE)
    assert resp.status_code == 409


def test_session_overlap_adjacency_allowed_buffer_collides(api):
    """PRD section 3.7: "Each session occupies a half-open interval that begins
    at its `start_minute` and runs until thirty minutes after its scheduled end
    — the extra half hour is a turnover buffer — and a new session's
    occupied interval must not intersect the occupied interval of any
    existing `SCHEDULED` session on that venue and date." and "Because the
    intervals are half-open, a gap of exactly 30 minutes between
    one session's start and the previous session's end is allowed" and "An
    intersection is rejected with `ERR_SESSION_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/session_overlap_half_open_with_buffer
    """
    fx.reset_clock()
    fx.create_session()  # Hall A 2026-10-17 [600, 750)
    ok = api_client.create_attraction_session(
        {"venue_name": "Hall A", "session_date": "2026-10-17T00:00:00Z",
         "start_minute": 750, "duration_minutes": 60, "capacity_units": 50,
         "base_price_cents": 2000}, ADMIN)
    validate_success(ok, 201)  # gap of exactly 30 minutes is allowed
    bad = api_client.create_attraction_session(
        {"venue_name": "Hall A", "session_date": "2026-10-17T00:00:00Z",
         "start_minute": 749, "duration_minutes": 60, "capacity_units": 50,
         "base_price_cents": 2000}, ADMIN)
    validate_error(bad, ApiErrorId.ERR_SESSION_WINDOW_CONFLICT)
    assert bad.status_code == 409


def test_session_overlap_other_venue_never_collides(api):
    """PRD section 3.7: "a new session's occupied interval must not intersect
    the occupied interval of any existing `SCHEDULED` session on that venue and
    date" — the resource is the (venue, date) pair, so a different venue at the
    same minute is legal.

    Design: Difficulty/resource_temporal_overlap/session_overlap_half_open_with_buffer
    """
    fx.reset_clock()
    fx.create_session()  # Hall A 2026-10-17 [600, 750)
    other = api_client.create_attraction_session(
        {"venue_name": "Hall B", "session_date": "2026-10-17T00:00:00Z",
         "start_minute": 600, "duration_minutes": 120, "capacity_units": 50,
         "base_price_cents": 2000}, ADMIN)
    data = validate_success(other, 201)
    assert data["status"] == "SCHEDULED"


def _three_pricing_sessions():
    """Hall A Saturday 2026-10-17 (capacity 100); Hall B and Hall C Monday
    2026-10-19 (capacity 50 each); all base 2000, start 600, duration 120."""
    a = fx.create_session(venue="Hall A", date="2026-10-17T00:00:00Z", capacity_units=100)
    b = fx.create_session(venue="Hall B", date="2026-10-19T00:00:00Z", capacity_units=50)
    c = fx.create_session(venue="Hall C", date="2026-10-19T00:00:00Z", capacity_units=50)
    return a, b, c


def test_ticket_price_stacks_weekend_and_group_tiers_low_fill(api):
    """PRD section 3.7: "The dynamic price multiplies the session's
    `base_price_cents` by three factors." — Saturday individual at ratio 0:
    round_half_up(2000 x 0.9 x 1.0 x 1.15) = 2070; Monday group of 25 at
    ratio 0: unit round_half_up(2000 x 0.9 x 0.85 x 1.0) = 1530, x 25 = 38250.

    Design: Difficulty/combinatorial_formula/ticket_price_stacks_capacity_tier_group_discount_and_weekend
    """
    fx.reset_clock()
    ses_a, ses_b, _ = _three_pricing_sessions()
    t1 = fx.book_individual_ok(ses_a["id"])
    assert t1["price_cents"] == 2070
    ga = fx.book_group_ok(ses_b["id"], 25, "Lincoln Elementary")
    assert ga["price_cents"] == 38250  # 1530 x 25


def test_ticket_price_tier_boundaries_at_half_and_eighty_percent(api):
    """PRD section 3.7: "below the low-tier ceiling `LOW_TIER_CEIL` of 0.5 the
    factor is the low multiplier `LOW_MULT`, 0.9; from 0.5 up to but not
    including the high-tier floor `HIGH_TIER_FLOOR` of 0.8 the factor is 1.0; at
    0.8 or above the factor is the high multiplier `HIGH_MULT`, 1.25." — ratio
    exactly 25/50 = 0.5 prices at 1.0 (group of 10: 20000); ratio exactly
    40/50 = 0.8 prices at 1.25 (individual: 2500).

    Design: Difficulty/combinatorial_formula/ticket_price_stacks_capacity_tier_group_discount_and_weekend
    """
    fx.reset_clock()
    _, ses_b, ses_c = _three_pricing_sessions()
    fx.book_group_ok(ses_b["id"], 25, "Lincoln Elementary")     # booked 25
    gb = fx.book_group_ok(ses_c["id"], 40, "Jefferson High")
    assert gb["price_cents"] == 61200  # unit 1530 x 40 (ratio 0 -> 0.9 x 0.85)
    t2 = fx.book_individual_ok(ses_c["id"])
    assert t2["price_cents"] == 2500   # ratio 40/50 == 0.8 -> 1.25 tier
    assert fx.get_session(ses_c["id"])["booked_units"] == 41
    # ratio exactly 0.5 falls in the [0.5, 0.8) tier; group of 10 -> 1.0
    g10 = fx.book_group_ok(ses_b["id"], 10, "Roosevelt Middle")
    assert g10["price_cents"] == 20000  # unit 2000 x 10


def test_session_booked_units_refund_rebook_conservation(api):
    """PRD section 3.7: "the session's `booked_units` is always the sum of
    `units` over its tickets in `CONFIRMED` or `CHECKED_IN` status — immediate
    consistency, maintained on every confirmation, promotion, refund,
    cancellation, and no-show" — refunding 20 and promoting 10 lands on exactly
    40 = 30 + 10, and the promoted group's price is computed "at the current
    booked ratio" (30/50 = 0.6 -> tier 1.0; group of 10 -> 1.0 -> 20000).

    Design: Difficulty/compensating_invariant/session_booked_units_refund_rebook_conservation
    """
    fx.reset_clock()
    session = fx.create_session(venue="Hall E", date="2026-10-19T00:00:00Z",
                                capacity_units=50)
    g1 = fx.book_group_ok(session["id"], 30, "Lincoln Elementary")
    g2 = fx.book_group_ok(session["id"], 20, "Roosevelt Middle")
    g3 = fx.book_group_ok(session["id"], 10, "Jefferson High")
    assert g3["status"] == "WAITLISTED"
    refunded = fx.ticket_decision_ok(g2["id"], "REFUND")
    assert refunded["status"] == "REFUNDED"
    promoted = fx.find_ticket(session["id"], g3["id"])
    assert promoted["status"] == "CONFIRMED"
    assert promoted["price_cents"] == 20000
    assert fx.get_session(session["id"])["booked_units"] == 40  # 30 + 10


def test_session_ticket_statuses_after_refund_and_promotion(api):
    """PRD section 3.7: "A refund moves the ticket to `REFUNDED`, subtracts its
    `units` from the session's `booked_units`, and then runs the **waitlist
    promotion cascade**" — afterwards the session lists 1 REFUNDED, 2 CONFIRMED,
    0 WAITLISTED.

    Design: Difficulty/compensating_invariant/session_booked_units_refund_rebook_conservation
    """
    fx.reset_clock()
    session = fx.create_session(venue="Hall E", date="2026-10-19T00:00:00Z",
                                capacity_units=50)
    g1 = fx.book_group_ok(session["id"], 30, "Lincoln Elementary")
    g2 = fx.book_group_ok(session["id"], 20, "Roosevelt Middle")
    g3 = fx.book_group_ok(session["id"], 10, "Jefferson High")
    fx.ticket_decision_ok(g2["id"], "REFUND")
    tickets = fx.list_session_tickets(session["id"])
    statuses = sorted(t["status"] for t in tickets)
    assert statuses == ["CONFIRMED", "CONFIRMED", "REFUNDED"]
    by_id = {t["id"]: t["status"] for t in tickets}
    assert by_id[g1["id"]] == "CONFIRMED"
    assert by_id[g2["id"]] == "REFUNDED"
    assert by_id[g3["id"]] == "CONFIRMED"
