"""Gates that live on a row the request never names: parent state decides."""

import pytest

from test_helpers import (
    PRACTICE_PARTNER,
    RESOURCE_MANAGER,
    ApiErrorId,
    AssignmentStatus,
    AvailabilityStatus,
    BenchSpellState,
    PlacementStatus,
    Posture,
    ProgramStatus,
    StaffingStatus,
    assert_bench_ratio,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import INSTANT_AUG_03


class TestAssignmentGatedByItsDemand:
    @staticmethod
    def _one_unqualified_and_one_external_demand(api):
        """D1 still QUALIFYING with no branch; D2 QUALIFIED on the EXTERNAL branch."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
        )
        untouched = fixtures.create_demand(
            api,
            world["group"]["id"],
            world["skill"]["id"],
            client_name="Acme Retail",
            required_fte=1.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        external = fixtures.qualified_demand(
            api,
            world,
            staffing_mode="EXTERNAL",
            client_name="Globex Bank",
            required_fte=1.00,
            industry_code="BANKING",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        return world, staff, untouched, external

    def test_the_pipeline_gate_answers_before_the_branch_gate(self, api):
        """PRD §2.9: "8. **Demand pipeline state** — qualification requires
        `QUALIFYING`; staffing-branch selection requires `QUALIFYING` or `QUALIFIED` with
        the branch still unset; closure requires `QUALIFIED`; auto-staffing, assignment
        proposal and external-placement request all require `QUALIFIED`;
        discount-approval creation is likewise gated here. Failure:
        `ERR_OPPORTUNITY_STATE_INVALID` (409)."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_gated_by_opportunity_pipeline_then_staffing_mode
        """
        _, staff, untouched, _ = self._one_unqualified_and_one_external_demand(api)
        consultant_id = staff["consultant"]["id"]
        version = fixtures.consultant_version(api, consultant_id)

        response = api.create_assignment(
            factories.assignment_payload(
                consultant_id,
                untouched["id"],
                version,
                allocation_pct=60.00,
                start_date="2026-08-03",
                end_date="2026-08-29",
            ),
            RESOURCE_MANAGER,
        )

        # The unset staffing_mode breaks rung 36 too; rung 8 answers first.
        error = validate_error(response, ApiErrorId.ERR_OPPORTUNITY_STATE_INVALID, 409)
        assert error["error_id"] != ApiErrorId.ERR_STAFFING_MODE_MISMATCH

        _, meta = validate_paginated(
            api.list_assignments(
                RESOURCE_MANAGER, {"demand_opportunity_id": untouched["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_the_branch_gate_answers_next_and_the_same_payload_then_lands(self, api):
        """PRD §2.9: "36. **Branch coherence** — assignment proposal and auto-staffing
        require `staffing_mode` to be `INTERNAL`; external-placement request and
        placement approval require `staffing_mode` to be `EXTERNAL`. Failure:
        `ERR_STAFFING_MODE_MISMATCH` (409)."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_gated_by_opportunity_pipeline_then_staffing_mode
        """
        _, staff, untouched, external = self._one_unqualified_and_one_external_demand(api)
        consultant_id = staff["consultant"]["id"]
        version = fixtures.consultant_version(api, consultant_id)

        def payload(demand_id):
            return factories.assignment_payload(
                consultant_id,
                demand_id,
                version,
                allocation_pct=60.00,
                start_date="2026-08-03",
                end_date="2026-08-29",
            )

        wrong_branch = api.create_assignment(payload(external["id"]), RESOURCE_MANAGER)
        validate_error(wrong_branch, ApiErrorId.ERR_STAFFING_MODE_MISMATCH, 409)

        # Neither rejection touched the parent, so the quoted version is still current.
        assert fixtures.consultant_version(api, consultant_id) == version

        fixtures.qualify(api, untouched["id"])
        fixtures.set_mode(api, untouched["id"], "INTERNAL")

        accepted = validate_success(
            api.create_assignment(payload(untouched["id"]), RESOURCE_MANAGER), 201
        )
        assert accepted["status"] == AssignmentStatus.PROPOSED
        assert accepted["allocation_pct"] == pytest.approx(60.00, abs=0.005)

        consultant = fixtures.read_consultant(api, consultant_id)
        assert consultant["allocated_pct"] == pytest.approx(0.00, abs=0.005)
        assert consultant["availability_status"] == AvailabilityStatus.BENCH


class TestPlacementGatedByPostureAndScarcity:
    @staticmethod
    def _constrained_practice_with_an_external_demand(api):
        """Two of three heads staffed, so own_bench_ratio is 0.3333 and the group
        posture is CONSTRAINED, with a second demand on the EXTERNAL branch."""
        world = fixtures.base_world(
            api, clock=INSTANT_AUG_03, external_sourcing_cap_pct=60.00
        )
        internal_demand = fixtures.qualified_demand(
            api,
            world,
            client_name="Acme Retail",
            required_fte=2.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        staffed = []
        for name, cost in (("Ada Byron", 120.00), ("Alan Turing", 130.00)):
            hired = fixtures.hire(
                api,
                world,
                full_name=name,
                proficiency_level=4,
                cost_rate_usd_per_hour=cost,
            )
            fixtures.confirmed_assignment(
                api,
                hired["consultant"]["id"],
                internal_demand["id"],
                allocation_pct=100.00,
                start_date="2026-08-03",
                end_date="2026-08-29",
            )
            staffed.append(hired)
        benched = fixtures.hire(
            api,
            world,
            full_name="Grace Hopper",
            proficiency_level=4,
            cost_rate_usd_per_hour=140.00,
        )
        external = fixtures.demand_with_external_branch(
            api,
            world,
            firm_kwargs={
                "name": "NorthStar Partners",
                "geo_code": "NA",
                "max_concurrent_placements": 2,
                "pass_through_rate_usd_per_hour": 150.00,
            },
            demand_kwargs={
                "client_name": "Globex Bank",
                "required_fte": 2.00,
                "win_probability_pct": 70,
                "industry_code": "BANKING",
                "standard_rate_usd_per_hour": 250.00,
                "requested_rate_usd_per_hour": 240.00,
            },
        )
        return world, staffed, benched, internal_demand, external

    def test_a_constrained_practice_refuses_the_placement_outright(self, api):
        """PRD §2.9: "43. **Constrained posture with scarcity carve-out** — when the
        demand's practice group `posture` is `CONSTRAINED`, external sourcing is refused
        unless the demand's required skill has a `scarcity_index` of at least 0.7000.
        Applies to external-placement request and placement approval. Failure:
        `ERR_PRACTICE_POSTURE_CONSTRAINED` (409)."

        Design: Difficulty/cross_entity_state_dependency/external_placement_gated_by_group_posture_with_skill_scarcity_carveout
        """
        world, _, benched, _, external = self._constrained_practice_with_an_external_demand(
            api
        )

        group = fixtures.read_group(api, world["group"]["id"])
        assert group["total_headcount"] == 3
        assert group["bench_headcount"] == 1
        assert_bench_ratio(group, 0.3333, 0.3333, Posture.CONSTRAINED)
        assert fixtures.read_skill(api, world["skill"]["id"])[
            "scarcity_index"
        ] == pytest.approx(0.5000, abs=0.00005)

        response = api.create_placement(
            factories.placement_payload(
                external["firm"]["id"],
                external["demand"]["id"],
                fte=1.00,
                start_date="2026-08-03",
                end_date="2026-08-28",
            ),
            RESOURCE_MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_PRACTICE_POSTURE_CONSTRAINED, 409)

        _, meta = validate_paginated(api.list_placements(RESOURCE_MANAGER))
        assert meta["total_count"] == 0
        assert fixtures.read_firm(api, external["firm"]["id"])[
            "active_placements_count"
        ] == 0
        assert (
            fixtures.read_consultant(api, benched["consultant"]["id"])[
                "availability_status"
            ]
            == AvailabilityStatus.BENCH
        )

    def test_raising_the_skills_scarcity_alone_opens_the_carve_out(self, api):
        """PRD §3.2: "Raising `scarcity_index` to 0.7000 or higher opens the carve-out
        that lets external sourcing proceed against a `CONSTRAINED` practice — the market
        judgement being that a genuinely scarce skill is worth buying even from a
        practice already carrying too much bench."

        Design: Difficulty/cross_entity_state_dependency/external_placement_gated_by_group_posture_with_skill_scarcity_carveout
        """
        world, _, benched, _, external = self._constrained_practice_with_an_external_demand(
            api
        )
        refused = api.create_placement(
            factories.placement_payload(
                external["firm"]["id"],
                external["demand"]["id"],
                fte=1.00,
                start_date="2026-08-03",
                end_date="2026-08-28",
            ),
            RESOURCE_MANAGER,
        )
        validate_error(refused, ApiErrorId.ERR_PRACTICE_POSTURE_CONSTRAINED)

        scarce = validate_success(
            api.patch_skill(
                world["skill"]["id"], {"scarcity_index": 0.7000}, PRACTICE_PARTNER
            )
        )
        assert scarce["scarcity_index"] == pytest.approx(0.7000, abs=0.00005)

        placement = fixtures.create_placement(
            api,
            external["firm"]["id"],
            external["demand"]["id"],
            fte=1.00,
            start_date="2026-08-03",
            end_date="2026-08-28",
        )
        assert placement["status"] == PlacementStatus.REQUESTED

        approved = fixtures.approve_placement(api, placement["id"])
        assert approved["status"] == PlacementStatus.APPROVED

        # Nothing about the group changed; only the skill's scarcity moved.
        after_group = fixtures.read_group(api, world["group"]["id"])
        assert_bench_ratio(after_group, 0.3333, 0.3333, Posture.CONSTRAINED)
        assert after_group["bench_headcount"] == 1
        assert (
            fixtures.read_consultant(api, benched["consultant"]["id"])[
                "availability_status"
            ]
            == AvailabilityStatus.BENCH
        )

        after_demand = fixtures.read_demand(api, external["demand"]["id"])
        assert after_demand["covered_external_fte"] == pytest.approx(1.00, abs=0.005)
        assert after_demand["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert after_demand["staffing_status"] == StaffingStatus.PARTIALLY_COVERED
        assert (
            fixtures.read_firm(api, external["firm"]["id"])["active_placements_count"]
            == 1
        )


class TestEnrolmentGatedByTheBenchSpell:
    @staticmethod
    def _monitoring_bencher_and_a_planned_cohort(api):
        """A consultant whose spell is still MONITORING, plus a PLANNED cohort."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        consultant = fixtures.create_consultant(
            api,
            world["group"]["id"],
            full_name="Ada Byron",
            level="CONSULTANT",
            cost_rate_usd_per_hour=120.00,
            standard_bill_rate_usd_per_hour=300.00,
        )
        program = fixtures.create_program(
            api,
            world["skill"]["id"],
            target_proficiency_level=4,
            cohort_start_on="2026-09-01",
            cohort_end_on="2026-09-30",
            seat_capacity=2,
        )
        spell = fixtures.open_spell_of(api, consultant["id"])
        assert spell["state"] == BenchSpellState.MONITORING
        assert program["status"] == ProgramStatus.PLANNED
        return world, consultant, program, spell

    def test_a_monitoring_spell_refuses_an_enrolment_it_is_never_named_in(self, api):
        """PRD §2.9: "10. **Bench spell state** — cohort enrolment requires
        `ESCALATED_L1` or `ESCALATED_L2`; internal-project placement requires
        `ESCALATED_L1` or `ESCALATED_L2`; a separation proposal requires `ESCALATED_L2`;
        a separation decision requires `SEPARATION_PROPOSED`. A `CLOSED` or `SEPARATED`
        spell accepts nothing at all. Failure: `ERR_BENCH_SPELL_STATE_INVALID` (409)."

        Design: Difficulty/cross_entity_state_dependency/reskilling_enrollment_gated_by_bench_spell_escalation_state
        """
        world, consultant, program, spell = self._monitoring_bencher_and_a_planned_cohort(
            api
        )

        response = api.enrol_in_program(
            program["id"], consultant["id"], RESOURCE_MANAGER
        )
        validate_error(response, ApiErrorId.ERR_BENCH_SPELL_STATE_INVALID, 409)

        after_program = fixtures.read_program(api, program["id"])
        assert after_program["seats_taken"] == 0
        assert after_program["status"] == ProgramStatus.PLANNED

        after_spell = fixtures.read_spell(api, spell["id"])
        assert after_spell["state"] == BenchSpellState.MONITORING
        assert after_spell["reskilling_program_id"] is None
        assert after_spell["investment_started_on"] is None
        assert (
            fixtures.read_consultant(api, consultant["id"])["availability_status"]
            == AvailabilityStatus.BENCH
        )
        assert_bench_ratio(
            fixtures.read_group(api, world["group"]["id"]),
            1.0000,
            1.0000,
            Posture.FROZEN,
        )

    def test_the_identical_request_lands_once_a_bench_run_escalates_that_spell(self, api):
        """PRD §3.8: "**Enrolment** is a `ResourceManager` action naming a
        `consultant_id`, and it returns the consultant's bench spell rather than the
        programme, because the spell is the row that changes state."

        Design: Difficulty/cross_entity_state_dependency/reskilling_enrollment_gated_by_bench_spell_escalation_state
        """
        world, consultant, program, spell = self._monitoring_bencher_and_a_planned_cohort(
            api
        )
        validate_error(
            api.enrol_in_program(program["id"], consultant["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_BENCH_SPELL_STATE_INVALID,
        )

        fixtures.advance_clock_and_run(api, "2026-08-17T00:00:00Z")
        escalated = fixtures.read_spell(api, spell["id"])
        assert escalated["state"] == BenchSpellState.ESCALATED_L1
        assert escalated["age_days"] == 14
        assert escalated["escalation_count"] == 1

        enrolled = fixtures.enrol(api, program["id"], consultant["id"])

        # The endpoint answers with the very row the first attempt could not move.
        assert enrolled["id"] == spell["id"]
        assert enrolled["state"] == BenchSpellState.RESKILLING
        assert enrolled["reskilling_program_id"] == program["id"]
        assert enrolled["investment_started_on"] == "2026-08-17"

        after_program = fixtures.read_program(api, program["id"])
        assert after_program["seats_taken"] == 1
        # Enrolment does not start the cohort; only a checkpoint on or after
        # cohort_start_on does.
        assert after_program["status"] == ProgramStatus.PLANNED

        assert (
            fixtures.read_consultant(api, consultant["id"])["availability_status"]
            == AvailabilityStatus.RESKILLING
        )
        after_group = fixtures.read_group(api, world["group"]["id"])
        # bench_headcount counts a RESKILLING spell, so the posture does not move.
        assert after_group["bench_headcount"] == 1
        assert_bench_ratio(after_group, 1.0000, 1.0000, Posture.FROZEN)
