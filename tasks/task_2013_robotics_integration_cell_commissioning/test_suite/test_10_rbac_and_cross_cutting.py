"""RBAC denials, OCC on advance, and the project design gate (PRD §2.1,
§2.6, §2.7, §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_application_study_payload,
    create_org,
    create_project,
    create_site,
    create_user,
    get_project,
    make_finance_admin_headers,
    make_project_engineer_headers,
    make_safety_lead_headers,
    make_trainer_headers,
    move_project_to_study,
    setup_full_project,
    validate_error,
    validate_success,
)


def test_safety_lead_cannot_create_study(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: `POST /robotics/cell-projects/{id}/application-studies` is
    authorized for `ProjectEngineer` only.

    Design: Corner/rbac/safety_lead_cannot_create_study
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-RBAC"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sl = ctx["users"]["SAFETY_LEAD"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    resp = api.create_application_study(
        proj["id"],
        create_application_study_payload(
            proj["version"], sim_cycle_time_s=9.0, sim_confidence_pct=100.0
        ),
        make_safety_lead_headers(sl["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_trainer_cannot_close_guarantee_and_unauthenticated_rejected(api):
    """PRD §2.1: "A request missing either header, carrying an empty
    `X-User-ID`, or carrying a role string outside this set is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but
    not permitted for the target endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4: guarantee close is authorized
    for `ServiceManager` only, and §2.6 lists role authorization (priority 2)
    ahead of existence (priority 3).

    Design: Corner/rbac/trainer_cannot_close_guarantee_and_unauthenticated_rejected
    """
    org = create_org()
    trn = create_user(org["id"], "Trainer One", "TRAINER")

    # Trainer hits a ServiceManager-exclusive endpoint. Role check (priority
    # 2) precedes existence (priority 3), so a non-existent guarantee id
    # still produces ERR_FORBIDDEN_ROLE.
    resp = api.close_throughput_guarantee(
        "11111111-2222-3333-4444-555555555555",
        {"outcome": "MET", "observed_cycle_time_s": 9.0, "observed_uptime_pct": 90.0},
        make_trainer_headers(trn["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # Missing role header entirely -> ERR_UNAUTHENTICATED (priority 1).
    resp2 = api.close_throughput_guarantee(
        "11111111-2222-3333-4444-555555555555",
        {"outcome": "MET", "observed_cycle_time_s": 9.0, "observed_uptime_pct": 90.0},
        {"X-User-ID": trn["id"], "Content-Type": "application/json"},
    )
    validate_error(resp2, ApiErrorId.ERR_UNAUTHENTICATED)


def test_occ_stale_version_on_advance(api):
    """PRD §2.7: "`POST /robotics/cell-projects/{id}/advance` — advancing the
    project to its next stage. A version mismatch is rejected with
    `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    Design: Corner/errors/occ_stale_version_on_advance
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-OCC"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    eng_hdrs = make_project_engineer_headers(eng["id"])
    proj = ctx["project"]
    v0 = proj["version"]

    # First advance succeeds (DRAFT -> STUDY) and bumps version.
    validate_success(
        api.advance_cell_project(
            proj["id"], {"expected_project_version": v0}, eng_hdrs
        )
    )

    # Replay the stale version: rejected.
    resp = api.advance_cell_project(
        proj["id"], {"expected_project_version": v0 - 1}, eng_hdrs
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION)


def test_project_design_advance_requires_approved_assessment(api):
    """PRD §3.6: "`STUDY` → `DESIGN`, by a `ProjectEngineer`: an application
    study in `APPROVED` status exists, and a safety risk assessment in
    `APPROVED` status exists." Failure is rejected with
    `ERR_GATE_PRECONDITION_UNMET` (PRD §2.6 rung 19).

    Design: Difficulty/cross_entity_state_dependency/project_design_advance_requires_approved_assessment
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-XD1"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sl = ctx["users"]["SAFETY_LEAD"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    from test_helpers import (
        approve_study,
        create_and_submit_assessment,
        create_and_submit_study,
    )

    study = create_and_submit_study(proj, eng["id"])
    approve_study(study["id"], sl["id"])
    # Assessment is submitted (IN_REVIEW) but not approved.
    create_and_submit_assessment(proj, eng["id"])

    eng_hdrs = make_project_engineer_headers(eng["id"])
    current = get_project(proj["id"], eng_hdrs)
    resp = api.advance_cell_project(
        proj["id"], {"expected_project_version": current["version"]}, eng_hdrs
    )
    validate_error(resp, ApiErrorId.ERR_GATE_PRECONDITION_UNMET)

    after = get_project(proj["id"], eng_hdrs)
    assert after["status"] == "STUDY"
