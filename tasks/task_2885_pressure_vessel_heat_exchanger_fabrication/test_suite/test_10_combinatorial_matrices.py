"""Cross-product inputs resolved in one job: the coverage cascade and the weighted roll-up."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    COMPONENT_HEAD,
    COMPONENT_SHELL,
    COMPONENT_TYPE_HEAD,
    COMPONENT_TYPE_SHELL,
    DESIGN_CODE_DIV1,
    DESIGN_CODE_DIV2,
    FAB_STATUS_PLANNED,
    FORM_TYPE_U1A,
    JOB_STATUS_FABRICATION,
    JOINT_CATEGORY_A,
    JOINT_CATEGORY_B,
    JOINT_CATEGORY_C,
    JOINT_CATEGORY_D,
    JOINT_TYPE_BUTT,
    JOINT_TYPE_CORNER,
    JOINT_TYPE_FILLET,
    METHOD_MT,
    METHOD_PT,
    METHOD_RT,
    METHOD_UT,
    NDE_STATUS_NOT_PLANNED,
    PWHT_STATUS_NOT_REQUIRED,
    REPORT_STATUS_ASSEMBLING,
    RT_EXTENT_FULL,
    RT_EXTENT_SPOT,
    SPEC_SA_240_304L,
    SPEC_SA_516_70,
    VESSEL_TYPE_HEAT_EXCHANGER,
    VESSEL_TYPE_PRESSURE_VESSEL,
)


def _division_two_shop(shop):
    """A DIV2 vessel at SPOT radiography with one ferritic and one austenitic heat cut into parts."""
    certificate = shop.certificate(cert_number="CA-U-8801")
    job = shop.job(
        certificate,
        job_number="J-2885-03",
        customer_name="Cascade Refining",
        vessel_type=VESSEL_TYPE_PRESSURE_VESSEL,
        design_code=DESIGN_CODE_DIV2,
        mawp_psi=350,
        design_temp_f=650,
        mdmt_f=-20,
        inside_radius_in=30.0,
        stress_ratio=1.00,
    )
    sheets = shop.release_design(
        job,
        rt_extent_declared=RT_EXTENT_SPOT,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=1.0000,
    )
    ferritic = shop.accepted_heat(
        heat_number="H-4471", spec=SPEC_SA_516_70, quantity_received_lb=3000.00
    )
    austenitic = shop.accepted_heat(
        heat_number="H-9902",
        spec=SPEC_SA_240_304L,
        yield_ksi=30.0,
        tensile_ksi=75.0,
        quantity_received_lb=500.00,
    )
    parts = {
        "SH-01": shop.issue_part(
            job["id"],
            ferritic["id"],
            part_mark="SH-01",
            component_type=COMPONENT_TYPE_SHELL,
            issued_quantity_lb=1000.00,
        ),
        "SH-02": shop.issue_part(
            job["id"],
            ferritic["id"],
            part_mark="SH-02",
            component_type=COMPONENT_TYPE_SHELL,
            issued_quantity_lb=800.00,
        ),
        "HD-01": shop.issue_part(
            job["id"],
            ferritic["id"],
            part_mark="HD-01",
            component_type=COMPONENT_TYPE_HEAD,
            issued_quantity_lb=600.00,
        ),
        "HD-02": shop.issue_part(
            job["id"],
            austenitic["id"],
            part_mark="HD-02",
            component_type=COMPONENT_TYPE_HEAD,
            issued_quantity_lb=400.00,
        ),
    }
    procedure = shop.qualified_wps(wps_number="WPS-1", pwht_required=False, preheat_min_f=50)
    return job, sheets, parts, procedure


def _plan(client, shop, job, procedure, engineer, part_a, **overrides):
    return validate_success(
        client.plan_weld(
            job["id"],
            factories.production_weld_payload(procedure["id"], part_a["id"], **overrides),
            shop.acting_as(engineer),
        ),
        201,
    )


def test_the_division_two_override_and_the_heavy_butt_crossover_size_the_two_main_seams(
    client, shop
):
    """A SPOT declaration would size 25 percent, but DIV2 lifts both main seams to 100 and 2.5000 in swaps RT for UT.

    PRD §3.6: "Otherwise, a joint whose parent job has `design_code` `DIV2` and whose `joint_category` is `A` or `B` takes 100, because Division 2 mandates full volumetric examination of all main seams irrespective of the declared extent."

    PRD §3.6: "For a Category A joint, a `FULL` declaration gives 100, a `SPOT` declaration gives 25 and a `NONE` declaration gives 0."

    PRD §3.6: "`volumetric_method` is null whenever the resolved coverage is 0. Otherwise it is `UT` when `thickness_in` is at least 2.000 **and** `joint_type` is `BUTT`, since ultrasonic examination is the practical method on heavy butt joints, and `RT` in every other case."

    PRD §3.6: "Otherwise it is `MT` when the `joint_category` is `C` or `D`, or the `joint_type` is `FILLET` or `CORNER`. Otherwise it is null."

    Design: Difficulty/combinatorial_formula/combinatorial_nde_coverage_matrix_over_division_category_thickness_and_material
    """
    engineer = shop.welding_engineer()
    job, sheets, parts, procedure = _division_two_shop(shop)

    assert job["design_code"] == DESIGN_CODE_DIV2
    assert sheets[COMPONENT_SHELL]["rt_extent_declared"] == RT_EXTENT_SPOT
    assert_number_equals(sheets[COMPONENT_SHELL]["joint_efficiency"], 0.85, 2, "joint_efficiency")

    category_a = _plan(
        client,
        shop,
        job,
        procedure,
        engineer,
        parts["SH-01"],
        weld_number="W-001",
        joint_category=JOINT_CATEGORY_A,
        joint_type=JOINT_TYPE_BUTT,
        thickness_in=1.0000,
        part_b_id=parts["SH-02"]["id"],
    )
    assert category_a["required_volumetric_pct"] == 100
    assert category_a["volumetric_method"] == METHOD_RT
    assert category_a["required_surface_method"] is None

    heavy_category_b = _plan(
        client,
        shop,
        job,
        procedure,
        engineer,
        parts["SH-01"],
        weld_number="W-002",
        joint_category=JOINT_CATEGORY_B,
        joint_type=JOINT_TYPE_BUTT,
        thickness_in=2.5000,
        part_b_id=parts["HD-01"]["id"],
    )
    assert heavy_category_b["required_volumetric_pct"] == 100
    assert heavy_category_b["volumetric_method"] == METHOD_UT
    assert heavy_category_b["required_surface_method"] is None

    for joint in (category_a, heavy_category_b):
        assert joint["fab_status"] == FAB_STATUS_PLANNED
        assert joint["nde_status"] == NDE_STATUS_NOT_PLANNED
        assert joint["pwht_status"] == PWHT_STATUS_NOT_REQUIRED


def test_attachment_welds_owe_no_volumetric_and_the_austenitic_piece_swaps_mt_for_pt(client, shop):
    """Category C and D take zero coverage, and the non-magnetic head plate forces dye penetrant.

    PRD §3.6: "Category C and Category D joints take 0 — attachment welds get no volumetric requirement from this rule, only from the repair clause above."

    PRD §3.6: "`required_surface_method` is resolved independently of coverage, and the austenitic clause outranks the geometry clause."

    PRD §3.6: "It is `PT` when either joined piece traces to a heat whose `material_class` is `AUSTENITIC` — magnetic-particle examination is not valid on non-magnetic stainless, so dye penetrant is substituted."

    PRD §3.6: "A surface examination, when required, always carries a `required_coverage_pct` of 100; the percentage sampling notion applies only to volumetric examination."

    Design: Difficulty/combinatorial_formula/combinatorial_nde_coverage_matrix_over_division_category_thickness_and_material
    """
    engineer = shop.welding_engineer()
    job, sheets, parts, procedure = _division_two_shop(shop)

    assert sheets[COMPONENT_HEAD]["rt_extent_declared"] == RT_EXTENT_SPOT
    assert parts["HD-02"]["heat_id"] != parts["HD-01"]["heat_id"]

    ferritic_fillet = _plan(
        client,
        shop,
        job,
        procedure,
        engineer,
        parts["SH-02"],
        weld_number="W-003",
        joint_category=JOINT_CATEGORY_C,
        joint_type=JOINT_TYPE_FILLET,
        thickness_in=0.7500,
        part_b_id=parts["HD-01"]["id"],
    )
    assert ferritic_fillet["required_volumetric_pct"] == 0
    assert ferritic_fillet["volumetric_method"] is None
    assert ferritic_fillet["required_surface_method"] == METHOD_MT

    austenitic_corner = _plan(
        client,
        shop,
        job,
        procedure,
        engineer,
        parts["HD-02"],
        weld_number="W-004",
        joint_category=JOINT_CATEGORY_D,
        joint_type=JOINT_TYPE_CORNER,
        thickness_in=0.5000,
    )
    assert austenitic_corner["required_volumetric_pct"] == 0
    assert austenitic_corner["volumetric_method"] is None
    assert austenitic_corner["required_surface_method"] == METHOD_PT

    for joint in (ferritic_fillet, austenitic_corner):
        assert joint["fab_status"] == FAB_STATUS_PLANNED
        assert joint["nde_status"] == NDE_STATUS_NOT_PLANNED
        assert joint["pwht_status"] == PWHT_STATUS_NOT_REQUIRED


def _partly_built_exchanger(shop):
    """An exchanger with every sheet approved, two of three components cut, two of three joints welded."""
    certificate = shop.certificate(cert_number="CA-U-8801")
    job = shop.job(
        certificate,
        job_number="J-2885-04",
        customer_name="Cascade Refining",
        vessel_type=VESSEL_TYPE_HEAT_EXCHANGER,
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
    procedure = shop.qualified_wps(wps_number="WPS-1", pwht_required=False, preheat_min_f=50)
    qualification = shop.welder_qualification(
        procedure["id"], welder_stamp="W12", welder_name="Rosa Vela"
    )
    joints = []
    for number in ("W-001", "W-002", "W-003"):
        joints.append(
            shop.plan_joint(
                job["id"],
                procedure["id"],
                shell_part["id"],
                weld_number=number,
                joint_category=JOINT_CATEGORY_C,
                joint_type=JOINT_TYPE_FILLET,
                thickness_in=0.7500,
                part_b_id=head_part["id"],
            )
        )
    shop.release_weld_map(job["id"])
    shop.complete_joint(
        joints[0]["id"], qualification["id"], welded_at="2026-07-30T09:00:00.000Z"
    )
    shop.complete_joint(
        joints[1]["id"], qualification["id"], welded_at="2026-07-30T13:00:00.000Z"
    )
    return job, joints


def test_two_sections_at_two_thirds_prove_each_section_is_rounded_before_the_sum(client, shop):
    """MATERIAL and WELDING both land on two thirds, so the roll-up reads 86.66 rather than 86.67.

    PRD §3.9: "The weights are 25 for `DESIGN`, 20 for `MATERIAL`, 20 for `WELDING`, 15 for `NDE`, 10 for `PWHT` and 10 for `TEST`, summing to 100."

    PRD §3.9: "A section whose denominator is 0 takes a fraction of exactly 1.000 — a vessel that needs no heat treatment scores full marks for heat treatment rather than zero."

    PRD §3.9: "Each section's points are its weight multiplied by its fraction, rounded half up to two decimal places, and that rounded figure is what `section_scores` reports."

    PRD §3.9: "`completeness_score` is then the sum of those already-rounded section points, rounded half up to two decimal places once more."

    PRD §3.9: "Summing the unrounded products and rounding only at the end gives a different answer — a two-thirds `DESIGN` fraction alone separates the two orders by a hundredth, 66.66 against 66.67 — and only the per-section-first order is correct."

    Design: Difficulty/combinatorial_formula/combinatorial_data_package_completeness_per_section_rounding_order
    """
    assembler = shop.qc_inspector()
    job, _ = _partly_built_exchanger(shop)

    report = validate_success(
        client.assemble_data_report(
            job["id"],
            factories.data_report_payload(shop.job_version(job["id"]), form_type=FORM_TYPE_U1A),
            shop.acting_as(assembler),
        ),
        201,
    )

    scores = report["section_scores"]
    assert_number_equals(scores["DESIGN"], 25.00, 2, "DESIGN")
    assert_number_equals(scores["MATERIAL"], 13.33, 2, "MATERIAL")
    assert_number_equals(scores["WELDING"], 13.33, 2, "WELDING")
    assert_number_equals(scores["NDE"], 15.00, 2, "NDE")
    assert_number_equals(scores["PWHT"], 10.00, 2, "PWHT")
    assert_number_equals(scores["TEST"], 10.00, 2, "TEST")

    assert_number_equals(report["completeness_score"], 86.66, 2, "completeness_score")
    assert round(float(report["completeness_score"]), 2) != 86.67

    summed = sum(round(float(scores[section]), 2) for section in scores)
    assert_number_equals(round(summed, 2), 86.66, 2, "sum of rounded sections")


def test_only_the_two_short_sections_are_named_and_they_arrive_in_the_pinned_section_order(
    client, shop
):
    """`missing_items` names MATERIAL then WELDING and nothing else, on a report still ASSEMBLING.

    PRD §3.9: "`MATERIAL` is the number of members of `required_components` for which at least one `ISSUED` part exists whose heat's `status` is `ACCEPTED` or `DEPLETED`, divided by the number of `required_components`."

    PRD §3.9: "`WELDING` is the number of the job's joints whose `fab_status` is `WELDED`, divided by the number of the job's joints."

    PRD §3.9: "It contains, in the section order `DESIGN`, `MATERIAL`, `WELDING`, `NDE`, `PWHT`, `TEST`, the name of every section whose fraction is below 1.000."

    PRD §3.9: "Creation answers 201 with the report at `status` `ASSEMBLING` and `assembled_by_personnel_id` set to the acting `X-User-ID`."

    PRD §3.6: "The numerator counts the job's joints whose `fab_status` is `WELDED` **and** whose `nde_status` is `ACCEPTED` **and** whose `pwht_status` is either `NOT_REQUIRED` or `COMPLETE`; a joint failing any one of the three is not counted."

    Design: Difficulty/combinatorial_formula/combinatorial_data_package_completeness_per_section_rounding_order
    """
    assembler = shop.qc_inspector()
    job, joints = _partly_built_exchanger(shop)

    report = validate_success(
        client.assemble_data_report(
            job["id"],
            factories.data_report_payload(shop.job_version(job["id"]), form_type=FORM_TYPE_U1A),
            shop.acting_as(assembler),
        ),
        201,
    )

    assert report["status"] == REPORT_STATUS_ASSEMBLING
    assert report["missing_items"] == ["MATERIAL", "WELDING"]
    assert report["assembled_by_personnel_id"] == assembler["id"]
    assert report["nameplate_serial"] is None
    assert report["form_type"] == FORM_TYPE_U1A

    carrying_job = shop.read_job(job["id"])
    assert carrying_job["status"] == JOB_STATUS_FABRICATION
    assert_number_equals(carrying_job["weld_completion_pct"], 0.00, 2, "weld_completion_pct")
    assert carrying_job["nonconformance_open_count"] == 0

    assert len(joints) == 3
    assert shop.read_joint(joints[2]["id"])["fab_status"] == FAB_STATUS_PLANNED
