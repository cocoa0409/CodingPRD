"""Multi-hop cascades: acceptance, verification, and the leave cycle."""
from test_helpers import assert_employment_eligibility, validate_success

from test_helpers.fixtures import (
    COMPLETER,
    PLACEMENT_COORDINATOR,
    VERIFIER,
    accept_offer,
    complete_and_verify_milestone,
    create_confirmed_placement,
    get_member,
    list_milestones,
    list_placements,
    milestones_by_type,
    setup_member_for_eligibility_flip,
    setup_member_scenario,
    setup_member_with_full_verified_hours,
    setup_offered_application,
)


class TestOfferAcceptanceCascade:
    """Acceptance synthesizes the member and the whole milestone schedule."""

    def test_acceptance_synthesizes_member_and_writes_it_back(self, api):
        """PRD §3.3: "The first hop moves the application to `ACCEPTED` and synthesizes a **CorpsMember** whose `application_id` points back at the application, whose `cohort_year` is the calendar year of the region's `term_start_date`, whose `service_status` starts at `ACTIVE` and whose `institute_status` starts at `ENROLLED`"
        PRD §3.3: "The new member's identifier is written back onto the application as `created_corps_member_id`"

        Design: Difficulty/transitive_cascade/offer_accept_three_hop_cascade
        """
        offered = setup_offered_application()
        app_id = offered["application"]["id"]

        accepted = accept_offer(app_id, offered["applicant"]["id"])
        member_id = accepted["created_corps_member_id"]
        assert accepted["status"] == "ACCEPTED"
        assert member_id, "hop 1 must write created_corps_member_id onto the application"

        member = get_member(member_id)
        assert member["application_id"] == app_id
        assert member["service_status"] == "ACTIVE"
        assert member["institute_status"] == "ENROLLED"
        assert member["cohort_year"] == 2026, "the year of the region's term_start_date"

    def test_second_hop_builds_the_schedule_and_third_hop_advances_versions(self, api):
        """PRD §3.3: "For every certification pathway whose `region_id` equals the application's `preferred_region_id`, the server synthesizes one **CertificationMilestone** per milestone type"
        PRD §3.3: "The milestones are synthesized in the fixed order `COURSEWORK`, `PRACTICUM`, `ORIENTATION`, `EXAM`, and that order is also the order in which the member's milestone collection is returned"
        PRD §3.3: "each synthesized milestone, as it is created, recomputes the member's `certification_hours_verified` and `readiness_score`, and each of those recomputes advances the member's `version` once"

        Design: Difficulty/transitive_cascade/offer_accept_three_hop_cascade
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]

        milestones = list_milestones(member_id)
        assert [m["milestone_type"] for m in milestones] == [
            "COURSEWORK",
            "PRACTICUM",
            "ORIENTATION",
            "EXAM",
        ], "the schedule must read in the canonical type order"
        assert [m["required_hours"] for m in milestones] == [60, 120, 60, 0]
        assert all(m["progress_status"] == "PENDING" for m in milestones)
        assert all(m["verification_status"] == "UNVERIFIED" for m in milestones)

        assert scenario["member"]["version"] == 5, (
            "version 1 at synthesis plus one advance per synthesized milestone"
        )
        assert scenario["member"]["certification_hours_verified"] == 0
        assert scenario["member"]["readiness_score"] == 0.0


class TestVerificationEligibilityCascade:
    """Verifying a milestone flips the placement's eligibility through hop 1."""

    def test_verify_flips_placement_eligibility(self, api):
        """PRD §3.5: "Verifying a milestone recomputes the member's `certification_hours_verified`, which sums the `required_hours` of every milestone of that member that is simultaneously `COMPLETED` and `VERIFIED`"
        PRD §3.5: "The same recompute refreshes the member's `readiness_score`, and that in turn re-evaluates `employment_eligible` on every placement the member holds whose status is `CONFIRMED` or `ACTIVE`."

        Design: Difficulty/transitive_cascade/milestone_verify_two_hop_eligibility_cascade
        """
        scenario = setup_member_for_eligibility_flip()
        member_id = scenario["member_id"]
        placement_id = scenario["placement"]["id"]

        before = list_placements(member_id)[0]
        assert before["employment_eligible"] is False, (
            "60 verified hours is below the pathway's 180-hour floor"
        )
        assert get_member(member_id)["certification_hours_verified"] == 60

        complete_and_verify_milestone(milestones_by_type(member_id)["PRACTICUM"]["id"])

        after_member = get_member(member_id)
        assert after_member["certification_hours_verified"] == 180, "hop 1"
        after_placement = list_placements(member_id)[0]
        assert after_placement["id"] == placement_id
        assert after_placement["employment_eligible"] is True, (
            "hop 2: the flag moved only because hop 1 recomputed the verified hours"
        )
        assert after_placement["status"] == "CONFIRMED"
        assert after_member["service_status"] == "ACTIVE"

    def test_eligibility_stays_false_below_the_hour_floor(self, api):
        """PRD §3.5: "It is true only when all five of the following hold at once: the placement's `status` is `CONFIRMED` or `ACTIVE`; the member's `service_status` is `ACTIVE`; the member's `institute_status` is `COMPLETED`; none of the member's milestones has a `deadline_status` of `OVERDUE`; and the member's `certification_hours_verified` is at least the sum of the selected pathway's `required_practice_hours` and `required_coursework_hours`."

        Design: Difficulty/transitive_cascade/milestone_verify_two_hop_eligibility_cascade
        """
        scenario = setup_member_for_eligibility_flip()
        member_id = scenario["member_id"]
        placement = list_placements(member_id)[0]
        member = get_member(member_id)

        assert member["certification_hours_verified"] == 60 < 180
        assert placement["status"] == "CONFIRMED"
        assert member["service_status"] == "ACTIVE"
        assert member["institute_status"] == "COMPLETED"
        assert placement["employment_eligible"] is False
        assert_employment_eligibility(
            placement, member, list_milestones(member_id), scenario["pathway"]
        )


class TestLeaveReturnConservation:
    """The leave cycle never touches verified hours."""

    def test_verified_hours_survive_leave_and_return(self, api):
        """PRD §3.9: "A `PlacementCoordinator` places a member on leave by transitioning them from `ACTIVE` to `ON_LEAVE`, which stamps `leave_started_at` with the current logical clock"
        PRD §3.9: "The return from leave closes the cycle: the member goes back from `ON_LEAVE` to `ACTIVE`, `leave_started_at` is cleared to null, and `service_started_at` is set to the current logical clock"

        Design: Difficulty/compensating_invariant/leave_return_conserves_verified_hours
        """
        scenario = setup_member_with_full_verified_hours()
        member_id = scenario["member_id"]

        before = get_member(member_id)
        assert before["service_status"] == "ACTIVE"
        assert before["certification_hours_verified"] == 180

        on_leave = validate_success(api.place_member_on_leave(member_id, PLACEMENT_COORDINATOR))
        assert on_leave["service_status"] == "ON_LEAVE"
        assert on_leave["certification_hours_verified"] == 180, (
            "the leave transition must not disturb the member-scoped hour sum"
        )

        back = validate_success(api.return_member_from_leave(member_id, PLACEMENT_COORDINATOR))
        assert back["service_status"] == "ACTIVE"
        assert back["certification_hours_verified"] == 180
        assert back.get("leave_started_at") is None

    def test_leave_and_return_move_employment_eligibility(self, api):
        """PRD §3.9: "forces `employment_eligible` to false on every placement of that member whose status is `CONFIRMED` or `ACTIVE`"
        PRD §3.9: "The return also recomputes `employment_eligible` on the member's confirmed and active placements, so a member returning with their certification in order comes back employable."

        Design: Difficulty/compensating_invariant/leave_return_conserves_verified_hours
        """
        scenario = setup_member_with_full_verified_hours()
        member_id = scenario["member_id"]
        placement = create_confirmed_placement(member_id, scenario["school"]["id"])
        assert placement["employment_eligible"] is True

        validate_success(api.place_member_on_leave(member_id, PLACEMENT_COORDINATOR))
        on_leave = list_placements(member_id)[0]
        assert on_leave["employment_eligible"] is False

        validate_success(api.return_member_from_leave(member_id, PLACEMENT_COORDINATOR))
        back = list_placements(member_id)[0]
        assert back["employment_eligible"] is True
