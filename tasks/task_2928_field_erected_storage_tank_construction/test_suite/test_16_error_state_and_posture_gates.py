"""Error catalogue, part two: state gates, posture gates and evidence gates.

Each case here drives one endpoint into the guard that owns it, checks that the
refusal wrote nothing, and then repeats the identical request once the missing
precondition is in place, so the error identifier is pinned to the precondition
rather than to the request shape.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_APPURTENANCES_NOT_INSTALLED,
    ERR_APPURTENANCE_STATE_INVALID,
    ERR_DFT_NOT_PASSED,
    ERR_FILL_PERCENT_NOT_ADVANCING,
    ERR_INDICATION_COUNT_INCONSISTENT,
    ERR_INVALID_WINDOW,
    ERR_MISSING_COMMISSIONING_DOCUMENTS,
    ERR_NDE_STATE_INVALID,
    ERR_SETTLEMENT_HOLD_POINT_MISSING,
    ERR_TANK_POSTURE_FROZEN,
    ERR_WELD_SEQUENCE_VIOLATION,
)
from test_helpers.assertions import (
    assert_instant,
    assert_list_total,
    assert_object_envelope,
    assert_thickness,
    assert_weight,
)
from test_helpers.constants import (
    APP_INSTALLED,
    APP_DESIGNED,
    CLOCK_BASE,
    COATING_DFT_RECORDED,
    COATING_REWORK_REQUIRED,
    COATING_SPEC_ISSUED,
    COURSE_FITTED,
    COURSE_SPECIFIED,
    COURSE_WELDED,
    DECISION_ACCEPT,
    DECISION_REJECT,
    DEFECT_CRACK,
    DEFECT_POROSITY,
    DEFECT_SLAG_INCLUSION,
    DFT_FAIL,
    DOC_AS_BUILT_DRAWING,
    DOC_HYDROTEST_RECORD,
    DOC_MILL_TEST_REPORTS,
    DOC_RT_FILM_LOG,
    NDE_REPORTED_ACCEPT,
    NDE_SCHEDULED,
    NDE_VOIDED,
    PACKAGE_DRAFT,
    PACKAGE_SUBMITTED,
    PHASE_COATED,
    PHASE_DESIGN_REGISTERED,
    PLAN_FILLING,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    PREP_SSPC_SP10,
    PREP_SSPC_SP6,
    SCOPE_EXTERNAL_COATING,
    SEAM_EXAM_SCHEDULED,
    SEAM_FIT_READY,
    SEAM_RT_ACCEPTED,
    SEAM_WELDED,
    SURVEY_ROLE_MONITORING,
    VERDICT_WITHIN_TOLERANCE,
)
from test_helpers.factories import (
    allocation_payload,
    fill_advance_payload,
    holiday_test_payload,
    installation_payload,
    nde_report_payload,
    nde_result_payload,
    submission_payload,
    surface_prep_payload,
    weld_log_payload,
)
from test_helpers.test_users import CC1, ES1, PE1, PE1_ID, QC1, welder_headers


class TestNdeSchedulingAndEvidence:
    def test_three_rules_guard_one_radiograph_at_three_different_depths(self, api):
        """A seam state gate, a window ordering gate and a film evidence gate.

        PRD: "The window end must be strictly after the window start, or the request is rejected
        with `ERR_INVALID_WINDOW`."

        PRD: "The seam must be `WELDED` or `RT_ACCEPTED`, and the seam must not already have
        another report sitting in `SCHEDULED`; either violation is rejected with
        `ERR_NDE_STATE_INVALID`."

        PRD: "The decision must agree with the film evidence: `ACCEPT` requires
        `indication_count` to be exactly 0, and `REJECT` requires `indication_count` to be
        at least 1 **and** a `defect_type` to be present; a disagreement is rejected with
        `ERR_INDICATION_COUNT_INCONSISTENT`."

        PRD: "A new report is created at `status` `SCHEDULED` with `nonconformance_open` false,
        `reported_by_user_id` and `reported_at_utc` null, and `void_reason` null. The seam
        moves to `EXAM_SCHEDULED` and its `last_nde_report_id` is pointed at the new
        report."

        PRD: "An acceptance moves the report `SCHEDULED → REPORTED_ACCEPT` and the seam
        `EXAM_SCHEDULED → RT_ACCEPTED`."

        PRD: "The host course's `status` is re-derived — `WELDED → RT_ACCEPTED` once every
        sibling seam is accepted — and the tank's `weld_reject_rate`,
        `required_examination_pct`, `open_nonconformance_count` and `quality_posture` are
        all recomputed."

        Design: Corner/errors/nde_scheduling_and_result_evidence_violations_are_rejected
        """
        ctx = X.erecting_tank(api)
        welder = X.create_welder(api)
        first = X.create_seam(api, ctx.course_id, "V1", 1)
        second = X.create_seam(api, ctx.course_id, "V2", 2)
        X.weld(api, first["id"], welder["id"])

        validate_error(
            api.create_nde_report(
                nde_report_payload(
                    second["id"],
                    "2026-08-11T10:00:00Z",
                    "2026-08-11T11:00:00Z",
                    technician_stamp="RT-3",
                ),
                QC1,
            ),
            ERR_NDE_STATE_INVALID,
            409,
        )
        assert X.read_seam(api, second["id"])["status"] == SEAM_FIT_READY
        assert_list_total(api.list_nde_reports(QC1, {"weld_seam_id": second["id"]}), 0)

        validate_error(
            api.create_nde_report(
                nde_report_payload(
                    first["id"],
                    "2026-08-11T11:00:00Z",
                    "2026-08-11T11:00:00Z",
                    technician_stamp="RT-3",
                ),
                QC1,
            ),
            ERR_INVALID_WINDOW,
            409,
        )
        assert X.read_seam(api, first["id"])["status"] == SEAM_WELDED

        report = assert_object_envelope(
            api.create_nde_report(
                nde_report_payload(
                    first["id"],
                    "2026-08-11T10:00:00Z",
                    "2026-08-11T11:00:00Z",
                    technician_stamp="RT-3",
                ),
                QC1,
            ),
            201,
        )
        assert report["status"] == NDE_SCHEDULED
        assert report["nonconformance_open"] is False
        assert report["reported_by_user_id"] is None
        welded_seam = X.read_seam(api, first["id"])
        assert welded_seam["status"] == SEAM_EXAM_SCHEDULED
        assert welded_seam["last_nde_report_id"] == report["id"]

        validate_error(
            api.create_nde_report(
                nde_report_payload(
                    first["id"],
                    "2026-08-11T20:00:00Z",
                    "2026-08-11T21:00:00Z",
                    technician_stamp="RT-4",
                ),
                QC1,
            ),
            ERR_NDE_STATE_INVALID,
            409,
        )
        assert_list_total(api.list_nde_reports(QC1, {"weld_seam_id": first["id"]}), 1)

        validate_error(
            api.nde_result(report["id"], nde_result_payload(DECISION_ACCEPT, 2, 4), QC1),
            ERR_INDICATION_COUNT_INCONSISTENT,
            409,
        )
        validate_error(
            api.nde_result(
                report["id"],
                nde_result_payload(DECISION_REJECT, 0, 4, DEFECT_POROSITY),
                QC1,
            ),
            ERR_INDICATION_COUNT_INCONSISTENT,
            409,
        )
        refused = X.read_nde_report(api, report["id"])
        assert refused["status"] == NDE_SCHEDULED
        assert refused["reported_at_utc"] is None
        assert refused["reported_by_user_id"] is None

        accepted = assert_object_envelope(
            api.nde_result(report["id"], nde_result_payload(DECISION_ACCEPT, 0, 4), QC1),
            200,
        )
        assert accepted["status"] == NDE_REPORTED_ACCEPT
        assert accepted["indication_count"] == 0
        assert X.read_seam(api, first["id"])["status"] == SEAM_RT_ACCEPTED
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_FITTED


class TestWeldSequence:
    def test_the_same_weld_log_fails_twice_and_lands_only_after_acceptance(self, api):
        """A predecessor that is WELDED, and then EXAM_SCHEDULED, still blocks its successor.

        PRD: "And where the seam has a `predecessor_seam_id`, that predecessor must already have
        reached `RT_ACCEPTED`, because distortion control depends on the sequence being
        honoured; welding out of sequence is rejected with `ERR_WELD_SEQUENCE_VIOLATION`."

        PRD: "On success the seam moves to `WELDED` — either `FIT_READY → WELDED` for a first
        weld or `REPAIR_IN_PROGRESS → WELDED` for a re-weld after excavation, in which
        case `repair_cycle_count` is incremented by 1."

        PRD: "`welder_id` and `filler_lot` are recorded (both overwritten on each repair
        re-weld), and `welded_at_utc` is set to `completed_at_utc` when supplied and
        otherwise to the logical clock. The welder's continuity is refreshed from that
        same instant, and the host course's `status` is re-derived from its seams —
        typically `FITTED → WELDED` once every sibling seam is welded or better."

        Design: Corner/errors/weld_log_ahead_of_its_predecessor_seam_is_rejected
        """
        ctx = X.erecting_tank(api)
        welder = X.create_welder(api)
        leader = X.create_seam(api, ctx.course_id, "A", 1)
        follower = X.create_seam(api, ctx.course_id, "B", 2, predecessor_seam_id=leader["id"])
        assert follower["predecessor_seam_id"] == leader["id"]
        X.weld(api, leader["id"], welder["id"])
        assert X.read_seam(api, leader["id"])["status"] == SEAM_WELDED

        headers = welder_headers(welder["id"])
        payload = weld_log_payload(welder["id"])

        validate_error(
            api.weld_log(follower["id"], payload, headers),
            ERR_WELD_SEQUENCE_VIOLATION,
            409,
        )
        blocked = X.read_seam(api, follower["id"])
        assert blocked["status"] == SEAM_FIT_READY
        assert blocked["welder_id"] is None
        assert blocked["welded_at_utc"] is None

        report = X.schedule_nde(
            api, leader["id"], "2026-08-11T10:00:00Z", "2026-08-11T11:00:00Z"
        )
        assert X.read_seam(api, leader["id"])["status"] == SEAM_EXAM_SCHEDULED

        validate_error(
            api.weld_log(follower["id"], payload, headers),
            ERR_WELD_SEQUENCE_VIOLATION,
            409,
        )
        blocked = X.read_seam(api, follower["id"])
        assert blocked["status"] == SEAM_FIT_READY
        assert blocked["welder_id"] is None

        X.report_nde(api, report["id"], DECISION_ACCEPT, 0, 4)
        assert X.read_seam(api, leader["id"])["status"] == SEAM_RT_ACCEPTED
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_FITTED

        welded = assert_object_envelope(api.weld_log(follower["id"], payload, headers), 200)
        assert welded["status"] == SEAM_WELDED
        assert welded["welder_id"] == welder["id"]
        assert_instant(welded["welded_at_utc"], CLOCK_BASE, "weld stamp")
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_WELDED


class TestFillAdvanceGuards:
    def test_a_repeat_level_masks_the_hold_point_the_cited_survey_does_not_cover(self, api):
        """Equal is not an advance, and yesterday's survey is not this hold point's evidence.

        PRD: "The target must be strictly greater than the plan's `fill_percent_current`;
        refilling to the same level or draining is not an advance and is rejected with
        `ERR_FILL_PERCENT_NOT_ADVANCING`."

        PRD: "Four fill levels — 25, 50, 75 and 100 percent — are mandatory settlement hold
        points, and an advance to any of them must carry a `settlement_survey_id` whose
        survey belongs to the tank's foundation package, whose own `fill_percent` equals
        the requested `target_fill_percent`, and whose `verdict` is `WITHIN_TOLERANCE`; a
        missing or non-matching survey is rejected with
        `ERR_SETTLEMENT_HOLD_POINT_MISSING`."

        PRD: "Each advance sets `fill_percent_current` to the target and increments
        `settlement_survey_count` by 1 whenever a survey is supplied."

        PRD: "An advance from `APPROVED` with a target above 0 and below 100 moves the plan
        `APPROVED → FILLING`; a further advance below 100 keeps it `FILLING`; and an
        advance to exactly 100 moves it `FILLING → FILL_HOLD` and stamps
        `hold_started_at_utc` from the logical clock."

        PRD: "Every later survey on the package has `survey_role` `MONITORING` and is evaluated
        against that original baseline, matched point index to point index — never against
        the previous monitoring round."

        Design: Corner/errors/non_advancing_fill_and_mismatched_hold_point_are_rejected
        """
        ctx = X.approved_plan_with_water(api)
        first_survey = X.create_survey(
            api, ctx.package_id, X.SETTLED_2IN, 25.0, hydrotest_plan_id=ctx.plan_id
        )
        plan = X.fill_advance(api, ctx.plan_id, 25.0, first_survey["id"])
        assert plan["status"] == PLAN_FILLING
        assert plan["fill_percent_current"] == 25.0
        assert plan["settlement_survey_count"] == 1

        validate_error(
            api.fill_advance(
                ctx.plan_id, fill_advance_payload(25.0, first_survey["id"]), ES1
            ),
            ERR_FILL_PERCENT_NOT_ADVANCING,
            409,
        )
        validate_error(
            api.fill_advance(
                ctx.plan_id, fill_advance_payload(10.0, first_survey["id"]), ES1
            ),
            ERR_FILL_PERCENT_NOT_ADVANCING,
            409,
        )
        validate_error(
            api.fill_advance(
                ctx.plan_id, fill_advance_payload(50.0, first_survey["id"]), ES1
            ),
            ERR_SETTLEMENT_HOLD_POINT_MISSING,
            409,
        )

        held = X.read_plan(api, ctx.plan_id)
        assert held["status"] == PLAN_FILLING
        assert held["fill_percent_current"] == 25.0
        assert held["settlement_survey_count"] == 1

        second_survey = X.create_survey(
            api, ctx.package_id, X.SETTLED_2IN, 50.0, hydrotest_plan_id=ctx.plan_id
        )
        assert second_survey["survey_role"] == SURVEY_ROLE_MONITORING
        assert second_survey["verdict"] == VERDICT_WITHIN_TOLERANCE
        assert second_survey["fill_percent"] == 50.0
        assert_thickness(second_survey["uniform_settlement_in"], 2.000, "uniform settlement")

        advanced = assert_object_envelope(
            api.fill_advance(
                ctx.plan_id, fill_advance_payload(50.0, second_survey["id"]), ES1
            ),
            200,
        )
        assert advanced["fill_percent_current"] == 50.0
        assert advanced["settlement_survey_count"] == 2
        assert advanced["status"] == PLAN_FILLING
        assert advanced["hold_started_at_utc"] is None


class TestFrozenTankStopWork:
    def test_the_third_rejection_stops_unrelated_work_until_a_void_thaws_it(self, api):
        """A stop-work order nobody requested, and the whitelist it deliberately leaves open.

        PRD: "A `FROZEN` tank accepts no production work at all — no course fit-up, no weld log,
        no plate allocation, no fill advance, no coating step, no appurtenance
        installation, no operator phase transition, no hydrostatic plan approval and no
        commissioning submission — and any such attempt is rejected with
        `ERR_TANK_POSTURE_FROZEN` (HTTP 409)."

        PRD: "Only the operations that can *close* a nonconformance remain available on a frozen
        tank: reporting examination results, voiding examination reports, recording
        settlement surveys, and welder qualification actions."

        PRD: "`quality_posture` is then `OPEN` when the count is zero, `RESTRICTED` when the
        count is 1 or 2 inclusive, and `FROZEN` when the count is 3 or more."

        PRD: "That void moves the report `REPORTED_REJECT → VOIDED` with `nonconformance_open`
        set to false and `void_reason` stored, returns the seam `RT_REJECTED → WELDED`
        **without** incrementing `repair_cycle_count`, decrements the tank's
        `open_nonconformance_count` and recomputes `quality_posture` — a return to `OPEN`
        restoring every suspended plan of the tank to its `state_before_suspension` — and
        recomputes the reject rate and required examination percentage with this report
        excluded from the examined population."

        PRD: "Those four require `quality_posture` to be exactly `OPEN`; `RESTRICTED` is
        sufficient for ordinary erection work but not for these, and an attempt made while
        the posture is `RESTRICTED` is rejected with `ERR_TANK_POSTURE_RESTRICTED` (HTTP
        409)."

        Design: Corner/errors/frozen_tank_refuses_every_production_write
        """
        ctx = X.welded_course(api, seam_labels=("V1", "V2", "V3"))
        second_course = X.create_course(api, ctx.tank_id, 2)
        lot = X.receive_plate_lot(api, ctx.tank_id, mtr_number="MTR-4471-A")
        coating = X.create_coating(
            api,
            ctx.tank_id,
            SCOPE_EXTERNAL_COATING,
            surface_area_sqft=9000.0,
            specified_prep_standard=PREP_SSPC_SP6,
            specified_min_dft_mils=8.0,
            coating_system="acrylic 3 coat",
        )
        assert coating["status"] == COATING_SPEC_ISSUED

        X.reject_examination(
            api, ctx.seams[0]["id"], window_index=0, indication_count=3,
            defect_type=DEFECT_SLAG_INCLUSION,
        )
        tank = X.read_tank(api, ctx.tank_id)
        assert tank["open_nonconformance_count"] == 1
        assert tank["quality_posture"] == POSTURE_RESTRICTED

        X.reject_examination(
            api, ctx.seams[1]["id"], window_index=1, indication_count=2,
            defect_type=DEFECT_POROSITY,
        )
        tank = X.read_tank(api, ctx.tank_id)
        assert tank["open_nonconformance_count"] == 2
        assert tank["quality_posture"] == POSTURE_RESTRICTED

        third = X.reject_examination(
            api, ctx.seams[2]["id"], window_index=2, indication_count=1,
            defect_type=DEFECT_CRACK,
        )
        tank = X.read_tank(api, ctx.tank_id)
        assert tank["open_nonconformance_count"] == 3
        assert tank["quality_posture"] == POSTURE_FROZEN

        validate_error(api.fitup(second_course["id"], ES1), ERR_TANK_POSTURE_FROZEN, 409)
        assert X.read_course(api, second_course["id"])["status"] == COURSE_SPECIFIED

        validate_error(
            api.plate_lot_allocation(
                lot["id"], allocation_payload(second_course["id"], 8000.0), ES1
            ),
            ERR_TANK_POSTURE_FROZEN,
            409,
        )
        held_lot = X.read_plate_lot(api, lot["id"])
        assert_weight(held_lot["allocated_weight_lb"], 0.00, "lot allocated weight")
        assert_weight(held_lot["remaining_weight_lb"], 12505.00, "lot remaining weight")

        validate_error(
            api.surface_prep(
                coating["id"], surface_prep_payload(PREP_SSPC_SP10, 2.5, 9.0), QC1
            ),
            ERR_TANK_POSTURE_FROZEN,
            409,
        )
        assert X.read_coating(api, coating["id"])["status"] == COATING_SPEC_ISSUED

        survey = X.create_survey(api, ctx.package_id, [99.900] * 8, headers=CC1)
        assert survey["survey_role"] == SURVEY_ROLE_MONITORING
        assert survey["verdict"] == VERDICT_WITHIN_TOLERANCE
        assert_thickness(survey["uniform_settlement_in"], 0.100, "uniform settlement")

        voided = X.void_nde(
            api, third["id"], void_reason="film mislabelled - wrong seam radiographed"
        )
        assert voided["status"] == NDE_VOIDED
        assert voided["nonconformance_open"] is False
        tank = X.read_tank(api, ctx.tank_id)
        assert tank["open_nonconformance_count"] == 2
        assert tank["quality_posture"] == POSTURE_RESTRICTED
        assert X.read_seam(api, ctx.seams[2]["id"])["status"] == SEAM_WELDED

        thawed = assert_object_envelope(api.fitup(second_course["id"], ES1), 200)
        assert thawed["status"] == COURSE_FITTED


class TestHolidayTestOverAFailedDft:
    def test_the_clean_test_is_refused_and_the_dirty_one_is_recorded(self, api):
        """The same endpoint turns away the good news and books the bad news.

        PRD: "A test reporting zero holidays may only be accepted when `dft_verdict` is `PASS`;
        a `FAIL` verdict must be reworked no matter how clean the holiday test came back,
        and the attempt is rejected with `ERR_DFT_NOT_PASSED`."

        PRD: "An `EXTERNAL_COATING` scope has no voltage floor whatsoever."

        PRD: "Under `SPOT_AVERAGE_80_120` a `PASS` requires all three of: every per-spot average
        at or above 0.80 times `specified_min_dft_mils`; every per-spot average at or
        below 1.20 times `specified_min_dft_mils`; and `computed_overall_average_mils` at
        or above `specified_min_dft_mils`."

        PRD: "First, the application moves `DFT_RECORDED → REWORK_REQUIRED` with
        `holidays_found` and `holiday_test_voltage_v` stored. Second, the tank's posture
        is recomputed: an open coating rework counts as one nonconformance, so a
        previously `OPEN` tank becomes `RESTRICTED`."

        PRD: "Each link is conditional on its own precondition, so a tank that was never
        `COATED` skips link three and a tank with no submitted package skips link four."

        Design: Corner/errors/clean_holiday_test_over_a_failed_dft_is_rejected
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        coating = X.create_coating(
            api,
            tank["id"],
            SCOPE_EXTERNAL_COATING,
            surface_area_sqft=9000.0,
            specified_prep_standard=PREP_SSPC_SP6,
            specified_min_dft_mils=10.0,
            coating_system="acrylic 3 coat",
        )
        X.surface_prep(
            api, coating["id"], achieved_prep_standard=PREP_SSPC_SP6,
            profile_mils=2.5, dew_point_spread_f=9.0,
        )
        recorded = X.dft_readings(api, coating["id"], [[6.0, 6.0, 6.0]])
        assert recorded["status"] == COATING_DFT_RECORDED
        assert recorded["spot_count"] == 1
        assert_thickness(recorded["computed_spot_average_min_mils"], 6.00, "spot average min")
        assert_thickness(recorded["computed_spot_average_max_mils"], 6.00, "spot average max")
        assert_thickness(recorded["computed_overall_average_mils"], 6.00, "overall average")
        assert recorded["dft_verdict"] == DFT_FAIL

        validate_error(
            api.holiday_test(coating["id"], holiday_test_payload(0, 200.0), QC1),
            ERR_DFT_NOT_PASSED,
            409,
        )
        refused = X.read_coating(api, coating["id"])
        assert refused["status"] == COATING_DFT_RECORDED
        assert refused["holidays_found"] is None
        assert refused["holiday_test_voltage_v"] is None

        reworked = assert_object_envelope(
            api.holiday_test(coating["id"], holiday_test_payload(2, 200.0), QC1), 200
        )
        assert reworked["status"] == COATING_REWORK_REQUIRED
        assert reworked["holidays_found"] == 2
        assert reworked["holiday_test_voltage_v"] == 200.0

        tank = X.read_tank(api, tank["id"])
        assert tank["open_nonconformance_count"] == 1
        assert tank["quality_posture"] == POSTURE_RESTRICTED
        assert tank["construction_phase"] == PHASE_DESIGN_REGISTERED


class TestAppurtenanceInstallationIsTerminal:
    def test_the_second_installation_is_refused_and_keeps_the_first_stamp(self, api):
        """INSTALLED is terminal, so the repeat is not an idempotent re-record.

        PRD: "Installation is recorded by the `ErectionSuperintendent`, optionally supplying
        `installed_at_utc`; when omitted, the installation instant is taken from the
        logical clock."

        PRD: "The appurtenance must be `DESIGNED`, or the request is rejected with
        `ERR_APPURTENANCE_STATE_INVALID`; the tank must not be `FROZEN`; and the host
        shell course must already be `RT_ACCEPTED`, since nobody cuts a hole in plate
        whose seams have not yet been radiographically accepted — a course in any other
        state is rejected with `ERR_HOST_COURSE_NOT_ACCEPTED`."

        PRD: "For a `NOZZLE` or a `MANWAY` it is the greater of 8.0 degrees and
        `nominal_size_in` multiplied by 1.5, so small nozzles all sit at the 8.0-degree
        floor while a size above 5.333… inches begins to drive the requirement upward."

        PRD: "On success the appurtenance moves `DESIGNED → INSTALLED`, which is terminal, and
        `installed_at_utc` is stamped."

        PRD: "The latter pair deserves care: `designed_appurtenance_count` is the size of the
        tank's whole design set — every appurtenance row of the tank whatever its status —
        while `installed_appurtenance_count` counts only the subset already installed, so
        the two are equal exactly when the appurtenance scope is complete."

        PRD: "`version` is an integer that starts at 1 when the resource is created and
        increases by exactly 1 on every mutation of that resource; `updated_at` is
        refreshed on the same mutation."

        Design: Corner/errors/installing_an_already_installed_appurtenance_is_rejected
        """
        ctx = X.rt_accepted_course(api)
        appurtenance = X.create_appurtenance(
            api, ctx.tank_id, ctx.course_id, nominal_size_in=6.0, azimuth_deg=0.0
        )
        assert appurtenance["status"] == APP_DESIGNED
        assert appurtenance["installed_at_utc"] is None
        assert appurtenance["required_clearance_deg"] == 9.0
        assert appurtenance["version"] == 1

        installed = assert_object_envelope(
            api.appurtenance_installation(
                appurtenance["id"], installation_payload("2026-08-12T08:00:00Z"), ES1
            ),
            200,
        )
        assert installed["status"] == APP_INSTALLED
        assert_instant(installed["installed_at_utc"], "2026-08-12T08:00:00Z", "installation stamp")
        assert installed["required_clearance_deg"] == 9.0
        assert installed["version"] == 2

        validate_error(
            api.appurtenance_installation(
                appurtenance["id"], installation_payload("2026-08-20T08:00:00Z"), ES1
            ),
            ERR_APPURTENANCE_STATE_INVALID,
            409,
        )

        after = X.read_appurtenance(api, appurtenance["id"])
        assert after["status"] == APP_INSTALLED
        assert_instant(after["installed_at_utc"], "2026-08-12T08:00:00Z", "installation stamp")
        assert after["version"] == 2

        summary = assert_object_envelope(api.get_tank_summary(ctx.tank_id, PE1), 200)
        assert summary["installed_appurtenance_count"] == 1
        assert summary["designed_appurtenance_count"] == 1


class TestCommissioningSubmissionGates:
    def test_the_uninstalled_nozzle_is_reported_before_the_missing_drawing(self, api):
        """The physical scope gate precedes the paperwork gate on the same request.

        PRD: "`missing_document_types` must be empty, a shortfall being rejected with
        `ERR_MISSING_COMMISSIONING_DOCUMENTS`. Every appurtenance of the tank must be
        `INSTALLED`, any still `DESIGNED` causing rejection with
        `ERR_APPURTENANCES_NOT_INSTALLED`."

        PRD: "On success the package moves `DRAFT → SUBMITTED`, or `RETURNED_FOR_CORRECTION →
        SUBMITTED` on a re-submission after correction, and `submitted_by_user_id` records
        the acting `X-User-ID`, overwriting any earlier value so that the operator barred
        from reviewing is always the one who submitted most recently."

        PRD: "`submitted_document_types` holds the distinct types recorded, emitted in the
        required order first and then any extra types in the order they were first
        recorded, and `missing_document_types` is the required list minus the submitted
        types, preserving the required order."

        PRD: "Next come the referential checks: same-tank agreement between every entity
        referenced in one request (`ERR_CROSS_TANK_REFERENCE`), then the
        accepted-foundation precondition for fit-up and weld logging
        (`ERR_FOUNDATION_NOT_ACCEPTED`), then the host-course acceptance precondition for
        appurtenance installation (`ERR_HOST_COURSE_NOT_ACCEPTED`), then the
        all-appurtenances-installed precondition for commissioning submission
        (`ERR_APPURTENANCES_NOT_INSTALLED`)."

        PRD: "Then come the constraint checks, in this order: weld sequence honoured
        (`ERR_WELD_SEQUENCE_VIOLATION`), predecessor chain acyclic
        (`ERR_SEAM_SEQUENCE_CYCLE`), scoped uniqueness (`ERR_DUPLICATE_IDENTIFIER`),
        singleton packages (`ERR_SINGLETON_EXISTS`), survey point completeness
        (`ERR_INSUFFICIENT_SURVEY_POINTS`), appurtenance clearance
        (`ERR_APPURTENANCE_CLEARANCE_VIOLATION`), commissioning document completeness
        (`ERR_MISSING_COMMISSIONING_DOCUMENTS`), fill level strictly advancing
        (`ERR_FILL_PERCENT_NOT_ADVANCING`), mandatory settlement hold points
        (`ERR_SETTLEMENT_HOLD_POINT_MISSING`), and the repair-cycle cap
        (`ERR_REPAIR_LIMIT_EXCEEDED`)."

        PRD: "The package fixes `required_document_types` as the four types every tank must
        produce — `MILL_TEST_REPORTS`, `RT_FILM_LOG`, `HYDROTEST_RECORD` and
        `AS_BUILT_DRAWING`, in that order — and opens with `submitted_document_types`
        empty, `missing_document_types` equal to all four in that same order,
        `document_count` and `deficiency_count` at 0, `status` `DRAFT`,
        `submitted_by_user_id` and `reviewed_by_user_id` null, and
        `bottom_remaining_life_years`, `internal_inspection_interval_years`,
        `external_inspection_interval_years`, `next_internal_due_utc`,
        `next_external_due_utc` and `accepted_at_utc` all null."

        Design: Corner/errors/commissioning_submission_with_open_scope_or_missing_paper_is_rejected
        """
        ctx = X.coated_tank(api)
        tank = X.read_tank(api, ctx.tank_id)
        assert tank["construction_phase"] == PHASE_COATED
        assert tank["quality_posture"] == POSTURE_OPEN

        first_nozzle = X.create_appurtenance(
            api, ctx.tank_id, ctx.course_id, nominal_size_in=6.0, azimuth_deg=0.0
        )
        assert X.install_appurtenance(api, first_nozzle["id"])["status"] == APP_INSTALLED
        second_nozzle = X.create_appurtenance(
            api, ctx.tank_id, ctx.course_id, nominal_size_in=6.0, azimuth_deg=90.0
        )
        assert second_nozzle["status"] == APP_DESIGNED

        X.package_with_documents(
            api,
            ctx,
            document_types=[DOC_MILL_TEST_REPORTS, DOC_RT_FILM_LOG, DOC_HYDROTEST_RECORD],
        )
        package = X.read_commissioning_package(api, ctx.commissioning_id)
        assert package["status"] == PACKAGE_DRAFT
        assert package["document_count"] == 3
        assert package["submitted_document_types"] == [
            DOC_MILL_TEST_REPORTS,
            DOC_RT_FILM_LOG,
            DOC_HYDROTEST_RECORD,
        ]
        assert package["missing_document_types"] == [DOC_AS_BUILT_DRAWING]
        assert package["submitted_by_user_id"] is None

        validate_error(
            api.package_submission(ctx.commissioning_id, submission_payload(), PE1),
            ERR_APPURTENANCES_NOT_INSTALLED,
            409,
        )

        installed = X.install_appurtenance(api, second_nozzle["id"])
        assert installed["status"] == APP_INSTALLED

        validate_error(
            api.package_submission(ctx.commissioning_id, submission_payload(), PE1),
            ERR_MISSING_COMMISSIONING_DOCUMENTS,
            409,
        )
        still_draft = X.read_commissioning_package(api, ctx.commissioning_id)
        assert still_draft["status"] == PACKAGE_DRAFT
        assert still_draft["submitted_by_user_id"] is None

        completed = X.add_document(api, ctx.commissioning_id, DOC_AS_BUILT_DRAWING)
        assert completed["document_count"] == 4
        assert completed["missing_document_types"] == []

        submitted = assert_object_envelope(
            api.package_submission(ctx.commissioning_id, submission_payload(), PE1), 200
        )
        assert submitted["status"] == PACKAGE_SUBMITTED
        assert submitted["submitted_by_user_id"] == PE1_ID
        assert submitted["deficiency_count"] == 0
