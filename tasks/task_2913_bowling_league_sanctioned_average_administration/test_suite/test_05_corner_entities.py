"""Entity-level corners: creation echoes, declared defaults, listing filters,
typed not-found codes, request-shape refusals and the one immutable resource.

Every test in this module builds its world through the API itself and asserts
only what the PRD pins: the response envelope of §2.2, the pagination contract
of §2.3, the identity and timestamp rules of §2.4, the refusal order of §2.6
and the error catalogue of §5.
"""
from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing.constants import NON_EXISTENT_UUID
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
    assert_identity,
    assert_millisecond_instant,
    assert_pagination_meta,
)
from test_helpers.constants import BASE_BYLAWS, ORG_MEETING_INSTANT
from test_helpers.test_users import (
    make_association_officer_headers,
    make_league_secretary_headers,
)
from test_helpers.types import (
    LeagueStatus,
    MatchStatus,
    MemberClass,
    PrizeFundStatus,
    RosterRole,
    SanctionStatus,
)

# The prize and expense split the shared bylaws imply (PRD §3.7): the weekly
# prize share is the dues less the expense portion, and the expense share is
# that portion itself.
_WEEKLY_DUES_CENTS = BASE_BYLAWS["weekly_dues_cents"]
_WEEKLY_EXPENSE_CENTS = BASE_BYLAWS["weekly_expense_cents"]
_WEEKLY_PRIZE_SHARE_CENTS = _WEEKLY_DUES_CENTS - _WEEKLY_EXPENSE_CENTS


def _charter_fresh_league(api: ApiClient) -> Tuple[Any, str, str]:
    """Register the two officers and charter a league, returning the raw
    chartering response so its status and body can both be asserted."""
    fx.set_clock(api, ORG_MEETING_INSTANT)
    secretary_id = fx.register_member(api, "Ann Secretary", MemberClass.ADULT)
    treasurer_id = fx.register_member(api, "Bob Treasurer", MemberClass.ADULT)
    response = api.charter_league(
        f.league_payload(
            secretary_id,
            treasurer_id,
            name="Monday Mixed",
            center_name="Cedar Lanes",
            declared_team_count=2,
            organizational_meeting_at=ORG_MEETING_INSTANT,
        ),
        make_league_secretary_headers(secretary_id),
    )
    return response, secretary_id, treasurer_id


def _row_count(response: Any) -> int:
    """The ``total_count`` a list endpoint reports for the current filters."""
    _, meta = validate_paginated(response)
    return meta["total_count"]


# ─── Member registration (PRD §3.1, §2.4) ──────────────

def test_member_registration_echoes_inputs_and_mints_system_fields(api: ApiClient):
    """Registration echoes the three declared inputs and mints nothing else:
    the national number stays null until a first sanctioning and the sanctioned
    membership count starts at 0, over a server-minted UUID id at version 1.

    Design: Corner/entities/corner_member_creation_returns_declared_and_system_fields
    """
    fx.set_clock(api, ORG_MEETING_INSTANT)
    response = api.register_member(
        f.member_payload("Ivy Novice", MemberClass.YOUTH, email="ivy@bowl.test"),
        make_association_officer_headers(),
    )
    member = validate_success(response, 201)

    assert_envelope(response.json(), "object")
    assert_fields(
        member,
        full_name="Ivy Novice",
        email="ivy@bowl.test",
        member_class=MemberClass.YOUTH.value,
        national_member_number=None,
        sanctioned_membership_count=0,
        version=1,
    )
    assert_identity(member)
    assert_millisecond_instant(member["created_at"], "created_at")


def test_member_read_returns_the_registration_body_unchanged(api: ApiClient):
    """A read mutates nothing, so reading a freshly registered member answers
    200 with every field exactly as the registration response reported it.

    Design: Corner/entities/corner_member_creation_returns_declared_and_system_fields
    """
    fx.set_clock(api, ORG_MEETING_INSTANT)
    created = get_success_data(
        api.register_member(
            f.member_payload("Ivy Novice", MemberClass.YOUTH, email="ivy@bowl.test"),
            make_association_officer_headers(),
        )
    )

    response = api.get_member(created["id"], make_association_officer_headers())
    fetched = validate_success(response, 200)

    assert_envelope(response.json(), "object")
    assert fetched == created, (
        f"the read must return the registered member unchanged: "
        f"created {created}, read {fetched}"
    )


# ─── League defaults before any bylaw is adopted (PRD §3.1) ───

def test_chartered_league_starts_at_forming_with_zeroed_counters(api: ApiClient):
    """Chartering answers 201 with the league at FORMING, version 1 and every
    derived counter at 0, and the declared inputs echoed back unchanged.

    Design: Corner/entities/corner_league_system_and_computed_defaults_before_bylaws
    """
    response, secretary_id, treasurer_id = _charter_fresh_league(api)
    league = validate_success(response, 201)

    assert_envelope(response.json(), "object")
    assert_fields(
        league,
        status=LeagueStatus.FORMING.value,
        version=1,
        total_weeks=0,
        sanctioned_member_count=0,
        confirmed_team_count=0,
        certified_week_high_water=0,
        declared_team_count=2,
        secretary_member_id=secretary_id,
        treasurer_member_id=treasurer_id,
    )
    assert_identity(league)

    reread = validate_success(
        api.get_league(league["id"], make_league_secretary_headers(secretary_id)), 200
    )
    assert_fields(reread, status=LeagueStatus.FORMING.value, version=1)


def test_chartered_league_carries_every_bylaw_field_null(api: ApiClient):
    """No bylaw field is accepted at chartering, so every bylaw value and the
    bylaw-adoption instant are still null on the freshly chartered league.

    Design: Corner/entities/corner_league_system_and_computed_defaults_before_bylaws
    """
    response, secretary_id, _ = _charter_fresh_league(api)
    league = validate_success(response, 201)

    assert league["bylaws_adopted_at"] is None, (
        f"bylaws_adopted_at is set only when bylaws are adopted, "
        f"got {league['bylaws_adopted_at']!r}"
    )
    still_null = {key: league.get(key) for key in BASE_BYLAWS if league.get(key) is not None}
    assert not still_null, f"these bylaw fields should still be null: {still_null}"

    reread = validate_success(
        api.get_league(league["id"], make_league_secretary_headers(secretary_id)), 200
    )
    assert reread["bylaws_adopted_at"] is None
    assert all(reread.get(key) is None for key in BASE_BYLAWS)


# ─── Membership listing: filters and the pagination envelope (PRD §2.3, §4) ───

def test_membership_listing_filters_narrow_the_matching_set(api: ApiClient):
    """The membership listing honours its league, team and sanction-status
    filters, and reports total_count against the filtered set rather than the
    whole table — including a filter that matches nothing at all.

    Design: Corner/entities/corner_membership_listing_filters_and_pagination_envelope
    """
    scn = fx.build_sanctioned_league(api)

    sanctioned_rows, sanctioned_meta = validate_paginated(
        api.list_memberships(
            scn.secretary,
            params={
                "league_id": scn.league_id,
                "sanction_status": SanctionStatus.SANCTIONED.value,
            },
        )
    )
    assert len(sanctioned_rows) == 4, f"expected four sanctioned rows, got {sanctioned_rows}"
    assert sanctioned_meta["total_count"] == 4
    assert sanctioned_meta["has_more"] is False
    assert all(
        row["sanction_status"] == SanctionStatus.SANCTIONED.value for row in sanctioned_rows
    )

    team_rows, team_meta = validate_paginated(
        api.list_memberships(
            scn.secretary, params={"league_id": scn.league_id, "team_id": scn.team_ids[0]}
        )
    )
    assert team_meta["total_count"] == 2
    assert [row["team_id"] for row in team_rows] == [scn.team_ids[0], scn.team_ids[0]]

    empty_rows, empty_meta = validate_paginated(
        api.list_memberships(
            scn.secretary,
            params={
                "league_id": scn.league_id,
                "sanction_status": SanctionStatus.UNSANCTIONED.value,
            },
        )
    )
    assert empty_rows == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False


def test_membership_listing_window_reports_limit_offset_and_has_more(api: ApiClient):
    """A window taking the trailing rows of a four-row filtered set returns
    exactly those rows, echoes its own limit and offset, keeps total_count at
    the pre-window figure and reports has_more false because nothing remains.

    Design: Corner/entities/corner_membership_listing_filters_and_pagination_envelope
    """
    scn = fx.build_sanctioned_league(api)

    all_rows, all_meta = validate_paginated(
        api.list_memberships(scn.secretary, params={"league_id": scn.league_id})
    )
    assert_pagination_meta(all_meta, limit=10, offset=0, total_count=4, has_more=False)

    window_rows, window_meta = validate_paginated(
        api.list_memberships(
            scn.secretary, params={"league_id": scn.league_id, "limit": 2, "offset": 2}
        )
    )
    assert_pagination_meta(window_meta, limit=2, offset=2, total_count=4, has_more=False)
    assert [row["id"] for row in window_rows] == [row["id"] for row in all_rows[2:]]

    first_page_rows, first_page_meta = validate_paginated(
        api.list_memberships(
            scn.secretary, params={"league_id": scn.league_id, "limit": 2, "offset": 0}
        )
    )
    assert_pagination_meta(first_page_meta, limit=2, offset=0, total_count=4, has_more=True)
    assert [row["id"] for row in first_page_rows] == [row["id"] for row in all_rows[:2]]


def test_membership_listing_envelope_agrees_with_the_league_counter(api: ApiClient):
    """A list response carries the array envelope with its generated request id
    and timestamp, and the league's own sanctioned member count agrees with the
    number of sanctioned membership rows the listing reports.

    Design: Corner/entities/corner_membership_listing_filters_and_pagination_envelope
    """
    scn = fx.build_sanctioned_league(api)

    response = api.list_memberships(
        scn.secretary,
        params={
            "league_id": scn.league_id,
            "sanction_status": SanctionStatus.SANCTIONED.value,
        },
    )
    rows, meta = validate_paginated(response)
    assert_envelope(response.json(), "array")
    assert meta["total_count"] == len(rows) == 4
    assert scn.league()["sanctioned_member_count"] == meta["total_count"]


# ─── Typed not-found codes on the read surfaces (PRD §2.6 check 4, §5) ───

def test_reads_of_unknown_ids_return_each_resource_own_not_found_code(
    sanctioned_league: fx.Scenario, officer: Dict[str, str]
):
    """Each read resolves its own path parameter and answers with the 404 code
    belonging to that resource family, never a neighbour's code, even though the
    database holds live members, leagues, teams and memberships.

    Design: Corner/entities/corner_get_with_unknown_ids_returns_typed_not_found
    """
    api = sanctioned_league.api

    member_response = api.get_member(NON_EXISTENT_UUID, officer)
    validate_error(member_response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)
    assert_envelope(member_response.json(), "error")

    league_response = api.get_league(NON_EXISTENT_UUID, officer)
    validate_error(league_response, ApiErrorId.ERR_LEAGUE_NOT_FOUND.value)
    assert_envelope(league_response.json(), "error")

    team_response = api.get_team(NON_EXISTENT_UUID, officer)
    validate_error(team_response, ApiErrorId.ERR_TEAM_NOT_FOUND.value)
    assert_envelope(team_response.json(), "error")

    membership_response = api.get_membership(NON_EXISTENT_UUID, officer)
    validate_error(membership_response, ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND.value)
    assert_envelope(membership_response.json(), "error")

    # The live rows are still readable, so the misses were genuine misses.
    validate_success(api.get_league(sanctioned_league.league_id, officer), 200)
    validate_success(api.get_team(sanctioned_league.team_ids[0], officer), 200)


def test_action_and_deep_reads_of_unknown_ids_return_typed_not_found(
    certified_match: fx.Scenario, officer: Dict[str, str]
):
    """The remittance, lane-pair, lineup-slot and dues-payment reads each own a
    distinct 404 code, and none of them is collapsed into a neighbour's.

    Design: Corner/entities/corner_action_path_unknown_ids_return_typed_not_found
    """
    api = certified_match.api

    validate_error(
        api.get_fee_remittance(NON_EXISTENT_UUID, officer),
        ApiErrorId.ERR_FEE_REMITTANCE_NOT_FOUND.value,
    )
    validate_error(
        api.get_lane_pair(NON_EXISTENT_UUID, officer),
        ApiErrorId.ERR_LANE_PAIR_NOT_FOUND.value,
    )
    validate_error(
        api.get_series_entry(NON_EXISTENT_UUID, officer),
        ApiErrorId.ERR_SERIES_ENTRY_NOT_FOUND.value,
    )
    validate_error(
        api.get_dues_payment(NON_EXISTENT_UUID, officer),
        ApiErrorId.ERR_DUES_PAYMENT_NOT_FOUND.value,
    )


def test_certify_on_unknown_match_is_not_found_before_any_state_check(
    certified_match: fx.Scenario
):
    """Path-resource existence is resolved before the match-state check, so
    certifying a match that does not exist answers the match not-found code
    rather than the state code, and the real certified match is untouched.

    Design: Corner/entities/corner_action_path_unknown_ids_return_typed_not_found
    """
    scn = certified_match
    response = scn.api.certify_match(NON_EXISTENT_UUID, {}, scn.secretary)
    validate_error(response, ApiErrorId.ERR_MATCH_NOT_FOUND.value)
    assert_envelope(response.json(), "error")

    assert scn.match(0)["status"] == MatchStatus.CERTIFIED.value


def test_prize_and_award_reads_of_unknown_ids_return_typed_not_found(
    certified_match: fx.Scenario, officer: Dict[str, str]
):
    """The prize fund and the honor-score application each answer with their own
    404 code when the identifier on the path resolves to nothing.

    Design: Corner/entities/corner_prize_and_award_and_protest_unknown_ids_return_typed_not_found
    """
    api = certified_match.api

    fund_response = api.get_prize_fund(NON_EXISTENT_UUID, officer)
    validate_error(fund_response, ApiErrorId.ERR_PRIZE_FUND_NOT_FOUND.value)
    assert_envelope(fund_response.json(), "error")

    application_response = api.get_award_application(NON_EXISTENT_UUID, officer)
    validate_error(
        application_response, ApiErrorId.ERR_AWARD_APPLICATION_NOT_FOUND.value
    )
    assert_envelope(application_response.json(), "error")


def test_award_reversal_and_protest_review_on_unknown_ids_precede_state_checks(
    certified_match: fx.Scenario
):
    """Reversing an award and opening a hearing both resolve the path first, so
    an unknown identifier answers the resource's 404 code rather than the fund
    or protest state code, and the league's one prize fund is undisturbed.

    Design: Corner/entities/corner_prize_and_award_and_protest_unknown_ids_return_typed_not_found
    """
    scn = certified_match

    validate_error(
        scn.api.reverse_award(
            NON_EXISTENT_UUID, f.reversal_payload("No such award."), scn.treasurer
        ),
        ApiErrorId.ERR_PRIZE_AWARD_NOT_FOUND.value,
    )
    validate_error(
        scn.api.review_protest(NON_EXISTENT_UUID, f.review_payload(), scn.secretary),
        ApiErrorId.ERR_PROTEST_NOT_FOUND.value,
    )

    funds, meta = validate_paginated(
        scn.api.list_prize_funds(scn.secretary, params={"league_id": scn.league_id})
    )
    assert meta["total_count"] == 1, "chartering creates exactly one prize fund"
    assert funds[0]["status"] == PrizeFundStatus.ACCUMULATING.value


# ─── Required inputs are enforced before any write (PRD §2.6 check 9) ───

def test_enrolment_without_roster_role_is_rejected_and_writes_nothing(
    league: fx.Scenario
):
    """A roster role is a declared input of enrolment, so an enrolment that omits
    it is a malformed request and no membership row is created.

    Design: Corner/entities/corner_missing_required_inputs_rejected_before_any_write
    """
    scn = league
    payload = f.membership_payload(
        scn.league_id,
        scn.secretary_member_id,
        team_id=scn.team_ids[0],
        prior_season_average=150,
        prior_season_games=30,
    )
    payload.pop("roster_role")

    response = scn.api.create_membership(payload, scn.secretary)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert_envelope(response.json(), "error")

    assert _row_count(
        scn.api.list_memberships(scn.secretary, params={"league_id": scn.league_id})
    ) == 4, "the rejected enrolment must not have created a membership"


def test_team_entry_without_a_name_is_rejected_and_writes_nothing(league: fx.Scenario):
    """A team is entered with a league and a name, so an entry that carries no
    name is refused as a malformed request and the league's team count stands.

    Design: Corner/entities/corner_missing_required_inputs_rejected_before_any_write
    """
    scn = league
    response = scn.api.create_team({"league_id": scn.league_id}, scn.secretary)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    assert _row_count(scn.api.list_league_teams(scn.league_id, scn.secretary)) == 2, (
        "the rejected team entry must not have created a team"
    )


def test_remittance_draft_with_an_empty_membership_list_is_rejected(league: fx.Scenario):
    """An array input may not be empty, and a remittance lists between one and
    sixty memberships, so an empty list is a malformed request that drafts
    nothing at all.

    Design: Corner/entities/corner_missing_required_inputs_rejected_before_any_write
    """
    scn = league
    response = scn.api.create_fee_remittance(
        f.fee_remittance_payload(scn.league_id, [], 0), scn.treasurer
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    assert _row_count(
        scn.api.list_fee_remittances(scn.treasurer, params={"league_id": scn.league_id})
    ) == 0, "the rejected draft must not have created a remittance"


# ─── Type, range and cross-field constraints (PRD §2.6 check 9, §2.7) ───

def test_undeclared_enum_and_negative_integer_inputs_are_rejected(league: fx.Scenario):
    """Range and enum constraints are enforced independently of presence: a
    member class outside the two declared values, and a prior-season average
    below the declared floor of zero, are both malformed requests.

    Design: Corner/entities/corner_type_constraints_reject_bad_enum_negative_and_incoherent_bylaws
    """
    scn = league
    enum_response = scn.api.register_member(
        f.member_payload("Sam Senior", "SENIOR", email="sam@bowl.test"),
        scn.officer,
    )
    validate_error(enum_response, ApiErrorId.ERR_INVALID_REQUEST.value)

    negative_response = scn.api.create_membership(
        f.membership_payload(
            scn.league_id,
            scn.secretary_member_id,
            team_id=scn.team_ids[0],
            roster_role=RosterRole.REGULAR,
            prior_season_average=-5,
            prior_season_games=30,
        ),
        scn.secretary,
    )
    validate_error(negative_response, ApiErrorId.ERR_INVALID_REQUEST.value)

    assert _row_count(
        scn.api.list_memberships(scn.secretary, params={"league_id": scn.league_id})
    ) == 4


def test_bylaw_weights_that_do_not_sum_to_one_are_rejected(league: fx.Scenario):
    """The prize place weights must sum to exactly 1.00, so an amendment whose
    weights sum short is refused and not one bylaw field of the league moves.

    Design: Corner/entities/corner_type_constraints_reject_bad_enum_negative_and_incoherent_bylaws
    """
    scn = league
    before = scn.league()

    response = scn.api.adopt_bylaws(
        scn.league_id,
        f.bylaws_payload(before["version"], prize_place_weights=[0.60, 0.30]),
        scn.secretary,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    after = scn.league()
    assert after["version"] == before["version"], "a refused amendment moves no version"
    assert after["prize_place_weights"] == BASE_BYLAWS["prize_place_weights"]
    assert after["bylaws_adopted_at"] == before["bylaws_adopted_at"]


def test_bylaw_legal_minimum_above_lineup_positions_is_rejected(league: fx.Scenario):
    """The legal lineup minimum may not exceed the number of lineup positions, so
    an amendment breaking that coherence rule leaks no partial bylaw write.

    Design: Corner/entities/corner_type_constraints_reject_bad_enum_negative_and_incoherent_bylaws
    """
    scn = league
    before = scn.league()

    response = scn.api.adopt_bylaws(
        scn.league_id,
        f.bylaws_payload(before["version"], lineup_positions=2, legal_lineup_minimum=3),
        scn.secretary,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    after = scn.league()
    assert after["version"] == before["version"]
    assert_fields(
        after,
        legal_lineup_minimum=BASE_BYLAWS["legal_lineup_minimum"],
        lineup_positions=BASE_BYLAWS["lineup_positions"],
        status=LeagueStatus.BYLAWS_ADOPTED.value,
    )


# ─── The one immutable resource (PRD §2.4, §3.7) ────────

def test_dues_payment_carries_no_version_and_no_updated_at(
    certified_match: fx.Scenario
):
    """A weekly dues payment is immutable: it answers 201 with the bylaw-derived
    prize and expense split over only an id and a creation instant, carrying
    neither an update instant nor a version, on creation and on re-read alike.

    Design: Corner/entities/corner_dues_payment_is_immutable_with_no_version_field
    """
    scn = certified_match
    response = scn.api.record_dues_payment(
        scn.membership_ids[0],
        f.dues_payload(1, _WEEKLY_DUES_CENTS),
        scn.treasurer,
    )
    created = validate_success(response, 201)

    assert_envelope(response.json(), "object")
    assert_identity(created, versioned=False)
    assert "version" not in created, "an immutable dues payment carries no version"
    assert "updated_at" not in created, "an immutable dues payment carries no updated_at"
    assert_cents(created["amount_cents"], _WEEKLY_DUES_CENTS, "amount_cents")
    assert_cents(created["prize_share_cents"], _WEEKLY_PRIZE_SHARE_CENTS, "prize_share_cents")
    assert_cents(
        created["expense_share_cents"], _WEEKLY_EXPENSE_CENTS, "expense_share_cents"
    )
    assert_fields(created, membership_id=scn.membership_ids[0], week_number=1)

    fetched = validate_success(scn.api.get_dues_payment(created["id"], scn.treasurer), 200)
    assert_identity(fetched, versioned=False)
    assert fetched == created, (
        f"the read must return the recorded payment unchanged: {created} vs {fetched}"
    )


def test_dues_payment_listing_and_membership_figures_follow_the_payment(
    certified_match: fx.Scenario
):
    """The filtered dues listing finds exactly the recorded payment, and the
    paying membership's dues total rises by the tender while its arrears count
    falls to nothing, week one being the only settled week.

    Design: Corner/entities/corner_dues_payment_is_immutable_with_no_version_field
    """
    scn = certified_match
    created = get_success_data(
        scn.api.record_dues_payment(
            scn.membership_ids[0], f.dues_payload(1, _WEEKLY_DUES_CENTS), scn.treasurer
        )
    )

    rows, meta = validate_paginated(
        scn.api.list_dues_payments(
            scn.treasurer,
            params={"membership_id": scn.membership_ids[0], "week_number": 1},
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0] == created

    membership = scn.membership(0)
    assert_cents(membership["dues_paid_cents"], _WEEKLY_DUES_CENTS, "dues_paid_cents")
    assert membership["dues_arrears_weeks"] == 0, (
        "week one is the only settled week and it has been paid"
    )


# ─── Body-carried parent references (PRD §2.6 check 5) ───

def test_team_entry_under_an_unknown_league_is_league_not_found(league: fx.Scenario):
    """A team's league reference is resolved from the body before any officer or
    state check, so an unknown league yields the league not-found code and no
    team is entered.

    Design: Corner/entities/corner_child_creation_under_unknown_parent_league
    """
    scn = league
    response = scn.api.create_team(
        f.team_payload(NON_EXISTENT_UUID, "Ghost Team"), scn.secretary
    )
    validate_error(response, ApiErrorId.ERR_LEAGUE_NOT_FOUND.value)
    assert_envelope(response.json(), "error")

    assert _row_count(scn.api.list_league_teams(scn.league_id, scn.secretary)) == 2


def test_enrolment_under_an_unknown_member_is_member_not_found(league: fx.Scenario):
    """Body references are resolved in the order the inputs are declared, so an
    enrolment whose league resolves but whose member does not yields the member
    not-found code rather than the league's.

    Design: Corner/entities/corner_child_creation_under_unknown_parent_league
    """
    scn = league
    response = scn.api.create_membership(
        f.membership_payload(
            scn.league_id,
            NON_EXISTENT_UUID,
            team_id=scn.team_ids[0],
            roster_role=RosterRole.REGULAR,
            prior_season_average=150,
            prior_season_games=30,
        ),
        scn.secretary,
    )
    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)

    assert _row_count(
        scn.api.list_memberships(scn.secretary, params={"league_id": scn.league_id})
    ) == 4


def test_lane_pair_registration_under_an_unknown_league_is_league_not_found(
    league: fx.Scenario
):
    """Lane-pair registration resolves its league reference from the body too, so
    an unknown league yields the league not-found code and the league's existing
    pair remains the only one.

    Design: Corner/entities/corner_child_creation_under_unknown_parent_league
    """
    scn = league
    response = scn.api.register_lane_pair(
        f.lane_pair_payload(NON_EXISTENT_UUID, pair_number=9), scn.officer
    )
    validate_error(response, ApiErrorId.ERR_LEAGUE_NOT_FOUND.value)

    assert _row_count(
        scn.api.list_lane_pairs(scn.officer, params={"league_id": scn.league_id})
    ) == 1
