"""Compensating operations return the conserved rollups to their exact prior value.

Both rollups are recomputed from their source set rather than nudged by deltas, so
each pair of forward and compensating operations must land on the byte-identical
integer or three-decimal figure it started from, with no residue after two cycles.
"""

from test_helpers import (
    ApiErrorId,
    EngagementStatus,
    InvoiceStatus,
    MembershipStatus,
    Opinion,
    REGULATOR_HEADERS,
    ReportFeeStatus,
    SubmissionStatus,
    VERIFIER_HEADERS,
    VERIFIER_ALT_HEADERS,
    VERIFIER_USER_ID,
    VERIFIER_USER_ID_ALT,
    assert_cents,
    assert_engagement,
    assert_instant_equals,
    assert_invoice,
    assert_report,
    assert_report_line,
    assert_weight,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

OPERATOR_VOID_REASON = "Issued against the wrong billing contact"


# ---------------------------------------------------------------------------
# Conserved quantity one: money in whole cents on the producer's balance
# ---------------------------------------------------------------------------
def _finally_assessed_report(api):
    """A FINAL-assessed 5.500 kg report whose producer still owes nothing."""
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Money Conservation Co",
            annual_gross_revenue_usd=8000000,
            contact_email="pm@x.com",
        ),
        sku_overrides=dict(name="Money Jar", product_category="HOUSEHOLD_CHEM"),
    )
    producer = validate_success(
        api.get_producer(chain["producer"]["id"], chain["officer_headers"])
    )
    assert_cents(producer["assessed_fee_balance_cents"], 0, "assessed_fee_balance_cents")

    assessed = fx.assess_report(api, chain["pro"], chain["report"], "FINAL")
    assert_report(
        assessed,
        fee_status=ReportFeeStatus.FINAL,
        fee_subtotal_cents=50,
        total_weight_kg=5.500,
    )
    return chain


def test_voiding_the_invoice_returns_the_balance_to_exactly_zero(api):
    """Issuing then voiding the invoice leaves the producer owing nothing again.

    The fifty-cent subtotal falls in the low administrative bracket, so the bill is
    three cents of administration on top and a total of fifty-three; after the
    operator void the balance is recomputed from the issued set and is exactly zero,
    while the voided row keeps its own money fields and the report is priced again.

    Design: Difficulty/compensating_invariant/invoice_issue_void_reissue_restores_fee_balance_exactly
    """
    chain = _finally_assessed_report(api)
    officer_headers, admin_headers = chain["officer_headers"], chain["admin_headers"]

    invoice = fx.issue_invoice(api, chain["pro"], chain["report"], chain["membership"])
    assert_invoice(
        invoice,
        fee_subtotal_cents=50,
        admin_fee_bps_applied=500,
        admin_fee_cents=3,
        total_cents=53,
        status=InvoiceStatus.ISSUED,
        void_reason=None,
    )
    producer = validate_success(api.get_producer(chain["producer"]["id"], officer_headers))
    assert_cents(producer["assessed_fee_balance_cents"], 53, "assessed_fee_balance_cents")
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], officer_headers)),
        fee_status=ReportFeeStatus.INVOICED,
    )

    voided = validate_success(
        api.void_invoice(invoice["id"], f.void_payload(OPERATOR_VOID_REASON), admin_headers)
    )

    assert_invoice(
        voided,
        status=InvoiceStatus.VOID,
        void_reason=OPERATOR_VOID_REASON,
        fee_subtotal_cents=50,
        admin_fee_cents=3,
        total_cents=53,
    )
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], officer_headers)),
        fee_status=ReportFeeStatus.FINAL,
        fee_subtotal_cents=50,
    )
    producer = validate_success(api.get_producer(chain["producer"]["id"], officer_headers))
    assert_cents(producer["assessed_fee_balance_cents"], 0, "assessed_fee_balance_cents")


def test_reissuing_after_the_void_restores_the_balance_without_drift(api):
    """The same report billed a second time reproduces the same fifty-three cents.

    Re-invoicing the still-priced report puts the identical total back on the
    balance, and a second void of the already-voided first invoice is refused
    without disturbing that figure by a single cent in either direction.

    Design: Difficulty/compensating_invariant/invoice_issue_void_reissue_restores_fee_balance_exactly
    """
    chain = _finally_assessed_report(api)
    officer_headers, admin_headers = chain["officer_headers"], chain["admin_headers"]

    first = fx.issue_invoice(api, chain["pro"], chain["report"], chain["membership"])
    validate_success(
        api.void_invoice(first["id"], f.void_payload(OPERATOR_VOID_REASON), admin_headers)
    )
    second = fx.issue_invoice(api, chain["pro"], chain["report"], chain["membership"])

    assert_invoice(
        second,
        fee_subtotal_cents=50,
        admin_fee_bps_applied=500,
        admin_fee_cents=3,
        total_cents=53,
        status=InvoiceStatus.ISSUED,
        void_reason=None,
    )
    assert second["id"] != first["id"]
    producer = validate_success(api.get_producer(chain["producer"]["id"], officer_headers))
    assert_cents(producer["assessed_fee_balance_cents"], 53, "assessed_fee_balance_cents")

    validate_error(
        api.void_invoice(first["id"], f.void_payload("Second attempt"), admin_headers),
        ApiErrorId.INVOICE_NOT_ISSUED,
        409,
    )

    still_void = validate_success(api.get_invoice(first["id"], officer_headers))
    assert_invoice(
        still_void,
        status=InvoiceStatus.VOID,
        void_reason=OPERATOR_VOID_REASON,
        total_cents=53,
    )
    producer = validate_success(api.get_producer(chain["producer"]["id"], officer_headers))
    assert_cents(producer["assessed_fee_balance_cents"], 53, "assessed_fee_balance_cents")


# ---------------------------------------------------------------------------
# Conserved quantity two: mass in kilograms on the registration's running total
# ---------------------------------------------------------------------------
def _report_under_verification(api):
    """A submitted 5.500 kg report with fieldwork already under way."""
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Mass Conservation Co",
            annual_gross_revenue_usd=8000000,
            contact_email="pn@x.com",
        ),
        sku_overrides=dict(name="Mass Jar", product_category="HOUSEHOLD_CHEM"),
    )
    engagement = fx.assign_engagement(
        api, chain["report"], VERIFIER_USER_ID, "2026-09-10", "2026-09-12"
    )
    started = fx.start_engagement(api, engagement, VERIFIER_HEADERS)
    assert_engagement(started, status=EngagementStatus.IN_PROGRESS, round_index=1)

    assert_report(
        validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"])),
        submission_status=SubmissionStatus.UNDER_VERIFICATION,
        total_weight_kg=5.500,
    )
    assert_weight(
        validate_success(
            api.get_registration(chain["registration"]["id"], chain["officer_headers"])
        )["reported_weight_kg_ytd"],
        5.500,
        "reported_weight_kg_ytd",
    )
    chain["engagement"] = started
    return chain


def _assert_mass_is_still_declared_once(api, chain):
    """The single line and its report always agree on the 5.500 kg of glass."""
    line = validate_success(api.get_report_line(chain["line"]["id"], chain["officer_headers"]))
    assert_report_line(line, line_weight_kg=5.500)
    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_weight(report["total_weight_kg"], 5.500, "total_weight_kg")
    return report


def test_a_qualified_opinion_drops_the_running_total_and_resubmission_restores_it(api):
    """The report leaves the counted set on the opinion and re-enters on resubmission.

    A qualified opinion pushes the report into correction, so the running total falls
    to nothing and the membership goes on probation; resubmitting inside the
    thirty-day window puts the identical 5.500 kg back and lifts the probation.

    Design: Difficulty/compensating_invariant/correction_cycle_restores_reported_weight_ytd
    """
    chain = _report_under_verification(api)
    officer_headers = chain["officer_headers"]

    fx.issue_opinion(
        api,
        chain["engagement"],
        VERIFIER_HEADERS,
        Opinion.QUALIFIED,
        "Two glass stock keeping units undocumented",
    )

    corrected = _assert_mass_is_still_declared_once(api, chain)
    assert_report(corrected, submission_status=SubmissionStatus.CORRECTION_REQUIRED)
    assert_instant_equals(
        corrected["correction_due_at"], "2026-10-01T00:00:00Z", "correction_due_at"
    )
    assert_weight(
        validate_success(api.get_registration(chain["registration"]["id"], officer_headers))[
            "reported_weight_kg_ytd"
        ],
        0.000,
        "reported_weight_kg_ytd",
    )
    assert (
        validate_success(api.get_membership(chain["membership"]["id"], officer_headers))["status"]
        == MembershipStatus.PROBATION
    )

    resubmitted = validate_success(
        api.resubmit_report(chain["report"]["id"], None, officer_headers)
    )

    assert_report(
        resubmitted,
        submission_status=SubmissionStatus.SUBMITTED,
        correction_round=1,
        correction_due_at=None,
        fee_status=ReportFeeStatus.UNASSESSED,
    )
    _assert_mass_is_still_declared_once(api, chain)
    assert_weight(
        validate_success(api.get_registration(chain["registration"]["id"], officer_headers))[
            "reported_weight_kg_ytd"
        ],
        5.500,
        "reported_weight_kg_ytd",
    )
    assert (
        validate_success(api.get_membership(chain["membership"]["id"], officer_headers))["status"]
        == MembershipStatus.ACTIVE
    )


def test_a_second_correction_cycle_lands_on_the_same_figure_again(api):
    """Two full cycles over unchanged lines leave no residue in the running total.

    The second round is examined by a different verifier, whose engagement records
    round two, and an adverse opinion empties the running total once more; the
    second resubmission restores exactly 5.500 kg for the second time.

    Design: Difficulty/compensating_invariant/correction_cycle_restores_reported_weight_ytd
    """
    chain = _report_under_verification(api)
    officer_headers = chain["officer_headers"]
    fx.issue_opinion(
        api,
        chain["engagement"],
        VERIFIER_HEADERS,
        Opinion.QUALIFIED,
        "Two glass stock keeping units undocumented",
    )
    validate_success(api.resubmit_report(chain["report"]["id"], None, officer_headers))

    second = fx.assign_engagement(
        api,
        chain["report"],
        VERIFIER_USER_ID_ALT,
        "2026-09-20",
        "2026-09-22",
        regulator_headers=REGULATOR_HEADERS,
    )
    assert_engagement(second, round_index=2, verifier_user_id=VERIFIER_USER_ID_ALT)
    fx.start_engagement(api, second, VERIFIER_ALT_HEADERS)
    fx.issue_opinion(api, second, VERIFIER_ALT_HEADERS, Opinion.ADVERSE, "Still understated")

    _assert_mass_is_still_declared_once(api, chain)
    assert_weight(
        validate_success(api.get_registration(chain["registration"]["id"], officer_headers))[
            "reported_weight_kg_ytd"
        ],
        0.000,
        "reported_weight_kg_ytd",
    )

    resubmitted = validate_success(
        api.resubmit_report(chain["report"]["id"], None, officer_headers)
    )

    assert_report(
        resubmitted,
        submission_status=SubmissionStatus.SUBMITTED,
        correction_round=2,
        correction_due_at=None,
    )
    _assert_mass_is_still_declared_once(api, chain)
    assert_weight(
        validate_success(api.get_registration(chain["registration"]["id"], officer_headers))[
            "reported_weight_kg_ytd"
        ],
        5.500,
        "reported_weight_kg_ytd",
    )
