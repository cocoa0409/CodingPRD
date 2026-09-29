"""Endpoint surfaces driven end to end: CRUD, action, cross-reference link and computed read."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    AUDIT_STATUS_CLOSED,
    AUDIT_TYPE_INTERNAL_QMS,
    CERT_STATUS_PROBATION,
    FAB_STATUS_PLANNED,
    HEAT_STATUS_QUARANTINE,
    HEAT_STATUS_REJECTED,
    JOB_STATUS_FABRICATION,
    JOB_STATUS_FAB_PLANNING,
    JOINT_CATEGORY_A,
    JOINT_TYPE_BUTT,
    NDE_STATUS_NOT_PLANNED,
    POSITIONS,
    PWHT_STATUS_NOT_REQUIRED,
    QUALIFICATION_STATUS_QUALIFIED,
    RT_EXTENT_FULL,
    SPEC_SA_240_304L,
    SPEC_SA_516_70,
    UNKNOWN_UUID,
)


def test_a_material_heat_is_created_read_listed_then_rejected_into_its_terminal_state(
    client, shop, admin_headers
):
    """Receiving inspection is exercised over one heat: create, read back, filtered list, terminal reject.

    PRD §3.4: "The heat opens at `status` `QUARANTINE`, with `quantity_issued_lb` at 0.00 and `quantity_remaining_lb` equal to `quantity_received_lb`."

    PRD §3.4: "A `REJECT` decision requires a non-blank `reason` and moves the heat `QUARANTINE → REJECTED`, which is terminal."

    Design: Corner/endpoints/endpoint_standard_crud_on_material_heats_through_terminal_rejection
    """
    inspector = shop.qc_inspector()

    created = validate_success(
        client.create_heat(
            factories.material_heat_payload(
                heat_number="H-6200",
                spec=SPEC_SA_240_304L,
                yield_ksi=30.0,
                tensile_ksi=75.0,
                quantity_received_lb=900.5,
            ),
            shop.acting_as(inspector),
        ),
        201,
    )
    assert created["version"] == 1
    assert created["status"] == HEAT_STATUS_QUARANTINE
    assert created["material_class"] == "AUSTENITIC"
    assert created["p_number"] == 8
    assert_number_equals(created["quantity_issued_lb"], 0.00, 2, "quantity_issued_lb")
    assert_number_equals(created["quantity_remaining_lb"], 900.50, 2, "quantity_remaining_lb")

    read_back = validate_success(client.get_heat(created["id"], admin_headers), 200)
    assert read_back["heat_number"] == "H-6200"
    assert_number_equals(read_back["quantity_received_lb"], 900.50, 2, "quantity_received_lb")
    assert read_back == created

    listed, meta = validate_paginated(
        client.list_heats(
            admin_headers,
            params={
                "status": HEAT_STATUS_QUARANTINE,
                "spec": SPEC_SA_240_304L,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in listed] == [created["id"]]

    rejected = validate_success(
        client.review_heat(
            created["id"],
            factories.mtr_review_payload(
                "REJECT", reason="Laminar indication found on ultrasonic scan of plate edge"
            ),
            shop.acting_as(inspector),
        ),
        200,
    )
    assert rejected["status"] == HEAT_STATUS_REJECTED
    assert rejected["version"] == 2

    _, quarantine_meta = validate_paginated(
        client.list_heats(
            admin_headers,
            params={"status": HEAT_STATUS_QUARANTINE, "limit": 10, "offset": 0},
        )
    )
    assert quarantine_meta["total_count"] == 0

    still_listed, rejected_meta = validate_paginated(
        client.list_heats(
            admin_headers, params={"status": HEAT_STATUS_REJECTED, "limit": 10, "offset": 0}
        )
    )
    assert rejected_meta["total_count"] == 1
    assert [row["id"] for row in still_listed] == [created["id"]]


def test_weld_map_release_refuses_an_empty_map_performs_once_then_refuses_the_replay(client, shop):
    """One action endpoint is driven through refusal, performance and replay refusal in a single history.

    PRD §3.5: "The job must have at least one planned joint, or the release draws `ERR_EMPTY_WELD_MAP`."

    PRD §2.8: "**Target state.** The record named in the path is in a state from which the requested transition is declared — otherwise the matching 409: `ERR_INVALID_JOB_STATE`, `ERR_INVALID_CALCULATION_STATE`, `ERR_INVALID_HEAT_STATE`, `ERR_INVALID_PART_STATE`, `ERR_INVALID_WPS_STATE`, `ERR_INVALID_WELD_STATE`, `ERR_INVALID_EXAM_STATE`, `ERR_INVALID_NONCONFORMANCE_STATE`, `ERR_INVALID_BATCH_STATE`, `ERR_INVALID_TEST_STATE`, `ERR_INVALID_REPORT_STATE`, `ERR_INVALID_AUDIT_STATE` or `ERR_INVALID_CERTIFICATE_STATE`."

    PRD §3.6: "For a Category A joint, a `FULL` declaration gives 100, a `SPOT` declaration gives 25 and a `NONE` declaration gives 0."

    Design: Corner/endpoints/endpoint_action_weld_map_release_enforces_then_performs_then_refuses
    """
    engineer = shop.welding_engineer()
    job = shop.job(job_number="J-2885-C40", mawp_psi=350)
    shop.release_design(job, rt_extent_declared=RT_EXTENT_FULL)

    planning = shop.read_job(job["id"])
    assert planning["status"] == JOB_STATUS_FAB_PLANNING
    assert_number_equals(planning["governing_joint_efficiency"], 1.00, 2, "governing_joint_efficiency")

    empty_release = client.release_weld_map(job["id"], shop.acting_as(engineer))
    validate_error(empty_release, api_errors.ERR_EMPTY_WELD_MAP, 409)
    assert shop.read_job(job["id"])["status"] == JOB_STATUS_FAB_PLANNING

    heat = shop.accepted_heat(heat_number="H-6300", spec=SPEC_SA_516_70, quantity_received_lb=2000.00)
    part = shop.issue_part(
        job["id"], heat["id"], part_mark="SH-01", issued_quantity_lb=1200.00
    )
    procedure = shop.qualified_wps(wps_number="WPS-110")
    joint = shop.plan_joint(
        job["id"],
        procedure["id"],
        part["id"],
        weld_number="W-001",
        joint_category=JOINT_CATEGORY_A,
        joint_type=JOINT_TYPE_BUTT,
        thickness_in=0.7500,
    )

    version_before = shop.job_version(job["id"])
    released = validate_success(
        client.release_weld_map(job["id"], shop.acting_as(engineer)), 200
    )
    assert released["status"] == JOB_STATUS_FABRICATION
    assert released["version"] == version_before + 1
    assert released["design_release_at"] is not None
    assert_number_equals(released["weld_completion_pct"], 0.00, 2, "weld_completion_pct")

    untouched = shop.read_joint(joint["id"])
    assert untouched["fab_status"] == FAB_STATUS_PLANNED
    assert untouched["nde_status"] == NDE_STATUS_NOT_PLANNED
    assert untouched["pwht_status"] == PWHT_STATUS_NOT_REQUIRED
    assert untouched["required_volumetric_pct"] == 100

    replay = client.release_weld_map(job["id"], shop.acting_as(engineer))
    validate_error(replay, api_errors.ERR_INVALID_JOB_STATE, 409)
    assert shop.read_job(job["id"])["status"] == JOB_STATUS_FABRICATION


def test_a_welder_qualification_links_to_an_existing_procedure_and_then_updates_in_place(
    client, shop, admin_headers
):
    """The link row demands a live procedure, is queryable from the procedure side, and a continuity log updates it rather than adding a row.

    PRD §2.8: "**Body-reference existence.** Every identifier carried in the request body resolves to a live row, validated in the field order the endpoint declares — `certificate_id`, then `heat_id`, then `wps_id`, then `welder_qualification_id`, then `part_a_id`, then `part_b_id`, then `repair_of_weld_id`, then the entries of `weld_ids` — otherwise `ERR_CERTIFICATE_NOT_FOUND`, `ERR_HEAT_NOT_FOUND`, `ERR_WPS_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_PART_NOT_FOUND` or `ERR_WELD_NOT_FOUND` (404)."

    PRD §3.5: "On creation `last_continuity_date` is initialised to `qualified_on`."

    PRD §3.5: "`days_since_continuity` is the whole number of days from `last_continuity_date` to the current logical UTC date."

    PRD §3.5: "A successful log sets `last_continuity_date` to `continuity_date`, re-derives `days_since_continuity` and `status`, and increments the qualification's `version`."

    Design: Corner/endpoints/endpoint_cross_reference_link_binds_welder_qualification_to_procedure
    """
    engineer = shop.welding_engineer()
    procedure = shop.qualified_wps(wps_number="WPS-120")

    dangling = client.create_welder_qualification(
        factories.welder_qualification_payload(
            UNKNOWN_UUID,
            welder_stamp="W-77",
            welder_name="Ola Beck",
            position_qualified=POSITIONS[0],
            thickness_range_max_in=1.5000,
            qualified_on="2026-06-01",
        ),
        shop.acting_as(engineer),
    )
    validate_error(dangling, api_errors.ERR_WPS_NOT_FOUND, 404)

    _, empty_meta = validate_paginated(
        client.list_welder_qualifications(admin_headers, params={"limit": 10, "offset": 0})
    )
    assert empty_meta["total_count"] == 0

    created = validate_success(
        client.create_welder_qualification(
            factories.welder_qualification_payload(
                procedure["id"],
                welder_stamp="W-77",
                welder_name="Ola Beck",
                position_qualified=POSITIONS[0],
                thickness_range_max_in=1.5000,
                qualified_on="2026-06-01",
            ),
            shop.acting_as(engineer),
        ),
        201,
    )
    assert created["version"] == 1
    assert created["status"] == QUALIFICATION_STATUS_QUALIFIED
    assert created["last_continuity_date"] == "2026-06-01"
    assert created["days_since_continuity"] == 61

    from_procedure_side, link_meta = validate_paginated(
        client.list_welder_qualifications(
            admin_headers, params={"wps_id": procedure["id"], "limit": 10, "offset": 0}
        )
    )
    assert link_meta["total_count"] == 1
    assert [row["id"] for row in from_procedure_side] == [created["id"]]

    logged = validate_success(
        client.log_continuity(
            created["id"],
            factories.continuity_log_payload("2026-07-15"),
            shop.acting_as(engineer),
        ),
        200,
    )
    assert logged["version"] == 2
    assert logged["last_continuity_date"] == "2026-07-15"
    assert logged["days_since_continuity"] == 17
    assert logged["status"] == QUALIFICATION_STATUS_QUALIFIED

    rows, after_meta = validate_paginated(
        client.list_welder_qualifications(admin_headers, params={"limit": 10, "offset": 0})
    )
    assert after_meta["total_count"] == 1
    assert [row["id"] for row in rows] == [created["id"]]


def test_audit_counters_are_read_back_straight_from_the_posted_findings_array(
    client, shop, admin_headers
):
    """Observations count in neither bucket, one major already forfeits `satisfactory`, and two majors land the licence on probation.

    PRD §3.1: "On close, `major_finding_count` becomes the number of findings whose `severity` is `MAJOR` and `minor_finding_count` the number whose `severity` is `MINOR`; findings recorded as `OBSERVATION` are counted in neither."

    PRD §3.1: "`satisfactory` becomes true only when the audit is `CLOSED`, its `major_finding_count` is 0 and its `minor_finding_count` is 5 or fewer, and `CLOSED` is terminal for an audit."

    PRD §3.1: "The certificate adds this audit's `major_finding_count` to its own `open_major_findings_count` and this audit's `minor_finding_count` to its own `open_minor_findings_count`, sets `last_audit_closed_on` to the audit's `closed_on`, re-derives `status` and `stamping_authorized` from the new counters, and increments its `version`."

    PRD §3.1: "`stamping_authorized` is true only when `status` is `ACTIVE`, `expires_on` is on or after the current logical UTC date, and `open_major_findings_count` is exactly 0 — it is the single flag every witness, signature and nameplate attempt consults."

    Design: Corner/endpoints/endpoint_computed_read_audit_counters_derived_from_findings_array
    """
    certificate = shop.certificate(cert_number="CA-U-8925")
    audit = validate_success(
        client.create_audit(
            factories.audit_payload(
                certificate["id"],
                audit_type=AUDIT_TYPE_INTERNAL_QMS,
                scheduled_date="2026-06-01",
            ),
            admin_headers,
        ),
        201,
    )

    posted_findings = [
        {"finding_code": "F-01", "severity": "MAJOR", "clause_reference": "QW-201"},
        {"finding_code": "F-02", "severity": "MAJOR", "clause_reference": "QW-322"},
        {"finding_code": "F-03", "severity": "MINOR", "clause_reference": "UG-90"},
        {"finding_code": "F-04", "severity": "OBSERVATION", "clause_reference": "UG-116"},
        {"finding_code": "F-05", "severity": "OBSERVATION", "clause_reference": "UW-51"},
    ]
    closed = validate_success(
        client.close_audit(
            audit["id"],
            factories.audit_close_payload(closed_on="2026-06-15", findings=posted_findings),
            admin_headers,
        ),
        200,
    )
    assert closed["status"] == AUDIT_STATUS_CLOSED
    assert closed["version"] == 2

    read_back = validate_success(client.get_audit(audit["id"], admin_headers), 200)
    assert read_back["major_finding_count"] == 2
    assert read_back["minor_finding_count"] == 1
    assert read_back["satisfactory"] is False
    assert [
        (row["finding_code"], row["severity"], row["clause_reference"])
        for row in read_back["findings"]
    ] == [
        (row["finding_code"], row["severity"], row["clause_reference"]) for row in posted_findings
    ]

    reconciled = validate_success(
        client.get_certificate(certificate["id"], admin_headers), 200
    )
    assert reconciled["open_major_findings_count"] == 2
    assert reconciled["open_minor_findings_count"] == 1
    assert reconciled["status"] == CERT_STATUS_PROBATION
    assert reconciled["stamping_authorized"] is False
    assert reconciled["last_audit_closed_on"] == "2026-06-15"
