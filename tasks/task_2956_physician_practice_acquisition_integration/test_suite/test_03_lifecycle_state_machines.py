"""Cyclic lifecycles whose repeated request lands somewhere else the third time.

The deal status cycles forward and back with a compensating backward edge; the
compensation plan's return cycle terminates in a withdrawal; the migration
batch's fail-and-requeue cycle terminates in an abort.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BATCH_ACTION_EXTRACT,
    BATCH_ACTION_LOAD,
    BATCH_ACTION_REQUEUE,
    BATCH_STATUS_ABORTED,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_STAGED,
    CLEARANCE_PENDING,
    DEAL_STATUS_BOARD_REVIEW,
    DEAL_STATUS_DILIGENCE,
    EMPLOYMENT_DECLINED,
    OPINION_STATUS_ACCEPTED,
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_SUBMITTED,
    PLAN_STATUS_WITHDRAWN,
    RETENTION_YEARS_DEFAULT,
    SOURCE_SYSTEM_ECLINICALWORKS,
)
from test_helpers.fixtures import (
    COMPENSATION_DESIGNER,
    COMPLIANCE_OFFICER_ALT,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    VALUATION_ANALYST,
    advance_deal_status,
    board_review_deal,
    create_acquisition,
    create_plan,
    diligence_deal,
    loaded_batch,
    progress_batch,
    read_acquisition,
    reconcile_batch,
    reset_clock,
    submit_plan,
)

GROSS_CENTS = 1_500_750_000
SYNERGY_BPS = 275
NET_CENTS = 1_459_479_375

# 19,899 of 20,000 records validated truncates to 9949 basis points, one basis
# point under the reconciliation floor.
RECORD_COUNT = 20_000
VALIDATED_COUNT = 19_899
DEFECT_COUNT = 101
SUB_THRESHOLD_RATE_BPS = 9_949


def _return_plan(api: ApiClient, plan_id: str, note: str):
    return api.set_compensation_plan_status(
        plan_id, f.plan_status_payload(PLAN_STATUS_DRAFT, review_note=note), COMPLIANCE_OFFICER_ALT
    )


def _board_review_deal_with_submitted_plan(api: ApiClient):
    deal = board_review_deal(api)
    plan = create_plan(api, deal["acquisition"]["id"], deal["physician"]["id"])
    deal["plan"] = validate_success(submit_plan_response(api, plan["id"]))
    return deal


def submit_plan_response(api: ApiClient, plan_id: str):
    return api.set_compensation_plan_status(
        plan_id, f.plan_status_payload(PLAN_STATUS_SUBMITTED), COMPENSATION_DESIGNER
    )


def test_reverting_board_review_clears_the_price_and_unpins_the_opinion(api: ApiClient):
    """The backward edge out of board review is compensating, not a no-op.

    PRD: "All six consideration fields — `purchase_price_cents`,
    `integration_reserve_cents`, `gross_consideration_cents`,
    `synergy_credit_bps`, `synergy_credit_cents`, and `net_consideration_cents` —
    are cleared back to null."

    Design: Difficulty/non_linear_state_machine/acquisition_board_review_returns_to_diligence_and_unpins_valuation
    """
    deal = _board_review_deal_with_submitted_plan(api)
    acquisition_id = deal["acquisition"]["id"]

    reverted = advance_deal_status(api, acquisition_id, DEAL_STATUS_DILIGENCE)

    a.assert_status(reverted, DEAL_STATUS_DILIGENCE, "deal_status")
    a.assert_consideration_all_null(reverted)

    opinion = validate_success(api.get_valuation_opinion(deal["fmv"]["id"], VALUATION_ANALYST))
    assert opinion["is_pinned"] is False
    a.assert_status(opinion, OPINION_STATUS_ACCEPTED)


def test_reverting_board_review_returns_submitted_plans_to_draft(api: ApiClient):
    """A plan submitted against a withdrawn price is redrafted and charged one return.

    PRD: "And every compensation plan on the acquisition that is in `SUBMITTED`
    is returned to `DRAFT`, with each of those plans' `returned_count`
    incremented by 1."

    Design: Difficulty/non_linear_state_machine/acquisition_board_review_returns_to_diligence_and_unpins_valuation
    """
    deal = _board_review_deal_with_submitted_plan(api)
    plan_id = deal["plan"]["id"]

    advance_deal_status(api, deal["acquisition"]["id"], DEAL_STATUS_DILIGENCE)

    plan = validate_success(api.get_compensation_plan(plan_id, COMPENSATION_DESIGNER))
    a.assert_status(plan, PLAN_STATUS_DRAFT)
    assert plan["returned_count"] == 1
    a.assert_money_equals(
        plan["projected_total_cash_comp_cents"], 29_800_000, "projected_total_cash_comp_cents"
    )
    a.assert_percentage_equals(plan["benchmark_percentile"], 68.33, "benchmark_percentile")


def test_re_entering_board_review_recomputes_the_identical_chain(api: ApiClient):
    """The forward edge is idempotent: the second entry restores the same figures.

    PRD: "The pinned `FMV` opinion has `is_pinned` set back to false, freeing it
    to be superseded."

    Design: Difficulty/non_linear_state_machine/acquisition_board_review_returns_to_diligence_and_unpins_valuation
    """
    deal = _board_review_deal_with_submitted_plan(api)
    acquisition_id = deal["acquisition"]["id"]

    advance_deal_status(api, acquisition_id, DEAL_STATUS_DILIGENCE)
    restored = advance_deal_status(api, acquisition_id, DEAL_STATUS_BOARD_REVIEW)

    a.assert_status(restored, DEAL_STATUS_BOARD_REVIEW, "deal_status")
    a.assert_money_equals(
        restored["gross_consideration_cents"], GROSS_CENTS, "gross_consideration_cents"
    )
    assert restored["synergy_credit_bps"] == SYNERGY_BPS
    a.assert_money_equals(
        restored["net_consideration_cents"], NET_CENTS, "net_consideration_cents"
    )
    assert restored["compliance_clearance"] == CLEARANCE_PENDING

    opinion = validate_success(api.get_valuation_opinion(deal["fmv"]["id"], VALUATION_ANALYST))
    assert opinion["is_pinned"] is True


def test_third_return_withdraws_the_plan_instead_of_redrafting_it(api: ApiClient):
    """The same request lands in a different state once the allowance is spent.

    PRD: "The observable sequence for a single plan is therefore a
    `returned_count` of 0 becoming 1 with the plan back in `DRAFT`, then 1
    becoming 2 with the plan back in `DRAFT` again, then 2 becoming 3 with the
    plan `WITHDRAWN`."

    Design: Difficulty/non_linear_state_machine/comp_plan_return_cycle_terminates_as_withdrawn_after_two_returns
    """
    deal = diligence_deal(api)
    plan = create_plan(api, deal["acquisition"]["id"], deal["physician"]["id"])
    submit_plan(api, plan["id"])

    first = validate_success(_return_plan(api, plan["id"], "First redraft requested."))
    a.assert_status(first, PLAN_STATUS_DRAFT)
    assert first["returned_count"] == 1

    submit_plan(api, plan["id"])
    second = validate_success(_return_plan(api, plan["id"], "Second redraft requested."))
    a.assert_status(second, PLAN_STATUS_DRAFT)
    assert second["returned_count"] == 2

    submit_plan(api, plan["id"])
    third = validate_success(_return_plan(api, plan["id"], "Third redraft requested."))
    a.assert_status(third, PLAN_STATUS_WITHDRAWN)
    assert third["returned_count"] == 3


def test_withdrawn_plan_is_terminal_and_recomputes_employment(api: ApiClient):
    """A withdrawn plan cannot be resubmitted and moves the physician to DECLINED.

    PRD: "`DECLINED` when the most recently created plan for that physician is in
    `WITHDRAWN`, and `PROSPECTIVE` otherwise."

    Design: Difficulty/non_linear_state_machine/comp_plan_return_cycle_terminates_as_withdrawn_after_two_returns
    """
    deal = diligence_deal(api)
    physician_id = deal["physician"]["id"]
    plan = create_plan(api, deal["acquisition"]["id"], physician_id)

    for note in ("First redraft.", "Second redraft.", "Third redraft."):
        submit_plan(api, plan["id"])
        _return_plan(api, plan["id"], note)

    physician = validate_success(api.get_physician(physician_id, DEAL_LEAD))
    assert physician["employment_status"] == EMPLOYMENT_DECLINED

    rejected = submit_plan_response(api, plan["id"])
    validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)


def test_third_failing_reconcile_aborts_the_batch(api: ApiClient):
    """Two retries are allowed; the third sub-threshold reconcile abandons the batch.

    PRD: "When the computed rate falls below 9950 basis points and `retry_count`
    has already reached 2, the same request instead takes `LOADED → ABORTED`."

    Design: Difficulty/non_linear_state_machine/ehr_batch_failed_requeue_cycle_aborts_after_two_retries
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    batch = loaded_batch(
        api,
        acquisition["id"],
        batch_label="CHARTS-A",
        source_system=SOURCE_SYSTEM_ECLINICALWORKS,
        record_count=RECORD_COUNT,
    )

    first = reconcile_batch(api, batch["id"], VALIDATED_COUNT, DEFECT_COUNT)
    a.assert_status(first, BATCH_STATUS_FAILED)
    assert first["retry_count"] == 1
    assert first["match_rate_bps"] == SUB_THRESHOLD_RATE_BPS

    requeued = progress_batch(api, batch["id"], BATCH_ACTION_REQUEUE)
    a.assert_status(requeued, BATCH_STATUS_STAGED)
    assert requeued["validated_count"] == 0
    assert requeued["defect_count"] == 0
    assert requeued["unprocessed_count"] == RECORD_COUNT
    assert requeued["match_rate_bps"] == 0

    progress_batch(api, batch["id"], BATCH_ACTION_EXTRACT)
    progress_batch(api, batch["id"], BATCH_ACTION_LOAD)
    second = reconcile_batch(api, batch["id"], VALIDATED_COUNT, DEFECT_COUNT)
    a.assert_status(second, BATCH_STATUS_FAILED)
    assert second["retry_count"] == 2

    progress_batch(api, batch["id"], BATCH_ACTION_REQUEUE)
    progress_batch(api, batch["id"], BATCH_ACTION_EXTRACT)
    progress_batch(api, batch["id"], BATCH_ACTION_LOAD)
    third = reconcile_batch(api, batch["id"], VALIDATED_COUNT, DEFECT_COUNT)

    a.assert_status(third, BATCH_STATUS_ABORTED)
    assert third["retry_count"] == 3
    assert third["match_rate_bps"] == SUB_THRESHOLD_RATE_BPS
    assert third["validated_count"] == VALIDATED_COUNT
    assert third["defect_count"] == DEFECT_COUNT
    assert third["unprocessed_count"] == 0


def test_aborted_batch_is_terminal_and_keeps_its_retention_schedule(api: ApiClient):
    """An aborted batch refuses further pipeline actions and keeps its purge date.

    PRD: "`RECONCILED` and `ABORTED` are the batch's terminal states."

    Design: Difficulty/non_linear_state_machine/ehr_batch_failed_requeue_cycle_aborts_after_two_retries
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    batch = loaded_batch(
        api,
        acquisition["id"],
        batch_label="CHARTS-A",
        source_system=SOURCE_SYSTEM_ECLINICALWORKS,
        record_count=RECORD_COUNT,
    )

    for _ in range(2):
        reconcile_batch(api, batch["id"], VALIDATED_COUNT, DEFECT_COUNT)
        progress_batch(api, batch["id"], BATCH_ACTION_REQUEUE)
        progress_batch(api, batch["id"], BATCH_ACTION_EXTRACT)
        progress_batch(api, batch["id"], BATCH_ACTION_LOAD)
    aborted = reconcile_batch(api, batch["id"], VALIDATED_COUNT, DEFECT_COUNT)

    a.assert_status(aborted, BATCH_STATUS_ABORTED)
    assert aborted["retention_years"] == RETENTION_YEARS_DEFAULT
    assert aborted["legacy_purge_eligible_on"] == "2036-07-15"

    rejected = api.progress_ehr_migration_batch(
        batch["id"], f.batch_progress_payload(BATCH_ACTION_REQUEUE), INTEGRATION_MANAGER
    )
    validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)


def test_the_deal_status_cycle_leaves_the_clearance_dimension_alone(api: ApiClient):
    """The two acquisition dimensions move independently of one another.

    PRD: "A newly opened acquisition sits in `deal_status` `SOURCING` with
    `compliance_clearance` `PENDING` and `readiness_posture` `BLOCKED`, carries
    `hr_staffing_coverage_pct` of 0.00, and has `tail_premium_cents` not yet
    computed."

    Design: Difficulty/non_linear_state_machine/acquisition_board_review_returns_to_diligence_and_unpins_valuation
    """
    deal = board_review_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    advance_deal_status(api, acquisition_id, DEAL_STATUS_DILIGENCE)
    advance_deal_status(api, acquisition_id, DEAL_STATUS_BOARD_REVIEW)

    refreshed = read_acquisition(api, acquisition_id)
    assert refreshed["compliance_clearance"] == CLEARANCE_PENDING
