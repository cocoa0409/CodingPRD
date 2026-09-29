"""Access control, concurrency tokens and the immediate-consistency contract.

Three families of corner live here.  The first is the role and binding surface
of PRD §2.1 read through the refusal order of §2.6: an endpoint's role list is
consulted at check 2, long before any state, officer-binding or money check, and
the officer and owner bindings of checks 6, 7 and 8 are per *resource* rather
than per role, so the very same principal is refused on one league and obeyed on
another.  The second is the optimistic-concurrency surface of §2.5: exactly three
endpoints take a version echo, each refuses a token its own resource has already
moved past, and a refused write is provably inert.  The third is the consistency
model of §2.9 and §3.7: every derived figure is final in the response that caused
it, so the next request never sees a stale average, counter or money triple.

Nothing here asserts a value the PRD does not pin.  Bowling arithmetic truncates
and handicaps floor before they cap (§2.8); the prize reserve floors while the
administrative fee rounds half up (§3.7); money is integer cents and instants
carry an explicit UTC offset (§2.8, §2.4).
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing.constants import NON_EXISTENT_UUID
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
    assert_prize_money_invariant,
    expected_admin_fee_cents,
    expected_reserve_cents,
)
from test_helpers.constants import (
    BASE_BYLAWS,
    RESERVE_TIER_THRESHOLD_CENTS,
    WEEK1_STARTS_AT,
)
from test_helpers.fixtures import RosterSpec, Scenario
from test_helpers.types import (
    AverageStatus,
    AwardApplicationStatus,
    AwardType,
    BasisVariant,
    LeagueStatus,
    LeagueVerificationDecision,
    MatchStatus,
    MemberClass,
    PrizeFundStatus,
    ProtestCategory,
    ProtestDecision,
    ProtestStatus,
    Remedy,
)

# The shared bylaws split a 1200-cent weekly due into 700 cents of prize share
# and 500 cents of league expense (PRD §3.7).
PRIZE_SHARE_CENTS = BASE_BYLAWS["weekly_dues_cents"] - BASE_BYLAWS["weekly_expense_cents"]
EXPENSE_SHARE_CENTS = BASE_BYLAWS["weekly_expense_cents"]

# A dues tender that is neither the bylaw amount nor a negative number, used to
# prove that the ownership check of §2.6 outranks the amount check.
WRONG_TENDER_CENTS = 900

# The reserve-tier scenario needs a settled amount and a projection that land on
# either side of the 100000-cent threshold using nothing but legal bylaws: the
# weekly dues ceiling is 10000 cents (§3.1) and the whole due is prize share
# when the expense share is zero.
TIER_DUES_CENTS = 10_000
TIER_BYLAWS: Dict[str, Any] = {
    "weekly_dues_cents": TIER_DUES_CENTS,
    "weekly_expense_cents": 0,
}
# Five sanctioned bowlers, so one remaining week projects 5 * 10000 = 50000 on
# top of the 50000 already settled — exactly the threshold, to the cent.
TIER_ROSTER: Tuple[RosterSpec, ...] = (
    RosterSpec("Cara Captain", MemberClass.ADULT, 180, 30, 0),
    RosterSpec("Dan Bowler", MemberClass.ADULT, 195, 30, 0),
    RosterSpec("Eve Captain", MemberClass.ADULT, 170, 30, 1),
    RosterSpec("Fay Bowler", MemberClass.ADULT, 160, 30, 1),
    RosterSpec("Gus Reserve", MemberClass.ADULT, 175, 30, 0),
)
TIER_SETTLED_CENTS = len(TIER_ROSTER) * TIER_DUES_CENTS

# The duty-segregation scenario: the league's secretary is also a bowler on the
# home side, so three bowlers are enrolled by the roster and the secretary's own
# membership is added afterwards, landing at membership index 3.
SEGREGATION_ROSTER: Tuple[RosterSpec, ...] = (
    RosterSpec("Cara Captain", MemberClass.ADULT, 180, 30, 0),
    RosterSpec("Eve Captain", MemberClass.ADULT, 170, 30, 1),
    RosterSpec("Fay Bowler", MemberClass.ADULT, 160, 30, 1),
)
SECRETARY_MEMBERSHIP_INDEX = 3
# The secretary bowls 230, 240 and 250 for a 720 scratch series, which with the
# 22-pin handicap frozen onto his slot claims 720 + 3 * 22 = 786 handicap pins.
SEGREGATION_PINS: Dict[int, Tuple[int, int, int]] = {
    0: (170, 180, 190),
    1: (150, 160, 170),
    2: (140, 150, 160),
    3: (230, 240, 250),
}
SECRETARY_SCRATCH_SERIES = 720
SECRETARY_SLOT_HANDICAP = 22
SECRETARY_CLAIMED_PINS = SECRETARY_SCRATCH_SERIES + 3 * SECRETARY_SLOT_HANDICAP


# ══════════════════════════════════════════════════════════════════════════
# Local helpers.  The shared builders cover every layered world this module
# needs except two, and neither belongs in shared infrastructure.
# ══════════════════════════════════════════════════════════════════════════

def _enrol_existing_member(
    scn: Scenario,
    member_id: str,
    *,
    team_index: int,
    prior_season_average: Optional[int],
    prior_season_games: int,
) -> str:
    """Enrol a member who was registered before the league was chartered.

    The shared roster builder registers a fresh person per specification, which
    cannot express a league officer who is also one of its bowlers: the officer
    binding is supplied at chartering and therefore has to exist first.
    """
    data = validate_success(
        scn.api.create_membership(
            f.membership_payload(
                scn.league_id,
                member_id,
                team_id=scn.team_ids[team_index],
                prior_season_average=prior_season_average,
                prior_season_games=prior_season_games,
            ),
            scn.secretary,
        ),
        201,
    )
    scn.member_ids.append(member_id)
    scn.member_classes.append(MemberClass.ADULT)
    scn.membership_ids.append(data["id"])
    scn.membership_teams.append(team_index)
    return data["id"]


def _league_where_the_secretary_also_bowls(api: ApiClient) -> Scenario:
    """A league IN_SEASON whose ``secretary_member_id`` holds a certified slot.

    Week one is bowled and certified, the secretary's own series is honor-score
    material, and the logical clock sits on the certification instant, well
    inside both the 72-hour protest and 168-hour honor-score windows.
    """
    secretary_member_id = fx.register_member(api, "Dan Bowler", MemberClass.ADULT)
    scn = fx.build_league(
        api, roster=SEGREGATION_ROSTER, secretary_member_id=secretary_member_id
    )
    _enrol_existing_member(
        scn,
        secretary_member_id,
        team_index=0,
        prior_season_average=195,
        prior_season_games=30,
    )
    fx.sanction(scn)
    fx.submit_both_lineups(
        scn,
        0,
        home_membership_indexes=(0, SECRETARY_MEMBERSHIP_INDEX),
        away_membership_indexes=(1, 2),
    )
    fx.set_clock(api, WEEK1_STARTS_AT)
    fx.open_match(scn, 0)
    fx.enter_scores(scn, fx.score_entries_for(scn, 0, SEGREGATION_PINS), 0)
    fx.certify_match(scn, 0)
    return scn


def _tier_league(api: ApiClient) -> Scenario:
    """A league IN_SEASON with week one certified and week one's dues settled.

    Five sanctioned bowlers each tender the 10000-cent weekly due against a zero
    expense share, so the settled prize amount is exactly 50000 cents and one
    week of the two-week season remains unsettled.
    """
    scn = fx.build_certified_match(api, bylaws=TIER_BYLAWS, roster=TIER_ROSTER)
    fx.pay_dues_for_all(scn, 1)
    return scn


def _league_in_season_with_a_stale_token(api: ApiClient) -> Tuple[Scenario, int]:
    """A league IN_SEASON plus the version its client last saw at adoption.

    Sanctioning and opening week one both mutate the league row, so the token the
    client still holds from bylaw adoption is two cascades out of date while the
    league's status still admits an amendment.
    """
    scn = fx.build_league(api)
    stale_version = scn.league_version()
    fx.sanction(scn)
    fx.submit_both_lineups(scn, 0)
    fx.set_clock(api, WEEK1_STARTS_AT)
    fx.open_match(scn, 0)
    return scn, stale_version


def _assert_bylaws_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """All eighteen bylaw values stand exactly where they stood."""
    drifted = {
        key: (before.get(key), after.get(key))
        for key in BASE_BYLAWS
        if before.get(key) != after.get(key)
    }
    assert not drifted, f"a refused amendment moved bylaws: {drifted}"


def _slot_shape(rows: Sequence[Dict[str, Any]]) -> List[Tuple[Any, ...]]:
    """The identity of every lineup slot, in listing order."""
    return [
        (
            row["id"],
            row["position"],
            row["membership_id"],
            row["entry_type"],
            row["handicap_per_game_applied"],
        )
        for row in rows
    ]


def _slot_of(scn: Scenario, membership_index: int, match_index: int = 0) -> Dict[str, Any]:
    return fx.slot_by_membership(scn, match_index)[scn.membership_ids[membership_index]]


def _membership(scn: Scenario, index: int) -> Dict[str, Any]:
    return validate_success(
        scn.api.get_membership(scn.membership_ids[index], scn.secretary), 200
    )


def _league_of(scn: Scenario) -> Dict[str, Any]:
    return validate_success(scn.api.get_league(scn.league_id, scn.secretary), 200)


def _match_of(scn: Scenario, index: int = 0) -> Dict[str, Any]:
    return validate_success(
        scn.api.get_match(scn.match_ids[index], scn.secretary), 200
    )


def _fund_of(scn: Scenario) -> Dict[str, Any]:
    return validate_success(
        scn.api.get_prize_fund(scn.prize_fund_id(), scn.secretary), 200
    )


# ══════════════════════════════════════════════════════════════════════════
# The role list is consulted at check 2, before every state and money check
# ══════════════════════════════════════════════════════════════════════════

def test_member_registration_refuses_the_league_secretary(forming_league: Scenario):
    """Registering a person with the national body is the officer's act alone.

    `POST /members` authorises `AssociationOfficer` and nobody else, so a
    perfectly well-formed registration presented by the league secretary — a
    real member, acting in a declared role — is refused with
    `ERR_FORBIDDEN_ROLE` at check 2 of the refusal order.

    Design: Corner/rbac/corner_exclusive_operation_rejects_every_other_role_before_any_state_check
    """
    scn = forming_league

    response = scn.api.register_member(
        f.member_payload("Ivy Interloper", MemberClass.ADULT), scn.secretary
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_team_entry_refuses_the_treasurer_before_the_league_state_check(
    certified_match: Scenario,
):
    """The wrong role outranks the wrong league state on team entry.

    Team entry is the secretary's act and is permitted only while the league is
    `FORMING` or `BYLAWS_ADOPTED`.  This league is `IN_SEASON`, so the request
    breaks the state rule of check 15 as well as the role rule of check 2 — and
    the earliest broken check decides, so the answer is `ERR_FORBIDDEN_ROLE`
    and not `ERR_LEAGUE_STATE_INVALID`.

    Design: Corner/rbac/corner_exclusive_operation_rejects_every_other_role_before_any_state_check
    """
    scn = certified_match
    assert_fields(_league_of(scn), status=LeagueStatus.IN_SEASON.value)

    response = scn.api.create_team(
        f.team_payload(scn.league_id, "Late Arrivals"), scn.treasurer
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_remittance_drafting_refuses_the_secretary_before_membership_state(
    certified_match: Scenario,
):
    """Fee remittance is the treasurer's errand, whoever else the actor is.

    Every membership listed here is already `SANCTIONED` and `REMITTED`, a
    combination check 21 refuses outright, and the same request also names a
    league whose secretary the actor genuinely is.  Neither matters: the role
    list of `POST /fee-remittances` names only `LeagueTreasurer`, so check 2
    answers `ERR_FORBIDDEN_ROLE`.

    Design: Corner/rbac/corner_exclusive_operation_rejects_every_other_role_before_any_state_check
    """
    scn = certified_match

    response = scn.api.create_fee_remittance(
        f.fee_remittance_payload(
            scn.league_id,
            scn.membership_ids,
            fx.expected_remittance_cents(scn, scn.membership_ids),
        ),
        scn.secretary,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_honor_score_filing_refuses_the_secretary_role(certified_match: Scenario):
    """An honor-score claim originates with the bowler and with nobody else.

    The claim below is substantively sound — a 720 scratch series with a 22-pin
    handicap frozen onto the slot claims 786 handicap pins, past the 700
    threshold — but `POST /award-applications` authorises `Bowler` only, so the
    secretary is refused at check 2 before the threshold is ever computed.

    Design: Corner/rbac/corner_exclusive_operation_rejects_every_other_role_before_any_state_check
    """
    scn = certified_match
    slot = _slot_of(scn, 1)

    response = scn.api.create_award_application(
        f.award_application_payload(
            scn.league_id,
            scn.membership_ids[1],
            slot["id"],
            AwardType.HANDICAP_SERIES_700,
        ),
        scn.secretary,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_lineup_submission_refuses_the_plain_bowler_role(certified_match: Scenario):
    """Lineup submission is shared by two roles, and `Bowler` is not one of them.

    `POST /matches/{id}/lineups` authorises `TeamCaptain` and `LeagueSecretary`.
    A member who does hold a membership on the team being acted for is still
    refused with `ERR_FORBIDDEN_ROLE` when they present the plain `Bowler`
    capacity, because the role list is consulted before the ownership check of
    check 8 is ever reached.

    Design: Corner/rbac/corner_exclusive_operation_rejects_every_other_role_before_any_state_check
    """
    scn = certified_match

    response = scn.api.submit_lineup(
        scn.match_ids[1],
        f.lineup_payload(
            scn.match_version(1), scn.team_ids[0], fx.regular_slots(scn, (0, 1))
        ),
        scn.bowler(0),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_disbursement_refuses_the_secretary_before_the_fund_state_check(
    certified_match: Scenario,
):
    """The secretary approves a plan and may never pay one.

    This fund is still `ACCUMULATING`, which check 18 would refuse, and the
    league is still `IN_SEASON`, which the disbursement rules also forbid.  The
    response is nonetheless `ERR_FORBIDDEN_ROLE`, because `POST
    /prize-funds/{id}/disburse` authorises `LeagueTreasurer` alone.

    Design: Corner/rbac/corner_exclusive_operation_rejects_every_other_role_before_any_state_check
    """
    scn = certified_match
    assert_fields(_fund_of(scn), status=PrizeFundStatus.ACCUMULATING.value)

    response = scn.api.disburse(scn.prize_fund_id(), {}, scn.secretary)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_the_logical_clock_refuses_the_league_secretary(forming_league: Scenario):
    """Moving the logical clock is an association-officer operation.

    `POST /_clock/set_current_utc` authorises `AssociationOfficer` only, so the
    secretary cannot advance time under the league's own feet.

    Design: Corner/rbac/corner_exclusive_operation_rejects_every_other_role_before_any_state_check
    """
    scn = forming_league

    response = scn.api.set_clock(WEEK1_STARTS_AT, scn.secretary)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_the_two_restricted_read_listings_exclude_the_bowler_and_the_captain(
    certified_match: Scenario,
):
    """Most reads are open to all five roles; two fiscal listings are not.

    The fee-remittance and dues-payment reads are restricted to
    `LeagueSecretary`, `LeagueTreasurer` and `AssociationOfficer`, so a `Bowler`
    and a `TeamCaptain` are refused with `ERR_FORBIDDEN_ROLE` even though they
    are members of the very league whose money they are asking about.

    Design: Corner/rbac/corner_exclusive_operation_rejects_every_other_role_before_any_state_check
    """
    scn = certified_match

    validate_error(
        scn.api.list_fee_remittances(scn.bowler(0), params={"league_id": scn.league_id}),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        scn.api.list_dues_payments(
            scn.captain(0), params={"membership_id": scn.membership_ids[0]}
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )


def test_the_open_read_and_the_shared_lineup_endpoint_admit_both_roles(
    certified_match: Scenario,
):
    """An exclusive endpoint is exclusive; a shared one really is shared.

    Reading a league is open to all five roles, so the bowler refused on the two
    fiscal listings reads the league itself with 200.  And the one endpoint whose
    role list carries two entries obeys both of them: the captain of the away
    side submits that side's lineup, freezing 36 plus 18 for 54, and the
    secretary then submits the home side's, freezing 45 plus 54 for 99 and
    moving the match to `LINEUPS_SUBMITTED`.

    Design: Corner/rbac/corner_exclusive_operation_rejects_every_other_role_before_any_state_check
    """
    scn = certified_match

    league = validate_success(scn.api.get_league(scn.league_id, scn.bowler(0)), 200)
    assert_fields(league, id=scn.league_id, status=LeagueStatus.IN_SEASON.value)

    week_two = _match_of(scn, 1)
    assert_fields(week_two, home_team_id=scn.team_ids[1], away_team_id=scn.team_ids[0])

    away = validate_success(
        scn.api.submit_lineup(
            scn.match_ids[1],
            f.lineup_payload(
                week_two["version"], scn.team_ids[0], fx.regular_slots(scn, (0, 1))
            ),
            scn.captain(0),
        ),
        200,
    )
    assert_fields(
        away,
        away_team_handicap_per_game=54,
        version=week_two["version"] + 1,
    )

    home = validate_success(
        scn.api.submit_lineup(
            scn.match_ids[1],
            f.lineup_payload(
                away["version"], scn.team_ids[1], fx.regular_slots(scn, (2, 3))
            ),
            scn.secretary,
        ),
        200,
    )
    assert_fields(
        home,
        home_team_handicap_per_game=99,
        away_team_handicap_per_game=54,
        status=MatchStatus.LINEUPS_SUBMITTED.value,
        version=away["version"] + 1,
    )


def test_none_of_the_role_refusals_left_a_row_behind(certified_match: Scenario):
    """A refusal at check 2 is inert: nothing is created, nothing transitions.

    After the whole battery of wrong-role attempts the league still has exactly
    its two teams and its four memberships, the single remittance that sanctioned
    them is still the only one, and no honor-score application exists at all.

    Design: Corner/rbac/corner_exclusive_operation_rejects_every_other_role_before_any_state_check
    """
    scn = certified_match

    scn.api.register_member(f.member_payload("Ivy Interloper"), scn.secretary)
    scn.api.create_team(f.team_payload(scn.league_id, "Late Arrivals"), scn.treasurer)
    scn.api.create_fee_remittance(
        f.fee_remittance_payload(
            scn.league_id,
            scn.membership_ids,
            fx.expected_remittance_cents(scn, scn.membership_ids),
        ),
        scn.secretary,
    )
    scn.api.create_award_application(
        f.award_application_payload(
            scn.league_id,
            scn.membership_ids[1],
            _slot_of(scn, 1)["id"],
            AwardType.HANDICAP_SERIES_700,
        ),
        scn.secretary,
    )
    scn.api.disburse(scn.prize_fund_id(), {}, scn.secretary)

    teams, _ = validate_paginated(
        scn.api.list_league_teams(scn.league_id, scn.secretary)
    )
    assert len(teams) == 2, f"a refused team entry created a row: {teams}"

    _, memberships_meta = validate_paginated(
        scn.api.list_memberships(scn.secretary, params={"league_id": scn.league_id})
    )
    assert memberships_meta["total_count"] == len(scn.membership_ids)

    _, remittances_meta = validate_paginated(
        scn.api.list_fee_remittances(scn.secretary, params={"league_id": scn.league_id})
    )
    assert remittances_meta["total_count"] == 1

    _, applications_meta = validate_paginated(
        scn.api.list_award_applications(
            scn.secretary, params={"league_id": scn.league_id}
        )
    )
    assert applications_meta["total_count"] == 0


# ══════════════════════════════════════════════════════════════════════════
# Officer and owner bindings attach to the resource, not to the role string
# ══════════════════════════════════════════════════════════════════════════

def test_bylaw_amendment_refuses_another_leagues_secretary(certified_match: Scenario):
    """Holding the secretary role somewhere is not holding it here.

    Officer binding is checked once the target resource has been loaded: the
    acting `X-User-ID` must equal *this* league's `secretary_member_id`.  A
    genuine secretary of a different league, presenting a well-formed amendment
    with a perfectly fresh version echo, is refused with
    `ERR_NOT_LEAGUE_SECRETARY` and the league does not move.

    Design: Corner/rbac/corner_officer_and_owner_bindings_are_per_resource_not_per_role
    """
    scn = certified_match
    other = fx.charter_league(scn.api, name="Thursday Trios")
    before = _league_of(scn)

    response = scn.api.adopt_bylaws(
        scn.league_id,
        f.bylaws_payload(before["version"], max_dues_arrears_weeks=3),
        other.secretary,
    )
    validate_error(response, ApiErrorId.ERR_NOT_LEAGUE_SECRETARY.value)

    after = _league_of(scn)
    assert_fields(after, version=before["version"])
    _assert_bylaws_unchanged(before, after)


def test_an_unknown_league_path_outranks_the_secretary_binding(
    certified_match: Scenario,
):
    """Path existence is resolved before any officer binding is consulted.

    The identical payload and the identical foreign secretary, aimed at a league
    id that does not exist, answers `ERR_LEAGUE_NOT_FOUND` rather than
    `ERR_NOT_LEAGUE_SECRETARY`: check 4 resolves the path left to right and
    check 6 is never reached.

    Design: Corner/rbac/corner_officer_and_owner_bindings_are_per_resource_not_per_role
    """
    scn = certified_match
    other = fx.charter_league(scn.api, name="Thursday Trios")

    response = scn.api.adopt_bylaws(
        NON_EXISTENT_UUID,
        f.bylaws_payload(scn.league_version(), max_dues_arrears_weeks=3),
        other.secretary,
    )
    validate_error(response, ApiErrorId.ERR_LEAGUE_NOT_FOUND.value)


def test_remittance_drafting_refuses_a_foreign_treasurer_before_membership_state(
    certified_match: Scenario,
):
    """The treasurer binding outranks the membership-state check.

    Every membership named below is already `SANCTIONED` and `REMITTED`, which
    check 21 refuses with `ERR_MEMBERSHIP_STATE_INVALID`.  Because the acting
    treasurer serves a different league, the earlier check 7 decides instead and
    the answer is `ERR_NOT_LEAGUE_TREASURER`; no second remittance appears.

    Design: Corner/rbac/corner_officer_and_owner_bindings_are_per_resource_not_per_role
    """
    scn = certified_match
    other = fx.charter_league(scn.api, name="Thursday Trios")

    response = scn.api.create_fee_remittance(
        f.fee_remittance_payload(
            scn.league_id,
            scn.membership_ids,
            fx.expected_remittance_cents(scn, scn.membership_ids),
        ),
        other.treasurer,
    )
    validate_error(response, ApiErrorId.ERR_NOT_LEAGUE_TREASURER.value)

    _, meta = validate_paginated(
        scn.api.list_fee_remittances(scn.secretary, params={"league_id": scn.league_id})
    )
    assert meta["total_count"] == 1


def test_dues_payment_by_a_non_owning_bowler_outranks_the_amount_check(
    certified_match: Scenario,
):
    """Ownership is decided before money is even looked at.

    A bowler may record dues for their own membership only.  This request is
    doubly wrong — the wrong payer *and* a 900-cent tender against a 1200-cent
    weekly due — and the PRD is explicit that money checks run last, so the
    answer is `ERR_NOT_RESOURCE_OWNER` and never `ERR_DUES_AMOUNT_MISMATCH`.

    Design: Corner/rbac/corner_officer_and_owner_bindings_are_per_resource_not_per_role
    """
    scn = certified_match

    response = scn.api.record_dues_payment(
        scn.membership_ids[0], f.dues_payload(1, WRONG_TENDER_CENTS), scn.bowler(1)
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    assert_fields(_membership(scn, 0), dues_paid_cents=0)


def test_honor_score_filing_for_a_teammates_membership_is_refused(
    certified_match: Scenario,
):
    """A bowler files on their own membership and on no other.

    The claim names a teammate's membership and that teammate's own slot, so it
    is internally consistent and its 786 handicap pins clear the threshold.  The
    ownership check of check 8 still refuses it with `ERR_NOT_RESOURCE_OWNER`,
    ahead of the reference and threshold checks, and no application is created.

    Design: Corner/rbac/corner_officer_and_owner_bindings_are_per_resource_not_per_role
    """
    scn = certified_match

    response = scn.api.create_award_application(
        f.award_application_payload(
            scn.league_id,
            scn.membership_ids[1],
            _slot_of(scn, 1)["id"],
            AwardType.HANDICAP_SERIES_700,
        ),
        scn.bowler(0),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    _, meta = validate_paginated(
        scn.api.list_award_applications(
            scn.secretary, params={"league_id": scn.league_id}
        )
    )
    assert meta["total_count"] == 0


def test_a_captain_may_not_submit_for_a_team_he_holds_no_membership_on(
    certified_match: Scenario,
):
    """The captaincy is asserted by header but bound to a membership.

    A `TeamCaptain` is accepted for a team only when the acting member holds a
    membership of that league whose `team_id` is the team being acted for.  The
    member below holds one on the other side of the match, so submitting the
    first team's lineup is refused with `ERR_NOT_RESOURCE_OWNER`.

    Design: Corner/rbac/corner_officer_and_owner_bindings_are_per_resource_not_per_role
    """
    scn = certified_match

    response = scn.api.submit_lineup(
        scn.match_ids[1],
        f.lineup_payload(
            scn.match_version(1), scn.team_ids[0], fx.regular_slots(scn, (0, 1))
        ),
        scn.captain(2),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    assert scn.series_entries(1) == [], "a refused lineup created slots"


def test_the_owning_bowler_and_the_owning_captain_are_obeyed(
    certified_match: Scenario,
):
    """The same two endpoints answer 201 and 200 for the rightful owner.

    The bowler who owns the membership tenders exactly the bylaw weekly due and
    the payment splits 700 to the prize fund and 500 to league expenses.  The
    captain who does hold a membership on the team submits that team's lineup and
    the match version the earlier refusal never consumed is still the live one.

    Design: Corner/rbac/corner_officer_and_owner_bindings_are_per_resource_not_per_role
    """
    scn = certified_match
    version_before = scn.match_version(1)

    payment = validate_success(
        scn.api.record_dues_payment(
            scn.membership_ids[0],
            f.dues_payload(1, BASE_BYLAWS["weekly_dues_cents"]),
            scn.bowler(0),
        ),
        201,
    )
    assert_cents(payment["amount_cents"], BASE_BYLAWS["weekly_dues_cents"])
    assert_cents(payment["prize_share_cents"], PRIZE_SHARE_CENTS, "prize_share_cents")
    assert_cents(payment["expense_share_cents"], EXPENSE_SHARE_CENTS, "expense_share_cents")

    lineup = validate_success(
        scn.api.submit_lineup(
            scn.match_ids[1],
            f.lineup_payload(
                version_before, scn.team_ids[0], fx.regular_slots(scn, (0, 1))
            ),
            scn.captain(0),
        ),
        200,
    )
    assert_fields(
        lineup,
        away_team_handicap_per_game=54,
        status=MatchStatus.SCHEDULED.value,
        version=version_before + 1,
    )


def test_the_refused_secretary_is_obeyed_on_his_own_league(certified_match: Scenario):
    """The binding is per resource: refused there, obeyed here.

    The very principal who cannot amend the first league's bylaws adopts his own
    league's eighteen values in the same test run and is answered with 200 and a
    `BYLAWS_ADOPTED` status, which is the whole point of a per-resource binding.

    Design: Corner/rbac/corner_officer_and_owner_bindings_are_per_resource_not_per_role
    """
    scn = certified_match
    other = fx.charter_league(scn.api, name="Thursday Trios")

    validate_error(
        scn.api.adopt_bylaws(
            scn.league_id,
            f.bylaws_payload(scn.league_version(), max_dues_arrears_weeks=3),
            other.secretary,
        ),
        ApiErrorId.ERR_NOT_LEAGUE_SECRETARY.value,
    )

    own = validate_success(
        scn.api.get_league(other.league_id, other.secretary), 200
    )
    adopted = validate_success(
        scn.api.adopt_bylaws(
            other.league_id, f.bylaws_payload(own["version"]), other.secretary
        ),
        200,
    )
    assert_fields(
        adopted,
        status=LeagueStatus.BYLAWS_ADOPTED.value,
        version=own["version"] + 1,
        max_dues_arrears_weeks=BASE_BYLAWS["max_dues_arrears_weeks"],
    )


# ══════════════════════════════════════════════════════════════════════════
# One member wearing two hats: the §2.10 duty separations
# ══════════════════════════════════════════════════════════════════════════

def test_the_secretary_who_bowled_may_file_his_own_honor_score(api: ApiClient):
    """Wearing the bowler hat, the secretary is an ordinary applicant.

    Nothing in the separations stops the secretary from *claiming*: filing is the
    bowler's own act on the bowler's own membership.  His slot carries a 720
    scratch series and a 22-pin frozen handicap, so `claimed_pins` is 720 plus
    three times 22, which is 786 and past the 700 handicap-series threshold.  The
    application is created at `SUBMITTED` with `round_count` 1, and both evidence
    flags are true because the lane pair was never revoked and the slot is a
    certified average-bearing one.

    Design: Corner/rbac/corner_segregation_of_duties_when_the_secretary_is_also_a_bowler
    """
    scn = _league_where_the_secretary_also_bowls(api)
    assert_fields(
        _league_of(scn),
        secretary_member_id=scn.member_ids[SECRETARY_MEMBERSHIP_INDEX],
    )
    slot = _slot_of(scn, SECRETARY_MEMBERSHIP_INDEX)
    assert_fields(
        slot,
        scratch_series=SECRETARY_SCRATCH_SERIES,
        handicap_per_game_applied=SECRETARY_SLOT_HANDICAP,
        certified=True,
        counts_toward_average=True,
    )

    application = validate_success(
        scn.api.create_award_application(
            f.award_application_payload(
                scn.league_id,
                scn.membership_ids[SECRETARY_MEMBERSHIP_INDEX],
                slot["id"],
                AwardType.HANDICAP_SERIES_700,
            ),
            scn.bowler(SECRETARY_MEMBERSHIP_INDEX),
        ),
        201,
    )
    assert_fields(
        application,
        claimed_pins=SECRETARY_CLAIMED_PINS,
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=1,
        lane_certification_verified=True,
        sanctioned_at_game_time=True,
        verified_by_user_id=None,
    )


def test_the_secretary_may_not_verify_his_own_honor_score(api: ApiClient):
    """Verification compares the league's secretary against the applicant.

    The comparison is between `secretary_member_id` and the `member_id` behind
    the applying membership, and here they are the same person, so `VERIFY` is
    refused with `ERR_SEGREGATION_OF_DUTIES`.  The refusal is inert: the
    application stays at `SUBMITTED`, its `round_count` stays 1 and no
    `verified_by_user_id` is recorded.

    Design: Corner/rbac/corner_segregation_of_duties_when_the_secretary_is_also_a_bowler
    """
    scn = _league_where_the_secretary_also_bowls(api)
    application = validate_success(
        scn.api.create_award_application(
            f.award_application_payload(
                scn.league_id,
                scn.membership_ids[SECRETARY_MEMBERSHIP_INDEX],
                _slot_of(scn, SECRETARY_MEMBERSHIP_INDEX)["id"],
                AwardType.HANDICAP_SERIES_700,
            ),
            scn.bowler(SECRETARY_MEMBERSHIP_INDEX),
        ),
        201,
    )

    response = scn.api.league_verify_application(
        application["id"],
        f.league_verification_payload(LeagueVerificationDecision.VERIFY.value),
        scn.secretary,
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    after = validate_success(
        scn.api.get_award_application(application["id"], scn.secretary), 200
    )
    assert_fields(
        after,
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=1,
        verified_by_user_id=None,
        version=application["version"],
    )


def test_the_secretary_may_not_open_a_hearing_on_his_own_protest(api: ApiClient):
    """The filer may not convene the hearing, even wearing the officer hat.

    Filing as a `Bowler` is legitimate and creates the protest at `FILED` with
    `review_round` 0.  Opening the hearing compares `secretary_member_id` against
    the `member_id` behind `filed_by_membership_id`, which is the same member, so
    the hearing is refused with `ERR_SEGREGATION_OF_DUTIES` and the protest does
    not move.

    Design: Corner/rbac/corner_segregation_of_duties_when_the_secretary_is_also_a_bowler
    """
    scn = _league_where_the_secretary_also_bowls(api)

    protest = validate_success(
        scn.api.file_protest(
            f.protest_payload(
                scn.league_id,
                scn.membership_ids[SECRETARY_MEMBERSHIP_INDEX],
                ProtestCategory.SCORE_ERROR,
                match_id=scn.match_ids[0],
            ),
            scn.bowler(SECRETARY_MEMBERSHIP_INDEX),
        ),
        201,
    )
    assert_fields(
        protest,
        status=ProtestStatus.FILED.value,
        review_round=0,
        remedy=Remedy.NONE.value,
    )

    response = scn.api.review_protest(protest["id"], f.review_payload(), scn.secretary)
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    after = validate_success(scn.api.get_protest(protest["id"], scn.secretary), 200)
    assert_fields(
        after,
        status=ProtestStatus.FILED.value,
        review_round=0,
        version=protest["version"],
    )


def test_protest_state_outranks_segregation_on_a_ruling(api: ApiClient):
    """Two rules broken at once, and the earlier check decides.

    Ruling is legal only from `UNDER_REVIEW`, and the protest below is still
    `FILED` because the hearing the secretary was not allowed to open never
    happened.  The ruling therefore breaks check 20 as well as check 26, and the
    answer is `ERR_PROTEST_STATE_INVALID` rather than the segregation code.

    Design: Corner/rbac/corner_segregation_of_duties_when_the_secretary_is_also_a_bowler
    """
    scn = _league_where_the_secretary_also_bowls(api)
    protest = validate_success(
        scn.api.file_protest(
            f.protest_payload(
                scn.league_id,
                scn.membership_ids[SECRETARY_MEMBERSHIP_INDEX],
                ProtestCategory.SCORE_ERROR,
                match_id=scn.match_ids[0],
            ),
            scn.bowler(SECRETARY_MEMBERSHIP_INDEX),
        ),
        201,
    )

    response = scn.api.rule_on_protest(
        protest["id"],
        f.ruling_payload(ProtestDecision.DENY.value, remedy=Remedy.NONE),
        scn.secretary,
    )
    validate_error(response, ApiErrorId.ERR_PROTEST_STATE_INVALID.value)

    assert_fields(
        validate_success(scn.api.get_protest(protest["id"], scn.secretary), 200),
        status=ProtestStatus.FILED.value,
        review_round=0,
    )


def test_the_same_secretary_hears_and_rules_on_a_teammates_protest(api: ApiClient):
    """The separation is about the person, not about the office.

    The identical secretary calls that were refused on his own protest succeed on
    another member's: the hearing moves the protest to `UNDER_REVIEW` and
    increments `review_round` to 1, and the denial moves it to the terminal
    `DENIED` with the only remedy a denial may carry, `NONE`, leaving
    `review_round` at 1 and changing no match state — the week-one match is still
    `CERTIFIED` with its 4.0 to 0.0 points intact.

    Design: Corner/rbac/corner_segregation_of_duties_when_the_secretary_is_also_a_bowler
    """
    scn = _league_where_the_secretary_also_bowls(api)
    own = validate_success(
        scn.api.file_protest(
            f.protest_payload(
                scn.league_id,
                scn.membership_ids[SECRETARY_MEMBERSHIP_INDEX],
                ProtestCategory.SCORE_ERROR,
                match_id=scn.match_ids[0],
            ),
            scn.bowler(SECRETARY_MEMBERSHIP_INDEX),
        ),
        201,
    )
    teammates = validate_success(
        scn.api.file_protest(
            f.protest_payload(
                scn.league_id,
                scn.membership_ids[1],
                ProtestCategory.SCORE_ERROR,
                match_id=scn.match_ids[0],
            ),
            scn.bowler(1),
        ),
        201,
    )

    heard = validate_success(
        scn.api.review_protest(teammates["id"], f.review_payload(), scn.secretary), 200
    )
    assert_fields(heard, status=ProtestStatus.UNDER_REVIEW.value, review_round=1)

    ruled = validate_success(
        scn.api.rule_on_protest(
            teammates["id"],
            f.ruling_payload(ProtestDecision.DENY.value, remedy=Remedy.NONE),
            scn.secretary,
        ),
        200,
    )
    assert_fields(
        ruled,
        status=ProtestStatus.DENIED.value,
        remedy=Remedy.NONE.value,
        review_round=1,
    )

    rows, meta = validate_paginated(
        scn.api.list_protests(scn.secretary, params={"league_id": scn.league_id})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {own["id"], teammates["id"]}

    match = _match_of(scn, 0)
    assert_fields(match, status=MatchStatus.CERTIFIED.value)
    assert_points(match["home_points"], 4.0, "home_points")
    assert_points(match["away_points"], 0.0, "away_points")


# ══════════════════════════════════════════════════════════════════════════
# All three concurrency tokens refuse the value the client still holds
# ══════════════════════════════════════════════════════════════════════════

def test_bylaw_amendment_refuses_a_token_the_cascades_invalidated(api: ApiClient):
    """A version the client never saw move is still a stale version.

    The client read its token when the bylaws were adopted.  Sanctioning the
    roster and opening week one both mutate the league row — every row a cascade
    actually mutates has its `version` incremented — so the echo is out of date
    even though the league's status still admits an amendment.  The refusal is
    `ERR_STALE_LEAGUE_VERSION` and it is provably inert: the version stands and
    all eighteen bylaw values stand.

    Design: Corner/cross-cutting complexity layers/corner_all_three_occ_rules_refuse_the_token_the_client_still_holds
    """
    scn, stale_version = _league_in_season_with_a_stale_token(api)
    before = _league_of(scn)
    assert_fields(before, status=LeagueStatus.IN_SEASON.value)
    assert before["version"] != stale_version, (
        "the sanction and opening cascades must have moved the league's version"
    )

    response = scn.api.adopt_bylaws(
        scn.league_id,
        f.bylaws_payload(stale_version, max_dues_arrears_weeks=3),
        scn.secretary,
    )
    validate_error(response, ApiErrorId.ERR_STALE_LEAGUE_VERSION.value)

    after = _league_of(scn)
    assert_fields(after, version=before["version"])
    _assert_bylaws_unchanged(before, after)


def test_a_successful_amendment_invalidates_the_clients_own_token(
    certified_match: Scenario,
):
    """The version the response returns is the only one the next call may echo.

    A fresh token is accepted, the amendment lands and the league's version rises
    by exactly 1.  Replaying the very same request immediately — the classic
    double-submit — is refused with `ERR_STALE_LEAGUE_VERSION`, and the league
    still carries the first amendment's value rather than the replay's.

    Design: Corner/cross-cutting complexity layers/corner_all_three_occ_rules_refuse_the_token_the_client_still_holds
    """
    scn = certified_match
    version = scn.league_version()

    amended = validate_success(
        scn.api.adopt_bylaws(
            scn.league_id,
            f.bylaws_payload(version, max_dues_arrears_weeks=3),
            scn.secretary,
        ),
        200,
    )
    assert_fields(amended, version=version + 1, max_dues_arrears_weeks=3)

    validate_error(
        scn.api.adopt_bylaws(
            scn.league_id,
            f.bylaws_payload(version, max_dues_arrears_weeks=4),
            scn.secretary,
        ),
        ApiErrorId.ERR_STALE_LEAGUE_VERSION.value,
    )

    assert_fields(
        _league_of(scn), version=version + 1, max_dues_arrears_weeks=3
    )
    assert_fields(_membership(scn, 0), handicap_per_game=36)


def test_a_refused_lineup_resubmission_deletes_no_slot(certified_match: Scenario):
    """A supersede that never happened removes nothing.

    The first submission is accepted, freezing 36 and 18 onto the two positions
    for a side handicap of 54, and it consumes the token it echoed.  Resubmitting
    the same two bowlers in the opposite order with that consumed token is
    refused with `ERR_STALE_MATCH_VERSION`, and the slot listing still shows the
    original rows — the same ids, the same positions and the same frozen
    handicaps — because a refused supersede deletes nothing.

    Design: Corner/cross-cutting complexity layers/corner_all_three_occ_rules_refuse_the_token_the_client_still_holds
    """
    scn = certified_match
    version = scn.match_version(1)

    submitted = validate_success(
        scn.api.submit_lineup(
            scn.match_ids[1],
            f.lineup_payload(version, scn.team_ids[0], fx.regular_slots(scn, (0, 1))),
            scn.secretary,
        ),
        200,
    )
    assert_fields(
        submitted, version=version + 1, away_team_handicap_per_game=54
    )
    before = scn.series_entries(1, 0)
    assert [row["handicap_per_game_applied"] for row in before] == [36, 18]

    reordered = [
        f.slot(1, membership_id=scn.membership_ids[1]),
        f.slot(2, membership_id=scn.membership_ids[0]),
    ]
    validate_error(
        scn.api.submit_lineup(
            scn.match_ids[1],
            f.lineup_payload(version, scn.team_ids[0], reordered),
            scn.secretary,
        ),
        ApiErrorId.ERR_STALE_MATCH_VERSION.value,
    )

    after = scn.series_entries(1, 0)
    assert _slot_shape(after) == _slot_shape(before), (
        "a refused resubmission rewrote the lineup"
    )
    assert_fields(_match_of(scn, 1), version=version + 1)


def test_a_refused_plan_redraft_leaves_every_plan_figure_intact(
    certified_match: Scenario,
):
    """The fund's own token guards the plan the client is about to overwrite.

    The projected basis is the settled amount of 0 plus one remaining week times
    four sanctioned members times the 700-cent weekly prize share, which is 2800.
    The reserve floors 5 percent of that to 140 because 2800 is below the
    100000-cent tier, the administrative fee rounds 3 percent of the post-reserve
    2660 half up to 80, and 2580 remains distributable.  Redrafting with the
    consumed token is refused with `ERR_STALE_PRIZE_FUND_VERSION` and every one
    of those figures — and the basis variant that produced them — still stands.

    Design: Corner/cross-cutting complexity layers/corner_all_three_occ_rules_refuse_the_token_the_client_still_holds
    """
    scn = certified_match
    fund = _fund_of(scn)
    assert_fields(fund, status=PrizeFundStatus.ACCUMULATING.value)

    plan = validate_success(
        scn.api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                fund["version"], BasisVariant.PROJECTED_SEASON_END, 2
            ),
            scn.treasurer,
        ),
        200,
    )
    assert_fields(
        plan,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
        basis_variant=BasisVariant.PROJECTED_SEASON_END.value,
        place_count=2,
        version=fund["version"] + 1,
    )
    assert_cents(plan["plan_basis_cents"], 2800, "plan_basis_cents")
    assert_cents(plan["reserve_cents"], 140, "reserve_cents")
    assert_cents(plan["admin_fee_cents"], 80, "admin_fee_cents")
    assert_cents(plan["net_distributable_cents"], 2580, "net_distributable_cents")

    validate_error(
        scn.api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                fund["version"], BasisVariant.CERTIFIED_TO_DATE, 2
            ),
            scn.treasurer,
        ),
        ApiErrorId.ERR_STALE_PRIZE_FUND_VERSION.value,
    )

    after = _fund_of(scn)
    assert_fields(
        after,
        version=fund["version"] + 1,
        basis_variant=BasisVariant.PROJECTED_SEASON_END.value,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
    )
    assert_cents(after["plan_basis_cents"], 2800, "plan_basis_cents")
    assert_cents(after["reserve_cents"], 140, "reserve_cents")
    assert_cents(after["admin_fee_cents"], 80, "admin_fee_cents")
    assert_cents(after["net_distributable_cents"], 2580, "net_distributable_cents")


def test_the_redraft_the_fresh_token_carries_supersedes_the_plan_outright(
    certified_match: Scenario,
):
    """Reading the version the refusal did not move is all the retry needs.

    A fresh draft supersedes the prior one outright, overwriting every plan
    field.  With no dues collected the settled amount is 0, so the certified
    basis is 0 and so are the reserve, the fee and the net — a legal degenerate
    plan, drafted from `PLAN_DRAFTED`, whose version is one past the plan it
    replaced.

    Design: Corner/cross-cutting complexity layers/corner_all_three_occ_rules_refuse_the_token_the_client_still_holds
    """
    scn = certified_match
    fund = _fund_of(scn)

    first = validate_success(
        scn.api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                fund["version"], BasisVariant.PROJECTED_SEASON_END, 2
            ),
            scn.treasurer,
        ),
        200,
    )
    validate_error(
        scn.api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                fund["version"], BasisVariant.CERTIFIED_TO_DATE, 2
            ),
            scn.treasurer,
        ),
        ApiErrorId.ERR_STALE_PRIZE_FUND_VERSION.value,
    )

    second = validate_success(
        scn.api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                first["version"], BasisVariant.CERTIFIED_TO_DATE, 2
            ),
            scn.treasurer,
        ),
        200,
    )
    assert_fields(
        second,
        basis_variant=BasisVariant.CERTIFIED_TO_DATE.value,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
        version=first["version"] + 1,
    )
    assert_cents(second["plan_basis_cents"], 0, "plan_basis_cents")
    assert_cents(second["reserve_cents"], 0, "reserve_cents")
    assert_cents(second["admin_fee_cents"], 0, "admin_fee_cents")
    assert_cents(second["net_distributable_cents"], 0, "net_distributable_cents")
    assert_prize_money_invariant(second)


# ══════════════════════════════════════════════════════════════════════════
# The reserve tier is read from the basis itself, at exactly the threshold
# ══════════════════════════════════════════════════════════════════════════

def test_a_basis_below_the_tier_takes_the_five_percent_reserve(api: ApiClient):
    """Below 100000 cents the reserve is five percent of the basis.

    One settled week of five 10000-cent dues against a zero expense share leaves
    a settled prize amount of 50000 cents, and the certified basis is exactly
    that.  50000 is below the tier threshold, so the reserve floors 5 percent to
    2500, the administrative fee rounds 3 percent of the post-reserve 47500 half
    up to 1425, and 46075 is distributable.

    Design: Corner/cross-cutting complexity layers/corner_reserve_tier_is_read_from_the_basis_at_exactly_the_threshold
    """
    scn = _tier_league(api)
    fund = _fund_of(scn)
    assert_cents(fund["collected_prize_cents"], TIER_SETTLED_CENTS, "collected_prize_cents")

    plan = validate_success(
        scn.api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                fund["version"], BasisVariant.CERTIFIED_TO_DATE, 2
            ),
            scn.treasurer,
        ),
        200,
    )
    assert_cents(plan["plan_basis_cents"], 50_000, "plan_basis_cents")
    assert plan["plan_basis_cents"] < RESERVE_TIER_THRESHOLD_CENTS
    assert_cents(plan["reserve_cents"], 2_500, "reserve_cents")
    assert_cents(plan["admin_fee_cents"], 1_425, "admin_fee_cents")
    assert_cents(plan["net_distributable_cents"], 46_075, "net_distributable_cents")
    assert_cents(
        plan["reserve_cents"], expected_reserve_cents(plan["plan_basis_cents"])
    )
    assert_cents(
        plan["admin_fee_cents"],
        expected_admin_fee_cents(plan["plan_basis_cents"], plan["reserve_cents"]),
    )


def test_a_basis_at_exactly_the_tier_threshold_takes_the_eight_percent_reserve(
    api: ApiClient,
):
    """At the threshold the higher rate applies — the comparison is inclusive.

    The projected basis is the 50000 already settled plus one remaining week times
    five sanctioned members times the 10000-cent weekly prize share, landing on
    100000 cents exactly.  The tier is read from that basis and the threshold is
    "at or above", so the reserve is 8 percent — 8000, not the 5000 the lower
    band would have withheld.  The fee then rounds 3 percent of 92000 half up to
    2760 and 89240 is distributable.

    Design: Corner/cross-cutting complexity layers/corner_reserve_tier_is_read_from_the_basis_at_exactly_the_threshold
    """
    scn = _tier_league(api)
    fund = _fund_of(scn)

    plan = validate_success(
        scn.api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                fund["version"], BasisVariant.PROJECTED_SEASON_END, 2
            ),
            scn.treasurer,
        ),
        200,
    )
    assert_cents(plan["plan_basis_cents"], RESERVE_TIER_THRESHOLD_CENTS, "plan_basis_cents")
    assert_cents(plan["reserve_cents"], 8_000, "reserve_cents")
    assert_cents(plan["admin_fee_cents"], 2_760, "admin_fee_cents")
    assert_cents(plan["net_distributable_cents"], 89_240, "net_distributable_cents")
    assert_fields(
        plan,
        basis_variant=BasisVariant.PROJECTED_SEASON_END.value,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
        place_count=2,
        version=fund["version"] + 1,
    )


def test_the_reserve_tier_never_latches_across_redrafts(api: ApiClient):
    """The rate is chosen per draft, from that draft's own basis.

    The projected draft withholds 8 percent of 100000.  Redrafting on the
    certified basis over the same unchanged dues ledger drops the basis back to
    50000, and the reserve returns to 2500 — the 8 percent rate does not latch
    onto the fund, because step 1 of the waterfall reads the tier from
    `plan_basis_cents` and from nothing else.

    Design: Corner/cross-cutting complexity layers/corner_reserve_tier_is_read_from_the_basis_at_exactly_the_threshold
    """
    scn = _tier_league(api)
    fund = _fund_of(scn)

    projected = validate_success(
        scn.api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                fund["version"], BasisVariant.PROJECTED_SEASON_END, 2
            ),
            scn.treasurer,
        ),
        200,
    )
    assert_cents(projected["reserve_cents"], 8_000, "reserve_cents")

    certified = validate_success(
        scn.api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                projected["version"], BasisVariant.CERTIFIED_TO_DATE, 2
            ),
            scn.treasurer,
        ),
        200,
    )
    assert_cents(certified["plan_basis_cents"], 50_000, "plan_basis_cents")
    assert_cents(certified["reserve_cents"], 2_500, "reserve_cents")
    assert_cents(certified["admin_fee_cents"], 1_425, "admin_fee_cents")
    assert_cents(certified["net_distributable_cents"], 46_075, "net_distributable_cents")
    assert_fields(
        certified,
        basis_variant=BasisVariant.CERTIFIED_TO_DATE.value,
        version=fund["version"] + 2,
    )


def test_drafting_a_plan_moves_no_money_and_creates_no_award(api: ApiClient):
    """Three drafts, and the money triple is exactly where the dues left it.

    Drafting creates no award rows at all — awards are materialised only by
    approval — and it moves no money: the fund's collected and undistributed
    balances stay at the 50000 the five dues payments contributed, nothing is
    paid, and the money invariant holds throughout.  Each payer's membership
    still shows one settled week and no arrears.

    Design: Corner/cross-cutting complexity layers/corner_reserve_tier_is_read_from_the_basis_at_exactly_the_threshold
    """
    scn = _tier_league(api)
    fund = _fund_of(scn)

    version = fund["version"]
    for variant in (
        BasisVariant.CERTIFIED_TO_DATE,
        BasisVariant.PROJECTED_SEASON_END,
        BasisVariant.CERTIFIED_TO_DATE,
    ):
        drafted = validate_success(
            scn.api.draft_distribution_plan(
                fund["id"],
                f.distribution_plan_payload(version, variant, 2),
                scn.treasurer,
            ),
            200,
        )
        version = drafted["version"]

    after = _fund_of(scn)
    assert_cents(after["collected_prize_cents"], TIER_SETTLED_CENTS, "collected_prize_cents")
    assert_cents(
        after["undistributed_balance_cents"], TIER_SETTLED_CENTS, "undistributed_balance_cents"
    )
    assert_cents(after["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert_prize_money_invariant(after)

    _, meta = validate_paginated(
        scn.api.list_prize_awards(
            scn.secretary, params={"prize_fund_id": fund["id"]}
        )
    )
    assert meta["total_count"] == 0, "drafting a plan must create no award"

    membership = _membership(scn, 0)
    assert_cents(membership["dues_paid_cents"], TIER_DUES_CENTS, "dues_paid_cents")
    assert_fields(membership, dues_arrears_weeks=0)


# ══════════════════════════════════════════════════════════════════════════
# Immediate consistency: the response that causes a change already carries it
# ══════════════════════════════════════════════════════════════════════════

def test_the_certify_response_carries_the_final_match_state(opened_match: Scenario):
    """Certification settles the match inside its own response body.

    The home side wins all three games and the series on handicap — 458 to 389,
    478 to 409 and 498 to 429 — taking all four points, and the certify response
    itself already reports `CERTIFIED`, 4.0 to 0.0 and a `certified_at` stamped
    with the current logical-clock instant.  Nothing here is left for a later
    read to discover.

    Design: Corner/consistency model/corner_derived_state_is_final_in_the_response_that_caused_it
    """
    scn = opened_match
    fx.enter_scores(scn, fx.score_entries_for(scn, 0), 0)

    certified = validate_success(
        scn.api.certify_match(scn.match_ids[0], {}, scn.secretary), 200
    )
    assert_fields(
        certified,
        status=MatchStatus.CERTIFIED.value,
        home_team_handicap_per_game=58,
        away_team_handicap_per_game=99,
    )
    assert_points(certified["home_points"], 4.0, "home_points")
    assert_points(certified["away_points"], 0.0, "away_points")
    assert_instant_equals(certified["certified_at"], WEEK1_STARTS_AT, "certified_at")


def test_averages_and_handicaps_are_final_in_the_next_request(
    certified_match: Scenario,
):
    """The request after certification reads the new averages, not the old ones.

    Three certified games against a nine-game threshold leave both bowlers
    `PROVISIONAL`, so the `BLENDED` policy blends the prior record with the fresh
    pins: 180 over 30 games with 540 pins stays at 180, while 195 over 30 games
    with 720 pins rises to 199.  The handicaps follow immediately on the `CURRENT`
    basis — 36 unchanged, and 18 in place of the 22 the entering average bought.

    Design: Corner/consistency model/corner_derived_state_is_final_in_the_response_that_caused_it
    """
    scn = certified_match

    first = _membership(scn, 0)
    assert_fields(
        first,
        certified_games=3,
        certified_pins=540,
        average_status=AverageStatus.PROVISIONAL.value,
        current_average=180,
        handicap_per_game=36,
    )

    second = _membership(scn, 1)
    assert_fields(
        second,
        certified_games=3,
        certified_pins=720,
        entering_average=195,
        average_status=AverageStatus.PROVISIONAL.value,
        current_average=199,
        handicap_per_game=18,
    )


def test_team_and_league_aggregates_are_final_in_the_next_request(
    certified_match: Scenario,
):
    """Counters up the chain are recomputed by the certifying request itself.

    The winning team already reports its 4.0 points and the 1260 scratch pins its
    two bowlers rolled, and its roster handicap has been re-derived from the new
    averages to 36 plus 18, which is 54.  The league's `certified_week_high_water`
    stands at 1 and the league itself is `IN_SEASON`.

    Design: Corner/consistency model/corner_derived_state_is_final_in_the_response_that_caused_it
    """
    scn = certified_match

    team = validate_success(scn.api.get_team(scn.team_ids[0], scn.secretary), 200)
    assert_points(team["total_points"], 4.0, "total_points")
    assert_fields(team, total_scratch_pins=1260, team_handicap_per_game=54)

    league = _league_of(scn)
    assert_fields(
        league, certified_week_high_water=1, status=LeagueStatus.IN_SEASON.value
    )


def test_the_dues_response_and_the_fund_read_carry_the_split_at_once(
    certified_match: Scenario,
):
    """One payment, and the money is already where the bylaws send it.

    The dues response itself carries the deterministic split — 700 cents of prize
    share and 500 of league expense out of the 1200 tendered — and the very next
    read of the prize fund shows the 700 already collected and still
    undistributed, with nothing paid out and the money invariant intact.

    Design: Corner/consistency model/corner_derived_state_is_final_in_the_response_that_caused_it
    """
    scn = certified_match

    payment = validate_success(
        scn.api.record_dues_payment(
            scn.membership_ids[0],
            f.dues_payload(1, BASE_BYLAWS["weekly_dues_cents"]),
            scn.treasurer,
        ),
        201,
    )
    assert_cents(payment["prize_share_cents"], PRIZE_SHARE_CENTS, "prize_share_cents")
    assert_cents(payment["expense_share_cents"], EXPENSE_SHARE_CENTS, "expense_share_cents")

    fund = _fund_of(scn)
    assert_cents(fund["collected_prize_cents"], PRIZE_SHARE_CENTS, "collected_prize_cents")
    assert_cents(
        fund["undistributed_balance_cents"], PRIZE_SHARE_CENTS, "undistributed_balance_cents"
    )
    assert_cents(fund["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert_prize_money_invariant(fund)

    membership = _membership(scn, 0)
    assert_cents(membership["dues_paid_cents"], BASE_BYLAWS["weekly_dues_cents"], "dues_paid_cents")
    assert_fields(membership, dues_arrears_weeks=0)


def test_a_lineup_freezes_handicaps_that_only_the_certify_call_created(
    certified_match: Scenario,
):
    """The sharp end: the next lineup freezes averages that did not exist before.

    Week two's lineup is submitted one request after certification, and the side
    handicap it freezes is 36 plus 18, which is 54.  An implementation that
    deferred the average recomputation would still be holding the entering
    handicaps and would freeze 36 plus 22, which is 58.  Week one's own slots are
    untouched by any of it and still carry the 36 and 22 frozen before a single
    game was certified.

    Design: Corner/consistency model/corner_derived_state_is_final_in_the_response_that_caused_it
    """
    scn = certified_match
    version = scn.match_version(1)

    submitted = validate_success(
        scn.api.submit_lineup(
            scn.match_ids[1],
            f.lineup_payload(version, scn.team_ids[0], fx.regular_slots(scn, (0, 1))),
            scn.secretary,
        ),
        200,
    )
    assert_fields(
        submitted,
        away_team_handicap_per_game=54,
        status=MatchStatus.SCHEDULED.value,
        version=version + 1,
    )

    week_two_slots = scn.series_entries(1, 0)
    assert [row["handicap_per_game_applied"] for row in week_two_slots] == [36, 18]

    week_one_slots = scn.series_entries(0, 0)
    assert [row["handicap_per_game_applied"] for row in week_one_slots] == [36, 22]
    assert_fields(_match_of(scn, 0), home_team_handicap_per_game=58)
