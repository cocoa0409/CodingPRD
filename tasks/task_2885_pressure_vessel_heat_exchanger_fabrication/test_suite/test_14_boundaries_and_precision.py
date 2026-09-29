"""Values sitting exactly on a declared threshold, and the pair of values one unit either side of it."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    COMPONENT_TYPE_HEAD,
    COMPONENT_TYPE_SHELL,
    DESIGN_CODE_DIV1,
    FAB_STATUS_PLANNED,
    HEAT_STATUS_ACCEPTED,
    HEAT_STATUS_DEPLETED,
    JOINT_CATEGORY_B,
    JOINT_CATEGORY_C,
    JOINT_TYPE_BUTT,
    JOINT_TYPE_FILLET,
    METHOD_MT,
    METHOD_RT,
    METHOD_UT,
    NDE_STATUS_NOT_PLANNED,
    PART_STATUS_ISSUED,
    PWHT_STATUS_NOT_REQUIRED,
    RT_EXTENT_FULL,
    RT_EXTENT_SPOT,
    SPEC_SA_516_70,
    VESSEL_TYPE_PRESSURE_VESSEL,
)


def _job_ready_to_plan_joints(shop, job_number, rt_extent_declared):
    """A vessel released into fabrication planning with a shell piece and a head piece on the floor."""
    job = shop.job(
        job_number=job_number,
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
        rt_extent_declared=rt_extent_declared,
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
    return job, heat, shell_part, head_part, procedure


def test_the_category_b_full_radiography_threshold_admits_the_exact_value_and_excludes_the_one_below(
    client, shop
):
    """Three circumferential seams a thousandth of an inch apart split at 1.500 inch and nowhere else.

    PRD §3.6: "For a Category B joint, a `FULL` declaration gives 100 when `thickness_in` is at least 1.500 and gives 25 when it is thinner, a `SPOT` declaration gives 25, and a `NONE` declaration gives 0."

    PRD §3.6: "`volumetric_method` is null whenever the resolved coverage is 0. Otherwise it is `UT` when `thickness_in` is at least 2.000 **and** `joint_type` is `BUTT`, since ultrasonic examination is the practical method on heavy butt joints, and `RT` in every other case."

    PRD §3.5: "A newly planned joint opens with `fab_status` `PLANNED`, `nde_status` `NOT_PLANNED`, `repair_generation` 0, `repair_of_weld_id` null, `pwht_batch_id` null, `welder_qualification_id` null and `welded_at` null."

    Design: Difficulty/boundary_precision_check/boundary_category_b_full_rt_thickness_threshold_and_ut_crossover
    """
    engineer = shop.welding_engineer()
    job, heat, shell_part, head_part, procedure = _job_ready_to_plan_joints(
        shop, "J-2885-11", RT_EXTENT_FULL
    )

    def plan(weld_number, thickness_in):
        return validate_success(
            client.plan_weld(
                job["id"],
                factories.production_weld_payload(
                    procedure["id"],
                    shell_part["id"],
                    weld_number=weld_number,
                    joint_category=JOINT_CATEGORY_B,
                    joint_type=JOINT_TYPE_BUTT,
                    thickness_in=thickness_in,
                    part_b_id=head_part["id"],
                ),
                shop.acting_as(engineer),
            ),
            201,
        )

    below = plan("W-001", 1.4990)
    assert below["required_volumetric_pct"] == 25
    assert below["volumetric_method"] == METHOD_RT

    exactly = plan("W-002", 1.5000)
    assert exactly["required_volumetric_pct"] == 100
    assert exactly["volumetric_method"] == METHOD_RT

    above = plan("W-003", 1.5010)
    assert above["required_volumetric_pct"] == 100
    assert above["volumetric_method"] == METHOD_RT

    for joint in (below, exactly, above):
        assert joint["fab_status"] == FAB_STATUS_PLANNED
        assert joint["nde_status"] == NDE_STATUS_NOT_PLANNED
        assert joint["pwht_status"] == PWHT_STATUS_NOT_REQUIRED
        assert joint["repair_generation"] == 0
        assert joint["repair_of_weld_id"] is None
        assert joint["pwht_batch_id"] is None
        assert joint["welder_qualification_id"] is None
        assert joint["welded_at"] is None
        assert joint["required_surface_method"] is None
    assert heat["id"] is not None


def test_the_ultrasonic_crossover_lands_at_two_inches_while_an_attachment_owes_no_volumetric_at_all(
    client, shop
):
    """A butt seam at 1.999 inch is still radiographed, one at 2.000 inch is ultrasonically examined, and a fillet is neither.

    PRD §3.6: "`volumetric_method` is null whenever the resolved coverage is 0. Otherwise it is `UT` when `thickness_in` is at least 2.000 **and** `joint_type` is `BUTT`, since ultrasonic examination is the practical method on heavy butt joints, and `RT` in every other case."

    PRD §3.6: "Category C and Category D joints take 0 — attachment welds get no volumetric requirement from this rule, only from the repair clause above."

    PRD §3.6: "Otherwise it is `MT` when the `joint_category` is `C` or `D`, or the `joint_type` is `FILLET` or `CORNER`. Otherwise it is null."

    PRD §3.6: "A surface examination, when required, always carries a `required_coverage_pct` of 100; the percentage sampling notion applies only to volumetric examination."

    Design: Difficulty/boundary_precision_check/boundary_category_b_full_rt_thickness_threshold_and_ut_crossover
    """
    engineer = shop.welding_engineer()
    job, heat, shell_part, head_part, procedure = _job_ready_to_plan_joints(
        shop, "J-2885-11", RT_EXTENT_FULL
    )

    def plan(weld_number, joint_category, joint_type, thickness_in, part_b_id):
        return validate_success(
            client.plan_weld(
                job["id"],
                factories.production_weld_payload(
                    procedure["id"],
                    shell_part["id"],
                    weld_number=weld_number,
                    joint_category=joint_category,
                    joint_type=joint_type,
                    thickness_in=thickness_in,
                    part_b_id=part_b_id,
                ),
                shop.acting_as(engineer),
            ),
            201,
        )

    just_below = plan("W-004", JOINT_CATEGORY_B, JOINT_TYPE_BUTT, 1.9990, head_part["id"])
    assert just_below["required_volumetric_pct"] == 100
    assert just_below["volumetric_method"] == METHOD_RT
    assert just_below["required_surface_method"] is None

    at_crossover = plan("W-005", JOINT_CATEGORY_B, JOINT_TYPE_BUTT, 2.0000, head_part["id"])
    assert at_crossover["required_volumetric_pct"] == 100
    assert at_crossover["volumetric_method"] == METHOD_UT
    assert at_crossover["required_surface_method"] is None

    attachment = plan("W-006", JOINT_CATEGORY_C, JOINT_TYPE_FILLET, 2.5000, None)
    assert attachment["required_volumetric_pct"] == 0
    assert attachment["volumetric_method"] is None
    assert attachment["required_surface_method"] == METHOD_MT
    assert attachment["part_b_id"] is None
    assert attachment["fab_status"] == FAB_STATUS_PLANNED
    assert heat["id"] is not None


def _job_and_a_fresh_heat(shop):
    """A vessel in fabrication planning beside an accepted heat of exactly 2000.00 pounds."""
    job = shop.job(
        job_number="J-2885-12",
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
        rt_extent_declared=RT_EXTENT_SPOT,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=1.0000,
    )
    heat = shop.accepted_heat(
        heat_number="H-4471", spec=SPEC_SA_516_70, quantity_received_lb=2000.00
    )
    return job, heat, shop.welding_engineer()


def _assert_mass_invariant(heat):
    assert_number_equals(
        heat["quantity_received_lb"],
        heat["quantity_remaining_lb"] + heat["quantity_issued_lb"],
        2,
        "quantity_received_lb",
    )


def test_an_over_draw_of_one_hundredth_is_refused_while_the_exact_remainder_depletes_the_heat(
    client, shop
):
    """The ledger admits a draw equal to the remaining pounds and refuses one a hundredth of a pound larger.

    PRD §3.4: "`quantity_issued_lb` is the sum of `issued_quantity_lb` across all parts referencing this heat whose `status` is still `ISSUED`; scrapped pieces are excluded from that sum."

    PRD §3.4: "`quantity_remaining_lb` is `quantity_received_lb` minus that issued total, rounded half up to two decimal places."

    PRD §3.4: "An issue is admitted only when `issued_quantity_lb` is less than or equal to the heat's current `quantity_remaining_lb`, so remaining pounds never go negative; an over-draw is refused with `ERR_INSUFFICIENT_HEAT_QUANTITY`."

    PRD §3.4: "When an issue brings `quantity_remaining_lb` to exactly 0.00 the heat moves `ACCEPTED → DEPLETED`; any positive remainder, however small, keeps it `ACCEPTED`."

    Design: Difficulty/boundary_precision_check/boundary_heat_mass_ledger_exhaustion_at_exactly_zero_remaining
    """
    job, heat, engineer = _job_and_a_fresh_heat(shop)

    def issue(part_mark, issued_quantity_lb):
        return client.issue_part(
            job["id"],
            factories.part_payload(
                heat["id"],
                part_mark=part_mark,
                component_type=COMPONENT_TYPE_SHELL,
                issued_quantity_lb=issued_quantity_lb,
            ),
            shop.acting_as(engineer),
        )

    first = validate_success(issue("SH-01", 1200.00), 201)
    assert first["status"] == PART_STATUS_ISSUED
    assert first["heat_traceability_complete"] is True

    partly_drawn = shop.read_heat(heat["id"])
    assert_number_equals(partly_drawn["quantity_issued_lb"], 1200.00, 2, "quantity_issued_lb")
    assert_number_equals(partly_drawn["quantity_remaining_lb"], 800.00, 2, "quantity_remaining_lb")
    assert partly_drawn["status"] == HEAT_STATUS_ACCEPTED
    _assert_mass_invariant(partly_drawn)

    over_draw = issue("SH-02", 800.01)
    validate_error(over_draw, api_errors.ERR_INSUFFICIENT_HEAT_QUANTITY, 409)

    unmoved = shop.read_heat(heat["id"])
    assert_number_equals(unmoved["quantity_issued_lb"], 1200.00, 2, "quantity_issued_lb")
    assert_number_equals(unmoved["quantity_remaining_lb"], 800.00, 2, "quantity_remaining_lb")
    assert unmoved["status"] == HEAT_STATUS_ACCEPTED
    assert unmoved["version"] == partly_drawn["version"]
    _assert_mass_invariant(unmoved)

    second = validate_success(issue("SH-02", 800.00), 201)
    assert second["status"] == PART_STATUS_ISSUED

    exhausted = shop.read_heat(heat["id"])
    assert_number_equals(exhausted["quantity_issued_lb"], 2000.00, 2, "quantity_issued_lb")
    assert_number_equals(exhausted["quantity_remaining_lb"], 0.00, 2, "quantity_remaining_lb")
    assert exhausted["status"] == HEAT_STATUS_DEPLETED
    _assert_mass_invariant(exhausted)


def test_a_depleted_heat_reports_its_acceptance_posture_rather_than_its_empty_ledger(client, shop):
    """The smallest conceivable draw against an exhausted heat is diagnosed on acceptance, because that gate is the earlier of the two.

    PRD §3.4: "The heat must be `ACCEPTED`: a heat still in `QUARANTINE`, one that was `REJECTED`, or one already `DEPLETED` draws `ERR_HEAT_NOT_ACCEPTED`."

    PRD §3.4: "Each part also carries `heat_traceability_complete`, a derived flag that is true only when the referenced heat has `mtr_received` true **and** its `status` is either `ACCEPTED` or `DEPLETED`."

    PRD §2.8: "**Material acceptance.** Guards receiving inspection and part issue, drawing `ERR_MTR_BELOW_SPEC_MINIMUM`, `ERR_HEAT_NOT_ACCEPTED` or `ERR_MATERIAL_FORM_MISMATCH` (409)."

    PRD §2.8: "**Material mass ledger.** Guards part issue: `ERR_INSUFFICIENT_HEAT_QUANTITY` (409)."

    Design: Difficulty/boundary_precision_check/boundary_heat_mass_ledger_exhaustion_at_exactly_zero_remaining
    """
    job, heat, engineer = _job_and_a_fresh_heat(shop)

    def issue(part_mark, issued_quantity_lb):
        return client.issue_part(
            job["id"],
            factories.part_payload(
                heat["id"],
                part_mark=part_mark,
                component_type=COMPONENT_TYPE_SHELL,
                issued_quantity_lb=issued_quantity_lb,
            ),
            shop.acting_as(engineer),
        )

    validate_success(issue("SH-01", 1200.00), 201)
    validate_success(issue("SH-02", 800.00), 201)
    assert shop.read_heat(heat["id"])["status"] == HEAT_STATUS_DEPLETED

    sliver = issue("SH-03", 0.01)
    validate_error(sliver, api_errors.ERR_HEAT_NOT_ACCEPTED, 409)

    still_exhausted = shop.read_heat(heat["id"])
    assert still_exhausted["status"] == HEAT_STATUS_DEPLETED
    assert_number_equals(still_exhausted["quantity_remaining_lb"], 0.00, 2, "quantity_remaining_lb")
    _assert_mass_invariant(still_exhausted)

    rows, meta = validate_paginated(
        client.list_parts(shop.admin, params={"job_id": job["id"], "status": PART_STATUS_ISSUED})
    )
    assert meta["total_count"] == 2
    assert sorted(row["part_mark"] for row in rows) == ["SH-01", "SH-02"]
    assert all(row["heat_traceability_complete"] is True for row in rows)
    assert_number_equals(
        sum(row["issued_quantity_lb"] for row in rows), 2000.00, 2, "issued_quantity_lb"
    )
