"""What a write's own response body already knows, and what a follow-up read confirms."""

from test_helpers import (
    api_client,
    assert_cycle_pool_invariant,
    assert_instant_equals,
    get_success_data,
)
from test_helpers.constants import (
    APPEAL_WINDOW_CLOSES,
    DECISION_CLOCK,
    SCORE_TWO_SHEETS,
)
from test_helpers.fixtures import (
    ADMIN,
    OFFICER,
    seed_two_score_sheets,
    set_clock,
)


class TestComparativeDecisionResponseIsAuthoritative:
    def test_the_decision_body_already_shows_the_pool_drained_by_its_own_award(self):
        """One 12-bed award out of 19: the same response carries the surviving 7.

        PRD §3.7: "**Full award.** When the remaining need is greater than or equal
        to the candidate's `requested_bed_count`, the candidate's
        `allocated_bed_count` is set to its full `requested_bed_count`, its `status`
        becomes `APPROVED`, and the remaining need is reduced by that same count."
        PRD §3.7: "After the loop the cycle's `unallocated_bed_need` is set to
        whatever remaining need survived, and the invariant of §2.10 must hold:
        `unallocated_bed_need` plus the sum of `allocated_bed_count` over the cycle's
        `APPROVED` and `APPROVED_WITH_CONDITIONS` applications equals
        `unmet_bed_need_at_open`."
        PRD §3.7: "Finally the cycle's own `status` becomes `DECIDED` and its
        `version` increases by 1."
        PRD §3.7: "Every decided candidate, in all three branches, also receives
        `decision_at` set to the current logical-clock instant and
        `appeal_window_closes_at` set to `decision_at` plus 30 days, and each has its
        own `version` increased by 1."
        PRD §3.2: "One further counter lives on the cycle: `reopened_count` starts at
        0 and records how many times an appeal disposition has dragged the cycle back
        from `DECIDED` to `COMPARATIVE_REVIEW`, as §3.9 explains."
        PRD §3.8: "On the planning area, `approved_unimplemented_beds` is increased
        by the certificate's `authorized_bed_count` and
        `capital_authorization_committed_cents` is increased by its
        `approved_expenditure_limit_cents`."

        Design: Corner/consistency_model/comparative_decision_response_already_carries_the_drained_need_pool
        """
        world = seed_two_score_sheets()
        cycle_at_open = world["cycle"]
        assert cycle_at_open["unmet_bed_need_at_open"] == 19
        assert cycle_at_open["unallocated_bed_need"] == 19
        assert world["application"]["requested_bed_count"] == 12
        set_clock(DECISION_CLOCK)

        decided = get_success_data(
            api_client.run_comparative_decision(
                cycle_at_open["id"],
                {"decision_note": "Sole reviewable application; partial pool retained"},
                OFFICER,
            )
        )

        assert decided["status"] == "DECIDED"
        assert decided["unallocated_bed_need"] == 7
        assert decided["unmet_bed_need_at_open"] == 19
        assert decided["reopened_count"] == 0
        assert decided["version"] == cycle_at_open["version"] + 1

        reread_cycle = get_success_data(
            api_client.get_batching_cycle(cycle_at_open["id"], ADMIN)
        )
        assert reread_cycle["status"] == decided["status"]
        assert reread_cycle["unallocated_bed_need"] == decided["unallocated_bed_need"]
        assert reread_cycle["reopened_count"] == decided["reopened_count"]
        assert reread_cycle["version"] == decided["version"]

        application = get_success_data(
            api_client.get_application(world["application"]["id"], ADMIN)
        )
        assert application["status"] == "APPROVED"
        assert application["allocated_bed_count"] == 12
        assert application["comparative_score"] == SCORE_TWO_SHEETS
        assert application["denial_reason"] is None
        assert_instant_equals(application["decision_at"], DECISION_CLOCK)
        assert_instant_equals(
            application["appeal_window_closes_at"], APPEAL_WINDOW_CLOSES
        )
        assert application["version"] == world["application"]["version"] + 1
        assert_cycle_pool_invariant(reread_cycle, [application])

        hsa = get_success_data(
            api_client.get_health_service_area(world["hsa"]["id"], ADMIN)
        )
        assert hsa["approved_unimplemented_beds"] == 0
        assert hsa["capital_authorization_committed_cents"] == 0
