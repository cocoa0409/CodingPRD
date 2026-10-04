"""Each business rule and its declared error, exercised in isolation."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    DEVELOPER, COMPLIANCE, ANALYST, FAIR_LENDING,
    create_archive_sample,
    create_bureau_payload,
    create_reason_code,
    create_and_activate_license,
    create_model,
    create_score_model_payload,
    author_variant,
    release_variant,
    file_risk_report,
    post_score,
    schedule_study,
    run_study,
    setup_released_dual_auto,
    setup_deprecation_blocked,
    setup_occ_posting_target,
    create_score_result_payload,
    make_score_consumer_headers,
    TEST_USERS,
    create_model_documentation_payload,
    register_bureau,
)


class TestAuthenticationAndAuthorisation:

    def test_an_undeclared_role_is_rejected_before_any_other_check(self, api):
        """PRD §2.1: "The system recognises exactly seven roles, spelled as follows:
        `BureauAdministrator`, `ModelDeveloper`, `ValidationAnalyst`,
        `ComplianceOfficer`, `FairLendingOfficer`, `ReasonCodeAdministrator`, and
        `ScoreConsumer`. A request that omits either header, or that names a role
        outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/validation_returns_unauthenticated_without_a_role_header
        """
        res = api_client.create_score_model(
            create_score_model_payload(family_code="FICO_CORE", version_label="AUTH-V1",
                                       min_input_count=100),
            TEST_USERS["unknown_role_headers"])
        assert res.status_code == 401
        assert res.json()["data"]["error_id"] == "ERR_UNAUTHENTICATED"

    def test_the_rejected_request_wrote_no_version(self, api):
        """PRD §2.1: "A request that omits either header, or that names a role
        outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/validation_returns_unauthenticated_without_a_role_header
        """
        api_client.create_score_model(
            create_score_model_payload(family_code="FICO_CORE", version_label="AUTH-V1",
                                       min_input_count=100),
            TEST_USERS["unknown_role_headers"])
        res = api_client.list_score_models(DEVELOPER)
        data = validate_success(res, 200)
        assert data == []

    def test_a_role_outside_the_endpoint_list_is_unauthorised(self, api):
        """PRD §2.1: "A request whose role is valid but is not listed as an
        authorised role for the target operation is rejected with
        `ERR_UNAUTHORIZED`."

        Design: Corner/validations/validation_returns_unauthorized_for_a_role_outside_the_endpoint_list
        """
        res = api_client.create_bureau(
            create_bureau_payload(bureau_code="EXP", display_name="Experian"), DEVELOPER)
        assert res.status_code == 403
        assert res.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

    def test_only_the_privileged_bureau_landed(self, api):
        """PRD §4: "| POST | `/bureaus` | Register one of the three national bureaus |
        BureauAdministrator |"

        Design: Corner/validations/validation_returns_unauthorized_for_a_role_outside_the_endpoint_list
        """
        register_bureau("TUC", "TransUnion")
        api_client.create_bureau(
            create_bureau_payload(bureau_code="EXP", display_name="Experian"), DEVELOPER)
        res = api_client.list_bureaus(DEVELOPER)
        data = validate_success(res, 200)
        assert len(data) == 1


class TestUniquenessRules:

    def test_a_repeated_bureau_code_is_refused(self, api):
        """PRD §2.3: "Each row carries a `bureau_code` drawn from `TUC`, `EXP` or
        `EQF`, which must be unique across bureaus and is immutable once the row is
        created"

        Design: Corner/validations/validation_returns_duplicate_bureau_code_on_a_second_registration
        """
        register_bureau("TUC", "TransUnion")
        res = api_client.create_bureau(
            create_bureau_payload(bureau_code="TUC", display_name="TransUnion Duplicate"),
            TEST_USERS["bureau_admin_headers"])
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_DUPLICATE_BUREAU_CODE"

    def test_the_duplicate_registration_left_one_bureau(self, api):
        """PRD §2.3: "The `Bureau` registry is the one configuration surface with no
        lifecycle of its own."

        Design: Corner/validations/validation_returns_duplicate_bureau_code_on_a_second_registration
        """
        register_bureau("TUC", "TransUnion")
        api_client.create_bureau(
            create_bureau_payload(bureau_code="TUC", display_name="TransUnion Duplicate"),
            TEST_USERS["bureau_admin_headers"])
        res = api_client.list_bureaus(DEVELOPER)
        data = validate_success(res, 200)
        assert len(data) == 1

    def test_a_repeated_label_inside_one_family_is_refused(self, api):
        """PRD §3.1: "The `family_code` is drawn from `FICO_CORE` or `VANTAGE_STYLE`,
        and the pair of `family_code` and `version_label` must be unique across all
        versions — a repeat is refused with `ERR_DUPLICATE_VERSION_LABEL`."

        Design: Corner/validations/validation_returns_duplicate_version_label_within_one_family
        """
        create_model(version_label="SHARED-V1")
        res = api_client.create_score_model(
            create_score_model_payload(family_code="FICO_CORE", version_label="SHARED-V1",
                                       min_input_count=100), DEVELOPER)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_DUPLICATE_VERSION_LABEL"

    def test_the_same_label_in_the_other_family_is_legal(self, api):
        """PRD §3.1: "the pair of `family_code` and `version_label` must be unique
        across all versions"

        The uniqueness key is the family pair, not the label alone.

        Design: Corner/validations/validation_returns_duplicate_version_label_within_one_family
        """
        create_model(version_label="SHARED-V1")
        data = validate_success(api_client.create_score_model(
            create_score_model_payload(family_code="VANTAGE_STYLE",
                                       version_label="SHARED-V1", min_input_count=100),
            DEVELOPER), 201)
        assert data["id"] is not None

    def test_the_first_family_still_holds_exactly_one_version(self, api):
        """PRD §3.1: "the pair of `family_code` and `version_label` must be unique
        across all versions"

        Design: Corner/validations/validation_returns_duplicate_version_label_within_one_family
        """
        create_model(version_label="SHARED-V1")
        api_client.create_score_model(
            create_score_model_payload(family_code="VANTAGE_STYLE",
                                       version_label="SHARED-V1", min_input_count=100),
            DEVELOPER)
        res = api_client.list_score_models(DEVELOPER, params={"family_code": "FICO_CORE"})
        data = validate_success(res, 200)
        assert len(data) == 1

    def test_a_second_registered_slot_under_one_tag_is_refused(self, api):
        """PRD §3.8: "A supplied `discovery_tag` consumes a discovery slot: the
        registered request carrying that tag moves from `REGISTERED` to `CONSUMED`"
        PRD §2.11: "A discovery slot is registered in `REGISTERED` status with its
        `requested_at` stamped from the logical clock at the moment of registration"

        A tag may name only one slot while that slot is still REGISTERED.

        Design: Corner/validations/validation_returns_duplicate_discovery_tag_while_a_slot_is_registered
        """
        bureau, model, variant = setup_released_dual_auto()
        license_ = create_and_activate_license(variant["id"])
        headers = make_score_consumer_headers(license_["id"])
        api_client.create_discovery_request("DISC-DUP", headers)
        res = api_client.create_discovery_request("DISC-DUP", headers)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_DUPLICATE_DISCOVERY_TAG"

    def test_only_one_slot_carries_the_tag(self, api):
        """PRD §3.8: "A supplied `discovery_tag` consumes a discovery slot: the
        registered request carrying that tag moves from `REGISTERED` to `CONSUMED`
        and its `consumed_score_result_id` is bound to this posting"

        Design: Corner/validations/validation_returns_duplicate_discovery_tag_while_a_slot_is_registered
        """
        bureau, model, variant = setup_released_dual_auto()
        license_ = create_and_activate_license(variant["id"])
        headers = make_score_consumer_headers(license_["id"])
        api_client.create_discovery_request("DISC-DUP", headers)
        api_client.create_discovery_request("DISC-DUP", headers)
        res = api_client.list_discovery_requests(COMPLIANCE, params={"tag": "DISC-DUP"})
        _, meta = validate_success(res, 200), res.json()["meta"]
        assert meta["total_count"] == 1


class TestStudyRunEligibility:

    def test_a_draw_below_the_model_minimum_blocks_the_run(self, api):
        """PRD §3.3: "The linked sample's `record_count` must be at least the
        model's `min_input_count`, else `ERR_SAMPLE_TOO_SMALL`."

        Design: Corner/validations/validation_returns_sample_too_small_when_the_draw_misses_the_model_minimum
        """
        bureau, model, variant = setup_released_dual_auto(min_input_count=100)
        sample = create_archive_sample(model["id"], sample_ref="XFER-SMALL",
                                       record_count=40, segment_name="THIN_FILE",
                                       sample_kind="VALIDATION",
                                       observation_window_months=24,
                                       window_start_month="2024-01",
                                       window_end_month="2026-01")
        study = schedule_study(model["id"], sample["id"], study_path="CROSS_BUREAU",
                               performed_by="va-small")
        current = get_success_data(api_client.get_validation_study(study["id"], ANALYST), 200)
        res = api_client.run_validation_study(study["id"], current["version"], ANALYST)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_SAMPLE_TOO_SMALL"

    def test_the_blocked_study_stays_scheduled_and_unmeasured(self, api):
        """PRD §3.3: "Running the study is where the measurement happens, and it
        requires three eligibility conditions in order."

        Design: Corner/validations/validation_returns_sample_too_small_when_the_draw_misses_the_model_minimum
        """
        bureau, model, variant = setup_released_dual_auto(min_input_count=100)
        sample = create_archive_sample(model["id"], sample_ref="XFER-SMALL",
                                       record_count=40, segment_name="THIN_FILE",
                                       sample_kind="VALIDATION",
                                       observation_window_months=24,
                                       window_start_month="2024-01",
                                       window_end_month="2026-01")
        study = schedule_study(model["id"], sample["id"], study_path="CROSS_BUREAU",
                               performed_by="va-small")
        current = get_success_data(api_client.get_validation_study(study["id"], ANALYST), 200)
        api_client.run_validation_study(study["id"], current["version"], ANALYST)
        after = get_success_data(api_client.get_validation_study(study["id"], ANALYST), 200)
        assert after["status"] == "SCHEDULED"
        assert after["reconciliation_variance"] is None

    def test_a_cross_bureau_run_on_a_development_draw_is_refused(self, api):
        """PRD §3.3: "A cross-bureau study requires the linked sample's `sample_kind`
        to be `VALIDATION`, else `ERR_SAMPLE_KIND_MISMATCH`."

        Design: Corner/validations/validation_returns_sample_kind_mismatch_for_a_cross_bureau_study_on_a_development_draw
        """
        bureau, model, variant = setup_released_dual_auto(min_input_count=100)
        create_reason_code(variant["id"], depth_tier="PRIMARY",
                           trigger_feature_code="SEGMENT_ZERO", code_label="rc-kind",
                           weight_pct=0.30)
        sample = create_archive_sample(model["id"], sample_ref="DEV-KIND",
                                       record_count=6000, segment_name="PRIME",
                                       sample_kind="DEVELOPMENT",
                                       observation_window_months=24,
                                       window_start_month="2024-01",
                                       window_end_month="2026-01")
        study = schedule_study(model["id"], sample["id"], study_path="CROSS_BUREAU",
                               performed_by="va-kind")
        current = get_success_data(api_client.get_validation_study(study["id"], ANALYST), 200)
        res = api_client.run_validation_study(study["id"], current["version"], ANALYST)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_SAMPLE_KIND_MISMATCH"

    def test_the_same_development_draw_supports_a_protected_class_study(self, api):
        """PRD §3.3: "the `sample_kind` (either `DEVELOPMENT`, whose draws may run
        protected-class studies, or `VALIDATION`, which cross-bureau studies
        require)"

        Design: Corner/validations/validation_returns_sample_kind_mismatch_for_a_cross_bureau_study_on_a_development_draw
        """
        bureau, model, variant = setup_released_dual_auto(min_input_count=100)
        create_reason_code(variant["id"], depth_tier="PRIMARY",
                           trigger_feature_code="SEGMENT_ZERO", code_label="rc-kind2",
                           weight_pct=0.30)
        sample = create_archive_sample(model["id"], sample_ref="DEV-KIND2",
                                       record_count=6000, segment_name="PRIME",
                                       sample_kind="DEVELOPMENT",
                                       observation_window_months=24,
                                       window_start_month="2024-01",
                                       window_end_month="2026-01")
        study = schedule_study(model["id"], sample["id"], study_path="PROTECTED_CLASS",
                               performed_by="va-kind")
        ran = run_study(study["id"])
        assert ran["status"] == "VALIDATION_COMPLETE"

    def test_a_protected_class_run_without_a_catalogue_is_refused(self, api):
        """PRD §3.3: "A protected-class study requires at least one `ReasonCode`
        belonging to a variant of that model to be in `ACTIVE` status, else
        `ERR_REASON_CODE_MISSING`."

        Design: Corner/validations/validation_returns_reason_code_missing_for_a_protected_class_study
        """
        bureau, model, variant = setup_released_dual_auto(min_input_count=100)
        sample = create_archive_sample(model["id"], sample_ref="DEV-NORC",
                                       record_count=6000, segment_name="PRIME",
                                       sample_kind="DEVELOPMENT",
                                       observation_window_months=24,
                                       window_start_month="2024-01",
                                       window_end_month="2026-01")
        study = schedule_study(model["id"], sample["id"], study_path="PROTECTED_CLASS",
                               performed_by="va-norc")
        current = get_success_data(api_client.get_validation_study(study["id"], ANALYST), 200)
        res = api_client.run_validation_study(study["id"], current["version"], ANALYST)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_REASON_CODE_MISSING"

    def test_the_empty_catalogue_is_what_blocked_the_run(self, api):
        """PRD §3.5: "Adverse-action explanations are organised as a catalogue per
        variant."

        Design: Corner/validations/validation_returns_reason_code_missing_for_a_protected_class_study
        """
        bureau, model, variant = setup_released_dual_auto(min_input_count=100)
        res = api_client.list_reason_codes(COMPLIANCE,
                                           params={"score_variant_id": variant["id"]})
        _, meta = validate_success(res, 200), res.json()["meta"]
        assert meta["total_count"] == 0


class TestDocumentationAndDutyGates:

    def test_a_draft_report_does_not_unlock_the_release_gate(self, api):
        """PRD §2.10: "A `ScoreModel` cannot move into `RELEASED` from
        `DEVELOPMENT`, and cannot be reopened out of `DEPRECATED`, unless a
        `ModelDocumentation` with `doc_type` `MODEL_RISK_REPORT` whose
        `required_version_label` equals that model's `version_label` exists in status
        `FILED` or `SUPPLEMENTED`; otherwise the attempt fails with
        `ERR_MODEL_DOC_REQUIRED`."

        Design: Corner/validations/validation_returns_model_doc_required_when_the_risk_report_is_still_draft
        """
        model = create_model(version_label="CREDIT-DUAL-V1")
        variant = author_variant(model["id"])
        release_variant(variant["id"])
        md = get_success_data(api_client.create_model_documentation(
            create_model_documentation_payload(score_model_id=model["id"],
                                               doc_type="MODEL_RISK_REPORT",
                                               required_version_label="CREDIT-DUAL-V1"),
            COMPLIANCE), 201)
        assert md["status"] == "DRAFT"
        current = get_success_data(api_client.get_score_model(model["id"], DEVELOPER), 200)
        res = api_client.release_model(model["id"], current["version"], DEVELOPER)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_MODEL_DOC_REQUIRED"

    def test_filing_the_report_makes_the_same_release_succeed(self, api):
        """PRD §3.1: "When all three pass, `released_at` is stamped from the logical
        clock and the supersession cascade of §2.8 fires"

        Design: Corner/validations/validation_returns_model_doc_required_when_the_risk_report_is_still_draft
        """
        model = create_model(version_label="CREDIT-DUAL-V1")
        variant = author_variant(model["id"])
        release_variant(variant["id"])
        filed = file_risk_report(model["id"], "CREDIT-DUAL-V1")
        assert filed["status"] == "FILED"
        current = get_success_data(api_client.get_score_model(model["id"], DEVELOPER), 200)
        released = validate_success(
            api_client.release_model(model["id"], current["version"], DEVELOPER), 200)
        assert released["status"] == "RELEASED"

    def test_acknowledgement_by_the_analyst_named_performed_by_is_refused(self, api):
        """PRD §2.10: "The `finalized_by` value recorded at acknowledgement must
        differ from the `performed_by` value captured when the study was scheduled;
        an acknowledgement attempted by the analyst named as `performed_by` is
        refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/validation_returns_segregation_of_duties_when_the_analyst_acknowledges_own_study
        """
        bureau, model, variant = setup_released_dual_auto()
        sample = create_archive_sample(model["id"], sample_ref="XFER-SOD",
                                       record_count=6000, segment_name="PRIME",
                                       sample_kind="VALIDATION",
                                       observation_window_months=24,
                                       window_start_month="2024-01",
                                       window_end_month="2026-01")
        study = schedule_study(model["id"], sample["id"], study_path="CROSS_BUREAU",
                               performed_by="va-owner")
        run_study(study["id"])
        current = get_success_data(api_client.get_validation_study(study["id"], FAIR_LENDING), 200)
        res = api_client.acknowledge_validation_study(
            study["id"], "va-owner", "EV-SOD-1", current["version"], FAIR_LENDING)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_SEGREGATION_OF_DUTIES"

    def test_the_refused_acknowledgement_recorded_no_finalizer(self, api):
        """PRD §2.10: "Study acknowledgement is subject to a second pair of eyes."

        Design: Corner/validations/validation_returns_segregation_of_duties_when_the_analyst_acknowledges_own_study
        """
        bureau, model, variant = setup_released_dual_auto()
        sample = create_archive_sample(model["id"], sample_ref="XFER-SOD",
                                       record_count=6000, segment_name="PRIME",
                                       sample_kind="VALIDATION",
                                       observation_window_months=24,
                                       window_start_month="2024-01",
                                       window_end_month="2026-01")
        study = schedule_study(model["id"], sample["id"], study_path="CROSS_BUREAU",
                               performed_by="va-owner")
        run_study(study["id"])
        current = get_success_data(api_client.get_validation_study(study["id"], FAIR_LENDING), 200)
        api_client.acknowledge_validation_study(
            study["id"], "va-owner", "EV-SOD-1", current["version"], FAIR_LENDING)
        after = get_success_data(api_client.get_validation_study(study["id"], FAIR_LENDING), 200)
        assert after["finalized_by"] is None

    def test_deprecation_is_blocked_while_a_licence_is_active(self, api):
        """PRD §3.2: "The gate is that no licence on any variant of that version may
        be in `ACTIVE` status; an outstanding active licence blocks the move with
        `ERR_DEPRECATION_BLOCKED`."

        Design: Corner/validations/validation_returns_deprecation_blocked_while_a_license_is_active
        """
        bureau, model, variant, license_ = setup_deprecation_blocked()
        current = get_success_data(api_client.get_score_model(model["id"], COMPLIANCE), 200)
        res = api_client.deprecate_model(model["id"], current["version"], COMPLIANCE)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_DEPRECATION_BLOCKED"

    def test_terminating_the_licence_fixes_its_entitlement_flag(self, api):
        """PRD §3.7: "On termination `entitlement_status` is recomputed to
        `WITHIN_ENTITLEMENT` when `cumulative_score_count` is at most
        `entitled_count` and to `OVER_ENTITLED` when it is greater"

        Design: Corner/validations/validation_returns_deprecation_blocked_while_a_license_is_active
        """
        bureau, model, variant, license_ = setup_deprecation_blocked()
        current = get_success_data(api_client.get_license(license_["id"], COMPLIANCE), 200)
        terminated = validate_success(
            api_client.terminate_license(license_["id"], current["version"], COMPLIANCE), 200)
        assert terminated["entitlement_status"] == "WITHIN_ENTITLEMENT"

    def test_the_same_deprecation_succeeds_with_no_active_licence_left(self, api):
        """PRD §3.2: "Once `DEPRECATED`, the version stays selectable by the lenders
        already using it, but any attempt to create a *new* licence on one of its
        variants is refused with `ERR_MODEL_DEPRECATED`."

        Design: Corner/validations/validation_returns_deprecation_blocked_while_a_license_is_active
        """
        bureau, model, variant, license_ = setup_deprecation_blocked()
        current = get_success_data(api_client.get_score_model(model["id"], COMPLIANCE), 200)
        api_client.deprecate_model(model["id"], current["version"], COMPLIANCE)
        lic = get_success_data(api_client.get_license(license_["id"], COMPLIANCE), 200)
        api_client.terminate_license(license_["id"], lic["version"], COMPLIANCE)
        current = get_success_data(api_client.get_score_model(model["id"], COMPLIANCE), 200)
        deprecated = validate_success(
            api_client.deprecate_model(model["id"], current["version"], COMPLIANCE), 200)
        assert deprecated["status"] == "DEPRECATED"


class TestOptimisticConcurrency:

    def test_a_posting_on_a_stale_licence_view_is_refused(self, api):
        """PRD §2.5: "Every one of these checks rejects with `ERR_STALE_VERSION` at
        HTTP status 412 when the supplied value does not equal the parent record's
        current `version`."
        PRD §3.8: "the write carries `expected_license_version` and is a statement
        about the licence's current state, so a stale view is refused with
        `ERR_STALE_VERSION`."

        Design: Corner/validations/validation_returns_stale_version_on_a_posting_against_an_advanced_license
        """
        bureau, model, variant, license_, consumer = setup_occ_posting_target()
        stale = license_["version"]
        post_score(license_["id"], consumer["id"], variant["id"], bureau["id"], 715)
        res = api_client.create_score_result(
            create_score_result_payload(
                consumer_id=consumer["id"], score_variant_id=variant["id"],
                bureau_id=bureau["id"], license_id=license_["id"],
                raw_posted_score=716, expected_license_version=stale),
            make_score_consumer_headers(license_["id"]))
        assert res.status_code == 412
        assert res.json()["data"]["error_id"] == "ERR_STALE_VERSION"

    def test_the_stale_posting_settled_nothing(self, api):
        """PRD §3.8: "Settlement closes the posting. A `MARGINAL_PRICING` entry is
        appended to the fee ledger"

        Design: Corner/validations/validation_returns_stale_version_on_a_posting_against_an_advanced_license
        """
        bureau, model, variant, license_, consumer = setup_occ_posting_target()
        stale = license_["version"]
        post_score(license_["id"], consumer["id"], variant["id"], bureau["id"], 715)
        api_client.create_score_result(
            create_score_result_payload(
                consumer_id=consumer["id"], score_variant_id=variant["id"],
                bureau_id=bureau["id"], license_id=license_["id"],
                raw_posted_score=716, expected_license_version=stale),
            make_score_consumer_headers(license_["id"]))
        res = api_client.list_score_results(DEVELOPER, params={"consumer_id": consumer["id"]})
        _, meta = validate_success(res, 200), res.json()["meta"]
        assert meta["total_count"] == 1