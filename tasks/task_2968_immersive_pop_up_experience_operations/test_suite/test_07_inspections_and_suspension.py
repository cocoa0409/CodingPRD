"""The safety verdict: one derived outcome, three disjoint cascades and the lift."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_inspection,
    assert_instant_equals,
    assert_order,
    assert_row_inert,
    assert_run,
    assert_slot,
    assert_slot_ledger,
    assert_staff_member,
    assert_total_count,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_object,
    validate_success,
)

PRODUCER = fx.PRODUCER
OFFICER = fx.OFFICER
OFFICER_OTHER = fx.OFFICER_OTHER
AGENT = fx.AGENT


class TestFailedInspectionOverridesTheRefundLadder:
    """A four-hop chain that ends on a refund the guest could never have won."""

    @staticmethod
    def _world():
        """An open, cleared run with one confirmed party of four and one inspection.

        The order is bought on 2026-08-25 for a window on 2026-09-05, which is
        11 days of lead time, so the unit price is the plain list price and the
        cascade fires two hours before the doors would have opened.
        """
        bundle = fx.selling_world(
            slot_overrides={"base_capacity": 40, "wheelchair_positions": 4}
        )
        fx.set_clock("2026-08-25T00:00:00Z")
        bundle["order"] = fx.confirmed_order(
            bundle["slot"]["id"],
            bundle["guest"]["id"],
            order_type="SINGLE",
            party_size=4,
            wheelchair_party_count=0,
            sensory_accommodations=[],
            merch_amount_cents=0,
        )
        bundle["inspection"] = fx.scheduled_inspection(
            bundle["run"]["id"], "ACCESSIBILITY",
            scheduled_for_utc="2026-09-05T12:00:00Z",
        )
        fx.set_clock("2026-09-05T12:00:00Z")
        return bundle

    def test_one_finalisation_walks_the_run_the_window_and_the_order(self):
        """Six findings at MAJOR fail, and the failure pins the refund at 1.00.

        PRD: "Third, a `severity` of `MAJOR` yields `FAIL` when `findings_count`
        is greater than 5 and `CONDITIONAL` otherwise."
        PRD: "On every branch, whatever the verdict, finalisation moves the
        inspection `SCHEDULED → FINALIZED`, records `finalized_by_user_id` from
        the finalising `X-User-ID` and `finalized_at` from the clock, and writes
        `allowed_occupancy_cap` as the `measured_egress_width_cm` divided by
        2.03 centimetres per occupant and floored."
        PRD: "Hop 2, caused by hop 1, drives the run's `clearance_status` to
        `SUSPENDED` from either `UNCLEARED` or `CLEARED`, stamping `suspended_at`
        from the clock and recording `suspending_inspection_id` as this
        inspection's `id`."
        PRD: "Hop 3, caused by hop 2, moves every slot of the run in `OPEN` or
        `SOLD_OUT` to `SUSPENDED`, preserving their capacity counters."
        PRD: "moves every `CONFIRMED` order on those now-suspended slots to
        `REFUND_DUE` — and this is the operator-fault branch of the refund rule:
        `refund_pct` is forced to 1.00"
        PRD: "because a suspended window is not resellable and those seats must
        not be handed to anybody else."

        Design: Difficulty/transitive_cascade/failed_accessibility_inspection_cascade_overrides_the_refund_ladder
        """
        world = self._world()
        run_id = world["run"]["id"]
        slot_id = world["slot"]["id"]
        order_id = world["order"]["id"]
        assert world["order"]["unit_price_cents"] == 35833
        assert world["order"]["net_amount_cents"] == 143332
        assert world["order"]["net_collected_cents"] == 143332

        inspection = validate_success(
            api_client.finalize_inspection(
                world["inspection"]["id"],
                f.inspection_finalize_payload(
                    measured_egress_width_cm=400,
                    findings_count=6,
                    severity="MAJOR",
                    findings_note=(
                        "two quiet-route signs missing, ramp slope out of tolerance"
                    ),
                ),
                OFFICER,
            )
        )
        assert_inspection(inspection)
        assert inspection["status"] == "FINALIZED"
        assert inspection["outcome"] == "FAIL"
        assert inspection["allowed_occupancy_cap"] == 197
        assert inspection["finalized_by_user_id"] == "officer-1"
        assert_instant_equals(inspection["finalized_at"], "2026-09-05T12:00:00Z")

        run = fx.read_run(run_id)
        assert_run(run)
        assert run["clearance_status"] == "SUSPENDED"
        assert run["suspending_inspection_id"] == inspection["id"]
        assert_instant_equals(run["suspended_at"], "2026-09-05T12:00:00Z")
        assert run["run_status"] == "OPEN"
        assert run["closing_started_at"] is None
        assert run["effective_capacity_cap"] == 0
        assert run["effective_capacity"] == 120

        slot = fx.read_slot(slot_id)
        assert_slot(slot)
        assert slot["status"] == "SUSPENDED"
        assert_slot_ledger(slot, released=40, held=0, sold=4, available=36)
        assert slot["wheelchair_sold"] == 0

        order = fx.read_order(order_id)
        assert_order(order)
        assert order["status"] == "REFUND_DUE"
        assert order["refund_pct"] == 1.00
        assert order["refunded_cents"] == 143332
        assert order["credit_issued_cents"] == 0
        assert order["net_collected_cents"] == 0

    def test_the_settlement_lands_nothing_on_the_credit_leg_and_shuts_the_door(self):
        """The whole sum went out as cash, so the balance never moves.

        PRD: "`credit_issued_cents` is 0 because nothing is retained as credit
        when the failure is the operator's, and `net_collected_cents` becomes 0."
        PRD: "Settling moves `REFUND_DUE → REFUNDED`, stamps `refund_settled_at`,
        and adds `credit_issued_cents` to the guest's `experience_credit_cents`."
        PRD: "the code named for that entity — `ERR_VENUE_INVALID_STATE`,
        `ERR_AGREEMENT_INVALID_STATE`, `ERR_SUBMISSION_INVALID_STATE`,
        `ERR_RUN_INVALID_STATE`, `ERR_SLOT_INVALID_STATE`,
        `ERR_ORDER_INVALID_STATE`, `ERR_STAFF_INVALID_STATE`,
        `ERR_SHIFT_INVALID_STATE`, `ERR_INSPECTION_INVALID_STATE`,
        `ERR_KIT_INVALID_STATE` or `ERR_STATEMENT_INVALID_STATE` — at HTTP 409."

        Design: Difficulty/transitive_cascade/failed_accessibility_inspection_cascade_overrides_the_refund_ladder
        """
        world = self._world()
        order_id = world["order"]["id"]
        guest_id = world["guest"]["id"]
        validate_success(
            api_client.finalize_inspection(
                world["inspection"]["id"],
                f.inspection_finalize_payload(
                    measured_egress_width_cm=400,
                    findings_count=6,
                    severity="MAJOR",
                    findings_note="ramp slope out of tolerance",
                ),
                OFFICER,
            )
        )
        assert fx.read_guest(guest_id)["experience_credit_cents"] == 0

        settled = validate_success(api_client.settle_refund(order_id, AGENT))
        assert settled["status"] == "REFUNDED"
        assert_instant_equals(settled["refund_settled_at"], "2026-09-05T12:00:00Z")
        assert settled["refunded_cents"] == 143332
        assert settled["credit_issued_cents"] == 0
        assert settled["refunded_cents"] + settled["credit_issued_cents"] == 143332

        guest = fx.read_guest(guest_id)
        assert guest["experience_credit_cents"] == 0
        assert guest["visit_count"] == 0

        before = fx.read_order(order_id)
        validate_error(
            api_client.record_attendance(
                order_id, f.attendance_payload("CHECK_IN"), AGENT
            ),
            ApiErrorId.ERR_ORDER_INVALID_STATE.value,
            409,
        )
        after = fx.read_order(order_id)
        assert after["status"] == "REFUNDED"
        assert_row_inert(before, after)


class TestParallelDimensionsAndTheTwoWayLift:
    """One row, two standings, and a lift that picks its own destination."""

    @staticmethod
    def _world():
        """An open, cleared run with a released 40-seat window and no orders.

        The suspending SENSORY inspection is booked and the clock is parked on
        the instant it is due, so the finalisation stamps a known instant.
        """
        bundle = fx.open_run(
            slot_overrides={"base_capacity": 40, "wheelchair_positions": 4}
        )
        bundle["fail_inspection"] = fx.scheduled_inspection(
            bundle["run"]["id"], "SENSORY",
            scheduled_for_utc="2026-08-12T09:00:00Z",
        )
        fx.set_clock("2026-08-12T09:00:00Z")
        return bundle

    @staticmethod
    def _drive_to_a_fresh_pass(world):
        """Fail the run, pull the performer, then record a later SENSORY PASS."""
        validate_success(
            api_client.finalize_inspection(
                world["fail_inspection"]["id"],
                f.inspection_finalize_payload(
                    measured_egress_width_cm=380.0,
                    findings_count=1,
                    severity="CRITICAL",
                    findings_note="strobe intensity above the declared sensory plan",
                ),
                OFFICER,
            )
        )
        validate_success(
            api_client.decide_staff_status(
                world["roster"]["performer"]["id"],
                f.staff_status_decision_payload(
                    "SUSPEND", note="pulled pending retraining"
                ),
                PRODUCER,
            )
        )
        fx.set_clock("2026-08-14T09:00:00Z")
        world["pass_inspection"] = fx.finalized_inspection(
            world["run"]["id"], "SENSORY",
            headers=OFFICER,
            create_overrides={"scheduled_for_utc": "2026-08-14T09:00:00Z"},
            measured_egress_width_cm=380.0,
            findings_count=0,
            severity="NONE",
        )
        return world

    def test_the_compliance_dimension_walks_while_the_operational_one_stands_still(
        self,
    ):
        """Suspending the performer cannot move a run that a failure already froze.

        PRD: "A run can be commercially `OPEN` while compliance-wise
        `SUSPENDED`, and a run can be `CLEARED` while still `PLANNED`."
        PRD: "Second, a `severity` of `CRITICAL` yields `FAIL`."
        PRD: "Hop 2, caused by hop 1, drives the run's `clearance_status` to
        `SUSPENDED` from either `UNCLEARED` or `CLEARED`, stamping `suspended_at`
        from the clock and recording `suspending_inspection_id` as this
        inspection's `id`."
        PRD: "Whichever call completes the gate — the approval of the last
        outstanding scope, or the clearing of the last missing craft — is the
        call that moves the run `UNCLEARED → CLEARED`; whichever call breaks it
        moves the run `CLEARED → UNCLEARED`."
        PRD: "On `PASS` there is no cascade at all. Nothing outside the
        inspection row changes; in particular the run's `effective_capacity` and
        `effective_capacity_cap` are left untouched."

        Design: Difficulty/non_linear_state_machine/run_parallel_dimensions_and_two_way_suspension_lift_branch
        """
        world = self._world()
        run_id = world["run"]["id"]
        slot_id = world["slot"]["id"]
        performer_id = world["roster"]["performer"]["id"]
        assert world["run"]["run_status"] == "OPEN"
        assert world["run"]["clearance_status"] == "CLEARED"

        failed = validate_success(
            api_client.finalize_inspection(
                world["fail_inspection"]["id"],
                f.inspection_finalize_payload(
                    measured_egress_width_cm=380.0,
                    findings_count=1,
                    severity="CRITICAL",
                    findings_note="strobe intensity above the declared sensory plan",
                ),
                OFFICER,
            )
        )
        assert failed["outcome"] == "FAIL"

        run = fx.read_run(run_id)
        assert run["clearance_status"] == "SUSPENDED"
        assert run["suspending_inspection_id"] == failed["id"]
        assert_instant_equals(run["suspended_at"], "2026-08-12T09:00:00Z")
        assert run["run_status"] == "OPEN"
        assert run["closing_started_at"] is None
        slot = fx.read_slot(slot_id)
        assert slot["status"] == "SUSPENDED"
        assert slot["released_capacity"] == 40

        suspended_member = validate_success(
            api_client.decide_staff_status(
                performer_id,
                f.staff_status_decision_payload(
                    "SUSPEND", note="pulled pending retraining"
                ),
                PRODUCER,
            )
        )
        assert_staff_member(suspended_member)
        assert suspended_member["status"] == "SUSPENDED"
        run = fx.read_run(run_id)
        assert run["clearance_status"] == "SUSPENDED"
        assert run["suspending_inspection_id"] == failed["id"]
        assert run["run_status"] == "OPEN"

        fx.set_clock("2026-08-14T09:00:00Z")
        passed = fx.finalized_inspection(
            run_id, "SENSORY",
            headers=OFFICER,
            create_overrides={"scheduled_for_utc": "2026-08-14T09:00:00Z"},
            measured_egress_width_cm=380.0,
            findings_count=0,
            severity="NONE",
        )
        assert passed["outcome"] == "PASS"
        run = fx.read_run(run_id)
        assert run["effective_capacity_cap"] == 0
        assert run["effective_capacity"] == 120
        assert run["clearance_status"] == "SUSPENDED"
        assert run["run_status"] == "OPEN"

    def test_the_identical_lift_call_forks_on_the_gate_and_on_the_officer(self):
        """The officer who closed the run may not reopen it, and the gate decides where.

        PRD: "And the lifting `X-User-ID` must differ from the
        `finalized_by_user_id` of the suspending inspection, or the request is
        refused with `ERR_SOD_SUSPENSION_LIFT_SAME_USER` — the officer who
        closed the run may not be the one who reopens it."
        PRD: "On success `suspended_at` and `suspending_inspection_id` are both
        cleared, and every slot of the run still in `SUSPENDED` returns to
        `OPEN`, landing in `SOLD_OUT` instead where its `available_capacity` is
        already 0."
        PRD: "The destination of the run itself depends on the very same
        approval-and-staffing gate that governs the uncleared-cleared pair: when
        the gate holds the run moves `SUSPENDED → CLEARED`, and when it does not
        the run moves `SUSPENDED → UNCLEARED`."
        PRD: "`REINSTATE` moves `SUSPENDED → CLEARED` under exactly the same two
        readiness gates as `CLEAR`"
        PRD: "The clearance gate is a conjunction over two other entity
        families, re-derived on every change to either."

        Design: Difficulty/non_linear_state_machine/run_parallel_dimensions_and_two_way_suspension_lift_branch
        """
        world = self._drive_to_a_fresh_pass(self._world())
        run_id = world["run"]["id"]
        slot_id = world["slot"]["id"]
        performer_id = world["roster"]["performer"]["id"]
        clearing_id = world["pass_inspection"]["id"]

        before = fx.read_run(run_id)
        validate_error(
            api_client.lift_suspension(
                run_id,
                f.lift_suspension_payload(clearing_id, note="strobe re-programmed"),
                OFFICER,
            ),
            ApiErrorId.ERR_SOD_SUSPENSION_LIFT_SAME_USER.value,
            403,
        )
        after = fx.read_run(run_id)
        assert after["clearance_status"] == "SUSPENDED"
        assert_row_inert(before, after)

        lifted = validate_success(
            api_client.lift_suspension(
                run_id,
                f.lift_suspension_payload(clearing_id, note="strobe re-programmed"),
                OFFICER_OTHER,
            )
        )
        assert lifted["clearance_status"] == "UNCLEARED"
        assert lifted["suspended_at"] is None
        assert lifted["suspending_inspection_id"] is None
        assert lifted["run_status"] == "OPEN"
        slot = fx.read_slot(slot_id)
        assert slot["status"] == "OPEN"
        assert_slot_ledger(slot, released=40, held=0, sold=0, available=40)

        reinstated = validate_success(
            api_client.decide_staff_status(
                performer_id,
                f.staff_status_decision_payload(
                    "REINSTATE", note="retraining complete"
                ),
                PRODUCER,
            )
        )
        assert reinstated["status"] == "CLEARED"
        assert reinstated["readiness_score_audit"] >= 78.00
        run = fx.read_run(run_id)
        assert run["clearance_status"] == "CLEARED"
        assert run["run_status"] == "OPEN"


class TestTheVerdictLadderWalksAllFiveBranches:
    """Five rungs whose order is the whole point, and two edges facing opposite ways."""

    def test_the_five_branches_fire_in_their_declared_order(self):
        """Geometry beats severity, and both inclusive edges land on their own side.

        PRD: "First, the geometry override: on an `EGRESS` inspection whose
        `measured_egress_width_cm` is strictly below the egress floor, the
        outcome is `FAIL`. That floor is the venue's own `egress_width_cm`
        multiplied by 90 percent, rounded half up to two decimals"
        PRD: "Second, a `severity` of `CRITICAL` yields `FAIL`. Third, a
        `severity` of `MAJOR` yields `FAIL` when `findings_count` is greater than
        5 and `CONDITIONAL` otherwise. Fourth, a `severity` of `MINOR` yields
        `CONDITIONAL` when `findings_count` is greater than 2 and `PASS`
        otherwise. Fifth and last, a `severity` of `NONE` yields `PASS`."
        PRD: "Note the asymmetry between rungs three and four: five findings at
        `MAJOR` are conditional while six fail, whereas two findings at `MINOR`
        still pass and three are conditional."
        PRD: "whenever the derived outcome is anything other than `PASS`, the
        `findings_note` is mandatory and must be 1 to 500 characters"
        PRD: "and writes `allowed_occupancy_cap` as the
        `measured_egress_width_cm` divided by 2.03 centimetres per occupant and
        floored."

        Design: Corner/calculations/inspection_outcome_walks_all_five_ordered_branches
        """
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        assert bundle["venue"]["egress_width_cm"] == 400
        assert bundle["run"]["effective_capacity"] == 120

        cases = (
            ("EGRESS", "09", dict(
                measured_egress_width_cm=350, findings_count=0, severity="NONE",
                findings_note="corridor measured 350 cm against a 400 cm permit",
            ), "FAIL", 172),
            ("EGRESS", "10", dict(
                measured_egress_width_cm=360, findings_count=0, severity="NONE",
            ), "PASS", 177),
            ("CAPACITY", "11", dict(
                measured_egress_width_cm=400, findings_count=1, severity="CRITICAL",
                findings_note="one blocked exit device",
            ), "FAIL", 197),
            ("CAPACITY", "12", dict(
                measured_egress_width_cm=400, findings_count=5, severity="MAJOR",
                findings_note="five signage findings",
            ), "CONDITIONAL", 197),
            ("CAPACITY", "13", dict(
                measured_egress_width_cm=400, findings_count=6, severity="MAJOR",
                findings_note="six signage findings",
            ), "FAIL", 197),
            ("SENSORY", "14", dict(
                measured_egress_width_cm=200, findings_count=3, severity="MINOR",
                findings_note="three sensory-signage findings in a 200 cm corridor",
            ), "CONDITIONAL", 98),
            ("SENSORY", "15", dict(
                measured_egress_width_cm=400, findings_count=2, severity="MINOR",
            ), "PASS", 197),
            ("ACCESSIBILITY", "16", dict(
                measured_egress_width_cm=400, findings_count=0, severity="NONE",
            ), "PASS", 197),
        )

        verdicts = {}
        for index, (kind, hour, numbers, outcome, cap) in enumerate(cases, start=1):
            booked = fx.scheduled_inspection(
                run_id, kind, scheduled_for_utc=f"2026-08-03T{hour}:00:00Z"
            )
            assert booked["status"] == "SCHEDULED"
            assert booked["outcome"] is None
            finalised = validate_success(
                api_client.finalize_inspection(
                    booked["id"], f.inspection_finalize_payload(**numbers), OFFICER
                )
            )
            assert_inspection(finalised)
            assert finalised["status"] == "FINALIZED"
            assert finalised["outcome"] == outcome, (index, kind, numbers)
            assert finalised["allowed_occupancy_cap"] == cap, (index, kind, numbers)
            verdicts[index] = finalised

        assert verdicts[7]["findings_note"] is None

        run = fx.read_run(run_id)
        assert run["effective_capacity_cap"] == 98
        assert run["effective_capacity"] == 98
        assert run["clearance_status"] == "SUSPENDED"
        assert run["suspending_inspection_id"] == verdicts[5]["id"]
        assert run["run_status"] == "PLANNED"

        rows = assert_total_count(
            api_client.list_inspections(OFFICER, params={"run_id": run_id}), 8
        )
        assert all(row["status"] == "FINALIZED" for row in rows)


class TestConditionalCapsTheRunWithoutTouchingClearance:
    """One finalisation writes three entities, and the DRAFT window is not one of them."""

    @staticmethod
    def _world():
        """A capacity-120 run with a 20-seat and a 110-seat window released.

        A third window of 15 seats is left in `DRAFT` so the sweep can be seen
        to pass it by, and the SENSORY inspection is due at 2026-09-02T09:00:00Z.
        """
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        bundle["slot_small"] = fx.open_slot(run_id, base_capacity=20)
        bundle["slot_big"] = fx.open_slot(
            run_id,
            slot_start_utc="2026-09-06T14:00:00Z",
            slot_end_utc="2026-09-06T14:45:00Z",
            pricing_tier="PEAK",
            base_capacity=110,
            wheelchair_positions=4,
        )
        bundle["slot_draft"] = fx.draft_slot(
            run_id,
            slot_start_utc="2026-09-07T14:00:00Z",
            slot_end_utc="2026-09-07T14:45:00Z",
            pricing_tier="OFFPEAK",
            base_capacity=15,
            wheelchair_positions=1,
        )
        bundle["inspection"] = fx.scheduled_inspection(
            run_id, "SENSORY", scheduled_for_utc="2026-09-02T09:00:00Z"
        )
        fx.set_clock("2026-09-02T09:30:00Z")
        return bundle

    def test_the_cap_sweeps_only_the_live_windows_that_no_longer_fit(self):
        """98 seats of permitted headcount suspend the 110-seat window and nothing else.

        PRD: "Fourth, a `severity` of `MINOR` yields `CONDITIONAL` when
        `findings_count` is greater than 2 and `PASS` otherwise."
        PRD: "The run's `effective_capacity_cap` becomes this inspection's
        `allowed_occupancy_cap`, and the run's `effective_capacity` is recomputed
        as the tightest of the four ceilings, now including the new cap."
        PRD: "Every slot of that run in `OPEN` or `SOLD_OUT` whose
        `base_capacity` exceeds the new `effective_capacity_cap` moves to
        `SUSPENDED`, because those windows are now oversold against the permitted
        headcount; windows that already fit the cap keep selling."
        PRD: "it is never set directly by an operator command; it is derived from
        creative approvals and staffing, or forced by a failed safety inspection,
        and it has no terminal state."
        PRD: "`version` is an integer that is 1 at creation and increases by
        exactly 1 on every mutation of that row, again including cascaded
        mutations."

        Design: Corner/state_machines/a_conditional_inspection_caps_the_run_and_suspends_its_live_slots
        """
        world = self._world()
        run_id = world["run"]["id"]
        run_version_before = fx.run_version(run_id)
        small_before = fx.read_slot(world["slot_small"]["id"])
        big_before = fx.read_slot(world["slot_big"]["id"])
        draft_before = fx.read_slot(world["slot_draft"]["id"])

        finalised = validate_success(
            api_client.finalize_inspection(
                world["inspection"]["id"],
                f.inspection_finalize_payload(
                    measured_egress_width_cm=200,
                    findings_count=3,
                    severity="MINOR",
                    findings_note=(
                        "two sensory bypass signs missing and one strobe cue over level"
                    ),
                ),
                OFFICER,
            )
        )
        assert finalised["outcome"] == "CONDITIONAL"
        assert finalised["status"] == "FINALIZED"
        assert finalised["allowed_occupancy_cap"] == 98
        assert finalised["finalized_by_user_id"] == "officer-1"

        run = validate_object(api_client.get_run(run_id, PRODUCER))
        assert run["effective_capacity_cap"] == 98
        assert run["effective_capacity"] == 98
        assert run["clearance_status"] == "UNCLEARED"
        assert run["suspending_inspection_id"] is None
        assert run["suspended_at"] is None
        assert run["version"] == run_version_before + 1

        small_after = validate_object(
            api_client.get_slot(world["slot_small"]["id"], PRODUCER)
        )
        assert small_after["status"] == "OPEN"
        assert_row_inert(small_before, small_after)

        big_after = validate_object(
            api_client.get_slot(world["slot_big"]["id"], PRODUCER)
        )
        assert big_after["status"] == "SUSPENDED"
        assert_slot_ledger(big_after, released=110, held=0, sold=0, available=110)
        assert big_after["version"] == big_before["version"] + 1

        draft_after = validate_object(
            api_client.get_slot(world["slot_draft"]["id"], PRODUCER)
        )
        assert draft_after["status"] == "DRAFT"
        assert_row_inert(draft_before, draft_after)

        released = validate_success(
            api_client.release_slot(world["slot_draft"]["id"], PRODUCER)
        )
        assert released["status"] == "OPEN"
        assert_slot_ledger(released, released=15, held=0, sold=0, available=15)


class TestVoidingIsTerminalAndIsNotEvidence:
    """A sheet that stores less than it found can neither clear nor retract."""

    @staticmethod
    def _world():
        """A run suspended by a CRITICAL EGRESS failure, plus one sheet to void.

        The suspending inspection is finalised by the first officer so the second
        officer is free to attempt the lift, and the sheet to be voided is booked
        by that second officer and left `SCHEDULED`.
        """
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        bundle["slot"] = fx.open_slot(
            run_id,
            slot_start_utc="2026-09-15T14:00:00Z",
            slot_end_utc="2026-09-15T14:45:00Z",
            pricing_tier="PEAK",
            base_capacity=20,
            wheelchair_positions=2,
        )
        bundle["insp_fail"] = fx.finalized_inspection(
            run_id, "EGRESS",
            headers=OFFICER,
            create_overrides={"scheduled_for_utc": "2026-08-05T09:00:00Z"},
            measured_egress_width_cm=400,
            findings_count=3,
            severity="CRITICAL",
            findings_note="blocked corridor at the north exit",
        )
        bundle["insp_void"] = fx.scheduled_inspection(
            run_id, "EGRESS", scheduled_for_utc="2026-08-06T09:00:00Z"
        )
        bundle["run"] = fx.read_run(run_id)
        bundle["slot"] = fx.read_slot(bundle["slot"]["id"])
        return bundle

    def test_the_void_stores_less_than_it_found_and_admits_no_second_act(self):
        """VOIDED keeps the note, drops everything else, and closes both doors.

        PRD: "An inspection that will not be carried out is voided instead,
        moving `SCHEDULED → VOIDED` with the supplied `note` stored as
        `findings_note`, leaving `outcome` null and `allowed_occupancy_cap` at 0."
        PRD: "A new inspection is `SCHEDULED` with `outcome` null,
        `measured_egress_width_cm` at 0, `findings_count` at 0, `severity` at
        `NONE`, `allowed_occupancy_cap` at 0, and `findings_note`,
        `finalized_by_user_id` and `finalized_at` all null."
        PRD: "The resource named in the path is in a state from which the
        requested transition is declared."
        PRD: "`version` is an integer that is 1 at creation and increases by
        exactly 1 on every mutation of that row, again including cascaded
        mutations."

        Design: Corner/endpoints/voiding_an_inspection_is_terminal_and_never_clears_a_suspension
        """
        world = self._world()
        run_before = world["run"]
        assert run_before["clearance_status"] == "SUSPENDED"
        assert run_before["suspending_inspection_id"] == world["insp_fail"]["id"]

        voided = validate_success(
            api_client.void_inspection(
                world["insp_void"]["id"],
                f.inspection_void_payload(
                    note="inspector unavailable; reinspection rebooked"
                ),
                OFFICER_OTHER,
            )
        )
        assert_inspection(voided)
        assert voided["status"] == "VOIDED"
        assert voided["outcome"] is None
        assert voided["allowed_occupancy_cap"] == 0
        assert voided["measured_egress_width_cm"] == 0
        assert voided["findings_count"] == 0
        assert voided["severity"] == "NONE"
        assert voided["findings_note"] == (
            "inspector unavailable; reinspection rebooked"
        )
        assert voided["finalized_by_user_id"] is None
        assert voided["finalized_at"] is None
        assert voided["version"] == 2

        run_after = fx.read_run(run_before["id"])
        assert run_after["clearance_status"] == "SUSPENDED"
        assert run_after["suspending_inspection_id"] == world["insp_fail"]["id"]
        assert_row_inert(run_before, run_after)

        validate_error(
            api_client.void_inspection(
                world["insp_void"]["id"],
                f.inspection_void_payload(note="second attempt"),
                OFFICER_OTHER,
            ),
            ApiErrorId.ERR_INSPECTION_INVALID_STATE.value,
            409,
        )
        still_void = fx.read_inspection(world["insp_void"]["id"])
        assert still_void["findings_note"] == (
            "inspector unavailable; reinspection rebooked"
        )
        assert_row_inert(voided, still_void)

        validate_error(
            api_client.finalize_inspection(
                world["insp_void"]["id"],
                f.inspection_finalize_payload(
                    measured_egress_width_cm=400, findings_count=0, severity="NONE"
                ),
                OFFICER_OTHER,
            ),
            ApiErrorId.ERR_INSPECTION_INVALID_STATE.value,
            409,
        )
        assert fx.read_inspection(world["insp_void"]["id"])["outcome"] is None

        validate_error(
            api_client.void_inspection(
                world["insp_fail"]["id"],
                f.inspection_void_payload(note="trying to undo the failure"),
                OFFICER_OTHER,
            ),
            ApiErrorId.ERR_INSPECTION_INVALID_STATE.value,
            409,
        )
        assert fx.read_inspection(world["insp_fail"]["id"])["outcome"] == "FAIL"

    def test_only_a_recorded_pass_can_reopen_what_the_failure_closed(self):
        """The voided sheet is refused as evidence; a real PASS lifts the whole cascade.

        PRD: "A voided inspection can never clear a suspension, precisely because
        it has no outcome."
        PRD: "whose status is `FINALIZED` and whose `outcome` is `PASS`; anything
        else is refused with `ERR_INSPECTION_PASS_MISSING`."
        PRD: "On `PASS` there is no cascade at all. Nothing outside the
        inspection row changes; in particular the run's `effective_capacity` and
        `effective_capacity_cap` are left untouched."
        PRD: "On success `suspended_at` and `suspending_inspection_id` are both
        cleared, and every slot of the run still in `SUSPENDED` returns to
        `OPEN`, landing in `SOLD_OUT` instead where its `available_capacity` is
        already 0."
        PRD: "Safety inspections filter on `run_id`, `inspection_type` and
        `status`."

        Design: Corner/endpoints/voiding_an_inspection_is_terminal_and_never_clears_a_suspension
        """
        world = self._world()
        run_id = world["run"]["id"]
        slot_id = world["slot"]["id"]
        validate_success(
            api_client.void_inspection(
                world["insp_void"]["id"],
                f.inspection_void_payload(
                    note="inspector unavailable; reinspection rebooked"
                ),
                OFFICER_OTHER,
            )
        )
        assert fx.read_slot(slot_id)["status"] == "SUSPENDED"

        validate_error(
            api_client.lift_suspension(
                run_id,
                f.lift_suspension_payload(
                    world["insp_void"]["id"], note="trying the voided sheet"
                ),
                OFFICER_OTHER,
            ),
            ApiErrorId.ERR_INSPECTION_PASS_MISSING.value,
            409,
        )
        blocked = fx.read_run(run_id)
        assert blocked["clearance_status"] == "SUSPENDED"
        assert blocked["suspending_inspection_id"] == world["insp_fail"]["id"]
        assert fx.read_slot(slot_id)["status"] == "SUSPENDED"

        passed = fx.finalized_inspection(
            run_id, "EGRESS",
            headers=OFFICER_OTHER,
            create_overrides={"scheduled_for_utc": "2026-08-07T09:00:00Z"},
            measured_egress_width_cm=400,
            findings_count=0,
            severity="NONE",
        )
        assert passed["outcome"] == "PASS"
        assert passed["allowed_occupancy_cap"] == 197
        capped = fx.read_run(run_id)
        assert capped["effective_capacity"] == 120
        assert capped["effective_capacity_cap"] == 0

        lifted = validate_success(
            api_client.lift_suspension(
                run_id,
                f.lift_suspension_payload(
                    passed["id"], note="corridor cleared and re-measured"
                ),
                OFFICER_OTHER,
            )
        )
        assert lifted["clearance_status"] == "UNCLEARED"
        assert lifted["suspended_at"] is None
        assert lifted["suspending_inspection_id"] is None

        rows = assert_total_count(
            api_client.list_inspections(
                OFFICER_OTHER, params={"run_id": run_id, "status": "VOIDED"}
            ),
            1,
        )
        assert rows[0]["id"] == world["insp_void"]["id"]

        slot = validate_object(api_client.get_slot(slot_id, PRODUCER))
        assert slot["status"] == "OPEN"
        assert_slot_ledger(slot, released=20, held=0, sold=0, available=20)


class TestCrossEntityGatesUseTheirOwnErrorIds:
    """Four refusals, each about the state of a row the path never names."""

    def test_each_refusal_names_the_row_it_actually_read(self):
        """The venue, the licence and the run's compliance dimension refuse in turn.

        PRD: "the run's venue is not `LEASE_ACTIVE` when the run opens
        (`ERR_VENUE_LEASE_NOT_ACTIVE`); the licence agreement is not `ACTIVE`
        when a run is created or a submission is created or resubmitted
        (`ERR_AGREEMENT_NOT_ACTIVE`); the run is not `CLEARED` when it opens or
        when an order is confirmed (`ERR_RUN_NOT_CLEARED`); the run is
        `SUSPENDED` when an admission window is released or a guest is checked in
        (`ERR_RUN_SUSPENDED`)"
        PRD: "its venue must by then be `LEASE_ACTIVE`, or the request is refused
        with `ERR_VENUE_LEASE_NOT_ACTIVE`; its `clearance_status` must be
        `CLEARED`, or the request is refused with `ERR_RUN_NOT_CLEARED`"
        PRD: "the run's `clearance_status` to be `CLEARED`, or the request is
        refused with `ERR_RUN_NOT_CLEARED`"
        PRD: "The two optimistic-concurrency guards of §2.6:
        `ERR_RUN_VERSION_CONFLICT` on royalty-statement creation and
        `ERR_AGREEMENT_VERSION_CONFLICT` on creative-submission creation, both at
        HTTP 412."
        PRD: "the run's `clearance_status` must not be `SUSPENDED` — a suspended
        run may not put seats on sale, and the attempt is refused with
        `ERR_RUN_SUSPENDED`"

        Design: Corner/validations/cross_entity_state_gates_refuse_with_their_own_error_ids
        """
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        venue_id = bundle["venue"]["id"]
        assert bundle["venue"]["status"] == "PERMIT_ISSUED"
        assert bundle["run"]["run_status"] == "PLANNED"
        assert bundle["run"]["clearance_status"] == "UNCLEARED"

        agreement_id = bundle["agreement"]["id"]
        slot_a = fx.open_slot(run_id)
        guest = fx.create_guest()
        order = fx.place_order(
            slot_a["id"], guest["id"], order_type="SINGLE", party_size=2
        )
        inspection = fx.scheduled_inspection(
            run_id, "EGRESS", scheduled_for_utc="2026-08-03T09:00:00Z"
        )
        slot_b = fx.draft_slot(
            run_id,
            slot_start_utc="2026-09-06T14:00:00Z",
            slot_end_utc="2026-09-06T14:45:00Z",
            base_capacity=20,
            wheelchair_positions=2,
        )

        validate_error(
            api_client.open_run(run_id, PRODUCER),
            ApiErrorId.ERR_VENUE_LEASE_NOT_ACTIVE.value,
            409,
        )
        assert fx.read_run(run_id)["run_status"] == "PLANNED"

        activated = validate_success(api_client.activate_lease(venue_id, fx.VOM))
        assert activated["status"] == "LEASE_ACTIVE"

        validate_error(
            api_client.open_run(run_id, PRODUCER),
            ApiErrorId.ERR_RUN_NOT_CLEARED.value,
            409,
        )
        assert fx.read_run(run_id)["run_status"] == "PLANNED"

        validate_error(
            api_client.confirm_order(order["id"], AGENT),
            ApiErrorId.ERR_RUN_NOT_CLEARED.value,
            409,
        )
        held = fx.read_order(order["id"])
        assert held["status"] == "PENDING"
        assert_slot_ledger(
            fx.read_slot(slot_a["id"]), released=20, held=2, sold=0, available=18
        )

        # The submission's own licence gate needs a run staged under the licence
        # being probed: a run_id belonging to a different agreement would fail
        # the body-foreign-key scope rung first.  The run's own agreement is
        # therefore expired out from under it before the submission is filed.
        fx.set_clock("2027-01-01T00:00:00Z")
        expired = validate_success(api_client.expire_agreement(agreement_id, fx.LM))
        assert expired["status"] == "EXPIRED"
        validate_error(
            api_client.create_submission(
                f.submission_payload(
                    agreement_id, run_id,
                    fx.agreement_version(agreement_id),
                    asset_code="MERCH-PIN-01",
                    title="Enamel pin set",
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value,
            409,
        )
        assert_total_count(
            api_client.list_submissions(
                PRODUCER, params={"license_agreement_id": agreement_id}
            ),
            0,
        )
        fx.reset_clock()

        failed = validate_success(
            api_client.finalize_inspection(
                inspection["id"],
                f.inspection_finalize_payload(
                    measured_egress_width_cm=350,
                    findings_count=0,
                    severity="NONE",
                    findings_note=(
                        "corridor measured 350 cm against a 400 cm permit"
                    ),
                ),
                OFFICER,
            )
        )
        assert failed["outcome"] == "FAIL"
        assert fx.read_run(run_id)["clearance_status"] == "SUSPENDED"

        before = fx.read_slot(slot_b["id"])
        validate_error(
            api_client.release_slot(slot_b["id"], PRODUCER),
            ApiErrorId.ERR_RUN_SUSPENDED.value,
            409,
        )
        after = fx.read_slot(slot_b["id"])
        assert after["status"] == "DRAFT"
        assert after["released_capacity"] == 0
        assert_row_inert(before, after)
