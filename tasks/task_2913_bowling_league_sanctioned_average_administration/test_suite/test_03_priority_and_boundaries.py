"""Refusal precedence and the exact-boundary comparisons.

Two families of behaviour are exercised here.

The first is the ordered refusal chain of PRD §2.6: when one request breaks
several rules at once, the response belongs to the *earliest* broken check and
no later check is consulted.  Two pairs are probed from both sides — the
sanctioned-bowler gate (check 23) against the dues-arrears gate (check 43), and
the match-state gate (check 16) against the pre-bowl temporal gate (check 31).
In each pair the request is first made with both gates armed, then replayed with
only the lower-ranked gate armed, so the second error can only surface once the
first violation has been removed.

The second is boundary precision: the minimum-games threshold that flips a
membership between the established and provisional average variants, the
eligible-teams count compared against a plan's ``place_count``, and the
twenty-one-day late-filing grace period that the remittance penalty measures
with a strict inequality.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing.validators import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_instant_equals,
    assert_membership_axes,
    assert_points,
)
from test_helpers.constants import (
    LATE_PENALTY_CENTS,
    ORG_MEETING_INSTANT,
    WEEK1_STARTS_AT,
)
from test_helpers.fixtures import (
    DEFAULT_GAME_PINS,
    DEFAULT_ROSTER,
    RosterSpec,
    Scenario,
    adopt_bylaws,
    awards_of_fund,
    build_certified_match,
    build_league,
    build_open_match,
    build_sanctioned_league,
    certify_match,
    enter_scores,
    expected_remittance_cents,
    open_match,
    open_remittance,
    pay_dues,
    pay_dues_for_all,
    regular_slots,
    reject_remittance,
    sanction,
    score_entries_for,
    set_clock,
    slot_by_membership,
    submit_both_lineups,
    submit_lineup,
    submit_remittance,
)
from test_helpers.types import (
    AverageStatus,
    BasisVariant,
    EntryType,
    FeeRemittanceStatus,
    LeagueStatus,
    MatchStatus,
    MemberClass,
    MembershipRemittanceStatus,
    PrizeFundStatus,
    SanctionStatus,
)

# The instants this module pins, all measured against the logical clock.
BYLAWS_ADOPTED_INSTANT = ORG_MEETING_INSTANT          # 2026-08-05T00:00:00Z
TWENTY_ONE_DAYS_AFTER_ADOPTION = "2026-08-26T00:00:00Z"
TWENTY_TWO_DAYS_AFTER_ADOPTION = "2026-08-27T00:00:00Z"
WEEK2_STARTS_AT_INSTANT = "2026-08-19T01:00:00Z"
PREBOWL_AFTER_WEEK1_START = "2026-08-12T02:00:00Z"
PREBOWL_AFTER_WEEK2_START = "2026-08-19T02:00:00Z"
PREBOWL_BEFORE_WEEK2_START = "2026-08-12T00:30:00Z"


# ─── local plumbing ────────────────────────────────────
# Nothing here belongs in the shared infrastructure: these two helpers exist
# only to keep the refused calls of this module raw, so the response envelope
# can be asserted rather than unwrapped by a setup helper.

def _lineup_response(
    scn: Scenario,
    match_index: int,
    team_index: int,
    slots: List[Dict[str, Any]],
    expected_match_version: Optional[int] = None,
    actor: Optional[Dict[str, str]] = None,
):
    """Submit one side's lineup and hand back the untouched response."""
    version = (
        expected_match_version
        if expected_match_version is not None
        else scn.match_version(match_index)
    )
    return scn.api.submit_lineup(
        scn.match_ids[match_index],
        f.lineup_payload(version, scn.team_ids[team_index], slots),
        actor if actor is not None else scn.secretary,
    )


def _score_entries_with_absentee(scn: Scenario, absentee_index: int) -> List[Dict[str, Any]]:
    """One entry per bowling slot, the absentee's three game fields null.

    An `ABSENTEE` slot is listed in `entries` but rolls nothing, so it records
    `games_recorded` 0 and `scratch_series` 0 (PRD §3.5).
    """
    by_membership = slot_by_membership(scn, 0)
    entries: List[Dict[str, Any]] = []
    for index, membership_id in enumerate(scn.membership_ids):
        row = by_membership.get(membership_id)
        if row is None:
            continue
        if index == absentee_index:
            entries.append(f.absentee_score_entry(row["id"]))
            continue
        game1, game2, game3 = DEFAULT_GAME_PINS[index]
        entries.append(f.score_entry(row["id"], game1, game2, game3))
    return entries


# ═══════════════════════════════════════════════════════
# Check 23 (ERR_BOWLER_NOT_SANCTIONED) outranks check 43
# (ERR_DUES_ARREARS_BLOCK) on one and the same slot.
# ═══════════════════════════════════════════════════════

def _arrears_scenario(api: ApiClient) -> Scenario:
    """A league IN_SEASON with week one certified and a fifth bowler adrift.

    The league adopts `max_dues_arrears_weeks` 0, so a single unsettled week is
    already over the ceiling.  Four of the five memberships are sanctioned; the
    fifth was left off the remittance, so it is `UNSANCTIONED` *and* — because
    week one is certified and it has paid nothing — carries one week of arrears.
    The two bowlers who do appear alongside it have paid week one, so neither can
    be the source of the arrears refusal.
    """
    roster = tuple(DEFAULT_ROSTER) + (
        RosterSpec("Gus Sub", MemberClass.ADULT, 175, 30, 0),
    )
    scn = build_league(api, bylaws={"max_dues_arrears_weeks": 0}, roster=roster)
    sanction(scn, scn.membership_ids[:4])
    submit_both_lineups(scn, 0)
    set_clock(api, WEEK1_STARTS_AT)
    open_match(scn, 0)
    enter_scores(scn, score_entries_for(scn, 0), 0)
    certify_match(scn, 0)
    pay_dues(scn, 0, 1)
    pay_dues(scn, 1, 1)
    return scn


def test_unsanctioned_bowler_outranks_that_bowlers_dues_arrears(api: ApiClient) -> None:
    """One slot breaks both the sanctioned-bowler gate and the arrears gate.

    The fifth membership is `UNSANCTIONED` (check 23) and carries one week of
    arrears against a ceiling of 0 (check 43).  Because checks are evaluated
    strictly in order and the first violated check decides the response, the
    submission is refused with `ERR_BOWLER_NOT_SANCTIONED` and the later money
    check is never consulted.  The refusal writes nothing: the match keeps its
    `version` and the submitting side gains no slots.

    Design: Difficulty/priority_pair_validation_conflict/safety_sanction_gate_outranks_fiscal_arrears_gate_on_one_slot
    """
    scn = _arrears_scenario(api)

    league = scn.league()
    assert_fields(league, status=LeagueStatus.IN_SEASON.value, max_dues_arrears_weeks=0)
    assert league["certified_week_high_water"] == 1, (
        "week one is certified, so the high-water mark stands at 1"
    )
    stray = scn.membership(4)
    assert_fields(
        stray,
        sanction_status=SanctionStatus.UNSANCTIONED.value,
        dues_arrears_weeks=1,
    )
    assert scn.membership(0)["dues_arrears_weeks"] == 0, (
        "the co-listed bowler has paid week one, so only the fifth is in arrears"
    )

    version_before = scn.match_version(1)
    response = _lineup_response(
        scn,
        1,
        0,
        [
            f.slot(1, membership_id=scn.membership_ids[0]),
            f.slot(2, membership_id=scn.membership_ids[4]),
        ],
        expected_match_version=version_before,
    )
    validate_error(response, ApiErrorId.ERR_BOWLER_NOT_SANCTIONED.value)

    assert scn.match_version(1) == version_before, (
        "a refused submission must not increment the match's version"
    )
    assert scn.series_entries(1, 0) == [], (
        "a refused submission must create no slot for the submitting side"
    )


def test_sanctioning_the_bowler_surfaces_the_arrears_gate(api: ApiClient) -> None:
    """With the earlier gate cleared, the identical request hits the later one.

    Accepting a second remittance moves the fifth membership to `SANCTIONED` and
    grants it a handicap, but sanctioning settles no dues: `dues_arrears_weeks`
    is still 1 against a ceiling of 0.  The same payload therefore now returns
    `ERR_DUES_ARREARS_BLOCK`, which proves the first refusal was ordering and not
    a missing arrears check.

    Design: Difficulty/priority_pair_validation_conflict/safety_sanction_gate_outranks_fiscal_arrears_gate_on_one_slot
    """
    scn = _arrears_scenario(api)
    slots = [
        f.slot(1, membership_id=scn.membership_ids[0]),
        f.slot(2, membership_id=scn.membership_ids[4]),
    ]
    validate_error(
        _lineup_response(scn, 1, 0, slots),
        ApiErrorId.ERR_BOWLER_NOT_SANCTIONED.value,
    )

    sanction(scn, [scn.membership_ids[4]])

    stray = scn.membership(4)
    assert_membership_axes(
        stray, SanctionStatus.SANCTIONED, MembershipRemittanceStatus.REMITTED
    )
    # Entering average 175, no certified game of its own: min(floor((220 - 175)
    # * 0.90), 60) == 40.
    assert_fields(stray, handicap_per_game=40, dues_arrears_weeks=1)

    version_before = scn.match_version(1)
    validate_error(
        _lineup_response(scn, 1, 0, slots, expected_match_version=version_before),
        ApiErrorId.ERR_DUES_ARREARS_BLOCK.value,
    )
    assert scn.match_version(1) == version_before, (
        "the arrears refusal must not increment the match's version either"
    )


def test_settling_the_arrears_week_admits_the_same_lineup(api: ApiClient) -> None:
    """Once both gates are clear the submission lands and freezes its handicaps.

    Recording the outstanding week takes `dues_arrears_weeks` to 0, and the
    submission then succeeds, freezing each named membership's own
    `handicap_per_game` onto its slot: 36 for the bowler blended to 180 and 40
    for the newly sanctioned bowler entering at 175, so the side's frozen team
    handicap reads 76.

    Design: Difficulty/priority_pair_validation_conflict/safety_sanction_gate_outranks_fiscal_arrears_gate_on_one_slot
    """
    scn = _arrears_scenario(api)
    sanction(scn, [scn.membership_ids[4]])
    pay_dues(scn, 4, 1)

    settled = scn.membership(4)
    assert_fields(settled, dues_arrears_weeks=0)
    assert_cents(settled["dues_paid_cents"], 1200, "dues_paid_cents")

    version_before = scn.match_version(1)
    data = get_success_data(
        _lineup_response(
            scn,
            1,
            0,
            [
                f.slot(1, membership_id=scn.membership_ids[0]),
                f.slot(2, membership_id=scn.membership_ids[4]),
            ],
            expected_match_version=version_before,
        )
    )
    assert data["version"] == version_before + 1, (
        "a successful submission increments the match's version by exactly 1"
    )

    match = scn.match(1)
    assert_fields(
        match,
        status=MatchStatus.SCHEDULED.value,
        away_team_handicap_per_game=76,
        home_team_handicap_per_game=0,
    )
    assert scn.team(0)["sanctioned_roster_count"] == 3, (
        "the fifth sanctioned membership raises the team's sanctioned roster count"
    )


# ═══════════════════════════════════════════════════════
# Check 16 (ERR_MATCH_STATE_INVALID) outranks check 31
# (ERR_PREBOWL_NOT_BEFORE_MATCH) on one submission.
# ═══════════════════════════════════════════════════════

def test_open_match_state_outranks_the_prebowl_instant(api: ApiClient) -> None:
    """A late pre-bowl against an already-open match answers on the state.

    Lineup submission is legal only while the match sits at `DRAFT`, `SCHEDULED`
    or `LINEUPS_SUBMITTED`, so a submission against an `OPEN` match breaks check
    16; the same payload also dates its `PREBOWL` slot after the match's
    `starts_at`, which breaks check 31.  The earlier check decides, so the
    response is `ERR_MATCH_STATE_INVALID` and the open match keeps both its
    `version` and its existing slots.

    Design: Difficulty/priority_pair_validation_conflict/match_state_gate_outranks_prebowl_temporal_gate
    """
    scn = build_open_match(api)

    match = scn.match(0)
    assert_fields(match, status=MatchStatus.OPEN.value)
    assert_instant_equals(match["starts_at"], WEEK1_STARTS_AT, "starts_at")
    assert PREBOWL_AFTER_WEEK1_START > WEEK1_STARTS_AT, (
        "the pre-bowl instant must also breach the temporal gate"
    )

    version_before = match["version"]
    slots_before = scn.series_entries(0)
    response = _lineup_response(
        scn,
        0,
        0,
        [
            f.slot(1, membership_id=scn.membership_ids[0]),
            f.prebowl_slot(2, scn.membership_ids[1], PREBOWL_AFTER_WEEK1_START),
        ],
        expected_match_version=version_before,
    )
    validate_error(response, ApiErrorId.ERR_MATCH_STATE_INVALID.value)

    assert scn.match_version(0) == version_before, (
        "a refused submission must not increment the match's version"
    )
    slots_after = scn.series_entries(0)
    assert len(slots_after) == len(slots_before) == 4, (
        "the open match's four slots must survive the refusal"
    )
    assert {row["entry_type"] for row in slots_after} == {EntryType.REGULAR.value}, (
        "no PREBOWL slot may be written by a refused submission"
    )


def test_prebowl_at_or_after_starts_at_is_refused_on_a_scheduled_match(
    api: ApiClient,
) -> None:
    """With the state gate cleared, the pre-bowl instant decides the response.

    Week two is still `SCHEDULED`, so check 16 is satisfied and the identical
    slot shape now reaches check 31: a `PREBOWL` slot must carry a `prebowled_at`
    strictly earlier than the match's `starts_at`, and one dated after it is
    refused with `ERR_PREBOWL_NOT_BEFORE_MATCH` — writing no slot at all.

    Design: Difficulty/priority_pair_validation_conflict/match_state_gate_outranks_prebowl_temporal_gate
    """
    scn = build_open_match(api)

    week_two = scn.match(1)
    assert_fields(week_two, status=MatchStatus.SCHEDULED.value)
    assert_instant_equals(week_two["starts_at"], WEEK2_STARTS_AT_INSTANT, "starts_at")

    version_before = week_two["version"]
    response = _lineup_response(
        scn,
        1,
        0,
        [
            f.slot(1, membership_id=scn.membership_ids[0]),
            f.prebowl_slot(2, scn.membership_ids[1], PREBOWL_AFTER_WEEK2_START),
        ],
        expected_match_version=version_before,
    )
    validate_error(response, ApiErrorId.ERR_PREBOWL_NOT_BEFORE_MATCH.value)

    assert scn.match_version(1) == version_before, (
        "the temporal refusal must not increment the match's version"
    )
    assert scn.series_entries(1) == [], (
        "a refused submission must create no slot for either side"
    )


def test_prebowl_strictly_before_starts_at_is_accepted(api: ApiClient) -> None:
    """A pre-bowl dated strictly earlier than `starts_at` completes the pair.

    The accepted submission leaves the match at `SCHEDULED` — the opposing side
    has no slots yet — increments its `version` by 1, and freezes the pre-bowled
    bowler's own handicap onto the slot, which counts toward their average
    exactly as a `REGULAR` slot does.

    Design: Difficulty/priority_pair_validation_conflict/match_state_gate_outranks_prebowl_temporal_gate
    """
    scn = build_open_match(api)

    version_before = scn.match_version(1)
    data = get_success_data(
        _lineup_response(
            scn,
            1,
            0,
            [
                f.slot(1, membership_id=scn.membership_ids[0]),
                f.prebowl_slot(2, scn.membership_ids[1], PREBOWL_BEFORE_WEEK2_START),
            ],
            expected_match_version=version_before,
        )
    )
    assert data["version"] == version_before + 1, (
        "a successful submission increments the match's version by exactly 1"
    )

    match = scn.match(1)
    # Entering handicaps: 36 for the bowler entering at 180 and 22 for the one
    # entering at 195, because week one is open but nothing is certified yet.
    assert_fields(
        match,
        status=MatchStatus.SCHEDULED.value,
        away_team_handicap_per_game=58,
    )

    prebowled = [
        row
        for row in scn.series_entries(1, 0)
        if row["entry_type"] == EntryType.PREBOWL.value
    ]
    assert len(prebowled) == 1, "exactly one PREBOWL slot was submitted"
    assert_fields(
        prebowled[0],
        membership_id=scn.membership_ids[1],
        position=2,
        counts_toward_average=True,
        certified=False,
        handicap_per_game_applied=22,
    )
    assert_instant_equals(
        prebowled[0]["prebowled_at"], PREBOWL_BEFORE_WEEK2_START, "prebowled_at"
    )


# ═══════════════════════════════════════════════════════
# The minimum-games threshold: `certified_games` at the
# bylaw value, and one game short of it.
# ═══════════════════════════════════════════════════════

def test_certified_games_exactly_at_the_threshold_establishes_the_average(
    api: ApiClient,
) -> None:
    """Three certified games against a threshold of three is `ESTABLISHED`.

    The comparison is "at least", so landing exactly on
    `minimum_games_for_average` flips every bowler to `ESTABLISHED` and to the
    truncated quotient of certified pins over certified games — the prior-season
    record is then ignored entirely, however generous it was.  Handicaps follow
    the new averages, flooring the product before applying the ceiling, and a
    basis average above `handicap_base` yields 0 rather than a negative figure.

    Design: Difficulty/boundary_precision_check/minimum_games_threshold_reached_exactly_flips_average_variant
    """
    scn = build_certified_match(api, bylaws={"minimum_games_for_average": 3})

    assert_fields(scn.league(), minimum_games_for_average=3, certified_week_high_water=1)

    first = scn.membership(0)
    assert_fields(
        first,
        certified_games=3,
        certified_pins=540,
        average_status=AverageStatus.ESTABLISHED.value,
        current_average=180,
        handicap_per_game=36,
    )
    # 720 certified pins over three games is an average of 240, above the
    # handicap base of 220, so the negative difference is replaced by 0.
    assert_fields(
        scn.membership(1),
        certified_games=3,
        certified_pins=720,
        average_status=AverageStatus.ESTABLISHED.value,
        current_average=240,
        handicap_per_game=0,
    )
    # floor(480 / 3) == 160, not the blended 169 the provisional variant gives.
    assert_fields(
        scn.membership(2),
        certified_games=3,
        certified_pins=480,
        average_status=AverageStatus.ESTABLISHED.value,
        current_average=160,
        handicap_per_game=54,
    )
    # floor(450 / 3) == 150, whose floored product 63 is clipped by the cap.
    assert_fields(
        scn.membership(3),
        certified_games=3,
        certified_pins=450,
        average_status=AverageStatus.ESTABLISHED.value,
        current_average=150,
        handicap_per_game=60,
    )

    assert_fields(scn.team(0), team_handicap_per_game=36)
    assert_fields(scn.team(1), team_handicap_per_game=114)


def test_certified_games_one_short_of_the_threshold_keeps_the_blend(
    api: ApiClient,
) -> None:
    """The same certified pins under a threshold of four stay `PROVISIONAL`.

    One game short of `minimum_games_for_average`, the carryover policy still
    governs: under `BLENDED` the entering average is weighted by the prior-season
    games, the certified pins are added, and the quotient over the combined game
    count is truncated.  The identical scoring data therefore yields different
    averages and different handicaps from the established variant.

    Design: Difficulty/boundary_precision_check/minimum_games_threshold_reached_exactly_flips_average_variant
    """
    scn = build_certified_match(api, bylaws={"minimum_games_for_average": 4})

    assert_fields(scn.league(), minimum_games_for_average=4)

    # (180 * 30 + 540) / 33 == 180 exactly.
    assert_fields(
        scn.membership(0),
        certified_games=3,
        average_status=AverageStatus.PROVISIONAL.value,
        current_average=180,
        handicap_per_game=36,
    )
    # (195 * 30 + 720) / 33 == 199.09..., truncated to 199.
    assert_fields(
        scn.membership(1),
        certified_games=3,
        average_status=AverageStatus.PROVISIONAL.value,
        current_average=199,
        handicap_per_game=18,
    )
    # (170 * 30 + 480) / 33 == 169.09..., truncated to 169 — not the 160 the
    # established variant would report from the same pins.
    assert_fields(
        scn.membership(2),
        certified_games=3,
        average_status=AverageStatus.PROVISIONAL.value,
        current_average=169,
        handicap_per_game=45,
    )
    # (160 * 30 + 450) / 33 == 159.09..., truncated to 159.
    assert_fields(
        scn.membership(3),
        certified_games=3,
        average_status=AverageStatus.PROVISIONAL.value,
        current_average=159,
        handicap_per_game=54,
    )

    assert_fields(scn.team(0), team_handicap_per_game=54)
    assert_fields(scn.team(1), team_handicap_per_game=99)


def test_absentee_slot_contributes_no_certified_game_at_the_threshold(
    api: ApiClient,
) -> None:
    """A certified absentee slot leaves its bowler short of the threshold.

    The average input set is the slots that are both certified and
    average-bearing, so an `ABSENTEE` slot never participates however the match
    ends: its bowler stays at `certified_games` 0 and keeps the provisional blend
    of the prior-season record alone, even though every other bowler on the match
    has just crossed the threshold.  The slot still contributes the handicap
    frozen onto it, which is priced from the bowler's basis average less the
    bylaw `absentee_deduction`.

    Design: Difficulty/boundary_precision_check/minimum_games_threshold_reached_exactly_flips_average_variant
    """
    scn = build_sanctioned_league(
        api, bylaws={"minimum_games_for_average": 3, "legal_lineup_minimum": 1}
    )
    submit_lineup(
        scn,
        0,
        [
            f.slot(1, membership_id=scn.membership_ids[0]),
            f.absentee_slot(2, scn.membership_ids[1]),
        ],
        0,
    )
    submit_lineup(scn, 1, regular_slots(scn, (2, 3)), 0)
    set_clock(api, WEEK1_STARTS_AT)
    open_match(scn, 0)

    match_before = scn.match(0)
    # 36 for the bowler entering at 180 plus 31 for the absentee: the penalised
    # basis average is 195 - 10, so floor((220 - 185) * 0.90) == 31.
    assert_fields(
        match_before, home_team_handicap_per_game=67, away_team_handicap_per_game=99
    )

    enter_scores(scn, _score_entries_with_absentee(scn, 1), 0)
    validate_success(scn.api.certify_match(scn.match_ids[0], {}, scn.secretary), 200)

    assert_fields(
        scn.membership(0),
        certified_games=3,
        certified_pins=540,
        average_status=AverageStatus.ESTABLISHED.value,
        current_average=180,
    )
    assert_fields(
        scn.membership(1),
        certified_games=0,
        certified_pins=0,
        average_status=AverageStatus.PROVISIONAL.value,
        current_average=195,
        handicap_per_game=22,
    )

    absentee = [
        row
        for row in scn.series_entries(0, 0)
        if row["entry_type"] == EntryType.ABSENTEE.value
    ]
    assert len(absentee) == 1, "exactly one ABSENTEE slot was submitted"
    assert_fields(
        absentee[0],
        certified=True,
        counts_toward_average=False,
        handicap_per_game_applied=31,
        games_recorded=0,
        scratch_series=0,
    )

    match = scn.match(0)
    assert_fields(match, status=MatchStatus.CERTIFIED.value)
    assert_points(match["home_points"], 0.0, "home_points")
    assert_points(match["away_points"], 4.0, "away_points")


# ═══════════════════════════════════════════════════════
# `place_count` against the number of confirmed teams:
# equal to it, and one place beyond it.
# ═══════════════════════════════════════════════════════

def test_place_count_one_beyond_the_confirmed_teams_has_no_eligible_field(
    api: ApiClient,
) -> None:
    """A third paying place with only two confirmed teams is refused.

    The candidates for the standings are the league's `CONFIRMED` teams, and when
    there are fewer candidates than `place_count` the draft is refused rather than
    padded out with an empty place.  Two confirmed teams therefore support two
    places and no more, and the refusal leaves the fund exactly where it stood:
    still `ACCUMULATING`, with no plan figures and no version bump.

    Design: Difficulty/boundary_precision_check/place_count_at_and_one_above_confirmed_team_count
    """
    scn = build_certified_match(api)
    pay_dues_for_all(scn, 1)
    # A third weight is what makes `place_count` 3 a shape-legal request, so the
    # eligibility check is the first one the draft can break.
    adopt_bylaws(scn, prize_place_weights=[0.50, 0.30, 0.20])

    assert_fields(scn.league(), confirmed_team_count=2)
    fund_before = scn.prize_fund()
    assert_fields(fund_before, status=PrizeFundStatus.ACCUMULATING.value)

    response = api.draft_distribution_plan(
        fund_before["id"],
        f.distribution_plan_payload(
            fund_before["version"], BasisVariant.CERTIFIED_TO_DATE, 3
        ),
        scn.treasurer,
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_TEAMS.value)

    fund_after = scn.prize_fund()
    assert_fields(
        fund_after,
        status=PrizeFundStatus.ACCUMULATING.value,
        version=fund_before["version"],
        place_count=fund_before["place_count"],
        plan_basis_cents=fund_before["plan_basis_cents"],
        net_distributable_cents=fund_before["net_distributable_cents"],
    )
    assert fund_after["plan_drafted_at"] == fund_before["plan_drafted_at"], (
        "a refused draft must not stamp plan_drafted_at"
    )
    assert awards_of_fund(scn) == [], "a refused draft creates no award rows"


def test_place_count_equal_to_the_confirmed_teams_drafts_the_waterfall(
    api: ApiClient,
) -> None:
    """Two paying places against exactly two confirmed teams is accepted.

    The comparison is "at least as many confirmed teams as places", so standing
    exactly level is enough and the waterfall runs.  With a settled amount of
    2800 cents the reserve tier is the sub-threshold 5 percent, and the
    administrative fee is three percent of the *post-reserve* amount rather than
    of the basis — 2660 cents, whose 79.8 rounds half up to 80.

    Design: Difficulty/boundary_precision_check/place_count_at_and_one_above_confirmed_team_count
    """
    scn = build_certified_match(api)
    pay_dues_for_all(scn, 1)

    assert_fields(scn.league(), confirmed_team_count=2, certified_week_high_water=1)
    fund_before = scn.prize_fund()
    # Four bowlers at a 700-cent weekly prize share, for the one settled week.
    assert_cents(fund_before["collected_prize_cents"], 2800, "collected_prize_cents")

    data = validate_success(
        api.draft_distribution_plan(
            fund_before["id"],
            f.distribution_plan_payload(
                fund_before["version"], BasisVariant.CERTIFIED_TO_DATE, 2
            ),
            scn.treasurer,
        ),
        200,
    )

    assert_fields(
        data,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
        basis_variant=BasisVariant.CERTIFIED_TO_DATE.value,
        place_count=2,
        version=fund_before["version"] + 1,
    )
    assert_cents(data["plan_basis_cents"], 2800, "plan_basis_cents")
    assert_cents(data["reserve_cents"], 140, "reserve_cents")
    assert_cents(data["admin_fee_cents"], 80, "admin_fee_cents")
    assert_cents(data["net_distributable_cents"], 2580, "net_distributable_cents")
    assert_instant_equals(data["plan_drafted_at"], WEEK1_STARTS_AT, "plan_drafted_at")

    # Drafting moves no money and materialises no awards; the reserve and the fee
    # both stay inside the undistributed balance.
    assert_cents(data["collected_prize_cents"], 2800, "collected_prize_cents")
    assert_cents(data["undistributed_balance_cents"], 2800, "undistributed_balance_cents")
    assert_cents(data["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert awards_of_fund(scn) == [], "drafting creates no award rows at all"


# ═══════════════════════════════════════════════════════
# The twenty-one-day late-filing window: at the boundary,
# and one whole day beyond it.
# ═══════════════════════════════════════════════════════

def test_filing_at_exactly_twenty_one_days_carries_no_penalty(
    api: ApiClient,
) -> None:
    """Twenty-one whole elapsed days is inside the grace period.

    The penalty applies only when the whole-day count measured from
    `bylaws_adopted_at` is strictly greater than twenty-one, so a filing that
    lands exactly on the twenty-first day is priced at the bare fees: four adult
    memberships at 2600 cents of national fee plus the flat 500-cent local fee
    each, and nothing more.

    Design: Difficulty/boundary_precision_check/remittance_penalty_flips_strictly_after_twenty_one_days
    """
    scn = build_league(api)
    assert_instant_equals(
        scn.league()["bylaws_adopted_at"], BYLAWS_ADOPTED_INSTANT, "bylaws_adopted_at"
    )

    remittance_id = open_remittance(scn)
    assert expected_remittance_cents(scn, scn.membership_ids) == 12400, (
        "the unpenalised price of four adult memberships is 12400 cents"
    )

    set_clock(api, TWENTY_ONE_DAYS_AFTER_ADOPTION)
    data = validate_success(
        api.submit_fee_remittance(
            remittance_id, f.remittance_submit_payload(), scn.treasurer
        ),
        200,
    )

    assert_fields(
        data,
        status=FeeRemittanceStatus.SUBMITTED.value,
        member_count=4,
        submitted_by_user_id=scn.treasurer_member_id,
    )
    assert_cents(data["penalty_cents"], 0, "penalty_cents")
    assert_cents(data["computed_amount_cents"], 12400, "computed_amount_cents")
    assert_cents(data["declared_amount_cents"], 12400, "declared_amount_cents")
    assert_instant_equals(
        data["submitted_at"], TWENTY_ONE_DAYS_AFTER_ADOPTION, "submitted_at"
    )

    for index in range(4):
        assert_membership_axes(
            scn.membership(index),
            SanctionStatus.PENDING_REMITTANCE,
            MembershipRemittanceStatus.INVOICED,
        )
    # Pricing reads the adoption instant; it never moves it.
    assert_instant_equals(
        scn.league()["bylaws_adopted_at"], BYLAWS_ADOPTED_INSTANT, "bylaws_adopted_at"
    )


def test_filing_one_day_beyond_the_window_carries_the_full_penalty(
    api: ApiClient,
) -> None:
    """Twenty-two whole elapsed days is outside it, for every listed member.

    One day past the boundary the per-member penalty of 1000 cents applies, and
    `penalty_cents` is that figure multiplied by `member_count` — the whole
    membership list is surcharged, not merely the league as a single filer.

    Design: Difficulty/boundary_precision_check/remittance_penalty_flips_strictly_after_twenty_one_days
    """
    scn = build_league(api)
    remittance_id = open_remittance(scn, penalty_per_member=LATE_PENALTY_CENTS)
    assert (
        expected_remittance_cents(
            scn, scn.membership_ids, penalty_per_member=LATE_PENALTY_CENTS
        )
        == 16400
    ), "the penalised price of four adult memberships is 16400 cents"

    set_clock(api, TWENTY_TWO_DAYS_AFTER_ADOPTION)
    data = validate_success(
        api.submit_fee_remittance(
            remittance_id, f.remittance_submit_payload(), scn.treasurer
        ),
        200,
    )

    assert_fields(data, status=FeeRemittanceStatus.SUBMITTED.value, member_count=4)
    assert_cents(data["penalty_cents"], 4000, "penalty_cents")
    assert_cents(data["computed_amount_cents"], 16400, "computed_amount_cents")
    assert_instant_equals(
        data["submitted_at"], TWENTY_TWO_DAYS_AFTER_ADOPTION, "submitted_at"
    )


def test_refiling_after_the_window_reprices_against_the_current_clock(
    api: ApiClient,
) -> None:
    """A rejected remittance re-filed past the boundary acquires the penalty.

    Re-filing recomputes the penalty against the clock as it stands at the second
    submission, not against the first, so the amount that was exactly right on day
    twenty-one is now a mismatch and the corrected declaration must include the
    surcharge.  The refused attempt leaves the remittance where the rejection left
    it, and the successful re-filing walks the money axis `REFUNDED → INVOICED`
    while the sanction axis repeats `UNSANCTIONED → PENDING_REMITTANCE`.

    Design: Difficulty/boundary_precision_check/remittance_penalty_flips_strictly_after_twenty_one_days
    """
    scn = build_league(api)
    remittance_id = open_remittance(scn)
    set_clock(api, TWENTY_ONE_DAYS_AFTER_ADOPTION)
    first = submit_remittance(scn, remittance_id)
    assert_cents(first["penalty_cents"], 0, "penalty_cents")

    reject_remittance(scn, remittance_id)
    for index in range(4):
        assert_membership_axes(
            scn.membership(index),
            SanctionStatus.UNSANCTIONED,
            MembershipRemittanceStatus.REFUNDED,
        )

    set_clock(api, TWENTY_TWO_DAYS_AFTER_ADOPTION)
    validate_error(
        api.submit_fee_remittance(
            remittance_id, f.remittance_submit_payload(12400), scn.treasurer
        ),
        ApiErrorId.ERR_REMITTANCE_AMOUNT_MISMATCH.value,
    )
    refused = get_success_data(api.get_fee_remittance(remittance_id, scn.treasurer))
    assert_fields(refused, status=FeeRemittanceStatus.REJECTED.value)
    assert_membership_axes(
        scn.membership(0),
        SanctionStatus.UNSANCTIONED,
        MembershipRemittanceStatus.REFUNDED,
    )

    data = validate_success(
        api.submit_fee_remittance(
            remittance_id, f.remittance_submit_payload(16400), scn.treasurer
        ),
        200,
    )
    assert_fields(data, status=FeeRemittanceStatus.SUBMITTED.value, member_count=4)
    assert_cents(data["penalty_cents"], 4000, "penalty_cents")
    assert_cents(data["computed_amount_cents"], 16400, "computed_amount_cents")
    assert_cents(data["declared_amount_cents"], 16400, "declared_amount_cents")
    for index in range(4):
        assert_membership_axes(
            scn.membership(index),
            SanctionStatus.PENDING_REMITTANCE,
            MembershipRemittanceStatus.INVOICED,
        )
