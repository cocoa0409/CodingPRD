"""Compensating writes that must return a derived ledger to its prior value exactly.

Steel mass, permitted water volume, the open-nonconformance count and the weld
reject rate each survive an undo with no residual drift — and two deliberate
non-compensations mark the exact boundary of the reversal.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_ALLOCATION_STATE_INVALID,
    ERR_PHASE_TRANSITION_INVALID,
    ERR_PLAN_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_money,
    assert_plan_costs,
    assert_reject_rate,
    assert_source_ledger,
    assert_steel_conservation,
    assert_tank_state,
    assert_weight,
)
from test_helpers.constants import (
    ALLOCATION_ALLOCATED,
    ALLOCATION_UNALLOCATED,
    BASE_EXAMINATION_PCT,
    CANCELLATION_PLAN_REJECTED,
    CANCELLATION_PLAN_SUSPENDED,
    CLOCK_BASE,
    COURSE_WELDED,
    DECISION_REJECT,
    DEFECT_SLAG_INCLUSION,
    ESCALATED_EXAMINATION_PCT,
    LOT_QUARANTINED,
    LOT_RECEIVED,
    NDE_REPORTED_ACCEPT,
    NDE_REPORTED_REJECT,
    NDE_VOIDED,
    PHASE_ERECTION_IN_PROGRESS,
    PHASE_SHELL_COMPLETE,
    PLAN_APPROVED,
    PLAN_REJECTED,
    PLAN_SUSPENDED,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    SEAM_RT_REJECTED,
    SEAM_WELDED,
    SOURCE_MUNICIPAL,
    WITHDRAWAL_CANCELLED,
)
from test_helpers.test_users import ES1, PE1, QC1

LOT_A_WEIGHT = 12505.00
LOT_B_WEIGHT = 3601.00
RECEIVED_TOTAL = 16106.00


class TestSteelMassConservedAcrossAllocationAndRelease:
    def _two_received_lots_and_two_specified_courses(self, api):
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        ctx = X.Ctx(tank=tank, tank_id=tank["id"])
        ctx.c1 = X.create_course(api, ctx.tank_id, 1)
        ctx.c2 = X.create_course(api, ctx.tank_id, 2)
        ctx.lot_a = X.receive_plate_lot(
            api, ctx.tank_id, mtr_number="MTR-A-1", heat_number="H-4471",
            plate_count=10, plate_weight_lb=1250.5,
        )
        ctx.lot_b = X.receive_plate_lot(
            api, ctx.tank_id, mtr_number="MTR-B-1", heat_number="H-4472",
            plate_count=4, plate_weight_lb=900.25,
        )
        return ctx

    def _lots(self, api, ctx):
        return [
            X.read_plate_lot(api, ctx.lot_a["id"]),
            X.read_plate_lot(api, ctx.lot_b["id"]),
        ]

    def test_receipt_books_the_whole_lot_weight_into_the_tank_ledger(self, api):
        """Nothing is allocated yet, so remaining equals received on both lots.

        PRD: "On reaching `RECEIVED`, the lot's `received_weight_lb` is set once
        and for all to `plate_count` multiplied by `plate_weight_lb`, and its
        `remaining_weight_lb` is set to the same figure because nothing has yet
        been allocated."

        Design: Difficulty/compensating_invariant/steel_mass_conserved_across_allocation_and_release
        """
        ctx = self._two_received_lots_and_two_specified_courses(api)

        assert ctx.lot_a["status"] == LOT_RECEIVED
        assert_weight(ctx.lot_a["received_weight_lb"], LOT_A_WEIGHT, "lot A received")
        assert_weight(ctx.lot_a["allocated_weight_lb"], 0.00, "lot A allocated")
        assert_weight(ctx.lot_a["remaining_weight_lb"], LOT_A_WEIGHT, "lot A remaining")
        assert_weight(ctx.lot_b["received_weight_lb"], LOT_B_WEIGHT, "lot B received")
        assert_weight(ctx.lot_b["remaining_weight_lb"], LOT_B_WEIGHT, "lot B remaining")

        tank = X.read_tank(api, ctx.tank_id)
        assert_weight(tank["steel_received_lb"], RECEIVED_TOTAL, "tank steel received")
        assert_weight(tank["steel_allocated_lb"], 0.00, "tank steel allocated")
        assert_steel_conservation(tank, self._lots(api, ctx))

    def test_allocating_the_whole_remaining_weight_is_accepted_at_the_bound(self, api):
        """8000 lb from lot A and every last pound of lot B, and the identity holds.

        PRD: "The requested weight may not exceed the lot's `remaining_weight_lb`;
        a weight exactly equal to the remaining figure is accepted, and anything
        above it is rejected with `ERR_PLATE_WEIGHT_EXCEEDED`."

        Design: Difficulty/compensating_invariant/steel_mass_conserved_across_allocation_and_release
        """
        ctx = self._two_received_lots_and_two_specified_courses(api)

        course1 = X.allocate(api, ctx.lot_a["id"], ctx.c1["id"], 8000.00)
        assert course1["allocation_status"] == ALLOCATION_ALLOCATED
        assert course1["allocated_plate_lot_id"] == ctx.lot_a["id"]
        assert_weight(course1["allocated_weight_lb"], 8000.00, "course 1 allocated")
        tank = X.read_tank(api, ctx.tank_id)
        assert_weight(tank["steel_allocated_lb"], 8000.00, "tank steel allocated")
        assert_weight(
            X.read_plate_lot(api, ctx.lot_a["id"])["remaining_weight_lb"], 4505.00,
            "lot A remaining",
        )
        assert_steel_conservation(tank, self._lots(api, ctx))

        course2 = X.allocate(api, ctx.lot_b["id"], ctx.c2["id"], LOT_B_WEIGHT)
        assert course2["allocation_status"] == ALLOCATION_ALLOCATED
        assert_weight(
            X.read_plate_lot(api, ctx.lot_b["id"])["remaining_weight_lb"], 0.00,
            "lot B remaining",
        )
        tank = X.read_tank(api, ctx.tank_id)
        assert_weight(tank["steel_allocated_lb"], 11601.00, "tank steel allocated")
        assert_steel_conservation(tank, self._lots(api, ctx))

    def test_the_release_restores_the_pre_allocation_snapshot_exactly(self, api):
        """Course 2 and lot B come back to byte-identical figures.

        PRD: "A release therefore reconciles the lot's remaining weight and the
        tank's allocated total back to exactly their pre-allocation values."

        Design: Difficulty/compensating_invariant/steel_mass_conserved_across_allocation_and_release
        """
        ctx = self._two_received_lots_and_two_specified_courses(api)
        X.allocate(api, ctx.lot_a["id"], ctx.c1["id"], 8000.00)
        X.allocate(api, ctx.lot_b["id"], ctx.c2["id"], LOT_B_WEIGHT)

        released = X.release_allocation(
            api, ctx.c2["id"], reason="course 2 re-detailed to a thicker plate"
        )

        assert released["allocation_status"] == ALLOCATION_UNALLOCATED
        assert released["allocated_plate_lot_id"] is None
        assert_weight(released["allocated_weight_lb"], 0.00, "course 2 allocated")

        lot_b = X.read_plate_lot(api, ctx.lot_b["id"])
        assert_weight(lot_b["allocated_weight_lb"], 0.00, "lot B allocated")
        assert_weight(lot_b["remaining_weight_lb"], LOT_B_WEIGHT, "lot B remaining")

        tank = X.read_tank(api, ctx.tank_id)
        assert_weight(tank["steel_allocated_lb"], 8000.00, "tank steel allocated")
        assert_weight(tank["steel_received_lb"], RECEIVED_TOTAL, "tank steel received")
        assert_steel_conservation(tank, self._lots(api, ctx))

    def test_quarantine_keeps_the_steel_in_the_conserved_total(self, api):
        """The mass stays on the books even though the lot becomes unallocatable.

        PRD: "Quarantine deliberately does **not** roll that back: quarantined
        steel is physically on site but contractually unavailable, so it continues
        to count toward `steel_received_lb` while being barred from allocation."

        Design: Difficulty/compensating_invariant/steel_mass_conserved_across_allocation_and_release
        """
        ctx = self._two_received_lots_and_two_specified_courses(api)
        X.allocate(api, ctx.lot_a["id"], ctx.c1["id"], 8000.00)
        X.allocate(api, ctx.lot_b["id"], ctx.c2["id"], LOT_B_WEIGHT)
        X.release_allocation(api, ctx.c2["id"], reason="course 2 re-detailed")

        quarantined = X.lot_transition(
            api, ctx.lot_b["id"], LOT_QUARANTINED, remarks="MTR chemistry mismatch"
        )
        assert quarantined["status"] == LOT_QUARANTINED

        tank = X.read_tank(api, ctx.tank_id)
        assert_weight(tank["steel_received_lb"], RECEIVED_TOTAL, "tank steel received")
        assert_weight(tank["steel_allocated_lb"], 8000.00, "tank steel allocated")
        assert_steel_conservation(tank, self._lots(api, ctx))

        validate_error(
            api.plate_lot_allocation(
                ctx.lot_b["id"],
                {"shell_course_id": ctx.c2["id"], "allocated_weight_lb": 100.00},
                ES1,
            ),
            ERR_ALLOCATION_STATE_INVALID,
        )

        tank = X.read_tank(api, ctx.tank_id)
        assert_weight(tank["steel_allocated_lb"], 8000.00, "tank steel allocated")
        assert_steel_conservation(tank, self._lots(api, ctx))


# The two windows reserved against the 2,000,000 gal permit before the rejection.
W1_WINDOW = ("2026-08-12T08:00:00Z", "2026-08-12T12:00:00Z")
W2_WINDOW = ("2026-08-13T08:00:00Z", "2026-08-13T20:00:00Z")


class TestWaterVolumeConservedAcrossPlanRejectionCascade:
    def _draft_plan_holding_two_reservations(self, api):
        ctx = X.shell_complete_tank(api)
        ctx.source = X.create_water_source(
            api,
            source_name="Municipal Hydrant 12",
            source_type=SOURCE_MUNICIPAL,
            permitted_volume_gal=2000000.0,
            max_concurrent_rate_gpm=900.0,
            water_cost_usd_per_kgal=3.33,
            disposal_cost_usd_per_kgal=2.10,
        )
        ctx.source_id = ctx.source["id"]
        ctx.plan = X.create_plan(
            api, ctx.tank_id, ctx.source_id, fill_volume_gal=350000.0, hold_hours=24
        )
        ctx.plan_id = ctx.plan["id"]
        ctx.w1 = X.reserve_withdrawal(
            api, ctx.plan_id, ctx.source_id, *W1_WINDOW, 400.0, 100000.0
        )
        ctx.w2 = X.reserve_withdrawal(
            api, ctx.plan_id, ctx.source_id, *W2_WINDOW, 400.0, 250000.0
        )
        return ctx

    def test_the_two_reservations_price_the_plan_before_any_undo(self, api):
        """350 kgal of water at the 1.00 disposal tier and the 0.03 surcharge band.

        PRD: "The plan's `water_cost_usd` is then the **sum of those
        already-rounded per-withdrawal amounts**, taken over every withdrawal of
        the plan whose `status` is `RESERVED` or `CONSUMED`, processed in
        `created_at` order."

        Design: Difficulty/compensating_invariant/water_volume_conserved_across_plan_rejection_cascade
        """
        ctx = self._draft_plan_holding_two_reservations(api)

        assert_money(ctx.w1["withdrawal_cost_usd"], 333.00, "w1 withdrawal cost")
        assert_money(ctx.w2["withdrawal_cost_usd"], 832.50, "w2 withdrawal cost")
        assert_plan_costs(
            X.read_plan(api, ctx.plan_id),
            water=1165.50, disposal=735.00, subtotal=1900.50,
            surcharge_pct=0.03, surcharge=57.02, total=1957.52,
        )
        assert_source_ledger(
            X.read_water_source(api, ctx.source_id), 350000.00, 0.00, 1650000.00
        )

    def test_one_rejection_cancels_every_reservation_and_restores_the_volume(self, api):
        """The volume ledger returns to its pre-reservation values with no drift.

        PRD: "On `REJECT` the plan moves `DRAFT → REJECTED` and every `RESERVED`
        withdrawal of the plan is cancelled with `cancellation_reason`
        `PLAN_REJECTED`, each releasing its volume back to the source."

        Design: Difficulty/compensating_invariant/water_volume_conserved_across_plan_rejection_cascade
        """
        ctx = self._draft_plan_holding_two_reservations(api)

        rejected = X.approve_plan(
            api, ctx.plan_id, decision=DECISION_REJECT,
            remarks="water disposal permit not in hand",
        )
        assert rejected["status"] == PLAN_REJECTED

        for withdrawal in (ctx.w1, ctx.w2):
            row = X.read_withdrawal(api, withdrawal["id"])
            assert row["status"] == WITHDRAWAL_CANCELLED
            assert row["cancellation_reason"] == CANCELLATION_PLAN_REJECTED

        assert_source_ledger(
            X.read_water_source(api, ctx.source_id), 0.00, 0.00, 2000000.00
        )

    def test_the_currency_ledger_unwinds_while_the_row_history_survives(self, api):
        """Every plan cost falls to 0.00, yet each cancelled row keeps its own price.

        PRD: "Because a cancellation removes a withdrawal from the input set, it
        lowers both cost components and can move the disposal tier and the
        surcharge tier downward."

        Design: Difficulty/compensating_invariant/water_volume_conserved_across_plan_rejection_cascade
        """
        ctx = self._draft_plan_holding_two_reservations(api)
        X.approve_plan(api, ctx.plan_id, decision=DECISION_REJECT)

        assert_plan_costs(
            X.read_plan(api, ctx.plan_id),
            water=0.00, disposal=0.00, subtotal=0.00,
            surcharge_pct=0.00, surcharge=0.00, total=0.00,
        )
        assert_money(
            X.read_withdrawal(api, ctx.w1["id"])["withdrawal_cost_usd"], 333.00,
            "w1 withdrawal cost",
        )
        assert_money(
            X.read_withdrawal(api, ctx.w2["id"])["withdrawal_cost_usd"], 832.50,
            "w2 withdrawal cost",
        )
        assert X.read_tank(api, ctx.tank_id)["active_hydrotest_plan_id"] is None

    def test_the_released_volume_cannot_be_redrawn_against_the_rejected_plan(self, api):
        """A terminal plan accepts no further reservation.

        PRD: "While a plan is `SUSPENDED`, and likewise once it is `SUPERSEDED`,
        `PASSED`, `FAILED` or `REJECTED`, it accepts no further action of any kind,
        and any attempt is rejected with `ERR_PLAN_STATE_INVALID`."

        Design: Difficulty/compensating_invariant/water_volume_conserved_across_plan_rejection_cascade
        """
        ctx = self._draft_plan_holding_two_reservations(api)
        X.approve_plan(api, ctx.plan_id, decision=DECISION_REJECT)

        validate_error(
            api.create_water_withdrawal(
                {
                    "hydrotest_plan_id": ctx.plan_id,
                    "water_source_id": ctx.source_id,
                    "window_start_utc": W1_WINDOW[0],
                    "window_end_utc": W1_WINDOW[1],
                    "rate_gpm": 400.0,
                    "reserved_volume_gal": 100000.0,
                    "expected_water_source_version": X.source_version(api, ctx.source_id),
                },
                ES1,
            ),
            ERR_PLAN_STATE_INVALID,
        )
        assert_source_ledger(
            X.read_water_source(api, ctx.source_id), 0.00, 0.00, 2000000.00
        )


class TestNonconformanceCountAndRejectRateReversedByVoid:
    def _approved_plan_and_a_re_examination_on_an_accepted_seam(self, api):
        ctx = X.shell_complete_tank(api, seam_labels=("V1", "V2", "V3"))
        ctx.source = X.create_water_source(
            api, source_name="Municipal Hydrant 12", source_type=SOURCE_MUNICIPAL
        )
        ctx.source_id = ctx.source["id"]
        ctx.plan = X.create_plan(api, ctx.tank_id, ctx.source_id, fill_volume_gal=400000.0)
        ctx.plan_id = ctx.plan["id"]
        ctx.plan = X.approve_plan(api, ctx.plan_id)
        ctx.w1 = X.reserve_withdrawal(
            api, ctx.plan_id, ctx.source_id,
            "2026-08-20T08:00:00Z", "2026-08-20T18:00:00Z", 700.0, 400000.0,
        )
        ctx.reexam = X.schedule_nde(
            api, ctx.seams[2]["id"], "2026-08-14T10:00:00Z", "2026-08-14T11:00:00Z"
        )
        return ctx

    def test_the_re_examination_leaves_a_clean_tank_at_the_base_rate(self, api):
        """Scheduling on an accepted seam has already pulled the phase back.

        PRD: "A course falling out of `RT_ACCEPTED` back to `WELDED`, because a
        fresh examination was scheduled on an already accepted seam, also reverts
        the tank `SHELL_COMPLETE → ERECTION_IN_PROGRESS` when the tank had reached
        `SHELL_COMPLETE`; and a course falling from `RT_ACCEPTED` to `FITTED`,
        because a seam was rejected, does the same."

        Design: Difficulty/compensating_invariant/nonconformance_count_and_reject_rate_reversed_by_nde_void
        """
        ctx = self._approved_plan_and_a_re_examination_on_an_accepted_seam(api)

        tank = X.read_tank(api, ctx.tank_id)
        assert_tank_state(
            tank, phase=PHASE_ERECTION_IN_PROGRESS, posture=POSTURE_OPEN,
            nonconformance_count=0,
        )
        assert_reject_rate(tank["weld_reject_rate"], 0.0000)
        assert tank["required_examination_pct"] == pytest.approx(BASE_EXAMINATION_PCT)
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_WELDED

    def test_the_rejection_raises_the_count_and_the_rate_and_suspends_the_plan(self, api):
        """One reject in four reported RT reports is 0.2500 and escalates to 50 percent.

        PRD: "`weld_reject_rate` is 0.0 when that population is empty, and
        otherwise the count of rejected reports divided by the count of examined
        reports, rounded half up to 4 decimal places."

        Design: Difficulty/compensating_invariant/nonconformance_count_and_reject_rate_reversed_by_nde_void
        """
        ctx = self._approved_plan_and_a_re_examination_on_an_accepted_seam(api)

        report = X.report_nde(
            api, ctx.reexam["id"], DECISION_REJECT, 2, 4, defect_type=DEFECT_SLAG_INCLUSION
        )
        assert report["status"] == NDE_REPORTED_REJECT
        assert report["nonconformance_open"] is True

        seam = X.read_seam(api, ctx.seams[2]["id"])
        assert seam["status"] == SEAM_RT_REJECTED
        assert seam["repair_cycle_count"] == 0

        tank = X.read_tank(api, ctx.tank_id)
        assert_tank_state(tank, posture=POSTURE_RESTRICTED, nonconformance_count=1)
        assert_reject_rate(tank["weld_reject_rate"], 0.2500)
        assert tank["required_examination_pct"] == pytest.approx(ESCALATED_EXAMINATION_PCT)

        plan = X.read_plan(api, ctx.plan_id)
        assert plan["status"] == PLAN_SUSPENDED
        assert plan["state_before_suspension"] == PLAN_APPROVED
        withdrawal = X.read_withdrawal(api, ctx.w1["id"])
        assert withdrawal["status"] == WITHDRAWAL_CANCELLED
        assert withdrawal["cancellation_reason"] == CANCELLATION_PLAN_SUSPENDED
        assert_source_ledger(
            X.read_water_source(api, ctx.source_id), 0.00, 0.00, 2000000.00
        )

    def test_the_void_restores_the_count_the_rate_and_the_plan(self, api):
        """Both derived quantities return to their pre-rejection values exactly.

        PRD: "Every side effect of the rejection is reversed with no residual
        drift."

        Design: Difficulty/compensating_invariant/nonconformance_count_and_reject_rate_reversed_by_nde_void
        """
        ctx = self._approved_plan_and_a_re_examination_on_an_accepted_seam(api)
        X.report_nde(
            api, ctx.reexam["id"], DECISION_REJECT, 2, 4, defect_type=DEFECT_SLAG_INCLUSION
        )

        voided = X.void_nde(
            api, ctx.reexam["id"], void_reason="radiograph attributed to the wrong seam"
        )
        assert voided["status"] == NDE_VOIDED
        assert voided["nonconformance_open"] is False
        assert voided["void_reason"] == "radiograph attributed to the wrong seam"

        seam = X.read_seam(api, ctx.seams[2]["id"])
        assert seam["status"] == SEAM_WELDED
        assert seam["repair_cycle_count"] == 0

        tank = X.read_tank(api, ctx.tank_id)
        assert_tank_state(tank, posture=POSTURE_OPEN, nonconformance_count=0)
        assert_reject_rate(tank["weld_reject_rate"], 0.0000)
        assert tank["required_examination_pct"] == pytest.approx(BASE_EXAMINATION_PCT)

        plan = X.read_plan(api, ctx.plan_id)
        assert plan["status"] == PLAN_APPROVED
        assert plan["state_before_suspension"] is None
        assert plan["fill_percent_current"] == pytest.approx(0.0)

    def test_the_cancelled_window_and_the_operator_phase_are_not_compensated(self, api):
        """The compensation stops at the derived quantities, by design.

        PRD: "Compensation is deliberately partial: the plan comes back, but the
        cancelled withdrawal windows are **not** resurrected and must be reserved
        again explicitly."

        Design: Difficulty/compensating_invariant/nonconformance_count_and_reject_rate_reversed_by_nde_void
        """
        ctx = self._approved_plan_and_a_re_examination_on_an_accepted_seam(api)
        X.report_nde(
            api, ctx.reexam["id"], DECISION_REJECT, 2, 4, defect_type=DEFECT_SLAG_INCLUSION
        )
        X.void_nde(api, ctx.reexam["id"], void_reason="radiograph attributed to the wrong seam")

        assert X.read_withdrawal(api, ctx.w1["id"])["status"] == WITHDRAWAL_CANCELLED
        assert_source_ledger(
            X.read_water_source(api, ctx.source_id), 0.00, 0.00, 2000000.00
        )

        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_ERECTION_IN_PROGRESS
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_WELDED
        validate_error(
            api.phase_transition(ctx.tank_id, {"target_phase": PHASE_SHELL_COMPLETE}, PE1),
            ERR_PHASE_TRANSITION_INVALID,
        )

        rows, meta = X.list_rows(
            api, api.list_nde_reports(QC1, {"weld_seam_id": ctx.seams[2]["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"]: row["status"] for row in rows} == {
            ctx.reports[2]["id"]: NDE_REPORTED_ACCEPT,
            ctx.reexam["id"]: NDE_VOIDED,
        }
