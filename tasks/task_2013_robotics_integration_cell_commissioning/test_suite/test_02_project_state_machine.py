"""CellProject state machine: initial/terminal, hold/resume, terminate
cascade, and rework loop (PRD §3.1, §3.6, §3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_cell_project,
    create_and_submit_study,
    create_org,
    create_project,
    create_site,
    create_training_session_payload,
    create_user,
    get_project,
    make_finance_admin_headers,
    make_project_engineer_headers,
    make_trainer_headers,
    move_project_to_study,
    setup_full_project,
    validate_error,
    validate_success,
)


def test_project_initial_state_draft_and_terminal_lockdown(api):
    """PRD §3.1: "The project opens in `DRAFT` status with `hold_reason` null
    and `rework_count` at zero." PRD §3.9: "`CLOSED` and `TERMINATED` are the
    project's terminal states."

    Design: Corner/state_machines/project_initial_state_draft_and_terminal_lockdown
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-INIT"})
    proj = ctx["project"]
    eng = ctx["users"]["PROJECT_ENGINEER"]
    assert proj["status"] == "DRAFT"
    assert proj["rework_count"] == 0
    assert proj.get("hold_reason") is None

    terminated = validate_success(
        api.terminate_cell_project(proj["id"], make_finance_admin_headers())
    )
    assert terminated["status"] == "TERMINATED"

    # From TERMINATED no further transition is possible.
    current = get_project(proj["id"], make_finance_admin_headers())
    resp = api.advance_cell_project(
        proj["id"],
        {"expected_project_version": current["version"]},
        make_project_engineer_headers(eng["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_hold_resume_roundtrip_restores_prior_status(api):
    """PRD §3.1: "resuming is the only exit from `ON_HOLD`, and it restores
    exactly the status captured at hold time while clearing `hold_reason`."

    Design: Corner/state_machines/hold_resume_roundtrip_restores_prior_status
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-HOLD"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    held = validate_success(
        api.hold_cell_project(
            proj["id"],
            {"hold_reason": "supply delay"},
            make_project_engineer_headers(eng["id"]),
        )
    )
    assert held["status"] == "ON_HOLD"
    assert held["hold_reason"] == "supply delay"

    resumed = validate_success(
        api.resume_cell_project(proj["id"], make_project_engineer_headers(eng["id"]))
    )
    assert resumed["status"] == "STUDY"
    assert resumed.get("hold_reason") is None


def test_terminate_cascades_children_to_terminal(api):
    """PRD §3.9: "Termination cascades through every child. Application
    studies in `DRAFT` or `SUBMITTED` move to `REJECTED`. ... Training
    sessions in `SCHEDULED` or `IN_PROGRESS` move to `CANCELLED`. ... either
    `retention_balance_cents` already stands at zero, or a compensating
    `PENALTY` entry is posted atomically with the termination to zero it."

    Design: Corner/state_machines/terminate_cascades_children_to_terminal
    """
    org = create_org(retention_rate_bps=1000)
    eng = create_user(org["id"], "Eng One", "PROJECT_ENGINEER")
    trn = create_user(org["id"], "Trainer One", "TRAINER")
    site = create_site(org["id"], eng["id"], site_name="S9")
    proj = create_project(
        site["id"],
        eng["id"],
        project_code="P-TERM",
        contracted_cycle_time_s=10.0,
        contract_value_cents=1_000_000,
        guaranteed_oee_pct=80.0,
    )
    proj = move_project_to_study(proj, eng["id"])
    study = create_and_submit_study(proj, eng["id"])
    # Reject the study to leave it non-DRAFT/SUBMITTED? No — keep a DRAFT
    # study in place by creating a second one after the first moved out.
    # Simpler: terminate while the study is SUBMITTED (still cascades).
    # Schedule a training session for the project (SCHEDULED).
    trainer = make_trainer_headers(trn["id"])
    sess = validate_success(
        api.create_training_session(
            proj["id"],
            create_training_session_payload(
                "OPERATOR",
                "2026-08-20T08:00:00Z",
                "2026-08-20T16:00:00Z",
                trn["id"],
                attendee_count=5,
            ),
            trainer,
        ),
        201,
    )
    assert sess["session_status"] == "SCHEDULED"

    terminated = validate_success(
        api.terminate_cell_project(proj["id"], make_finance_admin_headers())
    )
    assert_cell_project(terminated)
    assert terminated["status"] == "TERMINATED"
    assert terminated["retention_balance_cents"] == 0

    study_after = validate_success(
        api.get_application_study(study["id"], make_project_engineer_headers(eng["id"]))
    )
    assert study_after["status"] == "REJECTED"

    sess_after = validate_success(
        api.get_training_session(sess["id"], make_trainer_headers(trn["id"]))
    )
    assert sess_after["session_status"] == "CANCELLED"


def test_project_rework_cycle_design_fat_design(api):
    """PRD §3.6: "Failing a `PENDING` test whose `phase` is `FAT` moves the
    project from `FAT` back to `DESIGN` ... Either failure increments the
    project's `rework_count` by one, moves every `RELEASED` robot program to
    `REWORK` (with `sim_status` untouched), moves a `LOCKED` robot selection
    back to `VALIDATED` for re-check."

    Design: Difficulty/non_linear_state_machine/project_rework_cycle_design_fat_design
    """
    from test_helpers import (
        create_acceptance_test_payload,
        make_controls_programmer_headers,
        make_site_supervisor_headers,
        setup_project_in_fat,
    )

    ctx = setup_project_in_fat(project_overrides={"project_code": "P-CYC"})
    proj = ctx["project"]
    sup = ctx["users"]["SITE_SUPERVISOR"]
    eng = ctx["users"]["PROJECT_ENGINEER"]
    p1 = ctx["users"]["CONTROLS_PROGRAMMER"]

    # Capture the released program and locked selection for cascade assertions.
    sup_hdrs = make_site_supervisor_headers(sup["id"])
    programs, _ = __import__(
        "test_helpers", fromlist=["validate_paginated"]
    ).validate_paginated(api.list_robot_programs(proj["id"], sup_hdrs))
    assert len(programs) == 1
    rp = programs[0]
    assert rp["dev_status"] == "RELEASED"
    assert rp["sim_status"] == "SIM_PASSED"

    selections, _ = __import__(
        "test_helpers", fromlist=["validate_paginated"]
    ).validate_paginated(api.list_robot_selections(proj["id"], sup_hdrs))
    assert len(selections) == 1
    rs = selections[0]
    assert rs["selection_status"] == "LOCKED"

    # Create a FAT acceptance test and explicitly fail it.
    fat = validate_success(
        api.create_acceptance_test(
            proj["id"],
            create_acceptance_test_payload(
                "FAT",
                measured_cycle_time_s=12.0,
                measured_oee_pct=70.0,
                defects_observed=5,
            ),
            sup_hdrs,
        ),
        201,
    )
    validate_success(api.fail_acceptance_test(fat["id"], sup_hdrs))

    proj_after = get_project(proj["id"], sup_hdrs)
    assert proj_after["status"] == "DESIGN"
    assert proj_after["rework_count"] == 1

    rp_after = validate_success(
        api.get_robot_program(rp["id"], make_controls_programmer_headers(p1["id"]))
    )
    assert rp_after["dev_status"] == "REWORK"
    assert rp_after["sim_status"] == "SIM_PASSED", (
        "sim axis must be untouched by the rework cascade"
    )

    rs_after = validate_success(api.get_robot_selection(rs["id"], sup_hdrs))
    assert rs_after["selection_status"] == "VALIDATED"


def test_sat_fail_cascade_depth3(api):
    """PRD §3.6: "A site-acceptance failure additionally moves the `APPROVED`
    safety assessment to `SUPERSEDED` and creates a successor `DRAFT` shell
    with `assessment_revision` incremented by one, forcing the safety case
    back through review."

    Design: Difficulty/transitive_cascade/sat_fail_cascade_depth3
    """
    from test_helpers import (
        create_acceptance_test_payload,
        make_project_engineer_headers,
        make_site_supervisor_headers,
        setup_project_in_sat,
        validate_paginated,
    )

    ctx = setup_project_in_sat(project_overrides={"project_code": "P-CAS"})
    proj = ctx["project"]
    sup = ctx["users"]["SITE_SUPERVISOR"]
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sra = ctx["sra"]
    sup_hdrs = make_site_supervisor_headers(sup["id"])

    programs, _ = validate_paginated(api.list_robot_programs(proj["id"], sup_hdrs))
    rp = programs[0]
    selections, _ = validate_paginated(api.list_robot_selections(proj["id"], sup_hdrs))
    rs = selections[0]

    # Create a SAT acceptance test with failing measurements, then fail it.
    sat = validate_success(
        api.create_acceptance_test(
            proj["id"],
            create_acceptance_test_payload(
                "SAT",
                measured_cycle_time_s=13.0,
                measured_oee_pct=60.0,
                defects_observed=9,
            ),
            sup_hdrs,
        ),
        201,
    )
    validate_success(api.fail_acceptance_test(sat["id"], sup_hdrs))

    proj_after = get_project(proj["id"], sup_hdrs)
    assert proj_after["status"] == "DESIGN"
    assert proj_after["rework_count"] == 1

    rp_after = validate_success(api.get_robot_program(rp["id"], sup_hdrs))
    assert rp_after["dev_status"] == "REWORK"

    rs_after = validate_success(api.get_robot_selection(rs["id"], sup_hdrs))
    assert rs_after["selection_status"] == "VALIDATED"

    sra_after = validate_success(api.get_safety_risk_assessment(sra["id"], sup_hdrs))
    assert sra_after["status"] == "SUPERSEDED"

    sras, _ = validate_paginated(
        api.list_safety_risk_assessments(
            proj["id"], make_project_engineer_headers(eng["id"])
        )
    )
    drafts = [s for s in sras if s["status"] == "DRAFT"]
    assert len(drafts) == 1, f"Expected one successor DRAFT, got {len(drafts)}"
    assert drafts[0]["assessment_revision"] == sra["assessment_revision"] + 1
