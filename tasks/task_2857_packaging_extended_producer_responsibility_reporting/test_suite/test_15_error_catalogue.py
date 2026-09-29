"""The refusal catalogue: each guard answers with its own declared code.

Every test here drives one family of refusals to the exact code and status the
error table declares, and then reads the resources back to show that a refused
request wrote nothing at all.
"""

from test_helpers import (
    ApiErrorId,
    CompliancePosture,
    DecisionReason,
    EngagementStatus,
    ExemptionStatus,
    FeePaymentStatus,
    FeeScheduleStatus,
    FeeVariant,
    InvoiceStatus,
    MembershipStatus,
    NON_EXISTENT_UUID,
    ObligatedPartyRole,
    ObligationBasis,
    Opinion,
    ProducerStatus,
    REGULATOR_HEADERS,
    RegistrationStatus,
    ReportFeeStatus,
    SkuStatus,
    SubmissionStatus,
    VERIFIER_ALT_HEADERS,
    VERIFIER_HEADERS,
    VERIFIER_USER_ID,
    VERIFIER_USER_ID_ALT,
    assert_cents,
    assert_engagement,
    assert_fee_schedule,
    assert_instant_equals,
    assert_invoice,
    assert_membership,
    assert_producer,
    assert_registration,
    assert_report,
    assert_report_line,
    assert_sku,
    assert_state_program,
    assert_weight,
    factories as f,
    fixtures as fx,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_HALF_PERIOD = dict(
    period_label="CA-2026-H2",
    data_start="2027-01-01",
    data_end="2027-07-01",
    submission_open="2026-07-15T00:00:00Z",
    submission_deadline="2027-06-30T23:59:59Z",
    correction_window_days=30,
)


# ---------------------------------------------------------------------------
# Authentication is resolved before anything else about the request
# ---------------------------------------------------------------------------
def test_a_missing_or_undeclared_role_header_is_unauthenticated(api):
    """Three malformed identities are all refused before the path is inspected.

    An undeclared role name, a request with no role at all and a request with no
    principal at all each answer 401; a read of an identifier that exists nowhere
    answers the same way rather than a not-found, because nothing about the
    request is examined until the caller is authenticated. The program created
    first is still readable at version 1.

    Design: Corner/errors/requests_with_a_missing_or_undeclared_role_header_are_unauthenticated
    """
    program = fx.make_breadth_program(api)

    for headers in (
        headers_with_unknown_role(),
        headers_without_role(),
        headers_without_user_id(),
    ):
        validate_error(
            api.get_state_program(program["id"], headers),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )

    error = validate_error(
        api.get_producer(NON_EXISTENT_UUID, headers_with_unknown_role()),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    assert error["error_id"] != ApiErrorId.PRODUCER_NOT_FOUND.value

    unchanged = validate_success(api.get_state_program(program["id"], REGULATOR_HEADERS))
    assert_state_program(unchanged, state_code="CA", version=1)


# ---------------------------------------------------------------------------
# The obligation prerequisites, in the order the producer meets them
# ---------------------------------------------------------------------------
def test_activation_determination_and_submission_demand_their_prerequisites(api):
    """A contract packer walks the three prerequisites and still cannot register.

    A unit with no components cannot be activated and a producer with no active
    unit cannot be determined, so a registration cannot even be opened; once a
    paper component is appended the unit activates and the determination lands at
    1.200 kg, but the classification ladder finds no qualifying flag and the
    submission is refused because the party is not obligated at all.

    Design: Corner/errors/obligation_prerequisites_gate_activate_determine_and_registration_submit
    """
    program = fx.make_breadth_program(api)
    producer = fx.make_producer(
        api,
        legal_name="Contract Packer Only LLC",
        brand_owner_flag=False,
        importer_of_record_flag=False,
        domestic_licensor_flag=False,
        annual_gross_revenue_usd=9000000,
        contact_email="epr@packer.example",
    )
    headers = fx.officer(producer)
    sku = validate_success(
        api.create_sku(
            f.sku_payload(
                producer["id"],
                name="Co-packed Tray",
                product_category="FOOD_DRY",
                units_sold_annual_estimate=40,
            ),
            headers,
        ),
        201,
    )

    validate_error(
        api.activate_sku(sku["id"], None, headers), ApiErrorId.SKU_HAS_NO_COMPONENTS, 422
    )
    assert_sku(validate_success(api.get_sku(sku["id"], headers)), status=SkuStatus.DRAFT)

    validate_error(
        api.determine_obligation(producer["id"], None, REGULATOR_HEADERS),
        ApiErrorId.PRODUCER_HAS_NO_ACTIVE_SKUS,
        422,
    )
    assert_producer(
        validate_success(api.get_producer(producer["id"], headers)),
        status=ProducerStatus.DRAFT,
        obligated_party_role=ObligatedPartyRole.UNDETERMINED,
    )

    validate_error(
        api.create_registration(
            f.registration_payload(producer["id"], program["id"]), headers
        ),
        ApiErrorId.OBLIGATION_NOT_DETERMINED,
        409,
    )

    validate_success(
        api.add_sku_component(
            sku["id"],
            f.component_payload(material_type="PAPER", unit_weight_grams=30.0),
            headers,
        )
    )
    activated = validate_success(api.activate_sku(sku["id"], None, headers))
    assert_sku(activated, status=SkuStatus.ACTIVE, unit_packaging_weight_grams=30.00)

    determined = fx.determine_obligation(api, producer)
    assert_producer(
        determined,
        status=ProducerStatus.OBLIGATION_DETERMINED,
        obligated_party_role=ObligatedPartyRole.NOT_OBLIGATED,
        determination_stale=False,
    )
    assert_weight(
        determined["annual_packaging_weight_kg"], 1.200, "annual_packaging_weight_kg"
    )

    registration = validate_success(
        api.create_registration(
            f.registration_payload(producer["id"], program["id"]), headers
        ),
        201,
    )
    assert_registration(
        registration,
        status=RegistrationStatus.DRAFT,
        exemption_status=ExemptionStatus.UNDETERMINED,
    )

    validate_error(
        api.submit_registration(registration["id"], None, headers),
        ApiErrorId.PRODUCER_NOT_OBLIGATED,
        422,
    )
    still_draft = validate_success(api.get_registration(registration["id"], headers))
    assert_registration(
        still_draft,
        status=RegistrationStatus.DRAFT,
        exemption_status=ExemptionStatus.UNDETERMINED,
        submitted_at=None,
        version=1,
    )


# ---------------------------------------------------------------------------
# Three uniqueness scopes: (producer, program), (registration, period), (report, unit)
# ---------------------------------------------------------------------------
def test_the_three_uniqueness_scopes_answer_with_three_distinct_codes(api):
    """Each repeat attempt is refused by its own scope and overwrites nothing.

    A second registration for the same producer and program, a second report for
    the same registration and period, and a second line for the same report and
    unit are three different conflicts with three different codes; afterwards the
    producer still holds one registration, the registration still holds two
    reports and the surviving line still carries its original hundred and ten
    units.

    Design: Corner/errors/duplicate_registration_report_and_line_are_all_rejected_with_distinct_codes
    """
    chain = fx.base_ca_chain(api)
    producer, registration = chain["producer"], chain["registration"]
    officer_headers = chain["officer_headers"]
    second_period = fx.make_reporting_period(
        api, chain["program"]["id"], **SECOND_HALF_PERIOD
    )
    draft_report = fx.make_report(api, producer, registration, second_period)
    existing_line = fx.add_line(api, producer, draft_report, chain["sku"], 110)

    validate_error(
        api.create_registration(
            f.registration_payload(producer["id"], chain["program"]["id"]), officer_headers
        ),
        ApiErrorId.DUPLICATE_REGISTRATION,
        409,
    )
    validate_error(
        api.create_report(
            f.report_payload(registration["id"], chain["period"]["id"]), officer_headers
        ),
        ApiErrorId.DUPLICATE_REPORT_FOR_PERIOD,
        409,
    )
    validate_error(
        api.add_report_line(
            draft_report["id"],
            f.report_line_payload(chain["sku"]["id"], 55),
            officer_headers,
        ),
        ApiErrorId.DUPLICATE_REPORT_LINE,
        409,
    )

    registrations, reg_meta = validate_paginated(
        api.list_registrations(officer_headers, {"producer_id": producer["id"]})
    )
    assert reg_meta["total_count"] == 1
    assert [row["id"] for row in registrations] == [registration["id"]]
    reports, report_meta = validate_paginated(
        api.list_reports(officer_headers, {"registration_id": registration["id"]})
    )
    assert report_meta["total_count"] == 2
    assert {row["id"] for row in reports} == {
        chain["report"]["id"],
        draft_report["id"],
    }

    unchanged = validate_success(api.get_report(draft_report["id"], officer_headers))
    assert_report(unchanged, submission_status=SubmissionStatus.DRAFT, line_count=1)
    assert_weight(unchanged["total_weight_kg"], 5.500, "total_weight_kg")
    assert_report_line(
        validate_success(api.get_report_line(existing_line["id"], officer_headers)),
        units_sold=110,
    )


# ---------------------------------------------------------------------------
# The rate-band shape is checked at creation, its emptiness only at publication
# ---------------------------------------------------------------------------
def _pro_and_program(api):
    """One program and one organisation that owns no schedule yet."""
    program = fx.make_breadth_program(api)
    pro = fx.make_pro(
        api, name="Circular Stewardship Alliance", contact_email="ops@csa.example"
    )
    return program, pro, fx.admin(pro)


def test_bands_that_are_not_a_contiguous_partition_are_refused_at_create(api):
    """A gap, an overlap and a set that does not start at zero all fail alike.

    The bands of one material must form a contiguous half-open partition from
    zero, so all three malformed glass sets are refused with the same code and no
    schedule is stored; the organisation's own version never moves, because a
    refused authoring attempt is not a publication.

    Design: Corner/errors/fee_schedule_tier_shape_and_empty_rate_set_are_rejected_at_create_and_publish
    """
    program, pro, admin_headers = _pro_and_program(api)
    malformed = (
        [f.material_rate("GLASS", 0, 100, 9), f.material_rate("GLASS", 200, None, 7)],
        [f.material_rate("GLASS", 0, 300, 9), f.material_rate("GLASS", 200, None, 7)],
        [f.material_rate("GLASS", 50, None, 9)],
    )

    for rates in malformed:
        validate_error(
            api.create_fee_schedule(
                f.fee_schedule_payload(pro["id"], program["id"], material_rates=rates),
                admin_headers,
            ),
            ApiErrorId.FEE_TIER_DISCONTINUOUS,
            422,
        )

    schedules, meta = validate_paginated(
        api.list_fee_schedules(admin_headers, {"pro_id": pro["id"]})
    )
    assert meta["total_count"] == 0
    assert schedules == []
    assert validate_success(api.get_pro(pro["id"], admin_headers))["version"] == 1


def test_an_empty_rate_set_survives_the_create_and_is_refused_at_publish(api):
    """Emptiness is a publication guard, so the draft is stored and then blocked.

    A schedule with no rate rows is accepted as a draft and only the publication
    refuses it, leaving both the schedule and the organisation exactly where they
    were; a second schedule carrying two contiguous glass bands publishes
    normally and takes the organisation's version to two.

    Design: Corner/errors/fee_schedule_tier_shape_and_empty_rate_set_are_rejected_at_create_and_publish
    """
    program, pro, admin_headers = _pro_and_program(api)
    empty = fx.make_fee_schedule(
        api,
        pro,
        program["id"],
        effective_from="2026-01-01",
        effective_to="2026-03-31",
        material_rates=[],
    )
    assert_fee_schedule(empty, status=FeeScheduleStatus.DRAFT, version=1)
    pro_version = fx.read_pro_version(api, pro)

    validate_error(
        api.publish_fee_schedule(
            empty["id"], f.publish_payload(pro_version), admin_headers
        ),
        ApiErrorId.FEE_SCHEDULE_HAS_NO_RATES,
        422,
    )

    assert_fee_schedule(
        validate_success(api.get_fee_schedule(empty["id"], admin_headers)),
        status=FeeScheduleStatus.DRAFT,
        version=1,
    )
    assert fx.read_pro_version(api, pro) == pro_version

    contiguous = fx.make_fee_schedule(
        api,
        pro,
        program["id"],
        effective_from="2026-07-01",
        effective_to=None,
        material_rates=[
            f.material_rate("GLASS", 0, 100, 9),
            f.material_rate("GLASS", 100, None, 7),
        ],
    )
    published = fx.publish_fee_schedule(api, pro, contiguous)

    assert_fee_schedule(published, status=FeeScheduleStatus.PUBLISHED, version=2)
    assert fx.read_pro_version(api, pro) == pro_version + 1


# ---------------------------------------------------------------------------
# Pricing refusals: an unpriced material and a window that ended too early
# ---------------------------------------------------------------------------
def _glass_and_paper_reports(api):
    """One producer filing glass in the first half and paper in the second.

    Both units are activated before the single determination, so the rollup is
    7.500 kg and the determination is never stale; the published schedule prices
    glass alone.
    """
    program = fx.make_breadth_program(api)
    first_period = fx.make_reporting_period(
        api,
        program["id"],
        period_label="CA-2026-H1",
        data_start="2026-07-01",
        data_end="2027-01-01",
        submission_open="2026-07-01T00:00:00Z",
        submission_deadline="2026-12-31T23:59:59Z",
        correction_window_days=30,
    )
    second_period = fx.make_reporting_period(api, program["id"], **SECOND_HALF_PERIOD)
    producer = fx.make_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        brand_owner_flag=True,
        contact_email="compliance@northlake.example",
    )
    glass_sku = fx.glass_mini_sku(api, producer, name="Sparkling Water 750ml")
    paper_sku = fx.make_sku_with_components(
        api,
        producer,
        components=[f.component_payload(material_type="PAPER", unit_weight_grams=40.0)],
        name="Shipper Case 12x750ml",
        units_sold_annual_estimate=50,
    )
    producer = fx.determine_obligation(api, producer)
    assert_weight(
        producer["annual_packaging_weight_kg"], 7.500, "annual_packaging_weight_kg"
    )
    registration = fx.active_registration(api, producer, program["id"])
    pro = fx.make_pro(
        api, name="Circular Stewardship Alliance", contact_email="ops@csa.example"
    )
    schedule = fx.published_fee_schedule(api, pro, program["id"])
    membership = fx.paid_membership(api, producer, registration, pro, schedule)

    glass_report = fx.make_report(api, producer, registration, first_period)
    glass_line = fx.add_line(api, producer, glass_report, glass_sku, 110)
    glass_report = fx.submit_report(api, producer, glass_report)
    paper_report = fx.make_report(api, producer, registration, second_period)
    paper_line = fx.add_line(api, producer, paper_report, paper_sku, 50)
    paper_report = fx.submit_report(api, producer, paper_report)

    officer_headers = fx.officer(producer)
    assert_weight(
        validate_success(api.get_registration(registration["id"], officer_headers))[
            "reported_weight_kg_ytd"
        ],
        7.500,
        "reported_weight_kg_ytd",
    )
    return {
        "producer": producer,
        "pro": pro,
        "membership": membership,
        "glass_report": glass_report,
        "glass_line": glass_line,
        "paper_report": paper_report,
        "paper_line": paper_line,
        "officer_headers": officer_headers,
        "admin_headers": fx.admin(pro),
    }


def test_assessment_refuses_a_material_the_pinned_schedule_does_not_price(api):
    """The paper report cannot be priced at all, while the glass report still can.

    Every priced material needs a band in the pinned schedule, so the paper
    report is refused and stays unassessed with a zero subtotal and a zero line
    fee; the glass report of the same registration prices normally against a tier
    basis of the whole 7.500 kg filed to date.

    Design: Corner/errors/assessment_refuses_a_material_type_absent_from_the_pinned_schedule
    """
    built = _glass_and_paper_reports(api)

    validate_error(
        api.assess_report(
            built["paper_report"]["id"],
            f.assess_payload(FeeVariant.FINAL),
            built["admin_headers"],
        ),
        ApiErrorId.MATERIAL_RATE_MISSING,
        422,
    )

    refused = validate_success(
        api.get_report(built["paper_report"]["id"], built["officer_headers"])
    )
    assert_report(
        refused,
        fee_status=ReportFeeStatus.UNASSESSED,
        fee_subtotal_cents=0,
    )
    assert_report_line(
        validate_success(
            api.get_report_line(built["paper_line"]["id"], built["officer_headers"])
        ),
        line_fee_cents=0,
    )

    assessed = validate_success(
        api.assess_report(
            built["glass_report"]["id"],
            f.assess_payload(FeeVariant.FINAL),
            built["admin_headers"],
        )
    )

    assert_report(
        assessed,
        fee_status=ReportFeeStatus.FINAL,
        fee_variant_applied=FeeVariant.FINAL,
        tier_basis_kg=7.500,
        fee_subtotal_cents=50,
    )
    assert_report_line(
        validate_success(
            api.get_report_line(built["glass_line"]["id"], built["officer_headers"])
        ),
        line_fee_cents=50,
    )
    assert_membership(
        validate_success(
            api.get_membership(built["membership"]["id"], built["officer_headers"])
        ),
        fee_schedule_version_pinned=2,
    )


def test_assessment_refuses_a_pinned_schedule_whose_window_ended_too_early(api):
    """A healthy published schedule still cannot price a period it never covered.

    The producer switches to a second organisation whose schedule ran only to the
    end of March, so the new membership is active and paid and the schedule is
    published, yet the assessment is refused because the window does not reach
    the period's data start; the report keeps its unassessed defaults and the
    superseded membership records why it was terminated.

    Design: Corner/errors/assessment_refuses_a_pinned_schedule_that_was_not_effective_for_the_period
    """
    chain = fx.base_ca_chain(api)
    officer_headers = chain["officer_headers"]
    second_pro = fx.make_pro(
        api, name="Pacific Stewardship Cooperative", contact_email="ops@pacific.example"
    )
    expired = fx.published_fee_schedule(
        api,
        second_pro,
        chain["program"]["id"],
        effective_from="2026-01-01",
        effective_to="2026-03-31",
    )
    switched = fx.paid_membership(
        api, chain["producer"], chain["registration"], second_pro, expired
    )
    assert_membership(
        switched,
        status=MembershipStatus.ACTIVE,
        fee_payment_status=FeePaymentStatus.PAID,
        fee_schedule_version_pinned=2,
    )
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], officer_headers)),
        status=MembershipStatus.TERMINATED,
        decision_reason=DecisionReason.SUPERSEDED_BY_NEW_MEMBERSHIP,
    )

    validate_error(
        api.assess_report(
            chain["report"]["id"],
            f.assess_payload(FeeVariant.FINAL),
            fx.admin(second_pro),
        ),
        ApiErrorId.FEE_SCHEDULE_NOT_EFFECTIVE_FOR_PERIOD,
        422,
    )

    assert_fee_schedule(
        validate_success(api.get_fee_schedule(expired["id"], fx.admin(second_pro))),
        status=FeeScheduleStatus.PUBLISHED,
    )
    unpriced = validate_success(api.get_report(chain["report"]["id"], officer_headers))
    assert_report(
        unpriced,
        fee_status=ReportFeeStatus.UNASSESSED,
        fee_subtotal_cents=0,
    )
    assert_report_line(
        validate_success(api.get_report_line(chain["line"]["id"], officer_headers)),
        line_fee_cents=0,
    )


# ---------------------------------------------------------------------------
# Verification: who may act, what a loud opinion must carry, who comes next
# ---------------------------------------------------------------------------
def test_only_the_assigned_verifier_may_act_and_a_loud_opinion_needs_its_note(api):
    """A stranger cannot start the fieldwork and a qualified opinion needs a note.

    The engagement names one verifier, so a different verifier is refused at 403
    and the engagement stays assigned; once the named verifier starts, a qualified
    opinion with no findings note is refused and leaves the opinion unwritten,
    while the same verifier's unqualified opinion closes the engagement and
    carries the report to verified.

    Design: Corner/errors/verification_actions_are_gated_by_assignment_findings_note_and_rotation
    """
    chain = fx.base_ca_chain(api)
    officer_headers = chain["officer_headers"]
    engagement = fx.assign_engagement(api, chain["report"], VERIFIER_USER_ID)
    assert_engagement(
        engagement,
        status=EngagementStatus.ASSIGNED,
        verifier_user_id=VERIFIER_USER_ID,
        round_index=1,
        opinion=None,
        findings_note=None,
    )
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], officer_headers)),
        submission_status=SubmissionStatus.UNDER_VERIFICATION,
    )

    validate_error(
        api.start_engagement(engagement["id"], None, VERIFIER_ALT_HEADERS),
        ApiErrorId.NOT_ASSIGNED_VERIFIER,
        403,
    )
    assert_engagement(
        validate_success(api.get_engagement(engagement["id"], REGULATOR_HEADERS)),
        status=EngagementStatus.ASSIGNED,
    )

    started = fx.start_engagement(api, engagement, VERIFIER_HEADERS)
    assert_engagement(started, status=EngagementStatus.IN_PROGRESS)

    validate_error(
        api.issue_opinion(
            engagement["id"], f.opinion_payload(Opinion.QUALIFIED), VERIFIER_HEADERS
        ),
        ApiErrorId.FINDINGS_NOTE_REQUIRED,
        422,
    )
    assert_engagement(
        validate_success(api.get_engagement(engagement["id"], VERIFIER_HEADERS)),
        status=EngagementStatus.IN_PROGRESS,
        opinion=None,
        findings_note=None,
    )

    opined = fx.issue_opinion(api, engagement, VERIFIER_HEADERS, Opinion.UNQUALIFIED)

    assert_engagement(
        opined, status=EngagementStatus.OPINION_ISSUED, opinion=Opinion.UNQUALIFIED
    )
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], officer_headers)),
        submission_status=SubmissionStatus.VERIFIED,
    )


def test_the_next_period_demands_a_verifier_who_did_not_opine_before(api):
    """The verifier of the finalised report cannot examine the following one.

    The first report is verified, priced, billed and finalised, so the running
    total holds its 5.500 kg; the next period's report is then submitted and the
    original verifier is refused on rotation grounds, while a second verifier is
    engaged for the first round of that new report.

    Design: Corner/errors/verification_actions_are_gated_by_assignment_findings_note_and_rotation
    """
    chain = fx.base_ca_chain(api)
    officer_headers = chain["officer_headers"]
    fx.verify_report(api, chain["report"], VERIFIER_USER_ID, VERIFIER_HEADERS)
    fx.assess_report(api, chain["pro"], chain["report"], FeeVariant.FINAL)
    fx.issue_invoice(api, chain["pro"], chain["report"], chain["membership"])
    closed = validate_success(
        api.close_report(
            chain["report"]["id"], f.decision_payload("FINALIZE"), REGULATOR_HEADERS
        )
    )
    assert_report(closed, submission_status=SubmissionStatus.FINALIZED)
    assert_weight(
        validate_success(api.get_registration(chain["registration"]["id"], officer_headers))[
            "reported_weight_kg_ytd"
        ],
        5.500,
        "reported_weight_kg_ytd",
    )

    second_period = fx.make_reporting_period(
        api, chain["program"]["id"], **SECOND_HALF_PERIOD
    )
    next_report = fx.make_report(
        api, chain["producer"], chain["registration"], second_period
    )
    fx.add_line(api, chain["producer"], next_report, chain["sku"], 110)
    next_report = fx.submit_report(api, chain["producer"], next_report)
    assert_report(next_report, submission_status=SubmissionStatus.SUBMITTED)

    validate_error(
        api.create_engagement(
            f.engagement_payload(
                next_report["id"], VERIFIER_USER_ID, "2026-08-20", "2026-08-25"
            ),
            REGULATOR_HEADERS,
        ),
        ApiErrorId.VERIFIER_ROTATION_REQUIRED,
        422,
    )
    assert_report(
        validate_success(api.get_report(next_report["id"], officer_headers)),
        submission_status=SubmissionStatus.SUBMITTED,
    )

    rotated = fx.assign_engagement(
        api, next_report, VERIFIER_USER_ID_ALT, "2026-08-20", "2026-08-25"
    )

    assert_engagement(
        rotated,
        status=EngagementStatus.ASSIGNED,
        verifier_user_id=VERIFIER_USER_ID_ALT,
        round_index=1,
    )
    assert_report(
        validate_success(api.get_report(next_report["id"], officer_headers)),
        submission_status=SubmissionStatus.UNDER_VERIFICATION,
    )


# ---------------------------------------------------------------------------
# The registration's own exits: a foreign period and an open report
# ---------------------------------------------------------------------------
def test_a_foreign_period_is_refused_and_an_open_report_blocks_the_withdrawal(api):
    """A period of another program cannot be reported and an open report holds the exit.

    The registration belongs to one program, so a period of the second program is
    refused outright; the withdrawal is then refused while the first report is
    still submitted, and only after that report has been priced, billed and
    finalised does the withdrawal succeed — terminating the membership, clearing
    the posture and deleting nothing.

    Design: Corner/errors/withdraw_is_blocked_by_open_reports_and_reports_reject_a_foreign_period
    """
    chain = fx.base_ca_chain(api)
    officer_headers = chain["officer_headers"]
    other_program = fx.make_breadth_program(api, state_code="WA")
    foreign_period = fx.make_reporting_period(
        api,
        other_program["id"],
        period_label="WA-2026-H1",
        data_start="2026-07-01",
        data_end="2027-01-01",
        submission_open="2026-07-01T00:00:00Z",
        submission_deadline="2026-12-31T23:59:59Z",
        correction_window_days=45,
    )

    validate_error(
        api.create_report(
            f.report_payload(chain["registration"]["id"], foreign_period["id"]),
            officer_headers,
        ),
        ApiErrorId.PERIOD_PROGRAM_MISMATCH,
        422,
    )
    validate_error(
        api.withdraw_registration(
            chain["registration"]["id"],
            f.withdraw_payload("exiting the California market"),
            officer_headers,
        ),
        ApiErrorId.REGISTRATION_HAS_OPEN_REPORTS,
        409,
    )
    assert_registration(
        validate_success(api.get_registration(chain["registration"]["id"], officer_headers)),
        status=RegistrationStatus.ACTIVE,
    )

    fx.assess_report(api, chain["pro"], chain["report"], FeeVariant.FINAL)
    fx.issue_invoice(api, chain["pro"], chain["report"], chain["membership"])
    closed = validate_success(
        api.close_report(
            chain["report"]["id"], f.decision_payload("FINALIZE"), REGULATOR_HEADERS
        )
    )
    assert_report(closed, submission_status=SubmissionStatus.FINALIZED)
    assert_weight(
        validate_success(api.get_registration(chain["registration"]["id"], officer_headers))[
            "reported_weight_kg_ytd"
        ],
        5.500,
        "reported_weight_kg_ytd",
    )

    withdrawn = validate_success(
        api.withdraw_registration(
            chain["registration"]["id"],
            f.withdraw_payload("exiting the California market"),
            officer_headers,
        )
    )

    assert_registration(
        withdrawn,
        status=RegistrationStatus.WITHDRAWN,
        compliance_posture=CompliancePosture.UNDETERMINED,
    )
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], officer_headers)),
        status=MembershipStatus.TERMINATED,
        decision_reason=DecisionReason.REGISTRATION_WITHDRAWN,
    )
    reports, meta = validate_paginated(
        api.list_reports(officer_headers, {"registration_id": chain["registration"]["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in reports] == [chain["report"]["id"]]


# ---------------------------------------------------------------------------
# The membership fee: payable only once approved, and only in full
# ---------------------------------------------------------------------------
def test_the_membership_fee_is_payable_only_when_active_and_only_in_full(api):
    """A pending application has nothing to pay and one cent short is not payment.

    A second application supersedes the paid coverage and starts pending with a
    zero fee, so a payment against it is refused; the approval assesses the flat
    250000 cents because the producer is far below the free tonnage, one cent
    short is refused and leaves the fee outstanding, and only the exact figure
    settles it.

    Design: Corner/errors/membership_fee_payment_requires_an_active_membership_and_the_exact_amount
    """
    chain = fx.base_ca_chain(api)
    officer_headers, pro = chain["officer_headers"], chain["pro"]
    fresh = fx.apply_for_membership(
        api, chain["producer"], chain["registration"], pro, chain["schedule"]
    )
    assert_membership(
        fresh,
        status=MembershipStatus.PENDING,
        membership_fee_cents=0,
        fee_payment_status=FeePaymentStatus.OUTSTANDING,
        fee_schedule_version_pinned=None,
    )

    validate_error(
        api.record_fee_payment(
            fresh["id"], f.fee_payment_payload(250000), fx.admin(pro)
        ),
        ApiErrorId.MEMBERSHIP_NOT_ACTIVE,
        409,
    )

    approved = fx.approve_membership(api, pro, fresh)
    assert_membership(
        approved,
        status=MembershipStatus.ACTIVE,
        fee_payment_status=FeePaymentStatus.OUTSTANDING,
        fee_schedule_version_pinned=2,
    )
    assert_cents(approved["membership_fee_cents"], 250000, "membership_fee_cents")

    validate_error(
        api.record_fee_payment(
            fresh["id"], f.fee_payment_payload(249999), fx.admin(pro)
        ),
        ApiErrorId.MEMBERSHIP_FEE_AMOUNT_MISMATCH,
        422,
    )
    assert_membership(
        validate_success(api.get_membership(fresh["id"], officer_headers)),
        fee_payment_status=FeePaymentStatus.OUTSTANDING,
    )

    paid = fx.pay_membership_fee(api, pro, approved)

    assert_membership(
        paid, status=MembershipStatus.ACTIVE, fee_payment_status=FeePaymentStatus.PAID
    )
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], officer_headers)),
        status=MembershipStatus.TERMINATED,
        decision_reason=DecisionReason.SUPERSEDED_BY_NEW_MEMBERSHIP,
        fee_payment_status=FeePaymentStatus.PAID,
    )


# ---------------------------------------------------------------------------
# Billing the wrong pair, and the inclusive registration deadline
# ---------------------------------------------------------------------------
def test_the_invoice_refuses_a_membership_from_another_registration(api):
    """Two healthy rows still cannot be billed together across registrations.

    The named membership is active and paid and its own registration is active,
    yet the invoice is refused because that coverage belongs to a different
    registration than the report's; billing the matching pair then produces the
    fifty-cent subtotal, three cents of administration and a total of fifty-three
    on the filing producer's balance alone.

    Design: Corner/errors/invoice_refuses_a_membership_belonging_to_another_registration
    """
    chain = fx.base_ca_chain(api)
    officer_headers, admin_headers = chain["officer_headers"], chain["admin_headers"]
    fx.assess_report(api, chain["pro"], chain["report"], FeeVariant.FINAL)

    peer = fx.determined_producer(
        api,
        components=[f.component_payload(material_type="GLASS", unit_weight_grams=25.0)],
        sku_kwargs=dict(
            name="Snack Pouch 150g",
            product_category="FOOD_DRY",
            units_sold_annual_estimate=60,
        ),
        legal_name="Cascade Snacks Corp",
        annual_gross_revenue_usd=7000000,
        brand_owner_flag=True,
        contact_email="epr@cascade.example",
    )
    peer_producer = peer["producer"]
    peer_registration = fx.active_registration(api, peer_producer, chain["program"]["id"])
    peer_membership = fx.paid_membership(
        api, peer_producer, peer_registration, chain["pro"], chain["schedule"]
    )
    assert_membership(
        peer_membership,
        status=MembershipStatus.ACTIVE,
        fee_payment_status=FeePaymentStatus.PAID,
    )

    validate_error(
        api.create_invoice(
            f.invoice_payload(chain["report"]["id"], peer_membership["id"]), admin_headers
        ),
        ApiErrorId.MEMBERSHIP_REGISTRATION_MISMATCH,
        422,
    )

    assert_registration(
        validate_success(
            api.get_registration(peer_registration["id"], fx.officer(peer_producer))
        ),
        status=RegistrationStatus.ACTIVE,
    )
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], officer_headers)),
        fee_status=ReportFeeStatus.FINAL,
    )
    assert_cents(
        validate_success(api.get_producer(chain["producer"]["id"], officer_headers))[
            "assessed_fee_balance_cents"
        ],
        0,
        "assessed_fee_balance_cents",
    )

    invoice = fx.issue_invoice(
        api, chain["pro"], chain["report"], chain["membership"]
    )

    assert_invoice(
        invoice,
        membership_id=chain["membership"]["id"],
        fee_subtotal_cents=50,
        admin_fee_cents=3,
        total_cents=53,
        status=InvoiceStatus.ISSUED,
    )
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], officer_headers)),
        fee_status=ReportFeeStatus.INVOICED,
    )
    assert_cents(
        validate_success(api.get_producer(chain["producer"]["id"], officer_headers))[
            "assessed_fee_balance_cents"
        ],
        53,
        "assessed_fee_balance_cents",
    )
    assert_cents(
        validate_success(
            api.get_producer(peer_producer["id"], fx.officer(peer_producer))
        )["assessed_fee_balance_cents"],
        0,
        "assessed_fee_balance_cents",
    )


def test_the_registration_deadline_instant_is_admitted_and_the_next_is_not(api):
    """The deadline is inclusive: one second later fails, the instant itself passes.

    At the first instant of the new year the submission is refused and the
    registration keeps its draft position with no submission instant at all; wound
    back to the declared deadline instant the same submission succeeds, stamps
    that instant and runs the exemption analysis on the producer's own 5000000
    dollars and 1.200 kg, leaving the posture undetermined because the
    registration is not active yet.

    Design: Corner/errors/registration_submit_admits_the_deadline_instant_and_rejects_the_next_one
    """
    program = fx.make_breadth_program(api)
    built = fx.determined_producer(
        api,
        components=[
            f.component_payload(
                material_type="PLASTIC",
                unit_weight_grams=15.0,
                recyclability_class="LIMITED",
                pcr_content_pct=10,
            )
        ],
        sku_kwargs=dict(
            name="Yoghurt Pot 500g",
            product_category="FOOD_DRY",
            units_sold_annual_estimate=80,
        ),
        legal_name="Deadline Dairy Co",
        annual_gross_revenue_usd=5000000,
        brand_owner_flag=True,
        contact_email="epr@dairy.example",
    )
    producer = built["producer"]
    headers = fx.officer(producer)
    assert_producer(
        producer,
        status=ProducerStatus.OBLIGATION_DETERMINED,
        obligated_party_role=ObligatedPartyRole.BRAND_OWNER,
        determination_stale=False,
    )
    assert_weight(
        producer["annual_packaging_weight_kg"], 1.200, "annual_packaging_weight_kg"
    )
    registration = fx.make_registration(api, producer, program["id"])

    fx.set_clock(api, "2027-01-01T00:00:00Z")
    validate_error(
        api.submit_registration(registration["id"], None, headers),
        ApiErrorId.REGISTRATION_DEADLINE_PASSED,
        422,
    )
    assert_registration(
        validate_success(api.get_registration(registration["id"], headers)),
        status=RegistrationStatus.DRAFT,
        submitted_at=None,
        version=1,
    )

    fx.set_clock(api, "2026-12-31T23:59:59Z")
    submitted = validate_success(
        api.submit_registration(registration["id"], None, headers)
    )

    assert_registration(
        submitted,
        status=RegistrationStatus.SUBMITTED,
        exemption_status=ExemptionStatus.OBLIGATED,
        exemption_basis_applied=ObligationBasis.ENTITY_LEVEL,
        assessed_group_revenue_usd=5000000,
        compliance_posture=CompliancePosture.UNDETERMINED,
    )
    assert_instant_equals(
        submitted["submitted_at"], "2026-12-31T23:59:59Z", "submitted_at"
    )
    assert_weight(
        submitted["assessed_group_weight_kg"], 1.200, "assessed_group_weight_kg"
    )
