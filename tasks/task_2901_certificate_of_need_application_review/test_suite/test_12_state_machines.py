"""Lifecycles: initial states, single-step advances, terminal locks and cascades."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_four_decimal_value,
    assert_instant_equals,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.factories import (
    application_payload,
    public_hearing_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    INTAKE,
    advance_cycle,
    create_application,
    decide_intervention,
    file_letter_of_intent,
    issue_deficiency_notice,
    refresh_application,
    refresh_cycle,
    refresh_intervention,
    refresh_letter_of_intent,
    refresh_public_hearing,
    request_intervention,
    seed_applicant,
    seed_application_submitted,
    seed_batching_cycle,
    seed_completeness_window,
    seed_hearing_room,
    seed_second_applicant,
    set_clock,
)
from test_helpers.test_users import TEST_USERS, make_applicant_headers

INTAKE_2 = TEST_USERS["intake_analyst_2_headers"]

HEARING_START = "2026-08-26T09:00:00Z"
HEARING_END = "2026-08-26T11:00:00Z"
NEW_HEARING_START = "2026-08-27T14:00:00Z"
NEW_HEARING_END = "2026-08-27T16:00:00Z"
NEW_OCCUPANCY_START = "2026-08-27T13:00:00Z"

CURE_DEADLINE = "2026-09-01T00:00:00Z"
PAST_CURE_DEADLINE_CLOCK = "2026-09-02T00:00:00Z"


def _scheduled_hearing():
    world = seed_batching_cycle()
    world["room"] = seed_hearing_room(name="BOARD-A")
    world["hearing"] = get_success_data(
        api_client.create_public_hearing(
            public_hearing_payload(
                world["cycle"]["id"],
                world["room"]["id"],
                scheduled_start_at=HEARING_START,
                scheduled_end_at=HEARING_END,
            ),
            INTAKE,
        ),
        201,
    )
    return world


def _denied_intervention():
    world = seed_application_submitted()
    world["affected_party"] = seed_second_applicant()
    world["intervention"] = request_intervention(
        world["application"],
        world["affected_party"],
        grounds="Lakeview serves the same area and is materially affected",
    )
    world["intervention"] = decide_intervention(
        world["intervention"],
        "DENY",
        denial_reason="Service areas do not overlap materially",
    )
    return world


def _open_deficiency_notice():
    world = seed_completeness_window()
    world["review"] = issue_deficiency_notice(
        world["application"],
        ["Audited financial statements missing"],
        CURE_DEADLINE,
    )
    world["application"] = refresh_application(world["application"]["id"])
    return world


class TestBatchingCycleLifecycle:
    def test_a_new_cycle_opens_for_letters_with_its_need_already_computed(self):
        """Creation is the state entry that also runs the whole methodology.

        PRD §3.2: "A cycle begins life at `OPEN_FOR_LOI` and moves through its
        stages one step at a time, driven by an `IntakeAnalyst` who names the
        destination as `to_status`."
        PRD §3.2: "One further counter lives on the cycle: `reopened_count` starts
        at 0 and records how many times an appeal disposition has dragged the cycle
        back from `DECIDED` to `COMPARATIVE_REVIEW`, as §3.9 explains."
        PRD §3.2: "Creation pins the formula and runs the need methodology."
        PRD §3.2: "The pool is then opened by setting `unallocated_bed_need` equal
        to `unmet_bed_need_at_open`; from that point on the pool moves only through
        allocation and release."

        Design: Corner/state_machines/batching_cycle_starts_in_open_for_loi_with_need_computed_at_creation
        """
        world = seed_batching_cycle()

        cycle = world["cycle"]
        assert cycle["status"] == "OPEN_FOR_LOI"
        assert cycle["reopened_count"] == 0
        assert cycle["pinned_formula_version"] == world["formula"]["version"] == 1
        assert_four_decimal_value(cycle["projected_patient_days"], 27375.0000)
        assert_four_decimal_value(cycle["provisional_required_beds"], 100.0000)
        assert cycle["selected_target_occupancy_rate"] == 0.85
        assert cycle["required_beds_final"] == 89
        assert cycle["inventory_beds_at_open"] == 70
        assert cycle["unmet_bed_need_at_open"] == 19
        assert cycle["unallocated_bed_need"] == 19

    def test_an_advance_that_skips_a_stage_is_refused(self):
        """Only the immediate successor may be named, so a skip forward fails.

        PRD §3.2: "The permitted sequence is `OPEN_FOR_LOI` →
        `OPEN_FOR_APPLICATIONS` → `COMPLETENESS_WINDOW` → `COMPARATIVE_REVIEW`,
        then `DECIDED` (reached not by an advance but by the comparative decision
        of §3.7), then `CLOSED`; `CLOSED` is terminal."
        PRD §3.2: "Only the immediate successor of the current status may be named,
        and any other destination — including a skip forward or a step back — is
        refused with `ERR_INVALID_CYCLE_STATUS_TRANSITION`."
        PRD §3.2: "Each successful advance increases the cycle's `version` by 1."

        Design: Corner/state_machines/cycle_advance_skipping_completeness_window_returns_invalid_transition
        """
        world = seed_batching_cycle()
        opened = advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
        assert opened["status"] == "OPEN_FOR_APPLICATIONS"
        assert opened["version"] == world["cycle"]["version"] + 1

        response = api_client.advance_batching_cycle(
            world["cycle"]["id"], "COMPARATIVE_REVIEW", INTAKE
        )

        validate_error(response, ApiErrorId.ERR_INVALID_CYCLE_STATUS_TRANSITION, 409)
        cycle = refresh_cycle(world["cycle"]["id"])
        assert cycle["status"] == "OPEN_FOR_APPLICATIONS"
        assert cycle["version"] == opened["version"]

    def test_closing_the_application_window_expires_and_withdraws_the_stragglers(
        self,
    ):
        """One advance fires both housekeeping sweeps and touches neither pool.

        PRD §3.2: "Entering `COMPLETENESS_WINDOW` from `OPEN_FOR_APPLICATIONS`
        closes the door on unfinished intake: every letter of intent belonging to
        the cycle that is still `FILED` is set to `EXPIRED`, because it was never
        converted into an application, and every application belonging to the cycle
        that is still `DRAFT` is set to `WITHDRAWN`, because it was never
        submitted."
        PRD §3.4: "The same `WITHDRAWN` outcome is also written by the server,
        without any client request, when the cycle advances from
        `OPEN_FOR_APPLICATIONS` into `COMPLETENESS_WINDOW` and finds the
        application still sitting in `DRAFT`."

        Design: Corner/state_machines/advance_to_completeness_window_expires_unconverted_lois_and_withdraws_drafts
        """
        world = seed_batching_cycle()
        applicant_a = seed_applicant()
        applicant_b = seed_second_applicant()
        world["applicant"] = applicant_a
        loi_a = file_letter_of_intent(world, applicant_a)
        application_a = create_application(world, applicant_a, loi_a)
        loi_b = file_letter_of_intent(
            world,
            applicant_b,
            project_description="10-bed acute care expansion",
            capital_cost_cents=700000000,
            bed_delta=10,
        )
        advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
        assert loi_b["status"] == "FILED"
        assert application_a["status"] == "DRAFT"

        cycle = advance_cycle(world["cycle"]["id"], "COMPLETENESS_WINDOW")

        assert cycle["status"] == "COMPLETENESS_WINDOW"
        assert refresh_letter_of_intent(loi_b["id"])["status"] == "EXPIRED"
        assert refresh_letter_of_intent(loi_a["id"])["status"] == "CONVERTED"
        assert refresh_application(application_a["id"])["status"] == "WITHDRAWN"
        assert cycle["unallocated_bed_need"] == 19


class TestLetterOfIntentTerminalStates:
    def test_a_withdrawn_letter_can_never_become_an_application(self):
        """WITHDRAWN is terminal even though the determination says REVIEWABLE.

        PRD §3.3: "Withdrawal sets `status` to `WITHDRAWN` and increases the
        letter's `version` by 1, and it has a second-order effect worth noting:
        because withdrawn letters are excluded from the 24-month aggregation set,
        withdrawing a prior letter can move a later filing's
        `governing_review_basis` back to `PROJECT_BASED`."
        PRD §3.4: "A letter whose `status` is already `CONVERTED`, or `WITHDRAWN`,
        or `EXPIRED`, yields `ERR_LOI_ALREADY_CONVERTED`, which is also what a
        second conversion of the same letter receives, since the programme permits
        exactly one application per `loi_id`."

        Design: Corner/state_machines/withdrawn_letter_of_intent_cannot_be_converted_into_an_application
        """
        world = seed_batching_cycle()
        applicant = seed_applicant()
        world["applicant"] = applicant
        loi = file_letter_of_intent(world, applicant)
        assert loi["review_determination"] == "REVIEWABLE"
        withdrawn = get_success_data(
            api_client.withdraw_letter_of_intent(
                loi["id"],
                {"reason": "Project deferred to the next cycle"},
                make_applicant_headers(applicant["id"]),
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["review_determination"] == "REVIEWABLE"

        response = api_client.create_application(
            application_payload(loi["id"]), make_applicant_headers(applicant["id"])
        )

        validate_error(response, ApiErrorId.ERR_LOI_ALREADY_CONVERTED, 409)
        _, meta = validate_paginated(
            api_client.list_applications(ADMIN, params={"loi_id": loi["id"]})
        )
        assert meta["total_count"] == 0
        assert refresh_letter_of_intent(loi["id"])["status"] == "WITHDRAWN"


class TestCompletenessReviewLoopGuards:
    def test_an_open_deficiency_notice_blocks_the_deem_complete_declaration(self):
        """The child review is still open, and the notice also left the parent
        `INCOMPLETE`, so two rank-8 admissibility rules are violated at once.

        PRD §3.5: "Critically, no completeness review of that application may still
        be in `DEFICIENCY_NOTICE_ISSUED`: an open, uncured deficiency blocks the
        declaration with `ERR_COMPLETENESS_REVIEW_NOT_OPEN`."
        PRD §3.5: "An `IntakeAnalyst` may do so from `SUBMITTED` or from
        `COMPLETENESS_REVIEW`, again only while the cycle is in
        `COMPLETENESS_WINDOW` (otherwise
        `ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW`)."
        PRD §3.5: "Notice and cure therefore form a loop that can run any number of
        times: `COMPLETENESS_REVIEW` → `INCOMPLETE` on each new notice, `INCOMPLETE`
        → `COMPLETENESS_REVIEW` on each cure."
        PRD §2.8 rank 8 carries both identifiers, both at 409, and does not order
        them against each other, so either identifier is admissible here; the
        declaration must be refused and no state may move.

        Design: Corner/state_machines/deem_complete_with_open_deficiency_notice_returns_completeness_review_not_open
        """
        world = _open_deficiency_notice()
        assert world["review"]["round_number"] == 1
        assert world["review"]["status"] == "DEFICIENCY_NOTICE_ISSUED"

        response = api_client.deem_application_complete(
            world["application"]["id"], INTAKE
        )

        assert response.status_code == 409
        validate_error_is_one_of(
            response,
            [
                ApiErrorId.ERR_COMPLETENESS_REVIEW_NOT_OPEN,
                ApiErrorId.ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW,
            ],
        )
        application = refresh_application(world["application"]["id"])
        assert application["status"] == "INCOMPLETE"
        assert application["completeness_round_count"] == 1
        reviews, _ = validate_paginated(
            api_client.list_completeness_reviews(application["id"], INTAKE)
        )
        assert reviews[0]["id"] == world["review"]["id"]
        assert reviews[0]["status"] == "DEFICIENCY_NOTICE_ISSUED"

    def test_a_cure_filed_after_its_own_deadline_leaves_the_round_open(self):
        """One day past the cure deadline, still inside the cycle's window.

        PRD §3.5: "and the logical clock must be at or before the review's
        `cure_deadline_at`, or the filing is refused with
        `ERR_CURE_DEADLINE_PASSED`."
        PRD §3.5: "A review's own status enumeration is `DEFICIENCY_NOTICE_ISSUED`,
        `CURED` and `EXPIRED`, of which the last two are terminal; `cure_response`
        and `cured_at` are both null until the cure lands."

        Design: Corner/state_machines/cure_filed_after_cure_deadline_returns_cure_deadline_passed
        """
        world = _open_deficiency_notice()
        set_clock(PAST_CURE_DEADLINE_CLOCK)

        response = api_client.file_cure(
            world["review"]["id"],
            {"cure_response": "Audited statements attached"},
            make_applicant_headers(world["applicant"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_CURE_DEADLINE_PASSED, 409)
        reviews, _ = validate_paginated(
            api_client.list_completeness_reviews(
                world["application"]["id"], INTAKE
            )
        )
        review = reviews[0]
        assert review["status"] == "DEFICIENCY_NOTICE_ISSUED"
        assert review["cured_at"] is None
        assert review["cure_response"] is None
        assert refresh_application(world["application"]["id"])["status"] == "INCOMPLETE"


class TestInterventionRulingIsTerminal:
    def test_a_second_ruling_is_refused_and_preserves_the_first_one(self):
        """A different analyst granting afterwards cannot overwrite the denial.

        PRD §3.6: "The intervention must still be in `REQUESTED`; a second ruling
        on the same request is refused with `ERR_INTERVENTION_ALREADY_DECIDED`."
        PRD §3.6: "Either ruling sets `status` to `GRANTED` or `DENIED`, stamps
        `decided_by_user_id` from the acting analyst's `X-User-ID`, records
        `denial_reason` on a denial, and increases the intervention's `version` by
        1."
        PRD §3.6: "Both outcomes are terminal."

        Design: Corner/state_machines/intervention_decided_twice_returns_intervention_already_decided
        """
        world = _denied_intervention()
        assert world["intervention"]["status"] == "DENIED"
        assert world["intervention"]["decided_by_user_id"] == "intake-1"

        response = api_client.decide_intervention(
            world["intervention"]["id"], {"decision": "GRANT"}, INTAKE_2
        )

        validate_error(response, ApiErrorId.ERR_INTERVENTION_ALREADY_DECIDED, 409)
        intervention = refresh_intervention(world["intervention"]["id"], ADMIN)
        assert intervention["status"] == "DENIED"
        assert intervention["decided_by_user_id"] == "intake-1"
        assert (
            intervention["denial_reason"] == "Service areas do not overlap materially"
        )


class TestHearingLifecycle:
    def test_concluding_before_the_gavel_falls_is_refused(self):
        """The clock is weeks short of scheduled_end_at, so nothing is recorded.

        PRD §3.6: "The hearing must be `SCHEDULED` — a cancelled or already-held
        hearing yields `ERR_HEARING_NOT_SCHEDULED` — and the logical clock must be
        at or past the hearing's `scheduled_end_at`, because the programme will not
        certify a session as held before it has finished; an early attempt is
        refused with `ERR_HEARING_NOT_CONCLUDABLE`."
        PRD §3.6: "A hearing is created in `SCHEDULED`, with `attendee_count` and
        `transcript_reference` null and `reschedule_count` at 0."

        Design: Corner/state_machines/hearing_concluded_before_scheduled_end_returns_hearing_not_concludable
        """
        world = _scheduled_hearing()
        assert world["hearing"]["status"] == "SCHEDULED"
        assert_instant_equals(world["hearing"]["created_at"], DEFAULT_CLOCK)

        response = api_client.conclude_public_hearing(
            world["hearing"]["id"],
            {"attendee_count": 42, "transcript_reference": "TR-2026-0826-A"},
            INTAKE,
        )

        validate_error(response, ApiErrorId.ERR_HEARING_NOT_CONCLUDABLE, 409)
        hearing = refresh_public_hearing(world["hearing"]["id"], INTAKE)
        assert hearing["status"] == "SCHEDULED"
        assert hearing["attendee_count"] is None
        assert hearing["transcript_reference"] is None

    def test_a_cancelled_hearing_comes_back_scheduled_with_the_move_counted(self):
        """The cyclic loop runs once and recomputes the buffered occupancy start.

        PRD §3.6: "A scheduled hearing may be cancelled, optionally with a
        `reason`; cancellation sets `status` to `CANCELLED`, increases `version` by
        1, and releases the room: the cancelled row's buffered interval is ignored
        by every later overlap check."
        PRD §3.6: "Success replaces the times and, when supplied, the room,
        recomputes `occupancy_start_at` from the target room's
        `setup_buffer_minutes`, increases `reschedule_count` by 1, returns `status`
        to `SCHEDULED` and increases `version` by 1."
        PRD §3.6: "The `SCHEDULED` → `CANCELLED` → `SCHEDULED` loop may run
        repeatedly, which is what `reschedule_count` records."

        Design: Corner/state_machines/hearing_cancelled_then_rescheduled_returns_to_scheduled_and_counts_the_move
        """
        world = _scheduled_hearing()
        cancelled = get_success_data(
            api_client.cancel_public_hearing(
                world["hearing"]["id"], {"reason": "Room flooding"}, INTAKE
            )
        )
        assert cancelled["status"] == "CANCELLED"

        rescheduled = get_success_data(
            api_client.reschedule_public_hearing(
                world["hearing"]["id"],
                {
                    "scheduled_start_at": NEW_HEARING_START,
                    "scheduled_end_at": NEW_HEARING_END,
                },
                INTAKE,
            ),
            200,
        )

        assert rescheduled["status"] == "SCHEDULED"
        assert_instant_equals(
            rescheduled["occupancy_start_at"], NEW_OCCUPANCY_START
        )
        assert_instant_equals(
            rescheduled["scheduled_start_at"], NEW_HEARING_START
        )
        assert_instant_equals(rescheduled["scheduled_end_at"], NEW_HEARING_END)
        assert rescheduled["reschedule_count"] == 1
        assert rescheduled["hearing_room_id"] == world["room"]["id"]
