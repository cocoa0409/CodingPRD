"""Endpoint surface: partial patches, the checkpoint sweep, body links and counters."""

import pytest

from test_helpers import (
    PRACTICE_PARTNER,
    RESOURCE_MANAGER,
    ApiErrorId,
    AssertionStatus,
    AssignmentStatus,
    AvailabilityStatus,
    BenchSpellState,
    FirmApprovalStatus,
    PlacementStatus,
    Posture,
    ProgramStatus,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import INSTANT_AUG_03, INSTANT_AUG_10, INSTANT_AUG_17

UNKNOWN_CONSULTANT_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_SKILL_ID = "00000000-0000-4000-8000-000000000002"


class TestPatchesArePartialAndLocal:
    @staticmethod
    def _one_row_of_every_patchable_kind(api):
        """A group, a skill, a consultant, an assertion and a firm, each still at
        version 1."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=3,
            cost_rate_usd_per_hour=120.00,
            travel_max_nights_per_week=3,
        )
        firm = fixtures.create_firm(
            api,
            name="NorthStar Partners",
            geo_code="NA",
            max_concurrent_placements=2,
            pass_through_rate_usd_per_hour=150.00,
            approval_status=FirmApprovalStatus.PENDING,
        )
        return world, staff, firm

    def test_each_patch_rewrites_only_the_field_it_names(self, api):
        """PRD §2.4: "The `version` property is an integer that starts at 1 on creation and
        increments by one on every mutation of the row; it is the value optimistic
        concurrency control is quoted against (§2.8)."

        Design: Corner/endpoints/patch_endpoints_are_partial_and_bump_only_their_own_row
        """
        world, staff, firm = self._one_row_of_every_patchable_kind(api)
        skill = world["skill"]
        consultant = staff["consultant"]
        assertion = staff["assertion"]

        patched_skill = validate_success(
            api.patch_skill(skill["id"], {"scarcity_index": 0.8000}, PRACTICE_PARTNER), 200
        )
        assert patched_skill["scarcity_index"] == pytest.approx(0.8000, abs=0.00005)
        assert patched_skill["name"] == "Cloud Architecture"
        assert patched_skill["retired"] is False
        assert patched_skill["version"] == skill["version"] + 1

        patched_consultant = validate_success(
            api.patch_consultant(
                consultant["id"], {"cost_rate_usd_per_hour": 130.00}, RESOURCE_MANAGER
            ),
            200,
        )
        assert patched_consultant["cost_rate_usd_per_hour"] == pytest.approx(130.00, abs=0.01)
        assert patched_consultant["email"] == consultant["email"]
        assert patched_consultant["travel_max_nights_per_week"] == 3
        assert patched_consultant["version"] == consultant["version"] + 1

        patched_firm = validate_success(
            api.patch_firm(firm["id"], {"markup_pct": 25.00}, PRACTICE_PARTNER), 200
        )
        assert patched_firm["markup_pct"] == pytest.approx(25.00, abs=0.005)
        assert patched_firm["approval_status"] == FirmApprovalStatus.PENDING
        assert patched_firm["pass_through_rate_usd_per_hour"] == pytest.approx(150.00, abs=0.01)
        assert patched_firm["version"] == firm["version"] + 1

        patched_assertion = validate_success(
            api.patch_skill_assertion(
                assertion["id"], {"proficiency_level": 5}, RESOURCE_MANAGER
            ),
            200,
        )
        assert patched_assertion["proficiency_level"] == 5
        # No certification_code was ever supplied, so nothing can have expired.
        assert patched_assertion["assertion_status"] == AssertionStatus.ACTIVE
        assert patched_assertion["version"] == assertion["version"] + 1

    def test_no_neighbouring_row_moves_with_them(self, api):
        """PRD §4: "Update a consultant's level, cost rate, travel tolerance or practice
        group; the geography rule is re-checked on a group move."

        Design: Corner/endpoints/patch_endpoints_are_partial_and_bump_only_their_own_row
        """
        world, staff, _ = self._one_row_of_every_patchable_kind(api)
        # PRD §3.2: the hire already moved this group's headcounts, and PRD §2.4
        # bumps `version` on every mutation "including mutations that only touch
        # derived fields", so the baseline is read rather than assumed.
        before = fixtures.read_group(api, world["group"]["id"])["version"]

        validate_success(
            api.patch_consultant(
                staff["consultant"]["id"],
                {"cost_rate_usd_per_hour": 130.00},
                RESOURCE_MANAGER,
            ),
            200,
        )

        # A cost rate is nobody's derived field, so the group row is not rewritten.
        assert fixtures.read_group(api, world["group"]["id"])["version"] == before


class TestOneCheckpointMovesOnlyDueRows:
    @staticmethod
    def _four_machines_with_a_future_dated_twin(api):
        """Two assignments, two placements and two cohorts, one of each due on
        2026-08-17 and one of each dated a month later; the clock then stands at
        2026-08-17 with no checkpoint yet run."""
        world = fixtures.base_world(
            api, clock=INSTANT_AUG_03, external_sourcing_cap_pct=100.00
        )
        # PRD §3.6 refuses every external-sourcing write while the demand's
        # practice group posture is FROZEN, and PRD §2.10 freezes any group whose
        # whole headcount is on the bench, so consultants are hired elsewhere.
        fixtures.add_bench_group(api, world)
        firm = fixtures.create_firm(
            api,
            name="NorthStar Partners",
            geo_code="NA",
            max_concurrent_placements=4,
            pass_through_rate_usd_per_hour=150.00,
            approval_status=FirmApprovalStatus.APPROVED,
        )
        now_staff = fixtures.hire(
            api,
            world,
            full_name="Now Starter",
            proficiency_level=4,
            group_key="bench_group",
        )
        due_demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=2.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        due_assignment = fixtures.confirmed_assignment(
            api,
            now_staff["consultant"]["id"],
            due_demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-17",
            end_date="2026-08-29",
        )

        fixtures.set_clock(api, INSTANT_AUG_10)
        later_staff = fixtures.hire(
            api,
            world,
            full_name="Later Starter",
            proficiency_level=4,
            group_key="bench_group",
        )
        later_demand = fixtures.qualified_demand(
            api,
            world,
            client_name="Autumn Corp",
            required_fte=1.00,
            start_date="2026-09-01",
            end_date="2026-09-30",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        later_assignment = fixtures.confirmed_assignment(
            api,
            later_staff["consultant"]["id"],
            later_demand["id"],
            allocation_pct=100.00,
            start_date="2026-09-01",
            end_date="2026-10-01",
        )

        external_demand = fixtures.qualified_demand(
            api,
            world,
            staffing_mode="EXTERNAL",
            client_name="External Client",
            required_fte=4.00,
            start_date="2026-08-17",
            end_date="2026-09-30",
            industry_code="BANKING",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        due_placement = fixtures.approved_placement(
            api,
            firm["id"],
            external_demand["id"],
            fte=1.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
        )
        later_placement = fixtures.approved_placement(
            api,
            firm["id"],
            external_demand["id"],
            fte=1.00,
            start_date="2026-09-01",
            end_date="2026-09-30",
        )

        open_cohort = fixtures.create_program(
            api,
            world["skill"]["id"],
            cohort_start_on="2026-08-03",
            cohort_end_on="2026-08-28",
            seat_capacity=2,
        )
        future_cohort = fixtures.create_program(
            api,
            world["skill"]["id"],
            cohort_start_on="2026-09-01",
            cohort_end_on="2026-09-30",
            seat_capacity=2,
        )
        fixtures.set_clock(api, INSTANT_AUG_17)
        return {
            "world": world,
            "due_assignment": due_assignment,
            "later_assignment": later_assignment,
            "due_placement": due_placement,
            "later_placement": later_placement,
            "open_cohort": open_cohort,
            "future_cohort": future_cohort,
            "later_consultant": later_staff["consultant"],
        }

    def test_only_the_commitments_that_have_started_are_activated(self, api):
        """PRD §3.9: "It activates due commitments: every `CONFIRMED` assignment whose
        `start_date` has arrived becomes `ACTIVE` with `activated_on` stamped, and every
        `APPROVED` external placement whose `start_date` has arrived becomes `ACTIVE`."

        Design: Corner/endpoints/one_bench_run_moves_only_the_rows_whose_clock_test_passes
        """
        scene = self._four_machines_with_a_future_dated_twin(api)
        fixtures.bench_run(api)

        active_assignments, meta = validate_paginated(
            api.list_assignments(RESOURCE_MANAGER, {"status": AssignmentStatus.ACTIVE})
        )
        assert meta["total_count"] == 1
        assert active_assignments[0]["id"] == scene["due_assignment"]["id"]
        assert active_assignments[0]["activated_on"] == "2026-08-17"

        untouched_assignment = fixtures.read_assignment(
            api, scene["later_assignment"]["id"]
        )
        assert untouched_assignment["status"] == AssignmentStatus.CONFIRMED
        assert untouched_assignment["activated_on"] is None

        active_placements, placement_meta = validate_paginated(
            api.list_placements(RESOURCE_MANAGER, {"status": PlacementStatus.ACTIVE})
        )
        assert placement_meta["total_count"] == 1
        assert active_placements[0]["id"] == scene["due_placement"]["id"]
        assert (
            fixtures.read_placement(api, scene["later_placement"]["id"])["status"]
            == PlacementStatus.APPROVED
        )

    def test_only_the_due_cohort_starts_and_the_young_spell_stays_put(self, api):
        """PRD §3.9: "And it starts due cohorts: every `PLANNED` programme whose
        `cohort_start_on` has arrived becomes `RUNNING`."
        PRD §3.8: "A spell in `MONITORING` whose `age_days` has reached the level-one
        escalation threshold for its consultant's level moves to `ESCALATED_L1` and its
        `escalation_count` increases by one; a spell in `ESCALATED_L1` whose `age_days` has
        reached the level-two threshold moves to `ESCALATED_L2` and its `escalation_count`
        increases by one again."

        Design: Corner/endpoints/one_bench_run_moves_only_the_rows_whose_clock_test_passes
        """
        scene = self._four_machines_with_a_future_dated_twin(api)
        fixtures.bench_run(api)

        running, meta = validate_paginated(
            api.list_reskilling_programs(
                RESOURCE_MANAGER, {"status": ProgramStatus.RUNNING}
            )
        )
        assert meta["total_count"] == 1
        assert running[0]["id"] == scene["open_cohort"]["id"]
        assert (
            fixtures.read_program(api, scene["future_cohort"]["id"])["status"]
            == ProgramStatus.PLANNED
        )

        # Hired 2026-08-10, so the spell is 7 days old against a 14-day L1 threshold.
        young_spell = fixtures.open_spell_of(api, scene["later_consultant"]["id"])
        assert young_spell["state"] == BenchSpellState.MONITORING
        assert young_spell["escalation_count"] == 0
        assert young_spell["age_days"] == 7


class TestTheAssertionLinkResolvesItsBodyKeysInOrder:
    def test_the_first_declared_key_decides_which_404_is_returned(self, api):
        """PRD §2.7: "Body-borne foreign keys are resolved **in the order the owning entity
        declares its fields**, which is the order §3 introduces them."

        Design: Corner/endpoints/skill_assertion_link_validates_body_fks_in_declared_order
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=None)

        # §3.2 declares consultant_id before skill_id, so the consultant answers first.
        validate_error(
            api.create_skill_assertion(
                factories.skill_assertion_payload(
                    UNKNOWN_CONSULTANT_ID, UNKNOWN_SKILL_ID, proficiency_level=3
                ),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_CONSULTANT_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_skill_assertion(
                factories.skill_assertion_payload(
                    staff["consultant"]["id"], UNKNOWN_SKILL_ID, proficiency_level=3
                ),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_SKILL_NOT_FOUND,
            404,
        )
        _, meta = validate_paginated(api.list_skill_assertions(RESOURCE_MANAGER))
        assert meta["total_count"] == 0

    def test_the_valid_pair_links_and_reads_back_from_both_sides(self, api):
        """PRD §3.2: "**Skill assertions** are the many-to-many junction between a consultant
        and the taxonomy, and they are the only evidence the staffing gates accept."

        Design: Corner/endpoints/skill_assertion_link_validates_body_fks_in_declared_order
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=None)
        consultant_id = staff["consultant"]["id"]
        skill_id = world["skill"]["id"]

        assertion = validate_success(
            api.create_skill_assertion(
                factories.skill_assertion_payload(
                    consultant_id, skill_id, proficiency_level=3
                ),
                RESOURCE_MANAGER,
            ),
            201,
        )
        assert assertion["consultant_id"] == consultant_id
        assert assertion["skill_id"] == skill_id
        assert assertion["assertion_status"] == AssertionStatus.ACTIVE

        _, by_consultant = validate_paginated(
            api.list_skill_assertions(RESOURCE_MANAGER, {"consultant_id": consultant_id})
        )
        assert by_consultant["total_count"] == 1
        _, by_skill = validate_paginated(
            api.list_skill_assertions(RESOURCE_MANAGER, {"skill_id": skill_id})
        )
        assert by_skill["total_count"] == 1


class TestTheInternalProjectRoute:
    @staticmethod
    def _a_lone_benched_consultant(api):
        """One consultant alone in their group: own_bench_ratio 1.0000 and FROZEN."""
        world = fixtures.base_world(api, clock="2026-08-01T00:00:00Z")
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=None)
        consultant_id = staff["consultant"]["id"]
        spell = fixtures.open_spell_of(api, consultant_id)
        assert spell["state"] == BenchSpellState.MONITORING
        assert fixtures.read_group(api, world["group"]["id"])["posture"] == Posture.FROZEN
        return world, consultant_id, spell

    def test_a_monitoring_spell_is_too_fresh_to_be_parked(self, api):
        """PRD §3.8: "`MONITORING` is the only state from which nothing but the ladder and a
        confirmation can move a spell: enrolment and internal-project placement both refuse a
        `MONITORING` spell with `ERR_BENCH_SPELL_STATE_INVALID`, because the firm does not
        spend money on a consultant who has only just come off a project."

        Design: Corner/endpoints/internal_project_is_conditional_on_escalation_and_expires_after_thirty_days
        """
        _, consultant_id, spell = self._a_lone_benched_consultant(api)

        validate_error(
            api.start_internal_project(spell["id"], "IP-TOOLING-01", RESOURCE_MANAGER),
            ApiErrorId.ERR_BENCH_SPELL_STATE_INVALID,
            409,
        )
        after = fixtures.read_spell(api, spell["id"])
        assert after["state"] == BenchSpellState.MONITORING
        assert after["internal_project_code"] is None
        assert (
            fixtures.read_consultant(api, consultant_id)["availability_status"]
            == AvailabilityStatus.BENCH
        )

    def test_the_park_relaxes_the_posture_and_expires_on_the_thirtieth_day(self, api):
        """PRD §3.8: "The return is automatic: at the first operations checkpoint at which the
        whole number of days from `investment_started_on` to the logical clock date has
        reached 30, the spell returns to `MONITORING` with `age_reset_on` and
        `investment_ended_on` both stamped from the clock date, and the consultant's
        `availability_status` returns to `BENCH`, which puts them back into `bench_headcount`
        and re-derives the ratios and posture up the ancestor chain."

        Design: Corner/endpoints/internal_project_is_conditional_on_escalation_and_expires_after_thirty_days
        """
        world, consultant_id, spell = self._a_lone_benched_consultant(api)
        group_id = world["group"]["id"]

        fixtures.advance_clock_and_run(api, "2026-08-15T00:00:00Z")
        assert (
            fixtures.read_spell(api, spell["id"])["state"] == BenchSpellState.ESCALATED_L1
        )

        parked = validate_success(
            api.start_internal_project(spell["id"], "IP-TOOLING-01", RESOURCE_MANAGER), 200
        )
        assert parked["state"] == BenchSpellState.INTERNAL_PROJECT
        assert parked["internal_project_code"] == "IP-TOOLING-01"
        assert parked["investment_started_on"] == "2026-08-15"
        assert (
            fixtures.read_consultant(api, consultant_id)["availability_status"]
            == AvailabilityStatus.INTERNAL_PROJECT
        )
        relaxed = fixtures.read_group(api, group_id)
        assert relaxed["total_headcount"] == 1
        assert relaxed["bench_headcount"] == 0
        assert relaxed["own_bench_ratio"] == pytest.approx(0.0000, abs=0.00005)
        assert relaxed["posture"] == Posture.OPEN

        # 2026-08-15 to 2026-09-13 is 29 whole days: one day short.
        fixtures.advance_clock_and_run(api, "2026-09-13T00:00:00Z")
        assert (
            fixtures.read_spell(api, spell["id"])["state"]
            == BenchSpellState.INTERNAL_PROJECT
        )

        fixtures.advance_clock_and_run(api, "2026-09-14T00:00:00Z")
        returned = fixtures.read_spell(api, spell["id"])
        assert returned["state"] == BenchSpellState.MONITORING
        assert returned["age_reset_on"] == "2026-09-14"
        assert returned["investment_ended_on"] == "2026-09-14"
        assert (
            fixtures.read_consultant(api, consultant_id)["availability_status"]
            == AvailabilityStatus.BENCH
        )
        assert fixtures.read_group(api, group_id)["posture"] == Posture.FROZEN


class TestDerivedCountersReadBackThroughTheirOwnEndpoints:
    @staticmethod
    def _one_enrolment_and_one_approved_placement(api):
        """An escalated consultant enrolled in a three-seat cohort, a brand-new consultant
        still monitoring, and one approved placement against an APPROVED firm."""
        world = fixtures.base_world(
            api, clock="2026-08-01T00:00:00Z", external_sourcing_cap_pct=100.00
        )
        # PRD §3.6 refuses every external-sourcing write while the demand's
        # practice group posture is FROZEN, and PRD §2.10 freezes any group whose
        # whole headcount is on the bench, so consultants are hired elsewhere.
        fixtures.add_bench_group(api, world)
        escalated = fixtures.hire(
            api,
            world,
            full_name="Escalated One",
            proficiency_level=None,
            group_key="bench_group",
        )
        firm = fixtures.create_firm(
            api,
            name="NorthStar Partners",
            geo_code="NA",
            max_concurrent_placements=3,
            pass_through_rate_usd_per_hour=150.00,
            approval_status=FirmApprovalStatus.APPROVED,
        )
        assert firm["active_placements_count"] == 0
        demand = fixtures.qualified_demand(
            api,
            world,
            staffing_mode="EXTERNAL",
            client_name="External Client",
            required_fte=2.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
            industry_code="BANKING",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )

        fixtures.set_clock(api, "2026-08-15T00:00:00Z")
        fresh = fixtures.hire(
            api,
            world,
            full_name="Fresh Two",
            proficiency_level=None,
            group_key="bench_group",
        )
        fixtures.bench_run(api)
        program = fixtures.create_program(
            api,
            world["skill"]["id"],
            target_proficiency_level=4,
            cohort_start_on="2026-09-01",
            cohort_end_on="2026-09-30",
            seat_capacity=3,
        )
        assert program["seats_taken"] == 0
        fixtures.enrol(api, program["id"], escalated["consultant"]["id"])
        fixtures.approved_placement(
            api,
            firm["id"],
            demand["id"],
            fte=1.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
        )
        return {
            "program": program,
            "firm": firm,
            "escalated": escalated["consultant"],
            "fresh": fresh["consultant"],
        }

    def test_neither_counter_is_ever_an_input(self, api):
        """PRD §3.6: "A newly registered firm has an `active_placements_count` of 0; that
        count is always the number of the firm's placements whose `status` is `APPROVED` or
        `ACTIVE`."
        PRD §3.8: "The cohort is created `PLANNED` with `seats_taken` at 0, where
        `seats_taken` is always the count of spells currently enrolled in it."

        Design: Corner/endpoints/derived_counters_are_only_readable_through_their_own_list_and_detail_reads
        """
        scene = self._one_enrolment_and_one_approved_placement(api)

        program = fixtures.read_program(api, scene["program"]["id"])
        assert program["seats_taken"] == 1
        # The 2026-08-15 checkpoint ran before this cohort existed and it opens 2026-09-01.
        assert program["status"] == ProgramStatus.PLANNED
        assert fixtures.read_firm(api, scene["firm"]["id"])["active_placements_count"] == 1

    def test_the_spell_filters_partition_the_two_spells(self, api):
        """PRD §3.8: "Spells are read as a list filtered by `consultant_id`, `state` and
        `reskilling_program_id`, or one at a time; there is no way to create one by hand."

        Design: Corner/endpoints/derived_counters_are_only_readable_through_their_own_list_and_detail_reads
        """
        scene = self._one_enrolment_and_one_approved_placement(api)

        reskilling, reskilling_meta = validate_paginated(
            api.list_bench_spells(RESOURCE_MANAGER, {"state": BenchSpellState.RESKILLING})
        )
        assert reskilling_meta["total_count"] == 1
        assert reskilling[0]["consultant_id"] == scene["escalated"]["id"]

        monitoring, monitoring_meta = validate_paginated(
            api.list_bench_spells(RESOURCE_MANAGER, {"state": BenchSpellState.MONITORING})
        )
        assert monitoring_meta["total_count"] == 1
        assert monitoring[0]["consultant_id"] == scene["fresh"]["id"]

        _, by_program = validate_paginated(
            api.list_bench_spells(
                RESOURCE_MANAGER, {"reskilling_program_id": scene["program"]["id"]}
            )
        )
        assert by_program["total_count"] == 1
