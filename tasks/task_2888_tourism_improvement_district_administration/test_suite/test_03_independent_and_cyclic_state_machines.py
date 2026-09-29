"""State machines that are not a single line from start to finish.

An assessment statement carries two independent status dimensions that advance
without waiting for each other, and a dispute carries two cycles that differ in
kind: the information cycle repeats without limit while the appeal cycle fires
exactly once.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_APPEAL_LIMIT_EXCEEDED
from test_helpers.assertions import assert_fields
from test_helpers.test_users import (
    ADMIN,
    AUDITOR,
    AUDITOR_2,
    HEARING_OFFICER,
    operator_headers,
)


# --------------------------------------------------------------------------
# Chain: one statement walked along the filing and the payment axis in turn
# --------------------------------------------------------------------------
def test_a_payment_lands_while_the_filing_dimension_is_still_filed(api):
    """Part-paying a FILED statement moves payment_status to PARTIALLY_PAID and
    leaves filing_status exactly where it was.

    PRD 3.3: "Neither of these two moves touches filing_status, and no payment
    transition anywhere touches it either."

    Design: Difficulty/non_linear_state_machine/statement_filing_and_payment_dimensions_advance_independently
    """
    ctx = fx.statements_filed(api)
    fx.remit(api, ctx, "st1_id", "b1_id", 300000, received_on="2026-08-01T00:00:00Z", method="ACH")

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement,
        filing_status="FILED",
        payment_status="PARTIALLY_PAID",
        provisional_assessment_cents=824500,
        principal_paid_cents=300000,
        total_due_cents=524500,
    )


def test_an_audit_advances_the_filing_dimension_and_leaves_the_payment_alone(api):
    """Auditing a part-paid statement moves filing_status FILED to AUDITED while
    payment_status stays PARTIALLY_PAID.

    PRD 3.3: "Auditing is accepted from FILED or AMENDED, moving the statement to
    AUDITED in either case".

    Design: Difficulty/non_linear_state_machine/statement_filing_and_payment_dimensions_advance_independently
    """
    ctx = fx.statements_filed(api)
    fx.remit(api, ctx, "st1_id", "b1_id", 300000, received_on="2026-08-01T00:00:00Z", method="ACH")
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)
    fx.audit_statement(api, ctx, "st1_id", headers=AUDITOR)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement,
        filing_status="AUDITED",
        payment_status="PARTIALLY_PAID",
        final_assessment_cents=824500,
        effective_assessment_cents=824500,
        principal_paid_cents=300000,
        total_due_cents=524500,
    )


def test_the_two_dimensions_reach_certified_and_paid_in_full_out_of_step(api):
    """Walking the two axes alternately gives four distinct pairs, ending at
    CERTIFIED and PAID_IN_FULL without either axis ever waiting on the other.

    PRD 3.3: "With action CERTIFY, the statement moves AUDITED to CERTIFIED and
    its amount is locked permanently."

    Design: Difficulty/non_linear_state_machine/statement_filing_and_payment_dimensions_advance_independently
    """
    ctx = fx.statements_filed(api)
    fx.remit(api, ctx, "st1_id", "b1_id", 300000, received_on="2026-08-01T00:00:00Z", method="ACH")
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)
    fx.audit_statement(api, ctx, "st1_id", headers=AUDITOR)
    fx.remit(
        api,
        ctx,
        "st1_id",
        "b1_id",
        524500,
        received_on="2026-11-05T00:00:00Z",
        method="WIRE",
        key="rem2_id",
    )

    paid = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(paid, filing_status="AUDITED", payment_status="PAID_IN_FULL")

    validate_success(
        api.audit_certify_statement(ctx.st1_id, f.certify_statement_payload(), headers=AUDITOR_2)
    )

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement,
        filing_status="CERTIFIED",
        payment_status="PAID_IN_FULL",
        principal_paid_cents=824500,
        total_due_cents=0,
        credit_balance_cents=0,
    )

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, collected_to_date_cents=824500)


# --------------------------------------------------------------------------
# Chain: a dispute driven twice around the info cycle and once around appeal
# --------------------------------------------------------------------------
def _dispute_after_two_info_rounds(api):
    """File a 400000-cent dispute, open review, and run the information cycle
    twice so the dispute ends back in UNDER_REVIEW."""
    ctx = fx.statements_filed(api)
    fx.file_dispute(
        api, ctx, dispute_type="CALCULATION_ERROR", claimed_adjustment_cents=400000
    )
    fx.open_dispute_review(api, ctx)
    operator = operator_headers(ctx.b1_id)
    for _ in range(2):
        validate_success(
            api.advance_dispute(
                ctx.dsp_id, f.proceeding_payload("REQUEST_INFO"), headers=HEARING_OFFICER
            )
        )
        validate_success(
            api.advance_dispute(
                ctx.dsp_id, f.proceeding_payload("SUBMIT_RESPONSE"), headers=operator
            )
        )
    return ctx


def test_the_information_cycle_repeats_without_limit(api):
    """Two full REQUEST_INFO and SUBMIT_RESPONSE rounds are both accepted and the
    dispute is back in UNDER_REVIEW with no appeal recorded.

    PRD 3.6: "REQUEST_INFO moves an UNDER_REVIEW dispute to INFO_REQUESTED, and
    SUBMIT_RESPONSE moves it back from INFO_REQUESTED to UNDER_REVIEW. This
    information cycle may repeat without limit; there is no cap on how many times
    a hearing officer may ask for more material."

    Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_repeats_but_appeal_cycle_is_one_shot
    """
    ctx = _dispute_after_two_info_rounds(api)

    dispute = validate_success(api.get_dispute(ctx.dsp_id, headers=ADMIN))
    assert_fields(dispute, status="UNDER_REVIEW", appeal_count=0, granted_adjustment_cents=0)


def test_the_first_appeal_reopens_an_upheld_dispute_for_review(api):
    """An UPHELD resolution is appealable exactly once, and the appeal returns the
    dispute to UNDER_REVIEW with appeal_count at 1.

    PRD 3.6: "APPEAL moves a RESOLVED_UPHELD dispute back to UNDER_REVIEW,
    increments appeal_count by one and clears resolved_by_user_id back to null."

    Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_repeats_but_appeal_cycle_is_one_shot
    """
    ctx = _dispute_after_two_info_rounds(api)
    fx.resolve_dispute(api, ctx, outcome="UPHELD")

    upheld = validate_success(api.get_dispute(ctx.dsp_id, headers=ADMIN))
    assert_fields(upheld, status="RESOLVED_UPHELD", granted_adjustment_cents=0, appeal_count=0)

    validate_success(
        api.advance_dispute(
            ctx.dsp_id, f.proceeding_payload("APPEAL"), headers=operator_headers(ctx.b1_id)
        )
    )

    appealed = validate_success(api.get_dispute(ctx.dsp_id, headers=ADMIN))
    assert_fields(appealed, status="UNDER_REVIEW", appeal_count=1)
    assert appealed["resolved_by_user_id"] is None


def test_the_second_appeal_is_refused_once_appeal_count_has_reached_one(api):
    """After the appealed dispute is upheld again, a second APPEAL is refused and
    neither the status nor appeal_count moves.

    PRD 3.6: "The appeal cycle is one-shot: at most one appeal may be taken, so
    the action is refused with ERR_APPEAL_LIMIT_EXCEEDED once appeal_count has
    reached 1."

    Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_repeats_but_appeal_cycle_is_one_shot
    """
    ctx = _dispute_after_two_info_rounds(api)
    operator = operator_headers(ctx.b1_id)
    fx.resolve_dispute(api, ctx, outcome="UPHELD")
    validate_success(
        api.advance_dispute(ctx.dsp_id, f.proceeding_payload("APPEAL"), headers=operator)
    )
    fx.resolve_dispute(api, ctx, outcome="UPHELD")

    response = api.advance_dispute(
        ctx.dsp_id, f.proceeding_payload("APPEAL"), headers=operator
    )
    validate_error(response, ERR_APPEAL_LIMIT_EXCEEDED, expected_status=409)

    dispute = validate_success(api.get_dispute(ctx.dsp_id, headers=ADMIN))
    assert_fields(dispute, status="RESOLVED_UPHELD", appeal_count=1, granted_adjustment_cents=0)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(statement, effective_assessment_cents=824500, granted_adjustment_cents=0)
