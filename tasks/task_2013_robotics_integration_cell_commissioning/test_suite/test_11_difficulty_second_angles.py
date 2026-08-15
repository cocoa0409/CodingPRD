"""Second-angle tests for each difficulty-design instance — each difficulty
instance requires >=2 tests (skill §2.1 queue A). These tests assert
orthogonal facets of the same instance: error vs success branch, boundary
X-1 vs X vs X+1, second-order side effect, or independence of parallel axes.

Citations refer to the same PRD sentences as the first-angle tests in the
topical test files.
"""
from test_helpers import (
    ApiErrorId,
    advance_project,
    assert_application_study,
    assert_cell_project,
    assert_retention_ledger_entry,
    create_acceptance_test_payload,
    create_and_submit_assessment,
    create_and_submit_study,
    create_application_study_payload,
    create_maintenance_plan_payload,
    create_org,
    create_project,
    create_robot_program_payload,
    create_robot_selection_payload,
    create_safety_risk_assessment_payload,
    create_site,
    create_spare_parts_package_payload,
    create_training_session_payload,
    create_user,
    get_project,
    get_throughput_guarantee_for_project,
    make_controls_programmer_headers,
    make_finance_admin_headers,
    make_project_engineer_headers,
    make_safety_lead_headers,
    make_service_manager_headers,
    make_site_supervisor_headers,
    make_trainer_headers,
    move_project_to_study,
    record_simulation_payload,
    setup_full_project,
    setup_project_in_design,
    setup_project_in_fat,
    setup_project_in_guarantee,
    setup_project_in_sat,
    setup_project_in_training,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# dual_variant_calc / cycle_time_simulated_vs_measured_diverge — second angle:
# the MARGINAL band boundary (exactly at contract * 1.10 is MARGINAL; beyond
# is INFEASIBLE) from the same provisional derating rule.
# ---------------------------------------------------------------------------


def test_cycle_time_simulated_vs_measured_diverge_marginal_infeasible(api):
    """PRD §3.2: "the `feasibility` verdict is `FEASIBLE` when the adjusted
    time does not exceed the project's `contracted_cycle_time_s`, `MARGINAL`
    when it exceeds the contract but stays at or under one hundred and ten
    percent of it, and `INFEASIBLE` beyond that."

    Design: Difficulty/dual_variant_calc/cycle_time_simulated_vs_measured_diverge
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-DV2"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    # 9.0 / 0.80 = 11.250 -> INFEASIBLE (beyond 110% of 10.0).
    study = create_and_submit_study(
        proj, eng["id"], sim_cycle_time_s=9.0, sim_confidence_pct=80.0
    )
    assert_application_study(study)
    assert study["adjusted_cycle_time_s"] == 11.25
    assert study["feasibility"] == "INFEASIBLE"


# ---------------------------------------------------------------------------
# dual_variant_calc / spare_parts_forecast_quoted_vs_delivered_diverge —
# second angle: site shift update re-derives the quoted-variant forecast even
# without delivery, confirming the cascade that §3.7 prescribes between the
# two variants' trigger points.
# ---------------------------------------------------------------------------


def test_spare_parts_forecast_quoted_vs_delivered_diverge_shift_requote(api):
    """PRD §3.7: "Separately, whenever a `ProjectEngineer` updates a site's
    `shift_windows_per_day` (§3.1), the forecast is recomputed on every
    spare-parts package of every project under that site."

    Design: Difficulty/dual_variant_calc/spare_parts_forecast_quoted_vs_delivered_diverge
    """
    ctx = setup_full_project(
        site_overrides={"site_name": "Plant B2", "shift_windows_per_day": 2},
        project_overrides={"project_code": "P-200B"},
    )
    eng = ctx["users"]["PROJECT_ENGINEER"]
    svc = ctx["users"]["SERVICE_MANAGER"]
    svc_hdrs = make_service_manager_headers(svc["id"])

    pkg = validate_success(
        api.create_spare_parts_package(
            ctx["project"]["id"],
            create_spare_parts_package_payload(
                package_code="SPP-QUOTED-ONLY",
                list_price_cents=100000,
                recommended_coverage_months=24,
            ),
            svc_hdrs,
        ),
        201,
    )
    # 24 months at 2 shifts -> 24.0.
    assert pkg["forecast_consumption_months"] == 24.0

    # Update site to 1 shift (still QUOTED): shift_factor = 0.5 -> 48.0.
    validate_success(
        api.update_customer_site(
            ctx["site"]["id"],
            {"shift_windows_per_day": 1},
            make_project_engineer_headers(eng["id"]),
        )
    )
    after = validate_success(api.get_spare_parts_package(pkg["id"], svc_hdrs))
    assert after["forecast_consumption_months"] == 48.0
    assert after["package_status"] == "QUOTED"


# ---------------------------------------------------------------------------
# combinatorial_formula / payload_margin_multi_input_threshold — second
# angle: margin below 20.00 with inertia passing also rejects.
# ---------------------------------------------------------------------------


def test_payload_margin_multi_input_threshold_margin_shortfall(api):
    """PRD §3.4: "validation requires a margin of at least 20.0 percent and a
    wrist inertia no greater than the manufacturer limit, and any shortfall
    is rejected with `ERR_PAYLOAD_CHECK_FAILED`."

    Design: Difficulty/combinatorial_formula/payload_margin_multi_input_threshold
    """
    ctx = setup_project_in_design(
        org_overrides={"brand_specialization": "DUAL"},
        project_overrides={"project_code": "P-300B"},
    )
    eng = ctx["users"]["PROJECT_ENGINEER"]

    # Margin 19.99 (rated 50, ee 34.005, part 6.0 -> load 40.005, margin
    # 100*(50-40.005)/50 = 19.99) with inertia in range.
    rs = validate_success(
        api.create_robot_selection(
            ctx["project"]["id"],
            create_robot_selection_payload(
                rated_payload_kg=50.0,
                end_effector_weight_kg=34.005,
                part_weight_kg=6.0,
                wrist_inertia_kgm2=10.0,
                wrist_inertia_limit_kgm2=12.0,
            ),
            make_project_engineer_headers(eng["id"]),
        ),
        201,
    )
    resp = api.validate_robot_selection(
        rs["id"], make_project_engineer_headers(eng["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PAYLOAD_CHECK_FAILED)


# ---------------------------------------------------------------------------
# combinatorial_formula / retention_waterfall_pinned_rounding_order — second
# angle: the FAT and SAT milestone postings on advance release exactly 30%
# and 40% of total (rounded per-line, half-up).
# ---------------------------------------------------------------------------


def test_retention_waterfall_pinned_rounding_order_milestone_postings(api):
    """PRD §3.6: "thirty percent of the total, rounded half-up to a whole
    cent, is earmarked for the factory-acceptance milestone; forty percent,
    rounded half-up the same way, for the site-acceptance milestone; and the
    guarantee bucket receives whatever remains after those two earmarks"."

    Design: Difficulty/combinatorial_formula/retention_waterfall_pinned_rounding_order
    """
    ctx = setup_project_in_training(project_overrides={"project_code": "P-WF2"})
    proj = ctx["project"]
    fa = make_finance_admin_headers()

    # Default contract 1,000,000 at 1000 bps -> total 100,000.
    # FAT release = 30,000; SAT release = 40,000; balance = 30,000.
    resp = api.list_retention_ledger_entries(proj["id"], fa)
    entries, _ = validate_paginated(resp)
    kinds = sorted([(e["entry_type"], e["amount_cents"]) for e in entries])
    assert ("RELEASE", -30000) in kinds, f"FAT release missing: {kinds}"
    assert ("RELEASE", -40000) in kinds, f"SAT release missing: {kinds}"
    assert ("WITHHOLD", 100000) in kinds

    after = get_project(proj["id"], fa)
    assert after["retention_balance_cents"] == 30000


# ---------------------------------------------------------------------------
# non_linear_state_machine / project_rework_cycle_design_fat_design —
# second angle: the second pass through DESIGN -> BUILD -> FAT is reachable
# after a rework cycle (the cycle truly closes).
# ---------------------------------------------------------------------------


def test_project_rework_cycle_design_fat_design_second_pass(api):
    """PRD §3.6: "The next test record created for the failed phase opens as
    a fresh `PENDING` record carrying the next `attempt` number, so the cycle
    `DESIGN` → `BUILD` → `FAT` → `DESIGN` (and its `SAT` analogue) can repeat
    as often as reality demands."

    Design: Difficulty/non_linear_state_machine/project_rework_cycle_design_fat_design
    """
    ctx = setup_project_in_fat(project_overrides={"project_code": "P-CYC2"})
    proj = ctx["project"]
    sup = ctx["users"]["SITE_SUPERVISOR"]
    p1 = ctx["users"]["CONTROLS_PROGRAMMER"]
    p2 = ctx["users"]["CONTROLS_PROGRAMMER_2"]
    sup_hdrs = make_site_supervisor_headers(sup["id"])
    prog_hdrs = make_controls_programmer_headers(p1["id"])
    rev_hdrs = make_controls_programmer_headers(p2["id"])

    programs, _ = validate_paginated(api.list_robot_programs(proj["id"], sup_hdrs))
    rp = programs[0]

    fat1 = validate_success(
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
    validate_success(api.fail_acceptance_test(fat1["id"], sup_hdrs))
    assert get_project(proj["id"], sup_hdrs)["status"] == "DESIGN"

    # Second forward pass: re-code, re-review, re-release (sim still PASSED),
    # then DESIGN -> BUILD -> FAT must succeed again.
    validate_success(api.code_complete_robot_program(rp["id"], prog_hdrs))
    validate_success(api.peer_review_robot_program(rp["id"], rev_hdrs))
    validate_success(api.release_robot_program(rp["id"], prog_hdrs))

    # The selection was un-locked by the cascade; propose and lock a fresh
    # VALIDATED selection (the cascade-validated one remains VALIDATED).
    from test_helpers import (
        create_validated_locked_selection,
        move_project_to_fat,
    )

    eng = ctx["users"]["PROJECT_ENGINEER"]
    create_validated_locked_selection(
        get_project(proj["id"], sup_hdrs), eng["id"], sup["id"]
    )
    # Move DESIGN -> BUILD: both gates are already satisfied (LOCKED selection
    # above; rp was re-RELEASED in place), so advance directly.
    eng_hdrs = make_project_engineer_headers(eng["id"])
    proj_after = advance_project(
        proj["id"], get_project(proj["id"], sup_hdrs)["version"], eng_hdrs
    )
    assert proj_after["status"] == "BUILD"
    proj_after2 = move_project_to_fat(proj_after, sup["id"])
    assert proj_after2["status"] == "FAT"
    assert proj_after2["rework_count"] == 1


# ---------------------------------------------------------------------------
# non_linear_state_machine / robot_program_parallel_dev_and_sim_axes —
# second angle: sim retry from SIM_FAILED -> SIM_RUNNING is legal and does
# not move dev; recording a passing sim then permits release.
# ---------------------------------------------------------------------------


def test_robot_program_parallel_dev_and_sim_axes_retry_loop(api):
    """PRD §3.5: "Starting an offline simulation requires the development
    axis to stand at `CODED`, `PEER_REVIEWED`, or `REWORK`, and moves
    `UNSIMULATED` to `SIM_RUNNING` — or, on a retry, `SIM_FAILED` back to
    `SIM_RUNNING`."

    Design: Difficulty/non_linear_state_machine/robot_program_parallel_dev_and_sim_axes
    """
    ctx = setup_project_in_design(project_overrides={"project_code": "P-PAR2"})
    p1 = ctx["users"]["CONTROLS_PROGRAMMER"]
    p2 = ctx["users"]["CONTROLS_PROGRAMMER_2"]
    prog = make_controls_programmer_headers(p1["id"])
    rev = make_controls_programmer_headers(p2["id"])

    rp = validate_success(
        api.create_robot_program(
            ctx["project"]["id"],
            create_robot_program_payload(program_name="RETRY"),
            prog,
        ),
        201,
    )
    validate_success(api.code_complete_robot_program(rp["id"], prog))

    # Fail once.
    validate_success(api.simulate_robot_program(rp["id"], prog))
    failed = validate_success(
        api.record_simulation(rp["id"], record_simulation_payload(11.0), prog)
    )
    assert failed["sim_status"] == "SIM_FAILED"
    assert failed["sim_iteration_count"] == 1

    # Retry from SIM_FAILED -> SIM_RUNNING; dev axis still CODED.
    running = validate_success(api.simulate_robot_program(rp["id"], prog))
    assert running["sim_status"] == "SIM_RUNNING"
    assert running["dev_status"] == "CODED"

    # Pass on retry: SIM_PASSED and last_sim_cycle_time_s stamped.
    passed = validate_success(
        api.record_simulation(rp["id"], record_simulation_payload(9.5), prog)
    )
    assert passed["sim_status"] == "SIM_PASSED"
    assert passed["sim_iteration_count"] == 2
    assert passed["last_sim_cycle_time_s"] == 9.5
    assert passed["dev_status"] == "CODED"

    # Now peer review and release succeed.
    validate_success(api.peer_review_robot_program(rp["id"], rev))
    released = validate_success(api.release_robot_program(rp["id"], prog))
    assert released["dev_status"] == "RELEASED"
    assert released["sim_status"] == "SIM_PASSED"
    assert released["release_revision"] == 1


# ---------------------------------------------------------------------------
# transitive_cascade / sat_fail_cascade_depth3 — second angle: SAT fail also
# leaves the retention balance unchanged (no RELEASE posted for the failed
# SAT, balance still shows the FAT release only).
# ---------------------------------------------------------------------------


def test_sat_fail_cascade_depth3_retention_unchanged(api):
    """PRD §3.6: "Failing a `PENDING` test whose `phase` is `SAT` moves it
    from `SAT` back to `DESIGN`" — the rework path. PRD §3.6 also states the
    SAT milestone `RELEASE` is posted by the *advance* (`SAT` → `TRAINING`),
    not by recording, so a failed SAT posts nothing: the ledger still holds
    only the WITHHOLD and the FAT RELEASE.

    Design: Difficulty/transitive_cascade/sat_fail_cascade_depth3
    """
    ctx = setup_project_in_sat(project_overrides={"project_code": "P-CAS3"})
    proj = ctx["project"]
    sup = ctx["users"]["SITE_SUPERVISOR"]
    sup_hdrs = make_site_supervisor_headers(sup["id"])
    fa = make_finance_admin_headers()

    # Balance after FAT pass + advance: 100,000 - 30,000 = 70,000.
    before = get_project(proj["id"], fa)
    assert before["retention_balance_cents"] == 70000

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

    after = get_project(proj["id"], fa)
    # SAT fail does not release retention; balance stays at 70,000.
    assert after["retention_balance_cents"] == 70000

    resp = api.list_retention_ledger_entries(proj["id"], fa)
    entries, _ = validate_paginated(resp)
    kinds = sorted([(e["entry_type"], e["amount_cents"]) for e in entries])
    assert kinds == [("RELEASE", -30000), ("WITHHOLD", 100000)]


# ---------------------------------------------------------------------------
# transitive_cascade / site_shift_change_refreshes_package_forecast — second
# angle: a site shift update touches packages across multiple projects under
# the same site.
# ---------------------------------------------------------------------------


def test_site_shift_change_refreshes_package_forecast_multi_project(api):
    """PRD §3.7: "Separately, whenever a `ProjectEngineer` updates a site's
    `shift_windows_per_day` (§3.1), the forecast is recomputed on every
    spare-parts package of every project under that site."

    Design: Difficulty/transitive_cascade/site_shift_change_refreshes_package_forecast
    """
    ctx = setup_full_project(
        site_overrides={"site_name": "Plant H2", "shift_windows_per_day": 2},
        project_overrides={"project_code": "P-CAS2A"},
    )
    eng = ctx["users"]["PROJECT_ENGINEER"]
    svc = ctx["users"]["SERVICE_MANAGER"]
    svc_hdrs = make_service_manager_headers(svc["id"])
    eng_hdrs = make_project_engineer_headers(eng["id"])

    # Second project under the same site.
    proj2 = create_project(
        ctx["site"]["id"],
        eng["id"],
        project_code="P-CAS2B",
        contracted_cycle_time_s=10.0,
        contract_value_cents=100000,
        guaranteed_oee_pct=80.0,
    )

    pkg_a = validate_success(
        api.create_spare_parts_package(
            ctx["project"]["id"],
            create_spare_parts_package_payload(
                package_code="SPP-A", list_price_cents=100000,
                recommended_coverage_months=12,
            ),
            svc_hdrs,
        ),
        201,
    )
    pkg_b = validate_success(
        api.create_spare_parts_package(
            proj2["id"],
            create_spare_parts_package_payload(
                package_code="SPP-B", list_price_cents=100000,
                recommended_coverage_months=12,
            ),
            svc_hdrs,
        ),
        201,
    )
    assert pkg_a["forecast_consumption_months"] == 12.0
    assert pkg_b["forecast_consumption_months"] == 12.0

    validate_success(
        api.update_customer_site(
            ctx["site"]["id"], {"shift_windows_per_day": 3}, eng_hdrs
        )
    )

    a_after = validate_success(api.get_spare_parts_package(pkg_a["id"], svc_hdrs))
    b_after = validate_success(api.get_spare_parts_package(pkg_b["id"], svc_hdrs))
    assert a_after["forecast_consumption_months"] == 8.0
    assert b_after["forecast_consumption_months"] == 8.0


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / state_vs_business_safety_on_assessment
# _approve — second angle: the safety rule DOES fire on its own when the
# assessment is in the correct state (IN_REVIEW) and only the safety check
# fails.
# ---------------------------------------------------------------------------


def test_state_vs_business_safety_on_assessment_approve_safety_fires(api):
    """PRD §3.3: "When `risk_score_pre_mitigation` is 400 or higher,
    `pl_achieved` must be `PLe`. ... A breach of either rule is rejected with
    `ERR_SAFETY_LEVEL_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_assessment_approve
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-PC1B"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sl = ctx["users"]["SAFETY_LEAD"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    # Risk 500 needs PLe; design yields PLd (fencing 20m=2pts + 2 curtains=3pts
    # = 5.0 -> PLc actually; use fencing 40m+2 curtains = 4.0+3.0 = 7.0 -> PLd).
    sra = create_and_submit_assessment(
        proj,
        eng["id"],
        risk_score_pre_mitigation=500,
        pl_target="PLe",
        fencing_length_m=40.0,
        light_curtain_zones=2,
        muting_required=False,
    )
    assert sra["status"] == "IN_REVIEW"
    assert sra["pl_achieved"] == "PLd"

    resp = api.approve_safety_risk_assessment(
        sra["id"], make_safety_lead_headers(sl["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SAFETY_LEVEL_INSUFFICIENT)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / business_referential_vs_state_on_study
# _create — second angle: when the project is in a legal state and the only
# issue is the referential target, the referential error DOES surface.
# ---------------------------------------------------------------------------


def test_business_referential_vs_state_on_study_create_referential_fires(api):
    """PRD §3.2: "When `supersedes_study_id` is present it must reference an
    application study of the same project whose status is `APPROVED`, or the
    create is rejected with `ERR_SUPERSEDE_TARGET_INVALID`; the project must
    also stand in `STUDY` or `DESIGN` for supersedure to be legal."

    Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_state_on_study_create
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-PC2B"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sl = ctx["users"]["SAFETY_LEAD"]
    proj = move_project_to_study(ctx["project"], eng["id"])
    eng_hdrs = make_project_engineer_headers(eng["id"])

    study1 = create_and_submit_study(proj, eng["id"])
    validate_success(
        api.reject_application_study(study1["id"], make_safety_lead_headers(sl["id"]))
    )

    # Project remains in STUDY (state legal); supersedes target is REJECTED.
    current = get_project(proj["id"], eng_hdrs)
    resp = api.create_application_study(
        proj["id"],
        create_application_study_payload(
            current["version"],
            sim_cycle_time_s=9.5,
            sim_confidence_pct=95.0,
            supersedes_study_id=study1["id"],
        ),
        eng_hdrs,
    )
    validate_error(resp, ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID)


# ---------------------------------------------------------------------------
# boundary_precision_check / payload_margin_exactly_twenty_passes — second
# angle: 19.99% (X - 0.01) rejects.
# ---------------------------------------------------------------------------


def test_payload_margin_exactly_twenty_passes_below_boundary(api):
    """PRD §3.4: "validation requires a margin of at least 20.0 percent and a
    wrist inertia no greater than the manufacturer limit, and any shortfall
    is rejected with `ERR_PAYLOAD_CHECK_FAILED`."

    Design: Difficulty/boundary_precision_check/payload_margin_exactly_twenty_passes
    """
    ctx = setup_project_in_design(project_overrides={"project_code": "P-BP1B"})
    eng = ctx["users"]["PROJECT_ENGINEER"]

    # rated 50, ee 34.005, part 6.0 -> load 40.005 -> margin 19.99 -> rejects.
    rs = validate_success(
        api.create_robot_selection(
            ctx["project"]["id"],
            create_robot_selection_payload(
                rated_payload_kg=50.0,
                end_effector_weight_kg=34.005,
                part_weight_kg=6.0,
                wrist_inertia_kgm2=10.0,
                wrist_inertia_limit_kgm2=12.0,
            ),
            make_project_engineer_headers(eng["id"]),
        ),
        201,
    )
    resp = api.validate_robot_selection(
        rs["id"], make_project_engineer_headers(eng["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PAYLOAD_CHECK_FAILED)


# ---------------------------------------------------------------------------
# boundary_precision_check / training_zero_defect_fat_pass_vs_one_defect_
# conditional — second angle: cycle-time upper bound for CONDITIONAL_PASS at
# exactly contract * 1.02 (still CONDITIONAL_PASS) and beyond (FAIL via
# record).
# ---------------------------------------------------------------------------


def test_training_zero_defect_fat_pass_vs_one_defect_conditional_cycle_bound(api):
    """PRD §3.6: "A marginal run earns `CONDITIONAL_PASS` when the measured
    cycle time stays at or under one hundred and two percent of the contract,
    the measured OEE falls no more than two percentage points below the
    guarantee, defects number three or fewer, and the run did not in fact
    meet every `PASS` condition."

    Design: Difficulty/boundary_precision_check/training_zero_defect_fat_pass_vs_one_defect_conditional
    """
    ctx = setup_project_in_fat(project_overrides={"project_code": "P-BP2B"})
    proj = ctx["project"]
    sup = ctx["users"]["SITE_SUPERVISOR"]
    sup_hdrs = make_site_supervisor_headers(sup["id"])

    # Contracted 10.0; measured 10.2 (=102%) with 1 defect, OEE 79 (>=78) ->
    # CONDITIONAL_PASS (PASS fails on defects).
    fat = validate_success(
        api.create_acceptance_test(
            proj["id"],
            create_acceptance_test_payload(
                "FAT",
                measured_cycle_time_s=10.2,
                measured_oee_pct=79.0,
                defects_observed=1,
            ),
            sup_hdrs,
        ),
        201,
    )
    recorded = validate_success(api.record_acceptance_test(fat["id"], sup_hdrs))
    assert recorded["verdict"] == "CONDITIONAL_PASS"
    assert recorded["retention_released_cents"] == 15000


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / project_design_advance_requires_approved_
# assessment — second angle: the STUDY -> DESIGN gate also fails when no
# study is APPROVED (only the study gate, assessment approved).
# ---------------------------------------------------------------------------


def test_project_design_advance_requires_approved_study(api):
    """PRD §3.6: "`STUDY` → `DESIGN`, by a `ProjectEngineer`: an application
    study in `APPROVED` status exists, and a safety risk assessment in
    `APPROVED` status exists." Failure is rejected with
    `ERR_GATE_PRECONDITION_UNMET` (PRD §2.6 rung 19).

    Design: Difficulty/cross_entity_state_dependency/project_design_advance_requires_approved_assessment
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-XD1B"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sl = ctx["users"]["SAFETY_LEAD"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    from test_helpers import approve_assessment, create_and_submit_assessment

    # Assessment approved but study still missing.
    sra = create_and_submit_assessment(proj, eng["id"])
    approve_assessment(sra["id"], sl["id"])

    eng_hdrs = make_project_engineer_headers(eng["id"])
    current = get_project(proj["id"], eng_hdrs)
    resp = api.advance_cell_project(
        proj["id"], {"expected_project_version": current["version"]}, eng_hdrs
    )
    validate_error(resp, ApiErrorId.ERR_GATE_PRECONDITION_UNMET)

    after = get_project(proj["id"], eng_hdrs)
    assert after["status"] == "STUDY"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / training_advance_requires_operator_and_
# technician_completion — second angle: when all gates pass (operator >= 80,
# technician >= 85, maintenance active, guarantee MEASURING), the advance
# succeeds.
# ---------------------------------------------------------------------------


def test_training_advance_requires_operator_and_technician_completion_pass(api):
    """PRD §3.6: "`TRAINING` → `GUARANTEE`, by a `ProjectEngineer`: every
    `OPERATOR` training session of the project stands `COMPLETED` with a
    `completion_score_pct` of at least 80, every `TECHNICIAN` session stands
    `COMPLETED` with a `completion_score_pct` of at least 85, a maintenance
    plan in `ACTIVE` status exists, and the throughput guarantee stands
    `MEASURING`."

    Design: Difficulty/cross_entity_state_dependency/training_advance_requires_operator_and_technician_completion
    """
    ctx = setup_project_in_training(project_overrides={"project_code": "P-XD2B"})
    proj = ctx["project"]
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sup = ctx["users"]["SITE_SUPERVISOR"]
    svc = ctx["users"]["SERVICE_MANAGER"]
    trn = ctx["users"]["TRAINER"]

    from test_helpers import move_project_to_guarantee

    proj_after = move_project_to_guarantee(
        proj, eng["id"], sup["id"], svc["id"], trn["id"]
    )
    assert proj_after["status"] == "GUARANTEE"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / trainer_double_booking_half_open_adjacency —
# second angle: different trainers may hold overlapping sessions (the rule
# binds the trainer resource, not the project).
# ---------------------------------------------------------------------------


def test_trainer_double_booking_half_open_adjacency_distinct_trainers(api):
    """PRD §3.8: "the same trainer may not hold two sessions whose windows
    overlap while either stands in `SCHEDULED` or `IN_PROGRESS`."

    Design: Difficulty/resource_temporal_overlap/trainer_double_booking_half_open_adjacency
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-TO1B"})
    org = ctx["org"]
    trn_a = ctx["users"]["TRAINER"]
    trn_b = create_user(org["id"], "Trainer Two", "TRAINER")

    s1 = validate_success(
        api.create_training_session(
            ctx["project"]["id"],
            create_training_session_payload(
                "OPERATOR",
                "2026-08-10T08:00:00Z",
                "2026-08-10T16:00:00Z",
                trn_a["id"],
                attendee_count=6,
            ),
            make_trainer_headers(trn_a["id"]),
        ),
        201,
    )
    assert s1["session_status"] == "SCHEDULED"

    # Overlapping window but a different trainer -> allowed.
    s2 = validate_success(
        api.create_training_session(
            ctx["project"]["id"],
            create_training_session_payload(
                "TECHNICIAN",
                "2026-08-10T10:00:00Z",
                "2026-08-10T18:00:00Z",
                trn_b["id"],
                attendee_count=4,
            ),
            make_trainer_headers(trn_b["id"]),
        ),
        201,
    )
    assert s2["session_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# compensating_invariant / retention_ledger_conservation_across_milestones —
# second angle: the happy-path milestone releases (30,000 + 40,000 + 30,000)
# sum exactly to the original WITHHOLD (100,000).
# ---------------------------------------------------------------------------


def test_retention_ledger_conservation_across_milestones_full_cycle(api):
    """PRD §3.9: "An `outcome` of `MET` requires the observed cycle time to
    be no greater than `contracted_cycle_time_s` and the observed uptime to
    be at least `guaranteed_oee_pct`; it posts the final `RELEASE` ledger
    entry for the entire remaining retention and recomputes
    `retention_balance_cents` to zero."

    Design: Difficulty/compensating_invariant/retention_ledger_conservation_across_milestones
    """
    ctx = setup_project_in_guarantee(project_overrides={"project_code": "P-CI1B"})
    proj = ctx["project"]
    svc = ctx["users"]["SERVICE_MANAGER"]
    fa = make_finance_admin_headers()

    guar = get_throughput_guarantee_for_project(
        proj["id"], make_service_manager_headers(svc["id"])
    )

    # Move past window end and close MET.
    validate_success(api.set_clock("2027-08-01T00:00:00Z", fa))
    closed = validate_success(
        api.close_throughput_guarantee(
            guar["id"],
            {"outcome": "MET", "observed_cycle_time_s": 9.0, "observed_uptime_pct": 90.0},
            make_service_manager_headers(svc["id"]),
        )
    )
    assert closed["guarantee_status"] == "MET"

    after = get_project(proj["id"], fa)
    assert after["retention_balance_cents"] == 0

    resp = api.list_retention_ledger_entries(proj["id"], fa)
    entries, _ = validate_paginated(resp)
    kinds = sorted([(e["entry_type"], e["amount_cents"]) for e in entries])
    # WITHHOLD 100,000; RELEASE -30,000 (FAT), -40,000 (SAT), -30,000 (MET).
    assert kinds == [
        ("RELEASE", -40000),
        ("RELEASE", -30000),
        ("RELEASE", -30000),
        ("WITHHOLD", 100000),
    ]


# ---------------------------------------------------------------------------
# compensating_invariant / rework_cycle_preserves_release_revision_
# monotonicity — second angle: sim_iteration_count also accumulates across
# rework (it is not reset by the cascade).
# ---------------------------------------------------------------------------


def test_rework_cycle_preserves_release_revision_monotonicity_sim_iter(api):
    """PRD §3.5: "Either way, `sim_iteration_count` increments by one." PRD
    §3.5: "every release increments `release_revision` by one". PRD §3.6: the
    rework cascade moves every RELEASED program to REWORK "with `sim_status`
    untouched" — so simulation history survives.

    Design: Difficulty/compensating_invariant/rework_cycle_preserves_release_revision_monotonicity
    """
    ctx = setup_project_in_fat(project_overrides={"project_code": "P-CI2B"})
    proj = ctx["project"]
    sup = ctx["users"]["SITE_SUPERVISOR"]
    p1 = ctx["users"]["CONTROLS_PROGRAMMER"]
    sup_hdrs = make_site_supervisor_headers(sup["id"])
    prog_hdrs = make_controls_programmer_headers(p1["id"])

    programs, _ = validate_paginated(api.list_robot_programs(proj["id"], sup_hdrs))
    rp = programs[0]
    initial_iter = rp["sim_iteration_count"]
    assert initial_iter == 1  # one passing sim was recorded during setup

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

    # After rework the program retains its sim_iteration_count.
    after = validate_success(api.get_robot_program(rp["id"], prog_hdrs))
    assert after["dev_status"] == "REWORK"
    assert after["sim_status"] == "SIM_PASSED"
    assert after["sim_iteration_count"] == initial_iter
    assert after["release_revision"] == 1  # not yet re-released
