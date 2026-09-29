"""Complexity-layer corners: optimistic concurrency, derived-field reconciliation and bulk writes.

Each test pins one behaviour the PRD derives uniquely, on a world built from the
Stage 1 fixtures with the tier, catalogue and category calibrated explicitly.
"""
from test_helpers import (
    ADMIN,
    ADMIN_2_USER_ID,
    ADMIN_3_USER_ID,
    ADMIN_USER_ID,
    ApiErrorId,
    api_client,
    assert_case_statuses,
    assert_grant_statuses,
    assert_money_cents,
    assert_pagination_meta,
    assert_penalty_ledger,
    assert_score,
    assert_status,
    assert_version_is,
    factories,
    fixtures,
    make_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

DESIGN_CRITERIA = [
    {"criterion_code": "AUTH-1", "practice_area": "AUTHENTICATION", "weight": 10,
     "requires_lab_verification": False, "criterion_text": "Unique per-device credentials"},
    {"criterion_code": "UPD-1", "practice_area": "SOFTWARE_UPDATE", "weight": 10,
     "requires_lab_verification": False, "criterion_text": "Signed firmware updates"},
    {"criterion_code": "DAT-1", "practice_area": "DATA_PROTECTION", "weight": 10,
     "requires_lab_verification": False, "criterion_text": "Encryption of data at rest"},
    {"criterion_code": "VLN-1", "practice_area": "VULN_DISCLOSURE", "weight": 10,
     "requires_lab_verification": False, "criterion_text": "Published disclosure contact"},
]
CRITERION_CODES = ["AUTH-1", "UPD-1", "DAT-1", "VLN-1"]
PRACTICE_AREAS_IN_ORDER = [
    "AUTHENTICATION",
    "SOFTWARE_UPDATE",
    "DATA_PROTECTION",
    "VULN_DISCLOSURE",
]
PRODUCT = {"model_name": "Speaker One", "sku": "SPK-001", "firmware_version": "1.0.0",
           "declared_support_period_end": "2029-08-01T00:00:00Z",
           "update_policy_disclosed": True, "retail_units_shipped": 1000}
REGISTRY_CONTENT = {"update_policy_url": "https://acme.example/updates",
                    "update_cadence": "AUTOMATIC",
                    "vuln_disclosure_contact": "security@acme.example"}
RENEWAL_FEE_CENTS = 57200  # subtotal 40000 + 12000 selects the 0.10 band, 5200 surcharge
ONLINE_SIX_UNIT_PENALTY_CENTS = 34020  # 4200 x 6 units x 1.00 x 1.35
IN_STORE_FOUR_UNIT_AGGRAVATED_CENTS = 24150  # 4200 x 4 units x 1.25 x 1.15
NOTICE_ADMIN_1 = make_admin_headers(ADMIN_USER_ID)
ADJUDICATE_ADMIN_2 = make_admin_headers(ADMIN_2_USER_ID)
VACATE_ADMIN_3 = make_admin_headers(ADMIN_3_USER_ID)


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


class TestStaleProductVersionOnAssessmentOpen:
    """A spec change moves the product on, so the version the client last read is dead."""

    def _changed_product(self):
        fixtures.reset_clock()
        program = design_program()
        sponsor = design_sponsor()
        product = fixtures.register_product(program, sponsor, **PRODUCT)
        validate_success(
            api_client.create_spec_change(
                product["id"],
                factories.spec_change_payload(
                    product["version"],
                    change_summary="Firmware hardening release",
                    firmware_version="1.1.0",
                ),
                sponsor.headers,
            ),
            201,
        )
        fresh = validate_success(api_client.get_product(product["id"], sponsor.headers))
        assert fresh["version"] == product["version"] + 1
        return program, sponsor, product, fresh

    def test_open_replayed_with_the_pre_change_version_is_rejected(self):
        """The stale expectation returns 412 and persists no assessment at all.

        PRD: "If the product's `version` has advanced since the client last read it, the create is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412)."
        Design: Corner/complexity_layers/occ_stale_product_version_rejects_the_assessment_open_then_accepts_the_fresh_one
        """
        _program, sponsor, stale_product, _fresh = self._changed_product()

        validate_error(
            api_client.create_assessment(
                stale_product["id"],
                factories.open_assessment_payload(stale_product["version"]),
                sponsor.headers,
            ),
            ApiErrorId.ERR_STALE_PRODUCT_VERSION.value,
        )

        _items, meta = validate_paginated(
            api_client.list_assessments(sponsor.headers, {"product_id": stale_product["id"]})
        )
        assert meta["total_count"] == 0

    def test_open_carrying_the_fresh_version_snapshots_the_new_spec_revision(self):
        """The same call with the observed version is accepted and snapshots revision 2.

        PRD: "The new assessment records the `product_id` it belongs to, copies the `required_route` of the product's device category's program tier into its own `route` — so `route` reads either `SELF_ATTESTATION` or `THIRD_PARTY_TEST` — snapshots the product's current `spec_revision` into `assessed_spec_revision`, sets `status` to `DRAFT` and `deficiency_round` to 0, and increments the product's `version` by one."
        Design: Corner/complexity_layers/occ_stale_product_version_rejects_the_assessment_open_then_accepts_the_fresh_one
        """
        _program, sponsor, _stale_product, fresh = self._changed_product()

        assessment = validate_success(
            api_client.create_assessment(
                fresh["id"],
                factories.open_assessment_payload(fresh["version"]),
                sponsor.headers,
            ),
            201,
        )
        assert_status(assessment, "status", "DRAFT")
        assert_status(assessment, "route", "SELF_ATTESTATION")
        assert assessment["deficiency_round"] == 0
        assert assessment["assessed_spec_revision"] == 2

    def test_only_the_accepted_open_moved_the_product_row(self):
        """The rejected replay bumped nothing and neither open touched the currency dimension.

        PRD: "When more than one condition is violated by a single request, the identifier returned is the one belonging to the highest-priority rung of the rejection ladder in §2.6, and the request has no partial effect: a rejected request writes nothing, mutates no derived quantity and advances no state machine."
        Design: Corner/complexity_layers/occ_stale_product_version_rejects_the_assessment_open_then_accepts_the_fresh_one
        """
        _program, sponsor, stale_product, fresh = self._changed_product()

        validate_error(
            api_client.create_assessment(
                stale_product["id"],
                factories.open_assessment_payload(stale_product["version"]),
                sponsor.headers,
            ),
            ApiErrorId.ERR_STALE_PRODUCT_VERSION.value,
        )
        validate_success(
            api_client.create_assessment(
                fresh["id"],
                factories.open_assessment_payload(fresh["version"]),
                sponsor.headers,
            ),
            201,
        )

        after = validate_success(api_client.get_product(fresh["id"], sponsor.headers))
        assert_version_is(after, 3)
        assert after["spec_revision"] == 2
        assert_status(after, "conformance_currency", "STALE")


class TestStaleGrantVersionOnRenewal:
    """A renewal must carry the version of the predecessor the client actually observed."""

    def _published(self):
        fixtures.reset_clock()
        claim = fixtures.approved_claim(
            program=design_program(), sponsor=design_sponsor(), product_overrides=dict(PRODUCT)
        )
        grant = fixtures.published_grant(claim, **REGISTRY_CONTENT)
        observed = validate_success(
            api_client.get_label_grant(grant.id, claim.sponsor.headers)
        )
        return claim, grant, observed

    def test_renewal_carrying_the_previous_version_is_rejected(self):
        """One version behind returns 412 and leaves the predecessor live and unsuperseded.

        PRD: "If the predecessor's `version` has advanced since the client last read it, the renewal is rejected with `ERR_STALE_GRANT_VERSION` (HTTP 412)."
        Design: Corner/complexity_layers/occ_stale_grant_version_rejects_the_renewal_of_an_active_grant
        """
        claim, grant, observed = self._published()

        validate_error(
            api_client.create_renewal(
                grant.id,
                factories.renewal_payload(claim.assessment_id, observed["version"] - 1),
                claim.sponsor.headers,
            ),
            ApiErrorId.ERR_STALE_GRANT_VERSION.value,
        )

        items, meta = validate_paginated(
            api_client.list_label_grants(claim.sponsor.headers, {"product_id": claim.product_id})
        )
        assert meta["total_count"] == 1
        assert_grant_statuses(items[0], "ACTIVE", "PUBLISHED")
        assert items[0]["superseded_by_grant_id"] is None

    def test_renewal_carrying_the_observed_version_mints_the_next_generation(self):
        """The fresh version is accepted and the new grant carries the renewal fee.

        PRD: "A successful renewal creates a *new* grant whose `renewal_generation` is the predecessor's `renewal_generation` plus one, starting at `PENDING_REGISTRY` and `DRAFT` exactly like an original issuance, with its own freshly minted `scannable_code` and its own `issuance_fee_cents` computed from the incremented generation — so each successive renewal costs one more 12000-cent supplement and may cross into a higher surcharge band."
        Design: Corner/complexity_layers/occ_stale_grant_version_rejects_the_renewal_of_an_active_grant
        """
        claim, grant, observed = self._published()

        renewal = validate_success(
            api_client.create_renewal(
                grant.id,
                factories.renewal_payload(claim.assessment_id, observed["version"]),
                claim.sponsor.headers,
            ),
            201,
        )
        assert renewal["renewal_generation"] == 1
        assert_grant_statuses(renewal, "PENDING_REGISTRY", "DRAFT")
        assert_money_cents(renewal["issuance_fee_cents"], RENEWAL_FEE_CENTS, "issuance_fee_cents")
        assert renewal["valid_from"] is None
        assert renewal["valid_until"] is None
        assert renewal["scannable_code"] != observed["scannable_code"]

    def test_the_accepted_renewal_retires_the_predecessor(self):
        """The predecessor is revoked, points at its successor and bumps its own version.

        PRD: "The predecessor is retired in the same operation: whether it was `ACTIVE` or `SUSPENDED`, it moves to `REVOKED`, its `superseded_by_grant_id` is set to the new grant's identifier, and its `version` increments."
        Design: Corner/complexity_layers/occ_stale_grant_version_rejects_the_renewal_of_an_active_grant
        """
        claim, grant, observed = self._published()

        renewal = validate_success(
            api_client.create_renewal(
                grant.id,
                factories.renewal_payload(claim.assessment_id, observed["version"]),
                claim.sponsor.headers,
            ),
            201,
        )

        predecessor = validate_success(
            api_client.get_label_grant(grant.id, claim.sponsor.headers)
        )
        assert_status(predecessor, "grant_status", "REVOKED")
        assert predecessor["superseded_by_grant_id"] == renewal["id"]
        assert_version_is(predecessor, observed["version"] + 1)


class TestProductVersionIncrementsOnEveryWrite:
    """Every accepted write moves the OCC counter, even when no product field changed."""

    def _product(self):
        fixtures.reset_clock()
        program = design_program()
        sponsor = design_sponsor()
        return sponsor, fixtures.register_product(program, sponsor, **PRODUCT)

    def test_each_accepted_open_bumps_the_version_while_the_spec_revision_stands_still(self):
        """Two opens walk the version 1 to 2 to 3 with `spec_revision` fixed at 1.

        PRD: "`version` (integer): a counter that begins at 1 and increments by one on every accepted mutation of the row."
        Design: Corner/complexity_layers/occ_product_version_increments_on_every_write_and_the_prior_value_stops_working
        """
        sponsor, product = self._product()
        assert_version_is(product, 1)

        validate_success(
            api_client.create_assessment(
                product["id"], factories.open_assessment_payload(1), sponsor.headers
            ),
            201,
        )
        after_first = validate_success(api_client.get_product(product["id"], sponsor.headers))
        assert_version_is(after_first, 2)
        assert after_first["spec_revision"] == 1

        validate_success(
            api_client.create_assessment(
                product["id"], factories.open_assessment_payload(2), sponsor.headers
            ),
            201,
        )
        after_second = validate_success(api_client.get_product(product["id"], sponsor.headers))
        assert_version_is(after_second, 3)
        assert after_second["spec_revision"] == 1

    def test_replaying_a_consumed_version_is_rejected_and_bumps_nothing(self):
        """Version 2 works once; the replay after the second open returns 412.

        PRD: "If the product's `version` has advanced since the client last read it, the create is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412)."
        Design: Corner/complexity_layers/occ_product_version_increments_on_every_write_and_the_prior_value_stops_working
        """
        sponsor, product = self._product()

        validate_success(
            api_client.create_assessment(
                product["id"], factories.open_assessment_payload(1), sponsor.headers
            ),
            201,
        )
        validate_success(
            api_client.create_assessment(
                product["id"], factories.open_assessment_payload(2), sponsor.headers
            ),
            201,
        )
        validate_error(
            api_client.create_assessment(
                product["id"], factories.open_assessment_payload(2), sponsor.headers
            ),
            ApiErrorId.ERR_STALE_PRODUCT_VERSION.value,
        )

        after = validate_success(api_client.get_product(product["id"], sponsor.headers))
        assert_version_is(after, 3)
        assert after["spec_revision"] == 1

    def test_the_first_draft_is_superseded_by_the_second_open(self):
        """The earlier DRAFT moves to SUPERSEDED and names its successor.

        PRD: "If an existing assessment of the same product has a `status` of `DRAFT`, `UNDER_REVIEW` or `DEFICIENT`, that older assessment moves to `SUPERSEDED` and its `superseded_by_assessment_id` is set to the new assessment's identifier."
        Design: Corner/complexity_layers/occ_product_version_increments_on_every_write_and_the_prior_value_stops_working
        """
        sponsor, product = self._product()

        first = validate_success(
            api_client.create_assessment(
                product["id"], factories.open_assessment_payload(1), sponsor.headers
            ),
            201,
        )
        second = validate_success(
            api_client.create_assessment(
                product["id"], factories.open_assessment_payload(2), sponsor.headers
            ),
            201,
        )

        superseded = validate_success(api_client.get_assessment(first["id"], sponsor.headers))
        assert_status(superseded, "status", "SUPERSEDED")
        assert superseded["superseded_by_assessment_id"] == second["id"]

        successor = validate_success(api_client.get_assessment(second["id"], sponsor.headers))
        assert_status(successor, "status", "DRAFT")
        assert successor["assessed_spec_revision"] == 1


class TestPenaltyLedgerReconciliation:
    """The five derived ledger fields stay reconciled across assessment, payment and vacate."""

    def _two_cases(self):
        fixtures.reset_clock()
        sponsor = design_sponsor()
        case_one = fixtures.open_case(
            sponsor,
            reported_scannable_code="ZZ-NO-SUCH-CD009",
            violation_type="UNAUTHORIZED_DISPLAY",
            violation_line_items=[factories.violation_line("LST-21", "ONLINE", 6)],
            reporter_note="Label artwork on a marketplace listing",
        )
        fixtures.issue_notice(case_one, headers=NOTICE_ADMIN_1, notice_reference="NOT-2026-0021")
        fixtures.adjudicate(case_one, "UPHELD", headers=ADJUDICATE_ADMIN_2)
        case_two = fixtures.open_case(
            sponsor,
            reported_scannable_code="ZZ-NO-SUCH-CD010",
            violation_type="UNAUTHORIZED_DISPLAY",
            violation_line_items=[factories.violation_line("LST-22", "IN_STORE", 4)],
            reporter_note="Shelf talker carrying the program label",
        )
        fixtures.issue_notice(case_two, headers=NOTICE_ADMIN_1, notice_reference="NOT-2026-0022")
        return sponsor, case_one, case_two

    def _subject(self, sponsor):
        return validate_success(api_client.get_manufacturer(sponsor.id, ADMIN))

    def test_the_first_upheld_case_makes_the_subject_delinquent(self):
        """34020 outstanding crosses the 25000 threshold with one upheld case.

        PRD: "Then `standing` is derived in this fixed order: a manufacturer whose `upheld_case_count` is 3 or more is `BARRED`; failing that, a manufacturer whose `outstanding_penalty_cents` is 25000 or more is `DELINQUENT`; every other manufacturer is `GOOD`."
        Design: Corner/complexity_layers/derived_field_reconciliation_penalty_ledger_after_assessment_payment_and_vacate
        """
        sponsor, _case_one, _case_two = self._two_cases()

        subject = self._subject(sponsor)
        assert_penalty_ledger(
            subject, outstanding=ONLINE_SIX_UNIT_PENALTY_CENTS, paid=0, vacated=0
        )
        assert_money_cents(
            subject["total_assessed_penalty_cents"],
            ONLINE_SIX_UNIT_PENALTY_CENTS,
            "total_assessed_penalty_cents",
        )
        assert subject["upheld_case_count"] == 1
        assert_status(subject, "standing", "DELINQUENT")

    def test_payment_moves_the_amount_from_outstanding_to_paid(self):
        """The total is unchanged, the standing recovers and the case reads PAID.

        PRD: "Payment moves `penalty_status` from `ASSESSED` to `PAID`, which moves the amount out of `outstanding_penalty_cents` and into `paid_penalty_cents` with `total_assessed_penalty_cents` unchanged, and re-derives `standing`."
        Design: Corner/complexity_layers/derived_field_reconciliation_penalty_ledger_after_assessment_payment_and_vacate
        """
        sponsor, case_one, _case_two = self._two_cases()

        fixtures.pay_penalty(case_one, sponsor, payment_reference="PAY-2026-0021")

        subject = self._subject(sponsor)
        assert_penalty_ledger(
            subject, outstanding=0, paid=ONLINE_SIX_UNIT_PENALTY_CENTS, vacated=0
        )
        assert_money_cents(
            subject["total_assessed_penalty_cents"],
            ONLINE_SIX_UNIT_PENALTY_CENTS,
            "total_assessed_penalty_cents",
        )
        assert subject["upheld_case_count"] == 1
        assert_status(subject, "standing", "GOOD")

        settled = validate_success(api_client.get_enforcement_case(case_one["id"], ADMIN))
        assert_case_statuses(settled, "ADJUDICATED_UPHELD", "PAID")
        assert settled["payment_reference"] == "PAY-2026-0021"

    def test_the_second_adjudication_reads_the_count_before_it_increments(self):
        """One prior upheld case carries 1.25, so the second penalty is 24150.

        PRD: "A first-time offender therefore carries a multiplier of exactly 1.00, a subject with one prior upheld case carries 1.25, two priors 1.50, three priors 1.75, four priors 2.00, and every subject beyond that stays at the 2.00 cap."
        Design: Corner/complexity_layers/derived_field_reconciliation_penalty_ledger_after_assessment_payment_and_vacate
        """
        sponsor, case_one, case_two = self._two_cases()
        fixtures.pay_penalty(case_one, sponsor, payment_reference="PAY-2026-0021")

        upheld = validate_success(
            api_client.adjudicate_case(
                case_two["id"], factories.adjudicate_payload("UPHELD"), ADJUDICATE_ADMIN_2
            ),
            201,
        )
        assert_score(upheld["aggravation_multiplier"], 1.25, "aggravation_multiplier")
        assert_money_cents(
            upheld["penalty_cents"], IN_STORE_FOUR_UNIT_AGGRAVATED_CENTS, "penalty_cents"
        )

        subject = self._subject(sponsor)
        assert_penalty_ledger(
            subject,
            outstanding=IN_STORE_FOUR_UNIT_AGGRAVATED_CENTS,
            paid=ONLINE_SIX_UNIT_PENALTY_CENTS,
            vacated=0,
        )
        assert_money_cents(
            subject["total_assessed_penalty_cents"],
            ONLINE_SIX_UNIT_PENALTY_CENTS + IN_STORE_FOUR_UNIT_AGGRAVATED_CENTS,
            "total_assessed_penalty_cents",
        )
        assert subject["upheld_case_count"] == 2
        assert_status(subject, "standing", "GOOD")

    def test_vacating_the_second_case_moves_the_amount_into_vacated(self):
        """The vacate drops the upheld count back to one and leaves the total alone.

        PRD: "Because those figures moved, `upheld_case_count` drops by one (the case is no longer `ADJUDICATED_UPHELD`) and `standing` is re-derived, returning to `GOOD` when `outstanding_penalty_cents` is below 25000 and `upheld_case_count` is below 3."
        Design: Corner/complexity_layers/derived_field_reconciliation_penalty_ledger_after_assessment_payment_and_vacate
        """
        sponsor, case_one, case_two = self._two_cases()
        fixtures.pay_penalty(case_one, sponsor, payment_reference="PAY-2026-0021")
        fixtures.adjudicate(case_two, "UPHELD", headers=ADJUDICATE_ADMIN_2)

        fixtures.vacate(case_two, headers=VACATE_ADMIN_3, vacate_reason="Evidence retracted on appeal")

        subject = self._subject(sponsor)
        assert_penalty_ledger(
            subject,
            outstanding=0,
            paid=ONLINE_SIX_UNIT_PENALTY_CENTS,
            vacated=IN_STORE_FOUR_UNIT_AGGRAVATED_CENTS,
        )
        assert_money_cents(
            subject["total_assessed_penalty_cents"],
            ONLINE_SIX_UNIT_PENALTY_CENTS + IN_STORE_FOUR_UNIT_AGGRAVATED_CENTS,
            "total_assessed_penalty_cents",
        )
        assert subject["upheld_case_count"] == 1
        assert_status(subject, "standing", "GOOD")

        vacated = validate_success(api_client.get_enforcement_case(case_two["id"], ADMIN))
        assert_case_statuses(vacated, "VACATED", "VACATED")


class TestBulkCriterionResponseBatch:
    """One batch of four resolvable elements is written whole and scores whole."""

    def _draft(self):
        fixtures.reset_clock()
        program = design_program()
        sponsor = design_sponsor()
        product = fixtures.register_product(program, sponsor, **PRODUCT)
        assessment = fixtures.open_assessment(program, sponsor, product)
        return program, sponsor, assessment

    def _batch(self, program):
        return factories.criterion_responses_payload(
            [
                factories.response_item(program.criterion_id(code), True, evidence_ref=f"EV-{code}")
                for code in CRITERION_CODES
            ]
        )

    def test_the_batch_returns_four_rows_in_the_submitted_order(self):
        """Every element is stored against the assessment and starts unverified.

        PRD: "Two derived fields start at their initial values and stay there until a laboratory reports: `lab_result` is `NOT_TESTED` — the other permitted values being `PASS` and `FAIL` — and `lab_verified` is false, becoming true precisely when `lab_result` is either `PASS` or `FAIL`."
        Design: Corner/complexity_layers/bulk_operations_all_four_criterion_responses_succeed_in_one_batch
        """
        program, sponsor, assessment = self._draft()

        rows = validate_success(
            api_client.create_criterion_responses(
                assessment["id"], self._batch(program), sponsor.headers
            ),
            201,
        )
        assert isinstance(rows, list)
        assert len(rows) == 4
        assert rows[0]["criterion_id"] == program.criterion_id("AUTH-1")
        assert rows[3]["criterion_id"] == program.criterion_id("VLN-1")
        for row in rows:
            assert row["assessment_id"] == assessment["id"]
            assert_status(row, "lab_result", "NOT_TESTED")
            assert row["lab_verified"] is False

    def test_the_stored_batch_lists_as_exactly_four_responses(self):
        """The list read confirms four rows matched the filter and no page remains.

        PRD: "Each stored response records the `assessment_id` it belongs to alongside those fields, and at most one response may exist per pairing of `assessment_id` with `criterion_id`."
        Design: Corner/complexity_layers/bulk_operations_all_four_criterion_responses_succeed_in_one_batch
        """
        program, sponsor, assessment = self._draft()
        validate_success(
            api_client.create_criterion_responses(
                assessment["id"], self._batch(program), sponsor.headers
            ),
            201,
        )

        items, meta = validate_paginated(
            api_client.list_criterion_responses(
                sponsor.headers, {"assessment_id": assessment["id"]}
            )
        )
        assert len(items) == 4
        assert_pagination_meta(meta, 10, 0, total_count=4, has_more=False)

    def test_the_following_submit_scores_all_four_areas_at_once(self):
        """Four conformant self-declarable criteria score 100.00 in every area.

        PRD: "A successful submission stamps `submitted_at` from the logical clock and runs the provisional scoring pass of §3.4, writing `provisional_area_scores`, `provisional_overall_score`, `decided_min_area_score` and `gate_applied`."
        Design: Corner/complexity_layers/bulk_operations_all_four_criterion_responses_succeed_in_one_batch
        """
        program, sponsor, assessment = self._draft()
        validate_success(
            api_client.create_criterion_responses(
                assessment["id"], self._batch(program), sponsor.headers
            ),
            201,
        )

        submitted = validate_success(
            api_client.submit_assessment(assessment["id"], sponsor.headers), 201
        )
        assert_status(submitted, "status", "UNDER_REVIEW")
        assert_score(submitted["provisional_overall_score"], 100.00, "provisional_overall_score")
        for area in PRACTICE_AREAS_IN_ORDER:
            assert_score(submitted["provisional_area_scores"][area], 100.00, area)
