"""Master-data and staffing-gate validations: uniqueness, hierarchy, geography, fitness."""

import pytest

from test_helpers import (
    FINANCE_CONTROLLER,
    PRACTICE_PARTNER,
    RESOURCE_MANAGER,
    SALES_LEAD,
    ApiErrorId,
    AssertionStatus,
    AssignmentStatus,
    AvailabilityStatus,
    BenchSpellState,
    PipelineStatus,
    StaffingMode,
    StaffingStatus,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    INSTANT_AUG_03,
    INSTANT_AUG_11,
    INSTANT_AUG_17,
    INSTANT_AUG_31,
)


class TestUniquenessAcrossEveryDeclaredKey:
    def test_all_five_declared_unique_keys_refuse_their_duplicate(self, api):
        """PRD §2.9: "23. **Uniqueness** — `name` unique across practice groups, `code`
        unique across skills, `email` unique across consultants, `name` unique across
        subcontractor firms, and at most one skill assertion per consultant-and-skill
        pair. Applies to practice-group creation, skill creation, consultant creation,
        firm creation and skill-assertion creation. Failure: `ERR_UNIQUENESS_CONFLICT`
        (409)."

        Design: Corner/validations/uniqueness_conflicts_across_every_declared_unique_key
        """
        fixtures.set_clock(api, INSTANT_AUG_03)
        group = fixtures.create_group(api, name="Cloud NA", geography_code="NA")
        skill = fixtures.create_skill(
            api, code="CLOUD_ARCH", name="Cloud Architecture", family="CLOUD"
        )
        consultant = fixtures.create_consultant(
            api, group["id"], full_name="Ada Byron", email="ada.byron@firm.test"
        )
        firm = fixtures.create_firm(api, name="Northwind Partners", geo_code="NA")
        assertion = fixtures.create_assertion(
            api, consultant["id"], skill["id"], proficiency_level=4
        )

        # One duplicate per declared key, each on the creation endpoint §2.9 names.
        validate_error(
            api.create_practice_group(
                factories.practice_group_payload(name="Cloud NA", geography_code="EMEA"),
                PRACTICE_PARTNER,
            ),
            ApiErrorId.ERR_UNIQUENESS_CONFLICT,
            409,
        )
        validate_error(
            api.create_skill(
                factories.skill_payload(
                    code="CLOUD_ARCH", name="Cloud Architecture Redux", family="DATA"
                ),
                PRACTICE_PARTNER,
            ),
            ApiErrorId.ERR_UNIQUENESS_CONFLICT,
            409,
        )
        validate_error(
            api.create_consultant(
                factories.consultant_payload(
                    group["id"],
                    full_name="Grace Hopper",
                    email="ada.byron@firm.test",
                ),
                # PRD §4: POST /consultants authorises ResourceManager only, and
                # PRD §2.9 puts authorisation (rung 2) above uniqueness (rung 23).
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_UNIQUENESS_CONFLICT,
            409,
        )
        validate_error(
            api.create_firm(
                factories.firm_payload(name="Northwind Partners", geo_code="EMEA"),
                PRACTICE_PARTNER,
            ),
            ApiErrorId.ERR_UNIQUENESS_CONFLICT,
            409,
        )
        validate_error(
            api.create_skill_assertion(
                factories.skill_assertion_payload(
                    consultant["id"], skill["id"], proficiency_level=5
                ),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_UNIQUENESS_CONFLICT,
            409,
        )

        # The refused assertion did not double as an upgrade of the existing row.
        untouched = validate_success(
            api.get_skill_assertion(assertion["id"], RESOURCE_MANAGER), 200
        )
        assert untouched["proficiency_level"] == 4
        assert untouched["version"] == 1

        for response in (
            api.list_practice_groups(PRACTICE_PARTNER),
            api.list_skills(PRACTICE_PARTNER),
            api.list_consultants(PRACTICE_PARTNER),
            api.list_firms(PRACTICE_PARTNER),
            api.list_skill_assertions(RESOURCE_MANAGER),
        ):
            _, meta = validate_paginated(response)
            assert meta["total_count"] == 1

        assert fixtures.read_firm(api, firm["id"])["geo_code"] == "NA"


class TestHierarchyAcyclicity:
    def test_neither_a_self_parent_nor_a_transitive_cycle_is_admitted(self, api):
        """PRD §2.9: "24. **Hierarchy acyclicity** — `parent_group_id` must not equal the
        group's own `id` and must not close a cycle through the transitive parent chain.
        Applies to practice-group creation and practice-group update. Failure:
        `ERR_GROUP_CYCLE` (409)."

        Design: Corner/validations/parent_group_link_may_not_close_a_cycle
        """
        fixtures.set_clock(api, INSTANT_AUG_03)
        parent = fixtures.create_group(api, name="Cloud Global", geography_code="NA")
        child = fixtures.create_group(
            api,
            name="Cloud NA",
            geography_code="NA",
            parent_group_id=parent["id"],
        )

        validate_error(
            api.patch_practice_group(
                parent["id"], {"parent_group_id": parent["id"]}, PRACTICE_PARTNER
            ),
            ApiErrorId.ERR_GROUP_CYCLE,
            409,
        )
        # A → B while B's parent is already A closes a two-node cycle.
        validate_error(
            api.patch_practice_group(
                parent["id"], {"parent_group_id": child["id"]}, PRACTICE_PARTNER
            ),
            ApiErrorId.ERR_GROUP_CYCLE,
            409,
        )

        assert fixtures.read_group(api, parent["id"])["parent_group_id"] is None
        assert fixtures.read_group(api, child["id"])["parent_group_id"] == parent["id"]

        # A third level down the same chain closes nothing and is accepted.
        grandchild = fixtures.create_group(
            api,
            name="Cloud NA East",
            geography_code="NA",
            parent_group_id=child["id"],
        )
        assert grandchild["parent_group_id"] == child["id"]

        rows, meta = validate_paginated(
            api.list_child_groups(child["id"], PRACTICE_PARTNER)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == grandchild["id"]


class TestGeographyCoherence:
    def test_a_foreign_home_geo_is_refused_on_create_and_on_update(self, api):
        """PRD §2.9: "35. **Geography coherence** — a consultant's `home_geo_code` must
        equal the `geography_code` of their practice group, and a forecast's `skill_code`
        must match the `code` of an existing skill. Applies to consultant creation,
        consultant update and forecast generation. Failure: `ERR_GEOGRAPHY_MISMATCH`
        (409)."

        Design: Corner/validations/geography_must_agree_between_consultant_group_and_forecast_skill
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03, geography_code="NA")
        consultant = fixtures.create_consultant(
            api, world["group"]["id"], full_name="Ada Byron"
        )
        assert consultant["home_geo_code"] == "NA"

        validate_error(
            api.create_consultant(
                factories.consultant_payload(
                    world["group"]["id"],
                    full_name="Grace Hopper",
                    email=factories.unique_email("grace"),
                    home_geo_code="EMEA",
                ),
                # PRD §4: POST /consultants authorises ResourceManager only, and
                # PRD §2.9 puts authorisation (rung 2) above geography coherence
                # (rung 35).
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_GEOGRAPHY_MISMATCH,
            409,
        )
        _, meta = validate_paginated(api.list_consultants(PRACTICE_PARTNER))
        assert meta["total_count"] == 1

        validate_error(
            api.patch_consultant(
                # PRD §4: PATCH /consultants/{id} authorises ResourceManager only.
                consultant["id"], {"home_geo_code": "APAC"}, RESOURCE_MANAGER
            ),
            ApiErrorId.ERR_GEOGRAPHY_MISMATCH,
            409,
        )
        after = fixtures.read_consultant(api, consultant["id"])
        assert after["home_geo_code"] == "NA"
        assert after["version"] == 1

    def test_a_forecast_naming_an_unknown_skill_code_is_the_same_mismatch(self, api):
        """PRD §2.9: "35. **Geography coherence** — a consultant's `home_geo_code` must
        equal the `geography_code` of their practice group, and a forecast's `skill_code`
        must match the `code` of an existing skill. Applies to consultant creation,
        consultant update and forecast generation. Failure: `ERR_GEOGRAPHY_MISMATCH`
        (409)."

        Design: Corner/validations/geography_must_agree_between_consultant_group_and_forecast_skill
        """
        fixtures.base_world(api, clock=INSTANT_AUG_03, geography_code="NA")

        # A body value that resolves to no skill row at all: a 409, not a 404.
        validate_error(
            api.create_hiring_forecast(
                factories.hiring_forecast_payload(
                    skill_code="GHOST_ARCH", geography_code="NA"
                ),
                FINANCE_CONTROLLER,
            ),
            ApiErrorId.ERR_GEOGRAPHY_MISMATCH,
            409,
        )
        _, meta = validate_paginated(api.list_hiring_forecasts(FINANCE_CONTROLLER))
        assert meta["total_count"] == 0

        # The declared code is accepted, so the refusal was about the code alone.
        accepted = fixtures.create_forecast(
            api, skill_code="CLOUD_ARCH", geography_code="NA"
        )
        assert accepted["skill_code"] == "CLOUD_ARCH"


class TestSkillRetirement:
    def test_a_retired_skill_takes_no_new_demand_no_new_cohort_and_no_qualify(self, api):
        """PRD §2.9: "15. **Skill retirement** — a skill whose `retired` flag is true may
        not be referenced by a new demand, by a new reskilling programme, or by a
        qualification call. Failure: `ERR_SKILL_RETIRED` (409)."

        Design: Corner/validations/retiring_a_skill_blocks_new_demand_new_programmes_and_qualify
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        group_id = world["group"]["id"]
        skill_id = world["skill"]["id"]
        demand = fixtures.create_demand(api, group_id, skill_id, client_name="Acme Retail")
        assert demand["pipeline_status"] == PipelineStatus.QUALIFYING

        retired = validate_success(
            api.patch_skill(skill_id, {"retired": True}, PRACTICE_PARTNER), 200
        )
        assert retired["retired"] is True

        validate_error(
            api.create_demand(
                factories.demand_payload(group_id, skill_id, client_name="Globex Bank"),
                SALES_LEAD,
            ),
            ApiErrorId.ERR_SKILL_RETIRED,
            409,
        )
        validate_error(
            api.create_reskilling_program(
                factories.reskilling_program_payload(skill_id), RESOURCE_MANAGER
            ),
            ApiErrorId.ERR_SKILL_RETIRED,
            409,
        )
        # The demand that already exists is still refused its qualification.
        validate_error(
            api.qualify_demand(demand["id"], SALES_LEAD),
            ApiErrorId.ERR_SKILL_RETIRED,
            409,
        )

        still = fixtures.read_demand(api, demand["id"])
        assert still["pipeline_status"] == PipelineStatus.QUALIFYING
        assert still["version"] == 1

        _, demands_meta = validate_paginated(api.list_demands(SALES_LEAD))
        assert demands_meta["total_count"] == 1
        _, programs_meta = validate_paginated(
            api.list_reskilling_programs(RESOURCE_MANAGER)
        )
        assert programs_meta["total_count"] == 0


class TestBranchGatesOutrankBranchMismatch:
    @staticmethod
    def _three_demands_and_one_firm(api):
        """One QUALIFIED demand with no branch, one EXTERNAL, one INTERNAL."""
        world = fixtures.base_world(
            api, clock=INSTANT_AUG_03, external_sourcing_cap_pct=100.00
        )
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
        )
        unset = fixtures.create_demand(
            api, world["group"]["id"], world["skill"]["id"], client_name="Acme Retail"
        )
        fixtures.qualify(api, unset["id"])
        external = fixtures.qualified_demand(
            api, world, staffing_mode="EXTERNAL", client_name="Globex Bank"
        )
        internal = fixtures.qualified_demand(
            api, world, staffing_mode="INTERNAL", client_name="Initech"
        )
        firm = fixtures.create_firm(
            api,
            name="Northwind Partners",
            geo_code="NA",
            max_concurrent_placements=2,
        )
        return world, staff, unset, external, internal, firm

    def test_an_unset_branch_refuses_all_three_staffing_writes(self, api):
        """PRD §2.9: "16. **Staffing branch selected** — auto-staffing, assignment proposal
        and external-placement request all require the demand's `staffing_mode` to be set.
        Failure: `ERR_STAFFING_MODE_NOT_SET` (409)."

        Design: Corner/validations/staffing_mode_not_set_outranks_staffing_mode_mismatch
        """
        _, staff, unset, _, _, firm = self._three_demands_and_one_firm(api)
        consultant_id = staff["consultant"]["id"]
        version = fixtures.consultant_version(api, consultant_id)

        validate_error(
            api.create_assignment(
                factories.assignment_payload(consultant_id, unset["id"], version),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_STAFFING_MODE_NOT_SET,
            409,
        )
        validate_error(
            api.auto_staff_demand(unset["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_STAFFING_MODE_NOT_SET,
            409,
        )
        validate_error(
            api.create_placement(
                factories.placement_payload(firm["id"], unset["id"]), RESOURCE_MANAGER
            ),
            ApiErrorId.ERR_STAFFING_MODE_NOT_SET,
            409,
        )

        still = fixtures.read_demand(api, unset["id"])
        assert still["pipeline_status"] == PipelineStatus.QUALIFIED
        assert still["staffing_mode"] is None
        assert still["staffing_status"] == StaffingStatus.UNSTAFFED

        _, meta = validate_paginated(
            api.list_assignments(RESOURCE_MANAGER, {"demand_opportunity_id": unset["id"]})
        )
        assert meta["total_count"] == 0

    def test_each_branch_refuses_the_other_branchs_write(self, api):
        """PRD §2.9: "36. **Branch coherence** — assignment proposal and auto-staffing
        require `staffing_mode` to be `INTERNAL`; external-placement request and placement
        approval require `staffing_mode` to be `EXTERNAL`. Failure:
        `ERR_STAFFING_MODE_MISMATCH` (409)."

        Design: Corner/validations/staffing_mode_not_set_outranks_staffing_mode_mismatch
        """
        _, staff, _, external, internal, firm = self._three_demands_and_one_firm(api)
        consultant_id = staff["consultant"]["id"]
        version = fixtures.consultant_version(api, consultant_id)

        validate_error(
            api.create_assignment(
                factories.assignment_payload(consultant_id, external["id"], version),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_STAFFING_MODE_MISMATCH,
            409,
        )
        validate_error(
            api.auto_staff_demand(external["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_STAFFING_MODE_MISMATCH,
            409,
        )
        validate_error(
            api.create_placement(
                factories.placement_payload(firm["id"], internal["id"]),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_STAFFING_MODE_MISMATCH,
            409,
        )

        # PRD §2.9 rung 8: branch selection needs the branch still unset, so a
        # second call is a pipeline-state refusal rather than a mismatch.
        validate_error(
            api.set_staffing_mode(external["id"], "INTERNAL", RESOURCE_MANAGER),
            ApiErrorId.ERR_OPPORTUNITY_STATE_INVALID,
            409,
        )
        assert (
            fixtures.read_demand(api, external["id"])["staffing_mode"]
            == StaffingMode.EXTERNAL
        )
        assert fixtures.consultant_version(api, consultant_id) == version

        _, assignments_meta = validate_paginated(api.list_assignments(RESOURCE_MANAGER))
        assert assignments_meta["total_count"] == 0
        _, placements_meta = validate_paginated(api.list_placements(RESOURCE_MANAGER))
        assert placements_meta["total_count"] == 0


class TestSeparatedConsultantIsRefusedEverywhere:
    def test_no_assertion_no_assignment_and_no_period_after_separation(self, api):
        """PRD §2.9: "17. **Consultant not separated** — assignment proposal, assignment
        confirmation, skill-assertion creation, cohort enrolment and utilization-period
        creation all require the named consultant's `availability_status` to be anything
        other than `SEPARATED`. Failure: `ERR_CONSULTANT_SEPARATED` (409)."

        Design: Corner/validations/separated_consultant_is_refused_for_assertions_staffing_and_periods
        """
        world = fixtures.base_world(api, clock="2026-08-01T00:00:00Z")
        second_skill = fixtures.create_skill(
            api, code="DATA_ENG", name="Data Engineering", family="DATA"
        )
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
        )
        consultant_id = staff["consultant"]["id"]
        demand = fixtures.qualified_demand(api, world, staffing_mode="INTERNAL")
        version = fixtures.consultant_version(api, consultant_id)

        fixtures.separated_consultant(
            api,
            world,
            consultant_id,
            l1_instant="2026-08-15T00:00:00Z",
            l2_instant=INSTANT_AUG_31,
        )
        separated = fixtures.read_consultant(api, consultant_id)
        assert separated["availability_status"] == AvailabilityStatus.SEPARATED

        validate_error(
            api.create_skill_assertion(
                factories.skill_assertion_payload(
                    consultant_id, second_skill["id"], proficiency_level=3
                ),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_CONSULTANT_SEPARATED,
            409,
        )
        # A current expected_consultant_version, so the OCC guard is not what bites.
        validate_error(
            api.create_assignment(
                factories.assignment_payload(
                    consultant_id, demand["id"], separated["version"]
                ),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_CONSULTANT_SEPARATED,
            409,
        )
        validate_error(
            api.create_utilization_period(
                consultant_id,
                factories.utilization_period_payload(
                    period_start_on="2026-09-01", period_end_on="2026-09-30"
                ),
                FINANCE_CONTROLLER,
            ),
            ApiErrorId.ERR_CONSULTANT_SEPARATED,
            409,
        )
        assert separated["version"] > version

        _, assignments_meta = validate_paginated(api.list_assignments(RESOURCE_MANAGER))
        assert assignments_meta["total_count"] == 0
        _, assertions_meta = validate_paginated(
            api.list_skill_assertions(RESOURCE_MANAGER, {"consultant_id": consultant_id})
        )
        assert assertions_meta["total_count"] == 1
        _, periods_meta = validate_paginated(
            api.list_utilization_periods(consultant_id, FINANCE_CONTROLLER)
        )
        assert periods_meta["total_count"] == 0

        group = fixtures.read_group(api, world["group"]["id"])
        assert group["total_headcount"] == 0
        assert group["bench_headcount"] == 0


class TestReskillingBlocksConfirmationOnly:
    def test_a_proposal_survives_the_enrolment_but_the_confirmation_does_not(self, api):
        """PRD §2.9: "18. **Consultant not mid-programme** — assignment confirmation
        additionally requires the consultant's `availability_status` to be anything other
        than `RESKILLING`. A proposal may legitimately have been created before the
        enrolment; the confirmation is where it is caught. Applies to assignment
        confirmation only. Failure: `ERR_CONSULTANT_IN_RESKILLING` (409)."

        Design: Corner/validations/reskilling_consultant_can_be_proposed_but_not_confirmed
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
        )
        consultant_id = staff["consultant"]["id"]
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=1.00,
            start_date="2026-09-01",
            end_date="2026-09-30",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        # Proposed while the consultant is still BENCH and still unenrolled.
        assignment = fixtures.propose_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-09-01",
            end_date="2026-10-01",
        )
        assert assignment["status"] == AssignmentStatus.PROPOSED
        assert assignment["confirmed_on"] is None

        enrolment = fixtures.enrolled_in_cohort(
            api,
            world,
            consultant_id,
            program_kwargs={
                "target_proficiency_level": 5,
                "cohort_start_on": "2026-09-01",
                "cohort_end_on": "2026-09-30",
                "seat_capacity": 2,
            },
            l1_instant=INSTANT_AUG_17,
        )
        assert enrolment["spell"]["state"] == BenchSpellState.RESKILLING
        assert (
            fixtures.read_consultant(api, consultant_id)["availability_status"]
            == AvailabilityStatus.RESKILLING
        )

        validate_error(
            api.confirm_assignment(assignment["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_CONSULTANT_IN_RESKILLING,
            409,
        )

        refused = fixtures.read_assignment(api, assignment["id"])
        assert refused["status"] == AssignmentStatus.PROPOSED
        assert refused["confirmed_on"] is None

        after = fixtures.read_demand(api, demand["id"])
        assert after["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert after["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert after["staffing_status"] == StaffingStatus.INTERNAL_STAFFING


class TestExpiredCertificationOutranksProficiency:
    @staticmethod
    def _weak_assertion_expiring_on_the_tenth(api):
        """A proficiency-2 assertion certified only to 2026-08-10, backing a PROPOSED
        row on a demand that demands level 3."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=2,
            cost_rate_usd_per_hour=120.00,
            assertion_kwargs={
                "certification_code": "AWS-SA-PRO",
                "certification_expires_on": "2026-08-10",
            },
        )
        demand = fixtures.qualified_demand(
            api,
            world,
            min_proficiency_level=3,
            required_fte=1.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        assignment = fixtures.propose_assignment(
            api,
            staff["consultant"]["id"],
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-17",
            end_date="2026-08-29",
        )
        return world, staff, demand, assignment

    def test_the_clock_alone_flips_the_assertion_to_expired(self, api):
        """PRD §3.2: "It is `ACTIVE` when there is no `certification_code` at all, or when
        `certification_expires_on` falls on or after the logical clock date; it is
        `EXPIRED` otherwise."

        Design: Corner/validations/expired_certification_outranks_insufficient_proficiency
        """
        _, staff, _, _ = self._weak_assertion_expiring_on_the_tenth(api)
        assertion_id = staff["assertion"]["id"]

        before = validate_success(
            api.get_skill_assertion(assertion_id, RESOURCE_MANAGER), 200
        )
        assert before["assertion_status"] == AssertionStatus.ACTIVE
        assert before["certification_expires_on"] == "2026-08-10"
        assert before["version"] == 1

        fixtures.set_clock(api, INSTANT_AUG_11)

        after = validate_success(
            api.get_skill_assertion(assertion_id, RESOURCE_MANAGER), 200
        )
        assert after["assertion_status"] == AssertionStatus.EXPIRED
        # Nothing was rewritten: the derivation is read against the clock.
        assert after["version"] == 1
        assert after["proficiency_level"] == 2

    def test_the_confirm_names_the_certification_not_the_proficiency(self, api):
        """PRD §2.9: "21. **Certification currency** — the skill assertion backing a
        confirmation must have `assertion_status` equal to `ACTIVE`. Applies to assignment
        confirmation only. Failure: `ERR_CERTIFICATION_EXPIRED` (409)."

        Design: Corner/validations/expired_certification_outranks_insufficient_proficiency
        """
        _, staff, demand, assignment = self._weak_assertion_expiring_on_the_tenth(api)
        fixtures.set_clock(api, INSTANT_AUG_11)

        response = api.confirm_assignment(assignment["id"], RESOURCE_MANAGER)
        # Rung 21 sits above rung 25, so the weak proficiency is never reached.
        error = validate_error(response, ApiErrorId.ERR_CERTIFICATION_EXPIRED, 409)
        assert error["error_id"] != ApiErrorId.ERR_PROFICIENCY_INSUFFICIENT

        refused = fixtures.read_assignment(api, assignment["id"])
        assert refused["status"] == AssignmentStatus.PROPOSED
        assert refused["confirmed_on"] is None
        assert fixtures.read_consultant(api, staff["consultant"]["id"])[
            "allocated_pct"
        ] == pytest.approx(0.00, abs=0.005)
        assert fixtures.read_demand(api, demand["id"])[
            "covered_internal_fte"
        ] == pytest.approx(0.00, abs=0.005)


class TestConfirmationFitnessGates:
    @staticmethod
    def _four_candidates_on_two_demands(api):
        """Three misfits and one fit, each holding a PROPOSED 100% row for
        [2026-08-17, 2026-08-29)."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        domestic = fixtures.qualified_demand(
            api,
            world,
            client_name="Acme Retail",
            min_proficiency_level=3,
            onsite_nights_per_week=3,
            required_fte=2.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        international = fixtures.qualified_demand(
            api,
            world,
            client_name="Globex Bank",
            min_proficiency_level=3,
            onsite_nights_per_week=2,
            is_international=True,
            required_fte=1.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        candidates = {}
        recipes = (
            ("low", "Ada Byron", domestic, 2, {"travel_max_nights_per_week": 3}),
            ("travel", "Grace Hopper", domestic, 4, {"travel_max_nights_per_week": 1}),
            (
                "international",
                "Alan Turing",
                international,
                4,
                {
                    "travel_max_nights_per_week": 5,
                    "travel_willing_international": False,
                },
            ),
            ("fit", "Edsger Dijkstra", domestic, 4, {"travel_max_nights_per_week": 3}),
        )
        for key, full_name, demand, proficiency, extra in recipes:
            staff = fixtures.hire(
                api,
                world,
                full_name=full_name,
                proficiency_level=proficiency,
                cost_rate_usd_per_hour=120.00,
                **extra,
            )
            assignment = fixtures.propose_assignment(
                api,
                staff["consultant"]["id"],
                demand["id"],
                allocation_pct=100.00,
                start_date="2026-08-17",
                end_date="2026-08-29",
            )
            candidates[key] = {"staff": staff, "assignment": assignment}
        return world, domestic, international, candidates

    def test_a_level_two_assertion_cannot_back_a_level_three_demand(self, api):
        """PRD §2.9: "25. **Proficiency sufficiency** — the consultant must hold an `ACTIVE`
        assertion for the demand's `required_skill_id` at a `proficiency_level` at or above
        the demand's `min_proficiency_level`. Applies to assignment confirmation only.
        Failure: `ERR_PROFICIENCY_INSUFFICIENT` (409)."

        Design: Corner/validations/proficiency_and_both_travel_arms_reject_confirm_while_a_fit_passes
        """
        _, domestic, _, candidates = self._four_candidates_on_two_demands(api)
        weak = candidates["low"]

        # No certification at all, so the assertion is ACTIVE and rung 21 passes.
        backing = validate_success(
            api.get_skill_assertion(weak["staff"]["assertion"]["id"], RESOURCE_MANAGER),
            200,
        )
        assert backing["assertion_status"] == AssertionStatus.ACTIVE
        assert backing["proficiency_level"] == 2

        validate_error(
            api.confirm_assignment(weak["assignment"]["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_PROFICIENCY_INSUFFICIENT,
            409,
        )
        assert (
            fixtures.read_assignment(api, weak["assignment"]["id"])["status"]
            == AssignmentStatus.PROPOSED
        )
        assert fixtures.read_demand(api, domestic["id"])[
            "covered_internal_fte"
        ] == pytest.approx(0.00, abs=0.005)

    def test_both_travel_arms_refuse_while_the_fitting_candidate_confirms(self, api):
        """PRD §2.9: "26. **Travel fit** — the demand's `onsite_nights_per_week` must be at
        most the consultant's `travel_max_nights_per_week`, and when the demand's
        `is_international` is true the consultant's `travel_willing_international` must also
        be true. Applies to assignment confirmation only. Failure:
        `ERR_TRAVEL_CONSTRAINT_VIOLATED` (409)."

        Design: Corner/validations/proficiency_and_both_travel_arms_reject_confirm_while_a_fit_passes
        """
        _, domestic, international, candidates = self._four_candidates_on_two_demands(api)

        # Arm one: 3 onsite nights against a ceiling of 1.
        validate_error(
            api.confirm_assignment(
                candidates["travel"]["assignment"]["id"], RESOURCE_MANAGER
            ),
            ApiErrorId.ERR_TRAVEL_CONSTRAINT_VIOLATED,
            409,
        )
        # Arm two: the nights arm is satisfied (2 <= 5) and the passport arm is not.
        validate_error(
            api.confirm_assignment(
                candidates["international"]["assignment"]["id"], RESOURCE_MANAGER
            ),
            ApiErrorId.ERR_TRAVEL_CONSTRAINT_VIOLATED,
            409,
        )

        confirmed = fixtures.confirm(api, candidates["fit"]["assignment"]["id"])
        assert confirmed["status"] == AssignmentStatus.CONFIRMED
        assert confirmed["confirmed_on"] == "2026-08-03"

        after_domestic = fixtures.read_demand(api, domestic["id"])
        assert after_domestic["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert after_domestic["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert after_domestic["staffing_status"] == StaffingStatus.PARTIALLY_COVERED

        after_international = fixtures.read_demand(api, international["id"])
        assert after_international["covered_internal_fte"] == pytest.approx(
            0.00, abs=0.005
        )
        assert after_international["staffing_status"] == StaffingStatus.INTERNAL_STAFFING
