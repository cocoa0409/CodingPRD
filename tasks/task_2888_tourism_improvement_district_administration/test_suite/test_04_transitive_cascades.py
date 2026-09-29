"""Cascades whose later hops are caused by what an earlier hop wrote.

Two administrative acts in this system reach several entities away from the call
that started them.  A delinquency sweep charges a statement, which strikes the
owning property, which withdraws that property's petition signature.  A granted
dispute adjustment reduces a statement, which sinks a work plan's funding ratio,
which freezes the plan's running marketing programs.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_PROGRAM_SPEND_FROZEN
from test_helpers.assertions import assert_fields, assert_ratio_four_dp
from test_helpers.test_users import ADMIN, operator_headers


def _statement_of(api, period_id, business_id):
    """Find the statement a period issued for one property."""
    rows = validate_success(api.list_period_statements(period_id, headers=ADMIN))
    for row in rows:
        if row["lodging_business_id"] == business_id:
            return row["id"]
    raise AssertionError(f"no statement for {business_id} in period {period_id}")


# --------------------------------------------------------------------------
# Chain: two consecutive sweeps carrying one property to SUSPENDED
# --------------------------------------------------------------------------
def _two_periods_filed_with_a_renewal_signature(api):
    """File the same 824500-cent assessment in two consecutive quarters and put a
    renewal petition signature from the same property on the board.

    The district's term is one year from 2026-08-01, so its renewal window opens
    on 2027-02-02 and the drive is opened at 2027-02-10.
    """
    ctx = fx.active_district(api)
    fx.open_period(api, ctx)
    fx.generate_statements(api, ctx)
    fx.index_statements(api, ctx)
    fx.file_statement(api, ctx, "st1_id", "b1_id", 2000, 41225000)
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)
    fx.open_period(
        api,
        ctx,
        key="ap2_id",
        period_label="FY2027-Q2",
        period_start="2026-11-01T00:00:00Z",
        period_end="2027-02-01T00:00:00Z",
        due_date="2027-02-15T00:00:00Z",
        grace_days=10,
    )
    fx.generate_statements(api, ctx, period_key="ap2_id")
    ctx.st1_q2_id = _statement_of(api, ctx.ap2_id, ctx.b1_id)
    fx.set_clock(api, "2027-02-10T00:00:00Z")
    fx.file_statement(api, ctx, "st1_q2_id", "b1_id", 2000, 41225000)
    fx.open_renewal_drive(api, ctx, "2027-04-01T00:00:00Z")
    fx.sign(
        api,
        ctx,
        "b1_id",
        drive_key="renewal_pd_id",
        headers=operator_headers(ctx.b1_id),
    )
    return ctx


def test_the_first_sweep_charges_the_statement_and_strikes_the_property_once(api):
    """Sweeping the first quarter 78 days late charges 82450 of penalty and 32156
    of interest and carries the property from GOOD to WATCH.

    PRD 3.5: "Hop three. The delinquency stamp on the statement increments the
    owning property's delinquency_strike_count by one and re-derives its
    compliance_standing from the new count: zero strikes is GOOD, exactly one
    strike is WATCH, and two or more strikes is SUSPENDED."

    Design: Difficulty/transitive_cascade/delinquency_sweep_cascades_four_hops_into_renewal_petition_support
    """
    ctx = _two_periods_filed_with_a_renewal_signature(api)
    fx.set_clock(api, "2027-02-11T00:00:00Z")
    fx.sweep_period(api, ctx)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement,
        payment_status="DELINQUENT",
        delinquency_stage="NOTICE",
        penalty_cents=82450,
        interest_cents=32156,
    )

    business = validate_success(api.get_lodging_business(ctx.b1_id, headers=ADMIN))
    assert_fields(business, delinquency_strike_count=1, compliance_standing="WATCH")


def test_a_single_strike_leaves_the_petition_signature_standing(api):
    """A property on WATCH has not been suspended, so hop four does not fire and
    the drive keeps its full weighted support.

    PRD 3.5: "A property that has just reached compliance_standing SUSPENDED as a
    result of hop three has every one of its VALID petition signatures on drives
    still OPEN moved to DISQUALIFIED".

    Design: Difficulty/transitive_cascade/delinquency_sweep_cascades_four_hops_into_renewal_petition_support
    """
    ctx = _two_periods_filed_with_a_renewal_signature(api)
    fx.set_clock(api, "2027-02-11T00:00:00Z")
    fx.sweep_period(api, ctx)

    signature = validate_success(api.get_petition_signature(ctx.sig_b1, headers=ADMIN))
    assert_fields(signature, status="VALID", disqualification_reason="NONE")

    drive = validate_success(api.get_petition_drive(ctx.renewal_pd_id))
    assert_fields(drive, signed_basis_cents=60000000, valid_signature_count=1)
    assert_ratio_four_dp(drive["weighted_support_pct"], 0.6000, "weighted_support_pct")


def test_the_second_sweep_suspends_the_property_and_withdraws_its_signature(api):
    """A second strike suspends the property, which disqualifies its renewal
    signature and drops the drive's weighted support to 0.0000.

    PRD 3.5: "The disqualification_reason records which of the three causes
    applied" and the drive's support is recomputed; "A suspended operator's
    political support for a district is withdrawn as a direct consequence of its
    arrears, four hops away from the call that caused it."

    Design: Difficulty/transitive_cascade/delinquency_sweep_cascades_four_hops_into_renewal_petition_support
    """
    ctx = _two_periods_filed_with_a_renewal_signature(api)
    fx.set_clock(api, "2027-02-11T00:00:00Z")
    fx.sweep_period(api, ctx)
    fx.close_period(api, ctx, period_key="ap2_id")
    fx.set_clock(api, "2027-02-26T00:00:00Z")
    fx.sweep_period(api, ctx, period_key="ap2_id")

    business = validate_success(api.get_lodging_business(ctx.b1_id, headers=ADMIN))
    assert_fields(business, delinquency_strike_count=2, compliance_standing="SUSPENDED")

    signature = validate_success(api.get_petition_signature(ctx.sig_b1, headers=ADMIN))
    assert_fields(
        signature, status="DISQUALIFIED", disqualification_reason="COMPLIANCE_SUSPENDED"
    )

    drive = validate_success(api.get_petition_drive(ctx.renewal_pd_id))
    assert_fields(drive, signed_basis_cents=0, valid_signature_count=0)
    assert_ratio_four_dp(drive["weighted_support_pct"], 0.0000, "weighted_support_pct")
    assert_ratio_four_dp(drive["headcount_support_pct"], 0.0000, "headcount_support_pct")


def test_a_sweep_that_itself_suspends_the_property_still_stages_only_a_notice(api):
    """The second quarter is one day late; its 824500 arrears is under the
    1000000 lien threshold and the property was only on WATCH when the sweep
    began, so the stage is NOTICE rather than LIEN_REFERRED.

    PRD 3.5: "delinquency_stage ... becomes LIEN_REFERRED when either the
    outstanding amount is at least 1000000 cents or the owning property's
    compliance_standing already stood SUSPENDED when the sweep began, before this
    sweep's own strike increment ... A property that reaches SUSPENDED because of
    this very sweep is therefore staged NOTICE, not LIEN_REFERRED."

    Design: Difficulty/transitive_cascade/delinquency_sweep_cascades_four_hops_into_renewal_petition_support
    """
    ctx = _two_periods_filed_with_a_renewal_signature(api)
    fx.set_clock(api, "2027-02-11T00:00:00Z")
    fx.sweep_period(api, ctx)
    fx.close_period(api, ctx, period_key="ap2_id")
    fx.set_clock(api, "2027-02-26T00:00:00Z")
    fx.sweep_period(api, ctx, period_key="ap2_id")

    statement = validate_success(api.get_assessment_statement(ctx.st1_q2_id, headers=ADMIN))
    assert_fields(
        statement,
        payment_status="DELINQUENT",
        delinquency_stage="NOTICE",
        penalty_cents=82450,
        interest_cents=412,
    )

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, delinquent_charges_cents=197468)

    for key in ("ap_id", "ap2_id"):
        period = validate_success(api.get_assessment_period(ctx[key], headers=ADMIN))
        assert_fields(period, status="DELINQUENCY_SWEPT")


# --------------------------------------------------------------------------
# Chain: an abatement that reaches a running program's spend freeze
# --------------------------------------------------------------------------
def _adjusted_dispute_over_a_running_program(api):
    """Abate 400000 cents of a 824500-cent assessment while a 62000-cent program
    is running under an approved 1000000-cent plan."""
    ctx = fx.running_program(api)
    fx.file_dispute(
        api, ctx, dispute_type="CALCULATION_ERROR", claimed_adjustment_cents=400000
    )
    fx.open_dispute_review(api, ctx)
    fx.resolve_dispute(api, ctx, outcome="ADJUSTED", granted_adjustment_cents=400000)
    return ctx


def test_a_granted_adjustment_reduces_the_statement_it_was_filed_against(api):
    """The first hop lands on the statement: 400000 of granted adjustment cuts the
    effective assessment from 824500 to 424500.

    PRD 3.6: "Hop one. The statement's granted_adjustment_cents increases by the
    granted figure, final_assessment_cents is recomputed by the final variant of
    the assessment when it is already non-null, effective_assessment_cents is
    re-derived, and payment_status is re-derived".

    Design: Difficulty/transitive_cascade/granted_dispute_cascades_through_funding_ratio_into_a_frozen_program
    """
    ctx = _adjusted_dispute_over_a_running_program(api)

    dispute = validate_success(api.get_dispute(ctx.dsp_id, headers=ADMIN))
    assert_fields(dispute, status="RESOLVED_ADJUSTED", granted_adjustment_cents=400000)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement,
        granted_adjustment_cents=400000,
        provisional_assessment_cents=824500,
        effective_assessment_cents=424500,
    )


def test_the_reduced_assessment_sinks_the_plan_into_amendment_pending(api):
    """The second hop recomputes the forecast to 424500 plus 340000 and the ratio
    to 0.7645, which is under the 0.9000 floor.

    PRD 3.6: "Hop two. That change in the statement's effective_assessment_cents
    itself forces the district's annual work plan for its current_fiscal_year to
    recompute assessment_revenue_forecast_cents and funding_ratio. An APPROVED
    plan whose recomputed funding_ratio falls below 0.9000 moves APPROVED to
    AMENDMENT_PENDING."

    Design: Difficulty/transitive_cascade/granted_dispute_cascades_through_funding_ratio_into_a_frozen_program
    """
    ctx = _adjusted_dispute_over_a_running_program(api)

    plan = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(
        plan,
        total_budget_cents=1000000,
        assessment_revenue_forecast_cents=764500,
        status="AMENDMENT_PENDING",
    )
    assert_ratio_four_dp(plan["funding_ratio"], 0.7645, "funding_ratio")


def test_the_unfunded_plan_freezes_its_running_program_without_stopping_it(api):
    """The third hop freezes spend on the still-RUNNING program, and closure is
    then refused because performance may not be published against an unfunded
    budget.

    PRD 3.8: "The program's spend_frozen must be false — a running program frozen
    because its funding plan fell into AMENDMENT_PENDING may not be closed, since
    performance may not be published against a budget that is no longer funded,
    and because the program's status is still RUNNING the generic state check does
    not fire and ERR_PROGRAM_SPEND_FROZEN is the only possible outcome."

    Design: Difficulty/transitive_cascade/granted_dispute_cascades_through_funding_ratio_into_a_frozen_program
    """
    ctx = _adjusted_dispute_over_a_running_program(api)

    frozen = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(frozen, status="RUNNING", spend_frozen=True)

    response = api.close_marketing_program(
        ctx.mp_id, f.program_closure_payload(), headers=ADMIN
    )
    validate_error(response, ERR_PROGRAM_SPEND_FROZEN, expected_status=409)

    program = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(program, status="RUNNING", spend_frozen=True, performance_flag="NOT_MEASURED")


def test_a_compliant_amendment_thaws_the_program_and_restores_the_plan(api):
    """Cutting the budget to 800000 lifts the ratio to 0.9556, which returns the
    plan to APPROVED and clears the freeze on its running program.

    PRD 3.7: "On success the plan's status becomes APPROVED — which is how an
    AMENDMENT_PENDING plan returns to good standing once its ratio again reaches
    0.9000 — its version increments by one, every marketing program of the plan
    standing SUSPENDED_PENDING_AMENDMENT returns to PLANNED, and every RUNNING
    program has spend_frozen set back to false."

    Design: Difficulty/transitive_cascade/granted_dispute_cascades_through_funding_ratio_into_a_frozen_program
    """
    ctx = _adjusted_dispute_over_a_running_program(api)

    pending = validate_success(api.get_work_plan(ctx.wp_id))
    lines = [
        f.expenditure_line("SALES_AND_MARKETING", 520000, "reduced autumn campaign"),
        f.expenditure_line("ADMINISTRATION", 120000, "reduced district administration"),
        f.expenditure_line("CONTINGENCY_RESERVE", 80000, "reduced reserve"),
        f.expenditure_line("DESTINATION_EVENTS", 80000, "reduced events programme"),
    ]
    validate_success(
        api.amend_work_plan(
            ctx.wp_id,
            f.work_plan_amendment_payload(pending["version"], lines),
            headers=ADMIN,
        )
    )

    plan = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(
        plan,
        total_budget_cents=800000,
        status="APPROVED",
        revision_count=1,
        assessment_revenue_forecast_cents=764500,
    )
    assert_ratio_four_dp(plan["funding_ratio"], 0.9556, "funding_ratio")

    program = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(program, status="RUNNING", spend_frozen=False)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(statement, effective_assessment_cents=424500)
