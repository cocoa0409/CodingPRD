"""Volunteer screening lifecycle, role-assignment gates, and staffing levels
(PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_volunteer,
    clear_volunteer,
    create_classroom,
    create_program,
    create_volunteer,
    create_volunteer_with_assignment,
    decide_check,
    get_assignment,
    get_classroom,
    get_screening_check,
    get_volunteer,
    make_volunteer_headers,
    open_registration,
    propose_assignment,
    register_child,
    resubmit_check,
    setup_family_with_children,
    setup_open_program_with_classroom,
    submit_check,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_safety_officer_headers

_VOLCOORD = TEST_USERS["volunteer_coordinator_headers"]


class TestVolunteerIntake:
    def test_minor_computed_and_lead_role_forbidden(self, api, volunteer_coordinator_headers):
        """PRD §3.4: "The application is born `APPLIED`, and `is_minor` is
        derived at once: true when the volunteer's age at the program's
        `start_date` — computed by the same calendar method as
        `age_at_registration` — is strictly under 18"; and "A minor may never
        be proposed as `LEAD_TEACHER` (`ERR_MINOR_ROLE_FORBIDDEN`, HTTP 422)".

        Design: Corner/entities/volunteer_minor_computed_and_lead_role_rejected
        """
        program = create_program()
        classroom = create_classroom(program["id"])
        teen = create_volunteer(program["id"], birth_date="2012-06-01")
        assert teen["is_minor"] is True, (
            "age 14 on the 2026-08-17 start_date — computed, not client input"
        )

        resp = api.create_role_assignment(
            {"volunteer_id": teen["id"], "classroom_id": classroom["id"],
             "role": "LEAD_TEACHER"},
            volunteer_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MINOR_ROLE_FORBIDDEN, 422)

        resp_ok = api.create_role_assignment(
            {"volunteer_id": teen["id"], "classroom_id": classroom["id"],
             "role": "ASSISTANT_TEACHER"},
            volunteer_coordinator_headers,
        )
        assert validate_success(resp_ok, 201)["status"] == "PROPOSED", (
            "minors may assist, not lead"
        )


class TestScreeningChecks:
    def test_duplicate_active_check_type_rejected(self, api):
        """PRD §3.4: "A volunteer may hold only one active check per type,
        active meaning `SUBMITTED`, `INFO_REQUESTED`, or `CLEARED`; a duplicate
        is rejected with `ERR_DUPLICATE_CHECK`."

        Design: Corner/validations/duplicate_active_check_type_rejected
        """
        program = create_program()
        volunteer = create_volunteer(program["id"])
        submit_check(volunteer["id"], "BACKGROUND")
        resp = api.create_screening_check(
            {"volunteer_id": volunteer["id"], "check_type": "BACKGROUND"},
            make_volunteer_headers(volunteer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CHECK, 409)

    def test_self_review_on_decide_forbidden(self, api):
        """PRD §3.4: "Self-review is forbidden — a decision on a check whose
        `volunteer_id` equals the officer's own `X-User-ID` fails with
        `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403), ahead of the state gate".

        Design: Corner/validations/self_review_on_decide_forbidden
        """
        program = create_program()
        volunteer = create_volunteer(program["id"])
        check = submit_check(volunteer["id"], "BACKGROUND")
        resp = api.decide_screening_check(
            check["id"], {"decision": "CLEARED"},
            make_safety_officer_headers(volunteer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_REVIEW_FORBIDDEN, 403)
        assert get_screening_check(check["id"])["status"] == "SUBMITTED"

    def test_decide_after_terminal_returns_invalid_state(self, api):
        """PRD §3.4: "deciding a check that is not `SUBMITTED` fails with
        `ERR_INVALID_STATE`" — `CLEARED` is terminal, so a further decide is
        rejected without rewriting the decision.

        Design: Corner/state_machines/screening_decide_after_terminal_returns_invalid_state
        """
        program = create_program()
        volunteer = create_volunteer(program["id"])
        check = submit_check(volunteer["id"], "BACKGROUND")
        decided = decide_check(check["id"], "CLEARED")
        first_decided_at = decided["decided_at"]

        resp = api.decide_screening_check(
            check["id"], {"decision": "REJECTED"},
            TEST_USERS["safety_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        after = get_screening_check(check["id"])
        assert after["status"] == "CLEARED"
        assert after["decided_at"] == first_decided_at


class TestScreeningInfoRequestCycle:
    def _setup(self):
        program = create_program()
        volunteer = create_volunteer(program["id"])
        check = submit_check(volunteer["id"], "BACKGROUND")
        return volunteer, check

    def test_info_request_resubmit_cycle_revisits_submitted(self, api):
        """PRD §3.4: "An `INFO_REQUESTED` check loops: the owning volunteer —
        and only that volunteer, `ERR_FORBIDDEN` otherwise — resubmits it with
        `response_notes`, returning it `INFO_REQUESTED` → `SUBMITTED` and
        incrementing `resubmission_count` by one; the cycle may repeat."

        Design: Difficulty/non_linear_state_machine/screening_check_info_request_cycle
        """
        volunteer, check = self._setup()
        decided_1 = decide_check(check["id"], "INFO_REQUESTED",
                                 notes="Need a clearer scan")
        assert decided_1["status"] == "INFO_REQUESTED"

        resub_1 = resubmit_check(check["id"], volunteer["id"], "Re-scanned")
        assert resub_1["status"] == "SUBMITTED"
        assert resub_1["resubmission_count"] == 1

        decided_2 = decide_check(check["id"], "INFO_REQUESTED",
                                 notes="Still unreadable")
        assert decided_2["status"] == "INFO_REQUESTED", "the cycle revisits SUBMITTED"

        resub_2 = resubmit_check(check["id"], volunteer["id"], "Third attempt")
        assert resub_2["resubmission_count"] == 2, (
            "the counter accumulates across the loop"
        )

    def test_cycle_accumulates_counter_and_records_reviewer(self, api):
        """PRD §3.4: the SafetyOfficer decides "in one of three directions
        supplied as `decision`, recording `reviewer_id`, `decision_notes`, and
        `decided_at` on any decision"; and "the cycle may repeat". After the
        loop the volunteer is still `SCREENING`: §3.4 moves a volunteer to
        `CLEARED` only when they hold "a `CLEARED` check for every one of the
        three required types".

        Design: Difficulty/non_linear_state_machine/screening_check_info_request_cycle
        """
        volunteer, check = self._setup()
        decide_check(check["id"], "INFO_REQUESTED", notes="Need a clearer scan")
        resubmit_check(check["id"], volunteer["id"], "Re-scanned")
        decide_check(check["id"], "INFO_REQUESTED", notes="Still unreadable")
        resubmit_check(check["id"], volunteer["id"], "Third attempt")

        final = decide_check(check["id"], "CLEARED")
        assert final["status"] == "CLEARED"
        assert final["resubmission_count"] == 2
        assert final["reviewer_id"] == "so-1"

        volunteer_after = get_volunteer(volunteer["id"])
        assert_volunteer(volunteer_after)
        assert volunteer_after["status"] == "SCREENING", (
            "only one of the three required check types is CLEARED"
        )


class TestAssignmentGates:
    def test_duplicate_assignment_same_classroom_rejected(self, api):
        """PRD §3.4: "a volunteer may hold only one active assignment per
        classroom — active meaning `PROPOSED` or `CONFIRMED` — with duplicates
        rejected as `ERR_DUPLICATE_ASSIGNMENT`."

        Design: Corner/validations/duplicate_assignment_same_classroom_rejected
        """
        program = create_program()
        classroom = create_classroom(program["id"])
        volunteer = create_volunteer(program["id"])
        propose_assignment(volunteer["id"], classroom["id"], "CRAFT_LEADER")
        resp = api.create_role_assignment(
            {"volunteer_id": volunteer["id"], "classroom_id": classroom["id"],
             "role": "SNACK_COORDINATOR"},
            _VOLCOORD,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT, 409)

    def test_second_lead_teacher_rejected(self, api):
        """PRD §3.4: "for `LEAD_TEACHER`, no other `CONFIRMED` lead teacher may
        exist in the classroom (`ERR_LEAD_TEACHER_TAKEN`)"; and on clearance
        "every `PROPOSED` role assignment of that volunteer auto-confirms —
        except any that would violate the one-lead-teacher-per-classroom rule
        or the child-facing double-booking rule, which stay `PROPOSED`."

        Design: Corner/validations/lead_teacher_second_lead_rejected
        """
        program, classroom = setup_open_program_with_classroom(capacity=10)
        first = create_volunteer_with_assignment(
            program["id"], classroom["id"], "LEAD_TEACHER", decide_count=3
        )
        assert first["assignment"]["status"] == "CONFIRMED"

        second = create_volunteer_with_assignment(
            program["id"], classroom["id"], "LEAD_TEACHER", decide_count=3
        )
        assert second["assignment"]["status"] == "PROPOSED", (
            "auto-confirm skipped the violating assignment instead of erroring"
        )

        resp = api.confirm_role_assignment(second["assignment"]["id"], _VOLCOORD)
        validate_error(resp, ApiErrorId.ERR_LEAD_TEACHER_TAKEN, 409)
        assert get_assignment(first["assignment"]["id"])["status"] == "CONFIRMED"

    def test_double_booking_across_classrooms_rejected(self, api):
        """PRD §3.4: "for the child-facing roles `LEAD_TEACHER` and
        `ASSISTANT_TEACHER`, the volunteer may hold no other `CONFIRMED`
        child-facing assignment in any other classroom of the same program
        (`ERR_VOLUNTEER_DOUBLE_BOOKED`)".

        Design: Corner/validations/volunteer_double_booking_across_classrooms_rejected
        """
        program = create_program()
        koalas = create_classroom(program["id"], name="Koalas", age_min=4, age_max=6)
        bears = create_classroom(program["id"], name="Bears", age_min=7, age_max=9)
        open_registration(program["id"])

        volunteer = create_volunteer(program["id"])
        propose_assignment(volunteer["id"], koalas["id"], "LEAD_TEACHER")
        clear_volunteer(volunteer["id"])
        second = propose_assignment(volunteer["id"], bears["id"], "ASSISTANT_TEACHER")

        resp = api.confirm_role_assignment(second["id"], _VOLCOORD)
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_DOUBLE_BOOKED, 409)
        assert get_assignment(second["id"])["status"] == "PROPOSED"


class TestClearanceCascade:
    def _setup(self):
        """1 enrolled child (required_adults == 2); volunteer v1 with a
        PROPOSED LEAD_TEACHER assignment and 2 of 3 checks CLEARED."""
        program, classroom = setup_open_program_with_classroom(capacity=10)
        family, children = setup_family_with_children(count=1)
        register_child(children[0]["id"], classroom["id"], family["id"])
        v1 = create_volunteer_with_assignment(
            program["id"], classroom["id"], "LEAD_TEACHER", decide_count=2
        )
        return program, classroom, v1

    def test_two_of_three_cleared_fires_nothing(self, api):
        """PRD §3.4: "When the volunteer holds a `CLEARED` check for every one
        of the three required types, the volunteer moves `SCREENING` →
        `CLEARED`, and every `PROPOSED` role assignment of that volunteer
        auto-confirms" — at two of three cleared, none of the cascade hops
        have fired.

        Design: Difficulty/transitive_cascade/screening_clearance_auto_confirms_assignment
        """
        _program, _classroom, v1 = self._setup()
        assert get_volunteer(v1["volunteer"]["id"])["status"] == "SCREENING"
        assert get_assignment(v1["assignment"]["id"])["status"] == "PROPOSED"

    def test_third_clearance_cascades_to_staffing(self, api):
        """PRD §3.4: "When the volunteer holds a `CLEARED` check for every one
        of the three required types, the volunteer moves `SCREENING` →
        `CLEARED`, and every `PROPOSED` role assignment of that volunteer
        auto-confirms — except any that would violate the
        one-lead-teacher-per-classroom rule or the child-facing double-booking
        rule, which stay `PROPOSED`. Each auto-confirm stamps `confirmed_at`
        and recomputes the classroom's staffing."

        Design: Difficulty/transitive_cascade/screening_clearance_auto_confirms_assignment
        """
        _program, classroom, v1 = self._setup()
        decide_check(v1["checks"][2]["id"], "CLEARED")

        assert get_volunteer(v1["volunteer"]["id"])["status"] == "CLEARED"
        assignment = get_assignment(v1["assignment"]["id"])
        assert assignment["status"] == "CONFIRMED"
        assert assignment["confirmed_at"] is not None

        view = get_classroom(classroom["id"])
        assert view["confirmed_adult_count"] == 1
        assert view["staffing_status"] == "UNDERSTAFFED", (
            "1 confirmed adult against the two-adult minimum (PRD §3.4)"
        )


class TestConfirmGatedByClearance:
    def _setup(self):
        """Volunteer with a PROPOSED ASSISTANT_TEACHER assignment and exactly
        2 of 3 checks CLEARED (volunteer still SCREENING)."""
        program, classroom = setup_open_program_with_classroom(capacity=10)
        v1 = create_volunteer_with_assignment(
            program["id"], classroom["id"], "ASSISTANT_TEACHER", decide_count=2
        )
        return program, classroom, v1

    def test_confirm_rejected_until_volunteer_cleared(self, api):
        """PRD §3.4: "the volunteer must be `CLEARED`
        (`ERR_VOLUNTEER_NOT_CLEARED`)" — with only two of three checks cleared
        the confirm is rejected.

        Design: Difficulty/cross_entity_state_dependency/assignment_confirm_gated_by_volunteer_clearance
        """
        _program, _classroom, v1 = self._setup()
        resp = api.confirm_role_assignment(v1["assignment"]["id"], _VOLCOORD)
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_CLEARED, 409)

    def test_third_clearance_confirms_without_second_call(self, api):
        """PRD §3.4: "every `PROPOSED` role assignment of that volunteer
        auto-confirms" when "the volunteer holds a `CLEARED` check for every
        one of the three required types" — the third clearance cascades with no
        further confirm call.

        Design: Difficulty/cross_entity_state_dependency/assignment_confirm_gated_by_volunteer_clearance
        """
        _program, _classroom, v1 = self._setup()
        decide_check(v1["checks"][2]["id"], "CLEARED")
        assert get_assignment(v1["assignment"]["id"])["status"] == "CONFIRMED"


class TestStaffingThreshold:
    def test_second_confirmed_adult_flips_to_adequate(self, api):
        """PRD §3.4: "`staffing_status` is `ADEQUATE` when the confirmed count
        meets the requirement — or when no adults are required at all —
        `UNSTAFFED` when the confirmed count is zero while adults are required,
        and `UNDERSTAFFED` otherwise." With one enrolled child the requirement
        is the two-adult minimum, so exactly-one confirmed adult reads
        UNDERSTAFFED and the second confirmation flips to ADEQUATE (inclusive
        threshold).

        Design: Corner/cross_cutting_layers/staffing_threshold_exact_flip
        """
        program, classroom = setup_open_program_with_classroom(capacity=10)
        family, children = setup_family_with_children(count=1)
        register_child(children[0]["id"], classroom["id"], family["id"])

        create_volunteer_with_assignment(
            program["id"], classroom["id"], "LEAD_TEACHER", decide_count=3
        )
        second = create_volunteer_with_assignment(
            program["id"], classroom["id"], "ASSISTANT_TEACHER", decide_count=2
        )

        mid = get_classroom(classroom["id"])
        assert mid["confirmed_adult_count"] == 1
        assert mid["staffing_status"] == "UNDERSTAFFED", "one below the threshold"

        decide_check(second["checks"][2]["id"], "CLEARED")
        final = get_classroom(classroom["id"])
        assert final["confirmed_adult_count"] == 2
        assert final["staffing_status"] == "ADEQUATE", (
            "confirmed == required flips to ADEQUATE — inclusive threshold"
        )


class TestRequiredAdultsFormula:
    """The nested zero-branch / max / ceil staffing formula (PRD §3.4)."""

    def test_zero_branch_and_two_adult_floor(self, api):
        """PRD §3.4: "A classroom's `required_adults` is zero when
        `enrolled_count` is zero, and otherwise the larger of two — the
        two-adult minimum — and `enrolled_count` divided by the program's
        `child_staff_ratio` rounded up to the next whole adult." With ratio 4:
        0 enrolled -> 0 (zero branch); 1 enrolled -> 2 (the floor dominates
        ceil(1/4) == 1).

        Design: Difficulty/combinatorial_formula/required_adults_nested_max_ceil_branches
        """
        program, classroom = setup_open_program_with_classroom(
            capacity=10, program_overrides={"child_staff_ratio": 4}
        )
        assert classroom["required_adults"] == 0, "zero-enrollment branch"

        family, children = setup_family_with_children(count=1)
        register_child(children[0]["id"], classroom["id"], family["id"])
        view = get_classroom(classroom["id"])
        assert view["enrolled_count"] == 1
        assert view["required_adults"] == 2, "two-adult floor dominates ceil(1/4)"

    def test_ceil_crossing_at_eight_and_nine(self, api):
        """PRD §3.4: "A classroom's `required_adults` is zero when
        `enrolled_count` is zero, and otherwise the larger of two — the
        two-adult minimum — and `enrolled_count` divided by the program's
        `child_staff_ratio` rounded up to the next whole adult." With ratio 4:
        8 enrolled -> 2 (ceil(8/4) == 2, the exact boundary); 9 enrolled -> 3
        (ceil(9/4) crosses to 3).

        Design: Difficulty/combinatorial_formula/required_adults_nested_max_ceil_branches
        """
        program, classroom = setup_open_program_with_classroom(
            capacity=10, program_overrides={"child_staff_ratio": 4}
        )
        family, children = setup_family_with_children(count=9)
        for child in children[:8]:
            register_child(child["id"], classroom["id"], family["id"])
        view8 = get_classroom(classroom["id"])
        assert view8["enrolled_count"] == 8
        assert view8["required_adults"] == 2, "ceil(8/4) == 2 exact boundary"

        register_child(children[8]["id"], classroom["id"], family["id"])
        view9 = get_classroom(classroom["id"])
        assert view9["enrolled_count"] == 9
        assert view9["required_adults"] == 3, "ceil(9/4) == 3 threshold crossing"
