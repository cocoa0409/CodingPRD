"""Eligibility case lifecycle: creation defaults, submit gates, the
more-info revision loop, reconstruction, and decision integrity."""
from test_helpers import (
    ApiErrorId,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)
from test_helpers import factories, fixtures
from test_helpers.fixtures import (
    APPLICANT,
    OFFICER_A,
    OFFICER_B,
    OFFICER_C,
    add_evidence,
    add_service_record,
    build_case,
    reconstruct_case,
    submit_case,
)


class TestCaseCreation:
    def test_create_direct_case_returns_system_defaults(self, api):
        """PRD §3.1: "An `EligibilityApplicant` opens an eligibility case by
        supplying the `applicant_legal_name` exactly as it appears on the
        submitted documentation, the `applicant_dob` as an ISO 8601 date, and
        the `basis_type`... The case is persisted in `INTAKE` status."
        PRD §3.1: "A direct-service or cadet case must leave both null. An
        optional boolean `adoption_or_divorce_flag`, defaulting to `false`...
        Until approval, the case's `member_id`, `eligibility_category`,
        `verification_officer_id`, `record_reconstruction_officer_id`,
        `denial_reason`, and `decision_note` are all null."

        Design: Corner/entities/eligibility_case_create_returns_system_defaults
        """
        resp = api.create_eligibility_case(
            {
                "applicant_legal_name": "Wes Warden",
                "applicant_dob": "1986-04-04",
                "basis_type": "DIRECT_SERVICE",
            },
            APPLICANT,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        case = body["data"]
        assert case["status"] == "INTAKE"
        assert case["version"] == 1
        assert case["member_id"] is None
        assert case["eligibility_category"] is None
        assert case["sponsor_member_id"] is None
        assert case["claimed_relationship"] is None
        assert case["adoption_or_divorce_flag"] is False
        assert is_valid_uuid(case["id"])
        assert is_iso8601_timestamp(case["created_at"])
        assert is_iso8601_timestamp(case["updated_at"])

    def test_create_case_missing_applicant_dob_rejected(self, api):
        """PRD §2.7: "(4) request-body well-formedness — every required input
        field present and every enum field carrying a declared value —
        producing `ERR_INVALID_REQUEST`".

        Design: Corner/entities/eligibility_case_missing_required_field_rejected
        """
        resp = api.create_eligibility_case(
            {"applicant_legal_name": "No Dob", "basis_type": "DIRECT_SERVICE"},
            APPLICANT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_create_case_undeclared_basis_type_rejected(self, api):
        """PRD §3.1: "the `basis_type` — one of `DIRECT_SERVICE`,
        `FAMILY_DERIVATION`, or `CADET_APPOINTMENT`."
        PRD §2.7: "every enum field carrying a declared value — producing
        `ERR_INVALID_REQUEST`".

        Design: Corner/entities/eligibility_case_invalid_enum_rejected
        """
        resp = api.create_eligibility_case(
            {
                "applicant_legal_name": "Enum Err",
                "applicant_dob": "1980-01-01",
                "basis_type": "ALIEN_SERVICE",
            },
            APPLICANT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestSubmitGates:
    def test_submit_without_evidence_rejected(self, api):
        """PRD §3.3: "no case of any basis can be submitted without at least
        one evidence document, failing with `ERR_EVIDENCE_REQUIRED`."

        Design: Difficulty/boundary_precision_check/evidence_presence_empty_set_boundary_on_submit
        """
        case = build_case(api, applicant_legal_name="No Doc")
        add_service_record(api, case["id"])
        resp = api.submit_case(case["id"], APPLICANT)
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_REQUIRED)
        current = validate_success(api.get_eligibility_case(case["id"], OFFICER_A))
        assert current["status"] == "INTAKE"

    def test_submit_without_service_record_rejected(self, api):
        """PRD §3.3: "A case on the direct-service or cadet basis cannot be
        submitted without at least one service record, failing with
        `ERR_SERVICE_RECORD_REQUIRED`"

        Design: Difficulty/boundary_precision_check/evidence_presence_empty_set_boundary_on_submit
        """
        case = build_case(api, applicant_legal_name="No Rec")
        add_evidence(api, case["id"])
        resp = api.submit_case(case["id"], APPLICANT)
        validate_error(resp, ApiErrorId.ERR_SERVICE_RECORD_REQUIRED)
        current = validate_success(api.get_eligibility_case(case["id"], OFFICER_A))
        assert current["status"] == "INTAKE"


class TestMoreInfoRevisionLoop:
    def _case_in_more_info_required(self, api):
        case = build_case(api, applicant_legal_name="Eli Guard")
        record = add_service_record(api, case["id"])
        add_evidence(
            api, case["id"], content_hash="loop-h1",
            doc_type="NGB22", covers_service_record_id=record["id"],
        )
        submit_case(api, case["id"])
        decided = fixtures.decide_case(
            api, case["id"], "REQUEST_MORE_INFO",
            officer=OFFICER_A, decision_note="need clearer NGB-22",
        )
        assert decided["status"] == "MORE_INFO_REQUIRED"
        return case, record

    def test_resubmit_without_new_evidence_rejected(self, api):
        """PRD §3.3: "resubmission back to `UNDER_REVIEW` requires at least
        one additional evidence document uploaded since the case entered
        `MORE_INFO_REQUIRED`, failing with `ERR_NO_NEW_EVIDENCE` otherwise."

        Design: Difficulty/non_linear_state_machine/eligibility_case_more_info_revision_loop
        """
        case, _ = self._case_in_more_info_required(api)
        resp = api.submit_case(case["id"], APPLICANT)
        validate_error(resp, ApiErrorId.ERR_NO_NEW_EVIDENCE)
        current = validate_success(api.get_eligibility_case(case["id"], OFFICER_A))
        assert current["status"] == "MORE_INFO_REQUIRED"

    def test_resubmit_with_new_evidence_returns_to_under_review(self, api):
        """PRD §3.3: "A decision of `REQUEST_MORE_INFO` moves the case to
        `MORE_INFO_REQUIRED` and records the note; the applicant may then
        upload further evidence, and resubmission back to `UNDER_REVIEW`
        requires at least one additional evidence document uploaded since the
        case entered `MORE_INFO_REQUIRED`... This review loop is unbounded."

        Design: Difficulty/non_linear_state_machine/eligibility_case_more_info_revision_loop
        """
        case, record = self._case_in_more_info_required(api)
        add_evidence(
            api, case["id"], content_hash="loop-h2",
            doc_type="NGB22", covers_service_record_id=record["id"],
        )
        resubmitted = validate_success(api.submit_case(case["id"], APPLICANT))
        assert resubmitted["status"] == "UNDER_REVIEW"


class TestDecideStatePreconditions:
    def test_decide_from_intake_rejected(self, api):
        """PRD §2.7: "(5) state-machine preconditions on state-transition
        endpoints, producing `ERR_INVALID_STATE`".
        PRD §3.3: "A `VerificationOfficer` then decides the case" — after
        "Submission moves a case from `INTAKE` to `UNDER_REVIEW`."

        Design: Corner/state_machines/case_decide_from_intake_returns_invalid_state
        """
        case = build_case(api, applicant_legal_name="Skip Submit")
        record = add_service_record(api, case["id"])
        add_evidence(api, case["id"], covers_service_record_id=record["id"])
        resp = api.decide_case(case["id"], {"decision": "APPROVE"}, OFFICER_B)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = validate_success(api.get_eligibility_case(case["id"], OFFICER_A))
        assert current["status"] == "INTAKE"
        assert current["member_id"] is None

    def test_second_approve_on_approved_case_rejected(self, api):
        """PRD §3.3: "A decision of `DENY` moves the case to `DENIED` and
        records the supplied `denial_reason`; a denied case becomes
        immutable." PRD §2.7: "(5) state-machine preconditions on
        state-transition endpoints, producing `ERR_INVALID_STATE`"

        Design: Corner/state_machines/decide_idempotency_second_approve_rejected
        """
        decided, member_id = fixtures.approve_direct_member(
            api, name="Twice Tina"
        )
        assert decided["status"] == "APPROVED"
        resp = api.decide_case(decided["id"], {"decision": "APPROVE"}, OFFICER_C)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = validate_success(api.get_eligibility_case(decided["id"], OFFICER_A))
        assert current["member_id"] == member_id


class TestRecordReconstruction:
    def test_reconstruction_deny_moves_case_to_denied(self, api):
        """PRD §3.4: "A reconstruction `DENY` moves the case directly to
        `DENIED`." and "records the acting officer's `X-User-ID` as the
        case's `record_reconstruction_officer_id`".

        Design: Corner/errors/error_catalog_triggerable_reconstruction_deny
        """
        case = build_case(api, applicant_legal_name="Recon Rick")
        record = add_service_record(api, case["id"])
        add_evidence(api, case["id"], covers_service_record_id=record["id"])
        submit_case(api, case["id"])
        resp = api.record_reconstruction(
            case["id"],
            {"decision": "DENY",
             "decision_note": "archives search exhausted, records unrecoverable"},
            OFFICER_A,
        )
        denied = validate_success(resp)
        assert denied["status"] == "DENIED"
        assert denied["member_id"] is None
        assert denied["record_reconstruction_officer_id"] == "officer-A"


class TestSegregationOfDuties:
    def _reconstructed_under_review_case(self, api):
        case = build_case(api, applicant_legal_name="Sod Steve")
        record = add_service_record(api, case["id"])
        add_evidence(api, case["id"], covers_service_record_id=record["id"])
        submit_case(api, case["id"])
        reconstruct_case(api, case["id"])  # recorded by officer A
        return case

    def test_reconstructing_officer_cannot_approve(self, api):
        """PRD §2.6: "at decide time the acting officer's `X-User-ID` must
        differ from the case's `record_reconstruction_officer_id`, and a
        match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/same_officer_reconstruct_then_approve_denied_sod
        """
        case = self._reconstructed_under_review_case(api)
        resp = api.decide_case(case["id"], {"decision": "APPROVE"}, OFFICER_A)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        current = validate_success(api.get_eligibility_case(case["id"], OFFICER_A))
        assert current["status"] == "UNDER_REVIEW"

    def test_different_officer_approves_after_sod_rejection(self, api):
        """PRD §2.6: "at decide time the acting officer's `X-User-ID` must
        differ from the case's `record_reconstruction_officer_id`, and a
        match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.3: "A decision of `APPROVE` runs the full adjudication gate
        described next."

        Design: Corner/validations/same_officer_reconstruct_then_approve_denied_sod
        """
        case = self._reconstructed_under_review_case(api)
        validate_error(
            api.decide_case(case["id"], {"decision": "APPROVE"}, OFFICER_A),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403,
        )
        approved = validate_success(
            api.decide_case(case["id"], {"decision": "APPROVE"}, OFFICER_B)
        )
        assert approved["status"] == "APPROVED"
        assert approved["member_id"] is not None

    def test_state_check_masks_sod_on_terminal_case(self, api):
        """PRD §2.7: "Validations are applied in a fixed priority order on
        every request, and an earlier failure masks every later one... (5)
        state-machine preconditions on state-transition endpoints, producing
        `ERR_INVALID_STATE`; then (6) onward, the business checks...
        segregation of duties..."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_case_decide
        """
        case = build_case(api, applicant_legal_name="Ned Null")
        record = add_service_record(
            api, case["id"],
            discharge_characterization="GENERAL_UNDER_HONORABLE",
        )
        add_evidence(api, case["id"], covers_service_record_id=record["id"])
        submit_case(api, case["id"])
        reconstruct_case(api, case["id"])  # officer A recorded
        fixtures.decide_case(
            api, case["id"], "DENY", officer=OFFICER_B,
            decision_note="insufficient character of service",
        )
        # officer A would trip segregation of duties, but the DENIED case is
        # terminal: the state check fires first.
        resp = api.decide_case(case["id"], {"decision": "APPROVE"}, OFFICER_A)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        current = validate_success(api.get_eligibility_case(case["id"], OFFICER_A))
        assert current["status"] == "DENIED"
        assert current["member_id"] is None

    def test_state_check_masks_sod_on_terminal_case_repeat_denied(self, api):
        """PRD §2.7: "an earlier failure masks every later one... (5)
        state-machine preconditions on state-transition endpoints, producing
        `ERR_INVALID_STATE`; then (6) onward, the business checks".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_case_decide
        """
        # Same priority pair, second leg: the reconstructing officer repeats
        # a DENY decision on the already-DENIED case — still the state error.
        case = build_case(api, applicant_legal_name="Ned Null Two")
        record = add_service_record(api, case["id"])
        add_evidence(api, case["id"], covers_service_record_id=record["id"])
        submit_case(api, case["id"])
        reconstruct_case(api, case["id"])
        fixtures.decide_case(
            api, case["id"], "DENY", officer=OFFICER_B,
            decision_note="insufficient",
        )
        resp = api.decide_case(
            case["id"], {"decision": "DENY", "decision_note": "again"}, OFFICER_A
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestApprovalEffects:
    def test_approval_response_immediately_reflects_minted_member(self, api):
        """PRD §3.3: "A successful approval mints the `Member`. The new
        member receives the next sequential `member_number`, a `legal_name`
        and `dob` copied from the case, the derived `eligibility_category`,
        and a `case_id` back-reference to the approving case — unique per
        member — while the case's `member_id` is set to the new row."

        Design: Corner/consistency_model/approval_response_immediately_reflects_minted_member
        """
        decided, member_id = fixtures.approve_direct_member(api, name="Imm Ivan")
        assert decided["member_id"] == member_id
        assert decided["status"] == "APPROVED"
        assert decided["eligibility_category"] == "VETERAN_HONORABLE"
        member = validate_success(api.get_member(member_id, OFFICER_B))
        assert member["status"] == "ACTIVE"
        assert member["member_number"] is not None
        assert member["eligibility_category"] == "VETERAN_HONORABLE"

    def test_first_member_number_is_zero_padded_one(self, api):
        """PRD §2.4: "The `Member` resource additionally carries
        `member_number`, a zero-padded ten-digit sequential number assigned
        at the moment a case is approved. The first member ever minted
        receives `0000000001`..."

        Design: Corner/entities/member_get_returns_stored_row_with_member_number
        """
        decided, member_id = fixtures.approve_direct_member(
            api, name="First Member", start="2001-01-01", end="2007-01-01"
        )
        member = validate_success(api.get_member(member_id, OFFICER_A))
        assert member["member_number"] == "0000000001"
        assert member["legal_name"] == "First Member"
        assert member["eligibility_category"] == "VETERAN_HONORABLE"
        assert member["lineage_depth"] == 0
        assert member["status"] == "ACTIVE"
        assert member["deployment_posture"] == "NONE"

    def test_bad_conduct_discharge_fails_derivation(self, api):
        """PRD §3.3: "A `DIRECT_SERVICE` case inspects its single service
        record: a discharge characterization of `OTHER_THAN_HONORABLE`,
        `BAD_CONDUCT`, or `DISHONORABLE` fails the derivation outright..."
        and "Then the derivation rule itself runs, failing with
        `ERR_ELIGIBILITY_DERIVATION_FAILED` when unsatisfied."

        Design: Corner/calculations/category_assignment_bad_conduct_discharge_denied
        """
        case = build_case(api, applicant_legal_name="Bad Paper")
        record = add_service_record(
            api, case["id"], discharge_characterization="BAD_CONDUCT",
            branch="NAVY",
        )
        add_evidence(api, case["id"], covers_service_record_id=record["id"])
        submit_case(api, case["id"])
        reconstruct_case(
            api, case["id"],
            decision_note="record verified, characterization confirmed",
        )
        resp = api.decide_case(case["id"], {"decision": "APPROVE"}, OFFICER_B)
        validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_DERIVATION_FAILED)
        current = validate_success(api.get_eligibility_case(case["id"], OFFICER_A))
        assert current["status"] == "UNDER_REVIEW"
        assert current["member_id"] is None

    def test_system_derived_member_fields_on_family_approval(self, api):
        """PRD §3.3: "The `lineage_depth` is 0 for a direct-service or cadet
        basis, and the sponsor's `lineage_depth` plus one for a derived
        member; `sponsor_member_id` and `claimed_relationship` are copied
        onto the member for derived members and remain null for
        direct-service members." PRD §2.4: "the counter advances by one per
        approval".

        Design: Corner/entities/member_system_fields_client_input_ignored
        """
        _, sponsor_id = fixtures.approve_direct_member(api, name="Sys Parent")
        _, child_id = fixtures.approve_family_member(
            api, sponsor_id, "CHILD", name="Sys Child",
            doc_type="BIRTH_CERTIFICATE",
        )
        sponsor = validate_success(api.get_member(sponsor_id, OFFICER_A))
        child = validate_success(api.get_member(child_id, OFFICER_A))
        assert child["lineage_depth"] == sponsor["lineage_depth"] + 1
        assert child["sponsor_member_id"] == sponsor_id
        assert int(child["member_number"]) == int(sponsor["member_number"]) + 1


class TestEvidenceUploadStates:
    def test_evidence_upload_to_denied_case_rejected(self, api):
        """PRD §3.2: "Evidence documents attach to cases in `INTAKE`,
        `MORE_INFO_REQUIRED`, or `APPROVED`; post-approval uploads exist to
        support reinstatement evidence and audit trails, while uploads to a
        `DENIED` case are rejected with `ERR_INVALID_STATE`."

        Design: Corner/endpoints/evidence_upload_to_denied_case_rejected
        """
        case = build_case(api, applicant_legal_name="Deny Dana")
        record = add_service_record(api, case["id"])
        add_evidence(api, case["id"], covers_service_record_id=record["id"],
                     content_hash="deny-h1")
        submit_case(api, case["id"])
        fixtures.decide_case(
            api, case["id"], "DENY", officer=OFFICER_B,
            decision_note="insufficient",
        )
        resp = api.upload_evidence(
            case["id"], factories.evidence_payload(content_hash="deny-h2"),
            APPLICANT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
