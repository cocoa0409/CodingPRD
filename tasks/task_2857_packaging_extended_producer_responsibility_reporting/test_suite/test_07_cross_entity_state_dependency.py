"""Cross-entity state dependency: one row's status decides another row's fate.

Each pair below is exercised twice — once while the depended-upon row is in the
blocking state and once after it has moved — so the only thing that changes
between the refusal and the success is the other entity's status.
"""

from test_helpers import (
    ApiErrorId,
    CompliancePosture,
    EngagementStatus,
    ExemptionStatus,
    FeePaymentStatus,
    FeeScheduleStatus,
    FeeVariant,
    MembershipStatus,
    Opinion,
    REGULATOR_HEADERS,
    RegistrationStatus,
    ReportFeeStatus,
    SubmissionStatus,
    VERIFIER_HEADERS,
    VERIFIER_USER_ID,
    assert_cents,
    assert_exact_cents,
    assert_fee_schedule,
    assert_membership,
    assert_registration,
    assert_report,
    assert_report_line,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# A report may only be opened against an ACTIVE registration
# ---------------------------------------------------------------------------
def _suspended_registration(api):
    """An accepted CA registration that has since been suspended for an audit."""
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Cross F Co",
            annual_gross_revenue_usd=8000000,
            contact_email="pf@x.com",
        ),
        sku_overrides=dict(name="Cross Jar", product_category="HOUSEHOLD_CHEM"),
        with_membership=False,
        with_report=False,
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
        exemption_status=ExemptionStatus.OBLIGATED,
    )
    chain["registration"] = suspended
    return chain


def test_a_suspended_registration_cannot_open_a_report(api):
    """The create is refused on the parent registration's status alone.

    The registration is suspended and therefore delinquent, and the refusal names
    the inactive registration rather than any exemption, because the exemption
    verdict is obligated throughout; no report row is left behind.

    Design: Difficulty/cross_entity_state_dependency/report_create_blocked_by_suspended_registration
    """
    chain = _suspended_registration(api)

    error = validate_error(
        api.create_report(
            f.report_payload(chain["registration"]["id"], chain["period"]["id"]),
            chain["officer_headers"],
        ),
        ApiErrorId.REGISTRATION_NOT_ACTIVE,
        409,
    )
    assert error["error_id"] != ApiErrorId.EXEMPT_REGISTRATION_CANNOT_REPORT.value

    registration = validate_success(
        api.get_registration(chain["registration"]["id"], chain["officer_headers"])
    )
    assert_registration(
        registration,
        status=RegistrationStatus.SUSPENDED,
        compliance_posture=CompliancePosture.DELINQUENT,
        exemption_status=ExemptionStatus.OBLIGATED,
    )
    reports, meta = validate_paginated(
        api.list_reports(
            chain["officer_headers"], {"registration_id": chain["registration"]["id"]}
        )
    )
    assert reports == [] and meta["total_count"] == 0


def test_reinstating_the_registration_lets_the_identical_create_through(api):
    """The same request body succeeds once the registration is active again.

    Reinstatement clears the suspension reason and returns the posture to
    compliant, after which the report is created with the declared defaults.

    Design: Difficulty/cross_entity_state_dependency/report_create_blocked_by_suspended_registration
    """
    chain = _suspended_registration(api)
    body = f.report_payload(chain["registration"]["id"], chain["period"]["id"])
    validate_error(
        api.create_report(body, chain["officer_headers"]),
        ApiErrorId.REGISTRATION_NOT_ACTIVE,
        409,
    )

    reinstated = validate_success(
        api.reinstate_registration(chain["registration"]["id"], None, REGULATOR_HEADERS)
    )
    assert_registration(
        reinstated,
        status=RegistrationStatus.ACTIVE,
        suspension_reason=None,
        compliance_posture=CompliancePosture.COMPLIANT,
    )

    report = validate_success(api.create_report(body, chain["officer_headers"]), 201)
    assert_report(
        report,
        submission_status=SubmissionStatus.DRAFT,
        fee_status=ReportFeeStatus.UNASSESSED,
        total_weight_kg=0.000,
        correction_round=0,
    )


# ---------------------------------------------------------------------------
# A membership may only elect a PUBLISHED fee schedule
# ---------------------------------------------------------------------------
def _registration_facing_a_draft_schedule(api):
    """An ACTIVE registration and a GLASS-only schedule still sitting in DRAFT."""
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    program = fx.make_deep_ca_program(api)
    pro = fx.make_pro(api, name="PRO West", contact_email="pro@x.com")
    built = fx.determined_producer(
        api,
        components=[f.component_payload(material_type="GLASS", unit_weight_grams=50)],
        sku_kwargs=dict(name="Cross Jar G", product_category="HOUSEHOLD_CHEM"),
        legal_name="Cross G Co",
        annual_gross_revenue_usd=8000000,
        contact_email="pg@x.com",
    )
    producer = built["producer"]
    schedule = fx.make_fee_schedule(
        api, pro, program["id"], effective_from="2026-07-01", admin_fee_bps_high=300
    )
    assert_fee_schedule(schedule, status=FeeScheduleStatus.DRAFT)
    registration = fx.active_registration(api, producer, program["id"])
    return {
        "producer": producer,
        "pro": pro,
        "schedule": schedule,
        "registration": registration,
        "officer_headers": fx.officer(producer),
        "admin_headers": fx.admin(pro),
    }


def test_a_draft_fee_schedule_cannot_be_elected(api):
    """The application is refused while the elected schedule is unpublished.

    Nothing is written: no membership row exists for the registration and the
    registration's own version has not moved, which is what makes the same
    concurrency token usable again afterwards.

    Design: Difficulty/cross_entity_state_dependency/membership_create_blocked_by_draft_fee_schedule
    """
    built = _registration_facing_a_draft_schedule(api)
    registration = built["registration"]

    validate_error(
        api.create_membership(
            f.membership_payload(
                registration["id"],
                built["pro"]["id"],
                built["schedule"]["id"],
                registration["version"],
            ),
            built["officer_headers"],
        ),
        ApiErrorId.FEE_SCHEDULE_NOT_PUBLISHED,
        409,
    )

    memberships, meta = validate_paginated(
        api.list_memberships(built["officer_headers"], {"registration_id": registration["id"]})
    )
    assert memberships == [] and meta["total_count"] == 0
    reread = validate_success(
        api.get_registration(registration["id"], built["officer_headers"])
    )
    assert reread["version"] == registration["version"]


def test_publishing_the_schedule_lets_the_same_application_through(api):
    """Once published, the identical body is accepted and the pin follows at approval.

    The application is created pending with nothing assessed and no pinned version,
    and it is the approval that both assesses the 250000 cent fee — the producer's
    5.500 kg carries no tonnage surcharge — and pins the schedule version.

    Design: Difficulty/cross_entity_state_dependency/membership_create_blocked_by_draft_fee_schedule
    """
    built = _registration_facing_a_draft_schedule(api)
    registration = built["registration"]
    body = f.membership_payload(
        registration["id"],
        built["pro"]["id"],
        built["schedule"]["id"],
        registration["version"],
    )
    validate_error(
        api.create_membership(body, built["officer_headers"]),
        ApiErrorId.FEE_SCHEDULE_NOT_PUBLISHED,
        409,
    )

    published = fx.publish_fee_schedule(api, built["pro"], built["schedule"])
    assert_fee_schedule(published, status=FeeScheduleStatus.PUBLISHED)

    membership = validate_success(api.create_membership(body, built["officer_headers"]), 201)
    assert_membership(
        membership,
        status=MembershipStatus.PENDING,
        membership_fee_cents=0,
        fee_payment_status=FeePaymentStatus.OUTSTANDING,
        fee_schedule_version_pinned=None,
        decision_reason=None,
    )

    approved = fx.approve_membership(api, built["pro"], membership)
    assert_membership(
        approved,
        status=MembershipStatus.ACTIVE,
        fee_payment_status=FeePaymentStatus.OUTSTANDING,
        fee_schedule_version_pinned=published["version"],
    )
    assert_cents(approved["membership_fee_cents"], 250000, "membership_fee_cents")


# ---------------------------------------------------------------------------
# A final assessment waits on an opinion that lives on the engagement
# ---------------------------------------------------------------------------
def _submitted_report_that_needs_an_opinion(api):
    """A 5.500 kg report in a program whose verification threshold is one kilogram."""
    chain = fx.deep_ca_chain(
        api,
        program_overrides=dict(verification_required_threshold_kg=1),
        producer_overrides=dict(
            legal_name="Cross H Co",
            annual_gross_revenue_usd=8000000,
            contact_email="ph@x.com",
        ),
        sku_overrides=dict(name="Cross Jar H", product_category="HOUSEHOLD_CHEM"),
    )
    assert_report(
        chain["report"],
        submission_status=SubmissionStatus.SUBMITTED,
        verification_required=True,
        total_weight_kg=5.500,
    )
    return chain


def test_a_final_assessment_is_refused_while_verification_is_outstanding(api):
    """The money dimension will not move without an opinion on the engagement.

    The report requires verification at this tonnage and no engagement has issued
    an opinion, so the final assessment is refused and the fee dimension is left
    unassessed at zero.

    Design: Difficulty/cross_entity_state_dependency/final_assessment_blocked_until_engagement_issues_unqualified
    """
    chain = _submitted_report_that_needs_an_opinion(api)

    validate_error(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), chain["admin_headers"]
        ),
        ApiErrorId.VERIFICATION_REQUIRED,
        409,
    )

    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(
        report,
        fee_status=ReportFeeStatus.UNASSESSED,
        fee_subtotal_cents=0,
        submission_status=SubmissionStatus.SUBMITTED,
    )


def test_an_unqualified_opinion_unlocks_the_final_assessment(api):
    """After the engagement issues its opinion the same assessment succeeds.

    The engagement reaches its terminal opinion state, the report becomes verified,
    and the final pricing then values the 5.500 kg line at 49.5000 exact cents,
    stored as 50 whole cents, without any provisional pass in between.

    Design: Difficulty/cross_entity_state_dependency/final_assessment_blocked_until_engagement_issues_unqualified
    """
    chain = _submitted_report_that_needs_an_opinion(api)
    validate_error(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), chain["admin_headers"]
        ),
        ApiErrorId.VERIFICATION_REQUIRED,
        409,
    )

    engagement = fx.assign_engagement(
        api, chain["report"], VERIFIER_USER_ID, "2026-09-10", "2026-09-12"
    )
    fx.start_engagement(api, engagement, VERIFIER_HEADERS)
    issued = fx.issue_opinion(api, engagement, VERIFIER_HEADERS, Opinion.UNQUALIFIED)
    assert issued["status"] == EngagementStatus.OPINION_ISSUED
    assert issued["opinion"] == Opinion.UNQUALIFIED

    verified = validate_success(
        api.get_report(chain["report"]["id"], chain["officer_headers"])
    )
    assert_report(verified, submission_status=SubmissionStatus.VERIFIED)

    assessed = validate_success(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), chain["admin_headers"]
        )
    )
    assert_report(
        assessed,
        fee_status=ReportFeeStatus.FINAL,
        fee_variant_applied=FeeVariant.FINAL,
        tier_basis_kg=5.500,
        fee_subtotal_cents=50,
    )
    line = validate_success(api.get_report_line(chain["line"]["id"], chain["officer_headers"]))
    assert_exact_cents(line["line_fee_exact_cents"], 49.5000, "line_fee_exact_cents")
    assert_report_line(line, line_fee_cents=50)
