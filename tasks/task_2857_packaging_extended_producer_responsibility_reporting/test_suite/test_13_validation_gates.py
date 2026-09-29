"""Admission gates: the satisfied path, the priority order and the two clock windows.

The first test walks the whole fee lifecycle with every gate satisfied; the rest force
several gates to fail at once, or force one gate to fail on either side of a single
instant, and pin the answer the ordering rules require.
"""

from test_helpers import (
    ApiErrorId,
    CompliancePosture,
    FeeVariant,
    InvoiceStatus,
    MembershipStatus,
    NON_EXISTENT_UUID,
    Opinion,
    REGULATOR_HEADERS,
    RegistrationStatus,
    ReportFeeStatus,
    SubmissionStatus,
    VERIFIER_HEADERS,
    VERIFIER_USER_ID,
    assert_cents,
    assert_exact_cents,
    assert_instant_equals,
    assert_invoice,
    assert_membership,
    assert_registration,
    assert_report,
    assert_report_line,
    assert_weight,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

ANOTHER_SKU_UUID = "88888888-8888-4888-8888-888888888888"


# ---------------------------------------------------------------------------
# Every gate satisfied: pricing, billing and close-out all succeed
# ---------------------------------------------------------------------------
def test_the_satisfied_path_prices_bills_and_finalises_the_report(api):
    """Assess, invoice and finalise all pass, and the verification gate stays quiet.

    At 5.500 kg the report sits far below the state's three tonne verification
    threshold, so the final assessment is admitted straight from the submitted
    position; the fifty cent subtotal draws three cents of administration and the
    fifty-three cent bill is what allows the close-out to finalise the report.

    Design: Corner/validations/golden_path_submit_assess_invoice_close_satisfies_every_gate
    """
    chain = fx.base_ca_chain(api)
    officer_headers, admin_headers = chain["officer_headers"], chain["admin_headers"]
    assert_report(chain["report"], verification_required=False)

    assessed = fx.assess_report(api, chain["pro"], chain["report"], FeeVariant.FINAL)
    invoice = fx.issue_invoice(api, chain["pro"], chain["report"], chain["membership"])
    closed = validate_success(
        api.close_report(chain["report"]["id"], f.decision_payload("FINALIZE"), REGULATOR_HEADERS)
    )

    assert_report(
        assessed,
        tier_basis_kg=5.500,
        fee_variant_applied=FeeVariant.FINAL,
        fee_subtotal_cents=50,
    )
    line = validate_success(api.get_report_line(chain["line"]["id"], officer_headers))
    assert_report_line(line, line_fee_cents=50)
    assert_exact_cents(line["line_fee_exact_cents"], 49.5000, "line_fee_exact_cents")
    assert line["eco_mod_detail"][0]["net_pct"] == 0
    assert_invoice(
        invoice,
        status=InvoiceStatus.ISSUED,
        fee_subtotal_cents=50,
        admin_fee_bps_applied=500,
        admin_fee_cents=3,
        total_cents=53,
    )
    assert_report(
        closed,
        submission_status=SubmissionStatus.FINALIZED,
        fee_status=ReportFeeStatus.INVOICED,
    )
    assert_cents(
        validate_success(api.get_producer(chain["producer"]["id"], officer_headers))[
            "assessed_fee_balance_cents"
        ],
        53,
        "assessed_fee_balance_cents",
    )
    registration = validate_success(
        api.get_registration(chain["registration"]["id"], officer_headers)
    )
    assert_registration(registration, compliance_posture=CompliancePosture.COMPLIANT)
    assert_weight(registration["reported_weight_kg_ytd"], 5.500, "reported_weight_kg_ytd")
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], admin_headers)),
        status=MembershipStatus.ACTIVE,
    )


# ---------------------------------------------------------------------------
# Three gates fail at once and the highest-priority one answers
# ---------------------------------------------------------------------------
def test_a_blocked_report_answers_with_its_own_position_not_the_lower_gates(api):
    """A line-less blocked report under a suspended registration answers only once.

    Three separate gates are violated together — the report's own position, the
    registration's suspension and the absence of any line — and the answer is the
    invalid-state refusal, because the suspension cascade has already moved the report
    out of draft.

    Design: Corner/validations/blocked_report_submit_returns_invalid_state_not_the_lower_priority_gates
    """
    chain = fx.base_ca_chain(api)
    headers = chain["officer_headers"]
    second_period = fx.make_reporting_period(
        api,
        chain["program"]["id"],
        period_label="CA-2026-H2",
        data_start="2027-01-01",
        data_end="2027-07-01",
        submission_open="2027-01-01T00:00:00Z",
        submission_deadline="2027-06-30T23:59:59Z",
        correction_window_days=30,
    )
    empty = fx.make_report(api, chain["producer"], chain["registration"], second_period)
    validate_success(
        api.suspend_registration(
            chain["registration"]["id"],
            f.suspend_payload("Missing brand-ownership attestation for 2026"),
            REGULATOR_HEADERS,
        )
    )

    error = validate_error(
        api.submit_report(empty["id"], None, headers), ApiErrorId.INVALID_STATE, 409
    )

    assert error["error_id"] != ApiErrorId.REGISTRATION_NOT_ACTIVE.value
    assert error["error_id"] != ApiErrorId.REPORT_HAS_NO_LINES.value
    assert_report(
        validate_success(api.get_report(empty["id"], headers)),
        submission_status=SubmissionStatus.BLOCKED,
        line_count=0,
    )
    assert_registration(
        validate_success(api.get_registration(chain["registration"]["id"], headers)),
        status=RegistrationStatus.SUSPENDED,
    )
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], headers)),
        submission_status=SubmissionStatus.SUBMITTED,
    )


# ---------------------------------------------------------------------------
# The submission window opens at its own instant, not one tick later
# ---------------------------------------------------------------------------
def test_the_submission_window_admits_the_opening_instant_and_nothing_before_it(api):
    """The identical filing fails one second early and succeeds exactly on the hour.

    A report for the following year is refused while the clock still reads the last
    second of this one, and the same call is admitted the moment the clock reaches the
    period's opening instant, which is what shows the comparison to be inclusive. Both
    filed reports then count towards the running total.

    Design: Corner/validations/submission_window_boundary_rejects_before_open_and_admits_at_exactly_open
    """
    chain = fx.base_ca_chain(api)
    headers = chain["officer_headers"]
    future_period = fx.make_reporting_period(
        api,
        chain["program"]["id"],
        period_label="CA-2027-H1",
        data_start="2027-01-01",
        data_end="2027-07-01",
        submission_open="2027-01-01T00:00:00Z",
        submission_deadline="2027-06-30T23:59:59Z",
        correction_window_days=30,
    )
    future_report = fx.make_report(api, chain["producer"], chain["registration"], future_period)
    future_line = fx.add_line(api, chain["producer"], future_report, chain["sku"], 110)

    fx.set_clock(api, "2026-12-31T23:59:59Z")
    validate_error(
        api.submit_report(future_report["id"], None, headers),
        ApiErrorId.SUBMISSION_WINDOW_NOT_OPEN,
        422,
    )
    assert_report(
        validate_success(api.get_report(future_report["id"], headers)),
        submission_status=SubmissionStatus.DRAFT,
    )

    fx.set_clock(api, "2027-01-01T00:00:00Z")
    submitted = validate_success(api.submit_report(future_report["id"], None, headers))

    assert_report(
        submitted, submission_status=SubmissionStatus.SUBMITTED, total_weight_kg=5.500
    )
    assert_instant_equals(submitted["submitted_at"], "2027-01-01T00:00:00Z", "submitted_at")
    assert_report_line(
        validate_success(api.get_report_line(future_line["id"], headers)),
        line_weight_kg=5.500,
    )
    registration = validate_success(api.get_registration(chain["registration"]["id"], headers))
    assert_registration(registration, compliance_posture=CompliancePosture.COMPLIANT)
    assert_weight(registration["reported_weight_kg_ytd"], 11.000, "reported_weight_kg_ytd")


# ---------------------------------------------------------------------------
# One instant, two endpoints, opposite senses
# ---------------------------------------------------------------------------
def _report_in_correction(api):
    """The standard chain with a qualified opinion and a thirty-day window open."""
    chain = fx.base_ca_chain(api)
    engagement = fx.assign_engagement(api, chain["report"], VERIFIER_USER_ID)
    fx.start_engagement(api, engagement, VERIFIER_HEADERS)
    fx.issue_opinion(
        api,
        engagement,
        VERIFIER_HEADERS,
        Opinion.QUALIFIED,
        "Glass tonnage understated against warehouse records",
    )
    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(report, submission_status=SubmissionStatus.CORRECTION_REQUIRED)
    assert_instant_equals(
        report["correction_due_at"], "2026-08-31T00:00:00Z", "correction_due_at"
    )
    return chain


def test_a_rejection_is_refused_while_the_correction_window_is_still_open(api):
    """The regulator may not write the report off before the producer's time is up.

    The correction instant is thirty days past the opinion, and until the clock passes
    it the rejection is refused outright while the report keeps waiting for its
    correction with nothing priced against it.

    Design: Corner/validations/correction_window_gates_resubmit_and_close_reject_in_opposite_directions
    """
    chain = _report_in_correction(api)
    headers = chain["officer_headers"]

    validate_error(
        api.close_report(
            chain["report"]["id"],
            f.decision_payload("REJECT", "premature rejection attempt"),
            REGULATOR_HEADERS,
        ),
        ApiErrorId.CORRECTION_WINDOW_OPEN,
        409,
    )

    report = validate_success(api.get_report(chain["report"]["id"], headers))
    assert_report(
        report,
        submission_status=SubmissionStatus.CORRECTION_REQUIRED,
        fee_status=ReportFeeStatus.UNASSESSED,
        correction_round=0,
    )
    assert_instant_equals(
        report["correction_due_at"], "2026-08-31T00:00:00Z", "correction_due_at"
    )


def test_once_the_window_has_passed_the_correction_is_refused_and_the_rejection_lands(api):
    """The same instant that closes the producer's door opens the regulator's.

    A day past the correction instant the refiling is refused as expired and the
    correction round stays at nothing, while the rejection that was premature before
    now succeeds, clears the correction instant and leaves the producer compliant with
    no tonnage counted and its membership off probation.

    Design: Corner/validations/correction_window_gates_resubmit_and_close_reject_in_opposite_directions
    """
    chain = _report_in_correction(api)
    headers, admin_headers = chain["officer_headers"], chain["admin_headers"]
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], admin_headers)),
        status=MembershipStatus.PROBATION,
    )
    fx.set_clock(api, "2026-09-01T00:00:00Z")

    validate_error(
        api.resubmit_report(chain["report"]["id"], None, headers),
        ApiErrorId.CORRECTION_WINDOW_EXPIRED,
        422,
    )
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], headers)),
        submission_status=SubmissionStatus.CORRECTION_REQUIRED,
        correction_round=0,
    )

    rejected = validate_success(
        api.close_report(
            chain["report"]["id"],
            f.decision_payload("REJECT", "correction window elapsed with no resubmission"),
            REGULATOR_HEADERS,
        )
    )

    assert_report(
        rejected,
        submission_status=SubmissionStatus.REJECTED,
        correction_due_at=None,
        fee_status=ReportFeeStatus.UNASSESSED,
    )
    registration = validate_success(api.get_registration(chain["registration"]["id"], headers))
    assert_registration(registration, compliance_posture=CompliancePosture.COMPLIANT)
    assert_weight(registration["reported_weight_kg_ytd"], 0.000, "reported_weight_kg_ytd")
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], admin_headers)),
        status=MembershipStatus.ACTIVE,
    )


# ---------------------------------------------------------------------------
# Five stacked failures on one append, answered in the declared order
# ---------------------------------------------------------------------------
def test_the_line_append_answers_each_layer_in_its_declared_order(api):
    """Path, ownership, report position, body reference and referential fit, in turn.

    Each call below violates one more layer than the last while leaving the earlier
    ones satisfied, so the sequence of answers reads out the admission order directly:
    an unknown report beats a foreign unit in the body, ownership beats the body
    reference, an unknown unit named in the body is answered before the report's own
    position, that position answers once the body reference resolves, an unknown unit
    is reported before its ownership is judged, and only then does the mismatch
    answer. The last call, with every layer satisfied, appends the line and rolls the
    report up.

    Design: Corner/validations/report_line_checks_run_existence_then_ownership_then_state_then_referential
    """
    chain = fx.base_ca_chain(api)
    headers = chain["officer_headers"]
    second_period = fx.make_reporting_period(
        api,
        chain["program"]["id"],
        period_label="CA-2026-H2",
        data_start="2027-01-01",
        data_end="2027-07-01",
        submission_open="2027-01-01T00:00:00Z",
        submission_deadline="2027-06-30T23:59:59Z",
        correction_window_days=30,
    )
    draft_report = fx.make_report(api, chain["producer"], chain["registration"], second_period)
    stranger = fx.make_producer(
        api,
        legal_name="Cascade Foods Inc",
        annual_gross_revenue_usd=2000000,
        brand_owner_flag=True,
        contact_email="ops@cascadefoods.example",
    )
    stranger_sku = fx.glass_mini_sku(api, stranger, name="Cascade Cordial 500ml")

    validate_error(
        api.add_report_line(
            NON_EXISTENT_UUID, f.report_line_payload(stranger_sku["id"], 10), headers
        ),
        ApiErrorId.REPORT_NOT_FOUND,
        404,
    )
    validate_error(
        api.add_report_line(
            draft_report["id"],
            f.report_line_payload(stranger_sku["id"], 10),
            fx.officer(stranger),
        ),
        ApiErrorId.NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api.add_report_line(
            chain["report"]["id"], f.report_line_payload(ANOTHER_SKU_UUID, 10), headers
        ),
        ApiErrorId.SKU_NOT_FOUND,
        404,
    )
    validate_error(
        api.add_report_line(
            chain["report"]["id"], f.report_line_payload(chain["sku"]["id"], 10), headers
        ),
        ApiErrorId.REPORT_NOT_IN_DRAFT,
        409,
    )
    validate_error(
        api.add_report_line(
            draft_report["id"], f.report_line_payload(ANOTHER_SKU_UUID, 10), headers
        ),
        ApiErrorId.SKU_NOT_FOUND,
        404,
    )
    validate_error(
        api.add_report_line(
            draft_report["id"], f.report_line_payload(stranger_sku["id"], 10), headers
        ),
        ApiErrorId.SKU_PRODUCER_MISMATCH,
        422,
    )

    appended = validate_success(
        api.add_report_line(
            draft_report["id"], f.report_line_payload(chain["sku"]["id"], 110), headers
        ),
        201,
    )

    assert_report_line(appended, line_weight_kg=5.500)
    assert_report(
        validate_success(api.get_report(draft_report["id"], headers)),
        total_weight_kg=5.500,
        line_count=1,
    )
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], headers)), line_count=1
    )
