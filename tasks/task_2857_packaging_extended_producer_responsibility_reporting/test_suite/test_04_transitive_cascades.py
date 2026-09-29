"""Transitive cascades: one call whose effects are only reachable hop by hop.

An adverse verification opinion propagates six hops across five entities, and a
revenue restatement fans out from the producer down to its registrations and
their draft reports. Each test walks the hops in the order the PRD pins.
"""

from test_helpers import (
    ApiErrorId,
    CompliancePosture,
    ExemptionStatus,
    FeeVariant,
    InvoiceStatus,
    MembershipStatus,
    Opinion,
    ProducerStatus,
    REGULATOR_HEADERS,
    RegistrationStatus,
    ReportFeeStatus,
    SubmissionStatus,
    VERIFIER_HEADERS,
    VERIFIER_USER_ID,
    VoidReason,
    assert_instant_equals,
    assert_invoice,
    assert_membership,
    assert_producer,
    assert_registration,
    assert_report,
    assert_weight,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)


def _report_under_verification_with_an_issued_invoice(api):
    """A billed 5.500 kg report whose first engagement is already in progress."""
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Cascade Glass Co",
            annual_gross_revenue_usd=8000000,
            contact_email="p7@x.com",
        ),
    )
    validate_success(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), chain["admin_headers"]
        )
    )
    invoice = validate_success(
        api.create_invoice(
            f.invoice_payload(chain["report"]["id"], chain["membership"]["id"]),
            chain["admin_headers"],
        ),
        201,
    )
    assert_invoice(invoice, total_cents=53, status=InvoiceStatus.ISSUED)
    engagement = fx.assign_engagement(
        api,
        chain["report"],
        VERIFIER_USER_ID,
        fieldwork_start="2026-09-10",
        fieldwork_end="2026-09-12",
    )
    fx.start_engagement(api, engagement, VERIFIER_HEADERS)

    registration = validate_success(
        api.get_registration(chain["registration"]["id"], chain["officer_headers"])
    )
    assert_weight(registration["reported_weight_kg_ytd"], 5.500, "reported_weight_kg_ytd")
    producer = validate_success(
        api.get_producer(chain["producer"]["id"], chain["officer_headers"])
    )
    assert_producer(producer, assessed_fee_balance_cents=53)
    membership = validate_success(
        api.get_membership(chain["membership"]["id"], chain["officer_headers"])
    )
    assert_membership(membership, status=MembershipStatus.ACTIVE)

    chain["invoice"] = invoice
    chain["engagement"] = engagement
    return chain


def test_adverse_opinion_opens_the_correction_window_and_voids_the_money(api):
    """Hops one to three: the report corrects, the tonnage leaves, the invoice voids.

    The correction window is the opinion instant plus the period's thirty days;
    the registration's year-to-date tonnage falls back to zero because the report
    has left the counted set; and the fee dimension is voided along with the
    issued invoice, whose total is preserved rather than rewritten.

    Design: Difficulty/transitive_cascade/adverse_opinion_six_hop_cascade
    """
    chain = _report_under_verification_with_an_issued_invoice(api)

    fx.issue_opinion(
        api,
        chain["engagement"],
        VERIFIER_HEADERS,
        Opinion.ADVERSE,
        findings_note="Glass tonnage understated by 40 percent",
    )

    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(
        report,
        submission_status=SubmissionStatus.CORRECTION_REQUIRED,
        fee_status=ReportFeeStatus.VOIDED,
    )
    assert_instant_equals(
        report["correction_due_at"], "2026-10-01T00:00:00Z", "correction_due_at"
    )

    registration = validate_success(
        api.get_registration(chain["registration"]["id"], chain["officer_headers"])
    )
    assert_weight(registration["reported_weight_kg_ytd"], 0.000, "reported_weight_kg_ytd")

    invoice = validate_success(
        api.get_invoice(chain["invoice"]["id"], chain["admin_headers"])
    )
    assert_invoice(
        invoice,
        status=InvoiceStatus.VOID,
        void_reason=VoidReason.REPORT_CORRECTION_REQUIRED,
        total_cents=53,
    )


def test_adverse_opinion_reaches_the_balance_the_posture_and_the_membership(api):
    """Hops four to six, each reachable only through the hop before it.

    The voided invoice leaves the producer's balance set, the correction puts the
    registration at risk, and the at-risk posture is what moves the active
    membership into probation.

    Design: Difficulty/transitive_cascade/adverse_opinion_six_hop_cascade
    """
    chain = _report_under_verification_with_an_issued_invoice(api)

    fx.issue_opinion(
        api,
        chain["engagement"],
        VERIFIER_HEADERS,
        Opinion.ADVERSE,
        findings_note="Glass tonnage understated by 40 percent",
    )

    producer = validate_success(
        api.get_producer(chain["producer"]["id"], chain["officer_headers"])
    )
    assert_producer(producer, assessed_fee_balance_cents=0)

    registration = validate_success(
        api.get_registration(chain["registration"]["id"], chain["officer_headers"])
    )
    assert_registration(
        registration,
        status=RegistrationStatus.ACTIVE,
        compliance_posture=CompliancePosture.AT_RISK,
    )

    membership = validate_success(
        api.get_membership(chain["membership"]["id"], chain["officer_headers"])
    )
    assert_membership(membership, status=MembershipStatus.PROBATION)


def _producer_registered_in_two_states(api):
    """One producer with an ACTIVE CA registration plus a SUBMITTED OR registration."""
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    ca_program = fx.make_deep_ca_program(api)
    or_program = fx.make_deep_or_program(api)
    period_kwargs = dict(
        data_start="2026-07-01",
        data_end="2027-01-01",
        submission_open="2026-08-15T00:00:00Z",
        submission_deadline="2026-09-30T23:59:59Z",
        correction_window_days=30,
    )
    ca_period = fx.make_reporting_period(
        api, ca_program["id"], period_label="CA-2026-H2", **period_kwargs
    )
    fx.make_reporting_period(
        api, or_program["id"], period_label="OR-2026-H2", **period_kwargs
    )
    built = fx.determined_producer(
        api,
        components=[f.component_payload(material_type="GLASS", unit_weight_grams=50)],
        sku_kwargs=dict(
            name="Restate Jar", product_category="HOUSEHOLD_CHEM",
            units_sold_annual_estimate=110,
        ),
        legal_name="Restatement Brands Co",
        annual_gross_revenue_usd=12000000,
        brand_owner_flag=True,
        contact_email="p9@x.com",
    )
    producer = built["producer"]
    ca_registration = fx.active_registration(api, producer, ca_program["id"])
    ca_report = fx.make_report(api, producer, ca_registration, ca_period)
    or_registration = fx.make_registration(api, producer, or_program["id"])
    or_registration = fx.submit_registration(api, producer, or_registration)
    assert_registration(or_registration, status=RegistrationStatus.SUBMITTED)
    return {
        "producer": producer,
        "ca_registration": ca_registration,
        "or_registration": or_registration,
        "ca_report": ca_report,
        "officer_headers": fx.officer(producer),
    }


def test_restating_revenue_suspends_every_live_registration_of_the_producer(api):
    """The root moves back to DRAFT and hop one suspends both registrations.

    The corrected revenue is stored, the obligated-party role is cleared and the
    staleness flag is false again, while the active and the submitted registration
    both reach SUSPENDED with the system reason and an undetermined exemption.

    Design: Difficulty/transitive_cascade/restate_revenue_three_hop_cascade
    """
    built = _producer_registered_in_two_states(api)

    restated = validate_success(
        api.restate_revenue(
            built["producer"]["id"],
            f.restate_revenue_payload(
                4000000, reason="Audited restatement excludes a divested brand"
            ),
            REGULATOR_HEADERS,
        )
    )

    assert_producer(
        restated,
        status=ProducerStatus.DRAFT,
        annual_gross_revenue_usd=4000000,
        obligated_party_role="UNDETERMINED",
        determination_stale=False,
    )
    assert_weight(restated["annual_packaging_weight_kg"], 5.500, "annual_packaging_weight_kg")

    for key in ("ca_registration", "or_registration"):
        registration = validate_success(
            api.get_registration(built[key]["id"], built["officer_headers"])
        )
        assert_registration(
            registration,
            status=RegistrationStatus.SUSPENDED,
            suspension_reason="PRODUCER_REDETERMINATION_REQUIRED",
            exemption_status=ExemptionStatus.UNDETERMINED,
        )


def test_the_restatement_cascade_blocks_the_draft_report_and_marks_both_delinquent(api):
    """Hops two and three, plus the state guard the suspension now imposes.

    The draft report of the suspended registration is blocked, both registrations
    recompute to DELINQUENT, and a submission aimed at the suspended registration
    is refused for its state rather than for the producer's determination.

    Design: Difficulty/transitive_cascade/restate_revenue_three_hop_cascade
    """
    built = _producer_registered_in_two_states(api)

    validate_success(
        api.restate_revenue(
            built["producer"]["id"],
            f.restate_revenue_payload(
                4000000, reason="Audited restatement excludes a divested brand"
            ),
            REGULATOR_HEADERS,
        )
    )

    report = validate_success(
        api.get_report(built["ca_report"]["id"], built["officer_headers"])
    )
    assert_report(report, submission_status=SubmissionStatus.BLOCKED)

    for key in ("ca_registration", "or_registration"):
        registration = validate_success(
            api.get_registration(built[key]["id"], built["officer_headers"])
        )
        assert_registration(registration, compliance_posture=CompliancePosture.DELINQUENT)

    validate_error(
        api.submit_registration(
            built["ca_registration"]["id"], None, built["officer_headers"]
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
