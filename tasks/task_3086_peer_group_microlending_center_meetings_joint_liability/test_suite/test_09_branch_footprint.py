"""Full-chain footprint round-trip: the branch counters after a complete
cycle of group formation, disbursement, collections, and close-out.
"""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    post_collection,
    close_meeting,
    setup_open_meeting_with_loan,
)

PA = TEST_USERS["program_admin_headers"]


class TestBranchFootprint:
    def test_fixture_anchor_chain_not_a_test(self, api):
        """PRD §3.1: "The `active_member_count` counts members of the branch
        whose status is `IN_TRAINING`, `ELIGIBLE`, `ACTIVE_BORROWER`, or
        `DELINQUENT` — recruits not yet in a group and blacklisted members do
        not count."
        PRD §3.1: "A manager's `current_caseload` counts the distinct members —
        again in `IN_TRAINING`, `ELIGIBLE`, `ACTIVE_BORROWER`, or `DELINQUENT` —
        whose peer group sits at a center assigned to that manager, and the
        branch's `total_manager_caseload` is the sum of its managers'
        caseloads."

        Design: Corner/entities/fixture_anchor_chain_not_a_test
        """
        ctx = setup_open_meeting_with_loan(prefix="anchor")
        post_collection(
            ctx["meeting"]["id"], ctx["manager"],
            ctx["applicant"]["id"], ctx["loan"]["id"], 109_808,
        )
        close_meeting(ctx["meeting"]["id"], ctx["manager"])

        branch = get_success_data(api.get_branch(ctx["branch"]["id"], PA))
        assert branch["active_member_count"] == 5, (
            "five group members, all ELIGIBLE or ACTIVE_BORROWER"
        )
        assert branch["total_manager_caseload"] == 5, (
            "the single manager carries the whole center"
        )
        assert branch["tier"] == "SMALL"
