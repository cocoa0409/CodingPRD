"""Declared transitions, refused transitions and the side effects each one carries.

Initial states, forward steps, terminal lockdown, derived parent state and the
one transition that reaches sideways into a sibling row.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_COATING_STEP_INVALID,
    ERR_COURSE_STATE_INVALID,
    ERR_COURSE_THICKNESS_DEFICIENT,
    ERR_PACKAGE_STATE_INVALID,
    ERR_SEAM_STATE_INVALID,
    ERR_WELDER_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_instant,
    assert_list_total,
    assert_tank_state,
    assert_thickness,
    assert_weight,
)
from test_helpers.constants import (
    ACTION_RENEW,
    ACTION_REVOKE,
    CLOCK_BASE,
    COATING_SPEC_ISSUED,
    COURSE_FITTED,
    COURSE_SPECIFIED,
    COURSE_WELDED,
    DECISION_REJECT,
    DFT_NOT_EVALUATED,
    GOVERNING_DESIGN,
    LOT_ORDERED,
    LOT_RECEIVED,
    LOT_ROLLED,
    LOT_SHIPPED,
    NC_NOT_APPLICABLE,
    PACKAGE_DRAFT,
    PHASE_DESIGN_REGISTERED,
    PHASE_ERECTION_IN_PROGRESS,
    PHASE_FOUNDATION_ACCEPTED,
    PKG_BASELINE_SET,
    PKG_REJECTED,
    REVIEW_ACCEPT,
    SCOPE_EXTERNAL_COATING,
    SEAM_FIT_READY,
    SEAM_WELDED,
    SURVEY_ROLE_BASELINE,
    THICKNESS_ADEQUATE,
    THICKNESS_DEFICIENT,
    VERDICT_BASELINE,
    WELDER_REVOKED,
)
from test_helpers.factories import (
    dft_readings_payload,
    repair_start_payload,
    review_payload,
    qualification_action_payload,
)
from test_helpers.test_users import AI1, AI3, CC1, ES1, PE1_ID, QC1


LOT_A_WEIGHT = 12505.00
LOT_B_WEIGHT = 3601.00


class TestPlateLotProcurementChain:
    def test_a_new_lot_opens_in_ordered_with_an_empty_weight_ledger(self, api):
        """Ordering plate books no steel: the tank ledger is still at zero.

        PRD: "A new lot starts at `status` `ORDERED` with `received_weight_lb`,
        `allocated_weight_lb` and `remaining_weight_lb` all at 0.0 and
        `quarantine_reason` null."

        Design: Corner/state_machines/plate_lot_starts_in_declared_initial_state
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)

        lot = X.create_plate_lot(api, tank["id"])

        assert lot["status"] == LOT_ORDERED
        assert_weight(lot["received_weight_lb"], 0.00, "received weight")
        assert_weight(lot["allocated_weight_lb"], 0.00, "allocated weight")
        assert_weight(lot["remaining_weight_lb"], 0.00, "remaining weight")
        assert lot["quarantine_reason"] is None
        assert lot["mtr_number"] is None
        assert lot["version"] == 1

        assert_weight(X.read_tank(api, tank["id"])["steel_received_lb"], 0.00, "steel received")

    def test_the_rolled_step_moves_status_forward_without_touching_the_ledger(self, api):
        """One step per request, and the weights wait for receipt.

        PRD: "From `ORDERED` the lot may go to `ROLLED`; from `ROLLED` to
        `SHIPPED`; from `SHIPPED` to `RECEIVED`; from `RECEIVED` to either
        `QUARANTINED` or `RELEASED`; and from `QUARANTINED` to `RELEASED`."

        PRD: "`version` is an integer that starts at 1 when the resource is
        created and increases by exactly 1 on every mutation of that resource;
        `updated_at` is refreshed on the same mutation."

        Design: Corner/state_machines/plate_lot_rolled_transition_moves_status_forward
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        lot = X.create_plate_lot(api, tank["id"])

        rolled = X.lot_transition(api, lot["id"], LOT_ROLLED)

        assert rolled["status"] == LOT_ROLLED
        assert rolled["version"] == 2
        assert_weight(rolled["received_weight_lb"], 0.00, "received weight")
        assert_weight(rolled["remaining_weight_lb"], 0.00, "remaining weight")
        assert rolled["mtr_number"] is None

        rows, _ = assert_list_total(api.list_plate_lots(ES1, {"status": LOT_ROLLED}), 1)
        assert rows[0]["id"] == lot["id"]
        assert_list_total(api.list_plate_lots(ES1, {"status": LOT_ORDERED}), 0)

    def test_receipt_applies_every_declared_side_effect_of_the_transition(self, api):
        """Two lots received in turn, and the tank total is re-summed each time.

        PRD: "On reaching `RECEIVED`, the lot's `received_weight_lb` is set once
        and for all to `plate_count` multiplied by `plate_weight_lb`, and its
        `remaining_weight_lb` is set to the same figure because nothing has yet
        been allocated."

        PRD: "The parent tank's `steel_received_lb` is then recomputed as the sum
        of `received_weight_lb` over every lot of the tank whose status is
        `RECEIVED`, `RELEASED` or `QUARANTINED`."

        Design: Corner/state_machines/plate_lot_received_applies_every_declared_side_effect
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        lot_a = X.create_plate_lot(api, tank["id"])
        lot_b = X.create_plate_lot(
            api,
            tank["id"],
            heat_number="H-44822",
            thickness_in=0.3125,
            plate_count=4,
            plate_weight_lb=900.25,
            unit_cost_usd_per_lb=0.60,
        )
        for lot_id in (lot_a["id"], lot_b["id"]):
            X.lot_transition(api, lot_id, LOT_ROLLED)
            X.lot_transition(api, lot_id, LOT_SHIPPED)

        received_a = X.lot_transition(
            api, lot_a["id"], LOT_RECEIVED, mtr_number="MTR-44821-A"
        )
        assert received_a["status"] == LOT_RECEIVED
        assert received_a["mtr_number"] == "MTR-44821-A"
        assert_weight(received_a["received_weight_lb"], LOT_A_WEIGHT, "lot A received")
        assert_weight(received_a["allocated_weight_lb"], 0.00, "lot A allocated")
        assert_weight(received_a["remaining_weight_lb"], LOT_A_WEIGHT, "lot A remaining")
        assert_weight(
            X.read_tank(api, tank["id"])["steel_received_lb"], LOT_A_WEIGHT, "steel received"
        )

        received_b = X.lot_transition(
            api, lot_b["id"], LOT_RECEIVED, mtr_number="MTR-44822-B"
        )
        assert_weight(received_b["received_weight_lb"], LOT_B_WEIGHT, "lot B received")
        assert_weight(received_b["remaining_weight_lb"], LOT_B_WEIGHT, "lot B remaining")

        tank_after = X.read_tank(api, tank["id"])
        assert_weight(
            tank_after["steel_received_lb"], LOT_A_WEIGHT + LOT_B_WEIGHT, "steel received"
        )
        assert_weight(tank_after["steel_allocated_lb"], 0.00, "steel allocated")


class TestCourseFitupPreconditions:
    def test_a_thickness_deficient_course_may_never_be_erected(self, api):
        """The state gate is satisfied, so the thickness gate is what answers.

        PRD: "And it requires the course's `thickness_verdict` to be `ADEQUATE`: a
        course whose ordered plate is thinner than the governing requirement may
        never be erected, and the attempt is rejected with
        `ERR_COURSE_THICKNESS_DEFICIENT`."

        Design: Corner/state_machines/fitup_precondition_blocks_thickness_deficient_course
        """
        ctx = X.foundation_accepted_tank(api)
        course = X.create_course(api, ctx.tank_id, 1, plate_thickness_in=0.3125)

        assert course["thickness_verdict"] == THICKNESS_DEFICIENT
        assert_thickness(course["required_thickness_design_in"], 0.434, "design thickness")
        assert_thickness(course["required_thickness_test_in"], 0.407, "test thickness")
        assert_thickness(course["required_thickness_in"], 0.434, "governing thickness")
        assert course["governing_case"] == GOVERNING_DESIGN

        validate_error(api.fitup(course["id"], ES1), ERR_COURSE_THICKNESS_DEFICIENT, 409)

        after = X.read_course(api, course["id"])
        assert after["status"] == COURSE_SPECIFIED
        assert after["fitup_at_utc"] is None
        assert_tank_state(X.read_tank(api, ctx.tank_id), phase=PHASE_FOUNDATION_ACCEPTED)

    def test_a_repeat_fitup_is_refused_and_keeps_the_first_timestamp(self, api):
        """The clock has moved on, but no second stamp is written.

        PRD: "It requires the course to still be `SPECIFIED` — a course already
        `FITTED`, `WELDED` or `RT_ACCEPTED` cannot be fitted up again, and a
        repeat is rejected with `ERR_COURSE_STATE_INVALID`."

        Design: Corner/state_machines/repeat_fitup_on_a_fitted_course_is_rejected
        """
        ctx = X.erecting_tank(api, clock=CLOCK_BASE)
        assert ctx.course["thickness_verdict"] == THICKNESS_ADEQUATE
        assert_instant(ctx.course["fitup_at_utc"], CLOCK_BASE, "first fitup stamp")

        X.set_clock(api, "2026-08-11T00:00:00Z")
        validate_error(api.fitup(ctx.course_id, ES1), ERR_COURSE_STATE_INVALID, 409)

        after = X.read_course(api, ctx.course_id)
        assert after["status"] == COURSE_FITTED
        assert_instant(after["fitup_at_utc"], CLOCK_BASE, "fitup stamp after the repeat")
        assert_tank_state(X.read_tank(api, ctx.tank_id), phase=PHASE_ERECTION_IN_PROGRESS)


class TestUndeclaredTransitionsAreRefused:
    def test_repair_start_on_a_fit_ready_seam_is_refused(self, api):
        """Repair is declared from rejection only, so a fresh seam has no repair.

        PRD: "The seam must be `RT_REJECTED`, or the request is rejected with
        `ERR_SEAM_STATE_INVALID`; on success it moves `RT_REJECTED →
        REPAIR_IN_PROGRESS`, and the open rejection on the seam stays open until a
        fresh examination is accepted."

        Design: Corner/state_machines/repair_start_from_fit_ready_is_an_undeclared_transition
        """
        ctx = X.erecting_tank(api, clock=CLOCK_BASE)
        seam = X.create_seam(api, ctx.course_id, "V1", 1)

        validate_error(
            api.repair_start(seam["id"], repair_start_payload(), ES1),
            ERR_SEAM_STATE_INVALID,
            409,
        )

        after = X.read_seam(api, seam["id"])
        assert after["status"] == SEAM_FIT_READY
        assert after["repair_cycle_count"] == 0
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_FITTED

    def test_dft_readings_before_the_prep_step_compute_nothing(self, api):
        """A well-formed spot payload is still refused out of turn.

        PRD: "Every step checks that the application is in the state that step
        expects — `SPEC_ISSUED` or `REWORK_REQUIRED` for preparation,
        `PREP_ACCEPTED` for readings, `DFT_RECORDED` for the holiday test — and
        any step requested out of turn, including any step at all on a terminal
        `ACCEPTED` application, is rejected with `ERR_COATING_STEP_INVALID`."

        Design: Corner/state_machines/dft_readings_before_surface_prep_is_an_undeclared_step
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        application = X.create_coating(api, tank["id"], scope=SCOPE_EXTERNAL_COATING)
        assert application["status"] == COATING_SPEC_ISSUED

        validate_error(
            api.dft_readings(
                application["id"],
                dft_readings_payload([[8.0, 8.5, 9.0], [8.2, 8.4, 8.6]]),
                QC1,
            ),
            ERR_COATING_STEP_INVALID,
            409,
        )

        after = X.read_coating(api, application["id"])
        assert after["status"] == COATING_SPEC_ISSUED
        assert after["spot_count"] == 0
        assert after["dft_verdict"] == DFT_NOT_EVALUATED
        assert after["computed_overall_average_mils"] == 0.0
        assert after["computed_min_gauge_reading_mils"] == 0.0

    def test_reviewing_a_draft_package_never_reaches_the_review_gates(self, api):
        """No inspection schedule is computed and no phase moves.

        PRD: "The package must be `SUBMITTED` (`ERR_PACKAGE_STATE_INVALID`) and
        the acting `X-User-ID` must differ from `submitted_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/state_machines/package_review_from_draft_is_an_undeclared_transition
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        package = X.create_commissioning_package(api, tank["id"])

        validate_error(
            api.package_review(package["id"], review_payload(REVIEW_ACCEPT), AI3),
            ERR_PACKAGE_STATE_INVALID,
            409,
        )

        after = X.read_commissioning_package(api, package["id"])
        assert after["status"] == PACKAGE_DRAFT
        assert after["reviewed_by_user_id"] is None
        assert after["accepted_at_utc"] is None
        assert after["internal_inspection_interval_years"] is None
        assert after["next_internal_due_utc"] is None
        assert_tank_state(X.read_tank(api, tank["id"]), phase=PHASE_DESIGN_REGISTERED)

    def test_a_revoked_welder_accepts_no_further_qualification_action(self, api):
        """Both a renewal and a second revocation bounce off the terminal status.

        PRD: "`REVOKE` is available from either `QUALIFIED` or `LAPSED` and drives
        the welder to the terminal `REVOKED` status with `revoked_at_utc` stamped
        from the logical clock; seams the welder has already completed keep their
        status, because revocation is not retroactive."

        PRD: "A `RENEW` requested on a welder who is not `LAPSED`, and any action
        at all requested on a `REVOKED` welder, is rejected with
        `ERR_WELDER_STATE_INVALID`."

        Design: Corner/state_machines/revoked_welder_cannot_be_renewed_terminal_lockdown
        """
        X.set_clock(api, CLOCK_BASE)
        welder = X.create_welder(api)
        revoked = X.welder_action(
            api, welder["id"], ACTION_REVOKE, remarks="falsified continuity log"
        )
        assert revoked["qualification_status"] == WELDER_REVOKED
        assert_instant(revoked["revoked_at_utc"], CLOCK_BASE, "revocation stamp")

        X.set_clock(api, "2026-08-20T00:00:00Z")
        for action in (ACTION_RENEW, ACTION_REVOKE):
            validate_error(
                api.welder_qualification_action(
                    welder["id"], qualification_action_payload(action), AI1
                ),
                ERR_WELDER_STATE_INVALID,
                409,
            )

        after = X.read_welder(api, welder["id"])
        assert after["qualification_status"] == WELDER_REVOKED
        assert_instant(after["revoked_at_utc"], CLOCK_BASE, "revocation stamp")
        assert_instant(
            after["qualification_date_utc"], "2026-06-01T00:00:00Z", "performance test date"
        )


class TestDerivedParentStateAndSidewaysEffects:
    def test_the_course_flips_to_welded_only_once_the_last_seam_is_welded(self, api):
        """The parent state is re-derived after every child write, not the first.

        PRD: "It is `WELDED` when every one of its seams is `WELDED`,
        `EXAM_SCHEDULED` or `RT_ACCEPTED` and at least one seam is not yet
        `RT_ACCEPTED`."

        PRD: "The welder's continuity is refreshed from that same instant, and the host
        course's `status` is re-derived from its seams — typically `FITTED → WELDED` once
        every sibling seam is welded or better."

        Design: Corner/state_machines/course_status_bubbles_up_only_when_every_seam_is_welded
        """
        ctx = X.erecting_tank(api, clock=CLOCK_BASE)
        welder = X.create_welder(api)
        first = X.create_seam(api, ctx.course_id, "V1", 1)
        second = X.create_seam(api, ctx.course_id, "V2", 2)

        welded_first = X.weld(api, first["id"], welder["id"])
        assert welded_first["status"] == SEAM_WELDED
        assert_instant(welded_first["welded_at_utc"], CLOCK_BASE, "first weld stamp")
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_FITTED

        welded_second = X.weld(api, second["id"], welder["id"])
        assert welded_second["status"] == SEAM_WELDED
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_WELDED

        assert_tank_state(X.read_tank(api, ctx.tank_id), phase=PHASE_ERECTION_IN_PROGRESS)
        after = X.read_welder(api, welder["id"])
        assert_instant(after["last_weld_date_utc"], CLOCK_BASE, "last weld date")
        assert_instant(
            after["continuity_expires_at_utc"], "2027-02-06T00:00:00Z", "continuity expiry"
        )

    def test_a_rejected_foundation_clears_the_baseline_pointer_and_re_arms(self, api):
        """The tank phase does not move; the survey linkage does.

        PRD: "On `REJECT`, the package moves `BASELINE_SET → REJECTED`,
        `decided_by_user_id`, `decided_at_utc` and `decision_remarks` are stamped
        exactly as on the accept branch, the tank's `construction_phase` is left
        untouched at `DESIGN_REGISTERED`, and — the divergence that matters —
        `baseline_survey_id` is cleared back to null so that a fresh baseline can
        be shot after the civil rework."

        PRD: "Shooting that fresh baseline, a survey at `fill_percent` 0 against a
        package whose `baseline_survey_id` is null, moves the package `REJECTED →
        BASELINE_SET` and puts the decision back in front of the engineer."

        Design: Corner/state_machines/foundation_rejection_clears_the_baseline_pointer_cross_entity
        """
        ctx = X.tank_with_baseline(api)
        assert ctx.package["status"] == PKG_BASELINE_SET
        assert ctx.package["baseline_survey_id"] == ctx.baseline_id

        rejected = X.accept_foundation(
            api,
            ctx.package_id,
            DECISION_REJECT,
            decision_remarks="ringwall out of level, regrade required",
        )
        assert rejected["status"] == PKG_REJECTED
        assert rejected["decision_remarks"] == "ringwall out of level, regrade required"
        assert rejected["decided_by_user_id"] == PE1_ID
        assert_instant(rejected["decided_at_utc"], CLOCK_BASE, "decision stamp")
        assert rejected["baseline_survey_id"] is None
        assert_tank_state(X.read_tank(api, ctx.tank_id), phase=PHASE_DESIGN_REGISTERED)

        first_survey = X.read_survey(api, ctx.baseline_id)
        assert first_survey["survey_role"] == SURVEY_ROLE_BASELINE
        assert first_survey["verdict"] == VERDICT_BASELINE
        assert first_survey["nonconformance_state"] == NC_NOT_APPLICABLE

        re_shot = X.create_survey(api, ctx.package_id, [99.500] * 8, 0.0)
        assert re_shot["survey_role"] == SURVEY_ROLE_BASELINE

        package = X.read_foundation_package(api, ctx.package_id)
        assert package["status"] == PKG_BASELINE_SET
        assert package["baseline_survey_id"] == re_shot["id"]
        assert_list_total(
            api.list_settlement_surveys(CC1, {"foundation_package_id": ctx.package_id}), 2
        )
