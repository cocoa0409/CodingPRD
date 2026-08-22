"""Rotation draws for premium pitches: entries, the selector and the award."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_lottery_draw, assert_lottery_entry, assert_session_booking,
    create_lottery_draw_payload, create_lottery_entry_payload,
    set_clock, create_zone, create_pitch,
    setup_active_permit, setup_district_pitch_and_active_permit,
    open_draw, enter_draw, execute_draw, uphold_new_complaint,
    read_draw, read_entry, read_permit, read_performer, list_bookings,
    make_officer_headers, make_performer_headers, make_resident_headers,
    OFFICER_ALPHA,
)
from test_helpers.api_client import api_client


PREMIUM_PITCH = dict(code="RP-P1", tier="PREMIUM", noise_cap_db=84,
                     amplification_allowed=True, max_session_minutes=90,
                     daily_session_cap=2, premium_slots_per_draw=1)


def _premium_draw(season_year=2026):
    ctx = setup_district_pitch_and_active_permit(pitch_overrides=PREMIUM_PITCH)
    ctx["draw"] = open_draw(ctx["pitch"]["id"], season_year=season_year,
                            slot_start_at="2026-08-20T12:00:00Z",
                            slot_end_at="2026-08-20T13:30:00Z",
                            entry_deadline_at="2026-08-15T00:00:00Z")
    return ctx


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check /
#          lottery_execute_with_empty_candidate_pool_voids_the_draw
# ---------------------------------------------------------------------------

def test_execute_with_an_empty_candidate_set_voids_the_draw(api):
    """PRD §3.7: "A draw with entries but no eligible ones is not an error. When
    the candidate set turns out to be empty, the draw moves `OPEN → VOID` with a
    200 response, every entry still `SUBMITTED` becomes `LOST` with
    `rank_position` null, `winner_count` is set to 0, `executed_at` is stamped,
    no session is minted and the pitch slot is released."
    PRD §3.7: "An entry is a candidate when it belongs to this draw, its own
    `status` is still `SUBMITTED`, its permit's lifecycle axis is `ACTIVE`, its
    permit's compliance axis is `CLEAR`, its permit's `season_year` equals the
    draw's `season_year`, the holder's `standing` is `GOOD` or `WATCH`, the
    permit's `season_minutes_used` plus the slot's whole-minute duration is less
    than or equal to the 1800-minute season cap, and no invoice on that permit is
    `PAST_DUE`."

    Design: Difficulty/boundary_precision_check/lottery_execute_with_empty_candidate_pool_voids_the_draw
    """
    ctx = _premium_draw(season_year=2027)
    entry = enter_draw(ctx["draw"]["id"], ctx["permit"]["id"],
                       ctx["performer"]["id"])
    set_clock("2026-08-16T00:00:00Z")

    resp = api.execute_lottery_draw(ctx["draw"]["id"],
                                    make_officer_headers(OFFICER_ALPHA))
    draw = validate_success(resp, 200)
    assert_lottery_draw(draw)
    assert draw["status"] == "VOID", \
        "a draw whose only entry fails the season_year clause voids rather than errors"
    assert draw["winner_count"] == 0
    assert draw["entry_count"] == 1

    reread = read_entry(entry["id"])
    assert reread["status"] == "LOST"
    assert reread["rank_position"] is None
    assert reread["priority_band"] is None


def test_voided_execution_mints_no_booking_and_awards_no_premium_win(api):
    """PRD §3.7: "A draw with entries but no eligible ones is not an error. When
    the candidate set turns out to be empty, the draw moves `OPEN → VOID` with a
    200 response, every entry still `SUBMITTED` becomes `LOST` with
    `rank_position` null, `winner_count` is set to 0, `executed_at` is stamped,
    no session is minted and the pitch slot is released."
    PRD §3.7: "Each minted booking in turn adds its `duration_minutes` to the
    permit's `season_minutes_used` and increments the permit's `version`, and
    each win increments the holder's `premium_wins_this_season` by one."

    Design: Difficulty/boundary_precision_check/lottery_execute_with_empty_candidate_pool_voids_the_draw
    """
    ctx = _premium_draw(season_year=2027)
    entry = enter_draw(ctx["draw"]["id"], ctx["permit"]["id"],
                       ctx["performer"]["id"])
    set_clock("2026-08-16T00:00:00Z")
    execute_draw(ctx["draw"]["id"])

    assert read_permit(ctx["permit"]["id"])["season_minutes_used"] == 0
    assert read_performer(ctx["performer"]["id"])["premium_wins_this_season"] == 0
    _, meta = validate_paginated(api.list_session_bookings(
        make_officer_headers(), params={"lottery_entry_id": entry["id"]}))
    assert meta["total_count"] == 0, "no session is minted on a voided draw"


# ---------------------------------------------------------------------------
# Queue B: the award cascade and the selector
# ---------------------------------------------------------------------------

def test_execute_awards_the_single_slot_and_mints_a_lottery_booking(api):
    """PRD §3.7: "Third it awards. The first `winner_slots` entries of the ranked
    candidate list become `WON` and receive `rank_position` 1 upward in order."
    PRD §3.7: "Each win cascades. The winning entry mints a session booking on
    the draw's pitch with `origin` `LOTTERY` and `status` `RESERVED`, whose
    `start_at` and `end_at` are the draw's `slot_start_at` and `slot_end_at`,
    whose `amplification_planned` is copied from the permit's
    `amplification_endorsed`, and whose `lottery_entry_id` points back at the
    winning entry."
    PRD §3.7: "Each candidate is assigned a `priority_band` from the holder's
    `premium_wins_this_season`: band 1 when the holder has won nothing this
    season, band 2 when they have won exactly once, band 3 when they have won
    twice or more."

    Design: Corner/state_machines/corner_lottery_execute_awards_winner_and_mints_lottery_booking
    """
    ctx = _premium_draw()
    entry = enter_draw(ctx["draw"]["id"], ctx["permit"]["id"],
                       ctx["performer"]["id"])
    set_clock("2026-08-16T00:00:00Z")

    draw = execute_draw(ctx["draw"]["id"])
    assert draw["status"] == "DRAWN"
    assert draw["winner_count"] == 1

    won = read_entry(entry["id"])
    assert_lottery_entry(won)
    assert won["status"] == "WON"
    assert won["rank_position"] == 1
    assert won["priority_band"] == 1

    bookings = list_bookings(lottery_entry_id=entry["id"])
    assert len(bookings) == 1
    booking = bookings[0]
    assert_session_booking(booking)
    assert booking["origin"] == "LOTTERY"
    assert booking["status"] == "RESERVED"
    assert booking["pitch_id"] == ctx["pitch"]["id"]
    assert booking["duration_minutes"] == 90

    assert read_permit(ctx["permit"]["id"])["season_minutes_used"] == 90
    assert read_performer(ctx["performer"]["id"])["premium_wins_this_season"] == 1


def test_ranking_falls_to_conduct_score_then_to_the_earlier_filed_entry(api):
    """PRD §3.7: "Candidates are then sorted by `priority_band` ascending — band
    1 first — and within a band by the holder's live `conduct_score` descending,
    so the better-behaved performer outranks the worse. Where both keys tie
    exactly, the earlier-filed entry wins: the tie-break is the entry's own
    `created_at` ascending, and the entry's `id` is never consulted."
    PRD §3.7: "The remaining candidates become `LOST` and receive their own
    `rank_position`, continuing the same numbering from `winner_slots` plus
    one."

    Design: Corner/cross_cutting_layers/corner_lottery_ranking_uses_conduct_desc_then_created_at_tiebreak
    """
    zone = create_zone()
    pitch = create_pitch(zone["id"], **PREMIUM_PITCH)
    ada = setup_active_permit(zone["id"])
    ben = setup_active_permit(
        zone["id"], performer_overrides={"legal_name": "Ben Torrance",
                                         "stage_name": "Ben T",
                                         "email": "ben@example.org"})
    cara = setup_active_permit(
        zone["id"], performer_overrides={"legal_name": "Cara Idle",
                                         "stage_name": "Cara I",
                                         "email": "cara@example.org"})
    uphold_new_complaint(cara["permit"]["id"], "MODERATE", "DIRECT",
                         resident="resident-1", category="NOISE",
                         description="Loud rehearsal")

    draw = open_draw(pitch["id"], season_year=2026,
                     slot_start_at="2026-08-20T12:00:00Z",
                     slot_end_at="2026-08-20T13:30:00Z",
                     entry_deadline_at="2026-08-15T00:00:00Z")
    entry_a = enter_draw(draw["id"], ada["permit"]["id"], ada["performer"]["id"])
    entry_b = enter_draw(draw["id"], ben["permit"]["id"], ben["performer"]["id"])
    entry_c = enter_draw(draw["id"], cara["permit"]["id"], cara["performer"]["id"])

    assert read_performer(ada["performer"]["id"])["conduct_score"] == 100
    assert read_performer(ben["performer"]["id"])["conduct_score"] == 100
    assert read_performer(cara["performer"]["id"])["conduct_score"] == 88

    set_clock("2026-08-16T00:00:00Z")
    executed = execute_draw(draw["id"])
    assert executed["status"] == "DRAWN"
    assert executed["winner_count"] == 1

    first, second, third = (read_entry(entry_a["id"]), read_entry(entry_b["id"]),
                            read_entry(entry_c["id"]))
    assert first["status"] == "WON" and first["rank_position"] == 1, \
        "the earlier-filed of the two tied band-1 entries takes the slot"
    assert second["status"] == "LOST" and second["rank_position"] == 2
    assert third["status"] == "LOST" and third["rank_position"] == 3, \
        "the lower conduct_score ranks last inside the band"
    assert [first["priority_band"], second["priority_band"],
            third["priority_band"]] == [1, 1, 1]

    assert read_permit(ada["permit"]["id"])["season_minutes_used"] == 90
    assert read_permit(ben["permit"]["id"])["season_minutes_used"] == 0
    assert read_permit(cara["permit"]["id"])["season_minutes_used"] == 0
    assert read_performer(ada["performer"]["id"])["premium_wins_this_season"] == 1


# ---------------------------------------------------------------------------
# Queue B: draw and entry preconditions
# ---------------------------------------------------------------------------

def test_opening_a_draw_on_a_standard_pitch_is_refused(api):
    """PRD §3.7: "The pitch's `tier` must be `PREMIUM`; opening a draw on a
    standard pitch is refused with `ERR_PITCH_NOT_PREMIUM`."

    Design: Corner/errors/corner_error_pitch_not_premium_on_draw_creation
    """
    zone = create_zone()
    pitch = create_pitch(zone["id"], code="RP-01", tier="STANDARD",
                         noise_cap_db=82, amplification_allowed=True)

    resp = api.create_lottery_draw(
        create_lottery_draw_payload(pitch["id"], season_year=2026,
                                    slot_start_at="2026-08-20T12:00:00Z",
                                    slot_end_at="2026-08-20T13:00:00Z",
                                    entry_deadline_at="2026-08-15T00:00:00Z"),
        make_officer_headers(OFFICER_ALPHA))
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PITCH_NOT_PREMIUM)

    _, meta = validate_paginated(api.list_lottery_draws(
        make_officer_headers(), params={"pitch_id": pitch["id"]}))
    assert meta["total_count"] == 0


def test_entry_filed_after_the_deadline_is_refused(api):
    """PRD §3.7: "Entry requires the permit's lifecycle axis to be `ACTIVE`
    (`ERR_PERMIT_NOT_ACTIVE`) and its compliance axis not `SUSPENDED`
    (`ERR_PERMIT_SUSPENDED`), and it must be filed no later than the draw's
    `entry_deadline_at`; an entry filed at or after that instant is refused with
    `ERR_ENTRY_DEADLINE_PASSED`."

    Design: Corner/errors/corner_error_entry_deadline_passed_blocks_new_entries
    """
    ctx = _premium_draw()
    set_clock("2026-08-16T00:00:00Z")

    resp = api.create_lottery_entry(
        ctx["draw"]["id"], create_lottery_entry_payload(ctx["permit"]["id"]),
        make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_ENTRY_DEADLINE_PASSED)

    draw = read_draw(ctx["draw"]["id"])
    assert draw["entry_count"] == 0
    assert draw["status"] == "OPEN"


def test_execute_before_the_deadline_is_refused(api):
    """PRD §3.7: "Execution is the officer's act and is only possible after the
    deadline has passed: calling it at or before `entry_deadline_at` is refused
    with `ERR_ENTRY_DEADLINE_NOT_PASSED`."

    Design: Corner/errors/corner_error_entry_deadline_not_passed_blocks_execute
    """
    ctx = _premium_draw()

    resp = api.execute_lottery_draw(ctx["draw"]["id"],
                                    make_officer_headers(OFFICER_ALPHA))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_ENTRY_DEADLINE_NOT_PASSED)

    draw = read_draw(ctx["draw"]["id"])
    assert draw["status"] == "OPEN"
    assert draw["executed_at"] is None


def test_execute_on_a_draw_with_no_entries_at_all_is_refused(api):
    """PRD §3.7: "A draw that has attracted no entries at all — `entry_count` of
    zero — cannot be executed either, and is refused with
    `ERR_NO_ELIGIBLE_ENTRIES`, leaving the draw `OPEN`."
    PRD §3.7: "This is the case that must be distinguished carefully from a draw
    with no entries at all, which is the `ERR_NO_ELIGIBLE_ENTRIES` refusal
    above."

    Design: Corner/errors/corner_error_no_eligible_entries_when_draw_has_zero_entries
    """
    ctx = _premium_draw()
    set_clock("2026-08-16T00:00:00Z")

    resp = api.execute_lottery_draw(ctx["draw"]["id"],
                                    make_officer_headers(OFFICER_ALPHA))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ENTRIES)

    draw = read_draw(ctx["draw"]["id"])
    assert draw["status"] == "OPEN"
    assert draw["winner_count"] == 0


def test_the_same_permit_may_not_enter_one_draw_twice(api):
    """PRD §3.7: "A permit may appear at most once in a draw — a second attempt
    is refused with `ERR_DUPLICATE_LOTTERY_ENTRY` — and a permit carrying a
    `PAST_DUE` invoice may not enter at all (`ERR_INVOICE_PAST_DUE`)."

    Design: Corner/errors/corner_error_duplicate_lottery_entry_rejected
    """
    ctx = _premium_draw()
    enter_draw(ctx["draw"]["id"], ctx["permit"]["id"], ctx["performer"]["id"])

    resp = api.create_lottery_entry(
        ctx["draw"]["id"], create_lottery_entry_payload(ctx["permit"]["id"]),
        make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOTTERY_ENTRY)

    assert read_draw(ctx["draw"]["id"])["entry_count"] == 1
    _, meta = validate_paginated(api.list_lottery_entries(
        make_officer_headers(), params={"draw_id": ctx["draw"]["id"]}))
    assert meta["total_count"] == 1


def test_entry_listings_serve_both_of_the_entrys_foreign_keys(api):
    """PRD §3.7: "A filed entry starts in `SUBMITTED` with `priority_band` and
    `rank_position` both null, and it increments the draw's `entry_count` and the
    draw's `version`."
    PRD §3.7: "A new draw starts `OPEN` with `entry_count` 0, `winner_count` 0,
    `executed_at` null, and `winner_slots` copied from the pitch's
    `premium_slots_per_draw`."
    PRD §2.11: "Draw listings filter on `pitch_id`, on `status` and on
    `season_year`; entry listings filter on `draw_id`, on `permit_id` and on
    `status`."

    Design: Corner/endpoints/corner_lottery_entries_list_filters_by_draw_and_permit
    """
    ctx = _premium_draw()
    entry = enter_draw(ctx["draw"]["id"], ctx["permit"]["id"],
                       ctx["performer"]["id"])
    assert entry["status"] == "SUBMITTED"
    assert entry["priority_band"] is None
    assert entry["rank_position"] is None

    draw = read_draw(ctx["draw"]["id"])
    assert draw["entry_count"] == 1
    assert draw["winner_slots"] == 1

    by_draw, draw_meta = validate_paginated(api.list_lottery_entries(
        make_officer_headers(), params={"draw_id": ctx["draw"]["id"]}))
    assert draw_meta["total_count"] == 1 and by_draw[0]["id"] == entry["id"]

    by_permit, permit_meta = validate_paginated(api.list_lottery_entries(
        make_officer_headers(), params={"permit_id": ctx["permit"]["id"]}))
    assert permit_meta["total_count"] == 1 and by_permit[0]["id"] == entry["id"]

    _, pitch_meta = validate_paginated(api.list_lottery_draws(
        make_officer_headers(), params={"pitch_id": ctx["pitch"]["id"]}))
    assert pitch_meta["total_count"] == 1


def test_a_resident_may_not_open_a_rotation_draw(api):
    """PRD §2.1: "If both headers are well formed but the named role is not one
    of the roles authorised for the endpoint being called (the authorised set for
    each endpoint is listed in section 4), the request is rejected with
    `ERR_FORBIDDEN_ROLE` and HTTP 403."
    PRD §3.7: "An officer opens a draw on a pitch by naming the `pitch_id`, the
    `season_year` the slot belongs to (between 2026 and 2035 inclusive), the
    `slot_start_at` and `slot_end_at` bounds of the premium slot being allocated,
    and the `entry_deadline_at` after which entries close."

    Design: Corner/roles/corner_resident_cannot_open_a_lottery_draw
    """
    zone = create_zone()
    pitch = create_pitch(zone["id"], code="RP-P1", tier="PREMIUM",
                         noise_cap_db=84, amplification_allowed=True,
                         max_session_minutes=90)

    resp = api.create_lottery_draw(
        create_lottery_draw_payload(pitch["id"], season_year=2026,
                                    slot_start_at="2026-08-20T12:00:00Z",
                                    slot_end_at="2026-08-20T13:30:00Z",
                                    entry_deadline_at="2026-08-15T00:00:00Z"),
        make_resident_headers("resident-1"))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    _, meta = validate_paginated(api.list_lottery_draws(
        make_officer_headers(), params={"pitch_id": pitch["id"]}))
    assert meta["total_count"] == 0
