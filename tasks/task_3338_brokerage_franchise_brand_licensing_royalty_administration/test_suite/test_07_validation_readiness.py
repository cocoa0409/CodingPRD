"""Validation ordering pairs and conversion-plan readiness rules."""
from test_helpers import (
    NON_EXISTENT_UUID,
    validate_error, get_success_data,
    setup_active_agreement, setup_assessed_period, setup_agreement_with_plan,
    submit_gci_report, assess_period,
    create_brand,
    ApiErrorId, TEST_USERS,
)

OPS = TEST_USERS["franchisor_ops_headers"]


def test_waive_of_settled_period_reports_invalid_state(api):
    """PRD §3.5: "Waiver moves it `ASSESSED` → `WAIVED`, but only when
    `royalty_due_cents` is exactly zero; waiving a period with any positive due
    is rejected with `ERR_WAIVE_REQUIRES_ZERO_DUE`."
    PRD §2.9: "then state-machine legality of the requested transition
    (`ERR_INVALID_STATE`); then the optimistic-concurrency version match on
    activation and amendment (`ERR_STALE_VERSION`); then payload shape, enum
    membership, and numeric ranges (`ERR_INVALID_REQUEST`); and only then the
    business rules"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_waive
    """
    ctx = setup_assessed_period("2027-01", 100_000_000)
    period = ctx["period"]
    assert period["royalty_due_cents"] > 0
    get_success_data(api.settle_royalty_period(period["id"], OPS))

    resp = api.waive_royalty_period(period["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_settle_then_waive_leaves_period_settled(api):
    """PRD §3.5: "A period is born in `ASSESSED` status and ends in one of two
    terminal states. Settlement moves it `ASSESSED` → `SETTLED` and stamps
    `settled_at`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_waive
    """
    ctx = setup_assessed_period("2027-01", 100_000_000)
    period = ctx["period"]
    settled = get_success_data(api.settle_royalty_period(period["id"], OPS))
    assert settled["status"] == "SETTLED"

    api.waive_royalty_period(period["id"], OPS)
    reread = get_success_data(api.get_royalty_period(period["id"], OPS))
    assert reread["status"] == "SETTLED", "rejected waive must not move the period"


def test_execute_of_nonexistent_proposal_reports_not_found(api):
    """PRD §2.8: "The same existence discipline applies to identifiers carried in
    the request body: every referenced `id` — agreement, brand, market,
    brokerage, council, proposal, default case, audit, task, or royalty period —
    must resolve to an existing resource, or the request fails with
    `ERR_NOT_FOUND`."
    PRD §2.9: "then existence of every referenced identifier (`ERR_NOT_FOUND`);
    then state-machine legality of the requested transition (`ERR_INVALID_STATE`)"

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_fiscal_on_execute
    """
    create_brand()  # brand exists with zero fund balance; proposal id does not exist
    resp = api.execute_ad_fund_proposal(NON_EXISTENT_UUID, OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_execute_of_nonexistent_proposal_does_not_report_fund_error(api):
    """PRD §2.9: "then existence of every referenced identifier
    (`ERR_NOT_FOUND`); then state-machine legality of the requested transition
    (`ERR_INVALID_STATE`); then the optimistic-concurrency version match on
    activation and amendment (`ERR_STALE_VERSION`); then payload shape, enum
    membership, and numeric ranges (`ERR_INVALID_REQUEST`); and only then the
    business rules"

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_fiscal_on_execute
    """
    resp = api.execute_ad_fund_proposal(NON_EXISTENT_UUID, OPS)
    assert resp.status_code == 404
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"


def test_empty_milestone_plan_is_never_ready(api):
    """PRD §3.3: "the plan is ready exactly when `milestones_done` equals the
    total number of milestones and the plan contains at least one milestone. An
    empty milestone array is therefore never ready, and the readiness comparison
    is equality — a plan with every milestone done is ready, no more and no
    less."
    PRD §3.3: "that a `ConversionPlan` exists for this agreement with `ready`
    true (otherwise `ERR_CONVERSION_INCOMPLETE`)"

    Design: Difficulty/boundary_precision_check/empty_milestones_plan_never_ready
    """
    ctx = setup_agreement_with_plan(milestones=[])
    assert ctx["plan"]["ready"] is False
    assert ctx["plan"]["milestones_done"] == 0

    resp = api.activate_agreement(
        ctx["agreement"]["id"],
        {"expected_agreement_version": ctx["agreement"]["version"]},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_CONVERSION_INCOMPLETE)


def test_activation_without_ready_plan_rejected(api):
    """PRD §3.3: "that a `ConversionPlan` exists for this agreement with `ready`
    true (otherwise `ERR_CONVERSION_INCOMPLETE`)"

    Design: Difficulty/boundary_precision_check/empty_milestones_plan_never_ready
    """
    ctx = setup_agreement_with_plan(num_milestones=2)
    # Complete only the first of two milestones: ready stays false.
    get_success_data(
        api.complete_milestone(ctx["plan"]["id"], {"sequence": 1}, OPS)
    )
    resp = api.activate_agreement(
        ctx["agreement"]["id"],
        {"expected_agreement_version": ctx["agreement"]["version"]},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_CONVERSION_INCOMPLETE)
