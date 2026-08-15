"""Composite setup helpers for multi-step test prerequisites.

The test runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so a failed precondition surfaces as a
clear "Setup failed" error rather than a confusing assertion failure.

Identity threading: all seven roles are entity-backed by IntegratorUser, so
any call whose downstream behaviour depends on the caller's identity
(segregation of duties on approve/peer-review, trainer scoring on complete,
recorded_by stamping) uses the make_*_headers() builder with the actual
IntegratorUser.id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    create_acceptance_test_payload,
    create_application_study_payload,
    create_cell_project_payload,
    create_customer_site_payload,
    create_integrator_org_payload,
    create_integrator_user_payload,
    create_maintenance_plan_payload,
    create_robot_program_payload,
    create_robot_selection_payload,
    create_safety_risk_assessment_payload,
    create_spare_parts_package_payload,
    create_training_session_payload,
    record_simulation_payload,
)
from .test_users import (
    TEST_USERS,
    make_controls_programmer_headers,
    make_finance_admin_headers,
    make_project_engineer_headers,
    make_safety_lead_headers,
    make_service_manager_headers,
    make_site_supervisor_headers,
    make_trainer_headers,
)

FA = TEST_USERS["finance_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: org / users / site / project primitives
# ---------------------------------------------------------------------------


def create_org(**overrides):
    """Create an integrator org as FinanceAdmin (PRD §3.1)."""
    return get_success_data(
        api_client.create_integrator_org(create_integrator_org_payload(**overrides), FA),
        201,
    )


def create_user(org_id, display_name, user_role, **overrides):
    """Create an IntegratorUser under the org as FinanceAdmin (PRD §3.1)."""
    return get_success_data(
        api_client.create_integrator_user(
            org_id,
            create_integrator_user_payload(display_name, user_role, **overrides),
            FA,
        ),
        201,
    )


def create_site(org_id, eng_id, **overrides):
    """Create a customer site under the org as the given ProjectEngineer."""
    return get_success_data(
        api_client.create_customer_site(
            org_id,
            create_customer_site_payload(**overrides),
            make_project_engineer_headers(eng_id),
        ),
        201,
    )


def create_project(site_id, eng_id, **overrides):
    """Create a cell project under the site as the given ProjectEngineer."""
    return get_success_data(
        api_client.create_cell_project(
            site_id,
            create_cell_project_payload(**overrides),
            make_project_engineer_headers(eng_id),
        ),
        201,
    )


def setup_org_site_project(
    org_overrides=None,
    site_overrides=None,
    project_overrides=None,
    roles=("PROJECT_ENGINEER",),
):
    """Smallest reusable composite: org + users (one per requested role) +
    site + project. Returns a dict with keys org, site, project, users.
    `users` maps role -> IntegratorUser dict.
    """
    org = create_org(**(org_overrides or {}))
    users = {}
    for role in roles:
        display = role.replace("_", " ").title()
        users[role] = create_user(org["id"], display, role)
    eng_id = users["PROJECT_ENGINEER"]["id"]
    site = create_site(org["id"], eng_id, **(site_overrides or {}))
    project = create_project(site["id"], eng_id, **(project_overrides or {}))
    return {"org": org, "site": site, "project": project, "users": users}


def get_project(project_id, headers=None):
    return get_success_data(api_client.get_cell_project(project_id, headers or FA))


# ---------------------------------------------------------------------------
# Tier 1: state-progression helpers (DRAFT -> STUDY -> DESIGN -> BUILD -> FAT)
# ---------------------------------------------------------------------------


def advance_project(project_id, expected_version, headers):
    return get_success_data(
        api_client.advance_cell_project(
            project_id, {"expected_project_version": expected_version}, headers
        )
    )


def move_project_to_study(project, eng_id):
    """Advance DRAFT -> STUDY. Returns the refreshed project."""
    eng = make_project_engineer_headers(eng_id)
    return advance_project(project["id"], project["version"], eng)


def create_and_submit_study(project, eng_id, **overrides):
    """Create + submit an ApplicationStudy while project is in STUDY."""
    eng = make_project_engineer_headers(eng_id)
    proj = get_project(project["id"], eng)
    study = get_success_data(
        api_client.create_application_study(
            project["id"],
            create_application_study_payload(proj["version"], **overrides),
            eng,
        ),
        201,
    )
    return get_success_data(api_client.submit_application_study(study["id"], eng))


def approve_study(study_id, safety_lead_id):
    return get_success_data(
        api_client.approve_application_study(
            study_id, make_safety_lead_headers(safety_lead_id)
        )
    )


def create_and_submit_assessment(project, eng_id, **overrides):
    """Create + submit a SafetyRiskAssessment while project is in STUDY."""
    eng = make_project_engineer_headers(eng_id)
    sra = get_success_data(
        api_client.create_safety_risk_assessment(
            project["id"],
            create_safety_risk_assessment_payload(**overrides),
            eng,
        ),
        201,
    )
    return get_success_data(api_client.submit_safety_risk_assessment(sra["id"], eng))


def approve_assessment(sra_id, safety_lead_id):
    return get_success_data(
        api_client.approve_safety_risk_assessment(
            sra_id, make_safety_lead_headers(safety_lead_id)
        )
    )


def move_project_to_design(project, eng_id, safety_lead_id, **kwargs):
    """Walk STUDY -> DESIGN: approved study + approved assessment.

    Returns (project_after, study, sra).
    """
    study = create_and_submit_study(project, eng_id, **kwargs.pop("study_overrides", {}))
    approve_study(study["id"], safety_lead_id)
    sra = create_and_submit_assessment(
        project, eng_id, **kwargs.pop("sra_overrides", {})
    )
    approve_assessment(sra["id"], safety_lead_id)
    eng = make_project_engineer_headers(eng_id)
    proj = get_project(project["id"], eng)
    proj = advance_project(proj["id"], proj["version"], eng)
    return proj, study, sra


def create_validated_locked_selection(project, eng_id, sup_id, **overrides):
    """PROPOSED -> VALIDATED -> LOCKED. Project must already be in DESIGN."""
    eng = make_project_engineer_headers(eng_id)
    sup = make_site_supervisor_headers(sup_id)
    rs = get_success_data(
        api_client.create_robot_selection(
            project["id"], create_robot_selection_payload(**overrides), eng
        ),
        201,
    )
    get_success_data(api_client.validate_robot_selection(rs["id"], eng))
    return get_success_data(api_client.lock_robot_selection(rs["id"], sup))


def create_released_program(project, prog_id, reviewer_id, sim_time=9.5):
    """Create a RobotProgram and walk it OUTLINE->CODED->PEER_REVIEWED with
    a passing SIM, then release it. Returns the released program."""
    prog = make_controls_programmer_headers(prog_id)
    rev = make_controls_programmer_headers(reviewer_id)
    rp = get_success_data(
        api_client.create_robot_program(
            project["id"], create_robot_program_payload(), prog
        ),
        201,
    )
    get_success_data(api_client.code_complete_robot_program(rp["id"], prog))
    get_success_data(api_client.peer_review_robot_program(rp["id"], rev))
    get_success_data(api_client.simulate_robot_program(rp["id"], prog))
    get_success_data(
        api_client.record_simulation(
            rp["id"], record_simulation_payload(sim_time), prog
        )
    )
    return get_success_data(api_client.release_robot_program(rp["id"], prog))


def move_project_to_build(project, eng_id, sup_id, prog_id, prog2_id):
    """Walk DESIGN -> BUILD: locked selection + released program."""
    create_validated_locked_selection(project, eng_id, sup_id)
    create_released_program(project, prog_id, prog2_id)
    eng = make_project_engineer_headers(eng_id)
    proj = get_project(project["id"], eng)
    return advance_project(proj["id"], proj["version"], eng)


def move_project_to_fat(project, sup_id):
    """BUILD -> FAT: all programs RELEASED+SIM_PASSED; assessment pl_achieved
    >= pl_target. Caller must have already established those gates."""
    sup = make_site_supervisor_headers(sup_id)
    proj = get_project(project["id"], sup)
    return advance_project(proj["id"], proj["version"], sup)


def record_passing_acceptance(project, sup_id, phase, **overrides):
    """Create + record an acceptance test in the given phase with measurements
    that satisfy PASS by default. Returns the recorded AcceptanceTest."""
    sup = make_site_supervisor_headers(sup_id)
    at = get_success_data(
        api_client.create_acceptance_test(
            project["id"], create_acceptance_test_payload(phase, **overrides), sup
        ),
        201,
    )
    return get_success_data(api_client.record_acceptance_test(at["id"], sup))


def move_project_to_ship(project, sup_id):
    """FAT -> SHIP: latest FAT acceptance test verdict PASS / CONDITIONAL_PASS."""
    sup = make_site_supervisor_headers(sup_id)
    proj = get_project(project["id"], sup)
    return advance_project(proj["id"], proj["version"], sup)


def create_and_order_spare_package(project, svc_id, **overrides):
    svc = make_service_manager_headers(svc_id)
    pkg = get_success_data(
        api_client.create_spare_parts_package(
            project["id"], create_spare_parts_package_payload(**overrides), svc
        ),
        201,
    )
    return get_success_data(api_client.order_spare_parts_package(pkg["id"], svc))


def move_project_to_sat(project, sup_id, svc_id, pkg_overrides=None):
    """SHIP -> SAT: ORDERED/DELIVERED spare parts package must exist."""
    create_and_order_spare_package(project, svc_id, **(pkg_overrides or {}))
    sup = make_site_supervisor_headers(sup_id)
    proj = get_project(project["id"], sup)
    return advance_project(proj["id"], proj["version"], sup)


def move_project_to_training(project, sup_id):
    """SAT -> TRAINING: latest SAT acceptance test verdict PASS /
    CONDITIONAL_PASS; posts the SAT retention release and starts the
    throughput guarantee."""
    sup = make_site_supervisor_headers(sup_id)
    proj = get_project(project["id"], sup)
    return advance_project(proj["id"], proj["version"], sup)


def create_and_activate_maintenance_plan(project, svc_id, **overrides):
    svc = make_service_manager_headers(svc_id)
    mp = get_success_data(
        api_client.create_maintenance_plan(
            project["id"], create_maintenance_plan_payload(**overrides), svc
        ),
        201,
    )
    return get_success_data(api_client.activate_maintenance_plan(mp["id"], svc))


def run_training_session(
    project,
    trainer_id,
    audience,
    start_utc,
    end_utc,
    clock_at_start,
    practical,
    written,
    attendee_count=6,
):
    """Schedule a session, advance clock, start it, complete it. Returns the
    completed session."""
    trainer = make_trainer_headers(trainer_id)
    sess = get_success_data(
        api_client.create_training_session(
            project["id"],
            create_training_session_payload(
                audience,
                start_utc,
                end_utc,
                trainer_id,
                attendee_count=attendee_count,
            ),
            trainer,
        ),
        201,
    )
    get_success_data(api_client.set_clock(clock_at_start, FA))
    get_success_data(api_client.start_training_session(sess["id"], trainer))
    return get_success_data(
        api_client.complete_training_session(
            sess["id"],
            {"practical_score_pct": practical, "written_score_pct": written},
            trainer,
        )
    )


def move_project_to_guarantee(project, eng_id, sup_id, svc_id, trainer_id):
    """TRAINING -> GUARANTEE: both audiences complete at/above their
    thresholds; maintenance plan ACTIVE; guarantee MEASURING."""
    create_and_activate_maintenance_plan(project, svc_id)
    # OPERATOR pass (>=80) and TECHNICIAN pass (>=85).
    run_training_session(
        project,
        trainer_id,
        "OPERATOR",
        "2026-08-10T08:00:00Z",
        "2026-08-10T16:00:00Z",
        "2026-08-10T09:00:00Z",
        95.0,
        90.0,
    )
    run_training_session(
        project,
        trainer_id,
        "TECHNICIAN",
        "2026-08-11T08:00:00Z",
        "2026-08-11T16:00:00Z",
        "2026-08-11T09:00:00Z",
        95.0,
        90.0,
    )
    eng = make_project_engineer_headers(eng_id)
    proj = get_project(project["id"], eng)
    return advance_project(proj["id"], proj["version"], eng)


# ---------------------------------------------------------------------------
# Tier 5: full-lifecycle composites (DRAFT -> ... -> FAT / SAT / TRAINING /
# GUARANTEE). These are the workhorse fixtures used by cascade, retention,
# and shortfall tests.
# ---------------------------------------------------------------------------


def setup_full_project(
    org_overrides=None,
    site_overrides=None,
    project_overrides=None,
):
    """Org with full seven-role roster + site + fresh DRAFT project.

    Returns dict with keys: org, site, project, users. `users` is keyed by
    user_role (PROJECT_ENGINEER, SAFETY_LEAD, CONTROLS_PROGRAMMER (primary),
    CONTROLS_PROGRAMMER_2 (peer reviewer), SITE_SUPERVISOR, TRAINER,
    SERVICE_MANAGER, FINANCE_ADMIN).
    """
    org = create_org(**(org_overrides or {}))
    eng = create_user(org["id"], "Eng One", "PROJECT_ENGINEER")
    sl = create_user(org["id"], "Safety Lead", "SAFETY_LEAD")
    p1 = create_user(org["id"], "Prog One", "CONTROLS_PROGRAMMER")
    p2 = create_user(org["id"], "Prog Two", "CONTROLS_PROGRAMMER")
    sup = create_user(org["id"], "Sup One", "SITE_SUPERVISOR")
    svc = create_user(org["id"], "Svc Mgr", "SERVICE_MANAGER")
    trn = create_user(org["id"], "Trainer One", "TRAINER")
    fin = create_user(org["id"], "Fin Admin", "FINANCE_ADMIN")
    site = create_site(org["id"], eng["id"], **(site_overrides or {}))
    project = create_project(site["id"], eng["id"], **(project_overrides or {}))
    return {
        "org": org,
        "site": site,
        "project": project,
        "users": {
            "PROJECT_ENGINEER": eng,
            "SAFETY_LEAD": sl,
            "CONTROLS_PROGRAMMER": p1,
            "CONTROLS_PROGRAMMER_2": p2,
            "SITE_SUPERVISOR": sup,
            "SERVICE_MANAGER": svc,
            "TRAINER": trn,
            "FINANCE_ADMIN": fin,
        },
    }


def setup_project_in_design(**kwargs):
    """Project advanced DRAFT -> STUDY -> DESIGN with approved study and
    approved safety risk assessment."""
    ctx = setup_full_project(**kwargs)
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sl = ctx["users"]["SAFETY_LEAD"]
    proj = move_project_to_study(ctx["project"], eng["id"])
    proj, study, sra = move_project_to_design(proj, eng["id"], sl["id"])
    ctx.update({"project": proj, "study": study, "sra": sra})
    return ctx


def setup_project_in_build(**kwargs):
    """Project in BUILD with locked selection and released program."""
    ctx = setup_project_in_design(**kwargs)
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sup = ctx["users"]["SITE_SUPERVISOR"]
    p1 = ctx["users"]["CONTROLS_PROGRAMMER"]
    p2 = ctx["users"]["CONTROLS_PROGRAMMER_2"]
    proj = move_project_to_build(
        ctx["project"], eng["id"], sup["id"], p1["id"], p2["id"]
    )
    ctx["project"] = proj
    return ctx


def setup_project_in_fat(**kwargs):
    """Project in FAT with selection LOCKED and program RELEASED+SIM_PASSED."""
    ctx = setup_project_in_build(**kwargs)
    sup = ctx["users"]["SITE_SUPERVISOR"]
    proj = move_project_to_fat(ctx["project"], sup["id"])
    ctx["project"] = proj
    return ctx


def setup_project_in_ship(**kwargs):
    """Project in SHIP: FAT advance posted after a passing FAT acceptance."""
    ctx = setup_project_in_fat(**kwargs)
    sup = ctx["users"]["SITE_SUPERVISOR"]
    record_passing_acceptance(ctx["project"], sup["id"], "FAT")
    proj = move_project_to_ship(ctx["project"], sup["id"])
    ctx["project"] = proj
    return ctx


def setup_project_in_sat(**kwargs):
    """Project in SAT with ORDERED spare parts package."""
    ctx = setup_project_in_ship(**kwargs)
    sup = ctx["users"]["SITE_SUPERVISOR"]
    svc = ctx["users"]["SERVICE_MANAGER"]
    proj = move_project_to_sat(ctx["project"], sup["id"], svc["id"])
    ctx["project"] = proj
    return ctx


def setup_project_in_training(**kwargs):
    """Project in TRAINING after a passing SAT: guarantee MEASURING, SAT
    retention release posted."""
    ctx = setup_project_in_sat(**kwargs)
    sup = ctx["users"]["SITE_SUPERVISOR"]
    record_passing_acceptance(ctx["project"], sup["id"], "SAT")
    proj = move_project_to_training(ctx["project"], sup["id"])
    ctx["project"] = proj
    return ctx


def setup_project_in_guarantee(**kwargs):
    """Project in GUARANTEE with active maintenance plan, both audiences
    trained to passing scores, and guarantee MEASURING."""
    ctx = setup_project_in_training(**kwargs)
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sup = ctx["users"]["SITE_SUPERVISOR"]
    svc = ctx["users"]["SERVICE_MANAGER"]
    trn = ctx["users"]["TRAINER"]
    proj = move_project_to_guarantee(
        ctx["project"], eng["id"], sup["id"], svc["id"], trn["id"]
    )
    ctx["project"] = proj
    return ctx


def get_throughput_guarantee_for_project(project_id, headers=None):
    """Fetch the 1:1 reverse-reachability guarantee; returns the single
    ThroughputGuarantee object."""
    hdrs = headers or FA
    data = get_success_data(
        api_client.get_project_throughput_guarantee(project_id, hdrs)
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"Expected exactly one guarantee, got: {data}"
    )
    return data[0]
