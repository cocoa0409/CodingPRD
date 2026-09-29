"""State-machine corners, part A.

These tests walk the declared transitions of the Match, League, Team,
Membership, FeeRemittance, LanePair, PrizeFund, Protest and AwardApplication
machines at their sharp edges: the happy path end to end, the initial state
every freshly created row occupies, the status gates that refuse a transition
taken out of order, the terminal states that refuse every further trigger, and
the remand cycle that must terminate at the third hearing.

Every figure asserted here is derived from the shared bylaw configuration and
the PRD's own arithmetic, never from a magic number: the roster's entering
handicaps, the frozen per-side lineup handicaps, the blended averages after one
certified week and the sanction-fee totals are all computed by the helpers
below.
"""
from typing import Any, Dict, List, Sequence

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
    assert_membership_axes,
    assert_points,
    expected_blended_average,
    expected_bowler_handicap,
    expected_team_handicap,
)
from test_helpers.constants import BASE_BYLAWS, ORG_MEETING_INSTANT, WEEK1_STARTS_AT
from test_helpers.types import (
    AssociationAwardDecision,
    AverageStatus,
    AwardApplicationStatus,
    AwardType,
    BasisVariant,
    EntryType,
    FeeRemittanceStatus,
    LanePairCertificationStatus,
    LeagueStatus,
    LeagueVerificationDecision,
    MatchStatus,
    MemberClass,
    MembershipRemittanceStatus,
    PrizeFundStatus,
    ProtestCategory,
    ProtestDecision,
    ProtestStatus,
    Remedy,
    RosterRole,
    SanctionStatus,
    TeamStatus,
)

# ─── Derived expectations (PRD §3.6, §3.5) ─────────────

_HANDICAP_BASE: int = BASE_BYLAWS["handicap_base"]
_MAX_HANDICAP: int = BASE_BYLAWS["max_handicap_per_game"]

# A series is three games (PRD §3.5).
_GAMES_PER_SERIES = 3

# The shared schedule puts roster slots 0 and 1 on the home side of week one and
# slots 2 and 3 on the away side.
_HOME_ROSTER = (0, 1)
_AWAY_ROSTER = (2, 3)

# The four points of one match go entirely to the side that wins all three games
# and the series (PRD §3.5).
_ALL_FOUR_POINTS = 4.0
_NO_POINTS = 0.0


def _percentage_for(index: int) -> float:
    """The handicap percentage the bowler's member class entitles them to."""
    spec = fx.DEFAULT_ROSTER[index]
    if spec.member_class is MemberClass.YOUTH:
        return BASE_BYLAWS["handicap_percentage_youth"]
    return BASE_BYLAWS["handicap_percentage"]


def _entering_handicap(index: int) -> int:
    """The handicap a freshly sanctioned roster member carries.

    With no certified games the blended average equals the declared prior-season
    average, so the CURRENT and ENTERING bases agree at this moment.
    """
    spec = fx.DEFAULT_ROSTER[index]
    return expected_bowler_handicap(
        spec.prior_season_average,
        _HANDICAP_BASE,
        _percentage_for(index),
        _MAX_HANDICAP,
    )


def _frozen_side_handicap(indexes: Sequence[int]) -> int:
    """The per-side handicap frozen onto the match at lineup submission."""
    return expected_team_handicap(_entering_handicap(index) for index in indexes)


def _week_one_pins(index: int) -> int:
    """The scratch series the shared score set gives this roster member."""
    return sum(fx.DEFAULT_GAME_PINS[index])


def _week_one_average(index: int) -> int:
    """The blended provisional average after one certified week."""
    spec = fx.DEFAULT_ROSTER[index]
    return expected_blended_average(
        spec.prior_season_average,
        spec.prior_season_games,
        _week_one_pins(index),
        _GAMES_PER_SERIES,
    )


def _week_one_handicap(index: int) -> int:
    return expected_bowler_handicap(
        _week_one_average(index),
        _HANDICAP_BASE,
        _percentage_for(index),
        _MAX_HANDICAP,
    )


# ─── Local scenario helpers ────────────────────────────


def _lineups_submitted(api: ApiClient, **kwargs: Any) -> fx.Scenario:
    """A sanctioned league whose week-one match has both lineups in."""
    scn = fx.build_sanctioned_league(api, **kwargs)
    fx.submit_both_lineups(scn, 0)
    return scn


def _slot_ids(scn: fx.Scenario, team_index: int) -> List[str]:
    return [row["id"] for row in scn.series_entries(0, team_index)]


def _membership_slot(scn: fx.Scenario, membership_index: int) -> Dict[str, Any]:
    """The week-one lineup slot naming this roster member."""
    slots = fx.slot_by_membership(scn, 0)
    return slots[scn.membership_ids[membership_index]]


# The rationale a ruling must record, and the evidence notes the honor-score
# loop exchanges.  They are module constants so a test can assert that the very
# text it sent is the text the server stored.
_DENIAL_NOTE = "Scorer sheet and pinsetter log agree; no error shown."
_REMAND_NOTE = "The panel still awaits the association's reading of the bylaw."
_ESCALATION_NOTE = "The league cannot resolve the eligibility question; escalating."
_ASSOCIATION_RULING = "Bowler was sanctioned at game time; the certified series stands."
_REOPENING_NOTE = "Reopening the settled protest."

_FIRST_EVIDENCE = "Score sheet only."
_RETURN_NOTE = "Lane certification printout missing."
_SECOND_EVIDENCE = "Score sheet plus the lane certification printout."
_CERTIFY_NOTE = "Handicap series certified on the national record."
_DENY_NOTE = "Lane dressing record for the date is unavailable."


def _file_protest(
    scn: fx.Scenario,
    category: ProtestCategory,
    *,
    membership_index: int = 0,
    match_index: int = 0,
) -> Dict[str, Any]:
    """File a protest as the bowler behind the named membership."""
    payload = f.protest_payload(
        scn.league_id,
        scn.membership_ids[membership_index],
        category,
        match_id=scn.match_ids[match_index],
    )
    return get_success_data(scn.api.file_protest(payload, scn.bowler(membership_index)))


def _open_hearing(scn: fx.Scenario, protest_id: str) -> Dict[str, Any]:
    return get_success_data(
        scn.api.review_protest(protest_id, f.review_payload(), scn.secretary)
    )


def _rule(
    scn: fx.Scenario, protest_id: str, decision: ProtestDecision, note: str, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        scn.api.rule_on_protest(
            protest_id,
            f.ruling_payload(decision.value, ruling_note=note, **kwargs),
            scn.secretary,
        )
    )


def _denied_protest(api: ApiClient) -> Dict[str, Any]:
    """A certified week one with a score-error protest heard once and denied."""
    scn = fx.build_certified_match(api)
    protest = _file_protest(scn, ProtestCategory.SCORE_ERROR)
    _open_hearing(scn, protest["id"])
    denied = _rule(
        scn, protest["id"], ProtestDecision.DENY, _DENIAL_NOTE, remedy=Remedy.NONE
    )
    assert_fields(
        denied,
        status=ProtestStatus.DENIED.value,
        remedy=Remedy.NONE.value,
        review_round=1,
    )
    return {"scn": scn, "protest_id": protest["id"]}


def _remanded_twice(api: ApiClient) -> Dict[str, Any]:
    """An eligibility protest heard and remanded twice, so review_round is 2."""
    scn = fx.build_certified_match(api)
    protest = _file_protest(scn, ProtestCategory.ELIGIBILITY)
    for _ in range(2):
        _open_hearing(scn, protest["id"])
        remanded = _rule(
            scn, protest["id"], ProtestDecision.REMAND, _REMAND_NOTE, remedy=Remedy.NONE
        )
    assert_fields(
        remanded, status=ProtestStatus.REMANDED.value, review_round=2
    )
    return {"scn": scn, "protest_id": protest["id"]}


def _claimed_pins(slot: Dict[str, Any]) -> int:
    """A HANDICAP_SERIES_700 claim is the scratch series plus three games of the
    handicap frozen onto the slot (PRD §3.8)."""
    return slot["scratch_series"] + _GAMES_PER_SERIES * slot["handicap_per_game_applied"]


def _application_payload(
    scn: fx.Scenario, slot: Dict[str, Any], evidence_note: str
) -> Dict[str, Any]:
    """A handicap-series claim carries no claimed_game_number at all."""
    return f.award_application_payload(
        scn.league_id,
        scn.membership_ids[1],
        slot["id"],
        AwardType.HANDICAP_SERIES_700,
        evidence_note=evidence_note,
    )


def _submitted_application(api: ApiClient) -> Dict[str, Any]:
    """A certified week one with a handicap-series claim sitting at SUBMITTED."""
    scn = fx.build_certified_match(api)
    slot = _membership_slot(scn, 1)
    application = get_success_data(
        scn.api.create_award_application(
            _application_payload(scn, slot, _FIRST_EVIDENCE), scn.bowler(1)
        )
    )
    return {"scn": scn, "slot": slot, "application_id": application["id"]}


# ─── The match machine's happy path, end to end ────────


def test_lineup_resubmission_is_a_self_loop_that_replaces_the_side_slots(
    api: ApiClient,
) -> None:
    """A side revising its own lineup before the match opens stays at
    LINEUPS_SUBMITTED, deletes and replaces its previous slots, and moves no
    handicap when the same two bowlers merely swap positions.

    Design: Corner/state_machines/corner_full_match_lifecycle_walks_every_declared_transition
    """
    scn = _lineups_submitted(api)
    superseded = set(_slot_ids(scn, 0))
    version = scn.match_version(0)

    swapped = [
        f.slot(1, membership_id=scn.membership_ids[1]),
        f.slot(2, membership_id=scn.membership_ids[0]),
    ]
    match = validate_success(
        scn.api.submit_lineup(
            scn.match_ids[0],
            f.lineup_payload(version, scn.team_ids[0], swapped),
            scn.captain(0),
        ),
        200,
    )
    assert_fields(
        match,
        status=MatchStatus.LINEUPS_SUBMITTED.value,
        version=version + 1,
        home_team_handicap_per_game=_frozen_side_handicap(_HOME_ROSTER),
        away_team_handicap_per_game=_frozen_side_handicap(_AWAY_ROSTER),
    )

    rows = scn.series_entries(0, 0)
    assert len(rows) == BASE_BYLAWS["lineup_positions"], (
        f"the submitting side must carry exactly {BASE_BYLAWS['lineup_positions']} "
        f"slots, got {len(rows)}"
    )
    assert_fields(
        rows[0],
        position=1,
        membership_id=scn.membership_ids[1],
        entry_type=EntryType.REGULAR.value,
        handicap_per_game_applied=_entering_handicap(1),
        counts_toward_average=True,
        certified=False,
    )
    assert_fields(
        rows[1],
        position=2,
        membership_id=scn.membership_ids[0],
        entry_type=EntryType.REGULAR.value,
        handicap_per_game_applied=_entering_handicap(0),
        counts_toward_average=True,
        certified=False,
    )
    assert not superseded.intersection(row["id"] for row in rows), (
        "the prior slots must be deleted and replaced, never updated in place"
    )


def test_opening_the_first_match_moves_the_league_in_season_and_scores_award_the_points(
    api: ApiClient,
) -> None:
    """Opening moves the match LINEUPS_SUBMITTED to OPEN and the league
    SANCTIONED to IN_SEASON, and score entry then moves OPEN to SCORES_ENTERED
    with all four points to the side that wins every game and the series while
    certifying nothing at all.

    Design: Corner/state_machines/corner_full_match_lifecycle_walks_every_declared_transition
    """
    scn = _lineups_submitted(api)
    fx.set_clock(api, WEEK1_STARTS_AT)

    opened = validate_success(
        scn.api.open_match(scn.match_ids[0], {}, scn.secretary), 200
    )
    assert_fields(opened, status=MatchStatus.OPEN.value)
    league = validate_success(scn.api.get_league(scn.league_id, scn.secretary), 200)
    assert_fields(league, status=LeagueStatus.IN_SEASON.value)

    scored = validate_success(
        scn.api.record_scores(
            scn.match_ids[0], f.scores_payload(fx.score_entries_for(scn, 0)), scn.secretary
        ),
        200,
    )
    assert_fields(scored, status=MatchStatus.SCORES_ENTERED.value)
    assert_points(scored["home_points"], _ALL_FOUR_POINTS, "home_points")
    assert_points(scored["away_points"], _NO_POINTS, "away_points")

    bowled = _membership_slot(scn, 1)
    assert_fields(
        bowled,
        games_recorded=_GAMES_PER_SERIES,
        scratch_series=_week_one_pins(1),
        certified=False,
    )
    for index in range(len(scn.membership_ids)):
        assert_fields(scn.membership(index), certified_games=0, certified_pins=0)


def test_certification_moves_scores_entered_to_certified_and_runs_its_cascade(
    api: ApiClient,
) -> None:
    """Certification is the only way games become certified games: it stamps
    certified_at from the logical clock, re-derives every bowler's average and
    handicap, absorbs the match into the team's standings figures and lifts the
    league's certified-week high-water mark.

    Design: Corner/state_machines/corner_full_match_lifecycle_walks_every_declared_transition
    """
    scn = _lineups_submitted(api)
    fx.set_clock(api, WEEK1_STARTS_AT)
    fx.open_match(scn, 0)
    fx.enter_scores(scn, fx.score_entries_for(scn, 0), 0)

    certified = validate_success(
        scn.api.certify_match(scn.match_ids[0], {}, scn.secretary), 200
    )
    assert_fields(certified, status=MatchStatus.CERTIFIED.value)
    assert_instant_equals(certified["certified_at"], WEEK1_STARTS_AT, "certified_at")

    for index in _HOME_ROSTER:
        membership = scn.membership(index)
        assert_fields(
            membership,
            certified_games=_GAMES_PER_SERIES,
            certified_pins=_week_one_pins(index),
            current_average=_week_one_average(index),
            average_status=AverageStatus.PROVISIONAL.value,
            handicap_per_game=_week_one_handicap(index),
        )

    home_team = scn.team(0)
    assert_points(home_team["total_points"], _ALL_FOUR_POINTS, "total_points")
    assert_fields(
        home_team,
        total_scratch_pins=sum(_week_one_pins(index) for index in _HOME_ROSTER),
        team_handicap_per_game=expected_team_handicap(
            _week_one_handicap(index) for index in _HOME_ROSTER
        ),
    )

    league = validate_success(scn.api.get_league(scn.league_id, scn.secretary), 200)
    assert_fields(
        league, status=LeagueStatus.IN_SEASON.value, certified_week_high_water=1
    )


# ─── The initial state of every machine ────────────────


def test_freshly_created_rows_sit_in_their_declared_initial_states(
    api: ApiClient,
) -> None:
    """A team starts PROVISIONAL with every counter at zero, a membership starts
    UNSANCTIONED on the sanction axis and UNPAID on the money axis with its
    entering average already derived but no handicap, a lane pair reads CERTIFIED
    with last_certified_at at the clock, a match created while the league is only
    BYLAWS_ADOPTED starts DRAFT rather than SCHEDULED, and the prize fund minted
    silently at chartering sits at ACCUMULATING with no paying places.

    Design: Corner/state_machines/corner_new_rows_start_in_their_declared_initial_states
    """
    scn = fx.build_league(api)

    team = validate_success(scn.api.get_team(scn.team_ids[0], scn.secretary), 200)
    assert_fields(
        team,
        status=TeamStatus.PROVISIONAL.value,
        sanctioned_roster_count=0,
        team_handicap_per_game=0,
        total_scratch_pins=0,
    )
    assert_points(team["total_points"], 0.0, "total_points")

    membership = validate_success(
        scn.api.get_membership(scn.membership_ids[1], scn.secretary), 200
    )
    assert_membership_axes(
        membership, SanctionStatus.UNSANCTIONED, MembershipRemittanceStatus.UNPAID
    )
    assert_fields(
        membership,
        entering_average=fx.DEFAULT_ROSTER[1].prior_season_average,
        average_status=AverageStatus.PROVISIONAL.value,
        handicap_per_game=0,
        certified_games=0,
        certified_pins=0,
        dues_arrears_weeks=0,
        roster_role=RosterRole.REGULAR.value,
    )

    lane_pair = validate_success(
        scn.api.get_lane_pair(scn.lane_pair_ids[0], scn.officer), 200
    )
    assert_fields(
        lane_pair,
        certification_status=LanePairCertificationStatus.CERTIFIED.value,
        revoked_at=None,
    )
    assert_instant_equals(
        lane_pair["last_certified_at"], ORG_MEETING_INSTANT, "last_certified_at"
    )

    match = validate_success(scn.api.get_match(scn.match_ids[0], scn.secretary), 200)
    assert_fields(
        match,
        status=MatchStatus.DRAFT.value,
        home_team_handicap_per_game=0,
        away_team_handicap_per_game=0,
        certified_at=None,
        forfeiting_team_id=None,
        void_reason=None,
    )
    assert_points(match["home_points"], 0.0, "home_points")
    assert_points(match["away_points"], 0.0, "away_points")

    funds, meta = validate_paginated(
        scn.api.list_prize_funds(scn.secretary, params={"league_id": scn.league_id})
    )
    assert meta["total_count"] == 1, (
        f"chartering creates exactly one prize fund, got {meta['total_count']}"
    )
    fund = funds[0]
    assert_fields(
        fund,
        status=PrizeFundStatus.ACCUMULATING.value,
        basis_variant=BasisVariant.PROJECTED_SEASON_END.value,
        place_count=0,
        plan_drafted_at=None,
        plan_approved_by_user_id=None,
    )
    assert_cents(fund["collected_prize_cents"], 0, "collected_prize_cents")
    assert_cents(fund["plan_basis_cents"], 0, "plan_basis_cents")
    assert_cents(fund["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert_cents(fund["undistributed_balance_cents"], 0, "undistributed_balance_cents")

    league = validate_success(scn.api.get_league(scn.league_id, scn.secretary), 200)
    assert_fields(
        league,
        status=LeagueStatus.BYLAWS_ADOPTED.value,
        confirmed_team_count=0,
        sanctioned_member_count=0,
    )


def test_a_new_fee_remittance_starts_at_draft_and_prices_nothing(
    api: ApiClient,
) -> None:
    """Opening a remittance creates it at DRAFT with member_count taken from the
    listed identifiers but computed_amount_cents and penalty_cents still zero,
    because the draft prices nothing and nothing has been submitted upward yet.

    Design: Corner/state_machines/corner_new_rows_start_in_their_declared_initial_states
    """
    scn = fx.build_league(api)
    declared = fx.expected_remittance_cents(scn, scn.membership_ids)

    remittance = validate_success(
        scn.api.create_fee_remittance(
            f.fee_remittance_payload(scn.league_id, scn.membership_ids, declared),
            scn.treasurer,
        ),
        201,
    )
    assert_fields(
        remittance,
        status=FeeRemittanceStatus.DRAFT.value,
        member_count=len(scn.membership_ids),
        submitted_at=None,
        submitted_by_user_id=None,
        national_receipt_no=None,
        rejection_reason=None,
    )
    assert_cents(remittance["computed_amount_cents"], 0, "computed_amount_cents")
    assert_cents(remittance["penalty_cents"], 0, "penalty_cents")
    assert_cents(remittance["declared_amount_cents"], declared, "declared_amount_cents")


# ─── Certification is gated on SCORES_ENTERED ──────────


def test_certifying_an_open_match_is_refused_and_fires_no_cascade_hop(
    api: ApiClient,
) -> None:
    """Certification admits only a match at SCORES_ENTERED, so an OPEN match with
    a complete legal lineup on both sides is refused with the match-state code,
    no slot flips its certified flag and no average, handicap or league
    high-water mark moves.

    Design: Corner/state_machines/corner_certify_before_scores_are_entered_is_refused
    """
    scn = fx.build_open_match(api)

    validate_error(
        scn.api.certify_match(scn.match_ids[0], {}, scn.secretary),
        ApiErrorId.ERR_MATCH_STATE_INVALID.value,
    )

    match = validate_success(scn.api.get_match(scn.match_ids[0], scn.secretary), 200)
    assert_fields(match, status=MatchStatus.OPEN.value, certified_at=None)

    slot = _membership_slot(scn, 0)
    assert_fields(
        slot,
        certified=False,
        games_recorded=0,
        scratch_series=0,
        game1_pins=None,
    )
    assert_fields(
        scn.membership(0),
        certified_games=0,
        certified_pins=0,
        handicap_per_game=_entering_handicap(0),
    )
    league = validate_success(scn.api.get_league(scn.league_id, scn.secretary), 200)
    assert_fields(league, certified_week_high_water=0)


def test_the_refused_certification_succeeds_once_the_scores_are_recorded(
    api: ApiClient,
) -> None:
    """The very call the OPEN match refused is accepted the moment score entry
    has moved the match to SCORES_ENTERED, which is what shows the refusal was a
    status gate and nothing else.

    Design: Corner/state_machines/corner_certify_before_scores_are_entered_is_refused
    """
    scn = fx.build_open_match(api)
    validate_error(
        scn.api.certify_match(scn.match_ids[0], {}, scn.secretary),
        ApiErrorId.ERR_MATCH_STATE_INVALID.value,
    )

    scored = validate_success(
        scn.api.record_scores(
            scn.match_ids[0], f.scores_payload(fx.score_entries_for(scn, 0)), scn.secretary
        ),
        200,
    )
    assert_fields(scored, status=MatchStatus.SCORES_ENTERED.value)

    certified = validate_success(
        scn.api.certify_match(scn.match_ids[0], {}, scn.secretary), 200
    )
    assert_fields(certified, status=MatchStatus.CERTIFIED.value)
    assert_instant_equals(certified["certified_at"], WEEK1_STARTS_AT, "certified_at")

    assert_fields(
        scn.membership(0),
        certified_games=_GAMES_PER_SERIES,
        certified_pins=_week_one_pins(0),
        current_average=_week_one_average(0),
    )
    league = validate_success(scn.api.get_league(scn.league_id, scn.secretary), 200)
    assert_fields(league, certified_week_high_water=1)


# ─── The remittance status gate, in both directions ────


def test_replaying_submit_on_a_submitted_remittance_is_refused_and_reprices_nothing(
    api: ApiClient,
) -> None:
    """Submission is legal only from DRAFT or REJECTED, so a replayed submit on
    an already SUBMITTED remittance is refused with the remittance-state code and
    neither re-prices the remittance nor advances either membership axis twice.

    Design: Corner/state_machines/corner_remittance_submitted_twice_and_a_decision_on_a_draft_are_refused
    """
    scn = fx.build_league(api)
    declared = fx.expected_remittance_cents(scn, scn.membership_ids)
    remittance_id = fx.open_remittance(scn)
    submitted = fx.submit_remittance(scn, remittance_id)
    assert_fields(submitted, status=FeeRemittanceStatus.SUBMITTED.value)
    assert_cents(submitted["computed_amount_cents"], declared, "computed_amount_cents")

    validate_error(
        scn.api.submit_fee_remittance(
            remittance_id, f.remittance_submit_payload(declared), scn.treasurer
        ),
        ApiErrorId.ERR_REMITTANCE_STATE_INVALID.value,
    )

    read_back = validate_success(
        scn.api.get_fee_remittance(remittance_id, scn.treasurer), 200
    )
    assert_fields(
        read_back,
        status=FeeRemittanceStatus.SUBMITTED.value,
        version=submitted["version"],
        member_count=len(scn.membership_ids),
    )
    assert_cents(read_back["computed_amount_cents"], declared, "computed_amount_cents")
    assert_cents(read_back["penalty_cents"], 0, "penalty_cents")
    assert_instant_equals(read_back["submitted_at"], ORG_MEETING_INSTANT, "submitted_at")

    for index in range(len(scn.membership_ids)):
        assert_membership_axes(
            scn.membership(index),
            SanctionStatus.PENDING_REMITTANCE,
            MembershipRemittanceStatus.INVOICED,
        )


def test_a_national_decision_on_a_draft_remittance_is_refused_until_it_is_submitted(
    api: ApiClient,
) -> None:
    """The national decision admits only a SUBMITTED remittance, so a decision on
    a draft that was never filed is refused with the same remittance-state code
    and leaves both membership axes where they were; submitting the draft then
    prices it and the acceptance sanctions the listed bowler.

    Design: Corner/state_machines/corner_remittance_submitted_twice_and_a_decision_on_a_draft_are_refused
    """
    substitute = fx.RosterSpec(
        "Gus Sub",
        MemberClass.ADULT,
        prior_season_average=175,
        prior_season_games=30,
        team_index=None,
        roster_role=RosterRole.SUBSTITUTE,
    )
    scn = fx.build_league(api, roster=tuple(fx.DEFAULT_ROSTER) + (substitute,))
    sub_index = len(scn.membership_ids) - 1
    listed = [scn.membership_ids[sub_index]]
    declared = fx.expected_remittance_cents(scn, listed)

    draft = validate_success(
        scn.api.create_fee_remittance(
            f.fee_remittance_payload(scn.league_id, listed, declared), scn.treasurer
        ),
        201,
    )
    assert_fields(draft, status=FeeRemittanceStatus.DRAFT.value, member_count=1)
    assert_cents(draft["computed_amount_cents"], 0, "computed_amount_cents")

    validate_error(
        scn.api.record_national_decision(
            draft["id"], f.national_accept_payload("NR-2913-0021"), scn.officer
        ),
        ApiErrorId.ERR_REMITTANCE_STATE_INVALID.value,
    )
    assert_membership_axes(
        scn.membership(sub_index),
        SanctionStatus.UNSANCTIONED,
        MembershipRemittanceStatus.UNPAID,
    )

    submitted = validate_success(
        scn.api.submit_fee_remittance(
            draft["id"], f.remittance_submit_payload(), scn.treasurer
        ),
        200,
    )
    assert_fields(submitted, status=FeeRemittanceStatus.SUBMITTED.value)
    assert_cents(submitted["computed_amount_cents"], declared, "computed_amount_cents")
    assert_cents(submitted["penalty_cents"], 0, "penalty_cents")

    accepted = validate_success(
        scn.api.record_national_decision(
            draft["id"], f.national_accept_payload("NR-2913-0022"), scn.officer
        ),
        200,
    )
    assert_fields(
        accepted,
        status=FeeRemittanceStatus.ACCEPTED.value,
        national_receipt_no="NR-2913-0022",
    )
    membership = scn.membership(sub_index)
    assert_membership_axes(
        membership, SanctionStatus.SANCTIONED, MembershipRemittanceStatus.REMITTED
    )
    assert_fields(
        membership,
        handicap_per_game=expected_bowler_handicap(
            substitute.prior_season_average,
            _HANDICAP_BASE,
            BASE_BYLAWS["handicap_percentage"],
            _MAX_HANDICAP,
        ),
    )


# ─── DENIED is terminal for the protest machine ────────


def test_a_denied_protest_refuses_a_further_hearing_and_a_further_ruling(
    api: ApiClient,
) -> None:
    """A denial is terminal: a hearing admits only FILED or REMANDED and a ruling
    admits only UNDER_REVIEW, so both triggers are refused with the protest-state
    code and the denial's own review round, remedy and rationale stand.

    Design: Corner/state_machines/corner_denied_protest_is_terminal_for_every_further_trigger
    """
    context = _denied_protest(api)
    scn: fx.Scenario = context["scn"]
    protest_id: str = context["protest_id"]

    validate_error(
        scn.api.review_protest(protest_id, f.review_payload(), scn.secretary),
        ApiErrorId.ERR_PROTEST_STATE_INVALID.value,
    )
    validate_error(
        scn.api.rule_on_protest(
            protest_id,
            f.ruling_payload(
                ProtestDecision.UPHOLD.value,
                ruling_note=_REOPENING_NOTE,
                remedy=Remedy.VOID_MATCH,
            ),
            scn.secretary,
        ),
        ApiErrorId.ERR_PROTEST_STATE_INVALID.value,
    )

    protest = validate_success(scn.api.get_protest(protest_id, scn.secretary), 200)
    assert_fields(
        protest,
        status=ProtestStatus.DENIED.value,
        remedy=Remedy.NONE.value,
        review_round=1,
        ruling_note=_DENIAL_NOTE,
    )


def test_a_denied_protest_refuses_an_association_ruling_and_runs_no_remedy(
    api: ApiClient,
) -> None:
    """An association ruling admits only an ESCALATED protest, so one aimed at a
    denial is refused before its remedy is ever considered, leaving the protested
    match certified with its points, its bowlers' certified pins and its team
    standings figures exactly as the certification left them.

    Design: Corner/state_machines/corner_denied_protest_is_terminal_for_every_further_trigger
    """
    context = _denied_protest(api)
    scn: fx.Scenario = context["scn"]
    protest_id: str = context["protest_id"]

    validate_error(
        scn.api.association_rule_on_protest(
            protest_id,
            f.association_ruling_payload(
                _ASSOCIATION_RULING, remedy=Remedy.VOID_MATCH.value
            ),
            scn.officer,
        ),
        ApiErrorId.ERR_PROTEST_STATE_INVALID.value,
    )

    protest = validate_success(scn.api.get_protest(protest_id, scn.secretary), 200)
    assert_fields(
        protest, status=ProtestStatus.DENIED.value, association_ruling=None
    )

    match = validate_success(scn.api.get_match(scn.match_ids[0], scn.secretary), 200)
    assert_fields(match, status=MatchStatus.CERTIFIED.value, void_reason=None)
    assert_instant_equals(match["certified_at"], WEEK1_STARTS_AT, "certified_at")
    assert_points(match["home_points"], _ALL_FOUR_POINTS, "home_points")
    assert_points(match["away_points"], _NO_POINTS, "away_points")

    assert_fields(
        scn.membership(0),
        certified_pins=_week_one_pins(0),
        certified_games=_GAMES_PER_SERIES,
        handicap_per_game=_week_one_handicap(0),
    )
    assert_points(scn.team(0)["total_points"], _ALL_FOUR_POINTS, "total_points")


# ─── The remand cycle terminates at the third hearing ──


def test_the_third_hearing_may_no_longer_remand_the_protest(api: ApiClient) -> None:
    """Two walks of the remand cycle carry review_round to 3, and the third
    hearing may not remand again: a REMAND is refused with the review-round
    ceiling, because REMANDED's only exit is a fourth hearing that would never be
    legal, and the protest stays under review at the round it reached.

    Design: Corner/state_machines/corner_remand_loop_terminates_at_review_round_three
    """
    context = _remanded_twice(api)
    scn: fx.Scenario = context["scn"]
    protest_id: str = context["protest_id"]

    reopened = validate_success(
        scn.api.review_protest(protest_id, f.review_payload(), scn.secretary), 200
    )
    assert_fields(
        reopened, status=ProtestStatus.UNDER_REVIEW.value, review_round=3
    )

    validate_error(
        scn.api.rule_on_protest(
            protest_id,
            f.ruling_payload(
                ProtestDecision.REMAND.value,
                ruling_note=_REMAND_NOTE,
                remedy=Remedy.NONE,
            ),
            scn.secretary,
        ),
        ApiErrorId.ERR_REVIEW_ROUND_LIMIT.value,
    )

    protest = validate_success(scn.api.get_protest(protest_id, scn.secretary), 200)
    assert_fields(
        protest,
        status=ProtestStatus.UNDER_REVIEW.value,
        review_round=3,
        remedy=Remedy.NONE.value,
    )


def test_escalation_from_the_third_hearing_reaches_the_association_terminal_state(
    api: ApiClient,
) -> None:
    """The round-three hearing keeps its legal exits: ESCALATE is permitted once
    review_round has reached 2, the association's ruling then moves the protest to
    its terminal ASSOCIATION_RULED without touching review_round, and a NONE
    remedy leaves the certified match and its figures alone.

    Design: Corner/state_machines/corner_remand_loop_terminates_at_review_round_three
    """
    context = _remanded_twice(api)
    scn: fx.Scenario = context["scn"]
    protest_id: str = context["protest_id"]
    _open_hearing(scn, protest_id)

    escalated = validate_success(
        scn.api.rule_on_protest(
            protest_id,
            f.ruling_payload(
                ProtestDecision.ESCALATE.value,
                ruling_note=_ESCALATION_NOTE,
                remedy=Remedy.NONE,
            ),
            scn.secretary,
        ),
        200,
    )
    assert_fields(
        escalated, status=ProtestStatus.ESCALATED.value, review_round=3
    )

    ruled = validate_success(
        scn.api.association_rule_on_protest(
            protest_id,
            f.association_ruling_payload(_ASSOCIATION_RULING, remedy=Remedy.NONE.value),
            scn.officer,
        ),
        200,
    )
    assert_fields(
        ruled,
        status=ProtestStatus.ASSOCIATION_RULED.value,
        remedy=Remedy.NONE.value,
        review_round=3,
        association_ruling=_ASSOCIATION_RULING,
    )

    match = validate_success(scn.api.get_match(scn.match_ids[0], scn.secretary), 200)
    assert_fields(match, status=MatchStatus.CERTIFIED.value)
    assert_points(match["home_points"], _ALL_FOUR_POINTS, "home_points")
    assert_points(match["away_points"], _NO_POINTS, "away_points")
    assert_fields(scn.membership(0), certified_pins=_week_one_pins(0))
    assert_points(scn.team(0)["total_points"], _ALL_FOUR_POINTS, "total_points")


# ─── The honor-score machine cannot be short-circuited ─


def test_an_award_application_at_submitted_refuses_the_association_and_evidence_steps(
    api: ApiClient,
) -> None:
    """Only league verification is legal from SUBMITTED: the association step
    needs LEAGUE_VERIFIED and the evidence step needs RETURNED_FOR_EVIDENCE, so
    both are refused with the award-application state code and the claim keeps its
    round count, its null verifier and its null association note.

    Design: Corner/state_machines/corner_award_association_decision_and_evidence_are_gated_on_status
    """
    scn = fx.build_certified_match(api)
    slot = _membership_slot(scn, 1)

    application = validate_success(
        scn.api.create_award_application(
            _application_payload(scn, slot, _FIRST_EVIDENCE), scn.bowler(1)
        ),
        201,
    )
    assert_fields(
        application,
        status=AwardApplicationStatus.SUBMITTED.value,
        award_type=AwardType.HANDICAP_SERIES_700.value,
        claimed_game_number=None,
        claimed_pins=_claimed_pins(slot),
        round_count=1,
        lane_certification_verified=True,
        sanctioned_at_game_time=True,
    )

    validate_error(
        scn.api.association_decide_application(
            application["id"],
            f.association_decision_payload(
                AssociationAwardDecision.CERTIFY.value, _CERTIFY_NOTE
            ),
            scn.officer,
        ),
        ApiErrorId.ERR_AWARD_APPLICATION_STATE_INVALID.value,
    )
    validate_error(
        scn.api.resubmit_evidence(
            application["id"], f.evidence_payload(_SECOND_EVIDENCE), scn.bowler(1)
        ),
        ApiErrorId.ERR_AWARD_APPLICATION_STATE_INVALID.value,
    )

    read_back = validate_success(
        scn.api.get_award_application(application["id"], scn.secretary), 200
    )
    assert_fields(
        read_back,
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=1,
        verified_by_user_id=None,
        association_ruling_note=None,
        evidence_note=_FIRST_EVIDENCE,
    )


def test_league_verification_then_association_certification_walk_the_legal_path(
    api: ApiClient,
) -> None:
    """The two steps the refusals were waiting for succeed in order: verification
    moves SUBMITTED to LEAGUE_VERIFIED and records the acting secretary, and the
    association's certification moves LEAGUE_VERIFIED to its terminal
    ASSOCIATION_CERTIFIED with the claim figure frozen at its filed value.

    Design: Corner/state_machines/corner_award_association_decision_and_evidence_are_gated_on_status
    """
    context = _submitted_application(api)
    scn: fx.Scenario = context["scn"]
    slot: Dict[str, Any] = context["slot"]
    application_id: str = context["application_id"]

    verified = validate_success(
        scn.api.league_verify_application(
            application_id,
            f.league_verification_payload(LeagueVerificationDecision.VERIFY.value),
            scn.secretary,
        ),
        200,
    )
    assert_fields(
        verified,
        status=AwardApplicationStatus.LEAGUE_VERIFIED.value,
        verified_by_user_id=scn.secretary_member_id,
        round_count=1,
    )

    certified = validate_success(
        scn.api.association_decide_application(
            application_id,
            f.association_decision_payload(
                AssociationAwardDecision.CERTIFY.value, _CERTIFY_NOTE
            ),
            scn.officer,
        ),
        200,
    )
    assert_fields(
        certified,
        status=AwardApplicationStatus.ASSOCIATION_CERTIFIED.value,
        association_ruling_note=_CERTIFY_NOTE,
        claimed_pins=_claimed_pins(slot),
    )


def test_returning_an_application_for_evidence_and_resupplying_it_bumps_round_count(
    api: ApiClient,
) -> None:
    """The applicant's loop writes every declared side effect: the return records
    what is missing and leaves round_count alone, the resubmission overwrites the
    evidence note, counts the fresh entry into SUBMITTED and clears the verifier,
    and the later verification does not count itself.

    Design: Corner/state_machines/corner_award_returned_for_evidence_then_resubmitted_increments_round_count
    """
    context = _submitted_application(api)
    scn: fx.Scenario = context["scn"]
    application_id: str = context["application_id"]

    returned = validate_success(
        scn.api.league_verify_application(
            application_id,
            f.league_verification_payload(
                LeagueVerificationDecision.RETURN_FOR_EVIDENCE.value,
                evidence_note=_RETURN_NOTE,
            ),
            scn.secretary,
        ),
        200,
    )
    assert_fields(
        returned,
        status=AwardApplicationStatus.RETURNED_FOR_EVIDENCE.value,
        evidence_note=_RETURN_NOTE,
        round_count=1,
    )

    resubmitted = validate_success(
        scn.api.resubmit_evidence(
            application_id, f.evidence_payload(_SECOND_EVIDENCE), scn.bowler(1)
        ),
        200,
    )
    assert_fields(
        resubmitted,
        status=AwardApplicationStatus.SUBMITTED.value,
        evidence_note=_SECOND_EVIDENCE,
        round_count=2,
        verified_by_user_id=None,
    )

    verified = validate_success(
        scn.api.league_verify_application(
            application_id,
            f.league_verification_payload(LeagueVerificationDecision.VERIFY.value),
            scn.secretary,
        ),
        200,
    )
    assert_fields(
        verified,
        status=AwardApplicationStatus.LEAGUE_VERIFIED.value,
        verified_by_user_id=scn.secretary_member_id,
        round_count=2,
    )


def test_an_association_denial_is_terminal_and_touches_no_average(
    api: ApiClient,
) -> None:
    """A denial by the association is terminal, so a second decision on the same
    application is refused with the award-application state code, the recorded
    reason stands, and the bowler's certified pins and handicap are untouched
    throughout — an honor-score claim never feeds an average.

    Design: Corner/state_machines/corner_award_returned_for_evidence_then_resubmitted_increments_round_count
    """
    context = _submitted_application(api)
    scn: fx.Scenario = context["scn"]
    slot: Dict[str, Any] = context["slot"]
    application_id: str = context["application_id"]

    get_success_data(
        scn.api.league_verify_application(
            application_id,
            f.league_verification_payload(
                LeagueVerificationDecision.RETURN_FOR_EVIDENCE.value,
                evidence_note=_RETURN_NOTE,
            ),
            scn.secretary,
        )
    )
    get_success_data(
        scn.api.resubmit_evidence(
            application_id, f.evidence_payload(_SECOND_EVIDENCE), scn.bowler(1)
        )
    )
    get_success_data(
        scn.api.league_verify_application(
            application_id,
            f.league_verification_payload(LeagueVerificationDecision.VERIFY.value),
            scn.secretary,
        )
    )

    denied = validate_success(
        scn.api.association_decide_application(
            application_id,
            f.association_decision_payload(
                AssociationAwardDecision.DENY.value, _DENY_NOTE
            ),
            scn.officer,
        ),
        200,
    )
    assert_fields(
        denied,
        status=AwardApplicationStatus.ASSOCIATION_DENIED.value,
        association_ruling_note=_DENY_NOTE,
        round_count=2,
    )

    validate_error(
        scn.api.association_decide_application(
            application_id,
            f.association_decision_payload(
                AssociationAwardDecision.CERTIFY.value, _CERTIFY_NOTE
            ),
            scn.officer,
        ),
        ApiErrorId.ERR_AWARD_APPLICATION_STATE_INVALID.value,
    )

    read_back = validate_success(
        scn.api.get_award_application(application_id, scn.secretary), 200
    )
    assert_fields(
        read_back,
        status=AwardApplicationStatus.ASSOCIATION_DENIED.value,
        association_ruling_note=_DENY_NOTE,
        claimed_pins=_claimed_pins(slot),
    )
    assert_fields(
        scn.membership(1),
        certified_pins=_week_one_pins(1),
        certified_games=_GAMES_PER_SERIES,
        handicap_per_game=_week_one_handicap(1),
    )
