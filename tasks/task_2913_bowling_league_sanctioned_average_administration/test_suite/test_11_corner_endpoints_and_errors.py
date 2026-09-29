"""Endpoint-surface and error-envelope corners.

Four themes live here.  The listing surface of PRD §2.3 and §4 — the default
window, the filters that conjoin before the page is cut, and the array envelope
that single reads must not carry.  The three entities that have no creation
endpoint at all, reachable only through their reverse-lookup filters.  The two
action endpoints of §2.7 whose companion field is required on one branch and
forbidden on the other.  The bulk-replace semantics of lineup submission in
§3.4.  And the refusal order of §2.6 walked one gate at a time over a single
endpoint, with the uniform error envelope of §2.2 asserted on every refusal.
"""
from typing import Any, Dict, List

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
    assert_envelope,
    assert_fields,
    assert_instant_equals,
    assert_pagination_meta,
    assert_points,
)
from test_helpers.constants import (
    BASE_BYLAWS,
    DEFAULT_LIMIT,
    LANE_CERTIFIED_THROUGH,
    LOCAL_ASSOCIATION_FEE_CENTS,
    MAX_LIMIT,
    NATIONAL_FEE_ADULT_CENTS,
    ORG_MEETING_INSTANT,
    WEEK1_STARTS_AT,
)
from test_helpers.test_users import (
    headers_empty_user_id,
    make_team_captain_headers,
)
from test_helpers.types import (
    BasisVariant,
    FeeRemittanceStatus,
    LanePairCertificationStatus,
    LeagueStatus,
    MatchStatus,
    MemberClass,
    MembershipRemittanceStatus,
    PrizeFundStatus,
    SanctionStatus,
    TeamStatus,
    UserRole,
)

# Two identifiers that name nothing in this system.  They are kept distinct so a
# refusal naming one of them cannot be confused with a refusal naming the other.
_UNKNOWN_ACTOR_ID = "99999999-9999-4999-8999-999999999999"
_UNKNOWN_ENTITY_ID = "11111111-1111-4111-8111-111111111111"

# The shared bylaw values this module reasons about (PRD §3.1).
_HANDICAP_BASE = BASE_BYLAWS["handicap_base"]
_HANDICAP_PCT = BASE_BYLAWS["handicap_percentage"]
_MAX_HANDICAP = BASE_BYLAWS["max_handicap_per_game"]

# A fifth bowler carried on the first team, deliberately left out of the
# remittance so the league holds one UNSANCTIONED membership on a team whose
# other members are sanctioned.
_FIFTH_BOWLER = fx.RosterSpec("Gus Sub", MemberClass.ADULT, 175, 30, 0)
_FIVE_BOWLER_ROSTER = fx.DEFAULT_ROSTER + (_FIFTH_BOWLER,)


def _entering_handicap(prior_season_average: int) -> int:
    """The per-game handicap a bowler carries from a prior-season average alone.

    With no certified games the BLENDED provisional average is the entering
    average itself, so the CURRENT basis reads that same integer (PRD §3.6).
    """
    difference = max(_HANDICAP_BASE - prior_season_average, 0)
    return min(int(difference * _HANDICAP_PCT), _MAX_HANDICAP)


def _blended_handicap(prior_season_average: int, certified_pins: int) -> int:
    """The per-game handicap a bowler carries after one certified three-game set.

    The shared roster brings thirty prior games, so the blended provisional
    average is the integer quotient of the weighted pins by thirty-three games,
    and the CURRENT basis feeds that average to the handicap rule (PRD §3.6).
    """
    prior_games = fx.DEFAULT_ROSTER[0].prior_season_games
    certified_games = 3
    blended = (prior_season_average * prior_games + certified_pins) // (
        prior_games + certified_games
    )
    difference = max(_HANDICAP_BASE - blended, 0)
    return min(int(difference * _HANDICAP_PCT), _MAX_HANDICAP)


def _league_in_season_with_one_unsanctioned_membership(api: ApiClient) -> fx.Scenario:
    """Five memberships, four of them sanctioned, with the league IN_SEASON.

    The fifth membership sits on the first team and is never listed on the
    remittance, so a team filter and a sanction-status filter disagree about it —
    which is what makes the conjunction of the two observable.
    """
    scn = fx.build_league(api, roster=_FIVE_BOWLER_ROSTER)
    fx.sanction(scn, scn.membership_ids[:4])
    fx.submit_both_lineups(scn, 0)
    fx.set_clock(api, WEEK1_STARTS_AT)
    fx.open_match(scn, 0)
    return scn


def _ids(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


# ─── The listing window and its filters (PRD §2.3, §4) ──

def test_unpaged_listing_reports_the_declared_default_window(api: ApiClient):
    """A list read with neither parameter supplied applies limit 10 and offset 0,
    reports total_count as the number of rows matching the filters and reports
    has_more false because no row remains beyond the window.

    Design: Corner/endpoints/corner_pagination_envelope_and_filter_conjunctions_on_one_collection
    """
    scn = _league_in_season_with_one_unsanctioned_membership(api)

    rows, meta = validate_paginated(
        api.list_memberships(scn.secretary, params={"league_id": scn.league_id})
    )

    assert len(rows) == 5, f"the league holds five memberships, got {rows}"
    assert_pagination_meta(
        meta, limit=DEFAULT_LIMIT, offset=0, total_count=5, has_more=False
    )


def test_listing_windows_tile_the_matching_set_without_repeat_or_omission(api: ApiClient):
    """Successive windows over one filtered set report the same total_count, flip
    has_more only on the last window, and between them return each matching row
    exactly once.

    Design: Corner/endpoints/corner_pagination_envelope_and_filter_conjunctions_on_one_collection
    """
    scn = _league_in_season_with_one_unsanctioned_membership(api)
    params = {"league_id": scn.league_id}

    all_rows, _ = validate_paginated(api.list_memberships(scn.secretary, params=params))

    first, first_meta = validate_paginated(
        api.list_memberships(scn.secretary, params={**params, "limit": 2})
    )
    assert_pagination_meta(first_meta, limit=2, offset=0, total_count=5, has_more=True)
    assert len(first) == 2

    middle, middle_meta = validate_paginated(
        api.list_memberships(scn.secretary, params={**params, "limit": 2, "offset": 2})
    )
    assert_pagination_meta(middle_meta, limit=2, offset=2, total_count=5, has_more=True)

    last, last_meta = validate_paginated(
        api.list_memberships(scn.secretary, params={**params, "limit": 2, "offset": 4})
    )
    assert_pagination_meta(last_meta, limit=2, offset=4, total_count=5, has_more=False)
    assert len(last) == 1, f"one row remains in the trailing window, got {last}"

    tiled = _ids(first) + _ids(middle) + _ids(last)
    assert tiled == _ids(all_rows), (
        f"the three windows should reproduce the unpaged order exactly once each: "
        f"{tiled} vs {_ids(all_rows)}"
    )


def test_window_past_the_end_and_unmatched_filter_value_are_empty_successes(api: ApiClient):
    """An offset beyond the matching set answers 200 with an empty array and the
    unchanged total_count, and a filter value that matches nothing answers 200
    with an empty array and a total_count of 0 — neither is an error.

    Design: Corner/endpoints/corner_pagination_envelope_and_filter_conjunctions_on_one_collection
    """
    scn = _league_in_season_with_one_unsanctioned_membership(api)

    past_end = api.list_memberships(
        scn.secretary,
        params={"league_id": scn.league_id, "limit": 2, "offset": 5},
    )
    rows, meta = validate_paginated(past_end)
    assert rows == [], f"a window past the end returns no rows, got {rows}"
    assert_pagination_meta(meta, limit=2, offset=5, total_count=5, has_more=False)

    unmatched = api.list_memberships(
        scn.secretary,
        params={
            "league_id": scn.league_id,
            "remittance_status": MembershipRemittanceStatus.REFUNDED.value,
        },
    )
    empty_rows, empty_meta = validate_paginated(unmatched)
    assert empty_rows == [], f"no membership was ever refunded, got {empty_rows}"
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False


def test_filters_are_applied_before_the_window_is_cut(api: ApiClient):
    """total_count counts the rows matching the filters before the window, so a
    filter that removes one of five rows leaves a total_count of 4 even though
    the window itself returns only 2 rows and reports more remaining.

    Design: Corner/endpoints/corner_pagination_envelope_and_filter_conjunctions_on_one_collection
    """
    scn = _league_in_season_with_one_unsanctioned_membership(api)

    rows, meta = validate_paginated(
        api.list_memberships(
            scn.secretary,
            params={
                "league_id": scn.league_id,
                "sanction_status": SanctionStatus.SANCTIONED.value,
                "limit": 2,
            },
        )
    )

    assert len(rows) == 2, f"the window admits two rows, got {rows}"
    assert_pagination_meta(meta, limit=2, offset=0, total_count=4, has_more=True)
    assert all(
        row["sanction_status"] == SanctionStatus.SANCTIONED.value for row in rows
    )


def test_two_filters_on_one_collection_conjoin_rather_than_union(api: ApiClient):
    """Every supplied filter must hold at once: the unsanctioned membership sits
    on the filtered team and is still excluded, so the team-plus-status read
    returns exactly the two sanctioned memberships of that team.

    Design: Corner/endpoints/corner_pagination_envelope_and_filter_conjunctions_on_one_collection
    """
    scn = _league_in_season_with_one_unsanctioned_membership(api)
    unsanctioned_id = scn.membership_ids[4]

    on_team, on_team_meta = validate_paginated(
        api.list_memberships(
            scn.secretary,
            params={"league_id": scn.league_id, "team_id": scn.team_ids[0]},
        )
    )
    assert on_team_meta["total_count"] == 3
    assert unsanctioned_id in _ids(on_team), (
        "the unsanctioned membership is on the filtered team when the team filter "
        "stands alone"
    )

    both, both_meta = validate_paginated(
        api.list_memberships(
            scn.secretary,
            params={
                "league_id": scn.league_id,
                "team_id": scn.team_ids[0],
                "sanction_status": SanctionStatus.SANCTIONED.value,
            },
        )
    )
    assert _ids(both) == scn.membership_ids[:2], (
        f"the conjunction admits only the two sanctioned rows of that team, "
        f"got {_ids(both)}"
    )
    assert both_meta["total_count"] == 2
    assert unsanctioned_id not in _ids(both)


def test_pagination_parameters_outside_their_declared_range_are_refused(api: ApiClient):
    """limit may not exceed 100 nor fall below 1, and offset may not be negative;
    each violation is a malformed request rather than a clamped window.

    Design: Corner/endpoints/corner_pagination_envelope_and_filter_conjunctions_on_one_collection
    """
    scn = _league_in_season_with_one_unsanctioned_membership(api)
    params = {"league_id": scn.league_id}

    validate_error(
        api.list_memberships(scn.secretary, params={**params, "limit": MAX_LIMIT + 1}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api.list_memberships(scn.secretary, params={**params, "limit": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api.list_memberships(scn.secretary, params={**params, "offset": -1}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, meta = validate_paginated(
        api.list_memberships(scn.secretary, params={**params, "limit": MAX_LIMIT})
    )
    assert meta["limit"] == MAX_LIMIT, "the declared maximum itself is accepted"


def test_league_listing_conjoins_its_own_declared_filters(api: ApiClient):
    """The league listing filters on season_year and status together, so the one
    league on the server is returned by the pair that describes it and by neither
    a wrong season nor a wrong status.

    Design: Corner/endpoints/corner_pagination_envelope_and_filter_conjunctions_on_one_collection
    """
    scn = _league_in_season_with_one_unsanctioned_membership(api)

    rows, meta = validate_paginated(
        api.list_leagues(
            scn.officer,
            params={"season_year": 2026, "status": LeagueStatus.IN_SEASON.value},
        )
    )
    assert _ids(rows) == [scn.league_id], f"expected the one IN_SEASON league, got {rows}"
    assert meta["total_count"] == 1

    wrong_season, wrong_season_meta = validate_paginated(
        api.list_leagues(scn.officer, params={"season_year": 2025})
    )
    assert wrong_season == []
    assert wrong_season_meta["total_count"] == 0

    wrong_status, wrong_status_meta = validate_paginated(
        api.list_leagues(
            scn.officer,
            params={"season_year": 2026, "status": LeagueStatus.SEASON_CLOSED.value},
        )
    )
    assert wrong_status == []
    assert wrong_status_meta["total_count"] == 0


def test_array_envelope_carries_the_window_fields_and_object_envelope_omits_them(
    api: ApiClient,
):
    """A list response is an array envelope carrying all four window fields; the
    single-resource read of one of those very rows is an object envelope that
    carries none of them.

    Design: Corner/endpoints/corner_pagination_envelope_and_filter_conjunctions_on_one_collection
    """
    scn = _league_in_season_with_one_unsanctioned_membership(api)

    listing = api.list_memberships(scn.secretary, params={"league_id": scn.league_id})
    validate_success(listing, 200)
    list_body = listing.json()
    assert_envelope(list_body, "array")
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in list_body["meta"], (
            f"a list response must carry meta.{field}: {list_body['meta']}"
        )

    single = api.get_membership(scn.membership_ids[0], scn.secretary)
    validate_success(single, 200)
    single_body = single.json()
    assert_envelope(single_body, "object")
    present = [
        field
        for field in ("limit", "offset", "total_count", "has_more")
        if field in single_body["meta"]
    ]
    assert not present, (
        f"a single-resource response omits every pagination field, found {present}"
    )


# ─── Cascade-created children and their reverse-lookup filters (PRD §4) ───

def _assert_grouped_by_team_then_position(rows: List[Dict[str, Any]]) -> None:
    """The slot listing is ordered by owning team and then by position ascending,
    so each team's rows are contiguous and ascend within their block."""
    seen: List[str] = []
    for team_id, group in _grouped(rows):
        assert team_id not in seen, (
            f"team {team_id} appears in two separate blocks, so the rows are not "
            f"grouped by owning team: {[row['team_id'] for row in rows]}"
        )
        seen.append(team_id)
        positions = [row["position"] for row in group]
        assert positions == sorted(positions), (
            f"positions within team {team_id} must ascend, got {positions}"
        )


def _grouped(rows: List[Dict[str, Any]]):
    """Walk the rows, yielding each run of consecutive rows sharing a team."""
    current_team = None
    block: List[Dict[str, Any]] = []
    for row in rows:
        if row["team_id"] != current_team:
            if block:
                yield current_team, block
            current_team = row["team_id"]
            block = []
        block.append(row)
    if block:
        yield current_team, block


def test_series_entry_listing_is_the_only_channel_to_the_slots_of_a_match(
    certified_match: fx.Scenario,
):
    """Lineup slots have no creation endpoint and no listing of their own beyond
    the match filter, which returns exactly the four slots two lineups created,
    grouped by owning team and ascending by position, every one of them certified
    and average-bearing after the match was certified.

    Design: Corner/endpoints/corner_cascade_created_children_are_only_reachable_through_query_filters
    """
    scn = certified_match

    rows, meta = validate_paginated(
        scn.api.list_series_entries(
            scn.secretary, params={"match_id": scn.match_ids[0], "limit": 100}
        )
    )

    assert len(rows) == 4, f"two lineups of two positions each produce four slots: {rows}"
    assert meta["total_count"] == 4
    _assert_grouped_by_team_then_position(rows)
    assert all(row["certified"] is True for row in rows), (
        f"certification sets the flag on every slot of the match: {rows}"
    )
    assert all(row["counts_toward_average"] is True for row in rows), (
        f"every slot here is a REGULAR slot naming a membership: {rows}"
    )

    uncertified, uncertified_meta = validate_paginated(
        scn.api.list_series_entries(
            scn.secretary, params={"match_id": scn.match_ids[0], "certified": False}
        )
    )
    assert uncertified == [], (
        f"no slot of a certified match remains uncertified, got {uncertified}"
    )
    assert uncertified_meta["total_count"] == 0


def test_series_entry_filters_narrow_to_one_side_and_to_one_bowler(
    certified_match: fx.Scenario,
):
    """Adding the team filter returns just that side's two slots with the
    handicaps frozen onto them at submission, the membership filter returns the
    single slot that bowler occupied with its recorded games and pins, and a
    match that never received a lineup has no slots at all.

    Design: Corner/endpoints/corner_cascade_created_children_are_only_reachable_through_query_filters
    """
    scn = certified_match
    away_team_id = scn.match(0)["away_team_id"]

    away_rows, away_meta = validate_paginated(
        scn.api.list_series_entries(
            scn.secretary,
            params={"match_id": scn.match_ids[0], "team_id": away_team_id},
        )
    )
    assert away_meta["total_count"] == 2
    assert [row["position"] for row in away_rows] == [1, 2]
    assert [row["membership_id"] for row in away_rows] == scn.membership_ids[2:4]
    assert [row["handicap_per_game_applied"] for row in away_rows] == [
        _entering_handicap(170),
        _entering_handicap(160),
    ]

    one_bowler, one_bowler_meta = validate_paginated(
        scn.api.list_series_entries(
            scn.secretary, params={"membership_id": scn.membership_ids[1]}
        )
    )
    assert one_bowler_meta["total_count"] == 1, (
        f"that bowler occupied exactly one slot, got {one_bowler}"
    )
    assert_fields(
        one_bowler[0],
        match_id=scn.match_ids[0],
        games_recorded=3,
        scratch_series=230 + 240 + 250,
    )

    empty_rows, empty_meta = validate_paginated(
        scn.api.list_series_entries(
            scn.secretary, params={"match_id": scn.match_ids[1]}
        )
    )
    assert empty_rows == [], (
        f"the second week received no lineup, so it owns no slots: {empty_rows}"
    )
    assert empty_meta["total_count"] == 0


def test_prize_fund_created_at_chartering_is_found_only_through_its_listing(
    certified_match: fx.Scenario,
):
    """Chartering creates one prize fund that no response body ever returned, so
    the league-filtered listing is the only channel to it; it stands accumulating
    with a zeroed money triple, no places and the projected basis, and its award
    listing is empty because approval has not run.

    Design: Corner/endpoints/corner_cascade_created_children_are_only_reachable_through_query_filters
    """
    scn = certified_match

    funds, funds_meta = validate_paginated(
        scn.api.list_prize_funds(scn.treasurer, params={"league_id": scn.league_id})
    )
    assert funds_meta["total_count"] == 1, f"exactly one fund per league, got {funds}"
    fund = funds[0]
    assert_fields(
        fund,
        league_id=scn.league_id,
        status=PrizeFundStatus.ACCUMULATING.value,
        basis_variant=BasisVariant.PROJECTED_SEASON_END.value,
        place_count=0,
        collected_prize_cents=0,
        paid_award_total_cents=0,
        undistributed_balance_cents=0,
    )

    awards, awards_meta = validate_paginated(
        scn.api.list_prize_awards(scn.treasurer, params={"prize_fund_id": fund["id"]})
    )
    assert awards == [], f"awards exist only after plan approval, got {awards}"
    assert awards_meta["total_count"] == 0

    dues, dues_meta = validate_paginated(
        scn.api.list_dues_payments(
            scn.treasurer, params={"membership_id": scn.membership_ids[0]}
        )
    )
    assert dues == [], f"no dues have been recorded, got {dues}"
    assert dues_meta["total_count"] == 0


def test_lane_pair_and_match_listings_narrow_by_their_declared_filters(
    certified_match: fx.Scenario,
):
    """A lane pair is reachable by its league and by its read-time certification
    status, and the match listing narrows by lane pair and then by status, so the
    two scheduled weeks reduce to the single certified one.

    Design: Corner/endpoints/corner_cascade_created_children_are_only_reachable_through_query_filters
    """
    scn = certified_match

    pairs, pairs_meta = validate_paginated(
        scn.api.list_lane_pairs(
            scn.secretary,
            params={
                "league_id": scn.league_id,
                "certification_status": LanePairCertificationStatus.CERTIFIED.value,
            },
        )
    )
    assert pairs_meta["total_count"] == 1, f"one certified pair, got {pairs}"
    assert_fields(pairs[0], id=scn.lane_pair_ids[0], pair_number=1, revoked_at=None)
    assert_instant_equals(
        pairs[0]["certified_through"], LANE_CERTIFIED_THROUGH, "certified_through"
    )

    expired, expired_meta = validate_paginated(
        scn.api.list_lane_pairs(
            scn.secretary,
            params={
                "league_id": scn.league_id,
                "certification_status": LanePairCertificationStatus.EXPIRED.value,
            },
        )
    )
    assert expired == [], f"the pair's certification has not lapsed, got {expired}"
    assert expired_meta["total_count"] == 0

    on_pair, on_pair_meta = validate_paginated(
        scn.api.list_matches(
            scn.secretary,
            params={"league_id": scn.league_id, "lane_pair_id": scn.lane_pair_ids[0]},
        )
    )
    assert on_pair_meta["total_count"] == 2
    assert sorted(row["week_number"] for row in on_pair) == [1, 2]

    certified_rows, certified_meta = validate_paginated(
        scn.api.list_matches(
            scn.secretary,
            params={
                "league_id": scn.league_id,
                "lane_pair_id": scn.lane_pair_ids[0],
                "status": MatchStatus.CERTIFIED.value,
            },
        )
    )
    assert _ids(certified_rows) == [scn.match_ids[0]], (
        f"only week one is certified, got {certified_rows}"
    )
    assert certified_meta["total_count"] == 1


def test_team_sub_listing_and_the_two_officer_binding_filters(
    certified_match: fx.Scenario,
):
    """The league-scoped team listing is ordered by created_at ascending and
    reports both teams confirmed by their sanctioned roster counts, while the
    league listing's secretary and treasurer filters read two separate fields —
    the secretary's id matches on one and on neither the other.

    Design: Corner/endpoints/corner_cascade_created_children_are_only_reachable_through_query_filters
    """
    scn = certified_match

    teams, teams_meta = validate_paginated(
        scn.api.list_league_teams(scn.league_id, scn.secretary)
    )
    assert _ids(teams) == scn.team_ids, (
        f"teams list in creation order, got {_ids(teams)} vs {scn.team_ids}"
    )
    assert teams_meta["total_count"] == 2
    for team in teams:
        assert_fields(
            team,
            status=TeamStatus.CONFIRMED.value,
            sanctioned_roster_count=2,
        )

    by_secretary, by_secretary_meta = validate_paginated(
        scn.api.list_leagues(
            scn.officer, params={"secretary_member_id": scn.secretary_member_id}
        )
    )
    assert _ids(by_secretary) == [scn.league_id]
    assert by_secretary_meta["total_count"] == 1

    crossed, crossed_meta = validate_paginated(
        scn.api.list_leagues(
            scn.officer, params={"treasurer_member_id": scn.secretary_member_id}
        )
    )
    assert crossed == [], (
        f"the secretary is not the treasurer of any league, got {crossed}"
    )
    assert crossed_meta["total_count"] == 0


# ─── Conditional companion fields on two action endpoints (PRD §2.7) ───

# An instant strictly after the shared lane certification lapses, and the
# replacement horizon a recertification supplies once it has.
_AFTER_LANE_EXPIRY_INSTANT = "2027-01-02T00:00:00Z"
_REPLACEMENT_CERTIFIED_THROUGH = "2027-06-30T00:00:00Z"

_ADULT_SANCTION_FEE_CENTS = NATIONAL_FEE_ADULT_CENTS + LOCAL_ASSOCIATION_FEE_CENTS


def test_lane_pair_action_refuses_each_action_carrying_the_other_companion_field(
    league: fx.Scenario,
):
    """A recertification without its replacement horizon, a revocation that
    carries one anyway, and an action word outside the declared pair are all
    refused on request shape, and none of the three touches the pair.

    Design: Corner/endpoints/corner_two_conditional_action_endpoints_reject_the_wrong_companion_field
    """
    scn = league
    lane_pair_id = scn.lane_pair_ids[0]

    recertify_without_horizon = f.recertify_payload(_REPLACEMENT_CERTIFIED_THROUGH)
    del recertify_without_horizon["certified_through"]
    validate_error(
        scn.api.set_lane_pair_certification(
            lane_pair_id, recertify_without_horizon, scn.officer
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    validate_error(
        scn.api.set_lane_pair_certification(
            lane_pair_id,
            f.revoke_payload(certified_through=_REPLACEMENT_CERTIFIED_THROUGH),
            scn.officer,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    validate_error(
        scn.api.set_lane_pair_certification(
            lane_pair_id, f.revoke_payload(action="RENEW"), scn.officer
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    pair = validate_success(scn.api.get_lane_pair(lane_pair_id, scn.secretary))
    assert_fields(
        pair,
        certification_status=LanePairCertificationStatus.CERTIFIED.value,
        revoked_at=None,
    )
    assert_instant_equals(
        pair["certified_through"], LANE_CERTIFIED_THROUGH, "certified_through"
    )
    assert_instant_equals(
        pair["last_certified_at"], ORG_MEETING_INSTANT, "last_certified_at"
    )


def test_national_decision_refuses_each_branch_without_its_own_companion_field(
    league: fx.Scenario,
):
    """An acceptance with no receipt number and a rejection with no reason are
    both refused on request shape, leaving the remittance submitted with both
    fields null and every listed membership still only invoiced; the acceptance
    then succeeds the moment its own companion field is supplied.

    Design: Corner/endpoints/corner_two_conditional_action_endpoints_reject_the_wrong_companion_field
    """
    scn = league
    remittance_id = fx.open_remittance(scn)
    fx.submit_remittance(scn, remittance_id)
    expected_total = len(scn.membership_ids) * _ADULT_SANCTION_FEE_CENTS

    accept_without_receipt = f.national_accept_payload()
    del accept_without_receipt["national_receipt_no"]
    validate_error(
        scn.api.record_national_decision(
            remittance_id, accept_without_receipt, scn.officer
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    reject_without_reason = f.national_reject_payload()
    del reject_without_reason["rejection_reason"]
    validate_error(
        scn.api.record_national_decision(
            remittance_id, reject_without_reason, scn.officer
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    still_submitted = validate_success(
        scn.api.get_fee_remittance(remittance_id, scn.treasurer)
    )
    assert_fields(
        still_submitted,
        status=FeeRemittanceStatus.SUBMITTED.value,
        national_receipt_no=None,
        rejection_reason=None,
        member_count=len(scn.membership_ids),
        penalty_cents=0,
    )
    assert_cents(still_submitted["computed_amount_cents"], expected_total)
    assert_cents(still_submitted["declared_amount_cents"], expected_total)
    for index in range(len(scn.membership_ids)):
        assert_fields(
            scn.membership(index),
            sanction_status=SanctionStatus.PENDING_REMITTANCE.value,
            remittance_status=MembershipRemittanceStatus.INVOICED.value,
            handicap_per_game=0,
        )
    assert scn.league()["status"] == LeagueStatus.BYLAWS_ADOPTED.value

    receipt = "NR-2913-0007"
    accepted = validate_success(
        scn.api.record_national_decision(
            remittance_id, f.national_accept_payload(receipt), scn.officer
        )
    )
    assert_fields(
        accepted,
        status=FeeRemittanceStatus.ACCEPTED.value,
        national_receipt_no=receipt,
        rejection_reason=None,
    )
    assert_fields(
        scn.membership(0),
        sanction_status=SanctionStatus.SANCTIONED.value,
        remittance_status=MembershipRemittanceStatus.REMITTED.value,
        handicap_per_game=_entering_handicap(180),
    )
    assert scn.league()["status"] == LeagueStatus.SANCTIONED.value


def test_recertification_with_its_companion_field_revives_a_lapsed_pair(
    league: fx.Scenario,
):
    """Once the clock has run past the horizon the pair reads expired without any
    request having been addressed to it, and a recertification carrying the
    companion field it requires puts the pair back to certified on the
    replacement horizon with its certification instant reset to now.

    Design: Corner/endpoints/corner_two_conditional_action_endpoints_reject_the_wrong_companion_field
    """
    scn = league
    lane_pair_id = scn.lane_pair_ids[0]

    fx.set_clock(scn.api, _AFTER_LANE_EXPIRY_INSTANT)
    lapsed = validate_success(scn.api.get_lane_pair(lane_pair_id, scn.secretary))
    assert_fields(
        lapsed,
        certification_status=LanePairCertificationStatus.EXPIRED.value,
        revoked_at=None,
    )

    revived = validate_success(
        scn.api.set_lane_pair_certification(
            lane_pair_id,
            f.recertify_payload(_REPLACEMENT_CERTIFIED_THROUGH),
            scn.officer,
        )
    )
    assert_fields(
        revived,
        certification_status=LanePairCertificationStatus.CERTIFIED.value,
        revoked_at=None,
    )
    assert_instant_equals(
        revived["certified_through"],
        _REPLACEMENT_CERTIFIED_THROUGH,
        "certified_through",
    )
    assert_instant_equals(
        revived["last_certified_at"], _AFTER_LANE_EXPIRY_INSTANT, "last_certified_at"
    )


# ─── Lineup submission is a bulk replace of one side only (PRD §3.4) ───

def _slots_of_side(scn: fx.Scenario, match_index: int, team_id: str) -> List[Dict[str, Any]]:
    """One side's slots for one match, read through the only listing that shows
    them, ordered by position within that side."""
    rows = get_success_data(
        scn.api.list_series_entries(
            scn.secretary,
            params={
                "match_id": scn.match_ids[match_index],
                "team_id": team_id,
                "limit": MAX_LIMIT,
            },
        )
    )
    return sorted(rows, key=lambda row: row["position"])


def test_resubmitting_one_side_replaces_its_slots_outright(
    sanctioned_league: fx.Scenario,
):
    """A side that revises its lineup gets brand-new slot rows: the earlier rows
    are gone rather than amended, the two bowlers now sit in the reversed
    positions with each one's own frozen handicap, and the match stays where it
    was while its version moves on by one.

    Design: Corner/endpoints/corner_lineup_supersede_replaces_one_side_and_leaves_the_other_alone
    """
    scn = sanctioned_league
    fx.submit_both_lineups(scn, 0)
    match = scn.match(0)
    home_team_id = match["home_team_id"]
    version_before = match["version"]
    superseded_ids = {row["id"] for row in _slots_of_side(scn, 0, home_team_id)}

    revised = validate_success(
        scn.api.submit_lineup(
            scn.match_ids[0],
            f.lineup_payload(
                version_before,
                home_team_id,
                [
                    f.slot(1, membership_id=scn.membership_ids[1]),
                    f.slot(2, membership_id=scn.membership_ids[0]),
                ],
            ),
            scn.captain(0),
        )
    )
    assert_fields(
        revised,
        status=MatchStatus.LINEUPS_SUBMITTED.value,
        version=version_before + 1,
        home_team_handicap_per_game=_entering_handicap(180) + _entering_handicap(195),
    )

    rows = _slots_of_side(scn, 0, home_team_id)
    assert len(rows) == 2, f"the side still holds exactly two slots, got {rows}"
    assert superseded_ids.isdisjoint({row["id"] for row in rows}), (
        "the earlier slots were amended in place rather than deleted and recreated"
    )
    assert [row["membership_id"] for row in rows] == [
        scn.membership_ids[1],
        scn.membership_ids[0],
    ]
    assert [row["handicap_per_game_applied"] for row in rows] == [
        _entering_handicap(195),
        _entering_handicap(180),
    ]
    for row in rows:
        assert_fields(row, counts_toward_average=True, certified=False)


def test_resubmitting_one_side_leaves_the_opposing_side_untouched(
    sanctioned_league: fx.Scenario,
):
    """The replacement is confined to the submitting side: the opposing side keeps
    the very same slot rows with the very same frozen handicaps, its own frozen
    team handicap does not move, and the match still holds four slots in total.

    Design: Corner/endpoints/corner_lineup_supersede_replaces_one_side_and_leaves_the_other_alone
    """
    scn = sanctioned_league
    fx.submit_both_lineups(scn, 0)
    match = scn.match(0)
    home_team_id = match["home_team_id"]
    away_team_id = match["away_team_id"]
    away_before = _slots_of_side(scn, 0, away_team_id)
    expected_away_handicap = _entering_handicap(170) + _entering_handicap(160)
    assert match["away_team_handicap_per_game"] == expected_away_handicap

    revised = validate_success(
        scn.api.submit_lineup(
            scn.match_ids[0],
            f.lineup_payload(
                match["version"],
                home_team_id,
                [
                    f.slot(1, membership_id=scn.membership_ids[1]),
                    f.slot(2, membership_id=scn.membership_ids[0]),
                ],
            ),
            scn.secretary,
        )
    )
    assert revised["away_team_handicap_per_game"] == expected_away_handicap, (
        "revising one side must not recompute the other side's frozen handicap"
    )

    away_after = _slots_of_side(scn, 0, away_team_id)
    assert _ids(away_after) == _ids(away_before), (
        f"the opposing side's slots were replaced too: "
        f"{_ids(away_before)} became {_ids(away_after)}"
    )
    assert [row["handicap_per_game_applied"] for row in away_after] == [
        _entering_handicap(170),
        _entering_handicap(160),
    ]

    _, meta = validate_paginated(
        scn.api.list_series_entries(
            scn.secretary, params={"match_id": scn.match_ids[0], "limit": MAX_LIMIT}
        )
    )
    assert meta["total_count"] == 4, (
        "a replacement must neither leave the old rows behind nor drop the "
        "opposing side's rows"
    )


def test_repeated_supersession_is_idempotent_in_everything_but_the_version(
    sanctioned_league: fx.Scenario,
):
    """Submitting the same side a third time again replaces its rows and again
    lifts the version by one, while both frozen team handicaps, the slot count,
    the match state and the league state all stand still; the team's own roster
    handicap is a separate figure that no lineup revision touches.

    Design: Corner/endpoints/corner_lineup_supersede_replaces_one_side_and_leaves_the_other_alone
    """
    scn = sanctioned_league
    fx.submit_both_lineups(scn, 0)
    home_team_id = scn.match(0)["home_team_id"]
    expected_home = _entering_handicap(180) + _entering_handicap(195)
    expected_away = _entering_handicap(170) + _entering_handicap(160)

    for attempt in range(2):
        version_before = scn.match_version(0)
        slots = [
            f.slot(1, membership_id=scn.membership_ids[1 - attempt]),
            f.slot(2, membership_id=scn.membership_ids[attempt]),
        ]
        again = validate_success(
            scn.api.submit_lineup(
                scn.match_ids[0],
                f.lineup_payload(version_before, home_team_id, slots),
                scn.secretary,
            )
        )
        assert_fields(
            again,
            status=MatchStatus.LINEUPS_SUBMITTED.value,
            version=version_before + 1,
            home_team_handicap_per_game=expected_home,
            away_team_handicap_per_game=expected_away,
        )
        assert len(_slots_of_side(scn, 0, home_team_id)) == 2

    home_team = validate_success(scn.api.get_team(home_team_id, scn.secretary))
    assert home_team["team_handicap_per_game"] == expected_home
    assert_points(home_team["total_points"], 0.0, "total_points")
    assert scn.league()["status"] == LeagueStatus.SANCTIONED.value


# ─── The refusal chain and the uniform error envelope (PRD §2.2, §2.6) ───

def _week_two_lineup(
    scn: fx.Scenario,
    *,
    team_id: str,
    membership_id: str,
    expected_match_version: int,
) -> Dict[str, Any]:
    """One week-two lineup payload whose team, first-slot membership and version
    echo can each be spoiled independently."""
    return f.lineup_payload(
        expected_match_version,
        team_id,
        [
            f.slot(1, membership_id=membership_id),
            f.slot(2, membership_id=scn.membership_ids[1]),
        ],
    )


def test_authentication_outranks_every_other_defect_on_reads_and_writes(
    certified_match: fx.Scenario,
):
    """A write whose actor header is blank and whose path, body references and
    version echo are all wrong is refused as unauthenticated, and so is a read of
    an identifier that names nothing — the first check in the order decides both.

    Design: Corner/errors/corner_error_envelope_is_uniform_and_the_preamble_gates_run_in_order
    """
    scn = certified_match
    blank_actor = headers_empty_user_id(UserRole.LEAGUE_SECRETARY)

    validate_error(
        scn.api.submit_lineup(
            _UNKNOWN_ENTITY_ID,
            _week_two_lineup(
                scn,
                team_id=_UNKNOWN_ENTITY_ID,
                membership_id=_UNKNOWN_ENTITY_ID,
                expected_match_version=999,
            ),
            blank_actor,
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    validate_error(
        scn.api.get_match(_UNKNOWN_ENTITY_ID, blank_actor),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


def test_the_preamble_gates_of_one_endpoint_fire_strictly_in_order(
    certified_match: fx.Scenario,
):
    """Walking one write endpoint gate by gate: each request repairs exactly the
    defect the previous refusal named and leaves every later defect in place, so
    the sequence of codes is the sequence of checks — role, then unknown actor,
    then the path resource, then the body references in their declared order, and
    only then the version echo.

    Design: Corner/errors/corner_error_envelope_is_uniform_and_the_preamble_gates_run_in_order
    """
    scn = certified_match
    week_two_id = scn.match_ids[1]
    week_two = scn.match(1)
    away_team_id = week_two["away_team_id"]
    stale_version = week_two["version"] + 1

    def payload(*, team_id: str, membership_id: str, version: int) -> Dict[str, Any]:
        return _week_two_lineup(
            scn,
            team_id=team_id,
            membership_id=membership_id,
            expected_match_version=version,
        )

    spoiled = payload(
        team_id=_UNKNOWN_ENTITY_ID,
        membership_id=_UNKNOWN_ENTITY_ID,
        version=stale_version,
    )

    # Gate 2: the role is not one the endpoint authorises at all.
    validate_error(
        scn.api.submit_lineup(_UNKNOWN_ENTITY_ID, spoiled, scn.bowler(0)),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    # Gate 3: an authorised, entity-backed role whose actor is nobody.
    validate_error(
        scn.api.submit_lineup(
            _UNKNOWN_ENTITY_ID, spoiled, make_team_captain_headers(_UNKNOWN_ACTOR_ID)
        ),
        ApiErrorId.ERR_UNKNOWN_ACTOR.value,
    )

    # Gate 4: the path resource, ahead of both body references and the echo.
    validate_error(
        scn.api.submit_lineup(_UNKNOWN_ENTITY_ID, spoiled, scn.secretary),
        ApiErrorId.ERR_MATCH_NOT_FOUND.value,
    )

    # Gate 5, first declared reference: the team, ahead of the slot membership.
    validate_error(
        scn.api.submit_lineup(week_two_id, spoiled, scn.secretary),
        ApiErrorId.ERR_TEAM_NOT_FOUND.value,
    )

    # Gate 5, next declared reference: the membership named on a slot.
    validate_error(
        scn.api.submit_lineup(
            week_two_id,
            payload(
                team_id=away_team_id,
                membership_id=_UNKNOWN_ENTITY_ID,
                version=stale_version,
            ),
            scn.secretary,
        ),
        ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND.value,
    )

    # Gate 13: with every identifier resolvable, the echo finally decides.
    validate_error(
        scn.api.submit_lineup(
            week_two_id,
            payload(
                team_id=away_team_id,
                membership_id=scn.membership_ids[0],
                version=stale_version,
            ),
            scn.secretary,
        ),
        ApiErrorId.ERR_STALE_MATCH_VERSION.value,
    )


def test_the_error_envelope_is_the_same_shape_whatever_the_refusal(
    certified_match: fx.Scenario,
):
    """Three refusals from three different points in the order — an authentication
    failure, a missing path resource and a stale echo — all answer with the same
    envelope: an error response type, a data object holding exactly the error
    identifier and a message, and a meta object holding exactly the request
    identifier and its timestamp, with none of the four window fields.

    Design: Corner/errors/corner_error_envelope_is_uniform_and_the_preamble_gates_run_in_order
    """
    scn = certified_match
    week_two = scn.match(1)

    refusals = [
        (
            scn.api.get_match(
                scn.match_ids[1], headers_empty_user_id(UserRole.LEAGUE_SECRETARY)
            ),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        ),
        (
            scn.api.get_match(_UNKNOWN_ENTITY_ID, scn.secretary),
            ApiErrorId.ERR_MATCH_NOT_FOUND.value,
        ),
        (
            scn.api.submit_lineup(
                scn.match_ids[1],
                _week_two_lineup(
                    scn,
                    team_id=week_two["away_team_id"],
                    membership_id=scn.membership_ids[0],
                    expected_match_version=week_two["version"] + 1,
                ),
                scn.secretary,
            ),
            ApiErrorId.ERR_STALE_MATCH_VERSION.value,
        ),
    ]

    for response, expected_error_id in refusals:
        validate_error(response, expected_error_id)
        body = response.json()
        assert_envelope(body, "error")
        assert set(body["data"]) == {"error_id", "message"}, (
            f"an error payload carries exactly the identifier and the message, "
            f"got {sorted(body['data'])}"
        )
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
            f"an error meta object carries exactly the request identifier and its "
            f"timestamp, got {sorted(body['meta'])}"
        )
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
            "the message must be a non-empty human-readable string"
        )


def test_the_fully_repaired_submission_is_accepted_and_freezes_the_new_handicaps(
    certified_match: fx.Scenario,
):
    """Once every defect the chain named is repaired the same request succeeds: it
    answers with a single-resource envelope carrying no window fields, holds the
    match at the scheduled self-loop because the opposing side has filed nothing,
    lifts the version by one and freezes the side's handicaps as they stand after
    week one was certified.

    Design: Corner/errors/corner_error_envelope_is_uniform_and_the_preamble_gates_run_in_order
    """
    scn = certified_match
    week_two_id = scn.match_ids[1]
    week_two = scn.match(1)
    away_team_id = week_two["away_team_id"]
    version_before = week_two["version"]

    response = scn.api.submit_lineup(
        week_two_id,
        _week_two_lineup(
            scn,
            team_id=away_team_id,
            membership_id=scn.membership_ids[0],
            expected_match_version=version_before,
        ),
        scn.secretary,
    )
    accepted = validate_success(response)
    body = response.json()
    assert_envelope(body, "object")
    for window_field in ("limit", "offset", "total_count", "has_more"):
        assert window_field not in body["meta"], (
            f"a single-resource response must omit {window_field}: {body['meta']}"
        )

    assert_fields(
        accepted,
        status=MatchStatus.SCHEDULED.value,
        version=version_before + 1,
        away_team_handicap_per_game=_blended_handicap(180, 540) + _blended_handicap(195, 720),
        home_team_handicap_per_game=0,
    )

    rows, meta = validate_paginated(
        scn.api.list_series_entries(
            scn.secretary, params={"match_id": week_two_id, "limit": MAX_LIMIT}
        )
    )
    assert meta["total_count"] == 2, (
        f"only the one side that filed has slots on week two, got {rows}"
    )
    assert all(row["team_id"] == away_team_id for row in rows)
    assert all(row["certified"] is False for row in rows)
