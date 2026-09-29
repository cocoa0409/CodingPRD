"""Operations refused because of the state of an entity their request body never names."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    AUDIT_STATUS_CLOSED,
    AUDIT_STATUS_SCHEDULED,
    AUDIT_TYPE_INTERNAL_QMS,
    AUDIT_TYPE_TRIENNIAL_RENEWAL,
    BATCH_STATUS_COMPLETE,
    BATCH_STATUS_IN_PROGRESS,
    BATCH_STATUS_SCHEDULED,
    BAY_1,
    CERT_STATUS_ACTIVE,
    CERT_STATUS_PROBATION,
    COMPONENT_TYPE_HEAD,
    COMPONENT_TYPE_SHELL,
    DESIGN_CODE_DIV1,
    FURNACE_A,
    JOB_STATUS_FABRICATION,
    JOB_STATUS_TESTING,
    JOINT_CATEGORY_C,
    JOINT_TYPE_FILLET,
    NDE_STATUS_ACCEPTED,
    PWHT_STATUS_COMPLETE,
    PWHT_STATUS_IN_PROGRESS,
    PWHT_STATUS_PENDING,
    RT_EXTENT_FULL,
    SPEC_SA_516_70,
    TEST_RESULT_PENDING,
    TEST_SIDE_SHELL,
    TEST_TYPE_HYDROSTATIC,
    VESSEL_TYPE_PRESSURE_VESSEL,
)


def _job_with_a_scheduled_charge_over_its_only_joint(shop):
    """One examined fillet weld awaiting heat treatment, its charge booked but not yet run."""
    job = shop.job(
        job_number="J-2885-13",
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
    shop.issue_part(
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
    joint = shop.plan_joint(
        job["id"],
        procedure["id"],
        shell_part["id"],
        weld_number="W-001",
        joint_category=JOINT_CATEGORY_C,
        joint_type=JOINT_TYPE_FILLET,
        thickness_in=0.7500,
    )
    shop.release_weld_map(job["id"])
    shop.complete_joint(joint["id"], qualification["id"], welded_at="2026-07-30T09:00:00.000Z")
    exams = shop.run_nde_plan(job["id"])
    shop.accept_exam(exams[0]["id"], examined_coverage_pct=100.00, exam_date="2026-07-31")
    scheduler = shop.welding_engineer()
    batch = shop.pwht_batch(
        job["id"],
        [joint["id"]],
        scheduler=scheduler,
        furnace_code=FURNACE_A,
        scheduled_start="2026-08-10T08:00:00.000Z",
        scheduled_end="2026-08-10T12:00:00.000Z",
        soak_temp_f=1150,
    )
    return job, joint, batch, scheduler


def _schedule_shell_test(client, shop, job, inspector):
    return client.create_pressure_test(
        factories.pressure_test_payload(
            job["id"],
            test_side=TEST_SIDE_SHELL,
            test_type=TEST_TYPE_HYDROSTATIC,
            test_bay_code=BAY_1,
            scheduled_start="2026-08-11T08:00:00.000Z",
            scheduled_end="2026-08-11T12:00:00.000Z",
        ),
        shop.acting_as(inspector),
    )


def test_a_booked_and_then_running_charge_both_hold_the_pressure_test_back(client, shop):
    """The test request names no charge, yet is refused identically while that charge is SCHEDULED and while it is IN_PROGRESS.

    PRD §3.8: "Every joint whose `pwht_status` is not `NOT_REQUIRED` must have reached `COMPLETE`, or the gate draws `ERR_PWHT_INCOMPLETE`."

    PRD §3.8: "Every batched joint moves `pwht_status` `PENDING → IN_PROGRESS` in the same request."

    PRD §3.8: "`actual_soak_minutes` must be at least `required_soak_minutes`, or it draws `ERR_SOAK_TIME_INSUFFICIENT`."

    PRD §3.6: "The numerator counts the job's joints whose `fab_status` is `WELDED` **and** whose `nde_status` is `ACCEPTED` **and** whose `pwht_status` is either `NOT_REQUIRED` or `COMPLETE`; a joint failing any one of the three is not counted."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_pressure_test_creation_blocked_by_incomplete_pwht_batch
    """
    inspector = shop.qc_inspector()
    job, joint, batch, scheduler = _job_with_a_scheduled_charge_over_its_only_joint(shop)

    assert batch["status"] == BATCH_STATUS_SCHEDULED
    assert batch["required_soak_minutes"] == 45
    booked = shop.read_joint(joint["id"])
    assert booked["nde_status"] == NDE_STATUS_ACCEPTED
    assert booked["pwht_status"] == PWHT_STATUS_PENDING
    assert_number_equals(
        shop.read_job(job["id"])["weld_completion_pct"], 0.00, 2, "weld_completion_pct"
    )

    validate_error(
        _schedule_shell_test(client, shop, job, inspector), api_errors.ERR_PWHT_INCOMPLETE, 409
    )
    assert shop.read_job(job["id"])["status"] == JOB_STATUS_FABRICATION

    started = shop.start_pwht_batch(batch["id"], actor=scheduler)
    assert started["status"] == BATCH_STATUS_IN_PROGRESS
    assert shop.read_joint(joint["id"])["pwht_status"] == PWHT_STATUS_IN_PROGRESS

    validate_error(
        _schedule_shell_test(client, shop, job, inspector), api_errors.ERR_PWHT_INCOMPLETE, 409
    )

    short_soak = client.complete_pwht_batch(
        batch["id"],
        factories.pwht_complete_payload(
            actual_soak_minutes=44, chart_record_number="CR-2885-01", chart_uploaded=True
        ),
        shop.acting_as(shop.second_welding_engineer()),
    )
    validate_error(short_soak, api_errors.ERR_SOAK_TIME_INSUFFICIENT, 409)

    still_running = validate_success(client.get_pwht_batch(batch["id"], shop.admin), 200)
    assert still_running["status"] == BATCH_STATUS_IN_PROGRESS
    assert still_running["chart_record_number"] is None
    assert still_running["actual_soak_minutes"] is None
    assert shop.read_joint(joint["id"])["pwht_status"] == PWHT_STATUS_IN_PROGRESS


def test_the_chart_review_at_exactly_the_required_soak_releases_the_vessel_into_testing(
    client, shop
):
    """A second engineer certifies the chart at exactly the required soak, and the test that was refused twice is admitted.

    PRD §3.8: "On success `chart_reviewed_by_personnel_id` records the acting user, every batched joint moves `pwht_status` `IN_PROGRESS → COMPLETE`, the job's `weld_completion_pct` is recomputed, and every data report of the job re-derives its `PWHT` section score and its `completeness_score`."

    PRD §3.8: "And the acting `X-User-ID` must differ from `scheduled_by_personnel_id`, or it draws `ERR_SEGREGATION_OF_DUTIES` — the person who scheduled the charge may not be the person who certifies its chart."

    PRD §3.8: "For a `HYDROSTATIC` test, `test_pressure_psi` is 1.3 multiplied by the job's `mawp_psi` multiplied by the job's `stress_ratio`, rounded half up to one decimal place; `min_hold_minutes` is 30; and `min_medium_temp_f` is the job's `mdmt_f` plus 30."

    PRD §3.8: "Creation answers 201 with the test at `result` `PENDING`, `ai_witness_confirmed` false, `witnessed_by_personnel_id` null and the observed figures null."

    PRD §3.8: "Scheduling the first test of a job is the aggregate gate that moves it `FABRICATION → TESTING`, and it walks the entire weld map."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_pressure_test_creation_blocked_by_incomplete_pwht_batch
    """
    inspector = shop.qc_inspector()
    reviewer = shop.second_welding_engineer()
    job, joint, batch, scheduler = _job_with_a_scheduled_charge_over_its_only_joint(shop)
    shop.start_pwht_batch(batch["id"], actor=scheduler)

    completed = validate_success(
        client.complete_pwht_batch(
            batch["id"],
            factories.pwht_complete_payload(
                actual_soak_minutes=45, chart_record_number="CR-2885-01", chart_uploaded=True
            ),
            shop.acting_as(reviewer),
        ),
        200,
    )
    assert completed["status"] == BATCH_STATUS_COMPLETE
    assert completed["chart_uploaded"] is True
    assert completed["actual_soak_minutes"] == 45
    assert completed["chart_reviewed_by_personnel_id"] == reviewer["id"]
    assert completed["chart_reviewed_by_personnel_id"] != completed["scheduled_by_personnel_id"]
    assert completed["scheduled_by_personnel_id"] == scheduler["id"]

    treated = shop.read_joint(joint["id"])
    assert treated["pwht_status"] == PWHT_STATUS_COMPLETE
    assert_number_equals(
        shop.read_job(job["id"])["weld_completion_pct"], 100.00, 2, "weld_completion_pct"
    )

    admitted = validate_success(_schedule_shell_test(client, shop, job, inspector), 201)
    assert admitted["result"] == TEST_RESULT_PENDING
    assert admitted["ai_witness_confirmed"] is False
    assert admitted["witnessed_by_personnel_id"] is None
    assert admitted["observed_pressure_psi"] is None
    assert admitted["observed_hold_minutes"] is None
    assert admitted["test_medium_temp_f"] is None
    assert_number_equals(admitted["test_pressure_psi"], 455.0, 1, "test_pressure_psi")
    assert admitted["min_hold_minutes"] == 30
    assert admitted["min_medium_temp_f"] == 10
    assert shop.read_job(job["id"])["status"] == JOB_STATUS_TESTING


def _licence_on_probation_with_two_open_audits(shop):
    """A certificate carrying one major finding, plus a routine audit and a renewal audit both still open."""
    certificate = shop.certificate(
        cert_number="CA-U-8801",
        scope_codes=["U"],
        issued_on="2026-01-01",
        expires_on="2029-01-01",
    )
    first = shop.audit(
        certificate["id"], audit_type=AUDIT_TYPE_INTERNAL_QMS, scheduled_date="2026-07-01"
    )
    shop.close_audit(first["id"], closed_on="2026-07-05", major=1)
    routine = shop.audit(
        certificate["id"], audit_type=AUDIT_TYPE_INTERNAL_QMS, scheduled_date="2026-07-10"
    )
    renewal = shop.audit(
        certificate["id"], audit_type=AUDIT_TYPE_TRIENNIAL_RENEWAL, scheduled_date="2026-07-20"
    )
    return certificate, routine, renewal


def test_neither_an_open_audit_nor_a_closed_unsatisfactory_one_can_carry_a_renewal(client, shop):
    """The same audit is refused as a renewal basis while it is SCHEDULED and again once it closes with six minors.

    PRD §3.1: "The named audit must exist — a `renewal_audit_id` that names nothing draws `ERR_AUDIT_NOT_FOUND` — must belong to this certificate, and must be `CLOSED` with `satisfactory` true; anything else is refused with `ERR_RENEWAL_AUDIT_NOT_SATISFACTORY`."

    PRD §3.1: "`satisfactory` becomes true only when the audit is `CLOSED`, its `major_finding_count` is 0 and its `minor_finding_count` is 5 or fewer, and `CLOSED` is terminal for an audit."

    PRD §3.1: "the certificate is `EXPIRED` whenever `expires_on` falls before the current logical UTC date; otherwise it is `SUSPENDED` whenever `open_major_findings_count` has reached 3 or more; otherwise it is `PROBATION` whenever `open_major_findings_count` is 1 or more or `open_minor_findings_count` is more than 5; otherwise it is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_certificate_renewal_gated_on_satisfactory_closed_audit
    """
    certificate, routine, renewal = _licence_on_probation_with_two_open_audits(shop)

    on_probation = shop.read_certificate(certificate["id"])
    assert on_probation["status"] == CERT_STATUS_PROBATION
    assert on_probation["open_major_findings_count"] == 1
    assert on_probation["stamping_authorized"] is False
    assert routine["status"] == AUDIT_STATUS_SCHEDULED
    assert renewal["status"] == AUDIT_STATUS_SCHEDULED

    while_open = client.renew_certificate(
        certificate["id"],
        factories.renewal_payload(
            on_probation["version"], routine["id"], new_expires_on="2030-01-01"
        ),
        shop.admin,
    )
    validate_error(while_open, api_errors.ERR_RENEWAL_AUDIT_NOT_SATISFACTORY, 409)

    closed = validate_success(
        client.close_audit(
            routine["id"],
            factories.audit_close_payload(closed_on="2026-07-15", minor=6),
            shop.admin,
        ),
        200,
    )
    assert closed["status"] == AUDIT_STATUS_CLOSED
    assert closed["major_finding_count"] == 0
    assert closed["minor_finding_count"] == 6
    assert closed["satisfactory"] is False

    accumulated = shop.read_certificate(certificate["id"])
    assert accumulated["open_major_findings_count"] == 1
    assert accumulated["open_minor_findings_count"] == 6
    assert accumulated["status"] == CERT_STATUS_PROBATION
    assert accumulated["stamping_authorized"] is False

    while_unsatisfactory = client.renew_certificate(
        certificate["id"],
        factories.renewal_payload(
            accumulated["version"], routine["id"], new_expires_on="2030-01-01"
        ),
        shop.admin,
    )
    validate_error(while_unsatisfactory, api_errors.ERR_RENEWAL_AUDIT_NOT_SATISFACTORY, 409)
    assert shop.read_certificate(certificate["id"])["renewal_count"] == 0


def test_the_satisfactory_renewal_audit_clears_both_counters_and_the_replay_is_stale(client, shop):
    """A clean renewal audit lifts the licence back to ACTIVE, and the identical second attempt fails on the version it no longer holds.

    PRD §3.1: "On close, `major_finding_count` becomes the number of findings whose `severity` is `MAJOR` and `minor_finding_count` the number whose `severity` is `MINOR`; findings recorded as `OBSERVATION` are counted in neither."

    PRD §3.1: "`expires_on` is replaced by `new_expires_on`, both `open_major_findings_count` and `open_minor_findings_count` are reset to 0, `renewal_count` increases by 1, `status` and `stamping_authorized` are re-derived — which lands the certificate at `ACTIVE` with `stamping_authorized` true — and `version` increments."

    PRD §2.8: "**Stale version.** The optimistic-concurrency field matches the parent's current `version` on the three endpoints of §2.7 — otherwise `ERR_STALE_JOB_VERSION` or `ERR_STALE_CERTIFICATE_VERSION` (412)."

    PRD §3.1: "Renewing a certificate that is already `ACTIVE` is not a declared transition and is refused with `ERR_INVALID_CERTIFICATE_STATE`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_certificate_renewal_gated_on_satisfactory_closed_audit
    """
    certificate, routine, renewal = _licence_on_probation_with_two_open_audits(shop)
    validate_success(
        client.close_audit(
            routine["id"],
            factories.audit_close_payload(closed_on="2026-07-15", minor=6),
            shop.admin,
        ),
        200,
    )

    clean = validate_success(
        client.close_audit(
            renewal["id"],
            factories.audit_close_payload(closed_on="2026-07-25", observation=1),
            shop.admin,
        ),
        200,
    )
    assert clean["status"] == AUDIT_STATUS_CLOSED
    assert clean["major_finding_count"] == 0
    assert clean["minor_finding_count"] == 0
    assert clean["satisfactory"] is True

    before = shop.read_certificate(certificate["id"])
    assert before["status"] == CERT_STATUS_PROBATION
    assert before["open_major_findings_count"] == 1
    assert before["open_minor_findings_count"] == 6

    renewed = validate_success(
        client.renew_certificate(
            certificate["id"],
            factories.renewal_payload(
                before["version"], renewal["id"], new_expires_on="2030-01-01"
            ),
            shop.admin,
        ),
        200,
    )
    assert renewed["status"] == CERT_STATUS_ACTIVE
    assert renewed["open_major_findings_count"] == 0
    assert renewed["open_minor_findings_count"] == 0
    assert renewed["renewal_count"] == 1
    assert renewed["expires_on"] == "2030-01-01"
    assert renewed["stamping_authorized"] is True
    assert renewed["version"] == before["version"] + 1

    replay = client.renew_certificate(
        certificate["id"],
        factories.renewal_payload(before["version"], renewal["id"], new_expires_on="2030-01-01"),
        shop.admin,
    )
    validate_error(replay, api_errors.ERR_STALE_CERTIFICATE_VERSION, 412)

    unchanged = shop.read_certificate(certificate["id"])
    assert unchanged["expires_on"] == "2030-01-01"
    assert unchanged["renewal_count"] == 1
    assert unchanged["status"] == CERT_STATUS_ACTIVE
    assert unchanged["version"] == renewed["version"]
