"""Every total a write derives is already in the response that write returns.

There is no deferred recomputation anywhere in this API: the filing that computes
an assessment publishes it in its own body, and the payment that moves money
reaches the district's ledger before the 201 is written.  Each test here reads
the same figures a second and a third time, from the owning record and from the
public summary, and finds them unmoved.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_instant_equals
from test_helpers.test_users import ADMIN, operator_headers


# --------------------------------------------------------------------------
# The filing response is the whole recompute
# --------------------------------------------------------------------------
def test_the_filing_response_already_carries_every_total_the_next_read_returns(api):
    """One filing computes an assessment, re-derives the statement's own totals, the
    owning period's billed figure and the district's public summary.  All of it is
    visible in the response body itself, and the three reads that follow return the
    same integers rather than a stale or a null one.

    PRD 3.3: "On acceptance the reported figures are stored, filed_at is stamped from
    the logical clock, the statement moves NOT_FILED to FILED, the provisional variant
    of the assessment is computed into provisional_assessment_cents,
    effective_assessment_cents and total_due_cents are re-derived, and the owning
    period's billed_total_cents is recomputed."

    PRD 3.1: "For transparency purposes the district also publishes a computed
    financial summary, derived on read from the statements themselves and never
    stored."

    Design: Corner/consistency_model/the_filing_response_already_carries_every_derived_total
    """
    ctx = fx.period_with_statements(api)

    filed = validate_success(
        api.file_statement(
            ctx.st1_id,
            f.filing_payload(2000, 41225000),
            headers=operator_headers(ctx.b1_id),
        ),
    )
    expected = {
        "filing_status": "FILED",
        "reported_room_nights": 2000,
        "reported_gross_room_revenue_cents": 41225000,
        "provisional_assessment_cents": 824500,
        "effective_assessment_cents": 824500,
        "total_due_cents": 824500,
        "version": 2,
    }
    assert_fields(filed, **expected)
    assert_instant_equals(filed["filed_at"], "2026-08-01T00:00:00Z", "filed_at")

    reread = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(reread, **expected)
    assert_instant_equals(reread["filed_at"], "2026-08-01T00:00:00Z", "filed_at")

    period = validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN))
    assert_fields(period, billed_total_cents=824500, collected_total_cents=0)

    summary = validate_success(
        api.get_district_financial_summary(
            ctx.d_id, headers=None, params={"fiscal_year": 2027}
        )
    )
    assert_fields(
        summary,
        billed_total_cents=824500,
        collected_to_date_cents=0,
        statement_count=4,
        delinquent_statement_count=0,
    )

    again = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(again, **expected)
    assert_fields(
        validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN)),
        billed_total_cents=824500,
    )


# --------------------------------------------------------------------------
# The payment reaches three records before the 201 returns
# --------------------------------------------------------------------------
def test_a_payment_reaches_the_district_ledger_before_its_own_response_returns(api):
    """The remittance body already records how the money was split, and by the time
    that 201 has been written the statement stands PAID_IN_FULL, the period's
    collected total has moved and the district's ledger has moved with it.

    PRD 3.4: "The statement's interest_paid_cents, penalty_paid_cents,
    principal_paid_cents and credit_balance_cents are then each increased by the
    corresponding allocation, and the district's collected_to_date_cents together
    with the period's collected_total_cents are increased by the full amount_cents."

    PRD 3.4: "Each accepted remittance creates its own record with status APPLIED,
    reversed_on and reversal_reason null, and version 1."

    Design: Corner/consistency_model/a_remittance_reaches_the_district_ledger_inside_the_same_request
    """
    ctx = fx.period_with_statements(api)
    fx.file_statement(api, ctx, "st1_id", "b1_id", 2000, 41225000)

    remittance = fx.remit(api, ctx, "st1_id", "b1_id", 824500)
    assert_fields(
        remittance,
        status="APPLIED",
        amount_cents=824500,
        applied_to_interest_cents=0,
        applied_to_penalty_cents=0,
        applied_to_principal_cents=824500,
        applied_to_credit_cents=0,
        version=1,
    )

    paid = {
        "payment_status": "PAID_IN_FULL",
        "principal_paid_cents": 824500,
        "credit_balance_cents": 0,
        "total_due_cents": 0,
        "version": 3,
    }
    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(statement, **paid)
    assert_fields(
        validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN)), **paid
    )

    assert_fields(
        validate_success(api.get_district(ctx.d_id)), collected_to_date_cents=824500
    )
    assert_fields(
        validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN)),
        collected_total_cents=824500,
        billed_total_cents=824500,
    )

    summary = validate_success(
        api.get_district_financial_summary(
            ctx.d_id, headers=None, params={"fiscal_year": 2027}
        )
    )
    assert_fields(
        summary,
        billed_total_cents=824500,
        collected_to_date_cents=824500,
        credit_total_cents=0,
        delinquent_charges_cents=0,
    )
