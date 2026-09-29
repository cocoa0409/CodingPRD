"""Refusal families: scoped uniqueness, state guards, design adequacy and the weld-map planning gates."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    AUDIT_TYPE_TRIENNIAL_RENEWAL,
    CALC_STATUS_DRAFT,
    CALC_STATUS_SUBMITTED,
    COMPONENT_SHELL,
    COMPONENT_TYPE_NOZZLE,
    FORM_FORGING,
    FORM_PLATE,
    HEAT_STATUS_QUARANTINE,
    HEAT_STATUS_REJECTED,
    JOB_STATUS_DESIGN_REVIEW,
    JOB_STATUS_DRAFT,
    JOB_STATUS_FAB_PLANNING,
    JOINT_CATEGORY_A,
    JOINT_CATEGORY_C,
    JOINT_TYPE_BUTT,
    JOINT_TYPE_CORNER,
    JOINT_TYPE_FILLET,
    METHOD_RT,
    PART_STATUS_SCRAPPED,
    POSITIONS,
    PROCESS_GTAW,
    PROCESS_SAW,
    ROLE_CODE_AUTHORIZED_INSPECTOR,
    RT_EXTENT_FULL,
    SPEC_SA_105,
    SPEC_SA_516_70,
    VESSEL_TYPE_HEAT_EXCHANGER,
)


def test_every_unique_business_key_refuses_its_repeat_while_keeping_its_declared_scope(
    client, shop, admin_headers
):
    """Each uniqueness key fires once, and the two scoped keys admit the control create that proves their scope.

    PRD §2.8: "**Scoped uniqueness.** Guards every create endpoint, drawing `ERR_DUPLICATE_CERT_NUMBER`, `ERR_DUPLICATE_STAMP_INITIALS`, `ERR_DUPLICATE_JOB_NUMBER`, `ERR_DUPLICATE_HEAT_NUMBER`, `ERR_DUPLICATE_WPS_NUMBER`, `ERR_DUPLICATE_WELDER_QUALIFICATION`, `ERR_DUPLICATE_WELD_NUMBER`, `ERR_DUPLICATE_CHART_RECORD_NUMBER` or `ERR_DUPLICATE_NAMEPLATE_SERIAL` (409)."

    PRD §3.4: "A `QCInspector` records a **heat** of material with its `heat_number` — the mill heat number stamped on the steel and printed on the mill test report, non-blank and unique per material specification, so a repeat under the same specification draws `ERR_DUPLICATE_HEAT_NUMBER` — a `spec` of `SA-516-70`, `SA-240-304L`, `SA-105` or `SA-179`, a `form` of `PLATE`, `FORGING`, `PIPE` or `TUBE`, an `mtr_received` flag stating whether the mill test report is on file, the certified strengths `mtr_certified_yield_ksi` and `mtr_certified_tensile_ksi` in ksi, and `quantity_received_lb`, the pounds taken into the shop, strictly positive at two decimal places."

    PRD §3.5: "The pairing of `welder_stamp` and `wps_id` must be unique — one row per welder per procedure — and a repeat draws `ERR_DUPLICATE_WELDER_QUALIFICATION`."

    Design: Corner/errors/error_duplicate_key_family_across_every_unique_business_key
    """
    inspector = shop.qc_inspector()
    engineer = shop.welding_engineer()
    certificate = shop.certificate(cert_number="CA-U-8926")
    shop.job(certificate=certificate, job_number="J-2885-C41", mawp_psi=350)
    shop.heat(heat_number="H-6400", spec=SPEC_SA_516_70, quantity_received_lb=2000.00)
    procedure_a = shop.qualified_wps(wps_number="WPS-130")
    procedure_b = shop.qualified_wps(
        wps_number="WPS-131", process=PROCESS_SAW, filler_f_number=6,
        thickness_min_in=0.2500, thickness_max_in=2.0000,
    )
    shop.welder_qualification(
        procedure_a["id"], welder_stamp="W-88", welder_name="Ola Beck", thickness_range_max_in=1.5000
    )

    validate_error(
        client.create_certificate(
            factories.certificate_payload(
                cert_number="CA-U-8926",
                scope_codes=["U", "S"],
                issued_on="2026-02-01",
                expires_on="2030-01-01",
            ),
            admin_headers,
        ),
        api_errors.ERR_DUPLICATE_CERT_NUMBER,
        409,
    )

    validate_error(
        client.register_person(
            factories.personnel_payload(
                ROLE_CODE_AUTHORIZED_INSPECTOR,
                full_name="Priya Quandt",
                stamp_initials=inspector["stamp_initials"],
            ),
            admin_headers,
        ),
        api_errors.ERR_DUPLICATE_STAMP_INITIALS,
        409,
    )

    validate_error(
        client.create_job(
            factories.vessel_job_payload(
                certificate["id"],
                job_number="J-2885-C41",
                customer_name="Other Buyer",
                vessel_type=VESSEL_TYPE_HEAT_EXCHANGER,
                mawp_psi=400,
                inside_radius_in=24.0,
            ),
            admin_headers,
        ),
        api_errors.ERR_DUPLICATE_JOB_NUMBER,
        409,
    )

    validate_error(
        client.create_heat(
            factories.material_heat_payload(
                heat_number="H-6400",
                spec=SPEC_SA_516_70,
                form=FORM_PLATE,
                yield_ksi=42.0,
                tensile_ksi=76.0,
                quantity_received_lb=500.00,
            ),
            shop.acting_as(inspector),
        ),
        api_errors.ERR_DUPLICATE_HEAT_NUMBER,
        409,
    )

    other_spec = validate_success(
        client.create_heat(
            factories.material_heat_payload(
                heat_number="H-6400",
                spec=SPEC_SA_105,
                form=FORM_FORGING,
                yield_ksi=40.0,
                tensile_ksi=75.0,
                quantity_received_lb=500.00,
            ),
            shop.acting_as(inspector),
        ),
        201,
    )
    assert other_spec["heat_number"] == "H-6400"
    assert other_spec["spec"] == SPEC_SA_105

    validate_error(
        client.create_wps(
            factories.wps_payload(
                wps_number="WPS-130",
                process=PROCESS_GTAW,
                base_metal_p_number=8,
                filler_f_number=6,
                thickness_min_in=0.0625,
                thickness_max_in=0.5000,
                position=POSITIONS[1],
            ),
            shop.acting_as(engineer),
        ),
        api_errors.ERR_DUPLICATE_WPS_NUMBER,
        409,
    )

    validate_error(
        client.create_welder_qualification(
            factories.welder_qualification_payload(
                procedure_a["id"],
                welder_stamp="W-88",
                welder_name="Ola Beck",
                position_qualified=POSITIONS[1],
                thickness_range_max_in=2.0000,
                qualified_on="2026-07-01",
            ),
            shop.acting_as(engineer),
        ),
        api_errors.ERR_DUPLICATE_WELDER_QUALIFICATION,
        409,
    )

    on_other_procedure = validate_success(
        client.create_welder_qualification(
            factories.welder_qualification_payload(
                procedure_b["id"],
                welder_stamp="W-88",
                welder_name="Ola Beck",
                thickness_range_max_in=1.5000,
                qualified_on="2026-07-01",
            ),
            shop.acting_as(engineer),
        ),
        201,
    )
    assert on_other_procedure["wps_id"] == procedure_b["id"]

    for lister, expected_total in (
        (client.list_certificates, 1),
        (client.list_jobs, 1),
        (client.list_wps, 2),
        (client.list_heats, 2),
        (client.list_welder_qualifications, 2),
    ):
        _, meta = validate_paginated(lister(admin_headers, params={"limit": 10, "offset": 0}))
        assert meta["total_count"] == expected_total


def test_renewal_and_receiving_inspection_state_guards_refuse_and_leave_no_trace(
    client, shop, admin_headers
):
    """Three refusals the happy path never meets: renewing an ACTIVE licence, accepting without a mill report, reviewing a settled heat.

    PRD §3.1: "Renewing a certificate that is already `ACTIVE` is not a declared transition and is refused with `ERR_INVALID_CERTIFICATE_STATE`."

    PRD §3.4: "The heat must be `QUARANTINE`, or the review is refused with `ERR_INVALID_HEAT_STATE`."

    PRD §3.4: "An `ACCEPT` decision requires `mtr_received` to be true — accepting material whose mill test report has not arrived is refused with `ERR_TRACEABILITY_INCOMPLETE` — and requires both certified strengths to reach the minima for the heat's specification: at least 38 ksi yield and 70 ksi tensile for `SA-516-70`, at least 25 ksi yield and 70 ksi tensile for `SA-240-304L`, at least 36 ksi yield and 70 ksi tensile for `SA-105`, and at least 26 ksi yield and 47 ksi tensile for `SA-179`."

    Design: Corner/errors/error_state_guard_family_on_certificate_renewal_and_receiving_inspection
    """
    inspector = shop.qc_inspector()
    certificate = shop.certificate(cert_number="CA-U-8927")
    audit = shop.audit(
        certificate["id"], audit_type=AUDIT_TYPE_TRIENNIAL_RENEWAL, scheduled_date="2026-06-01"
    )
    shop.close_audit(audit["id"], closed_on="2026-06-10")

    before = shop.read_certificate(certificate["id"])
    refused_renewal = client.renew_certificate(
        certificate["id"],
        factories.renewal_payload(before["version"], audit["id"], new_expires_on="2032-01-01"),
        admin_headers,
    )
    validate_error(refused_renewal, api_errors.ERR_INVALID_CERTIFICATE_STATE, 409)

    after = shop.read_certificate(certificate["id"])
    assert after["version"] == before["version"]
    assert after["expires_on"] == "2029-01-01"
    assert after["renewal_count"] == 0

    without_report = shop.heat(
        heat_number="H-6500",
        mtr_received=False,
        yield_ksi=45.0,
        tensile_ksi=80.0,
        quantity_received_lb=1000.00,
    )
    validate_error(
        client.review_heat(
            without_report["id"], factories.mtr_review_payload("ACCEPT"), shop.acting_as(inspector)
        ),
        api_errors.ERR_TRACEABILITY_INCOMPLETE,
        409,
    )
    assert shop.read_heat(without_report["id"])["status"] == HEAT_STATUS_QUARANTINE
    assert shop.read_heat(without_report["id"])["version"] == 1

    settled = shop.heat(heat_number="H-6501", quantity_received_lb=1000.00)
    validate_success(
        client.review_heat(
            settled["id"],
            factories.mtr_review_payload(
                "REJECT", reason="Chemistry outside the ordered range on the ladle analysis"
            ),
            shop.acting_as(inspector),
        ),
        200,
    )
    validate_error(
        client.review_heat(
            settled["id"], factories.mtr_review_payload("ACCEPT"), shop.acting_as(inspector)
        ),
        api_errors.ERR_INVALID_HEAT_STATE,
        409,
    )
    replayed = shop.read_heat(settled["id"])
    assert replayed["status"] == HEAT_STATUS_REJECTED
    assert replayed["version"] == 2


def test_a_nominal_wall_thinner_than_the_code_demands_is_stored_but_refused_at_submission(
    client, shop
):
    """Adequacy is checked at submission, not at sheet creation, and the comparison admits equality.

    PRD §3.3: "Submitting a sheet for independent review moves it `DRAFT → SUBMITTED` and requires three things: the sheet is currently `DRAFT` (a second submit draws `ERR_INVALID_CALCULATION_STATE`), the parent job is in `DRAFT` or `DESIGN_REVIEW`, and `thickness_nominal_in` is at least `thickness_required_in`."

    PRD §3.3: "A sheet whose intended nominal wall is thinner than the code demands is refused with `ERR_INSUFFICIENT_WALL_THICKNESS`."

    Design: Corner/errors/error_design_submission_refused_when_nominal_is_below_required_thickness
    """
    engineer = shop.design_engineer()
    certificate = shop.certificate(cert_number="CA-U-8928")
    job = shop.job(certificate=certificate, job_number="J-2885-C42", mawp_psi=350)

    thin = shop.prepare_sheet(
        job["id"],
        COMPONENT_SHELL,
        preparer=engineer,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.5000,
    )
    assert_number_equals(thin["thickness_required_in"], 0.5931, 4, "thickness_required_in")
    assert_number_equals(thin["joint_efficiency"], 1.00, 2, "joint_efficiency")
    assert thin["status"] == CALC_STATUS_DRAFT
    assert thin["version"] == 1

    validate_error(
        client.submit_calculation(thin["id"], shop.acting_as(engineer)),
        api_errors.ERR_INSUFFICIENT_WALL_THICKNESS,
        409,
    )
    assert shop.read_job(job["id"])["status"] == JOB_STATUS_DRAFT
    still_draft = validate_success(client.get_calculation(thin["id"], shop.acting_as(engineer)), 200)
    assert still_draft["status"] == CALC_STATUS_DRAFT

    control_job = shop.job(certificate=certificate, job_number="J-2885-C43", mawp_psi=350)
    exact = shop.prepare_sheet(
        control_job["id"],
        COMPONENT_SHELL,
        preparer=engineer,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.5931,
    )
    assert_number_equals(exact["thickness_nominal_in"], 0.5931, 4, "thickness_nominal_in")
    assert_number_equals(exact["thickness_required_in"], 0.5931, 4, "thickness_required_in")

    submitted = validate_success(
        client.submit_calculation(exact["id"], shop.acting_as(engineer)), 200
    )
    assert submitted["status"] == CALC_STATUS_SUBMITTED
    assert shop.read_job(control_job["id"])["status"] == JOB_STATUS_DESIGN_REVIEW


def test_weld_map_planning_and_release_gates_each_refuse_on_an_otherwise_healthy_job(client, shop):
    """Each planning refusal is fired on a healthy job, and the two release refusals sit on separate jobs so each diagnosis is unambiguous.

    PRD §3.4: "The product form must suit the piece — `SHELL` and `HEAD` require a heat whose `form` is `PLATE`, `NOZZLE` requires `PIPE`, `TUBESHEET` accepts either `FORGING` or `PLATE`, and `FLANGE` requires `FORGING` — and a mismatch is refused with `ERR_MATERIAL_FORM_MISMATCH`."

    PRD §3.5: "The cited procedure must be `QUALIFIED`, or the request draws `ERR_WPS_NOT_QUALIFIED`."

    PRD §3.5: "The joint's `thickness_in` must fall inside the cited procedure's qualified window, at least `thickness_min_in` and at most `thickness_max_in`; outside it the request draws `ERR_THICKNESS_OUTSIDE_WPS_RANGE`."

    PRD §3.6: "Otherwise it is `UT` when `thickness_in` is at least 2.000 **and** `joint_type` is `BUTT`, since ultrasonic examination is the practical method on heavy butt joints, and `RT` in every other case."

    PRD §3.5: "When the job's `governing_joint_efficiency` equals 1.00 — that is, when every approved calculation sheet declared full radiography — every Category A joint must have `joint_type` `BUTT`, because a full-efficiency design cannot be built with a corner or fillet on a main seam; a violation draws `ERR_JOINT_TYPE_NOT_PERMITTED`."

    PRD §3.5: "No joint still at `PLANNED` may reference a piece whose `status` is `SCRAPPED`, or the release draws `ERR_PART_SCRAPPED`."

    PRD §3.4: "A part that is already `SCRAPPED`, or one that is still referenced as `part_a_id` or `part_b_id` by a joint whose `fab_status` has reached `WELDED`, cannot be scrapped and draws `ERR_INVALID_PART_STATE`."

    Design: Corner/errors/error_weld_map_planning_gate_family_from_material_form_to_release
    """
    engineer = shop.welding_engineer()
    certificate = shop.certificate(cert_number="CA-U-8929")
    heat = shop.accepted_heat(
        heat_number="H-6600", spec=SPEC_SA_516_70, form=FORM_PLATE, quantity_received_lb=4000.00
    )
    procedure = shop.qualified_wps(wps_number="WPS-140")
    unqualified = shop.wps(
        wps_number="WPS-141", process=PROCESS_SAW, filler_f_number=6,
        thickness_min_in=0.2500, thickness_max_in=2.0000,
    )

    job_a = shop.job(certificate=certificate, job_number="J-2885-C44", mawp_psi=350)
    shop.release_design(job_a, rt_extent_declared=RT_EXTENT_FULL)
    part_a1 = shop.issue_part(job_a["id"], heat["id"], part_mark="SH-01", issued_quantity_lb=1000.00)
    part_a2 = shop.issue_part(job_a["id"], heat["id"], part_mark="SH-02", issued_quantity_lb=1000.00)

    job_b = shop.job(certificate=certificate, job_number="J-2885-C45", mawp_psi=350)
    shop.release_design(job_b, rt_extent_declared=RT_EXTENT_FULL)
    part_b1 = shop.issue_part(job_b["id"], heat["id"], part_mark="SH-01B", issued_quantity_lb=1000.00)

    validate_error(
        client.issue_part(
            job_a["id"],
            factories.part_payload(
                heat["id"],
                part_mark="NZ-01",
                component_type=COMPONENT_TYPE_NOZZLE,
                issued_quantity_lb=100.00,
            ),
            shop.acting_as(engineer),
        ),
        api_errors.ERR_MATERIAL_FORM_MISMATCH,
        409,
    )

    validate_error(
        client.plan_weld(
            job_a["id"],
            factories.production_weld_payload(
                unqualified["id"],
                part_a1["id"],
                weld_number="W-001",
                joint_category=JOINT_CATEGORY_A,
                joint_type=JOINT_TYPE_BUTT,
                thickness_in=0.7500,
            ),
            shop.acting_as(engineer),
        ),
        api_errors.ERR_WPS_NOT_QUALIFIED,
        409,
    )

    validate_error(
        client.plan_weld(
            job_a["id"],
            factories.production_weld_payload(
                procedure["id"],
                part_a1["id"],
                weld_number="W-001",
                joint_category=JOINT_CATEGORY_A,
                joint_type=JOINT_TYPE_BUTT,
                thickness_in=4.0000,
            ),
            shop.acting_as(engineer),
        ),
        api_errors.ERR_THICKNESS_OUTSIDE_WPS_RANGE,
        409,
    )

    healthy = shop.plan_joint(
        job_a["id"],
        procedure["id"],
        part_a1["id"],
        weld_number="W-001",
        joint_category=JOINT_CATEGORY_A,
        joint_type=JOINT_TYPE_BUTT,
        thickness_in=0.7500,
    )
    assert healthy["weld_number"] == "W-001"
    assert healthy["required_volumetric_pct"] == 100
    assert healthy["volumetric_method"] == METHOD_RT

    validate_error(
        client.plan_weld(
            job_a["id"],
            factories.production_weld_payload(
                procedure["id"],
                part_a2["id"],
                weld_number="W-001",
                joint_category=JOINT_CATEGORY_C,
                joint_type=JOINT_TYPE_FILLET,
                thickness_in=0.5000,
            ),
            shop.acting_as(engineer),
        ),
        api_errors.ERR_DUPLICATE_WELD_NUMBER,
        409,
    )

    shop.plan_joint(
        job_a["id"],
        procedure["id"],
        part_a1["id"],
        weld_number="W-002",
        joint_category=JOINT_CATEGORY_A,
        joint_type=JOINT_TYPE_CORNER,
        thickness_in=0.7500,
    )
    validate_error(
        client.release_weld_map(job_a["id"], shop.acting_as(engineer)),
        api_errors.ERR_JOINT_TYPE_NOT_PERMITTED,
        409,
    )
    assert shop.read_job(job_a["id"])["status"] == JOB_STATUS_FAB_PLANNING

    scrapped = shop.scrap_part(
        part_b1["id"], scrap_reason="Plate warped beyond tolerance during rolling"
    )
    assert scrapped["status"] == PART_STATUS_SCRAPPED
    assert_number_equals(
        shop.read_heat(heat["id"])["quantity_remaining_lb"], 2000.00, 2, "quantity_remaining_lb"
    )

    validate_error(
        client.scrap_part(
            part_b1["id"],
            factories.scrap_payload("Duplicate scrap ticket raised by the second shift"),
            shop.acting_as(engineer),
        ),
        api_errors.ERR_INVALID_PART_STATE,
        409,
    )
    assert_number_equals(
        shop.read_heat(heat["id"])["quantity_remaining_lb"], 2000.00, 2, "quantity_remaining_lb"
    )

    shop.plan_joint(
        job_b["id"],
        procedure["id"],
        part_b1["id"],
        weld_number="W-101",
        joint_category=JOINT_CATEGORY_A,
        joint_type=JOINT_TYPE_BUTT,
        thickness_in=0.7500,
    )
    validate_error(
        client.release_weld_map(job_b["id"], shop.acting_as(engineer)),
        api_errors.ERR_PART_SCRAPPED,
        409,
    )
    assert shop.read_job(job_b["id"])["status"] == JOB_STATUS_FAB_PLANNING

    joints, meta = validate_paginated(
        client.list_welds(
            shop.acting_as(engineer), params={"job_id": job_a["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["weld_number"] for row in joints) == ["W-001", "W-002"]
