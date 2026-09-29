"""The approval chain: supersede cascade and the rejected-to-draft revision cycle.

Covers PRD section 3.4 - approving one plan retires a rival plan for the same
checkpoint and date across three causal links, and the backward edge out of
REJECTED resets the whole cost block before the plan can be priced again.
"""

from test_helpers import (
    DUTY_MANAGER_HEADERS,
    MANAGER_HEADERS,
    PLANNER_HEADERS,
    SECOND_PLANNER_HEADERS,
    assert_instant,
    assert_nulls,
    assert_officer_ledger,
    assert_plan_cost,
    factories as f,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    BAND_1000,
    BAND_1200,
    CLOCK_1000,
    FLIGHT_1030,
    FLIGHT_1230,
    Scenario,
)

BAND_1400 = "2026-09-10T14:00:00Z"
FLIGHT_1430 = "2026-09-10T14:30:00Z"

COST_FIELDS = (
    "planned_regular_minutes",
    "planned_overtime_minutes",
    "base_cost_cents",
    "overtime_cost_cents",
    "detail_cost_cents",
    "subtotal_cents",
    "admin_fee_rate",
    "admin_fee_cents",
    "total_cost_cents",
)


def _two_band_submitted_plan(staffed_floor: Scenario) -> Scenario:
    """A SUBMITTED plan with Ada on the 10:00 and 12:00 bands.

    Ada's 45-minute regular cap splits her 60 planned minutes into 45 regular
    and 15 overtime: base 4500, overtime 2250, subtotal 6750, fee 304.
    """
    staffed_floor.build_forecast_band(BAND_1000, FLIGHT_1030)
    staffed_floor.build_forecast_band(BAND_1200, FLIGHT_1230)
    bands = staffed_floor.extras["bands"]
    staffed_floor.build_draft_plan()
    staffed_floor.build_assignment(band_id=bands[0]["id"])
    staffed_floor.build_assignment(band_id=bands[1]["id"])
    staffed_floor.build_submitted_plan()
    return staffed_floor


def _rival_plan_ready_to_approve(staffed_floor: Scenario) -> Scenario:
    """Plan A ACTIVATED with a checked-in officer, plan B SUBMITTED beside it."""
    scenario = _two_band_submitted_plan(staffed_floor)
    scenario.build_approved_plan()
    scenario.build_activated_plan()
    plan_a = scenario.plan
    scenario.extras["plan_a"] = plan_a

    scenario.set_clock(CLOCK_1000)
    scenario.build_checked_in()

    # The shared lane is a STANDARD lane, so it hosts an ADVANCED_IMAGING unit;
    # PRD 3.3 therefore requires that certification on top of STANDARD_LANE.
    rival_officer = scenario.create_officer(
        badge_number="B-1002",
        full_name="Bea Ridge",
        certifications=["STANDARD_LANE", "ADVANCED_IMAGING"],
        base_rate_cents_per_minute=100,
        weekly_regular_minutes_cap=45,
        weekly_overtime_minutes_cap=600,
    )
    scenario.extras["rival_officer"] = rival_officer
    scenario.build_forecast_band(BAND_1400, FLIGHT_1430)
    rival_band = scenario.extras["bands"][2]

    scenario.extras["checkpoint_version_before"] = scenario.checkpoint_version()
    plan_b = scenario.create_plan(
        expected_checkpoint_version=scenario.extras["checkpoint_version_before"],
        headers=SECOND_PLANNER_HEADERS,
    )
    scenario.extras["plan_b"] = plan_b
    scenario.extras["rival_assignment"] = validate_success(
        scenario.api.create_lane_assignment(
            f.lane_assignment_payload(
                plan_b["id"], scenario.lane_id, rival_officer["id"], rival_band["id"]
            ),
            SECOND_PLANNER_HEADERS,
        ),
        201,
    )
    validate_success(
        scenario.api.submit_staffing_plan(plan_b["id"], SECOND_PLANNER_HEADERS)
    )
    return scenario


def _approve_rival(scenario: Scenario) -> dict:
    return validate_success(
        scenario.api.decide_staffing_plan(
            scenario.extras["plan_b"]["id"],
            f.plan_decision_payload("APPROVE"),
            DUTY_MANAGER_HEADERS,
        )
    )


class TestSupersedeCascade:
    """PRD 3.4 - approving one plan retires every rival plan for the same day."""

    def test_approving_a_rival_supersedes_the_activated_plan_it_never_names(
        self, staffed_floor: Scenario
    ):
        """Link one: the losing plan is found by checkpoint and date, not by reference.

        Design: Difficulty/transitive_cascade/plan_approval_supersede_depth_three
        """
        scenario = _rival_plan_ready_to_approve(staffed_floor)
        plan_a, plan_b = scenario.extras["plan_a"], scenario.extras["plan_b"]

        approved = _approve_rival(scenario)
        assert approved["state"] == "APPROVED"
        assert approved["approved_by_user_id"] == "duty-1"

        loser = validate_success(scenario.api.get_staffing_plan(plan_a["id"], PLANNER_HEADERS))
        assert loser["state"] == "SUPERSEDED"
        assert loser["superseded_by_staffing_plan_id"] == plan_b["id"]

    def test_the_superseded_plan_retires_each_row_along_its_own_edge(
        self, staffed_floor: Scenario
    ):
        """Link two: a checked-in row is RELEASED while a scheduled row is CANCELLED.

        Design: Difficulty/transitive_cascade/plan_approval_supersede_depth_three
        """
        scenario = _rival_plan_ready_to_approve(staffed_floor)
        first, second = scenario.extras["assignments"]

        _approve_rival(scenario)

        released = validate_success(
            scenario.api.get_lane_assignment(first["id"], PLANNER_HEADERS)
        )
        assert released["assignment_state"] == "RELEASED"
        assert_instant(released["released_at_utc"], CLOCK_1000, "released_at_utc")

        cancelled = validate_success(
            scenario.api.get_lane_assignment(second["id"], PLANNER_HEADERS)
        )
        assert cancelled["assignment_state"] == "CANCELLED"

        rows, _meta = validate_paginated(
            scenario.api.list_lane_assignments(
                PLANNER_HEADERS,
                {
                    "staffing_plan_id": scenario.extras["plan_a"]["id"],
                    "assignment_state": "CANCELLED",
                },
            )
        )
        assert [row["id"] for row in rows] == [second["id"]]

    def test_the_drained_duty_ledger_sends_the_officer_off_duty(
        self, staffed_floor: Scenario
    ):
        """Link three: the officer axis moves because the ledger reached zero.

        Design: Difficulty/transitive_cascade/plan_approval_supersede_depth_three
        """
        scenario = _rival_plan_ready_to_approve(staffed_floor)
        before = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        assert_officer_ledger(before, committed_duty_minutes=60, duty_status="ON_DUTY")

        _approve_rival(scenario)

        after = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        assert_officer_ledger(after, committed_duty_minutes=0, duty_status="OFF_DUTY")

        # The winning plan's own rows and its officer are untouched by the cascade.
        rival_row = validate_success(
            scenario.api.get_lane_assignment(
                scenario.extras["rival_assignment"]["id"], PLANNER_HEADERS
            )
        )
        assert rival_row["assignment_state"] == "SCHEDULED"
        rival_officer = validate_success(
            scenario.api.get_officer(
                scenario.extras["rival_officer"]["id"], PLANNER_HEADERS
            )
        )
        assert_officer_ledger(rival_officer, committed_duty_minutes=30)

    def test_the_winning_plan_keeps_its_own_price_and_bumps_the_checkpoint_version(
        self, staffed_floor: Scenario
    ):
        """The approval prices only the winner and makes a read version stale.

        Design: Difficulty/transitive_cascade/plan_approval_supersede_depth_three
        """
        scenario = _rival_plan_ready_to_approve(staffed_floor)
        version_before = scenario.extras["checkpoint_version_before"]

        approved = _approve_rival(scenario)
        assert_plan_cost(
            approved,
            subtotal_cents=3000,
            admin_fee_rate="0.060",
            admin_fee_cents=180,
            total_cost_cents=3180,
        )

        checkpoint = validate_success(
            scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
        )
        assert checkpoint["version"] > version_before, (
            "the approval advances the parent checkpoint version"
        )


class TestRevisionCycle:
    """PRD 3.4 - REJECTED to DRAFT is a backward edge that resets the price."""

    def test_rejection_retains_the_price_and_revise_clears_the_whole_cost_block(
        self, staffed_floor: Scenario
    ):
        """Going backwards increments the revision and nulls all nine cost fields.

        Design: Difficulty/non_linear_state_machine/staffing_plan_rejected_to_draft_revision_cycle
        """
        scenario = _two_band_submitted_plan(staffed_floor)

        rejected = scenario.reject_plan(rejection_reason_code="COST")
        assert rejected["state"] == "REJECTED"
        assert rejected["rejection_reason_code"] == "COST"
        assert rejected["revision_number"] == 1
        assert rejected["total_cost_cents"] == 7054, (
            "a rejection is inert - the computed price stays on the record"
        )
        for assignment in scenario.extras["assignments"]:
            row = validate_success(
                scenario.api.get_lane_assignment(assignment["id"], PLANNER_HEADERS)
            )
            assert row["assignment_state"] == "SCHEDULED"

        revised = validate_success(
            scenario.api.revise_staffing_plan(scenario.plan_id, PLANNER_HEADERS)
        )
        assert revised["state"] == "DRAFT"
        assert revised["revision_number"] == 2
        assert_nulls(revised, ("rejection_reason_code", "submitted_at_utc"))
        assert_nulls(revised, COST_FIELDS)

    def test_resubmitting_a_revised_plan_reprices_from_scratch(self, staffed_floor: Scenario):
        """The second pass recomputes the identical price and holds the revision at 2.

        Design: Difficulty/non_linear_state_machine/staffing_plan_rejected_to_draft_revision_cycle
        """
        scenario = _two_band_submitted_plan(staffed_floor)
        scenario.reject_plan(rejection_reason_code="COST")
        validate_success(scenario.api.revise_staffing_plan(scenario.plan_id, PLANNER_HEADERS))

        resubmitted = scenario.submit_plan()
        assert resubmitted["state"] == "SUBMITTED"
        assert resubmitted["revision_number"] == 2, (
            "revision_number moves on revise, never on submit"
        )
        assert_plan_cost(
            resubmitted,
            subtotal_cents=6750,
            admin_fee_rate="0.045",
            admin_fee_cents=304,
            total_cost_cents=7054,
            planned_regular_minutes=45,
            planned_overtime_minutes=15,
            base_cost_cents=4500,
            overtime_cost_cents=2250,
        )
        for assignment in scenario.extras["assignments"]:
            row = validate_success(
                scenario.api.get_lane_assignment(assignment["id"], PLANNER_HEADERS)
            )
            assert row["assignment_state"] == "SCHEDULED"
