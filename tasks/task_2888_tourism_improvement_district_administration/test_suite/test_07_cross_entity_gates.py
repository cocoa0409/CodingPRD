"""Transitions that are blocked by the state of a different entity.

Each test here builds a target that is perfectly eligible on its own terms and
then shows the request refused because some other record is not yet where the
transition requires it to be.  In every case the same request is repeated once
the other record has moved, so the gate is observed opening as well as closing.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DMO_AGREEMENT_NOT_EXECUTED,
    ERR_PERIOD_NOT_CLOSED,
    ERR_TRANSPARENCY_REQUIREMENTS_UNMET,
)
from test_helpers.assertions import assert_fields, assert_instant_equals, assert_null_fields
from test_helpers.test_users import ADMIN, ADMIN_2, AUDITOR, AUDITOR_USER_ID, DMO_LIAISON


# --------------------------------------------------------------------------
# A program launch gated on the district's DMO agreement
# --------------------------------------------------------------------------
def _planned_program_without_an_agreement(api):
    """Create a program under an approved plan, put the clock inside its booking
    window, and leave the district's DMO agreement unrecorded."""
    ctx = fx.statements_filed(api)
    fx.approved_work_plan(api, ctx)
    fx.create_program(api, ctx)
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    return ctx


def test_launch_is_refused_while_the_district_has_no_dmo_agreement(api):
    """The program is PLANNED, its plan is APPROVED and the clock is inside the
    booking window, but the district's agreement stands at NONE.

    PRD 3.8: "the district's dmo_agreement_status must be EXECUTED — a program in
    a perfectly valid PLANNED state still cannot go to market under a merely
    PROPOSED or TERMINATED agreement, which is refused with
    ERR_DMO_AGREEMENT_NOT_EXECUTED".

    Design: Difficulty/cross_entity_state_dependency/program_launch_gated_on_the_district_dmo_agreement_reaching_executed
    """
    ctx = _planned_program_without_an_agreement(api)

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, dmo_agreement_status="NONE", status="ACTIVE")

    response = api.launch_marketing_program(ctx.mp_id, f.launch_payload(), headers=DMO_LIAISON)
    validate_error(response, ERR_DMO_AGREEMENT_NOT_EXECUTED, expected_status=409)

    program = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(program, status="PLANNED")
    assert_null_fields(program, "launched_at")


def test_a_merely_proposed_agreement_still_does_not_open_the_gate(api):
    """Recording the agreement as PROPOSED moves the district but not far enough,
    and the launch is refused with the same error.

    PRD 3.1: "Moving dmo_agreement_status to EXECUTED is the cross-entity gate
    that lets marketing programs launch at all."

    Design: Difficulty/cross_entity_state_dependency/program_launch_gated_on_the_district_dmo_agreement_reaching_executed
    """
    ctx = _planned_program_without_an_agreement(api)
    fx.execute_dmo_agreement(api, ctx, dmo_agreement_status="PROPOSED")

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, dmo_agreement_status="PROPOSED")

    response = api.launch_marketing_program(ctx.mp_id, f.launch_payload(), headers=DMO_LIAISON)
    validate_error(response, ERR_DMO_AGREEMENT_NOT_EXECUTED, expected_status=409)

    program = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(program, status="PLANNED")
    assert_null_fields(program, "launched_at")


def test_an_executed_agreement_lets_the_unchanged_program_launch(api):
    """With the agreement at EXECUTED the identical launch request succeeds and
    stamps launched_at from the logical clock.

    PRD 3.8: "On success the program moves PLANNED to RUNNING and launched_at is
    stamped from the logical clock."

    Design: Difficulty/cross_entity_state_dependency/program_launch_gated_on_the_district_dmo_agreement_reaching_executed
    """
    ctx = _planned_program_without_an_agreement(api)
    fx.execute_dmo_agreement(api, ctx, dmo_agreement_status="PROPOSED")
    fx.execute_dmo_agreement(api, ctx)

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(
        district, dmo_agreement_status="EXECUTED", lodging_tax_match_pool_cents=400000
    )

    program = validate_success(
        api.launch_marketing_program(ctx.mp_id, f.launch_payload(), headers=DMO_LIAISON)
    )
    assert_fields(program, status="RUNNING")
    assert_instant_equals(program["launched_at"], "2026-09-01T00:00:00Z", "launched_at")

    plan = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(plan, status="APPROVED")


# --------------------------------------------------------------------------
# An audit gated on the owning period leaving OPEN
# --------------------------------------------------------------------------
def test_an_audit_is_refused_while_the_owning_period_is_still_open(api):
    """The statement's own filing_status is FILED and therefore eligible, yet the
    audit is refused because its period has not been closed.

    PRD 3.3: "it requires the owning period to have left OPEN — the period must be
    CLOSED or DELINQUENCY_SWEPT, and an attempt while the period is still OPEN is
    refused with ERR_PERIOD_NOT_CLOSED even though the statement's own
    filing_status was perfectly eligible."

    Design: Difficulty/cross_entity_state_dependency/audit_certification_gated_on_the_owning_period_leaving_open
    """
    ctx = fx.statements_filed(api)

    period = validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN))
    assert_fields(period, status="OPEN")

    response = api.audit_certify_statement(
        ctx.st1_id, f.audit_payload(audit_note="field audit"), headers=AUDITOR
    )
    validate_error(response, ERR_PERIOD_NOT_CLOSED, expected_status=409)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(statement, filing_status="FILED", provisional_assessment_cents=824500)
    assert_null_fields(statement, "final_assessment_cents", "audited_by_user_id")


def test_closing_the_period_opens_the_gate_for_the_same_audit(api):
    """Once the clock reaches period_end and the period is closed, the identical
    audit request is accepted and writes the final variant.

    PRD 3.3: "The audit stores the audited figures, records audited_by_user_id
    from the acting X-User-ID, computes the final variant of the assessment into
    final_assessment_cents, sets effective_assessment_cents to that figure,
    recomputes the period's billed_total_cents".

    Design: Difficulty/cross_entity_state_dependency/audit_certification_gated_on_the_owning_period_leaving_open
    """
    ctx = fx.statements_filed(api)
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    closed = fx.close_period(api, ctx)
    assert_fields(closed, status="CLOSED", billed_total_cents=1164500)

    statement = validate_success(
        api.audit_certify_statement(
            ctx.st1_id, f.audit_payload(audit_note="field audit"), headers=AUDITOR
        )
    )
    assert_fields(
        statement,
        filing_status="AUDITED",
        final_assessment_cents=824500,
        effective_assessment_cents=824500,
        audited_by_user_id=AUDITOR_USER_ID,
    )


# --------------------------------------------------------------------------
# Renewal gated on two published transparency artifacts
# --------------------------------------------------------------------------
def _district_with_two_noticed_transparency_records(api):
    """Schedule and notice an annual report and a financial audit for fiscal 2027,
    then put the clock inside the district's renewal window.

    The term runs one year from 2026-08-01, so the window opens on 2027-02-02.
    Both records are targeted at 2027-01-25 and noticed on 2027-01-05, twenty
    whole days ahead.
    """
    ctx = fx.active_district(api)
    fx.set_clock(api, "2027-01-05T00:00:00Z")
    for record_type, key in (("ANNUAL_REPORT", "tr_ar"), ("FINANCIAL_AUDIT", "tr_fa")):
        fx.schedule_transparency_record(
            api,
            ctx,
            key=key,
            record_type=record_type,
            fiscal_year=2027,
            scheduled_for="2027-01-25T00:00:00Z",
            required_by="2027-03-01T00:00:00Z",
        )
        fx.advance_transparency_record(api, ctx, "NOTICED", record_key=key)
    fx.set_clock(api, "2027-02-10T00:00:00Z")
    return ctx


def _request_renewal_pending(api, ctx):
    return api.advance_district_lifecycle(
        ctx.d_id,
        f.lifecycle_advance_payload("RENEWAL_PENDING", "2027-02-10T00:00:00Z"),
        headers=ADMIN,
    )


def test_renewal_is_refused_while_both_artifacts_are_only_noticed(api):
    """The clock is inside the renewal window and the standing is COMPLIANT, but
    neither the annual report nor the financial audit has been published.

    PRD 3.9: "Before a district may enter RENEWAL_PENDING, and before a RENEWAL
    petition drive may be certified, the district must hold PUBLISHED records of
    record_type ANNUAL_REPORT and of record_type FINANCIAL_AUDIT for its
    current_fiscal_year, and its transparency_standing must not be DEFICIENT."

    Design: Difficulty/cross_entity_state_dependency/renewal_pending_gated_on_published_annual_report_and_financial_audit
    """
    ctx = _district_with_two_noticed_transparency_records(api)

    validate_error(
        _request_renewal_pending(api, ctx),
        ERR_TRANSPARENCY_REQUIREMENTS_UNMET,
        expected_status=409,
    )

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, status="ACTIVE", transparency_standing="COMPLIANT")


def test_publishing_only_the_annual_report_still_leaves_the_gate_shut(api):
    """One of the two required artifacts is not enough: the gate reads both, so it
    reports the same shortfall with the annual report already PUBLISHED.

    PRD 3.9: "A district failing any arm of that test is refused with
    ERR_TRANSPARENCY_REQUIREMENTS_UNMET, however strong its petition support may
    be."

    Design: Difficulty/cross_entity_state_dependency/renewal_pending_gated_on_published_annual_report_and_financial_audit
    """
    ctx = _district_with_two_noticed_transparency_records(api)
    fx.advance_transparency_record(
        api, ctx, "COMPLETED", record_key="tr_ar", document_reference="ar-2027-draft"
    )
    fx.advance_transparency_record(
        api, ctx, "PUBLISHED", record_key="tr_ar", document_reference="ar-2027-final"
    )

    report = validate_success(api.get_transparency_record(ctx.tr_ar))
    assert_fields(report, status="PUBLISHED", document_reference="ar-2027-final")
    audit = validate_success(api.get_transparency_record(ctx.tr_fa))
    assert_fields(audit, status="NOTICED")

    validate_error(
        _request_renewal_pending(api, ctx),
        ERR_TRANSPARENCY_REQUIREMENTS_UNMET,
        expected_status=409,
    )

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, status="ACTIVE", transparency_standing="COMPLIANT")


def test_publishing_both_artifacts_opens_the_renewal_window(api):
    """With the financial audit published by a second administrator, the same
    lifecycle request is accepted and the district enters RENEWAL_PENDING.

    PRD 3.2: "On success status becomes RENEWAL_PENDING, and the cycle ACTIVE to
    RENEWAL_PENDING to ACTIVE closes when the renewal drive is certified."

    Design: Difficulty/cross_entity_state_dependency/renewal_pending_gated_on_published_annual_report_and_financial_audit
    """
    ctx = _district_with_two_noticed_transparency_records(api)
    fx.advance_transparency_record(
        api, ctx, "COMPLETED", record_key="tr_ar", document_reference="ar-2027-draft"
    )
    fx.advance_transparency_record(
        api, ctx, "PUBLISHED", record_key="tr_ar", document_reference="ar-2027-final"
    )
    fx.advance_transparency_record(
        api,
        ctx,
        "COMPLETED",
        record_key="tr_fa",
        document_reference="fa-2027-fieldwork",
        headers=ADMIN_2,
    )
    fx.advance_transparency_record(
        api,
        ctx,
        "PUBLISHED",
        record_key="tr_fa",
        document_reference="fa-2027-opinion",
        headers=ADMIN_2,
    )

    district = validate_success(
        api.advance_district_lifecycle(
            ctx.d_id,
            f.lifecycle_advance_payload("RENEWAL_PENDING", "2027-02-10T00:00:00Z"),
            headers=ADMIN,
        )
    )
    assert_fields(district, status="RENEWAL_PENDING", transparency_standing="COMPLIANT")
