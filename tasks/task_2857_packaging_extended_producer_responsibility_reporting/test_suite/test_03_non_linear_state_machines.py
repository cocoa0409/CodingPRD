"""Non-linear state machines: two dimensions on one row and a returning cycle.

A packaging report carries a submission dimension and a fee dimension that move
independently, and the submission dimension can return to a state it already
occupied. A registration does the same across suspension and reinstatement,
dragging its draft reports through the mirror-image cycle.
"""

from test_helpers import (
    CompliancePosture,
    EngagementStatus,
    FeeVariant,
    InvoiceStatus,
    Opinion,
    REGULATOR_HEADERS,
    RegistrationStatus,
    ReportFeeStatus,
    SubmissionStatus,
    VERIFIER_HEADERS,
    VERIFIER_USER_ID,
    assert_engagement,
    assert_instant_equals,
    assert_invoice,
    assert_registration,
    assert_report,
    factories as f,
    fixtures as fx,
    validate_success,
)


def _invoiced_glass_report(api):
    """A submitted 5.500 kg report priced at 50 cents and billed at 53."""
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Ledger Foods Co",
            annual_gross_revenue_usd=8000000,
            contact_email="p6@x.com",
        ),
    )
    assessed = validate_success(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), chain["admin_headers"]
        )
    )
    assert_report(
        assessed,
        submission_status=SubmissionStatus.SUBMITTED,
        fee_status=ReportFeeStatus.FINAL,
        fee_subtotal_cents=50,
    )
    invoice = validate_success(
        api.create_invoice(
            f.invoice_payload(chain["report"]["id"], chain["membership"]["id"]),
            chain["admin_headers"],
        ),
        201,
    )
    assert_invoice(invoice, total_cents=53, status=InvoiceStatus.ISSUED)
    chain["report"] = assessed
    chain["invoice"] = invoice
    return chain


def test_the_fee_and_submission_dimensions_advance_independently(api):
    """Pricing moves only the money dimension; assigning a verifier only the other.

    The final assessment leaves the report in SUBMITTED while its fee dimension
    reaches FINAL, and the engagement assignment then carries the submission
    dimension to UNDER_VERIFICATION while the fee dimension stays INVOICED.

    Design: Difficulty/non_linear_state_machine/report_parallel_dimensions_and_correction_cycle
    """
    chain = _invoiced_glass_report(api)

    billed = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(
        billed,
        submission_status=SubmissionStatus.SUBMITTED,
        fee_status=ReportFeeStatus.INVOICED,
    )

    engagement = fx.assign_engagement(
        api,
        chain["report"],
        VERIFIER_USER_ID,
        fieldwork_start="2026-09-10",
        fieldwork_end="2026-09-12",
    )
    assert_engagement(engagement, status=EngagementStatus.ASSIGNED, round_index=1)

    under_verification = validate_success(
        api.get_report(chain["report"]["id"], chain["officer_headers"])
    )
    assert_report(
        under_verification,
        submission_status=SubmissionStatus.UNDER_VERIFICATION,
        fee_status=ReportFeeStatus.INVOICED,
    )


def test_an_adverse_opinion_and_a_resubmission_complete_the_correction_cycle(api):
    """The submission dimension returns to SUBMITTED with the round counter raised.

    An adverse opinion drives the report to CORRECTION_REQUIRED with a thirty-day
    correction window and voids the money dimension; the resubmission takes the
    report back to SUBMITTED, clears the window, raises correction_round from zero
    to one and resets the fee dimension to UNASSESSED with no variant applied.

    Design: Difficulty/non_linear_state_machine/report_parallel_dimensions_and_correction_cycle
    """
    chain = _invoiced_glass_report(api)
    engagement = fx.assign_engagement(
        api,
        chain["report"],
        VERIFIER_USER_ID,
        fieldwork_start="2026-09-10",
        fieldwork_end="2026-09-12",
    )
    fx.start_engagement(api, engagement, VERIFIER_HEADERS)
    engagement = fx.issue_opinion(
        api,
        engagement,
        VERIFIER_HEADERS,
        Opinion.ADVERSE,
        findings_note="Understated glass tonnage",
    )
    assert_engagement(engagement, status=EngagementStatus.OPINION_ISSUED, round_index=1)

    in_correction = validate_success(
        api.get_report(chain["report"]["id"], chain["officer_headers"])
    )
    assert_report(
        in_correction,
        submission_status=SubmissionStatus.CORRECTION_REQUIRED,
        fee_status=ReportFeeStatus.VOIDED,
        correction_round=0,
    )
    assert_instant_equals(
        in_correction["correction_due_at"], "2026-10-01T00:00:00Z", "correction_due_at"
    )

    resubmitted = validate_success(
        api.resubmit_report(chain["report"]["id"], None, chain["officer_headers"])
    )
    assert_report(
        resubmitted,
        submission_status=SubmissionStatus.SUBMITTED,
        fee_status=ReportFeeStatus.UNASSESSED,
        correction_round=1,
        correction_due_at=None,
        fee_subtotal_cents=0,
        fee_variant_applied=FeeVariant.NONE,
    )


def _active_registration_with_a_draft_report(api):
    """An ACTIVE registration whose only report is still DRAFT and empty."""
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Cycle Co",
            annual_gross_revenue_usd=9000000,
            contact_email="p8@x.com",
        ),
        sku_overrides=dict(name="Cycle Jar", product_category="HOUSEHOLD_CHEM"),
        with_membership=False,
        with_report=False,
    )
    report = fx.make_report(api, chain["producer"], chain["registration"], chain["period"])
    assert_report(
        report, submission_status=SubmissionStatus.DRAFT, fee_status=ReportFeeStatus.UNASSESSED
    )
    chain["report"] = report
    return chain


def test_suspending_a_registration_blocks_its_draft_report(api):
    """The registration leaves ACTIVE and the draft report follows it into BLOCKED.

    The posture recomputation yields DELINQUENT for as long as the registration
    stays suspended, and the supplied reason is stored on the row.

    Design: Difficulty/non_linear_state_machine/registration_suspend_reinstate_cycle
    """
    chain = _active_registration_with_a_draft_report(api)
    before = validate_success(
        api.get_registration(chain["registration"]["id"], chain["officer_headers"])
    )
    assert_registration(
        before,
        status=RegistrationStatus.ACTIVE,
        compliance_posture=CompliancePosture.COMPLIANT,
        suspension_reason=None,
    )

    suspended = validate_success(
        api.suspend_registration(
            chain["registration"]["id"], f.suspend_payload("AUDIT_OPEN"), REGULATOR_HEADERS
        )
    )

    assert_registration(
        suspended,
        status=RegistrationStatus.SUSPENDED,
        suspension_reason="AUDIT_OPEN",
        compliance_posture=CompliancePosture.DELINQUENT,
    )
    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(report, submission_status=SubmissionStatus.BLOCKED)


def test_reinstating_the_registration_returns_both_rows_to_where_they_started(api):
    """The cycle closes: ACTIVE again, the reason cleared and the report back in DRAFT.

    Two mutating calls move the registration's version by exactly two, and the
    recomputed posture returns to COMPLIANT.

    Design: Difficulty/non_linear_state_machine/registration_suspend_reinstate_cycle
    """
    chain = _active_registration_with_a_draft_report(api)
    before = validate_success(
        api.get_registration(chain["registration"]["id"], chain["officer_headers"])
    )
    suspended = validate_success(
        api.suspend_registration(
            chain["registration"]["id"], f.suspend_payload("AUDIT_OPEN"), REGULATOR_HEADERS
        )
    )
    assert_registration(suspended, status=RegistrationStatus.SUSPENDED)

    reinstated = validate_success(
        api.reinstate_registration(chain["registration"]["id"], None, REGULATOR_HEADERS)
    )

    assert_registration(
        reinstated,
        status=RegistrationStatus.ACTIVE,
        suspension_reason=None,
        compliance_posture=CompliancePosture.COMPLIANT,
    )
    assert reinstated["version"] == before["version"] + 2, (
        f"registration version: expected {before['version'] + 2}, got {reinstated['version']}"
    )
    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(report, submission_status=SubmissionStatus.DRAFT)
