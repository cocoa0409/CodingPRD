"""Corner coverage indexed under the validation surface."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    STAFF, LICENSING,
    api_client, set_clock, create_society, create_applicant, create_meeting,
    create_cycle, create_change, docket, open_meeting, cast_vote,
    create_licence_and_territory, setup_submitted_change_in_cycle,
)


class TestSponsorRequiredOnSubmission:
    @pytest.fixture
    def unsponsored_change(self, api):
        """An open cycle around an unenrolled change that carries no society.

        PRD SS2.10: expected_change_version must equal the current version of the
        named change, so the probe echoes the change's own version. PRD SS3.6:
        enrolment may occur only while the logical clock is at or before the
        cycle's comment_close, so the window is placed around the clock. The
        change has not been enrolled and carries no society, which is the state
        the sponsor rule reads.
        """
        return setup_submitted_change_in_cycle(
            change_code="00081", meeting_code="DEC2030", meeting_month="DECEMBER",
            year=2030, capacity=400, sponsored=False, submit=False,
            meeting_starts="2030-12-09T14:00:00Z", meeting_ends="2030-12-09T23:00:00Z",
        )

    def test_submission_without_a_sponsoring_society_is_refused(self, api, unsponsored_change):
        """PRD §3.6: "A change entering the pool must also carry a sponsoring society
        on record. A change whose society_id is null is refused with
        ERR_SPONSOR_REQUIRED at 422."

        Design: Corner/validations/sponsor_required_on_cycle_submission
        """
        bundle = unsponsored_change
        response = api.submit_release_cycle_changes(
            bundle["cycle"]["id"],
            {"change_ids": [bundle["change"]["id"]],
             "expected_change_version": bundle["version_at_creation"]},
            STAFF,
        )
        validate_error(response, ApiErrorId.ERR_SPONSOR_REQUIRED, expected_status=422)

    def test_refused_submission_leaves_the_change_unenrolled(self, api, unsponsored_change):
        """PRD §2.12: "A cascade is not a partial write — a request that requires a
        cascade either performs all of its hops or fails." The refused submission
        fails the sponsor hop, so the enrolment hop must not have run and the
        change's release link and target effective date stay unset.

        Design: Corner/validations/sponsor_required_on_cycle_submission
        """
        bundle = unsponsored_change
        api.submit_release_cycle_changes(
            bundle["cycle"]["id"],
            {"change_ids": [bundle["change"]["id"]],
             "expected_change_version": bundle["version_at_creation"]},
            STAFF,
        )
        row = validate_success(api.get_code_change(bundle["change"]["id"], STAFF))
        assert row["cycle_id"] is None
        assert row["effective_date"] is None


class TestProviderInterpretationEntitlement:
    @pytest.fixture
    def provider_request(self, api):
        """An active provider licence with an interpretation request filed against it."""
        set_clock("2026-09-01T00:00:00Z")
        licence, territory = create_licence_and_territory(
            territory_code="US-CAROLINAS", method="SITE", licensee_type="PROVIDER",
            licensee_name="Carolinas Clinic", sales_unit_count=9, expected_users=14,
            activate=True,
        )
        request = validate_success(api.create_interpretation_request(
            {
                "requesting_licensee_id": licence["id"],
                "code": "00001",
                "question": "Does the parenthetical apply to the family?",
            },
            LICENSING,
        ), 201)
        return {"licence": licence, "request": request}

    def test_a_provider_licence_is_never_entitled_to_an_interpretation(self, api, provider_request):
        """PRD §3.10: "It is not entitled when the licence class is PROVIDER".
        PRD §3.10: "Answering a request requires entitlement_status to be ENTITLED; an
        answer attempted against a not-entitled request is rejected with
        ERR_NOT_ENTITLED at 403."

        Design: Corner/validations/provider_interpretation_request_not_entitled
        """
        request = provider_request["request"]
        response = api.answer_interpretation_request(
            request["id"],
            {"answer_text": "Yes, the parenthetical governs the whole family."},
            STAFF,
        )
        validate_error(response, ApiErrorId.ERR_NOT_ENTITLED, expected_status=403)

    def test_the_request_row_records_the_derived_entitlement(self, api, provider_request):
        """PRD §3.10: "Its entitlement is derived, not declared: a request is entitled
        when the licence named by requesting_licensee_id is ACTIVE, and it is also
        entitled when that licence is an EDUCATOR licence in any non-terminated status.
        It is not entitled when the licence class is PROVIDER".
        PRD §3.10: "The outcome is stored in entitlement_status as ENTITLED or
        NOT_ENTITLED, and the request itself opens in response_status PENDING."

        Design: Corner/validations/provider_interpretation_request_not_entitled
        """
        request = provider_request["request"]
        api.answer_interpretation_request(
            request["id"],
            {"answer_text": "Yes, the parenthetical governs the whole family."},
            STAFF,
        )
        row = validate_success(api.get_interpretation_request(request["id"], LICENSING))
        assert row["entitlement_status"] == "NOT_ENTITLED"
        assert row["response_status"] == "PENDING"


class TestHighPriorityErrorWinsDualFailure:
    @pytest.fixture
    def descriptor_taken(self):
        set_clock("2026-09-01T00:00:00Z")
        applicant = create_applicant("Dual Applicant", "MANUFACTURER")
        create_change("00090", applicant["id"], tier="TIER_I", volume=5000,
                      descriptor_current="Placeholder descriptor")
        return {"applicant": applicant}

    def test_duplicate_descriptor_outranks_the_evidence_shortfall(self, api, descriptor_taken):
        """PRD §3.1: "Where a filing violates more than one rule at once, the descriptor
        format check runs before the uniqueness check, and both run before the evidence
        sufficiency check".
        PRD §2.7: "Filing a second change bearing a descriptor number that already
        exists is rejected with ERR_CODE_ALREADY_EXISTS at 409".
        PRD §2.7: "A TIER_IV addition below that volume is rejected with
        ERR_EVIDENCE_INSUFFICIENT at 422."

        Design: Corner/validations/high_priority_error_wins_dual_failure
        """
        applicant = descriptor_taken["applicant"]
        response = api.create_code_change(
            {
                "code": "00090",
                "change_type": "ADDITION",
                "category": "CATEGORY_I",
                "code_family": "000",
                "applicant_id": applicant["id"],
                "clinical_evidence_tier": "TIER_IV",
                "procedure_volume_threshold": 30,
                "descriptor_current": "Other placeholder",
            },
            STAFF,
        )
        validate_error(response, ApiErrorId.ERR_CODE_ALREADY_EXISTS, expected_status=409)

    def test_only_one_row_survives_for_the_contested_descriptor(self, api, descriptor_taken):
        """PRD §2.7: "Descriptor numbers are unique across the entire code change corpus."

        Design: Corner/validations/high_priority_error_wins_dual_failure
        """
        applicant = descriptor_taken["applicant"]
        api.create_code_change(
            {
                "code": "00090",
                "change_type": "ADDITION",
                "category": "CATEGORY_I",
                "code_family": "000",
                "applicant_id": applicant["id"],
                "clinical_evidence_tier": "TIER_IV",
                "procedure_volume_threshold": 30,
                "descriptor_current": "Other placeholder",
            },
            STAFF,
        )
        rows, meta = validate_paginated(api.list_code_changes(STAFF, {"code": "00090"}))
        assert meta["total_count"] == 1
        assert len(rows) == 1