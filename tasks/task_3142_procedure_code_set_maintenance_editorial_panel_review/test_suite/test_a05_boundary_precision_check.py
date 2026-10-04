"""Boundary precision: thresholds measured at, just below and just above the edge."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    CHAIR, STAFF, TEST_USERS,
    api_client, set_clock, create_society, create_applicant, create_meeting,
    create_change, docket, open_meeting, cast_vote,
)


class TestCitationModeApprovalFloor:
    @pytest.fixture
    def citation_meeting_with_votes(self):
        """A citation-mode meeting holding a 2-1 seat tally (66.6667 percent)."""
        set_clock("2026-09-01T00:00:00Z")
        societies = [
            create_society("Nu Society", "NUU", seats=1),
            create_society("Xi Society", "XII", seats=1),
            create_society("Omicron Society", "OMI", seats=1),
        ]
        applicant = create_applicant("Nu Applicant", "SPECIALTY_SOCIETY",
                                     society_id=societies[0]["id"])
        meeting = create_meeting("OCT2029", "OCTOBER",
                                 "2029-10-08T14:00:00Z", "2029-10-08T23:00:00Z",
                                 citation_mode=True)
        change = create_change("00040", applicant["id"], society_id=societies[0]["id"],
                               tier="TIER_I", volume=2500, organ_systems=1)
        fillers = [create_change("00041", applicant["id"], society_id=societies[0]["id"]),
                   create_change("00042", applicant["id"], society_id=societies[0]["id"])]
        docket(meeting["id"], [change["id"]] + [f["id"] for f in fillers])
        open_meeting(meeting["id"])
        cast_vote(change["id"], meeting["id"], societies[0]["id"], "YES")
        cast_vote(change["id"], meeting["id"], societies[1]["id"], "YES")
        cast_vote(change["id"], meeting["id"], societies[2]["id"], "NO")
        return {"meeting": meeting, "change": change, "societies": societies}

    def test_tally_resolving_to_exactly_two_thirds_is_refused(self, api, citation_meeting_with_votes):
        """PRD §3.5: "The citation-mode floor is also enforced by truncating the
        weighted percentage to three decimals before comparing it with 66.667; as a
        consequence, a tally that resolves to exactly 66.6667 percent falls below the
        floor and is refused."

        Design: Difficulty/boundary_precision_check/truncated_percentage_floor_at_exact_two_thirds
        """
        bundle = citation_meeting_with_votes
        response = api.determine_code_change(
            bundle["change"]["id"],
            {"determination": "APPROVED", "determination_basis": "Descriptor is distinct"},
            CHAIR,
        )
        validate_error(response, ApiErrorId.ERR_APPROVAL_PERCENT_TOO_LOW, expected_status=409)

    def test_refused_tally_leaves_the_change_in_panel_review(self, api, citation_meeting_with_votes):
        """PRD §3.5: "Recording a determination is the chair's act on a change sitting
        in PANEL_REVIEW."
        PRD §3.5: "In citation-only mode, a determination whose weighted percentage
        falls below the 66.667 floor is rejected with ERR_APPROVAL_PERCENT_TOO_LOW at
        409, and the same code and status are returned when more than one percent of
        the meeting's weighted affirmative vote was cast from outside the seated
        societies — that is, when the outside cast share exceeds one percent of the
        weighted affirmative total."

        Design: Difficulty/boundary_precision_check/truncated_percentage_floor_at_exact_two_thirds
        """
        bundle = citation_meeting_with_votes
        api.determine_code_change(
            bundle["change"]["id"],
            {"determination": "APPROVED", "determination_basis": "Descriptor is distinct"},
            CHAIR,
        )
        change = validate_success(api.get_code_change(bundle["change"]["id"], STAFF))
        assert change["review_status"] == "PANEL_REVIEW"

    def test_citation_weighting_flattens_every_ballot_to_one(self, api, citation_meeting_with_votes):
        """PRD §3.5: "When a meeting sets citation_mode, votes_carried is forced to 1
        for every ballot regardless of the casting society's voting_seat_count, so the
        weighted totals become raw ballot counts rather than seat counts."

        Design: Difficulty/boundary_precision_check/truncated_percentage_floor_at_exact_two_thirds
        """
        bundle = citation_meeting_with_votes
        meeting = validate_success(api.get_meeting(bundle["meeting"]["id"], STAFF))
        assert meeting["weighted_yes"] == 2
        assert meeting["weighted_no"] == 1


class TestEmptyCommentCollectionBoundary:
    @pytest.fixture
    def meeting_with_open_comment_window(self, api):
        """A meeting whose public comment window is open and no comments are filed."""
        set_clock("2026-09-01T00:00:00Z")
        meeting = create_meeting("DEC2028", "DECEMBER",
                                 "2028-12-11T14:00:00Z", "2028-12-11T23:00:00Z")
        opened = validate_success(api.open_meeting_comment_window(
            meeting["id"],
            {"public_comment_open_at": "2026-09-01T00:00:00Z",
             "public_comment_close_at": "2026-10-01T00:00:00Z"},
            STAFF,
        ))
        return opened

    def test_reversal_with_no_comments_returns_the_meeting_to_scheduled(
        self, api, meeting_with_open_comment_window,
    ):
        """PRD §3.4: "A meeting whose comment window closed with no comments filed at
        all can be reversed back — the reversal requires that no PublicComment row
        exists for any change docketed at the meeting — and it returns meeting_status
        to SCHEDULED and clears both public comment instants."

        Design: Difficulty/boundary_precision_check/empty_comment_collection_boundary
        """
        meeting = meeting_with_open_comment_window
        reversed_meeting = validate_success(api.reverse_meeting_comment_window(
            meeting["id"], {"reason": "No comments were filed"}, STAFF))
        assert reversed_meeting["meeting_status"] == "SCHEDULED"
        assert reversed_meeting["public_comment_open_at"] is None

    def test_reversal_also_clears_the_comment_close_instant(
        self, api, meeting_with_open_comment_window,
    ):
        """PRD §3.4: "returns meeting_status to SCHEDULED and clears both public
        comment instants."

        Design: Difficulty/boundary_precision_check/empty_comment_collection_boundary
        """
        meeting = meeting_with_open_comment_window
        reversed_meeting = validate_success(api.reverse_meeting_comment_window(
            meeting["id"], {"reason": "No comments were filed"}, STAFF))
        assert reversed_meeting["public_comment_open_at"] is None
        assert reversed_meeting["public_comment_close_at"] is None