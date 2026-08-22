"""Functional performance testing: scheduling gates, the witness calendar, outcomes."""

from test_helpers import (
    ApiErrorId,
    assert_functional_test,
    create_approved_requirement,
    create_functional_test_payload,
    create_plan,
    create_project,
    get_equipment,
    get_project,
    get_test,
    list_issues,
    record_test_result,
    run_functional_test,
    schedule_functional_test,
    set_install_status,
    setup_prefunctional_verified_equipment,
    setup_project_with_approved_plan,
    setup_ready_equipment_on_pinned_plan,
    setup_two_ready_units_with_occupied_window,
    start_test,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import CXA


class TestSchedulingGates:
    def test_new_test_is_refused_while_the_unit_is_only_installed(self, api):
        """PRD §3.4: "Scheduling a **new** test is heavily gated: the engagement's newest
        commissioning plan must be `APPROVED` or the request is refused with
        `ERR_PLAN_NOT_APPROVED`; the `requirement_id` must appear in that plan's
        `pinned_requirement_ids` or the request is refused with
        `ERR_REQUIREMENT_NOT_PINNED`; the unit must be both `PREFUNCTIONAL_VERIFIED` and
        `STARTED_UP` or the request is refused with `ERR_EQUIPMENT_NOT_READY`;
        `scheduled_end` must be strictly after `scheduled_start` or the request is refused
        with `ERR_INVALID_WINDOW`; and the witness calendar must have room."

        Design: Difficulty/cross_entity_state_dependency/functional_test_creation_gated_by_equipment_dual_state
        """
        setup = setup_ready_equipment_on_pinned_plan(
            project_overrides={"name": "Maple Cx", "building_name": "Maple Court"},
            equipment_overrides={"tag": "AHU-6"},
            started_up=False,
        )
        equipment = get_equipment(setup["equipment"]["id"])
        assert equipment["verification_status"] == "PREFUNCTIONAL_VERIFIED"
        assert equipment["install_status"] == "INSTALLED"

        response = api.create_functional_test(
            create_functional_test_payload(
                equipment["id"],
                setup["requirement"]["id"],
                "2026-09-11T09:00:00Z",
                "2026-09-11T11:00:00Z",
                script_code="FPT-AHU-03",
            ),
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_EQUIPMENT_NOT_READY.value, 409)

        _, meta = validate_paginated(
            api.list_functional_tests(CXA, params={"equipment_id": equipment["id"]})
        )
        assert meta["total_count"] == 0

    def test_new_test_is_accepted_once_the_unit_reaches_started_up(self, api):
        """PRD §2.5: "The referenced equipment unit is commissioning-ready — otherwise
        `ERR_EQUIPMENT_NOT_READY` (409). Scheduling a **new** functional test requires the
        unit to be `PREFUNCTIONAL_VERIFIED` *and* `STARTED_UP`; scheduling a re-test and
        starting a test require only `STARTED_UP`, so a unit that the very failure being
        re-tested demoted to `UNVERIFIED` can still be re-tested; executing a pre-functional
        checklist requires the unit to be `INSTALLED` or `STARTED_UP`."
        PRD §3.4: "A new test is born `SCHEDULED` with `retest_of_test_id`,
        `measured_value`, `outcome_deviation_pct`, `witness_user_id`, `started_at`,
        `completed_at` and `generated_issue_id` all null."

        Design: Difficulty/cross_entity_state_dependency/functional_test_creation_gated_by_equipment_dual_state
        """
        setup = setup_ready_equipment_on_pinned_plan(
            project_overrides={"name": "Maple Cx", "building_name": "Maple Court"},
            equipment_overrides={"tag": "AHU-6"},
            started_up=False,
        )
        set_install_status(setup["equipment"]["id"], "STARTED_UP")

        test = validate_success(
            api.create_functional_test(
                create_functional_test_payload(
                    setup["equipment"]["id"],
                    setup["requirement"]["id"],
                    "2026-09-11T09:00:00Z",
                    "2026-09-11T11:00:00Z",
                    script_code="FPT-AHU-03",
                ),
                CXA,
            ),
            201,
        )
        assert_functional_test(test)
        assert test["status"] == "SCHEDULED"
        assert test["retest_of_test_id"] is None
        assert test["measured_value"] is None
        assert test["outcome_deviation_pct"] is None
        assert test["witness_user_id"] is None
        assert test["started_at"] is None
        assert test["completed_at"] is None
        assert test["generated_issue_id"] is None

        _, meta = validate_paginated(
            api.list_functional_tests(
                CXA, params={"equipment_id": setup["equipment"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert (
            get_equipment(setup["equipment"]["id"])["verification_status"]
            == "PREFUNCTIONAL_VERIFIED"
        )

    def test_unapproved_newest_plan_blocks_scheduling(self, api):
        """PRD §2.5: "The engagement's newest commissioning plan — the one with the greatest
        `created_at` — has status `APPROVED`, otherwise `ERR_PLAN_NOT_APPROVED` (409). Three
        operations are guarded: functional test scheduling, re-test scheduling and
        certification credit submission."

        Design: Corner/errors/unapproved_plan_blocks_functional_test_creation
        """
        project = create_project(name="NoPlan Cx", building_name="NoPlan Block")
        requirement = create_approved_requirement(project["id"])
        draft_plan = create_plan(project["id"], title="Draft only")
        assert draft_plan["status"] == "DRAFT"
        unit = setup_prefunctional_verified_equipment(
            project["id"], started_up=True, tag="AHU-NP"
        )

        response = api.create_functional_test(
            create_functional_test_payload(
                unit["equipment"]["id"],
                requirement["id"],
                "2026-09-21T09:00:00Z",
                "2026-09-21T11:00:00Z",
            ),
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_PLAN_NOT_APPROVED.value, 409)

        _, meta = validate_paginated(
            api.list_functional_tests(
                CXA, params={"equipment_id": unit["equipment"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_requirement_outside_the_pinned_set_blocks_scheduling(self, api):
        """PRD §2.5: "The supplied `requirement_id` appears in the `pinned_requirement_ids`
        array of the engagement's newest approved commissioning plan — otherwise
        `ERR_REQUIREMENT_NOT_PINNED` (422). Two operations are guarded: functional test
        scheduling and deferred test scheduling."
        PRD §3.1: "From that moment on, only a requirement whose identifier appears in that
        array may be tested against."

        Design: Corner/errors/unpinned_requirement_blocks_functional_test_creation
        """
        setup = setup_ready_equipment_on_pinned_plan(
            project_overrides={"name": "Unpinned Cx", "building_name": "Unpinned Block"},
            equipment_overrides={"tag": "AHU-UP"},
        )
        unpinned = create_approved_requirement(
            setup["project"]["id"],
            metric_key="RETURN_AIRFLOW_CFM",
            target_value=8_000,
            criticality="STANDARD",
        )

        response = api.create_functional_test(
            create_functional_test_payload(
                setup["equipment"]["id"],
                unpinned["id"],
                "2026-09-22T09:00:00Z",
                "2026-09-22T11:00:00Z",
                script_code="FPT-AHU-02",
            ),
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_REQUIREMENT_NOT_PINNED.value, 422)

        plan = validate_success(api.get_cx_plan(setup["plan"]["id"], CXA), 200)
        assert plan["pinned_requirement_count"] == 1
        assert plan["pinned_requirement_ids"] == [setup["requirement"]["id"]]

        _, meta = validate_paginated(
            api.list_functional_tests(
                CXA, params={"equipment_id": setup["equipment"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_equipment_and_requirement_from_different_engagements_are_refused(self, api):
        """PRD §2.11: "Whenever a request names more than one entity — a checklist naming
        equipment, a functional test naming both equipment and a requirement, an issue
        naming equipment, a deferred test naming equipment, a requirement and an issue, an
        evidence row naming an artifact — every named entity must resolve to the same
        `project_id`. A request that reaches across engagements is rejected with
        `ERR_PROJECT_SCOPE_MISMATCH` and HTTP 409."

        Design: Corner/entities/cross_project_equipment_and_requirement_returns_scope_mismatch
        """
        base = setup_project_with_approved_plan(
            project_overrides={
                "name": "Scope A",
                "building_name": "A Block",
                "contract_value_cents": 50_000_000,
            }
        )
        other = create_project(
            name="Scope B", building_name="B Block", contract_value_cents=50_000_000
        )
        from test_helpers import register_equipment

        foreign_equipment = register_equipment(
            other["id"], tag="AHU-B1", contract_value_cents=100_000, weight_units=1
        )
        set_install_status(foreign_equipment["id"], "INSTALLED")

        response = api.create_functional_test(
            create_functional_test_payload(
                foreign_equipment["id"],
                base["requirement"]["id"],
                "2026-09-12T09:00:00Z",
                "2026-09-12T11:00:00Z",
                script_code="FPT-X",
            ),
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_PROJECT_SCOPE_MISMATCH.value, 409)

        _, meta = validate_paginated(
            api.list_functional_tests(
                CXA, params={"equipment_id": foreign_equipment["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestWitnessCalendarGeometry:
    def test_buffered_windows_that_merely_touch_still_collide(self, api):
        """PRD §2.10: "The **witness calendar** for functional performance testing uses
        **closed** intervals expanded by a mobilisation buffer of one hour at each end,
        compared at second resolution."
        PRD §2.10: "Touching endpoints therefore **do** collide: a new window whose buffered
        start falls exactly on an occupant's buffered end is a collision."
        PRD §3.4: "If the number of colliding occupants is greater than or equal to the
        engagement's `witness_capacity`, the request is refused with
        `ERR_WITNESS_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/witness_window_closed_buffered_interval_blocks_touching_window
        """
        setup = setup_two_ready_units_with_occupied_window()

        response = api.create_functional_test(
            create_functional_test_payload(
                setup["equipment_b"]["id"],
                setup["requirement"]["id"],
                "2026-09-10T13:00:00Z",
                "2026-09-10T15:00:00Z",
                script_code="FPT-AHU-02",
            ),
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_WITNESS_WINDOW_CONFLICT.value, 409)

        _, meta = validate_paginated(
            api.list_functional_tests(
                CXA, params={"equipment_id": setup["equipment_b"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert get_test(setup["occupying_test"]["id"])["status"] == "SCHEDULED"

    def test_one_second_of_separation_clears_the_buffered_occupant(self, api):
        """PRD §3.4: "Each test's window is expanded by a mobilisation buffer of one hour
        before `scheduled_start` and one hour after `scheduled_end`, and the resulting
        buffered intervals are treated as closed at both ends — two buffered windows collide
        when each one's buffered start falls at or before the other one's buffered end, so
        windows that merely touch **do** collide."
        PRD §3.4: "An engagement left at the default capacity of 1 therefore admits no
        overlap at all, whereas one configured for a capacity of 2 tolerates a single
        overlapping occupant and refuses the second."

        Design: Difficulty/resource_temporal_overlap/witness_window_closed_buffered_interval_blocks_touching_window
        """
        setup = setup_two_ready_units_with_occupied_window()

        test = validate_success(
            api.create_functional_test(
                create_functional_test_payload(
                    setup["equipment_b"]["id"],
                    setup["requirement"]["id"],
                    "2026-09-10T13:00:01Z",
                    "2026-09-10T15:00:00Z",
                    script_code="FPT-AHU-02",
                ),
                CXA,
            ),
            201,
        )
        assert test["status"] == "SCHEDULED"

        _, meta = validate_paginated(
            api.list_functional_tests(
                CXA, params={"equipment_id": setup["equipment_b"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert get_test(setup["occupying_test"]["id"])["status"] == "SCHEDULED"


class TestSchedulingCheckOrder:
    def test_window_conflict_is_reported_ahead_of_the_unpinned_requirement(self, api):
        """PRD §2.5: "The buffered witness-window occupancy check finds fewer colliding
        occupants than the engagement's `witness_capacity` — otherwise
        `ERR_WITNESS_WINDOW_CONFLICT` (409). Two operations are guarded: functional test
        scheduling and re-test scheduling."
        PRD §2.5: "The server evaluates the checks below strictly in the order listed, and
        the **first** failing check decides the response."

        Design: Difficulty/priority_pair_validation_conflict/witness_window_conflict_outranks_unpinned_requirement_on_test_create
        """
        setup = setup_two_ready_units_with_occupied_window()
        unpinned = create_approved_requirement(
            setup["project"]["id"],
            metric_key="RETURN_AIRFLOW_CFM",
            target_value=8_000,
            criticality="STANDARD",
        )
        plan = validate_success(api.get_cx_plan(setup["plan"]["id"], CXA), 200)
        assert plan["pinned_requirement_count"] == 1
        assert unpinned["id"] not in plan["pinned_requirement_ids"]

        response = api.create_functional_test(
            create_functional_test_payload(
                setup["equipment_b"]["id"],
                unpinned["id"],
                "2026-09-10T12:00:00Z",
                "2026-09-10T14:00:00Z",
                script_code="FPT-AHU-02",
            ),
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_WITNESS_WINDOW_CONFLICT.value, 409)

    def test_the_rejected_scheduling_writes_no_row_at_all(self, api):
        """PRD §2.5: "When a request violates more than one rule, exactly one error is
        returned and no side effect of any kind is written."
        PRD §2.5: "The supplied `requirement_id` appears in the `pinned_requirement_ids`
        array of the engagement's newest approved commissioning plan — otherwise
        `ERR_REQUIREMENT_NOT_PINNED` (422). Two operations are guarded: functional test
        scheduling and deferred test scheduling."

        Design: Difficulty/priority_pair_validation_conflict/witness_window_conflict_outranks_unpinned_requirement_on_test_create
        """
        setup = setup_two_ready_units_with_occupied_window()
        unpinned = create_approved_requirement(
            setup["project"]["id"],
            metric_key="RETURN_AIRFLOW_CFM",
            target_value=8_000,
            criticality="STANDARD",
        )

        response = api.create_functional_test(
            create_functional_test_payload(
                setup["equipment_b"]["id"],
                unpinned["id"],
                "2026-09-10T12:00:00Z",
                "2026-09-10T14:00:00Z",
                script_code="FPT-AHU-02",
            ),
            CXA,
        )
        assert response.status_code >= 400, (
            f"the scheduling must be refused, got {response.status_code}"
        )
        error = response.json()["data"]["error_id"]
        assert error != ApiErrorId.ERR_REQUIREMENT_NOT_PINNED.value, (
            "the temporal check outranks the pinned-requirement check"
        )

        _, meta = validate_paginated(
            api.list_functional_tests(
                CXA, params={"equipment_id": setup["equipment_b"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert get_test(setup["occupying_test"]["id"])["status"] == "SCHEDULED"


class TestWitnessingAndOutcomes:
    def test_starting_an_in_progress_test_again_is_refused(self, api):
        """PRD §3.4: "Witnessing begins when the `CxAuthority` starts the test, moving it
        `SCHEDULED` → `IN_PROGRESS` and stamping `started_at` from the logical clock."
        PRD §2.5: "The target resource is in a status from which the requested transition is
        declared — otherwise `ERR_INVALID_STATE` (409). This applies to every state-changing
        action endpoint in the system."

        Design: Corner/state_machines/starting_a_functional_test_twice_returns_invalid_state
        """
        setup = setup_ready_equipment_on_pinned_plan(
            project_overrides={"name": "Twice Cx", "building_name": "Twice Block"},
            equipment_overrides={"tag": "AHU-TW"},
        )
        test = schedule_functional_test(
            setup["equipment"]["id"],
            setup["requirement"]["id"],
            "2026-09-13T09:00:00Z",
            "2026-09-13T11:00:00Z",
        )
        started = start_test(test["id"])
        assert started["status"] == "IN_PROGRESS"
        first_started_at = started["started_at"]

        response = api.start_functional_test(test["id"], CXA)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

        after = get_test(test["id"])
        assert after["status"] == "IN_PROGRESS"
        assert after["started_at"] == first_started_at, "started_at is not re-stamped"

    def test_passing_deviation_promotes_the_unit_and_opens_no_deficiency(self, api):
        """PRD §3.4: "That number is written to `outcome_deviation_pct`, and the outcome
        follows from it with both comparisons inclusive: a deviation at or below
        `tolerance_pct` is `PASSED`; a deviation above `tolerance_pct` but at or below twice
        `tolerance_pct` is `PASSED_WITH_EXCEPTIONS`; a deviation above twice `tolerance_pct`
        is `FAILED`."
        PRD §3.4: "The unit is promoted `PREFUNCTIONAL_VERIFIED` → `FUNCTIONAL_ACCEPTED` and
        the engagement's provisional acceptance completion score is recomputed. No
        deficiency is opened and no money is withheld."
        PRD §3.4: "All three branches leave `IN_PROGRESS`, write `measured_value`,
        `outcome_deviation_pct`, `witness_user_id` from the acting `X-User-ID` and
        `completed_at` from the logical clock, and increment the engagement's `version` by
        one."

        Design: Corner/state_machines/passed_functional_test_promotes_equipment_to_functional_accepted
        """
        setup = setup_ready_equipment_on_pinned_plan(
            project_overrides={"name": "Pass Cx", "building_name": "Pass Block"},
            equipment_overrides={"tag": "AHU-PS"},
        )
        test = schedule_functional_test(
            setup["equipment"]["id"],
            setup["requirement"]["id"],
            "2026-09-15T09:00:00Z",
            "2026-09-15T11:00:00Z",
        )
        start_test(test["id"])
        completed = record_test_result(test["id"], 10_500, user_id="u-cxa-2")

        assert completed["outcome_deviation_pct"] == 5.00
        assert completed["status"] == "PASSED"
        assert completed["witness_user_id"] == "u-cxa-2"
        assert completed["generated_issue_id"] is None

        assert (
            get_equipment(setup["equipment"]["id"])["verification_status"]
            == "FUNCTIONAL_ACCEPTED"
        )
        _, meta = list_issues(project_id=setup["project"]["id"])
        assert meta["total_count"] == 0, "a pass opens no deficiency"

        project = get_project(setup["project"]["id"])
        assert project["acceptance_completion_score"] == 80.00
        assert project["readiness_posture"] == "OPEN"

    def test_deviation_at_exactly_twice_the_tolerance_passes_with_exceptions(self, api):
        """PRD §3.4: "A deviation of exactly the tolerance is therefore a pass, and a
        deviation of exactly twice the tolerance is a pass with exceptions."
        PRD §3.4: "Because `S3` does not block acceptance, the unit's `blocking_issue_count`
        is unchanged and the unit is **not** demoted; instead it moves
        `PREFUNCTIONAL_VERIFIED` → `CONDITIONALLY_ACCEPTED`."
        PRD §2.7: "The **base hold rate** comes from the issue's own severity: 0.05 for
        `S1`, 0.02 for `S2`, 0.005 for `S3` and 0.0 for `S4`."

        Design: Corner/calculations/deviation_at_exactly_double_tolerance_is_passed_with_exceptions
        """
        setup = setup_ready_equipment_on_pinned_plan(
            project_overrides={"name": "Edge Cx", "building_name": "Edge Block"},
            requirement_overrides={"criticality": "STANDARD"},
            equipment_overrides={"tag": "AHU-ED"},
        )
        completed = run_functional_test(
            setup["equipment"]["id"],
            setup["requirement"]["id"],
            11_000,
            "2026-09-16T09:00:00Z",
            "2026-09-16T11:00:00Z",
        )

        assert completed["outcome_deviation_pct"] == 10.00
        assert completed["status"] == "PASSED_WITH_EXCEPTIONS"

        equipment = get_equipment(setup["equipment"]["id"])
        assert equipment["verification_status"] == "CONDITIONALLY_ACCEPTED"
        assert equipment["blocking_issue_count"] == 0

        rows, meta = list_issues(equipment_id=setup["equipment"]["id"])
        assert meta["total_count"] == 1
        assert rows[0]["severity"] == "S3"
        assert rows[0]["blocks_acceptance"] is False
        assert rows[0]["retainage_hold_cents"] == 5_000

        project = get_project(setup["project"]["id"])
        assert project["retainage_withheld_cents"] == 5_000
        assert project["issue_severity_index"] == 8.00
        assert project["readiness_posture"] == "OPEN"
        assert project["acceptance_completion_score"] == 80.00

    def test_zero_target_requirement_pins_the_deviation_to_one_hundred(self, api):
        """PRD §3.4: "The percentage deviation is computed as follows: when the requirement's
        `target_value` is 0, the deviation is 0.00 if the measured value is also 0 and
        100.00 otherwise; when the target is not 0, the deviation is the absolute difference
        between the measured value and the target, divided by the target, multiplied by 100,
        and rounded half up to two decimal places."
        PRD §3.4: "**Second**, when that issue's severity makes `blocks_acceptance` true —
        that is, when it came out `S1` or `S2` — the unit's `blocking_issue_count` increments
        and its verification dimension is demoted to `UNVERIFIED`."

        Design: Corner/calculations/zero_target_requirement_pins_deviation_to_one_hundred
        """
        setup = setup_ready_equipment_on_pinned_plan(
            project_overrides={"name": "Zero Cx", "building_name": "Zero Block"},
            requirement_overrides={
                "metric_key": "DUCT_LEAKAGE_CFM",
                "target_value": 0,
                "tolerance_pct": 5,
            },
            equipment_overrides={"tag": "AHU-ZR", "criticality": "CRITICAL"},
        )
        completed = run_functional_test(
            setup["equipment"]["id"],
            setup["requirement"]["id"],
            5,
            "2026-09-17T09:00:00Z",
            "2026-09-17T11:00:00Z",
            script_code="FPT-LEAK-01",
        )

        assert completed["outcome_deviation_pct"] == 100.00
        assert completed["status"] == "FAILED"

        rows, meta = list_issues(equipment_id=setup["equipment"]["id"])
        assert meta["total_count"] == 1
        assert rows[0]["severity"] == "S2"
        assert rows[0]["retainage_hold_cents"] == 24_000

        equipment = get_equipment(setup["equipment"]["id"])
        assert equipment["verification_status"] == "UNVERIFIED"
        assert equipment["blocking_issue_count"] == 1

        project = get_project(setup["project"]["id"])
        assert project["issue_severity_index"] == 24.00
        assert project["readiness_posture"] == "RESTRICTED"


class TestEquipmentRemovalCancelsTests:
    def test_removing_the_unit_cancels_its_scheduled_test_and_empties_the_denominator(
        self, api
    ):
        """PRD §3.3: "Removal is reachable from all three of `NOT_INSTALLED`, `INSTALLED`
        and `STARTED_UP`, and moving to `REMOVED` does two things regardless of where it
        started from: every functional test of that unit sitting in `SCHEDULED` or
        `IN_PROGRESS` is moved to `CANCELLED`, releasing its witness window; and the unit
        drops out of the completion-score denominator entirely, so the engagement's
        provisional acceptance completion score is recomputed over whatever units remain."
        PRD §3.9: "The denominator, `total_weight_units`, is the sum of `weight_units` over
        exactly those units; when that sum is 0 — because no equipment is registered, or
        every unit has been removed — the score is 0.00 and the walk stops there."

        Design: Corner/state_machines/removing_equipment_cancels_its_scheduled_functional_tests
        """
        setup = setup_ready_equipment_on_pinned_plan(
            project_overrides={"name": "Remove Cx", "building_name": "Remove Block"},
            equipment_overrides={"tag": "AHU-RM"},
        )
        test = schedule_functional_test(
            setup["equipment"]["id"],
            setup["requirement"]["id"],
            "2026-09-14T09:00:00Z",
            "2026-09-14T11:00:00Z",
        )

        removed = set_install_status(setup["equipment"]["id"], "REMOVED")
        assert removed["install_status"] == "REMOVED"
        assert get_test(test["id"])["status"] == "CANCELLED"

        project = get_project(setup["project"]["id"])
        assert project["acceptance_completion_score"] == 0.00
        assert project["verified_prefunctional_units"] == 10, (
            "the checklist is still VERIFIED, so the conserved weight does not move"
        )
