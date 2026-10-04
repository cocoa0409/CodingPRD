"""Application submission, risk scoring variants, debt-to-income, and the
verification lifecycle (instant checks, manual review, segregation of duties)."""
from test_helpers import (
    ApiErrorId,
    create_active_model,
    create_applicant,
    create_applicant_payload,
    fail_income_instant_check,
    get_success_data,
    get_verifications,
    manual_pass_verification,
    pass_all_instant_checks,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInitialBranch:

    def test_high_score_enters_verification_pending_with_two_pending_verifications(
        self, api, platform_admin_headers, verification_officer_headers
    ):
        """PRD 3.4: "Otherwise the application moves to `VERIFICATION_PENDING` and two `Verification` rows are created beneath it - one of `kind` `INCOME`, one of `kind` `IDENTITY`, both in `PENDING` status."

        Design: Corner/state_machines/application_created_in_submitted_or_declined_initial_branch
        """
        create_active_model(model_code="ADU-S-2A")
        applicant = create_applicant(full_name="High Hannah")
        app = submit_application(applicant["id"])
        assert app["status"] == "VERIFICATION_PENDING"
        # bureau 575 -> round_half_up(600 * 275 / 550) == 300, outside the
        # floor-reject band (score < 300).
        assert app["risk_score"] == 300

        data, meta = validate_paginated(
            api.list_verifications(app["id"], verification_officer_headers)
        )
        assert meta["total_count"] == 2
        kinds = sorted(v["kind"] for v in data)
        assert kinds == ["IDENTITY", "INCOME"]
        assert all(v["status"] == "PENDING" for v in data)

    def test_floor_reject_branch_declines_at_submission_with_no_verifications(
        self, api, platform_admin_headers, verification_officer_headers
    ):
        """PRD 3.4: "If the clamped `risk_score` is at least the model's `score_floor` but below 300, the application transitions directly from `SUBMITTED` to `DECLINED` and no verification rows are created at all."

        Design: Corner/state_machines/application_created_in_submitted_or_declined_initial_branch
        """
        create_active_model(model_code="ADU-S-2B")
        # bureau 300 -> score 0 under the bureau-only model; 0 is at least the
        # score_floor of 0 and below 300, so the floor-reject branch fires.
        applicant = create_applicant(full_name="Low Lou", bureau_score=300)
        app = submit_application(applicant["id"])
        assert app["status"] == "DECLINED"
        assert app["risk_score"] == 0

        data, meta = validate_paginated(
            api.list_verifications(app["id"], verification_officer_headers)
        )
        assert meta["total_count"] == 0


class TestScoringVariant:

    def test_cashflow_stress_multiplier_lowers_cashflow_contribution(
        self, api, platform_admin_headers
    ):
        """PRD 3.5: 'When the model's variable list contains at least one variable whose name begins with the cash-flow prefix "bank_account", a stress multiplier of 0.9 is applied to the cash-flow variables' contributions only - bureau, education, and employment contributions are untouched - before summing'

        Design: Difficulty/dual_variant_calc/risk_score_cashflow_stress_multiplier_changes_score
        """
        variables = [
            {"name": "bureau_score", "weight": 6, "min": 300, "max": 850},
            {"name": "bank_account_avg_balance_cents", "weight": 1, "min": 0, "max": 1000000},
        ]
        model = create_active_model(model_code="ADU-CF-1", variables=variables)
        # bureau 575 -> 600*275/550 = 300; avg balance 500000 -> 100 * 0.5 * 0.9 = 45.
        applicant = create_applicant(full_name="Casey Stress")
        app = submit_application(applicant["id"])
        assert app["risk_score"] == 345, (
            "bureau contributes 300, stressed cash-flow contributes 45; total 345"
        )
        assert app["risk_score"] != 350, "the unstressed total must not be stored"
        assert app["model_version_id"] == model["id"]

    def test_bureau_only_model_applies_no_stress_multiplier(
        self, api, platform_admin_headers
    ):
        """PRD 3.5: "when no such variable is present, no stress multiplier applies and the raw weighted sum stands."
        PRD 3.5: "The final score is the running total rounded half up to an integer, then clamped so it never falls below the model's `score_floor` nor exceeds its `score_ceiling`; clamping happens after rounding."

        Design: Difficulty/dual_variant_calc/risk_score_cashflow_stress_multiplier_changes_score
        """
        create_active_model(model_code="ADU-CF-2")
        applicant = create_applicant(full_name="Bureau Only Bob")
        app = submit_application(applicant["id"])
        # bureau 575 -> round_half_up(600 * (575 - 300) / 550) == 300
        assert app["risk_score"] == 300


class TestComputedFields:

    def test_client_supplied_computed_fields_are_ignored(
        self, api, platform_admin_headers
    ):
        """PRD 3.4: "On acceptance the application snapshots that active model's identity into `model_version_id`, computes the applicant's `risk_score` (section 3.5) and `debt_to_income_pct` at submission, and starts in `SUBMITTED` before the system immediately walks the verification branch."

        Design: Corner/entities/application_computed_score_ignores_client_supplied_risk_score_input_ignored
        """
        create_active_model(model_code="ADU-E-4")
        applicant = create_applicant(full_name="Smuggle Sam")
        resp = api.create_application(
            {
                "applicant_id": applicant["id"],
                "channel": "DIRECT",
                "requested_amount_cents": 5000000,
                "risk_score": 999,
                "status": "APPROVED",
            },
            platform_admin_headers,
        )
        app = validate_success(resp, expected_status=201)
        assert app["risk_score"] == 300, "server-computed score, not the smuggled 999"
        assert app["status"] == "VERIFICATION_PENDING", "initial branch, not the smuggled APPROVED"
        assert app["debt_to_income_pct"] == 20.0


class TestDebtToIncome:

    def test_zero_income_returns_100_percent(self, api, platform_admin_headers):
        """PRD 3.4: "if that monthly income is zero or negative the percentage is 100.0"

        Design: Corner/calculations/debt_to_income_zero_income_returns_100
        """
        create_active_model(model_code="ADU-C-3")
        applicant = create_applicant(
            full_name="Zero Zoe", annual_income_cents=0, employment_status="UNEMPLOYED"
        )
        app = submit_application(applicant["id"])
        assert app["debt_to_income_pct"] == 100.0

    def test_debt_to_income_rounds_half_up_to_two_decimals(
        self, api, platform_admin_headers
    ):
        """PRD 3.4: "otherwise it is one hundred times `monthly_debt_payments_cents` divided by monthly income, rounded half up to two decimal places."

        Design: Corner/calculations/debt_to_income_zero_income_returns_100
        """
        create_active_model(model_code="ADU-C-3B")
        applicant = create_applicant(
            full_name="Half Cent Hal",
            annual_income_cents=12000000,   # monthly income 1000000
            monthly_debt_payments_cents=200005,  # 100 * 200005 / 1000000 = 20.0005 -> 20.0
        )
        app = submit_application(applicant["id"])
        assert app["debt_to_income_pct"] == 20.0


class TestApprovedAmountHaircut:

    def test_instant_path_keeps_full_capacity_ratio(self, api, platform_admin_headers):
        """PRD 3.7: "files where both verifications passed instantly keep the full forty percent."
        PRD 3.7: "The approved amount is the lesser of `requested_amount_cents` and that supportable principal."

        Design: Difficulty/dual_variant_calc/approved_amount_manual_review_haircut_shrinks_principal
        """
        from test_helpers import setup_underwritten_application

        app = setup_underwritten_application()
        # capacity = floor(1000000 * 0.40) - 200000 = 200000; supportable 6000000;
        # approved = min(5000000, 6000000) = 5000000
        assert app["status"] == "UNDERWRITTEN"
        assert app["approved_amount_cents"] == 5000000

    def test_manual_review_haircut_shrinks_principal(
        self, api, platform_admin_headers, verification_officer_two_headers
    ):
        """PRD 3.7: "when at least one of the application's verifications passed through manual document review (reached `MANUAL_PASSED`), the capacity ratio is reduced: thirty-two percent of monthly income is used instead of forty percent, so identical applicants receive strictly smaller approved amounts whenever manual review was involved"

        Design: Difficulty/dual_variant_calc/approved_amount_manual_review_haircut_shrinks_principal
        """
        from test_helpers import setup_underwritten_application

        app = setup_underwritten_application(manual_review=True)
        # capacity = floor(1000000 * 0.32) - 200000 = 120000; supportable 3600000
        assert app["status"] == "UNDERWRITTEN"
        assert app["approved_amount_cents"] == 3600000

        verifications = get_verifications(app["id"])
        income = next(v for v in verifications if v["kind"] == "INCOME")
        assert income["status"] == "MANUAL_PASSED"
        assert income["reviewer_id"] == "vo-two"


class TestManualReviewLoop:

    def test_manual_pass_returns_application_to_underwritten(
        self, api, platform_admin_headers, verification_officer_two_headers
    ):
        """PRD 3.6: "When a passing decision leaves no verification still unresolved - none in `PENDING`, `INSTANT_FAILED`, `MANUAL_REVIEW`, or `MANUAL_FAILED` - the application moves from `DOCS_REQUIRED` to `UNDERWRITTEN` and the approved amount is computed."
        PRD 3.6: "A passing decision sets the verification to `MANUAL_PASSED`"

        Design: Difficulty/non_linear_state_machine/verification_manual_review_loop_returns_application_to_underwritten
        """
        create_active_model(model_code="ADU-B-4")
        applicant = create_applicant(full_name="Loop Larry", bank_account_nsf_count_90d=3)
        app = submit_application(applicant["id"])
        app, income = fail_income_instant_check(app["id"])

        # Before the manual decision the application waits in DOCS_REQUIRED while
        # the sibling IDENTITY verification is already INSTANT_PASSED.
        assert app["status"] == "DOCS_REQUIRED"
        verifications = get_verifications(app["id"])
        identity = next(v for v in verifications if v["kind"] == "IDENTITY")
        assert identity["status"] == "INSTANT_PASSED"

        app = manual_pass_verification(app["id"], income["id"], officer=verification_officer_two_headers)
        assert app["status"] == "UNDERWRITTEN"
        # Manual-review haircut applies: 0.32 ratio -> approved 3600000.
        assert app["approved_amount_cents"] == 3600000

        verifications = get_verifications(app["id"])
        income = next(v for v in verifications if v["kind"] == "INCOME")
        assert income["status"] == "MANUAL_PASSED"
        assert income["reviewer_id"] == "vo-two"

    def test_identity_passes_while_income_waits_for_manual_review(
        self, api, platform_admin_headers
    ):
        """PRD 3.6: "The moment any verification reaches `INSTANT_FAILED`, the application moves to `DOCS_REQUIRED` and waits on manual document review."

        Design: Difficulty/non_linear_state_machine/verification_manual_review_loop_returns_application_to_underwritten
        """
        create_active_model(model_code="ADU-B-4B")
        applicant = create_applicant(full_name="Half Pass Hank", bank_account_nsf_count_90d=3)
        app = submit_application(applicant["id"])
        app, income = fail_income_instant_check(app["id"])
        assert app["status"] == "DOCS_REQUIRED"
        assert income["status"] == "INSTANT_FAILED"

        # The application stays in DOCS_REQUIRED until the manual decision lands.
        app = get_success_data(api.get_application(app["id"], platform_admin_headers))
        assert app["status"] == "DOCS_REQUIRED"
        verifications = get_verifications(app["id"])
        identity = next(v for v in verifications if v["kind"] == "IDENTITY")
        assert identity["status"] == "INSTANT_PASSED"


class TestManualDecisionGating:

    def test_manual_decision_on_pending_verification_rejected_by_application_state(
        self, api, platform_admin_headers, verification_officer_two_headers
    ):
        """PRD 3.6: "A `VerificationOfficer` issues a manual decision on a verification in `INSTANT_FAILED` or `MANUAL_REVIEW`"

        Design: Difficulty/cross_entity_state_dependency/manual_decision_gated_by_application_state
        """
        create_active_model(model_code="ADU-B-8")
        applicant = create_applicant(full_name="Gate Gail")
        app = submit_application(applicant["id"])
        assert app["status"] == "VERIFICATION_PENDING"
        income = next(v for v in get_verifications(app["id"]) if v["kind"] == "INCOME")

        resp = api.manual_decide_verification(
            app["id"], income["id"], {"outcome": "PASS"}, verification_officer_two_headers
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)

        app = get_success_data(api.get_application(app["id"], platform_admin_headers))
        assert app["status"] == "VERIFICATION_PENDING"
        income = next(v for v in get_verifications(app["id"]) if v["kind"] == "INCOME")
        assert income["status"] == "PENDING"

    def test_manual_decision_rejected_until_instant_check_fails(
        self, api, platform_admin_headers, verification_officer_headers,
        verification_officer_two_headers
    ):
        """PRD 3.6: "A `VerificationOfficer` issues a manual decision on a verification in `INSTANT_FAILED` or `MANUAL_REVIEW`"

        Design: Difficulty/cross_entity_state_dependency/manual_decision_gated_by_application_state
        """
        create_active_model(model_code="ADU-B-8B")
        applicant = create_applicant(full_name="Gate Gina", bank_account_nsf_count_90d=3)
        app = submit_application(applicant["id"])
        income = next(v for v in get_verifications(app["id"]) if v["kind"] == "INCOME")

        # PENDING verification, VERIFICATION_PENDING application: manual decision
        # is not yet legal.
        resp = api.manual_decide_verification(
            app["id"], income["id"], {"outcome": "PASS"}, verification_officer_two_headers
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)

        # Fail the income instant check; the sibling IDENTITY verification is
        # still PENDING, so the manual PASS cannot bubble the application up
        # yet ("no verification still unresolved" - PRD 3.6).
        validate_success(
            api.instant_check_verification(app["id"], income["id"], verification_officer_headers)
        )
        resp = api.manual_decide_verification(
            app["id"], income["id"], {"outcome": "PASS"}, verification_officer_two_headers
        )
        validate_success(resp, expected_status=200)
        app = get_success_data(api.get_application(app["id"], platform_admin_headers))
        assert app["status"] == "DOCS_REQUIRED"

        # The manual decision is legal only on a verification in
        # INSTANT_FAILED or MANUAL_REVIEW: re-deciding the now-MANUAL_PASSED
        # income verification is rejected.
        resp = api.manual_decide_verification(
            app["id"], income["id"], {"outcome": "PASS"}, verification_officer_two_headers
        )
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_INVALID_STATE)


class TestSegregationOfDuties:

    def test_manual_decision_by_instant_checker_rejected(
        self, api, platform_admin_headers, verification_officer_headers
    ):
        """PRD 3.6: "the deciding officer must not be the same operator who ran that verification's instant check, on pain of `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/manual_decision_by_same_officer_as_instant_check_violates_segregation
        """
        create_active_model(model_code="ADU-S-3")
        applicant = create_applicant(full_name="Sod Sandy", bank_account_nsf_count_90d=3)
        app = submit_application(applicant["id"])
        app, income = fail_income_instant_check(app["id"], officer=verification_officer_headers)
        assert app["status"] == "DOCS_REQUIRED"

        # The same officer who ran the instant check may not render the decision.
        resp = api.manual_decide_verification(
            app["id"], income["id"], {"outcome": "PASS"}, verification_officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        income = next(v for v in get_verifications(app["id"]) if v["kind"] == "INCOME")
        assert income["status"] == "INSTANT_FAILED"
        assert income["reviewer_id"] is None
        app = get_success_data(api.get_application(app["id"], platform_admin_headers))
        assert app["status"] == "DOCS_REQUIRED"

    def test_application_not_found_beats_segregation_of_duties(
        self, api, verification_officer_headers
    ):
        """PRD 2.9: "then path-identifier existence (`ERR_NOT_FOUND`), then body foreign-key resolution (`ERR_REFERENCED_NOT_FOUND`), then state-transition legality (the entity-specific invalid-state errors, all HTTP 409), then segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`)"
        PRD 2.7: "The first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404), and no later segment is examined."

        Design: Difficulty/priority_pair_validation_conflict/application_not_found_beats_segregation_of_duties
        """
        resp = api.manual_decide_verification(
            "00000000-0000-4000-8000-0000000000aa",
            "00000000-0000-4000-8000-0000000000bb",
            {"outcome": "PASS"},
            verification_officer_headers,
        )
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value

    def test_verification_under_unknown_application_also_not_found(
        self, api, platform_admin_headers, verification_officer_headers
    ):
        """PRD 2.7: "the application identifier `id` before the verification identifier `verificationId` beneath it"

        Design: Difficulty/priority_pair_validation_conflict/application_not_found_beats_segregation_of_duties
        """
        create_active_model(model_code="ADU-NF-1")
        applicant = create_applicant(full_name="Not Found Nora")
        app = submit_application(applicant["id"])
        income = next(v for v in get_verifications(app["id"]) if v["kind"] == "INCOME")

        # Unknown application id with an existing verification id: the leftmost
        # unresolved path segment dominates.
        resp = api.manual_decide_verification(
            "00000000-0000-4000-8000-0000000000aa",
            income["id"],
            {"outcome": "PASS"},
            verification_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestApplicationSubmissionValidation:

    def test_missing_requested_amount_returns_invalid_request(
        self, api, platform_admin_headers, auditor_headers
    ):
        """PRD 3.4: "Application submission is performed by a `PlatformAdmin` and names the `applicant_id`, the `requested_amount_cents`, and a `channel` of `DIRECT` or `PARTNER_REFERRAL`."
        PRD 5: "`ERR_INVALID_REQUEST` | 400"

        Design: Corner/entities/application_create_missing_requested_amount_returns_invalid_request
        """
        create_active_model(model_code="ADU-E-3")
        applicant = create_applicant(full_name="Missing Mike")
        resp = api.create_application(
            {"applicant_id": applicant["id"], "channel": "DIRECT"},
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(
            api.list_applications(auditor_headers, params={"applicant_id": applicant["id"]})
        )
        assert meta["total_count"] == 0

    def test_referral_channel_requires_partner_and_direct_forbids_it(
        self, api, platform_admin_headers, partner_admin_headers, auditor_headers
    ):
        """PRD 3.4: "when `channel` is `PARTNER_REFERRAL` a `referral_partner_id` naming the partner under whose branding the applicant applied is required, and when `channel` is `DIRECT` a `referral_partner_id` must not be supplied - either violation fails with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/referral_channel_requires_referral_partner_and_direct_forbids_it
        """
        create_active_model(model_code="ADU-V-2")
        applicant = create_applicant(full_name="Channel Chen")
        from test_helpers import create_partner

        partner = create_partner(legal_name="Ref Bank", activated=False)

        resp = api.create_application(
            {
                "applicant_id": applicant["id"],
                "channel": "PARTNER_REFERRAL",
                "requested_amount_cents": 5000000,
            },
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        resp = api.create_application(
            {
                "applicant_id": applicant["id"],
                "channel": "DIRECT",
                "referral_partner_id": partner["id"],
                "requested_amount_cents": 5000000,
            },
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        data, meta = validate_paginated(
            api.list_applications(auditor_headers, params={"applicant_id": applicant["id"]})
        )
        assert meta["total_count"] == 0

    def test_no_active_model_blocks_submission(
        self, api, platform_admin_headers, auditor_headers
    ):
        """PRD 3.4: "Submission requires that exactly one model be `ACTIVE` at that instant; with none, it fails with `ERR_NO_ACTIVE_MODEL`."

        Design: Corner/validations/no_active_model_blocks_submission
        """
        from test_helpers import create_model_version_payload, TEST_USERS

        resp = api.create_model_version(
            create_model_version_payload(model_code="ADU-V-1"),
            TEST_USERS["risk_officer_creator_headers"],
        )
        validate_success(resp, expected_status=201)  # DRAFT only, never activated

        applicant = create_applicant(full_name="NoModel Ned")
        resp = api.create_application(
            {
                "applicant_id": applicant["id"],
                "channel": "DIRECT",
                "requested_amount_cents": 5000000,
            },
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_MODEL)
        data, meta = validate_paginated(
            api.list_applications(auditor_headers, params={"applicant_id": applicant["id"]})
        )
        assert meta["total_count"] == 0

    def test_both_body_fks_unknown_fails_on_applicant_first(
        self, api, platform_admin_headers
    ):
        """PRD 2.7: "foreign keys carried in request bodies are resolved in their declared input order - `applicant_id` is resolved before `referral_partner_id` on application submission"
        PRD 2.7: "the first unresolvable body reference is rejected with `ERR_REFERENCED_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/application_create_with_both_body_fks_unknown_fails_on_applicant_first
        """
        create_active_model(model_code="ADU-E-6")
        resp = api.create_application(
            {
                "applicant_id": "00000000-0000-4000-8000-000000000011",
                "channel": "PARTNER_REFERRAL",
                "referral_partner_id": "00000000-0000-4000-8000-000000000022",
                "requested_amount_cents": 5000000,
            },
            platform_admin_headers,
        )
        err = validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND)
        assert "applicant" in err["message"].lower(), (
            "declared input order resolves applicant_id before referral_partner_id"
        )

    def test_unknown_referral_partner_alone_also_referenced_not_found(
        self, api, platform_admin_headers
    ):
        """PRD 2.7: "the first unresolvable body reference is rejected with `ERR_REFERENCED_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/application_create_with_both_body_fks_unknown_fails_on_applicant_first
        """
        create_active_model(model_code="ADU-E-6B")
        applicant = create_applicant(full_name="Known Kim")
        resp = api.create_application(
            {
                "applicant_id": applicant["id"],
                "channel": "PARTNER_REFERRAL",
                "referral_partner_id": "00000000-0000-4000-8000-000000000022",
                "requested_amount_cents": 5000000,
            },
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND)
