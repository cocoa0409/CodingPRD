"""Single requests that violate two ranked rules at once.

The re-extend of an accepted offer against an exhausted pool breaks both a state
rule and a fiscal rule; the approval of an over-percentile plan against a lapsed
opinion breaks both a safety rule and a temporal rule. In each pair only the
higher-ranked error may surface.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BENCHMARK_BASIS_TOTAL_CASH_COMP,
    EMPLOYMENT_PROSPECTIVE,
    MODEL_STRAIGHT_SALARY,
    OFFER_STATUS_ACCEPTED,
    OFFER_STATUS_EXTENDED,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_SUBMITTED,
    ROLE_CODE_MA,
    ROLE_CODE_PRACTICE_MANAGER,
)
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER_ALT,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    VALUATION_ANALYST,
    board_review_deal,
    create_offer,
    create_plan,
    diligence_deal,
    read_acquisition,
    set_clock,
    set_offer_status,
    submit_plan,
)

# The pool is sized to the exact sum of the two awards, so extending both
# leaves nothing available.
POOL_TOTAL_CENTS = 1_710_000
MA_BONUS_CENTS = 210_000
MA_OFFERED_WAGE_CENTS = 4_200_000
PRACTICE_MANAGER_BONUS_CENTS = 1_500_000
COVERAGE_TWO_OF_FIVE_PCT = 40.00

# A straight salary one hundred thousand cents over the primary-care ninetieth
# percentile point of 36,000,000 lands at 90.03; the point itself is 90.00.
OVER_PERCENTILE_BASE_CENTS = 36_100_000
OVER_PERCENTILE = 90.03
ON_POINT_BASE_CENTS = 36_000_000
ON_POINT_PERCENTILE = 90.00
DAY_AFTER_EXPIRY_INSTANT = "2027-08-02T00:00:00Z"
OPINION_EXPIRES_ON = "2027-08-01"


def _deal_with_an_exhausted_pool(api: ApiClient):
    """Two extended offers whose awards exactly consume the retention pool."""
    deal = diligence_deal(
        api, retention_pool_total_cents=POOL_TOTAL_CENTS, required_staff_headcount=5
    )
    acquisition_id = deal["acquisition"]["id"]

    accepted = create_offer(
        api,
        acquisition_id,
        staff_member_name="Nia Carter",
        role_code=ROLE_CODE_MA,
        legacy_annual_wage_cents=3_600_000,
        legacy_pto_hours=40,
        credited_service_months=30,
        offer_expires_on="2026-10-31",
    )
    set_offer_status(api, accepted["id"], OFFER_STATUS_EXTENDED)
    accepted = set_offer_status(api, accepted["id"], OFFER_STATUS_ACCEPTED)

    extended = create_offer(
        api,
        acquisition_id,
        staff_member_name="Grace Okonkwo",
        role_code=ROLE_CODE_PRACTICE_MANAGER,
        legacy_annual_wage_cents=12_000_000,
        legacy_pto_hours=160,
        credited_service_months=200,
        offer_expires_on="2026-10-31",
    )
    extended = set_offer_status(api, extended["id"], OFFER_STATUS_EXTENDED)

    deal["accepted_offer"] = accepted
    deal["extended_offer"] = extended
    return deal


def _re_extend(api: ApiClient, offer_id: str):
    return api.set_staff_transition_offer_status(
        offer_id,
        f.offer_status_payload(
            OFFER_STATUS_EXTENDED, note="Attempting to re-extend an already accepted offer."
        ),
        INTEGRATION_MANAGER,
    )


def test_the_state_rule_outranks_the_pool_shortfall(api: ApiClient):
    """One request breaks both rules and only the higher-ranked one is reported.

    PRD: "Ranked below the state rule, so re-extending an already-extended offer
    against a depleted pool reports the invalid transition rather than the
    shortfall."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reextending_offer_with_depleted_pool
    """
    deal = _deal_with_an_exhausted_pool(api)
    acquisition = read_acquisition(api, deal["acquisition"]["id"])
    a.assert_retention_pool(acquisition, POOL_TOTAL_CENTS, POOL_TOTAL_CENTS, 0)

    rejected = _re_extend(api, deal["accepted_offer"]["id"])

    error = validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)
    assert error["error_id"] != ApiErrorId.RETENTION_POOL_EXCEEDED


def test_the_rejected_re_extend_changes_nothing(api: ApiClient):
    """The two offers and the pool ledger survive the rejection unchanged.

    PRD: "An accepted offer keeps its commitment against the pool; the money is
    spent, not released."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reextending_offer_with_depleted_pool
    """
    deal = _deal_with_an_exhausted_pool(api)
    _re_extend(api, deal["accepted_offer"]["id"])

    accepted = validate_success(
        api.get_staff_transition_offer(deal["accepted_offer"]["id"], INTEGRATION_MANAGER)
    )
    a.assert_status(accepted, OFFER_STATUS_ACCEPTED)
    a.assert_money_equals(
        accepted["offered_annual_wage_cents"], MA_OFFERED_WAGE_CENTS, "offered_annual_wage_cents"
    )
    assert accepted["wage_floor_applied"] is True
    a.assert_money_equals(accepted["retention_bonus_cents"], MA_BONUS_CENTS, "retention_bonus_cents")

    extended = validate_success(
        api.get_staff_transition_offer(deal["extended_offer"]["id"], INTEGRATION_MANAGER)
    )
    a.assert_status(extended, OFFER_STATUS_EXTENDED)
    a.assert_money_equals(
        extended["retention_bonus_cents"],
        PRACTICE_MANAGER_BONUS_CENTS,
        "retention_bonus_cents",
    )

    acquisition = read_acquisition(api, deal["acquisition"]["id"])
    a.assert_retention_pool(acquisition, POOL_TOTAL_CENTS, POOL_TOTAL_CENTS, 0)
    a.assert_percentage_equals(
        acquisition["hr_staffing_coverage_pct"], COVERAGE_TWO_OF_FIVE_PCT, "hr_staffing_coverage_pct"
    )


# ---------------------------------------------------------------------------
# Safety versus temporal on a compensation plan approval
# ---------------------------------------------------------------------------


def _board_review_deal_past_the_opinion_expiry(api: ApiClient):
    """Two submitted salary plans, then a clock one day past the pinned expiry."""
    deal = board_review_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    physician_id = deal["physician"]["id"]

    hot = create_plan(
        api,
        acquisition_id,
        physician_id,
        model_type=MODEL_STRAIGHT_SALARY,
        base_salary_cents=OVER_PERCENTILE_BASE_CENTS,
        conversion_factor_cents_per_wrvu=0,
        threshold_wrvu=0,
        projected_annual_wrvu=0,
    )
    deal["hot_plan"] = submit_plan(api, hot["id"])

    on_point = create_plan(
        api,
        acquisition_id,
        physician_id,
        model_type=MODEL_STRAIGHT_SALARY,
        base_salary_cents=ON_POINT_BASE_CENTS,
        conversion_factor_cents_per_wrvu=0,
        threshold_wrvu=0,
        projected_annual_wrvu=0,
    )
    deal["on_point_plan"] = submit_plan(api, on_point["id"])

    set_clock(api, DAY_AFTER_EXPIRY_INSTANT)
    return deal


def _approve(api: ApiClient, plan_id: str):
    return api.set_compensation_plan_status(
        plan_id,
        f.plan_status_payload(PLAN_STATUS_APPROVED, review_note="Approving despite the percentile."),
        COMPLIANCE_OFFICER_ALT,
    )


def test_the_safe_harbour_rule_outranks_the_stale_opinion(api: ApiClient):
    """The over-percentile defect is reported, not the lapsed governing opinion.

    PRD: "Ranked below the safe-harbour rule, so a plan that is both over the
    percentile and approved against a stale opinion reports the compensation
    defect rather than the staleness."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_approving_over_percentile_plan_with_expired_opinion
    """
    deal = _board_review_deal_past_the_opinion_expiry(api)

    rejected = _approve(api, deal["hot_plan"]["id"])

    error = validate_error(rejected, ApiErrorId.COMP_EXCEEDS_FMV_SAFE_HARBOR, 422)
    assert error["error_id"] != ApiErrorId.VALUATION_OPINION_EXPIRED


def test_the_rejected_approval_leaves_the_plan_and_the_pin_untouched(api: ApiClient):
    """The plan stays submitted, unapproved, and the pinned opinion keeps its expiry.

    PRD: "On approval the caller's `X-User-ID` is stored in
    `approved_by_user_id`, the linked physician's `employment_status` is
    recomputed to `OFFERED`, and any other compensation plan for the same
    `physician_id` that is currently in `EXECUTED` is set to `SUPERSEDED` — a
    physician may hold only one live executed arrangement."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_approving_over_percentile_plan_with_expired_opinion
    """
    deal = _board_review_deal_past_the_opinion_expiry(api)
    _approve(api, deal["hot_plan"]["id"])

    plan = validate_success(
        api.get_compensation_plan(deal["hot_plan"]["id"], COMPLIANCE_OFFICER_ALT)
    )
    a.assert_status(plan, PLAN_STATUS_SUBMITTED)
    a.assert_fields_null(plan, "approved_by_user_id")
    a.assert_percentage_equals(plan["benchmark_percentile"], OVER_PERCENTILE, "benchmark_percentile")
    assert plan["benchmark_basis"] == BENCHMARK_BASIS_TOTAL_CASH_COMP

    opinion = validate_success(api.get_valuation_opinion(deal["fmv"]["id"], VALUATION_ANALYST))
    assert opinion["expires_on"] == OPINION_EXPIRES_ON
    assert opinion["is_pinned"] is True

    physician = validate_success(api.get_physician(deal["physician"]["id"], DEAL_LEAD))
    assert physician["employment_status"] == EMPLOYMENT_PROSPECTIVE


def test_a_compliant_percentile_lets_the_expiry_rule_surface(api: ApiClient):
    """Satisfying the higher rule exposes the lower one on an otherwise identical call.

    PRD: "And the pinned opinion's `expires_on` must not be before the current
    logical date, or the request fails with `ERR_VALUATION_OPINION_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_approving_over_percentile_plan_with_expired_opinion
    """
    deal = _board_review_deal_past_the_opinion_expiry(api)
    a.assert_percentage_equals(
        deal["on_point_plan"]["benchmark_percentile"], ON_POINT_PERCENTILE, "benchmark_percentile"
    )

    rejected = _approve(api, deal["on_point_plan"]["id"])

    validate_error(rejected, ApiErrorId.VALUATION_OPINION_EXPIRED, 422)
