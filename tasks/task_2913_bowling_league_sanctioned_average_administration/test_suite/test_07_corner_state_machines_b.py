"""State-machine corners, part two: the lane pair, the forfeit, the season
close, the prize-fund plan and the mid-season bylaw amendment.

Every scenario in this module runs on the shared bylaw configuration adopted by
``test_helpers.fixtures`` — ``handicap_base`` 220, ``handicap_percentage`` 0.90,
``max_handicap_per_game`` 60, ``handicap_average_basis`` ``CURRENT``,
``minimum_games_for_average`` 9, ``carryover_policy`` ``BLENDED``,
``lineup_positions`` 2, ``weekly_dues_cents`` 1200, ``weekly_expense_cents``
500 and ``prize_place_weights`` ``[0.60, 0.40]`` — so the pinned integers below
are all derivable from PRD §3.6 and §3.7 against that one configuration.
"""
from typing import Any, Dict

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
    assert_instant_equals,
    assert_points,
)
from test_helpers.constants import (
    LANE_CERTIFIED_THROUGH,
    ORG_MEETING_INSTANT,
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
    SanctionStatus,
    TeamStatus,
    AverageStatus,
)

# A lane certification that lapses between the organizational meeting and week
# one, so the pair expires with no request ever addressed to it (PRD §2.4).
SHORT_CERTIFIED_THROUGH = "2026-08-10T00:00:00Z"
# One day after that lapse, and still before week one's start.
AFTER_LAPSE_INSTANT = "2026-08-11T00:00:00Z"
# A replacement certification comfortably later than the clock.
REPLACEMENT_CERTIFIED_THROUGH = "2026-12-31T00:00:00Z"
FAR_FUTURE_CERTIFIED_THROUGH = "2027-12-31T00:00:00Z"

# The fifth bowler of the amendment scenario: enrolled, carrying a prior-season
# record, but never listed on a remittance and therefore never sanctioned.
UNSANCTIONED_SUB = fx.RosterSpec("Gus Sub", MemberClass.ADULT, 175, 30, 0)


def _lane_pair(scn: fx.Scenario, index: int = 0) -> Dict[str, Any]:
    """Read the pair through the API so its derived status is re-evaluated."""
    return validate_success(
        scn.api.get_lane_pair(scn.lane_pair_ids[index], scn.officer)
    )


def _certified_week_one_with_dues(api: ApiClient) -> fx.Scenario:
    """Week one certified and every bowler's week-one dues collected.

    Four payments of 1200 cents each split 700 to the prize fund, so the fund
    holds ``collected_prize_cents`` 2800 while still ``ACCUMULATING``.
    """
    scn = fx.build_certified_match(api)
    fx.pay_dues_for_all(scn, 1)
    return scn


def _certified_week_one_with_an_unsanctioned_bowler(api: ApiClient) -> fx.Scenario:
    """Week one certified in a league carrying a fifth, unsanctioned membership.

    Only the first four memberships are listed on the remittance, so the fifth
    stays ``UNSANCTIONED`` with ``handicap_per_game`` 0 throughout.
    """
    scn = fx.build_league(api, roster=tuple(fx.DEFAULT_ROSTER) + (UNSANCTIONED_SUB,))
    fx.sanction(scn, scn.membership_ids[:4])
    fx.submit_both_lineups(scn, 0)
    fx.set_clock(api, WEEK1_STARTS_AT)
    fx.open_match(scn, 0)
    fx.enter_scores(scn, fx.score_entries_for(scn, 0), 0)
    fx.certify_match(scn, 0)
    return scn


# ─── REVOKED is terminal in both directions (PRD §3.4, §3.5) ──────────────

def test_revoked_lane_pair_blocks_opening_the_assigned_match(api: ApiClient):
    """Revoking a pair sets `revoked_at` to the clock and derives `REVOKED`,
    and every future opening on that pair is refused.

    The pair's own `certified_through` of 2026-12-31 is comfortably after the
    match's `starts_at`, so the temporal check of PRD §3.5 would have passed;
    the refusal is the revocation check, which the §2.6 order consults first,
    and it carries no league or match transition with it.

    Design: Corner/state_machines/corner_lane_pair_revoke_blocks_open_and_any_recertification
    """
    scn = fx.build_sanctioned_league(api)
    fx.submit_both_lineups(scn, 0)
    pair_id = scn.lane_pair_ids[0]

    revoked = validate_success(
        api.set_lane_pair_certification(pair_id, f.revoke_payload(), scn.officer)
    )
    assert_fields(
        revoked,
        certification_status=LanePairCertificationStatus.REVOKED.value,
    )
    assert_instant_equals(revoked["revoked_at"], ORG_MEETING_INSTANT, "revoked_at")

    fx.set_clock(api, WEEK1_STARTS_AT)
    validate_error(
        api.open_match(scn.match_ids[0], {}, scn.secretary),
        ApiErrorId.ERR_LANE_PAIR_NOT_CERTIFIED.value,
    )

    assert_fields(scn.match(0), status=MatchStatus.LINEUPS_SUBMITTED.value)
    assert_fields(scn.league(), status=LeagueStatus.SANCTIONED.value)


def test_recertification_cannot_revive_a_revoked_lane_pair(api: ApiClient):
    """A `RECERTIFY` aimed at a pair whose `revoked_at` is already set is
    refused rather than reviving the pair, and writes nothing.

    `revoked_at` is never cleared, so the refused action leaves the original
    `certified_through` and the original revocation instant exactly as they
    were.

    Design: Corner/state_machines/corner_lane_pair_revoke_blocks_open_and_any_recertification
    """
    scn = fx.build_sanctioned_league(api)
    pair_id = scn.lane_pair_ids[0]
    validate_success(
        api.set_lane_pair_certification(pair_id, f.revoke_payload(), scn.officer)
    )

    validate_error(
        api.set_lane_pair_certification(
            pair_id,
            f.recertify_payload(FAR_FUTURE_CERTIFIED_THROUGH),
            scn.officer,
        ),
        ApiErrorId.ERR_LANE_PAIR_NOT_CERTIFIED.value,
    )

    pair = _lane_pair(scn)
    assert_fields(
        pair, certification_status=LanePairCertificationStatus.REVOKED.value
    )
    assert_instant_equals(
        pair["certified_through"], LANE_CERTIFIED_THROUGH, "certified_through"
    )
    assert_instant_equals(pair["revoked_at"], ORG_MEETING_INSTANT, "revoked_at")


# ─── CERTIFIED → EXPIRED → CERTIFIED, driven by the clock (PRD §3.4) ─────

def test_lane_pair_expires_by_the_clock_alone_and_blocks_the_open(api: ApiClient):
    """Advancing the clock past `certified_through` flips the derived status to
    `EXPIRED` with no request addressed to the pair, and the expiry alone is
    enough to refuse the match opening.

    `revoked_at` stays null throughout, and the refused opening leaves the
    match at `LINEUPS_SUBMITTED`.

    Design: Corner/state_machines/corner_lane_pair_expires_by_the_clock_then_recertification_revives_it
    """
    scn = fx.build_sanctioned_league(
        api, lane_pairs=((1, SHORT_CERTIFIED_THROUGH),)
    )
    fx.submit_both_lineups(scn, 0)

    assert_fields(
        _lane_pair(scn),
        certification_status=LanePairCertificationStatus.CERTIFIED.value,
    )

    fx.set_clock(api, AFTER_LAPSE_INSTANT)
    expired = _lane_pair(scn)
    assert_fields(
        expired,
        certification_status=LanePairCertificationStatus.EXPIRED.value,
        revoked_at=None,
    )
    assert_instant_equals(
        expired["certified_through"], SHORT_CERTIFIED_THROUGH, "certified_through"
    )

    validate_error(
        api.open_match(scn.match_ids[0], {}, scn.secretary),
        ApiErrorId.ERR_LANE_PAIR_NOT_CERTIFIED.value,
    )
    assert_fields(scn.match(0), status=MatchStatus.LINEUPS_SUBMITTED.value)


def test_recertification_revives_the_pair_and_the_open_reaches_in_season(api: ApiClient):
    """A replacement `certified_through` later than the clock moves the pair
    `EXPIRED → CERTIFIED` and resets `last_certified_at`, after which the
    identical opening succeeds and carries the league `SANCTIONED → IN_SEASON`.

    The frozen per-side team handicaps captured at lineup submission — 58 for
    the home side and 99 for the away side under the shared bylaws — are
    untouched by the expiry, the recertification and the opening alike.

    Design: Corner/state_machines/corner_lane_pair_expires_by_the_clock_then_recertification_revives_it
    """
    scn = fx.build_sanctioned_league(
        api, lane_pairs=((1, SHORT_CERTIFIED_THROUGH),)
    )
    fx.submit_both_lineups(scn, 0)
    assert_fields(
        scn.match(0),
        home_team_handicap_per_game=58,
        away_team_handicap_per_game=99,
    )

    fx.set_clock(api, AFTER_LAPSE_INSTANT)
    validate_error(
        api.open_match(scn.match_ids[0], {}, scn.secretary),
        ApiErrorId.ERR_LANE_PAIR_NOT_CERTIFIED.value,
    )

    recertified = validate_success(
        api.set_lane_pair_certification(
            scn.lane_pair_ids[0],
            f.recertify_payload(REPLACEMENT_CERTIFIED_THROUGH),
            scn.officer,
        )
    )
    assert_fields(
        recertified,
        certification_status=LanePairCertificationStatus.CERTIFIED.value,
        revoked_at=None,
    )
    assert_instant_equals(
        recertified["certified_through"],
        REPLACEMENT_CERTIFIED_THROUGH,
        "certified_through",
    )
    assert_instant_equals(
        recertified["last_certified_at"], AFTER_LAPSE_INSTANT, "last_certified_at"
    )

    fx.set_clock(api, WEEK1_STARTS_AT)
    opened = validate_success(api.open_match(scn.match_ids[0], {}, scn.secretary))
    assert_fields(
        opened,
        status=MatchStatus.OPEN.value,
        home_team_handicap_per_game=58,
        away_team_handicap_per_game=99,
    )
    assert_fields(scn.league(), status=LeagueStatus.IN_SEASON.value)


# ─── The forfeit preallocation from OPEN (PRD §3.5) ───────────────────────

def test_forfeit_from_open_replaces_the_slots_and_awards_four_whole_points(
    api: ApiClient,
):
    """Declaring a forfeit against the away side of an open match replaces that
    side's slots with `FORFEIT` rows and awards the opponent all four points.

    No game-by-game comparison is performed, the forfeiting side's frozen team
    handicap is recomputed from its new `FORFEIT` rows and therefore collapses
    to 0, and the opponent's own slots are left alone — still `REGULAR`, still
    counting toward average, and still uncertified.

    Design: Corner/state_machines/corner_forfeit_from_open_replaces_slots_and_awards_the_full_four_points
    """
    scn = fx.build_open_match(api)
    match = scn.match(0)
    assert_fields(
        match,
        status=MatchStatus.OPEN.value,
        home_team_id=scn.team_ids[0],
        away_team_id=scn.team_ids[1],
    )

    forfeited = validate_success(
        api.forfeit_match(
            scn.match_ids[0], f.forfeit_payload(scn.team_ids[1]), scn.secretary
        )
    )
    assert_fields(
        forfeited,
        status=MatchStatus.FORFEITED.value,
        forfeiting_team_id=scn.team_ids[1],
        home_team_handicap_per_game=58,
        away_team_handicap_per_game=0,
    )
    assert_points(forfeited["home_points"], 4.0, "home_points")
    assert_points(forfeited["away_points"], 0.0, "away_points")

    forfeit_rows = scn.series_entries(0, team_index=1)
    assert len(forfeit_rows) == 2, (
        f"the forfeiting side must carry exactly lineup_positions rows, "
        f"got {len(forfeit_rows)}"
    )
    assert sorted(row["position"] for row in forfeit_rows) == [1, 2]
    for row in forfeit_rows:
        assert_fields(
            row,
            entry_type=EntryType.FORFEIT.value,
            membership_id=None,
            game1_pins=0,
            game2_pins=0,
            game3_pins=0,
            games_recorded=0,
            scratch_series=0,
            handicap_per_game_applied=0,
            counts_toward_average=False,
            certified=False,
        )

    kept_rows = scn.series_entries(0, team_index=0)
    assert len(kept_rows) == 2
    for row in kept_rows:
        assert_fields(
            row,
            entry_type=EntryType.REGULAR.value,
            counts_toward_average=True,
            certified=False,
        )
        assert row["membership_id"] in scn.membership_ids[:2]


def test_forfeited_week_is_settled_for_standings_but_never_certified(api: ApiClient):
    """A forfeited week counts as settled for the standings and the league's
    high-water mark, yet certifies nothing.

    The winning side takes the four points into `total_points` while neither
    side's `total_scratch_pins` moves, because no pins were ever recorded; the
    roster flavour of the team handicap is untouched by a forfeit; and no
    membership's certified games, certified pins, average or handicap changes,
    because the certification cascade never runs on a match that is forfeited.

    Design: Corner/state_machines/corner_forfeit_from_open_replaces_slots_and_awards_the_full_four_points
    """
    scn = fx.build_open_match(api)
    validate_success(
        api.forfeit_match(
            scn.match_ids[0], f.forfeit_payload(scn.team_ids[1]), scn.secretary
        )
    )

    winner = scn.team(0)
    loser = scn.team(1)
    assert_points(winner["total_points"], 4.0, "winner total_points")
    assert_points(loser["total_points"], 0.0, "forfeiter total_points")
    assert_fields(winner, total_scratch_pins=0, team_handicap_per_game=58)
    assert_fields(loser, total_scratch_pins=0, team_handicap_per_game=99)
    assert_fields(winner, status=TeamStatus.CONFIRMED.value)
    assert_fields(loser, status=TeamStatus.CONFIRMED.value)

    # The away side's first bowler entered at 170 over 30 prior games, so the
    # BLENDED provisional average is still exactly 170 and the handicap is
    # floor((220 - 170) * 0.90) == 45 — both untouched by the forfeit.
    forfeiting_bowler = scn.membership(2)
    assert_fields(
        forfeiting_bowler,
        certified_games=0,
        certified_pins=0,
        current_average=170,
        average_status=AverageStatus.PROVISIONAL.value,
        handicap_per_game=45,
        sanction_status=SanctionStatus.SANCTIONED.value,
    )

    league = scn.league()
    assert_fields(
        league,
        status=LeagueStatus.IN_SEASON.value,
        certified_week_high_water=1,
    )


# ─── Closing the season needs every match settled (PRD §3.1) ─────────────

def test_close_season_refused_while_week_two_is_still_scheduled(api: ApiClient):
    """The season may not close while one match is still merely `SCHEDULED`,
    even though week one is fully certified.

    The refusal changes nothing: the league stays `IN_SEASON` and its
    high-water mark stays at the one week that really is settled.

    Design: Corner/state_machines/corner_close_season_refused_while_one_match_is_unsettled
    """
    scn = fx.build_certified_match(api)
    assert_fields(scn.match(0), status=MatchStatus.CERTIFIED.value)
    assert_fields(scn.match(1), status=MatchStatus.SCHEDULED.value)

    validate_error(
        api.close_season(scn.league_id, {}, scn.secretary),
        ApiErrorId.ERR_LEAGUE_STATE_INVALID.value,
    )

    assert_fields(
        scn.league(),
        status=LeagueStatus.IN_SEASON.value,
        certified_week_high_water=1,
    )


def test_forfeiting_the_unplayed_week_lets_the_season_close(api: ApiClient):
    """Forfeiting a match that never had a lineup settles it, and the second
    close then succeeds.

    From `SCHEDULED` the forfeiting side has no slots to replace, so `FORFEIT`
    rows are created for positions 1 through `lineup_positions`; the side that
    is awarded the win has no slot invented for it at all.  With week two
    settled the league closes and its high-water mark reaches 2, the winning
    side's points total the week-one sweep plus the week-two forfeit award, and
    the forfeited week contributes no pins to either side.

    Design: Corner/state_machines/corner_close_season_refused_while_one_match_is_unsettled
    """
    scn = fx.build_certified_match(api)
    validate_error(
        api.close_season(scn.league_id, {}, scn.secretary),
        ApiErrorId.ERR_LEAGUE_STATE_INVALID.value,
    )

    week_two = scn.match(1)
    assert_fields(
        week_two, home_team_id=scn.team_ids[1], away_team_id=scn.team_ids[0]
    )
    forfeited = validate_success(
        api.forfeit_match(
            scn.match_ids[1], f.forfeit_payload(scn.team_ids[1]), scn.secretary
        )
    )
    assert_fields(forfeited, status=MatchStatus.FORFEITED.value)
    assert_points(forfeited["home_points"], 0.0, "home_points")
    assert_points(forfeited["away_points"], 4.0, "away_points")

    created_rows = scn.series_entries(1, team_index=1)
    assert len(created_rows) == 2, (
        f"the forfeiting side must gain lineup_positions FORFEIT rows, "
        f"got {len(created_rows)}"
    )
    assert sorted(row["position"] for row in created_rows) == [1, 2]
    for row in created_rows:
        assert_fields(
            row, entry_type=EntryType.FORFEIT.value, membership_id=None
        )
    assert scn.series_entries(1, team_index=0) == [], (
        "the side awarded the forfeit must gain no slot of its own"
    )

    closed = validate_success(api.close_season(scn.league_id, {}, scn.secretary))
    assert_fields(
        closed,
        status=LeagueStatus.SEASON_CLOSED.value,
        certified_week_high_water=2,
    )

    winner = scn.team(0)
    loser = scn.team(1)
    assert_points(winner["total_points"], 8.0, "winner total_points")
    assert_points(loser["total_points"], 0.0, "forfeiter total_points")
    assert_fields(winner, total_scratch_pins=1260)
    assert_fields(loser, total_scratch_pins=930)


def test_certifying_again_is_refused_once_the_season_is_closed(api: ApiClient):
    """A closed season cannot be certified back into motion.

    Certification requires the league to be `IN_SEASON`, and the league-status
    check is consulted before the match-status check, so a certify aimed at the
    already-certified week one of a `SEASON_CLOSED` league is refused on the
    league's status.

    Design: Corner/state_machines/corner_close_season_refused_while_one_match_is_unsettled
    """
    scn = fx.build_certified_match(api)
    validate_success(
        api.forfeit_match(
            scn.match_ids[1], f.forfeit_payload(scn.team_ids[1]), scn.secretary
        )
    )
    validate_success(api.close_season(scn.league_id, {}, scn.secretary))

    validate_error(
        api.certify_match(scn.match_ids[0], {}, scn.secretary),
        ApiErrorId.ERR_LEAGUE_STATE_INVALID.value,
    )

    assert_fields(scn.match(0), status=MatchStatus.CERTIFIED.value)
    assert_fields(scn.league(), status=LeagueStatus.SEASON_CLOSED.value)


# ─── Redrafting a plan, then locking it by approval (PRD §3.7) ────────────

def test_projected_plan_drafts_mid_season_but_cannot_be_approved_yet(
    api: ApiClient,
):
    """A projected plan is legal mid-season; approving it is not.

    With week one certified and one week still to bowl the projection adds a
    whole week of dues that nobody has paid: 2800 settled plus 1 remaining week
    times 4 sanctioned members times the 700-cent weekly prize share.  Approval
    then requires the league to be `SEASON_CLOSED`, and the league-status check
    is consulted before the fund's own status check that this `PLAN_DRAFTED`
    fund would have passed, so the refusal names the league.  Nothing is
    materialised: no award row exists and the fund has no approver.

    Design: Corner/state_machines/corner_prize_plan_redraft_supersedes_then_approval_locks_the_fund
    """
    scn = _certified_week_one_with_dues(api)
    fund = scn.prize_fund()

    drafted = validate_success(
        api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                fund["version"], BasisVariant.PROJECTED_SEASON_END, 2
            ),
            scn.treasurer,
        )
    )
    assert_fields(
        drafted,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
        basis_variant=BasisVariant.PROJECTED_SEASON_END.value,
        place_count=2,
    )
    assert_instant_equals(
        drafted["plan_drafted_at"], WEEK1_STARTS_AT, "plan_drafted_at"
    )
    assert_cents(drafted["plan_basis_cents"], 5600, "plan_basis_cents")
    assert_cents(drafted["reserve_cents"], 280, "reserve_cents")
    assert_cents(drafted["admin_fee_cents"], 160, "admin_fee_cents")
    assert_cents(
        drafted["net_distributable_cents"], 5160, "net_distributable_cents"
    )

    validate_error(
        api.approve_plan(fund["id"], {}, scn.secretary),
        ApiErrorId.ERR_LEAGUE_STATE_INVALID.value,
    )

    rows, meta = validate_paginated(
        api.list_prize_awards(
            scn.treasurer, params={"prize_fund_id": fund["id"], "limit": 100}
        )
    )
    assert rows == [], f"a refused approval must create no award: {rows}"
    assert meta["total_count"] == 0
    after = validate_success(api.get_prize_fund(fund["id"], scn.treasurer))
    assert_fields(
        after,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
        plan_approved_by_user_id=None,
    )


def test_redraft_supersedes_the_projection_with_the_settled_basis(
    api: ApiClient,
):
    """A second draft overwrites every figure of the first one.

    Once week two is forfeited and the season closed, the certified variant
    reads only settled money.  No week-two dues were ever paid, so raising the
    high-water mark to 2 adds nothing while dropping the projection removes
    2800: the basis falls from 5600 to 2800, and the waterfall is rerun from
    that new basis.  Drafting moves no money, so the collected and
    undistributed balances stay where the dues left them.

    Design: Corner/state_machines/corner_prize_plan_redraft_supersedes_then_approval_locks_the_fund
    """
    scn = _certified_week_one_with_dues(api)
    fund = scn.prize_fund()
    projected = validate_success(
        api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                fund["version"], BasisVariant.PROJECTED_SEASON_END, 2
            ),
            scn.treasurer,
        )
    )
    validate_success(
        api.forfeit_match(
            scn.match_ids[1], f.forfeit_payload(scn.team_ids[1]), scn.secretary
        )
    )
    validate_success(api.close_season(scn.league_id, {}, scn.secretary))

    redrafted = validate_success(
        api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                projected["version"], BasisVariant.CERTIFIED_TO_DATE, 2
            ),
            scn.treasurer,
        )
    )
    assert_fields(
        redrafted,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
        basis_variant=BasisVariant.CERTIFIED_TO_DATE.value,
        place_count=2,
    )
    assert_cents(redrafted["plan_basis_cents"], 2800, "plan_basis_cents")
    assert_cents(redrafted["reserve_cents"], 140, "reserve_cents")
    assert_cents(redrafted["admin_fee_cents"], 80, "admin_fee_cents")
    assert_cents(
        redrafted["net_distributable_cents"], 2580, "net_distributable_cents"
    )
    assert redrafted["version"] > projected["version"], (
        f"a redraft must increment the fund version past "
        f"{projected['version']}, got {redrafted['version']}"
    )
    assert_cents(
        redrafted["collected_prize_cents"], 2800, "collected_prize_cents"
    )
    assert_cents(
        redrafted["undistributed_balance_cents"],
        2800,
        "undistributed_balance_cents",
    )


def test_approval_materialises_the_awards_and_locks_out_a_further_draft(
    api: ApiClient,
):
    """Approval is the point of no return for drafting.

    The secretary's approval records them as the approver, materialises one
    `PENDING` award per paying place from the settled net of 2580 cents, and
    ranks the places by standings: the side that swept week one and was awarded
    week two takes place 1.  The two floored amounts total the net exactly, so
    no remainder cent is handed to place 1.  A further draft is then refused on
    the fund's own status — the version echoed was current, so the concurrency
    check does not fire, and the closed league passes its status check — and the
    refusal leaves every plan figure and both award rows exactly as they were.

    Design: Corner/state_machines/corner_prize_plan_redraft_supersedes_then_approval_locks_the_fund
    """
    scn = _certified_week_one_with_dues(api)
    fund = scn.prize_fund()
    projected = validate_success(
        api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                fund["version"], BasisVariant.PROJECTED_SEASON_END, 2
            ),
            scn.treasurer,
        )
    )
    validate_success(
        api.forfeit_match(
            scn.match_ids[1], f.forfeit_payload(scn.team_ids[1]), scn.secretary
        )
    )
    validate_success(api.close_season(scn.league_id, {}, scn.secretary))
    redrafted = validate_success(
        api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                projected["version"], BasisVariant.CERTIFIED_TO_DATE, 2
            ),
            scn.treasurer,
        )
    )
    assert_cents(redrafted["plan_basis_cents"], 2800, "plan_basis_cents")

    approved = validate_success(api.approve_plan(fund["id"], {}, scn.secretary))
    assert_fields(
        approved,
        status=PrizeFundStatus.PLAN_APPROVED.value,
        plan_approved_by_user_id=scn.secretary_member_id,
    )

    awards, meta = validate_paginated(
        api.list_prize_awards(
            scn.treasurer, params={"prize_fund_id": fund["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2, (
        f"approval must create exactly place_count awards, got {meta['total_count']}"
    )
    assert [row["place"] for row in awards] == [1, 2], (
        f"awards must list in ascending place order: {[r['place'] for r in awards]}"
    )
    first, second = awards
    assert_fields(
        first,
        team_id=scn.team_ids[0],
        status=PrizeAwardStatus.PENDING.value,
    )
    assert_cents(first["amount_cents"], 1548, "place 1 amount_cents")
    assert abs(float(first["weight"]) - 0.60) < 1e-9, (
        f"place 1 weight should be 0.60, got {first['weight']!r}"
    )
    assert_fields(
        second,
        team_id=scn.team_ids[1],
        status=PrizeAwardStatus.PENDING.value,
    )
    assert_cents(second["amount_cents"], 1032, "place 2 amount_cents")
    assert abs(float(second["weight"]) - 0.40) < 1e-9, (
        f"place 2 weight should be 0.40, got {second['weight']!r}"
    )
    assert first["amount_cents"] + second["amount_cents"] == 2580, (
        "the awards must total net_distributable_cents exactly"
    )

    validate_error(
        api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                approved["version"], BasisVariant.PROJECTED_SEASON_END, 2
            ),
            scn.treasurer,
        ),
        ApiErrorId.ERR_PRIZE_FUND_STATE_INVALID.value,
    )

    after = validate_success(api.get_prize_fund(fund["id"], scn.treasurer))
    assert_fields(
        after,
        status=PrizeFundStatus.PLAN_APPROVED.value,
        basis_variant=BasisVariant.CERTIFIED_TO_DATE.value,
        plan_basis_cents=2800,
        net_distributable_cents=2580,
    )
    untouched, _ = validate_paginated(
        api.list_prize_awards(
            scn.treasurer, params={"prize_fund_id": fund["id"], "limit": 100}
        )
    )
    assert untouched == awards, (
        "a refused draft must leave the materialised awards untouched"
    )


# ─── A mid-season amendment fans out conditionally (PRD §3.1, §3.6) ───────

def test_midseason_amendment_recomputes_only_sanctioned_handicaps(
    api: ApiClient,
):
    """Raising `handicap_base` mid-season re-derives every membership from the
    pins that are already certified, but the sanction gate still holds one
    bowler at zero.

    The amendment is a self-loop on `IN_SEASON`, not an error.  The four
    sanctioned bowlers move to the new base: 45 from an average of 180, 27 from
    199 (the floor of 27.9, never a round to 28), 54 from 169 (the floor of
    54.9) and 60 from 159, where the floored 63 is clipped by the ceiling.  The
    fifth membership was never listed on a remittance, so its average is
    recomputed to 175 while its handicap stays 0 — the gate fires before the
    basis is ever consulted.  No certified pin is added or removed by any of it.

    Design: Corner/state_machines/corner_midseason_bylaw_amendment_recomputes_only_sanctioned_handicaps
    """
    scn = _certified_week_one_with_an_unsanctioned_bowler(api)
    version_before = scn.league_version()

    amended = validate_success(
        api.adopt_bylaws(
            scn.league_id,
            f.bylaws_payload(version_before, handicap_base=230),
            scn.secretary,
        )
    )
    assert_fields(
        amended,
        status=LeagueStatus.IN_SEASON.value,
        handicap_base=230,
        version=version_before + 1,
    )
    assert_instant_equals(
        amended["bylaws_adopted_at"], WEEK1_STARTS_AT, "bylaws_adopted_at"
    )

    expected = [
        (0, 180, 45, 3, 540),
        (1, 199, 27, 3, 720),
        (2, 169, 54, 3, 480),
        (3, 159, 60, 3, 450),
    ]
    for index, average, handicap, games, pins in expected:
        assert_fields(
            scn.membership(index),
            current_average=average,
            average_status=AverageStatus.PROVISIONAL.value,
            handicap_per_game=handicap,
            certified_games=games,
            certified_pins=pins,
            sanction_status=SanctionStatus.SANCTIONED.value,
        )

    assert_fields(
        scn.membership(4),
        sanction_status=SanctionStatus.UNSANCTIONED.value,
        entering_average=175,
        current_average=175,
        average_status=AverageStatus.PROVISIONAL.value,
        handicap_per_game=0,
        certified_games=0,
        certified_pins=0,
    )

    rows, meta = validate_paginated(
        api.list_memberships(
            scn.secretary, params={"league_id": scn.league_id, "limit": 10}
        )
    )
    assert_fields(meta, total_count=5, has_more=False, limit=10, offset=0)
    assert len(rows) == 5


def test_amendment_moves_roster_handicaps_but_not_the_frozen_match_ones(
    api: ApiClient,
):
    """The same amendment moves both teams' roster handicaps while the handicaps
    frozen onto the already-certified match stay exactly where lineup submission
    left them.

    The roster flavour keeps the top `lineup_positions` of the *sanctioned*
    roster, so the team carrying the unsanctioned fifth bowler is 45 plus 27 —
    that bowler is skipped entirely rather than contributing a zero.  The other
    team is 60 plus 54.  The certified week is not re-scored: its per-side
    handicaps and its points are untouched.

    Design: Corner/state_machines/corner_midseason_bylaw_amendment_recomputes_only_sanctioned_handicaps
    """
    scn = _certified_week_one_with_an_unsanctioned_bowler(api)
    before = scn.match(0)
    assert_fields(
        before, home_team_handicap_per_game=58, away_team_handicap_per_game=99
    )

    validate_success(
        api.adopt_bylaws(
            scn.league_id,
            f.bylaws_payload(scn.league_version(), handicap_base=230),
            scn.secretary,
        )
    )

    assert_fields(
        scn.team(0),
        team_handicap_per_game=72,
        status=TeamStatus.CONFIRMED.value,
    )
    assert_fields(
        scn.team(1),
        team_handicap_per_game=114,
        status=TeamStatus.CONFIRMED.value,
    )

    after = validate_success(api.get_match(scn.match_ids[0], scn.secretary))
    assert_fields(
        after,
        status=MatchStatus.CERTIFIED.value,
        home_team_handicap_per_game=58,
        away_team_handicap_per_game=99,
    )
    assert_points(after["home_points"], 4.0, "home_points")
    assert_points(after["away_points"], 0.0, "away_points")
