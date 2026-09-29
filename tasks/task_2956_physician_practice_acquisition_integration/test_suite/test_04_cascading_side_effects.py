"""Cascades whose later links are caused by earlier links, not by the request.

Filing a performance report re-benchmarks one plan, that plan's hold flags the
acquisition, and that flag redrafts an unrelated pending plan. Denying a payer's
novation withdraws a package, fails a checklist line, and the failed line — not
the denial — drives the readiness posture down.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CLEARANCE_CLEARED,
    CLEARANCE_FLAGGED,
    CLEARANCE_PENDING,
    CONTRACT_FORM_CONSENT_REQUIRED,
    DEAL_STATUS_BOARD_REVIEW,
    DEAL_STATUS_CLOSED,
    DOMAIN_BY_TASK_CODE,
    EMPLOYMENT_PROSPECTIVE,
    MODEL_STRAIGHT_SALARY,
    NOVATION_ACTION_DENY,
    NOVATION_ACTION_SEND_NOTICE,
    NOVATION_DENIED,
    NOVATION_NOTICE_SENT,
    PACKAGE_STATUS_SUBMITTED,
    PACKAGE_STATUS_WITHDRAWN,
    PAYER_TYPE_COMMERCIAL,
    PLAN_STATUS_COMPLIANCE_HOLD,
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_SUBMITTED,
    POSTURE_AT_RISK,
    POSTURE_BLOCKED,
    POSTURE_READY,
    TASK_PAYER_CREDENTIALING,
    TASK_STATUS_FAILED,
    TASK_STATUS_IN_PROGRESS,
)
from test_helpers.fixtures import (
    COMPENSATION_DESIGNER,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    act_on_novation,
    board_review_deal,
    closed_deal,
    create_package,
    create_payer_contract,
    create_plan,
    create_report,
    in_progress_task,
    read_acquisition,
    read_task,
    set_package_status,
    set_task_status,
    submit_plan,
)

# One September of actuals against the canonical base-plus-incentive plan:
# 700 work RVUs in a single elapsed month annualises to 8400.
REPORT_PERIOD_START = "2026-09-01"
REPORT_PERIOD_END = "2026-09-30"
REPORT_ACTUAL_WRVU = 700
REPORT_COLLECTIONS_CENTS = 5_000_000
TRUE_UP_CENTS = 2_333_334
PERCENTILE_AFTER = 95.45
PROJECTED_TOTAL_CENTS = 29_800_000

# The pending revision proposal sits exactly on the primary-care median.
PENDING_PLAN_BASE_CENTS = 26_500_000
PENDING_PLAN_PERCENTILE = 50.00


def _closed_deal_with_a_pending_plan(api: ApiClient):
    """A closed, cleared deal with an executed plan and one SUBMITTED proposal."""
    deal = closed_deal(api)
    pending = create_plan(
        api,
        deal["acquisition"]["id"],
        deal["physician"]["id"],
        model_type=MODEL_STRAIGHT_SALARY,
        base_salary_cents=PENDING_PLAN_BASE_CENTS,
        conversion_factor_cents_per_wrvu=0,
        threshold_wrvu=0,
        projected_annual_wrvu=0,
    )
    deal["pending_plan"] = submit_plan(api, pending["id"])
    return deal


def _file_the_september_report(api: ApiClient, deal):
    return create_report(
        api,
        deal["acquisition"]["id"],
        deal["physician"]["id"],
        deal["plan"]["id"],
        period_start_on=REPORT_PERIOD_START,
        period_end_on=REPORT_PERIOD_END,
        actual_wrvu=REPORT_ACTUAL_WRVU,
        actual_collections_cents=REPORT_COLLECTIONS_CENTS,
    )


def test_report_folds_into_the_plan_and_re_benchmarks_the_run_rate(api: ApiClient):
    """The true-up and the re-benchmark both land on the plan, on the annualised volume.

    PRD: "The plan's `projected_annual_wrvu`,
    `projected_total_cash_comp_cents`, and `comp_per_wrvu_cents` are design
    inputs and are **never** overwritten by this reconciliation; only
    `benchmark_percentile`, `comp_true_up_cents`, `actual_ytd_wrvu`, and
    `months_elapsed` change."

    Design: Difficulty/transitive_cascade/performance_report_true_up_flags_acquisition_and_returns_pending_plans
    """
    deal = _closed_deal_with_a_pending_plan(api)
    report = _file_the_september_report(api, deal)

    a.assert_money_equals(report["true_up_applied_cents"], TRUE_UP_CENTS, "true_up_applied_cents")
    a.assert_percentage_equals(
        report["benchmark_percentile_after"], PERCENTILE_AFTER, "benchmark_percentile_after"
    )

    plan = validate_success(api.get_compensation_plan(deal["plan"]["id"], COMPENSATION_DESIGNER))
    assert plan["months_elapsed"] == 1
    assert plan["actual_ytd_wrvu"] == REPORT_ACTUAL_WRVU
    a.assert_money_equals(plan["comp_true_up_cents"], TRUE_UP_CENTS, "comp_true_up_cents")
    a.assert_percentage_equals(plan["benchmark_percentile"], PERCENTILE_AFTER, "benchmark_percentile")
    a.assert_money_equals(
        plan["projected_total_cash_comp_cents"],
        PROJECTED_TOTAL_CENTS,
        "projected_total_cash_comp_cents",
    )


def test_the_safe_harbour_trip_holds_the_plan_and_flags_the_deal(api: ApiClient):
    """Links one and two: the hold is caused by the percentile, the flag by the hold.

    PRD: "When the re-benchmarked `benchmark_percentile` is strictly greater than
    90.00, `fmv_justification_on_file` is false, and the plan is in `EXECUTED`,
    the plan moves `EXECUTED → COMPLIANCE_HOLD`."

    Design: Difficulty/transitive_cascade/performance_report_true_up_flags_acquisition_and_returns_pending_plans
    """
    deal = _closed_deal_with_a_pending_plan(api)
    before = read_acquisition(api, deal["acquisition"]["id"])
    assert before["compliance_clearance"] == CLEARANCE_CLEARED

    _file_the_september_report(api, deal)

    plan = validate_success(api.get_compensation_plan(deal["plan"]["id"], COMPENSATION_DESIGNER))
    a.assert_status(plan, PLAN_STATUS_COMPLIANCE_HOLD)
    assert plan["fmv_justification_on_file"] is False

    after = read_acquisition(api, deal["acquisition"]["id"])
    assert after["compliance_clearance"] == CLEARANCE_FLAGGED


def test_the_flag_redrafts_a_plan_the_report_never_named(api: ApiClient):
    """Link three reaches a plan that is not the report's subject.

    PRD: "That hold sets the acquisition's `compliance_clearance` to `FLAGGED`
    when it was `CLEARED`, and that flag in turn returns every compensation plan
    on the acquisition that is in `SUBMITTED` back to `DRAFT`, incrementing each
    of those plans' `returned_count` by 1."

    Design: Difficulty/transitive_cascade/performance_report_true_up_flags_acquisition_and_returns_pending_plans
    """
    deal = _closed_deal_with_a_pending_plan(api)
    pending_id = deal["pending_plan"]["id"]
    a.assert_status(deal["pending_plan"], PLAN_STATUS_SUBMITTED)
    a.assert_percentage_equals(
        deal["pending_plan"]["benchmark_percentile"],
        PENDING_PLAN_PERCENTILE,
        "benchmark_percentile",
    )

    _file_the_september_report(api, deal)

    pending = validate_success(api.get_compensation_plan(pending_id, COMPENSATION_DESIGNER))
    a.assert_status(pending, PLAN_STATUS_DRAFT)
    assert pending["returned_count"] == 1
    a.assert_percentage_equals(
        pending["benchmark_percentile"], PENDING_PLAN_PERCENTILE, "benchmark_percentile"
    )


def test_the_cascade_leaves_the_deal_status_and_the_posture_alone(api: ApiClient):
    """The chain touches neither the workflow status nor the posture, but employment re-derives.

    PRD: "Only when every blocking line is in `COMPLETE` or in `WAIVED` does the
    posture read `READY`."

    PRD: "A physician's `employment_status` is never supplied by a client. It is
    derived from that physician's compensation plans and is recomputed every time
    one of them moves: it reads `EMPLOYED` when one of the physician's plans is in
    `EXECUTED`, `OFFERED` when one is in `APPROVED`, `DECLINED` when the most
    recently created plan for that physician is in `WITHDRAWN`, and `PROSPECTIVE`
    otherwise."

    The hold moves the only executed plan out of `EXECUTED` and the flag returns
    the pending proposal to `DRAFT`, so no plan is left in `EXECUTED`, `APPROVED`
    or `WITHDRAWN` and the derived status falls through to `PROSPECTIVE`.

    Design: Difficulty/transitive_cascade/performance_report_true_up_flags_acquisition_and_returns_pending_plans
    """
    deal = _closed_deal_with_a_pending_plan(api)
    _file_the_september_report(api, deal)

    acquisition = read_acquisition(api, deal["acquisition"]["id"])
    a.assert_status(acquisition, DEAL_STATUS_CLOSED, "deal_status")
    assert acquisition["readiness_posture"] == POSTURE_READY

    physician = validate_success(api.get_physician(deal["physician"]["id"], DEAL_LEAD))
    assert physician["employment_status"] == EMPLOYMENT_PROSPECTIVE


def test_a_reported_period_may_never_be_restated(api: ApiClient):
    """The report is append-only and its period is unique per physician.

    PRD: "No other report may already exist for the same `physician_id` and the
    same `period_start_on`, or the request fails with
    `ERR_DUPLICATE_REPORT_PERIOD`."

    Design: Difficulty/transitive_cascade/performance_report_true_up_flags_acquisition_and_returns_pending_plans
    """
    deal = _closed_deal_with_a_pending_plan(api)
    report = _file_the_september_report(api, deal)
    a.assert_report_common_fields(report)

    duplicate = api.create_performance_report(
        f.performance_report_payload(
            deal["acquisition"]["id"],
            deal["physician"]["id"],
            deal["plan"]["id"],
            period_start_on=REPORT_PERIOD_START,
            period_end_on=REPORT_PERIOD_END,
            actual_wrvu=REPORT_ACTUAL_WRVU,
            actual_collections_cents=REPORT_COLLECTIONS_CENTS,
        ),
        INTEGRATION_MANAGER,
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_REPORT_PERIOD, 409)


# ---------------------------------------------------------------------------
# The payer denial cascade
# ---------------------------------------------------------------------------


def _noticed_payer_with_a_filed_package(api: ApiClient):
    """A noticed COMMERCIAL contract, one filed package, one started checklist line."""
    deal = board_review_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    contract = create_payer_contract(
        api,
        acquisition_id,
        payer_name="Aetna Choice",
        payer_type=PAYER_TYPE_COMMERCIAL,
        contract_form=CONTRACT_FORM_CONSENT_REQUIRED,
        notice_days_required=0,
        annual_revenue_share_bps=4_000,
        committee_slots_per_cycle=2,
    )
    contract = act_on_novation(
        api,
        contract["id"],
        NOVATION_ACTION_SEND_NOTICE,
        note="Assignment notice served on the payer.",
    )
    package = create_package(
        api, acquisition_id, deal["physician"]["id"], contract["id"], submitted_on="2026-08-03"
    )
    package = set_package_status(api, package["id"], PACKAGE_STATUS_SUBMITTED)
    task = in_progress_task(api, acquisition_id, task_code=TASK_PAYER_CREDENTIALING)

    deal["contract"] = contract
    deal["package"] = package
    deal["task"] = task
    return deal


def test_denial_withdraws_the_in_flight_package_and_frees_its_seat(api: ApiClient):
    """The denial reaches every non-terminal package on the contract.

    PRD: "Every credentialing package on this contract that is in `DRAFT`,
    `SUBMITTED`, or `IN_REVIEW` is set to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/payer_denial_withdraws_packages_fails_credentialing_task_and_blocks_posture
    """
    deal = _noticed_payer_with_a_filed_package(api)
    assert deal["contract"]["novation_status"] == NOVATION_NOTICE_SENT
    assert deal["package"]["committee_cycle_key"] == "2026-08-15"
    assert deal["package"]["projected_effective_on"] == "2026-11-01"
    assert deal["package"]["retro_billing_allowed"] is False

    contract = act_on_novation(
        api,
        deal["contract"]["id"],
        NOVATION_ACTION_DENY,
        note="Payer refuses to consent to assignment.",
    )

    assert contract["novation_status"] == NOVATION_DENIED
    assert contract["notice_sent_on"] == "2026-08-01"
    a.assert_fields_null(contract, "consent_received_on")

    package = validate_success(
        api.get_credentialing_package(deal["package"]["id"], INTEGRATION_MANAGER)
    )
    a.assert_status(package, PACKAGE_STATUS_WITHDRAWN)


def test_denial_fails_the_credentialing_line_and_that_line_blocks_the_posture(api: ApiClient):
    """The posture moves because the line failed, not because the payer denied.

    PRD: "The acquisition's readiness checklist line with `task_code`
    `PAYER_CREDENTIALING` is set to `FAILED` when it is currently in
    `IN_PROGRESS` or in `COMPLETE`, and its `failure_reason` is recorded."

    Design: Difficulty/transitive_cascade/payer_denial_withdraws_packages_fails_credentialing_task_and_blocks_posture
    """
    deal = _noticed_payer_with_a_filed_package(api)
    a.assert_status(deal["task"], TASK_STATUS_IN_PROGRESS)
    assert deal["task"]["domain"] == DOMAIN_BY_TASK_CODE[TASK_PAYER_CREDENTIALING]

    before = read_acquisition(api, deal["acquisition"]["id"])
    assert before["readiness_posture"] == POSTURE_AT_RISK

    act_on_novation(
        api, deal["contract"]["id"], NOVATION_ACTION_DENY, note="Payer refuses to consent."
    )

    task = read_task(api, deal["task"]["id"])
    a.assert_status(task, TASK_STATUS_FAILED)
    assert task["failure_reason"]
    assert task["failure_reason"].strip() != ""
    a.assert_fields_null(task, "verified_by_user_id")

    after = read_acquisition(api, deal["acquisition"]["id"])
    assert after["readiness_posture"] == POSTURE_BLOCKED
    a.assert_status(after, DEAL_STATUS_BOARD_REVIEW, "deal_status")
    assert after["compliance_clearance"] == CLEARANCE_PENDING


def test_reopening_the_failed_line_clears_the_reason_and_lifts_the_posture(api: ApiClient):
    """Reopening is the inverse of the cascade's second link.

    PRD: "A `FAILED` line can be reopened with `FAILED → IN_PROGRESS`, which has
    no precondition, clears `failure_reason` back to null, and recomputes the
    posture."

    Design: Difficulty/transitive_cascade/payer_denial_withdraws_packages_fails_credentialing_task_and_blocks_posture
    """
    deal = _noticed_payer_with_a_filed_package(api)
    act_on_novation(
        api, deal["contract"]["id"], NOVATION_ACTION_DENY, note="Payer refuses to consent."
    )

    reopened = set_task_status(api, deal["task"]["id"], TASK_STATUS_IN_PROGRESS)

    a.assert_status(reopened, TASK_STATUS_IN_PROGRESS)
    a.assert_fields_null(reopened, "failure_reason")

    acquisition = read_acquisition(api, deal["acquisition"]["id"])
    assert acquisition["readiness_posture"] == POSTURE_AT_RISK
