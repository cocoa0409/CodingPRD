"""
Strong consistency: the aggregates a write recomputes on another entity are
already final in that write's own response and identical on the very next read.
"""

from test_helpers import (
    ADMIN_HEADERS,
    assert_case_weight,
    assert_caseload_summary,
    create_child,
    create_coordinator,
    create_referral,
    factories,
    read_caseload_summary,
    set_clock,
    validate_success,
)

ASSIGNMENT_CLOCK = "2026-03-02T09:00:00Z"
ASSIGNMENT_DATE = "2026-03-02"
CEILING_POINTS = 3.20


class TestAssignmentAggregatesAreImmediatelyVisible:

    def test_the_coordinators_aggregates_are_final_in_the_same_request_sequence(
        self, api
    ):
        """
        An empty coordinator reads as zero, the assignment's own response already
        carries the new case weight and stage, and the caseload read taken directly
        afterwards — with no call in between — reports the recomputed aggregates.
        The referral read back agrees with the transition's response field for field.

        PRD 2.7: "There is no deferred reconciliation, no background sweep and no
        eventual consistency: when a request returns 200 or 201, every derived
        counter, aggregate and dependent state named in the workflow narratives has
        already been updated."
        PRD 3.2: "Either way the case's `coordinator_id` and its `assignment_date` —
        the logical clock date on which assignment happened — are stored, the case's
        `case_weight_points` is computed, the chosen coordinator's three aggregates
        are recomputed, and `Referral.version` is incremented by 1."
        PRD 3.2: "A coordinator's `active_case_count` is the number of referrals
        assigned to them whose status is neither `NOT_ELIGIBLE` nor `EXITED`, and
        their `weighted_caseload_points` is the sum of `case_weight_points` over
        exactly that same set of referrals, held to two decimal places rounded half
        up."
        PRD 3.2: "`utilization_ratio` is `weighted_caseload_points` divided by
        `max_weighted_caseload_points`, rounded half up to four decimal places."

        Design: Corner/consistency_model/assignment_aggregates_are_visible_immediately_in_the_same_request_sequence
        """
        set_clock(api, ASSIGNMENT_CLOCK)
        coordinator_id = create_coordinator(
            api, max_weighted_caseload_points=CEILING_POINTS
        )
        child_id = create_child(api)
        referral_id = create_referral(api, child_id)

        assert_caseload_summary(
            read_caseload_summary(api, coordinator_id),
            coordinator_id=coordinator_id,
            active_case_count=0,
            weighted_caseload_points=0.00,
            max_weighted_caseload_points=CEILING_POINTS,
            utilization_ratio=0.0000,
            caseload_posture="OPEN",
            headroom_points=CEILING_POINTS,
        )

        assigned = validate_success(
            api.assign_coordinator(
                referral_id,
                factories.assign_coordinator_payload(coordinator_id=coordinator_id),
                ADMIN_HEADERS,
            ),
            200,
        )
        assert assigned["status"] == "EVALUATION_PENDING"
        assert assigned["coordinator_id"] == coordinator_id
        assert assigned["assignment_date"] == ASSIGNMENT_DATE
        assert_case_weight(assigned["case_weight_points"], 1.50)

        assert_caseload_summary(
            read_caseload_summary(api, coordinator_id),
            coordinator_id=coordinator_id,
            active_case_count=1,
            weighted_caseload_points=1.50,
            max_weighted_caseload_points=CEILING_POINTS,
            utilization_ratio=0.4688,
            caseload_posture="OPEN",
            headroom_points=1.70,
        )

        read_back = validate_success(
            api.get_referral(referral_id, ADMIN_HEADERS), 200
        )
        for field in (
            "status",
            "coordinator_id",
            "assignment_date",
            "case_weight_points",
            "version",
        ):
            assert read_back[field] == assigned[field]
