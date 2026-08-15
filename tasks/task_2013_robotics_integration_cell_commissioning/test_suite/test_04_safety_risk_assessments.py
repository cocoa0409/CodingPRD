"""Safety risk assessments: PL derivation boundary, muting gate, priority
ordering, and reject-revise loop (PRD §3.3, §2.6)."""
from test_helpers import (
    ApiErrorId,
    assert_safety_risk_assessment,
    create_and_submit_assessment,
    create_org,
    create_project,
    create_safety_risk_assessment_payload,
    create_site,
    create_user,
    get_project,
    make_project_engineer_headers,
    make_safety_lead_headers,
    move_project_to_study,
    setup_full_project,
    validate_error,
    validate_success,
)


def test_safety_budget_boundary_pl_thresholds(api):
    """PRD §3.3: "The `pl_achieved` level derives from the same raw score:
    nine points or more yields `PLe`, six points or more but fewer than nine
    yields `PLd`, and anything lower yields `PLc`. Both thresholds are
    inclusive — a raw score of exactly nine counts as `PLe`."

    Design: Corner/calculations/safety_budget_boundary_pl_thresholds
    """
    ctx = setup_full_project(
        org_overrides={"default_pl_category_target": "PLe"},
        project_overrides={"project_code": "P-PL"},
    )
    eng = ctx["users"]["PROJECT_ENGINEER"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    # fencing 30.0m -> 3.0 points (30/10), curtains 4 -> 6.0 points,
    # muting false -> 0 penalty. raw = 9.0 -> PLe, budget = 90.0.
    sra = create_and_submit_assessment(
        proj,
        eng["id"],
        risk_score_pre_mitigation=100,
        pl_target="PLe",
        fencing_length_m=30.0,
        light_curtain_zones=4,
        muting_required=False,
    )
    assert_safety_risk_assessment(sra)
    assert sra["pl_achieved"] == "PLe"
    assert sra["safety_function_budget_pct"] == 90.0


def test_muting_requires_light_curtain_and_min_pld(api):
    """PRD §3.3: "When `muting_required` is true, there must be at least one
    light-curtain zone and `pl_achieved` must be `PLd` or `PLe`. A breach of
    either rule is rejected with `ERR_SAFETY_LEVEL_INSUFFICIENT`."

    Design: Corner/validations/muting_requires_light_curtain_and_min_pld
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-MUTE"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sl = ctx["users"]["SAFETY_LEAD"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    # fencing 50.0m -> 5.0 points (capped), curtains 0, muting true -> -2.
    # raw = 3.0 -> PLc. muting true with zero curtains fails the safety gate.
    sra = create_and_submit_assessment(
        proj,
        eng["id"],
        risk_score_pre_mitigation=100,
        pl_target="PLd",
        fencing_length_m=50.0,
        light_curtain_zones=0,
        muting_required=True,
    )
    assert sra["status"] == "IN_REVIEW"

    resp = api.approve_safety_risk_assessment(
        sra["id"], make_safety_lead_headers(sl["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SAFETY_LEVEL_INSUFFICIENT)


def test_state_vs_business_safety_on_assessment_approve(api):
    """PRD §2.6: "The ladder, from first to last, is: ... 4. Whether the
    target entity stands in a state from which the requested transition is
    defined — `ERR_INVALID_STATE` (HTTP 409). ... 6. Safety-level sufficiency
    on assessment approval — `ERR_SAFETY_LEVEL_INSUFFICIENT` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_assessment_approve
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-PC1"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sl = ctx["users"]["SAFETY_LEAD"]
    proj = move_project_to_study(ctx["project"], eng["id"])
    eng_hdrs = make_project_engineer_headers(eng["id"])

    # Create an assessment whose safety design would be insufficient if
    # submitted (risk 500 requires PLe; design yields PLd) — but leave it
    # DRAFT so the state check fires first.
    sra = validate_success(
        api.create_safety_risk_assessment(
            proj["id"],
            create_safety_risk_assessment_payload(
                risk_score_pre_mitigation=500,
                pl_target="PLe",
                fencing_length_m=20.0,
                light_curtain_zones=2,
                muting_required=False,
            ),
            eng_hdrs,
        ),
        201,
    )
    assert sra["status"] == "DRAFT"

    resp = api.approve_safety_risk_assessment(
        sra["id"], make_safety_lead_headers(sl["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_safety_assessment_reject_revise_loop(api):
    """PRD §3.3: "Rejection moves `IN_REVIEW` to `REJECTED`, and rejection is
    not terminal: a `ProjectEngineer` may revise the assessment, returning it
    to `DRAFT` with `assessment_revision` incremented by one, ready to be
    submitted again."

    Design: Corner/state_machines/safety_assessment_reject_revise_loop
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-REV"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sl = ctx["users"]["SAFETY_LEAD"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    sra = create_and_submit_assessment(
        proj,
        eng["id"],
        risk_score_pre_mitigation=100,
        pl_target="PLc",
        fencing_length_m=15.0,
        light_curtain_zones=1,
        muting_required=False,
    )
    rejected = validate_success(
        api.reject_safety_risk_assessment(
            sra["id"], make_safety_lead_headers(sl["id"])
        )
    )
    assert rejected["status"] == "REJECTED"

    revised = validate_success(
        api.revise_safety_risk_assessment(
            sra["id"], make_project_engineer_headers(eng["id"])
        )
    )
    assert revised["status"] == "DRAFT"
    assert revised["assessment_revision"] == sra["assessment_revision"] + 1
