"""One write reaching several entities away: down the fabrication spine and up the compliance spine."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    AUDIT_STATUS_CLOSED,
    AUDIT_TYPE_INTERNAL_QMS,
    BAY_1,
    CERT_STATUS_PROBATION,
    COMPONENT_TYPE_HEAD,
    COMPONENT_TYPE_SHELL,
    DESIGN_CODE_DIV1,
    DISPOSITION_OPEN,
    EXAM_RESULT_REJECT,
    FAB_STATUS_WELDED,
    FORM_TYPE_U1A,
    JOB_STATUS_DATA_PACKAGE,
    JOB_STATUS_NDE_HOLD,
    JOINT_CATEGORY_B,
    JOINT_CATEGORY_C,
    JOINT_TYPE_BUTT,
    JOINT_TYPE_FILLET,
    MISSING_ITEM_OPEN_NONCONFORMANCE,
    NCR_SOURCE_NDE_REJECT,
    NDE_STATUS_REJECTED,
    REPORT_STATUS_AI_SIGNED,
    REPORT_STATUS_ASSEMBLING,
    REPORT_STATUS_STAMP_HOLD,
    RT_EXTENT_FULL,
    SEVERITY_MAJOR,
    SEVERITY_OBSERVATION,
    SPEC_SA_516_70,
    TEST_SIDE_SHELL,
    TEST_TYPE_HYDROSTATIC,
    VESSEL_TYPE_PRESSURE_VESSEL,
)


def _designed_job(shop, job_number):
    certificate = shop.certificate(cert_number="CA-U-8801")
    job = shop.job(
        certificate,
        job_number=job_number,
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
    procedure = shop.qualified_wps(wps_number="WPS-1", pwht_required=False, preheat_min_f=50)
    qualification = shop.welder_qualification(
        procedure["id"], welder_stamp="W12", welder_name="Rosa Vela"
    )
    return certificate, job, shell_part, head_part, procedure, qualification


def _reported_job_awaiting_one_radiograph(shop):
    """A welded Category B seam with its RT examination pending and a report already assembled."""
    certificate, job, shell_part, head_part, procedure, qualification = _designed_job(
        shop, "J-2885-07"
    )
    joint = shop.plan_joint(
        job["id"],
        procedure["id"],
        shell_part["id"],
        weld_number="W-001",
        joint_category=JOINT_CATEGORY_B,
        joint_type=JOINT_TYPE_BUTT,
        thickness_in=1.5000,
        part_b_id=head_part["id"],
    )
    shop.release_weld_map(job["id"])
    shop.complete_joint(
        joint["id"], qualification["id"], welded_at="2026-07-30T09:00:00.000Z"
    )
    exams = shop.run_nde_plan(job["id"])
    assembler = shop.qc_inspector()
    report = shop.assemble_data_report(
        job["id"], assembler=assembler, form_type=FORM_TYPE_U1A
    )
    return job, joint, exams[0], report, assembler


def test_one_rejected_radiograph_marks_the_examination_the_joint_and_raises_a_nonconformance(
    client, shop
):
    """The first three levels of the chain move on a single interpretation write.

    PRD §3.6: "Both branches store `examiner_personnel_id` from the acting `X-User-ID` along with `exam_date`, `examined_coverage_pct` and `indications_count`."

    PRD §3.6: "The examination record itself moves `PENDING → ACCEPT` on the first branch and `PENDING → REJECT` on the second, and both `ACCEPT` and `REJECT` are terminal for it — an interpretation once recorded is never revised."

    PRD §3.6: "A `REJECT` moves the joint `nde_status` `PLANNED → REJECTED` and triggers the full cascade: a nonconformance report is raised with `source` `NDE_REJECT` and `disposition` `OPEN`, the job's `nonconformance_open_count` increases by 1, the job moves `FABRICATION → NDE_HOLD`, every data report of the job re-derives `completeness_score` and `missing_items`, and every data report of the job sitting at `AI_SIGNED` is pushed to `STAMP_HOLD`."

    Design: Difficulty/transitive_cascade/transitive_nde_reject_propagates_exam_weld_ncr_job_and_data_report
    """
    inspector = shop.qc_inspector()
    job, joint, exam, report, _ = _reported_job_awaiting_one_radiograph(shop)

    rejected = validate_success(
        client.record_exam_result(
            exam["id"],
            factories.exam_result_payload(
                result="REJECT",
                examined_coverage_pct=100.00,
                indications_count=2,
                exam_date="2026-08-01",
            ),
            shop.acting_as(inspector),
        ),
        200,
    )
    assert rejected["result"] == EXAM_RESULT_REJECT
    assert rejected["indications_count"] == 2
    assert rejected["examiner_personnel_id"] == inspector["id"]

    marked = shop.read_joint(joint["id"])
    assert marked["nde_status"] == NDE_STATUS_REJECTED
    assert marked["fab_status"] == FAB_STATUS_WELDED

    rows, meta = validate_paginated(
        client.list_nonconformances(shop.admin, params={"job_id": job["id"]})
    )
    assert meta["total_count"] == 1
    raised = rows[0]
    assert raised["weld_id"] == joint["id"]
    assert raised["source"] == NCR_SOURCE_NDE_REJECT
    assert raised["disposition"] == DISPOSITION_OPEN
    assert raised["closed_at"] is None
    assert report["id"] is not None


def test_the_same_rejection_reaches_the_job_and_a_report_assembled_before_it(client, shop):
    """The fifth level shows up only as a recomputed `missing_items` on a report that predates the reject.

    PRD §3.2: "`nonconformance_open_count` counts the job's nonconformance reports whose `disposition` is `OPEN`, `REPAIR` or `USE_AS_IS`; reaching 0 is what releases an examination hold."

    PRD §3.9: "`NDE` is the number of the job's examinations whose `result` is `ACCEPT`, divided by the number of the job's examinations."

    PRD §3.9: "It then contains the literal `OPEN_NONCONFORMANCE` when the job's `nonconformance_open_count` is above 0, and then the literal `CERTIFICATE_NOT_AUTHORIZED` when the governing certificate has `stamping_authorized` false."

    PRD §3.9: "Reports are listed with filters on `job_id`, `assembled_by_personnel_id`, `ai_personnel_id`, `form_type` and `status`; a single-report read re-derives the scores before answering."

    Design: Difficulty/transitive_cascade/transitive_nde_reject_propagates_exam_weld_ncr_job_and_data_report
    """
    inspector = shop.qc_inspector()
    job, joint, exam, report, assembler = _reported_job_awaiting_one_radiograph(shop)

    before = shop.read_data_report(report["id"])
    assert before["missing_items"] == ["NDE"]
    assert_number_equals(before["completeness_score"], 85.00, 2, "completeness_score")
    assert_number_equals(before["section_scores"]["NDE"], 0.00, 2, "NDE")

    validate_success(
        client.record_exam_result(
            exam["id"],
            factories.exam_result_payload(
                result="REJECT",
                examined_coverage_pct=100.00,
                indications_count=2,
                exam_date="2026-08-01",
            ),
            shop.acting_as(inspector),
        ),
        200,
    )

    held = shop.read_job(job["id"])
    assert held["status"] == JOB_STATUS_NDE_HOLD
    assert held["nonconformance_open_count"] == 1
    assert_number_equals(held["weld_completion_pct"], 0.00, 2, "weld_completion_pct")

    after = shop.read_data_report(report["id"])
    assert after["missing_items"] == ["NDE", MISSING_ITEM_OPEN_NONCONFORMANCE]
    assert_number_equals(after["completeness_score"], 85.00, 2, "completeness_score")
    assert_number_equals(after["section_scores"]["NDE"], 0.00, 2, "NDE")
    assert after["status"] == REPORT_STATUS_ASSEMBLING
    assert after["assembled_by_personnel_id"] == assembler["id"]
    assert shop.read_joint(joint["id"])["nde_status"] == NDE_STATUS_REJECTED


def _signed_package(shop):
    """A finished vessel whose data report has been assembled, submitted and countersigned."""
    certificate, job, shell_part, head_part, procedure, qualification = _designed_job(
        shop, "J-2885-08"
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
    test = shop.pressure_test(
        job["id"],
        test_side=TEST_SIDE_SHELL,
        test_type=TEST_TYPE_HYDROSTATIC,
        test_bay_code=BAY_1,
        scheduled_start="2026-08-10T08:00:00.000Z",
        scheduled_end="2026-08-10T12:00:00.000Z",
    )
    signer = shop.authorized_inspector()
    shop.witness_pressure_test(test["id"], witness=signer)
    shop.record_pressure_test_result(
        test["id"],
        result="PASS",
        observed_pressure_psi=460.0,
        observed_hold_minutes=35,
        test_medium_temp_f=70,
    )
    assembler = shop.qc_inspector()
    report = shop.assemble_data_report(
        job["id"], assembler=assembler, form_type=FORM_TYPE_U1A
    )
    shop.submit_report_to_ai(report["id"], actor=assembler)
    signed = shop.sign_data_report(report["id"], signer=signer)
    return certificate, job, signed, assembler, signer


def test_a_single_major_audit_finding_puts_the_licence_on_probation(client, shop):
    """The audit close counts the major, ignores the observation and re-derives the certificate posture.

    PRD §3.1: "On close, `major_finding_count` becomes the number of findings whose `severity` is `MAJOR` and `minor_finding_count` the number whose `severity` is `MINOR`; findings recorded as `OBSERVATION` are counted in neither."

    PRD §3.1: "`satisfactory` becomes true only when the audit is `CLOSED`, its `major_finding_count` is 0 and its `minor_finding_count` is 5 or fewer, and `CLOSED` is terminal for an audit."

    PRD §3.1: "The certificate adds this audit's `major_finding_count` to its own `open_major_findings_count` and this audit's `minor_finding_count` to its own `open_minor_findings_count`, sets `last_audit_closed_on` to the audit's `closed_on`, re-derives `status` and `stamping_authorized` from the new counters, and increments its `version`."

    PRD §3.1: "`stamping_authorized` is true only when `status` is `ACTIVE`, `expires_on` is on or after the current logical UTC date, and `open_major_findings_count` is exactly 0 — it is the single flag every witness, signature and nameplate attempt consults."

    Design: Difficulty/transitive_cascade/transitive_audit_close_suspends_certificate_and_freezes_signed_data_report
    """
    certificate, job, signed, assembler, signer = _signed_package(shop)

    assert_number_equals(signed["completeness_score"], 100.00, 2, "completeness_score")
    assert signed["status"] == REPORT_STATUS_AI_SIGNED
    assert signed["ai_personnel_id"] == signer["id"]
    assert signed["assembled_by_personnel_id"] == assembler["id"]

    audit = validate_success(
        client.create_audit(
            factories.audit_payload(
                certificate["id"],
                audit_type=AUDIT_TYPE_INTERNAL_QMS,
                scheduled_date="2026-08-01",
            ),
            shop.admin,
        ),
        201,
    )
    closed = validate_success(
        client.close_audit(
            audit["id"],
            factories.audit_close_payload(
                closed_on="2026-08-01",
                findings=[
                    factories.finding(
                        SEVERITY_MAJOR, finding_code="F-101", clause_reference="UG-90(c)"
                    ),
                    factories.finding(
                        SEVERITY_OBSERVATION, finding_code="F-102", clause_reference="UG-4"
                    ),
                ],
            ),
            shop.admin,
        ),
        200,
    )
    assert closed["status"] == AUDIT_STATUS_CLOSED
    assert closed["major_finding_count"] == 1
    assert closed["minor_finding_count"] == 0
    assert closed["satisfactory"] is False

    posture = shop.read_certificate(certificate["id"])
    assert posture["open_major_findings_count"] == 1
    assert posture["open_minor_findings_count"] == 0
    assert posture["status"] == CERT_STATUS_PROBATION
    assert posture["stamping_authorized"] is False
    assert posture["last_audit_closed_on"] == "2026-08-01"
    assert job["id"] is not None


def test_the_probation_freezes_the_signed_report_and_puts_the_nameplate_out_of_reach(client, shop):
    """The report is pushed to STAMP_HOLD with its signature intact, and the stamp is then refused on state.

    PRD §3.1: "In both the `ACTIVE → PROBATION` and `ACTIVE → SUSPENDED` cases `stamping_authorized` is re-derived to false, and the third cascade chain fires: every data report whose job was built under this certificate and which currently sits at `AI_SIGNED` is pushed to `STAMP_HOLD`."

    PRD §3.9: "A report moves `AI_SIGNED → STAMP_HOLD` whenever the governing certificate's `stamping_authorized` becomes false — which happens on a major audit finding, on suspension and on expiry — or whenever the job acquires an open nonconformance from a rejected examination or a failed test; the corresponding literal, `CERTIFICATE_NOT_AUTHORIZED` or `OPEN_NONCONFORMANCE`, is added to `missing_items`."

    PRD §3.9: "The signature itself, along with `ai_personnel_id` and `ai_signed_at`, survives the round trip."

    PRD §3.9: "The report must be `AI_SIGNED` — a report at `STAMP_HOLD` is refused with `ERR_INVALID_REPORT_STATE` — and the governing certificate must be unexpired with `stamping_authorized` true, drawing `ERR_CERTIFICATE_EXPIRED` or `ERR_STAMPING_NOT_AUTHORIZED` otherwise, since the authority is re-checked at the moment of stamping and not merely at the moment of signature."

    PRD §2.8: "**Target state.** The record named in the path is in a state from which the requested transition is declared — otherwise the matching 409: `ERR_INVALID_JOB_STATE`, `ERR_INVALID_CALCULATION_STATE`, `ERR_INVALID_HEAT_STATE`, `ERR_INVALID_PART_STATE`, `ERR_INVALID_WPS_STATE`, `ERR_INVALID_WELD_STATE`, `ERR_INVALID_EXAM_STATE`, `ERR_INVALID_NONCONFORMANCE_STATE`, `ERR_INVALID_BATCH_STATE`, `ERR_INVALID_TEST_STATE`, `ERR_INVALID_REPORT_STATE`, `ERR_INVALID_AUDIT_STATE` or `ERR_INVALID_CERTIFICATE_STATE`."

    Design: Difficulty/transitive_cascade/transitive_audit_close_suspends_certificate_and_freezes_signed_data_report
    """
    certificate, job, signed, assembler, signer = _signed_package(shop)
    assert signed["status"] == REPORT_STATUS_AI_SIGNED
    signed_at = signed["ai_signed_at"]

    audit = shop.audit(
        certificate["id"],
        audit_type=AUDIT_TYPE_INTERNAL_QMS,
        scheduled_date="2026-08-01",
    )
    validate_success(
        client.close_audit(
            audit["id"],
            factories.audit_close_payload(
                closed_on="2026-08-01",
                findings=[
                    factories.finding(
                        SEVERITY_MAJOR, finding_code="F-101", clause_reference="UG-90(c)"
                    ),
                    factories.finding(
                        SEVERITY_OBSERVATION, finding_code="F-102", clause_reference="UG-4"
                    ),
                ],
            ),
            shop.admin,
        ),
        200,
    )

    frozen = shop.read_data_report(signed["id"])
    assert frozen["status"] == REPORT_STATUS_STAMP_HOLD
    assert frozen["ai_personnel_id"] == signer["id"]
    assert frozen["ai_signed_at"] == signed_at
    assert shop.read_job(job["id"])["status"] == JOB_STATUS_DATA_PACKAGE

    refused = client.stamp_nameplate(
        signed["id"], factories.stamp_payload(nameplate_serial="NP-0001"), shop.admin
    )
    validate_error(refused, api_errors.ERR_INVALID_REPORT_STATE, 409)

    untouched = shop.read_data_report(signed["id"])
    assert untouched["nameplate_serial"] is None
    assert untouched["nameplate_stamped_at"] is None
    assert untouched["status"] == REPORT_STATUS_STAMP_HOLD
    assert untouched["assembled_by_personnel_id"] == assembler["id"]
