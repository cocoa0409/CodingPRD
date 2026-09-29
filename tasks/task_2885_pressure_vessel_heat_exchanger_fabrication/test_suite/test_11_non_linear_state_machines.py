"""State machines that are not a single line: a review cycle and three parallel joint dimensions."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    BATCH_STATUS_COMPLETE,
    BATCH_STATUS_IN_PROGRESS,
    CALC_STATUS_APPROVED,
    CALC_STATUS_DRAFT,
    CALC_STATUS_REJECTED,
    CALC_STATUS_SUBMITTED,
    COMPONENT_HEAD,
    COMPONENT_SHELL,
    COMPONENT_TYPE_HEAD,
    COMPONENT_TYPE_SHELL,
    DESIGN_CODE_DIV1,
    EXAM_CLASS_VOLUMETRIC,
    FAB_STATUS_WELDED,
    FURNACE_A,
    JOB_STATUS_DESIGN_REVIEW,
    JOINT_CATEGORY_B,
    JOINT_TYPE_BUTT,
    METHOD_RT,
    NDE_STATUS_ACCEPTED,
    NDE_STATUS_NOT_PLANNED,
    NDE_STATUS_PLANNED,
    PWHT_STATUS_COMPLETE,
    PWHT_STATUS_IN_PROGRESS,
    RT_EXTENT_FULL,
    RT_EXTENT_NONE,
    SPEC_SA_516_70,
    VARIANT_CIRCUMFERENTIAL,
    VESSEL_TYPE_PRESSURE_VESSEL,
)

REJECT_REASON = (
    "Radiography extent claimed as FULL is not supported by the shop's examination "
    "plan for this seam."
)


def _rejected_shell_sheet(shop):
    """One SHELL sheet driven DRAFT to SUBMITTED to REJECTED, leaving the job back in DRAFT."""
    preparer = shop.design_engineer()
    reviewer = shop.reviewing_design_engineer()
    certificate = shop.certificate(cert_number="CA-U-8801")
    job = shop.job(
        certificate,
        job_number="J-2885-05",
        customer_name="Northline Energy",
        vessel_type=VESSEL_TYPE_PRESSURE_VESSEL,
        design_code=DESIGN_CODE_DIV1,
        mawp_psi=350,
        design_temp_f=650,
        mdmt_f=-20,
        inside_radius_in=30.0,
        stress_ratio=1.00,
    )
    sheet = shop.prepare_sheet(
        job["id"],
        COMPONENT_SHELL,
        preparer=preparer,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=1.0000,
    )
    shop.submit_sheet(sheet["id"], preparer=preparer)
    rejected = shop.client.reject_calculation(
        sheet["id"],
        factories.reject_payload(reject_reason=REJECT_REASON),
        shop.acting_as(reviewer),
    )
    validate_success(rejected, 200)
    return job, sheet, preparer, reviewer


def test_a_rejected_sheet_refuses_a_second_submit_and_is_reopened_only_by_revising_it(
    client, shop
):
    """REJECTED to SUBMITTED is not declared; the revise re-enters DRAFT and recomputes every derived figure.

    PRD §3.3: "Submitting a sheet for independent review moves it `DRAFT → SUBMITTED` and requires three things: the sheet is currently `DRAFT` (a second submit draws `ERR_INVALID_CALCULATION_STATE`), the parent job is in `DRAFT` or `DESIGN_REVIEW`, and `thickness_nominal_in` is at least `thickness_required_in`."

    PRD §3.3: "Revising a sheet moves it `REJECTED → DRAFT` and requires the sheet to be `REJECTED` and the parent job to be in `DRAFT`; revising a sheet in any other posture draws `ERR_INVALID_CALCULATION_STATE`."

    PRD §3.3: "`revision` increases by 1, `reviewed_by_personnel_id` and `reject_reason` are both cleared back to null, and `joint_efficiency`, `thickness_circumferential_in`, `thickness_longitudinal_in`, `thickness_required_in` and `governing_variant` are all recomputed from the new inputs."

    Design: Difficulty/non_linear_state_machine/non_linear_design_calculation_reject_revise_resubmit_cycle
    """
    job, sheet, preparer, reviewer = _rejected_shell_sheet(shop)

    rejected = validate_success(client.get_calculation(sheet["id"], shop.admin), 200)
    assert rejected["status"] == CALC_STATUS_REJECTED
    assert rejected["revision"] == 1
    assert rejected["reject_reason"] == REJECT_REASON
    assert rejected["reviewed_by_personnel_id"] == reviewer["id"]

    replay = client.submit_calculation(sheet["id"], shop.acting_as(preparer))
    validate_error(replay, api_errors.ERR_INVALID_CALCULATION_STATE, 409)
    assert (
        validate_success(client.get_calculation(sheet["id"], shop.admin), 200)["status"]
        == CALC_STATUS_REJECTED
    )

    revised = validate_success(
        client.revise_calculation(
            sheet["id"],
            factories.revise_payload(
                rt_extent_declared=RT_EXTENT_NONE,
                allowable_stress_psi=20000,
                corrosion_allowance_in=0.0625,
                thickness_nominal_in=1.0000,
            ),
            shop.acting_as(preparer),
        ),
        200,
    )
    assert revised["status"] == CALC_STATUS_DRAFT
    assert revised["revision"] == 2
    assert revised["reject_reason"] is None
    assert revised["reviewed_by_personnel_id"] is None
    assert_number_equals(revised["joint_efficiency"], 0.70, 2, "joint_efficiency")
    assert_number_equals(
        revised["thickness_circumferential_in"], 0.7614, 4, "thickness_circumferential_in"
    )
    assert_number_equals(
        revised["thickness_longitudinal_in"], 0.3731, 4, "thickness_longitudinal_in"
    )
    assert_number_equals(revised["thickness_required_in"], 0.8239, 4, "thickness_required_in")
    assert revised["governing_variant"] == VARIANT_CIRCUMFERENTIAL


def test_the_second_lap_reaches_approved_while_the_job_waits_on_the_head_sheet(client, shop):
    """The row cycles back through SUBMITTED to APPROVED without a new revision, and the job stays in review.

    PRD §3.3: "A successful submit carries the job `DRAFT → DESIGN_REVIEW` and increments both records' versions."

    PRD §3.3: "On approval the reviewer's identity is written to `reviewed_by_personnel_id`, the job's `governing_joint_efficiency` is recomputed as the smallest `joint_efficiency` across the job's approved sheets, and — once **every** component listed in the job's `required_components` carries exactly one `APPROVED` sheet — the job moves `DESIGN_REVIEW → FAB_PLANNING` with `design_release_at` stamped to the current logical UTC instant."

    PRD §3.3: "The row therefore cycles `DRAFT → SUBMITTED → REJECTED → DRAFT` as many times as review demands, with `revision` incrementing on each pass, and the job cycles `DRAFT → DESIGN_REVIEW → DRAFT` alongside it until every required component is approved."

    Design: Difficulty/non_linear_state_machine/non_linear_design_calculation_reject_revise_resubmit_cycle
    """
    job, sheet, preparer, reviewer = _rejected_shell_sheet(shop)

    validate_success(
        client.revise_calculation(
            sheet["id"],
            factories.revise_payload(
                rt_extent_declared=RT_EXTENT_NONE,
                allowable_stress_psi=20000,
                corrosion_allowance_in=0.0625,
                thickness_nominal_in=1.0000,
            ),
            shop.acting_as(preparer),
        ),
        200,
    )

    resubmitted = validate_success(
        client.submit_calculation(sheet["id"], shop.acting_as(preparer)), 200
    )
    assert resubmitted["status"] == CALC_STATUS_SUBMITTED
    assert shop.read_job(job["id"])["status"] == JOB_STATUS_DESIGN_REVIEW

    approved = validate_success(
        client.approve_calculation(sheet["id"], shop.acting_as(reviewer)), 200
    )
    assert approved["status"] == CALC_STATUS_APPROVED
    assert approved["revision"] == 2
    assert approved["reviewed_by_personnel_id"] == reviewer["id"]

    waiting = shop.read_job(job["id"])
    assert waiting["status"] == JOB_STATUS_DESIGN_REVIEW
    assert COMPONENT_HEAD in waiting["required_components"]
    assert waiting["design_release_at"] is None
    assert_number_equals(
        waiting["governing_joint_efficiency"], 0.70, 2, "governing_joint_efficiency"
    )


def _welded_joint_in_a_scheduled_charge(shop):
    """One welded Category B seam loaded into a SCHEDULED furnace charge, nothing examined yet."""
    scheduler = shop.welding_engineer()
    reviewer = shop.second_welding_engineer()
    certificate = shop.certificate(cert_number="CA-U-8801")
    job = shop.job(
        certificate,
        job_number="J-2885-06",
        customer_name="Northline Energy",
        vessel_type=VESSEL_TYPE_PRESSURE_VESSEL,
        design_code=DESIGN_CODE_DIV1,
        mawp_psi=350,
        design_temp_f=650,
        mdmt_f=-20,
        inside_radius_in=30.0,
        stress_ratio=1.00,
    )
    shop.release_design(
        job,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=1.0000,
    )
    heat = shop.accepted_heat(
        heat_number="H-4471", spec=SPEC_SA_516_70, quantity_received_lb=2000.00
    )
    shell_part = shop.issue_part(
        job["id"],
        heat["id"],
        part_mark="SH-01",
        component_type=COMPONENT_TYPE_SHELL,
        issued_quantity_lb=1200.00,
    )
    head_part = shop.issue_part(
        job["id"],
        heat["id"],
        part_mark="HD-01",
        component_type=COMPONENT_TYPE_HEAD,
        issued_quantity_lb=600.00,
    )
    procedure = shop.qualified_wps(
        wps_number="WPS-2", pwht_required=True, preheat_min_f=200, base_metal_p_number=1
    )
    qualification = shop.welder_qualification(
        procedure["id"], welder_stamp="W12", welder_name="Rosa Vela"
    )
    joint = shop.plan_joint(
        job["id"],
        procedure["id"],
        shell_part["id"],
        weld_number="W-001",
        joint_category=JOINT_CATEGORY_B,
        joint_type=JOINT_TYPE_BUTT,
        thickness_in=0.6250,
        part_b_id=head_part["id"],
    )
    shop.release_weld_map(job["id"])
    shop.complete_joint(
        joint["id"], qualification["id"], welded_at="2026-07-30T09:00:00.000Z"
    )
    batch = shop.pwht_batch(
        job["id"],
        [joint["id"]],
        scheduler=scheduler,
        furnace_code=FURNACE_A,
        scheduled_start="2026-08-05T08:00:00.000Z",
        scheduled_end="2026-08-05T12:00:00.000Z",
        soak_temp_f=1150,
    )
    return job, joint, batch, scheduler, reviewer


def test_heat_treatment_runs_to_complete_while_the_examination_dimension_never_moves(client, shop):
    """The furnace dimension reaches COMPLETE with `nde_status` still NOT_PLANNED and the roll-up at zero.

    PRD §3.8: "`governing_thickness_in` is the greatest `thickness_in` among the batched joints — the thickest joint sets the hold for the whole charge."

    PRD §3.8: "`required_soak_minutes` is the larger of 15 minutes and the product of `governing_thickness_in` and 60 minutes per inch, that product being rounded half up to a whole number of minutes."

    PRD §3.8: "Every batched joint moves `pwht_status` `PENDING → IN_PROGRESS` in the same request."

    PRD §3.8: "And the acting `X-User-ID` must differ from `scheduled_by_personnel_id`, or it draws `ERR_SEGREGATION_OF_DUTIES` — the person who scheduled the charge may not be the person who certifies its chart."

    PRD §3.8: "On success `chart_reviewed_by_personnel_id` records the acting user, every batched joint moves `pwht_status` `IN_PROGRESS → COMPLETE`, the job's `weld_completion_pct` is recomputed, and every data report of the job re-derives its `PWHT` section score and its `completeness_score`."

    PRD §3.6: "The three advance on their own triggers and in any interleaving: a joint may be heat-treated to `COMPLETE` while still awaiting radiography, or examination-`ACCEPTED` while its `pwht_status` is still `PENDING`."

    Design: Difficulty/non_linear_state_machine/non_linear_production_weld_parallel_nde_and_pwht_dimensions
    """
    job, joint, batch, scheduler, reviewer = _welded_joint_in_a_scheduled_charge(shop)

    assert_number_equals(batch["governing_thickness_in"], 0.6250, 4, "governing_thickness_in")
    assert batch["required_soak_minutes"] == 38
    assert batch["scheduled_by_personnel_id"] == scheduler["id"]

    started = validate_success(
        client.start_pwht_batch(batch["id"], shop.acting_as(scheduler)), 200
    )
    assert started["status"] == BATCH_STATUS_IN_PROGRESS

    mid_charge = shop.read_joint(joint["id"])
    assert mid_charge["pwht_status"] == PWHT_STATUS_IN_PROGRESS
    assert mid_charge["fab_status"] == FAB_STATUS_WELDED
    assert mid_charge["nde_status"] == NDE_STATUS_NOT_PLANNED

    completed = validate_success(
        client.complete_pwht_batch(
            batch["id"],
            factories.pwht_complete_payload(
                actual_soak_minutes=45, chart_record_number="CH-0001", chart_uploaded=True
            ),
            shop.acting_as(reviewer),
        ),
        200,
    )
    assert completed["status"] == BATCH_STATUS_COMPLETE
    assert completed["chart_reviewed_by_personnel_id"] == reviewer["id"]
    assert completed["chart_reviewed_by_personnel_id"] != completed["scheduled_by_personnel_id"]

    after_charge = shop.read_joint(joint["id"])
    assert after_charge["pwht_status"] == PWHT_STATUS_COMPLETE
    assert after_charge["nde_status"] == NDE_STATUS_NOT_PLANNED
    assert after_charge["fab_status"] == FAB_STATUS_WELDED
    assert_number_equals(
        shop.read_job(job["id"])["weld_completion_pct"], 0.00, 2, "weld_completion_pct"
    )


def test_only_the_third_dimension_landing_lifts_the_progress_measure_to_full(client, shop):
    """With heat treatment already COMPLETE, planning and accepting the radiograph alone carries the job to 100.00.

    PRD §3.6: "The candidate set is every weld of the job whose `fab_status` is `WELDED` and whose `nde_status` is `NOT_PLANNED`; joints that are still `PLANNED`, and joints already past `NOT_PLANNED`, are skipped, which is what makes re-invocation safe and non-duplicating."

    PRD §3.6: "For a Category B joint, a `FULL` declaration gives 100 when `thickness_in` is at least 1.500 and gives 25 when it is thinner, a `SPOT` declaration gives 25, and a `NONE` declaration gives 0."

    PRD §3.6: "Every joint selected by either pass moves `nde_status` `NOT_PLANNED → PLANNED` and has its `version` incremented; a `WELDED` joint that neither pass touches stays at `NOT_PLANNED`, and that is a legitimate terminal posture for a joint that needs no examination at all."

    PRD §3.6: "An `ACCEPT` moves the joint `nde_status` `PLANNED → ACCEPTED`, but only once **every** examination attached to that joint reads `ACCEPT`; a joint carrying both a volumetric and a surface examination stays `PLANNED` until the second one lands."

    PRD §3.6: "The value is 0.00 when the denominator is 0, and otherwise 100 multiplied by the numerator divided by the denominator, rounded half up to two decimal places."

    Design: Difficulty/non_linear_state_machine/non_linear_production_weld_parallel_nde_and_pwht_dimensions
    """
    inspector = shop.qc_inspector()
    job, joint, batch, scheduler, reviewer = _welded_joint_in_a_scheduled_charge(shop)

    shop.start_pwht_batch(batch["id"], actor=scheduler)
    shop.complete_pwht_batch(
        batch["id"],
        reviewer=reviewer,
        actual_soak_minutes=45,
        chart_record_number="CH-0001",
        chart_uploaded=True,
    )
    assert shop.read_joint(joint["id"])["pwht_status"] == PWHT_STATUS_COMPLETE

    exams = validate_success(
        client.run_nde_plan(job["id"], shop.acting_as(inspector)), 201
    )
    assert len(exams) == 1
    assert exams[0]["method"] == METHOD_RT
    assert exams[0]["exam_class"] == EXAM_CLASS_VOLUMETRIC
    assert exams[0]["required_coverage_pct"] == 25

    planned = shop.read_joint(joint["id"])
    assert planned["nde_status"] == NDE_STATUS_PLANNED
    assert planned["pwht_status"] == PWHT_STATUS_COMPLETE

    validate_success(
        client.record_exam_result(
            exams[0]["id"],
            factories.exam_result_payload(
                result="ACCEPT",
                examined_coverage_pct=25.00,
                indications_count=0,
                exam_date="2026-08-01",
            ),
            shop.acting_as(inspector),
        ),
        200,
    )

    finished = shop.read_joint(joint["id"])
    assert finished["nde_status"] == NDE_STATUS_ACCEPTED
    assert finished["pwht_status"] == PWHT_STATUS_COMPLETE
    assert finished["fab_status"] == FAB_STATUS_WELDED
    assert_number_equals(
        shop.read_job(job["id"])["weld_completion_pct"], 100.00, 2, "weld_completion_pct"
    )
