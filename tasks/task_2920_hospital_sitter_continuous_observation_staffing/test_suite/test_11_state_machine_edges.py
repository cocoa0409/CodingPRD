"""
State-machine breadth: declared initial states, undeclared edges, terminal
lockdown, replayed transitions, the automatic sweep and the one cross-dimension
guard on a sitter assignment.
"""

from test_helpers import (
    HTTP_CONFLICT,
    HTTP_CREATED,
    HTTP_UNPROCESSABLE,
    ObservationApiClient,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    assert_row_count,
)
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    COMPETENCY_BASIC,
    COMPLETION_HANDOFF_COMPLETE,
    COST_POSTED,
    COST_REVERSED,
    DOC_HANDOFF_DRAFTED,
    DOC_WAIVED,
    ENTRY_KIND_PROVISIONAL,
    ERR_HANDOFF_NOT_SIGNED,
    ERR_INVALID_ASSIGNMENT_STATE,
    ERR_INVALID_EVENT_STATE,
    ERR_INVALID_FEED_STATE,
    EVENT_INCIDENT_REVIEW,
    EVENT_REPORTED,
    FEED_ACTIVE,
    FEED_RELEASED,
    HANDOFF_DRAFTED,
    INTERVENTION_BED_ALARM,
    INTERVENTION_VERBAL_REDIRECTION,
    KIND_ELOPEMENT_ATTEMPT,
    KIND_FALL_WITH_INJURY,
    KIND_SELF_HARM_ATTEMPT,
    ORDER_ACTIVE,
    ORDER_LAPSED,
    ORDER_REASSESSMENT_DUE,
    RELEASE_OBSERVER_RELEASE,
    RELEASE_ORDER_TERMINATED,
    RESOLUTION_CONTINUE_OBSERVATION,
    RESTRICTION_OBSERVATION_ORDER_LAPSED,
    RISK_ELOPEMENT,
    RISK_FALL,
    RISK_SELF_HARM,
    STAFF_AVAILABLE,
    STAFF_ON_ASSIGNMENT,
    STAFF_SUSPENDED,
    STATION_IDLE,
    SUSPENSION_INCIDENT_REVIEW_OPENED,
    UNIT_OPEN,
    UNIT_RESTRICTED,
    VARIANT_ADMISSION_BASELINE,
    VARIANT_ROLLING_EVENT_WEIGHTED,
    WATCH_ON_WATCH,
    WATCH_SCHEDULED,
    WATCH_VOIDED,
)
from test_helpers.factories import (
    certification_payload,
    completion_payload,
    escalate_response_payload,
    order_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    assignment_cost_entries,
    close_event_on_order,
    console_with_active_feed,
    make_assignment,
    make_handoff,
    make_safety_event,
    make_staff,
    read_assignment,
    read_event,
    read_feed,
    read_handoff,
    read_order,
    read_staff,
    read_station,
    read_unit,
    scheduled_watch,
    unit_head,
    unit_patient_order,
    watch_in_progress,
)
from test_helpers.test_users import (
    COORDINATOR,
    MANAGER,
    OFFICER_1,
    OFFICER_2,
    PROVIDER_1,
    make_remote_observer_headers,
    make_sitter_headers,
)


class TestOrderInitialState:
    """Every order begins ACTIVE on the admission-baseline reading of the score."""

    def test_a_second_order_scores_on_the_baseline_ignoring_the_patients_earlier_event(
        self, api: ObservationApiClient
    ) -> None:
        """
        A second order written for a patient who already carries a safety event on an
        earlier order is scored purely from stated criteria plus age: FALL 1.5 plus the
        age adjustment 1.0 for a patient of 76, with the event component pinned at 0.0.
        The earlier order, whose score was recomputed when its event closed, keeps a
        strictly higher figure under the rolling reading, proving the two orders are
        scored independently.

        PRD 3.2: "Every order begins `ACTIVE`."
        PRD 3.2: "At order creation the event component is fixed at exactly 0.0 points."
        PRD 3.2: "No safety-event row is consulted at all in this variant — not even
        events the same patient already accumulated under some earlier, now-terminal
        order."
        PRD 3.3: "Events are counted regardless of their own workflow `status`: an event
        that has already reached `CLOSED` still contributes its points."

        Design: Corner/state_machines/new_order_starts_active_with_the_admission_baseline_variant
        """
        world = unit_patient_order(
            api,
            unit_code="UNIT-C11",
            mrn="MRN-C1101",
            budget_cents=250000,
            age_years=76,
            risk_categories=[RISK_ELOPEMENT],
        )
        sitter = make_staff(api, world["unit"]["id"], full_name="Corner Sitter Eleven")
        close_event_on_order(
            api,
            world["order"]["id"],
            KIND_ELOPEMENT_ATTEMPT,
            sitter["id"],
            RESOLUTION_CONTINUE_OBSERVATION,
            opener_headers=OFFICER_1,
            closer_headers=OFFICER_2,
        )

        second = validate_success(
            api.create_order(
                order_payload(
                    world["patient"]["id"],
                    PROVIDER_1["X-User-ID"],
                    risk_categories=[RISK_FALL],
                    clinical_rationale="Second order, fall precautions",
                ),
                PROVIDER_1,
            ),
            expected_status=HTTP_CREATED,
        )

        assert_fields(
            second,
            label="second order",
            status=ORDER_ACTIVE,
            elopement_risk_score=2.5,
            risk_score_variant=VARIANT_ADMISSION_BASELINE,
            reassessment_interval_hours=24,
            next_reassessment_due_at="2026-08-02T00:00:00.000Z",
            last_reassessed_at=CLOCK_START,
            reassessment_count=0,
            coverage_gap_flag=False,
            discontinuation_recommendation=None,
            discontinued_at=None,
            lapsed_at=None,
            version=1,
        )

        # ELOPEMENT 2.5 + age adjustment 1.0 + 1.0 for the in-window ELOPEMENT_ATTEMPT,
        # which still contributes after reaching CLOSED.
        earlier = read_order(api, world["order"]["id"])
        assert_fields(
            earlier,
            label="earlier order",
            elopement_risk_score=4.5,
            risk_score_variant=VARIANT_ROLLING_EVENT_WEIGHTED,
        )


class TestUndeclaredWatchEdges:
    """The watch dimension refuses edges it never declared, and replays of taken ones."""

    def test_break_start_on_a_still_scheduled_watch_is_refused_with_no_segment_posted(
        self, api: ObservationApiClient
    ) -> None:
        """
        ON_BREAK is declared only as a target of ON_WATCH, so break relief on a watch
        that was never started fails at the state-legality rung — ahead of the rung-21
        break-eligibility rule — and posts no FINAL_SEGMENT row, leaving the ledger head
        at the single PROVISIONAL amount.

        PRD 2.6: "State legality: the target resource is in a state from which the
        requested transition is declared, which also covers terminal lockdown and a
        replayed second attempt at a transition already taken — `ERR_INVALID_ORDER_STATE`,
        `ERR_INVALID_ASSIGNMENT_STATE`, `ERR_INVALID_STATION_STATE`,
        `ERR_INVALID_FEED_STATE`, `ERR_INVALID_EVENT_STATE`,
        `ERR_INVALID_HANDOFF_STATE`, or `ERR_PATIENT_DISCHARGED`."
        PRD 3.5: "Advancing `ON_WATCH → ON_BREAK` requires that at least 120 whole
        minutes — two full hours — have elapsed on the currently open segment since
        `current_segment_started_at`; an earlier attempt is rejected with
        `ERR_BREAK_NOT_YET_ELIGIBLE`."

        Design: Corner/state_machines/break_start_from_scheduled_watch_is_rejected
        """
        world = scheduled_watch(
            api,
            unit_code="UNIT-C12",
            mrn="MRN-C1201",
            budget_cents=250000,
            risk_categories=[RISK_FALL],
            staff_name="Corner Sitter Twelve",
        )
        advance_clock(api, "2026-08-01T08:00:00Z")

        validate_error(
            api.break_start(
                world["assignment"]["id"], make_sitter_headers(world["staff"]["id"])
            ),
            ERR_INVALID_ASSIGNMENT_STATE,
            expected_status=HTTP_CONFLICT,
        )

        assignment = read_assignment(api, world["assignment"]["id"])
        assert_fields(
            assignment,
            label="assignment",
            watch_status=WATCH_SCHEDULED,
            break_started_at=None,
            current_segment_started_at=None,
            watch_segment_count=0,
            watched_minutes=0,
        )
        rows = assignment_cost_entries(api, world["assignment"]["id"])
        assert_row_count(rows, 1, "assignment cost entries")
        assert_fields(
            rows[0],
            label="only ledger row",
            entry_kind=ENTRY_KIND_PROVISIONAL,
            amount_cents=16000,
            status=COST_POSTED,
        )
        assert unit_head(api, world["unit"]["id"]) == 16000
        assert read_staff(api, world["staff"]["id"])["total_watch_minutes"] == 0

    def test_a_second_void_is_refused_and_never_reverses_the_provisional_twice(
        self, api: ObservationApiClient
    ) -> None:
        """
        VOIDED is terminal on the watch dimension, so replaying the void is refused as a
        second attempt at a transition already taken. The single PROVISIONAL row stays
        REVERSED exactly once and the unit's ledger head sits back at the value it held
        before the watch was scheduled rather than being driven negative.

        PRD 3.5: "A `NurseManager` may void a watch, but only one that has not yet begun:
        `SCHEDULED → VOIDED` is the sole void transition, and a watch that has already
        started can never be voided — an attempt from `ON_WATCH`, `ON_BREAK` or either
        terminal state is rejected with `ERR_INVALID_ASSIGNMENT_STATE`, as is a second
        attempt at any transition already taken."
        PRD 3.5: "The unit's `observed_cost_to_date_cents` is recomputed over the posted
        set, and by the conserved-quantity guarantee of §2.10 it returns to precisely the
        value it held before the watch was ever scheduled."

        Design: Corner/state_machines/second_void_on_an_already_voided_watch_is_rejected
        """
        world = scheduled_watch(
            api,
            unit_code="UNIT-C13",
            mrn="MRN-C1301",
            budget_cents=250000,
            risk_categories=[RISK_FALL],
            staff_name="Corner Sitter Thirteen",
        )
        validate_success(api.void_assignment(world["assignment"]["id"], MANAGER))

        validate_error(
            api.void_assignment(world["assignment"]["id"], MANAGER),
            ERR_INVALID_ASSIGNMENT_STATE,
            expected_status=HTTP_CONFLICT,
        )

        assignment = read_assignment(api, world["assignment"]["id"])
        assert_fields(
            assignment,
            label="assignment",
            watch_status=WATCH_VOIDED,
            voided_at=CLOCK_START,
            documentation_status=DOC_WAIVED,
        )
        rows = assignment_cost_entries(api, world["assignment"]["id"])
        assert_row_count(rows, 1, "assignment cost entries")
        assert_fields(
            rows[0],
            label="only ledger row",
            entry_kind=ENTRY_KIND_PROVISIONAL,
            amount_cents=16000,
            status=COST_REVERSED,
        )
        assert unit_head(api, world["unit"]["id"]) == 0


class TestTerminalFeedLockdown:
    """RELEASED is terminal on a video feed, so the console counters move once only."""

    def test_releasing_an_already_released_feed_is_refused_and_counters_stay_at_zero(
        self, api: ObservationApiClient
    ) -> None:
        """
        A second release of the same feed is refused, and the console's recomputed
        occupancy stays at zero feeds and zero acuity weight with the span ceiling back
        at the full declared figure rather than being decremented a second time.

        PRD 3.7: "Releasing a feed that is already `RELEASED` is rejected with
        `ERR_INVALID_FEED_STATE`."
        PRD 3.7: "The console recomputes `active_feed_count`, `active_acuity_weight` and
        `effective_span_limit`; when `active_feed_count` reaches 0 the console
        transitions `ACTIVE_MONITORING → IDLE`, with `active_acuity_weight` back at 0.0
        and `effective_span_limit` back at the full `declared_max_span`, and its observer
        moves `ON_ASSIGNMENT → AVAILABLE`."

        Design: Corner/state_machines/releasing_an_already_released_feed_is_rejected
        """
        world = console_with_active_feed(
            api,
            unit_code="UNIT-C14",
            mrn="MRN-C1401",
            budget_cents=250000,
            risk_categories=[RISK_ELOPEMENT],
            declared_max_span=2,
            station_label="CONSOLE-C14",
        )
        observer_headers = make_remote_observer_headers(world["observer"]["id"])
        validate_success(api.release_feed(world["feed"]["id"], observer_headers))

        validate_error(
            api.release_feed(world["feed"]["id"], observer_headers),
            ERR_INVALID_FEED_STATE,
            expected_status=HTTP_CONFLICT,
        )

        assert_fields(
            read_feed(api, world["feed"]["id"]),
            label="feed",
            status=FEED_RELEASED,
            release_reason=RELEASE_OBSERVER_RELEASE,
            released_at=CLOCK_START,
        )
        assert_fields(
            read_station(api, world["station"]["id"]),
            label="station",
            status=STATION_IDLE,
            active_feed_count=0,
            active_acuity_weight=0.0,
            effective_span_limit=2,
        )
        assert_fields(
            read_staff(api, world["observer"]["id"]),
            label="observer",
            status=STAFF_AVAILABLE,
        )


class TestKindGatedEventFork:
    """Which review branch a safety event may take is fixed by its kind."""

    def test_escalate_response_on_a_self_harm_event_is_refused_from_reported(
        self, api: ObservationApiClient
    ) -> None:
        """
        A SELF_HARM_ATTEMPT event sits in REPORTED, the very state the escalation-response
        branch demands, yet the branch is still refused because the precondition is on the
        event kind. Nothing is recorded on the event, and the order keeps both its status
        and its creation-time score, since neither of the two occasions that recompute the
        score has occurred.

        PRD 3.8: "Attempting this branch on a `FALL_WITH_INJURY` or `SELF_HARM_ATTEMPT`
        event, or from any status other than `REPORTED`, is rejected with
        `ERR_INVALID_EVENT_STATE`."
        PRD 3.8: "A `FALL_WITH_INJURY` or a `SELF_HARM_ATTEMPT` report leaves the order's
        `status` alone entirely; that event waits for the incident-review branch to act."
        PRD 3.2: "Finally, it is worth stating plainly where `elopement_risk_score` and
        `risk_score_variant` can change, because nothing else touches them: at order
        creation, at every reassessment, when an incident review is opened on one of the
        order's safety events, and when one of the order's safety events is closed."

        Design: Corner/state_machines/escalate_response_on_a_self_harm_event_is_rejected
        """
        world = unit_patient_order(
            api,
            unit_code="UNIT-C15",
            mrn="MRN-C1501",
            budget_cents=250000,
            risk_categories=[RISK_SELF_HARM],
        )
        sitter = make_staff(
            api,
            world["unit"]["id"],
            full_name="Corner Sitter Fifteen",
            competency_level=COMPETENCY_ADVANCED,
        )
        event = make_safety_event(
            api,
            world["order"]["id"],
            KIND_SELF_HARM_ATTEMPT,
            sitter["id"],
            narrative="Attempted to tie a gown cord around neck",
        )

        validate_error(
            api.escalate_response(
                event["id"],
                escalate_response_payload([INTERVENTION_VERBAL_REDIRECTION]),
                OFFICER_1,
            ),
            ERR_INVALID_EVENT_STATE,
            expected_status=HTTP_CONFLICT,
        )

        assert_fields(
            read_event(api, event["id"]),
            label="event",
            status=EVENT_REPORTED,
            response_actions=None,
            review_opened_by_user_id=None,
        )
        assert_fields(
            read_order(api, world["order"]["id"]),
            label="order",
            status=ORDER_ACTIVE,
            elopement_risk_score=3.0,
            risk_score_variant=VARIANT_ADMISSION_BASELINE,
        )


class TestAutomaticSweepTransitions:
    """The clock sweep is the only automatic transition source in the system."""

    def test_two_advances_are_needed_to_lapse_and_the_lapse_cascade_fires_in_full(
        self, api: ObservationApiClient
    ) -> None:
        """
        An ELOPEMENT-only order scores 2.5, falls to the 24-hour cadence and comes due at
        2026-08-02T00:00:00Z. The first advance can only mark it REASSESSMENT_DUE; the
        second, six hours past due, lapses it and runs the whole cascade in one call —
        the feed is released as ORDER_TERMINATED, the console recounts to IDLE, its
        observer is freed, and the patient's unit is restricted.

        PRD 3.3: "Because at most one transition applies per order per call, an `ACTIVE`
        order that is already many days overdue still needs two separate clock advances to
        reach `LAPSED`: one to become `REASSESSMENT_DUE` and a second to lapse."
        PRD 3.3: "The clock response reports the instant now in force as `current_utc`,
        together with `orders_marked_reassessment_due` and `orders_lapsed` as counts of
        what the sweep did."
        PRD 3.3: "First, every video feed on the lapsed order whose `status` is `ACTIVE`
        is released with `release_reason` set to `ORDER_TERMINATED`, processed in ascending
        `created_at`."
        PRD 3.3: "Alongside those hops, the unit occupied by the lapsed order's patient is
        driven to `RESTRICTED` with `restriction_reason` set to
        `OBSERVATION_ORDER_LAPSED`; a unit already `RESTRICTED` is left as it is, and this
        step is then a no-op."

        Design: Corner/state_machines/lapsed_order_sweep_releases_feeds_and_restricts_the_unit
        """
        world = console_with_active_feed(
            api,
            unit_code="UNIT-C16",
            mrn="MRN-C1601",
            budget_cents=250000,
            risk_categories=[RISK_ELOPEMENT],
            declared_max_span=2,
            station_label="CONSOLE-C16",
            monitor_start_at="2026-08-01T08:00:00Z",
            monitor_end_at="2026-08-02T08:00:00Z",
        )

        first = advance_clock(api, "2026-08-02T00:00:00Z")
        assert first["orders_marked_reassessment_due"] == 1, first
        assert first["orders_lapsed"] == 0, first
        assert_instant(first["current_utc"], "2026-08-02T00:00:00Z", "clock current_utc")
        assert_fields(
            read_order(api, world["order"]["id"]),
            label="order after the first advance",
            status=ORDER_REASSESSMENT_DUE,
            lapsed_at=None,
            next_reassessment_due_at="2026-08-02T00:00:00.000Z",
        )
        assert read_feed(api, world["feed"]["id"])["status"] == FEED_ACTIVE
        assert read_unit(api, world["unit"]["id"])["status"] == UNIT_OPEN

        second = advance_clock(api, "2026-08-02T07:00:00Z")
        assert second["orders_marked_reassessment_due"] == 0, second
        assert second["orders_lapsed"] == 1, second

        assert_fields(
            read_order(api, world["order"]["id"]),
            label="order after the second advance",
            status=ORDER_LAPSED,
            lapsed_at="2026-08-02T07:00:00.000Z",
        )
        assert_fields(
            read_feed(api, world["feed"]["id"]),
            label="feed",
            status=FEED_RELEASED,
            release_reason=RELEASE_ORDER_TERMINATED,
            released_at="2026-08-02T07:00:00.000Z",
        )
        assert_fields(
            read_station(api, world["station"]["id"]),
            label="station",
            status=STATION_IDLE,
            active_feed_count=0,
            active_acuity_weight=0.0,
            effective_span_limit=2,
        )
        assert read_staff(api, world["observer"]["id"])["status"] == STAFF_AVAILABLE
        assert_fields(
            read_unit(api, world["unit"]["id"]),
            label="unit",
            status=UNIT_RESTRICTED,
            restriction_reason=RESTRICTION_OBSERVATION_ORDER_LAPSED,
            observed_cost_to_date_cents=0,
        )


class TestSingleDooredSuspensionExit:
    """SUSPENDED is left by exactly one operation, and it clears both fields."""

    def test_recertification_reinstates_a_suspended_sitter_without_touching_the_watch(
        self, api: ObservationApiClient
    ) -> None:
        """
        Opening an incident review on a FALL_WITH_INJURY event that named the watch
        suspends the sitter keeping it. A fresh certification with an expiry strictly later
        than the clock is the single door out: it returns the observer to AVAILABLE and
        clears the suspension reason while writing both certification fields, and it moves
        neither the watch nor the event under review.

        PRD 3.1: "This operation carries a second, decisive effect: it is the **only** path
        out of `SUSPENDED`."
        PRD 3.1: "When the observer is `SUSPENDED` and the submitted
        `deescalation_cert_expires_on` is strictly later than the current logical clock,
        the observer returns to `AVAILABLE` and `suspension_reason` is cleared to null."
        PRD 3.8: "Finally, and strictly **after** all four cascade hops, if the event named
        an `assignment_id` then the observer who was keeping that watch transitions to
        `SUSPENDED` with `suspension_reason` `INCIDENT_REVIEW_OPENED`."

        Design: Corner/state_machines/recertification_is_the_only_exit_from_suspended
        """
        world = watch_in_progress(
            api,
            unit_code="UNIT-C17",
            mrn="MRN-C1701",
            budget_cents=250000,
            risk_categories=[RISK_FALL],
            competency_level=COMPETENCY_BASIC,
            staff_name="Corner Sitter Seventeen",
        )
        event = make_safety_event(
            api,
            world["order"]["id"],
            KIND_FALL_WITH_INJURY,
            world["staff"]["id"],
            narrative="Fall during transfer with wrist fracture",
            assignment_id=world["assignment"]["id"],
        )
        validate_success(api.open_incident_review(event["id"], OFFICER_1))
        assert_fields(
            read_staff(api, world["staff"]["id"]),
            label="sitter before recertification",
            status=STAFF_SUSPENDED,
            suspension_reason=SUSPENSION_INCIDENT_REVIEW_OPENED,
        )

        reinstated = validate_success(
            api.record_certification(
                world["staff"]["id"],
                certification_payload(COMPETENCY_ADVANCED, "2027-06-30T00:00:00Z"),
                COORDINATOR,
            )
        )

        assert_fields(
            reinstated,
            label="sitter after recertification",
            status=STAFF_AVAILABLE,
            suspension_reason=None,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on="2027-06-30T00:00:00.000Z",
        )
        assert (
            read_assignment(api, world["assignment"]["id"])["watch_status"]
            == WATCH_ON_WATCH
        )
        assert read_event(api, event["id"])["status"] == EVENT_INCIDENT_REVIEW


class TestCrossDimensionCompletionGuard:
    """The one place the documentation dimension guards the watch dimension."""

    def test_handoff_complete_is_refused_while_the_handoff_is_only_drafted(
        self, api: ObservationApiClient
    ) -> None:
        """
        A drafted but uncountersigned handoff leaves the outgoing watch in
        HANDOFF_DRAFTED, and closing it as HANDOFF_COMPLETE is refused at the single
        coupling point between the two dimensions. The watch stays open with no
        completion reason, the handoff record stays DRAFTED, no FINAL_SEGMENT is posted
        and neither PROVISIONAL row is reversed, so the ledger head still carries both
        scheduled watches.

        PRD 3.5: "Here is the single coupling point between the two dimensions: when the
        reason is `HANDOFF_COMPLETE` the assignment's `documentation_status` must already
        be `HANDOFF_SIGNED`, and if it is not the request is rejected with
        `ERR_HANDOFF_NOT_SIGNED`; when the reason is `SHIFT_END_NO_SUCCESSOR` no
        documentation state is required at all."
        PRD 3.6: "A successful draft creates a handoff record whose `documentation_state`
        is `DRAFTED`, with `countersigned_by_staff_id` and `countersigned_at` both null,
        and moves the outgoing assignment `PENDING → HANDOFF_DRAFTED` while leaving its
        `watch_status` completely untouched; the assignment's `version` advances by 1."

        Design: Corner/state_machines/complete_with_handoff_complete_requires_a_signed_handoff
        """
        world = watch_in_progress(
            api,
            unit_code="UNIT-C18",
            mrn="MRN-C1801",
            budget_cents=250000,
            risk_categories=[RISK_FALL],
            staff_name="Corner Outgoing Eighteen",
        )
        incoming_staff = make_staff(
            api, world["unit"]["id"], full_name="Corner Incoming Eighteen"
        )
        incoming = make_assignment(
            api,
            world["order"]["id"],
            incoming_staff["id"],
            "2026-08-01T16:00:00Z",
            "2026-08-02T00:00:00Z",
        )
        handoff = make_handoff(
            api,
            world["assignment"]["id"],
            incoming["id"],
            world["staff"]["id"],
            behavior_summary="Settled, no attempts to rise",
            interventions_used=[INTERVENTION_BED_ALARM],
        )

        validate_error(
            api.complete_watch(
                world["assignment"]["id"],
                completion_payload(COMPLETION_HANDOFF_COMPLETE),
                make_sitter_headers(world["staff"]["id"]),
            ),
            ERR_HANDOFF_NOT_SIGNED,
            expected_status=HTTP_UNPROCESSABLE,
        )

        assert_fields(
            read_assignment(api, world["assignment"]["id"]),
            label="outgoing watch",
            watch_status=WATCH_ON_WATCH,
            completion_reason=None,
            documentation_status=DOC_HANDOFF_DRAFTED,
            final_cost_cents=None,
        )
        assert_fields(
            read_handoff(api, handoff["id"]),
            label="handoff record",
            documentation_state=HANDOFF_DRAFTED,
            countersigned_by_staff_id=None,
            countersigned_at=None,
        )
        rows = assignment_cost_entries(api, world["assignment"]["id"])
        assert_row_count(rows, 1, "outgoing assignment cost entries")
        assert_fields(
            rows[0],
            label="only ledger row",
            entry_kind=ENTRY_KIND_PROVISIONAL,
            amount_cents=16000,
            status=COST_POSTED,
            reversed_at=None,
        )
        assert unit_head(api, world["unit"]["id"]) == 32000
        assert read_staff(api, world["staff"]["id"])["status"] == STAFF_ON_ASSIGNMENT
