"""Corner arithmetic: the thresholds, splits and filters the formulas turn on.

Every derived number in this system is computed by the server from primary
records, and most of the formulas have an edge that a plausible but wrong
implementation lands on the wrong side of.  This module walks those edges.

The carryover test of a bowler's entering average is inclusive at twenty-one
prior games, and it is re-derived from the stored prior-season record on every
bylaw amendment rather than frozen at enrolment.  Match points are decided game
by game and then on the series, and a level game hands each side half a point,
which is the only way a one-decimal figure ever arises.  A `VACANCY` slot and an
`ABSENTEE` slot both roll no ball yet behave oppositely: the vacancy scores the
bylaw `vacancy_score` per game against a handicap priced from `vacancy_average`,
the absentee scores nothing against a handicap priced from its own bowler's
average less `absentee_deduction`, and neither row ever enters any membership's
certified pins.  The dues ledger takes money the instant it is tendered while
the certified-to-date prize basis counts only weeks at or below the league's
certified week high-water mark.  And the four honor-score thresholds read
different expressions off one slot: an equality at three hundred, a closed band
at two hundred and ninety-eight through two hundred and ninety-nine, an
inclusive eight-hundred scratch floor and an inclusive seven-hundred floor that
adds three games' worth of the frozen handicap.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing.validators import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_identity,
    assert_points,
    assert_prize_money_invariant,
    expected_admin_fee_cents,
    expected_blended_average,
    expected_bowler_handicap,
    expected_reserve_cents,
    expected_team_handicap,
)
from test_helpers.constants import (
    BASE_BYLAWS,
    SERIES_HANDICAP_FLOOR,
    SERIES_SCRATCH_FLOOR,
    WEEK2_STARTS_AT,
)
from test_helpers.types import (
    AverageStatus,
    AwardApplicationStatus,
    AwardType,
    BasisVariant,
    CarryoverPolicy,
    EntryType,
    LeagueStatus,
    MatchStatus,
    MemberClass,
    PrizeFundStatus,
)

# ─── the shared bylaw configuration, quoted for the arithmetic below ───
HANDICAP_BASE = BASE_BYLAWS["handicap_base"]                 # 220
ADULT_PCT = BASE_BYLAWS["handicap_percentage"]               # 0.90
MAX_HANDICAP = BASE_BYLAWS["max_handicap_per_game"]           # 60
VACANCY_AVERAGE = BASE_BYLAWS["vacancy_average"]             # 120
VACANCY_SCORE = BASE_BYLAWS["vacancy_score"]                 # 120
ABSENTEE_DEDUCTION = BASE_BYLAWS["absentee_deduction"]       # 10
WEEKLY_DUES_CENTS = BASE_BYLAWS["weekly_dues_cents"]         # 1200
WEEKLY_EXPENSE_CENTS = BASE_BYLAWS["weekly_expense_cents"]   # 500
PRIZE_SHARE_CENTS = WEEKLY_DUES_CENTS - WEEKLY_EXPENSE_CENTS  # 700
PLACE_WEIGHTS = BASE_BYLAWS["prize_place_weights"]           # [0.60, 0.40]


# ─── reads a test asserts on, validated rather than lenient ───

def _league(scn: fx.Scenario) -> Dict[str, Any]:
    return validate_success(scn.api.get_league(scn.league_id, scn.secretary))


def _membership(scn: fx.Scenario, index: int) -> Dict[str, Any]:
    return validate_success(
        scn.api.get_membership(scn.membership_ids[index], scn.secretary)
    )


def _team(scn: fx.Scenario, index: int) -> Dict[str, Any]:
    return validate_success(scn.api.get_team(scn.team_ids[index], scn.secretary))


def _match(scn: fx.Scenario, index: int = 0) -> Dict[str, Any]:
    return validate_success(scn.api.get_match(scn.match_ids[index], scn.secretary))


def _prize_fund(scn: fx.Scenario) -> Dict[str, Any]:
    return validate_success(scn.api.get_prize_fund(scn.prize_fund_id(), scn.secretary))


def _slots(scn: fx.Scenario, match_index: int, team_index: int) -> List[Dict[str, Any]]:
    """This side's slots on this match, ordered by lineup position ascending."""
    rows, _meta = validate_paginated(
        scn.api.list_series_entries(
            scn.secretary,
            params={
                "match_id": scn.match_ids[match_index],
                "team_id": scn.team_ids[team_index],
                "limit": 100,
            },
        )
    )
    return sorted(rows, key=lambda row: row["position"])


def _slot_of(scn: fx.Scenario, membership_index: int, match_index: int = 0) -> Dict[str, Any]:
    """The slot on this match that names the given membership."""
    membership_id = scn.membership_ids[membership_index]
    by_membership = fx.slot_by_membership(scn, match_index)
    assert membership_id in by_membership, (
        f"membership {membership_id} occupies no slot on match {match_index}"
    )
    return by_membership[membership_id]


def _amend_bylaws(scn: fx.Scenario, **overrides: Any) -> Dict[str, Any]:
    """Re-adopt the whole bylaw set with one value bent, echoing the version."""
    return validate_success(
        scn.api.adopt_bylaws(
            scn.league_id,
            f.bylaws_payload(_league(scn)["version"], **overrides),
            scn.secretary,
        )
    )


# ─── the entering-average carryover floor (PRD §3.2, §3.6) ───
# Four deliberately different prior-season records against the same league:
# thirty games clears the twenty-one-game floor, twenty games is one short,
# twenty-one games hits the inclusive floor exactly, and the fourth bowler
# brings no prior average at all.
CARRYOVER_ROSTER: Tuple[fx.RosterSpec, ...] = (
    fx.RosterSpec("Cara Captain", MemberClass.ADULT, 180, 30, 0),
    fx.RosterSpec("Dan Bowler", MemberClass.ADULT, 195, 20, 0),
    fx.RosterSpec("Eve Captain", MemberClass.ADULT, 170, 21, 1),
    fx.RosterSpec("Fay Bowler", MemberClass.ADULT, None, 0, 1),
)


def test_entering_average_needs_twenty_one_prior_games_and_a_prior_average(
    api: ApiClient,
) -> None:
    """The three-part entering-average test is inclusive at twenty-one games.

    Enrolment copies `prior_season_average` into `entering_average` only when a
    prior average is present, `prior_season_games` is at least twenty-one and the
    league's `carryover_policy` is `PRIOR_SEASON_FULL` or `BLENDED`.  Twenty
    prior games is one short and yields null; exactly twenty-one clears the
    floor; a missing prior average yields null however many games came with it.
    No scoring data participates, and an unsanctioned bowler carries handicap 0.

    Design: Corner/calculations/corner_entering_average_game_floor_and_carryover_policy_switch
    """
    scn = fx.build_league(api, roster=CARRYOVER_ROSTER)

    league = _league(scn)
    assert_fields(
        league,
        status=LeagueStatus.BYLAWS_ADOPTED.value,
        carryover_policy=CarryoverPolicy.BLENDED.value,
        minimum_games_for_average=BASE_BYLAWS["minimum_games_for_average"],
    )

    thirty_games = _membership(scn, 0)
    assert_fields(
        thirty_games,
        prior_season_average=180,
        prior_season_games=30,
        entering_average=180,
        average_status=AverageStatus.PROVISIONAL.value,
        certified_games=0,
        certified_pins=0,
        handicap_per_game=0,
    )

    twenty_games = _membership(scn, 1)
    assert_fields(
        twenty_games,
        prior_season_average=195,
        prior_season_games=20,
        entering_average=None,
        handicap_per_game=0,
    )

    exactly_twenty_one = _membership(scn, 2)
    assert_fields(
        exactly_twenty_one,
        prior_season_average=170,
        prior_season_games=21,
        entering_average=170,
        handicap_per_game=0,
    )

    no_prior_record = _membership(scn, 3)
    assert_fields(
        no_prior_record,
        prior_season_average=None,
        prior_season_games=0,
        entering_average=None,
        handicap_per_game=0,
    )


def test_carryover_policy_switch_rederives_every_entering_average(
    api: ApiClient,
) -> None:
    """An amendment re-derives the entering average from the stored record.

    Amending `carryover_policy` to `NONE` fails the third part of the
    entering-average test, so every membership reads null even though its
    prior-season fields never changed; amending back to `PRIOR_SEASON_FULL`
    brings the same integers back, which is only possible if the value is
    re-derived rather than remembered.  Under `PRIOR_SEASON_FULL` a provisional
    `current_average` is the entering average substituted whole, and no
    amendment invents a certified game.

    Design: Corner/calculations/corner_entering_average_game_floor_and_carryover_policy_switch
    """
    scn = fx.build_league(api, roster=CARRYOVER_ROSTER)
    version_before = _league(scn)["version"]

    none_league = _amend_bylaws(scn, carryover_policy=CarryoverPolicy.NONE)
    assert_fields(
        none_league,
        status=LeagueStatus.BYLAWS_ADOPTED.value,
        carryover_policy=CarryoverPolicy.NONE.value,
        version=version_before + 1,
    )
    for index in range(4):
        membership = _membership(scn, index)
        assert_fields(
            membership,
            entering_average=None,
            current_average=None,
            certified_games=0,
            certified_pins=0,
        )

    restored = _amend_bylaws(scn, carryover_policy=CarryoverPolicy.PRIOR_SEASON_FULL)
    assert_fields(
        restored,
        carryover_policy=CarryoverPolicy.PRIOR_SEASON_FULL.value,
        version=version_before + 2,
    )
    assert_fields(
        _membership(scn, 0),
        entering_average=180,
        current_average=180,
        average_status=AverageStatus.PROVISIONAL.value,
        certified_games=0,
        certified_pins=0,
    )
    assert_fields(
        _membership(scn, 2), entering_average=170, current_average=170
    )
    for index in (1, 3):
        assert_fields(
            _membership(scn, index), entering_average=None, current_average=None
        )


# ─── the only scoreline where a game comes out exactly level ───
# Home scratch 400 plus the frozen team handicap 58 equals away scratch 359 plus
# the frozen 99, so game one splits; the away side takes game two, the home side
# takes game three and the series, for 2.5 against 1.5.
TIE_PINS: Dict[int, Tuple[int, int, int]] = {
    0: (200, 210, 220),
    1: (200, 210, 220),
    2: (180, 200, 175),
    3: (179, 200, 175),
}

# The four entering handicaps the shared roster carries into week one, each
# floored before the ceiling: 180 -> 36, 195 -> 22, 170 -> 45, 160 -> 54.
ENTERING_HANDICAPS: Tuple[int, ...] = tuple(
    expected_bowler_handicap(average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP)
    for average in (180, 195, 170, 160)
)


def test_a_level_game_hands_each_side_half_a_point(api: ApiClient) -> None:
    """A tied game splits, and the fourth point is decided on the series.

    Each side's game total is its slots' pins for that game plus the per-game
    team handicap frozen onto the match, and equal totals award half a point to
    each side.  Game one is level at 458 apiece, game two goes to the away side,
    game three and the series total go to the home side, so the four points
    divide 2.5 to 1.5 — a split no all-or-nothing rule can produce.

    Design: Corner/calculations/corner_match_points_tie_splits_half_a_point_per_game_and_on_series
    """
    scn = fx.build_open_match(api)

    before = _match(scn, 0)
    assert before["home_team_handicap_per_game"] == expected_team_handicap(
        ENTERING_HANDICAPS[0:2]
    ), "the home side's frozen handicap is 36 + 22"
    assert before["away_team_handicap_per_game"] == expected_team_handicap(
        ENTERING_HANDICAPS[2:4]
    ), "the away side's frozen handicap is 45 + 54"

    scored = validate_success(
        scn.api.record_scores(
            scn.match_ids[0],
            f.scores_payload(fx.score_entries_for(scn, 0, TIE_PINS)),
            scn.secretary,
        ),
        200,
    )
    assert scored["status"] == MatchStatus.SCORES_ENTERED.value
    assert_points(scored["home_points"], 2.5, "home_points")
    assert_points(scored["away_points"], 1.5, "away_points")
    assert_points(
        scored["home_points"] + scored["away_points"], 4.0, "total match points"
    )

    home_first = _slot_of(scn, 0)
    assert_fields(home_first, scratch_series=630, games_recorded=3)
    away_second = _slot_of(scn, 3)
    assert_fields(away_second, scratch_series=554, games_recorded=3)


def test_certification_keeps_the_split_and_absorbs_it_into_the_standings(
    api: ApiClient,
) -> None:
    """Certifying does not re-score the match, and the halves survive it.

    A team's `total_points` is the sum of its points over certified and forfeited
    matches, recorded to one decimal place, so the home side banks 2.5 and the
    away side 1.5.  The same certification turns the recorded pins into certified
    ones, so each bowler's blended provisional average and floored handicap move,
    and the roster team handicap is the sum of the floored integers.

    Design: Corner/calculations/corner_match_points_tie_splits_half_a_point_per_game_and_on_series
    """
    scn = fx.build_open_match(api)
    fx.enter_scores(scn, fx.score_entries_for(scn, 0, TIE_PINS), 0)

    certified = validate_success(
        scn.api.certify_match(scn.match_ids[0], {}, scn.secretary), 200
    )
    assert certified["status"] == MatchStatus.CERTIFIED.value
    assert_points(certified["home_points"], 2.5, "home_points after certification")
    assert_points(certified["away_points"], 1.5, "away_points after certification")

    # floor((180 * 30 + 630) / 33) == floor(182.72) == 182, handicap floor(34.2)
    first_average = expected_blended_average(180, 30, 630, 3)
    assert first_average == 182
    assert_fields(
        _membership(scn, 0),
        certified_games=3,
        certified_pins=630,
        current_average=first_average,
        average_status=AverageStatus.PROVISIONAL.value,
        handicap_per_game=expected_bowler_handicap(
            first_average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
        ),
    )
    # floor(6480 / 33) == floor(196.36) == 196, handicap floor(21.6)
    second_average = expected_blended_average(195, 30, 630, 3)
    assert second_average == 196
    assert_fields(
        _membership(scn, 1),
        certified_games=3,
        certified_pins=630,
        current_average=second_average,
        handicap_per_game=expected_bowler_handicap(
            second_average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
        ),
    )

    home_team = _team(scn, 0)
    assert_points(home_team["total_points"], 2.5, "home team total_points")
    assert home_team["total_scratch_pins"] == 1260, "630 + 630 scratch pins"
    assert home_team["team_handicap_per_game"] == expected_team_handicap(
        (
            expected_bowler_handicap(
                first_average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
            ),
            expected_bowler_handicap(
                second_average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
            ),
        )
    ), "the roster handicap sums per-bowler floored integers: 34 + 21"

    away_team = _team(scn, 1)
    assert_points(away_team["total_points"], 1.5, "away team total_points")
    assert away_team["total_scratch_pins"] == 1109, "555 + 554 scratch pins"
    third_average = expected_blended_average(170, 30, 555, 3)
    fourth_average = expected_blended_average(160, 30, 554, 3)
    assert away_team["team_handicap_per_game"] == expected_team_handicap(
        (
            expected_bowler_handicap(
                third_average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
            ),
            expected_bowler_handicap(
                fourth_average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
            ),
        )
    )


# ─── week one's certified figures under the shared score set ───
PRIOR_AVERAGES: Tuple[int, ...] = (180, 195, 170, 160)
WEEK1_SCRATCH: Tuple[int, ...] = (540, 720, 480, 450)
WEEK1_AVERAGES: Tuple[int, ...] = tuple(
    expected_blended_average(prior, 30, scratch, 3)
    for prior, scratch in zip(PRIOR_AVERAGES, WEEK1_SCRATCH)
)                                                     # 180, 199, 169, 159
WEEK1_HANDICAPS: Tuple[int, ...] = tuple(
    expected_bowler_handicap(average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP)
    for average in WEEK1_AVERAGES
)                                                     # 36, 18, 45, 54

# A vacancy is priced from the bylaw vacancy average at the adult percentage and
# clamped by the ceiling: min(60, floor((220 - 120) * 0.90)) == min(60, 90) == 60.
VACANCY_HANDICAP = expected_bowler_handicap(
    VACANCY_AVERAGE, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
)
# An absentee is priced from its own bowler's basis average less the deduction:
# min(60, floor((220 - (199 - 10)) * 0.90)) == floor(27.9) == 27.
ABSENTEE_HANDICAP = expected_bowler_handicap(
    WEEK1_AVERAGES[1] - ABSENTEE_DEDUCTION, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
)


def _week_two_with_a_vacancy_and_an_absentee(api: ApiClient) -> fx.Scenario:
    """Week one certified, then week two's two sides filled with one empty slot
    and one absent bowler.

    The shared configuration demands two occupied positions for a legal lineup,
    so the league first amends `legal_lineup_minimum` to 1 at a special meeting
    while it is under way.  On week two the second team is at home.
    """
    scn = fx.build_certified_match(api)
    _amend_bylaws(scn, legal_lineup_minimum=1)
    fx.submit_lineup(
        scn,
        1,
        [
            f.slot(1, membership_id=scn.membership_ids[2]),
            f.vacancy_slot(2),
        ],
        match_index=1,
    )
    fx.submit_lineup(
        scn,
        0,
        [
            f.slot(1, membership_id=scn.membership_ids[0]),
            f.absentee_slot(2, scn.membership_ids[1]),
        ],
        match_index=1,
    )
    return scn


def test_vacancy_and_absentee_slots_freeze_different_handicaps(
    api: ApiClient,
) -> None:
    """Two slots that roll no ball are priced from two different averages.

    A `VACANCY` slot freezes the smaller of the ceiling and the floor of the
    adult percentage times the gap between `handicap_base` and `vacancy_average`,
    which the ceiling clamps to 60; an `ABSENTEE` slot freezes the same shape
    computed from its own bowler's basis average less `absentee_deduction`, which
    gives 27 rather than that bowler's own 18.  Both rows carry
    `counts_toward_average` false, and the vacancy carries no membership at all.

    Design: Corner/calculations/corner_vacancy_scores_by_bylaw_and_absentee_never_feeds_an_average
    """
    scn = _week_two_with_a_vacancy_and_an_absentee(api)

    league = _league(scn)
    assert_fields(
        league, status=LeagueStatus.IN_SEASON.value, legal_lineup_minimum=1
    )
    for index, handicap in enumerate(WEEK1_HANDICAPS):
        assert _membership(scn, index)["handicap_per_game"] == handicap, (
            "the amendment re-derived every handicap from the pins already "
            "certified, landing on the integer it already held"
        )

    assert VACANCY_HANDICAP == MAX_HANDICAP
    assert ABSENTEE_HANDICAP == 27

    match = _match(scn, 1)
    assert match["home_team_handicap_per_game"] == expected_team_handicap(
        (WEEK1_HANDICAPS[2], VACANCY_HANDICAP)
    ), "the home side's frozen handicap is 45 + 60"
    assert match["away_team_handicap_per_game"] == expected_team_handicap(
        (WEEK1_HANDICAPS[0], ABSENTEE_HANDICAP)
    ), "the away side's frozen handicap is 36 + 27, not 36 + 18"

    home_slots = _slots(scn, 1, 1)
    assert_fields(
        home_slots[1],
        entry_type=EntryType.VACANCY.value,
        membership_id=None,
        handicap_per_game_applied=VACANCY_HANDICAP,
        counts_toward_average=False,
    )
    away_slots = _slots(scn, 1, 0)
    assert_fields(
        away_slots[0],
        entry_type=EntryType.REGULAR.value,
        handicap_per_game_applied=WEEK1_HANDICAPS[0],
        counts_toward_average=True,
    )
    assert_fields(
        away_slots[1],
        entry_type=EntryType.ABSENTEE.value,
        membership_id=scn.membership_ids[1],
        handicap_per_game_applied=ABSENTEE_HANDICAP,
        counts_toward_average=False,
    )


def test_vacancy_scores_the_bylaw_pins_while_the_absentee_scores_none(
    api: ApiClient,
) -> None:
    """The vacancy is never listed in `entries` yet still scores every game.

    A `VACANCY` slot contributes the league's `vacancy_score` to its side's game
    total although it records no pins of its own, while an `ABSENTEE` slot is
    listed with its three game fields null and contributes 0 pins against the
    handicap frozen onto it.  Home totals 200 + 120 + 105 == 425 against away
    210 + 0 + 63 == 273 in every game and on the series, so the points are 4.0
    to 0.0, and both silent rows record `games_recorded` 0 and `scratch_series` 0.

    Design: Corner/calculations/corner_vacancy_scores_by_bylaw_and_absentee_never_feeds_an_average
    """
    scn = _week_two_with_a_vacancy_and_an_absentee(api)
    fx.set_clock(api, WEEK2_STARTS_AT)
    fx.open_match(scn, 1)

    home_slots = _slots(scn, 1, 1)
    away_slots = _slots(scn, 1, 0)
    scored = validate_success(
        scn.api.record_scores(
            scn.match_ids[1],
            f.scores_payload(
                [
                    f.score_entry(home_slots[0]["id"], 200, 200, 200),
                    f.score_entry(away_slots[0]["id"], 210, 210, 210),
                    f.absentee_score_entry(away_slots[1]["id"]),
                ]
            ),
            scn.secretary,
        ),
        200,
    )
    assert scored["status"] == MatchStatus.SCORES_ENTERED.value
    assert_points(scored["home_points"], 4.0, "home_points")
    assert_points(scored["away_points"], 0.0, "away_points")
    assert VACANCY_SCORE == 120

    vacancy = _slots(scn, 1, 1)[1]
    assert_fields(vacancy, games_recorded=0, scratch_series=0)
    absentee = _slots(scn, 1, 0)[1]
    assert_fields(absentee, games_recorded=0, scratch_series=0)


def test_neither_the_vacancy_nor_the_absentee_feeds_any_average(
    api: ApiClient,
) -> None:
    """Certification leaves the absent bowler's average exactly where it was.

    Only slots that are both certified and average-bearing feed a membership's
    certified games and pins, so the absentee's row is certified yet filtered
    out: that bowler's three games, 720 pins, average 199 and handicap 18 are
    untouched by a match their side lost 4.0 to 0.0.  The bowlers who did roll
    absorb their pins, and the roster team handicaps ignore both the vacancy's 60
    and the absentee's 27 that actually decided the match.

    Design: Corner/calculations/corner_vacancy_scores_by_bylaw_and_absentee_never_feeds_an_average
    """
    scn = _week_two_with_a_vacancy_and_an_absentee(api)
    fx.set_clock(api, WEEK2_STARTS_AT)
    fx.open_match(scn, 1)
    home_slots = _slots(scn, 1, 1)
    away_slots = _slots(scn, 1, 0)
    fx.enter_scores(
        scn,
        [
            f.score_entry(home_slots[0]["id"], 200, 200, 200),
            f.score_entry(away_slots[0]["id"], 210, 210, 210),
            f.absentee_score_entry(away_slots[1]["id"]),
        ],
        1,
    )

    certified = validate_success(
        scn.api.certify_match(scn.match_ids[1], {}, scn.secretary), 200
    )
    assert certified["status"] == MatchStatus.CERTIFIED.value

    assert_fields(
        _slots(scn, 1, 1)[1], certified=True, counts_toward_average=False
    )
    assert_fields(
        _slots(scn, 1, 0)[1], certified=True, counts_toward_average=False
    )

    assert_fields(
        _membership(scn, 1),
        certified_games=3,
        certified_pins=WEEK1_SCRATCH[1],
        current_average=WEEK1_AVERAGES[1],
        handicap_per_game=WEEK1_HANDICAPS[1],
    )

    # floor((180 * 30 + 1170) / 36) == floor(182.5) == 182, handicap floor(34.2)
    first_average = expected_blended_average(180, 30, WEEK1_SCRATCH[0] + 630, 6)
    assert first_average == 182
    assert_fields(
        _membership(scn, 0),
        certified_games=6,
        certified_pins=1170,
        current_average=first_average,
        handicap_per_game=expected_bowler_handicap(
            first_average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
        ),
    )
    # floor((170 * 30 + 1080) / 36) == floor(171.66) == 171, handicap floor(44.1)
    third_average = expected_blended_average(170, 30, WEEK1_SCRATCH[2] + 600, 6)
    assert third_average == 171
    assert_fields(
        _membership(scn, 2),
        certified_games=6,
        certified_pins=1080,
        current_average=third_average,
        handicap_per_game=expected_bowler_handicap(
            third_average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
        ),
    )

    away_side = _team(scn, 0)
    assert_points(away_side["total_points"], 4.0, "team total_points")
    assert away_side["total_scratch_pins"] == 1890, "1260 + 630 + 0"
    assert away_side["team_handicap_per_game"] == expected_team_handicap(
        (
            expected_bowler_handicap(
                first_average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
            ),
            WEEK1_HANDICAPS[1],
        )
    ), "the roster handicap is 34 + 18, with no absentee substitute in it"

    home_side = _team(scn, 1)
    assert_points(home_side["total_points"], 4.0, "team total_points")
    assert home_side["total_scratch_pins"] == 1530, (
        "930 + 600: the vacancy scored 120 a game and contributed no scratch pins"
    )
    assert home_side["team_handicap_per_game"] == expected_team_handicap(
        (
            expected_bowler_handicap(
                third_average, HANDICAP_BASE, ADULT_PCT, MAX_HANDICAP
            ),
            WEEK1_HANDICAPS[3],
        )
    ), "the roster handicap is 44 + 54, with no vacancy substitute in it"

    assert _league(scn)["certified_week_high_water"] == 2


# ─── the dues ledger and the settled-week filter (PRD §3.7) ───

def test_a_dues_payment_splits_into_a_prize_share_and_an_expense_share(
    api: ApiClient,
) -> None:
    """The split is read off the bylaws, never off the tender.

    A payment of the exact weekly dues records a prize share of
    `weekly_dues_cents` less `weekly_expense_cents` and an expense share of
    `weekly_expense_cents`, which is 700 and 500 against the 1200 tendered.  The
    record is immutable, so it carries an `id` and a `created_at` and neither an
    `updated_at` nor a `version`; the bowler's `dues_paid_cents` rises by the
    whole tender while only the prize share reaches the fund.

    Design: Corner/calculations/corner_dues_ledger_running_total_and_settled_week_filtering
    """
    scn = fx.build_sanctioned_league(api)

    payment = validate_success(
        scn.api.record_dues_payment(
            scn.membership_ids[0],
            f.dues_payload(1, WEEKLY_DUES_CENTS),
            scn.treasurer,
        ),
        201,
    )
    assert_fields(payment, membership_id=scn.membership_ids[0], week_number=1)
    assert_cents(payment["amount_cents"], WEEKLY_DUES_CENTS, "amount_cents")
    assert_cents(payment["prize_share_cents"], PRIZE_SHARE_CENTS, "prize_share_cents")
    assert_cents(
        payment["expense_share_cents"], WEEKLY_EXPENSE_CENTS, "expense_share_cents"
    )
    assert_identity(payment, versioned=False)

    assert_cents(
        _membership(scn, 0)["dues_paid_cents"], WEEKLY_DUES_CENTS, "dues_paid_cents"
    )
    fund = _prize_fund(scn)
    assert fund["status"] == PrizeFundStatus.ACCUMULATING.value
    assert_cents(
        fund["collected_prize_cents"], PRIZE_SHARE_CENTS, "collected_prize_cents"
    )
    assert_cents(
        fund["undistributed_balance_cents"],
        PRIZE_SHARE_CENTS,
        "undistributed_balance_cents",
    )
    assert_cents(fund["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert_prize_money_invariant(fund)


def test_the_fund_ledger_runs_a_total_over_every_payment_tendered(
    api: ApiClient,
) -> None:
    """Every payment moves the fund the moment it is tendered.

    The prize share accrues per payment rather than per bowler or per week, so
    three payments of 1200 build a collected total of 700, 1400 and then 2100
    with the undistributed balance tracking it cent for cent and the money
    invariant holding at every step.  A bowler who has paid two weeks carries
    2400 in `dues_paid_cents`, the whole tender rather than the prize share.

    Design: Corner/calculations/corner_dues_ledger_running_total_and_settled_week_filtering
    """
    scn = fx.build_sanctioned_league(api)

    running = 0
    for membership_index, week in ((0, 1), (1, 1), (0, 2)):
        fx.pay_dues(scn, membership_index, week)
        running += PRIZE_SHARE_CENTS
        fund = _prize_fund(scn)
        assert_cents(
            fund["collected_prize_cents"], running, "collected_prize_cents"
        )
        assert_cents(
            fund["undistributed_balance_cents"],
            running,
            "undistributed_balance_cents",
        )
        assert_prize_money_invariant(fund)

    assert running == 3 * PRIZE_SHARE_CENTS == 2100
    assert_cents(
        _membership(scn, 0)["dues_paid_cents"],
        2 * WEEKLY_DUES_CENTS,
        "dues_paid_cents",
    )
    assert_cents(
        _membership(scn, 1)["dues_paid_cents"], WEEKLY_DUES_CENTS, "dues_paid_cents"
    )
    assert_cents(_membership(scn, 2)["dues_paid_cents"], 0, "dues_paid_cents")


def test_the_certified_to_date_basis_counts_only_settled_weeks(
    api: ApiClient,
) -> None:
    """Money in the fund is not the same figure as money in the basis.

    With week one certified and week two not yet settled the league's
    `certified_week_high_water` stands at 1, so of the 2100 cents collected only
    the two week-one payments — 1400 cents — are settled money and the week-two
    payment is excluded.  The waterfall then runs in its pinned order off that
    1400: a 5 percent reserve because the basis is below the 100000-cent tier,
    giving 70; 3 percent of the 1330 remaining rounded half up from 39.9, giving
    40; and 1290 net.  The collected ledger is untouched by the drafting.

    Design: Corner/calculations/corner_dues_ledger_running_total_and_settled_week_filtering
    """
    scn = fx.build_certified_match(api)
    fx.pay_dues(scn, 0, 1)
    fx.pay_dues(scn, 1, 1)
    fx.pay_dues(scn, 0, 2)

    league = _league(scn)
    assert_fields(
        league, status=LeagueStatus.IN_SEASON.value, certified_week_high_water=1
    )
    before = _prize_fund(scn)
    assert_cents(
        before["collected_prize_cents"], 2100, "collected_prize_cents"
    )

    fx.draft_plan(scn, BasisVariant.CERTIFIED_TO_DATE)

    settled = 2 * PRIZE_SHARE_CENTS
    reserve = expected_reserve_cents(settled)
    admin = expected_admin_fee_cents(settled, reserve)
    assert (settled, reserve, admin) == (1400, 70, 40)

    fund = _prize_fund(scn)
    assert_fields(
        fund,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
        basis_variant=BasisVariant.CERTIFIED_TO_DATE.value,
        place_count=len(PLACE_WEIGHTS),
        version=before["version"] + 1,
    )
    assert_cents(fund["plan_basis_cents"], settled, "plan_basis_cents")
    assert_cents(fund["reserve_cents"], reserve, "reserve_cents")
    assert_cents(fund["admin_fee_cents"], admin, "admin_fee_cents")
    assert_cents(
        fund["net_distributable_cents"],
        settled - reserve - admin,
        "net_distributable_cents",
    )
    assert_cents(fund["collected_prize_cents"], 2100, "collected_prize_cents")
    assert_prize_money_invariant(fund)


def test_arrears_count_settled_weeks_rather_than_the_calendar(
    api: ApiClient,
) -> None:
    """Paying week two early settles nothing that arrears are measured against.

    `dues_arrears_weeks` is the high-water mark less the number of distinct weeks
    at or below it that the bowler has paid, floored at 0.  With the mark at 1,
    the bowler who paid weeks one and two carries no arrears and the bowler who
    paid only week one carries none either; the bowler who paid only week two has
    tendered exactly as much money yet carries one week of arrears, and so does
    the bowler who has paid nothing at all.

    Design: Corner/calculations/corner_dues_ledger_running_total_and_settled_week_filtering
    """
    scn = fx.build_certified_match(api)
    fx.pay_dues(scn, 0, 1)
    fx.pay_dues(scn, 0, 2)
    fx.pay_dues(scn, 1, 1)
    fx.pay_dues(scn, 2, 2)

    assert _league(scn)["certified_week_high_water"] == 1

    expected = (
        (0, 2 * WEEKLY_DUES_CENTS, 0),
        (1, WEEKLY_DUES_CENTS, 0),
        (2, WEEKLY_DUES_CENTS, 1),
        (3, 0, 1),
    )
    for index, paid_cents, arrears in expected:
        membership = _membership(scn, index)
        assert_cents(membership["dues_paid_cents"], paid_cents, "dues_paid_cents")
        assert membership["dues_arrears_weeks"] == arrears, (
            f"membership {index} should carry {arrears} weeks of arrears, "
            f"got {membership['dues_arrears_weeks']}"
        )


# ─── the four honor-score thresholds (PRD §3.8) ───
# One certified match carrying every edge at once: a pair of perfect games and a
# 200 on the same slot, the 299 and 298 that bracket the high-game band, a series
# that lands exactly on the eight-hundred scratch floor, and two more that land
# exactly on and just under the seven-hundred handicap floor.
AWARD_PINS: Dict[int, Tuple[int, int, int]] = {
    0: (300, 300, 200),   # scratch series 800, frozen handicap 36
    1: (299, 298, 200),   # scratch series 797, frozen handicap 22
    2: (190, 190, 185),   # scratch series 565, frozen handicap 45
    3: (140, 150, 160),   # scratch series 450, frozen handicap 54
}


def _honor_score_match(api: ApiClient) -> fx.Scenario:
    """Week one bowled to the pin counts above and certified."""
    return fx.build_certified_match(api, pins=AWARD_PINS)


def _file_claim(
    scn: fx.Scenario,
    membership_index: int,
    award_type: AwardType,
    claimed_game_number: Optional[int] = None,
    **overrides: Any,
) -> Any:
    """The bowler behind this membership claims on their own certified slot."""
    return scn.api.create_award_application(
        f.award_application_payload(
            scn.league_id,
            scn.membership_ids[membership_index],
            _slot_of(scn, membership_index)["id"],
            award_type,
            claimed_game_number,
            **overrides,
        ),
        scn.bowler(membership_index),
    )


def test_the_perfect_game_threshold_is_an_equality_on_the_named_game(
    api: ApiClient,
) -> None:
    """Three hundred exactly, on the game the claim names.

    `claimed_pins` for a perfect game is the pin count of the game named by
    `claimed_game_number`, so the same slot yields 300 for game one and 200 for
    game three, and only the first is eligible.  A 299 on somebody else's slot
    falls short of the equality.  A second live claim for the same slot and the
    same award type is refused on uniqueness rather than accepted twice.

    Design: Corner/calculations/corner_game_award_thresholds_and_the_conditional_game_number
    """
    scn = _honor_score_match(api)
    slot = _slot_of(scn, 0)
    assert slot["game1_pins"] == 300 and slot["game3_pins"] == 200

    application = validate_success(
        _file_claim(scn, 0, AwardType.PERFECT_GAME_300, 1), 201
    )
    assert_fields(
        application,
        league_id=scn.league_id,
        membership_id=scn.membership_ids[0],
        series_entry_id=slot["id"],
        award_type=AwardType.PERFECT_GAME_300.value,
        claimed_game_number=1,
        claimed_pins=300,
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=1,
        lane_certification_verified=True,
        sanctioned_at_game_time=True,
        verified_by_user_id=None,
    )
    assert_identity(application)

    validate_error(
        _file_claim(scn, 0, AwardType.PERFECT_GAME_300, 3),
        ApiErrorId.ERR_AWARD_THRESHOLD_NOT_MET.value,
    )
    validate_error(
        _file_claim(scn, 1, AwardType.PERFECT_GAME_300, 1),
        ApiErrorId.ERR_AWARD_THRESHOLD_NOT_MET.value,
    )
    validate_error(
        _file_claim(scn, 0, AwardType.PERFECT_GAME_300, 1),
        ApiErrorId.ERR_AWARD_THRESHOLD_NOT_MET.value,
    )


def test_the_high_game_band_is_closed_at_both_ends(api: ApiClient) -> None:
    """At least two hundred and ninety-eight and at most two hundred and ninety-nine.

    A 300 belongs to the perfect-game category and is refused here even though it
    is the larger number, a 298 sits on the inclusive lower edge and is accepted,
    and a 190 falls short.  The band is genuinely two-sided rather than a floor.

    Design: Corner/calculations/corner_game_award_thresholds_and_the_conditional_game_number
    """
    scn = _honor_score_match(api)

    validate_error(
        _file_claim(scn, 0, AwardType.HIGH_GAME_298_PLUS, 1),
        ApiErrorId.ERR_AWARD_THRESHOLD_NOT_MET.value,
    )

    accepted = validate_success(
        _file_claim(scn, 1, AwardType.HIGH_GAME_298_PLUS, 2), 201
    )
    assert_fields(
        accepted,
        award_type=AwardType.HIGH_GAME_298_PLUS.value,
        claimed_game_number=2,
        claimed_pins=298,
        status=AwardApplicationStatus.SUBMITTED.value,
    )

    validate_error(
        _file_claim(scn, 2, AwardType.HIGH_GAME_298_PLUS, 1),
        ApiErrorId.ERR_AWARD_THRESHOLD_NOT_MET.value,
    )


def test_the_claimed_game_number_is_conditional_in_both_directions(
    api: ApiClient,
) -> None:
    """Required for the game categories, forbidden for the series ones.

    A perfect-game claim that omits `claimed_game_number` is malformed, and so is
    a series claim that supplies one — the condition binds in both directions.
    Because the shape pass runs far ahead of the threshold check, a series claim
    that both carries a forbidden game number and falls short of its floor is
    refused as malformed rather than for the shortfall.

    Design: Corner/calculations/corner_game_award_thresholds_and_the_conditional_game_number
    """
    scn = _honor_score_match(api)

    validate_error(
        _file_claim(scn, 0, AwardType.PERFECT_GAME_300),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        _file_claim(scn, 1, AwardType.HIGH_GAME_298_PLUS),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        _file_claim(scn, 0, AwardType.SERIES_800_SCRATCH, 1),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        _file_claim(scn, 3, AwardType.HANDICAP_SERIES_700, 2),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


# ─── the two series floors (PRD §3.8) ───

def test_the_eight_hundred_scratch_floor_is_inclusive(api: ApiClient) -> None:
    """A series of exactly eight hundred qualifies; seven hundred and ninety-seven
    does not.

    `claimed_pins` for a scratch-series claim is the slot's `scratch_series`
    itself, with no handicap of any kind added, and the comparison is "at least
    eight hundred".  Two perfect games and a 200 total exactly 800 and clear the
    floor, while a 299, a 298 and a 200 total 797 and fall three pins short — even
    though that slot carries a handicap that would more than close the gap.

    Design: Corner/calculations/corner_series_award_floors_are_inclusive_at_eight_hundred_and_seven_hundred
    """
    scn = _honor_score_match(api)

    on_the_floor = _slot_of(scn, 0)
    assert on_the_floor["scratch_series"] == SERIES_SCRATCH_FLOOR == 800
    assert on_the_floor["handicap_per_game_applied"] == ENTERING_HANDICAPS[0]

    application = validate_success(
        _file_claim(scn, 0, AwardType.SERIES_800_SCRATCH), 201
    )
    assert_fields(
        application,
        award_type=AwardType.SERIES_800_SCRATCH.value,
        claimed_game_number=None,
        claimed_pins=SERIES_SCRATCH_FLOOR,
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=1,
    )

    just_short = _slot_of(scn, 1)
    assert just_short["scratch_series"] == 797
    validate_error(
        _file_claim(scn, 1, AwardType.SERIES_800_SCRATCH),
        ApiErrorId.ERR_AWARD_THRESHOLD_NOT_MET.value,
    )


def test_the_seven_hundred_handicap_floor_adds_three_games_of_handicap(
    api: ApiClient,
) -> None:
    """The handicap series adds three times the handicap frozen onto the slot.

    A scratch series of 565 against a frozen handicap of 45 totals exactly 700 and
    sits on the inclusive floor, while 450 against a frozen 54 totals 612 and
    falls short.  The bowler who shot 800 scratch reaches 908 on the same
    arithmetic, which shows the addend is the slot's own frozen figure rather than
    any team or current handicap.

    Design: Corner/calculations/corner_series_award_floors_are_inclusive_at_eight_hundred_and_seven_hundred
    """
    scn = _honor_score_match(api)

    on_the_floor = _slot_of(scn, 2)
    assert on_the_floor["handicap_per_game_applied"] == ENTERING_HANDICAPS[2]
    assert (
        on_the_floor["scratch_series"] + 3 * on_the_floor["handicap_per_game_applied"]
        == SERIES_HANDICAP_FLOOR
        == 700
    )
    exact = validate_success(
        _file_claim(scn, 2, AwardType.HANDICAP_SERIES_700), 201
    )
    assert_fields(
        exact,
        award_type=AwardType.HANDICAP_SERIES_700.value,
        claimed_game_number=None,
        claimed_pins=SERIES_HANDICAP_FLOOR,
    )

    just_short = _slot_of(scn, 3)
    assert (
        just_short["scratch_series"] + 3 * just_short["handicap_per_game_applied"]
        == 612
    )
    validate_error(
        _file_claim(scn, 3, AwardType.HANDICAP_SERIES_700),
        ApiErrorId.ERR_AWARD_THRESHOLD_NOT_MET.value,
    )

    generous = validate_success(
        _file_claim(scn, 0, AwardType.HANDICAP_SERIES_700), 201
    )
    assert generous["claimed_pins"] == 800 + 3 * ENTERING_HANDICAPS[0] == 908


def test_verification_leaves_the_series_arithmetic_exactly_as_filed(
    api: ApiClient,
) -> None:
    """The secretary's verification re-checks the floor and changes no number.

    Verification requires the claim still to reach its threshold, so a series
    sitting exactly on the eight-hundred floor passes on the same inclusive
    comparison used at filing.  The application keeps its `claimed_pins`, keeps
    `claimed_game_number` null, keeps `round_count` at 1, and gains the acting
    secretary's identifier as `verified_by_user_id`.

    Design: Corner/calculations/corner_series_award_floors_are_inclusive_at_eight_hundred_and_seven_hundred
    """
    scn = _honor_score_match(api)
    application = validate_success(
        _file_claim(scn, 0, AwardType.SERIES_800_SCRATCH), 201
    )

    verified = validate_success(
        scn.api.league_verify_application(
            application["id"], f.league_verification_payload(), scn.secretary
        ),
        200,
    )
    assert_fields(
        verified,
        id=application["id"],
        status=AwardApplicationStatus.LEAGUE_VERIFIED.value,
        verified_by_user_id=scn.secretary_member_id,
        claimed_pins=SERIES_SCRATCH_FLOOR,
        claimed_game_number=None,
        round_count=1,
        lane_certification_verified=True,
        sanctioned_at_game_time=True,
    )
