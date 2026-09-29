"""Corner cases in the ordered refusal chain of PRD §2.6, second half.

Five clusters live here.  The dues surface is guarded by three rules that a
single tiny payload can break all at once, so the order membership state, then
week uniqueness, then amount has to be provoked pair by pair.  The two filing
windows are asserted on their exact closing instant and one second later, from
one and the same `certified_at`.  The honor-score evidence gate is shown to be
about the lane pair rather than the paperwork, since a revoked pair is terminal
and no evidence round can repair it.  Remedy applicability is checked against
the protest's own subject on both the league and the association surface.  And
the insufficient-fund guard is shown to be the only thing between a projected
plan and a negative prize balance.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing.validators import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_identity,
    assert_instant_equals,
    assert_points,
    assert_prize_money_invariant,
    expected_admin_fee_cents,
    expected_award_amounts,
    expected_blended_average,
    expected_reserve_cents,
)
from test_helpers.constants import (
    BASE_BYLAWS,
    HONOR_SCORE_WINDOW_HOURS,
    PROTEST_WINDOW_HOURS,
    SERIES_HANDICAP_FLOOR,
    SERIES_SCRATCH_FLOOR,
    WEEK1_STARTS_AT,
)
from test_helpers.types import (
    AssociationAwardDecision,
    AwardApplicationStatus,
    AwardType,
    BasisVariant,
    LanePairCertificationStatus,
    LeagueStatus,
    LeagueVerificationDecision,
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

# ─── instants derived from the one certified match ──────
# Every window in this module is measured from the week-one match's
# `certified_at`, which the shared builders stamp at WEEK1_STARTS_AT because the
# logical clock stands there when the match is opened, scored and certified.


def _shift(instant: str, *, hours: int = 0, seconds: int = 0) -> str:
    """Move an ISO-8601 instant by whole hours and seconds, keeping UTC."""
    moment = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    moved = moment + timedelta(hours=hours, seconds=seconds)
    return moved.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


PROTEST_DEADLINE = _shift(WEEK1_STARTS_AT, hours=PROTEST_WINDOW_HOURS)
PROTEST_ONE_SECOND_LATE = _shift(PROTEST_DEADLINE, seconds=1)
AWARD_DEADLINE = _shift(WEEK1_STARTS_AT, hours=HONOR_SCORE_WINDOW_HOURS)
AWARD_ONE_SECOND_LATE = _shift(AWARD_DEADLINE, seconds=1)
DISBURSEMENT_INSTANT = "2026-08-26T00:00:00Z"

WEEKLY_DUES_CENTS = BASE_BYLAWS["weekly_dues_cents"]
WEEKLY_EXPENSE_CENTS = BASE_BYLAWS["weekly_expense_cents"]
WEEKLY_PRIZE_SHARE_CENTS = WEEKLY_DUES_CENTS - WEEKLY_EXPENSE_CENTS
PLACE_WEIGHTS: List[float] = list(BASE_BYLAWS["prize_place_weights"])


# ─── reads, validated rather than lenient ───────────────


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


def _fund(scn: fx.Scenario) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = validate_success(
        scn.api.list_prize_funds(scn.treasurer, params={"league_id": scn.league_id})
    )
    assert rows, "chartering must have created exactly one prize fund for the league"
    return rows[0]


def _awards(scn: fx.Scenario) -> List[Dict[str, Any]]:
    return validate_success(
        scn.api.list_prize_awards(
            scn.secretary, params={"prize_fund_id": _fund(scn)["id"], "limit": 100}
        )
    )


def _protest(scn: fx.Scenario, protest_id: str) -> Dict[str, Any]:
    return validate_success(scn.api.get_protest(protest_id, scn.secretary))


def _application(scn: fx.Scenario, application_id: str) -> Dict[str, Any]:
    return validate_success(
        scn.api.get_award_application(application_id, scn.secretary)
    )


def _dues_rows(scn: fx.Scenario, index: int) -> List[Dict[str, Any]]:
    return validate_success(
        scn.api.list_dues_payments(
            scn.treasurer,
            params={"membership_id": scn.membership_ids[index], "limit": 100},
        )
    )


def _slots_by_membership(scn: fx.Scenario) -> Dict[str, Dict[str, Any]]:
    rows: List[Dict[str, Any]] = validate_success(
        scn.api.list_series_entries(
            scn.secretary, params={"match_id": scn.match_ids[0], "limit": 100}
        )
    )
    return {row["membership_id"]: row for row in rows if row.get("membership_id")}


# ─── the three dues gates, in order ─────────────────────
# The dues surface can be broken three ways at once, and §2.6 pins which
# complaint the caller hears: the membership-state check sits at position 21,
# the week-uniqueness check at 45 and the amount check at 47, so state precedes
# uniqueness precedes amount.  To provoke the first pair the league needs one
# bowler who never got sanctioned, and enrolment closes when the league leaves
# BYLAWS_ADOPTED, so the fifth bowler has to be enrolled up front and then left
# out of the remittance.

_UNSANCTIONED_SPEC = fx.RosterSpec("Gus Substitute", MemberClass.ADULT, 175, 30, 0)
_UNSANCTIONED_INDEX = 4


def _league_with_one_unsanctioned_bowler(api: ApiClient) -> fx.Scenario:
    """Week one certified, with a fifth enrolled bowler left UNSANCTIONED."""
    scn = fx.build_league(api, roster=list(fx.DEFAULT_ROSTER) + [_UNSANCTIONED_SPEC])
    fx.sanction(scn, scn.membership_ids[:4])
    fx.submit_both_lineups(scn, 0)
    fx.set_clock(api, WEEK1_STARTS_AT)
    fx.open_match(scn, 0)
    fx.enter_scores(scn, fx.score_entries_for(scn, 0), 0)
    fx.certify_match(scn, 0)
    return scn


def test_dues_membership_state_gate_outranks_the_amount_gate(api: ApiClient) -> None:
    """An unsanctioned bowler tendering the wrong amount hears about the state.

    Both the state rule and the amount rule are broken by the same payload, and
    the ordered chain puts the membership-state check ahead of the money check,
    which runs last of all.

    Design: Corner/validations/corner_dues_gates_run_membership_state_then_week_then_amount
    """
    scn = _league_with_one_unsanctioned_bowler(api)
    membership_id = scn.membership_ids[_UNSANCTIONED_INDEX]

    response = scn.api.record_dues_payment(
        membership_id, f.dues_payload(1, WEEKLY_DUES_CENTS - 300), scn.treasurer
    )
    validate_error(response, ApiErrorId.ERR_MEMBERSHIP_STATE_INVALID.value)

    # A correctly priced tender is refused for exactly the same reason, which is
    # what shows the state gate is not a side effect of the amount comparison.
    validate_error(
        scn.api.record_dues_payment(
            membership_id, f.dues_payload(1, WEEKLY_DUES_CENTS), scn.treasurer
        ),
        ApiErrorId.ERR_MEMBERSHIP_STATE_INVALID.value,
    )

    membership = _membership(scn, _UNSANCTIONED_INDEX)
    assert_fields(
        membership,
        sanction_status=SanctionStatus.UNSANCTIONED.value,
        dues_paid_cents=0,
        dues_arrears_weeks=1,
    )
    assert _dues_rows(scn, _UNSANCTIONED_INDEX) == [], (
        "a refused dues payment must leave no dues-payment row behind"
    )
    fund = _fund(scn)
    assert_cents(fund["collected_prize_cents"], 0, "collected_prize_cents")
    assert_prize_money_invariant(fund)


def test_dues_amount_must_match_the_weekly_bylaw_exactly(api: ApiClient) -> None:
    """A short tender and an over tender are both refused, from a clean state.

    With the membership sanctioned and the week still unpaid, the only broken
    rule left is the amount, so the money check at the very end of the chain is
    the one that speaks.

    Design: Corner/validations/corner_dues_gates_run_membership_state_then_week_then_amount
    """
    scn = fx.build_certified_match(api)
    membership_id = scn.membership_ids[0]

    validate_error(
        scn.api.record_dues_payment(
            membership_id, f.dues_payload(1, WEEKLY_DUES_CENTS - 1), scn.treasurer
        ),
        ApiErrorId.ERR_DUES_AMOUNT_MISMATCH.value,
    )
    validate_error(
        scn.api.record_dues_payment(
            membership_id, f.dues_payload(1, WEEKLY_DUES_CENTS + 1), scn.treasurer
        ),
        ApiErrorId.ERR_DUES_AMOUNT_MISMATCH.value,
    )

    assert _dues_rows(scn, 0) == [], "neither refusal may leave a payment row"
    assert_fields(_membership(scn, 0), dues_paid_cents=0, dues_arrears_weeks=1)
    assert_prize_money_invariant(_fund(scn))


def test_dues_payment_splits_into_prize_and_expense_shares(api: ApiClient) -> None:
    """The accepted tender is an immutable record carrying its own split.

    Design: Corner/validations/corner_dues_gates_run_membership_state_then_week_then_amount
    """
    scn = fx.build_certified_match(api)

    payment = validate_success(
        scn.api.record_dues_payment(
            scn.membership_ids[0],
            f.dues_payload(1, WEEKLY_DUES_CENTS),
            scn.treasurer,
        ),
        201,
    )
    assert_identity(payment, versioned=False)
    assert_fields(payment, week_number=1, membership_id=scn.membership_ids[0])
    assert_cents(payment["amount_cents"], WEEKLY_DUES_CENTS, "amount_cents")
    assert_cents(
        payment["prize_share_cents"], WEEKLY_PRIZE_SHARE_CENTS, "prize_share_cents"
    )
    assert_cents(
        payment["expense_share_cents"], WEEKLY_EXPENSE_CENTS, "expense_share_cents"
    )

    membership = _membership(scn, 0)
    assert_cents(membership["dues_paid_cents"], WEEKLY_DUES_CENTS, "dues_paid_cents")
    assert_fields(membership, dues_arrears_weeks=0)


def test_dues_week_uniqueness_gate_outranks_the_amount_gate(api: ApiClient) -> None:
    """Once a week is paid, a second tender for it never reaches the money check.

    Design: Corner/validations/corner_dues_gates_run_membership_state_then_week_then_amount
    """
    scn = fx.build_certified_match(api)
    membership_id = scn.membership_ids[0]
    fx.pay_dues(scn, 0, 1)

    validate_error(
        scn.api.record_dues_payment(
            membership_id, f.dues_payload(1, WEEKLY_DUES_CENTS - 300), scn.treasurer
        ),
        ApiErrorId.ERR_DUES_WEEK_ALREADY_PAID.value,
    )
    validate_error(
        scn.api.record_dues_payment(
            membership_id, f.dues_payload(1, WEEKLY_DUES_CENTS), scn.treasurer
        ),
        ApiErrorId.ERR_DUES_WEEK_ALREADY_PAID.value,
    )

    rows = _dues_rows(scn, 0)
    assert len(rows) == 1, f"exactly one payment may exist for week 1, got {len(rows)}"
    assert_cents(
        _membership(scn, 0)["dues_paid_cents"], WEEKLY_DUES_CENTS, "dues_paid_cents"
    )


def test_dues_counters_and_fund_follow_every_accepted_week(api: ApiClient) -> None:
    """Two accepted weeks, one paid by the treasurer and one by the bowler.

    Arrears are measured against settled weeks only, so paying week two while
    only week one is settled leaves the bowler at zero arrears, and the bowler
    who has paid nothing sits at one — under the two-week ceiling either way.

    Design: Corner/validations/corner_dues_gates_run_membership_state_then_week_then_amount
    """
    scn = fx.build_certified_match(api)
    fx.pay_dues(scn, 0, 1)

    second = validate_success(
        scn.api.record_dues_payment(
            scn.membership_ids[0], f.dues_payload(2, WEEKLY_DUES_CENTS), scn.bowler(0)
        ),
        201,
    )
    assert_fields(second, week_number=2)
    assert_cents(
        second["prize_share_cents"], WEEKLY_PRIZE_SHARE_CENTS, "prize_share_cents"
    )

    payer = _membership(scn, 0)
    assert_cents(payer["dues_paid_cents"], 2 * WEEKLY_DUES_CENTS, "dues_paid_cents")
    assert_fields(payer, dues_arrears_weeks=0)
    assert len(_dues_rows(scn, 0)) == 2, "both accepted weeks must be listed"

    silent = _membership(scn, 1)
    assert_cents(silent["dues_paid_cents"], 0, "dues_paid_cents")
    assert_fields(silent, dues_arrears_weeks=1)

    fund = _fund(scn)
    assert_cents(
        fund["collected_prize_cents"],
        2 * WEEKLY_PRIZE_SHARE_CENTS,
        "collected_prize_cents",
    )
    assert_cents(
        fund["undistributed_balance_cents"],
        2 * WEEKLY_PRIZE_SHARE_CENTS,
        "undistributed_balance_cents",
    )
    assert_cents(fund["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert_fields(fund, status=PrizeFundStatus.ACCUMULATING.value)
    assert_prize_money_invariant(fund)


# ─── the two filing windows, at the instant they close ──
# Both windows are "no later than" windows measured from one and the same
# `certified_at`, so the closing instant itself is still open and the second
# after it is not.  A protest that cites no match has no window at all, and its
# `deadline_at` is null rather than some far-future instant.


def test_protest_window_is_still_open_at_exactly_seventy_two_hours(
    api: ApiClient,
) -> None:
    """A protest filed on the closing instant is accepted, deadline included.

    Design: Corner/validations/corner_filing_windows_are_inclusive_at_the_hour_and_null_without_a_match
    """
    scn = fx.build_certified_match(api)
    assert_instant_equals(_match(scn)["certified_at"], WEEK1_STARTS_AT, "certified_at")

    fx.set_clock(api, PROTEST_DEADLINE)
    protest = validate_success(
        scn.api.file_protest(
            f.protest_payload(
                scn.league_id,
                scn.membership_ids[2],
                ProtestCategory.SCORE_ERROR,
                match_id=scn.match_ids[0],
            ),
            scn.bowler(2),
        ),
        201,
    )
    assert_identity(protest)
    assert_fields(
        protest,
        status=ProtestStatus.FILED.value,
        review_round=0,
        remedy=Remedy.NONE.value,
        match_id=scn.match_ids[0],
        category=ProtestCategory.SCORE_ERROR.value,
        ruling_note=None,
        association_ruling=None,
    )
    assert_instant_equals(protest["filed_at"], PROTEST_DEADLINE, "filed_at")
    assert_instant_equals(protest["deadline_at"], PROTEST_DEADLINE, "deadline_at")


def test_protest_one_second_past_the_window_is_refused(api: ApiClient) -> None:
    """One second beyond the same instant closes the protest window for good.

    Design: Corner/validations/corner_filing_windows_are_inclusive_at_the_hour_and_null_without_a_match
    """
    scn = fx.build_certified_match(api)
    fx.set_clock(api, PROTEST_ONE_SECOND_LATE)

    validate_error(
        scn.api.file_protest(
            f.protest_payload(
                scn.league_id,
                scn.membership_ids[2],
                ProtestCategory.SCORE_ERROR,
                match_id=scn.match_ids[0],
            ),
            scn.bowler(2),
        ),
        ApiErrorId.ERR_FILING_WINDOW_CLOSED.value,
    )

    rows = validate_success(
        scn.api.list_protests(scn.secretary, params={"league_id": scn.league_id})
    )
    assert rows == [], "a refused filing must create no protest row"


def test_honor_score_window_is_still_open_at_exactly_one_hundred_sixty_eight_hours(
    api: ApiClient,
) -> None:
    """An honor-score claim filed on the closing instant is accepted.

    The handicap-series arithmetic is the slot's scratch series plus three
    games' worth of the handicap frozen onto that slot at lineup submission.

    Design: Corner/validations/corner_filing_windows_are_inclusive_at_the_hour_and_null_without_a_match
    """
    scn = fx.build_certified_match(api)
    slot = _slots_by_membership(scn)[scn.membership_ids[1]]
    expected_claim = slot["scratch_series"] + 3 * slot["handicap_per_game_applied"]
    assert expected_claim >= SERIES_HANDICAP_FLOOR, (
        "the shared score set must clear the handicap-series threshold"
    )

    fx.set_clock(api, AWARD_DEADLINE)
    application = validate_success(
        scn.api.create_award_application(
            f.award_application_payload(
                scn.league_id,
                scn.membership_ids[1],
                slot["id"],
                AwardType.HANDICAP_SERIES_700,
                evidence_note="Scoresheet signed by both captains.",
            ),
            scn.bowler(1),
        ),
        201,
    )
    assert_identity(application)
    assert_fields(
        application,
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=1,
        claimed_pins=expected_claim,
        claimed_game_number=None,
        award_type=AwardType.HANDICAP_SERIES_700.value,
        lane_certification_verified=True,
        sanctioned_at_game_time=True,
        verified_by_user_id=None,
    )


def test_honor_score_one_second_late_hears_about_the_window_not_the_threshold(
    api: ApiClient,
) -> None:
    """A late claim that is also short of its threshold hears about the window.

    The filing-window check sits ahead of the threshold check in the ordered
    chain, so the earlier complaint is the one that decides the response.

    Design: Corner/validations/corner_filing_windows_are_inclusive_at_the_hour_and_null_without_a_match
    """
    scn = fx.build_certified_match(api)
    slot = _slots_by_membership(scn)[scn.membership_ids[0]]
    assert slot["scratch_series"] < SERIES_SCRATCH_FLOOR, (
        "this slot must fall short of the scratch-series threshold too"
    )

    fx.set_clock(api, AWARD_ONE_SECOND_LATE)
    validate_error(
        scn.api.create_award_application(
            f.award_application_payload(
                scn.league_id,
                scn.membership_ids[0],
                slot["id"],
                AwardType.SERIES_800_SCRATCH,
            ),
            scn.bowler(0),
        ),
        ApiErrorId.ERR_FILING_WINDOW_CLOSED.value,
    )

    rows = validate_success(
        scn.api.list_award_applications(
            scn.secretary, params={"league_id": scn.league_id}
        )
    )
    assert rows == [], "a refused claim must create no application row"


def test_protest_citing_no_match_carries_a_null_deadline(api: ApiClient) -> None:
    """A pure rules question has no cited match, so it has no window to miss.

    Filed a full week after the match was certified — long past the seventy-two
    hour mark — it is still accepted, and its `deadline_at` is null.

    Design: Corner/validations/corner_filing_windows_are_inclusive_at_the_hour_and_null_without_a_match
    """
    scn = fx.build_certified_match(api)
    fx.set_clock(api, AWARD_ONE_SECOND_LATE)

    protest = validate_success(
        scn.api.file_protest(
            f.protest_payload(
                scn.league_id,
                scn.membership_ids[2],
                ProtestCategory.RULES_INTERPRETATION,
                protest_note="Does the vacancy rule apply to a two-position lineup?",
            ),
            scn.bowler(2),
        ),
        201,
    )
    assert_fields(
        protest,
        status=ProtestStatus.FILED.value,
        review_round=0,
        remedy=Remedy.NONE.value,
        match_id=None,
        deadline_at=None,
        category=ProtestCategory.RULES_INTERPRETATION.value,
    )
    assert_instant_equals(protest["filed_at"], AWARD_ONE_SECOND_LATE, "filed_at")


# ─── a revoked pair leaves a claim unverifiable ─────────
# The two evidence flags are captured at filing and re-evaluated at
# verification, and revocation is terminal in the strongest sense, so a claim
# on a pair revoked after the game was bowled can never be verified, no matter
# how many evidence rounds the applicant supplies.

_EVIDENCE_NOTE = "Scoresheet, lane audit and both captains' signatures attached."


def _revoked_after_certification(api: ApiClient) -> fx.Scenario:
    """Week one certified, then the lane pair it was bowled on revoked."""
    scn = fx.build_certified_match(api)
    pair = validate_success(
        scn.api.set_lane_pair_certification(
            scn.lane_pair_ids[0], f.revoke_payload(), scn.officer
        )
    )
    assert_fields(
        pair, certification_status=LanePairCertificationStatus.REVOKED.value
    )
    assert pair["revoked_at"] is not None, "revocation must stamp revoked_at"
    return scn


def _file_handicap_series_claim(scn: fx.Scenario) -> Dict[str, Any]:
    """File the claim that the certified series of roster index 1 supports."""
    slot = _slots_by_membership(scn)[scn.membership_ids[1]]
    return validate_success(
        scn.api.create_award_application(
            f.award_application_payload(
                scn.league_id,
                scn.membership_ids[1],
                slot["id"],
                AwardType.HANDICAP_SERIES_700,
                evidence_note=_EVIDENCE_NOTE,
            ),
            scn.bowler(1),
        ),
        201,
    )


def test_claim_filed_after_revocation_captures_the_lane_flag_as_false(
    api: ApiClient,
) -> None:
    """Filing still succeeds; it is the lane flag that records the damage.

    The threshold is met and the bowler is sanctioned, so nothing refuses the
    claim — but `lane_certification_verified` is evaluated against the pair as
    it stands at filing, and that pair has been revoked.

    Design: Corner/validations/corner_revoked_lane_leaves_an_honor_claim_permanently_unverifiable
    """
    scn = _revoked_after_certification(api)
    slot = _slots_by_membership(scn)[scn.membership_ids[1]]
    expected_claim = slot["scratch_series"] + 3 * slot["handicap_per_game_applied"]

    application = _file_handicap_series_claim(scn)
    assert_fields(
        application,
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=1,
        claimed_pins=expected_claim,
        lane_certification_verified=False,
        sanctioned_at_game_time=True,
        verified_by_user_id=None,
        association_ruling_note=None,
    )
    assert expected_claim >= SERIES_HANDICAP_FLOOR, (
        "the claim must clear its threshold, so nothing but the lane is wrong"
    )


def test_verifying_a_claim_on_a_revoked_pair_is_refused(api: ApiClient) -> None:
    """Verification re-reads the flags and refuses on incomplete evidence.

    Design: Corner/validations/corner_revoked_lane_leaves_an_honor_claim_permanently_unverifiable
    """
    scn = _revoked_after_certification(api)
    application = _file_handicap_series_claim(scn)

    validate_error(
        scn.api.league_verify_application(
            application["id"],
            f.league_verification_payload(LeagueVerificationDecision.VERIFY.value),
            scn.secretary,
        ),
        ApiErrorId.ERR_AWARD_EVIDENCE_INCOMPLETE.value,
    )

    unchanged = _application(scn, application["id"])
    assert_fields(
        unchanged,
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=1,
        verified_by_user_id=None,
        lane_certification_verified=False,
    )


def test_no_evidence_round_can_repair_a_revoked_pair(api: ApiClient) -> None:
    """Return and resubmission move the claim around but never past the gate.

    Design: Corner/validations/corner_revoked_lane_leaves_an_honor_claim_permanently_unverifiable
    """
    scn = _revoked_after_certification(api)
    application = _file_handicap_series_claim(scn)

    returned = validate_success(
        scn.api.league_verify_application(
            application["id"],
            f.league_verification_payload(
                LeagueVerificationDecision.RETURN_FOR_EVIDENCE.value,
                evidence_note="Supply the lane certificate covering match night.",
            ),
            scn.secretary,
        )
    )
    assert_fields(
        returned,
        status=AwardApplicationStatus.RETURNED_FOR_EVIDENCE.value,
        round_count=1,
        verified_by_user_id=None,
    )

    resubmitted = validate_success(
        scn.api.resubmit_evidence(
            application["id"],
            f.evidence_payload("The centre's own audit of the pair, dated match day."),
            scn.bowler(1),
        )
    )
    assert_fields(
        resubmitted,
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=2,
        verified_by_user_id=None,
        evidence_note="The centre's own audit of the pair, dated match day.",
    )

    validate_error(
        scn.api.league_verify_application(
            application["id"],
            f.league_verification_payload(LeagueVerificationDecision.VERIFY.value),
            scn.secretary,
        ),
        ApiErrorId.ERR_AWARD_EVIDENCE_INCOMPLETE.value,
    )
    assert_fields(
        _application(scn, application["id"]),
        status=AwardApplicationStatus.SUBMITTED.value,
        round_count=2,
        verified_by_user_id=None,
    )


def test_recertifying_a_revoked_pair_is_itself_refused(api: ApiClient) -> None:
    """The one act that would clear the flag is the one act revocation forbids.

    Design: Corner/validations/corner_revoked_lane_leaves_an_honor_claim_permanently_unverifiable
    """
    scn = _revoked_after_certification(api)
    application = _file_handicap_series_claim(scn)

    validate_error(
        scn.api.set_lane_pair_certification(
            scn.lane_pair_ids[0],
            f.recertify_payload("2027-12-31T00:00:00Z"),
            scn.officer,
        ),
        ApiErrorId.ERR_LANE_PAIR_NOT_CERTIFIED.value,
    )

    pair = validate_success(
        scn.api.get_lane_pair(scn.lane_pair_ids[0], scn.secretary)
    )
    assert_fields(
        pair, certification_status=LanePairCertificationStatus.REVOKED.value
    )
    assert pair["revoked_at"] is not None, "revoked_at is never cleared"

    validate_error(
        scn.api.league_verify_application(
            application["id"],
            f.league_verification_payload(LeagueVerificationDecision.VERIFY.value),
            scn.secretary,
        ),
        ApiErrorId.ERR_AWARD_EVIDENCE_INCOMPLETE.value,
    )


def test_association_cannot_reach_a_claim_that_never_left_submitted(
    api: ApiClient,
) -> None:
    """The association's surface opens only from league-verified, so it is shut.

    The application's own state is checked ahead of the evidence flags, so the
    complaint names the state rather than the evidence.  None of this disturbs
    the certified record the claim was made against.

    Design: Corner/validations/corner_revoked_lane_leaves_an_honor_claim_permanently_unverifiable
    """
    scn = _revoked_after_certification(api)
    application = _file_handicap_series_claim(scn)

    validate_error(
        scn.api.association_decide_application(
            application["id"],
            f.association_decision_payload(
                AssociationAwardDecision.CERTIFY.value,
                association_ruling_note="Recorded on the national register.",
            ),
            scn.officer,
        ),
        ApiErrorId.ERR_AWARD_APPLICATION_STATE_INVALID.value,
    )
    assert_fields(
        _application(scn, application["id"]),
        status=AwardApplicationStatus.SUBMITTED.value,
        association_ruling_note=None,
    )

    claimant = _membership(scn, 1)
    assert_fields(
        claimant,
        certified_games=3,
        certified_pins=720,
        current_average=expected_blended_average(195, 30, 720, 3),
    )
    assert_fields(_match(scn), status=MatchStatus.CERTIFIED.value)


# ─── remedy applicability, on both ruling surfaces ──────
# Each remedy carries its own applicability test measured against the protest's
# own subject: a forfeit needs a lineup-legality protest with a named forfeiting
# side, a void needs a protested match that is certified, and a denial may carry
# nothing but NONE.  The same check guards the association's ruling.

_RULING_NOTE = "The hearing panel recorded its rationale in full."


def _protest_under_review(
    api: ApiClient,
    category: ProtestCategory,
    *,
    cite_match: bool = True,
) -> Tuple[fx.Scenario, str]:
    """A certified week and one protest whose first hearing is already open."""
    scn = fx.build_certified_match(api)
    payload = f.protest_payload(
        scn.league_id,
        scn.membership_ids[2],
        category,
        protest_note="The panel is asked to read the bylaw as written.",
        match_id=scn.match_ids[0] if cite_match else None,
    )
    protest = validate_success(scn.api.file_protest(payload, scn.bowler(2)), 201)
    opened = validate_success(
        scn.api.review_protest(protest["id"], f.review_payload(), scn.secretary)
    )
    assert_fields(
        opened, status=ProtestStatus.UNDER_REVIEW.value, review_round=1
    )
    return scn, protest["id"]


def test_forfeit_award_needs_a_lineup_legality_protest(api: ApiClient) -> None:
    """A forfeit remedy on a scoring protest fails its own applicability test.

    The remedy is well formed and the forfeiting side is named, so the only
    thing wrong is that this protest is not about lineup legality — and nothing
    the refusal touches moves, on the protest or on the certified match.

    Design: Corner/validations/corner_remedy_applicability_is_checked_against_the_protest_subject
    """
    scn, protest_id = _protest_under_review(api, ProtestCategory.SCORE_ERROR)

    validate_error(
        scn.api.rule_on_protest(
            protest_id,
            f.ruling_payload(
                ProtestDecision.UPHOLD.value,
                remedy=Remedy.FORFEIT_AWARD.value,
                forfeiting_team_id=scn.team_ids[0],
            ),
            scn.secretary,
        ),
        ApiErrorId.ERR_REMEDY_NOT_APPLICABLE.value,
    )

    protest = _protest(scn, protest_id)
    assert_fields(
        protest,
        status=ProtestStatus.UNDER_REVIEW.value,
        review_round=1,
        remedy=Remedy.NONE.value,
        ruling_note=None,
    )

    match = _match(scn)
    assert_fields(
        match, status=MatchStatus.CERTIFIED.value, forfeiting_team_id=None
    )
    assert_points(match["home_points"], 4.0, "home_points")
    assert_points(match["away_points"], 0.0, "away_points")
    assert_fields(_membership(scn, 2), certified_games=3, certified_pins=480)
    assert_points(_team(scn, 0)["total_points"], 4.0, "total_points")
    assert_points(_team(scn, 1)["total_points"], 0.0, "total_points")


def test_forfeit_award_needs_a_forfeiting_side_named(api: ApiClient) -> None:
    """The right category is not enough; the remedy also needs its team.

    With the side left unnamed the applicability test fails, and the hearing is
    still open afterwards, so the panel can close it with a plain denial.

    Design: Corner/validations/corner_remedy_applicability_is_checked_against_the_protest_subject
    """
    scn, protest_id = _protest_under_review(api, ProtestCategory.LINEUP_LEGALITY)

    validate_error(
        scn.api.rule_on_protest(
            protest_id,
            f.ruling_payload(
                ProtestDecision.UPHOLD.value, remedy=Remedy.FORFEIT_AWARD.value
            ),
            scn.secretary,
        ),
        ApiErrorId.ERR_REMEDY_NOT_APPLICABLE.value,
    )
    assert_fields(
        _protest(scn, protest_id),
        status=ProtestStatus.UNDER_REVIEW.value,
        remedy=Remedy.NONE.value,
    )

    denied = validate_success(
        scn.api.rule_on_protest(
            protest_id,
            f.ruling_payload(
                ProtestDecision.DENY.value,
                ruling_note=_RULING_NOTE,
                remedy=Remedy.NONE.value,
            ),
            scn.secretary,
        )
    )
    assert_fields(
        denied,
        status=ProtestStatus.DENIED.value,
        remedy=Remedy.NONE.value,
        ruling_note=_RULING_NOTE,
    )
    assert_fields(_match(scn), status=MatchStatus.CERTIFIED.value)


def test_a_denial_may_carry_no_remedy_but_none(api: ApiClient) -> None:
    """A void attached to a denial is refused even though the match is certified.

    The match this protest cites *is* certified, so the void's own precondition
    holds; what fails is that a denial changes nothing and may therefore carry
    only the empty remedy.

    Design: Corner/validations/corner_remedy_applicability_is_checked_against_the_protest_subject
    """
    scn, protest_id = _protest_under_review(api, ProtestCategory.SCORE_ERROR)
    assert_fields(_match(scn), status=MatchStatus.CERTIFIED.value)

    validate_error(
        scn.api.rule_on_protest(
            protest_id,
            f.ruling_payload(
                ProtestDecision.DENY.value, remedy=Remedy.VOID_MATCH.value
            ),
            scn.secretary,
        ),
        ApiErrorId.ERR_REMEDY_NOT_APPLICABLE.value,
    )
    assert_fields(
        _protest(scn, protest_id), status=ProtestStatus.UNDER_REVIEW.value
    )
    assert_fields(_match(scn), status=MatchStatus.CERTIFIED.value)

    denied = validate_success(
        scn.api.rule_on_protest(
            protest_id,
            f.ruling_payload(ProtestDecision.DENY.value, remedy=Remedy.NONE.value),
            scn.secretary,
        )
    )
    assert_fields(
        denied, status=ProtestStatus.DENIED.value, remedy=Remedy.NONE.value
    )
    match = _match(scn)
    assert_fields(match, status=MatchStatus.CERTIFIED.value)
    assert_points(match["home_points"], 4.0, "home_points")


def test_void_match_needs_a_protested_match_to_void(api: ApiClient) -> None:
    """A pure rules question cites no match, so it cannot void one.

    Design: Corner/validations/corner_remedy_applicability_is_checked_against_the_protest_subject
    """
    scn, protest_id = _protest_under_review(
        api, ProtestCategory.RULES_INTERPRETATION, cite_match=False
    )
    assert_fields(_protest(scn, protest_id), match_id=None)

    validate_error(
        scn.api.rule_on_protest(
            protest_id,
            f.ruling_payload(
                ProtestDecision.UPHOLD.value, remedy=Remedy.VOID_MATCH.value
            ),
            scn.secretary,
        ),
        ApiErrorId.ERR_REMEDY_NOT_APPLICABLE.value,
    )
    assert_fields(
        _protest(scn, protest_id),
        status=ProtestStatus.UNDER_REVIEW.value,
        remedy=Remedy.NONE.value,
        ruling_note=None,
    )
    assert_fields(_match(scn), status=MatchStatus.CERTIFIED.value)


def test_association_ruling_runs_the_same_applicability_test(api: ApiClient) -> None:
    """Escalation passes jurisdiction, not permission to skip the remedy test.

    A rules-interpretation protest may escalate from its very first hearing.
    The association then meets the same refusal on a void it cannot apply, and
    the two ruling texts stay independent of one another.

    Design: Corner/validations/corner_remedy_applicability_is_checked_against_the_protest_subject
    """
    scn, protest_id = _protest_under_review(
        api, ProtestCategory.RULES_INTERPRETATION, cite_match=False
    )

    escalated = validate_success(
        scn.api.rule_on_protest(
            protest_id,
            f.ruling_payload(ProtestDecision.ESCALATE.value, ruling_note=_RULING_NOTE),
            scn.secretary,
        )
    )
    assert_fields(
        escalated,
        status=ProtestStatus.ESCALATED.value,
        review_round=1,
        ruling_note=_RULING_NOTE,
        association_ruling=None,
    )

    validate_error(
        scn.api.association_rule_on_protest(
            protest_id,
            f.association_ruling_payload(remedy=Remedy.VOID_MATCH.value),
            scn.officer,
        ),
        ApiErrorId.ERR_REMEDY_NOT_APPLICABLE.value,
    )
    assert_fields(_protest(scn, protest_id), status=ProtestStatus.ESCALATED.value)

    ruled = validate_success(
        scn.api.association_rule_on_protest(
            protest_id,
            f.association_ruling_payload(
                "The association affirms the league's reading of the bylaw.",
                remedy=Remedy.NONE.value,
            ),
            scn.officer,
        )
    )
    assert_fields(
        ruled,
        status=ProtestStatus.ASSOCIATION_RULED.value,
        remedy=Remedy.NONE.value,
        ruling_note=_RULING_NOTE,
        association_ruling="The association affirms the league's reading of the bylaw.",
    )
    assert_fields(_match(scn), status=MatchStatus.CERTIFIED.value)


# ─── a projected plan outruns the money on hand ─────────
# The projected basis counts a week nobody has paid for yet, so the approved
# awards deliberately exceed `undistributed_balance_cents`.  Disbursement is the
# only place that shortfall is caught, and the guard holds the balance at or
# above zero until the projected dues actually arrive.

_SETTLED_WEEK_ONE_CENTS = 4 * WEEKLY_PRIZE_SHARE_CENTS
_PROJECTED_BASIS_CENTS = _SETTLED_WEEK_ONE_CENTS + 1 * 4 * WEEKLY_PRIZE_SHARE_CENTS
_RESERVE_CENTS = expected_reserve_cents(_PROJECTED_BASIS_CENTS)
_ADMIN_FEE_CENTS = expected_admin_fee_cents(_PROJECTED_BASIS_CENTS, _RESERVE_CENTS)
_NET_CENTS = _PROJECTED_BASIS_CENTS - _RESERVE_CENTS - _ADMIN_FEE_CENTS
_AWARD_AMOUNTS = expected_award_amounts(_NET_CENTS, PLACE_WEIGHTS)


def _projected_plan_drafted(api: ApiClient) -> Tuple[fx.Scenario, Dict[str, Any]]:
    """Week one certified and paid, with a projected plan drafted mid-season."""
    scn = fx.build_certified_match(api)
    fx.pay_dues_for_all(scn, 1)
    fund = _fund(scn)
    plan = validate_success(
        scn.api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                fund["version"], BasisVariant.PROJECTED_SEASON_END, len(PLACE_WEIGHTS)
            ),
            scn.treasurer,
        )
    )
    return scn, plan


def _settle_the_season_and_approve(scn: fx.Scenario) -> Dict[str, Any]:
    """Forfeit the remaining week, close the season and approve the plan."""
    fx.set_clock(scn.api, DISBURSEMENT_INSTANT)
    validate_success(
        scn.api.forfeit_match(
            scn.match_ids[1], f.forfeit_payload(scn.team_ids[1]), scn.secretary
        )
    )
    validate_success(scn.api.close_season(scn.league_id, {}, scn.secretary))
    return validate_success(scn.api.approve_plan(_fund(scn)["id"], {}, scn.secretary))


def test_projected_basis_counts_a_week_nobody_has_paid_for(api: ApiClient) -> None:
    """The projected plan is drafted from money that has not arrived yet.

    One week of dues is settled, one week remains, and four sanctioned members
    are projected to pay it, so the basis is double the settled amount while the
    fund's own balance is still only the settled half.

    Design: Corner/validations/corner_projected_plan_cannot_be_paid_until_the_projected_dues_arrive
    """
    scn, plan = _projected_plan_drafted(api)

    assert_fields(
        plan,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
        basis_variant=BasisVariant.PROJECTED_SEASON_END.value,
        place_count=len(PLACE_WEIGHTS),
        plan_approved_by_user_id=None,
        disbursed_at=None,
    )
    assert_cents(plan["plan_basis_cents"], _PROJECTED_BASIS_CENTS, "plan_basis_cents")
    assert_cents(plan["reserve_cents"], _RESERVE_CENTS, "reserve_cents")
    assert_cents(plan["admin_fee_cents"], _ADMIN_FEE_CENTS, "admin_fee_cents")
    assert_cents(plan["net_distributable_cents"], _NET_CENTS, "net_distributable_cents")
    assert_instant_equals(plan["plan_drafted_at"], WEEK1_STARTS_AT, "plan_drafted_at")

    assert_cents(
        plan["collected_prize_cents"], _SETTLED_WEEK_ONE_CENTS, "collected_prize_cents"
    )
    assert_cents(
        plan["undistributed_balance_cents"],
        _SETTLED_WEEK_ONE_CENTS,
        "undistributed_balance_cents",
    )
    assert plan["net_distributable_cents"] > plan["undistributed_balance_cents"], (
        "the projection must outrun the money on hand for this corner to bite"
    )
    assert_prize_money_invariant(plan)
    assert _awards(scn) == [], "drafting creates no award rows at all"


def test_approval_materialises_awards_the_fund_cannot_yet_cover(
    api: ApiClient,
) -> None:
    """Approval writes the pending awards from the drafted net, unchanged.

    Approval does not revisit the basis: the awards total the net computed when
    the plan was drafted, which is why they can exceed the balance.

    Design: Corner/validations/corner_projected_plan_cannot_be_paid_until_the_projected_dues_arrive
    """
    scn, _plan = _projected_plan_drafted(api)
    approved = _settle_the_season_and_approve(scn)

    assert_fields(
        approved,
        status=PrizeFundStatus.PLAN_APPROVED.value,
        plan_approved_by_user_id=scn.secretary_member_id,
        disbursed_at=None,
    )
    assert_cents(
        approved["net_distributable_cents"], _NET_CENTS, "net_distributable_cents"
    )
    assert_cents(approved["paid_award_total_cents"], 0, "paid_award_total_cents")

    assert_fields(_team(scn, 0), status=TeamStatus.CONFIRMED.value)
    assert_fields(_team(scn, 1), status=TeamStatus.CONFIRMED.value)
    assert_points(_team(scn, 0)["total_points"], 8.0, "total_points")
    assert_points(_team(scn, 1)["total_points"], 0.0, "total_points")

    awards = _awards(scn)
    assert [row["place"] for row in awards] == [1, 2], (
        f"awards must be listed one per place in ascending order, got {awards}"
    )
    for award, amount, weight, team_id in zip(
        awards, _AWARD_AMOUNTS, PLACE_WEIGHTS, [scn.team_ids[0], scn.team_ids[1]]
    ):
        assert_identity(award)
        assert_fields(
            award,
            status=PrizeAwardStatus.PENDING.value,
            weight=weight,
            team_id=team_id,
        )
        assert_cents(award["amount_cents"], amount, "amount_cents")
    assert sum(row["amount_cents"] for row in awards) == _NET_CENTS, (
        "the awards must total the net distributable amount exactly"
    )


def test_disbursement_is_refused_while_the_projected_dues_are_missing(
    api: ApiClient,
) -> None:
    """The shortfall is caught at disbursement rather than driving the balance
    below zero.

    Design: Corner/validations/corner_projected_plan_cannot_be_paid_until_the_projected_dues_arrive
    """
    scn, _plan = _projected_plan_drafted(api)
    _settle_the_season_and_approve(scn)

    validate_error(
        scn.api.disburse(_fund(scn)["id"], {}, scn.treasurer),
        ApiErrorId.ERR_INSUFFICIENT_PRIZE_FUND.value,
    )

    fund = _fund(scn)
    assert_fields(
        fund, status=PrizeFundStatus.PLAN_APPROVED.value, disbursed_at=None
    )
    assert_cents(fund["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert_cents(
        fund["undistributed_balance_cents"],
        _SETTLED_WEEK_ONE_CENTS,
        "undistributed_balance_cents",
    )
    assert_prize_money_invariant(fund)
    assert all(
        row["status"] == PrizeAwardStatus.PENDING.value for row in _awards(scn)
    ), "a refused disbursement must leave every award PENDING"
    assert_fields(_league(scn), status=LeagueStatus.SEASON_CLOSED.value)


def test_disbursement_succeeds_once_the_projected_dues_arrive(api: ApiClient) -> None:
    """Collecting the remaining week — legal after the close — unblocks the plan.

    Design: Corner/validations/corner_projected_plan_cannot_be_paid_until_the_projected_dues_arrive
    """
    scn, _plan = _projected_plan_drafted(api)
    _settle_the_season_and_approve(scn)

    for index in range(len(scn.membership_ids)):
        payment = validate_success(
            scn.api.record_dues_payment(
                scn.membership_ids[index],
                f.dues_payload(2, WEEKLY_DUES_CENTS),
                scn.treasurer,
            ),
            201,
        )
        assert_cents(
            payment["prize_share_cents"],
            WEEKLY_PRIZE_SHARE_CENTS,
            "prize_share_cents",
        )

    disbursed = validate_success(scn.api.disburse(_fund(scn)["id"], {}, scn.treasurer))
    assert_fields(disbursed, status=PrizeFundStatus.DISBURSED.value)
    assert_instant_equals(
        disbursed["disbursed_at"], DISBURSEMENT_INSTANT, "disbursed_at"
    )
    assert_cents(
        disbursed["collected_prize_cents"],
        2 * _SETTLED_WEEK_ONE_CENTS,
        "collected_prize_cents",
    )
    assert_cents(
        disbursed["paid_award_total_cents"], _NET_CENTS, "paid_award_total_cents"
    )
    assert_cents(
        disbursed["undistributed_balance_cents"],
        2 * _SETTLED_WEEK_ONE_CENTS - _NET_CENTS,
        "undistributed_balance_cents",
    )
    assert_prize_money_invariant(disbursed)

    awards = _awards(scn)
    for award, amount in zip(awards, _AWARD_AMOUNTS):
        assert_fields(award, status=PrizeAwardStatus.PAID.value)
        assert_cents(award["amount_cents"], amount, "amount_cents")

    assert_fields(_league(scn), status=LeagueStatus.PRIZES_DISBURSED.value)
    for index in range(len(scn.membership_ids)):
        membership = _membership(scn, index)
        assert_cents(
            membership["dues_paid_cents"], 2 * WEEKLY_DUES_CENTS, "dues_paid_cents"
        )
        assert_fields(membership, dues_arrears_weeks=0)
