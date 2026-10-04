"""Corner coverage indexed under the endpoint surface."""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    CHAIR, STAFF,
    api_client, set_clock, create_society, create_applicant, create_meeting,
    create_change, docket, open_meeting, cast_vote,
    setup_three_docketed_changes,
)


class TestAgendaDocketing:
    def test_docketing_three_changes_sets_the_agenda_and_moves_each_change(self, api):
        """PRD §3.4: "Each named change is moved to AGENDA_SET and has its meeting_id
        pointed at the meeting; the meeting's own agenda_status moves to SET as a
        cascade, and quorum_present is recomputed."

        Design: Corner/endpoints/agenda_docketed_change_reports_agenda_status_set
        """
        bundle = setup_three_docketed_changes()
        meeting = validate_success(api.get_meeting(bundle["meeting"]["id"], STAFF))
        assert meeting["agenda_status"] == "SET"
        assert meeting["quorum_present"] is True
        first = validate_success(api.get_code_change(bundle["changes"][0]["id"], STAFF))
        third = validate_success(api.get_code_change(bundle["changes"][2]["id"], STAFF))
        assert first["review_status"] == "AGENDA_SET"
        assert third["meeting_id"] == bundle["meeting"]["id"]


class TestMeetingVoteSubresource:
    @pytest.fixture
    def meeting_with_one_ballot(self):
        """A meeting opened for deliberation holding exactly one YES ballot."""
        set_clock("2026-09-01T00:00:00Z")
        society_one = create_society("Vote Society One", "VS1", seats=3)
        society_two = create_society("Vote Society Two", "VS2", seats=2)
        applicant = create_applicant("Vote Applicant", "SPECIALTY_SOCIETY",
                                     society_id=society_one["id"])
        meeting = create_meeting("APR2030", "APRIL",
                                 "2030-04-08T14:00:00Z", "2030-04-08T23:00:00Z")
        changes = [
            create_change("00094", applicant["id"], society_id=society_one["id"],
                          descriptor_proposed="First placeholder revised"),
            create_change("00095", applicant["id"], society_id=society_one["id"],
                          descriptor_current="Second placeholder"),
            create_change("00096", applicant["id"], society_id=society_one["id"],
                          descriptor_current="Third placeholder"),
        ]
        docket(meeting["id"], [c["id"] for c in changes])
        open_meeting(meeting["id"])
        ballot = cast_vote(changes[0]["id"], meeting["id"], society_one["id"], "YES")
        return {"meeting": meeting, "changes": changes, "ballot": ballot,
                "society_one": society_one, "society_two": society_two}

    def test_meeting_votes_subresource_returns_only_that_meetings_ballots(
        self, api, meeting_with_one_ballot,
    ):
        """PRD §3.5: "The server stamps cast_at when the ballot is recorded and computes
        votes_carried as the voting seats the casting society carries — that is, the
        society's voting_seat_count as read at the moment the ballot is cast."

        Design: Corner/endpoints/reverse_reachability_lists_votes_for_meeting
        """
        bundle = meeting_with_one_ballot
        ballots, meta = validate_paginated(
            api.list_meeting_votes(bundle["meeting"]["id"], CHAIR))
        assert meta["total_count"] == 1
        assert len(ballots) == 1
        assert ballots[0]["id"] == bundle["ballot"]["id"]

    def test_each_ballot_carries_the_casting_societys_seat_count(
        self, api, meeting_with_one_ballot,
    ):
        """PRD §3.5: "An EditorialVote names the motion in change_id, the sitting in
        meeting_id, the casting society in society_id, and the position in vote, which
        is one of YES, NO or ABSTAIN."

        Design: Corner/endpoints/reverse_reachability_lists_votes_for_meeting
        """
        bundle = meeting_with_one_ballot
        ballot = validate_success(api.get_editorial_vote(bundle["ballot"]["id"], CHAIR))
        assert ballot["votes_carried"] == 3
        assert ballot["vote"] == "YES"


class TestLogicalClock:
    def test_first_clock_call_succeeds_against_the_fixed_default(self, api):
        """PRD §2.8: "The server maintains a logical clock which reads
        2026-09-01T00:00:00Z before any call is made, and which never falls back to
        the host's wall clock."
        PRD §2.8: "Setting the clock forward is a test-driving capability that takes
        the target instant in a to_iso8601 field".

        Design: Corner/endpoints/clock_default_time_before_any_set_call
        """
        response = api.set_clock("2026-09-01T00:00:00Z", STAFF)
        validate_success(response)
        assert response.status_code == 200