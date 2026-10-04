"""Difficulty depth index: transitive cascades — one adjudication propagating
through warranty, qualification and an unrelated work order; and a superseding
specification issuance cascading onto the incumbent's dependents.
"""
from test_helpers import (
    PROBATION_PENALTY,
    ApiClient,
    adjudicate,
    assert_cents,
    assert_score,
    begin_evidence,
    certify_qualification,
    claim_warranty,
    create_coating_system,
    create_program,
    create_project,
    create_specification,
    create_substitution_request,
    create_work_order,
    create_world,
    drive_to_completed_work_order,
    enroll_qualification,
    issue_specification,
    issue_warranty,
    read_applicator,
    read_investigation,
    read_project,
    read_qualification,
    read_specification,
    read_substitution_request,
    read_warranty,
    read_work_order,
)


def test_adjudication_application_error_depth3_cascade(api: ApiClient):
    """PRD §3.7: "on an application-error outcome the blame cascade extends
    further, moving the applicator qualification used on the warranty's work
    order from `CERTIFIED` to `PROBATION` and applying the 150-point probation
    penalty to the applicator's score per §3.3."
    PRD §3.3: "if the resulting score has fallen below the
    `min_quality_history_score` of any program under which the applicator
    currently holds a `CERTIFIED` qualification, that qualification moves
    automatically to `SUSPENDED` and the work-order cascade below fires."

    Design: Difficulty/transitive_cascade/adjudication_application_error_depth3_cascade
    """
    world = create_world(
        api,
        system_overrides={"system_code": "SW-CAD-A"},
        program_overrides={"program_code": "QP-CAD-A", "min_quality_history_score": 300},
        applicator_overrides={"company_name": "Cascade Coatings"},
    )
    applicator_id = world["applicator"]["id"]
    qualification_a_id = world["qualification"]["id"]

    # A second, stricter program (floor 400) on another system; same applicator.
    system_b = create_coating_system(
        api,
        system_code="SW-CAD-B",
        surface_prep_standard="SSPC_SP6_COMMERCIAL",
        min_surface_profile_mils=1.5,
        max_surface_profile_mils=3.5,
        total_dft_min_mils=6.0,
        total_dft_max_mils=12.0,
        adhesion_min_psi=400,
    )
    program_b = create_program(
        api, system_b["id"], program_code="QP-CAD-B", min_quality_history_score=400
    )
    qualification_b = enroll_qualification(api, applicator_id, program_b["id"])
    certify_qualification(api, applicator_id, qualification_b["id"])

    # Project A: one coat ACCEPTED (score 500 -> 510), work order completed.
    completion = drive_to_completed_work_order(api, world, asset_zone="SPAN-1")
    warranty = issue_warranty(
        api, world["project"]["id"], completion["work_order"]["id"],
        term_years=5, exposure_cents=80_000,
    )
    claim_warranty(
        api, world["project"]["id"], warranty["id"],
        defect_mode="ADHESION_LOSS", evidence_notes="peeling at edges",
    )
    investigation = begin_evidence(
        api, warranty["id"], read_investigation(api, warranty["id"])["id"]
    )

    # Project B: issued spec on system B and a never-begun SCHEDULED work order.
    project_b = create_project(api, project_name="Airport Hangar", owner_name="City Aviation")
    spec_b = create_specification(api, project_b["id"], system_b["id"])
    issue_specification(api, project_b["id"], spec_b["id"])
    work_order_b = create_work_order(
        api, project_b["id"], spec_b["id"], applicator_id, asset_zone="BAY-1"
    )

    adjudicate(api, warranty["id"], investigation["id"], "APPLICATION_ERROR", adjudicated_fault_pct=0)

    # Hop 1: the claim resolves and the exposure is released.
    resolved = read_warranty(api, warranty["id"])
    assert read_investigation(api, warranty["id"])["status"] == "ADJUDICATED_APPLICATION_ERROR"
    assert resolved["status"] == "RESOLVED"
    assert resolved["manufacturer_fault_pct"] == 0
    assert_cents(resolved["material_share_cents"], 0, "material_share_cents")
    assert_cents(resolved["application_share_cents"], 80_000, "application_share_cents")
    assert read_project(api, world["project"]["id"])["committed_warranty_exposure_cents"] == 0

    # Hop 2: the qualification used on the failed work order enters PROBATION.
    qualification_a = read_qualification(api, applicator_id, qualification_a_id)
    assert qualification_a["status"] == "PROBATION"
    assert_score(read_applicator(api, applicator_id)["quality_history_score"], 510 - PROBATION_PENALTY)

    # Hop 3: the other qualification (floor 400 > 360) is score-suspended.
    qualification_b = read_qualification(api, applicator_id, qualification_b["id"])
    assert qualification_b["status"] == "SUSPENDED"
    assert qualification_b["suspension_count"] == 1

    # Hop 4: the suspension cascade reaches the unrelated project's work order.
    assert read_work_order(api, work_order_b["id"])["status"] == "ON_HOLD"


def test_spec_issue_supersede_cascade(api: ApiClient):
    """PRD §3.4: "If the issued draft carried a `supersedes_specification_id`,
    the superseded specification moves to `SUPERSEDED`, every pending
    substitution request against it is rejected with `decision_reason`
    "specification superseded", and every `SCHEDULED` work order referencing
    it is cancelled."
    PRD §3.4: "Issuance increments the project's `version` by 1 — the mutation
    the OCC guard exists to serialize — and moves a `PLANNING` project to
    `SPECIFIED`."

    Design: Difficulty/transitive_cascade/spec_issue_supersede_cascade
    """
    world = create_world(
        api,
        asset_type="STRUCTURAL_STEEL",
        system_overrides={"system_code": "SW-SUP-100"},
        applicator_overrides={"company_name": "Canopy Crews"},
    )
    project_id = world["project"]["id"]
    spec1_id = world["spec"]["id"]
    competitor = create_coating_system(
        api,
        system_code="CMP-SUP-200",
        manufacturer_name="Competitor Coatings",
        is_competitor_system=True,
        base_voc_gpl=320,
    )
    request = create_substitution_request(api, spec1_id, competitor["id"], rationale="cost reduction")
    work_order = create_work_order(
        api, project_id, spec1_id, world["applicator"]["id"], asset_zone="CANOPY-A"
    )
    project_before = read_project(api, project_id)

    spec2 = create_specification(
        api, project_id, world["system"]["id"], supersedes_specification_id=spec1_id
    )
    issue_specification(api, project_id, spec2["id"], expected_project_version=project_before["version"])

    spec2_after = read_specification(api, spec2["id"])
    assert spec2_after["status"] == "ISSUED"
    assert spec2_after["pinned_spec_revision"] == 1

    # Hop 1: the incumbent is superseded.
    assert read_specification(api, spec1_id)["status"] == "SUPERSEDED"

    # Hop 2a: the pending substitution request on the incumbent is rejected.
    request_after = read_substitution_request(api, request["id"])
    assert request_after["status"] == "REJECTED"
    assert request_after["decision_reason"] == "specification superseded"

    # Hop 2b: the SCHEDULED work order referencing the incumbent is cancelled.
    assert read_work_order(api, work_order["id"])["status"] == "CANCELLED"

    # Issuance consumed the OCC-observed version and bumped exactly once.
    assert read_project(api, project_id)["version"] == project_before["version"] + 1
