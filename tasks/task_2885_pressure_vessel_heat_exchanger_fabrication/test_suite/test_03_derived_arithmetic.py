"""Table constants, wall arithmetic, continuity and posture ladders, progress and sampling."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import assert_number_equals, assert_scale
from test_helpers.constants import (
    CERT_STATUS_ACTIVE,
    CERT_STATUS_EXPIRED,
    CERT_STATUS_PROBATION,
    CERT_STATUS_SUSPENDED,
    COMPONENT_HEAD,
    COMPONENT_NOZZLE,
    COMPONENT_SHELL,
    EXAM_RESULT_PENDING,
    FAB_STATUS_WELDED,
    JOB_STATUS_DRAFT,
    JOB_STATUS_FABRICATION,
    JOINT_CATEGORY_B,
    JOINT_CATEGORY_C,
    JOINT_TYPE_BUTT,
    JOINT_TYPE_FILLET,
    METHOD_MT,
    METHOD_RT,
    NDE_STATUS_ACCEPTED,
    NDE_STATUS_NOT_PLANNED,
    NDE_STATUS_PLANNED,
    PWHT_STATUS_NOT_REQUIRED,
    QUALIFICATION_STATUS_LAPSED,
    QUALIFICATION_STATUS_QUALIFIED,
    RT_EXTENT_FULL,
    RT_EXTENT_NONE,
    RT_EXTENT_SPOT,
    VARIANT_CIRCUMFERENTIAL,
)


def test_each_declared_radiographic_extent_pulls_its_own_efficiency_constant(client, shop, admin_headers):
    """FULL, SPOT and NONE resolve to 1.00, 0.85 and 0.70 and each drives its own wall.

    PRD §3.3: "`joint_efficiency` is resolved directly from `rt_extent_declared`: a `FULL` declaration yields 1.00, a `SPOT` declaration yields 0.85 and a `NONE` declaration yields 0.70, carried at two decimal places."

    Design: Corner/calculations/calculation_joint_efficiency_table_constants_applied_to_each_declaration
    """
    job = shop.job(job_number="J-2885-C29", mawp_psi=350, inside_radius_in=30)
    common = {
        "allowable_stress_psi": 20000,
        "corrosion_allowance_in": 0.0625,
        "thickness_nominal_in": 1.0000,
    }

    full = shop.prepare_sheet(job["id"], COMPONENT_SHELL, rt_extent_declared=RT_EXTENT_FULL, **common)
    spot = shop.prepare_sheet(job["id"], COMPONENT_HEAD, rt_extent_declared=RT_EXTENT_SPOT, **common)
    none = shop.prepare_sheet(job["id"], COMPONENT_NOZZLE, rt_extent_declared=RT_EXTENT_NONE, **common)

    expected = {
        full["id"]: (1.00, 0.5306, 0.2616, 0.5931),
        spot["id"]: (0.85, 0.6254, 0.3076, 0.6879),
        none["id"]: (0.70, 0.7614, 0.3731, 0.8239),
    }
    for sheet_id, (efficiency, circumferential, longitudinal, required) in expected.items():
        sheet = validate_success(client.get_calculation(sheet_id, admin_headers), 200)
        assert_number_equals(sheet["joint_efficiency"], efficiency, 2, "joint_efficiency")
        assert_number_equals(
            sheet["thickness_circumferential_in"], circumferential, 4, "thickness_circumferential_in"
        )
        assert_number_equals(
            sheet["thickness_longitudinal_in"], longitudinal, 4, "thickness_longitudinal_in"
        )
        assert_number_equals(sheet["thickness_required_in"], required, 4, "thickness_required_in")
        assert sheet["governing_variant"] == VARIANT_CIRCUMFERENTIAL
        assert sheet["revision"] == 1
        assert sheet["status"] == "DRAFT"

    parent = shop.read_job(job["id"])
    assert parent["status"] == JOB_STATUS_DRAFT
    assert parent["governing_joint_efficiency"] is None


def test_the_two_variant_thicknesses_carry_no_corrosion_allowance(client, shop, admin_headers):
    """The allowance appears once, in the required thickness, and after the addition.

    PRD §3.3: "Both are report-only, both are always populated, and **neither of them ever includes the corrosion allowance**."

    PRD §3.3: "`thickness_required_in` is the greater of the two unrounded values, plus `corrosion_allowance_in`, with the sum rounded half up to four decimal places **once**."

    Design: Corner/calculations/calculation_wall_thickness_variant_fields_exclude_corrosion_allowance
    """
    job = shop.job(job_number="J-2885-C30", mawp_psi=350, inside_radius_in=30)

    sheet = shop.prepare_sheet(
        job["id"],
        COMPONENT_SHELL,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=17500,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.7500,
    )

    stored = validate_success(client.get_calculation(sheet["id"], admin_headers), 200)
    assert_number_equals(
        stored["thickness_circumferential_in"], 0.6073, 4, "thickness_circumferential_in"
    )
    assert_number_equals(stored["thickness_longitudinal_in"], 0.2988, 4, "thickness_longitudinal_in")
    assert_number_equals(stored["thickness_required_in"], 0.6698, 4, "thickness_required_in")
    assert_scale(stored["thickness_circumferential_in"], 4, "thickness_circumferential_in")
    assert_scale(stored["thickness_longitudinal_in"], 4, "thickness_longitudinal_in")
    assert_scale(stored["thickness_required_in"], 4, "thickness_required_in")
    assert stored["governing_variant"] == VARIANT_CIRCUMFERENTIAL
    assert float(stored["thickness_required_in"]) != round(
        float(stored["thickness_circumferential_in"]) + float(stored["thickness_longitudinal_in"]), 4
    )


def test_a_welder_lapses_only_on_the_day_after_the_continuity_limit(client, shop, admin_headers):
    """Exactly 180 days is still qualified; the 181st day lapses the row.

    PRD §3.5: "`status` is `LAPSED` when `days_since_continuity` is strictly greater than 180, and `QUALIFIED` otherwise: exactly 180 days is still `QUALIFIED`, and 181 days lapses."

    PRD §3.5: "On creation `last_continuity_date` is initialised to `qualified_on`."

    Design: Corner/calculations/calculation_welder_continuity_lapses_only_past_one_hundred_eighty_days
    """
    wps = shop.qualified_wps(wps_number="WPS-98", supporting_pqr_number="PQR-98")
    qualification = shop.welder_qualification(
        wps["id"], welder_stamp="W-20", welder_name="Marta Quill", qualified_on="2026-02-02"
    )

    at_the_limit = shop.read_welder_qualification(qualification["id"])
    clock = shop.set_clock("2026-08-02T00:00:00.000Z")
    past_the_limit = shop.read_welder_qualification(qualification["id"])

    assert at_the_limit["last_continuity_date"] == "2026-02-02"
    assert at_the_limit["days_since_continuity"] == 180
    assert at_the_limit["status"] == QUALIFICATION_STATUS_QUALIFIED
    assert clock["welder_qualifications_recomputed"] == 1
    assert past_the_limit["days_since_continuity"] == 181
    assert past_the_limit["status"] == QUALIFICATION_STATUS_LAPSED

    lapsed, meta = validate_paginated(
        client.list_welder_qualifications(
            admin_headers,
            params={"status": QUALIFICATION_STATUS_LAPSED, "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in lapsed] == [qualification["id"]]


def test_three_major_findings_suspend_the_shop_and_expiry_then_outranks_them(client, shop):
    """The suspension threshold is three majors, and expiry relabels the same row.

    PRD §3.1: "`status` is drawn from `ACTIVE`, `PROBATION`, `SUSPENDED` and `EXPIRED`, and it is resolved in this priority: the certificate is `EXPIRED` whenever `expires_on` falls before the current logical UTC date; otherwise it is `SUSPENDED` whenever `open_major_findings_count` has reached 3 or more; otherwise it is `PROBATION` whenever `open_major_findings_count` is 1 or more or `open_minor_findings_count` is more than 5; otherwise it is `ACTIVE`."

    Design: Corner/calculations/calculation_certificate_posture_suspends_at_three_majors_then_expiry_outranks
    """
    certificate = shop.certificate(
        cert_number="CA-U-8915", issued_on="2026-01-01", expires_on="2026-09-01"
    )
    audit = shop.audit(certificate["id"], scheduled_date="2026-08-01")

    closed = shop.close_audit(audit["id"], closed_on="2026-08-01", major=3, observation=1)
    after_audit = shop.read_certificate(certificate["id"])
    clock = shop.set_clock("2026-09-02T00:00:00.000Z")
    after_clock = shop.read_certificate(certificate["id"])

    assert closed["major_finding_count"] == 3
    assert closed["minor_finding_count"] == 0
    assert closed["satisfactory"] is False
    assert after_audit["status"] == CERT_STATUS_SUSPENDED
    assert after_audit["open_major_findings_count"] == 3
    assert after_audit["stamping_authorized"] is False
    assert clock["certificates_recomputed"] == 1
    assert after_clock["status"] == CERT_STATUS_EXPIRED
    assert after_clock["open_major_findings_count"] == 3
    assert after_clock["stamping_authorized"] is False
    assert after_clock["renewal_count"] == 0


def test_probation_begins_only_past_the_fifth_minor_finding(client, shop, admin_headers):
    """Four and five minors stay clean; the sixth puts the shop on probation.

    PRD §3.1: "`satisfactory` becomes true only when the audit is `CLOSED`, its `major_finding_count` is 0 and its `minor_finding_count` is 5 or fewer, and `CLOSED` is terminal for an audit."

    PRD §3.1: "The posture consequences follow the counters exactly: an `ACTIVE` certificate moves `ACTIVE → PROBATION` when the closing audit contributes 1 or 2 majors, or contributes more than 5 minors; it moves `ACTIVE → SUSPENDED` when the closing audit contributes 3 or more majors; and a certificate already on `PROBATION` moves `PROBATION → SUSPENDED` when the close pushes its cumulative `open_major_findings_count` to 3 or more."

    Design: Corner/calculations/calculation_certificate_posture_minor_finding_threshold_boundary
    """
    expected = {}
    for cert_number, minors in (("CA-U-8916", 4), ("CA-U-8917", 5), ("CA-U-8918", 6)):
        certificate = shop.certificate(cert_number=cert_number)
        audit = shop.audit(certificate["id"], scheduled_date="2026-07-01")
        closed = shop.close_audit(audit["id"], closed_on="2026-07-15", minor=minors)
        expected[minors] = (shop.read_certificate(certificate["id"]), closed)

    below, below_audit = expected[4]
    assert below["open_minor_findings_count"] == 4
    assert below["status"] == CERT_STATUS_ACTIVE
    assert below["stamping_authorized"] is True
    assert below_audit["satisfactory"] is True

    at_threshold, at_threshold_audit = expected[5]
    assert at_threshold["open_minor_findings_count"] == 5
    assert at_threshold["status"] == CERT_STATUS_ACTIVE
    assert at_threshold["stamping_authorized"] is True
    assert at_threshold_audit["satisfactory"] is True

    above, above_audit = expected[6]
    assert above["open_minor_findings_count"] == 6
    assert above["status"] == CERT_STATUS_PROBATION
    assert above["stamping_authorized"] is False
    assert above_audit["satisfactory"] is False

    for certificate, _ in expected.values():
        assert certificate["open_major_findings_count"] == 0

    on_probation, meta = validate_paginated(
        client.list_certificates(
            admin_headers, params={"status": CERT_STATUS_PROBATION, "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in on_probation] == [above["id"]]


def test_progress_counts_only_joints_satisfied_on_all_three_dimensions(client, shop):
    """Welding a third joint without examining it leaves the measure where it was.

    PRD §3.6: "The numerator counts the job's joints whose `fab_status` is `WELDED` **and** whose `nde_status` is `ACCEPTED` **and** whose `pwht_status` is either `NOT_REQUIRED` or `COMPLETE`; a joint failing any one of the three is not counted."

    Design: Corner/calculations/calculation_weld_completion_counts_only_fully_satisfied_joints
    """
    job = shop.job(job_number="J-2885-C32", mawp_psi=350, inside_radius_in=30)
    shop.release_design(
        job,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.7500,
    )
    heat = shop.accepted_heat(heat_number="H-5600", quantity_received_lb=2000.00)
    part_a = shop.issue_part(
        job["id"], heat["id"], part_mark="SH-01", component_type=COMPONENT_SHELL, issued_quantity_lb=1200.00
    )
    part_b = shop.issue_part(
        job["id"], heat["id"], part_mark="HD-01", component_type=COMPONENT_HEAD, issued_quantity_lb=600.00
    )
    wps = shop.qualified_wps(wps_number="WPS-97", supporting_pqr_number="PQR-97")
    qualification = shop.welder_qualification(wps["id"], welder_stamp="W-21", welder_name="Marta Quill")
    joint_shape = {
        "joint_category": JOINT_CATEGORY_C,
        "joint_type": JOINT_TYPE_FILLET,
        "thickness_in": 0.7500,
    }
    first = shop.plan_joint(job["id"], wps["id"], part_a["id"], weld_number="W-001", **joint_shape)
    second = shop.plan_joint(job["id"], wps["id"], part_b["id"], weld_number="W-002", **joint_shape)
    third = shop.plan_joint(job["id"], wps["id"], part_a["id"], weld_number="W-003", **joint_shape)
    shop.release_weld_map(job["id"])
    shop.complete_joint(first["id"], qualification["id"], welded_at="2026-07-30T08:00:00.000Z")
    shop.complete_joint(second["id"], qualification["id"], welded_at="2026-07-30T09:00:00.000Z")

    exams = shop.run_nde_plan(job["id"])
    for exam in exams:
        shop.accept_exam(exam["id"], examined_coverage_pct=100.00, exam_date="2026-07-31")
    two_of_three = shop.read_job(job["id"])
    shop.complete_joint(third["id"], qualification["id"], welded_at="2026-07-31T08:00:00.000Z")
    welded_but_unexamined = shop.read_job(job["id"])

    assert len(exams) == 2
    assert {exam["method"] for exam in exams} == {METHOD_MT}
    assert all(exam["required_coverage_pct"] == 100 for exam in exams)
    assert_number_equals(two_of_three["weld_completion_pct"], 66.67, 2, "weld_completion_pct")
    for weld_id in (first["id"], second["id"]):
        joint = shop.read_joint(weld_id)
        assert joint["fab_status"] == FAB_STATUS_WELDED
        assert joint["nde_status"] == NDE_STATUS_ACCEPTED
        assert joint["pwht_status"] == PWHT_STATUS_NOT_REQUIRED

    assert_number_equals(
        welded_but_unexamined["weld_completion_pct"], 66.67, 2, "weld_completion_pct"
    )
    last_joint = shop.read_joint(third["id"])
    assert last_joint["fab_status"] == FAB_STATUS_WELDED
    assert last_joint["nde_status"] == NDE_STATUS_NOT_PLANNED
    assert welded_but_unexamined["status"] == JOB_STATUS_FABRICATION
    assert welded_but_unexamined["nonconformance_open_count"] == 0


def test_the_spot_sample_is_resized_against_each_invocations_own_candidates(client, shop, admin_headers):
    """One quarter of this run's candidates, taken in weld-number order, never re-planned.

    PRD §3.6: "When it is 25, the number selected is the group's candidate count multiplied by 0.25 and rounded **up** to the next whole joint, and the joints taken are that many from the front of the group ordered by `weld_number` ascending, ties broken by `created_at` ascending; a group of one therefore still yields one examination, and a group of five yields two."

    PRD §3.6: "Crucially, the group size used in that arithmetic counts only **this invocation's** candidates, not every joint of that category ever planned, so examining in two passes can select more joints in total than examining in one."

    Design: Corner/calculations/calculation_nde_plan_spot_sample_sized_per_invocation_in_weld_number_order
    """
    job = shop.job(job_number="J-2885-C33", mawp_psi=350, inside_radius_in=30)
    shop.release_design(
        job,
        rt_extent_declared=RT_EXTENT_SPOT,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.7500,
    )
    heat = shop.accepted_heat(heat_number="H-5700", quantity_received_lb=2000.00)
    part = shop.issue_part(
        job["id"], heat["id"], part_mark="SH-01", component_type=COMPONENT_SHELL, issued_quantity_lb=1200.00
    )
    wps = shop.qualified_wps(wps_number="WPS-99", supporting_pqr_number="PQR-99")
    qualification = shop.welder_qualification(wps["id"], welder_stamp="W-22", welder_name="Marta Quill")
    joint_shape = {
        "joint_category": JOINT_CATEGORY_B,
        "joint_type": JOINT_TYPE_BUTT,
        "thickness_in": 0.7500,
    }
    third = shop.plan_joint(job["id"], wps["id"], part["id"], weld_number="W-003", **joint_shape)
    first = shop.plan_joint(job["id"], wps["id"], part["id"], weld_number="W-001", **joint_shape)
    second = shop.plan_joint(job["id"], wps["id"], part["id"], weld_number="W-002", **joint_shape)
    shop.release_weld_map(job["id"])
    shop.complete_joint(third["id"], qualification["id"], welded_at="2026-07-28T08:00:00.000Z")
    shop.complete_joint(first["id"], qualification["id"], welded_at="2026-07-29T08:00:00.000Z")
    shop.complete_joint(second["id"], qualification["id"], welded_at="2026-07-30T08:00:00.000Z")

    run_one = shop.run_nde_plan(job["id"])
    after_run_one = {weld["id"]: shop.read_joint(weld["id"]) for weld in (first, second, third)}
    run_two = shop.run_nde_plan(job["id"])
    run_three = shop.run_nde_plan(job["id"])

    assert len(run_one) == 1
    assert run_one[0]["weld_id"] == first["id"]
    assert run_one[0]["method"] == METHOD_RT
    assert run_one[0]["required_coverage_pct"] == 25
    assert run_one[0]["result"] == EXAM_RESULT_PENDING
    assert after_run_one[first["id"]]["nde_status"] == NDE_STATUS_PLANNED
    assert after_run_one[second["id"]]["nde_status"] == NDE_STATUS_NOT_PLANNED
    assert after_run_one[third["id"]]["nde_status"] == NDE_STATUS_NOT_PLANNED

    assert len(run_two) == 1
    assert run_two[0]["weld_id"] == second["id"]
    assert len(run_three) == 1
    assert run_three[0]["weld_id"] == third["id"]
    assert len({run_one[0]["id"], run_two[0]["id"], run_three[0]["id"]}) == 3

    _, first_joint_meta = validate_paginated(
        client.list_exams(admin_headers, params={"weld_id": first["id"], "limit": 10, "offset": 0})
    )
    assert first_joint_meta["total_count"] == 1
    _, volumetric_meta = validate_paginated(
        client.list_exams(
            admin_headers,
            params={"method": METHOD_RT, "result": EXAM_RESULT_PENDING, "limit": 10, "offset": 0},
        )
    )
    assert volumetric_meta["total_count"] == 3
    _, surface_meta = validate_paginated(
        client.list_exams(admin_headers, params={"method": METHOD_MT, "limit": 10, "offset": 0})
    )
    assert surface_meta["total_count"] == 0
