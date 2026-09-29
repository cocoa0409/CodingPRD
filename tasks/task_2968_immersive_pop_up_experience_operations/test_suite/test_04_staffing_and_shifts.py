"""Rostering the cast: two readiness variants, the clearing gate and shift geometry."""

from test_helpers import (
    UNKNOWN_UUID_ALT,
    ApiErrorId,
    api_client,
    assert_row_inert,
    assert_shift,
    assert_staff_member,
    assert_total_count,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_object,
    validate_paginated,
    validate_success,
)

PRODUCER = fx.PRODUCER
OFFICER = fx.OFFICER


class TestTwoReadinessVariants:
    """The optimistic roster figure and the figure the gate actually reads."""

    def test_the_roster_view_looks_clear_while_the_gate_refuses(self):
        """One row carries 87.80 and 75.30 at once, and only the lower one counts.

        PRD: "`readiness_score_audit` counts `completed_rehearsal_count` only.
        Whenever `scheduled_rehearsal_count` is above zero the audit figure is
        strictly the lower of the two".
        PRD: "`CLEAR` moves a person `TRAINING → CLEARED` and is doubly gated:
        `readiness_score_audit` must be at least 78.00, or the decision is
        refused with `ERR_STAFF_READINESS_BELOW_MIN`".

        Design: Difficulty/dual_variant_calc/readiness_preflight_clears_while_audit_refuses
        """
        run = fx.planned_run()
        member = fx.enrol_staff(
            run["id"], "PERFORMER", full_name="Ada Perez", incident_count=1
        )
        assert member["status"] == "CANDIDATE"
        assert member["readiness_score_preflight"] == 0.00
        assert member["readiness_score_audit"] == 0.00

        trained = validate_success(
            api_client.add_training_record(
                member["id"],
                f.training_record_payload(
                    training_score=82, completed_rehearsal_count=2,
                    scheduled_rehearsal_count=2, incident_delta=0,
                ),
                PRODUCER,
            )
        )
        assert_staff_member(trained)
        assert trained["status"] == "TRAINING"
        assert trained["cert_coverage_pct"] == 100.00
        # 0.40*82 + 0.35*100.00 + 0.25*100.00 - 5.00 for the single incident.
        assert trained["readiness_score_preflight"] == 87.80
        # The same sum with the two booked rehearsals uncounted: 0.25*50.00.
        assert trained["readiness_score_audit"] == 75.30

        validate_error(
            api_client.decide_staff_status(
                member["id"],
                f.staff_status_decision_payload(
                    "CLEAR", note="roster view looked clear"
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_STAFF_READINESS_BELOW_MIN.value,
            409,
        )
        after = fx.read_staff_member(member["id"])
        assert after["status"] == "TRAINING"
        assert after["version"] == trained["version"]
        assert fx.read_run(run["id"])["clearance_status"] == "UNCLEARED"

    def test_working_the_booked_rehearsals_makes_the_two_figures_agree(self):
        """Once the rehearsals are worked the audit figure catches up and clears.

        PRD: "the two rehearsal counters accumulate by addition, adding the
        submitted figures to the running totals".
        PRD: "a person can therefore look clearable on the roster view while the
        gate still refuses".

        Design: Difficulty/dual_variant_calc/readiness_preflight_clears_while_audit_refuses
        """
        run = fx.planned_run()
        member = fx.enrol_staff(
            run["id"], "PERFORMER", full_name="Ada Perez", incident_count=1
        )
        validate_success(
            api_client.add_training_record(
                member["id"],
                f.training_record_payload(
                    training_score=82, completed_rehearsal_count=2,
                    scheduled_rehearsal_count=2, incident_delta=0,
                ),
                PRODUCER,
            )
        )
        worked = validate_success(
            api_client.add_training_record(
                member["id"],
                f.training_record_payload(
                    training_score=82, completed_rehearsal_count=2,
                    scheduled_rehearsal_count=0, incident_delta=0,
                ),
                PRODUCER,
            )
        )
        assert worked["status"] == "TRAINING"
        assert worked["training_score"] == 82
        assert worked["completed_rehearsal_count"] == 4
        assert worked["scheduled_rehearsal_count"] == 2
        # Counted 4 for the audit variant and 6 for the preflight one, whose
        # 150.00 is capped at 100.00, so both variants now report the same score.
        assert worked["readiness_score_audit"] == 87.80
        assert worked["readiness_score_preflight"] == 87.80

        cleared = validate_success(
            api_client.decide_staff_status(
                member["id"],
                f.staff_status_decision_payload("CLEAR", note="rehearsals worked"),
                PRODUCER,
            )
        )
        assert cleared["status"] == "CLEARED"
        assert fx.read_run(run["id"])["clearance_status"] == "UNCLEARED"


class TestShiftBufferAndLengthEdges:
    """Two one-minute edges that sit on opposite sides of the inclusive divide."""

    def test_a_gap_of_exactly_thirty_minutes_collides_and_thirty_one_does_not(self):
        """The buffered endpoint is inclusive, so 14:30 is still occupied.

        PRD: "Each of that same person's existing `SCHEDULED` shifts is widened
        by a rest buffer of 30 minutes at both ends, and the widened interval is
        also closed at both ends."
        PRD: "Touching endpoints collide, and a gap of exactly 30 minutes still
        collides because the buffered endpoint is inclusive; the first admissible
        gap is 31 minutes."

        Design: Difficulty/boundary_precision_check/shift_rest_buffer_and_length_edges_at_thirty_and_six_hundred_minutes
        """
        bundle = fx.run_with_room(lease_active=True)
        run_id = bundle["run"]["id"]
        room_id = bundle["room"]["id"]
        member = fx.cleared_staff(run_id, "PERFORMER", full_name="Ada Perez")
        assert member["readiness_score_audit"] == 96.00

        first = fx.book_shift(
            member["id"], themed_room_id=room_id,
            shift_start_utc="2026-09-05T10:00:00Z",
            shift_end_utc="2026-09-05T14:00:00Z",
        )
        assert first["status"] == "SCHEDULED"

        validate_error(
            api_client.create_shift(
                f.shift_payload(
                    member["id"], "2026-09-05T14:30:00Z", "2026-09-05T16:00:00Z",
                    themed_room_id=room_id,
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_SHIFT_OVERLAP.value,
            409,
        )
        admitted = validate_object(
            api_client.create_shift(
                f.shift_payload(
                    member["id"], "2026-09-05T14:31:00Z", "2026-09-05T16:00:00Z",
                    themed_room_id=room_id,
                ),
                PRODUCER,
            ),
            201,
        )
        assert_shift(admitted)
        assert admitted["status"] == "SCHEDULED"
        assert admitted["run_id"] == run_id
        assert admitted["version"] == 1

        assert_row_inert(first, fx.read_shift(first["id"]))
        assert_total_count(
            api_client.list_shifts(PRODUCER, {"staff_member_id": member["id"]}), 2
        )

    def test_exactly_six_hundred_minutes_fits_and_six_hundred_and_one_does_not(self):
        """The length rung is only reached once the collision sweep has passed.

        PRD: "Only after the collision sweep passes is the length checked: a
        shift longer than 600 minutes is refused with `ERR_SHIFT_TOO_LONG`."

        Design: Difficulty/boundary_precision_check/shift_rest_buffer_and_length_edges_at_thirty_and_six_hundred_minutes
        """
        bundle = fx.run_with_room(lease_active=True)
        member = fx.cleared_staff(
            bundle["run"]["id"], "PERFORMER", full_name="Ada Perez"
        )
        first = fx.book_shift(
            member["id"], themed_room_id=bundle["room"]["id"],
            shift_start_utc="2026-09-05T10:00:00Z",
            shift_end_utc="2026-09-05T14:00:00Z",
        )

        exact = validate_object(
            api_client.create_shift(
                f.shift_payload(
                    member["id"], "2026-09-07T00:00:00Z", "2026-09-07T10:00:00Z",
                    station="BOOTH",
                ),
                PRODUCER,
            ),
            201,
        )
        assert exact["status"] == "SCHEDULED"
        assert exact["station"] == "BOOTH"

        validate_error(
            api_client.create_shift(
                f.shift_payload(
                    member["id"], "2026-09-08T00:00:00Z", "2026-09-08T10:01:00Z",
                    station="BOOTH",
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_SHIFT_TOO_LONG.value,
            409,
        )
        rows, meta = validate_paginated(
            api_client.list_shifts(PRODUCER, {"staff_member_id": member["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], exact["id"]}
        assert_row_inert(first, fx.read_shift(first["id"]))


class TestClearanceStateGovernsScheduling:
    """The shift reads the person's state, and the person's state rewrites shifts."""

    def test_only_a_cleared_person_may_be_booked(self):
        """Candidate refuses, training still refuses, clearance admits.

        PRD: "Only a `CLEARED` staff member may be scheduled — anyone else earns
        `ERR_STAFF_NOT_CLEARED` — and the shift's `run_id` is copied from that
        person's own `run_id` rather than supplied by the client."

        Design: Difficulty/cross_entity_state_dependency/shift_scheduling_blocked_by_the_members_clearance_state
        """
        bundle = fx.run_with_room(lease_active=True)
        run_id = bundle["run"]["id"]
        room_id = bundle["room"]["id"]
        member = fx.enrol_staff(run_id, "PERFORMER", full_name="Ada Perez")
        assert member["status"] == "CANDIDATE"

        window = dict(
            shift_start_utc="2026-09-05T10:00:00Z",
            shift_end_utc="2026-09-05T14:00:00Z",
            themed_room_id=room_id,
        )
        booking = lambda: api_client.create_shift(
            f.shift_payload(member["id"], **window), PRODUCER
        )
        validate_error(
            booking(), ApiErrorId.ERR_STAFF_NOT_CLEARED.value, 409
        )

        trained = validate_success(
            api_client.add_training_record(
                member["id"],
                f.training_record_payload(
                    training_score=90, completed_rehearsal_count=4,
                    scheduled_rehearsal_count=0, incident_delta=0,
                ),
                PRODUCER,
            )
        )
        assert trained["status"] == "TRAINING"
        assert trained["readiness_score_preflight"] == 96.00
        assert trained["readiness_score_audit"] == 96.00
        validate_error(
            booking(), ApiErrorId.ERR_STAFF_NOT_CLEARED.value, 409
        )
        assert_total_count(
            api_client.list_shifts(PRODUCER, {"staff_member_id": member["id"]}), 0
        )

        cleared = validate_success(
            api_client.decide_staff_status(
                member["id"],
                f.staff_status_decision_payload("CLEAR", note="readiness 96.00"),
                PRODUCER,
            )
        )
        assert cleared["status"] == "CLEARED"
        shift = validate_object(booking(), 201)
        assert shift["status"] == "SCHEDULED"
        assert shift["run_id"] == run_id

    def test_suspension_cancels_the_booking_and_reinstatement_frees_the_window(self):
        """The parent's transition rewrites the child, and the freed window reopens.

        PRD: "`SUSPEND` moves a cleared person `CLEARED → SUSPENDED`, cancels
        every one of that person's `SCHEDULED` shifts — each cancelled shift
        taking its own version increment".
        PRD: "`CANCELLED` and `COMPLETED` shifts never collide with anything."

        Design: Difficulty/cross_entity_state_dependency/shift_scheduling_blocked_by_the_members_clearance_state
        """
        bundle = fx.run_with_room(lease_active=True)
        run_id = bundle["run"]["id"]
        room_id = bundle["room"]["id"]
        member = fx.cleared_staff(run_id, "PERFORMER", full_name="Ada Perez")
        window = dict(
            shift_start_utc="2026-09-05T10:00:00Z",
            shift_end_utc="2026-09-05T14:00:00Z",
            themed_room_id=room_id,
        )
        first = fx.book_shift(member["id"], **window)
        assert first["status"] == "SCHEDULED"

        suspended = validate_success(
            api_client.decide_staff_status(
                member["id"],
                f.staff_status_decision_payload(
                    "SUSPEND", note="scripted-interaction complaint"
                ),
                OFFICER,
            )
        )
        assert suspended["status"] == "SUSPENDED"
        cancelled = fx.read_shift(first["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["version"] == first["version"] + 1

        validate_error(
            api_client.create_shift(
                f.shift_payload(member["id"], **window), PRODUCER
            ),
            ApiErrorId.ERR_STAFF_NOT_CLEARED.value,
            409,
        )

        reinstated = validate_success(
            api_client.decide_staff_status(
                member["id"],
                f.staff_status_decision_payload(
                    "REINSTATE", note="complaint withdrawn"
                ),
                OFFICER,
            )
        )
        assert reinstated["status"] == "CLEARED"
        # The cancelled shift no longer occupies the rest buffer, so the very
        # same window is admissible a second time.
        again = validate_object(
            api_client.create_shift(
                f.shift_payload(member["id"], **window), PRODUCER
            ),
            201,
        )
        assert again["status"] == "SCHEDULED"

        rows, meta = validate_paginated(
            api_client.list_shifts(PRODUCER, {"staff_member_id": member["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["status"] for row in rows} == {"CANCELLED", "SCHEDULED"}


class TestPersonIsTheContendedResource:
    """Four overlap shapes on one person, and a room that contends with nothing."""

    def test_containment_and_touching_shapes_all_collide(self):
        """Contained, containing and touching windows are each refused.

        PRD: "If the new interval touches or overlaps any widened interval — that
        is, if the new start is at or before the widened end while the widened
        start is at or before the new end — the request is refused with
        `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/staff_member_closed_interval_occupation_across_overlap_shapes
        """
        bundle = fx.run_with_room(lease_active=True)
        run_id = bundle["run"]["id"]
        room_id = bundle["room"]["id"]
        member_a = fx.cleared_staff(run_id, "PERFORMER", full_name="Ada Perez")
        member_b = fx.cleared_staff(run_id, "PERFORMER", full_name="Dario Sen")
        base = fx.book_shift(
            member_a["id"], themed_room_id=room_id,
            shift_start_utc="2026-09-05T10:00:00Z",
            shift_end_utc="2026-09-05T14:00:00Z",
        )

        shapes = [
            ("2026-09-05T11:00:00Z", "2026-09-05T12:00:00Z"),
            ("2026-09-05T09:00:00Z", "2026-09-05T15:00:00Z"),
            ("2026-09-05T14:00:00Z", "2026-09-05T15:00:00Z"),
        ]
        for start, end in shapes:
            validate_error(
                api_client.create_shift(
                    f.shift_payload(
                        member_a["id"], start, end, themed_room_id=room_id
                    ),
                    PRODUCER,
                ),
                ApiErrorId.ERR_SHIFT_OVERLAP.value,
                409,
            )

        # The occupied resource is the person, not the room they stand in.
        twin = validate_object(
            api_client.create_shift(
                f.shift_payload(
                    member_b["id"], "2026-09-05T10:00:00Z", "2026-09-05T14:00:00Z",
                    themed_room_id=room_id,
                ),
                PRODUCER,
            ),
            201,
        )
        assert twin["status"] == "SCHEDULED"
        assert twin["themed_room_id"] == room_id
        assert_row_inert(base, fx.read_shift(base["id"]))
        assert_total_count(
            api_client.list_shifts(PRODUCER, {"themed_room_id": room_id}), 2
        )

    def test_cancelling_the_shift_frees_the_contained_window(self):
        """A cancelled shift drops out of the occupation scan altogether.

        PRD: "Existing shifts are examined in ascending `created_at` order and
        the first collision found decides the rejection."
        PRD: "`CANCEL` moves `SCHEDULED → CANCELLED`. Both are terminal, and a
        shift may also be cancelled as a side effect of its own staff member
        being suspended or released."

        Design: Difficulty/resource_temporal_overlap/staff_member_closed_interval_occupation_across_overlap_shapes
        """
        bundle = fx.run_with_room(lease_active=True)
        run_id = bundle["run"]["id"]
        room_id = bundle["room"]["id"]
        member_a = fx.cleared_staff(run_id, "PERFORMER", full_name="Ada Perez")
        member_b = fx.cleared_staff(run_id, "PERFORMER", full_name="Dario Sen")
        base = fx.book_shift(
            member_a["id"], themed_room_id=room_id,
            shift_start_utc="2026-09-05T10:00:00Z",
            shift_end_utc="2026-09-05T14:00:00Z",
        )
        twin = fx.book_shift(
            member_b["id"], themed_room_id=room_id,
            shift_start_utc="2026-09-05T10:00:00Z",
            shift_end_utc="2026-09-05T14:00:00Z",
        )
        contained = f.shift_payload(
            member_a["id"], "2026-09-05T11:00:00Z", "2026-09-05T12:00:00Z",
            themed_room_id=room_id,
        )
        validate_error(
            api_client.create_shift(contained, PRODUCER),
            ApiErrorId.ERR_SHIFT_OVERLAP.value,
            409,
        )

        cancelled = validate_success(
            api_client.decide_shift_status(
                base["id"],
                f.shift_status_decision_payload("CANCEL", note="reassigned"),
                PRODUCER,
            )
        )
        assert cancelled["status"] == "CANCELLED"

        # Member B's overlapping SCHEDULED shift is irrelevant to member A.
        freed = validate_object(api_client.create_shift(contained, PRODUCER), 201)
        assert freed["status"] == "SCHEDULED"
        rows, meta = validate_paginated(api_client.list_shifts(PRODUCER))
        assert meta["total_count"] == 3
        by_id = {row["id"]: row["status"] for row in rows}
        assert by_id[base["id"]] == "CANCELLED"
        assert by_id[twin["id"]] == "SCHEDULED"
        assert by_id[freed["id"]] == "SCHEDULED"


class TestStaffMemberMachineWalk:
    """The whole happy path including the self-loop and the way back."""

    def test_the_member_walks_candidate_training_cleared_suspended_and_back(self):
        """Six accepted transitions, one refused, and the gate re-checked on the way back.

        PRD: "Every record recomputes `cert_coverage_pct` and both readiness
        variants, and moves the person `CANDIDATE → TRAINING`, or
        `TRAINING → TRAINING` on each further block."
        PRD: "`REINSTATE` moves `SUSPENDED → CLEARED` under exactly the same two
        readiness gates as `CLEAR`, which is why incidents charged during a
        suspension can keep the gate shut".
        PRD: "`RELEASE` moves a person to the terminal `RELEASED` from any of
        `CANDIDATE`, `TRAINING`, `CLEARED` or `SUSPENDED`".

        Design: Corner/state_machines/staff_member_walks_candidate_training_cleared_suspended_and_back
        """
        run = fx.planned_run()
        member = fx.enrol_staff(run["id"], "AMBASSADOR", full_name="Dara Vance")

        optimistic = validate_success(
            api_client.add_training_record(
                member["id"],
                f.training_record_payload(
                    training_score=90, completed_rehearsal_count=1,
                    scheduled_rehearsal_count=3,
                ),
                PRODUCER,
            )
        )
        assert optimistic["status"] == "TRAINING"
        assert optimistic["cert_coverage_pct"] == 100.00
        assert optimistic["readiness_score_preflight"] == 96.00
        # 0.40*90 + 0.35*100.00 + 0.25*25.00, three quarters of a point short.
        assert optimistic["readiness_score_audit"] == 77.25

        validate_error(
            api_client.decide_staff_status(
                member["id"], f.staff_status_decision_payload("CLEAR"), PRODUCER
            ),
            ApiErrorId.ERR_STAFF_READINESS_BELOW_MIN.value,
            409,
        )

        worked = validate_success(
            api_client.add_training_record(
                member["id"],
                f.training_record_payload(
                    training_score=90, completed_rehearsal_count=4,
                    scheduled_rehearsal_count=0,
                ),
                PRODUCER,
            )
        )
        assert worked["status"] == "TRAINING"
        assert worked["readiness_score_audit"] == 96.00
        assert worked["readiness_score_preflight"] == 96.00

        for decision, expected, headers in (
            ("CLEAR", "CLEARED", PRODUCER),
            ("SUSPEND", "SUSPENDED", OFFICER),
            ("REINSTATE", "CLEARED", OFFICER),
            ("RELEASE", "RELEASED", PRODUCER),
        ):
            landed = validate_success(
                api_client.decide_staff_status(
                    member["id"],
                    f.staff_status_decision_payload(decision),
                    headers,
                )
            )
            assert landed["status"] == expected

        final = fx.read_staff_member(member["id"])
        assert final["status"] == "RELEASED"
        # One for the create plus one for each of the six accepted calls; the
        # refused clearance added none.
        assert final["version"] == 7
        assert fx.read_run(run["id"])["clearance_status"] == "UNCLEARED"


class TestSuspensionFanOut:
    """The cascade is filtered to the shifts that are still live, and one level deep."""

    def test_only_the_scheduled_shift_is_cancelled(self):
        """A completed shift keeps its symbol and a cancelled one is not re-versioned.

        PRD: "`SUSPEND` moves a cleared person `CLEARED → SUSPENDED`, cancels
        every one of that person's `SCHEDULED` shifts — each cancelled shift
        taking its own version increment".
        PRD: "`COMPLETE` moves `SCHEDULED → COMPLETED` and is admissible only
        once the logical clock has reached `shift_end_utc`; an earlier attempt is
        refused with `ERR_SHIFT_NOT_ENDED`."

        Design: Corner/state_machines/suspending_a_member_cancels_every_shift_it_still_holds
        """
        bundle = fx.run_with_room(lease_active=True)
        run_id = bundle["run"]["id"]
        room = bundle["room"]
        member = fx.cleared_staff(run_id, "PERFORMER", full_name="Ada Perez")

        done = fx.book_shift(
            member["id"], themed_room_id=room["id"],
            shift_start_utc="2026-09-05T09:00:00Z",
            shift_end_utc="2026-09-05T13:00:00Z",
        )
        by_hand = fx.book_shift(
            member["id"], themed_room_id=room["id"],
            shift_start_utc="2026-09-06T09:00:00Z",
            shift_end_utc="2026-09-06T13:00:00Z",
        )
        live = fx.book_shift(
            member["id"], themed_room_id=room["id"],
            shift_start_utc="2026-09-07T09:00:00Z",
            shift_end_utc="2026-09-07T13:00:00Z",
        )

        validate_error(
            api_client.decide_shift_status(
                done["id"], f.shift_status_decision_payload("COMPLETE"), PRODUCER
            ),
            ApiErrorId.ERR_SHIFT_NOT_ENDED.value,
            409,
        )
        fx.set_clock("2026-09-05T13:00:00Z")
        completed = validate_success(
            api_client.decide_shift_status(
                done["id"], f.shift_status_decision_payload("COMPLETE"), PRODUCER
            )
        )
        assert completed["status"] == "COMPLETED"
        assert completed["version"] == 2
        cancelled_by_hand = validate_success(
            api_client.decide_shift_status(
                by_hand["id"],
                f.shift_status_decision_payload(
                    "CANCEL", note="double-booked with a rehearsal"
                ),
                PRODUCER,
            )
        )
        assert cancelled_by_hand["status"] == "CANCELLED"
        assert cancelled_by_hand["version"] == 2

        run_before = fx.read_run(run_id)
        suspended = validate_success(
            api_client.decide_staff_status(
                member["id"],
                f.staff_status_decision_payload(
                    "SUSPEND", note="sensory de-escalation certificate withdrawn"
                ),
                OFFICER,
            )
        )
        assert suspended["status"] == "SUSPENDED"

        swept = fx.read_shift(live["id"])
        assert swept["status"] == "CANCELLED"
        assert swept["version"] == 2
        assert_row_inert(completed, fx.read_shift(done["id"]))
        assert_row_inert(cancelled_by_hand, fx.read_shift(by_hand["id"]))

        assert_total_count(
            api_client.list_shifts(
                PRODUCER,
                {"staff_member_id": member["id"], "status": "CANCELLED"},
            ),
            2,
        )
        # The fan-out is exactly one level deep and never reaches the room.
        assert_row_inert(room, validate_object(api_client.get_room(room["id"], PRODUCER)))
        run_after = fx.read_run(run_id)
        assert run_after["clearance_status"] == "UNCLEARED"
        assert run_after["version"] == run_before["version"]


class TestReadinessWeights:
    """Three weighted terms, one penalty, one interior cap and one final clamp."""

    def test_partial_coverage_rounds_once_and_the_third_certificate_lifts_it(self):
        """Two of three certificates is 66.67, and the sum is rounded exactly once.

        PRD: "`cert_coverage_pct` is 100 multiplied by the number of required
        certifications the person holds, divided by the number required for that
        craft, rounded half up to two decimals — certifications outside the
        craft's required set add nothing."
        PRD: "The raw score is 0.40 times `training_score`, plus 0.35 times
        `cert_coverage_pct`, plus 0.25 times the rehearsal percentage, minus 5.00
        for each recorded incident."

        Design: Corner/calculations/readiness_weights_partial_cert_coverage_and_the_zero_clamp
        """
        run = fx.planned_run()
        partial = validate_object(
            api_client.create_staff_member(
                f.staff_member_payload(
                    run["id"], "AMBASSADOR", full_name="Dara Vance",
                    certifications=["SCRIPTED_INTERACTION", "ADA_ASSIST"],
                ),
                PRODUCER,
            ),
            201,
        )
        assert partial["cert_coverage_pct"] == 0.00
        assert partial["readiness_score_preflight"] == 0.00
        assert partial["readiness_score_audit"] == 0.00

        scored = validate_success(
            api_client.add_training_record(
                partial["id"],
                f.training_record_payload(
                    training_score=82, completed_rehearsal_count=3,
                    scheduled_rehearsal_count=2, incident_delta=1,
                ),
                PRODUCER,
            )
        )
        assert scored["cert_coverage_pct"] == 66.67
        # 32.8 + 23.3345 + 18.75 - 5 = 69.8845 rounded once, not 69.89.
        assert scored["readiness_score_audit"] == 69.88
        # The preflight rehearsal term is 125.00 capped to 100.00: 32.8 + 23.3345
        # + 25 - 5 = 76.1345.
        assert scored["readiness_score_preflight"] == 76.13
        validate_error(
            api_client.decide_staff_status(
                partial["id"], f.staff_status_decision_payload("CLEAR"), PRODUCER
            ),
            ApiErrorId.ERR_STAFF_READINESS_BELOW_MIN.value,
            409,
        )

        full = fx.enrol_staff(run["id"], "AMBASSADOR", full_name="Lior Achebe")
        lifted = validate_success(
            api_client.add_training_record(
                full["id"],
                f.training_record_payload(
                    training_score=82, completed_rehearsal_count=4,
                    incident_delta=1,
                ),
                PRODUCER,
            )
        )
        assert lifted["cert_coverage_pct"] == 100.00
        assert lifted["readiness_score_audit"] == 87.80
        cleared = validate_success(
            api_client.decide_staff_status(
                full["id"], f.staff_status_decision_payload("CLEAR"), PRODUCER
            )
        )
        assert cleared["status"] == "CLEARED"

    def test_a_negative_raw_score_clamps_to_zero(self):
        """Five incidents and nothing else must not store a negative readiness.

        PRD: "rounding each term first is forbidden — and the result is clamped
        into 0.00 to 100.00."
        PRD: "an optional opening `incident_count` from 0 to 20, which is 0 when
        omitted."

        Design: Corner/calculations/readiness_weights_partial_cert_coverage_and_the_zero_clamp
        """
        run = fx.planned_run()
        bare = validate_object(
            api_client.create_staff_member(
                f.staff_member_payload(
                    run["id"], "TECHNICIAN", full_name="Ola Brandt",
                    certifications=[], incident_count=5,
                ),
                PRODUCER,
            ),
            201,
        )
        assert bare["incident_count"] == 5
        assert bare["readiness_score_preflight"] == 0.00
        assert bare["readiness_score_audit"] == 0.00

        scored = validate_success(
            api_client.add_training_record(
                bare["id"],
                f.training_record_payload(
                    training_score=0, completed_rehearsal_count=0
                ),
                PRODUCER,
            )
        )
        assert scored["status"] == "TRAINING"
        assert scored["cert_coverage_pct"] == 0.00
        # The raw score is -25.00, which the clamp lifts to the field floor.
        assert scored["readiness_score_audit"] == 0.00
        assert scored["readiness_score_preflight"] == 0.00


class TestShiftRoomLinkScope:
    """The only scoped optional link in the API, and its reverse channel."""

    def test_a_room_of_another_run_is_reported_as_no_room_at_all(self):
        """Out of scope is indistinguishable from non-existent, and both are 404.

        PRD: "A `themed_room_id` naming a room that belongs to a different run is
        treated exactly like an identifier that names nothing at all and is
        refused with `ERR_ROOM_NOT_FOUND`."
        PRD: "Staff shifts filter on `staff_member_id`, `run_id`,
        `themed_room_id` and `status`."

        Design: Corner/endpoints/shift_room_link_resolves_only_within_the_shifts_own_run
        """
        bundle = fx.run_with_room()
        run_a = bundle["run"]["id"]
        room_a = bundle["room"]["id"]
        kit_b = fx.create_kit(module_count=18)
        run_b = validate_object(
            api_client.create_run(
                f.run_payload(
                    bundle["venue"]["id"], bundle["agreement"]["id"], kit_b["id"],
                    run_name="Neon Atrium NYC stage two",
                ),
                PRODUCER,
            ),
            201,
        )
        room_b = fx.add_room(run_b["id"], 1, name="Vestibule B")
        member = fx.cleared_staff(run_a, "PERFORMER", full_name="Ines Duarte")

        for room_id in (room_b["id"], UNKNOWN_UUID_ALT):
            validate_error(
                api_client.create_shift(
                    f.shift_payload(
                        member["id"], "2026-08-12T10:00:00Z", "2026-08-12T14:00:00Z",
                        themed_room_id=room_id,
                    ),
                    PRODUCER,
                ),
                ApiErrorId.ERR_ROOM_NOT_FOUND.value,
                404,
            )
        assert_total_count(
            api_client.list_shifts(PRODUCER, {"staff_member_id": member["id"]}), 0
        )

        linked = validate_object(
            api_client.create_shift(
                f.shift_payload(
                    member["id"], "2026-08-12T10:00:00Z", "2026-08-12T14:00:00Z",
                    themed_room_id=room_a,
                ),
                PRODUCER,
            ),
            201,
        )
        assert linked["themed_room_id"] == room_a
        assert linked["run_id"] == run_a
        assert linked["status"] == "SCHEDULED"
        assert linked["version"] == 1

        unlinked = validate_object(
            api_client.create_shift(
                f.shift_payload(
                    member["id"], "2026-08-13T10:00:00Z", "2026-08-13T12:00:00Z",
                    station="ENTRY",
                ),
                PRODUCER,
            ),
            201,
        )
        assert unlinked["themed_room_id"] is None
        assert unlinked["station"] == "ENTRY"

        rows, meta = validate_paginated(
            api_client.list_shifts(PRODUCER, {"themed_room_id": room_a})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == linked["id"]
        assert_total_count(
            api_client.list_shifts(OFFICER, {"themed_room_id": room_b["id"]}), 0
        )
        assert_total_count(api_client.list_shifts(PRODUCER, {"run_id": run_a}), 2)
        assert_total_count(
            api_client.list_shifts(PRODUCER, {"run_id": run_b["id"]}), 0
        )
        assert_total_count(
            api_client.list_shifts(
                PRODUCER,
                {
                    "staff_member_id": member["id"],
                    "themed_room_id": room_a,
                    "status": "SCHEDULED",
                },
            ),
            1,
        )
        stored = validate_object(api_client.get_shift(unlinked["id"], PRODUCER))
        assert stored["run_id"] == run_a
        assert stored["themed_room_id"] is None


class TestContradictoryInputErrors:
    """Two identifiers that exist only because a second field contradicts the first."""

    def test_the_incident_cap_and_the_severity_mismatch_are_both_reachable(self):
        """A passing score still fails the incident cap, and NONE with findings is refused.

        PRD: "and `incident_count` must be no more than 2, or it is refused with
        `ERR_STAFF_INCIDENTS_ABOVE_MAX`."
        PRD: "A finalisation declaring `severity` of `NONE` while reporting a
        `findings_count` above 0 is contradictory and is refused with
        `ERR_SEVERITY_FINDINGS_MISMATCH`".

        Design: Corner/errors/staff_and_inspection_input_errors_are_each_reachable
        """
        bundle = fx.run_bundle()
        run_id = bundle["run"]["id"]
        member = fx.enrol_staff(
            run_id, "PERFORMER", full_name="Rafe Villanueva", incident_count=3
        )
        validate_success(
            api_client.add_training_record(
                member["id"],
                f.training_record_payload(
                    training_score=90, completed_rehearsal_count=4
                ),
                PRODUCER,
            )
        )
        inspection = fx.scheduled_inspection(run_id)

        loaded = validate_object(api_client.get_staff_member(member["id"], PRODUCER))
        assert loaded["status"] == "TRAINING"
        assert loaded["incident_count"] == 3
        assert loaded["cert_coverage_pct"] == 100.00
        # 36.00 + 35.00 + 25.00 - 15.00, comfortably past the 78.00 floor.
        assert loaded["readiness_score_audit"] == 81.00
        assert loaded["readiness_score_preflight"] == 81.00

        validate_error(
            api_client.decide_staff_status(
                member["id"],
                f.staff_status_decision_payload("CLEAR", note="rehearsals complete"),
                PRODUCER,
            ),
            ApiErrorId.ERR_STAFF_INCIDENTS_ABOVE_MAX.value,
            409,
        )
        assert_row_inert(loaded, fx.read_staff_member(member["id"]))

        validate_error(
            api_client.finalize_inspection(
                inspection["id"],
                f.inspection_finalize_payload(findings_count=2, severity="NONE"),
                OFFICER,
            ),
            ApiErrorId.ERR_SEVERITY_FINDINGS_MISMATCH.value,
            409,
        )
        untouched = fx.read_inspection(inspection["id"])
        assert untouched["status"] == "SCHEDULED"
        assert untouched["outcome"] is None
        assert untouched["measured_egress_width_cm"] == 0
        assert untouched["severity"] == "NONE"
        assert fx.read_run(run_id)["clearance_status"] == "UNCLEARED"

        passed = validate_success(
            api_client.finalize_inspection(
                inspection["id"],
                f.inspection_finalize_payload(findings_count=0, severity="NONE"),
                OFFICER,
            )
        )
        assert passed["outcome"] == "PASS"
        stored = fx.read_inspection(inspection["id"])
        assert stored["status"] == "FINALIZED"
        assert stored["findings_count"] == 0
        assert stored["severity"] == "NONE"
        assert stored["allowed_occupancy_cap"] == 197
