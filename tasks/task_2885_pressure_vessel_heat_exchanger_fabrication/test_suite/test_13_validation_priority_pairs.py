"""Requests that violate two rules at once, proving which of the two true diagnoses is reported."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    BATCH_STATUS_SCHEDULED,
    COMPONENT_TYPE_HEAD,
    COMPONENT_TYPE_SHELL,
    DESIGN_CODE_DIV1,
    FAB_STATUS_PLANNED,
    FURNACE_A,
    FURNACE_B,
    JOB_STATUS_FABRICATION,
    JOB_STATUS_NDE_HOLD,
    JOINT_CATEGORY_B,
    JOINT_CATEGORY_C,
    JOINT_TYPE_BUTT,
    JOINT_TYPE_FILLET,
    PROCESS_SMAW,
    PWHT_STATUS_PENDING,
    QUALIFICATION_STATUS_LAPSED,
    QUALIFICATION_STATUS_QUALIFIED,
    RT_EXTENT_FULL,
    SPEC_SA_516_70,
    VESSEL_TYPE_PRESSURE_VESSEL,
)

LAPSE_CLOCK = "2026-11-30T00:00:00.000Z"


def _job_with_one_welded_seam_and_one_planned_attachment(shop):
    """A vessel in FABRICATION carrying a welded Category B seam and a still-planned fillet."""
    job = shop.job(
        job_number="J-2885-09",
        customer_name="Northline Energy",
        vessel_type=VESSEL_TYPE_PRESSURE_VESSEL,
        design_code=DESIGN_CODE_DIV1,
        mawp_psi=350,
        design_temp_f=650,
        mdmt_f=-20,
        inside_radius_in=30.0,
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
        procedure["id"], welder_stamp="W12", welder_name="Rosa Vela", qualified_on="2026-06-01"
    )
    seam = shop.plan_joint(
        job["id"],
        procedure["id"],
        shell_part["id"],
        weld_number="W-001",
        joint_category=JOINT_CATEGORY_B,
        joint_type=JOINT_TYPE_BUTT,
        thickness_in=1.5000,
        part_b_id=head_part["id"],
    )
    attachment = shop.plan_joint(
        job["id"],
        procedure["id"],
        head_part["id"],
        weld_number="W-002",
        joint_category=JOINT_CATEGORY_C,
        joint_type=JOINT_TYPE_FILLET,
        thickness_in=0.7500,
    )
    shop.release_weld_map(job["id"])
    shop.complete_joint(seam["id"], qualification["id"], welded_at="2026-07-30T09:00:00.000Z")
    exams = shop.run_nde_plan(job["id"])
    return job, seam, attachment, qualification, exams[0]


def test_a_lapsed_welder_alone_blocks_completion_while_the_job_is_still_in_fabrication(
    client, shop
):
    """With the job in the required state, the only violated rule is the welder's continuity, so that is the diagnosis.

    PRD §3.5: "`status` is `LAPSED` when `days_since_continuity` is strictly greater than 180, and `QUALIFIED` otherwise: exactly 180 days is still `QUALIFIED`, and 181 days lapses."

    PRD §3.5: "Both `days_since_continuity` and `status` are re-derived whenever a qualification is read and whenever the logical clock is advanced, so a qualification traverses `QUALIFIED → LAPSED` purely as a consequence of the clock being set forward past its 180-day mark, with no request ever touching the qualification row, and every joint that welder could have made turns into an `ERR_WELDER_NOT_QUALIFIED` refusal."

    PRD §3.5: "The cited qualification's `status` must be `QUALIFIED`, or the request draws `ERR_WELDER_NOT_QUALIFIED` — this is the lapse check, and it is evaluated against the qualification's continuity as of the current logical date, not as of `welded_at`."

    PRD §2.8: "**Welding qualification adequacy.** Guards weld-map entry creation, weld completion and repair-joint creation, drawing `ERR_WPS_NOT_QUALIFIED`, `ERR_THICKNESS_OUTSIDE_WPS_RANGE`, `ERR_WELDER_NOT_QUALIFIED`, `ERR_QUALIFICATION_WPS_MISMATCH` or `ERR_THICKNESS_OUTSIDE_QUALIFICATION` (409)."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_job_state_outranks_lapsed_welder_on_weld_completion
    """
    engineer = shop.welding_engineer()
    job, seam, attachment, qualification, exam = _job_with_one_welded_seam_and_one_planned_attachment(
        shop
    )

    current = shop.read_welder_qualification(qualification["id"])
    assert current["status"] == QUALIFICATION_STATUS_QUALIFIED
    assert current["days_since_continuity"] == 61

    shop.set_clock(LAPSE_CLOCK)

    lapsed = shop.read_welder_qualification(qualification["id"])
    assert lapsed["days_since_continuity"] == 182
    assert lapsed["status"] == QUALIFICATION_STATUS_LAPSED
    assert lapsed["last_continuity_date"] == "2026-06-01"
    assert shop.read_job(job["id"])["status"] == JOB_STATUS_FABRICATION

    refused = client.complete_weld(
        attachment["id"],
        factories.weld_complete_payload(
            qualification["id"], welded_at="2026-11-30T09:00:00.000Z"
        ),
        shop.acting_as(engineer),
    )
    validate_error(refused, api_errors.ERR_WELDER_NOT_QUALIFIED, 409)

    untouched = shop.read_joint(attachment["id"])
    assert untouched["fab_status"] == FAB_STATUS_PLANNED
    assert untouched["welded_at"] is None
    assert untouched["welder_qualification_id"] is None
    assert exam["id"] is not None
    assert seam["id"] is not None
    assert_number_equals(
        shop.read_job(job["id"])["weld_completion_pct"], 0.00, 2, "weld_completion_pct"
    )


def test_the_examination_hold_outranks_the_welder_posture_in_both_directions(client, shop):
    """Once the job sits on an examination hold, the job-state diagnosis is reported whether or not the welder has lapsed.

    PRD §2.8: "When a request violates more than one rule, exactly one error is returned, and which one is fully determined. Checks run strictly in the ascending order below; the **first** violated check produces the response and no later check runs."

    PRD §2.8: "The required parent job state, gathered in one place: calculation submit needs the job in `DRAFT` or `DESIGN_REVIEW`; calculation revise needs `DRAFT`; part issue and part scrap need `FAB_PLANNING`, `FABRICATION` or `NDE_HOLD`; weld-map entry creation needs `FAB_PLANNING` or `FABRICATION`; weld completion needs `FABRICATION`, or `NDE_HOLD` when the joint is a repair joint whose covering nonconformance is dispositioned `REPAIR`"

    PRD §3.5: "This is the reinstatement path: a `LAPSED` qualification returns `LAPSED → QUALIFIED` on a fresh continuity log without any new performance test, and a still-current one traverses `QUALIFIED → QUALIFIED`, resetting the 180-day window each time."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_job_state_outranks_lapsed_welder_on_weld_completion
    """
    engineer = shop.welding_engineer()
    job, seam, attachment, qualification, exam = _job_with_one_welded_seam_and_one_planned_attachment(
        shop
    )

    shop.set_clock(LAPSE_CLOCK)
    validate_success(
        client.record_exam_result(
            exam["id"],
            factories.exam_result_payload(
                result="REJECT",
                examined_coverage_pct=100.00,
                indications_count=3,
                exam_date="2026-11-30",
            ),
            shop.acting_as(shop.qc_inspector()),
        ),
        200,
    )

    held = shop.read_job(job["id"])
    assert held["status"] == JOB_STATUS_NDE_HOLD
    assert held["nonconformance_open_count"] == 1

    both_violated = client.complete_weld(
        attachment["id"],
        factories.weld_complete_payload(
            qualification["id"], welded_at="2026-11-30T09:00:00.000Z"
        ),
        shop.acting_as(engineer),
    )
    validate_error(both_violated, api_errors.ERR_INVALID_JOB_STATE, 409)

    reinstated = validate_success(
        client.log_continuity(
            qualification["id"],
            factories.continuity_log_payload("2026-11-29", process=PROCESS_SMAW),
            shop.acting_as(engineer),
        ),
        200,
    )
    assert reinstated["status"] == QUALIFICATION_STATUS_QUALIFIED
    assert reinstated["days_since_continuity"] == 1
    assert reinstated["last_continuity_date"] == "2026-11-29"

    state_alone = client.complete_weld(
        attachment["id"],
        factories.weld_complete_payload(
            qualification["id"], welded_at="2026-11-30T09:00:00.000Z"
        ),
        shop.acting_as(engineer),
    )
    validate_error(state_alone, api_errors.ERR_INVALID_JOB_STATE, 409)

    untouched = shop.read_joint(attachment["id"])
    assert untouched["fab_status"] == FAB_STATUS_PLANNED
    assert untouched["welded_at"] is None
    assert seam["id"] is not None
    assert_number_equals(
        shop.read_job(job["id"])["weld_completion_pct"], 0.00, 2, "weld_completion_pct"
    )


def _two_attachment_welds_with_one_charge_booked(shop):
    """Two welded fillets needing heat treatment, the first already loaded into a morning charge."""
    job = shop.job(
        job_number="J-2885-10",
        customer_name="Northline Energy",
        vessel_type=VESSEL_TYPE_PRESSURE_VESSEL,
        design_code=DESIGN_CODE_DIV1,
        mawp_psi=350,
        design_temp_f=650,
        mdmt_f=-20,
        inside_radius_in=30.0,
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
        wps_number="WPS-2",
        pwht_required=True,
        preheat_min_f=250,
        supporting_pqr_number="PQR-2",
    )
    qualification = shop.welder_qualification(
        procedure["id"], welder_stamp="W12", welder_name="Rosa Vela", qualified_on="2026-06-01"
    )
    first = shop.plan_joint(
        job["id"],
        procedure["id"],
        shell_part["id"],
        weld_number="W-001",
        joint_category=JOINT_CATEGORY_C,
        joint_type=JOINT_TYPE_FILLET,
        thickness_in=0.7500,
    )
    second = shop.plan_joint(
        job["id"],
        procedure["id"],
        head_part["id"],
        weld_number="W-002",
        joint_category=JOINT_CATEGORY_C,
        joint_type=JOINT_TYPE_FILLET,
        thickness_in=0.5000,
    )
    shop.release_weld_map(job["id"])
    shop.complete_joint(first["id"], qualification["id"], welded_at="2026-07-30T09:00:00.000Z")
    shop.complete_joint(second["id"], qualification["id"], welded_at="2026-07-31T09:00:00.000Z")
    scheduler = shop.welding_engineer()
    booked = shop.pwht_batch(
        job["id"],
        [first["id"]],
        scheduler=scheduler,
        furnace_code=FURNACE_A,
        scheduled_start="2026-08-10T08:00:00.000Z",
        scheduled_end="2026-08-10T12:00:00.000Z",
        soak_temp_f=1150,
    )
    return job, first, second, booked, scheduler


def test_the_empty_charge_is_diagnosed_ahead_of_the_furnace_window_it_also_conflicts_with(
    client, shop
):
    """An afternoon window inside the cooldown buffer reports the empty set, because the domain limit is checked before the booking.

    PRD §3.8: "An empty array satisfies the request shape and is then refused by the domain check with `ERR_EMPTY_WELD_SET`."

    PRD §2.11: "A requested window conflicts with an existing charge in the **same** `furnace_code` when the requested `scheduled_start` falls earlier than 180 minutes after that charge's `scheduled_end`, and simultaneously the requested `scheduled_end` falls later than 180 minutes before that charge's `scheduled_start`."

    PRD §2.8: "**Domain limits and applicability.** Guards nonconformance disposition, repair-joint creation, furnace-charge scheduling, pressure-test scheduling, data-report submission to the Authorized Inspector and certificate renewal, drawing `ERR_REPAIR_LIMIT_EXCEEDED`, `ERR_EMPTY_WELD_SET`, `ERR_TEST_SIDE_NOT_APPLICABLE`, `ERR_PNEUMATIC_JUSTIFICATION_REQUIRED`, `ERR_DATA_PACKAGE_INCOMPLETE` or `ERR_RENEWAL_AUDIT_NOT_SATISFACTORY` (409)."

    PRD §2.8: "**Resource scheduling.** Guards furnace-charge scheduling and pressure-test scheduling, drawing `ERR_FURNACE_WINDOW_CONFLICT` or `ERR_TEST_BAY_CAPACITY_EXCEEDED` (409). This is the last gate in the ladder, so a request that is both out of state and in conflict with a booked window always reports the state problem."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_empty_weld_set_outranks_furnace_window_conflict
    """
    job, first, second, booked, scheduler = _two_attachment_welds_with_one_charge_booked(shop)
    assert booked["furnace_code"] == FURNACE_A
    assert booked["weld_count"] == 1

    def schedule(furnace_code, weld_ids):
        return client.create_pwht_batch(
            factories.pwht_batch_payload(
                job["id"],
                weld_ids,
                furnace_code=furnace_code,
                scheduled_start="2026-08-10T13:00:00.000Z",
                scheduled_end="2026-08-10T15:00:00.000Z",
                soak_temp_f=1150,
            ),
            shop.acting_as(scheduler),
        )

    validate_error(schedule(FURNACE_A, []), api_errors.ERR_EMPTY_WELD_SET, 409)
    validate_error(
        schedule(FURNACE_A, [second["id"]]), api_errors.ERR_FURNACE_WINDOW_CONFLICT, 409
    )
    validate_error(schedule(FURNACE_B, []), api_errors.ERR_EMPTY_WELD_SET, 409)

    _, meta = validate_paginated(
        client.list_pwht_batches(shop.admin, params={"job_id": job["id"]})
    )
    assert meta["total_count"] == 1
    assert shop.read_joint(second["id"])["pwht_batch_id"] is None
    assert shop.read_joint(first["id"])["pwht_batch_id"] == booked["id"]


def test_the_second_furnace_admits_the_same_window_and_derives_the_charge_figures(client, shop):
    """The identical window is booked in the other furnace, where nothing conflicts, and the thinner joint sets its own hold.

    PRD §2.11: "Only charges that are `SCHEDULED` or `IN_PROGRESS` are considered; `COMPLETE` and `ABORTED` charges never conflict, and a charge in the other furnace never conflicts."

    PRD §3.8: "Creation answers 201 with the charge at `status` `SCHEDULED`, `scheduled_by_personnel_id` set to the acting `X-User-ID`, `weld_count` equal to the number of entries in `weld_ids`, `chart_uploaded` false, `actual_soak_minutes` null, `chart_record_number` null and `chart_reviewed_by_personnel_id` null."

    PRD §3.8: "Each named joint has its `pwht_batch_id` set to the new charge and its `version` incremented."

    PRD §3.8: "`governing_thickness_in` is the greatest `thickness_in` among the batched joints — the thickest joint sets the hold for the whole charge."

    PRD §3.8: "`required_soak_minutes` is the larger of 15 minutes and the product of `governing_thickness_in` and 60 minutes per inch, that product being rounded half up to a whole number of minutes."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_empty_weld_set_outranks_furnace_window_conflict
    """
    job, first, second, booked, scheduler = _two_attachment_welds_with_one_charge_booked(shop)

    admitted = validate_success(
        client.create_pwht_batch(
            factories.pwht_batch_payload(
                job["id"],
                [second["id"]],
                furnace_code=FURNACE_B,
                scheduled_start="2026-08-10T13:00:00.000Z",
                scheduled_end="2026-08-10T15:00:00.000Z",
                soak_temp_f=1150,
            ),
            shop.acting_as(scheduler),
        ),
        201,
    )
    assert admitted["status"] == BATCH_STATUS_SCHEDULED
    assert admitted["furnace_code"] == FURNACE_B
    assert admitted["scheduled_by_personnel_id"] == scheduler["id"]
    assert admitted["weld_count"] == 1
    assert admitted["chart_uploaded"] is False
    assert admitted["actual_soak_minutes"] is None
    assert admitted["chart_record_number"] is None
    assert admitted["chart_reviewed_by_personnel_id"] is None
    assert_number_equals(
        admitted["governing_thickness_in"], 0.5000, 4, "governing_thickness_in"
    )
    assert admitted["required_soak_minutes"] == 30

    loaded = shop.read_joint(second["id"])
    assert loaded["pwht_batch_id"] == admitted["id"]
    assert loaded["pwht_status"] == PWHT_STATUS_PENDING
    assert loaded["version"] > second["version"]
    assert shop.read_joint(first["id"])["pwht_batch_id"] == booked["id"]

    rows, meta = validate_paginated(
        client.list_pwht_batches(shop.admin, params={"job_id": job["id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(row["furnace_code"] for row in rows) == [FURNACE_A, FURNACE_B]
