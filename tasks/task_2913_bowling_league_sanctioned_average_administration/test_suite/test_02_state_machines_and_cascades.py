"""State machines that are not straight lines, and cascades that reach four
entities deep.

Two families of PRD behaviour live here.  The first is non-linearity: a
`Membership` carries two independent state axes on one row, and a national
rejection drives them apart before a re-filing drives them back together; a
`Protest` is a cyclic machine whose exit to the association is gated on the
number of hearings that have been opened.  The second is transitivity: one
national acceptance walks FeeRemittance -> Membership -> Team -> League ->
Match, and one certification walks SeriesEntry -> Membership -> Team -> League,
in both cases touching rows whose identifiers appear nowhere in the request.
"""
from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing.validators import validate_error, validate_success

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
)
from test_helpers.constants import WEEK1_STARTS_AT
from test_helpers.types import (
    AverageStatus,
    FeeRemittanceStatus,
    LeagueStatus,
    MatchStatus,
    MembershipRemittanceStatus,
    ProtestCategory,
    ProtestDecision,
    ProtestStatus,
    Remedy,
    SanctionStatus,
    TeamStatus,
)

# ─── local reads, validated rather than lenient ─────────
# The layered builders use the lenient setup validator; every read a test
# asserts on goes through ``validate_success`` so a wrong success status is
# caught where it matters.


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


def _remittance(scn: fx.Scenario, remittance_id: str) -> Dict[str, Any]:
    return validate_success(
        scn.api.get_fee_remittance(remittance_id, scn.secretary)
    )


def _protest(scn: fx.Scenario, protest_id: str) -> Dict[str, Any]:
    return validate_success(scn.api.get_protest(protest_id, scn.secretary))


# ─── local scenario shapes the shared builders stop short of ───


def _submitted_remittance(api: ApiClient) -> Tuple[fx.Scenario, str]:
    """A league at BYLAWS_ADOPTED whose whole roster sits on one SUBMITTED
    remittance, so every membership stands at (PENDING_REMITTANCE, INVOICED)
    and no team, league or match counter has moved yet."""
    scn = fx.build_league(api)
    remittance_id = fx.open_remittance(scn)
    fx.submit_remittance(scn, remittance_id)
    return scn, remittance_id


def _reject(scn: fx.Scenario, remittance_id: str, reason: str) -> Dict[str, Any]:
    return validate_success(
        scn.api.record_national_decision(
            remittance_id, f.national_reject_payload(reason), scn.officer
        )
    )


def _accept(scn: fx.Scenario, remittance_id: str, receipt: str) -> Dict[str, Any]:
    return validate_success(
        scn.api.record_national_decision(
            remittance_id, f.national_accept_payload(receipt), scn.officer
        )
    )


def _scores_entered_match(api: ApiClient) -> fx.Scenario:
    """Week one bowled but not yet certified: the match sits at SCORES_ENTERED
    with both sides' pins recorded and nothing certified anywhere."""
    scn = fx.build_open_match(api)
    fx.enter_scores(scn, fx.score_entries_for(scn, 0), 0)
    return scn


def _filed_protest(api: ApiClient) -> Tuple[fx.Scenario, str]:
    """A certified week-one match with a SCORE_ERROR protest filed against it by
    a sanctioned bowler who is not the league secretary."""
    scn = fx.build_certified_match(api)
    data = validate_success(
        scn.api.file_protest(
            f.protest_payload(
                scn.league_id,
                scn.membership_ids[0],
                ProtestCategory.SCORE_ERROR,
                protest_note="Game 3 pinfall for position 2 was posted 10 pins high",
                match_id=scn.match_ids[0],
            ),
            scn.bowler(0),
        ),
        201,
    )
    return scn, data["id"]


def _review(scn: fx.Scenario, protest_id: str) -> Dict[str, Any]:
    return validate_success(
        scn.api.review_protest(protest_id, f.review_payload(), scn.secretary)
    )


def _rule(
    scn: fx.Scenario, protest_id: str, decision: ProtestDecision, note: str
) -> Any:
    return scn.api.rule_on_protest(
        protest_id, f.ruling_payload(decision.value, ruling_note=note), scn.secretary
    )


def _slots_by_membership(scn: fx.Scenario) -> Dict[str, Dict[str, Any]]:
    rows: List[Dict[str, Any]] = validate_success(
        scn.api.list_series_entries(
            scn.secretary, params={"match_id": scn.match_ids[0], "limit": 100}
        )
    )
    return {row["membership_id"]: row for row in rows if row.get("membership_id")}


# ══════════════════════════════════════════════════════════
# Membership's two axes: they diverge on a rejection and rejoin on a re-filing
# ══════════════════════════════════════════════════════════

_REJECTION_REASON = "Member roster page missing from the filing"


def test_national_rejection_drives_the_two_membership_axes_apart(api: ApiClient):
    """A REJECT decision runs the inverse of hop 1 only: every listed membership
    falls back PENDING_REMITTANCE -> UNSANCTIONED on the sanction axis while it
    advances INVOICED -> REFUNDED on the money axis, so one row stands at a pair
    of values no creation path produces — enrolment always yields UNSANCTIONED
    with UNPAID.  The handicap the pending sanctioning would have granted is
    forced back to 0, and the remittance itself records the reason.

    Design: Difficulty/non_linear_state_machine/membership_two_axes_diverge_through_rejection_and_refiling
    """
    scn, remittance_id = _submitted_remittance(api)
    for index in range(4):
        assert_membership_axes(
            _membership(scn, index),
            SanctionStatus.PENDING_REMITTANCE,
            MembershipRemittanceStatus.INVOICED,
        )

    _reject(scn, remittance_id, _REJECTION_REASON)

    for index in range(4):
        membership = _membership(scn, index)
        assert_membership_axes(
            membership,
            SanctionStatus.UNSANCTIONED,
            MembershipRemittanceStatus.REFUNDED,
        )
        assert_fields(membership, handicap_per_game=0)

    remittance = _remittance(scn, remittance_id)
    assert_fields(
        remittance,
        status=FeeRemittanceStatus.REJECTED.value,
        rejection_reason=_REJECTION_REASON,
        national_receipt_no=None,
        member_count=4,
    )


def test_rejection_moves_no_team_league_or_match_row(api: ApiClient):
    """The rejection runs the inverse of hop 1 and of nothing else, precisely
    because none of the listed rows ever reached SANCTIONED: both teams stay
    PROVISIONAL with a sanctioned roster count of 0, the league keeps
    sanctioned_member_count and confirmed_team_count at 0 and stays at
    BYLAWS_ADOPTED, and every scheduled match stays in DRAFT.

    Design: Difficulty/non_linear_state_machine/membership_two_axes_diverge_through_rejection_and_refiling
    """
    scn, remittance_id = _submitted_remittance(api)

    _reject(scn, remittance_id, _REJECTION_REASON)

    for team_index in (0, 1):
        assert_fields(
            _team(scn, team_index),
            status=TeamStatus.PROVISIONAL.value,
            sanctioned_roster_count=0,
            team_handicap_per_game=0,
        )
    assert_fields(
        _league(scn),
        status=LeagueStatus.BYLAWS_ADOPTED.value,
        sanctioned_member_count=0,
        confirmed_team_count=0,
    )
    for match_index in range(len(scn.match_ids)):
        assert_fields(_match(scn, match_index), status=MatchStatus.DRAFT.value)


def test_refiling_a_rejected_remittance_returns_both_axes_to_the_pending_pair(
    api: ApiClient,
):
    """Submission is legal from REJECTED as well as from DRAFT, and that
    re-filing loop drives the same row back through the pending pair: the money
    axis moves REFUNDED -> INVOICED while the sanction axis repeats
    UNSANCTIONED -> PENDING_REMITTANCE.  The re-filing re-prices the remittance
    against the current clock, which is still inside the twenty-one-day grace
    period, so the penalty stays at 0.

    Design: Difficulty/non_linear_state_machine/membership_two_axes_diverge_through_rejection_and_refiling
    """
    scn, remittance_id = _submitted_remittance(api)
    _reject(scn, remittance_id, _REJECTION_REASON)
    expected_total = fx.expected_remittance_cents(scn, scn.membership_ids)

    data = validate_success(
        scn.api.submit_fee_remittance(
            remittance_id,
            f.remittance_submit_payload(expected_total),
            scn.treasurer,
        )
    )

    assert_fields(data, status=FeeRemittanceStatus.SUBMITTED.value)
    remittance = _remittance(scn, remittance_id)
    assert_fields(remittance, status=FeeRemittanceStatus.SUBMITTED.value)
    assert_cents(remittance["computed_amount_cents"], expected_total, "computed_amount_cents")
    assert_cents(remittance["penalty_cents"], 0, "penalty_cents")
    for index in range(4):
        assert_membership_axes(
            _membership(scn, index),
            SanctionStatus.PENDING_REMITTANCE,
            MembershipRemittanceStatus.INVOICED,
        )


def test_acceptance_after_a_refiling_lands_both_axes_on_the_sanctioned_pair(
    api: ApiClient,
):
    """The loop closes where the first filing would have: the acceptance of the
    re-filed remittance moves every listed membership PENDING_REMITTANCE ->
    SANCTIONED and INVOICED -> REMITTED, grants each one the handicap its basis
    average entitles it to under the adopted bylaws, and drives the league's
    sanctioned member count to four and the league itself to SANCTIONED.

    Design: Difficulty/non_linear_state_machine/membership_two_axes_diverge_through_rejection_and_refiling
    """
    scn, remittance_id = _submitted_remittance(api)
    _reject(scn, remittance_id, _REJECTION_REASON)
    fx.submit_remittance(
        scn, remittance_id, fx.expected_remittance_cents(scn, scn.membership_ids)
    )

    _accept(scn, remittance_id, "NR-2913-0004")

    expected_handicaps = (36, 22, 45, 54)
    for index, handicap in enumerate(expected_handicaps):
        membership = _membership(scn, index)
        assert_membership_axes(
            membership,
            SanctionStatus.SANCTIONED,
            MembershipRemittanceStatus.REMITTED,
        )
        assert_fields(membership, handicap_per_game=handicap)
    assert_fields(
        _remittance(scn, remittance_id),
        status=FeeRemittanceStatus.ACCEPTED.value,
        national_receipt_no="NR-2913-0004",
        rejection_reason=None,
    )
    assert_fields(
        _league(scn),
        status=LeagueStatus.SANCTIONED.value,
        sanctioned_member_count=4,
    )


# ══════════════════════════════════════════════════════════
# The protest hearing cycle, and the loop counter that unlocks escalation
# ══════════════════════════════════════════════════════════


def test_first_hearing_moves_a_filed_protest_under_review_at_round_one(api: ApiClient):
    """Filing creates the protest at FILED with review_round 0 and remedy NONE.
    Opening a hearing is legal from FILED, belongs to the secretary who did not
    file, moves the protest to UNDER_REVIEW and increments review_round by 1,
    because review_round counts how many hearings have been opened.

    Design: Difficulty/non_linear_state_machine/protest_review_remand_cycle_unlocks_escalation_at_round_two
    """
    scn, protest_id = _filed_protest(api)
    assert_fields(
        _protest(scn, protest_id),
        status=ProtestStatus.FILED.value,
        review_round=0,
        remedy=Remedy.NONE.value,
        category=ProtestCategory.SCORE_ERROR.value,
        ruling_note=None,
        association_ruling=None,
    )

    data = _review(scn, protest_id)

    assert_fields(data, status=ProtestStatus.UNDER_REVIEW.value, review_round=1)
    assert_fields(
        _protest(scn, protest_id),
        status=ProtestStatus.UNDER_REVIEW.value,
        review_round=1,
    )


def test_escalation_is_refused_while_the_loop_counter_still_reads_one(api: ApiClient):
    """A SCORE_ERROR protest may only be escalated once review_round has reached
    at least 2; escalation without a second hearing is not open to it, since only
    a RULES_INTERPRETATION question may leave the league at the first hearing.
    The refused ruling changes nothing: the protest is still UNDER_REVIEW at
    review_round 1, with no ruling_note recorded.

    Design: Difficulty/non_linear_state_machine/protest_review_remand_cycle_unlocks_escalation_at_round_two
    """
    scn, protest_id = _filed_protest(api)
    _review(scn, protest_id)

    response = _rule(
        scn,
        protest_id,
        ProtestDecision.ESCALATE,
        "Premature escalation attempt at the first hearing",
    )

    validate_error(response, ApiErrorId.ERR_PROTEST_STATE_INVALID.value)
    assert_fields(
        _protest(scn, protest_id),
        status=ProtestStatus.UNDER_REVIEW.value,
        review_round=1,
        ruling_note=None,
    )


def test_remand_sends_the_protest_back_without_touching_the_match(api: ApiClient):
    """REMAND moves the protest to REMANDED to await a further hearing, records
    the rationale the decision requires, leaves review_round where the hearing
    that has already happened put it, and changes no match state at all.

    Design: Difficulty/non_linear_state_machine/protest_review_remand_cycle_unlocks_escalation_at_round_two
    """
    scn, protest_id = _filed_protest(api)
    _review(scn, protest_id)
    note = "Scorer unavailable; remanded for a second hearing"

    data = validate_success(_rule(scn, protest_id, ProtestDecision.REMAND, note))

    assert_fields(
        data,
        status=ProtestStatus.REMANDED.value,
        review_round=1,
        ruling_note=note,
        remedy=Remedy.NONE.value,
    )
    match = _match(scn, 0)
    assert_fields(match, status=MatchStatus.CERTIFIED.value)
    assert_points(match["home_points"], 4.0, "home_points")


def test_second_hearing_raises_the_counter_and_unlocks_escalation(api: ApiClient):
    """The only exit from REMANDED is a further hearing, which is legal from
    REMANDED and drives review_round from 1 to 2.  The very ruling that was
    refused at round 1 now succeeds: the protest moves UNDER_REVIEW ->
    ESCALATED, passing jurisdiction to the association, and carries the remedy
    NONE it was created with.

    Design: Difficulty/non_linear_state_machine/protest_review_remand_cycle_unlocks_escalation_at_round_two
    """
    scn, protest_id = _filed_protest(api)
    _review(scn, protest_id)
    validate_success(
        _rule(
            scn,
            protest_id,
            ProtestDecision.REMAND,
            "Scorer unavailable; remanded for a second hearing",
        )
    )

    reopened = _review(scn, protest_id)
    assert_fields(
        reopened, status=ProtestStatus.UNDER_REVIEW.value, review_round=2
    )

    escalated = validate_success(
        _rule(
            scn,
            protest_id,
            ProtestDecision.ESCALATE,
            "League cannot resolve the pinfall dispute; escalating",
        )
    )
    assert_fields(
        escalated,
        status=ProtestStatus.ESCALATED.value,
        review_round=2,
        remedy=Remedy.NONE.value,
    )


def test_association_ruling_closes_the_cycle_and_disturbs_no_certified_figure(
    api: ApiClient,
):
    """The association's ruling is legal only from ESCALATED and moves the
    protest to the terminal ASSOCIATION_RULED, recording its own
    association_ruling text independently of the league's ruling_note.  A remedy
    of NONE changes nothing, so the protested match keeps its status and its
    points and every bowler keeps the certified games and pins the certification
    granted them.

    Design: Difficulty/non_linear_state_machine/protest_review_remand_cycle_unlocks_escalation_at_round_two
    """
    scn, protest_id = _filed_protest(api)
    _review(scn, protest_id)
    validate_success(
        _rule(
            scn,
            protest_id,
            ProtestDecision.REMAND,
            "Scorer unavailable; remanded for a second hearing",
        )
    )
    _review(scn, protest_id)
    validate_success(
        _rule(
            scn,
            protest_id,
            ProtestDecision.ESCALATE,
            "League cannot resolve the pinfall dispute; escalating",
        )
    )
    ruling_text = "Recorded score stands; no remedy"

    data = validate_success(
        scn.api.association_rule_on_protest(
            protest_id,
            f.association_ruling_payload(ruling_text, remedy=Remedy.NONE.value),
            scn.officer,
        )
    )

    assert_fields(
        data,
        status=ProtestStatus.ASSOCIATION_RULED.value,
        association_ruling=ruling_text,
        remedy=Remedy.NONE.value,
    )
    match = _match(scn, 0)
    assert_fields(match, status=MatchStatus.CERTIFIED.value)
    assert_points(match["home_points"], 4.0, "home_points")
    assert_points(match["away_points"], 0.0, "away_points")
    assert_fields(_membership(scn, 0), certified_games=3, certified_pins=540)


# ══════════════════════════════════════════════════════════
# One national acceptance, four hops deep
# ══════════════════════════════════════════════════════════

_NATIONAL_NUMBER_PREFIX = "NM-"


def _national_sequence(number: Any) -> int:
    """The national member number is the literal prefix NM- followed by a
    zero-padded six-digit sequence; this reads that sequence back out."""
    assert isinstance(number, str), f"national_member_number must be a string, got {number!r}"
    assert number.startswith(_NATIONAL_NUMBER_PREFIX), (
        f"national_member_number must begin {_NATIONAL_NUMBER_PREFIX!r}, got {number!r}"
    )
    digits = number[len(_NATIONAL_NUMBER_PREFIX):]
    assert len(digits) == 6 and digits.isdigit(), (
        f"national_member_number must carry a zero-padded six-digit sequence, got {number!r}"
    )
    return int(digits)


def test_acceptance_cascades_onto_every_listed_membership_and_member(api: ApiClient):
    """Hop 0 and hop 1.  The acceptance moves the remittance SUBMITTED ->
    ACCEPTED and records the national receipt, then advances every listed
    membership PENDING_REMITTANCE -> SANCTIONED and INVOICED -> REMITTED,
    granting each the handicap its basis average earns under the adopted bylaws.
    Each affected member gains a sanctioned membership and, since the number was
    still null, has a national member number minted for it — in ascending
    created_at order of the members reaching their first sanctioning.

    Design: Difficulty/transitive_cascade/remittance_acceptance_cascades_membership_team_league_match
    """
    scn, remittance_id = _submitted_remittance(api)

    data = _accept(scn, remittance_id, "NR-2913-0005")

    assert_fields(
        data,
        status=FeeRemittanceStatus.ACCEPTED.value,
        national_receipt_no="NR-2913-0005",
        rejection_reason=None,
    )
    sequences: List[int] = []
    for index, handicap in enumerate((36, 22, 45, 54)):
        membership = _membership(scn, index)
        assert_membership_axes(
            membership,
            SanctionStatus.SANCTIONED,
            MembershipRemittanceStatus.REMITTED,
        )
        assert_fields(membership, handicap_per_game=handicap)
        member = validate_success(
            scn.api.get_member(scn.member_ids[index], scn.secretary)
        )
        assert_fields(member, sanctioned_membership_count=1)
        sequences.append(_national_sequence(member["national_member_number"]))
    assert sequences == sorted(sequences) and len(set(sequences)) == 4, (
        "national member numbers must be allocated in ascending created_at order "
        f"of the members reaching their first sanctioning, got {sequences}"
    )


def test_acceptance_confirms_both_teams_through_the_membership_hop(api: ApiClient):
    """Hop 2, caused by hop 1 and naming no team in the request.  Each roster
    team's sanctioned_roster_count rises to the two sanctioned bowlers it
    carries, which is the league's legal_lineup_minimum, so both teams move
    PROVISIONAL -> CONFIRMED and recompute their roster team handicap by summing
    the per-bowler handicaps that were floored one bowler at a time.

    Design: Difficulty/transitive_cascade/remittance_acceptance_cascades_membership_team_league_match
    """
    scn, remittance_id = _submitted_remittance(api)

    _accept(scn, remittance_id, "NR-2913-0005")

    assert_fields(
        _team(scn, 0),
        status=TeamStatus.CONFIRMED.value,
        sanctioned_roster_count=2,
        team_handicap_per_game=58,
    )
    assert_fields(
        _team(scn, 1),
        status=TeamStatus.CONFIRMED.value,
        sanctioned_roster_count=2,
        team_handicap_per_game=99,
    )


def test_acceptance_promotes_the_league_when_the_counter_reaches_the_declared_count(
    api: ApiClient,
):
    """Hop 3, caused by hop 2.  The league's confirmed_team_count rises by one
    for each newly confirmed team, and because that counter arrives at the
    declared team count of two inside this very request, the league itself moves
    BYLAWS_ADOPTED -> SANCTIONED.

    Design: Difficulty/transitive_cascade/remittance_acceptance_cascades_membership_team_league_match
    """
    scn, remittance_id = _submitted_remittance(api)
    assert_fields(_league(scn), status=LeagueStatus.BYLAWS_ADOPTED.value)

    _accept(scn, remittance_id, "NR-2913-0005")

    assert_fields(
        _league(scn),
        status=LeagueStatus.SANCTIONED.value,
        confirmed_team_count=2,
        sanctioned_member_count=4,
        declared_team_count=2,
    )


def test_acceptance_promotes_every_draft_match_to_scheduled(api: ApiClient):
    """Hop 4, caused by hop 3 and the furthest reach of the cascade: every match
    of the league still sitting at DRAFT moves to SCHEDULED, which is what makes
    it eligible for a lineup.  No match identifier and no team identifier appears
    anywhere in the national-decision request, and nothing is settled yet, so the
    league's certified week high-water mark still reads 0.

    Design: Difficulty/transitive_cascade/remittance_acceptance_cascades_membership_team_league_match
    """
    scn, remittance_id = _submitted_remittance(api)
    for match_index in range(len(scn.match_ids)):
        assert_fields(_match(scn, match_index), status=MatchStatus.DRAFT.value)

    _accept(scn, remittance_id, "NR-2913-0005")

    assert len(scn.match_ids) == 2, "the shared schedule adopts two weekly matches"
    for match_index in range(len(scn.match_ids)):
        assert_fields(_match(scn, match_index), status=MatchStatus.SCHEDULED.value)
    assert_fields(_league(scn), certified_week_high_water=0, total_weeks=2)


def test_cascade_stops_at_hop_two_when_only_one_team_is_completed(api: ApiClient):
    """The terminal hops are reached only because the counter arrives at the
    declared team count.  Sanctioning just one team's two bowlers confirms that
    team and moves confirmed_team_count to 1, which is short of the declared two,
    so the league stays at BYLAWS_ADOPTED and — hop 4 being caused by hop 3 —
    every match stays in DRAFT.

    Design: Difficulty/transitive_cascade/remittance_acceptance_cascades_membership_team_league_match
    """
    scn = fx.build_league(api)
    first_team_memberships = scn.membership_ids[:2]
    remittance_id = fx.open_remittance(scn, first_team_memberships)
    fx.submit_remittance(scn, remittance_id)

    _accept(scn, remittance_id, "NR-2913-0006")

    assert_fields(
        _team(scn, 0),
        status=TeamStatus.CONFIRMED.value,
        sanctioned_roster_count=2,
        team_handicap_per_game=58,
    )
    assert_fields(
        _team(scn, 1),
        status=TeamStatus.PROVISIONAL.value,
        sanctioned_roster_count=0,
        team_handicap_per_game=0,
    )
    assert_fields(
        _league(scn),
        status=LeagueStatus.BYLAWS_ADOPTED.value,
        confirmed_team_count=1,
        sanctioned_member_count=2,
    )
    for match_index in range(len(scn.match_ids)):
        assert_fields(_match(scn, match_index), status=MatchStatus.DRAFT.value)


# ══════════════════════════════════════════════════════════
# One certification, from the slots out to the league
# ══════════════════════════════════════════════════════════

_CERTIFIED_SCRATCH_SERIES = (540, 720, 480, 450)


def _certify(scn: fx.Scenario) -> Dict[str, Any]:
    return validate_success(scn.api.certify_match(scn.match_ids[0], {}, scn.secretary))


def test_certification_flips_every_slot_and_stamps_the_match(api: ApiClient):
    """Hop 1.  Certification moves the match SCORES_ENTERED -> CERTIFIED, sets
    certified true on every slot of the match and stamps certified_at with the
    current logical-clock instant.  The pins each slot recorded at score entry
    are untouched by the transition, and the four-point scheme computed at score
    entry stands.

    Design: Difficulty/transitive_cascade/certification_cascades_series_entry_membership_team_league
    """
    scn = _scores_entered_match(api)
    for row in _slots_by_membership(scn).values():
        assert_fields(row, certified=False)

    data = _certify(scn)

    assert_fields(data, status=MatchStatus.CERTIFIED.value)
    assert_instant_equals(data["certified_at"], WEEK1_STARTS_AT, "certified_at")
    slots = _slots_by_membership(scn)
    for index, scratch_series in enumerate(_CERTIFIED_SCRATCH_SERIES):
        row = slots[scn.membership_ids[index]]
        assert_fields(
            row,
            certified=True,
            counts_toward_average=True,
            games_recorded=3,
            scratch_series=scratch_series,
        )
    match = _match(scn, 0)
    assert_fields(match, status=MatchStatus.CERTIFIED.value)
    assert_points(match["home_points"], 4.0, "home_points")
    assert_points(match["away_points"], 0.0, "away_points")


def test_certification_recomputes_every_bowlers_average_and_handicap(api: ApiClient):
    """Hop 2, caused by hop 1.  Every membership behind a now-certified
    average-bearing slot recomputes certified_games and certified_pins from those
    slots, and with three certified games against a nine-game minimum each average
    stays PROVISIONAL and is blended with the bowler's declared prior-season
    record before the fraction is discarded.  Each handicap follows from the new
    average, the product floored before the ceiling is applied.

    Design: Difficulty/transitive_cascade/certification_cascades_series_entry_membership_team_league
    """
    scn = _scores_entered_match(api)

    _certify(scn)

    expected = ((180, 36), (199, 18), (169, 45), (159, 54))
    for index, (current_average, handicap) in enumerate(expected):
        assert_fields(
            _membership(scn, index),
            certified_games=3,
            certified_pins=_CERTIFIED_SCRATCH_SERIES[index],
            average_status=AverageStatus.PROVISIONAL.value,
            current_average=current_average,
            handicap_per_game=handicap,
        )


def test_certification_recomputes_teams_without_moving_the_frozen_handicaps(
    api: ApiClient,
):
    """Hop 3, caused by hop 2.  Each affected team recomputes its roster team
    handicap from its bowlers' new handicaps and absorbs the match into
    total_points and total_scratch_pins.  What the recompute must not touch are
    the per-side handicaps frozen onto the match when each lineup was submitted:
    those stay at the values the entering averages produced, which is why the
    home side reports a roster handicap of 54 while the match still reads 58.

    Design: Difficulty/transitive_cascade/certification_cascades_series_entry_membership_team_league
    """
    scn = _scores_entered_match(api)

    _certify(scn)

    home = _team(scn, 0)
    assert_fields(home, total_scratch_pins=1260, team_handicap_per_game=54)
    assert_points(home["total_points"], 4.0, "total_points")
    away = _team(scn, 1)
    assert_fields(away, total_scratch_pins=930, team_handicap_per_game=99)
    assert_points(away["total_points"], 0.0, "total_points")
    assert_fields(
        _match(scn, 0),
        home_team_handicap_per_game=58,
        away_team_handicap_per_game=99,
    )


def test_certification_raises_the_leagues_certified_week_high_water(api: ApiClient):
    """Hop 4, caused by hop 1 and reaching a league row the request never names.
    The high-water mark is the greatest week number at or below which every match
    has settled, so certifying the only week-one match raises it from 0 to 1,
    while week two — still merely SCHEDULED — keeps it from rising further even
    though the season declares two weeks.

    Design: Difficulty/transitive_cascade/certification_cascades_series_entry_membership_team_league
    """
    scn = _scores_entered_match(api)
    assert_fields(_league(scn), certified_week_high_water=0)

    _certify(scn)

    assert_fields(
        _league(scn),
        certified_week_high_water=1,
        total_weeks=2,
        status=LeagueStatus.IN_SEASON.value,
    )
    assert_fields(_match(scn, 1), status=MatchStatus.SCHEDULED.value)
