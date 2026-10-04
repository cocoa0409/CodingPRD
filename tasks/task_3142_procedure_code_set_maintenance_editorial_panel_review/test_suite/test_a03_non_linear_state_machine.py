"""Non-linear state machines: transitions that return to earlier states."""
import pytest

from test_helpers import (
    validate_success, ApiErrorId,
    assert_meeting_quorum_invariant,
    CHAIR, STAFF, LICENSING, TEST_USERS,
    api_client, set_clock, create_society, create_applicant,
    create_meeting, create_cycle, create_change, submit_into_cycle, post_change,
    docket, open_meeting, create_licence_and_territory,
)


@pytest.fixture
def posted_change():
    """A sponsored revision submitted into a cycle and posted for public comment."""
    set_clock("2026-09-01T00:00:00Z")
    society = create_society("Epsilon Society", "EPS", seats=1)
    applicant = create_applicant("Epsilon Applicant", "PHYSICIAN", society_id=society["id"])
    meeting = create_meeting("AUG2026", "AUGUST",
                             "2026-08-10T14:00:00Z", "2026-08-10T23:00:00Z")
    cycle = create_cycle([meeting["id"]], year=2027, capacity=300)
    change = create_change(
        "00005", applicant["id"], society_id=society["id"], change_type="REVISION",
        tier="TIER_II", evidence_index=70, volume=1200, organ_systems=2,
        descriptor_current="Existing descriptor",
        descriptor_proposed="Revised descriptor", guidelines="Revised guideline",
    )
    submit_into_cycle(cycle["id"], [change["id"]], change["version"])
    posted = post_change(change["id"])
    return {"society": society, "applicant": applicant, "meeting": meeting,
            "cycle": cycle, "change": posted}


class TestCodeChangeCyclicWorkflow:
    def test_administrative_return_moves_posted_change_back_to_draft(self, api, posted_change):
        """PRD §3.2: "A posted change whose screening is ADMIN_COMPLETE may be returned
        to administrative review through the reason field, which sets
        administrative_review_status back to ADMIN_RETURNED, sets posting_state back to
        NOT_POSTED, and moves review_status from POSTED_FOR_COMMENT back to DRAFT."

        Design: Difficulty/non_linear_state_machine/code_change_revision_cycle_returns_to_draft
        """
        change = validate_success(api.administrative_return_code_change(
            posted_change["change"]["id"], {"reason": "Incomplete evidence packet"}, STAFF))
        assert change["review_status"] == "DRAFT"
        assert change["administrative_review_status"] == "ADMIN_RETURNED"
        assert change["posting_state"] == "NOT_POSTED"

    def test_administrative_return_advances_the_change_version(self, api, posted_change):
        """PRD §2.5: "version is an integer that starts at its initial value and
        increments by exactly one on each such mutation."

        Design: Difficulty/non_linear_state_machine/code_change_revision_cycle_returns_to_draft
        """
        before = posted_change["change"]["version"]
        change = validate_success(api.administrative_return_code_change(
            posted_change["change"]["id"], {"reason": "Incomplete evidence packet"}, STAFF))
        assert change["version"] == before + 1

    def test_returning_a_posted_change_pulls_it_back_to_draft_for_rescreening(self, api, posted_change):
        """PRD §3.2: "A posted change whose screening is ADMIN_COMPLETE may be returned
        to administrative review through the reason field, which sets
        administrative_review_status back to ADMIN_RETURNED, sets posting_state back to
        NOT_POSTED, and moves review_status from POSTED_FOR_COMMENT back to DRAFT."
        PRD §2.4: "a packet that fails screening is set to ADMIN_RETURNED and cannot be
        posted."

        Design: Difficulty/non_linear_state_machine/code_change_revision_cycle_returns_to_draft
        """
        change_id = posted_change["change"]["id"]
        returned = validate_success(api.administrative_return_code_change(
            change_id, {"reason": "Incomplete evidence packet"}, STAFF))
        assert returned["review_status"] == "DRAFT"
        assert returned["administrative_review_status"] == "ADMIN_RETURNED"
        assert returned["posting_state"] == "NOT_POSTED"


class TestEditorialMeetingParallelDimensions:
    def test_opening_the_meeting_leaves_the_agenda_dimension_untouched(self, api):
        """PRD §3.4: "Opening the meeting for deliberation is the chair's act and
        requires the agenda to be SET and each change's screening to be
        UNDER_ADMIN_REVIEW or ADMIN_COMPLETE. It moves meeting_status to OPEN".
        PRD §3.4: "The meeting's second dimension is agenda_status, which begins at UNSET."

        Design: Difficulty/non_linear_state_machine/editorial_meeting_parallel_dimensions_independent
        """
        set_clock("2026-09-01T00:00:00Z")
        applicant = create_applicant("Eta Applicant", "PHYSICIAN")
        meeting = create_meeting("OCT2028", "OCTOBER",
                                 "2028-10-09T14:00:00Z", "2028-10-09T23:00:00Z")
        changes = [create_change(code, applicant["id"]) for code in ("00020", "00021", "00022")]
        docket(meeting["id"], [c["id"] for c in changes])
        opened = validate_success(api.open_meeting(meeting["id"], CHAIR))
        assert opened["meeting_status"] == "OPEN"
        assert opened["agenda_status"] == "SET"
        assert_meeting_quorum_invariant(opened)

    def test_recess_and_reopen_cycle_returns_to_open_without_touching_the_agenda(self, api):
        """PRD §3.4: "The chair can recess an open meeting provided the agenda is SET;
        a recess moves meeting_status to RECESSED and deliberately leaves conducted_at
        empty. Reopening a recessed meeting requires agenda_status to be ADDENDUM_OPEN."

        Design: Difficulty/non_linear_state_machine/editorial_meeting_parallel_dimensions_independent
        """
        set_clock("2026-09-01T00:00:00Z")
        applicant = create_applicant("Eta Applicant", "PHYSICIAN")
        meeting = create_meeting("OCT2028", "OCTOBER",
                                 "2028-10-09T14:00:00Z", "2028-10-09T23:00:00Z")
        # PRD §3.4: the addendum may be opened only while the logical clock is at
        # or before the addendum_comment_close of the release cycle naming this
        # meeting, so the clock is advanced to that cycle's own addendum close.
        create_cycle([meeting["id"]], year=2028)
        set_clock("2028-11-15T00:00:00Z")
        changes = [create_change(code, applicant["id"]) for code in ("00020", "00021", "00022")]
        docket(meeting["id"], [c["id"] for c in changes])
        open_meeting(meeting["id"])
        recessed = validate_success(api.recess_meeting(
            meeting["id"], {"reason": "Lunch recess"}, CHAIR))
        assert recessed["meeting_status"] == "RECESSED"
        assert recessed["conducted_at"] is None
        validate_success(api.open_addendum(
            meeting["id"], {"addendum_note": "Late business"}, STAFF))
        reopened = validate_success(api.reopen_meeting(meeting["id"], CHAIR))
        assert reopened["meeting_status"] == "OPEN"


class TestLicensingAgreementCyclicLifecycle:
    def test_suspend_then_reactivate_returns_the_licence_to_active(self, api):
        """PRD §3.9: "Suspension moves an ACTIVE licence to SUSPENDED. Reactivation
        moves a SUSPENDED licence back to ACTIVE and requires the fee threshold gate
        to be PASS, recomputing the royalty fee."

        Design: Difficulty/non_linear_state_machine/licensing_agreement_cyclic_lifecycle
        """
        set_clock("2026-09-01T00:00:00Z")
        licence, territory = create_licence_and_territory(
            territory_code="US-WEST", method="SITE", licensee_type="PROVIDER",
            licensee_name="West Clinic", sales_unit_count=10, expected_users=40,
            activate=True,
        )
        validate_success(api.suspend_licensing_agreement(
            licence["id"], {"reason": "Annual review"}, LICENSING))
        reactivated = validate_success(api.reactivate_licensing_agreement(
            licence["id"], LICENSING))
        assert reactivated["agreement_status"] == "ACTIVE"
        assert reactivated["fee_threshold_gate_status"] == "PASS"

    def test_reactivation_reprices_royalty_from_the_band_schedule(self, api):
        """PRD §3.9: "for up to and including 500,000 units the fee is the unit count
        multiplied by 0.90, rounded half up to a whole cent".
        PRD §3.9: "A positive score yields US_ONLY when vendor_worldwide is false and
        WORLDWIDE when vendor_worldwide is true."

        Design: Difficulty/non_linear_state_machine/licensing_agreement_cyclic_lifecycle
        """
        set_clock("2026-09-01T00:00:00Z")
        licence, territory = create_licence_and_territory(
            territory_code="US-WEST", method="SITE", licensee_type="PROVIDER",
            licensee_name="West Clinic", sales_unit_count=10, expected_users=40,
            activate=True,
        )
        validate_success(api.suspend_licensing_agreement(
            licence["id"], {"reason": "Annual review"}, LICENSING))
        reactivated = validate_success(api.reactivate_licensing_agreement(
            licence["id"], LICENSING))
        assert reactivated["royalty_fee_cents"] == 9
        assert reactivated["distribution_scope"] == "US_ONLY"