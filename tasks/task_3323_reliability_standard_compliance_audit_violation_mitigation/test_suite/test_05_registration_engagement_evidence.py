"""Registrations, engagements, evidence, and self-report lifecycle rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_engagement_payload,
    create_evidence_payload,
    create_registration_payload,
    create_self_report_payload,
    create_violation,
    create_violation_payload,
    get_success_data,
    make_cip_manager_headers,
    make_officer_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

AUD = TEST_USERS["auditor_headers"]
RC = TEST_USERS["registration_coordinator_headers"]
RER = TEST_USERS["regional_reviewer_headers"]


class TestRegistrationDerivesApplicableStandards:
    def test_multi_function_registration_union(self):
        """PRD §3.1: "At creation, and again whenever a registration is updated,
        the server derives applicable_standards: the union, across every
        function code the entity registered under, of the standard library
        entries mapped to that code."

        Design: Corner/entities/registration_derives_applicable_standards_from_functions
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.create_registration(
            create_registration_payload(legal_name="Multi Func Co",
                                        registration_functions=["GO", "TO"]), RC)
        data = validate_success(resp, expected_status=201)
        assert data["applicable_standard_count"] == len(data["applicable_standards"])
        std_ids = {s["standard_id"] for s in data["applicable_standards"]}
        assert {"STD-GO-001", "STD-GO-002"} <= std_ids
        assert {"STD-TO-001", "STD-TO-002"} <= std_ids

    def test_new_registration_starts_active_with_zero_counts(self):
        """PRD §3.1: "Every registered entity also carries three derived posture
        fields ... compliance_status is ACTIVE or RESTRICTED per the restriction
        rule of §2.8. open_violation_count counts the entity's violations whose
        status is OPEN, MITIGATION_SUBMITTED, MITIGATION_IN_PROGRESS, or
        APPEALED, and is recomputed on every violation creation and status
        change."

        Design: Corner/entities/registration_derives_applicable_standards_from_functions
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.create_registration(
            create_registration_payload(legal_name="Fresh Co",
                                        registration_functions=["GO", "TO"]), RC)
        data = validate_success(resp, expected_status=201)
        assert data["compliance_status"] == "ACTIVE"
        assert data["open_violation_count"] == 0


class TestRegistrationMissingLegalNameRejected:
    def test_missing_legal_name(self):
        """PRD §2.5: "Generic malformed input — a missing required field, a
        wrong type, or an unrecognized enum value — is the final catch-all and
        is rejected as ERR_INVALID_REQUEST."

        Design: Corner/entities/registration_missing_legal_name_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.create_registration(
            {"registration_functions": ["GO"]}, RC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_empty_functions_list(self):
        """PRD §3.1: "The function list must be a non-empty subset of the
        recognized function codes." PRD §2.5: "Generic malformed input — a
        missing required field, a wrong type, or an unrecognized enum value —
        is the final catch-all and is rejected as ERR_INVALID_REQUEST."

        Design: Corner/entities/registration_missing_legal_name_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.create_registration(
            {"legal_name": "Empty Funcs Co", "registration_functions": []}, RC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRegistrationInvalidFunctionCodeRejected:
    def test_unknown_function_code(self):
        """PRD §3.1: "The function list must be a non-empty subset of the
        recognized function codes — GO, GOP, TO, TOP, TP, BA, RC, IA, PC, DP,
        LSE, and RP." PRD §2.5: "an unrecognized enum value — is the final
        catch-all and is rejected as ERR_INVALID_REQUEST."

        Design: Corner/entities/registration_invalid_function_code_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.create_registration(
            create_registration_payload(legal_name="Bad Func Co",
                                        registration_functions=["GO", "XX"]), RC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_all_recognized_codes_accepted(self):
        """PRD §3.1: "The function list must be a non-empty subset of the
        recognized function codes — GO, GOP, TO, TOP, TP, BA, RC, IA, PC, DP,
        LSE, and RP."

        Design: Corner/entities/registration_invalid_function_code_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.create_registration(
            create_registration_payload(
                legal_name="All Funcs Co",
                registration_functions=["GO", "GOP", "TO", "TOP", "TP", "BA",
                                        "RC", "IA", "PC", "DP", "LSE", "RP"]), RC)
        validate_success(resp, expected_status=201)


class TestEnrollmentSelfLoggingDefaultsFalse:
    def test_default_flag_false_and_self_log_rejected(self):
        """PRD §3.1: "may flip enrollment_self_logging (which defaults to false
        when not supplied at creation)". PRD §3.6: "An entity not enrolled is
        rejected with ERR_SELF_LOG_NOT_ENROLLED."

        Design: Corner/entities/enrollment_self_logging_defaults_false
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Default Flag Co",
                                        registration_functions=["GO"]), RC))
        assert e1["enrollment_self_logging"] is False
        resp = api_client.create_self_log_entry(
            {"entity_id": e1["id"], "standard_id": "STD-GO-001", "exception_note": "x"},
            make_officer_headers(e1["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_LOG_NOT_ENROLLED)

    def test_enrollment_true_allows_self_log(self):
        """PRD §3.6: "Entities enrolled in the self-logging program — those
        whose enrollment_self_logging flag is true — may log minimal-risk
        exceptions directly."

        Design: Corner/entities/enrollment_self_logging_defaults_false
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Enrolled Co",
                                        registration_functions=["GO"],
                                        enrollment_self_logging=True), RC))
        assert e1["enrollment_self_logging"] is True
        period = get_success_data(api_client.create_review_period(AUD))
        resp = api_client.create_self_log_entry(
            {"entity_id": e1["id"], "standard_id": "STD-GO-001",
             "exception_note": "x", "period_id": period["id"]},
            make_officer_headers(e1["id"]))
        validate_success(resp, expected_status=201)


class TestPatchRegistrationRecomputesStandards:
    def test_patch_functions_recomputes_count(self):
        """PRD §3.1: "At creation, and again whenever a registration is updated,
        the server derives applicable_standards: the union, across every
        function code the entity registered under, of the standard library
        entries mapped to that code ... any such update triggers the
        applicability recomputation even if only the enrollment flag changed in
        the payload."

        Design: Corner/entities/patch_registration_recomputes_standards
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Patch Co",
                                        registration_functions=["GO"]), RC))
        before = e1["applicable_standard_count"]
        resp = api_client.patch_registration(
            e1["id"], {"registration_functions": ["TO", "BA"]}, RC)
        data = validate_success(resp)
        assert data["applicable_standard_count"] != before
        std_ids = {s["standard_id"] for s in data["applicable_standards"]}
        assert not ({"STD-GO-001", "STD-GO-002"} & std_ids)
        assert {"STD-TO-001", "STD-BA-001"} <= std_ids

    def test_patch_enrollment_flag_only(self):
        """PRD §3.1: "A registration update may change registration_functions,
        may flip enrollment_self_logging (which defaults to false when not
        supplied at creation), or both."

        Design: Corner/entities/patch_registration_recomputes_standards
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Patch2 Co",
                                        registration_functions=["GO"]), RC))
        assert e1["enrollment_self_logging"] is False
        resp = api_client.patch_registration(
            e1["id"], {"enrollment_self_logging": True}, RC)
        data = validate_success(resp)
        assert data["enrollment_self_logging"] is True


class TestGetNonexistentRegistrationReturns404:
    def test_get_missing_registration(self):
        """PRD §2.5: "every identifier referenced in the path or the body must
        resolve to an existing row, validated left-to-right along the path ...
        as ERR_NOT_FOUND."

        Design: Corner/entities/get_nonexistent_registration_returns_404
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.get_registration(NON_EXISTENT_UUID, AUD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_get_existing_registration(self):
        """PRD §4: "GET /compliance/registrations/{entityId} — Get one
        registered entity."

        Design: Corner/entities/get_nonexistent_registration_returns_404
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Found Co",
                                        registration_functions=["GO"]), RC))
        resp = api_client.get_registration(e1["id"], AUD)
        data = validate_success(resp)
        assert data["id"] == e1["id"]


class TestCipAssetIsBesDerivedFromImpactRating:
    def test_high_implies_bes_medium_not(self):
        """PRD §3.7: "The server derives is_bes_cyber_asset: it is true exactly
        when the impact rating is HIGH, and false otherwise."

        Design: Corner/entities/cip_asset_is_bes_derived_from_impact_rating
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="CIP Co",
                                        registration_functions=["GO"]), RC))
        cip = make_cip_manager_headers(e1["id"])
        hi = get_success_data(api_client.create_cip_asset(
            {"entity_id": e1["id"], "asset_name": "High One", "impact_rating": "HIGH"}, cip))
        med = get_success_data(api_client.create_cip_asset(
            {"entity_id": e1["id"], "asset_name": "Med One", "impact_rating": "MEDIUM"}, cip))
        assert hi["is_bes_cyber_asset"] is True
        assert med["is_bes_cyber_asset"] is False

    def test_low_not_bes(self):
        """PRD §3.7: "The server derives is_bes_cyber_asset: it is true exactly
        when the impact rating is HIGH, and false otherwise."

        Design: Corner/entities/cip_asset_is_bes_derived_from_impact_rating
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="CIP Low Co",
                                        registration_functions=["GO"]), RC))
        cip = make_cip_manager_headers(e1["id"])
        low = get_success_data(api_client.create_cip_asset(
            {"entity_id": e1["id"], "asset_name": "Low One", "impact_rating": "LOW"}, cip))
        assert low["is_bes_cyber_asset"] is False


class TestSystemFieldsInputIgnored:
    def test_client_supplied_id_and_version_ignored(self):
        """PRD §2.4: "id is a server-minted UUID with no type prefix ...
        version is an integer that increments by one on every mutation."

        Design: Corner/entities/system_fields_input_ignored
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.create_registration(
            {"legal_name": "SysFields Co", "registration_functions": ["GO"],
             "id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", "version": 99}, RC)
        data = validate_success(resp, expected_status=201)
        assert data["id"] != "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
        assert data["version"] == 1

    def test_created_at_server_stamped(self):
        """PRD §2.4: "created_at and updated_at are ISO 8601 UTC timestamps with
        three fractional digits."

        Design: Corner/entities/system_fields_input_ignored
        """
        from test_helpers import is_iso8601_timestamp
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.create_registration(
            create_registration_payload(legal_name="SysFields2 Co",
                                        registration_functions=["GO"]), RC)
        data = validate_success(resp, expected_status=201)
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])


class TestListPaginationEnvelope:
    def test_limit_offset_pagination(self):
        """PRD §2.3: "limit caps the number of items returned ... offset says
        how many items to skip ... the meta object of the envelope carries the
        pagination fields limit, offset, total_count, and has_more."

        Design: Corner/entities/list_pagination_envelope
        """
        set_clock("2026-09-01T00:00:00Z")
        for name in ("P1", "P2", "P3"):
            get_success_data(api_client.create_registration(
                create_registration_payload(legal_name=name,
                                            registration_functions=["GO"]), RC))
        rows1, meta1 = validate_paginated(api_client.list_registrations(
            AUD, params={"limit": 2, "offset": 0}))
        assert meta1["total_count"] == 3
        assert len(rows1) == 2
        assert meta1["has_more"] is True
        rows2, meta2 = validate_paginated(api_client.list_registrations(
            AUD, params={"limit": 2, "offset": 2}))
        assert len(rows2) == 1
        assert meta2["has_more"] is False

    def test_sorted_by_created_at_ascending(self):
        """PRD §2.3: "Every list response returns resources sorted by created_at
        in ascending order."

        Design: Corner/entities/list_pagination_envelope
        """
        set_clock("2026-09-01T00:00:00Z")
        for name in ("Q1", "Q2", "Q3"):
            get_success_data(api_client.create_registration(
                create_registration_payload(legal_name=name,
                                            registration_functions=["GO"]), RC))
        rows, meta = validate_paginated(api_client.list_registrations(AUD, params={"limit": 100}))
        stamps = [r["created_at"] for r in rows]
        assert stamps == sorted(stamps)


class TestEngagementLifecycle:
    def test_initial_state_scheduled(self):
        """PRD §3.2: "An engagement begins life SCHEDULED."

        Design: Corner/state_machines/engagement_initial_state_scheduled
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Init Co",
                                        registration_functions=["GO"]), RC))
        resp = api_client.create_engagement(
            create_engagement_payload(e1["id"],
                                      engagement_type="SELF_CERTIFICATION"), AUD)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_complete_from_scheduled_rejected(self):
        """PRD §3.2: "Completing moves IN_PROGRESS to COMPLETED." PRD §2.5:
        "the target resource must be in a state from which the requested
        transition is defined, or the request fails as ERR_INVALID_STATE."

        Design: Corner/state_machines/engagement_complete_from_scheduled_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="InvTr Co",
                                        registration_functions=["GO"]), RC))
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"]), AUD))
        resp = api_client.complete_engagement(eng["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_terminal_lockdown_on_completed(self):
        """PRD §3.2: "Starting an engagement moves it from SCHEDULED to
        IN_PROGRESS ... Completing moves IN_PROGRESS to COMPLETED ...
        Cancellation is allowed from either SCHEDULED or IN_PROGRESS." PRD §2.5:
        "the target resource must be in a state from which the requested
        transition is defined, or the request fails as ERR_INVALID_STATE."

        Design: Corner/state_machines/engagement_terminal_lockdown
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Term Co",
                                        registration_functions=["GO"]), RC))
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"]), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        get_success_data(api_client.complete_engagement(eng["id"], AUD))
        validate_error(api_client.start_engagement(eng["id"], AUD),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api_client.cancel_engagement(eng["id"], AUD),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api_client.complete_engagement(eng["id"], AUD),
                       ApiErrorId.ERR_INVALID_STATE)

    def test_start_before_period_start_rejected(self):
        """PRD §3.2: "Starting an engagement ... is permitted only once the
        logical clock has reached period_start; an early start attempt is
        rejected with ERR_ENGAGEMENT_NOT_YET_OPEN."

        Design: Corner/state_machines/engagement_start_before_period_start_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Future Co",
                                        registration_functions=["GO"]), RC))
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"],
                                      period_start="2026-10-01T00:00:00Z",
                                      period_end="2026-10-31T00:00:00Z"), AUD))
        resp = api_client.start_engagement(eng["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_YET_OPEN)

    def test_start_at_period_start_accepted(self):
        """PRD §3.2: "Starting an engagement moves it from SCHEDULED to
        IN_PROGRESS and is permitted only once the logical clock has reached
        period_start."

        Design: Corner/state_machines/engagement_start_before_period_start_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="OnTime Co",
                                        registration_functions=["GO"]), RC))
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"]), AUD))  # period starts 2026-01-01
        resp = api_client.start_engagement(eng["id"], AUD)
        data = validate_success(resp)
        assert data["status"] == "IN_PROGRESS"


class TestEvidenceDoubleAcceptRejected:
    def test_second_accept_rejected(self):
        """PRD §3.2: "Acceptance moves SUBMITTED to ACCEPTED." PRD §2.5: "the
        target resource must be in a state from which the requested transition
        is defined, or the request fails as ERR_INVALID_STATE."

        Design: Corner/state_machines/evidence_double_accept_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Idem Co",
                                        registration_functions=["GO"]), RC))
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"]), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"]), make_officer_headers(e1["id"])))
        get_success_data(api_client.accept_evidence(a1["id"], AUD))
        resp = api_client.accept_evidence(a1["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reject_after_accept_rejected(self):
        """PRD §3.2: "Both decisions are permitted only while the parent
        engagement remains IN_PROGRESS — once the engagement is completed or
        cancelled, its evidence is frozen." PRD §2.5: "the target resource must
        be in a state from which the requested transition is defined, or the
        request fails as ERR_INVALID_STATE."

        Design: Corner/state_machines/evidence_double_accept_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Idem2 Co",
                                        registration_functions=["GO"]), RC))
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"]), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"]), make_officer_headers(e1["id"])))
        get_success_data(api_client.accept_evidence(a1["id"], AUD))
        resp = api_client.reject_evidence(a1["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSelfReportInvalidSkipTriageRejected:
    def test_confirm_from_received_rejected(self):
        """PRD §3.3: "A self-report enters RECEIVED and then moves, under a
        ComplianceAuditor, from RECEIVED to TRIAGED, and from there either to
        CONFIRMED or to DISMISSED." PRD §2.5: "the target resource must be in a
        state from which the requested transition is defined, or the request
        fails as ERR_INVALID_STATE."

        Design: Corner/state_machines/self_report_invalid_skip_triage_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Skip Co",
                                        registration_functions=["GO"]), RC))
        sr = get_success_data(api_client.create_self_report(
            create_self_report_payload(e1["id"]), make_officer_headers(e1["id"])))
        resp = api_client.confirm_self_report(sr["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_triage_then_confirm_accepted(self):
        """PRD §3.3: "A self-report enters RECEIVED and then moves, under a
        ComplianceAuditor, from RECEIVED to TRIAGED, and from there either to
        CONFIRMED or to DISMISSED."

        Design: Corner/state_machines/self_report_invalid_skip_triage_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Flow Co",
                                        registration_functions=["GO"]), RC))
        sr = get_success_data(api_client.create_self_report(
            create_self_report_payload(e1["id"]), make_officer_headers(e1["id"])))
        get_success_data(api_client.triage_self_report(sr["id"], AUD))
        data = validate_success(api_client.confirm_self_report(sr["id"], AUD))
        assert data["status"] == "CONFIRMED"


class TestViolationSourceSelfReportNotConfirmedRejected:
    def test_triaged_self_report_not_a_valid_source(self):
        """PRD §3.4: "when the source type is SELF_REPORT, a
        source_self_report_id must be supplied referencing a self-report in
        CONFIRMED status. Violations whose source references are missing,
        mismatched, or not in the required terminal state are rejected with
        ERR_VIOLATION_SOURCE_INVALID."

        Design: Corner/validations/violation_source_self_report_not_confirmed_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Src Co",
                                        registration_functions=["GO"]), RC))
        sr = get_success_data(api_client.create_self_report(
            create_self_report_payload(e1["id"]), make_officer_headers(e1["id"])))
        get_success_data(api_client.triage_self_report(sr["id"], AUD))
        resp = api_client.create_violation(
            create_violation_payload(e1["id"], source_type="SELF_REPORT",
                                     source_self_report_id=sr["id"]), AUD)
        validate_error(resp, ApiErrorId.ERR_VIOLATION_SOURCE_INVALID)

    def test_confirmed_self_report_is_a_valid_source(self):
        """PRD §3.4: "when the source type is SELF_REPORT, a
        source_self_report_id must be supplied referencing a self-report in
        CONFIRMED status."

        Design: Corner/validations/violation_source_self_report_not_confirmed_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Src2 Co",
                                        registration_functions=["GO"]), RC))
        sr = get_success_data(api_client.create_self_report(
            create_self_report_payload(e1["id"]), make_officer_headers(e1["id"])))
        get_success_data(api_client.triage_self_report(sr["id"], AUD))
        get_success_data(api_client.confirm_self_report(sr["id"], AUD))
        resp = api_client.create_violation(
            create_violation_payload(e1["id"], source_type="SELF_REPORT",
                                     source_self_report_id=sr["id"]), AUD)
        data = validate_success(resp, expected_status=201)
        assert data["source_type"] == "SELF_REPORT"
        # PRD §3.4 self-report discount: 1000 * 0.6 = 600.00
        assert data["proposed_penalty"] == pytest.approx(600.00, abs=0.005)


class TestViolationCreateDependsOnEngagementCompleted:
    def test_in_progress_engagement_source_rejected(self):
        """PRD §3.4: "When the source type is AUDIT or SPOT_CHECK, a
        source_engagement_id must be supplied referencing an engagement of the
        matching type that has reached COMPLETED; ... Violations whose source
        references are missing, mismatched, or not in the required terminal
        state are rejected with ERR_VIOLATION_SOURCE_INVALID."

        Design: Difficulty/cross_entity_state_dependency/violation_create_depends_on_engagement_completed
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="GenCo XEnt",
                                        registration_functions=["GO"]), RC))
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"]), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        resp = api_client.create_violation(
            create_violation_payload(
                e1["id"], source_type="AUDIT",
                violation_start="2026-01-10T00:00:00Z",
                violation_end="2026-01-11T00:00:00Z",
                source_engagement_id=eng["id"]), AUD)
        validate_error(resp, ApiErrorId.ERR_VIOLATION_SOURCE_INVALID)

    def test_completed_engagement_source_accepted(self):
        """PRD §3.4: "When the source type is AUDIT or SPOT_CHECK, a
        source_engagement_id must be supplied referencing an engagement of the
        matching type that has reached COMPLETED."

        Design: Difficulty/cross_entity_state_dependency/violation_create_depends_on_engagement_completed
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="GenCo XEnt2",
                                        registration_functions=["GO"]), RC))
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"]), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        get_success_data(api_client.complete_engagement(eng["id"], AUD))
        resp = api_client.create_violation(
            create_violation_payload(
                e1["id"], source_type="AUDIT",
                violation_start="2026-01-10T00:00:00Z",
                violation_end="2026-01-11T00:00:00Z",
                source_engagement_id=eng["id"]), AUD)
        validate_success(resp, expected_status=201)


class TestInvalidIntervalViolationEndBeforeStart:
    def test_equal_start_end_rejected(self):
        """PRD §3.4: "a violation interval from violation_start to violation_end
        (end strictly after start, else ERR_INVALID_INTERVAL)."

        Design: Corner/validations/invalid_interval_violation_end_before_start
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Intv Co",
                                        registration_functions=["GO"]), RC))
        resp = api_client.create_violation(
            create_violation_payload(e1["id"],
                                     violation_start="2026-01-01T00:00:00Z",
                                     violation_end="2026-01-01T00:00:00Z"), AUD)
        validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL)

    def test_end_after_start_accepted(self):
        """PRD §3.4: "a violation interval from violation_start to violation_end
        (end strictly after start, else ERR_INVALID_INTERVAL)."

        Design: Corner/validations/invalid_interval_violation_end_before_start
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Intv2 Co",
                                        registration_functions=["GO"]), RC))
        v = create_violation(e1["id"])
        assert v["status"] == "OPEN"


class TestCipAccessLogEvidenceRequiresBesAsset:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="CipEv Co",
                                        registration_functions=["GO"]), RC))
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"]), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        cip = make_cip_manager_headers(e1["id"])
        ca_med = get_success_data(api_client.create_cip_asset(
            {"entity_id": e1["id"], "asset_name": "Med", "impact_rating": "MEDIUM"}, cip))
        ca_hi = get_success_data(api_client.create_cip_asset(
            {"entity_id": e1["id"], "asset_name": "High", "impact_rating": "HIGH"}, cip))
        return e1, eng, ca_med, ca_hi

    def test_medium_asset_reference_rejected(self):
        """PRD §3.2: "When the artifact kind is ACCESS_LOG, a CIP requirement
        applies: the artifact must carry a non-null cip_asset_id referencing an
        asset that is currently ACTIVE and flagged as a BES cyber asset; an
        access-log artifact without such a reference is rejected with
        ERR_CIP_EVIDENCE_REQUIRED."

        Design: Corner/validations/cip_access_log_evidence_requires_bes_asset
        """
        e1, eng, ca_med, ca_hi = self._setup()
        resp = api_client.create_evidence(
            create_evidence_payload(eng["id"], artifact_kind="ACCESS_LOG",
                                    coverage_start="2026-01-01T00:00:00Z",
                                    coverage_end="2026-01-15T00:00:00Z",
                                    cip_asset_id=ca_med["id"]),
            make_officer_headers(e1["id"]))
        validate_error(resp, ApiErrorId.ERR_CIP_EVIDENCE_REQUIRED)

    def test_high_active_asset_reference_accepted(self):
        """PRD §3.2: "the artifact must carry a non-null cip_asset_id
        referencing an asset that is currently ACTIVE and flagged as a BES cyber
        asset."

        Design: Corner/validations/cip_access_log_evidence_requires_bes_asset
        """
        e1, eng, ca_med, ca_hi = self._setup()
        resp = api_client.create_evidence(
            create_evidence_payload(eng["id"], artifact_kind="ACCESS_LOG",
                                    coverage_start="2026-01-01T00:00:00Z",
                                    coverage_end="2026-01-15T00:00:00Z",
                                    cip_asset_id=ca_hi["id"]),
            make_officer_headers(e1["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SUBMITTED"


class TestStandardNotApplicableOnEngagementCreate:
    def test_out_of_scope_standard_rejected(self):
        """PRD §3.2: "Every standard named in scope must belong to the target
        entity's applicable_standards; naming a standard the entity is not
        registered for is rejected with ERR_STANDARD_NOT_APPLICABLE."

        Design: Corner/validations/standard_not_applicable_on_engagement_create
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Scope Co",
                                        registration_functions=["GO"]), RC))
        resp = api_client.create_engagement(
            create_engagement_payload(e1["id"], standard_ids=["STD-TO-001"]), AUD)
        validate_error(resp, ApiErrorId.ERR_STANDARD_NOT_APPLICABLE)

    def test_in_scope_standard_accepted(self):
        """PRD §3.2: "Every standard named in scope must belong to the target
        entity's applicable_standards."

        Design: Corner/validations/standard_not_applicable_on_engagement_create
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Scope2 Co",
                                        registration_functions=["GO"]), RC))
        resp = api_client.create_engagement(
            create_engagement_payload(e1["id"], standard_ids=["STD-GO-001"]), AUD)
        validate_success(resp, expected_status=201)


class TestMitigationPlanForOtherEntitysViolationForbidden:
    def test_other_entity_plan_submission_forbidden(self):
        """PRD §2.5: "referential ownership (an entity-scoped caller acting only
        on its own entity's resources, else ERR_FORBIDDEN)." PRD §2.1: "When
        X-User-Role is EntityComplianceOfficer, X-User-ID is the id of the
        acting RegisteredEntity; ownership checks on any resource that
        references a RegisteredEntity compare the resource's foreign-key field
        ... to X-User-ID."

        Design: Corner/validations/mitigation_plan_for_other_entitys_violation_forbidden
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Owner Co",
                                        registration_functions=["GO"]), RC))
        e2 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Other Co",
                                        registration_functions=["GO"]), RC))
        v = create_violation(e1["id"])
        resp = api_client.create_mitigation_plan(
            v["id"], {"description": "not mine",
                      "expected_violation_version": v["version"]},
            make_officer_headers(e2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_own_entity_plan_submission_allowed(self):
        """PRD §2.5: "referential ownership (an entity-scoped caller acting only
        on its own entity's resources, else ERR_FORBIDDEN)."

        Design: Corner/validations/mitigation_plan_for_other_entitys_violation_forbidden
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="Owner2 Co",
                                        registration_functions=["GO"]), RC))
        v = create_violation(e1["id"])
        resp = api_client.create_mitigation_plan(
            v["id"], {"description": "mine",
                      "expected_violation_version": v["version"]},
            make_officer_headers(e1["id"]))
        validate_success(resp, expected_status=201)
