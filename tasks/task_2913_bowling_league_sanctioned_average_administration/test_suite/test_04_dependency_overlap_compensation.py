"""Cross-entity gates, contended-resource windows and the compensating invariants.

Three families of behaviour meet here.  Whether a match may be opened depends on
the clock-derived certification of a *different* entity, and whether a lineup may
be submitted depends on the opposing team's confirmation.  Schedule adoption
compares half-open lane-pair occupation windows while lineup submission compares
closed bowler windows widened by a thirty-minute travel buffer.  And the two
compensating actions of the system — voiding a certified match and reversing a
paid award — must land back on the exact figures that preceded the action they
compensate, to the pin and to the cent.
"""
from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing.validators import (
    get_success_data,
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
    assert_instant_equals,
    assert_points,
    assert_prize_money_invariant,
    assert_restored,
    snapshot,
)
from test_helpers.constants import (
    LANE_CERTIFIED_THROUGH,
    WEEK1_ENDS_AT,
    WEEK1_STARTS_AT,
)
from test_helpers.types import (
    BasisVariant,
    EntryType,
    LanePairCertificationStatus,
    LeagueStatus,
    MatchStatus,
    MemberClass,
    PrizeAwardStatus,
    PrizeFundStatus,
    ProtestCategory,
    ProtestDecision,
    ProtestStatus,
    Remedy,
    SanctionStatus,
    TeamStatus,
)

# ─── instants this module pins ─────────────────────────
# The shared lane pair is certified through 2026-12-31T00:00:00Z, so this clock
# sits strictly past that instant and the pair's derived status flips.
_EXPIRY_CLOCK = "2027-01-05T00:00:00Z"
_RECERTIFIED_THROUGH = "2027-06-30T00:00:00Z"

# Week one occupies [01:00Z, 03:00Z).  A second window beginning at exactly
# 03:00Z merely touches it; one beginning at 02:59Z shares a minute with it.
_TOUCHING_STARTS_AT = "2026-08-12T03:00:00Z"
_TOUCHING_ENDS_AT = "2026-08-12T05:00:00Z"
_OVERLAPPING_STARTS_AT = "2026-08-12T02:59:00Z"
_OVERLAPPING_ENDS_AT = "2026-08-12T04:59:00Z"

# Week one widened by the travel buffer is [00:30Z, 03:30Z]: a window opening at
# 03:30Z touches that closed interval, and one opening at 03:31Z clears it.
_BUFFER_TOUCH_STARTS_AT = "2026-08-12T03:30:00Z"
_BUFFER_TOUCH_ENDS_AT = "2026-08-12T05:30:00Z"
_BUFFER_CLEAR_STARTS_AT = "2026-08-12T03:31:00Z"
_BUFFER_CLEAR_ENDS_AT = "2026-08-12T05:31:00Z"

# ─── figures recomputed from the shared bylaws ─────────
# Entering handicaps at base 220, percentage 0.90 and ceiling 60, for the four
# bowlers whose prior-season averages are 180, 195, 170 and 160.
_ENTERING_HANDICAPS: Tuple[int, int, int, int] = (36, 22, 45, 54)
# The same four bowlers after one certified three-game match under BLENDED.
_CERTIFIED_HANDICAPS: Tuple[int, int, int, int] = (36, 18, 45, 54)
_CERTIFIED_PINS: Tuple[int, int, int, int] = (540, 720, 480, 450)
_HOME_LINEUP_HANDICAP = 58  # 36 + 22
_AWAY_LINEUP_HANDICAP = 99  # 45 + 54

# One week of dues from four bowlers at 1200 cents less 500 expense cents.
_COLLECTED_PRIZE_CENTS = 2800
_PLAN_BASIS_CENTS = 2800
_RESERVE_CENTS = 140            # 5 percent of 2800, floored
_ADMIN_FEE_CENTS = 80           # 3 percent of 2660, rounded half up
_NET_DISTRIBUTABLE_CENTS = 2580
_PLACE_ONE_CENTS = 1548         # floor(2580 * 0.60)
_PLACE_TWO_CENTS = 1032         # floor(2580 * 0.40)
_UNDISTRIBUTED_AFTER_DISBURSEMENT = 220   # the reserve plus the admin fee

# ─── field groups ──────────────────────────────────────
_MEMBERSHIP_CERTIFIED_FIELDS = (
    "certified_games",
    "certified_pins",
    "current_average",
    "average_status",
    "handicap_per_game",
)
_TEAM_FIGURE_FIELDS = ("total_points", "total_scratch_pins", "team_handicap_per_game")
_MATCH_UNTOUCHED_FIELDS = (
    "status",
    "version",
    "updated_at",
    "home_points",
    "away_points",
    "certified_at",
    "home_team_handicap_per_game",
    "away_team_handicap_per_game",
)
_FUND_MONEY_FIELDS = (
    "collected_prize_cents",
    "paid_award_total_cents",
    "undistributed_balance_cents",
)


# ─── private helpers ───────────────────────────────────

def _memberships(scn: fx.Scenario) -> List[Dict[str, Any]]:
    """Fresh reads of every enrolled membership, in roster order."""
    return [scn.membership(index) for index in range(len(scn.membership_ids))]


def _teams(scn: fx.Scenario) -> List[Dict[str, Any]]:
    return [scn.team(index) for index in range(len(scn.team_ids))]


def _certified_ledger_for(scn: fx.Scenario, membership_id: str) -> Tuple[int, int]:
    """Re-derive one bowler's certified ledger from the slots themselves.

    The certified-pin invariant says a membership's ``certified_games`` and
    ``certified_pins`` equal the sums over exactly those of its slots that are
    certified *and* count toward the average, so this recomputes both totals from
    the slot listing rather than trusting the membership row.
    """
    rows = get_success_data(
        scn.api.list_series_entries(
            scn.secretary, params={"membership_id": membership_id, "limit": 100}
        )
    )
    counting = [
        row for row in rows if row.get("certified") and row.get("counts_toward_average")
    ]
    games = sum(row["games_recorded"] for row in counting)
    pins = sum(row["scratch_series"] for row in counting)
    return games, pins


def _assert_certified_ledger_identity(scn: fx.Scenario) -> None:
    """Every membership's stored ledger must agree with its own slots."""
    for index, membership in enumerate(_memberships(scn)):
        games, pins = _certified_ledger_for(scn, scn.membership_ids[index])
        assert_fields(membership, certified_games=games, certified_pins=pins)


def _lineups_submitted_league(api: ApiClient) -> fx.Scenario:
    """A sanctioned league whose week-one match has both lineups in.

    The match is therefore one legal step away from being opened, so the only
    thing left that can refuse the opening is the state of another entity.
    """
    scn = fx.build_sanctioned_league(api)
    fx.submit_both_lineups(scn, 0)
    return scn


_THREE_TEAM_NAMES = ("Alley Cats", "Bench Warmers", "Pin Pals")
_THREE_TEAM_ROSTER = (
    fx.RosterSpec("Cara Captain", MemberClass.ADULT, 180, 30, 0),
    fx.RosterSpec("Dan Bowler", MemberClass.ADULT, 195, 30, 0),
    fx.RosterSpec("Gil Bench", MemberClass.ADULT, 150, 30, 1),
    fx.RosterSpec("Hal Bench", MemberClass.ADULT, 155, 30, 1),
    fx.RosterSpec("Eve Captain", MemberClass.ADULT, 170, 30, 2),
    fx.RosterSpec("Fay Bowler", MemberClass.ADULT, 160, 30, 2),
)


def _league_with_one_unconfirmed_team(api: ApiClient) -> fx.Scenario:
    """A sanctioned league in which the away side is still provisional.

    Three teams are enrolled but only the first two rosters are put through the
    association, which is enough to sanction the league itself while leaving the
    third team short of confirmation.  Week one pits the confirmed home team
    against that unconfirmed away team.
    """
    scn = fx.build_league(
        api,
        team_names=_THREE_TEAM_NAMES,
        roster=_THREE_TEAM_ROSTER,
        with_schedule=False,
    )
    fx.adopt_schedule(
        scn,
        [
            f.schedule_match(
                1,
                scn.team_ids[0],
                scn.team_ids[2],
                scn.lane_pair_ids[0],
                WEEK1_STARTS_AT,
                WEEK1_ENDS_AT,
            )
        ],
        total_weeks=1,
    )
    fx.sanction(scn, scn.membership_ids[:4])
    return scn


def _home_lineup(scn: fx.Scenario, team_index: int, membership_indexes: Tuple[int, ...]):
    """The lineup payload for one side, echoing the match's current version."""
    return f.lineup_payload(
        scn.match_version(0),
        scn.team_ids[team_index],
        fx.regular_slots(scn, membership_indexes),
    )


def _league_awaiting_schedule(api: ApiClient) -> fx.Scenario:
    """A league with bylaws, teams, roster and one lane pair but no schedule."""
    return fx.build_league(api, with_schedule=False)


def _touching_windows(scn: fx.Scenario) -> List[Dict[str, Any]]:
    """Two bookings of the same lane pair that meet at a single instant."""
    return [
        f.schedule_match(
            1, scn.team_ids[0], scn.team_ids[1], scn.lane_pair_ids[0],
            WEEK1_STARTS_AT, WEEK1_ENDS_AT,
        ),
        f.schedule_match(
            2, scn.team_ids[1], scn.team_ids[0], scn.lane_pair_ids[0],
            _TOUCHING_STARTS_AT, _TOUCHING_ENDS_AT,
        ),
    ]


def _travel_buffer_league(api: ApiClient) -> fx.Scenario:
    """A sanctioned league with three weeks on three separate lane pairs.

    The lane pairs differ, so nothing here can trip the lane-pair rule; the only
    contended resource left is the bowler.  Week two opens exactly thirty minutes
    after week one ends and week three opens thirty-one minutes after it.
    """
    scn = fx.build_league(
        api,
        with_schedule=False,
        lane_pairs=(
            (1, LANE_CERTIFIED_THROUGH),
            (2, LANE_CERTIFIED_THROUGH),
            (3, LANE_CERTIFIED_THROUGH),
        ),
    )
    fx.adopt_schedule(
        scn,
        [
            f.schedule_match(
                1, scn.team_ids[0], scn.team_ids[1], scn.lane_pair_ids[0],
                WEEK1_STARTS_AT, WEEK1_ENDS_AT,
            ),
            f.schedule_match(
                2, scn.team_ids[1], scn.team_ids[0], scn.lane_pair_ids[1],
                _BUFFER_TOUCH_STARTS_AT, _BUFFER_TOUCH_ENDS_AT,
            ),
            f.schedule_match(
                3, scn.team_ids[0], scn.team_ids[1], scn.lane_pair_ids[2],
                _BUFFER_CLEAR_STARTS_AT, _BUFFER_CLEAR_ENDS_AT,
            ),
        ],
        total_weeks=3,
    )
    fx.sanction(scn)
    return scn


def _submit_home_lineup(
    scn: fx.Scenario, match_index: int, team_index: int, membership_indexes: Tuple[int, ...]
):
    """Submit one side's lineup for an arbitrary week, returning the response."""
    return scn.api.submit_lineup(
        scn.match_ids[match_index],
        f.lineup_payload(
            scn.match_version(match_index),
            scn.team_ids[team_index],
            fx.regular_slots(scn, membership_indexes),
        ),
        scn.captain(membership_indexes[0]),
    )


def _uphold_with_void(scn: fx.Scenario, match_index: int = 0, filed_by_index: int = 0):
    """File, review and uphold a score protest with the void remedy.

    Voiding a certified match is reachable only through this path, so the whole
    protest lifecycle is setup here and only the ruling response is handed back.
    """
    protest = get_success_data(
        scn.api.file_protest(
            f.protest_payload(
                scn.league_id,
                scn.membership_ids[filed_by_index],
                ProtestCategory.SCORE_ERROR,
                "The pinsetter double-counted a rack in all three games.",
                match_id=scn.match_ids[match_index],
            ),
            scn.bowler(filed_by_index),
        )
    )
    get_success_data(scn.api.review_protest(protest["id"], f.review_payload(), scn.secretary))
    return scn.api.rule_on_protest(
        protest["id"],
        f.ruling_payload(
            ProtestDecision.UPHOLD.value,
            "Pinfall was unreliable for the whole series, so the match is voided.",
            remedy=Remedy.VOID_MATCH,
        ),
        scn.secretary,
    )


def _bowled_week_one(api: ApiClient) -> fx.Scenario:
    """Week one opened and scored but deliberately not yet certified.

    Stopping here is what makes the pre-certification figures observable, so the
    later void can be checked against them rather than against a guess.
    """
    scn = fx.build_open_match(api)
    fx.enter_scores(scn, fx.score_entries_for(scn, 0), 0)
    return scn


def _two_place_fund_ready_to_pay(api: ApiClient) -> Tuple[fx.Scenario, Dict[str, Any]]:
    """A closed season with an approved two-place plan, captured pre-payment."""
    scn = fx.build_closed_season(api)
    fx.draft_plan(scn, BasisVariant.CERTIFIED_TO_DATE)
    fx.approve_plan(scn)
    return scn, snapshot(scn.prize_fund(), _FUND_MONEY_FIELDS)


def _single_place_fund_ready_to_pay(api: ApiClient) -> Tuple[fx.Scenario, Dict[str, Any]]:
    """The same season, but with the whole distributable sum on one place.

    A single-place plan is what makes total restoration observable: reversing the
    one paid award is by itself the reversal of every paid award.
    """
    scn = fx.build_closed_season(api, bylaws={"prize_place_weights": [1.00]})
    fx.draft_plan(scn, BasisVariant.CERTIFIED_TO_DATE)
    fx.approve_plan(scn)
    return scn, snapshot(scn.prize_fund(), _FUND_MONEY_FIELDS)


# ─── opening a match against the lane pair's lifecycle ─

def test_lane_pair_certification_lapses_as_the_clock_passes_its_through_date(api):
    """The pair's own status re-reads itself against the clock, untouched.

    Nothing writes to the lane pair here: only the clock moves past the instant
    the pair is certified through.  The row must nevertheless read back as
    expired while its stored ``certified_through`` and ``revoked_at`` — and its
    version — stay exactly as they were, because the status is a reading of the
    row rather than a value stored in it.

    Design: Difficulty/cross_entity_state_dependency/match_open_gated_on_lane_pair_certification_lifecycle
    """
    scn = _lineups_submitted_league(api)
    lane_pair_id = scn.lane_pair_ids[0]

    before = validate_success(scn.api.get_lane_pair(lane_pair_id, scn.secretary))
    assert_fields(
        before,
        certification_status=LanePairCertificationStatus.CERTIFIED.value,
        revoked_at=None,
    )
    assert_instant_equals(
        before["certified_through"], LANE_CERTIFIED_THROUGH, "certified_through"
    )

    fx.set_clock(api, _EXPIRY_CLOCK)

    after = validate_success(scn.api.get_lane_pair(lane_pair_id, scn.secretary))
    assert_fields(
        after,
        certification_status=LanePairCertificationStatus.EXPIRED.value,
        revoked_at=None,
        version=before["version"],
        updated_at=before["updated_at"],
    )
    assert_instant_equals(
        after["certified_through"], LANE_CERTIFIED_THROUGH, "certified_through"
    )


def test_match_open_is_refused_while_its_lane_pair_reads_expired(api):
    """A match with both lineups in is still blocked by the other entity.

    Every condition local to the match is satisfied — it is scheduled, both sides
    have submitted legal lineups and the clock has reached its window — so the
    refusal can only come from the certification of the lane pair it is booked
    on.  The refusal must leave the match and the league completely alone.

    Design: Difficulty/cross_entity_state_dependency/match_open_gated_on_lane_pair_certification_lifecycle
    """
    scn = _lineups_submitted_league(api)
    fx.set_clock(api, _EXPIRY_CLOCK)
    before = snapshot(scn.match(0), _MATCH_UNTOUCHED_FIELDS)
    assert before["status"] == MatchStatus.LINEUPS_SUBMITTED.value

    validate_error(
        scn.api.open_match(scn.match_ids[0], {}, scn.secretary),
        ApiErrorId.ERR_LANE_PAIR_NOT_CERTIFIED.value,
    )

    assert_restored(
        before,
        snapshot(scn.match(0), _MATCH_UNTOUCHED_FIELDS),
        "the refused opening",
    )
    assert_fields(scn.league(), status=LeagueStatus.SANCTIONED.value)


def test_match_open_succeeds_once_the_same_lane_pair_is_recertified(api):
    """Recertifying the other entity is what unblocks the match.

    The identical opening request that was refused a moment ago must now be
    accepted, without a single change to the match itself in between; the pair's
    ``last_certified_at`` records the instant of the recertification.

    Design: Difficulty/cross_entity_state_dependency/match_open_gated_on_lane_pair_certification_lifecycle
    """
    scn = _lineups_submitted_league(api)
    lane_pair_id = scn.lane_pair_ids[0]
    fx.set_clock(api, _EXPIRY_CLOCK)
    validate_error(
        scn.api.open_match(scn.match_ids[0], {}, scn.secretary),
        ApiErrorId.ERR_LANE_PAIR_NOT_CERTIFIED.value,
    )

    pair = validate_success(
        scn.api.set_lane_pair_certification(
            lane_pair_id, f.recertify_payload(_RECERTIFIED_THROUGH), scn.officer
        )
    )
    assert_fields(
        pair,
        certification_status=LanePairCertificationStatus.CERTIFIED.value,
        revoked_at=None,
    )
    assert_instant_equals(
        pair["certified_through"], _RECERTIFIED_THROUGH, "certified_through"
    )
    assert_instant_equals(pair["last_certified_at"], _EXPIRY_CLOCK, "last_certified_at")

    match = validate_success(scn.api.open_match(scn.match_ids[0], {}, scn.secretary))
    assert_fields(match, status=MatchStatus.OPEN.value)
    assert_fields(scn.league(), status=LeagueStatus.IN_SEASON.value)


# ─── submitting a lineup against the other side's state ─

def test_lineup_refused_while_the_opposing_team_is_still_provisional(api):
    """A confirmed side cannot submit against an unconfirmed opponent.

    The league is sanctioned because two *other* teams satisfied its declared
    count, so the match is scheduled and the submitting side is confirmed with a
    fully sanctioned pair of bowlers.  The only defect is on the opposing team,
    and that alone must refuse the submission and leave no slots behind.

    Design: Difficulty/cross_entity_state_dependency/lineup_gated_on_opposing_team_confirmation
    """
    scn = _league_with_one_unconfirmed_team(api)
    assert_fields(scn.league(), status=LeagueStatus.SANCTIONED.value, confirmed_team_count=2)
    assert_fields(scn.team(0), status=TeamStatus.CONFIRMED.value, sanctioned_roster_count=2)
    assert_fields(scn.team(2), status=TeamStatus.PROVISIONAL.value, sanctioned_roster_count=0)
    match_before = scn.match(0)
    assert_fields(match_before, status=MatchStatus.SCHEDULED.value)

    validate_error(
        scn.api.submit_lineup(
            scn.match_ids[0], _home_lineup(scn, 0, (0, 1)), scn.captain(0)
        ),
        ApiErrorId.ERR_TEAM_NOT_CONFIRMED.value,
    )

    rows, meta = validate_paginated(
        scn.api.list_series_entries(scn.secretary, params={"match_id": scn.match_ids[0]})
    )
    assert rows == [], f"a refused lineup must create no slots, found {rows}"
    assert meta["total_count"] == 0, f"slot count should be 0, got {meta['total_count']}"
    assert_fields(
        scn.match(0),
        status=MatchStatus.SCHEDULED.value,
        version=match_before["version"],
        home_team_handicap_per_game=0,
        away_team_handicap_per_game=0,
    )


def test_lineup_refused_for_the_unconfirmed_team_itself(api):
    """The gate reads both sides, not merely the opponent.

    Here the secretary — who may act for either side and so cannot trip the
    ownership check — submits for the unconfirmed team.  Its own bowlers are not
    sanctioned either, but the confirmation of the team is consulted first, so
    that is the refusal that must come back.

    Design: Difficulty/cross_entity_state_dependency/lineup_gated_on_opposing_team_confirmation
    """
    scn = _league_with_one_unconfirmed_team(api)
    assert_fields(scn.membership(4), sanction_status=SanctionStatus.UNSANCTIONED.value)

    validate_error(
        scn.api.submit_lineup(
            scn.match_ids[0], _home_lineup(scn, 2, (4, 5)), scn.secretary
        ),
        ApiErrorId.ERR_TEAM_NOT_CONFIRMED.value,
    )

    rows, _ = validate_paginated(
        scn.api.list_series_entries(scn.secretary, params={"match_id": scn.match_ids[0]})
    )
    assert rows == [], f"a refused lineup must create no slots, found {rows}"


def test_lineup_accepted_once_the_opposing_roster_reaches_confirmation(api):
    """Sanctioning the opponent's roster is what unblocks the submission.

    The identical request that was refused is replayed after a second remittance
    confirms the away team.  The league's own status does not change — it was
    already sanctioned — so the acceptance is attributable to the opposing team's
    confirmation and nothing else.

    Design: Difficulty/cross_entity_state_dependency/lineup_gated_on_opposing_team_confirmation
    """
    scn = _league_with_one_unconfirmed_team(api)
    validate_error(
        scn.api.submit_lineup(
            scn.match_ids[0], _home_lineup(scn, 0, (0, 1)), scn.captain(0)
        ),
        ApiErrorId.ERR_TEAM_NOT_CONFIRMED.value,
    )
    version_before = scn.match_version(0)

    fx.sanction(scn, scn.membership_ids[4:])
    assert_fields(
        scn.team(2),
        status=TeamStatus.CONFIRMED.value,
        sanctioned_roster_count=2,
        team_handicap_per_game=_AWAY_LINEUP_HANDICAP,
    )
    assert_fields(
        scn.league(),
        status=LeagueStatus.SANCTIONED.value,
        confirmed_team_count=3,
        declared_team_count=2,
        sanctioned_member_count=6,
    )

    match = validate_success(
        scn.api.submit_lineup(
            scn.match_ids[0], _home_lineup(scn, 0, (0, 1)), scn.captain(0)
        )
    )
    assert_fields(
        match,
        status=MatchStatus.SCHEDULED.value,
        version=version_before + 1,
        home_team_handicap_per_game=_HOME_LINEUP_HANDICAP,
        away_team_handicap_per_game=0,
    )


# ─── lane-pair occupation windows are half-open ────────

def test_touching_lane_pair_windows_are_adopted_together(api):
    """One booking ending exactly where the next begins is not a collision.

    The occupation window runs from ``starts_at`` inclusive to ``ends_at``
    exclusive, so week two may begin at the very instant week one ends on the
    same pair.  Both matches must be created, in draft, with zeroed points and
    zeroed frozen handicaps.

    Design: Difficulty/resource_temporal_overlap/lane_pair_half_open_windows_touch_ok_overlap_rejected_atomically
    """
    scn = _league_awaiting_schedule(api)

    matches = validate_success(
        scn.api.adopt_schedule(
            scn.league_id,
            f.schedule_payload(2, _touching_windows(scn)),
            scn.secretary,
        ),
        201,
    )

    assert isinstance(matches, list) and len(matches) == 2, (
        f"schedule adoption should create both matches, got {matches}"
    )
    week_one, week_two = matches
    for match in matches:
        assert_fields(
            match,
            status=MatchStatus.DRAFT.value,
            lane_pair_id=scn.lane_pair_ids[0],
            home_team_handicap_per_game=0,
            away_team_handicap_per_game=0,
            certified_at=None,
            forfeiting_team_id=None,
        )
        assert_points(match["home_points"], 0.0, "home_points")
        assert_points(match["away_points"], 0.0, "away_points")
    assert_instant_equals(week_one["ends_at"], WEEK1_ENDS_AT, "week one ends_at")
    assert_instant_equals(week_two["starts_at"], _TOUCHING_STARTS_AT, "week two starts_at")
    assert_instant_equals(week_two["ends_at"], _TOUCHING_ENDS_AT, "week two ends_at")
    assert_fields(
        scn.league(),
        status=LeagueStatus.BYLAWS_ADOPTED.value,
        total_weeks=2,
        certified_week_high_water=0,
    )


def test_overlapping_lane_pair_windows_are_refused(api):
    """A single shared minute on one pair refuses the whole batch.

    The third booking begins one minute before week one's exclusive end, so it
    genuinely overlaps a window on the same lane pair, and the batch as a whole
    must come back as a conflict rather than being partially applied.

    Design: Difficulty/resource_temporal_overlap/lane_pair_half_open_windows_touch_ok_overlap_rejected_atomically
    """
    scn = _league_awaiting_schedule(api)
    batch = _touching_windows(scn) + [
        f.schedule_match(
            3, scn.team_ids[0], scn.team_ids[1], scn.lane_pair_ids[0],
            _OVERLAPPING_STARTS_AT, _OVERLAPPING_ENDS_AT,
        )
    ]

    validate_error(
        scn.api.adopt_schedule(scn.league_id, f.schedule_payload(3, batch), scn.secretary),
        ApiErrorId.ERR_LANE_PAIR_CONFLICT.value,
    )


def test_a_lane_pair_collision_leaves_no_match_behind(api):
    """The refusal is all-or-nothing, including the two innocent bookings.

    Two of the three bookings in the refused batch collide with nothing at all,
    yet neither may survive: no match is created, the league keeps its zero
    ``total_weeks`` and stays adoptable, which the immediately following legal
    batch demonstrates.

    Design: Difficulty/resource_temporal_overlap/lane_pair_half_open_windows_touch_ok_overlap_rejected_atomically
    """
    scn = _league_awaiting_schedule(api)
    batch = _touching_windows(scn) + [
        f.schedule_match(
            3, scn.team_ids[0], scn.team_ids[1], scn.lane_pair_ids[0],
            _OVERLAPPING_STARTS_AT, _OVERLAPPING_ENDS_AT,
        )
    ]
    validate_error(
        scn.api.adopt_schedule(scn.league_id, f.schedule_payload(3, batch), scn.secretary),
        ApiErrorId.ERR_LANE_PAIR_CONFLICT.value,
    )

    rows, meta = validate_paginated(
        scn.api.list_matches(scn.secretary, params={"league_id": scn.league_id})
    )
    assert rows == [], f"a refused schedule must create no match at all, found {rows}"
    assert meta["total_count"] == 0, f"match count should be 0, got {meta['total_count']}"
    assert_fields(
        scn.league(), status=LeagueStatus.BYLAWS_ADOPTED.value, total_weeks=0
    )

    retried = validate_success(
        scn.api.adopt_schedule(
            scn.league_id, f.schedule_payload(2, _touching_windows(scn)), scn.secretary
        ),
        201,
    )
    assert len(retried) == 2, f"the legal batch should still be adoptable, got {retried}"
    assert_fields(scn.league(), total_weeks=2)


# ─── the bowler's travel buffer is a closed interval ───

def test_a_thirty_minute_travel_gap_still_conflicts_for_the_bowler(api):
    """Week one widened by the buffer touches a week-two window at its edge.

    The three weeks sit on three different lane pairs, so the lane-pair rule is
    out of the picture and the contended resource is the bowler alone.  Week one
    runs to 03:00Z; widened by thirty minutes on both sides it closes at 03:30Z,
    which is exactly when week two opens — and a closed interval that touches is
    a conflict.

    Design: Difficulty/resource_temporal_overlap/bowler_travel_buffer_closed_interval_thirty_minutes_conflicts
    """
    scn = _travel_buffer_league(api)
    week_one = validate_success(_submit_home_lineup(scn, 0, 0, (0, 1)))
    assert_fields(
        week_one,
        status=MatchStatus.SCHEDULED.value,
        home_team_handicap_per_game=_HOME_LINEUP_HANDICAP,
    )

    validate_error(
        _submit_home_lineup(scn, 1, 0, (0, 1)),
        ApiErrorId.ERR_BOWLER_SCHEDULE_CONFLICT.value,
    )


def test_a_thirty_one_minute_travel_gap_clears_the_buffer(api):
    """One further minute of clearance makes the same bowlers submittable.

    Week three opens thirty-one minutes after week one ends, which is outside the
    widened interval, so the identical pair of bowlers may be named again.  Their
    frozen slot handicaps are the entering figures the bylaws produce, and both
    slots count toward the average.

    Design: Difficulty/resource_temporal_overlap/bowler_travel_buffer_closed_interval_thirty_minutes_conflicts
    """
    scn = _travel_buffer_league(api)
    validate_success(_submit_home_lineup(scn, 0, 0, (0, 1)))

    week_three = validate_success(_submit_home_lineup(scn, 2, 0, (0, 1)))
    assert_fields(
        week_three,
        status=MatchStatus.SCHEDULED.value,
        home_team_handicap_per_game=_HOME_LINEUP_HANDICAP,
        away_team_handicap_per_game=0,
    )

    slots = {row["membership_id"]: row for row in scn.series_entries(2)}
    for roster_index in (0, 1):
        slot = slots[scn.membership_ids[roster_index]]
        assert_fields(
            slot,
            entry_type=EntryType.REGULAR.value,
            counts_toward_average=True,
            certified=False,
            handicap_per_game_applied=_ENTERING_HANDICAPS[roster_index],
            games_recorded=0,
            scratch_series=0,
        )


def test_a_refused_travel_buffer_submission_creates_no_slots(api):
    """The conflicting week keeps neither slots nor a version bump.

    Only the version of the match that actually accepted a lineup may move; the
    refused week must be exactly as the schedule left it, so the same bowlers can
    later be named on a week that does clear the buffer.

    Design: Difficulty/resource_temporal_overlap/bowler_travel_buffer_closed_interval_thirty_minutes_conflicts
    """
    scn = _travel_buffer_league(api)
    validate_success(_submit_home_lineup(scn, 0, 0, (0, 1)))
    before = snapshot(scn.match(1), _MATCH_UNTOUCHED_FIELDS)

    validate_error(
        _submit_home_lineup(scn, 1, 0, (0, 1)),
        ApiErrorId.ERR_BOWLER_SCHEDULE_CONFLICT.value,
    )

    assert_restored(
        before, snapshot(scn.match(1), _MATCH_UNTOUCHED_FIELDS), "the refused lineup"
    )
    rows, meta = validate_paginated(
        scn.api.list_series_entries(scn.secretary, params={"match_id": scn.match_ids[1]})
    )
    assert rows == [], f"the refused week must hold no slots, found {rows}"
    assert meta["total_count"] == 0, f"slot count should be 0, got {meta['total_count']}"


# ─── voiding a certified match restores every pin ───────

def test_voiding_a_certified_match_restores_each_bowler_exactly(api):
    """Certification then a void must land on the pre-certification integers.

    The bowlers' figures are captured while the match is scored but uncertified,
    then certification moves all five of them — games, pins, average, average
    status and handicap — and the upheld void must put every one of them back.
    One bowler's handicap genuinely moves and comes back, so this is not a
    comparison of two identical zeroes.

    Design: Difficulty/compensating_invariant/void_match_restores_certified_pins_and_handicaps_exactly
    """
    scn = _bowled_week_one(api)
    before = [snapshot(row, _MEMBERSHIP_CERTIFIED_FIELDS) for row in _memberships(scn)]
    for index, row in enumerate(_memberships(scn)):
        assert_fields(
            row,
            certified_games=0,
            certified_pins=0,
            handicap_per_game=_ENTERING_HANDICAPS[index],
        )

    fx.certify_match(scn, 0)
    for index, row in enumerate(_memberships(scn)):
        assert_fields(
            row,
            certified_games=3,
            certified_pins=_CERTIFIED_PINS[index],
            handicap_per_game=_CERTIFIED_HANDICAPS[index],
        )

    ruling = validate_success(_uphold_with_void(scn))
    assert_fields(
        ruling,
        status=ProtestStatus.UPHELD.value,
        remedy=Remedy.VOID_MATCH.value,
        review_round=1,
    )

    for index, row in enumerate(_memberships(scn)):
        assert_restored(
            before[index],
            snapshot(row, _MEMBERSHIP_CERTIFIED_FIELDS),
            f"voiding week one (roster index {index})",
        )
    _assert_certified_ledger_identity(scn)


def test_voiding_a_certified_match_restores_the_team_standings(api):
    """The team figures the certification absorbed are given back in full.

    Certification hands the home side all four points and both sides their
    scratch pins, and re-derives both team handicaps from the new averages.  A
    void match contributes nothing to the standings, so all of that must reverse
    while the match itself lands on zeroed points with no certification stamp.

    Design: Difficulty/compensating_invariant/void_match_restores_certified_pins_and_handicaps_exactly
    """
    scn = _bowled_week_one(api)
    before = [snapshot(row, _TEAM_FIGURE_FIELDS) for row in _teams(scn)]

    fx.certify_match(scn, 0)
    home, away = _teams(scn)
    assert_points(home["total_points"], 4.0, "home total_points")
    assert_points(away["total_points"], 0.0, "away total_points")
    assert_fields(home, total_scratch_pins=1260, team_handicap_per_game=54)
    assert_fields(away, total_scratch_pins=930, team_handicap_per_game=_AWAY_LINEUP_HANDICAP)

    ruling = validate_success(_uphold_with_void(scn))

    for index, row in enumerate(_teams(scn)):
        assert_restored(
            before[index],
            snapshot(row, _TEAM_FIGURE_FIELDS),
            f"voiding week one (team index {index})",
        )
    match = scn.match(0)
    assert_fields(match, status=MatchStatus.VOID.value, certified_at=None)
    assert_points(match["home_points"], 0.0, "home_points")
    assert_points(match["away_points"], 0.0, "away_points")
    assert match["void_reason"], "a voided match must record why it was voided"
    assert ruling["id"] in match["void_reason"], (
        f"void_reason should name the protest {ruling['id']}, got {match['void_reason']!r}"
    )


def test_voiding_a_certified_match_decertifies_slots_without_erasing_pins(api):
    """The pins stay on the slots; only their certification is withdrawn.

    Decertification is not a deletion: each slot keeps the three games it
    recorded and its scratch series, and keeps counting toward the average by
    type, so the bowler's ledger falls back to zero purely because no slot of the
    voided match is certified any longer.

    Design: Difficulty/compensating_invariant/void_match_restores_certified_pins_and_handicaps_exactly
    """
    scn = _bowled_week_one(api)
    fx.certify_match(scn, 0)
    for row in scn.series_entries(0):
        assert_fields(row, certified=True)

    validate_success(_uphold_with_void(scn))

    slots = {row["membership_id"]: row for row in scn.series_entries(0)}
    for index in range(4):
        row = slots[scn.membership_ids[index]]
        assert_fields(
            row,
            certified=False,
            counts_toward_average=True,
            entry_type=EntryType.REGULAR.value,
            games_recorded=3,
            scratch_series=_CERTIFIED_PINS[index],
        )
    _assert_certified_ledger_identity(scn)


def test_voiding_a_certified_match_keeps_the_settled_week_settled(api):
    """A void is a settled outcome, so the high-water mark does not retreat.

    This is the one figure the compensation deliberately does *not* put back: the
    week-one high water rises on certification and stays where it is, because a
    voided match counts as settled just as a certified one does.  The league keeps
    its in-season status and its sanctioned head count.

    Design: Difficulty/compensating_invariant/void_match_restores_certified_pins_and_handicaps_exactly
    """
    scn = _bowled_week_one(api)
    assert_fields(scn.league(), certified_week_high_water=0)

    fx.certify_match(scn, 0)
    assert_fields(scn.league(), certified_week_high_water=1)

    validate_success(_uphold_with_void(scn))

    assert_fields(
        scn.league(),
        certified_week_high_water=1,
        status=LeagueStatus.IN_SEASON.value,
        sanctioned_member_count=4,
    )


# ─── reversing an award returns the money to the cent ───

def test_reversing_one_award_returns_exactly_its_amount_to_the_balance(api):
    """The balance moves by the reversed award's amount and by nothing else.

    Four bowlers paying one settled week fund 2800 cents, from which the
    waterfall pays 1548 and 1032 and keeps 220 back as the reserve and the
    administrative fee.  Reversing the first place must lift the undistributed
    balance by exactly 1548, leaving the second place paid and the collected
    total untouched.

    Design: Difficulty/compensating_invariant/award_reversal_restores_undistributed_balance_to_the_cent
    """
    scn, before = _two_place_fund_ready_to_pay(api)
    assert_cents(before["collected_prize_cents"], _COLLECTED_PRIZE_CENTS, "collected_prize_cents")
    assert_cents(before["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert_cents(
        before["undistributed_balance_cents"], _COLLECTED_PRIZE_CENTS, "undistributed_balance_cents"
    )

    fx.disburse(scn)
    fund = scn.prize_fund()
    assert_cents(fund["paid_award_total_cents"], _NET_DISTRIBUTABLE_CENTS, "paid_award_total_cents")
    assert_cents(
        fund["undistributed_balance_cents"],
        _UNDISTRIBUTED_AFTER_DISBURSEMENT,
        "undistributed_balance_cents",
    )
    assert_prize_money_invariant(fund)
    awards = fx.awards_of_fund(scn)
    assert len(awards) == 2, f"a two-place plan pays two awards, got {awards}"

    reversed_award = validate_success(
        scn.api.reverse_award(
            awards[0]["id"],
            f.reversal_payload("The first-place cheque came back unpresented."),
            scn.treasurer,
        )
    )
    assert_fields(reversed_award, place=1, status=PrizeAwardStatus.REVERSED.value)
    assert_cents(reversed_award["amount_cents"], _PLACE_ONE_CENTS, "amount_cents")
    assert reversed_award["reversal_reason"], "a reversal must record its reason"

    fund = scn.prize_fund()
    assert_cents(fund["paid_award_total_cents"], _PLACE_TWO_CENTS, "paid_award_total_cents")
    assert_cents(
        fund["undistributed_balance_cents"],
        _UNDISTRIBUTED_AFTER_DISBURSEMENT + _PLACE_ONE_CENTS,
        "undistributed_balance_cents",
    )
    assert_cents(fund["collected_prize_cents"], _COLLECTED_PRIZE_CENTS, "collected_prize_cents")
    assert_prize_money_invariant(fund)
    assert_fields(fx.awards_of_fund(scn)[1], place=2, status=PrizeAwardStatus.PAID.value)


def test_the_first_reversal_undisburses_the_fund_and_the_league(api):
    """One reversal is enough to undo the disbursement of the whole plan.

    The plan is no longer fully paid the moment a single award comes back, so the
    fund returns to approved with its disbursement stamp cleared and the league
    returns to closed — even though the second award is still paid.

    Design: Difficulty/compensating_invariant/award_reversal_restores_undistributed_balance_to_the_cent
    """
    scn, _ = _two_place_fund_ready_to_pay(api)
    fx.disburse(scn)
    fund = scn.prize_fund()
    assert_fields(fund, status=PrizeFundStatus.DISBURSED.value)
    assert fund["disbursed_at"], "disbursement must stamp disbursed_at"
    assert_fields(scn.league(), status=LeagueStatus.PRIZES_DISBURSED.value)

    awards = fx.awards_of_fund(scn)
    validate_success(
        scn.api.reverse_award(
            awards[0]["id"], f.reversal_payload("Paid to the wrong side."), scn.treasurer
        )
    )

    fund = scn.prize_fund()
    assert_fields(fund, status=PrizeFundStatus.PLAN_APPROVED.value, disbursed_at=None)
    assert_fields(scn.league(), status=LeagueStatus.SEASON_CLOSED.value)
    assert_fields(fx.awards_of_fund(scn)[1], status=PrizeAwardStatus.PAID.value)


def test_a_reversal_preserves_the_plan_and_the_award_amounts(api):
    """Compensation moves money, not the plan that computed it.

    The waterfall figures, the place count, the recorded approver and each
    award's own amount all survive the reversal untouched: a reversed award keeps
    its 1548 cents on the row, because zeroing it would destroy the audit trail
    the reversal exists to create.

    Design: Difficulty/compensating_invariant/award_reversal_restores_undistributed_balance_to_the_cent
    """
    scn, _ = _two_place_fund_ready_to_pay(api)
    fx.disburse(scn)
    awards = fx.awards_of_fund(scn)
    assert_cents(awards[0]["amount_cents"], _PLACE_ONE_CENTS, "place one amount_cents")
    assert_cents(awards[1]["amount_cents"], _PLACE_TWO_CENTS, "place two amount_cents")

    validate_success(
        scn.api.reverse_award(
            awards[0]["id"], f.reversal_payload("Bank returned the item."), scn.treasurer
        )
    )

    fund = scn.prize_fund()
    assert_fields(
        fund,
        basis_variant=BasisVariant.CERTIFIED_TO_DATE.value,
        place_count=2,
        plan_approved_by_user_id=scn.secretary_member_id,
    )
    assert_cents(fund["plan_basis_cents"], _PLAN_BASIS_CENTS, "plan_basis_cents")
    assert_cents(fund["reserve_cents"], _RESERVE_CENTS, "reserve_cents")
    assert_cents(fund["admin_fee_cents"], _ADMIN_FEE_CENTS, "admin_fee_cents")
    assert_cents(
        fund["net_distributable_cents"], _NET_DISTRIBUTABLE_CENTS, "net_distributable_cents"
    )
    after = fx.awards_of_fund(scn)
    assert_cents(after[0]["amount_cents"], _PLACE_ONE_CENTS, "reversed amount_cents")
    assert_cents(after[1]["amount_cents"], _PLACE_TWO_CENTS, "place two amount_cents")
    assert after[0]["weight"] == 0.60, f"place one weight should be 0.60, got {after[0]['weight']}"
    assert after[1]["weight"] == 0.40, f"place two weight should be 0.40, got {after[1]['weight']}"


def test_reversing_every_paid_award_restores_the_pre_payment_balance(api):
    """With the whole plan on one place, one reversal undoes the disbursement.

    Putting the entire distributable sum on a single place is what makes total
    restoration observable: reversing that award *is* reversing every paid award,
    so the undistributed balance must return to its exact pre-disbursement value
    of 2800 cents and the paid total to zero, with the collected total never
    having moved.

    Design: Difficulty/compensating_invariant/award_reversal_restores_undistributed_balance_to_the_cent
    """
    scn, before = _single_place_fund_ready_to_pay(api)
    awards = fx.awards_of_fund(scn)
    assert len(awards) == 1, f"a single-place plan pays one award, got {awards}"
    assert_cents(awards[0]["amount_cents"], _NET_DISTRIBUTABLE_CENTS, "amount_cents")

    fx.disburse(scn)
    fund = scn.prize_fund()
    assert_cents(fund["paid_award_total_cents"], _NET_DISTRIBUTABLE_CENTS, "paid_award_total_cents")
    assert_cents(
        fund["undistributed_balance_cents"],
        _UNDISTRIBUTED_AFTER_DISBURSEMENT,
        "undistributed_balance_cents",
    )

    reversed_award = validate_success(
        scn.api.reverse_award(
            awards[0]["id"],
            f.reversal_payload("The league voided the standings that decided the place."),
            scn.treasurer,
        )
    )
    assert_fields(reversed_award, status=PrizeAwardStatus.REVERSED.value)

    fund = scn.prize_fund()
    assert_restored(
        before, snapshot(fund, _FUND_MONEY_FIELDS), "reversing every paid award of the fund"
    )
    assert_cents(fund["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert_cents(
        fund["undistributed_balance_cents"], _COLLECTED_PRIZE_CENTS, "undistributed_balance_cents"
    )
    assert_prize_money_invariant(fund)
    assert_fields(fund, status=PrizeFundStatus.PLAN_APPROVED.value, disbursed_at=None)
    assert_fields(scn.league(), status=LeagueStatus.SEASON_CLOSED.value)
