"""Two intervals that look alike and behave oppositely.

A policy term is half-open, so the term that starts exactly where the incumbent
term expires goes on risk beside it, while a term reaching one single day back
into the incumbent is refused at bind. A buffered activity window is closed, so
two athlete footprints that meet at one instant collide — and each side of that
comparison is widened by its own sport's travel buffer, which is why one athlete
enrolled under two sports can be blocked from a pool session by a ball game on a
different policy.
"""
from test_helpers import (
    ApiErrorId,
    activate_policy,
    activities_for_policy,
    add_participant,
    bind_policy,
    create_league,
    create_sanctioned_activity_payload,
    create_sport_classification,
    enroll_participant,
    make_league_admin_headers,
    make_program_admin_headers,
    quote_policy,
    read_league,
    read_policy,
    schedule_activity,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _fairhaven_league_and_baseball():
    """The Fairhaven alliance and its BASEBALL_U12 classification."""
    league = create_league(
        name="Fairhaven Baseball Alliance",
        league_code="FBA-050",
        state_code="NY",
        governing_body_code="USYSA",
        contact_email="admin@fba.example",
    )
    sport = create_sport_classification("baseball")
    return league, sport


def test_baseball_term_starting_on_the_incumbents_expiration_date_binds_alongside_it(api):
    """PRD §2.11: "A **policy term** is the half-open interval running from `term_effective_date` inclusive to `term_expiration_date` exclusive."
    PRD §2.11: "A date equal to the effective date is inside the term; a date equal to the expiration date is outside it."
    PRD §2.11: "Two terms that merely touch — one term's expiration date equal to the next term's effective date — do not overlap, and both may be bound."
    PRD §3.2: "Binding requires the policy to be in `QUOTED`, the holding league to be `SANCTIONED` (otherwise `ERR_LEAGUE_NOT_SANCTIONED`), the declared `enrolled_participant_count` to be at least the sport's `minimum_participants` (otherwise `ERR_MINIMUM_PARTICIPANTS_NOT_MET`), and no other policy for the same league-and-sport pairing whose `status` is `BOUND`, `ACTIVE` or `RUN_OFF` to hold a term intersecting this one (otherwise `ERR_POLICY_TERM_OVERLAP`)."
    PRD §3.2: "Because terms are half-open, a prior term whose expiration date equals this term's effective date does not intersect and both may be bound."
    PRD §3.2: "On success the whole premium build-up is recomputed from scratch, `status` moves `QUOTED → BOUND`, the holding league's `in_force_policy_count` increases by one, and posture is recomputed."

    Design: Difficulty/resource_temporal_overlap/policy_terms_are_half_open_so_abutting_terms_bind_but_one_day_overlap_fails
    """
    league, sport = _fairhaven_league_and_baseball()

    incumbent = quote_policy(
        league["id"],
        sport["id"],
        term_effective_date="2026-03-01",
        term_expiration_date="2027-03-01",
        enrolled_participant_count=404,
    )
    bind_policy(incumbent["id"])

    abutting = quote_policy(
        league["id"],
        sport["id"],
        term_effective_date="2027-03-01",
        term_expiration_date="2028-03-01",
        enrolled_participant_count=410,
    )
    assert abutting["status"] == "QUOTED", (
        "the successor term is created as a quote and the overlap rule is only "
        f"applied at bind, got status {abutting['status']}"
    )

    bound = validate_success(
        api.bind_league_policy(abutting["id"], make_program_admin_headers()), 200
    )
    assert bound["status"] == "BOUND", (
        "an effective date equal to the incumbent's expiration date lies outside "
        f"the incumbent's half-open term, so the successor binds, got {bound['status']}"
    )

    assert read_policy(incumbent["id"])["status"] == "BOUND", (
        "the incumbent term is untouched by the successor's bind"
    )
    assert read_league(league["id"])["in_force_policy_count"] == 2, (
        "both abutting terms are in force at once, so in_force_policy_count "
        f"counts 2, got {read_league(league['id'])['in_force_policy_count']}"
    )

    rows, meta = validate_paginated(
        api.list_league_policies(
            make_program_admin_headers(), {"league_id": league["id"], "status": "BOUND"}
        )
    )
    assert meta["total_count"] == 2, (
        f"both touching terms are BOUND, got total_count {meta['total_count']}"
    )
    assert sorted(row["id"] for row in rows) == sorted(
        [incumbent["id"], abutting["id"]]
    ), "the two BOUND rows are the incumbent term and the term that abuts it"


def test_baseball_term_reaching_one_day_back_into_a_bound_term_is_refused_at_bind(api):
    """PRD §2.11: "A **policy term** is the half-open interval running from `term_effective_date` inclusive to `term_expiration_date` exclusive."
    PRD §2.11: "A date equal to the effective date is inside the term; a date equal to the expiration date is outside it."
    PRD §3.2: "Binding requires the policy to be in `QUOTED`, the holding league to be `SANCTIONED` (otherwise `ERR_LEAGUE_NOT_SANCTIONED`), the declared `enrolled_participant_count` to be at least the sport's `minimum_participants` (otherwise `ERR_MINIMUM_PARTICIPANTS_NOT_MET`), and no other policy for the same league-and-sport pairing whose `status` is `BOUND`, `ACTIVE` or `RUN_OFF` to hold a term intersecting this one (otherwise `ERR_POLICY_TERM_OVERLAP`)."
    PRD §3.2: "Because terms are half-open, a prior term whose expiration date equals this term's effective date does not intersect and both may be bound."

    Design: Difficulty/resource_temporal_overlap/policy_terms_are_half_open_so_abutting_terms_bind_but_one_day_overlap_fails
    """
    league, sport = _fairhaven_league_and_baseball()

    incumbent = quote_policy(
        league["id"],
        sport["id"],
        term_effective_date="2026-03-01",
        term_expiration_date="2027-03-01",
        enrolled_participant_count=404,
    )
    bind_policy(incumbent["id"])

    abutting = quote_policy(
        league["id"],
        sport["id"],
        term_effective_date="2027-03-01",
        term_expiration_date="2028-03-01",
        enrolled_participant_count=410,
    )
    bind_policy(abutting["id"])

    # One single day earlier than the abutting term: 2027-02-28 is still inside the
    # incumbent's half-open term [2026-03-01, 2027-03-01).
    overlapping = quote_policy(
        league["id"],
        sport["id"],
        term_effective_date="2027-02-28",
        term_expiration_date="2028-02-28",
        enrolled_participant_count=420,
    )
    assert overlapping["status"] == "QUOTED", (
        "the intersecting term is quotable; the overlap rule fires only at bind, "
        f"got status {overlapping['status']}"
    )

    validate_error(
        api.bind_league_policy(overlapping["id"], make_program_admin_headers()),
        ApiErrorId.ERR_POLICY_TERM_OVERLAP.value,
        409,
    )

    assert read_policy(overlapping["id"])["status"] == "QUOTED", (
        "a refused bind leaves the term exactly where it was, in QUOTED"
    )
    assert read_league(league["id"])["in_force_policy_count"] == 2, (
        "only the incumbent and the abutting term are in force, so "
        "in_force_policy_count stays at 2"
    )

    rows, meta = validate_paginated(
        api.list_league_policies(
            make_program_admin_headers(), {"league_id": league["id"], "status": "BOUND"}
        )
    )
    assert meta["total_count"] == 2, (
        "the refused term never joined the BOUND set, so exactly 2 rows remain, "
        f"got total_count {meta['total_count']}"
    )
    assert overlapping["id"] not in [row["id"] for row in rows], (
        "the term that intersects a bound term must not appear among the BOUND rows"
    )


def _glenview_two_sport_athlete_with_a_pending_ball_game():
    """One athlete enrolled under both an ACTIVE baseball term and an ACTIVE swim
    term, with a baseball game already on the calendar awaiting its sanction.

    The ball game runs 18:00 to 20:30 and inherits the baseball buffer of 60
    minutes, so its collision footprint is the closed interval [17:00, 21:30].
    """
    set_clock("2026-03-05T00:00:00Z")
    league = create_league(
        name="Glenview Multi-Sport Association",
        league_code="GMA-051",
        state_code="MN",
        governing_body_code="USYSA",
        contact_email="admin@gma.example",
    )
    baseball = create_sport_classification("baseball")
    swim = create_sport_classification("swim")
    assert baseball["travel_buffer_minutes"] == 60, (
        "the baseball classification carries a 60-minute travel buffer, got "
        f"{baseball['travel_buffer_minutes']}"
    )
    assert swim["travel_buffer_minutes"] == 30, (
        "the swim classification carries a 30-minute travel buffer, got "
        f"{swim['travel_buffer_minutes']}"
    )

    baseball_policy = quote_policy(
        league["id"],
        baseball["id"],
        term_effective_date="2026-03-01",
        term_expiration_date="2027-03-01",
        enrolled_participant_count=404,
    )
    bind_policy(baseball_policy["id"])
    baseball_policy = activate_policy(baseball_policy["id"])

    swim_policy = quote_policy(
        league["id"],
        swim["id"],
        term_effective_date="2026-03-01",
        term_expiration_date="2027-03-01",
        enrolled_participant_count=40,
    )
    bind_policy(swim_policy["id"])
    swim_policy = activate_policy(swim_policy["id"])

    athlete = add_participant(
        league["id"],
        first_name="Rowan",
        last_name="Kelleher",
        date_of_birth="2012-10-05",
        guardian_email="g17@gma.example",
    )
    enroll_participant(
        athlete["id"], baseball_policy["id"], league["id"], enrolled_on_date="2026-03-05"
    )
    enroll_participant(
        athlete["id"], swim_policy["id"], league["id"], enrolled_on_date="2026-03-05"
    )

    ball_game = schedule_activity(
        baseball_policy["id"],
        league["id"],
        activity_type="GAME",
        venue_name="Glenview Diamond 1",
        starts_at="2026-07-11T18:00:00Z",
        ends_at="2026-07-11T20:30:00Z",
    )
    return {
        "league": league,
        "baseball_policy": baseball_policy,
        "swim_policy": swim_policy,
        "athlete": athlete,
        "ball_game": ball_game,
    }


def test_swim_practice_whose_buffered_window_touches_a_pending_ball_game_is_refused(api):
    """PRD §2.11: "A **buffered activity window**, used only for detecting collisions between activities that share an athlete, widens the closed window symmetrically by that activity's own `travel_buffer_minutes` on each side, and the resulting intervals are also closed."
    PRD §2.11: "Two buffered windows that merely touch at a single instant *do* collide."
    PRD §3.4: "The optional `travel_buffer_minutes` may be supplied to widen this particular activity's collision footprint; when it is omitted, the activity inherits the governing sport classification's own `travel_buffer_minutes` as its default."
    PRD §3.4: "The candidate activity's window is widened symmetrically by the candidate's own `travel_buffer_minutes`, once before `starts_at` and once after `ends_at`."
    PRD §3.4: "Every activity it is compared against is widened by **its own** buffer, not the candidate's; two activities with different buffers therefore contribute different footprints."
    PRD §3.4: "The comparison set is assembled by walking from the candidate's policy to the athletes enrolled under it, then out from each of those athletes to every other policy they are also enrolled under, and collecting every activity of those policies whose `status` is `PENDING_SANCTION` or `SANCTIONED`."
    PRD §3.4: "Two widened windows collide when the candidate's widened start is at or before the other's widened end **and** the other's widened start is at or before the candidate's widened end — both intervals being closed, so windows that merely touch at a single instant do collide."
    PRD §3.4: "Any collision refuses the request with `ERR_PARTICIPANT_ACTIVITY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/participant_activity_windows_are_closed_and_buffered_per_activity_across_policies
    """
    world = _glenview_two_sport_athlete_with_a_pending_ball_game()

    assert world["ball_game"]["status"] == "PENDING_SANCTION", (
        "the ball game is still awaiting its official's decision, which does not "
        f"remove it from the collision comparison set, got {world['ball_game']['status']}"
    )
    assert world["ball_game"]["travel_buffer_minutes"] == 60, (
        "the ball game inherited the baseball classification's 60-minute buffer, got "
        f"{world['ball_game']['travel_buffer_minutes']}"
    )
    assert activities_for_policy(world["swim_policy"]["id"]) == [], (
        "the swim term carries no activity yet"
    )

    # Widened by the swim buffer of 30 minutes the candidate is [21:30, 23:30], and
    # the ball game widened by its own 60 minutes is [17:00, 21:30]: the two closed
    # intervals meet at exactly 21:30.
    validate_error(
        api.create_sanctioned_activity(
            create_sanctioned_activity_payload(
                world["swim_policy"]["id"],
                activity_type="PRACTICE",
                venue_name="Glenview Aquatic Center",
                starts_at="2026-07-11T22:00:00Z",
                ends_at="2026-07-11T23:00:00Z",
            ),
            make_league_admin_headers(world["league"]["id"]),
        ),
        ApiErrorId.ERR_PARTICIPANT_ACTIVITY_CONFLICT.value,
        409,
    )

    assert activities_for_policy(world["swim_policy"]["id"]) == [], (
        "the refused practice was never written, so the swim term still carries no "
        "activity at all"
    )
    remaining = activities_for_policy(world["baseball_policy"]["id"])
    assert len(remaining) == 1, (
        f"the ball game is the only activity on the baseball term, got {len(remaining)}"
    )
    assert remaining[0]["status"] == "PENDING_SANCTION", (
        "the ball game is untouched by the refused practice, got "
        f"{remaining[0]['status']}"
    )


def test_swim_practice_shifted_one_minute_clear_of_the_ball_game_footprint_is_scheduled(api):
    """PRD §2.11: "A **buffered activity window**, used only for detecting collisions between activities that share an athlete, widens the closed window symmetrically by that activity's own `travel_buffer_minutes` on each side, and the resulting intervals are also closed."
    PRD §2.11: "Two buffered windows that merely touch at a single instant *do* collide."
    PRD §3.4: "The optional `travel_buffer_minutes` may be supplied to widen this particular activity's collision footprint; when it is omitted, the activity inherits the governing sport classification's own `travel_buffer_minutes` as its default."
    PRD §3.4: "Every new activity starts in `PENDING_SANCTION`, with `sanctioning_official_id` and `rejection_reason` both null."
    PRD §3.4: "Every activity it is compared against is widened by **its own** buffer, not the candidate's; two activities with different buffers therefore contribute different footprints."
    PRD §3.4: "Two widened windows collide when the candidate's widened start is at or before the other's widened end **and** the other's widened start is at or before the candidate's widened end — both intervals being closed, so windows that merely touch at a single instant do collide."
    PRD §3.4: "Any collision refuses the request with `ERR_PARTICIPANT_ACTIVITY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/participant_activity_windows_are_closed_and_buffered_per_activity_across_policies
    """
    world = _glenview_two_sport_athlete_with_a_pending_ball_game()

    assert world["ball_game"]["travel_buffer_minutes"] == 60, (
        "the ball game inherited the baseball classification's 60-minute buffer, got "
        f"{world['ball_game']['travel_buffer_minutes']}"
    )

    # Shifted by one minute the candidate widens to [21:31, 23:31], which starts
    # strictly after the ball game's widened end of 21:30.
    practice = validate_success(
        api.create_sanctioned_activity(
            create_sanctioned_activity_payload(
                world["swim_policy"]["id"],
                activity_type="PRACTICE",
                venue_name="Glenview Aquatic Center",
                starts_at="2026-07-11T22:01:00Z",
                ends_at="2026-07-11T23:01:00Z",
            ),
            make_league_admin_headers(world["league"]["id"]),
        ),
        201,
    )

    assert practice["status"] == "PENDING_SANCTION", (
        f"a newly scheduled practice starts in PENDING_SANCTION, got {practice['status']}"
    )
    assert practice["sanctioning_official_id"] is None, (
        "no official has decided the new practice yet, so sanctioning_official_id "
        f"is null, got {practice['sanctioning_official_id']!r}"
    )
    assert practice["rejection_reason"] is None, (
        f"a newly scheduled practice carries no rejection_reason, got {practice['rejection_reason']!r}"
    )
    assert practice["travel_buffer_minutes"] == 30, (
        "the practice inherited the swim classification's 30-minute buffer, got "
        f"{practice['travel_buffer_minutes']}"
    )

    swim_rows = activities_for_policy(world["swim_policy"]["id"])
    assert len(swim_rows) == 1, (
        f"the swim term now carries exactly one activity, got {len(swim_rows)}"
    )
    assert swim_rows[0]["id"] == practice["id"]
    assert swim_rows[0]["status"] == "PENDING_SANCTION", (
        f"the stored practice reads PENDING_SANCTION, got {swim_rows[0]['status']}"
    )
