"""Role-based access control, shared operations and the segregation-of-duties bars.

Three families live here: a role acting outside its permitted set, an operation
legitimately shared between two roles, and the four institutional bars that stop
one operator carrying a decision from allegation to consequence unaided.
"""
from test_helpers import (
    ADMIN,
    ADMIN_2_USER_ID,
    ADMIN_3_USER_ID,
    ADMIN_USER_ID,
    DEFAULT_CLOCK,
    PUBLISHER,
    REVIEWER,
    REVIEWER_2_USER_ID,
    REVIEWER_USER_ID,
    ApiErrorId,
    api_client,
    assert_bench_hour_ledger,
    assert_case_statuses,
    assert_grant_statuses,
    assert_instant_equals,
    assert_money_cents,
    assert_penalty_ledger,
    assert_score,
    assert_status,
    factories,
    fixtures,
    make_admin_headers,
    make_consumer_headers,
    make_lab_operator_headers,
    plus_days,
    validate_error,
    validate_paginated,
    validate_success,
    validate_unpaginated,
)

DESIGN_CRITERIA = [
    {
        "criterion_code": "AUTH-1",
        "practice_area": "AUTHENTICATION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Unique per-device credentials",
    },
    {
        "criterion_code": "UPD-1",
        "practice_area": "SOFTWARE_UPDATE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Signed firmware updates",
    },
    {
        "criterion_code": "DAT-1",
        "practice_area": "DATA_PROTECTION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Encryption of data at rest",
    },
    {
        "criterion_code": "VLN-1",
        "practice_area": "VULN_DISCLOSURE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Published disclosure contact",
    },
]

# The third-party-test world: the same four practice areas, but the data
# protection criterion now demands bench corroboration.
CAMERA_CRITERIA = [
    dict(criterion, requires_lab_verification=(criterion["criterion_code"] == "DAT-1"))
    for criterion in DESIGN_CRITERIA
]

PRODUCT = {
    "model_name": "Speaker One",
    "sku": "SPK-001",
    "firmware_version": "1.0.0",
    "declared_support_period_end": "2029-08-01T00:00:00Z",
    "update_policy_disclosed": True,
    "retail_units_shipped": 1000,
}

REGISTRY_CONTENT = {
    "update_policy_url": "https://acme.example/updates",
    "update_cadence": "AUTOMATIC",
    "vuln_disclosure_contact": "security@acme.example",
}

VALID_UNTIL = plus_days(DEFAULT_CLOCK, 365)
IN_STORE_UNAUTHORIZED_PENALTY_CENTS = 19320  # 4200 x 4 units x 1.00 x 1.15

NOTICE_ADMIN_1 = make_admin_headers(ADMIN_USER_ID)
ADJUDICATE_ADMIN_2 = make_admin_headers(ADMIN_2_USER_ID)
VACATE_ADMIN_3 = make_admin_headers(ADMIN_3_USER_ID)
CONSUMER = make_consumer_headers()


def design_program():
    return fixtures.create_program(
        "SELF_ATTESTATION",
        tier_overrides={"min_overall_score": 70.00},
        category_overrides={"min_support_period_days": 180},
        criteria=DESIGN_CRITERIA,
    )


def design_sponsor():
    return fixtures.enrol_manufacturer(
        legal_name="Acme Devices",
        contact_email="ops@acme.example",
        enterprise_class="SMALL",
        annual_us_revenue_cents=900000000,
    )


def design_lab():
    return fixtures.register_lab(
        lab_name="Northline Labs",
        accreditation_status="ACCREDITED",
        total_bench_hours=200,
        concurrent_bench_capacity=2,
    )


def design_store():
    return fixtures.register_retailer(retailer_name="MegaMart")


def approved_design_claim():
    return fixtures.approved_claim(
        program=design_program(), sponsor=design_sponsor(), product_overrides=dict(PRODUCT)
    )


class TestConsumerCannotConfigureAProgramTier:
    """A Consumer may read the configuration catalogue but never write it."""

    def test_consumer_program_tier_creation_is_unauthorized_while_the_admin_succeeds(self):
        """The identical payload is refused from a Consumer and accepted from an admin.

        PRD: "A `Consumer` is strictly read-only: it may scan a code, read the configuration catalogue, read survey waves and read the program evaluation, and it has no write capability anywhere in the program."
        Design: Corner/rbac/role_denial_consumer_cannot_configure_a_program_tier
        """
        fixtures.reset_clock()
        payload = factories.create_program_tier_payload(min_overall_score=70.00)

        validate_error(
            api_client.create_program_tier(payload, CONSUMER),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

        tier = validate_success(api_client.create_program_tier(payload, ADMIN), 201)
        assert tier["tier_code"] == "TIER_1"

    def test_consumer_may_read_the_tier_it_could_not_create(self):
        """Reading the configuration catalogue stays inside the Consumer's permitted set.

        PRD: "A syntactically valid principal acting outside its permitted set is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        Design: Corner/rbac/role_denial_consumer_cannot_configure_a_program_tier
        """
        fixtures.reset_clock()
        payload = factories.create_program_tier_payload(min_overall_score=70.00)
        validate_error(
            api_client.create_program_tier(payload, CONSUMER),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        tier = validate_success(api_client.create_program_tier(payload, ADMIN), 201)

        read_back = validate_success(api_client.get_program_tier(tier["id"], CONSUMER))
        assert read_back["tier_code"] == "TIER_1"
        assert read_back["label_validity_days"] == 365


class TestManufacturerCannotDecideItsOwnAssessment:
    """The conformity decision belongs to the independent assessor alone."""

    def _under_review(self):
        claim = fixtures.submitted_claim(
            program=design_program(),
            sponsor=design_sponsor(),
            required_route="SELF_ATTESTATION",
            product_overrides=dict(PRODUCT),
        )
        return claim

    def test_sponsor_deciding_its_own_assessment_is_unauthorized(self):
        """Only a ConformityReviewer may decide, so the sponsoring role is refused.

        PRD: "A `ConformityReviewer` is the independent assessor: it and only it may decide a submitted conformity assessment and may publish or withhold a grant's registry entry."
        Design: Corner/rbac/role_denial_manufacturer_cannot_decide_its_own_assessment
        """
        fixtures.reset_clock()
        claim = self._under_review()

        validate_error(
            api_client.decide_assessment(
                claim.assessment_id,
                factories.decide_payload("APPROVED"),
                claim.sponsor.headers,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

    def test_refused_decision_advances_no_state_and_mints_no_label(self):
        """The assessment stays under review with no reviewer stamped and no grant.

        PRD: "When more than one condition is violated by a single request, the identifier returned is the one belonging to the highest-priority rung of the rejection ladder in §2.6, and the request has no partial effect: a rejected request writes nothing, mutates no derived quantity and advances no state machine."
        Design: Corner/rbac/role_denial_manufacturer_cannot_decide_its_own_assessment
        """
        fixtures.reset_clock()
        claim = self._under_review()

        validate_error(
            api_client.decide_assessment(
                claim.assessment_id,
                factories.decide_payload("APPROVED"),
                claim.sponsor.headers,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

        after = validate_success(
            api_client.get_assessment(claim.assessment_id, claim.sponsor.headers)
        )
        assert_status(after, "status", "UNDER_REVIEW")
        assert after["decided_by_user_id"] is None
        assert after["decided_at"] is None

        _, meta = validate_paginated(
            api_client.list_label_grants(
                claim.sponsor.headers, params={"product_id": claim.product_id}
            )
        )
        assert meta["total_count"] == 0


class TestTestLabOperatorCannotOpenAnAssessment:
    """Opening an assessment is the sponsoring manufacturer's act."""

    def _world(self):
        program = design_program()
        sponsor = design_sponsor()
        lab = design_lab()
        product = fixtures.register_product(program, sponsor, **dict(PRODUCT))
        return program, sponsor, lab, product

    def test_lab_operator_opening_an_assessment_is_unauthorized(self):
        """The laboratory's remit is reports and its own cancellations, not claims.

        PRD: "A `TestLabOperator` files bench-test reports and may cancel its own engagements."
        Design: Corner/rbac/role_denial_test_lab_operator_cannot_open_an_assessment
        """
        fixtures.reset_clock()
        _, _, lab, product = self._world()

        validate_error(
            api_client.create_assessment(
                product["id"],
                factories.open_assessment_payload(product["version"]),
                make_lab_operator_headers(lab.id),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

    def test_refused_open_leaves_the_product_untouched_and_the_list_empty(self):
        """No assessment exists and the product's version counter has not moved.

        PRD: "`version` (integer): a counter that begins at 1 and increments by one on every accepted mutation of the row."
        Design: Corner/rbac/role_denial_test_lab_operator_cannot_open_an_assessment
        """
        fixtures.reset_clock()
        _, _, lab, product = self._world()
        operator = make_lab_operator_headers(lab.id)

        validate_error(
            api_client.create_assessment(
                product["id"], factories.open_assessment_payload(product["version"]), operator
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

        after = validate_success(api_client.get_product(product["id"], operator))
        assert after["version"] == 1
        assert after["spec_revision"] == 1

        _, meta = validate_paginated(
            api_client.list_assessments(operator, params={"product_id": product["id"]})
        )
        assert meta["total_count"] == 0


class TestRetailerCannotRequestALabelGrant:
    """Issuance is the sponsor's request, not the shelf's."""

    def test_retailer_requesting_a_label_grant_is_unauthorized(self):
        """The retailer's remit is education acknowledgement and its own displays.

        PRD: "A `Retailer` acknowledges consumer-education materials and manages its own display authorizations."
        Design: Corner/rbac/role_denial_retailer_cannot_request_a_label_grant
        """
        fixtures.reset_clock()
        claim = approved_design_claim()
        store = design_store()

        validate_error(
            api_client.create_label_grant(
                factories.create_label_grant_payload(claim.product_id, claim.assessment_id),
                store.headers,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

    def test_refused_issuance_leaves_the_assessment_and_the_retailer_where_they_were(self):
        """No grant appears, the approval stands, and the retailer's counts are untouched.

        PRD: "When more than one condition is violated by a single request, the identifier returned is the one belonging to the highest-priority rung of the rejection ladder in §2.6, and the request has no partial effect: a rejected request writes nothing, mutates no derived quantity and advances no state machine."
        Design: Corner/rbac/role_denial_retailer_cannot_request_a_label_grant
        """
        fixtures.reset_clock()
        claim = approved_design_claim()
        store = design_store()

        validate_error(
            api_client.create_label_grant(
                factories.create_label_grant_payload(claim.product_id, claim.assessment_id),
                store.headers,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

        assessment = claim.refresh_assessment()
        assert_status(assessment, "status", "APPROVED")
        assert assessment["grade"] == "A"

        _, meta = validate_paginated(
            api_client.list_label_grants(
                claim.sponsor.headers, params={"product_id": claim.product_id}
            )
        )
        assert meta["total_count"] == 0

        retailer = store.refresh()
        assert retailer["education_materials_ack"] is True
        assert retailer["education_program_version"] == "EDU-2026.1"
        assert retailer["active_display_count"] == 0


class TestRegistryPageAndEvaluationServeConsumerAndRetailerAlike:
    """Two read surfaces admit several roles and answer all of them identically."""

    def _world(self):
        grant = fixtures.published_grant(approved_design_claim(), **REGISTRY_CONTENT)
        survey = fixtures.record_survey(
            survey_period_label="2026-H1",
            survey_period_end="2026-06-30T00:00:00Z",
            respondents_count=300,
            recognized_count=100,
        )
        store = design_store()
        return grant, survey, store

    def test_registry_page_is_field_identical_for_a_consumer_and_a_retailer(self):
        """The public page is a property of the label, not of who scanned it.

        PRD: "Given a `scannable_code`, it returns that code alongside the product's `model_name`, the sponsor's `manufacturer_legal_name`, the `device_category_code` and `program_tier_code` describing the regulatory context, the assessment's `grade` and `decided_overall_score`, the grant's `valid_from`, `valid_until` and `grant_status`, and the registry entry's `support_period_end`, `update_policy_url`, `update_cadence` and `vuln_disclosure_contact`."
        Design: Corner/rbac/shared_operations_registry_page_and_evaluation_serve_consumer_and_retailer_alike
        """
        fixtures.reset_clock()
        grant, _, store = self._world()

        as_consumer = validate_success(api_client.scan_registry(grant.scannable_code, CONSUMER))
        as_retailer = validate_success(
            api_client.scan_registry(grant.scannable_code, store.headers)
        )
        assert as_consumer == as_retailer

        assert as_consumer["grade"] == "A"
        assert_score(as_consumer["decided_overall_score"], 100.00, "decided_overall_score")
        assert_status(as_consumer, "grant_status", "ACTIVE")
        assert_instant_equals(as_consumer["valid_from"], DEFAULT_CLOCK, "valid_from")
        assert_instant_equals(as_consumer["valid_until"], VALID_UNTIL, "valid_until")

    def test_consumer_reads_the_participation_side_of_the_program_evaluation(self):
        """One enrolled sponsor with one active label reads as full participation.

        PRD: "`manufacturer_participation_rate` is 100 times `participating_manufacturer_count` divided by `enrolled_manufacturer_count`, rounded half-up to two decimal places — except that when `enrolled_manufacturer_count` is zero the rate is exactly 0.00."
        Design: Corner/rbac/shared_operations_registry_page_and_evaluation_serve_consumer_and_retailer_alike
        """
        fixtures.reset_clock()
        self._world()

        evaluation = validate_success(api_client.get_program_evaluation(CONSUMER))
        assert evaluation["enrolled_manufacturer_count"] == 1
        assert evaluation["participating_manufacturer_count"] == 1
        assert_score(
            evaluation["manufacturer_participation_rate"],
            100.00,
            "manufacturer_participation_rate",
        )
        assert evaluation["eligible_product_count"] == 1
        assert evaluation["labeled_product_count"] == 1

    def test_consumer_reads_the_recognition_side_of_the_program_evaluation(self):
        """The single closed survey wave supplies both counts and the rounded rate.

        PRD: "`consumer_recognition_rate` is 100 times `recognized_total` divided by `respondents_count`, rounded half-up to two decimal places — except that when `respondents_count` is zero the rate is exactly 0.00, by the same empty-denominator rule."
        Design: Corner/rbac/shared_operations_registry_page_and_evaluation_serve_consumer_and_retailer_alike
        """
        fixtures.reset_clock()
        self._world()

        evaluation = validate_success(api_client.get_program_evaluation(CONSUMER))
        assert evaluation["respondents_count"] == 300
        assert evaluation["recognized_total"] == 100
        assert_score(
            evaluation["consumer_recognition_rate"], 33.33, "consumer_recognition_rate"
        )
        assert_status(evaluation, "evaluation_grade", "PARTIAL")

    def test_retailer_reads_the_grant_and_the_consumer_reads_the_survey_wave(self):
        """Each role reaches the read surfaces its permitted set includes.

        PRD: "A `Consumer` is strictly read-only: it may scan a code, read the configuration catalogue, read survey waves and read the program evaluation, and it has no write capability anywhere in the program."
        Design: Corner/rbac/shared_operations_registry_page_and_evaluation_serve_consumer_and_retailer_alike
        """
        fixtures.reset_clock()
        grant, survey, store = self._world()

        as_retailer = validate_success(api_client.get_label_grant(grant.id, store.headers))
        assert_grant_statuses(as_retailer, "ACTIVE", "PUBLISHED")

        wave = validate_success(api_client.get_recognition_survey(survey["id"], CONSUMER))
        assert wave["respondents_count"] == 300
        assert wave["recognized_count"] == 100


class TestEngagementCancelAcceptedFromSponsorAndLab:
    """Cancellation is shared between the sponsor and the performing laboratory."""

    def _camera_world(self):
        program = fixtures.create_program(
            "THIRD_PARTY_TEST",
            tier_overrides={"min_overall_score": 70.00},
            category_overrides={
                "category_code": "SMART_CAMERA",
                "display_name": "Smart Camera",
                "min_support_period_days": 180,
            },
            criteria=CAMERA_CRITERIA,
        )
        sponsor = design_sponsor()
        lab = design_lab()
        claims = []
        for model_name, sku, units in (
            ("Camera One", "CAM-001", 5000),
            ("Camera Two", "CAM-002", 4000),
        ):
            product = fixtures.register_product(
                program,
                sponsor,
                model_name=model_name,
                sku=sku,
                firmware_version="2.0.0",
                declared_support_period_end="2029-08-01T00:00:00Z",
                update_policy_disclosed=True,
                retail_units_shipped=units,
            )
            assessment = fixtures.open_assessment(program, sponsor, product)
            responses = fixtures.attach_responses(program, sponsor, assessment)
            claim = fixtures.Claim(
                program=program,
                sponsor=sponsor,
                product=product,
                assessment=assessment,
                responses=responses,
            )
            fixtures.submit_claim(claim)
            fixtures.book_engagement(
                claim,
                lab,
                window_start="2026-08-10T09:00:00Z",
                window_end="2026-08-12T09:00:00Z",
                bench_hours=8,
            )
            claims.append(claim)
        return sponsor, lab, claims

    def test_cancellation_is_accepted_from_the_sponsor_and_from_the_laboratory(self):
        """Two engagements at one lab are cancelled by two different roles.

        PRD: "Cancellation is available to both the `Manufacturer` sponsoring the work and the `TestLabOperator` performing it, and it accepts a `cancellation_reason`."
        Design: Corner/rbac/shared_operations_engagement_cancel_accepted_from_both_the_sponsor_and_the_lab
        """
        fixtures.reset_clock()
        sponsor, lab, claims = self._camera_world()
        assert_bench_hour_ledger(lab.refresh(), reserved=16)

        by_sponsor = validate_success(
            api_client.cancel_test_engagement(
                claims[0].engagement["id"],
                factories.cancel_engagement_payload(cancellation_reason="SPONSOR_WITHDREW"),
                sponsor.headers,
            ),
            201,
        )
        assert_status(by_sponsor, "status", "CANCELLED")
        assert by_sponsor["cancellation_reason"] == "SPONSOR_WITHDREW"

        by_lab = validate_success(
            api_client.cancel_test_engagement(
                claims[1].engagement["id"],
                factories.cancel_engagement_payload(cancellation_reason="LAB_UNAVAILABLE"),
                lab.headers,
            ),
            201,
        )
        assert_status(by_lab, "status", "CANCELLED")
        assert by_lab["cancellation_reason"] == "LAB_UNAVAILABLE"

    def test_both_cancellations_return_the_whole_bench_reservation(self):
        """Whoever cancelled, the reserved hours come back and the claims stand.

        PRD: "It is accepted from either `SCHEDULED` or `IN_PROGRESS` — `SCHEDULED → CANCELLED` and `IN_PROGRESS → CANCELLED` behave identically — and it credits the reserved hours back so that `reserved_bench_hours` plus `available_bench_hours` still equals `total_bench_hours` and `reserved_bench_hours` returns to exactly its pre-booking value."
        Design: Corner/rbac/shared_operations_engagement_cancel_accepted_from_both_the_sponsor_and_the_lab
        """
        fixtures.reset_clock()
        sponsor, lab, claims = self._camera_world()

        fixtures.created(
            api_client.cancel_test_engagement(
                claims[0].engagement["id"],
                factories.cancel_engagement_payload(cancellation_reason="SPONSOR_WITHDREW"),
                sponsor.headers,
            )
        )
        fixtures.created(
            api_client.cancel_test_engagement(
                claims[1].engagement["id"],
                factories.cancel_engagement_payload(cancellation_reason="LAB_UNAVAILABLE"),
                lab.headers,
            )
        )

        after_lab = lab.refresh()
        assert_bench_hour_ledger(after_lab, reserved=0)
        assert after_lab["available_bench_hours"] == 200

        for claim in claims:
            assert_status(claim.refresh_assessment(), "status", "UNDER_REVIEW")


class TestPublisherMustDifferFromTheDecidingReviewer:
    """The reviewer who scored the claim may not be the one who makes it public."""

    def _pending(self):
        claim = approved_design_claim()
        return fixtures.pending_grant(claim, **REGISTRY_CONTENT)

    def test_deciding_reviewer_publishing_its_own_claim_is_refused(self):
        """The publication collides with `decided_by_user_id` and nothing moves.

        PRD: "Separately, the `ConformityReviewer` publishing a grant's registry entry must have an `X-User-ID` differing from the `decided_by_user_id` recorded on the backing `ConformanceAssessment`, so the reviewer who scored the claim may not also be the one who makes it public."
        Design: Corner/rbac/segregation_of_duties_publisher_must_differ_from_the_deciding_reviewer
        """
        fixtures.reset_clock()
        grant = self._pending()

        validate_error(
            api_client.decide_registry_publication(
                grant.id, factories.publication_payload("PUBLISHED"), REVIEWER
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

        after = grant.refresh()
        assert_grant_statuses(after, "PENDING_REGISTRY", "DRAFT")
        assert after["valid_from"] is None
        assert after["valid_until"] is None

        validate_error(
            api_client.scan_registry(grant.scannable_code, CONSUMER),
            ApiErrorId.ERR_REGISTRY_CODE_NOT_FOUND.value,
        )

    def test_a_second_reviewer_publishes_the_same_grant(self):
        """A distinct reviewer clears the bar and the first publication activates the label.

        PRD: "It stamps `valid_from` from the logical clock and computes `valid_until` per §3.7, stamps the registry entry's `published_at` from the logical clock and its `published_by_user_id` from the acting reviewer, and makes the public registry lookup resolve for this grant's `scannable_code`."
        Design: Corner/rbac/segregation_of_duties_publisher_must_differ_from_the_deciding_reviewer
        """
        fixtures.reset_clock()
        grant = self._pending()

        published = validate_success(
            api_client.decide_registry_publication(
                grant.id, factories.publication_payload("PUBLISHED"), PUBLISHER
            ),
            201,
        )
        assert_grant_statuses(published, "ACTIVE", "PUBLISHED")
        assert_instant_equals(published["valid_from"], DEFAULT_CLOCK, "valid_from")
        assert_instant_equals(published["valid_until"], VALID_UNTIL, "valid_until")

        entries = validate_unpaginated(
            api_client.get_registry_entry(grant.id, grant.claim.sponsor.headers)
        )
        assert len(entries) == 1
        assert entries[0]["published_by_user_id"] == REVIEWER_2_USER_ID
        assert_status(entries[0], "disclosure_completeness", "COMPLETE")
        assert_instant_equals(entries[0]["published_at"], DEFAULT_CLOCK, "published_at")

        assessment = grant.claim.refresh_assessment()
        assert assessment["decided_by_user_id"] == REVIEWER_USER_ID


class TestAdjudicatorMustDifferFromTheNoticeIssuer:
    """The officer who alleged the misuse may not decide it."""

    def _noticed(self):
        sponsor = design_sponsor()
        case = fixtures.open_case(
            sponsor,
            reported_scannable_code="ZZ-NO-SUCH-CD007",
            violation_type="UNAUTHORIZED_DISPLAY",
            violation_line_items=[factories.violation_line("LST-11", "IN_STORE", 4)],
        )
        noticed = fixtures.issue_notice(
            case, headers=NOTICE_ADMIN_1, notice_reference="NOT-2026-0011"
        )
        return sponsor, noticed

    def test_notice_issuer_adjudicating_its_own_case_is_refused(self):
        """The collision leaves the case at NOTICE_ISSUED with no penalty struck.

        PRD: "On the enforcement chain: the `ProgramAdministrator` adjudicating a case must have an `X-User-ID` differing from that case's `notice_issued_by_user_id`, so the officer who alleged the misuse may not decide it."
        Design: Corner/rbac/segregation_of_duties_adjudicator_must_differ_from_the_notice_issuer
        """
        fixtures.reset_clock()
        sponsor, noticed = self._noticed()

        validate_error(
            api_client.adjudicate_case(
                noticed["id"], factories.adjudicate_payload("UPHELD"), NOTICE_ADMIN_1
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

        after = validate_success(api_client.get_enforcement_case(noticed["id"], ADMIN))
        assert_case_statuses(after, "NOTICE_ISSUED", "NONE")
        assert_money_cents(after["penalty_cents"], 0, "penalty_cents")
        assert after["adjudicated_by_user_id"] is None
        assert_penalty_ledger(sponsor.refresh(), outstanding=0, paid=0, vacated=0)

    def test_a_second_administrator_upholds_and_the_statutory_penalty_lands(self):
        """A distinct adjudicator clears the bar and the first offence carries 1.00.

        PRD: "The first thing computed is the `aggravation_multiplier`, and the moment at which it is read matters: it is one plus 0.25 times the subject manufacturer's `upheld_case_count` **as observed immediately before this adjudication increments it**, capped at 2.00."
        Design: Corner/rbac/segregation_of_duties_adjudicator_must_differ_from_the_notice_issuer
        """
        fixtures.reset_clock()
        sponsor, noticed = self._noticed()

        upheld = validate_success(
            api_client.adjudicate_case(
                noticed["id"], factories.adjudicate_payload("UPHELD"), ADJUDICATE_ADMIN_2
            ),
            201,
        )
        assert_case_statuses(upheld, "ADJUDICATED_UPHELD", "ASSESSED")
        assert upheld["adjudicated_by_user_id"] == ADMIN_2_USER_ID
        assert_status(upheld, "penalty_variant", "STATUTORY_SCHEDULE")
        assert_score(upheld["aggravation_multiplier"], 1.00, "aggravation_multiplier")
        assert_money_cents(
            upheld["penalty_cents"], IN_STORE_UNAUTHORIZED_PENALTY_CENTS, "penalty_cents"
        )

        subject = sponsor.refresh()
        assert_penalty_ledger(
            subject, outstanding=IN_STORE_UNAUTHORIZED_PENALTY_CENTS, paid=0, vacated=0
        )
        assert_money_cents(
            subject["total_assessed_penalty_cents"],
            IN_STORE_UNAUTHORIZED_PENALTY_CENTS,
            "total_assessed_penalty_cents",
        )
        assert subject["upheld_case_count"] == 1
        assert_status(subject, "standing", "GOOD")


class TestVacateMustDifferFromTheAdjudicator:
    """An officer may not quietly undo their own adjudication on appeal."""

    def _upheld(self):
        sponsor = design_sponsor()
        case = fixtures.open_case(
            sponsor,
            reported_scannable_code="ZZ-NO-SUCH-CD008",
            violation_type="UNAUTHORIZED_DISPLAY",
            violation_line_items=[factories.violation_line("LST-12", "IN_STORE", 4)],
        )
        fixtures.issue_notice(case, headers=NOTICE_ADMIN_1, notice_reference="NOT-2026-0012")
        upheld = fixtures.adjudicate(case, "UPHELD", headers=ADJUDICATE_ADMIN_2)
        return sponsor, upheld

    def test_adjudicator_vacating_its_own_adjudication_is_refused(self):
        """The collision leaves the upheld case and its assessed penalty intact.

        PRD: "And a vacate must be performed by a `ProgramAdministrator` whose `X-User-ID` differs from the case's `adjudicated_by_user_id`, so an officer may not quietly undo their own adjudication on appeal."
        Design: Corner/rbac/segregation_of_duties_vacate_must_differ_from_the_adjudicator
        """
        fixtures.reset_clock()
        sponsor, upheld = self._upheld()

        validate_error(
            api_client.vacate_case(upheld["id"], factories.vacate_payload(), ADJUDICATE_ADMIN_2),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

        after = validate_success(api_client.get_enforcement_case(upheld["id"], ADMIN))
        assert_case_statuses(after, "ADJUDICATED_UPHELD", "ASSESSED")
        assert_money_cents(
            after["penalty_cents"], IN_STORE_UNAUTHORIZED_PENALTY_CENTS, "penalty_cents"
        )
        assert after["vacate_reason"] is None
        assert_penalty_ledger(
            sponsor.refresh(), outstanding=IN_STORE_UNAUTHORIZED_PENALTY_CENTS, paid=0, vacated=0
        )

    def test_a_third_administrator_vacates_and_the_money_moves_across(self):
        """A distinct vacating officer clears the bar and compensation reverses the ledger.

        PRD: "The penalty amount leaves `outstanding_penalty_cents` and enters `vacated_penalty_cents`, so `total_assessed_penalty_cents` is unchanged and the conservation identity still holds."
        Design: Corner/rbac/segregation_of_duties_vacate_must_differ_from_the_adjudicator
        """
        fixtures.reset_clock()
        sponsor, upheld = self._upheld()

        vacated = validate_success(
            api_client.vacate_case(
                upheld["id"],
                factories.vacate_payload(vacate_reason="Evidence retracted on appeal"),
                VACATE_ADMIN_3,
            ),
            201,
        )
        assert_case_statuses(vacated, "VACATED", "VACATED")
        assert vacated["vacate_reason"] == "Evidence retracted on appeal"
        assert_money_cents(
            vacated["penalty_cents"], IN_STORE_UNAUTHORIZED_PENALTY_CENTS, "penalty_cents"
        )

        subject = sponsor.refresh()
        assert_penalty_ledger(
            subject, outstanding=0, paid=0, vacated=IN_STORE_UNAUTHORIZED_PENALTY_CENTS
        )
        assert_money_cents(
            subject["total_assessed_penalty_cents"],
            IN_STORE_UNAUTHORIZED_PENALTY_CENTS,
            "total_assessed_penalty_cents",
        )
        assert subject["upheld_case_count"] == 0
        assert_status(subject, "standing", "GOOD")
