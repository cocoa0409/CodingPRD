"""Construction milestones: evidence, segregation of duties, sequencing, the
rejection loop, and project commissioning/COD gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    build_under_construction_project,
    certify_milestone,
    create_effective_offtake,
    create_milestone_payload,
    create_project,
    development_project,
    get_success_data,
    make_construction_manager_headers,
    make_tax_counsel_headers,
    site_secured_project,
    validate_error,
    validate_success,
)


def test_certifier_must_differ_from_submitter(
    api, developer_admin_headers, construction_manager_headers, tax_counsel_headers
):
    """PRD §3.6: "In either direction the certifier's `X-User-ID` must differ
    from the milestone's `submitted_by_user_id` — self-certification fails with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 409) — and the certifier's id is recorded
    as `certified_by_user_id`."

    Design: Corner/state_machines/certifier_must_differ_from_submitter
    """
    project = create_project(name="SoD Farm", technology="SOLAR", target_capacity_mw=35,
                             resource_class="B")
    milestone = get_success_data(
        api.create_milestone(
            project["id"],
            create_milestone_payload(milestone_type="FOUNDATION", sequence_no=1),
            construction_manager_headers,
        )
    )
    # Submitter id "shared_1".
    get_success_data(
        api.submit_milestone_evidence(
            milestone["id"],
            {"evidence_uri": "s3://ev/sod", "work_date": "2027-03-01T00:00:00Z"},
            make_construction_manager_headers("shared_1"),
        )
    )
    # Certifier id "shared_1" (a TaxCounsel role, same person): refused.
    resp = api.certify_milestone(
        milestone["id"], {"decision": "CERTIFIED"},
        make_tax_counsel_headers("shared_1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    current = get_success_data(
        api.get_milestone(milestone["id"], tax_counsel_headers)
    )
    assert current["status"] == "EVIDENCE_SUBMITTED"


def test_milestone_out_of_order_certification(
    api, developer_admin_headers, construction_manager_headers, tax_counsel_headers
):
    """PRD §3.6: "Certification (`decision` of `CERTIFIED`) additionally
    requires that every other milestone of the same project with a
    `sequence_no` lower than this milestone's is already `CERTIFIED`, failing
    with `ERR_MILESTONE_OUT_OF_ORDER` (HTTP 409) when an earlier sequence
    number is still open".

    Design: Corner/state_machines/milestone_out_of_order_certification
    """
    project = create_project(name="Seq Farm", target_capacity_mw=45)
    cm = make_construction_manager_headers("cm-1")
    tc = make_tax_counsel_headers("tc-1")
    m1 = get_success_data(
        api.create_milestone(
            project["id"],
            create_milestone_payload(milestone_type="FOUNDATION", sequence_no=1),
            cm,
        )
    )
    get_success_data(
        api.submit_milestone_evidence(
            m1["id"], {"evidence_uri": "s3://ev/s1", "work_date": "2027-03-01T00:00:00Z"}, cm
        )
    )
    m2 = get_success_data(
        api.create_milestone(
            project["id"],
            create_milestone_payload(milestone_type="ERECTION", sequence_no=2,
                                     planned_date="2027-05-01T00:00:00Z"),
            cm,
        )
    )
    get_success_data(
        api.submit_milestone_evidence(
            m2["id"], {"evidence_uri": "s3://ev/s2", "work_date": "2027-05-01T00:00:00Z"}, cm
        )
    )
    # seq 1 is still EVIDENCE_SUBMITTED: certifying seq 2 is out of order.
    resp = api.certify_milestone(m2["id"], {"decision": "CERTIFIED"}, tc)
    validate_error(resp, ApiErrorId.ERR_MILESTONE_OUT_OF_ORDER)
    current = get_success_data(api.get_milestone(m2["id"], tc))
    assert current["status"] == "EVIDENCE_SUBMITTED"


def test_milestone_rejection_resubmission_cycle(
    api, developer_admin_headers, construction_manager_headers, tax_counsel_headers
):
    """PRD §3.6: "A milestone whose evidence was rejected may be resubmitted
    along the same path, replacing the `evidence_uri` and `work_date` and
    re-stamping `submitted_by_user_id`." Also: "`REJECTED` loops back through
    resubmission."

    Design: Corner/state_machines/milestone_rejection_resubmission_cycle
    """
    project = create_project(name="Reject Farm", target_capacity_mw=45)
    cm = make_construction_manager_headers("cm-1")
    tc = make_tax_counsel_headers("tc-1")
    m1 = get_success_data(
        api.create_milestone(
            project["id"],
            create_milestone_payload(milestone_type="FOUNDATION", sequence_no=1),
            cm,
        )
    )
    get_success_data(
        api.submit_milestone_evidence(
            m1["id"], {"evidence_uri": "s3://ev/r1-bad", "work_date": "2027-03-01T00:00:00Z"}, cm
        )
    )
    rejected = get_success_data(
        api.certify_milestone(m1["id"], {"decision": "REJECTED"}, tc)
    )
    assert rejected["status"] == "REJECTED"
    get_success_data(
        api.submit_milestone_evidence(
            m1["id"], {"evidence_uri": "s3://ev/r1-good", "work_date": "2027-03-02T00:00:00Z"}, cm
        )
    )
    certified = get_success_data(
        api.certify_milestone(m1["id"], {"decision": "CERTIFIED"}, tc)
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["evidence_uri"] == "s3://ev/r1-good"


def test_ready_for_construction_requires_effective_offtake(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.1: "or advance to `READY_FOR_CONSTRUCTION`, which is gated on two
    cross-entity conditions — at least one offtake agreement of the project in
    `EFFECTIVE` status (otherwise `ERR_OFFTAKE_REQUIRED`, HTTP 409) and at
    least one interconnection request in `AGREEMENT_EXECUTED` or `IN_SERVICE`
    (otherwise `ERR_INTERCONNECTION_NOT_EXECUTED`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ready_for_construction_requires_effective_offtake
    """
    project = create_project(name="Gate Farm", target_capacity_mw=90)
    pid = project["id"]
    site_secured_project(pid, parcel_id="PCL-G1")
    development_project(pid, "CL-G", 90)
    # Offtake EXECUTED but not EFFECTIVE.
    version = get_success_data(api.get_project(pid, developer_admin_headers))["version"]
    agreement = validate_success(
        api.create_offtake_agreement(
            pid,
            {"buyer_type": "UTILITY", "base_price_usd_mwh": 44.00,
             "escalator_pct": 2.0, "term_years": 20,
             "delivery_start_date": "2028-01-01T00:00:00Z",
             "expected_project_version": version},
            origination_manager_headers,
        ),
        expected_status=201,
    )
    get_success_data(
        api.transition_offtake_agreement(agreement["id"], {"to": "EXECUTED"},
                                         origination_manager_headers)
    )
    resp = api.transition_project(pid, {"to": "READY_FOR_CONSTRUCTION"},
                                  developer_admin_headers)
    validate_error(resp, ApiErrorId.ERR_OFFTAKE_REQUIRED)
    # Once the offtake reaches EFFECTIVE, the identical transition succeeds.
    get_success_data(
        api.transition_offtake_agreement(agreement["id"], {"to": "EFFECTIVE"},
                                         origination_manager_headers)
    )
    advanced = get_success_data(
        api.transition_project(pid, {"to": "READY_FOR_CONSTRUCTION"},
                               developer_admin_headers)
    )
    assert advanced["status"] == "READY_FOR_CONSTRUCTION"


def test_ready_for_construction_requires_executed_interconnection(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.1: "at least one interconnection request in `AGREEMENT_EXECUTED`
    or `IN_SERVICE` (otherwise `ERR_INTERCONNECTION_NOT_EXECUTED`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ready_for_construction_requires_effective_offtake
    """
    project = create_project(name="Gate Farm 2", target_capacity_mw=90)
    pid = project["id"]
    site_secured_project(pid, parcel_id="PCL-G2")
    # Interconnection request exists but never leaves QUEUED.
    from test_helpers import create_interconnection_request, transition_project
    create_interconnection_request(pid, "CL-G2", 90)
    transition_project(pid, "DEVELOPMENT")
    create_effective_offtake(pid)
    resp = api.transition_project(pid, {"to": "READY_FOR_CONSTRUCTION"},
                                  developer_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INTERCONNECTION_NOT_EXECUTED)


def test_commissioning_gate_requires_all_four_milestones(
    api, developer_admin_headers
):
    """PRD §3.6: "The advance from `UNDER_CONSTRUCTION` to `COMMISSIONING`
    requires that milestones of all four types `FOUNDATION`, `ERECTION`,
    `ENERGIZATION`, and `SUBSTANTIAL_COMPLETION` exist and are `CERTIFIED`,
    failing with `ERR_COD_MILESTONE_PREREQUISITE` otherwise."

    Design: Corner/state_machines/commissioning_gate_requires_all_four_milestones
    """
    project, req, offtake, sa, order, tcq = build_under_construction_project(
        "Comm Gate Farm", "CL-CM", 60,
        order_overrides={
            "order_amount_usd": 4000000,
            "safe_harbor_method": "PHYSICAL_WORK",
            "eligible_cost_basis_usd": 4000000,
            "deposit_usd": 50000.00,
            "physical_work_evidence_uri": "s3://ev/pwt",
        },
    )
    pid = project["id"]
    # Only FOUNDATION certified; ERECTION/ENERGIZATION/SUBSTANTIAL_COMPLETION missing.
    certify_milestone(pid, 1, "FOUNDATION")
    resp = api.transition_project(pid, {"to": "COMMISSIONING"}, developer_admin_headers)
    validate_error(resp, ApiErrorId.ERR_COD_MILESTONE_PREREQUISITE)
    current = get_success_data(api.get_project(pid, developer_admin_headers))
    assert current["status"] == "UNDER_CONSTRUCTION"


def test_direct_project_cod_transition_rejected(api, developer_admin_headers):
    """PRD §3.6: "The step from `COMMISSIONING` to `COMMERCIAL_OPERATION` is
    cascade-only: there is no direct project transition for it, and a direct
    attempt fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/direct_project_cod_transition_rejected
    """
    from test_helpers import certify_four_prerequisite_milestones, transition_project
    project, req, offtake, sa, order, tcq = build_under_construction_project(
        "COD Gate Farm", "CL-CG", 200,
    )
    pid = project["id"]
    certify_four_prerequisite_milestones(pid)
    transition_project(pid, "COMMISSIONING")
    resp = api.transition_project(pid, {"to": "COMMERCIAL_OPERATION"},
                                  developer_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api.get_project(pid, developer_admin_headers))
    assert current["status"] == "COMMISSIONING"
