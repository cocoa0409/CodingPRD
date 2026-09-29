"""State machines: initial states, backward edges, terminal lockdown and cascades.

Every transition here is driven through the public verbs, and every rejection is
checked to have moved nothing — neither the target row's own status nor the version
of any row the successful transition would have touched.
"""

from test_helpers import (
    ApiErrorId,
    CompliancePosture,
    EngagementStatus,
    ExemptionStatus,
    FeePaymentStatus,
    FeeScheduleStatus,
    MembershipStatus,
    ObligatedPartyRole,
    ObligationBasis,
    Opinion,
    ProducerStatus,
    REGULATOR_HEADERS,
    RegistrationStatus,
    ReportFeeStatus,
    SkuStatus,
    SubmissionStatus,
    VERIFIER_HEADERS,
    VERIFIER_USER_ID,
    assert_engagement,
    assert_fee_schedule,
    assert_instant_equals,
    assert_membership,
    assert_no_version_movement,
    assert_producer,
    assert_registration,
    assert_report,
    assert_sku,
    assert_weight,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"
CORRECTION_DUE_INSTANT = "2026-08-31T00:00:00Z"


# ---------------------------------------------------------------------------
# The producer machine and its single backward edge
# ---------------------------------------------------------------------------
def test_restating_revenue_takes_a_determined_producer_back_to_draft(api):
    """The only backward edge undoes the classification but not the tonnage.

    Restating the revenue writes the corrected figure, returns the producer to its
    initial state and clears the classification, yet the packaging rollup survives
    because material data did not change; a second determination re-earns the
    brand-owner verdict.

    Design: Corner/state_machines/producer_initial_state_and_determination_round_trip_on_restatement
    """
    built = fx.determined_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        contact_email="compliance@northlake.example",
    )
    producer = built["producer"]
    assert_producer(
        producer,
        status=ProducerStatus.OBLIGATION_DETERMINED,
        obligated_party_role=ObligatedPartyRole.BRAND_OWNER,
    )

    restated = validate_success(
        api.restate_revenue(
            producer["id"],
            f.restate_revenue_payload(900000, "Audited restatement of FY2025 revenue"),
            REGULATOR_HEADERS,
        )
    )

    assert_producer(
        restated,
        status=ProducerStatus.DRAFT,
        obligated_party_role=ObligatedPartyRole.UNDETERMINED,
        annual_gross_revenue_usd=900000,
    )
    assert_weight(restated["annual_packaging_weight_kg"], 5.500, "annual_packaging_weight_kg")

    redetermined = fx.determine_obligation(api, producer)
    assert_producer(
        redetermined,
        status=ProducerStatus.OBLIGATION_DETERMINED,
        obligated_party_role=ObligatedPartyRole.BRAND_OWNER,
        annual_gross_revenue_usd=900000,
    )


# ---------------------------------------------------------------------------
# Publication is a one-way transition, not an idempotent write
# ---------------------------------------------------------------------------
def test_publishing_the_same_fee_schedule_twice_is_refused(api):
    """The second publication is rejected even with a freshly read pinned version.

    The first publication advances the organisation's own version, so the client
    re-reads it before trying again; the request is still refused on the schedule's
    own status, and neither the schedule nor the organisation moves again.

    Design: Corner/state_machines/fee_schedule_second_publish_attempt_is_rejected
    """
    program = fx.make_breadth_program(api, state_code="CA")
    pro = fx.make_pro(api, name="Circular Stewardship Alliance", contact_email="ops@csa.example")
    schedule = fx.make_fee_schedule(api, pro, program["id"], effective_from="2026-01-01")

    assert fx.read_pro_version(api, pro) == 1
    published = fx.publish_fee_schedule(api, pro, schedule)
    assert_fee_schedule(published, status=FeeScheduleStatus.PUBLISHED, version=2)
    pro_after_publish = validate_success(api.get_pro(pro["id"], fx.admin(pro)))
    assert pro_after_publish["version"] == 2

    validate_error(
        api.publish_fee_schedule(schedule["id"], f.publish_payload(2), fx.admin(pro)),
        ApiErrorId.INVALID_STATE,
        409,
    )

    unmoved_schedule = validate_success(api.get_fee_schedule(schedule["id"], fx.admin(pro)))
    assert_fee_schedule(unmoved_schedule, status=FeeScheduleStatus.PUBLISHED, version=2)
    assert_no_version_movement(published, unmoved_schedule, "FeeSchedule")
    unmoved_pro = validate_success(api.get_pro(pro["id"], fx.admin(pro)))
    assert_no_version_movement(pro_after_publish, unmoved_pro, "Pro")


# ---------------------------------------------------------------------------
# A rejected registration is terminal for all three remaining verbs
# ---------------------------------------------------------------------------
def test_a_rejected_registration_refuses_every_later_verb(api):
    """Decide, suspend and withdraw are all refused once the rejection is recorded.

    The row keeps the exemption verdict written at submission, an undetermined
    posture and no suspension reason, and its version stays at the three writes it
    genuinely received.

    Design: Corner/state_machines/registration_rejected_is_terminal_and_locks_every_later_action
    """
    program = fx.make_breadth_program(api, state_code="CA")
    built = fx.determined_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        contact_email="compliance@northlake.example",
    )
    producer = built["producer"]
    headers = fx.officer(producer)
    registration = fx.submit_registration(api, producer, fx.make_registration(api, producer, program["id"]))
    rejected = validate_success(
        api.decide_registration(
            registration["id"],
            f.decision_payload("REJECT", "Brand ownership evidence incomplete"),
            REGULATOR_HEADERS,
        )
    )
    assert_registration(rejected, status=RegistrationStatus.REJECTED, version=3)

    validate_error(
        api.decide_registration(
            registration["id"], f.decision_payload("ACCEPT"), REGULATOR_HEADERS
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.suspend_registration(
            registration["id"],
            f.suspend_payload("Attempt to suspend a rejected registration"),
            REGULATOR_HEADERS,
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.withdraw_registration(
            registration["id"],
            f.withdraw_payload("Attempt to withdraw a rejected registration"),
            headers,
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )

    final = validate_success(api.get_registration(registration["id"], headers))
    assert_registration(
        final,
        status=RegistrationStatus.REJECTED,
        version=3,
        exemption_status=ExemptionStatus.OBLIGATED,
        exemption_basis_applied=ObligationBasis.ENTITY_LEVEL,
        compliance_posture=CompliancePosture.UNDETERMINED,
        suspension_reason=None,
    )


# ---------------------------------------------------------------------------
# Verbs absent from a from-state move nothing at all
# ---------------------------------------------------------------------------
def test_verbs_outside_the_from_state_are_refused_and_move_nothing(api):
    """A draft registration refuses three verbs and an active unit refuses a fourth.

    Reinstatement, suspension and the accept decision all belong to later states, and
    a second activation belongs to no state at all; every version stays put, and in
    particular the producer's tonnage is not double-counted.

    Design: Corner/state_machines/actions_from_states_outside_the_transition_list_return_invalid_state
    """
    program = fx.make_breadth_program(api, state_code="CA")
    built = fx.determined_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        contact_email="compliance@northlake.example",
    )
    producer, sku = built["producer"], built["sku"]
    headers = fx.officer(producer)
    registration = fx.make_registration(api, producer, program["id"])

    validate_error(
        api.reinstate_registration(registration["id"], None, REGULATOR_HEADERS),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.suspend_registration(
            registration["id"], f.suspend_payload("Cannot suspend a draft"), REGULATOR_HEADERS
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.decide_registration(
            registration["id"], f.decision_payload("ACCEPT"), REGULATOR_HEADERS
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.activate_sku(sku["id"], None, headers), ApiErrorId.INVALID_STATE, 409
    )

    unmoved_registration = validate_success(api.get_registration(registration["id"], headers))
    assert_registration(
        unmoved_registration,
        status=RegistrationStatus.DRAFT,
        version=1,
        submitted_at=None,
    )
    unmoved_sku = validate_success(api.get_sku(sku["id"], headers))
    assert_sku(unmoved_sku, status=SkuStatus.ACTIVE, version=3, revision_count=0)
    unmoved_producer = validate_success(api.get_producer(producer["id"], headers))
    assert_producer(unmoved_producer, version=3)
    assert_weight(
        unmoved_producer["annual_packaging_weight_kg"], 5.500, "annual_packaging_weight_kg"
    )


# ---------------------------------------------------------------------------
# Suspension cascades into draft reports only
# ---------------------------------------------------------------------------
def _registration_with_one_filed_and_one_open_report(api):
    """A submitted first-half report and a still-draft second-half report."""
    chain = fx.base_ca_chain(api)
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
    chain["second_report"] = fx.make_report(
        api, chain["producer"], chain["registration"], second_period
    )
    return chain


def test_suspension_blocks_only_the_draft_report_and_reinstatement_frees_it(api):
    """The cascade takes in draft reports alone and the tonnage is untouched.

    Suspension blocks the open report but leaves the filed one in place, so the
    running tonnage stays whole while the posture turns delinquent; the membership
    stays active, because delinquency is not what puts a membership on probation.
    Reinstatement clears the reason, frees the blocked report and restores compliance.

    Design: Corner/state_machines/suspension_blocks_only_draft_reports_and_reinstatement_restores_them
    """
    chain = _registration_with_one_filed_and_one_open_report(api)
    headers, admin_headers = chain["officer_headers"], chain["admin_headers"]
    filed, open_report = chain["report"], chain["second_report"]

    suspended = validate_success(
        api.suspend_registration(
            chain["registration"]["id"],
            f.suspend_payload("Missing brand-ownership attestation for 2026"),
            REGULATOR_HEADERS,
        )
    )

    assert_registration(
        suspended,
        status=RegistrationStatus.SUSPENDED,
        suspension_reason="Missing brand-ownership attestation for 2026",
        compliance_posture=CompliancePosture.DELINQUENT,
    )
    assert_weight(suspended["reported_weight_kg_ytd"], 5.500, "reported_weight_kg_ytd")
    assert_report(
        validate_success(api.get_report(open_report["id"], headers)),
        submission_status=SubmissionStatus.BLOCKED,
    )
    assert_report(
        validate_success(api.get_report(filed["id"], headers)),
        submission_status=SubmissionStatus.SUBMITTED,
    )
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], admin_headers)),
        status=MembershipStatus.ACTIVE,
        fee_payment_status=FeePaymentStatus.PAID,
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
    assert_weight(reinstated["reported_weight_kg_ytd"], 5.500, "reported_weight_kg_ytd")
    freed = validate_success(api.get_report(open_report["id"], headers))
    assert_report(freed, submission_status=SubmissionStatus.DRAFT, line_count=0)
    assert_weight(freed["total_weight_kg"], 0.000, "total_weight_kg")
    assert_report(
        validate_success(api.get_report(filed["id"], headers)),
        submission_status=SubmissionStatus.SUBMITTED,
    )
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], admin_headers)),
        status=MembershipStatus.ACTIVE,
    )


# ---------------------------------------------------------------------------
# A qualified opinion moves three dimensions at once, and only one verb undoes it
# ---------------------------------------------------------------------------
def _fieldwork_in_progress(api):
    """The standard chain with fieldwork under way on its single submitted report."""
    chain = fx.base_ca_chain(api)
    engagement = fx.assign_engagement(api, chain["report"], VERIFIER_USER_ID)
    chain["engagement"] = fx.start_engagement(api, engagement, VERIFIER_HEADERS)
    return chain


def test_a_qualified_opinion_puts_the_membership_on_probation(api):
    """One opinion opens the correction window and demotes the membership.

    The report was never priced, so its fee dimension simply stays unassessed while
    the submission dimension moves into correction with a window thirty days past the
    opinion instant; the running tonnage empties, the posture becomes at-risk, and
    the active membership drops to probation.

    Design: Corner/state_machines/qualified_opinion_puts_the_membership_on_probation_and_resubmission_restores_it
    """
    chain = _fieldwork_in_progress(api)
    headers, admin_headers = chain["officer_headers"], chain["admin_headers"]

    opined = fx.issue_opinion(
        api,
        chain["engagement"],
        VERIFIER_HEADERS,
        Opinion.QUALIFIED,
        "Glass tonnage understated against warehouse records",
    )

    assert_engagement(
        opined,
        status=EngagementStatus.OPINION_ISSUED,
        opinion=Opinion.QUALIFIED,
        round_index=1,
    )
    assert_instant_equals(
        opined["opinion_issued_at"], DEFAULT_CLOCK_INSTANT, "opinion_issued_at"
    )

    report = validate_success(api.get_report(chain["report"]["id"], headers))
    assert_report(
        report,
        submission_status=SubmissionStatus.CORRECTION_REQUIRED,
        fee_status=ReportFeeStatus.UNASSESSED,
    )
    assert_instant_equals(
        report["correction_due_at"], CORRECTION_DUE_INSTANT, "correction_due_at"
    )
    registration = validate_success(api.get_registration(chain["registration"]["id"], headers))
    assert_registration(registration, compliance_posture=CompliancePosture.AT_RISK)
    assert_weight(registration["reported_weight_kg_ytd"], 0.000, "reported_weight_kg_ytd")
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], admin_headers)),
        status=MembershipStatus.PROBATION,
        fee_payment_status=FeePaymentStatus.PAID,
    )


def test_resubmission_clears_the_window_and_lifts_the_probation(api):
    """Refiling inside the window restores every field the opinion had moved.

    The report returns to submitted with its correction round advanced and its due
    instant cleared, the tonnage comes back whole, the posture is compliant again and
    the membership is restored to active; the engagement itself is terminal and keeps
    its issued opinion.

    Design: Corner/state_machines/qualified_opinion_puts_the_membership_on_probation_and_resubmission_restores_it
    """
    chain = _fieldwork_in_progress(api)
    headers, admin_headers = chain["officer_headers"], chain["admin_headers"]
    fx.issue_opinion(
        api,
        chain["engagement"],
        VERIFIER_HEADERS,
        Opinion.QUALIFIED,
        "Glass tonnage understated against warehouse records",
    )

    resubmitted = validate_success(
        api.resubmit_report(chain["report"]["id"], None, headers)
    )

    assert_report(
        resubmitted,
        submission_status=SubmissionStatus.SUBMITTED,
        correction_round=1,
        correction_due_at=None,
        total_weight_kg=5.500,
    )
    registration = validate_success(api.get_registration(chain["registration"]["id"], headers))
    assert_registration(registration, compliance_posture=CompliancePosture.COMPLIANT)
    assert_weight(registration["reported_weight_kg_ytd"], 5.500, "reported_weight_kg_ytd")
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], admin_headers)),
        status=MembershipStatus.ACTIVE,
    )
    assert_engagement(
        validate_success(api.get_engagement(chain["engagement"]["id"], headers)),
        status=EngagementStatus.OPINION_ISSUED,
        opinion=Opinion.QUALIFIED,
    )


def test_an_engagement_that_has_opined_accepts_no_further_action(api):
    """Neither a start nor a second opinion is admitted once the opinion exists.

    The terminal engagement position is what refuses both verbs, so the answer is the
    invalid-state code rather than the report-position code, and the engagement is
    left byte-for-byte as it was with the correction window still open.

    Design: Corner/state_machines/engagement_start_and_second_opinion_after_opinion_issued_rejected
    """
    chain = _fieldwork_in_progress(api)
    headers = chain["officer_headers"]
    opined = fx.issue_opinion(
        api,
        chain["engagement"],
        VERIFIER_HEADERS,
        Opinion.QUALIFIED,
        "Glass tonnage understated against warehouse records",
    )

    validate_error(
        api.start_engagement(opined["id"], None, VERIFIER_HEADERS),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.issue_opinion(
            opined["id"],
            f.opinion_payload(Opinion.ADVERSE, "Second look"),
            VERIFIER_HEADERS,
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )

    unmoved = validate_success(api.get_engagement(opined["id"], headers))
    assert_no_version_movement(opined, unmoved, "engagement")
    assert_engagement(
        unmoved, status=EngagementStatus.OPINION_ISSUED, opinion=Opinion.QUALIFIED
    )
    report = validate_success(api.get_report(chain["report"]["id"], headers))
    assert_report(report, submission_status=SubmissionStatus.CORRECTION_REQUIRED)
    assert_instant_equals(
        report["correction_due_at"], CORRECTION_DUE_INSTANT, "correction_due_at"
    )
    assert_registration(
        validate_success(api.get_registration(chain["registration"]["id"], headers)),
        compliance_posture=CompliancePosture.AT_RISK,
    )
