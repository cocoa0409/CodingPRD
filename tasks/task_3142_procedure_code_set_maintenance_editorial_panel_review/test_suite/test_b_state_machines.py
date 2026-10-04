"""Corner coverage indexed under the state-machine surface."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    CHAIR, STAFF,
    api_client, set_clock, create_society, create_applicant, create_meeting,
    create_change, docket, open_meeting, cast_vote,
)


class TestAdministrativeReturnFromDraft:
    @pytest.fixture
    def draft_change(self):
        set_clock("2026-09-01T00:00:00Z")
        applicant = create_applicant("Return Applicant", "PHYSICIAN")
        change = create_change("00062", applicant["id"], volume=700)
        return {"applicant": applicant, "change": change}

    def test_a_draft_change_has_no_administrative_return_transition(self, api, draft_change):
        """PRD §3.2: "A posted change whose screening is ADMIN_COMPLETE may be returned
        to administrative review through the reason field".
        PRD §3.5: "Where a change's review_status does not admit the operation being
        requested at all, the rejection is ERR_INVALID_STATE at 409."

        Design: Corner/state_machines/change_administrative_return_from_draft_returns_invalid_state
        """
        change = draft_change["change"]
        response = api.administrative_return_code_change(
            change["id"], {"reason": "Not posted yet"}, STAFF)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_refused_return_leaves_the_screening_status_untouched(self, api, draft_change):
        """PRD §2.4: "Every newly filed CodeChange begins in UNDER_ADMIN_REVIEW".

        Design: Corner/state_machines/change_administrative_return_from_draft_returns_invalid_state
        """
        change = draft_change["change"]
        api.administrative_return_code_change(change["id"], {"reason": "Not posted yet"}, STAFF)
        row = validate_success(api.get_code_change(change["id"], STAFF))
        assert row["review_status"] == "DRAFT"
        assert row["administrative_review_status"] == "UNDER_ADMIN_REVIEW"


class TestApprovedChangeTerminalLock:
    @pytest.fixture
    def approved_change(self, api):
        """A change already determined APPROVED at a closed meeting."""
        set_clock("2026-09-01T00:00:00Z")
        society = create_society("Terminal Society", "TRM", seats=1)
        applicant = create_applicant("Terminal Applicant", "SPECIALTY_SOCIETY",
                                     society_id=society["id"])
        meeting = create_meeting("FEB2026", "FEBRUARY",
                                 "2026-02-09T14:00:00Z", "2026-02-09T23:00:00Z")
        change = create_change("00063", applicant["id"], society_id=society["id"],
                               volume=4000, organ_systems=1,
                               descriptor_proposed="First placeholder revised")
        fillers = [
            create_change("00064", applicant["id"], society_id=society["id"],
                          descriptor_current="Second placeholder"),
            create_change("00065", applicant["id"], society_id=society["id"],
                          descriptor_current="Third placeholder"),
        ]
        docket(meeting["id"], [change["id"]] + [f["id"] for f in fillers])
        open_meeting(meeting["id"])
        approved = validate_success(api.determine_code_change(
            change["id"],
            {"determination": "APPROVED", "determination_basis": "Evidence is sufficient"},
            CHAIR,
        ))
        return {"society": society, "change": approved}

    def test_an_approved_change_cannot_be_reverted_to_draft(self, api, approved_change):
        """PRD §3.5: "It is worth stating plainly that a change whose determination is
        already APPROVED is terminal and may not be reverted to draft; such an attempt
        is rejected with ERR_ALREADY_TERMINAL at 409."
        PRD §3.5: "A change whose determination is APPROVED cannot travel this path at all."

        Design: Corner/state_machines/approved_change_cannot_be_reverted_to_draft
        """
        change = approved_change["change"]
        response = api.revert_code_change_to_draft(
            change["id"], {"reason": "Attempted rework"}, STAFF)
        validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)

    def test_the_failed_revert_leaves_the_determination_and_credits_intact(
        self, api, approved_change,
    ):
        """PRD §3.5: "A change whose determination is anything other than APPROVED
        contributes 0 credits. A change whose determination is APPROVED begins from a
        base award of 2.0 credits".

        Design: Corner/state_machines/approved_change_cannot_be_reverted_to_draft
        """
        change = approved_change["change"]
        credits_before = change["cea_credits"]
        api.revert_code_change_to_draft(change["id"], {"reason": "Attempted rework"}, STAFF)
        row = validate_success(api.get_code_change(change["id"], STAFF))
        assert row["determination"] == "APPROVED"
        assert row["cea_credits"] == credits_before