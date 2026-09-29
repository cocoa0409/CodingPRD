"""The declared transitions themselves: where a machine starts, which moves it
accepts, which it refuses, and what one accepted move does to its neighbours."""

from test_helpers import (
    ApiErrorId,
    CreditPolicy,
    IntakePosture,
    Pathway,
    PlacementStatus,
    PlanPosture,
    PlanStatus,
    ProgressState,
    ReferralStatus,
    StudentStatus,
    SubjectArea,
    DISTRICT_ADMIN_HEADERS,
    REGISTRAR_HEADERS,
    assert_close,
    assert_common_fields,
    assert_placement,
    assert_referral,
    assert_seat_picture,
    factories as f,
    fixtures as fx,
    make_home_school_counselor_headers,
    make_placement_coordinator_headers,
    validate_error,
    validate_success,
)

ALG1 = {
    "code": "ALG1",
    "title": "Algebra I",
    "subject_area": SubjectArea.MATH.value,
    "credit_value": 1.00,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "min_passing_percent": 60.00,
}

DEFICIENT_SIX = {
    "pathway": Pathway.CREDIT_DEFICIENCY.value,
    "deficiency_credits": 6.00,
    "behavior_incident_count": 1,
    "days_disengaged": 6,
}


def _intake_world(api):
    """One school, one ten-seat centre and one student, nothing referred yet."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC", seat_capacity=10)
    student = fx.register_student(api, home_school["id"])
    return {
        "home_school": home_school,
        "center": center,
        "student": student,
        "counselor": make_home_school_counselor_headers(home_school["id"]),
        "coordinator": make_placement_coordinator_headers(center["id"]),
    }


class TestTheReferralMachineStartsAndAdvancesWhereDeclared:
    """SUBMITTED is the entry state and screening is the only move out of it."""

    def test_a_new_referral_opens_in_submitted_with_its_score_already_computed(
        self, api
    ):
        """The referral reads SUBMITTED at version 1 with every optional intake
        field null, a priority score of 0.5300 and no seat reserved anywhere.

        PRD: "A new referral's `status` begins at `SUBMITTED`."

        Design: Corner/state_machines/new_referral_starts_in_submitted_state
        """
        world = _intake_world(api)

        referral = validate_success(
            api.create_referral(
                f.referral_payload(
                    world["student"]["id"],
                    world["center"]["id"],
                    narrative="six credits short",
                    **DEFICIENT_SIX,
                ),
                world["counselor"],
            ),
            201,
        )
        assert_referral(referral)
        assert_common_fields(referral, expected_version=1)
        assert referral["status"] == ReferralStatus.SUBMITTED.value
        assert_close(referral["priority_score"], 0.5300, "priority score")
        assert referral["missing_items"] is None
        assert referral["waitlist_reason"] is None
        assert referral["offer_expires_on"] is None
        assert referral["promoted_from_waitlist"] is False

        center = fx.read_center(api, world["center"]["id"])
        assert_seat_picture(center, 0, 0, 10, IntakePosture.OPEN.value)

    def test_screening_records_its_note_and_moves_no_seat(self, api):
        """The referral advances to SCREENING at version 2 while the centre's ledger
        and version stand still.

        PRD: "A `PlacementCoordinator` at the receiving center takes a referral from
        `SUBMITTED` to `SCREENING`, optionally recording a `screening_note`."

        Design: Corner/state_machines/screen_moves_referral_submitted_to_screening
        """
        world = _intake_world(api)
        referral = fx.submit_referral(
            api,
            world["student"]["id"],
            world["center"]["id"],
            world["home_school"]["id"],
            **DEFICIENT_SIX,
        )

        screened = validate_success(
            api.screen_referral(
                referral["id"],
                f.screen_payload(screening_note="records reviewed with the counselor"),
                world["coordinator"],
            )
        )
        assert screened["status"] == ReferralStatus.SCREENING.value
        assert screened["version"] == 2
        assert screened["screening_note"] == "records reviewed with the counselor"

        center = fx.read_center(api, world["center"]["id"])
        assert_seat_picture(center, 0, 0, 10, IntakePosture.OPEN.value)
        assert center["version"] == 1

    def test_offering_an_unscreened_referral_reserves_nothing(self, api):
        """The offer transition starts at SCREENING, so a SUBMITTED referral is
        refused with ERR_REFERRAL_STATE_INVALID even at an OPEN centre with a fresh
        version token.

        PRD: "A `PlacementCoordinator` whose `X-User-ID` equals the referral's
        `center_id` moves a referral from `SCREENING` to `PLACEMENT_OFFERED`,
        supplying `expected_center_version` per §2.6 and optionally
        `offer_valid_days`."

        Design: Corner/state_machines/offer_from_submitted_state_rejected
        """
        world = _intake_world(api)
        referral = fx.submit_referral(
            api,
            world["student"]["id"],
            world["center"]["id"],
            world["home_school"]["id"],
            **DEFICIENT_SIX,
        )

        response = api.offer_referral(
            referral["id"],
            f.offer_payload(world["center"]["version"], offer_valid_days=10),
            world["coordinator"],
        )
        validate_error(response, ApiErrorId.REFERRAL_STATE_INVALID.value, 409)

        held = fx.read_referral(api, referral["id"])
        assert held["status"] == ReferralStatus.SUBMITTED.value
        assert held["offer_expires_on"] is None
        assert held["version"] == 1

        center = fx.read_center(api, world["center"]["id"])
        assert_seat_picture(center, 0, 0, 10, IntakePosture.OPEN.value)
        assert center["version"] == 1

    def test_replaying_the_screen_call_keeps_the_first_note(self, api):
        """A second screening of an already-screened referral is refused and the
        original note and version survive the replay.

        PRD: "A transition attempted from the wrong status — screening something
        already screened, denying something already denied — is refused with
        `ERR_REFERRAL_STATE_INVALID`."

        Design: Corner/state_machines/second_screen_call_on_same_referral_rejected
        """
        world = _intake_world(api)
        referral = fx.submit_referral(
            api,
            world["student"]["id"],
            world["center"]["id"],
            world["home_school"]["id"],
            **DEFICIENT_SIX,
        )
        validate_success(
            api.screen_referral(
                referral["id"],
                f.screen_payload(screening_note="first pass"),
                world["coordinator"],
            )
        )

        replay = api.screen_referral(
            referral["id"],
            f.screen_payload(screening_note="second pass"),
            world["coordinator"],
        )
        validate_error(replay, ApiErrorId.REFERRAL_STATE_INVALID.value, 409)

        held = fx.read_referral(api, referral["id"])
        assert held["screening_note"] == "first pass"
        assert held["status"] == ReferralStatus.SCREENING.value
        assert held["version"] == 2

    def test_resubmitting_a_referral_that_was_never_asked_for_more_is_refused(
        self, api
    ):
        """Resubmission starts only at INFO_REQUESTED, so the SUBMITTED referral
        keeps its counters and its 0.3800 score untouched.

        PRD: "From `INFO_REQUESTED` the sending school's `HomeSchoolCounselor`
        resubmits, moving the referral `INFO_REQUESTED → SCREENING`, clearing
        `missing_items`, replacing `narrative` and overwriting whichever of
        `deficiency_credits`, `behavior_incident_count` and `days_disengaged` are
        supplied — each optional in the resubmission."

        Design: Corner/state_machines/resubmit_from_submitted_state_rejected
        """
        world = _intake_world(api)
        referral = fx.submit_referral(
            api,
            world["student"]["id"],
            world["center"]["id"],
            world["home_school"]["id"],
            pathway=Pathway.CREDIT_DEFICIENCY.value,
            deficiency_credits=4.00,
            behavior_incident_count=1,
            days_disengaged=6,
        )
        assert_close(referral["priority_score"], 0.3800, "priority score")

        response = api.resubmit_referral(
            referral["id"],
            f.resubmit_payload(deficiency_credits=6.00, narrative="updated counts"),
            world["counselor"],
        )
        validate_error(response, ApiErrorId.REFERRAL_STATE_INVALID.value, 409)

        held = fx.read_referral(api, referral["id"])
        assert held["status"] == ReferralStatus.SUBMITTED.value
        assert_close(held["deficiency_credits"], 4.00, "deficiency credits")
        assert_close(held["priority_score"], 0.3800, "priority score after the refusal")
        assert held["version"] == 1

    def test_a_denied_referral_accepts_neither_an_offer_nor_a_waitlist_place(
        self, api
    ):
        """DENIED is terminal: both onward seating calls are refused, the denial
        reason survives and the referral rests at version 3.

        PRD: "Denial moves the referral `SCREENING → DENIED`, a terminal status,
        recording the required `denial_reason`."

        Design: Corner/state_machines/denied_referral_is_terminal_and_rejects_offer
        """
        world = _intake_world(api)
        referral = fx.screened_referral(
            api,
            world["student"]["id"],
            world["center"]["id"],
            world["home_school"]["id"],
            **DEFICIENT_SIX,
        )
        denied = validate_success(
            api.deny_referral(
                referral["id"],
                f.deny_referral_payload(
                    denial_reason="student enrolled in a neighbouring district"
                ),
                world["coordinator"],
            )
        )
        assert denied["status"] == ReferralStatus.DENIED.value

        offer = api.offer_referral(
            referral["id"],
            f.offer_payload(world["center"]["version"], offer_valid_days=10),
            world["coordinator"],
        )
        validate_error(offer, ApiErrorId.REFERRAL_STATE_INVALID.value, 409)
        waitlist = api.waitlist_referral(
            referral["id"],
            f.waitlist_payload(waitlist_reason="try again later"),
            world["coordinator"],
        )
        validate_error(waitlist, ApiErrorId.REFERRAL_STATE_INVALID.value, 409)

        held = fx.read_referral(api, referral["id"])
        assert held["status"] == ReferralStatus.DENIED.value
        assert held["denial_reason"] == "student enrolled in a neighbouring district"
        assert held["offer_expires_on"] is None
        assert held["waitlist_reason"] is None
        assert held["version"] == 3

        center = fx.read_center(api, world["center"]["id"])
        assert center["seats_reserved"] == 0
        assert center["version"] == 1


class TestOneAcceptedMoveFiresEveryDeclaredSideEffect:
    """Acceptance writes four rows in one request."""

    def test_accepting_an_offer_creates_the_placement_and_converts_the_seat(self, api):
        """The referral closes at ACCEPTED, a fresh ACTIVE placement appears with
        empty accumulators, the student becomes PLACED_ALT and the reserved seat
        turns into an occupied one without changing the committed count.

        PRD: "Acceptance creates a placement whose `referral_id`, `student_id` and
        `center_id` are copied from the referral and whose `status` begins at
        `ACTIVE`, and it sets the student's `status` to `PLACED_ALT`."

        Design: Corner/state_machines/accept_offer_side_effects_create_placement_and_commit_seat
        """
        world = _intake_world(api)
        referral = fx.screened_referral(
            api,
            world["student"]["id"],
            world["center"]["id"],
            world["home_school"]["id"],
            **DEFICIENT_SIX,
        )
        fx.offer_seat(api, referral["id"], world["center"]["id"])

        placement = validate_success(
            api.accept_offer(
                referral["id"],
                f.accept_offer_payload(
                    credit_policy=CreditPolicy.SEAT_TIME.value,
                    start_date="2026-08-03",
                ),
                world["counselor"],
            ),
            201,
        )
        assert_placement(placement)
        assert placement["status"] == PlacementStatus.ACTIVE.value
        assert placement["credit_policy"] == CreditPolicy.SEAT_TIME.value
        assert placement["start_date"] == "2026-08-03"
        assert placement["referral_id"] == referral["id"]
        assert placement["student_id"] == world["student"]["id"]
        assert placement["center_id"] == world["center"]["id"]
        assert placement["days_present"] == 0
        assert placement["days_enrolled"] == 0
        assert placement["attendance_rate"] is None
        assert placement["support_sessions_completed"] == 0
        assert placement["re_entry_eligible"] is False

        assert fx.read_referral(api, referral["id"])["status"] == (
            ReferralStatus.ACCEPTED.value
        )
        assert fx.read_student(api, world["student"]["id"])["status"] == (
            StudentStatus.PLACED_ALT.value
        )

        center = fx.read_center(api, world["center"]["id"])
        assert_seat_picture(center, 1, 0, 9, IntakePosture.OPEN.value)
        assert center["seats_available"] + center["seats_committed"] == 10

    def test_a_denied_re_entry_cycles_the_placement_back_to_active(self, api):
        """The placement machine is cyclic: the denial returns it to ACTIVE, clears
        both re-entry fields, keeps the seat committed and leaves the placement
        immediately re-requestable.

        PRD: "Denial moves the placement from `RE_ENTRY_PENDING` back to `ACTIVE`,
        records the required `re_entry_denial_reason`, and clears both
        `target_re_entry_date` and `re_entry_requested_by_user_id` back to null so a
        later request starts clean; the seat is held throughout and the placement's
        `version` increments by 1."

        Design: Corner/state_machines/deny_re_entry_returns_placement_to_active_and_keeps_seat
        """
        world = fx.re_entry_ready_world(api)
        coordinator = make_placement_coordinator_headers(world["center"]["id"])
        pending = validate_success(
            api.request_re_entry(
                world["placement"]["id"],
                f.request_re_entry_payload(target_re_entry_date="2026-08-24"),
                coordinator,
            )
        )
        assert pending["status"] == PlacementStatus.RE_ENTRY_PENDING.value

        denied = validate_success(
            api.deny_re_entry(
                world["placement"]["id"],
                f.deny_re_entry_payload(
                    re_entry_denial_reason=(
                        "home school wants one more grading period of evidence"
                    )
                ),
                DISTRICT_ADMIN_HEADERS,
            )
        )
        assert denied["status"] == PlacementStatus.ACTIVE.value
        assert denied["re_entry_denial_reason"] == (
            "home school wants one more grading period of evidence"
        )
        assert denied["target_re_entry_date"] is None
        assert denied["re_entry_requested_by_user_id"] is None
        assert_close(denied["attendance_rate"], 0.9000, "attendance rate")
        assert_close(denied["readiness_score"], 0.7800, "readiness score")
        assert denied["re_entry_eligible"] is True
        assert denied["version"] == pending["version"] + 1

        center = fx.read_center(api, world["center"]["id"])
        assert center["active_student_count"] == 1
        assert center["seats_available"] == 9
        assert fx.read_student(api, world["student"]["id"])["status"] == (
            StudentStatus.PLACED_ALT.value
        )

    def test_a_draft_plan_refuses_the_award_that_an_active_plan_accepts(self, api):
        """The award is gated on another entity's state: the identical call fails
        with ERR_PLAN_STATE_INVALID while the plan is DRAFT and posts 0.50 credits
        once it is ACTIVE.

        PRD: "Activation is only legal from `DRAFT`; attempting it on a plan that has
        already moved on is refused with `ERR_PLAN_STATE_INVALID`, and that same code
        is what refuses a credit award aimed at a plan still sitting in `DRAFT`."

        Design: Corner/state_machines/award_credit_with_draft_plan_rejected
        """
        world = fx.submitted_world(
            api,
            final_percent=84.00,
            progress={
                "modules_passed_delta": 7,
                "seat_hours_delta": 30.00,
                "module_avg_percent": 84.00,
            },
            course_overrides=dict(ALG1),
            plan_overrides={"required_credits_total": 24.00},
            referral_overrides=dict(DEFICIENT_SIX),
            student_overrides={"grade_level": 11, "cohort_year": 2027},
            activate=False,
        )
        draft = fx.read_plan(api, world["plan"]["id"])
        assert draft["status"] == PlanStatus.DRAFT.value
        assert draft["version"] == 1

        refused = api.award_credit(
            world["enrollment"]["id"],
            f.award_credit_payload(draft["version"]),
            REGISTRAR_HEADERS,
        )
        validate_error(refused, ApiErrorId.PLAN_STATE_INVALID.value, 409)
        assert fx.read_enrollment(api, world["enrollment"]["id"])["progress_state"] == (
            ProgressState.SUBMITTED_FOR_AWARD.value
        )
        assert fx.read_plan(api, world["plan"]["id"])["version"] == 1

        activated = fx.activate_plan(api, world["plan"]["id"])
        assert activated["status"] == PlanStatus.ACTIVE.value
        assert activated["version"] == 2

        award = fx.award_credit(
            api, world["enrollment"]["id"], world["plan"]["id"], REGISTRAR_HEADERS
        )
        assert_close(award["credits_awarded"], 0.50, "credits awarded")
        assert award["award_basis"] == CreditPolicy.SEAT_TIME.value

        plan = fx.read_plan(api, world["plan"]["id"])
        assert_close(plan["credits_earned"], 0.50, "plan credits earned")
        assert_close(plan["expected_credits_by_grade"], 18.00, "expected credits")
        assert plan["posture"] == PlanPosture.OFF_TRACK.value
