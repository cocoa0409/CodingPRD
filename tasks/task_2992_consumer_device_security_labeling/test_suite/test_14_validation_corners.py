"""Corner cases in the validation rules and the rejection-precedence ladder.

Each test drives one request that breaks exactly one rule - or breaks two and
must report the earlier one - and then proves the refusal left no trace: the
target entity keeps its status, its version and its derived fields, and the
collections that would have grown stay empty.
"""
from test_helpers import (
    ADMIN,
    CONSUMER_HEADERS,
    DEFAULT_CLOCK,
    PUBLISHER,
    REVIEWER,
    ApiErrorId,
    api_client,
    assert_assessment_status,
    assert_case_statuses,
    assert_grant_statuses,
    assert_instant_equals,
    assert_money_cents,
    assert_pagination_meta,
    assert_penalty_ledger,
    assert_score,
    assert_status,
    assert_version_is,
    factories,
    fixtures,
    plus_days,
    validate_error,
    validate_paginated,
    validate_success,
    validate_unpaginated,
)

# --------------------------------------------------------------------------
# Shared literals
#
# A flat four-criterion catalogue - one criterion of weight 10 in each practice
# area, none of them lab-verifiable - scores every area at 100.00 and the claim
# at 100.00 overall, so no test below is entangled with the scoring rules.
# --------------------------------------------------------------------------
FLAT_CRITERIA = [
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

# The same catalogue with DATA_PROTECTION made lab-verifiable, so an unverified
# self-declaration in that area earns only the tier's 0.60 weight factor.
LAB_VERIFIED_DATA_CRITERIA = [
    dict(criterion, requires_lab_verification=(criterion["criterion_code"] == "DAT-1"))
    for criterion in FLAT_CRITERIA
]

TIER_OVERRIDES = {"min_overall_score": 70.00}
CATEGORY_OVERRIDES = {"min_support_period_days": 180}

SPONSOR_OVERRIDES = {
    "legal_name": "Acme Devices",
    "contact_email": "ops@acme.example",
    "enterprise_class": "SMALL",
    "annual_us_revenue_cents": 900000000,
}

PRODUCT_BASE = {
    "model_name": "Speaker One",
    "sku": "SPK-001",
    "firmware_version": "1.0.0",
    "declared_support_period_end": "2029-08-01T00:00:00Z",
    "update_policy_disclosed": True,
    "retail_units_shipped": 1000,
}

REGISTRY_ENTRY = {
    "update_policy_url": "https://acme.example/updates",
    "update_cadence": "AUTOMATIC",
    "vuln_disclosure_contact": "security@acme.example",
}


def _flat_program(criteria=None, tier_overrides=None, category_overrides=None):
    """A SELF_ATTESTATION tier whose minimum score is 70.00 plus one category."""
    tier = dict(TIER_OVERRIDES)
    tier.update(tier_overrides or {})
    category = dict(CATEGORY_OVERRIDES)
    category.update(category_overrides or {})
    return fixtures.create_program(
        "SELF_ATTESTATION",
        tier_overrides=tier,
        category_overrides=category,
        criteria=criteria if criteria is not None else FLAT_CRITERIA,
    )


def _acme():
    return fixtures.enrol_manufacturer(**SPONSOR_OVERRIDES)


def _product(program, sponsor, **overrides):
    payload = dict(PRODUCT_BASE)
    payload.update(overrides)
    return fixtures.register_product(program, sponsor, **payload)


def _draft_claim(program, sponsor, product, codes=None):
    """A DRAFT assessment carrying one response per criterion in `codes`."""
    assessment = fixtures.open_assessment(program, sponsor, product)
    claim = fixtures.Claim(
        program=program, sponsor=sponsor, product=product, assessment=assessment
    )
    claim.responses = fixtures.attach_responses(
        program, sponsor, assessment, codes=codes
    )
    claim.refresh_product()
    return claim


def _approved_claim(program, sponsor, product):
    """The whole self-attestation cycle up to APPROVED by reviewer-1."""
    claim = _draft_claim(program, sponsor, product)
    fixtures.submit_claim(claim)
    fixtures.decide_claim(claim, "APPROVED", REVIEWER)
    claim.refresh_product()
    return claim


class TestSubmitRequiresEveryPracticeArea:
    """A claim that answers only three of the four practice areas."""

    def test_an_unanswered_practice_area_blocks_submission_outright(self):
        """Submitting with VULN_DISCLOSURE unanswered is refused and nothing is stamped.

        PRD: "An unanswered practice area is not scored as a zero — it makes the claim unscoreable, and the submission is rejected with `ERR_PRACTICE_AREA_UNCOVERED`."
        Design: Corner/validations/violation_to_error_submit_without_all_four_practice_areas
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _flat_program()
        sponsor = _acme()
        product = _product(program, sponsor)
        claim = _draft_claim(
            program, sponsor, product, codes=["AUTH-1", "UPD-1", "DAT-1"]
        )

        validate_error(
            api_client.submit_assessment(claim.assessment_id, sponsor.headers),
            ApiErrorId.ERR_PRACTICE_AREA_UNCOVERED.value,
        )

        stored = validate_success(
            api_client.get_assessment(claim.assessment_id, ADMIN)
        )
        assert_assessment_status(stored, "DRAFT")
        assert stored["provisional_overall_score"] is None, stored[
            "provisional_overall_score"
        ]
        assert stored["submitted_at"] is None, stored["submitted_at"]


class TestDuplicateCriterionInsideOneBatch:
    """One batch that names AUTH-1 twice."""

    def _draft(self):
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _flat_program()
        sponsor = _acme()
        product = _product(program, sponsor)
        assessment = fixtures.open_assessment(program, sponsor, product)
        return program, sponsor, assessment

    def _duplicating_batch(self, program):
        return factories.criterion_responses_payload(
            [
                factories.response_item(program.criterion_id("AUTH-1"), True),
                factories.response_item(program.criterion_id("UPD-1"), True),
                factories.response_item(program.criterion_id("DAT-1"), True),
                factories.response_item(
                    program.criterion_id("AUTH-1"), False, evidence_ref="EV-AUTH-1-DUP"
                ),
            ]
        )

    def test_a_repeat_inside_the_batch_is_rejected(self):
        """The batch that names AUTH-1 twice is refused as a duplicate response.

        PRD: "A batch that repeats a criterion within itself, or that names a criterion already answered in this assessment, is rejected in its entirety with `ERR_DUPLICATE_CRITERION_RESPONSE` — nothing from the batch is written."
        Design: Corner/validations/violation_to_error_duplicate_criterion_inside_one_response_batch
        """
        program, sponsor, assessment = self._draft()

        validate_error(
            api_client.create_criterion_responses(
                assessment["id"], self._duplicating_batch(program), sponsor.headers
            ),
            ApiErrorId.ERR_DUPLICATE_CRITERION_RESPONSE.value,
        )

        stored = validate_success(api_client.get_assessment(assessment["id"], ADMIN))
        assert_assessment_status(stored, "DRAFT")

    def test_the_three_good_rows_in_the_rejected_batch_are_not_written(self):
        """Not even the non-duplicated responses survive the rejected batch.

        PRD: "A batch that repeats a criterion within itself, or that names a criterion already answered in this assessment, is rejected in its entirety with `ERR_DUPLICATE_CRITERION_RESPONSE` — nothing from the batch is written."
        Design: Corner/validations/violation_to_error_duplicate_criterion_inside_one_response_batch
        """
        program, sponsor, assessment = self._draft()

        validate_error(
            api_client.create_criterion_responses(
                assessment["id"], self._duplicating_batch(program), sponsor.headers
            ),
            ApiErrorId.ERR_DUPLICATE_CRITERION_RESPONSE.value,
        )

        rows, meta = validate_paginated(
            api_client.list_criterion_responses(
                sponsor.headers, params={"assessment_id": assessment["id"]}
            )
        )
        assert rows == [], rows
        assert_pagination_meta(meta, 10, 0, total_count=0)


class TestThirdPartyRouteNeedsACompletedEngagement:
    """A fully conformant third-party claim that never booked a bench."""

    def _submitted(self):
        fixtures.set_clock(DEFAULT_CLOCK)
        program = fixtures.create_program(
            "THIRD_PARTY_TEST",
            tier_overrides={"min_overall_score": 70.00},
            category_overrides={
                "category_code": "SMART_CAMERA",
                "display_name": "Smart Camera",
                "min_support_period_days": 180,
            },
            criteria=LAB_VERIFIED_DATA_CRITERIA,
        )
        sponsor = _acme()
        product = _product(
            program,
            sponsor,
            model_name="Camera One",
            sku="CAM-001",
            firmware_version="2.0.0",
            retail_units_shipped=500,
        )
        claim = _draft_claim(program, sponsor, product)
        fixtures.submit_claim(claim)
        return claim

    def test_approval_without_a_completed_engagement_is_refused(self):
        """The reviewer cannot approve a third-party claim no laboratory has corroborated.

        PRD: "An approval requires that `status` is `UNDER_REVIEW`, that a third-party-route assessment already has at least one test engagement whose `status` is `COMPLETED` (otherwise `ERR_THIRD_PARTY_TEST_REQUIRED`), and that `decided_overall_score` is greater than or equal to the tier's `min_overall_score` (otherwise `ERR_SCORE_BELOW_MINIMUM`)."
        Design: Corner/validations/conditional_validation_third_party_route_requires_a_completed_engagement
        """
        claim = self._submitted()

        validate_error(
            api_client.decide_assessment(
                claim.assessment_id, factories.decide_payload("APPROVED"), REVIEWER
            ),
            ApiErrorId.ERR_THIRD_PARTY_TEST_REQUIRED.value,
        )

        stored = validate_success(
            api_client.get_assessment(claim.assessment_id, ADMIN)
        )
        assert_assessment_status(stored, "UNDER_REVIEW")
        assert_status(stored, "route", "THIRD_PARTY_TEST")
        assert stored["decided_at"] is None, stored["decided_at"]
        assert stored["decided_by_user_id"] is None, stored["decided_by_user_id"]

    def test_the_provisional_score_exists_while_the_decided_score_stays_null(self):
        """Submission scores the claim provisionally, but the third-party route decides nothing.

        PRD: "What happens next depends on the route: when `route` is `SELF_ATTESTATION` the provisional score *is* the decided score, so `decided_overall_score` is set from `provisional_overall_score` and `grade` is derived from it; when `route` is `THIRD_PARTY_TEST` the assessment deliberately leaves `verified_overall_score`, `decided_overall_score` and `grade` null, because nothing has yet been corroborated."
        Design: Corner/validations/conditional_validation_third_party_route_requires_a_completed_engagement
        """
        claim = self._submitted()

        validate_error(
            api_client.decide_assessment(
                claim.assessment_id, factories.decide_payload("APPROVED"), REVIEWER
            ),
            ApiErrorId.ERR_THIRD_PARTY_TEST_REQUIRED.value,
        )

        stored = validate_success(
            api_client.get_assessment(claim.assessment_id, ADMIN)
        )
        assert_score(
            stored["provisional_area_scores"]["DATA_PROTECTION"],
            60.00,
            "provisional DATA_PROTECTION",
        )
        assert_score(stored["provisional_overall_score"], 90.00, "provisional overall")
        assert stored["verified_overall_score"] is None, stored["verified_overall_score"]
        assert stored["decided_overall_score"] is None, stored["decided_overall_score"]
        assert stored["grade"] is None, stored["grade"]


class TestRegistryEntrySupportPeriodFloor:
    """The snapshot must clear the category minimum measured from the clock."""

    def test_a_support_period_short_of_the_minimum_is_refused(self):
        """Support to 2026-10-01 is under the 180-day floor, so no entry is created.

        PRD: "That snapshot must be far enough out: it has to fall at least the device category's `min_support_period_days` after the logical clock at the time of creation, or the entry is rejected with `ERR_SUPPORT_PERIOD_TOO_SHORT`."
        Design: Corner/validations/temporal_validation_support_period_shorter_than_the_category_minimum
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _flat_program()
        sponsor = _acme()
        product = _product(
            program,
            sponsor,
            model_name="Speaker Short",
            sku="SPK-002",
            declared_support_period_end="2026-10-01T00:00:00Z",
        )
        claim = _approved_claim(program, sponsor, product)
        grant = fixtures.issue_grant(claim)

        validate_error(
            api_client.create_registry_entry(
                grant.id, dict(REGISTRY_ENTRY), sponsor.headers
            ),
            ApiErrorId.ERR_SUPPORT_PERIOD_TOO_SHORT.value,
        )

        entries = validate_unpaginated(
            api_client.get_registry_entry(grant.id, sponsor.headers)
        )
        assert entries == [], entries
        assert_grant_statuses(grant.refresh(), "PENDING_REGISTRY", "DRAFT")

    def test_a_support_period_exactly_at_the_minimum_is_accepted(self):
        """Support ending exactly 180 days after the clock clears the floor.

        PRD: "`support_period_end` is not supplied — it is snapshotted from the product's `declared_support_period_end` at the moment the entry is created, freezing the support commitment the registry discloses even if the product's own declaration later moves."
        Design: Corner/validations/satisfaction_to_pass_support_period_exactly_at_the_category_minimum
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        boundary = plus_days(DEFAULT_CLOCK, 180)
        assert_instant_equals(boundary, "2027-01-28T00:00:00Z", "180-day boundary")
        program = _flat_program()
        sponsor = _acme()
        product = _product(
            program,
            sponsor,
            model_name="Speaker Boundary",
            sku="SPK-003",
            declared_support_period_end=boundary,
        )
        claim = _approved_claim(program, sponsor, product)
        grant = fixtures.issue_grant(claim)

        entry = validate_success(
            api_client.create_registry_entry(
                grant.id, dict(REGISTRY_ENTRY), sponsor.headers
            ),
            201,
        )

        assert_instant_equals(
            entry["support_period_end"], boundary, "support_period_end"
        )
        assert_status(entry, "disclosure_completeness", "COMPLETE")
        assert entry["published_at"] is None, entry["published_at"]
        assert entry["published_by_user_id"] is None, entry["published_by_user_id"]
        assert_grant_statuses(grant.refresh(), "PENDING_REGISTRY", "DRAFT")


class TestSupportPeriodLapsedAtExactlyTheClock:
    """The comparison is strict, so equality with the clock already counts as lapsed."""

    def test_a_support_period_ending_on_the_clock_blocks_issuance(self):
        """Support ending at exactly the current instant is not strictly after it.

        PRD: "The declared support period has not already ended — otherwise `ERR_SUPPORT_PERIOD_EXPIRED`."
        Design: Corner/validations/temporal_validation_support_period_expired_at_exactly_the_clock
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _flat_program()
        sponsor = _acme()
        product = _product(
            program,
            sponsor,
            model_name="Speaker Lapsed",
            sku="SPK-004",
            declared_support_period_end="2026-09-01T00:00:00Z",
        )
        claim = _approved_claim(program, sponsor, product)

        fixtures.set_clock("2026-09-01T00:00:00Z")

        validate_error(
            api_client.create_label_grant(
                factories.create_label_grant_payload(
                    claim.product_id, claim.assessment_id
                ),
                sponsor.headers,
            ),
            ApiErrorId.ERR_SUPPORT_PERIOD_EXPIRED.value,
        )

        stored = validate_success(
            api_client.get_assessment(claim.assessment_id, ADMIN)
        )
        assert_assessment_status(stored, "APPROVED")
        assert_status(sponsor.refresh(), "standing", "GOOD")
        grants, meta = validate_paginated(
            api_client.list_label_grants(ADMIN, params={"product_id": claim.product_id})
        )
        assert grants == [], grants
        assert_pagination_meta(meta, 10, 0, total_count=0)


class TestPublicationWithIncompleteDisclosure:
    """The registry entry is accepted; only the publication is refused."""

    def _pending(self):
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _flat_program()
        sponsor = _acme()
        product = _product(
            program,
            sponsor,
            model_name="Speaker Quiet",
            sku="SPK-005",
            update_policy_disclosed=False,
        )
        claim = _approved_claim(program, sponsor, product)
        grant = fixtures.issue_grant(claim)
        entry = validate_success(
            api_client.create_registry_entry(
                grant.id, dict(REGISTRY_ENTRY), sponsor.headers
            ),
            201,
        )
        return grant, entry

    def test_a_product_that_discloses_no_update_policy_cannot_be_published(self):
        """The publication is refused even though all three entry fields are supplied.

        PRD: "A decision of `PUBLISHED` is accepted when `registry_publication_status` is `DRAFT` or `WITHHELD`, and it requires a registry entry whose `disclosure_completeness` is `COMPLETE` *and* a parent product whose `update_policy_disclosed` is true — either failing yields `ERR_REGISTRY_DISCLOSURE_INCOMPLETE`."
        Design: Corner/validations/violation_to_error_publication_with_incomplete_disclosure
        """
        grant, _entry = self._pending()

        validate_error(
            api_client.decide_registry_publication(
                grant.id, factories.publication_payload("PUBLISHED"), PUBLISHER
            ),
            ApiErrorId.ERR_REGISTRY_DISCLOSURE_INCOMPLETE.value,
        )

        entries = validate_unpaginated(api_client.get_registry_entry(grant.id, ADMIN))
        assert len(entries) == 1, entries
        assert entries[0]["published_at"] is None, entries[0]["published_at"]
        stored = grant.refresh()
        assert_grant_statuses(stored, "PENDING_REGISTRY", "DRAFT")
        assert stored["valid_from"] is None, stored["valid_from"]
        assert stored["valid_until"] is None, stored["valid_until"]

    def test_the_scannable_code_still_resolves_to_nothing_in_public(self):
        """A code whose entry was never published is invisible to a shopper.

        PRD: "An unknown code and a real code whose entry is not currently published are deliberately indistinguishable to the public: both return `ERR_REGISTRY_CODE_NOT_FOUND`."
        Design: Corner/validations/violation_to_error_publication_with_incomplete_disclosure
        """
        grant, _entry = self._pending()

        validate_error(
            api_client.decide_registry_publication(
                grant.id, factories.publication_payload("PUBLISHED"), PUBLISHER
            ),
            ApiErrorId.ERR_REGISTRY_DISCLOSURE_INCOMPLETE.value,
        )

        validate_error(
            api_client.scan_registry(grant.scannable_code, CONSUMER_HEADERS),
            ApiErrorId.ERR_REGISTRY_CODE_NOT_FOUND.value,
        )


class TestDisplayAuthorizationNeedsTheEducationAck:
    """Every grant-side gate passes; the retailer never acknowledged."""

    def test_an_unacknowledged_retailer_cannot_authorise_a_display(self):
        """CornerShop skipped the education materials, so its display request is refused.

        PRD: "The acting retailer's `education_materials_ack` must be true, or `ERR_EDUCATION_ACK_REQUIRED`."
        Design: Corner/validations/violation_to_error_display_authorization_without_education_ack
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _flat_program()
        sponsor = _acme()
        product = _product(program, sponsor)
        claim = _approved_claim(program, sponsor, product)
        grant = fixtures.issue_grant(claim)
        fixtures.supply_registry_entry(grant, **REGISTRY_ENTRY)
        fixtures.decide_publication(grant, "PUBLISHED", PUBLISHER)
        store = fixtures.register_retailer(acknowledge=False, retailer_name="CornerShop")

        validate_error(
            api_client.create_display_authorization(
                factories.create_display_authorization_payload(
                    store.id,
                    grant.id,
                    "2026-09-01T00:00:00Z",
                    "2026-12-31T00:00:00Z",
                    channel="IN_STORE",
                ),
                store.headers,
            ),
            ApiErrorId.ERR_EDUCATION_ACK_REQUIRED.value,
        )

        retailer = store.refresh()
        assert retailer["education_materials_ack"] is False, retailer[
            "education_materials_ack"
        ]
        assert retailer["active_display_count"] == 0, retailer["active_display_count"]
        assert_status(retailer, "participation_tier", "BASELINE")
        rows, meta = validate_paginated(
            api_client.list_display_authorizations(
                ADMIN, params={"retailer_id": store.id}
            )
        )
        assert rows == [], rows
        assert_pagination_meta(meta, 10, 0, total_count=0)


class TestRenewalChecksGrantStateBeforeTheVersion:
    """A doubly faulty renewal: wrong predecessor state and a stale handle."""

    def test_the_grant_state_error_wins_over_the_stale_version_error(self):
        """A renewal against a PENDING_REGISTRY grant reports the state, not the version.

        PRD: "This rung deliberately sits after the parent's state precondition and before every business rule, so a caller holding a stale handle on an otherwise-valid parent learns about the staleness rather than about a downstream business failure."
        Design: Corner/validations/cascading_validation_grant_state_is_checked_before_the_stale_version
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _flat_program()
        sponsor = _acme()
        product = _product(program, sponsor)
        claim = _approved_claim(program, sponsor, product)
        grant = fixtures.issue_grant(claim)
        grant_version = grant.label_grant["version"]
        product_version = claim.refresh_product()["version"]
        assert product_version != grant_version, (
            "the renewal must echo a version the grant does not have, "
            f"but both read {grant_version}"
        )

        validate_error(
            api_client.create_renewal(
                grant.id,
                factories.renewal_payload(claim.assessment_id, product_version),
                sponsor.headers,
            ),
            ApiErrorId.ERR_INVALID_GRANT_STATE.value,
        )

        stored = grant.refresh()
        assert_grant_statuses(stored, "PENDING_REGISTRY", "DRAFT")
        assert_version_is(stored, grant_version)
        grants, meta = validate_paginated(
            api_client.list_label_grants(ADMIN, params={"product_id": claim.product_id})
        )
        assert_pagination_meta(meta, 10, 0, total_count=1)
        assert grants[0]["id"] == grant.id, grants


class TestOwnershipIsCheckedBeforeAssessmentState:
    """A rival manufacturer resubmits somebody else's DRAFT assessment."""

    def test_the_stranger_learns_nothing_about_the_assessment_state(self):
        """Both ownership and state are violated, so the ownership error is reported.

        PRD: "A request that breaks several rules at once must always report the *first* rule it breaks, reading the ladder below from top to bottom."
        Design: Corner/validations/priority_ordering_ownership_is_checked_before_assessment_state
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _flat_program()
        sponsor = _acme()
        rival = fixtures.enrol_manufacturer(
            legal_name="Rival Devices",
            contact_email="ops@rival.example",
            enterprise_class="SMALL",
            annual_us_revenue_cents=700000000,
        )
        product = _product(program, sponsor)
        assessment = fixtures.open_assessment(program, sponsor, product)

        validate_error(
            api_client.resubmit_assessment(
                assessment["id"],
                factories.resubmit_payload(resubmission_note="Taking this over"),
                rival.headers,
            ),
            ApiErrorId.ERR_OWNERSHIP_VIOLATION.value,
        )

        stored = validate_success(api_client.get_assessment(assessment["id"], ADMIN))
        assert_assessment_status(stored, "DRAFT")
        assert stored["deficiency_round"] == 0, stored["deficiency_round"]


class TestPenaltyPaymentBeforeAnyPenaltyExists:
    """A payment offered against a case that has never been adjudicated."""

    def test_paying_a_case_at_penalty_status_none_is_refused(self):
        """The ledger stays at zero because there is nothing to settle yet.

        PRD: "Payment requires `penalty_status` to be exactly `ASSESSED`; `NONE`, `PAID` and `VACATED` all reject the payment with `ERR_PENALTY_NOT_ASSESSED`, so a penalty cannot be paid twice and a vacated penalty cannot be paid at all."
        Design: Corner/validations/violation_to_error_penalty_payment_before_any_penalty_is_assessed
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        sponsor = _acme()
        case = fixtures.open_case(
            sponsor,
            reported_scannable_code="ZZ-NO-SUCH-CD005",
            violation_type="UNAUTHORIZED_DISPLAY",
            violation_line_items=[factories.violation_line("LST-9", "IN_STORE", 3)],
            reporter_note="Sticker seen on an unlabelled model",
        )

        validate_error(
            api_client.pay_penalty(
                case["id"],
                factories.penalty_payment_payload(payment_reference="PAY-EARLY-1"),
                sponsor.headers,
            ),
            ApiErrorId.ERR_PENALTY_NOT_ASSESSED.value,
        )

        stored = validate_success(api_client.get_enforcement_case(case["id"], ADMIN))
        assert_case_statuses(stored, "OPENED", "NONE")
        assert_money_cents(stored["penalty_cents"], 0, "penalty_cents")
        assert stored["payment_reference"] is None, stored["payment_reference"]
        assert_penalty_ledger(sponsor.refresh(), outstanding=0, paid=0)
        assert_status(sponsor.manufacturer, "standing", "GOOD")


class TestCaseOnALegitimatelyDisplayedCode:
    """The reported code belongs to an ACTIVE grant the retailer may display."""

    def test_a_compliant_display_cannot_be_turned_into_a_case(self):
        """An AUTHORIZED display covering the clock blocks the enforcement report.

        PRD: "A case may not be opened at all when the reported display was in fact legitimate: if the reported code resolves to a label grant whose `grant_status` is `ACTIVE` and there is an `AUTHORIZED` display authorization covering the reported retailer at the reported instant, the report is rejected with `ERR_LABEL_LEGITIMATELY_ISSUED`."
        Design: Corner/validations/violation_to_error_case_opened_on_a_legitimately_displayed_code
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _flat_program()
        sponsor = _acme()
        product = _product(program, sponsor)
        claim = _approved_claim(program, sponsor, product)
        grant = fixtures.issue_grant(claim)
        fixtures.supply_registry_entry(grant, **REGISTRY_ENTRY)
        fixtures.decide_publication(grant, "PUBLISHED", PUBLISHER)
        store = fixtures.register_retailer(retailer_name="MegaMart")
        authorization = validate_success(
            api_client.create_display_authorization(
                factories.create_display_authorization_payload(
                    store.id,
                    grant.id,
                    "2026-08-01T00:00:00Z",
                    "2026-12-31T00:00:00Z",
                    channel="ONLINE",
                ),
                store.headers,
            ),
            201,
        )

        validate_error(
            api_client.create_enforcement_case(
                factories.create_enforcement_case_payload(
                    sponsor.id,
                    grant.scannable_code,
                    "EXPIRED_LABEL_DISPLAY",
                    [factories.violation_line("LST-4", "ONLINE", 12)],
                    reported_retailer_id=store.id,
                    reporter_note="Complaint about this listing",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_LABEL_LEGITIMATELY_ISSUED.value,
        )

        stored_authorization = validate_success(
            api_client.get_display_authorization(authorization["id"], ADMIN)
        )
        assert_status(stored_authorization, "status", "AUTHORIZED")
        assert_status(grant.refresh(), "grant_status", "ACTIVE")
        cases, meta = validate_paginated(
            api_client.list_enforcement_cases(
                ADMIN, params={"subject_manufacturer_id": sponsor.id}
            )
        )
        assert cases == [], cases
        assert_pagination_meta(meta, 10, 0, total_count=0)
        assert_status(sponsor.refresh(), "standing", "GOOD")
        assert_money_cents(
            sponsor.manufacturer["total_assessed_penalty_cents"],
            0,
            "total_assessed_penalty_cents",
        )


class TestGrantRequestAgainstAStaleAssessment:
    """A spec change lands between approval and the label request."""

    def test_a_label_may_not_rest_on_a_claim_the_spec_change_outdated(self):
        """The approved assessment describes firmware 1.0.0, so the grant is refused.

        PRD: "The assessment does not predate a spec change — otherwise `ERR_ASSESSMENT_SPEC_STALE`."
        Design: Corner/validations/violation_to_error_grant_request_against_a_stale_assessment_spec
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _flat_program()
        sponsor = _acme()
        product = _product(program, sponsor)
        claim = _approved_claim(program, sponsor, product)
        current_version = claim.refresh_product()["version"]

        validate_success(
            api_client.create_spec_change(
                claim.product_id,
                factories.spec_change_payload(
                    current_version,
                    change_summary="Bluetooth stack rewritten",
                    firmware_version="1.1.0",
                ),
                sponsor.headers,
            ),
            201,
        )

        validate_error(
            api_client.create_label_grant(
                factories.create_label_grant_payload(
                    claim.product_id, claim.assessment_id
                ),
                sponsor.headers,
            ),
            ApiErrorId.ERR_ASSESSMENT_SPEC_STALE.value,
        )

        stored_product = claim.refresh_product()
        assert stored_product["spec_revision"] == 2, stored_product["spec_revision"]
        assert_status(stored_product, "conformance_currency", "STALE")
        stored_assessment = validate_success(
            api_client.get_assessment(claim.assessment_id, ADMIN)
        )
        assert stored_assessment["assessed_spec_revision"] == 1, stored_assessment[
            "assessed_spec_revision"
        ]
        assert_assessment_status(stored_assessment, "APPROVED")
        grants, meta = validate_paginated(
            api_client.list_label_grants(ADMIN, params={"product_id": claim.product_id})
        )
        assert grants == [], grants
        assert_pagination_meta(meta, 10, 0, total_count=0)


class TestSecondWithdrawOnAWithdrawnAuthorization:
    """WITHDRAWN is terminal, so the repeat must not double-count anything."""

    def test_the_repeat_withdrawal_is_refused_and_the_count_stays_at_zero(self):
        """A second withdraw hits a terminal status and leaves the first one intact.

        PRD: "`WITHDRAWN` and `EXPIRED` are both terminal, and a withdrawal aimed at an authorization already in either is rejected with `ERR_INVALID_AUTHORIZATION_STATE`."
        Design: Corner/validations/violation_to_error_second_withdraw_on_a_withdrawn_authorization
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _flat_program()
        sponsor = _acme()
        product = _product(program, sponsor)
        claim = _approved_claim(program, sponsor, product)
        grant = fixtures.issue_grant(claim)
        fixtures.supply_registry_entry(grant, **REGISTRY_ENTRY)
        fixtures.decide_publication(grant, "PUBLISHED", PUBLISHER)
        store = fixtures.register_retailer(retailer_name="MegaMart")
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
        withdrawn = validate_success(
            api_client.withdraw_display_authorization(
                authorization["id"],
                factories.withdraw_authorization_payload(
                    withdrawal_reason="RETAILER_REQUEST"
                ),
                store.headers,
            ),
            201,
        )
        assert_status(withdrawn, "status", "WITHDRAWN")

        validate_error(
            api_client.withdraw_display_authorization(
                authorization["id"],
                factories.withdraw_authorization_payload(
                    withdrawal_reason="RETAILER_REQUEST"
                ),
                store.headers,
            ),
            ApiErrorId.ERR_INVALID_AUTHORIZATION_STATE.value,
        )

        stored = validate_success(
            api_client.get_display_authorization(authorization["id"], ADMIN)
        )
        assert_status(stored, "status", "WITHDRAWN")
        assert_status(stored, "withdrawal_reason", "RETAILER_REQUEST")
        retailer = store.refresh()
        assert retailer["active_display_count"] == 0, retailer["active_display_count"]
        assert_status(retailer, "participation_tier", "BASELINE")
