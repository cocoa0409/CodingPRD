"""Corner coverage indexed under the error surface (the satisfied side of a check)."""
import pytest

from test_helpers import (
    validate_success,
    CHAIR, STAFF,
    api_client, set_clock, create_society, create_applicant, create_meeting,
    create_change, docket, open_meeting, cast_vote,
)


class TestEvidenceBoundarySatisfied:
    def test_weakest_tier_addition_at_exactly_one_hundred_procedures_is_accepted(self, api):
        """PRD §2.7: "a TIER_IV ADDITION is acceptable only when the change also
        declares a procedure_volume_threshold of at least 100 procedures annually."
        PRD §3.1: "administrative_review_status begins at UNDER_ADMIN_REVIEW,
        posting_state begins at NOT_POSTED, and review_status begins at DRAFT."

        Design: Corner/errors/check_satisfied_no_error_on_valid_addition
        """
        set_clock("2026-09-01T00:00:00Z")
        applicant = create_applicant("Boundary Applicant", "MANUFACTURER")
        change = validate_success(api.create_code_change(
            {
                "code": "00097",
                "change_type": "ADDITION",
                "category": "CATEGORY_III",
                "code_family": "000",
                "applicant_id": applicant["id"],
                "clinical_evidence_tier": "TIER_IV",
                "procedure_volume_threshold": 100,
                "descriptor_current": "Placeholder descriptor",
            },
            STAFF,
        ), 201)
        assert change["code"] == "00097"
        assert change["clinical_evidence_tier"] == "TIER_IV"
        assert change["administrative_review_status"] == "UNDER_ADMIN_REVIEW"
        assert change["determination"] == "PENDING"


class TestDuplicateBallotSupersession:
    @pytest.fixture
    def meeting_with_earlier_ballot(self):
        """A three-seat society that already cast an ABSTAIN ballot on change one."""
        set_clock("2026-09-01T00:00:00Z")
        society = create_society("Supersede Society", "SUP", seats=3)
        applicant = create_applicant("Supersede Applicant", "SPECIALTY_SOCIETY",
                                     society_id=society["id"])
        meeting = create_meeting("JUN2030", "JUNE",
                                 "2030-06-10T14:00:00Z", "2030-06-10T23:00:00Z")
        changes = [
            create_change("00098", applicant["id"], society_id=society["id"],
                          descriptor_proposed="First placeholder revised"),
            create_change("00099", applicant["id"], society_id=society["id"],
                          descriptor_current="Second placeholder"),
            create_change("00100", applicant["id"], society_id=society["id"],
                          code_family="001", descriptor_current="Third placeholder"),
        ]
        docket(meeting["id"], [c["id"] for c in changes])
        open_meeting(meeting["id"])
        earlier = cast_vote(changes[0]["id"], meeting["id"], society["id"], "ABSTAIN")
        return {"society": society, "meeting": meeting, "changes": changes,
                "earlier": earlier}

    def test_a_later_ballot_replaces_the_earlier_one_on_the_same_change(
        self, api, meeting_with_earlier_ballot,
    ):
        """PRD §3.5: "Only a seated society may cast the single ballot it is entitled
        to on a given change at a given meeting. A society attempting a second ballot
        on the same change at the same meeting has its earlier ballot superseded rather
        than accumulated — the later ballot replaces the earlier one".
        PRD §3.5: "Supersession is resolved by keeping, for each society and change
        pair, only the ballot with the greatest cast_at".

        Design: Corner/errors/duplicate_vote_supersedes_earlier_ballot
        """
        bundle = meeting_with_earlier_ballot
        later = validate_success(api.create_editorial_vote(
            {
                "change_id": bundle["changes"][0]["id"],
                "meeting_id": bundle["meeting"]["id"],
                "society_id": bundle["society"]["id"],
                "vote": "NO",
            },
            CHAIR,
        ), 201)
        assert later["votes_carried"] == 3
        assert later["vote"] == "NO"

    def test_the_superseded_ballot_drops_out_of_the_weighted_tallies(
        self, api, meeting_with_earlier_ballot,
    ):
        """PRD §3.5: "weighted_yes is the sum of votes_carried over included ballots
        marked YES; weighted_no is the same sum over NO; weighted_abstain is the same
        sum over ABSTAIN."

        Design: Corner/errors/duplicate_vote_supersedes_earlier_ballot
        """
        bundle = meeting_with_earlier_ballot
        later = validate_success(api.create_editorial_vote(
            {
                "change_id": bundle["changes"][0]["id"],
                "meeting_id": bundle["meeting"]["id"],
                "society_id": bundle["society"]["id"],
                "vote": "NO",
            },
            CHAIR,
        ), 201)
        meeting = validate_success(api.get_meeting(bundle["meeting"]["id"], STAFF))
        ballot = validate_success(api.get_editorial_vote(later["id"], CHAIR))
        assert meeting["weighted_no"] == ballot["votes_carried"] == 3
        assert meeting["weighted_yes"] == 0