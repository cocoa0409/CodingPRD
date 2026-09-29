"""Refusal families whose members are only separable when the configuration
lets each rule fire alone.

The PRD orders every check and lets the first violated one decide the response,
so a rule buried deep in the chain is invisible until every earlier rule is
satisfied.  This module builds those configurations deliberately.  The lineup
family (slot shape, the vacancy ceiling, duplicate bowlers and substitute
eligibility) collapses into its first member at two positions with a minimum of
two, so the league amends itself to three positions with a minimum of one before
each rule is provoked on its own.  The honor-score surface carries three
referential gates in a row — request shape, single-league membership and the
slot-to-bowler relationship — which one body can break all at once.  Opening a
match distinguishes a pair that is certified *now* from a pair certified far
enough forward to cover the match's own start.  Score entry separates a negative
pin count, which is a shape violation, from a pin count of 301, which is not.
Schedule adoption reads its team coverage from the declared count rather than
from the teams that happen to exist.  And two uniqueness clauses share one error
code across enrolment and remittance drafting.

Every refusal here is also asserted to have written nothing at all.
"""
from typing import Any, Dict, List, Optional

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
    assert_ids_in_order,
    assert_instant_equals,
    assert_membership_axes,
    assert_ordered_by,
    assert_points,
)
from test_helpers.constants import (
    WEEK1_ENDS_AT,
    WEEK1_STARTS_AT,
    WEEK2_ENDS_AT,
    WEEK2_STARTS_AT,
)
from test_helpers.types import (
    AwardApplicationStatus,
    AwardType,
    EntryType,
    FeeRemittanceStatus,
    LanePairCertificationStatus,
    LeagueStatus,
    MatchStatus,
    MemberClass,
    MembershipRemittanceStatus,
    RosterRole,
    SanctionStatus,
    TeamStatus,
)

# ─── reads, validated rather than lenient ───────────────
# The layered builders use the lenient setup validator; every read a test
# asserts on goes through ``validate_success`` so a wrong success status is
# caught where it matters.


def _league(scn: fx.Scenario) -> Dict[str, Any]:
    return validate_success(scn.api.get_league(scn.league_id, scn.secretary))


def _team(scn: fx.Scenario, index: int) -> Dict[str, Any]:
    return validate_success(scn.api.get_team(scn.team_ids[index], scn.secretary))


def _membership(scn: fx.Scenario, index: int) -> Dict[str, Any]:
    return validate_success(
        scn.api.get_membership(scn.membership_ids[index], scn.secretary)
    )


def _match(scn: fx.Scenario, index: int = 0) -> Dict[str, Any]:
    return validate_success(scn.api.get_match(scn.match_ids[index], scn.secretary))


def _lane_pair(scn: fx.Scenario, index: int = 0) -> Dict[str, Any]:
    return validate_success(
        scn.api.get_lane_pair(scn.lane_pair_ids[index], scn.officer)
    )


def _slots(
    scn: fx.Scenario, match_index: int = 0, team_index: Optional[int] = None
) -> List[Dict[str, Any]]:
    """The lineup-slot listing is the only discovery channel for slots."""
    params: Dict[str, Any] = {"match_id": scn.match_ids[match_index], "limit": 100}
    if team_index is not None:
        params["team_id"] = scn.team_ids[team_index]
    return validate_success(scn.api.list_series_entries(scn.secretary, params=params))


def _submit_lineup(
    scn: fx.Scenario,
    team_index: int,
    slots: List[Dict[str, Any]],
    match_index: int = 1,
):
    """Post one side's lineup, echoing the match's version as read right now."""
    return scn.api.submit_lineup(
        scn.match_ids[match_index],
        f.lineup_payload(
            _match(scn, match_index)["version"], scn.team_ids[team_index], slots
        ),
        scn.secretary,
    )


# ══════════════════════════════════════════════════════════
# The lineup legality family, provoked one rule at a time
# ══════════════════════════════════════════════════════════

# Three positions with a minimum of one and a vacancy cap of one: the only
# configuration in which the slot-shape rule, the vacancy ceiling, the duplicate
# rule and substitute eligibility can each fail while the earlier ones hold.
_WIDER_LINEUP = {
    "lineup_positions": 3,
    "legal_lineup_minimum": 1,
    "max_vacancy_slots_per_lineup": 1,
}

# Roster indexes inside the scenario built by ``_widened_lineup_league``.
_BENCHED = 4       # enrolled on team 1 but never remitted, so UNSANCTIONED
_SWING = 5         # a SANCTIONED SUBSTITUTE carried on team 2

_WIDER_ROSTER = list(fx.DEFAULT_ROSTER) + [
    fx.RosterSpec("Gus Bench", MemberClass.ADULT, 175, 30, 0),
    fx.RosterSpec("Hal Swing", MemberClass.ADULT, 150, 30, 1, RosterRole.SUBSTITUTE),
]


def _widened_lineup_league(api: ApiClient) -> fx.Scenario:
    """Week one certified, then the bylaws amended to three lineup positions.

    Five of the six enrolled bowlers are remitted; Gus Bench is left off the
    remittance so team one carries a roster member who is no candidate for the
    team handicap.  Week two is still SCHEDULED with no slot on either side.
    """
    scn = fx.build_league(api, roster=_WIDER_ROSTER)
    fx.sanction(scn, [scn.membership_ids[index] for index in (0, 1, 2, 3, _SWING)])
    fx.submit_both_lineups(scn, 0)
    fx.set_clock(api, WEEK1_STARTS_AT)
    fx.open_match(scn, 0)
    fx.enter_scores(scn, fx.score_entries_for(scn, 0), 0)
    fx.certify_match(scn, 0)
    fx.adopt_bylaws(scn, **_WIDER_LINEUP)
    return scn


def _assert_no_slots_and_untouched_match(scn: fx.Scenario, version: int) -> None:
    """A refused submission writes no slot and does not move the match."""
    assert _slots(scn, 1) == [], "a refused lineup submission wrote slots"
    assert_fields(
        _match(scn, 1),
        status=MatchStatus.SCHEDULED.value,
        version=version,
        home_team_handicap_per_game=0,
        away_team_handicap_per_game=0,
    )


def test_amendment_widens_the_lineup_without_padding_the_team_handicap(
    api: ApiClient,
):
    """A mid-season amendment overwrites every bylaw field and re-derives every
    membership and team figure from the pins already certified.  Team one keeps a
    team handicap of 54 — the 36 and 18 its two SANCTIONED members earned from
    week one — even though the roster depth is now three positions and the team
    carries a third roster member: an UNSANCTIONED membership is no candidate,
    and the ranking keeps all the candidates there are rather than padding out to
    the new depth with notional vacancies.

    Design: Corner/validations/corner_lineup_legality_family_rejects_then_admits_the_padded_lineup
    """
    scn = _widened_lineup_league(api)

    league = _league(scn)
    assert_fields(
        league,
        status=LeagueStatus.IN_SEASON.value,
        lineup_positions=3,
        legal_lineup_minimum=1,
        max_vacancy_slots_per_lineup=1,
        handicap_base=220,
        handicap_percentage=0.90,
    )

    assert_fields(_membership(scn, 0), current_average=180, handicap_per_game=36)
    assert_fields(_membership(scn, 1), current_average=199, handicap_per_game=18)
    assert_membership_axes(
        _membership(scn, _BENCHED),
        SanctionStatus.UNSANCTIONED,
        MembershipRemittanceStatus.UNPAID,
    )
    assert_fields(_membership(scn, _BENCHED), handicap_per_game=0)
    assert_fields(_team(scn, 0), team_handicap_per_game=54)
    assert_fields(_match(scn, 1), status=MatchStatus.SCHEDULED.value)


def test_lineup_slot_shape_is_refused_before_the_vacancy_ceiling(api: ApiClient):
    """The first legality check covers three things at once — exactly
    ``lineup_positions`` slots, the positions being 1 through
    ``lineup_positions`` each exactly once, and at least
    ``legal_lineup_minimum`` bowling slots — and all three yield
    ERR_ILLEGAL_LINEUP.  The all-vacancy lineup proves the ordering: it breaks
    the legal-bowler minimum *and* the vacancy ceiling, and the shape check is
    consulted first, so ERR_VACANCY_LIMIT_EXCEEDED is never reported.

    Design: Corner/validations/corner_lineup_legality_family_rejects_then_admits_the_padded_lineup
    """
    scn = _widened_lineup_league(api)
    version = _match(scn, 1)["version"]

    two_slots = fx.regular_slots(scn, (0, 1))
    validate_error(
        _submit_lineup(scn, 0, two_slots),
        ApiErrorId.ERR_ILLEGAL_LINEUP.value,
    )
    _assert_no_slots_and_untouched_match(scn, version)

    repeated_position = fx.regular_slots(scn, (0, 1)) + [f.vacancy_slot(2)]
    validate_error(
        _submit_lineup(scn, 0, repeated_position),
        ApiErrorId.ERR_ILLEGAL_LINEUP.value,
    )
    _assert_no_slots_and_untouched_match(scn, version)

    all_vacancies = [f.vacancy_slot(position) for position in (1, 2, 3)]
    validate_error(
        _submit_lineup(scn, 0, all_vacancies),
        ApiErrorId.ERR_ILLEGAL_LINEUP.value,
    )
    _assert_no_slots_and_untouched_match(scn, version)


def test_absentee_slots_count_against_the_same_ceiling_as_vacancies(api: ApiClient):
    """The ceiling is on vacancies *plus* absentees, so one of each already
    exceeds a cap of one.  The lineup clears the shape check first — three slots
    at positions 1, 2 and 3 with one bowling slot against a minimum of one — so
    the refusal that surfaces is ERR_VACANCY_LIMIT_EXCEEDED.

    Design: Corner/validations/corner_lineup_legality_family_rejects_then_admits_the_padded_lineup
    """
    scn = _widened_lineup_league(api)
    version = _match(scn, 1)["version"]

    slots = [
        f.slot(1, EntryType.REGULAR, scn.membership_ids[0]),
        f.vacancy_slot(2),
        f.absentee_slot(3, scn.membership_ids[1]),
    ]
    validate_error(
        _submit_lineup(scn, 0, slots),
        ApiErrorId.ERR_VACANCY_LIMIT_EXCEEDED.value,
    )
    _assert_no_slots_and_untouched_match(scn, version)


def test_duplicate_bowler_outranks_substitute_eligibility(api: ApiClient):
    """No membership may appear twice in one lineup, and that check runs before
    substitute eligibility.  Naming one bowler at two positions is refused with
    ERR_DUPLICATE_BOWLER_IN_LINEUP on its own; a lineup that both duplicates a
    bowler and names a substitute carried on the opposing team returns the same
    code, and ERR_SUBSTITUTE_NOT_ELIGIBLE is never reported.

    Design: Corner/validations/corner_lineup_legality_family_rejects_then_admits_the_padded_lineup
    """
    scn = _widened_lineup_league(api)
    version = _match(scn, 1)["version"]

    duplicated = [
        f.slot(1, EntryType.REGULAR, scn.membership_ids[0]),
        f.slot(2, EntryType.REGULAR, scn.membership_ids[0]),
        f.vacancy_slot(3),
    ]
    validate_error(
        _submit_lineup(scn, 0, duplicated),
        ApiErrorId.ERR_DUPLICATE_BOWLER_IN_LINEUP.value,
    )
    _assert_no_slots_and_untouched_match(scn, version)

    duplicated_and_ineligible = [
        f.slot(1, EntryType.REGULAR, scn.membership_ids[0]),
        f.slot(2, EntryType.REGULAR, scn.membership_ids[0]),
        f.slot(3, EntryType.SUBSTITUTE, scn.membership_ids[_SWING]),
    ]
    validate_error(
        _submit_lineup(scn, 0, duplicated_and_ineligible),
        ApiErrorId.ERR_DUPLICATE_BOWLER_IN_LINEUP.value,
    )
    _assert_no_slots_and_untouched_match(scn, version)


def test_substitute_carried_on_the_opposing_team_is_ineligible(api: ApiClient):
    """A substitute must be a SANCTIONED membership of the league whose own team
    is either null or different from the opposing team.  Hal Swing is SANCTIONED
    and is carried with the SUBSTITUTE roster role, so the sanction gate and the
    roster gate both pass — but his team is the very side this match is played
    against, which is ERR_SUBSTITUTE_NOT_ELIGIBLE.

    Design: Corner/validations/corner_lineup_legality_family_rejects_then_admits_the_padded_lineup
    """
    scn = _widened_lineup_league(api)
    version = _match(scn, 1)["version"]

    match = _match(scn, 1)
    assert match["home_team_id"] == scn.team_ids[1], (
        "week two must be played with team two at home for the substitute to be "
        "carried on the opposing side"
    )
    assert_fields(
        _membership(scn, _SWING),
        sanction_status=SanctionStatus.SANCTIONED.value,
        roster_role=RosterRole.SUBSTITUTE.value,
        team_id=scn.team_ids[1],
    )

    slots = [
        f.slot(1, EntryType.REGULAR, scn.membership_ids[0]),
        f.slot(2, EntryType.SUBSTITUTE, scn.membership_ids[_SWING]),
        f.vacancy_slot(3),
    ]
    validate_error(
        _submit_lineup(scn, 0, slots),
        ApiErrorId.ERR_SUBSTITUTE_NOT_ELIGIBLE.value,
    )
    _assert_no_slots_and_untouched_match(scn, version)


def test_padded_lineup_freezes_a_handicap_for_a_bowler_who_does_not_exist(
    api: ApiClient,
):
    """The lineup that finally lands carries two bowlers and one vacancy.  Its
    frozen side handicap is the sum of the slots' own frozen values — 36 and 18
    for the two bowlers and 60 for the vacancy, which is priced at the adult
    percentage against ``vacancy_average`` and then capped — so the side's 114
    exceeds the team's own roster handicap of 54 by a bowler who does not exist.
    Only one side has submitted, so the match holds its SCHEDULED self-loop and
    the opposing side's frozen handicap stays 0.

    Design: Corner/validations/corner_lineup_legality_family_rejects_then_admits_the_padded_lineup
    """
    scn = _widened_lineup_league(api)
    version = _match(scn, 1)["version"]

    slots = fx.regular_slots(scn, (0, 1)) + [f.vacancy_slot(3)]
    data = validate_success(_submit_lineup(scn, 0, slots))
    assert_fields(
        data,
        status=MatchStatus.SCHEDULED.value,
        version=version + 1,
        away_team_handicap_per_game=114,
        home_team_handicap_per_game=0,
    )

    rows = _slots(scn, 1, team_index=0)
    assert len(rows) == 3, f"the submitting side must hold exactly 3 slots: {rows}"
    assert [row["position"] for row in rows] == [1, 2, 3]
    assert [row["handicap_per_game_applied"] for row in rows] == [36, 18, 60]
    assert [row["counts_toward_average"] for row in rows] == [True, True, False]
    assert [row["membership_id"] for row in rows] == [
        scn.membership_ids[0],
        scn.membership_ids[1],
        None,
    ]
    assert [row["entry_type"] for row in rows] == [
        EntryType.REGULAR.value,
        EntryType.REGULAR.value,
        EntryType.VACANCY.value,
    ]
    assert_fields(_team(scn, 0), team_handicap_per_game=54)


# ══════════════════════════════════════════════════════════
# Three referential gates on one honor-score filing
# ══════════════════════════════════════════════════════════

def _certified_week_and_a_second_league(api: ApiClient):
    """Week one certified in one league, plus a second FORMING league.

    The second league is chartered at the same centre with the same two
    officers, so nothing but the ``league_id`` in the body distinguishes it —
    which is what makes the cross-league gate the only rule broken.
    """
    scn = fx.build_certified_match(api)
    other = fx.charter_league(
        api,
        secretary_member_id=scn.secretary_member_id,
        treasurer_member_id=scn.treasurer_member_id,
        name="Thursday Trios Handicap",
    )
    slots = fx.slot_by_membership(scn, 0)
    return scn, other, slots


def _applications_of(scn: fx.Scenario, league_id: str):
    return validate_success(
        scn.api.list_award_applications(
            scn.secretary, params={"league_id": league_id, "limit": 100}
        )
    )


def test_forbidden_claimed_game_number_is_refused_before_the_referential_gates(
    api: ApiClient,
):
    """A series award computes its pins from the whole series, so naming a single
    game is a conditional-input violation in the forbidding direction and the
    shape check owns it.  The very same body also names the wrong league and
    another bowler's slot, yet the answer is ERR_INVALID_REQUEST at 400 — the
    shape gate is consulted before either referential rule.

    Design: Corner/validations/corner_award_application_referential_gates_run_shape_then_league_then_relationship
    """
    scn, other, slots = _certified_week_and_a_second_league(api)
    foreign_slot = slots[scn.membership_ids[0]]

    response = scn.api.create_award_application(
        f.award_application_payload(
            other.league_id,
            scn.membership_ids[1],
            foreign_slot["id"],
            AwardType.HANDICAP_SERIES_700,
            claimed_game_number=2,
        ),
        scn.bowler(1),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert _applications_of(scn, scn.league_id) == []
    assert _applications_of(scn, other.league_id) == []


def test_foreign_league_is_refused_before_the_relationship_gate(api: ApiClient):
    """With the forbidden field dropped the shape gate is satisfied and the next
    rule speaks: every entity a request references together must belong to one
    league.  The membership and the slot both belong to the first league while
    the body names the second, which is ERR_CROSS_LEAGUE_REFERENCE — reported in
    preference to the relationship mismatch the same body still carries.

    Design: Corner/validations/corner_award_application_referential_gates_run_shape_then_league_then_relationship
    """
    scn, other, slots = _certified_week_and_a_second_league(api)
    foreign_slot = slots[scn.membership_ids[0]]

    response = scn.api.create_award_application(
        f.award_application_payload(
            other.league_id,
            scn.membership_ids[1],
            foreign_slot["id"],
            AwardType.HANDICAP_SERIES_700,
        ),
        scn.bowler(1),
    )
    validate_error(response, ApiErrorId.ERR_CROSS_LEAGUE_REFERENCE.value)
    assert _applications_of(scn, scn.league_id) == []
    assert _applications_of(scn, other.league_id) == []


def test_another_bowlers_slot_is_refused_by_the_relationship_gate(api: ApiClient):
    """Once the league agrees, the last referential rule compares the rows to one
    another: the cited slot's own membership must be the membership filing the
    claim.  Filing on a team-mate's slot is ERR_REFERENCE_MISMATCH, and it is
    reported even though that slot's series would comfortably have cleared its
    own threshold for its own owner.

    Design: Corner/validations/corner_award_application_referential_gates_run_shape_then_league_then_relationship
    """
    scn, _other, slots = _certified_week_and_a_second_league(api)
    foreign_slot = slots[scn.membership_ids[0]]

    response = scn.api.create_award_application(
        f.award_application_payload(
            scn.league_id,
            scn.membership_ids[1],
            foreign_slot["id"],
            AwardType.HANDICAP_SERIES_700,
        ),
        scn.bowler(1),
    )
    validate_error(response, ApiErrorId.ERR_REFERENCE_MISMATCH.value)
    assert _applications_of(scn, scn.league_id) == []


def test_handicap_series_claim_is_priced_from_the_slot_not_the_bowler(api: ApiClient):
    """The filing that lands names the bowler's own slot, and its arithmetic is
    the point: a handicap series is the slot's scratch series plus three times
    the handicap frozen onto that slot at lineup submission — 720 plus three
    times 22, so 786 against a floor of 700 — and not three times the 18 the same
    bowler carries now that week one has moved his average.  Both evidence flags
    are captured true, the forbidden field reads null, no verifier is recorded
    yet, and the stored figure survives a later read unchanged.

    Design: Corner/validations/corner_award_application_referential_gates_run_shape_then_league_then_relationship
    """
    scn, _other, slots = _certified_week_and_a_second_league(api)
    own_slot = slots[scn.membership_ids[1]]
    assert own_slot["scratch_series"] == 720
    assert own_slot["handicap_per_game_applied"] == 22
    assert_fields(_membership(scn, 1), handicap_per_game=18, current_average=199)

    data = validate_success(
        scn.api.create_award_application(
            f.award_application_payload(
                scn.league_id,
                scn.membership_ids[1],
                own_slot["id"],
                AwardType.HANDICAP_SERIES_700,
                evidence_note="Score sheet and lineup card attached.",
            ),
            scn.bowler(1),
        ),
        201,
    )
    assert_fields(
        data,
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=1,
        league_id=scn.league_id,
        membership_id=scn.membership_ids[1],
        series_entry_id=own_slot["id"],
        award_type=AwardType.HANDICAP_SERIES_700.value,
        claimed_pins=786,
        claimed_game_number=None,
        verified_by_user_id=None,
        lane_certification_verified=True,
        sanctioned_at_game_time=True,
    )

    reread = validate_success(scn.api.get_award_application(data["id"], scn.officer))
    assert_fields(
        reread,
        claimed_pins=786,
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=1,
    )


# ══════════════════════════════════════════════════════════
# A pair that reads CERTIFIED and still cannot host the match
# ══════════════════════════════════════════════════════════

# The pair's certification runs out the day *before* week one is bowled.
_SHORT_CERTIFIED_THROUGH = "2026-08-11T00:00:00Z"
# A moment while that certification is still live …
_WHILE_STILL_CERTIFIED = "2026-08-10T12:00:00Z"
# … and a moment strictly after it, where the derived status flips on its own.
_ONCE_EXPIRED = "2026-08-11T12:00:00Z"


def _match_on_a_pair_expiring_first(api: ApiClient) -> fx.Scenario:
    """A sanctioned league with week one's lineups in, on a short-lived pair."""
    scn = fx.build_sanctioned_league(
        api, lane_pairs=((1, _SHORT_CERTIFIED_THROUGH),)
    )
    fx.submit_both_lineups(scn, 0)
    return scn


def test_certified_pair_whose_cover_ends_before_the_match_blocks_the_open(
    api: ApiClient,
):
    """Two distinct rules guard the open.  One asks whether the pair reads
    CERTIFIED right now, and it is satisfied: the clock has not passed
    ``certified_through``, so the derived status is CERTIFIED with no revocation.
    The other compares the cover against the match's own start, and it fails —
    2026-08-11 falls short of a match starting 2026-08-12 — so the answer is
    ERR_LANE_CERTIFICATION_EXPIRED rather than ERR_LANE_PAIR_NOT_CERTIFIED.  The
    refusal moves neither the match nor the league.

    Design: Corner/validations/corner_lane_certified_today_but_expiring_before_the_match_blocks_the_open
    """
    scn = _match_on_a_pair_expiring_first(api)
    fx.set_clock(api, _WHILE_STILL_CERTIFIED)

    pair = _lane_pair(scn)
    assert_fields(
        pair,
        certification_status=LanePairCertificationStatus.CERTIFIED.value,
        revoked_at=None,
    )
    assert_instant_equals(
        pair["certified_through"], _SHORT_CERTIFIED_THROUGH, "certified_through"
    )

    validate_error(
        scn.api.open_match(scn.match_ids[0], {}, scn.secretary),
        ApiErrorId.ERR_LANE_CERTIFICATION_EXPIRED.value,
    )
    assert_fields(
        _match(scn, 0),
        status=MatchStatus.LINEUPS_SUBMITTED.value,
        home_team_handicap_per_game=58,
        away_team_handicap_per_game=99,
    )
    assert_fields(_league(scn), status=LeagueStatus.SANCTIONED.value)


def test_recertifying_to_exactly_the_start_instant_clears_both_boundaries(
    api: ApiClient,
):
    """Left alone, the pair slides to EXPIRED the moment the clock moves strictly
    past its cover — no request is addressed to it.  An officer recertifies it to
    exactly the match's start instant, which is strictly later than the clock as
    the recertification requires, and resets ``last_certified_at`` to now.  At the
    start instant itself the pair still reads CERTIFIED, because expiry needs the
    clock strictly past the cover, and the open succeeds because the cover being
    equal to ``starts_at`` satisfies the second rule too: both boundaries are
    inclusive.  The open also carries the league into its season, and the
    handicaps frozen at lineup submission are untouched throughout.

    Design: Corner/validations/corner_lane_certified_today_but_expiring_before_the_match_blocks_the_open
    """
    scn = _match_on_a_pair_expiring_first(api)
    fx.set_clock(api, _ONCE_EXPIRED)
    assert_fields(
        _lane_pair(scn),
        certification_status=LanePairCertificationStatus.EXPIRED.value,
        revoked_at=None,
    )

    recertified = validate_success(
        scn.api.set_lane_pair_certification(
            scn.lane_pair_ids[0], f.recertify_payload(WEEK1_STARTS_AT), scn.officer
        )
    )
    assert_fields(
        recertified,
        certification_status=LanePairCertificationStatus.CERTIFIED.value,
        revoked_at=None,
    )
    assert_instant_equals(
        recertified["certified_through"], WEEK1_STARTS_AT, "certified_through"
    )
    assert_instant_equals(
        recertified["last_certified_at"], _ONCE_EXPIRED, "last_certified_at"
    )

    fx.set_clock(api, WEEK1_STARTS_AT)
    assert_fields(
        _lane_pair(scn),
        certification_status=LanePairCertificationStatus.CERTIFIED.value,
    )

    opened = validate_success(scn.api.open_match(scn.match_ids[0], {}, scn.secretary))
    assert_fields(
        opened,
        status=MatchStatus.OPEN.value,
        home_team_handicap_per_game=58,
        away_team_handicap_per_game=99,
    )
    assert_fields(_league(scn), status=LeagueStatus.IN_SEASON.value)


# ══════════════════════════════════════════════════════════
# A refused score set leaves every slot exactly as it was
# ══════════════════════════════════════════════════════════

def _unscored_slots(scn: fx.Scenario):
    """Every slot of week one, keyed by the membership it names."""
    return {
        row["membership_id"]: row
        for row in _slots(scn, 0)
        if row.get("membership_id")
    }


def _assert_nothing_recorded(scn: fx.Scenario) -> None:
    """All four bowling slots still hold no pins, and the match has not moved."""
    rows = _slots(scn, 0)
    assert len(rows) == 4, f"week one must hold exactly 4 slots: {rows}"
    for row in rows:
        assert_fields(
            row,
            games_recorded=0,
            scratch_series=0,
            game1_pins=None,
            game2_pins=None,
            game3_pins=None,
            certified=False,
        )
    match = _match(scn, 0)
    assert_fields(match, status=MatchStatus.OPEN.value)
    assert_points(match["home_points"], 0.0, "home_points")
    assert_points(match["away_points"], 0.0, "away_points")


def _score_entries(scn: fx.Scenario, pins):
    by_membership = _unscored_slots(scn)
    return [
        f.score_entry(by_membership[scn.membership_ids[index]]["id"], *games)
        for index, games in pins
    ]


def test_out_of_range_or_incomplete_score_sets_are_refused_whole(api: ApiClient):
    """Three different malformed sets are all refused as ERR_SCORE_SET_INVALID: a
    pin count above 300, a bowling slot left holding only two of its three games,
    and a set that omits one of the four slots that had to appear.  Every refusal
    is total — after all three, all four slots still read no games recorded, no
    scratch series and three null game fields, and the match holds OPEN with both
    sides on no points, so nothing was written and then rolled back part-way.

    Design: Corner/validations/corner_score_set_rejections_leave_every_slot_untouched
    """
    scn = fx.build_open_match(api)
    _assert_nothing_recorded(scn)

    over_the_top = _score_entries(
        scn,
        [(0, (170, 180, 301)), (1, (230, 240, 250)), (2, (150, 160, 170)),
         (3, (140, 150, 160))],
    )
    validate_error(
        scn.api.record_scores(
            scn.match_ids[0], f.scores_payload(over_the_top), scn.secretary
        ),
        ApiErrorId.ERR_SCORE_SET_INVALID.value,
    )
    _assert_nothing_recorded(scn)

    only_two_games = _score_entries(
        scn,
        [(0, (170, 180, 190)), (1, (230, 240, None)), (2, (150, 160, 170)),
         (3, (140, 150, 160))],
    )
    validate_error(
        scn.api.record_scores(
            scn.match_ids[0], f.scores_payload(only_two_games), scn.secretary
        ),
        ApiErrorId.ERR_SCORE_SET_INVALID.value,
    )
    _assert_nothing_recorded(scn)

    one_slot_missing = _score_entries(
        scn,
        [(0, (170, 180, 190)), (1, (230, 240, 250)), (2, (150, 160, 170))],
    )
    validate_error(
        scn.api.record_scores(
            scn.match_ids[0], f.scores_payload(one_slot_missing), scn.secretary
        ),
        ApiErrorId.ERR_SCORE_SET_INVALID.value,
    )
    _assert_nothing_recorded(scn)


def test_negative_pin_count_is_caught_by_the_shape_gate(api: ApiClient):
    """A negative pin count is not a range violation of the scoring rule but a
    malformed request: the shape gate requires pin counts to be non-negative and
    is consulted far earlier, so the answer is ERR_INVALID_REQUEST at 400 rather
    than ERR_SCORE_SET_INVALID at 422.  Nothing is written here either.

    Design: Corner/validations/corner_score_set_rejections_leave_every_slot_untouched
    """
    scn = fx.build_open_match(api)

    below_zero = _score_entries(
        scn,
        [(0, (170, -5, 190)), (1, (230, 240, 250)), (2, (150, 160, 170)),
         (3, (140, 150, 160))],
    )
    validate_error(
        scn.api.record_scores(
            scn.match_ids[0], f.scores_payload(below_zero), scn.secretary
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    _assert_nothing_recorded(scn)


def test_exactly_three_hundred_is_accepted_and_certifies_nothing(api: ApiClient):
    """The upper bound of the pin range is inclusive, so a perfect game lands.
    Points follow the four-point scheme from the pins plus each side's *frozen*
    team handicap: 458 to 389, 478 to 409 and 608 to 429 game by game, and 1544
    to 1227 on the series, so the home side takes all four points.  Score entry
    certifies nothing, so the slot reads three games recorded and a scratch
    series of 650 with its certified flag still false, and the bowler's average
    has not moved off the record it entered with.

    Design: Corner/validations/corner_score_set_rejections_leave_every_slot_untouched
    """
    scn = fx.build_open_match(api)
    perfect_third_game = _score_entries(
        scn,
        [(0, (170, 180, 300)), (1, (230, 240, 250)), (2, (150, 160, 170)),
         (3, (140, 150, 160))],
    )
    slot_id = _unscored_slots(scn)[scn.membership_ids[0]]["id"]

    data = validate_success(
        scn.api.record_scores(
            scn.match_ids[0], f.scores_payload(perfect_third_game), scn.secretary
        )
    )
    assert_fields(data, status=MatchStatus.SCORES_ENTERED.value)
    assert_points(data["home_points"], 4.0, "home_points")
    assert_points(data["away_points"], 0.0, "away_points")

    slot = validate_success(scn.api.get_series_entry(slot_id, scn.secretary))
    assert_fields(
        slot,
        games_recorded=3,
        scratch_series=650,
        game1_pins=170,
        game2_pins=180,
        game3_pins=300,
        certified=False,
    )
    assert_fields(
        _membership(scn, 0),
        certified_games=0,
        certified_pins=0,
        current_average=180,
        handicap_per_game=36,
    )


# ══════════════════════════════════════════════════════════
# Schedule adoption: team coverage, distinct sides, DRAFT matches
# ══════════════════════════════════════════════════════════

def _league_with_a_spare_team(api: ApiClient) -> fx.Scenario:
    """BYLAWS_ADOPTED, no schedule, and one team more than was declared.

    Entering a third team is legal at this status, and nothing about the extra
    team is itself an error — it only makes both directions of the coverage rule
    reachable from the same league.
    """
    scn = fx.build_league(api, with_schedule=False)
    fx.add_team(scn, "Split Enders")
    return scn


def _adopt(scn: fx.Scenario, total_weeks: int, matches):
    return scn.api.adopt_schedule(
        scn.league_id, f.schedule_payload(total_weeks, matches), scn.secretary
    )


def _matches_of(scn: fx.Scenario, **filters):
    params = {"league_id": scn.league_id, "limit": 100}
    params.update(filters)
    return validate_success(scn.api.list_matches(scn.secretary, params=params))


def test_a_team_scheduled_against_itself_is_a_coverage_failure(api: ApiClient):
    """The two sides of a match must be different teams, and a schedule that
    names one team on both sides of its only match therefore references a single
    distinct team where the league declared two.  Both readings land on the same
    code, ERR_TEAM_COUNT_MISMATCH, and the refusal is whole: no match row of the
    request survives and the league's declared length is still unwritten.

    Design: Corner/validations/corner_schedule_adoption_rejects_wrong_team_counts_then_creates_draft_matches
    """
    scn = _league_with_a_spare_team(api)

    validate_error(
        _adopt(
            scn,
            1,
            [
                f.schedule_match(
                    1, scn.team_ids[0], scn.team_ids[0], scn.lane_pair_ids[0],
                    WEEK1_STARTS_AT, WEEK1_ENDS_AT,
                )
            ],
        ),
        ApiErrorId.ERR_TEAM_COUNT_MISMATCH.value,
    )
    assert _matches_of(scn) == [], "a refused schedule created match rows"
    assert_fields(
        _league(scn), total_weeks=0, status=LeagueStatus.BYLAWS_ADOPTED.value
    )


def test_one_team_too_many_across_the_season_is_the_same_refusal(api: ApiClient):
    """Coverage is counted over the whole schedule, not match by match: two
    perfectly well-formed matches that between them name three distinct teams
    against a declared count of two are refused with ERR_TEAM_COUNT_MISMATCH.
    The two lane-pair windows are a week apart, so no occupation conflict is in
    play, and again nothing is written — not even the first, unobjectionable week.

    Design: Corner/validations/corner_schedule_adoption_rejects_wrong_team_counts_then_creates_draft_matches
    """
    scn = _league_with_a_spare_team(api)

    validate_error(
        _adopt(
            scn,
            2,
            [
                f.schedule_match(
                    1, scn.team_ids[0], scn.team_ids[1], scn.lane_pair_ids[0],
                    WEEK1_STARTS_AT, WEEK1_ENDS_AT,
                ),
                f.schedule_match(
                    2, scn.team_ids[2], scn.team_ids[0], scn.lane_pair_ids[0],
                    WEEK2_STARTS_AT, WEEK2_ENDS_AT,
                ),
            ],
        ),
        ApiErrorId.ERR_TEAM_COUNT_MISMATCH.value,
    )
    assert _matches_of(scn) == [], "a refused schedule created match rows"
    assert_fields(_league(scn), total_weeks=0)


def test_accepted_schedule_creates_draft_matches_and_leaves_the_spare_team(
    api: ApiClient,
):
    """A schedule covering exactly the declared two teams is adopted at 201.  Its
    matches are created at DRAFT rather than SCHEDULED, because the promotion to
    SCHEDULED is the sanctioning cascade's work and this league has not been
    sanctioned; each carries no points, no frozen handicap and no certification.
    Adoption writes the league's ``total_weeks`` but is not itself a league
    transition, and the third team is left alone at PROVISIONAL — the accepted
    schedule neither uses nor deletes it.

    Design: Corner/validations/corner_schedule_adoption_rejects_wrong_team_counts_then_creates_draft_matches
    """
    scn = _league_with_a_spare_team(api)

    validate_success(
        _adopt(
            scn,
            2,
            [
                f.schedule_match(
                    1, scn.team_ids[0], scn.team_ids[1], scn.lane_pair_ids[0],
                    WEEK1_STARTS_AT, WEEK1_ENDS_AT,
                ),
                f.schedule_match(
                    2, scn.team_ids[1], scn.team_ids[0], scn.lane_pair_ids[0],
                    WEEK2_STARTS_AT, WEEK2_ENDS_AT,
                ),
            ],
        ),
        201,
    )

    rows = _matches_of(scn)
    assert len(rows) == 2, f"the adopted schedule must hold exactly 2 matches: {rows}"
    for row in rows:
        assert_fields(
            row,
            status=MatchStatus.DRAFT.value,
            home_team_handicap_per_game=0,
            away_team_handicap_per_game=0,
            certified_at=None,
            lane_pair_id=scn.lane_pair_ids[0],
        )
        assert_points(row["home_points"], 0.0, "home_points")
        assert_points(row["away_points"], 0.0, "away_points")

    week_one = _matches_of(scn, week_number=1)
    week_two = _matches_of(scn, week_number=2)
    assert len(week_one) == 1 and len(week_two) == 1
    assert_fields(
        week_one[0], home_team_id=scn.team_ids[0], away_team_id=scn.team_ids[1]
    )
    assert_instant_equals(week_one[0]["starts_at"], WEEK1_STARTS_AT, "starts_at")
    assert_fields(
        week_two[0], home_team_id=scn.team_ids[1], away_team_id=scn.team_ids[0]
    )
    assert_instant_equals(week_two[0]["starts_at"], WEEK2_STARTS_AT, "starts_at")

    assert_fields(
        _league(scn), total_weeks=2, status=LeagueStatus.BYLAWS_ADOPTED.value
    )

    teams = validate_success(
        scn.api.list_league_teams(scn.league_id, scn.secretary, params={"limit": 100})
    )
    assert_ids_in_order(teams, scn.team_ids)
    assert_ordered_by(teams, "created_at")
    for team in teams:
        assert_fields(team, status=TeamStatus.PROVISIONAL.value)


# ══════════════════════════════════════════════════════════
# One membership per member, one live remittance listing
# ══════════════════════════════════════════════════════════

_FIFTH = 4  # Gus Sub, the one bowler left off the submitted remittance

_ROSTER_WITH_A_SPARE = list(fx.DEFAULT_ROSTER) + [
    fx.RosterSpec("Gus Sub", MemberClass.ADULT, 150, 30, 0)
]


def _league_with_a_submitted_remittance(api: ApiClient):
    """Five memberships, four of them already invoiced on a submitted filing.

    The fifth is deliberately left off, so the league carries one membership on
    each side of the money axis: four INVOICED and one still UNPAID.
    """
    scn = fx.build_league(api, roster=_ROSTER_WITH_A_SPARE)
    invoiced = scn.membership_ids[:4]
    remittance_id = fx.open_remittance(scn, invoiced)
    fx.submit_remittance(scn, remittance_id)
    return scn, remittance_id


def _draft_remittance(scn: fx.Scenario, membership_indexes):
    ids = [scn.membership_ids[index] for index in membership_indexes]
    return scn.api.create_fee_remittance(
        f.fee_remittance_payload(
            scn.league_id, ids, fx.expected_remittance_cents(scn, ids)
        ),
        scn.treasurer,
    )


def test_a_member_holds_at_most_one_membership_per_league(api: ApiClient):
    """A second enrolment for a member who already holds a membership in this
    league is ERR_DUPLICATE_MEMBERSHIP, and neither a different team nor the
    SUBSTITUTE roster role makes it legal — the uniqueness is on the member and
    the league alone.  The listing still counts five memberships, so the refusal
    created nothing.

    Design: Corner/validations/corner_one_membership_per_league_and_one_live_remittance_listing
    """
    scn, _remittance_id = _league_with_a_submitted_remittance(api)

    validate_error(
        scn.api.create_membership(
            f.membership_payload(
                scn.league_id,
                scn.member_ids[0],
                team_id=scn.team_ids[1],
                roster_role=RosterRole.SUBSTITUTE,
                prior_season_average=150,
                prior_season_games=30,
            ),
            scn.secretary,
        ),
        ApiErrorId.ERR_DUPLICATE_MEMBERSHIP.value,
    )

    rows, meta = validate_paginated(
        scn.api.list_memberships(
            scn.secretary, params={"league_id": scn.league_id, "limit": 10}
        )
    )
    assert meta["total_count"] == 5, f"the refusal changed the roster: {meta}"
    assert len(rows) == 5


def test_a_membership_on_an_unsubmitted_draft_is_already_spoken_for(api: ApiClient):
    """A draft remittance prices nothing — no computed amount, no penalty, just
    the count of the memberships listed — and invoices nobody, so the bowler it
    names still reads UNSANCTIONED and UNPAID.  That leaves the money axis wide
    open, and yet a second remittance naming the same bowler is refused with
    ERR_DUPLICATE_MEMBERSHIP: a DRAFT filing is not a rejected one, so the
    membership is already listed on a live remittance.

    Design: Corner/validations/corner_one_membership_per_league_and_one_live_remittance_listing
    """
    scn, _remittance_id = _league_with_a_submitted_remittance(api)

    draft = validate_success(_draft_remittance(scn, [_FIFTH]), 201)
    assert_fields(
        draft, status=FeeRemittanceStatus.DRAFT.value, member_count=1
    )
    assert_cents(draft["computed_amount_cents"], 0, "computed_amount_cents")
    assert_cents(draft["penalty_cents"], 0, "penalty_cents")
    assert_cents(
        draft["declared_amount_cents"], 3100, "declared_amount_cents"
    )
    assert_membership_axes(
        _membership(scn, _FIFTH),
        SanctionStatus.UNSANCTIONED,
        MembershipRemittanceStatus.UNPAID,
    )

    validate_error(
        _draft_remittance(scn, [_FIFTH]),
        ApiErrorId.ERR_DUPLICATE_MEMBERSHIP.value,
    )


def test_invoiced_membership_is_stopped_one_rule_before_the_duplicate_check(
    api: ApiClient,
):
    """A membership carried on a submitted filing is INVOICED, and drafting a
    remittance requires a membership whose two axes admit the operation.  That
    state rule is consulted before the uniqueness rule the same request also
    breaks, so the answer is ERR_MEMBERSHIP_STATE_INVALID at 409 rather than
    ERR_DUPLICATE_MEMBERSHIP at 422.

    Design: Corner/validations/corner_one_membership_per_league_and_one_live_remittance_listing
    """
    scn, _remittance_id = _league_with_a_submitted_remittance(api)
    assert_membership_axes(
        _membership(scn, 0),
        SanctionStatus.PENDING_REMITTANCE,
        MembershipRemittanceStatus.INVOICED,
    )

    validate_error(
        _draft_remittance(scn, [0]),
        ApiErrorId.ERR_MEMBERSHIP_STATE_INVALID.value,
    )


def test_a_national_rejection_releases_both_gates_at_once(api: ApiClient):
    """The rejection runs only the inverse of the membership hop: the four listed
    bowlers fall back to UNSANCTIONED on the sanction axis and REFUNDED on the
    money axis with their handicaps forced to 0, while the prior-season record and
    the entering average they were enrolled with are untouched.  That single act
    releases both gates — REFUNDED admits the drafting operation, and a REJECTED
    remittance is excluded from the live-listing count — so a fresh draft naming
    two of those bowlers is accepted.  The two refusals along the way left no row
    behind: the league holds exactly the three remittances that were created.

    Design: Corner/validations/corner_one_membership_per_league_and_one_live_remittance_listing
    """
    scn, remittance_id = _league_with_a_submitted_remittance(api)
    first_draft = validate_success(_draft_remittance(scn, [_FIFTH]), 201)
    validate_error(
        _draft_remittance(scn, [0]), ApiErrorId.ERR_MEMBERSHIP_STATE_INVALID.value
    )

    rejected = validate_success(
        scn.api.record_national_decision(
            remittance_id,
            f.national_reject_payload("Two member numbers illegible on the filing."),
            scn.officer,
        )
    )
    assert_fields(rejected, status=FeeRemittanceStatus.REJECTED.value)

    for index in range(4):
        membership = _membership(scn, index)
        assert_membership_axes(
            membership,
            SanctionStatus.UNSANCTIONED,
            MembershipRemittanceStatus.REFUNDED,
        )
        assert_fields(membership, handicap_per_game=0)
    assert_fields(
        _membership(scn, 0),
        entering_average=180,
        prior_season_average=180,
        prior_season_games=30,
        certified_games=0,
    )

    second_draft = validate_success(_draft_remittance(scn, [0, 1]), 201)
    assert_fields(
        second_draft, status=FeeRemittanceStatus.DRAFT.value, member_count=2
    )
    assert_cents(
        second_draft["declared_amount_cents"], 6200, "declared_amount_cents"
    )

    rows, meta = validate_paginated(
        scn.api.list_fee_remittances(
            scn.treasurer, params={"league_id": scn.league_id, "limit": 10}
        )
    )
    assert meta["total_count"] == 3, f"a refusal created a remittance row: {meta}"
    assert_ids_in_order(rows, [remittance_id, first_draft["id"], second_draft["id"]])
    assert [row["status"] for row in rows] == [
        FeeRemittanceStatus.REJECTED.value,
        FeeRemittanceStatus.DRAFT.value,
        FeeRemittanceStatus.DRAFT.value,
    ]
