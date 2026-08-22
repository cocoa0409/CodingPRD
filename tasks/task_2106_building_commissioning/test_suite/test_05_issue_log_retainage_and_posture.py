"""The issue log: frozen retainage holds, the severity index and the posture gate."""

from test_helpers import (
    ApiErrorId,
    assert_issue,
    create_issue,
    create_issue_payload,
    create_project,
    get_deferred_test,
    get_equipment,
    get_issue,
    get_project,
    get_readiness,
    list_issues,
    propose_resolution,
    register_equipment,
    set_logical_clock,
    setup_frozen_project_with_blocked_seasonal_test,
    setup_failed_life_safety_test_with_passing_peer,
    setup_project_at_severity_index_32,
    setup_three_holds_on_life_safety_unit,
    start_test,
    record_test_result,
    validate_error,
    validate_success,
    verify_closure,
    void_issue,
)
from test_helpers import CXA


class TestFrozenRetainageHolds:
    def test_each_hold_is_rounded_to_whole_cents_on_its_own(self, api):
        """PRD §2.7: "Multiply base by rate by factor and round half up to a whole number of
        cents — that is the issue's frozen hold."
        PRD §2.7: "The **criticality factor** is 1.5 for `LIFE_SAFETY` equipment, 1.2 for
        `CRITICAL` equipment and 1.0 for `STANDARD` equipment; an issue with no equipment
        always uses the `STANDARD` factor of 1.0."
        PRD §2.7: "The **base hold rate** comes from the issue's own severity: 0.05 for
        `S1`, 0.02 for `S2`, 0.005 for `S3` and 0.0 for `S4`."

        Design: Difficulty/combinatorial_formula/retainage_rounds_per_issue_before_summing
        """
        setup = setup_three_holds_on_life_safety_unit()

        assert setup["issue_s3"]["retainage_hold_cents"] == 7_500, (
            "1000005 * 0.005 * 1.5 = 7500.0375 rounds to 7500"
        )
        assert setup["issue_s2"]["retainage_hold_cents"] == 30_000, (
            "1000005 * 0.02 * 1.5 = 30000.15 rounds to 30000"
        )
        assert setup["issue_s1"]["retainage_hold_cents"] == 75_000, (
            "1000005 * 0.05 * 1.5 = 75000.375 rounds to 75000"
        )
        for issue in (setup["issue_s3"], setup["issue_s2"], setup["issue_s1"]):
            assert_issue(issue)

    def test_the_roll_up_sums_already_rounded_holds(self, api):
        """PRD §2.7: "The order of operations in the roll-up is pinned: each issue is
        rounded to whole cents **first**, and the already-rounded per-issue holds are
        **then** summed."
        PRD §2.7: "The cap is the engagement's `contract_value_cents` multiplied by 0.10
        with any fractional cent discarded — that is, the largest whole number of cents not
        exceeding ten percent of the contract value."

        Design: Difficulty/combinatorial_formula/retainage_rounds_per_issue_before_summing
        """
        setup = setup_three_holds_on_life_safety_unit()

        project = get_project(setup["project"]["id"])
        assert project["retainage_withheld_cents"] == 112_500, (
            "7500 + 30000 + 75000; summing unrounded products would give 112501"
        )
        assert project["retainage_withheld_cents"] != 112_501

        readiness = get_readiness(setup["project"]["id"])
        assert readiness["retainage_cap_cents"] == 10_000_000


class TestRetainageCap:
    def test_the_issue_that_would_cross_the_cap_is_not_written(self, api):
        """PRD §2.7: "Logging a new deficiency whose hold would push
        `retainage_withheld_cents` above that cap is refused with
        `ERR_RETAINAGE_CAP_EXCEEDED` and **no issue row is written at all**; the deficiency
        simply does not exist, and none of the cascades a new issue would have triggered
        run."

        Design: Corner/validations/retainage_cap_blocks_the_issue_that_would_cross_ten_percent
        """
        project = create_project(
            name="Cap Cx", building_name="Cap Block", contract_value_cents=1_000_000
        )
        equipment = register_equipment(
            project["id"],
            tag="FA-CP",
            system_type="FIRE_ALARM",
            criticality="LIFE_SAFETY",
            contract_value_cents=1_000_000,
        )
        first = create_issue(
            project["id"],
            "S1",
            description="Detector spacing violation",
            equipment_id=equipment["id"],
        )
        assert first["retainage_hold_cents"] == 75_000

        response = api.create_issue(
            create_issue_payload(
                project["id"],
                "S2",
                description="Battery calculation missing",
                equipment_id=equipment["id"],
            ),
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_RETAINAGE_CAP_EXCEEDED.value, 422)

        assert get_project(project["id"])["retainage_withheld_cents"] == 75_000
        _, meta = list_issues(project_id=project["id"])
        assert meta["total_count"] == 1
        assert get_readiness(project["id"])["retainage_cap_cents"] == 100_000


class TestBlocksAcceptanceDerivation:
    def test_blocks_acceptance_follows_only_from_severity(self, api):
        """PRD §3.5: "`blocks_acceptance` is derived on the spot and is true exactly when
        the `severity` is `S1` or `S2`; `retainage_hold_cents` is computed once and frozen;
        `reopen_count` starts at 0; and `closure_retest_id`, `proposed_by_user_id` and
        `proposed_resolution` are all null."
        PRD §2.6: "Multiply by 2.0 when the issue's `blocks_acceptance` flag is true, and by
        1.0 when it is false."

        Design: Corner/entities/issue_blocks_acceptance_is_computed_from_severity
        """
        project = create_project(name="Blocks Cx", building_name="Blocks Block")
        equipment = register_equipment(
            project["id"], tag="AHU-B", criticality="CRITICAL", weight_units=1
        )

        minor = create_issue(
            project["id"],
            "S3",
            description="Minor label error",
            equipment_id=equipment["id"],
        )
        assert minor["blocks_acceptance"] is False

        blocking = create_issue(
            project["id"],
            "S2",
            description="Control sequence wrong",
            equipment_id=equipment["id"],
        )
        assert blocking["blocks_acceptance"] is True

        project_now = get_project(project["id"])
        assert project_now["issue_severity_index"] == 32.00, (
            "8.0 * 1.00 * 1.0 plus 12.0 * 1.00 * 2.0"
        )
        assert project_now["open_blocking_issue_count"] == 1
        assert get_equipment(equipment["id"])["blocking_issue_count"] == 1


class TestSeverityIndexBoundary:
    def test_index_below_forty_leaves_the_engagement_restricted(self, api):
        """PRD §2.6: "An index of 40.00 or more yields `FROZEN`. An index below 40.00 but at
        or above 16.00 yields `RESTRICTED`. An index below 16.00 yields `OPEN`."
        PRD §2.6: "The severity weights are 25.0 for `S1`, 12.0 for `S2`, 8.0 for `S3` and
        2.0 for `S4`."

        Design: Difficulty/boundary_precision_check/severity_index_exactly_forty_freezes_project
        """
        setup = setup_project_at_severity_index_32()

        assert setup["after_s2"]["issue_severity_index"] == 24.00
        assert setup["after_s2"]["readiness_posture"] == "RESTRICTED"
        assert setup["after_s3"]["issue_severity_index"] == 32.00
        assert setup["after_s3"]["readiness_posture"] == "RESTRICTED"

    def test_index_of_exactly_forty_freezes_the_engagement(self, api):
        """PRD §2.6: "The lower bounds are inclusive: exactly 40.00 is `FROZEN`, exactly
        16.00 is `RESTRICTED`, and 15.99 is `OPEN`."
        PRD §2.6: "The issue's contribution is its severity weight multiplied by its aging
        multiplier multiplied by its blocking multiplier, **rounded half up to two decimal
        places at that point**."

        Design: Difficulty/boundary_precision_check/severity_index_exactly_forty_freezes_project
        """
        setup = setup_project_at_severity_index_32()
        create_issue(
            setup["project"]["id"],
            "S3",
            description="Occupancy sensor time-out not set",
            equipment_id=setup["equipment"]["id"],
        )

        project = get_project(setup["project"]["id"])
        assert project["issue_severity_index"] == 40.00
        assert project["readiness_posture"] == "FROZEN", (
            "the comparison is at or above 40.00, not strictly greater"
        )
        assert project["retainage_withheld_cents"] == 36_000
        assert project["open_blocking_issue_count"] == 1


class TestSeverityIndexInputSet:
    def test_closed_and_void_rows_leave_the_index_sum(self, api):
        """PRD §2.6: "The input set is every issue belonging to the engagement whose
        `status` is `OPEN` or `IN_REVIEW`. Issues in `DEFERRED`, `VERIFIED_CLOSED` or `VOID`
        contribute nothing at all."
        PRD §3.5: "This is the compensating action for issue creation: the row leaves every
        input set, so `retainage_withheld_cents` drops by exactly the frozen
        `retainage_hold_cents` and the severity index is recomputed in all three branches."

        Design: Corner/calculations/severity_index_excludes_closed_and_void_issues
        """
        project = create_project(name="Filter Cx", building_name="Filter Block")
        equipment = register_equipment(project["id"], tag="AHU-FL")
        issues = [
            create_issue(
                project["id"],
                "S3",
                description=f"Finding {n}",
                equipment_id=equipment["id"],
            )
            for n in (1, 2, 3)
        ]

        opened = get_project(project["id"])
        assert opened["issue_severity_index"] == 24.00
        assert opened["retainage_withheld_cents"] == 15_000

        propose_resolution(issues[0]["id"], "Report issued")
        verify_closure(issues[0]["id"], "Report reviewed")
        assert get_project(project["id"])["issue_severity_index"] == 16.00

        void_issue(issues[1]["id"], "Duplicate finding")

        project_now = get_project(project["id"])
        assert project_now["issue_severity_index"] == 8.00
        assert project_now["retainage_withheld_cents"] == 5_000
        assert project_now["readiness_posture"] == "OPEN"
        assert get_issue(issues[0]["id"])["status"] == "VERIFIED_CLOSED"
        assert get_issue(issues[1]["id"])["status"] == "VOID"
        assert get_issue(issues[2]["id"])["status"] == "OPEN"


class TestIssueAging:
    def test_aging_multiplier_steps_every_fortnight_and_then_caps(self, api):
        """PRD §2.6: "Start at 1.00 and add 0.25 for each complete fortnight, then cap the
        result at 2.00. A deficiency opened today multiplies by 1.00; one open for exactly
        fourteen days multiplies by 1.25; one open for four or more complete fortnights
        multiplies by 2.00 and no more."
        PRD §2.4: "It keeps a single logical clock that reads exactly `2026-08-01T00:00:00Z`
        until an administrator moves it, and that never falls back to real time thereafter."
        PRD §2.4: "Because deficiency aging is clock-dependent, moving the clock recomputes
        the severity index and re-derives the readiness posture for **every** engagement in
        the system, not only for one."

        Design: Corner/calculations/issue_aging_multiplier_steps_then_caps_with_the_logical_clock
        """
        project = create_project(name="Aging Cx", building_name="Aging Block")
        equipment = register_equipment(project["id"], tag="AHU-AG")
        issue = create_issue(
            project["id"],
            "S3",
            description="Balancing report outstanding",
            equipment_id=equipment["id"],
        )
        assert issue["opened_at"] == "2026-08-01T00:00:00.000Z"

        day_zero = get_project(project["id"])
        assert day_zero["issue_severity_index"] == 8.00
        assert day_zero["readiness_posture"] == "OPEN"

        set_logical_clock("2026-08-29T00:00:00Z")
        day_28 = get_project(project["id"])
        assert day_28["issue_severity_index"] == 12.00, (
            "two complete fortnights give a multiplier of 1.50"
        )
        assert day_28["readiness_posture"] == "OPEN"

        set_logical_clock("2027-08-01T00:00:00Z")
        after_a_year = get_project(project["id"])
        assert after_a_year["issue_severity_index"] == 16.00, (
            "the multiplier is capped at 2.00 however old the deficiency gets"
        )
        assert after_a_year["readiness_posture"] == "RESTRICTED"
        assert after_a_year["retainage_withheld_cents"] == 5_000, (
            "the hold is frozen at creation and is never re-aged"
        )


class TestCompensatingVoid:
    def test_voiding_one_issue_returns_exactly_its_own_hold(self, api):
        """PRD §2.7: "The invariant the system guarantees is exact reversal: closing,
        voiding or seasonally discharging a deficiency drops `retainage_withheld_cents` by
        exactly that issue's frozen `retainage_hold_cents`, and re-opening it grows the
        figure back by exactly the same amount."

        Design: Difficulty/compensating_invariant/void_issue_restores_project_retainage_exactly
        """
        setup = setup_three_holds_on_life_safety_unit()
        project_id = setup["project"]["id"]
        assert get_project(project_id)["retainage_withheld_cents"] == 112_500

        void_issue(setup["issue_s2"]["id"], "Battery calc was in a superseded package")

        assert get_project(project_id)["retainage_withheld_cents"] == 82_500, (
            "exactly 112500 minus the voided issue's frozen hold of 30000"
        )

    def test_voiding_every_issue_returns_the_engagement_to_zero(self, api):
        """PRD §2.7: "Each issue freezes a `retainage_hold_cents` at the moment it is
        created — computed once, never recomputed, even if the equipment's contract value or
        criticality is later understood differently."
        PRD §2.7: "The engagement's `retainage_withheld_cents` is the sum of
        `retainage_hold_cents` over the issues of that engagement whose `status` is `OPEN`,
        `IN_REVIEW` or `DEFERRED`."

        Design: Difficulty/compensating_invariant/void_issue_restores_project_retainage_exactly
        """
        setup = setup_three_holds_on_life_safety_unit()
        project_id = setup["project"]["id"]

        void_issue(setup["issue_s2"]["id"], "Battery calc was in a superseded package")
        void_issue(setup["issue_s3"]["id"], "Duplicate of drawing note")
        void_issue(setup["issue_s1"]["id"], "Raised against the wrong building")

        project = get_project(project_id)
        assert project["retainage_withheld_cents"] == 0
        assert project["issue_severity_index"] == 0.00
        assert project["readiness_posture"] == "OPEN"

        for key in ("issue_s1", "issue_s2", "issue_s3"):
            assert get_issue(setup[key]["id"])["status"] == "VOID"
        assert get_issue(setup["issue_s1"]["id"])["retainage_hold_cents"] == 75_000, (
            "the frozen per-issue hold is never rewritten by the void"
        )


class TestReopenAndDefer:
    def test_reopening_a_closed_issue_re_applies_every_effect(self, api):
        """PRD §3.5: "Re-opening from `VERIFIED_CLOSED` clears the same three fields and
        puts the row back into both input sets, so `retainage_withheld_cents` grows again by
        exactly the frozen `retainage_hold_cents`, and when the row blocks acceptance the
        unit's `blocking_issue_count` increments and the unit is demoted to `UNVERIFIED`."
        PRD §3.5: "All three branches set `status` to `OPEN` and increment `reopen_count` by
        one."

        Design: Corner/state_machines/reopening_a_closed_issue_restores_hold_and_demotes_equipment_again
        """
        from test_helpers import setup_prefunctional_verified_equipment

        project = create_project(name="Reopen Cx", building_name="Reopen Block")
        unit = setup_prefunctional_verified_equipment(
            project["id"], started_up=False, tag="AHU-RO", criticality="CRITICAL"
        )
        issue = create_issue(
            project["id"],
            "S2",
            description="Economizer sequence wrong",
            equipment_id=unit["equipment"]["id"],
        )
        assert issue["retainage_hold_cents"] == 24_000

        propose_resolution(issue["id"], "Sequence corrected in BAS")
        verify_closure(issue["id"], "Sequence witnessed")
        closed_project = get_project(project["id"])
        assert closed_project["retainage_withheld_cents"] == 0
        assert closed_project["issue_severity_index"] == 0.00

        reopened = validate_success(
            api.reopen_issue(
                issue["id"],
                {"reason": "Sequence regressed at the next site visit"},
                CXA,
            ),
            200,
        )
        assert reopened["status"] == "OPEN"
        assert reopened["reopen_count"] == 1
        assert reopened["closure_retest_id"] is None

        project_now = get_project(project["id"])
        assert project_now["retainage_withheld_cents"] == 24_000
        assert project_now["issue_severity_index"] == 24.00
        assert project_now["readiness_posture"] == "RESTRICTED"
        assert project_now["verified_prefunctional_units"] == 10, (
            "the checklist never left VERIFIED"
        )

        equipment = get_equipment(unit["equipment"]["id"])
        assert equipment["verification_status"] == "UNVERIFIED"
        assert equipment["blocking_issue_count"] == 1

    def test_deferral_relieves_the_index_but_keeps_the_money(self, api):
        """PRD §3.5: "The row leaves the severity-index input set, so the posture may
        improve, but it **stays** in the retainage input set, so `retainage_withheld_cents`
        does not move."
        PRD §2.7: "Note that `DEFERRED` issues keep their hold even though they have left
        the severity index: deferring a deficiency to a seasonal test relieves posture
        pressure but does not release the owner's money."

        Design: Corner/state_machines/deferring_an_issue_keeps_retainage_but_clears_severity_contribution
        """
        from test_helpers import setup_deferred_issue_with_seasonal_test

        setup = setup_deferred_issue_with_seasonal_test()
        project_id = setup["project"]["id"]

        assert setup["issue"]["status"] == "DEFERRED"
        assert get_issue(setup["issue"]["id"])["retainage_hold_cents"] == 20_000

        project = get_project(project_id)
        assert project["issue_severity_index"] == 0.00
        assert project["readiness_posture"] == "OPEN"
        assert project["retainage_withheld_cents"] == 20_000
        assert project["open_blocking_issue_count"] == 0
        assert get_equipment(setup["equipment"]["id"])["blocking_issue_count"] == 0
        assert get_deferred_test(setup["deferred_test"]["id"])["status"] == "PLANNED"


class TestClosureCascade:
    def test_closure_releases_the_hold_and_re_promotes_the_unit(self, api):
        """PRD §3.5: "First, the row is written closed with its `closure_retest_id`, and
        because it has left both the severity-index input set and the retainage input set,
        the engagement's `retainage_withheld_cents` drops by exactly this issue's frozen
        `retainage_hold_cents` and the severity index is recomputed."
        PRD §3.5: "Second, because the issue has left the `OPEN`/`IN_REVIEW` pair, a
        blocking issue's departure decrements the unit's `blocking_issue_count`, and when
        that count reaches 0 while the unit's checklist is still `VERIFIED`, the unit is
        promoted `UNVERIFIED` → `PREFUNCTIONAL_VERIFIED` and every `EQUIPMENT_VERIFICATION`
        evidence row pointing at it flips `is_stale` back to false."

        Design: Difficulty/transitive_cascade/verified_closure_cascades_to_posture_and_unblocks_seasonal_test
        """
        setup = setup_frozen_project_with_blocked_seasonal_test()
        project_id = setup["project"]["id"]

        assert setup["issue"]["retainage_hold_cents"] == 60_000, (
            "1000000 * 0.05 * 1.2 for an S1 on CRITICAL equipment"
        )
        assert setup["frozen_project"]["issue_severity_index"] == 50.00
        assert setup["frozen_project"]["readiness_posture"] == "FROZEN"

        closed = verify_closure(setup["issue"]["id"], "Relief path witnessed in place")
        assert closed["status"] == "VERIFIED_CLOSED"

        project = get_project(project_id)
        assert project["retainage_withheld_cents"] == 0
        assert project["issue_severity_index"] == 0.00

        equipment = get_equipment(setup["equipment"]["id"])
        assert equipment["blocking_issue_count"] == 0
        assert equipment["verification_status"] == "PREFUNCTIONAL_VERIFIED"

    def test_closure_thaws_the_posture_and_returns_the_seasonal_test_to_planned(self, api):
        """PRD §3.5: "Third, because a unit was promoted and the index fell, the provisional
        acceptance completion score is recomputed and the posture re-derived; if that takes
        the engagement out of `FROZEN`, every `BLOCKED` deferred test of the engagement
        returns to `PLANNED`."
        PRD §3.9: "In the **`PROVISIONAL`** variant, the functional sub-score is 1.0 when
        the latest completed test is `PASSED` or `PASSED_WITH_EXCEPTIONS`; otherwise it is
        0.5 when the unit has at least one deferred test in `PLANNED` or `BLOCKED`;
        otherwise it is 0.0."

        Design: Difficulty/transitive_cascade/verified_closure_cascades_to_posture_and_unblocks_seasonal_test
        """
        setup = setup_frozen_project_with_blocked_seasonal_test()
        project_id = setup["project"]["id"]
        assert setup["deferred_test"]["status"] == "BLOCKED", (
            "entering FROZEN moves every PLANNED deferred test to BLOCKED"
        )

        verify_closure(setup["issue"]["id"], "Relief path witnessed in place")

        project = get_project(project_id)
        assert project["readiness_posture"] == "OPEN"
        assert project["acceptance_completion_score"] == 55.00
        assert project["verified_prefunctional_units"] == 10, (
            "the checklist never left VERIFIED, so this quantity never moved"
        )
        assert get_deferred_test(setup["deferred_test"]["id"])["status"] == "PLANNED"


class TestRetestEvidenceForFunctionalClosures:
    def test_life_safety_functional_closure_needs_a_matching_passing_retest(self, api):
        """PRD §3.5: "Closing an issue whose `origin` is `FUNCTIONAL` and whose `severity`
        is `S1` or `S2` requires a `closure_retest_id`, and the functional test it names
        must have `status` `PASSED`; without it, or with a test in any other status, the
        closure is refused with `ERR_RETEST_EVIDENCE_REQUIRED`."
        PRD §3.5: "That re-test must also belong to the same unit: if its `equipment_id`
        differs from the issue's `equipment_id`, the closure is refused with
        `ERR_RETEST_SCOPE_MISMATCH`."
        PRD §3.4: "The `CxAuthority` supplies only a fresh `scheduled_start` and
        `scheduled_end`; the server mints a **new** functional test row in `SCHEDULED` whose
        `retest_of_test_id` points at the test being re-tested and whose `equipment_id`,
        `requirement_id` and `script_code` are copied from it."

        Design: Corner/errors/life_safety_functional_issue_closure_requires_matching_passing_retest
        """
        setup = setup_failed_life_safety_test_with_passing_peer()
        issue = setup["issue"]
        assert issue["severity"] == "S1"

        no_evidence = api.verify_closure(
            issue["id"], {"closure_note": "Trust me"}, CXA
        )
        validate_error(
            no_evidence, ApiErrorId.ERR_RETEST_EVIDENCE_REQUIRED.value, 422
        )

        wrong_unit = api.verify_closure(
            issue["id"],
            {
                "closure_note": "Using the AHU test",
                "closure_retest_id": setup["passed_peer_test"]["id"],
            },
            CXA,
        )
        validate_error(wrong_unit, ApiErrorId.ERR_RETEST_SCOPE_MISMATCH.value, 422)

        retest = validate_success(
            api.schedule_retest(
                setup["failed_test"]["id"],
                {
                    "scheduled_start": "2026-09-20T09:00:00Z",
                    "scheduled_end": "2026-09-20T11:00:00Z",
                },
                CXA,
            ),
            201,
        )
        assert retest["retest_of_test_id"] == setup["failed_test"]["id"]
        start_test(retest["id"])
        passed_retest = record_test_result(retest["id"], 10_000)
        assert passed_retest["status"] == "PASSED"

        closed = verify_closure(
            issue["id"],
            "Retest witnessed and passed",
            closure_retest_id=retest["id"],
        )
        assert closed["status"] == "VERIFIED_CLOSED"
        assert closed["closure_retest_id"] == retest["id"]

        project = get_project(setup["project"]["id"])
        assert project["retainage_withheld_cents"] == 0
        assert project["issue_severity_index"] == 0.00
        assert project["readiness_posture"] == "OPEN"
        assert (
            get_equipment(setup["equipment_a"]["id"])["verification_status"]
            == "PREFUNCTIONAL_VERIFIED"
        )
