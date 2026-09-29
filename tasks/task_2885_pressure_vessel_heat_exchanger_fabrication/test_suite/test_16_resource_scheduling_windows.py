"""Booked windows on the two shop resources, probed one minute either side of every declared edge."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    BATCH_STATUS_SCHEDULED,
    BAY_2,
    COMPONENT_TYPE_HEAD,
    COMPONENT_TYPE_SHELL,
    COMPONENT_TYPE_TUBESHEET,
    DESIGN_CODE_DIV1,
    FURNACE_A,
    FURNACE_B,
    JOB_STATUS_TESTING,
    JOINT_CATEGORY_C,
    JOINT_TYPE_FILLET,
    RT_EXTENT_NONE,
    SPEC_SA_516_70,
    TEST_RESULT_PENDING,
    TEST_SIDE_SHELL,
    TEST_SIDE_TUBE,
    TEST_TYPE_HYDROSTATIC,
    TEST_TYPE_PNEUMATIC,
    VESSEL_TYPE_HEAT_EXCHANGER,
    VESSEL_TYPE_PRESSURE_VESSEL,
)


def _five_welded_fillets_and_a_morning_charge(shop):
    """Five identical heat-treatable fillets, the first booked into FURNACE_A from 08:00 to 12:00."""
    job = shop.job(
        job_number="J-2885-14",
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
        rt_extent_declared=RT_EXTENT_NONE,
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
        wps_number="WPS-2",
        pwht_required=True,
        preheat_min_f=250,
        supporting_pqr_number="PQR-2",
    )
    qualification = shop.welder_qualification(
        procedure["id"], welder_stamp="W12", welder_name="Rosa Vela", qualified_on="2026-06-01"
    )
    joints = []
    for index in range(1, 6):
        joints.append(
            shop.plan_joint(
                job["id"],
                procedure["id"],
                shell_part["id"],
                weld_number="W-00{0}".format(index),
                joint_category=JOINT_CATEGORY_C,
                joint_type=JOINT_TYPE_FILLET,
                thickness_in=0.7500,
                part_b_id=head_part["id"],
            )
        )
    shop.release_weld_map(job["id"])
    for joint in joints:
        shop.complete_joint(
            joint["id"], qualification["id"], welded_at="2026-07-30T09:00:00.000Z"
        )
    scheduler = shop.welding_engineer()
    booked = shop.pwht_batch(
        job["id"],
        [joints[0]["id"]],
        scheduler=scheduler,
        furnace_code=FURNACE_A,
        scheduled_start="2026-08-10T08:00:00.000Z",
        scheduled_end="2026-08-10T12:00:00.000Z",
        soak_temp_f=1150,
    )
    return job, joints, booked, scheduler


def _charge(client, shop, job, scheduler, furnace_code, start, end, weld_ids):
    return client.create_pwht_batch(
        factories.pwht_batch_payload(
            job["id"],
            weld_ids,
            furnace_code=furnace_code,
            scheduled_start=start,
            scheduled_end=end,
            soak_temp_f=1150,
        ),
        shop.acting_as(scheduler),
    )


def test_a_charge_ending_one_minute_inside_the_pre_cooldown_buffer_is_refused_and_the_edge_is_not(
    client, shop
):
    """Three hours and one minute of clearance ahead of a booked charge is not enough; exactly three hours is.

    PRD §2.11: "The **post-weld heat-treatment furnaces** — `FURNACE_A` and `FURNACE_B` — are treated as closed intervals surrounded by a three-hour cooldown buffer of 180 minutes on each side."

    PRD §2.11: "A requested window conflicts with an existing charge in the **same** `furnace_code` when the requested `scheduled_start` falls earlier than 180 minutes after that charge's `scheduled_end`, and simultaneously the requested `scheduled_end` falls later than 180 minutes before that charge's `scheduled_start`."

    PRD §3.8: "`required_soak_minutes` is the larger of 15 minutes and the product of `governing_thickness_in` and 60 minutes per inch, that product being rounded half up to a whole number of minutes."

    Design: Difficulty/resource_temporal_overlap/resource_temporal_furnace_cooldown_buffer_boundaries_both_directions
    """
    job, joints, booked, scheduler = _five_welded_fillets_and_a_morning_charge(shop)
    assert booked["furnace_code"] == FURNACE_A

    one_minute_inside = _charge(
        client,
        shop,
        job,
        scheduler,
        FURNACE_A,
        "2026-08-10T03:00:00.000Z",
        "2026-08-10T05:01:00.000Z",
        [joints[1]["id"]],
    )
    validate_error(one_minute_inside, api_errors.ERR_FURNACE_WINDOW_CONFLICT, 409)
    assert shop.read_joint(joints[1]["id"])["pwht_batch_id"] is None

    on_the_edge = validate_success(
        _charge(
            client,
            shop,
            job,
            scheduler,
            FURNACE_A,
            "2026-08-10T03:00:00.000Z",
            "2026-08-10T05:00:00.000Z",
            [joints[1]["id"]],
        ),
        201,
    )
    assert on_the_edge["status"] == BATCH_STATUS_SCHEDULED
    assert on_the_edge["furnace_code"] == FURNACE_A
    assert on_the_edge["required_soak_minutes"] == 45
    assert_number_equals(
        on_the_edge["governing_thickness_in"], 0.7500, 4, "governing_thickness_in"
    )
    assert shop.read_joint(joints[1]["id"])["pwht_batch_id"] == on_the_edge["id"]

    _, meta = validate_paginated(
        client.list_pwht_batches(shop.admin, params={"job_id": job["id"]})
    )
    assert meta["total_count"] == 2


def test_the_forward_buffer_edge_is_admitted_while_containment_conflicts_and_the_other_furnace_does_not(
    client, shop
):
    """The buffer bites in both directions, a wholly contained window is an ordinary conflict, and the same window is free in the other furnace.

    PRD §2.11: "The boundary is exact: a window beginning precisely 180 minutes after an existing charge ends is admitted, while one beginning 179 minutes after it ends is refused with `ERR_FURNACE_WINDOW_CONFLICT`."

    PRD §2.11: "Only charges that are `SCHEDULED` or `IN_PROGRESS` are considered; `COMPLETE` and `ABORTED` charges never conflict, and a charge in the other furnace never conflicts."

    PRD §3.8: "Each named joint has its `pwht_batch_id` set to the new charge and its `version` incremented."

    PRD §3.8: "Charges are listed with filters on `job_id`, `scheduled_by_personnel_id`, `chart_reviewed_by_personnel_id`, `furnace_code` and `status`."

    Design: Difficulty/resource_temporal_overlap/resource_temporal_furnace_cooldown_buffer_boundaries_both_directions
    """
    job, joints, booked, scheduler = _five_welded_fillets_and_a_morning_charge(shop)
    early = shop.pwht_batch(
        job["id"],
        [joints[1]["id"]],
        scheduler=scheduler,
        furnace_code=FURNACE_A,
        scheduled_start="2026-08-10T03:00:00.000Z",
        scheduled_end="2026-08-10T05:00:00.000Z",
        soak_temp_f=1150,
    )

    late_by_one_minute = _charge(
        client,
        shop,
        job,
        scheduler,
        FURNACE_A,
        "2026-08-10T14:59:00.000Z",
        "2026-08-10T16:59:00.000Z",
        [joints[2]["id"]],
    )
    validate_error(late_by_one_minute, api_errors.ERR_FURNACE_WINDOW_CONFLICT, 409)

    on_the_edge = validate_success(
        _charge(
            client,
            shop,
            job,
            scheduler,
            FURNACE_A,
            "2026-08-10T15:00:00.000Z",
            "2026-08-10T17:00:00.000Z",
            [joints[2]["id"]],
        ),
        201,
    )
    assert on_the_edge["status"] == BATCH_STATUS_SCHEDULED
    assert shop.read_joint(joints[2]["id"])["pwht_batch_id"] == on_the_edge["id"]

    contained = _charge(
        client,
        shop,
        job,
        scheduler,
        FURNACE_A,
        "2026-08-10T09:00:00.000Z",
        "2026-08-10T10:00:00.000Z",
        [joints[3]["id"]],
    )
    validate_error(contained, api_errors.ERR_FURNACE_WINDOW_CONFLICT, 409)

    other_furnace = validate_success(
        _charge(
            client,
            shop,
            job,
            scheduler,
            FURNACE_B,
            "2026-08-10T09:00:00.000Z",
            "2026-08-10T10:00:00.000Z",
            [joints[3]["id"]],
        ),
        201,
    )
    assert other_furnace["furnace_code"] == FURNACE_B
    assert other_furnace["status"] == BATCH_STATUS_SCHEDULED

    fourth = shop.read_joint(joints[3]["id"])
    assert fourth["pwht_batch_id"] == other_furnace["id"]
    assert fourth["version"] > joints[3]["version"]
    assert shop.read_joint(joints[4]["id"])["pwht_batch_id"] is None

    rows, meta = validate_paginated(
        client.list_pwht_batches(shop.admin, params={"job_id": job["id"]})
    )
    assert meta["total_count"] == 4
    assert sorted(row["id"] for row in rows) == sorted(
        [booked["id"], early["id"], on_the_edge["id"], other_furnace["id"]]
    )


PNEUMATIC_JUSTIFICATION = (
    "Internals cannot tolerate the weight of water; UG-100 pneumatic test authorized."
)


def _two_examined_heat_exchangers(shop):
    """Two two-chamber vessels ready to test, the second one cleared for pneumatic testing."""
    certificate = shop.certificate(
        cert_number="CA-U-8801",
        scope_codes=["U"],
        issued_on="2026-01-01",
        expires_on="2029-01-01",
    )
    heat = shop.accepted_heat(
        heat_number="H-4471", spec=SPEC_SA_516_70, quantity_received_lb=2000.00
    )
    procedure = shop.qualified_wps(wps_number="WPS-1", pwht_required=False, preheat_min_f=50)
    qualification = shop.welder_qualification(
        procedure["id"], welder_stamp="W12", welder_name="Rosa Vela", qualified_on="2026-06-01"
    )

    def exchanger(job_number, suffix, **overrides):
        job = shop.job(
            certificate,
            job_number=job_number,
            customer_name="Northline Energy",
            vessel_type=VESSEL_TYPE_HEAT_EXCHANGER,
            design_code=DESIGN_CODE_DIV1,
            mawp_psi=350,
            design_temp_f=650,
            mdmt_f=-20,
            inside_radius_in=30.0,
            stress_ratio=1.00,
            **overrides
        )
        shop.release_design(
            job,
            rt_extent_declared=RT_EXTENT_NONE,
            allowable_stress_psi=20000,
            corrosion_allowance_in=0.0625,
            thickness_nominal_in=1.0000,
        )
        shell_part = shop.issue_part(
            job["id"],
            heat["id"],
            part_mark="SH-{0}".format(suffix),
            component_type=COMPONENT_TYPE_SHELL,
            issued_quantity_lb=400.00,
        )
        head_part = shop.issue_part(
            job["id"],
            heat["id"],
            part_mark="HD-{0}".format(suffix),
            component_type=COMPONENT_TYPE_HEAD,
            issued_quantity_lb=200.00,
        )
        shop.issue_part(
            job["id"],
            heat["id"],
            part_mark="TS-{0}".format(suffix),
            component_type=COMPONENT_TYPE_TUBESHEET,
            issued_quantity_lb=200.00,
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
            joint["id"], qualification["id"], welded_at="2026-07-30T09:00:00.000Z"
        )
        exams = shop.run_nde_plan(job["id"])
        shop.accept_exam(exams[0]["id"], examined_coverage_pct=100.00, exam_date="2026-08-01")
        return job

    first = exchanger("J-2885-15", "01")
    second = exchanger(
        "J-2885-16", "02", pneumatic_justification=PNEUMATIC_JUSTIFICATION
    )
    return first, second


def _book_bay(client, shop, job, inspector, test_side, test_type, start, end):
    return client.create_pressure_test(
        factories.pressure_test_payload(
            job["id"],
            test_side=test_side,
            test_type=test_type,
            test_bay_code=BAY_2,
            scheduled_start=start,
            scheduled_end=end,
        ),
        shop.acting_as(inspector),
    )


def test_one_bay_carries_two_concurrent_hydrostatic_tests_and_refuses_the_third(client, shop):
    """The first test also carries its job into testing; the second reaches the bay's hydrostatic capacity and the third exceeds it.

    PRD §2.11: "The **pressure-test bays** — `BAY_1` and `BAY_2` — are treated as half-open intervals with no buffer."

    PRD §2.11: "Within a single `test_bay_code` the shop tolerates two concurrent hydrostatic tests but no concurrent pneumatic test at all: a new `HYDROSTATIC` test is admitted only when it overlaps at most one existing pending `HYDROSTATIC` test in that bay, and a new `PNEUMATIC` test is admitted only when it overlaps nothing whatsoever in that bay — neither another pneumatic test nor any hydrostatic one."

    PRD §3.8: "For a `HYDROSTATIC` test, `test_pressure_psi` is 1.3 multiplied by the job's `mawp_psi` multiplied by the job's `stress_ratio`, rounded half up to one decimal place; `min_hold_minutes` is 30; and `min_medium_temp_f` is the job's `mdmt_f` plus 30."

    PRD §3.8: "A heat exchanger owes a test per chamber, so a job already in `TESTING` admits further tests through a self-transition `TESTING → TESTING`, subject to there being no existing test of the job on the same `test_side` whose `result` is still `PENDING`."

    Design: Difficulty/resource_temporal_overlap/resource_temporal_test_bay_half_open_windows_with_aggregate_capacity
    """
    inspector = shop.qc_inspector()
    first_job, second_job = _two_examined_heat_exchangers(shop)

    opening = validate_success(
        _book_bay(
            client,
            shop,
            first_job,
            inspector,
            TEST_SIDE_SHELL,
            TEST_TYPE_HYDROSTATIC,
            "2026-08-12T08:00:00.000Z",
            "2026-08-12T12:00:00.000Z",
        ),
        201,
    )
    assert opening["result"] == TEST_RESULT_PENDING
    assert_number_equals(opening["test_pressure_psi"], 455.0, 1, "test_pressure_psi")
    assert opening["min_hold_minutes"] == 30
    assert opening["min_medium_temp_f"] == 10
    assert shop.read_job(first_job["id"])["status"] == JOB_STATUS_TESTING

    at_capacity = validate_success(
        _book_bay(
            client,
            shop,
            first_job,
            inspector,
            TEST_SIDE_TUBE,
            TEST_TYPE_HYDROSTATIC,
            "2026-08-12T10:00:00.000Z",
            "2026-08-12T14:00:00.000Z",
        ),
        201,
    )
    assert at_capacity["result"] == TEST_RESULT_PENDING
    assert at_capacity["test_side"] == TEST_SIDE_TUBE

    over_capacity = _book_bay(
        client,
        shop,
        second_job,
        inspector,
        TEST_SIDE_SHELL,
        TEST_TYPE_HYDROSTATIC,
        "2026-08-12T11:00:00.000Z",
        "2026-08-12T13:00:00.000Z",
    )
    validate_error(over_capacity, api_errors.ERR_TEST_BAY_CAPACITY_EXCEEDED, 409)

    _, meta = validate_paginated(
        client.list_pressure_tests(shop.admin, params={"test_bay_code": BAY_2})
    )
    assert meta["total_count"] == 2


def test_a_pneumatic_test_must_touch_nothing_and_the_half_open_edge_lets_it_in(client, shop):
    """One minute of overlap defeats a pneumatic booking while an exactly adjacent start is admitted, and the pneumatic figures diverge from the hydrostatic ones in the same bay.

    PRD §2.11: "Two windows overlap when the new `scheduled_start` is earlier than the existing `scheduled_end` and the new `scheduled_end` is later than the existing `scheduled_start`; a window that begins exactly when another ends therefore does not overlap."

    PRD §2.11: "A pneumatic test already holding a bay likewise blocks any new test overlapping it."

    PRD §3.8: "For a `PNEUMATIC` test, `test_pressure_psi` is 1.1 multiplied by `mawp_psi` multiplied by `stress_ratio`, rounded half up to one decimal place; `min_hold_minutes` is 60; and `min_medium_temp_f` is `mdmt_f` plus 60."

    PRD §3.8: "The pneumatic variant deliberately demands a **lower** pressure — compressed gas stores far more energy than water, so the code reduces the overpressure — while demanding a **longer** hold and a **warmer** medium to guard against brittle fracture."

    Design: Difficulty/resource_temporal_overlap/resource_temporal_test_bay_half_open_windows_with_aggregate_capacity
    """
    inspector = shop.qc_inspector()
    first_job, second_job = _two_examined_heat_exchangers(shop)

    validate_success(
        _book_bay(
            client,
            shop,
            first_job,
            inspector,
            TEST_SIDE_SHELL,
            TEST_TYPE_HYDROSTATIC,
            "2026-08-12T08:00:00.000Z",
            "2026-08-12T12:00:00.000Z",
        ),
        201,
    )
    validate_success(
        _book_bay(
            client,
            shop,
            first_job,
            inspector,
            TEST_SIDE_TUBE,
            TEST_TYPE_HYDROSTATIC,
            "2026-08-12T10:00:00.000Z",
            "2026-08-12T14:00:00.000Z",
        ),
        201,
    )

    touching_by_one_minute = _book_bay(
        client,
        shop,
        second_job,
        inspector,
        TEST_SIDE_SHELL,
        TEST_TYPE_PNEUMATIC,
        "2026-08-12T13:59:00.000Z",
        "2026-08-12T18:00:00.000Z",
    )
    validate_error(touching_by_one_minute, api_errors.ERR_TEST_BAY_CAPACITY_EXCEEDED, 409)

    adjacent = validate_success(
        _book_bay(
            client,
            shop,
            second_job,
            inspector,
            TEST_SIDE_SHELL,
            TEST_TYPE_PNEUMATIC,
            "2026-08-12T14:00:00.000Z",
            "2026-08-12T18:00:00.000Z",
        ),
        201,
    )
    assert adjacent["test_type"] == TEST_TYPE_PNEUMATIC
    assert adjacent["result"] == TEST_RESULT_PENDING
    assert_number_equals(adjacent["test_pressure_psi"], 385.0, 1, "test_pressure_psi")
    assert adjacent["min_hold_minutes"] == 60
    assert adjacent["min_medium_temp_f"] == 40
    assert shop.read_job(second_job["id"])["status"] == JOB_STATUS_TESTING

    disjoint_hydro = validate_success(
        _book_bay(
            client,
            shop,
            second_job,
            inspector,
            TEST_SIDE_TUBE,
            TEST_TYPE_HYDROSTATIC,
            "2026-08-12T12:00:00.000Z",
            "2026-08-12T13:00:00.000Z",
        ),
        201,
    )
    assert_number_equals(disjoint_hydro["test_pressure_psi"], 455.0, 1, "test_pressure_psi")
    assert disjoint_hydro["min_hold_minutes"] == 30
    assert disjoint_hydro["min_medium_temp_f"] == 10

    rows, meta = validate_paginated(
        client.list_pressure_tests(shop.admin, params={"test_bay_code": BAY_2})
    )
    assert meta["total_count"] == 4
    assert all(row["result"] == TEST_RESULT_PENDING for row in rows)
