"""Late refusals: wrong-aggregate rows, the repair budget, furnace charts, test thresholds and the nameplate."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, factories
from test_helpers.api_client import same_instant
from test_helpers.assertions import (
    assert_number_equals,
    expected_min_medium_temp,
    expected_required_soak_minutes,
    expected_test_pressure,
)
from test_helpers.constants import (
    AUDIT_TYPE_INTERNAL_QMS,
    AUDIT_TYPE_TRIENNIAL_RENEWAL,
    BATCH_STATUS_COMPLETE,
    BATCH_STATUS_IN_PROGRESS,
    BAY_2,
    CERT_STATUS_ACTIVE,
    CERT_STATUS_PROBATION,
    COMPONENT_TYPE_SHELL,
    DISPOSITION_OPEN,
    DISPOSITION_REPAIR,
    DISPOSITION_USE_AS_IS,
    EXAM_RESULT_REJECT,
    FAB_STATUS_WELDED,
    FORM_TYPE_U1,
    FURNACE_A,
    FURNACE_B,
    JOB_STATUS_DATA_PACKAGE,
    JOB_STATUS_FABRICATION,
    JOB_STATUS_NDE_HOLD,
    JOB_STATUS_STAMPED,
    JOB_STATUS_TESTING,
    NDE_STATUS_REJECTED,
    PWHT_STATUS_COMPLETE,
    PWHT_STATUS_IN_PROGRESS,
    REPORT_STATUS_AI_SIGNED,
    REPORT_STATUS_STAMPED,
    RT_EXTENT_FULL,
    RT_EXTENT_SPOT,
    SEVERITY_MAJOR,
    TEST_RESULT_PASS,
    TEST_RESULT_PENDING,
    TEST_SIDE_TUBE,
    TEST_TYPE_HYDROSTATIC,
    TEST_TYPE_PNEUMATIC,
)


def test_rows_from_the_neighbouring_vessel_are_refused_and_the_welder_gates_hold(
    client, shop, admin_headers
):
    """Two vessels share a shop but not their rows, and a fully welded map still owes its radiography.

    PRD §3.5: "Both named pieces must belong to the same job as the joint, or the request draws `ERR_PART_NOT_IN_JOB`."

    PRD §3.8: "The job must be in `FABRICATION` or `NDE_HOLD`, and every named joint must belong to that job, or the request draws `ERR_WELD_NOT_IN_JOB`."

    PRD §3.5: "The qualification's `wps_id` must equal the joint's `wps_id`, or the request draws `ERR_QUALIFICATION_WPS_MISMATCH`: a welder qualified under a different procedure than the joint cites is not permitted to make it even when both procedures share a process."

    PRD §3.5: "The joint's `thickness_in` must be at most the qualification's `thickness_range_max_in`, or the request draws `ERR_THICKNESS_OUTSIDE_QUALIFICATION` — note that the qualification carries only a ceiling, whereas the procedure carries a two-sided window, so a joint can clear the procedure's window and still exceed the welder's."

    PRD §3.5: "The joint must be `PLANNED`."

    PRD §3.6: "For a Category A joint, a `FULL` declaration gives 100, a `SPOT` declaration gives 25 and a `NONE` declaration gives 0."

    PRD §3.6: "The numerator counts the job's joints whose `fab_status` is `WELDED` **and** whose `nde_status` is `ACCEPTED` **and** whose `pwht_status` is either `NOT_REQUIRED` or `COMPLETE`; a joint failing any one of the three is not counted."

    PRD §3.8: "Every joint's `nde_status` must be `ACCEPTED`, with one exemption: a joint still at `NOT_PLANNED` passes only when its `required_volumetric_pct` is 0 **and** its `required_surface_method` is null, meaning nothing was ever owed on it; any other posture draws `ERR_NDE_INCOMPLETE`."

    Design: Corner/errors/error_cross_aggregate_and_welder_qualification_family_at_completion
    """
    certificate = shop.certificate(cert_number="CA-U-8930")
    engineer = shop.welding_engineer()
    inspector = shop.qc_inspector()

    vessel_a = shop.fabricating_job(
        rt_extent_declared=RT_EXTENT_SPOT,
        joint_count=2,
        thickness_in=0.7500,
        quantity_received_lb=4000.00,
        certificate=certificate,
        job_overrides={"job_number": "J-2885-C46"},
    )
    vessel_b = shop.fabricating_job(
        rt_extent_declared=RT_EXTENT_SPOT,
        joint_count=1,
        thickness_in=0.7500,
        quantity_received_lb=4000.00,
        certificate=certificate,
        job_overrides={"job_number": "J-2885-C47"},
    )
    for joint in vessel_a.welds:
        assert shop.read_joint(joint["id"])["required_volumetric_pct"] == 25

    foreign_piece = client.plan_weld(
        vessel_a.job["id"],
        factories.production_weld_payload(
            vessel_a.wps["id"],
            vessel_b.parts[COMPONENT_TYPE_SHELL]["id"],
            weld_number="W-203",
            thickness_in=0.7500,
        ),
        shop.acting_as(engineer),
    )
    validate_error(foreign_piece, api_errors.ERR_PART_NOT_IN_JOB, 409)

    foreign_joint = client.create_pwht_batch(
        factories.pwht_batch_payload(vessel_a.job["id"], [vessel_b.welds[0]["id"]]),
        shop.acting_as(engineer),
    )
    validate_error(foreign_joint, api_errors.ERR_WELD_NOT_IN_JOB, 409)

    _, map_meta = validate_paginated(
        client.list_welds(
            admin_headers, params={"job_id": vessel_a.job["id"], "limit": 10, "offset": 0}
        )
    )
    assert map_meta["total_count"] == 2

    wrong_procedure = client.complete_weld(
        vessel_a.welds[0]["id"],
        factories.weld_complete_payload(
            vessel_b.qualification["id"], welded_at="2026-07-20T10:00:00.000Z"
        ),
        shop.acting_as(engineer),
    )
    validate_error(wrong_procedure, api_errors.ERR_QUALIFICATION_WPS_MISMATCH, 409)

    thin_welder = shop.welder_qualification(
        vessel_a.wps["id"],
        welder_stamp="W-91",
        welder_name="Ivo Marsh",
        thickness_range_max_in=0.5000,
    )
    beyond_ceiling = client.complete_weld(
        vessel_a.welds[0]["id"],
        factories.weld_complete_payload(thin_welder["id"], welded_at="2026-07-20T10:00:00.000Z"),
        shop.acting_as(engineer),
    )
    validate_error(beyond_ceiling, api_errors.ERR_THICKNESS_OUTSIDE_QUALIFICATION, 409)

    welded = validate_success(
        client.complete_weld(
            vessel_a.welds[0]["id"],
            factories.weld_complete_payload(
                vessel_a.qualification["id"], welded_at="2026-07-20T10:00:00.000Z"
            ),
            shop.acting_as(engineer),
        ),
        200,
    )
    assert welded["fab_status"] == FAB_STATUS_WELDED
    assert welded["welder_qualification_id"] == vessel_a.qualification["id"]
    assert same_instant(welded["welded_at"], "2026-07-20T10:00:00.000Z")

    replay = client.complete_weld(
        vessel_a.welds[0]["id"],
        factories.weld_complete_payload(
            vessel_a.qualification["id"], welded_at="2026-07-21T10:00:00.000Z"
        ),
        shop.acting_as(engineer),
    )
    validate_error(replay, api_errors.ERR_INVALID_WELD_STATE, 409)
    unchanged = shop.read_joint(vessel_a.welds[0]["id"])
    assert same_instant(unchanged["welded_at"], "2026-07-20T10:00:00.000Z")

    shop.complete_joint(
        vessel_a.welds[1]["id"],
        vessel_a.qualification["id"],
        welded_at="2026-07-20T11:00:00.000Z",
    )

    fully_welded = shop.read_job(vessel_a.job["id"])
    assert_number_equals(fully_welded["weld_completion_pct"], 0.00, 2, "weld_completion_pct")
    for joint in vessel_a.welds:
        _, exam_meta = validate_paginated(
            client.list_exams(admin_headers, params={"weld_id": joint["id"], "limit": 10, "offset": 0})
        )
        assert exam_meta["total_count"] == 0

    premature = client.create_pressure_test(
        factories.pressure_test_payload(vessel_a.job["id"]), shop.acting_as(inspector)
    )
    validate_error(premature, api_errors.ERR_NDE_INCOMPLETE, 409)
    assert shop.read_job(vessel_a.job["id"])["status"] == JOB_STATUS_FABRICATION
    _, test_meta = validate_paginated(
        client.list_pressure_tests(
            admin_headers, params={"job_id": vessel_a.job["id"], "limit": 10, "offset": 0}
        )
    )
    assert test_meta["total_count"] == 0


def test_the_repair_loop_runs_out_of_generations_before_it_runs_out_of_indications(
    client, shop, admin_headers
):
    """One rejected radiograph is driven around the repair cycle until the budget of two generations is spent.

    PRD §3.6: "Both branches share three preconditions: the examination must still be `PENDING`, or the request draws `ERR_INVALID_EXAM_STATE`; the examined joint's `fab_status` must be `WELDED`; and `exam_date` must be on or after the calendar date of the joint's `welded_at`, since a joint cannot be examined before it exists."

    PRD §3.6: "A `REJECT` moves the joint `nde_status` `PLANNED → REJECTED` and triggers the full cascade: a nonconformance report is raised with `source` `NDE_REJECT` and `disposition` `OPEN`, the job's `nonconformance_open_count` increases by 1, the job moves `FABRICATION → NDE_HOLD`, every data report of the job re-derives `completeness_score` and `missing_items`, and every data report of the job sitting at `AI_SIGNED` is pushed to `STAMP_HOLD`."

    PRD §3.7: "`severity` is derived, not supplied: it is `MAJOR` when `source` is `PRESSURE_TEST_FAIL`, or when the failed joint's `joint_category` is `A` or `B`, and `MINOR` in every other case — a rejected nozzle attachment is minor, a rejected main seam is not."

    PRD §3.9: "Assembly is refused with `ERR_OPEN_NONCONFORMANCE` while the job's `nonconformance_open_count` is above 0, and with `ERR_TRACEABILITY_INCOMPLETE` when any part of the job has `heat_traceability_complete` false."

    PRD §3.7: "A `QCInspector` who asks for `USE_AS_IS` is refused with `ERR_AI_CONCURRENCE_REQUIRED` even though the same role may freely ask for `REPAIR` on the same report — the two sibling branches of one endpoint carry deliberately different authority."

    PRD §3.7: "Both branches require the report to be `OPEN` and the job to be in `NDE_HOLD`."

    PRD §3.7: "Raising a **repair joint** is a `WeldingEngineer` action taken against a report already dispositioned `REPAIR`; a report in any other posture draws `ERR_INVALID_NONCONFORMANCE_STATE`, and the job must be in `NDE_HOLD`."

    PRD §3.7: "The new joint's `repair_of_weld_id` is set to the report's `weld_id`, its `repair_generation` is the parent joint's `repair_generation` plus 1, and its `joint_category`, `joint_type`, `thickness_in`, `part_a_id` and `part_b_id` are copied from the parent."

    PRD §3.6: "A joint whose `repair_of_weld_id` is not null takes 100 unconditionally — every repair is fully radiographed regardless of what the original joint required or what the design declared."

    PRD §3.6: "The candidate set is every weld of the job whose `fab_status` is `WELDED` and whose `nde_status` is `NOT_PLANNED`; joints that are still `PLANNED`, and joints already past `NOT_PLANNED`, are skipped, which is what makes re-invocation safe and non-duplicating."

    PRD §3.7: "A report at `REPAIR` moves `REPAIR → OPEN` when an examination of the repair joint records `REJECT`; because both `REPAIR` and `OPEN` sit inside the open set, `nonconformance_open_count` is unchanged by that move and the job stays in `NDE_HOLD`."

    PRD §3.7: "The cycle `OPEN → REPAIR → OPEN` is therefore traversable, once per generation, until `repair_generation` reaches the limit of 2, at which point the next disposition attempt fails with `ERR_REPAIR_LIMIT_EXCEEDED` and the only remaining route out is `USE_AS_IS` with Authorized Inspector concurrence, or cancellation of the job."

    Design: Corner/errors/error_nonconformance_lifecycle_family_through_the_repair_limit
    """
    inspector = shop.qc_inspector()
    scenario = shop.welded_job(
        rt_extent_declared=RT_EXTENT_FULL,
        joint_count=2,
        thickness_in=0.7500,
        quantity_received_lb=2000.00,
        job_overrides={"job_number": "J-2885-C48"},
    )
    parent_joint = scenario.welds[0]

    exams = shop.run_nde_plan(scenario.job["id"])
    exam_by_joint = dict((exam["weld_id"], exam) for exam in exams)
    assert sorted(exam_by_joint) == sorted(joint["id"] for joint in scenario.welds)

    rejected = validate_success(
        client.record_exam_result(
            exam_by_joint[parent_joint["id"]]["id"],
            factories.exam_reject_payload(indications_count=3, exam_date="2026-08-02"),
            shop.acting_as(inspector),
        ),
        200,
    )
    assert rejected["result"] == EXAM_RESULT_REJECT
    assert shop.read_joint(parent_joint["id"])["nde_status"] == NDE_STATUS_REJECTED
    held = shop.read_job(scenario.job["id"])
    assert held["status"] == JOB_STATUS_NDE_HOLD
    assert held["nonconformance_open_count"] == 1

    overwrite = client.record_exam_result(
        exam_by_joint[parent_joint["id"]]["id"],
        factories.exam_result_payload(exam_date="2026-08-03"),
        shop.acting_as(inspector),
    )
    validate_error(overwrite, api_errors.ERR_INVALID_EXAM_STATE, 409)

    blocked_package = client.assemble_data_report(
        scenario.job["id"],
        factories.data_report_payload(shop.job_version(scenario.job["id"]), form_type=FORM_TYPE_U1),
        shop.acting_as(inspector),
    )
    validate_error(blocked_package, api_errors.ERR_OPEN_NONCONFORMANCE, 409)
    _, package_meta = validate_paginated(
        client.list_data_reports(
            admin_headers, params={"job_id": scenario.job["id"], "limit": 10, "offset": 0}
        )
    )
    assert package_meta["total_count"] == 0

    reports = shop.nonconformances_of(scenario.job["id"])
    assert len(reports) == 1
    report = reports[0]
    assert report["weld_id"] == parent_joint["id"]
    assert report["severity"] == SEVERITY_MAJOR
    assert report["disposition"] == DISPOSITION_OPEN

    without_concurrence = client.disposition_nonconformance(
        report["id"],
        factories.disposition_payload(
            disposition=DISPOSITION_USE_AS_IS,
            disposition_notes="Indication is shallow and within the corrosion allowance",
        ),
        shop.acting_as(inspector),
    )
    validate_error(without_concurrence, api_errors.ERR_AI_CONCURRENCE_REQUIRED, 409)
    still_open = validate_success(client.get_nonconformance(report["id"], admin_headers), 200)
    assert still_open["ai_concurrence_personnel_id"] is None
    assert still_open["disposition"] == DISPOSITION_OPEN

    committed = validate_success(
        client.disposition_nonconformance(
            report["id"],
            factories.disposition_payload(
                disposition=DISPOSITION_REPAIR,
                disposition_notes="Excavate and reweld the indicated length",
            ),
            shop.acting_as(inspector),
        ),
        200,
    )
    assert committed["disposition"] == DISPOSITION_REPAIR

    second_ticket = client.disposition_nonconformance(
        report["id"],
        factories.disposition_payload(
            disposition=DISPOSITION_REPAIR,
            disposition_notes="Second disposition ticket raised in error",
        ),
        shop.acting_as(inspector),
    )
    validate_error(second_ticket, api_errors.ERR_INVALID_NONCONFORMANCE_STATE, 409)

    first_repair = shop.repair_joint(report["id"], scenario.wps["id"], weld_number="W-401R1")
    assert first_repair["repair_of_weld_id"] == parent_joint["id"]
    assert first_repair["repair_generation"] == 1
    assert first_repair["required_volumetric_pct"] == 100
    assert_number_equals(first_repair["thickness_in"], 0.7500, 4, "thickness_in")

    shop.complete_joint(
        first_repair["id"], scenario.qualification["id"], welded_at="2026-08-03T09:00:00.000Z"
    )
    first_repair_exams = shop.run_nde_plan(scenario.job["id"])
    assert [exam["weld_id"] for exam in first_repair_exams] == [first_repair["id"]]
    shop.reject_exam(first_repair_exams[0]["id"], indications_count=2, exam_date="2026-08-04")

    reopened = validate_success(client.get_nonconformance(report["id"], admin_headers), 200)
    assert reopened["disposition"] == DISPOSITION_OPEN
    assert shop.read_job(scenario.job["id"])["status"] == JOB_STATUS_NDE_HOLD

    shop.disposition(
        report["id"],
        DISPOSITION_REPAIR,
        actor=inspector,
        disposition_notes="Second excavation, wider groove",
    )
    second_repair = shop.repair_joint(report["id"], scenario.wps["id"], weld_number="W-401R2")
    assert second_repair["repair_of_weld_id"] == parent_joint["id"]
    assert second_repair["required_volumetric_pct"] == 100

    shop.complete_joint(
        second_repair["id"], scenario.qualification["id"], welded_at="2026-08-06T09:00:00.000Z"
    )
    second_repair_exams = shop.run_nde_plan(scenario.job["id"])
    assert [exam["weld_id"] for exam in second_repair_exams] == [second_repair["id"]]
    shop.reject_exam(second_repair_exams[0]["id"], indications_count=1, exam_date="2026-08-07")
    assert (
        validate_success(client.get_nonconformance(report["id"], admin_headers), 200)["disposition"]
        == DISPOSITION_OPEN
    )

    spent = client.disposition_nonconformance(
        report["id"],
        factories.disposition_payload(
            disposition=DISPOSITION_REPAIR,
            disposition_notes="Third excavation requested by the welding engineer",
        ),
        shop.acting_as(inspector),
    )
    validate_error(spent, api_errors.ERR_REPAIR_LIMIT_EXCEEDED, 409)

    repairs, repair_meta = validate_paginated(
        client.list_welds(
            admin_headers,
            params={
                "job_id": scenario.job["id"],
                "repair_of_weld_id": parent_joint["id"],
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert repair_meta["total_count"] == 2
    assert sorted(row["weld_number"] for row in repairs) == ["W-401R1", "W-401R2"]


def test_the_furnace_charge_refuses_a_second_start_an_unfiled_chart_and_a_reused_chart_number(
    client, shop, admin_headers
):
    """Two charges in two furnaces share nothing but a chart record number, and that alone is enough to refuse the second.

    PRD §3.5: "Its `pwht_status` opens at `PENDING` when the cited procedure has `pwht_required` true and at `NOT_REQUIRED` when it does not — the flag on the procedure, resolved once at planning time, is what decides whether the joint will ever need a furnace charge."

    PRD §3.8: "Creation answers 201 with the charge at `status` `SCHEDULED`, `scheduled_by_personnel_id` set to the acting `X-User-ID`, `weld_count` equal to the number of entries in `weld_ids`, `chart_uploaded` false, `actual_soak_minutes` null, `chart_record_number` null and `chart_reviewed_by_personnel_id` null."

    PRD §3.8: "`governing_thickness_in` is the greatest `thickness_in` among the batched joints — the thickest joint sets the hold for the whole charge."

    PRD §3.8: "`required_soak_minutes` is the larger of 15 minutes and the product of `governing_thickness_in` and 60 minutes per inch, that product being rounded half up to a whole number of minutes."

    PRD §3.8: "It requires the charge to be `SCHEDULED`, the job to be in `FABRICATION` or `NDE_HOLD`, every batched joint's `fab_status` to be `WELDED` — a charge cannot be run on joints that have not been made — and `soak_temp_f` to lie inside the applicable band, or the start draws `ERR_INVALID_BATCH_STATE`, the same error a charge in the wrong posture or holding an unwelded joint draws."

    PRD §3.8: "Every batched joint moves `pwht_status` `PENDING → IN_PROGRESS` in the same request."

    PRD §3.8: "The engineer supplies `actual_soak_minutes`, the soak time actually achieved at no less than 0; `chart_record_number`, the identifier of the time-temperature chart record, globally unique so a reused chart draws `ERR_DUPLICATE_CHART_RECORD_NUMBER`; and `chart_uploaded`, the flag stating the chart is on file."

    PRD §3.8: "`chart_uploaded` must be true and `chart_record_number` non-blank, or the completion draws `ERR_CHART_RECORD_MISSING`."

    PRD §3.8: "`actual_soak_minutes` must be at least `required_soak_minutes`, or it draws `ERR_SOAK_TIME_INSUFFICIENT`."

    PRD §3.8: "On success `chart_reviewed_by_personnel_id` records the acting user, every batched joint moves `pwht_status` `IN_PROGRESS → COMPLETE`, the job's `weld_completion_pct` is recomputed, and every data report of the job re-derives its `PWHT` section score and its `completeness_score`."

    Design: Corner/errors/error_pwht_charge_family_on_state_chart_and_chart_identity
    """
    engineer = shop.welding_engineer()
    reviewer = shop.second_welding_engineer()
    scenario = shop.welded_job(
        pwht_required=True,
        joint_count=1,
        thickness_in=0.7500,
        quantity_received_lb=2000.00,
        job_overrides={"job_number": "J-2885-C49"},
        wps_overrides={"wps_number": "WPS-170", "preheat_min_f": 250},
    )
    thick_joint = scenario.welds[0]
    thin_joint = shop.plan_joint(
        scenario.job["id"],
        scenario.wps["id"],
        scenario.parts[COMPONENT_TYPE_SHELL]["id"],
        weld_number="W-502",
        thickness_in=0.5000,
    )
    shop.complete_joint(thin_joint["id"], scenario.qualification["id"])

    thick_charge = shop.pwht_batch(
        scenario.job["id"], [thick_joint["id"]], scheduler=engineer, furnace_code=FURNACE_A
    )
    assert thick_charge["weld_count"] == 1
    assert thick_charge["scheduled_by_personnel_id"] == engineer["id"]
    assert thick_charge["chart_uploaded"] is False
    assert thick_charge["chart_record_number"] is None
    assert thick_charge["chart_reviewed_by_personnel_id"] is None
    thin_charge = shop.pwht_batch(
        scenario.job["id"], [thin_joint["id"]], scheduler=engineer, furnace_code=FURNACE_B
    )

    started = validate_success(
        client.start_pwht_batch(thick_charge["id"], shop.acting_as(engineer)), 200
    )
    assert started["status"] == BATCH_STATUS_IN_PROGRESS
    assert started["required_soak_minutes"] == expected_required_soak_minutes(0.7500)
    assert_number_equals(started["governing_thickness_in"], 0.7500, 4, "governing_thickness_in")
    assert shop.read_joint(thick_joint["id"])["pwht_status"] == PWHT_STATUS_IN_PROGRESS

    restart = client.start_pwht_batch(thick_charge["id"], shop.acting_as(engineer))
    validate_error(restart, api_errors.ERR_INVALID_BATCH_STATE, 409)

    no_chart = client.complete_pwht_batch(
        thick_charge["id"],
        factories.pwht_complete_payload(
            actual_soak_minutes=60, chart_record_number="CH-9001", chart_uploaded=False
        ),
        shop.acting_as(reviewer),
    )
    validate_error(no_chart, api_errors.ERR_CHART_RECORD_MISSING, 409)
    unfiled = validate_success(client.get_pwht_batch(thick_charge["id"], admin_headers), 200)
    assert unfiled["status"] == BATCH_STATUS_IN_PROGRESS
    assert unfiled["chart_record_number"] is None
    assert unfiled["actual_soak_minutes"] is None

    filed = validate_success(
        client.complete_pwht_batch(
            thick_charge["id"],
            factories.pwht_complete_payload(
                actual_soak_minutes=45, chart_record_number="CH-9001", chart_uploaded=True
            ),
            shop.acting_as(reviewer),
        ),
        200,
    )
    assert filed["status"] == BATCH_STATUS_COMPLETE
    assert filed["chart_reviewed_by_personnel_id"] == reviewer["id"]
    assert filed["chart_reviewed_by_personnel_id"] != filed["scheduled_by_personnel_id"]
    assert shop.read_joint(thick_joint["id"])["pwht_status"] == PWHT_STATUS_COMPLETE

    shop.start_pwht_batch(thin_charge["id"], actor=engineer)
    reused = client.complete_pwht_batch(
        thin_charge["id"],
        factories.pwht_complete_payload(
            actual_soak_minutes=30, chart_record_number="CH-9001", chart_uploaded=True
        ),
        shop.acting_as(reviewer),
    )
    validate_error(reused, api_errors.ERR_DUPLICATE_CHART_RECORD_NUMBER, 409)
    refused = validate_success(client.get_pwht_batch(thin_charge["id"], admin_headers), 200)
    assert refused["status"] == BATCH_STATUS_IN_PROGRESS
    assert refused["required_soak_minutes"] == expected_required_soak_minutes(0.5000)
    assert refused["chart_record_number"] is None
    assert shop.read_joint(thin_joint["id"])["pwht_status"] == PWHT_STATUS_IN_PROGRESS

    fresh_chart = validate_success(
        client.complete_pwht_batch(
            thin_charge["id"],
            factories.pwht_complete_payload(
                actual_soak_minutes=30, chart_record_number="CH-9002", chart_uploaded=True
            ),
            shop.acting_as(reviewer),
        ),
        200,
    )
    assert fresh_chart["status"] == BATCH_STATUS_COMPLETE
    assert fresh_chart["chart_record_number"] == "CH-9002"
    assert shop.read_joint(thin_joint["id"])["pwht_status"] == PWHT_STATUS_COMPLETE


def test_the_pressure_test_walks_applicability_witness_authority_and_the_three_thresholds(
    client, shop, admin_headers
):
    """Each PASS threshold is missed by exactly one unit, and the witness waits on the shop's licence rather than on the vessel.

    PRD §3.8: "The `test_side` must be a member of the job's `required_test_sides`, or the request draws `ERR_TEST_SIDE_NOT_APPLICABLE`: a single-chamber vessel has no tube side to test."

    PRD §3.8: "A `PNEUMATIC` test requires the job's `pneumatic_justification` to be non-blank, since pneumatic testing is only permitted where a hydrostatic test is impracticable, and its absence draws `ERR_PNEUMATIC_JUSTIFICATION_REQUIRED`."

    PRD §3.8: "Scheduling the first test of a job is the aggregate gate that moves it `FABRICATION → TESTING`, and it walks the entire weld map."

    PRD §3.8: "Creation answers 201 with the test at `result` `PENDING`, `ai_witness_confirmed` false, `witnessed_by_personnel_id` null and the observed figures null."

    PRD §3.8: "For a `HYDROSTATIC` test, `test_pressure_psi` is 1.3 multiplied by the job's `mawp_psi` multiplied by the job's `stress_ratio`, rounded half up to one decimal place; `min_hold_minutes` is 30; and `min_medium_temp_f` is the job's `mdmt_f` plus 30."

    PRD §3.8: "Both branches require the test to be `PENDING`, `ai_witness_confirmed` to be true — recording a result on an unwitnessed test draws `ERR_AI_WITNESS_REQUIRED` — and the job to be in `TESTING`."

    PRD §3.1: "`stamping_authorized` is true only when `status` is `ACTIVE`, `expires_on` is on or after the current logical UTC date, and `open_major_findings_count` is exactly 0 — it is the single flag every witness, signature and nameplate attempt consults."

    PRD §3.8: "The governing certificate must not be expired, or it draws `ERR_CERTIFICATE_EXPIRED`, and its `stamping_authorized` must be true, or it draws `ERR_STAMPING_NOT_AUTHORIZED` — an open audit finding at the shop level stops a witness from being recorded on an otherwise perfect vessel."

    PRD §3.1: "`expires_on` is replaced by `new_expires_on`, both `open_major_findings_count` and `open_minor_findings_count` are reset to 0, `renewal_count` increases by 1, `status` and `stamping_authorized` are re-derived — which lands the certificate at `ACTIVE` with `stamping_authorized` true — and `version` increments."

    PRD §3.8: "On success `ai_witness_confirmed` becomes true and `witnessed_by_personnel_id` records the acting `X-User-ID`."

    PRD §3.8: "The `PASS` branch additionally requires the job's `nonconformance_open_count` to be 0, `observed_pressure_psi` to be at least `test_pressure_psi` or it draws `ERR_TEST_PRESSURE_INSUFFICIENT`, `observed_hold_minutes` to be at least `min_hold_minutes` or it draws `ERR_HOLD_TIME_INSUFFICIENT`, and `test_medium_temp_f` to be at least `min_medium_temp_f` or it draws `ERR_MEDIUM_TEMP_TOO_LOW`."

    PRD §3.8: "A pass moves the job `TESTING → DATA_PACKAGE`, but only once every member of the job's `required_test_sides` is satisfied — for each such side, the test on that side with the greatest `created_at` must read `PASS`."

    PRD §3.8: "The test record moves `PENDING → PASS` on the first branch and `PENDING → FAIL` on the second, and both are terminal for it."

    PRD §3.8: "The `FAIL` branch raises a nonconformance report with `source` `PRESSURE_TEST_FAIL`, `severity` `MAJOR` and `disposition` `OPEN`, increases the job's `nonconformance_open_count`, and moves the job `TESTING → NDE_HOLD`."

    Design: Corner/errors/error_pressure_test_family_from_applicability_to_terminal_result
    """
    inspector = shop.qc_inspector()
    witness = shop.authorized_inspector()
    certificate = shop.certificate(cert_number="CA-U-8933")
    renewal_audit = shop.satisfactory_closed_audit(
        certificate["id"], audit_type=AUDIT_TYPE_TRIENNIAL_RENEWAL, scheduled_date="2026-05-01"
    )
    finding_audit = shop.audit(
        certificate["id"], audit_type=AUDIT_TYPE_INTERNAL_QMS, scheduled_date="2026-06-01"
    )
    scenario = shop.welded_job(
        joint_count=1,
        thickness_in=0.8750,
        quantity_received_lb=2000.00,
        certificate=certificate,
        job_overrides={"job_number": "J-2885-C50", "mawp_psi": 350},
    )
    job_id = scenario.job["id"]
    assert scenario.job["required_test_sides"] == ["SHELL_SIDE"]

    wrong_side = client.create_pressure_test(
        factories.pressure_test_payload(job_id, test_side=TEST_SIDE_TUBE),
        shop.acting_as(inspector),
    )
    validate_error(wrong_side, api_errors.ERR_TEST_SIDE_NOT_APPLICABLE, 409)

    unjustified = client.create_pressure_test(
        factories.pressure_test_payload(job_id, test_type=TEST_TYPE_PNEUMATIC),
        shop.acting_as(inspector),
    )
    validate_error(unjustified, api_errors.ERR_PNEUMATIC_JUSTIFICATION_REQUIRED, 409)

    assert shop.read_job(job_id)["status"] == JOB_STATUS_FABRICATION
    _, empty_meta = validate_paginated(
        client.list_pressure_tests(admin_headers, params={"job_id": job_id, "limit": 10, "offset": 0})
    )
    assert empty_meta["total_count"] == 0

    test = validate_success(
        client.create_pressure_test(
            factories.pressure_test_payload(job_id), shop.acting_as(inspector)
        ),
        201,
    )
    assert_number_equals(
        test["test_pressure_psi"],
        expected_test_pressure(350, 1.00, TEST_TYPE_HYDROSTATIC),
        1,
        "test_pressure_psi",
    )
    assert test["min_hold_minutes"] == 30
    assert test["min_medium_temp_f"] == expected_min_medium_temp(-20, TEST_TYPE_HYDROSTATIC)
    assert test["ai_witness_confirmed"] is False
    assert test["witnessed_by_personnel_id"] is None
    assert test["result"] == TEST_RESULT_PENDING
    assert shop.read_job(job_id)["status"] == JOB_STATUS_TESTING

    unwitnessed = client.record_pressure_test_result(
        test["id"],
        factories.pressure_test_result_payload(
            observed_pressure_psi=455.0, observed_hold_minutes=30, test_medium_temp_f=10
        ),
        shop.acting_as(inspector),
    )
    validate_error(unwitnessed, api_errors.ERR_AI_WITNESS_REQUIRED, 409)

    shop.close_audit(finding_audit["id"], closed_on="2026-06-20", major=1)
    on_probation = shop.read_certificate(certificate["id"])
    assert on_probation["status"] == CERT_STATUS_PROBATION
    assert on_probation["open_major_findings_count"] == 1
    assert on_probation["stamping_authorized"] is False

    refused_witness = client.witness_pressure_test(test["id"], shop.acting_as(witness))
    validate_error(refused_witness, api_errors.ERR_STAMPING_NOT_AUTHORIZED, 403)
    assert (
        validate_success(client.get_pressure_test(test["id"], admin_headers), 200)[
            "ai_witness_confirmed"
        ]
        is False
    )

    renewed = validate_success(
        client.renew_certificate(
            certificate["id"],
            factories.renewal_payload(
                shop.read_certificate(certificate["id"])["version"],
                renewal_audit["id"],
                new_expires_on="2032-01-01",
            ),
            admin_headers,
        ),
        200,
    )
    assert renewed["status"] == CERT_STATUS_ACTIVE
    assert renewed["open_major_findings_count"] == 0
    assert renewed["renewal_count"] == 1
    assert renewed["expires_on"] == "2032-01-01"
    assert renewed["stamping_authorized"] is True

    witnessed = validate_success(
        client.witness_pressure_test(test["id"], shop.acting_as(witness)), 200
    )
    assert witnessed["ai_witness_confirmed"] is True
    assert witnessed["witnessed_by_personnel_id"] == witness["id"]
    assert witnessed["result"] == TEST_RESULT_PENDING

    one_unit_short = [
        ((454.9, 30, 10), api_errors.ERR_TEST_PRESSURE_INSUFFICIENT),
        ((455.0, 29, 10), api_errors.ERR_HOLD_TIME_INSUFFICIENT),
        ((455.0, 30, 9), api_errors.ERR_MEDIUM_TEMP_TOO_LOW),
    ]
    for (pressure, hold, temp), expected_error in one_unit_short:
        refusal = client.record_pressure_test_result(
            test["id"],
            factories.pressure_test_result_payload(
                observed_pressure_psi=pressure,
                observed_hold_minutes=hold,
                test_medium_temp_f=temp,
            ),
            shop.acting_as(inspector),
        )
        validate_error(refusal, expected_error, 409)

    still_pending = validate_success(client.get_pressure_test(test["id"], admin_headers), 200)
    assert still_pending["result"] == TEST_RESULT_PENDING
    assert still_pending["observed_pressure_psi"] is None
    assert still_pending["observed_hold_minutes"] is None
    assert still_pending["test_medium_temp_f"] is None

    passed = validate_success(
        client.record_pressure_test_result(
            test["id"],
            factories.pressure_test_result_payload(
                observed_pressure_psi=455.0, observed_hold_minutes=30, test_medium_temp_f=10
            ),
            shop.acting_as(inspector),
        ),
        200,
    )
    assert passed["result"] == TEST_RESULT_PASS
    assert_number_equals(passed["observed_pressure_psi"], 455.0, 1, "observed_pressure_psi")
    assert passed["observed_hold_minutes"] == 30
    assert passed["test_medium_temp_f"] == 10
    assert shop.read_job(job_id)["status"] == JOB_STATUS_DATA_PACKAGE

    late_failure = client.record_pressure_test_result(
        test["id"],
        factories.pressure_test_result_payload(
            result="FAIL",
            observed_pressure_psi=455.0,
            observed_hold_minutes=30,
            test_medium_temp_f=10,
        ),
        shop.acting_as(inspector),
    )
    validate_error(late_failure, api_errors.ERR_INVALID_TEST_STATE, 409)
    assert shop.read_job(job_id)["status"] == JOB_STATUS_DATA_PACKAGE
    _, ncr_meta = validate_paginated(
        client.list_nonconformances(admin_headers, params={"job_id": job_id, "limit": 10, "offset": 0})
    )
    assert ncr_meta["total_count"] == 0


def test_two_finished_vessels_cannot_share_one_nameplate_serial(client, shop, admin_headers):
    """The serial is the one uniqueness key spanning two unrelated vessels, so it takes two complete packages to prove.

    PRD §3.9: "A section whose denominator is 0 takes a fraction of exactly 1.000 — a vessel that needs no heat treatment scores full marks for heat treatment rather than zero."

    PRD §3.9: "The report must be `ASSEMBLING`, the job must be in `DATA_PACKAGE`, the `completeness_score` must be exactly 100.00 — anything less draws `ERR_DATA_PACKAGE_INCOMPLETE` — and `nonconformance_open_count` must be 0 or the submission draws `ERR_OPEN_NONCONFORMANCE`."

    PRD §3.9: "On success `missing_items` is recomputed and is necessarily empty."

    PRD §3.9: "And the acting `X-User-ID` must differ from `assembled_by_personnel_id`, or the request draws `ERR_SEGREGATION_OF_DUTIES` — the same `AuthorizedInspector` who assembled the package cannot also sign it, which is precisely why assembly is open to two roles."

    PRD §3.9: "The request supplies `nameplate_serial`, the serial impressed on the code nameplate, which must be unique across all data reports; a repeat draws `ERR_DUPLICATE_NAMEPLATE_SERIAL`."

    PRD §3.9: "The report must be `AI_SIGNED` — a report at `STAMP_HOLD` is refused with `ERR_INVALID_REPORT_STATE` — and the governing certificate must be unexpired with `stamping_authorized` true, drawing `ERR_CERTIFICATE_EXPIRED` or `ERR_STAMPING_NOT_AUTHORIZED` otherwise, since the authority is re-checked at the moment of stamping and not merely at the moment of signature."

    PRD §3.9: "On success the report moves `AI_SIGNED → STAMPED` with `nameplate_serial` stored and `nameplate_stamped_at` set to the current logical UTC instant, and the job cascades `DATA_PACKAGE → STAMPED`."

    Design: Corner/errors/error_nameplate_serial_is_unique_across_every_stamped_vessel
    """
    certificate = shop.certificate(cert_number="CA-U-8934")
    vessel_a = shop.signed_report_job(
        certificate=certificate,
        thickness_in=0.8750,
        job_overrides={"job_number": "J-2885-C51"},
    )
    vessel_b = shop.signed_report_job(
        certificate=certificate,
        thickness_in=0.8750,
        job_overrides={"job_number": "J-2885-C52"},
        test_overrides={
            "test_bay_code": BAY_2,
            "scheduled_start": "2026-08-11T08:00:00.000Z",
            "scheduled_end": "2026-08-11T12:00:00.000Z",
        },
    )

    for vessel in (vessel_a, vessel_b):
        package = shop.read_data_report(vessel.report["id"])
        assert package["status"] == REPORT_STATUS_AI_SIGNED
        assert_number_equals(package["completeness_score"], 100.00, 2, "completeness_score")
        assert package["missing_items"] == []
        assert package["nameplate_serial"] is None
        assert package["ai_personnel_id"] == vessel.signer["id"]
        assert package["assembled_by_personnel_id"] == vessel.assembler["id"]
        assert package["ai_personnel_id"] != package["assembled_by_personnel_id"]
        assert shop.read_job(vessel.job["id"])["status"] == JOB_STATUS_DATA_PACKAGE

    stamped_a = validate_success(
        client.stamp_nameplate(
            vessel_a.report["id"], factories.stamp_payload(nameplate_serial="NP-0001"), admin_headers
        ),
        200,
    )
    assert stamped_a["status"] == REPORT_STATUS_STAMPED
    assert stamped_a["nameplate_serial"] == "NP-0001"
    assert stamped_a["nameplate_stamped_at"] is not None
    assert shop.read_job(vessel_a.job["id"])["status"] == JOB_STATUS_STAMPED

    duplicate = client.stamp_nameplate(
        vessel_b.report["id"], factories.stamp_payload(nameplate_serial="NP-0001"), admin_headers
    )
    validate_error(duplicate, api_errors.ERR_DUPLICATE_NAMEPLATE_SERIAL, 409)
    inert = shop.read_data_report(vessel_b.report["id"])
    assert inert["status"] == REPORT_STATUS_AI_SIGNED
    assert inert["nameplate_serial"] is None
    assert inert["nameplate_stamped_at"] is None
    assert shop.read_job(vessel_b.job["id"])["status"] == JOB_STATUS_DATA_PACKAGE

    stamped_b = validate_success(
        client.stamp_nameplate(
            vessel_b.report["id"], factories.stamp_payload(nameplate_serial="NP-0002"), admin_headers
        ),
        200,
    )
    assert stamped_b["status"] == REPORT_STATUS_STAMPED
    assert stamped_b["nameplate_serial"] == "NP-0002"
    assert shop.read_job(vessel_b.job["id"])["status"] == JOB_STATUS_STAMPED

    rows, stamped_meta = validate_paginated(
        client.list_data_reports(
            admin_headers, params={"status": REPORT_STATUS_STAMPED, "limit": 10, "offset": 0}
        )
    )
    assert stamped_meta["total_count"] == 2
    assert sorted(row["nameplate_serial"] for row in rows) == ["NP-0001", "NP-0002"]
