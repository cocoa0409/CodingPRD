"""Contracting teaching staff: signing, double-booking, activation and settlement."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_paid_registration,
    make_instructor_headers,
    read_contract,
    read_instructor,
    read_registration,
    reset_clock,
    set_clock,
    setup_completed_offering_for_settlement,
    setup_draft_offering,
    setup_dual_pay_basis_scene,
    setup_instructor_window_scene,
    setup_open_offering,
    validate_error,
    validate_success,
)


class TestPayBasisVariants:
    """The two pay bases settle materially different amounts from identical terms."""

    def test_census_locked_basis_pays_on_the_frozen_headcount(self, api):
        """PRD 3.8: "In both variants, a headcount is capped by taking the smaller of
        that headcount and `enrollment_cap_for_pay`; the capped figure is multiplied by
        `per_enrollment_cents` to give the variable component; the variable component is
        added to `base_stipend_cents` to give a raw total; and the raw total is
        multiplied by the instructor's credential multiplier — 1.00 for `ADJUNCT`, 1.15
        for `SENIOR`, 1.30 for `MASTER` — and rounded half up, once, to whole cents."
        PRD 3.8: "Under the default `CENSUS_LOCKED` basis, the headcount is the
        contract's `census_headcount`: the section's `paid_enrollment_count` frozen at
        the instant the census decision locked the section, unaffected by everything
        that happened afterwards."

        Design: Difficulty/dual_variant_calc/instructor_pay_census_locked_vs_final_completion_diverge
        """
        reset_clock()
        scene = setup_dual_pay_basis_scene()
        data = validate_success(
            api.settle_instructor_contract(scene["census_contract_id"], ADMIN)
        )
        assert data["census_headcount"] == 3
        assert data["settled_pay_cents"] == 330090, (
            f"(250000 + 3 * 12345) * 1.15 rounds to 330090, got "
            f"{data['settled_pay_cents']}"
        )
        assert data["status"] == "SETTLED"

    def test_final_completion_basis_pays_on_the_completed_headcount(self, api):
        """PRD 3.8: "Under the `FINAL_COMPLETION` basis, the headcount is the
        contract's `final_headcount`: the count of completed registrations measured at
        settle time. For any section where an enrolled learner withdrew, no-showed, or
        failed the attendance gate, the final-completion headcount is strictly smaller
        than the census headcount, so the two bases settle materially different amounts
        from otherwise identical inputs."
        PRD 3.8: "Settlement first records `final_headcount` as the number of
        registrations on the section whose `enrollment_status` is `COMPLETED`, evaluated
        at this instant."

        Design: Difficulty/dual_variant_calc/instructor_pay_census_locked_vs_final_completion_diverge
        """
        reset_clock()
        scene = setup_dual_pay_basis_scene()
        census_pay = validate_success(
            api.settle_instructor_contract(scene["census_contract_id"], ADMIN)
        )["settled_pay_cents"]
        data = validate_success(
            api.settle_instructor_contract(scene["final_contract_id"], ADMIN)
        )
        assert data["final_headcount"] == 2
        assert data["settled_pay_cents"] == 315894, (
            f"(250000 + 2 * 12345) * 1.15 rounds to 315894, got "
            f"{data['settled_pay_cents']}"
        )
        assert data["settled_pay_cents"] != census_pay
        assert data["status"] == "SETTLED"
        assert read_registration(scene["seats"][2]["registration_id"])[
            "enrollment_status"
        ] == "NO_SHOW"


class TestActivationDependsOnSectionState:
    """A signed contract activates only once its section has cleared census."""

    def test_activate_before_census_returns_invalid_state(self, api):
        """PRD 3.2: "Activation requires the contract to be `SIGNED` and requires the
        section it staffs to be in `status` `CENSUS_LOCKED`; a cross-entity failure on
        that second condition is reported as `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/contract_activate_depends_on_offering_reaching_census_locked
        """
        reset_clock()
        scene = setup_open_offering()
        add_paid_registration(scene["offering_id"], learner_index=0)
        set_clock("2026-09-01T00:00:00Z")

        validate_error(
            api.activate_instructor_contract(scene["contract_id"], ADMIN),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )
        assert read_contract(scene["contract_id"])["status"] == "SIGNED"

    def test_the_identical_activate_succeeds_once_the_section_is_census_locked(self, api):
        """PRD 3.2: "One later step in the contract lifecycle belongs here for
        completeness: once a section has cleared its census decision, a `ProgramAdmin`
        activates each signed contract, moving it `SIGNED → ACTIVE` and incrementing the
        contract's `version` by 1."
        PRD 3.6: "When the paid headcount meets or exceeds the minimum, the section
        runs. It moves `OPEN → CENSUS_LOCKED` or `WAITLIST_ONLY → CENSUS_LOCKED`, and
        the two starting states produce an identical set of consequences."

        Design: Difficulty/cross_entity_state_dependency/contract_activate_depends_on_offering_reaching_census_locked
        """
        reset_clock()
        scene = setup_open_offering()
        add_paid_registration(scene["offering_id"], learner_index=0)
        set_clock("2026-09-01T00:00:00Z")
        api.activate_instructor_contract(scene["contract_id"], ADMIN)

        offering = validate_success(api.census_offering(scene["offering_id"], ADMIN))
        assert offering["status"] == "CENSUS_LOCKED"

        data = validate_success(
            api.activate_instructor_contract(scene["contract_id"], ADMIN)
        )
        assert data["status"] == "ACTIVE"
        assert read_contract(scene["contract_id"])["status"] == "ACTIVE"


class TestInstructorScheduleWindows:
    """Teaching windows are compared as half-open intervals."""

    def test_adjacent_window_may_be_signed(self, api):
        """PRD 3.2: "Each of those staffs a section with its own teaching window, and
        each window is treated as **half-open**: it includes its `start_date` and
        excludes its `end_date`."
        PRD 3.2: "Because the windows are half-open, pure adjacency is not a conflict:
        an instructor may accept a section beginning at exactly the instant another of
        their sections ends."

        Design: Difficulty/resource_temporal_overlap/instructor_half_open_windows_allow_adjacency_reject_intersection
        """
        reset_clock()
        scene = setup_instructor_window_scene()
        data = validate_success(
            api.sign_instructor_contract(
                scene["winter_contract_id"],
                {"decision": "ACCEPT"},
                make_instructor_headers(scene["instructor_id"]),
            )
        )
        assert data["status"] == "SIGNED"

    def test_intersecting_window_is_refused_and_leaves_the_contract_offered(self, api):
        """PRD 3.2: "If any such window intersects the half-open window of the section
        being accepted, the acceptance is refused with
        `ERR_INSTRUCTOR_SCHEDULE_CONFLICT`."
        PRD 3.2: "Accepting moves it `OFFERED → SIGNED`, increments the instructor's
        `active_contract_count` by 1, and increments both the contract's `version` and
        the instructor's `version` by 1 each. `active_contract_count` is the number of
        that instructor's contracts whose `status` is `SIGNED` or `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/instructor_half_open_windows_allow_adjacency_reject_intersection
        """
        reset_clock()
        scene = setup_instructor_window_scene()
        validate_success(
            api.sign_instructor_contract(
                scene["winter_contract_id"],
                {"decision": "ACCEPT"},
                make_instructor_headers(scene["instructor_id"]),
            )
        )
        validate_error(
            api.sign_instructor_contract(
                scene["lab_contract_id"],
                {"decision": "ACCEPT"},
                make_instructor_headers(scene["instructor_id"]),
            ),
            ApiErrorId.ERR_INSTRUCTOR_SCHEDULE_CONFLICT,
            409,
        )
        assert read_contract(scene["lab_contract_id"])["status"] == "OFFERED"
        assert read_instructor(scene["instructor_id"])["active_contract_count"] == 2


def test_declining_a_contract_is_terminal_and_blocks_activation(api):
    """PRD 3.2: "Declining moves the contract `OFFERED → DECLINED`, a terminal state,
    and increments the contract's `version` by 1."
    PRD 3.2: "Accepting moves it `OFFERED → SIGNED`, increments the instructor's
    `active_contract_count` by 1, and increments both the contract's `version` and the
    instructor's `version` by 1 each. `active_contract_count` is the number of that
    instructor's contracts whose `status` is `SIGNED` or `ACTIVE`."
    PRD 3.2: "Activation requires the contract to be `SIGNED` and requires the section
    it staffs to be in `status` `CENSUS_LOCKED`; a cross-entity failure on that second
    condition is reported as `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decline_contract_moves_to_declined_and_blocks_later_activate
    """
    reset_clock()
    scene = setup_draft_offering(sign=False)

    declined = validate_success(
        api.sign_instructor_contract(
            scene["contract_id"],
            {"decision": "DECLINE"},
            make_instructor_headers(scene["instructor_id"]),
        )
    )
    assert declined["status"] == "DECLINED"

    validate_error(
        api.activate_instructor_contract(scene["contract_id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    assert read_contract(scene["contract_id"])["status"] == "DECLINED"
    assert read_instructor(scene["instructor_id"])["active_contract_count"] == 0


def test_pay_caps_the_variable_component_at_the_enrollment_cap(api):
    """PRD 3.8: "In both variants, a headcount is capped by taking the smaller of that
    headcount and `enrollment_cap_for_pay`; the capped figure is multiplied by
    `per_enrollment_cents` to give the variable component; the variable component is
    added to `base_stipend_cents` to give a raw total; and the raw total is multiplied
    by the instructor's credential multiplier — 1.00 for `ADJUNCT`, 1.15 for `SENIOR`,
    1.30 for `MASTER` — and rounded half up, once, to whole cents."
    PRD 3.8: "It then computes `settled_pay_cents`, moves the contract `ACTIVE →
    SETTLED` — terminal — decreases the instructor's `active_contract_count` by 1, and
    increments both the contract's `version` and the instructor's `version` by 1 each."

    Design: Corner/calculations/instructor_pay_caps_variable_component_at_enrollment_cap
    """
    reset_clock()
    scene = setup_completed_offering_for_settlement(
        num_learners=3,
        completions=0,
        contract_overrides={"enrollment_cap_for_pay": 1, "pay_basis": "CENSUS_LOCKED"},
        offering_overrides={"min_enrollment": 3},
    )
    data = validate_success(api.settle_instructor_contract(scene["contract_id"], ADMIN))
    assert data["census_headcount"] == 3
    assert data["settled_pay_cents"] == 301697, (
        f"(250000 + min(3, 1) * 12345) * 1.15 rounds to 301697, got "
        f"{data['settled_pay_cents']}"
    )
    assert data["settled_pay_cents"] != 330090
    assert data["status"] == "SETTLED"
    assert read_instructor(scene["instructor_id"])["active_contract_count"] == 0
    assert read_registration(scene["seats"][0]["registration_id"])[
        "enrollment_status"
    ] == "NO_SHOW"


def test_final_completion_with_no_completions_pays_the_base_stipend_only(api):
    """PRD 3.8: "Under the `FINAL_COMPLETION` basis, the headcount is the contract's
    `final_headcount`: the count of completed registrations measured at settle time."
    PRD 3.8: "Settlement first records `final_headcount` as the number of registrations
    on the section whose `enrollment_status` is `COMPLETED`, evaluated at this instant."
    PRD 3.8: "Any registration still sitting at `enrollment_status` `ENROLLED` —
    enrolled, paid, but never awarded a completion — moves `ENROLLED → NO_SHOW`; no
    refund is issued for a no-show, and the line remains inside the input set of the
    program-revenue calculation."

    Design: Corner/calculations/instructor_pay_final_completion_with_zero_completions_pays_base_only
    """
    reset_clock()
    scene = setup_completed_offering_for_settlement(
        num_learners=1,
        completions=0,
        contract_overrides={"pay_basis": "FINAL_COMPLETION"},
    )
    data = validate_success(api.settle_instructor_contract(scene["contract_id"], ADMIN))
    assert data["final_headcount"] == 0, (
        f"no completed registrations means a final headcount of 0, got "
        f"{data['final_headcount']}"
    )
    assert data["census_headcount"] == 1
    assert data["settled_pay_cents"] == 287500, (
        f"250000 * 1.15 rounds to 287500, got {data['settled_pay_cents']}"
    )
    assert data["status"] == "SETTLED"
    assert read_registration(scene["seats"][0]["registration_id"])[
        "enrollment_status"
    ] == "NO_SHOW"
