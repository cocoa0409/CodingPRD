"""Mapping exercise: provisional vs final reslot, approval cascade, gate
ordering, state/posture guards, OCC, pool exhaustion, reversal (PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_program,
    api_client,
    create_accepted_survey_with_cut,
    create_employee,
    create_mapping_decision_payload,
    create_market_cut_payload,
    create_market_survey_payload,
    create_pay_band_payload,
    create_price_approve_publish_band,
    create_submitted_mapping,
    create_triaged_mapping,
    get_success_data,
    make_department_manager_headers,
    set_clock,
    setup_published_band_pair,
    setup_pricing_program,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]
HRBP = TEST_USERS["hrbp_headers"]


# ─── dual variant: provisional at submit vs final at approve ──────────

def _reslot_dual_variant_setup():
    """P1 band PUBLISHED (mid 10m, spread 0.30); P2 band PRICED mid 13m; E1
    salary 10m on P1 profile; mapping E1 -> P2 submitted; then P2 re-priced
    (second cut) to mid 14018750 and published before approval."""
    ctx = setup_pricing_program(approve_profiles=(0, 1))
    fam, lvls, zone, prog = ctx["family"], ctx["levels"], ctx["zone"], ctx["program"]
    p1, p2 = ctx["profiles"][1], ctx["profiles"][2]
    survey, _ = create_accepted_survey_with_cut(p1["id"], zone["id"], 10_000_000,
                                                sample_size=10)
    _s, _c = create_accepted_survey_with_cut(p2["id"], zone["id"], 13_000_000,
                                             sample_size=10, survey_name="S-p2")
    create_price_approve_publish_band(prog["id"], fam["id"], lvls[0]["id"], zone["id"])
    band2 = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(prog["id"], fam["id"], lvls[1]["id"], zone["id"]),
        ANALYST))
    band2 = get_success_data(api_client.price_pay_band(
        band2["id"], {"pricing_variant": "OFFICIAL",
                      "expected_pay_band_version": band2["version"]}, ANALYST))
    prog = advance_program(prog["id"], "MAPPING_OPEN")
    from test_helpers import create_department_payload, create_employee_payload
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    emp = get_success_data(api_client.create_employee(
        create_employee_payload(dept["id"], p1["id"], zone["id"],
                                base_salary_cents=10_000_000, hire_date="2020-01-15",
                                employee_ref="E1"),
        HRBP))
    headers = make_department_manager_headers(dept["id"])
    md = get_success_data(api_client.create_mapping_decision(
        create_mapping_decision_payload(emp["id"], p2["id"]), headers))
    md = get_success_data(api_client.submit_mapping_decision(md["id"], headers))
    # Band moves between submit and approve: second cut aged 1 month at
    # 2026-08-01 -> 15037500; weighted with 13000000 (10+10 samples).
    s2b = get_success_data(api_client.create_market_survey(
        create_market_survey_payload(name="S2B", survey_year=2026,
                                     effective_date="2026-06-15"), ANALYST))
    get_success_data(api_client.accept_market_survey(s2b["id"], MANAGER))
    get_success_data(api_client.create_market_cut(
        create_market_cut_payload(s2b["id"], p2["id"], zone["id"],
                                  p50_cents=15_000_000, sample_size=10,
                                  effective_date="2026-06-15"), ANALYST))
    band2 = get_success_data(api_client.price_pay_band(
        band2["id"], {"pricing_variant": "OFFICIAL",
                      "expected_pay_band_version": band2["version"]}, ANALYST))
    get_success_data(api_client.approve_pay_band(band2["id"], MANAGER))
    get_success_data(api_client.publish_pay_band(band2["id"], MANAGER))
    get_success_data(api_client.hrbp_review_mapping_decision(md["id"], HRBP))
    md = get_success_data(api_client.comp_triage_mapping_decision(md["id"], ANALYST))
    ctx.update({"program": prog, "band2": band2, "department": dept,
                "employee": emp, "md": md})
    return ctx


def test_reslot_provisional_estimate_uses_submit_time_band(api):
    """PRD §3.7: "The estimate selects the band for the target profile's family
    and level in the employee's geo zone under the current program, considering
    bands in `PRICED`, `COMP_APPROVED`, or `PUBLISHED` and taking the latest
    `created_at` when several qualify; if no band qualifies,
    `provisional_adjustment_cents` is null."
    PRD §3.7: "Given a band and the employee's current salary, the provisional
    adjustment for an `UPSLOT` or `LATERAL` decision is the amount needed to
    reach the band minimum — the greater of the current salary and the band's
    `min_cents`, minus the current salary — while a `DOWNSLOT` decision carries
    a zero adjustment and no salary movement."

    Design: Difficulty/dual_variant_calc/reslot_provisional_vs_final_adjustment
    """
    ctx = setup_pricing_program(approve_profiles=(0, 1))
    fam, lvls, zone, prog = ctx["family"], ctx["levels"], ctx["zone"], ctx["program"]
    p1, p2 = ctx["profiles"][1], ctx["profiles"][2]
    create_accepted_survey_with_cut(p1["id"], zone["id"], 10_000_000, sample_size=10)
    create_accepted_survey_with_cut(p2["id"], zone["id"], 13_000_000, sample_size=10,
                                    survey_name="S-p2")
    create_price_approve_publish_band(prog["id"], fam["id"], lvls[0]["id"], zone["id"])
    band2 = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(prog["id"], fam["id"], lvls[1]["id"], zone["id"]),
        ANALYST))
    get_success_data(api_client.price_pay_band(
        band2["id"], {"pricing_variant": "OFFICIAL",
                      "expected_pay_band_version": band2["version"]}, ANALYST))
    advance_program(prog["id"], "MAPPING_OPEN")
    from test_helpers import create_department_payload, create_employee_payload
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    emp = get_success_data(api_client.create_employee(
        create_employee_payload(dept["id"], p1["id"], zone["id"],
                                base_salary_cents=10_000_000, employee_ref="E1"),
        HRBP))
    headers = make_department_manager_headers(dept["id"])
    md = get_success_data(api_client.create_mapping_decision(
        create_mapping_decision_payload(emp["id"], p2["id"]), headers))
    md = validate_success(api.submit_mapping_decision(md["id"], headers), 200)
    # PRICED band min 11050000 - salary 10000000.
    assert md["provisional_adjustment_cents"] == 1_050_000
    assert md["kind"] == "UPSLOT"
    assert md["from_job_profile_id"] == p1["id"]


def test_reslot_final_differs_after_band_repriced(api):
    """PRD §3.7: "Link one mutates the employee: the profile is set to the
    target, the final reslot variant re-reads the `PUBLISHED` band as of
    approval — so when the band was re-priced between submission and approval,
    the `final_adjustment_cents` legitimately differs from the
    `provisional_adjustment_cents` computed from identical employee data — and
    the salary is applied per `kind`: for `UPSLOT` and `LATERAL` the new salary
    is the greater of the current salary and the band minimum, while for
    `DOWNSLOT` the salary is left unchanged and `red_circled` is set when the
    salary exceeds the band maximum; the pre-approval salary is snapshotted
    into `pre_salary_cents`, `approved_at` — null until this moment — is
    stamped from the logical clock, `decided_by_user_id` records the approver,
    and the employee's `version` increments."

    Design: Difficulty/dual_variant_calc/reslot_provisional_vs_final_adjustment
    """
    ctx = _reslot_dual_variant_setup()
    md, emp, dept, p2 = ctx["md"], ctx["employee"], ctx["department"], ctx["profiles"][2]
    approved = validate_success(api.approve_mapping_decision(
        md["id"], {"expected_employee_version": emp["version"]}, MANAGER), 200)
    assert approved["provisional_adjustment_cents"] == 1_050_000
    assert approved["final_adjustment_cents"] == 1_915_938
    assert approved["final_adjustment_cents"] != approved["provisional_adjustment_cents"]
    assert approved["kind"] == "UPSLOT"
    emp_after = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert emp_after["base_salary_cents"] == 11_915_938
    assert emp_after["job_profile_id"] == p2["id"]
    dept_after = validate_success(api.get_department(dept["id"], ADMIN), 200)
    assert dept_after["committed_pool_cents"] == 1_915_938


# ─── approve cascade depth 3 ──────────────────────────────────────────

def test_mapping_approve_mutates_employee(api):
    """PRD §3.7: "Link one mutates the employee: the profile is set to the
    target, the final reslot variant re-reads the `PUBLISHED` band as of
    approval — so when the band was re-priced between submission and approval,
    the `final_adjustment_cents` legitimately differs from the
    `provisional_adjustment_cents` computed from identical employee data — and
    the salary is applied per `kind`: for `UPSLOT` and `LATERAL` the new salary
    is the greater of the current salary and the band minimum, while for
    `DOWNSLOT` the salary is left unchanged and `red_circled` is set when the
    salary exceeds the band maximum; the pre-approval salary is snapshotted
    into `pre_salary_cents`, `approved_at` — null until this moment — is
    stamped from the logical clock, `decided_by_user_id` records the approver,
    and the employee's `version` increments."

    Design: Difficulty/transitive_cascade/mapping_approve_cascade_depth3
    """
    ctx = setup_published_band_pair()
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                          employee_ref="E1")
    md = create_triaged_mapping(ctx, emp, ctx["profiles"][2])
    approved = validate_success(api.approve_mapping_decision(
        md["id"], {"expected_employee_version": emp["version"]}, MANAGER), 200)
    assert approved["status"] == "APPROVED"
    assert approved["final_adjustment_cents"] == 1_050_000
    assert approved["pre_salary_cents"] == 10_000_000
    assert approved["approved_at"] is not None
    assert approved["decided_by_user_id"] == MANAGER["X-User-ID"]
    emp_after = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert emp_after["base_salary_cents"] == 11_050_000
    assert emp_after["job_profile_id"] == ctx["profiles"][2]["id"]
    assert emp_after["version"] > emp["version"]


def test_mapping_approve_rolls_up_pool_and_payroll(api):
    """PRD §3.7: "Link two follows from the salary mutation: the department's
    `committed_pool_cents` grows by the `final_adjustment_cents` when it is
    positive, and `projected_payroll_cents` is recomputed. Link three follows
    from the payroll recompute: the program's `total_payroll_projection_cents`
    is recomputed."

    Design: Difficulty/transitive_cascade/mapping_approve_cascade_depth3
    """
    ctx = setup_published_band_pair()
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                          employee_ref="E1")
    assert validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)["total_payroll_projection_cents"] == 10_000_000
    md = create_triaged_mapping(ctx, emp, ctx["profiles"][2])
    validate_success(api.approve_mapping_decision(
        md["id"], {"expected_employee_version": emp["version"]}, MANAGER), 200)
    dept_after = validate_success(api.get_department(ctx["department"]["id"], ADMIN), 200)
    assert dept_after["committed_pool_cents"] == 1_050_000
    assert dept_after["projected_payroll_cents"] == 11_050_000
    prog_after = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
    assert prog_after["total_payroll_projection_cents"] == 11_050_000


# ─── gate ordering / terminal lockdown / profile-state gate ───────────

def test_withdraw_then_submit_terminal(api):
    """PRD §3.7: "Withdrawal by the owning manager is legal from `DRAFT`,
    `SUBMITTED`, or `RETURNED` and lands the decision in the terminal
    `WITHDRAWN` state."
    PRD §2.8 tier 7: "The requested action must be declared for the entity's
    current state (`ERR_INVALID_STATE_TRANSITION`, HTTP 409); an entity
    already in a terminal state accepts no further transitions
    (`ERR_ALREADY_TERMINAL`, HTTP 409)."

    Design: Corner/state_machines/withdraw_then_submit_terminal
    """
    ctx = setup_published_band_pair()
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                          employee_ref="E1")
    headers = make_department_manager_headers(ctx["department"]["id"])
    md = get_success_data(api_client.create_mapping_decision(
        create_mapping_decision_payload(emp["id"], ctx["profiles"][2]["id"]), headers))
    get_success_data(api_client.withdraw_mapping_decision(md["id"], headers))
    res = api.submit_mapping_decision(md["id"], headers)
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)
    after = validate_success(api.get_mapping_decision(md["id"], headers), 200)
    assert after["status"] == "WITHDRAWN"


def test_comp_triage_before_hrbp_rejected(api):
    """PRD §3.7: "A `CompAnalyst` then triages a reviewed decision, moving it
    from `HRBP_REVIEWED` to `COMP_TRIAGED`, or returns it from `HRBP_REVIEWED`
    with an optional `reason`."
    PRD §2.8 tier 7: "The requested action must be declared for the entity's
    current state (`ERR_INVALID_STATE_TRANSITION`, HTTP 409); an entity
    already in a terminal state accepts no further transitions
    (`ERR_ALREADY_TERMINAL`, HTTP 409)."

    Design: Corner/state_machines/comp_triage_before_hrbp_rejected
    """
    ctx = setup_published_band_pair()
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                          employee_ref="E1")
    md = create_submitted_mapping(ctx, emp, ctx["profiles"][2])
    res = api.comp_triage_mapping_decision(md["id"], ANALYST)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_mapping_decision(md["id"], ANALYST), 200)
    assert after["status"] == "SUBMITTED"


def test_mapping_submit_gated_by_profile_state(api):
    """PRD §3.7: "Submitting a draft decision — again ownership-scoped — moves
    it to `SUBMITTED` and performs the decision's analytic work. The posture
    gate requires the current program to be in `MAPPING_OPEN`; the
    referenced-entity tier requires the employee to be `ACTIVE` and the
    `to_job_profile_id` to reference an `APPROVED` profile, both failing as
    `ERR_REFERENCED_ENTITY_STATE`."

    Design: Difficulty/cross_entity_state_dependency/mapping_submit_gated_by_profile_state
    """
    from test_helpers import create_approved_profile, create_job_profile_payload
    ctx = setup_published_band_pair()
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                          employee_ref="E1")
    # Target profile determined and submitted but never approved (IN_REVIEW).
    target = get_success_data(api_client.create_job_profile(
        create_job_profile_payload(ctx["family"]["id"], ctx["levels"][1]["id"],
                                   title="SWE II"), ANALYST))
    get_success_data(api_client.determine_flsa(target["id"], ANALYST))
    get_success_data(api_client.submit_job_profile(target["id"], ANALYST))
    headers = make_department_manager_headers(ctx["department"]["id"])
    md = get_success_data(api_client.create_mapping_decision(
        create_mapping_decision_payload(emp["id"], target["id"]), headers))
    res = api.submit_mapping_decision(md["id"], headers)
    validate_error(res, ApiErrorId.ERR_REFERENCED_ENTITY_STATE, expected_status=422)
    after = validate_success(api.get_mapping_decision(md["id"], headers), 200)
    assert after["status"] == "DRAFT"


def test_mapping_submit_succeeds_after_profile_approved(api):
    """PRD §3.2: "A `CompManager` then approves the profile — legal only when
    the classification is `EXEMPT` or `NON_EXEMPT`, with the same
    `ERR_FLSA_TESTS_INCOMPLETE` guarding the gap — moving it to `APPROVED`, at
    which point it becomes eligible both as a mapping target and as an
    employee assignment."
    PRD §3.7: "At submission the system snapshots the employee's current
    profile into `from_job_profile_id`, computes the decision's `kind` by
    comparing the two profiles' level ranks — a target rank above the source
    rank yields `UPSLOT`, below yields `DOWNSLOT`, and equal ranks yield
    `LATERAL` — and runs the provisional reslot estimate."

    Design: Difficulty/cross_entity_state_dependency/mapping_submit_gated_by_profile_state
    """
    from test_helpers import create_job_profile_payload
    ctx = setup_published_band_pair()
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                          employee_ref="E1")
    target = get_success_data(api_client.create_job_profile(
        create_job_profile_payload(ctx["family"]["id"], ctx["levels"][1]["id"],
                                   title="SWE II"), ANALYST))
    get_success_data(api_client.determine_flsa(target["id"], ANALYST))
    get_success_data(api_client.submit_job_profile(target["id"], ANALYST))
    get_success_data(api_client.approve_job_profile(target["id"], MANAGER))
    headers = make_department_manager_headers(ctx["department"]["id"])
    md = get_success_data(api_client.create_mapping_decision(
        create_mapping_decision_payload(emp["id"], target["id"]), headers))
    submitted = validate_success(api.submit_mapping_decision(md["id"], headers), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["kind"] == "UPSLOT"


# ─── priority pair: state tier beats fiscal tier ──────────────────────

def test_state_beats_fiscal_on_mapping_approve(api):
    """PRD §2.8: "Every request is evaluated against thirteen validation tiers
    in a fixed order, and an earlier tier masks all later ones: a request that
    fails authentication never reaches the fiscal checks, and a request failing
    an earlier check reports that check's error rather than any later violation
    it also carries."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_mapping_approve
    """
    ctx = setup_published_band_pair(pool_cents=100)
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                          employee_ref="E1")
    md = create_submitted_mapping(ctx, emp, ctx["profiles"][2])
    # Decision is SUBMITTED (tier 7 fails); pool headroom 100 also fails tier 13.
    res = api.approve_mapping_decision(
        md["id"], {"expected_employee_version": emp["version"]}, MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)


def test_state_beats_fiscal_leaves_no_side_effects(api):
    """PRD §2.8: "Every request is evaluated against thirteen validation tiers
    in a fixed order, and an earlier tier masks all later ones: a request that
    fails authentication never reaches the fiscal checks, and a request failing
    an earlier check reports that check's error rather than any later violation
    it also carries."
    PRD §2.8 tier 13: "Department pool headroom and the program refresh budget
    are checked last; violations yield `ERR_DEPARTMENT_POOL_EXHAUSTED` (HTTP
    422) or, on the refresh side, `ERR_BUDGET_IMPACT_EXCEEDS` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_mapping_approve
    """
    ctx = setup_published_band_pair(pool_cents=100)
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                          employee_ref="E1")
    md = create_submitted_mapping(ctx, emp, ctx["profiles"][2])
    res = api.approve_mapping_decision(
        md["id"], {"expected_employee_version": emp["version"]}, MANAGER)
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION,
                         expected_status=409)
    assert err["error_id"] != ApiErrorId.ERR_DEPARTMENT_POOL_EXHAUSTED
    after = validate_success(api.get_mapping_decision(md["id"], MANAGER), 200)
    assert after["status"] == "SUBMITTED"
    dept_after = validate_success(api.get_department(ctx["department"]["id"], ADMIN), 200)
    assert dept_after["committed_pool_cents"] == 0


def test_pool_exhausted_on_mapping_approve(api):
    """PRD §3.7: "Five preconditions guard it, surfacing in the precedence
    order of §2.8: the OCC field `expected_employee_version` must match the
    employee's current `version` (`ERR_STALE_VERSION`); the employee must still
    be `ACTIVE` and the target band — the band for the target profile's family
    and level in the employee's geo under the current program — must exist in
    `PUBLISHED` status, both failing as `ERR_REFERENCED_ENTITY_STATE`;
    segregation of duties forbids the approver's `X-User-ID` from equalling
    the decision's `submitted_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP
    403); and the fiscal check requires any positive adjustment to fit within
    the department's headroom — its `adjustment_pool_cents` minus its
    `committed_pool_cents` — with an overrun rejected as
    `ERR_DEPARTMENT_POOL_EXHAUSTED` (HTTP 422)."

    Design: Corner/validations/pool_exhausted_on_mapping_approve
    """
    ctx = setup_published_band_pair(pool_cents=100)
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                          employee_ref="E1")
    md = create_triaged_mapping(ctx, emp, ctx["profiles"][2])
    res = api.approve_mapping_decision(
        md["id"], {"expected_employee_version": emp["version"]}, MANAGER)
    validate_error(res, ApiErrorId.ERR_DEPARTMENT_POOL_EXHAUSTED, expected_status=422)
    after = validate_success(api.get_mapping_decision(md["id"], MANAGER), 200)
    assert after["status"] == "COMP_TRIAGED"
    emp_after = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert emp_after["base_salary_cents"] == 10_000_000


def test_occ_mapping_approve_stale_employee(api):
    """PRD §2.7: "Approving a mapping decision requires
    `expected_employee_version` matching the subject employee's current
    `version`; a mismatch means the decision's provisional estimate and pool
    check were derived from a salary or profile view of the employee that has
    since changed, and the approval is refused with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_mapping_approve_stale_employee
    """
    ctx = setup_published_band_pair()
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=10_000_000,
                          employee_ref="E1")
    md = create_triaged_mapping(ctx, emp, ctx["profiles"][2])
    patched = validate_success(api.patch_employee(
        emp["id"], {"expected_employee_version": emp["version"],
                    "base_salary_cents": 10_100_000}, ADMIN), 200)
    assert patched["version"] > emp["version"]
    res = api.approve_mapping_decision(
        md["id"], {"expected_employee_version": emp["version"]}, MANAGER)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = validate_success(api.get_mapping_decision(md["id"], MANAGER), 200)
    assert after["status"] == "COMP_TRIAGED"
    assert validate_success(api.get_department(ctx["department"]["id"], ADMIN), 200)["committed_pool_cents"] == 0


# ─── reversal: window + conserved payroll invariant ───────────────────

def _approved_mapping(ctx=None, salary=10_000_000):
    ctx = ctx or setup_published_band_pair()
    emp = create_employee(ctx, profile_rank=1, base_salary_cents=salary,
                          employee_ref="E1")
    md = create_triaged_mapping(ctx, emp, ctx["profiles"][2])
    md = get_success_data(api_client.approve_mapping_decision(
        md["id"], {"expected_employee_version": emp["version"]}, MANAGER))
    return ctx, emp, md


def test_reverse_window_expired(api):
    """PRD §3.7: "Reversing a decision — a `CompManager` act moving it from
    `APPROVED` to the terminal `REVERSED` state — is legal only while the
    logical clock is no later than thirty days after `approved_at` (later
    attempts are rejected with `ERR_REVERSE_WINDOW_EXPIRED`) and only while
    the program is in `MAPPING_OPEN` or `PUBLISHED` (a program that has moved
    on rejects with `ERR_PROGRAM_STATE_FORBIDS`)."

    Design: Corner/errors/reverse_window_expired
    """
    ctx, emp, md = _approved_mapping()
    set_clock("2026-09-01T00:00:00Z")  # 31 days past the 2026-08-01 approval.
    res = api.reverse_mapping_decision(md["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_REVERSE_WINDOW_EXPIRED, expected_status=422)
    after = validate_success(api.get_mapping_decision(md["id"], MANAGER), 200)
    assert after["status"] == "APPROVED"
    emp_after = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert emp_after["base_salary_cents"] == 11_050_000


def test_mapping_approve_then_reverse_conserves_payroll(api):
    """PRD §2.10: "Approving a mapping decision and later reversing it must
    leave the department's committed pool and the program's payroll projection
    exactly as they stood before the approval."
    PRD §3.7: "Reversal restores the employee's `base_salary_cents` from
    `pre_salary_cents`, restores the profile from `from_job_profile_id`,
    increments the employee's `version`, credits the department's
    `committed_pool_cents` by the `final_adjustment_cents` when it was
    positive, and recomputes both payroll rollups — so that approval followed
    by reversal leaves the payroll projection and the committed pool exactly
    as they stood, the conserved invariant of §2.10."

    Design: Difficulty/compensating_invariant/mapping_approve_reverse_conserves_payroll
    """
    ctx, emp, md = _approved_mapping()
    prog_mid = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
    assert prog_mid["total_payroll_projection_cents"] == 11_050_000
    emp_mid = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert emp_mid["base_salary_cents"] == 11_050_000
    assert emp_mid["job_profile_id"] == ctx["profiles"][2]["id"]
    dept_mid = validate_success(api.get_department(ctx["department"]["id"], ADMIN), 200)
    assert dept_mid["committed_pool_cents"] == 1_050_000
    reversed_md = validate_success(api.reverse_mapping_decision(md["id"], MANAGER), 200)
    assert reversed_md["status"] == "REVERSED"
    prog_after = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
    assert prog_after["total_payroll_projection_cents"] == 10_000_000
    emp_after = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert emp_after["base_salary_cents"] == 10_000_000
    assert emp_after["job_profile_id"] == ctx["profiles"][1]["id"]
    dept_after = validate_success(api.get_department(ctx["department"]["id"], ADMIN), 200)
    assert dept_after["committed_pool_cents"] == 0


def test_mapping_reverse_within_window_succeeds(api):
    """PRD §3.7: "An approval can be undone. Reversing a decision — a
    `CompManager` act moving it from `APPROVED` to the terminal `REVERSED`
    state — is legal only while the logical clock is no later than thirty days
    after `approved_at` (later attempts are rejected with
    `ERR_REVERSE_WINDOW_EXPIRED`) and only while the program is in
    `MAPPING_OPEN` or `PUBLISHED` (a program that has moved on rejects with
    `ERR_PROGRAM_STATE_FORBIDS`)."

    Design: Difficulty/compensating_invariant/mapping_approve_reverse_conserves_payroll
    """
    ctx, emp, md = _approved_mapping()
    # Same logical day — well within the 30-day window.
    res = api.reverse_mapping_decision(md["id"], MANAGER)
    reversed_md = validate_success(res, 200)
    assert reversed_md["status"] == "REVERSED"
    prog_after = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
    assert prog_after["total_payroll_projection_cents"] == 10_000_000
