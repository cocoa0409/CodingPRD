"""Endpoint-surface corners for the Consumer Device Security Labeling API.

Covers the standard create/read/missing-read triple, batch atomicity on a
criterion-response write, the denormalised public registry page, a
cross-reference that needs both of its ends to exist, an action endpoint whose
two legs join before adjudication, and a conditional sweep with nothing due.
"""
from test_helpers import (
    ADMIN,
    ADMIN_2_USER_ID,
    ADMIN_USER_ID,
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_bench_hour_ledger,
    assert_case_statuses,
    assert_common_fields,
    assert_grant_statuses,
    assert_instant_equals,
    assert_money_cents,
    assert_pagination_meta,
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
)

# The canonical world these corners pin: a self-attestation tier whose approval
# bar sits at 70.00, one eligible smart-speaker category, and a four-criterion
# catalogue in which every criterion is self-declarable and carries equal
# weight, so a fully conformant claim scores exactly 100.00 and grades A.
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

NOTICE_ADMIN_1 = make_admin_headers(ADMIN_USER_ID)
ADJUDICATE_ADMIN_2 = make_admin_headers(ADMIN_2_USER_ID)
CONSUMER = make_consumer_headers()


def design_program():
    """Tier at a 70.00 bar, eligible category, four self-declarable criteria."""
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


def published_design_grant():
    """A live label over the canonical world, published by a second reviewer."""
    program = design_program()
    sponsor = design_sponsor()
    claim = fixtures.approved_claim(
        program=program, sponsor=sponsor, product_overrides=dict(PRODUCT)
    )
    return fixtures.published_grant(claim, **REGISTRY_CONTENT)


class TestTestLabRegistrationAndRead:
    """Create, read back and miss on the test-laboratory collection."""

    def test_registration_initialises_the_bench_ledger_and_reads_back_identically(self):
        """A registered lab starts at zero reserved hours and re-reads unchanged.

        PRD: "Registration initialises the bench ledger so that `reserved_bench_hours` is 0 and `available_bench_hours` equals `total_bench_hours`."
        Design: Corner/endpoints/standard_crud_test_lab_create_read_and_missing_read
        """
        fixtures.reset_clock()
        created = validate_success(
            api_client.create_test_lab(
                factories.create_test_lab_payload(
                    lab_name="Northline Labs",
                    accreditation_status="ACCREDITED",
                    total_bench_hours=200,
                    concurrent_bench_capacity=2,
                ),
                ADMIN,
            ),
            201,
        )
        assert_common_fields(created)
        assert created["lab_name"] == "Northline Labs"
        assert_status(created, "accreditation_status", "ACCREDITED")
        assert created["total_bench_hours"] == 200
        assert created["concurrent_bench_capacity"] == 2
        assert created["reserved_bench_hours"] == 0
        assert created["available_bench_hours"] == 200
        assert_bench_hour_ledger(created, reserved=0)

        # The lab operator reads its own row and sees exactly what was written.
        operator = make_lab_operator_headers(created["id"])
        fetched = validate_success(api_client.get_test_lab(created["id"], operator))
        assert fetched == created

    def test_unknown_lab_identifier_reports_the_lab_not_found_code(self):
        """A path id that resolves to no laboratory row is a 404 for that entity.

        PRD: "The reported code is the not-found code of whichever entity failed to resolve first — `ERR_PROGRAM_CONFIG_NOT_FOUND` for an unknown program tier or device category, `ERR_MANUFACTURER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CRITERION_NOT_FOUND`, `ERR_TEST_LAB_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CASE_NOT_FOUND` or `ERR_REGISTRY_CODE_NOT_FOUND`."
        Design: Corner/endpoints/standard_crud_test_lab_create_read_and_missing_read
        """
        fixtures.reset_clock()
        design_lab()
        validate_error(
            api_client.get_test_lab("00000000-0000-4000-8000-0000000000ff", ADMIN),
            ApiErrorId.ERR_TEST_LAB_NOT_FOUND.value,
        )


class TestCriterionResponseBatchAtomicity:
    """One unresolvable element rejects the whole response batch."""

    def _draft(self):
        program = design_program()
        sponsor = design_sponsor()
        product = fixtures.register_product(program, sponsor, **dict(PRODUCT))
        assessment = fixtures.open_assessment(program, sponsor, product)
        return program, sponsor, assessment

    def test_batch_naming_a_missing_criterion_reports_criterion_not_found(self):
        """The unresolvable body foreign key decides the response code.

        PRD: "The reported code is the not-found code of whichever entity failed to resolve first — `ERR_PROGRAM_CONFIG_NOT_FOUND` for an unknown program tier or device category, `ERR_MANUFACTURER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CRITERION_NOT_FOUND`, `ERR_TEST_LAB_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CASE_NOT_FOUND` or `ERR_REGISTRY_CODE_NOT_FOUND`."
        Design: Corner/endpoints/bulk_action_response_batch_writes_nothing_when_one_element_is_unresolvable
        """
        fixtures.reset_clock()
        program, sponsor, assessment = self._draft()
        payload = factories.criterion_responses_payload(
            [
                factories.response_item(program.criterion_id("AUTH-1"), True),
                factories.response_item("00000000-0000-4000-8000-0000000000aa", True),
            ]
        )
        validate_error(
            api_client.create_criterion_responses(assessment["id"], payload, sponsor.headers),
            ApiErrorId.ERR_CRITERION_NOT_FOUND.value,
        )

    def test_rejected_batch_writes_none_of_its_elements(self):
        """The valid first element is not persisted and the assessment does not move.

        PRD: "When more than one condition is violated by a single request, the identifier returned is the one belonging to the highest-priority rung of the rejection ladder in §2.6, and the request has no partial effect: a rejected request writes nothing, mutates no derived quantity and advances no state machine."
        Design: Corner/endpoints/bulk_action_response_batch_writes_nothing_when_one_element_is_unresolvable
        """
        fixtures.reset_clock()
        program, sponsor, assessment = self._draft()
        payload = factories.criterion_responses_payload(
            [
                factories.response_item(program.criterion_id("AUTH-1"), True),
                factories.response_item("00000000-0000-4000-8000-0000000000aa", True),
            ]
        )
        validate_error(
            api_client.create_criterion_responses(assessment["id"], payload, sponsor.headers),
            ApiErrorId.ERR_CRITERION_NOT_FOUND.value,
        )

        rows, meta = validate_paginated(
            api_client.list_criterion_responses(
                sponsor.headers, params={"assessment_id": assessment["id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        after = validate_success(api_client.get_assessment(assessment["id"], sponsor.headers))
        assert_status(after, "status", "DRAFT")


class TestPublicRegistryPageDenormalization:
    """The scan endpoint assembles one page out of five different rows."""

    def test_scan_returns_every_denormalized_field_of_the_published_label(self):
        """Product, sponsor, category, tier, assessment, grant and entry all show up.

        PRD: "Given a `scannable_code`, it returns that code alongside the product's `model_name`, the sponsor's `manufacturer_legal_name`, the `device_category_code` and `program_tier_code` describing the regulatory context, the assessment's `grade` and `decided_overall_score`, the grant's `valid_from`, `valid_until` and `grant_status`, and the registry entry's `support_period_end`, `update_policy_url`, `update_cadence` and `vuln_disclosure_contact`."
        Design: Corner/endpoints/computed_read_public_registry_page_denormalizes_product_and_registry_fields
        """
        fixtures.reset_clock()
        grant = published_design_grant()

        page = validate_success(api_client.scan_registry(grant.scannable_code, CONSUMER))
        assert page["scannable_code"] == grant.scannable_code
        assert page["model_name"] == "Speaker One"
        assert page["manufacturer_legal_name"] == "Acme Devices"
        assert page["device_category_code"] == "SMART_SPEAKER"
        assert page["program_tier_code"] == "TIER_1"
        assert page["grade"] == "A"
        assert_score(page["decided_overall_score"], 100.00, "decided_overall_score")
        assert_status(page, "grant_status", "ACTIVE")
        assert_instant_equals(page["valid_from"], DEFAULT_CLOCK, "valid_from")
        assert_instant_equals(page["valid_until"], VALID_UNTIL, "valid_until")
        assert_instant_equals(
            page["support_period_end"], "2029-08-01T00:00:00Z", "support_period_end"
        )
        assert page["update_policy_url"] == "https://acme.example/updates"
        assert page["update_cadence"] == "AUTOMATIC"
        assert page["vuln_disclosure_contact"] == "security@acme.example"


class TestDisplayAuthorizationCrossReference:
    """A display authorization resolves both of its foreign keys or neither."""

    def test_authorization_naming_a_missing_grant_reports_grant_not_found(self):
        """The unresolvable grant reference decides the response before any gate runs.

        PRD: "The reported code is the not-found code of whichever entity failed to resolve first — `ERR_PROGRAM_CONFIG_NOT_FOUND` for an unknown program tier or device category, `ERR_MANUFACTURER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CRITERION_NOT_FOUND`, `ERR_TEST_LAB_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CASE_NOT_FOUND` or `ERR_REGISTRY_CODE_NOT_FOUND`."
        Design: Corner/endpoints/cross_reference_link_display_authorization_needs_both_ends_to_exist
        """
        fixtures.reset_clock()
        published_design_grant()
        store = design_store()

        validate_error(
            api_client.create_display_authorization(
                factories.create_display_authorization_payload(
                    store.id,
                    "00000000-0000-4000-8000-0000000000bb",
                    "2026-09-01T00:00:00Z",
                    "2026-12-31T00:00:00Z",
                    channel="ONLINE",
                ),
                store.headers,
            ),
            ApiErrorId.ERR_GRANT_NOT_FOUND.value,
        )

    def test_authorization_with_both_ends_resolved_links_and_recounts_the_retailer(self):
        """With a real grant the link is created and the retailer's counts move.

        PRD: "A new authorization starts with `status` at `AUTHORIZED`, the initial value of a lifecycle whose full set is `AUTHORIZED`, `WITHDRAWN` and `EXPIRED`, and with `withdrawal_reason` null."
        Design: Corner/endpoints/cross_reference_link_display_authorization_needs_both_ends_to_exist
        """
        fixtures.reset_clock()
        grant = published_design_grant()
        store = design_store()

        authorization = validate_success(
            api_client.create_display_authorization(
                factories.create_display_authorization_payload(
                    store.id,
                    grant.id,
                    "2026-09-01T00:00:00Z",
                    "2026-12-31T00:00:00Z",
                    channel="ONLINE",
                ),
                store.headers,
            ),
            201,
        )
        assert_common_fields(authorization)
        assert authorization["retailer_id"] == store.id
        assert authorization["label_grant_id"] == grant.id
        assert authorization["channel"] == "ONLINE"
        assert_status(authorization, "status", "AUTHORIZED")
        assert authorization["withdrawal_reason"] is None

        retailer = store.refresh()
        assert retailer["active_display_count"] == 1
        assert_status(retailer, "participation_tier", "BASELINE")

        rows, meta = validate_paginated(
            api_client.list_display_authorizations(
                store.headers, params={"label_grant_id": grant.id}
            )
        )
        assert [row["id"] for row in rows] == [authorization["id"]]
        assert meta["total_count"] == 1


class TestEnforcementCaseForkJoin:
    """The referral leg and the notice leg join before adjudication."""

    def _forked_case(self):
        sponsor = design_sponsor()
        lab = design_lab()
        case = fixtures.open_case(
            sponsor,
            reported_scannable_code="ZZ-NO-SUCH-CD006",
            violation_type="UNAUTHORIZED_DISPLAY",
            violation_line_items=[factories.violation_line("LST-7", "ONLINE", 4)],
            reporter_note="Marketplace listing showed a code the registry does not know",
        )
        referred = fixtures.refer_to_lab(case, lab, headers=NOTICE_ADMIN_1)
        noticed = fixtures.issue_notice(
            case, headers=NOTICE_ADMIN_1, notice_reference="NOT-2026-014"
        )
        return sponsor, lab, case, referred, noticed

    def test_notice_after_referral_preserves_the_referral_evidence(self):
        """Each leg records its own field and neither erases the other's.

        PRD: "Crucially, the two legs do not overwrite each other's evidence: taking the referral leg after the notice leg preserves `notice_issued_by_user_id`, and taking the notice leg after the referral leg preserves `referred_test_lab_id`."
        Design: Corner/endpoints/action_endpoint_case_fork_joins_lab_referral_and_notice_before_dismissal
        """
        fixtures.reset_clock()
        _, lab, _, referred, noticed = self._forked_case()

        assert_case_statuses(referred, "LAB_REFERRAL", "NONE")
        assert referred["referred_test_lab_id"] == lab.id

        assert_case_statuses(noticed, "NOTICE_ISSUED", "NONE")
        assert noticed["notice_reference"] == "NOT-2026-014"
        assert noticed["notice_issued_by_user_id"] == ADMIN_USER_ID
        assert noticed["referred_test_lab_id"] == lab.id

    def test_dismissal_terminates_the_case_without_touching_the_money(self):
        """A dismissed adjudication ends `case_status` while `penalty_status` never moves.

        PRD: "A `DISMISSED` outcome moves `case_status` to `ADJUDICATED_DISMISSED` and stops there. It leaves `penalty_status` at `NONE` and `penalty_cents` at 0, performs no ledger recomputation, and leaves the subject's `standing` exactly as it was."
        Design: Corner/endpoints/action_endpoint_case_fork_joins_lab_referral_and_notice_before_dismissal
        """
        fixtures.reset_clock()
        sponsor, _, case, _, _ = self._forked_case()

        adjudicated = validate_success(
            api_client.adjudicate_case(
                case["id"], factories.adjudicate_payload("DISMISSED"), ADJUDICATE_ADMIN_2
            ),
            201,
        )
        assert_case_statuses(adjudicated, "ADJUDICATED_DISMISSED", "NONE")
        assert_money_cents(adjudicated["penalty_cents"], 0, "penalty_cents")
        assert adjudicated["penalty_variant"] is None
        assert adjudicated["aggravation_multiplier"] is None
        assert_instant_equals(adjudicated["adjudicated_at"], DEFAULT_CLOCK, "adjudicated_at")
        assert adjudicated["adjudicated_by_user_id"] == ADMIN_2_USER_ID

        subject = sponsor.refresh()
        assert subject["upheld_case_count"] == 0
        assert_penalty_ledger(subject, outstanding=0, paid=0, vacated=0)
        assert_money_cents(
            subject["total_assessed_penalty_cents"], 0, "total_assessed_penalty_cents"
        )
        assert_status(subject, "standing", "GOOD")


class TestExpirySweepWithNothingDue:
    """A sweep with no clock-dependent edge due reports four zeros."""

    def _world(self):
        grant = published_design_grant()
        store = design_store()
        authorization = fixtures.authorize_display(
            grant,
            store,
            channel="ONLINE",
            display_from="2026-09-01T00:00:00Z",
            display_until="2026-12-31T00:00:00Z",
        )
        return grant, store, authorization

    def test_sweep_reports_zero_on_every_counter_when_no_edge_is_due(self):
        """Nothing has reached its edge at the initial clock, so every counter is zero.

        PRD: "Time-driven transitions are applied by an administrator-only **expiry sweep** capability, which advances every clock-dependent edge in the program to the current logical clock and reports how much it moved: `grants_expired`, `grants_suspended`, `authorizations_expired` and `engagements_started`."
        Design: Corner/endpoints/conditional_action_expiry_sweep_reports_all_zero_when_nothing_is_due
        """
        fixtures.reset_clock()
        self._world()

        report = validate_success(api_client.run_expiry_sweep(ADMIN))
        assert report["grants_expired"] == 0
        assert report["grants_suspended"] == 0
        assert report["authorizations_expired"] == 0
        assert report["engagements_started"] == 0

    def test_second_sweep_changes_nothing_and_reports_zeros_again(self):
        """Re-running the sweep on a fixed clock leaves every row exactly as it was.

        PRD: "The sweep is idempotent for a fixed clock — running it twice without moving the clock changes nothing the second time and reports zeros."
        Design: Corner/endpoints/conditional_action_expiry_sweep_reports_all_zero_when_nothing_is_due
        """
        fixtures.reset_clock()
        grant, store, authorization = self._world()

        fixtures.run_sweep()
        second = validate_success(api_client.run_expiry_sweep(ADMIN))
        assert second["grants_expired"] == 0
        assert second["grants_suspended"] == 0
        assert second["authorizations_expired"] == 0
        assert second["engagements_started"] == 0

        after_grant = grant.refresh()
        assert_grant_statuses(after_grant, "ACTIVE", "PUBLISHED")
        assert after_grant["suspension_reason"] is None
        assert after_grant["renewal_required"] is False
        assert_instant_equals(after_grant["valid_until"], VALID_UNTIL, "valid_until")

        after_auth = validate_success(
            api_client.get_display_authorization(authorization["id"], store.headers)
        )
        assert_status(after_auth, "status", "AUTHORIZED")

        retailer = store.refresh()
        assert retailer["active_display_count"] == 1
        assert_status(retailer, "participation_tier", "BASELINE")
