"""Both variants of a dual-variant computation are reported from one request pair."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories
from test_helpers.assertions import assert_number_equals, assert_scale
from test_helpers.constants import (
    BAY_1,
    BAY_2,
    CALC_STATUS_DRAFT,
    COMPONENT_SHELL,
    COMPONENT_TYPE_HEAD,
    COMPONENT_TYPE_SHELL,
    DESIGN_CODE_DIV1,
    JOB_STATUS_DRAFT,
    JOB_STATUS_TESTING,
    JOINT_CATEGORY_C,
    JOINT_TYPE_FILLET,
    RT_EXTENT_FULL,
    SPEC_SA_516_70,
    TEST_RESULT_PENDING,
    TEST_SIDE_SHELL,
    TEST_SIDE_TUBE,
    TEST_TYPE_HYDROSTATIC,
    TEST_TYPE_PNEUMATIC,
    VARIANT_CIRCUMFERENTIAL,
    VESSEL_TYPE_HEAT_EXCHANGER,
    VESSEL_TYPE_PRESSURE_VESSEL,
)

PNEUMATIC_JUSTIFICATION = (
    "Tube bundle cannot be drained or dried after a hydrostatic fill; "
    "pneumatic test of the tube side authorized."
)


def _shell_sheet_job(shop):
    """A DRAFT pressure vessel whose envelope carries the terms of both wall formulas."""
    certificate = shop.certificate(cert_number="CA-U-8801")
    return shop.job(
        certificate,
        job_number="J-2885-01",
        customer_name="Northline Energy",
        vessel_type=VESSEL_TYPE_PRESSURE_VESSEL,
        design_code=DESIGN_CODE_DIV1,
        mawp_psi=350,
        design_temp_f=650,
        mdmt_f=-20,
        inside_radius_in=30.0,
        stress_ratio=1.00,
    )


def _prepare_shell_sheet(shop, client, job, preparer):
    """The single trigger create: one SHELL sheet at FULL radiography."""
    return validate_success(
        client.create_calculation(
            job["id"],
            factories.design_calculation_payload(
                shop.job_version(job["id"]),
                component=COMPONENT_SHELL,
                rt_extent_declared=RT_EXTENT_FULL,
                allowable_stress_psi=20000,
                corrosion_allowance_in=0.0625,
                thickness_nominal_in=1.0000,
            ),
            shop.acting_as(preparer),
        ),
        201,
    )


def _exchanger_ready_for_testing(shop):
    """A heat exchanger whose whole weld map is welded and examined, so tests may be booked."""
    certificate = shop.certificate(cert_number="CA-U-8801")
    job = shop.job(
        certificate,
        job_number="J-2885-02",
        customer_name="Northline Energy",
        vessel_type=VESSEL_TYPE_HEAT_EXCHANGER,
        design_code=DESIGN_CODE_DIV1,
        mawp_psi=350,
        design_temp_f=650,
        mdmt_f=-20,
        inside_radius_in=30.0,
        stress_ratio=1.00,
        pneumatic_justification=PNEUMATIC_JUSTIFICATION,
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
    procedure = shop.qualified_wps(wps_number="WPS-1", pwht_required=False, preheat_min_f=50)
    qualification = shop.welder_qualification(
        procedure["id"], welder_stamp="W12", welder_name="Rosa Vela"
    )
    joint = shop.plan_joint(
        job["id"],
        procedure["id"],
        shell_part["id"],
        weld_number="W-001",
        joint_category=JOINT_CATEGORY_C,
        joint_type=JOINT_TYPE_FILLET,
        thickness_in=0.7500,
        part_b_id=head_part["id"],
    )
    shop.release_weld_map(job["id"])
    shop.complete_joint(
        joint["id"], qualification["id"], welded_at="2026-07-31T14:00:00.000Z"
    )
    exams = shop.run_nde_plan(job["id"])
    shop.accept_exam(exams[0]["id"], examined_coverage_pct=100.00, exam_date="2026-08-01")
    return job


def test_one_shell_sheet_reports_both_stress_variants_and_the_once_rounded_required_wall(
    client, shop
):
    """A single sheet carries the circumferential wall, the longitudinal wall and the sum rounded once.

    PRD §3.3: "`joint_efficiency` is resolved directly from `rt_extent_declared`: a `FULL` declaration yields 1.00, a `SPOT` declaration yields 0.85 and a `NONE` declaration yields 0.70, carried at two decimal places."

    PRD §3.3: "The circumferential-stress variant — the one that governs a cylindrical shell's longitudinal seam — demands a thickness equal to the pressure multiplied by the radius, divided by the quantity formed by taking the stress multiplied by the efficiency and subtracting six tenths of the pressure."

    PRD §3.3: "The longitudinal-stress variant — the circumferential-seam case — demands a thickness equal to the pressure multiplied by the radius, divided by the quantity formed by taking twice the stress multiplied by the efficiency and adding four tenths of the pressure."

    PRD §3.3: "`thickness_circumferential_in` and `thickness_longitudinal_in` are each of those two raw values rounded half up to four decimal places."

    PRD §3.3: "`thickness_required_in` is the greater of the two unrounded values, plus `corrosion_allowance_in`, with the sum rounded half up to four decimal places **once**."

    Design: Difficulty/dual_variant_calc/dual_variant_shell_thickness_circumferential_vs_longitudinal
    """
    preparer = shop.design_engineer()
    job = _shell_sheet_job(shop)

    sheet = _prepare_shell_sheet(shop, client, job, preparer)

    assert_number_equals(sheet["joint_efficiency"], 1.00, 2, "joint_efficiency")
    assert_number_equals(
        sheet["thickness_circumferential_in"], 0.5306, 4, "thickness_circumferential_in"
    )
    assert_number_equals(
        sheet["thickness_longitudinal_in"], 0.2616, 4, "thickness_longitudinal_in"
    )
    assert_number_equals(sheet["thickness_required_in"], 0.5931, 4, "thickness_required_in")
    assert sheet["governing_variant"] == VARIANT_CIRCUMFERENTIAL

    difference = float(sheet["thickness_circumferential_in"]) - float(
        sheet["thickness_longitudinal_in"]
    )
    assert_number_equals(round(difference, 4), 0.2690, 4, "variant difference")
    assert float(sheet["thickness_circumferential_in"]) > float(
        sheet["thickness_longitudinal_in"]
    )

    read_back = validate_success(client.get_calculation(sheet["id"], shop.admin), 200)
    assert_scale(read_back["thickness_circumferential_in"], 4, "thickness_circumferential_in")
    assert_scale(read_back["thickness_longitudinal_in"], 4, "thickness_longitudinal_in")
    assert_scale(read_back["thickness_required_in"], 4, "thickness_required_in")
    assert read_back["governing_variant"] == VARIANT_CIRCUMFERENTIAL


def test_neither_reported_variant_absorbs_the_corrosion_allowance_on_a_fresh_draft_sheet(
    client, shop
):
    """The allowance lands only on `thickness_required_in`, and the fresh sheet leaves the job in DRAFT.

    PRD §3.3: "Both are report-only, both are always populated, and **neither of them ever includes the corrosion allowance**."

    PRD §3.3: "`governing_variant` is `CIRCUMFERENTIAL` whenever the unrounded circumferential value is greater than or equal to the unrounded longitudinal value, and `LONGITUDINAL` otherwise."

    PRD §3.3: "Creation answers 201 with the sheet at `status` `DRAFT`, `prepared_by_personnel_id` set to the acting `X-User-ID`, `reviewed_by_personnel_id` null and `reject_reason` null."

    PRD §3.3: "`revision` is a system-maintained index scoped to the pairing of job and `component`: the first sheet for a component is revision 1, and each superseding sheet starts at one more than the revision of the sheet it supersedes."

    PRD §3.2: "`governing_joint_efficiency` is the smallest `joint_efficiency` among the job's approved calculation sheets, and null while no sheet is approved."

    Design: Difficulty/dual_variant_calc/dual_variant_shell_thickness_circumferential_vs_longitudinal
    """
    preparer = shop.design_engineer()
    job = _shell_sheet_job(shop)

    sheet = _prepare_shell_sheet(shop, client, job, preparer)

    allowance = 0.0625
    assert_number_equals(
        round(float(sheet["thickness_required_in"]) - allowance, 4),
        0.5306,
        4,
        "required minus allowance",
    )
    assert float(sheet["thickness_circumferential_in"]) < float(sheet["thickness_required_in"])
    assert_number_equals(
        round(float(sheet["thickness_circumferential_in"]) + allowance, 4),
        0.5931,
        4,
        "circumferential plus allowance",
    )
    assert_number_equals(sheet["corrosion_allowance_in"], 0.0625, 4, "corrosion_allowance_in")

    assert sheet["revision"] == 1
    assert sheet["status"] == CALC_STATUS_DRAFT
    assert sheet["prepared_by_personnel_id"] == preparer["id"]
    assert sheet["reviewed_by_personnel_id"] is None
    assert sheet["reject_reason"] is None

    after = shop.read_job(job["id"])
    assert after["status"] == JOB_STATUS_DRAFT
    assert after["governing_joint_efficiency"] is None


def test_the_hydrostatic_shell_side_test_carries_the_higher_pressure_and_the_shorter_hold(
    client, shop
):
    """Booking the first test opens TESTING and derives the hydrostatic triple from the envelope.

    PRD §3.8: "For a `HYDROSTATIC` test, `test_pressure_psi` is 1.3 multiplied by the job's `mawp_psi` multiplied by the job's `stress_ratio`, rounded half up to one decimal place; `min_hold_minutes` is 30; and `min_medium_temp_f` is the job's `mdmt_f` plus 30."

    PRD §3.8: "Creation answers 201 with the test at `result` `PENDING`, `ai_witness_confirmed` false, `witnessed_by_personnel_id` null and the observed figures null."

    PRD §3.8: "Scheduling the first test of a job is the aggregate gate that moves it `FABRICATION → TESTING`, and it walks the entire weld map."

    Design: Difficulty/dual_variant_calc/dual_variant_test_pressure_hydrostatic_vs_pneumatic
    """
    inspector = shop.qc_inspector()
    job = _exchanger_ready_for_testing(shop)

    hydrostatic = validate_success(
        client.create_pressure_test(
            factories.pressure_test_payload(
                job["id"],
                test_side=TEST_SIDE_SHELL,
                test_type=TEST_TYPE_HYDROSTATIC,
                test_bay_code=BAY_1,
                scheduled_start="2026-08-10T08:00:00.000Z",
                scheduled_end="2026-08-10T12:00:00.000Z",
            ),
            shop.acting_as(inspector),
        ),
        201,
    )

    assert_number_equals(hydrostatic["test_pressure_psi"], 455.0, 1, "test_pressure_psi")
    assert hydrostatic["min_hold_minutes"] == 30
    assert hydrostatic["min_medium_temp_f"] == 10
    assert hydrostatic["result"] == TEST_RESULT_PENDING
    assert hydrostatic["ai_witness_confirmed"] is False
    assert hydrostatic["witnessed_by_personnel_id"] is None
    assert hydrostatic["observed_pressure_psi"] is None
    assert hydrostatic["observed_hold_minutes"] is None
    assert hydrostatic["test_medium_temp_f"] is None

    assert shop.read_job(job["id"])["status"] == JOB_STATUS_TESTING


def test_the_pneumatic_tube_side_test_drops_the_pressure_while_lengthening_the_hold(client, shop):
    """The second chamber's pneumatic booking diverges from the hydrostatic one in all three parameters.

    PRD §3.8: "For a `PNEUMATIC` test, `test_pressure_psi` is 1.1 multiplied by `mawp_psi` multiplied by `stress_ratio`, rounded half up to one decimal place; `min_hold_minutes` is 60; and `min_medium_temp_f` is `mdmt_f` plus 60."

    PRD §3.8: "The pneumatic variant deliberately demands a **lower** pressure — compressed gas stores far more energy than water, so the code reduces the overpressure — while demanding a **longer** hold and a **warmer** medium to guard against brittle fracture."

    PRD §3.8: "A heat exchanger owes a test per chamber, so a job already in `TESTING` admits further tests through a self-transition `TESTING → TESTING`, subject to there being no existing test of the job on the same `test_side` whose `result` is still `PENDING`."

    Design: Difficulty/dual_variant_calc/dual_variant_test_pressure_hydrostatic_vs_pneumatic
    """
    inspector = shop.qc_inspector()
    job = _exchanger_ready_for_testing(shop)

    hydrostatic = validate_success(
        client.create_pressure_test(
            factories.pressure_test_payload(
                job["id"],
                test_side=TEST_SIDE_SHELL,
                test_type=TEST_TYPE_HYDROSTATIC,
                test_bay_code=BAY_1,
                scheduled_start="2026-08-10T08:00:00.000Z",
                scheduled_end="2026-08-10T12:00:00.000Z",
            ),
            shop.acting_as(inspector),
        ),
        201,
    )
    assert shop.read_job(job["id"])["status"] == JOB_STATUS_TESTING

    pneumatic = validate_success(
        client.create_pressure_test(
            factories.pressure_test_payload(
                job["id"],
                test_side=TEST_SIDE_TUBE,
                test_type=TEST_TYPE_PNEUMATIC,
                test_bay_code=BAY_2,
                scheduled_start="2026-08-11T08:00:00.000Z",
                scheduled_end="2026-08-11T14:00:00.000Z",
            ),
            shop.acting_as(inspector),
        ),
        201,
    )

    assert_number_equals(pneumatic["test_pressure_psi"], 385.0, 1, "test_pressure_psi")
    assert pneumatic["min_hold_minutes"] == 60
    assert pneumatic["min_medium_temp_f"] == 40
    assert pneumatic["result"] == TEST_RESULT_PENDING
    assert pneumatic["ai_witness_confirmed"] is False

    pressure_gap = float(hydrostatic["test_pressure_psi"]) - float(pneumatic["test_pressure_psi"])
    assert_number_equals(round(pressure_gap, 1), 70.0, 1, "pressure gap")
    assert pneumatic["min_hold_minutes"] - hydrostatic["min_hold_minutes"] == 30
    assert pneumatic["min_medium_temp_f"] - hydrostatic["min_medium_temp_f"] == 30

    assert shop.read_job(job["id"])["status"] == JOB_STATUS_TESTING
