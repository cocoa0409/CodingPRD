"""Difficulty claims about quantities a compensating action must restore."""

from test_helpers import (
    fixtures,
    get_client_data,
    get_engagement_data,
    get_professional_data,
    get_service_data,
)


class TestFeePoolConservation:
    """Approving then revoking a service leaves the pool where it started."""

    def test_approval_moves_the_pool_by_the_rounded_fee(self, api):
        """PRD §3.6: "On success the service's `approved_fee_cents` is set to
        its fee rounded to the nearest whole dollar, `approved_on` is stamped
        from the logical clock, the client's `naf_approved_fee_cents` is
        recomputed through the fee pool rule".

        Design: Difficulty/compensating_invariant/naf_approve_then_revoke_conserves_the_client_fee_pool
        """
        world = fixtures.scenario_fee_pool_conservation(api)
        client_id = world["client"]["id"]
        assert get_client_data(api, client_id)["naf_approved_fee_cents"] == 0

        fixtures.service_transition_ok(
            api, world["service"]["id"], "APPROVE", committee_resolution_ref="AC-2027-0401"
        )

        service = get_service_data(api, world["service"]["id"])
        client = get_client_data(api, client_id)
        assert service["approved_fee_cents"] == 300000
        assert client["naf_approved_fee_cents"] == 300000

    def test_revocation_returns_the_pool_to_zero(self, api):
        """PRD §3.6: "an `APPROVED` service may be revoked through the `REVOKE`
        action, which resets `approved_fee_cents` and `approved_on` to null,
        recomputes the client's fee pool so the revoked fee leaves the ceiling
        calculation".

        Design: Difficulty/compensating_invariant/naf_approve_then_revoke_conserves_the_client_fee_pool
        """
        world = fixtures.scenario_fee_pool_conservation(api)
        client_id = world["client"]["id"]

        fixtures.service_transition_ok(
            api, world["service"]["id"], "APPROVE", committee_resolution_ref="AC-2027-0401"
        )
        assert get_client_data(api, client_id)["naf_approved_fee_cents"] == 300000

        fixtures.service_transition_ok(api, world["service"]["id"], "REVOKE")

        service = get_service_data(api, world["service"]["id"])
        client = get_client_data(api, client_id)
        assert service["status"] == "REVOKED"
        assert service["approved_fee_cents"] is None
        assert service["approved_on"] is None
        assert client["naf_approved_fee_cents"] == 0


class TestWorkloadConservation:
    """Creating then ending an assignment leaves both totals where they were."""

    def test_creating_an_assignment_adds_forty_points_to_both_totals(self, api):
        """PRD §3.3: "In the first step, each `ACTIVE` assignment's base is the
        role's base points multiplied by the multiplier of the risk tier of the
        engagement".
        PRD §3.3: "Engagement.assigned_workload_points is the sum of the step-1
        bases of that engagement's own `ACTIVE` assignments."

        Design: Difficulty/compensating_invariant/assignment_create_then_end_conserves_workload_points
        """
        world = fixtures.scenario_workload_conservation(api)
        professional_id = world["professional"]["id"]
        engagement_id = world["engagement"]["id"]

        assert get_professional_data(api, professional_id)["active_workload_points"] == 0
        assert get_engagement_data(api, engagement_id)["assigned_workload_points"] == 0

        assignment = fixtures.staff_ok(
            api, engagement_id, professional_id, "LEAD_PARTNER",
            "2027-05-01T00:00:00Z", "2028-05-01T00:00:00Z",
            ep_headers=world["ep_headers"],
        )

        professional = get_professional_data(api, professional_id)
        engagement = get_engagement_data(api, engagement_id)
        assert assignment["workload_points"] == 40
        assert professional["active_workload_points"] == 40
        assert engagement["assigned_workload_points"] == 40
        assert engagement["lead_partner_id"] == professional_id

    def test_ending_the_assignment_returns_both_totals_to_zero(self, api):
        """PRD §3.3: "refreshes the affected professional's
        `active_workload_points` and availability as well as the engagement's
        `assigned_workload_points`, `lead_partner_id` and
        `concurring_partner_id`."
        PRD §3.3: "`ENDED` assignments contribute nothing."

        Design: Difficulty/compensating_invariant/assignment_create_then_end_conserves_workload_points
        """
        world = fixtures.scenario_workload_conservation(api)
        professional_id = world["professional"]["id"]
        engagement_id = world["engagement"]["id"]

        assignment = fixtures.staff_ok(
            api, engagement_id, professional_id, "LEAD_PARTNER",
            "2027-05-01T00:00:00Z", "2028-05-01T00:00:00Z",
            ep_headers=world["ep_headers"],
        )
        fixtures.end_assignment_ok(api, assignment["id"], world["ep_headers"])

        professional = get_professional_data(api, professional_id)
        engagement = get_engagement_data(api, engagement_id)
        stored = fixtures.get_assignment_data(api, assignment["id"])
        assert professional["active_workload_points"] == 0
        assert engagement["assigned_workload_points"] == 0
        assert engagement["lead_partner_id"] is None
        # The step-1 base stays on the row even though it no longer counts.
        assert stored["workload_points"] == 40
