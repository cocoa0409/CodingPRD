"""Initial states, declared transitions, refused triggers and transition side effects."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import (
    assert_full_audit_fields,
    assert_number_equals,
)
from test_helpers.constants import (
    AUDIT_STATUS_CLOSED,
    AUDIT_STATUS_SCHEDULED,
    AUDIT_TYPE_INTERNAL_QMS,
    CALC_STATUS_APPROVED,
    CALC_STATUS_DRAFT,
    CALC_STATUS_SUPERSEDED,
    CERT_STATUS_ACTIVE,
    COMPONENT_HEAD,
    COMPONENT_SHELL,
    HEAT_STATUS_ACCEPTED,
    HEAT_STATUS_QUARANTINE,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_DESIGN_REVIEW,
    JOB_STATUS_DRAFT,
    JOB_STATUS_FAB_PLANNING,
    PART_STATUS_SCRAPPED,
    RT_EXTENT_FULL,
    RT_EXTENT_SPOT,
    SCRAP_REASON_JOB_CANCELLED,
    WPS_STATUS_DRAFT,
    WPS_STATUS_QUALIFIED,
)


def test_five_independently_created_records_each_open_on_their_own_initial_state(client, shop):
    """No creation call shortcuts a machine into a later posture.

    PRD §3.1: "A `ShopAdmin` schedules a quality-system audit against a certificate by supplying that certificate's `certificate_id`, an `audit_type` of `INTERNAL_QMS`, `JOINT_REVIEW` or `TRIENNIAL_RENEWAL`, and a `scheduled_date`; the audit opens at `status` `SCHEDULED` with `closed_on` null, `findings` an empty array, `major_finding_count` and `minor_finding_count` at 0 and `satisfactory` false."

    PRD §3.4: "The heat opens at `status` `QUARANTINE`, with `quantity_issued_lb` at 0.00 and `quantity_remaining_lb` equal to `quantity_received_lb`."

    Design: Corner/state_machines/state_machine_initial_states_are_assigned_on_create
    """
    certificate = shop.certificate(cert_number="CA-U-8906")

    audit = shop.audit(certificate["id"], audit_type=AUDIT_TYPE_INTERNAL_QMS, scheduled_date="2026-09-01")
    job = shop.job(certificate, job_number="J-2885-C21")
    heat = shop.heat(heat_number="H-5400", quantity_received_lb=2000.00)
    wps = shop.wps(wps_number="WPS-94")

    assert certificate["status"] == CERT_STATUS_ACTIVE
    assert certificate["renewal_count"] == 0
    assert_full_audit_fields(certificate, expected_version=1)

    assert audit["status"] == AUDIT_STATUS_SCHEDULED
    assert audit["closed_on"] is None
    assert audit["findings"] == []
    assert audit["major_finding_count"] == 0
    assert audit["minor_finding_count"] == 0
    assert audit["satisfactory"] is False
    assert_full_audit_fields(audit, expected_version=1)

    assert job["status"] == JOB_STATUS_DRAFT
    assert_full_audit_fields(job, expected_version=1)

    assert heat["status"] == HEAT_STATUS_QUARANTINE
    assert_number_equals(heat["quantity_issued_lb"], 0.00, 2, "quantity_issued_lb")
    assert_number_equals(heat["quantity_remaining_lb"], 2000.00, 2, "quantity_remaining_lb")
    assert_full_audit_fields(heat, expected_version=1)

    assert wps["status"] == WPS_STATUS_DRAFT
    assert_full_audit_fields(wps, expected_version=1)


def test_qualifying_a_drafted_procedure_advances_it_by_exactly_one_version(client, shop, admin_headers):
    """The one declared procedure transition lands and increments the row once.

    PRD §3.5: "Qualifying a procedure moves it `DRAFT → QUALIFIED` and requires that it currently be `DRAFT` — a second qualification draws `ERR_INVALID_WPS_STATE` — and that `supporting_pqr_number` be non-blank."

    PRD §2.4: "`version` is an integer that starts at 1 when the record is created and increments by exactly 1 on every mutation of that record, whether the mutation was requested directly by a client or applied by the server as a cascade from somewhere else."

    Design: Corner/state_machines/state_machine_wps_draft_to_qualified_on_qualify
    """
    engineer = shop.welding_engineer()
    drafted = shop.wps(wps_number="WPS-95", supporting_pqr_number="PQR-95")
    assert drafted["status"] == WPS_STATUS_DRAFT
    assert drafted["version"] == 1

    response = client.qualify_wps(drafted["id"], shop.acting_as(engineer))

    qualified = validate_success(response, 200)
    assert qualified["status"] == WPS_STATUS_QUALIFIED
    assert qualified["version"] == 2

    listed, meta = validate_paginated(
        client.list_wps(
            admin_headers, params={"status": WPS_STATUS_QUALIFIED, "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in listed] == [drafted["id"]]


def test_a_sheet_still_in_draft_cannot_be_approved(client, shop, admin_headers):
    """The independent-review step cannot be skipped over.

    PRD §2.8: "**Target state.** The record named in the path is in a state from which the requested transition is declared — otherwise the matching 409: `ERR_INVALID_JOB_STATE`, `ERR_INVALID_CALCULATION_STATE`, `ERR_INVALID_HEAT_STATE`, `ERR_INVALID_PART_STATE`, `ERR_INVALID_WPS_STATE`, `ERR_INVALID_WELD_STATE`, `ERR_INVALID_EXAM_STATE`, `ERR_INVALID_NONCONFORMANCE_STATE`, `ERR_INVALID_BATCH_STATE`, `ERR_INVALID_TEST_STATE`, `ERR_INVALID_REPORT_STATE`, `ERR_INVALID_AUDIT_STATE` or `ERR_INVALID_CERTIFICATE_STATE`."

    PRD §3.3: "Approval moves the sheet `SUBMITTED → APPROVED` and requires that the acting `X-User-ID` differ from the sheet's `prepared_by_personnel_id`; the same engineer approving their own arithmetic is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/state_machine_approve_precondition_requires_submitted_calculation
    """
    reviewer = shop.reviewing_design_engineer()
    job = shop.job(job_number="J-2885-C23", mawp_psi=350, inside_radius_in=30)
    sheet = shop.prepare_sheet(
        job["id"],
        COMPONENT_SHELL,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.7500,
    )

    response = client.approve_calculation(sheet["id"], shop.acting_as(reviewer))

    validate_error(response, api_errors.ERR_INVALID_CALCULATION_STATE, 409)
    unchanged = validate_success(client.get_calculation(sheet["id"], admin_headers), 200)
    assert unchanged["status"] == CALC_STATUS_DRAFT
    assert unchanged["reviewed_by_personnel_id"] is None
    parent = shop.read_job(job["id"])
    assert parent["status"] == JOB_STATUS_DRAFT
    assert parent["governing_joint_efficiency"] is None
    assert parent["design_release_at"] is None


def test_qualifying_the_same_procedure_twice_is_refused_rather_than_replayed(client, shop):
    """Qualification is not idempotent and the replay leaves no phantom version.

    PRD §3.5: "Qualifying a procedure moves it `DRAFT → QUALIFIED` and requires that it currently be `DRAFT` — a second qualification draws `ERR_INVALID_WPS_STATE` — and that `supporting_pqr_number` be non-blank."

    Design: Corner/state_machines/state_machine_second_qualify_on_same_wps_is_refused
    """
    engineer = shop.welding_engineer()
    qualified = shop.qualified_wps(
        wps_number="WPS-96",
        process="SAW",
        thickness_min_in=0.2500,
        thickness_max_in=4.0000,
        supporting_pqr_number="PQR-96",
    )
    assert qualified["status"] == WPS_STATUS_QUALIFIED
    assert qualified["version"] == 2

    response = client.qualify_wps(qualified["id"], shop.acting_as(engineer))

    validate_error(response, api_errors.ERR_INVALID_WPS_STATE, 409)
    after = validate_success(client.get_wps(qualified["id"], shop.admin), 200)
    assert after["status"] == WPS_STATUS_QUALIFIED
    assert after["version"] == 2


def test_a_closed_audit_cannot_absorb_a_second_set_of_findings(client, shop):
    """CLOSED is terminal, so the refused replay injects nothing into the certificate.

    PRD §3.1: "`satisfactory` becomes true only when the audit is `CLOSED`, its `major_finding_count` is 0 and its `minor_finding_count` is 5 or fewer, and `CLOSED` is terminal for an audit."

    Design: Corner/state_machines/state_machine_closed_audit_is_terminal_and_cannot_be_closed_again
    """
    certificate = shop.certificate(cert_number="CA-U-8909")
    audit = shop.audit(certificate["id"], scheduled_date="2026-09-01")
    shop.close_audit(audit["id"], closed_on="2026-09-15")

    replay = client.close_audit(
        audit["id"],
        factories.audit_close_payload(closed_on="2026-09-16", major=1),
        shop.admin,
    )

    validate_error(replay, api_errors.ERR_INVALID_AUDIT_STATE, 409)
    closed = validate_success(client.get_audit(audit["id"], shop.admin), 200)
    assert closed["status"] == AUDIT_STATUS_CLOSED
    assert closed["closed_on"] == "2026-09-15"
    assert closed["findings"] == []
    assert closed["major_finding_count"] == 0
    assert closed["minor_finding_count"] == 0
    assert closed["satisfactory"] is True
    licence = shop.read_certificate(certificate["id"])
    assert licence["status"] == CERT_STATUS_ACTIVE
    assert licence["open_major_findings_count"] == 0
    assert licence["stamping_authorized"] is True


def test_lifecycle_triggers_aimed_at_a_draft_job_are_all_refused(client, shop, admin_headers):
    """Part issue, weld-map release and the examination plan all need a later posture.

    PRD §2.8: "The required parent job state, gathered in one place: calculation submit needs the job in `DRAFT` or `DESIGN_REVIEW`; calculation revise needs `DRAFT`; part issue and part scrap need `FAB_PLANNING`, `FABRICATION` or `NDE_HOLD`; weld-map entry creation needs `FAB_PLANNING` or `FABRICATION`; weld completion needs `FABRICATION`, or `NDE_HOLD` when the joint is a repair joint whose covering nonconformance is dispositioned `REPAIR`; running the examination plan needs `FABRICATION` or `NDE_HOLD`; scheduling, starting and completing a furnace charge each need `FABRICATION` or `NDE_HOLD`; scheduling a pressure test needs `FABRICATION` or `TESTING`; recording a test result needs `TESTING`; dispositioning a nonconformance and creating its repair joint each need `NDE_HOLD`; and assembling a data report needs only that the job is neither `STAMPED` nor `CANCELLED`, so a partial package may be assembled and scored at any point during fabrication."

    Design: Corner/state_machines/state_machine_triggers_absent_from_draft_job_transition_list_are_refused
    """
    welding_engineer = shop.welding_engineer()
    inspector = shop.qc_inspector()
    job = shop.job(job_number="J-2885-C24")
    heat = shop.accepted_heat(heat_number="H-5450", quantity_received_lb=2000.00)
    version_after_creation = shop.read_job(job["id"])["version"]

    part_issue = client.issue_part(
        job["id"],
        factories.part_payload(heat["id"], part_mark="SH-01", issued_quantity_lb=1200.00),
        shop.acting_as(welding_engineer),
    )
    map_release = client.release_weld_map(job["id"], shop.acting_as(welding_engineer))
    nde_plan = client.run_nde_plan(job["id"], shop.acting_as(inspector))

    for response in (part_issue, map_release, nde_plan):
        assert response.status_code == 409
        validate_error(response, api_errors.ERR_INVALID_JOB_STATE, 409)

    unchanged = shop.read_job(job["id"])
    assert unchanged["status"] == JOB_STATUS_DRAFT
    assert unchanged["version"] == version_after_creation
    ledger = shop.read_heat(heat["id"])
    assert_number_equals(ledger["quantity_remaining_lb"], 2000.00, 2, "quantity_remaining_lb")
    _, meta = validate_paginated(
        client.list_parts(admin_headers, params={"job_id": job["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0


def test_only_the_last_required_component_releases_the_job_for_fabrication(client, shop, admin_headers):
    """Approving the final sheet stamps the release instant and takes the smallest efficiency.

    PRD §3.3: "On approval the reviewer's identity is written to `reviewed_by_personnel_id`, the job's `governing_joint_efficiency` is recomputed as the smallest `joint_efficiency` across the job's approved sheets, and — once **every** component listed in the job's `required_components` carries exactly one `APPROVED` sheet — the job moves `DESIGN_REVIEW → FAB_PLANNING` with `design_release_at` stamped to the current logical UTC instant."

    Design: Corner/state_machines/state_machine_final_approval_side_effects_release_the_job
    """
    preparer = shop.design_engineer()
    reviewer = shop.reviewing_design_engineer()
    job = shop.job(job_number="J-2885-C25", mawp_psi=350, inside_radius_in=30)
    shell = shop.prepare_sheet(
        job["id"],
        COMPONENT_SHELL,
        preparer=preparer,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.7500,
    )
    head = shop.prepare_sheet(
        job["id"],
        COMPONENT_HEAD,
        preparer=preparer,
        rt_extent_declared=RT_EXTENT_SPOT,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.7500,
    )
    shop.submit_sheet(shell["id"], preparer=preparer)
    shop.submit_sheet(head["id"], preparer=preparer)

    shop.approve_sheet(shell["id"], reviewer=reviewer)
    midway = shop.read_job(job["id"])
    shop.approve_sheet(head["id"], reviewer=reviewer)

    assert midway["status"] == JOB_STATUS_DESIGN_REVIEW
    assert_number_equals(midway["governing_joint_efficiency"], 1.00, 2, "governing_joint_efficiency")
    assert midway["design_release_at"] is None

    released = shop.read_job(job["id"])
    assert released["status"] == JOB_STATUS_FAB_PLANNING
    assert released["design_release_at"] == "2026-08-01T00:00:00.000Z"
    assert_number_equals(released["governing_joint_efficiency"], 0.85, 2, "governing_joint_efficiency")

    shell_sheet = validate_success(client.get_calculation(shell["id"], admin_headers), 200)
    assert shell_sheet["status"] == CALC_STATUS_APPROVED
    assert_number_equals(shell_sheet["joint_efficiency"], 1.00, 2, "joint_efficiency")
    assert_number_equals(shell_sheet["thickness_required_in"], 0.5931, 4, "thickness_required_in")
    assert shell_sheet["reviewed_by_personnel_id"] == reviewer["id"]
    assert shell_sheet["revision"] == 1

    head_sheet = validate_success(client.get_calculation(head["id"], admin_headers), 200)
    assert head_sheet["status"] == CALC_STATUS_APPROVED
    assert_number_equals(head_sheet["joint_efficiency"], 0.85, 2, "joint_efficiency")
    assert_number_equals(head_sheet["thickness_required_in"], 0.6879, 4, "thickness_required_in")
    assert head_sheet["reviewed_by_personnel_id"] == reviewer["id"]
    assert head_sheet["revision"] == 1


def test_cancelling_a_released_job_unwinds_sheets_parts_and_the_heat_ledger(client, shop, admin_headers):
    """One cancel reaches the sheets, the piece and the sibling heat in a single request.

    PRD §3.2: "The effect set is identical from every one of those seven origins, and it unwinds the whole aggregate in one request: every calculation sheet of the job in `DRAFT`, `SUBMITTED` or `APPROVED` becomes `SUPERSEDED`; every part of the job still `ISSUED` becomes `SCRAPPED` with its `scrap_reason` recorded as `JOB_CANCELLED`, returning its `issued_quantity_lb` to the heat it was cut from so that the heat's mass ledger is restored and a `DEPLETED` heat lifts back to `ACCEPTED`; every furnace charge of the job in `SCHEDULED` or `IN_PROGRESS` becomes `ABORTED`, which clears `pwht_batch_id` on its joints and returns their `pwht_status` to `PENDING`; every nonconformance of the job whose `disposition` is `OPEN`, `REPAIR` or `USE_AS_IS` becomes `CLOSED` with `closed_at` set to the current logical UTC instant; every data report of the job in `ASSEMBLING`, `READY_FOR_AI`, `AI_SIGNED` or `STAMP_HOLD` becomes `VOIDED`; `nonconformance_open_count` is recomputed to 0; and the job's own `version` increments."

    Design: Corner/state_machines/state_machine_cancel_cascades_down_to_sheets_parts_and_heat_ledger
    """
    job = shop.job(job_number="J-2885-C26", mawp_psi=350, inside_radius_in=30)
    sheets = shop.release_design(
        job,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.7500,
    )
    heat = shop.accepted_heat(heat_number="H-5500", quantity_received_lb=2000.00)
    part = shop.issue_part(
        job["id"], heat["id"], part_mark="SH-01", issued_quantity_lb=2000.00
    )

    cancelled = shop.cancel_job(job["id"], cancel_reason="Customer withdrew the order after design release")

    assert cancelled["status"] == JOB_STATUS_CANCELLED
    assert cancelled["nonconformance_open_count"] == 0
    for component in (COMPONENT_SHELL, COMPONENT_HEAD):
        sheet = validate_success(client.get_calculation(sheets[component]["id"], admin_headers), 200)
        assert sheet["status"] == CALC_STATUS_SUPERSEDED

    scrapped = validate_success(client.get_part(part["id"], admin_headers), 200)
    assert scrapped["status"] == PART_STATUS_SCRAPPED
    assert scrapped["scrap_reason"] == SCRAP_REASON_JOB_CANCELLED

    ledger = shop.read_heat(heat["id"])
    assert_number_equals(ledger["quantity_issued_lb"], 0.00, 2, "quantity_issued_lb")
    assert_number_equals(ledger["quantity_remaining_lb"], 2000.00, 2, "quantity_remaining_lb")
    assert ledger["status"] == HEAT_STATUS_ACCEPTED
    assert_number_equals(
        ledger["quantity_received_lb"],
        float(ledger["quantity_remaining_lb"]) + float(ledger["quantity_issued_lb"]),
        2,
        "quantity_received_lb",
    )

    _, meta = validate_paginated(
        client.list_parts(
            admin_headers,
            params={
                "job_id": job["id"],
                "status": PART_STATUS_SCRAPPED,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
