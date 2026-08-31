"""Results, postponement fallout, forfeits and the playoff bracket."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_four_decimal_places,
    assert_playoff_seed,
    assert_same_instant,
    find_seed,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

C4A_FIELD = [
    {"name": "Gale Prep", "classification": "C4A", "region_code": "R-EAST"},
    {"name": "Hollis High", "classification": "C4A", "region_code": "R-EAST"},
    {"name": "Iver Academy", "classification": "C4A", "region_code": "R-WEST"},
    {"name": "Juno High", "classification": "C4A", "region_code": "R-WEST"},
    {"name": "Kestrel High", "classification": "C4A", "region_code": "R-NORTH"},
]

C5A_FIELD = [
    {"name": "Alder High", "classification": "C5A", "region_code": "R-NORTH"},
    {"name": "Bramble High", "classification": "C5A", "region_code": "R-NORTH"},
    {"name": "Cedar High", "classification": "C5A", "region_code": "R-SOUTH"},
    {"name": "Dune High", "classification": "C5A", "region_code": "R-SOUTH"},
]


def _track_bracket():
    """Two forfeited TRACK contests plus a fifth school that plays nothing."""
    return fx.setup_seeded_season(
        schools=C4A_FIELD,
        contests=[
            (0, 1, "2026-09-12T18:00:00Z", "2026-09-12T20:00:00Z", 1),
            (2, 3, "2026-09-13T18:00:00Z", "2026-09-13T20:00:00Z", 3),
        ],
        season_overrides={"sport": "TRACK", "classification": "C4A",
                          "sport_tier": "TIER_B"},
    )


def test_seeding_writes_the_blended_rating_not_the_in_season_reading(api):
    """PRD §3.9: "`power_rating` is 65 percent of `raw_win_pct` plus 35 percent of
    `opponent_avg_win_pct`, rounded half up to four decimal places."
    PRD §3.9: "while a season is still standing at `REGULAR_SEASON`, the in-season
    reading of a school's `power_rating` ignores strength of schedule entirely and is
    simply its `raw_win_pct` rounded half up to four decimal places. The blended
    figure is only what the seeding run writes."
    PRD §3.9: "`opponent_avg_win_pct` is the arithmetic mean of the frozen
    `raw_win_pct` values of the distinct schools this school met in the snapshot,
    rounded half up to four decimal places, and is 0.0000 when that opponent set is
    empty."

    Design: Difficulty/dual_variant_calc/power_rating_final_seeding_diverges_from_in_season_reading
    """
    drawn = _track_bracket()
    gale, hollis = drawn["schools"][0], drawn["schools"][1]

    gale_seed = find_seed(drawn["seeds"], gale["id"])
    hollis_seed = find_seed(drawn["seeds"], hollis["id"])

    assert_playoff_seed(gale_seed)
    assert gale_seed["raw_win_pct"] == pytest.approx(1.0000, abs=0.00005)
    assert gale_seed["opponent_avg_win_pct"] == pytest.approx(0.0000, abs=0.00005)
    assert gale_seed["power_rating"] == pytest.approx(0.6500, abs=0.00005)
    assert hollis_seed["raw_win_pct"] == pytest.approx(0.0000, abs=0.00005)
    assert hollis_seed["opponent_avg_win_pct"] == pytest.approx(1.0000, abs=0.00005)
    assert hollis_seed["power_rating"] == pytest.approx(0.3500, abs=0.00005)
    for seed in drawn["seeds"]:
        assert_four_decimal_places(seed["power_rating"], "power_rating")
        assert seed["power_rating"] != seed["raw_win_pct"], (
            "the blended rating must differ from the in-season raw reading"
        )
    assert drawn["season"]["seeded_school_count"] == 4
    assert drawn["season"]["status"] == "SEEDING_LOCKED"


def test_a_school_with_no_snapshot_contests_receives_no_bracket_row(api):
    """PRD §3.9: "The season's `seeded_school_count` is set to the number of rows
    minted; its `unseeded_school_count` is set to the number of schools whose
    `classification` equals the season's and which hold zero contests in the frozen
    snapshot — those schools receive no bracket row at all, which is the
    empty-collection edge of the run."
    PRD §3.9: "Bracket rows can be read back per season, ordered by `seed_number`
    ascending, or per school across every season the school has been seeded in."

    Design: Difficulty/dual_variant_calc/power_rating_final_seeding_diverges_from_in_season_reading
    """
    drawn = _track_bracket()
    kestrel = drawn["schools"][4]

    response = api.list_school_playoff_seeds(kestrel["id"], fx.ADMIN, {"limit": 100})

    rows, _meta = validate_paginated(response)
    assert response.status_code == 200
    assert rows == [], "a school outside the frozen snapshot holds no bracket row"
    assert drawn["season"]["unseeded_school_count"] == 1


def _soccer_bracket():
    """Five forfeited SOCCER contests giving Alder 2-0, Bramble 1-2, Cedar 1-2, Dune 1-1."""
    return fx.setup_seeded_season(
        schools=C5A_FIELD,
        contests=[
            (0, 1, "2026-09-05T18:00:00Z", "2026-09-05T20:00:00Z", 1),
            (0, 2, "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z", 2),
            (1, 2, "2026-10-05T18:00:00Z", "2026-10-05T20:00:00Z", 2),
            (3, 1, "2026-10-20T18:00:00Z", "2026-10-20T20:00:00Z", 1),
            (2, 3, "2026-11-04T18:00:00Z", "2026-11-04T20:00:00Z", 3),
        ],
        clock="2026-09-02T09:00:00Z",
        season_overrides={"sport": "SOCCER", "classification": "C5A",
                          "sport_tier": "TIER_B"},
    )


def test_strength_of_schedule_reads_the_frozen_win_percentage_table(api):
    """PRD §3.9: "`raw_win_pct` is `wins` divided by the sum of `wins` and `losses`,
    rounded half up to four decimal places, and is 0.0000 when that sum is zero. This
    table is frozen at this point and is what every later step reads."
    PRD §3.9: "This step reads only the frozen step-3 table, never a rating computed
    in step 5 and never a value recomputed after any seed has been assigned."
    PRD §3.9: "Recomputing opponents' win percentages after step 5 — the naive
    fixed-point reading — yields different ratings and a different bracket, and is
    wrong."

    Design: Difficulty/combinatorial_formula/seeding_freezes_opponent_win_pct_table_before_power_ratings
    """
    drawn = _soccer_bracket()
    alder, bramble, cedar, dune = drawn["schools"]

    expected = {
        alder["id"]: (1.0000, 0.3333, 0.7667, 1),
        dune["id"]: (0.5000, 0.3333, 0.4417, 2),
        bramble["id"]: (0.3333, 0.6111, 0.4305, 3),
        cedar["id"]: (0.3333, 0.6111, 0.4305, 4),
    }
    for school_id, (raw, opponent, power, seed_number) in expected.items():
        seed = find_seed(drawn["seeds"], school_id)
        assert seed["raw_win_pct"] == pytest.approx(raw, abs=0.00005)
        assert seed["opponent_avg_win_pct"] == pytest.approx(opponent, abs=0.00005)
        assert seed["power_rating"] == pytest.approx(power, abs=0.00005)
        assert seed["seed_number"] == seed_number


def test_head_to_head_separates_the_pair_level_on_power_rating(api):
    """PRD §3.9: "Where two schools are level, the following criteria are applied in
    order, stopping at the first that separates the pair: higher `raw_win_pct`; then
    head-to-head, meaning that if the two met in the snapshot, the winner of their
    latest meeting by `starts_at` ranks higher (for a forfeited meeting the awarded
    side is the winner), and if they never met this criterion separates nothing; then
    fewer `forfeit_losses`; then higher `opponent_avg_win_pct`; then the earlier
    `created_at` of the school row itself."
    PRD §3.9: "Each seed records in `tiebreak_trace` which criterion separated it
    from the row immediately above it — `RAW_WIN_PCT`, `HEAD_TO_HEAD`,
    `FORFEIT_LOSSES`, `OPP_AVG_WIN_PCT`, or `CREATED_AT` — while a pair separated by
    the `power_rating` comparison itself records `POWER_RATING`."

    Design: Difficulty/combinatorial_formula/seeding_freezes_opponent_win_pct_table_before_power_ratings
    """
    drawn = _soccer_bracket()
    bramble, cedar = drawn["schools"][1], drawn["schools"][2]

    bramble_seed = find_seed(drawn["seeds"], bramble["id"])
    cedar_seed = find_seed(drawn["seeds"], cedar["id"])

    assert bramble_seed["seed_number"] == 3
    assert cedar_seed["seed_number"] == 4
    assert cedar_seed["tiebreak_trace"] == "HEAD_TO_HEAD", (
        "Bramble beat Cedar in their only meeting, so head-to-head separates them"
    )
    assert bramble_seed["forfeit_losses"] == 2
    assert cedar_seed["forfeit_losses"] == 2
    assert drawn["season"]["seeded_school_count"] == 4
    assert drawn["season"]["unseeded_school_count"] == 0


def _school_on_the_brink_of_probation():
    """North High carries one forfeit and holds a PROVISIONAL_ELIGIBLE athlete."""
    set_clock("2026-09-02T09:00:00Z")
    north = fx.create_school(name="North High", fee_cap_cents=20000)
    south = fx.create_school(name="South High", region_code="R-SOUTH")
    season = fx.create_season(required_officials=1)
    fx.open_season_to_regular(season["id"])
    student = fx.create_student(north["id"], full_name="Eli Braun",
                                birth_date="2009-02-18", grade_level=11,
                                residency_verified=True,
                                residency_verified_on="2026-08-10")
    fx.post_academic_record(student["id"], north["id"], gpa_prior_period=3.500,
                            gpa_current_period=3.500, credits_prior_period=3,
                            credits_current_period=3)
    case = fx.create_case(north["id"], student["id"], season["id"])
    fx.file_all_clearance_documents(case["id"], north["id"])
    case = fx.evaluate_case(case["id"])
    first = fx.create_contest(season["id"], north["id"], south["id"],
                              "2026-09-05T18:00:00Z", "2026-09-05T20:00:00Z")
    fx.forfeit_contest(first["id"], north["id"],
                       forfeit_note="insufficient eligible roster")
    second = fx.create_contest(season["id"], north["id"], south["id"],
                               "2026-09-25T18:00:00Z", "2026-09-25T20:00:00Z")
    return {"north": north, "south": south, "season": season,
            "case": case, "second_contest": second}


def test_second_forfeit_moves_the_school_from_good_standing_to_probation(api, admin_headers):
    """PRD §3.9: "the contest moves to `FORFEITED`, `forfeiting_school_id` is
    recorded, the non-forfeiting side is credited a score of 1 and the forfeiting
    side a score of 0, `result_recorded_at` is stamped with the clock instant, and
    the forfeiting school's `forfeit_count` increments by 1."
    PRD §3.9: "the school's sanction posture is re-derived — a `forfeit_count` that
    has reached 2 while still below 4 moves the school `GOOD_STANDING → PROBATION`,
    and a `forfeit_count` that has reached 4 moves it `PROBATION → SUSPENDED`."

    Design: Difficulty/transitive_cascade/second_forfeit_cascades_through_probation_to_provisional_revocation
    """
    ctx = _school_on_the_brink_of_probation()
    assert ctx["case"]["status"] == "PROVISIONAL_ELIGIBLE"

    forfeited = validate_success(
        api.forfeit_contest(ctx["second_contest"]["id"],
                            {"forfeiting_school_id": ctx["north"]["id"],
                             "forfeit_note": "second roster shortfall"},
                            admin_headers),
        200,
    )

    assert forfeited["status"] == "FORFEITED"
    assert forfeited["forfeiting_school_id"] == ctx["north"]["id"]
    assert forfeited["home_score"] == 0
    assert forfeited["away_score"] == 1
    school = fx.read_school(ctx["north"]["id"])
    assert school["forfeit_count"] == 2
    assert school["sanction_status"] == "PROBATION"


def test_probation_knocks_the_provisional_case_back_to_under_review(api, admin_headers):
    """PRD §3.9: "every eligibility case whose athlete belongs to that school and
    which is standing at `PROVISIONAL_ELIGIBLE` is knocked back `PROVISIONAL_ELIGIBLE
    → UNDER_REVIEW` with `provisional_revoked_at` stamped at the clock instant."
    PRD §3.6: "The first is a school sanction: when a forfeit pushes the athlete's
    school from `GOOD_STANDING` into `PROBATION`, every case of that school's
    students standing at `PROVISIONAL_ELIGIBLE` is knocked back to `UNDER_REVIEW`
    with `provisional_revoked_at` stamped, which is described as link three of
    Cascade B in §3.9."

    Design: Difficulty/transitive_cascade/second_forfeit_cascades_through_probation_to_provisional_revocation
    """
    ctx = _school_on_the_brink_of_probation()

    validate_success(
        api.forfeit_contest(ctx["second_contest"]["id"],
                            {"forfeiting_school_id": ctx["north"]["id"]},
                            admin_headers),
        200,
    )

    case = fx.read_case(ctx["case"]["id"])
    assert case["status"] == "UNDER_REVIEW"
    assert case["provisional_revoked_at"] is not None


def _one_forfeited_basketball_contest():
    return fx.setup_seeded_season(
        schools=[
            {"name": "Larch High", "classification": "C1A", "region_code": "R-EAST"},
            {"name": "Maple High", "classification": "C1A", "region_code": "R-EAST"},
            {"name": "Nettle High", "classification": "C1A", "region_code": "R-WEST"},
        ],
        contests=[(0, 1, "2026-09-12T18:00:00Z", "2026-09-12T20:00:00Z", 1)],
        season_overrides={"sport": "BASKETBALL", "classification": "C1A",
                          "sport_tier": "TIER_C"},
    )


def test_seeding_counts_the_contestless_school_as_unseeded(api, admin_headers):
    """PRD §3.9: "The season's `seeded_school_count` is set to the number of rows
    minted; its `unseeded_school_count` is set to the number of schools whose
    `classification` equals the season's and which hold zero contests in the frozen
    snapshot — those schools receive no bracket row at all, which is the
    empty-collection edge of the run."
    PRD §3.9: "Once every contest of a season has reached `PLAYED` or `FORFEITED`,
    the association draws the bracket, and this is the only way a season reaches
    `SEEDING_LOCKED`."

    Design: Difficulty/boundary_precision_check/seeding_counts_a_contestless_school_as_unseeded_and_returns_an_empty_seed_list
    """
    drawn = _one_forfeited_basketball_contest()
    nettle = drawn["schools"][2]

    season = fx.read_season(drawn["season"]["id"])
    empty = api.list_school_playoff_seeds(nettle["id"], admin_headers, {"limit": 100})

    assert season["seeded_school_count"] == 2
    assert season["unseeded_school_count"] == 1
    assert season["status"] == "SEEDING_LOCKED"
    rows, _meta = validate_paginated(empty)
    assert empty.status_code == 200
    assert rows == []


def test_the_two_seeded_rows_carry_the_snapshot_tallies_and_ratings(api, admin_headers):
    """PRD §3.9: "For every school holding at least one contest in the snapshot,
    count `wins` (the higher score, or the awarded side of a forfeit), `losses` (the
    lower score, or being the recorded `forfeiting_school_id`), and `forfeit_losses`
    (the subset of losses charged as forfeits)."
    PRD §3.9: "`seed_number` runs 1 upward in the resulting order."
    PRD §3.9: "`power_rating` is 65 percent of `raw_win_pct` plus 35 percent of
    `opponent_avg_win_pct`, rounded half up to four decimal places."

    Design: Difficulty/boundary_precision_check/seeding_counts_a_contestless_school_as_unseeded_and_returns_an_empty_seed_list
    """
    drawn = _one_forfeited_basketball_contest()
    larch, maple = drawn["schools"][0], drawn["schools"][1]

    seeds, _meta = validate_paginated(
        api.list_season_playoff_seeds(drawn["season"]["id"], admin_headers,
                                      {"limit": 100})
    )

    assert len(seeds) == 2
    larch_seed = find_seed(seeds, larch["id"])
    maple_seed = find_seed(seeds, maple["id"])
    assert (larch_seed["wins"], larch_seed["losses"]) == (1, 0)
    assert larch_seed["raw_win_pct"] == pytest.approx(1.0000, abs=0.00005)
    assert larch_seed["opponent_avg_win_pct"] == pytest.approx(0.0000, abs=0.00005)
    assert larch_seed["power_rating"] == pytest.approx(0.6500, abs=0.00005)
    assert larch_seed["seed_number"] == 1
    assert (maple_seed["wins"], maple_seed["losses"]) == (0, 1)
    assert maple_seed["forfeit_losses"] == 1
    assert maple_seed["raw_win_pct"] == pytest.approx(0.0000, abs=0.00005)
    assert maple_seed["opponent_avg_win_pct"] == pytest.approx(1.0000, abs=0.00005)
    assert maple_seed["power_rating"] == pytest.approx(0.3500, abs=0.00005)
    assert maple_seed["seed_number"] == 2


def test_a_bracket_row_is_reachable_from_the_season_and_from_the_school(api):
    """PRD §3.9: "Each seeded school gets exactly one bracket row, carrying the
    `sport_season_id`, the `school_id`, and all of the figures above."
    PRD §3.9: "Bracket rows can be read back per season, ordered by `seed_number`
    ascending, or per school across every season the school has been seeded in."

    Design: Corner/entities/playoff_seed_is_reachable_from_both_of_its_graph_endpoints
    """
    drawn = fx.setup_seeded_season(
        schools=[
            {"name": "Larch High", "classification": "C1A", "region_code": "R-EAST"},
            {"name": "Maple High", "classification": "C1A", "region_code": "R-EAST"},
        ],
        contests=[(0, 1, "2026-09-12T18:00:00Z", "2026-09-12T20:00:00Z", 1)],
        season_overrides={"sport": "BASKETBALL", "classification": "C1A",
                          "sport_tier": "TIER_C"},
    )
    larch = drawn["schools"][0]

    from_school, _meta = validate_paginated(
        api.list_school_playoff_seeds(larch["id"],
                                      fx.make_director_headers(larch["id"]),
                                      {"limit": 100})
    )
    from_season, _meta2 = validate_paginated(
        api.list_season_playoff_seeds(drawn["season"]["id"], fx.ADMIN, {"limit": 100})
    )

    assert len(from_school) == 1
    row = from_school[0]
    assert row["sport_season_id"] == drawn["season"]["id"]
    assert row["school_id"] == larch["id"]
    assert row["seed_number"] == 1
    assert len(from_season) == 2
    assert row["id"] in [seed["id"] for seed in from_season]


def test_posting_a_result_on_a_scheduled_contest_is_an_invalid_state(api):
    """PRD §3.9: "The home school's athletic director closes a `CONFIRMED` contest
    by posting `home_score` and `away_score`."
    PRD §2.6: "The target row's current state admits the requested transition —
    otherwise `ERR_INVALID_STATE` (409) on any transition endpoint that has no more
    specific state error."

    Design: Corner/state_machines/posting_a_result_on_a_scheduled_contest_returns_invalid_state
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-25T21:00:00Z", season_overrides={"required_officials": 1}
    )
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z")

    response = api.record_contest_result(
        contest["id"], {"home_score": 21, "away_score": 14},
        fx.make_director_headers(ctx["home"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = fx.read_contest(contest["id"])
    assert after["status"] == "SCHEDULED"
    assert after["home_score"] is None
    assert after["result_recorded_at"] is None


def test_recording_the_result_completes_the_trip_without_moving_the_ledger(api):
    """PRD §3.9: "On success the two scores are written, `result_recorded_at` is
    stamped with the clock instant, the contest moves `CONFIRMED → PLAYED`, and every
    trip on it standing at `APPROVED` moves to `COMPLETED` with the school's
    `release_minutes_used` untouched."
    PRD §3.8: "When the parent contest's result is recorded, every trip on it
    standing at `APPROVED` moves to `COMPLETED`, and `release_minutes_used` is left
    unchanged — a completed trip stays inside the conserved sum."

    Design: Corner/state_machines/recording_a_result_completes_the_trip_without_moving_release_minutes
    """
    ctx = fx.setup_approved_trip(confirm=True)
    assert fx.read_school(ctx["home"]["id"])["release_minutes_used"] == 60
    fx.set_clock("2026-09-20T20:30:00Z")

    played = validate_success(
        api.record_contest_result(ctx["contest"]["id"],
                                  {"home_score": 21, "away_score": 14},
                                  fx.make_director_headers(ctx["home"]["id"])),
        200,
    )

    assert played["status"] == "PLAYED"
    assert played["home_score"] == 21
    assert played["away_score"] == 14
    assert_same_instant(played["result_recorded_at"], "2026-09-20T20:30:00Z",
                        "result_recorded_at")
    assert fx.read_transport(ctx["trip"]["id"])["status"] == "COMPLETED"
    assert fx.read_school(ctx["home"]["id"])["release_minutes_used"] == 60


def test_seeding_is_blocked_while_a_contest_is_still_open(api, admin_headers):
    """PRD §3.9: "Two guards apply: if any contest of the season is still at
    `SCHEDULED`, `OFFICIALS_ASSIGNED`, or `CONFIRMED`, the answer is
    `ERR_SEASON_HAS_OPEN_CONTESTS`, and if the season has no completed contest at
    all, the answer is `ERR_SEEDING_EMPTY_SNAPSHOT`."

    Design: Corner/state_machines/seeding_while_a_contest_is_still_open_returns_season_has_open_contests
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-02T09:00:00Z", season_overrides={"required_officials": 1},
        open_season=False,
    )
    first = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                              "2026-09-05T18:00:00Z", "2026-09-05T20:00:00Z",
                              headers=admin_headers)
    fx.forfeit_contest(first["id"], ctx["away"]["id"])
    fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                      "2026-09-25T18:00:00Z", "2026-09-25T20:00:00Z",
                      headers=admin_headers)
    fx.open_season_to_regular(ctx["season"]["id"])

    response = api.seed_sport_season(ctx["season"]["id"], admin_headers)

    validate_error(response, ApiErrorId.ERR_SEASON_HAS_OPEN_CONTESTS.value, 409)
    season = fx.read_season(ctx["season"]["id"])
    assert season["status"] == "REGULAR_SEASON"
    assert season["seeded_school_count"] == 0
    seeds, _meta = validate_paginated(
        api.list_season_playoff_seeds(ctx["season"]["id"], admin_headers)
    )
    assert seeds == []


def test_seeding_a_season_with_no_contests_reports_an_empty_snapshot(api, admin_headers):
    """PRD §3.9: "Two guards apply: if any contest of the season is still at
    `SCHEDULED`, `OFFICIALS_ASSIGNED`, or `CONFIRMED`, the answer is
    `ERR_SEASON_HAS_OPEN_CONTESTS`, and if the season has no completed contest at
    all, the answer is `ERR_SEEDING_EMPTY_SNAPSHOT`."
    PRD §3.9: "The snapshot is exactly the contests of this season standing at
    `PLAYED` or `FORFEITED`."

    Design: Corner/errors/seeding_a_season_with_no_contests_returns_seeding_empty_snapshot
    """
    set_clock("2026-09-10T09:00:00Z")
    season = fx.create_season()
    fx.open_season_to_regular(season["id"])

    response = api.seed_sport_season(season["id"], admin_headers)

    validate_error(response, ApiErrorId.ERR_SEEDING_EMPTY_SNAPSHOT.value, 409)
    assert fx.read_season(season["id"])["status"] == "REGULAR_SEASON"


def test_forfeit_cancels_a_requested_trip_and_leaves_the_ledger_at_zero(api, admin_headers):
    """PRD §3.9: "Independently of those three links, every trip on the forfeited
    contest standing at `REQUESTED` or `APPROVED` is cancelled with
    `cancelled_reason` `CONTEST_HOLD_CASCADE`, and each formerly approved trip
    returns its `release_minutes` to its school."
    PRD §3.8: "When a contest is held, postponed, or forfeited, the cascades of §3.2
    and §3.9 cancel its trips with `cancelled_reason` `CONTEST_HOLD_CASCADE`; a trip
    cancelled that way from `APPROVED` returns its release minutes to the school,
    while one cancelled from `REQUESTED` has nothing to return."

    Design: Corner/state_machines/forfeiting_a_contest_cancels_its_requested_trip_and_leaves_minutes_untouched
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-10T09:00:00Z",
        home_overrides={"name": "North High", "school_day_end_utc_hhmm": "17:00",
                        "bus_fleet_size": 2},
        season_overrides={"required_officials": 1}, open_season=False,
    )
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z")
    trip = fx.create_transport(contest["id"], ctx["home"]["id"], travel_minutes=45,
                               bus_count=1)

    forfeited = validate_success(
        api.forfeit_contest(contest["id"],
                            {"forfeiting_school_id": ctx["home"]["id"],
                             "forfeit_note": "roster shortfall"},
                            admin_headers),
        200,
    )

    assert forfeited["status"] == "FORFEITED"
    school = fx.read_school(ctx["home"]["id"])
    assert school["forfeit_count"] == 1
    assert school["sanction_status"] == "GOOD_STANDING"
    stored = fx.read_transport(trip["id"])
    assert stored["status"] == "CANCELLED"
    assert stored["cancelled_reason"] == "CONTEST_HOLD_CASCADE"
    assert stored["release_minutes"] == 60
    assert school["release_minutes_used"] == 0


def test_a_score_posted_before_tipoff_is_refused(api):
    """PRD §3.9: "The logical clock must have reached or passed the contest's
    `starts_at`; a score posted before then is refused with
    `ERR_RESULT_BEFORE_TIPOFF`."

    Design: Corner/errors/posting_a_result_before_tipoff_is_rejected
    """
    ctx = fx.setup_confirmed_contest()
    assert ctx["contest"]["status"] == "CONFIRMED"

    response = api.record_contest_result(
        ctx["contest"]["id"], {"home_score": 21, "away_score": 14},
        fx.make_director_headers(ctx["home"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_RESULT_BEFORE_TIPOFF.value, 409)
    after = fx.read_contest(ctx["contest"]["id"])
    assert after["status"] == "CONFIRMED"
    assert after["home_score"] is None


def test_forfeit_count_agrees_with_the_forfeiting_school_filter(api, admin_headers):
    """PRD §2.10: "`forfeit_count` itself is the count of contests recording that
    school as `forfeiting_school_id`."
    PRD §3.7: "Contests can be listed and filtered by `sport_season_id`, by
    `home_school_id`, by `away_school_id`, by `forfeiting_school_id`, and by
    `status`; officiating assignments can be listed and filtered by `contest_id`, by
    `official_id`, and by `status`."

    Design: Corner/cross_cutting_layers/school_forfeit_counter_agrees_with_the_forfeiting_school_filter
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-02T09:00:00Z",
        home_overrides={"name": "Alpha High"},
        away_overrides={"name": "Beta High", "region_code": "R-SOUTH"},
        open_season=False,
    )
    first = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                              "2026-09-05T18:00:00Z", "2026-09-05T20:00:00Z",
                              headers=admin_headers, travel_miles=20)
    second = fx.create_contest(ctx["season"]["id"], ctx["away"]["id"], ctx["home"]["id"],
                               "2026-09-25T18:00:00Z", "2026-09-25T20:00:00Z",
                               headers=admin_headers, travel_miles=20)
    fx.forfeit_contest(first["id"], ctx["home"]["id"])

    charged = validate_success(
        api.forfeit_contest(second["id"], {"forfeiting_school_id": ctx["home"]["id"]},
                            admin_headers),
        200,
    )

    assert fx.read_school(ctx["home"]["id"])["forfeit_count"] == 2
    charged_rows, _meta = validate_paginated(
        api.list_contests(admin_headers,
                          {"forfeiting_school_id": ctx["home"]["id"], "limit": 100})
    )
    assert {row["id"] for row in charged_rows} == {first["id"], second["id"]}
    assert fx.read_school(ctx["away"]["id"])["forfeit_count"] == 0
    clean_rows, _meta2 = validate_paginated(
        api.list_contests(admin_headers,
                          {"forfeiting_school_id": ctx["away"]["id"], "limit": 100})
    )
    assert clean_rows == []
    assert charged["home_score"] == 1
    assert charged["away_score"] == 0


def test_forfeit_cascade_is_visible_in_the_same_request_cycle(api, admin_headers):
    """PRD §3.9: "the contest moves to `FORFEITED`, `forfeiting_school_id` is
    recorded, the non-forfeiting side is credited a score of 1 and the forfeiting
    side a score of 0, `result_recorded_at` is stamped with the clock instant, and
    the forfeiting school's `forfeit_count` increments by 1."
    PRD §4: "Successful responses always carry the created or updated resource in
    `data`, except the logical-clock endpoint, which returns its own small summary
    object."
    PRD §3.9: "the school's sanction posture is re-derived — a `forfeit_count` that
    has reached 2 while still below 4 moves the school `GOOD_STANDING → PROBATION`,
    and a `forfeit_count` that has reached 4 moves it `PROBATION → SUSPENDED`."

    Design: Corner/consistency_model/forfeit_cascade_is_observable_in_the_same_request_cycle
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-02T09:00:00Z",
        home_overrides={"name": "Alpha High"},
        away_overrides={"name": "Beta High", "region_code": "R-SOUTH"},
        open_season=False,
    )
    first = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                              "2026-09-05T18:00:00Z", "2026-09-05T20:00:00Z",
                              headers=admin_headers, travel_miles=20)
    fx.forfeit_contest(first["id"], ctx["home"]["id"])
    second = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                               "2026-09-25T18:00:00Z", "2026-09-25T20:00:00Z",
                               headers=admin_headers, travel_miles=20)

    body = validate_success(
        api.forfeit_contest(second["id"], {"forfeiting_school_id": ctx["home"]["id"]},
                            admin_headers),
        200,
    )
    school = validate_success(api.get_school(ctx["home"]["id"], admin_headers), 200)

    assert body["status"] == "FORFEITED"
    assert body["forfeiting_school_id"] == ctx["home"]["id"]
    assert_same_instant(body["result_recorded_at"], "2026-09-02T09:00:00Z",
                        "result_recorded_at")
    assert school["sanction_status"] == "PROBATION"
    assert school["forfeit_count"] == 2
