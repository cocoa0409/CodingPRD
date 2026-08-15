"""Refresh cycles: apply cascade, half-open window rules, budget gate, not-due
timing, OCC on the program, RBAC on approval (PRD §2.6, §2.7, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_accepted_survey_with_cut,
    create_employee,
    create_pay_band_payload,
    create_refresh_cycle_payload,
    current_program_version,
    get_success_data,
    set_clock,
    setup_published_band_pair,
    setup_published_program,
    setup_refresh_approved,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]
FINANCE = TEST_USERS["finance_partner_headers"]
HRBP = TEST_USERS["hrbp_headers"]


def _refresh_scenario(employee_rows, cut_new_p50=11_000_000,
                      program_overrides=None):
    """PUBLISHED program with band P1 mid 10m (spread 0.30) when salaries are
    around 9m-13m; replacement cut 11m eff 2027-01-01; old cut excluded.

    employee_rows: list of (ref, salary, hire_date).
    """
    ctx = setup_published_program(p1_p50=10_000_000, p2_p50=13_000_000,
                                  program_overrides=program_overrides)
    emps = {}
    for ref, salary, hire in employee_rows:
        emps[ref] = create_employee(ctx, profile_rank=1, base_salary_cents=salary,
                                    hire_date=hire, employee_ref=ref)
    # New-era cut; the original S1 cut leaves the OFFICIAL candidate set.
    s2, _k2 = create_accepted_survey_with_cut(
        ctx["profiles"][1]["id"], ctx["zone"]["id"], cut_new_p50, sample_size=25,
        effective_date="2027-01-01", survey_year=2027, survey_name="S2")
    # Exclude the original cut (created inside setup_published_program).
    from test_helpers import validate_paginated
    cuts, _meta = validate_paginated(api_client.list_market_cuts(
        ANALYST, params={"job_profile_id": ctx["profiles"][1]["id"]}))
    old_cut = [c for c in cuts if c["market_survey_id"] != s2["id"]][0]
    get_success_data(api_client.set_cut_exclusion(
        old_cut["id"], {"excluded_from_composite": True}, ANALYST))
    rc = setup_refresh_approved(ctx)
    set_clock("2027-01-01T00:00:00Z")
    prog_v = current_program_version(ctx["program"]["id"])
    return ctx, emps, rc, prog_v


def test_refresh_rollup_impact_and_affected_count(api):
    """PRD §3.9: "Fourth, each employee's adjustment is the greater of zero and
    the replacement band's `min_cents` minus the employee's `base_salary_cents`
    — a bring-to-minimum raise — so an employee whose salary already exceeds
    the new maximum, the red-circle case, contributes zero. Fifth, the cycle's
    `budget_impact_cents` is the sum of those adjustments and
    `affected_employee_count` is the count of employees whose adjustment is
    nonzero."

    Design: Difficulty/transitive_cascade/refresh_apply_cascade_depth3
    """
    ctx, emps, rc, _v = _refresh_scenario(
        [("E1", 10_200_000, "2020-01-15"), ("E2", 10_500_000, "2019-06-01"),
         ("E3", 13_000_000, "2021-03-01"), ("E4", 9_000_000, "2018-01-01")])
    # New midpoint 11000000 -> new min 9350000; only E4 below it: +350000.
    assert rc["budget_impact_cents"] == 350_000
    assert rc["affected_employee_count"] == 1


def test_refresh_apply_cascade_depth3(api):
    """PRD §3.9: "Link one re-prices every `PUBLISHED` band of the program
    through the OFFICIAL variant as of the `effective_date` — with the same
    empty-candidate-set exclusion as the rollup — moves each re-priced band
    from `PUBLISHED` to `SUPERSEDED` with its `superseded_by_band_id` pointing
    at the replacement, and creates each replacement band directly in
    `PUBLISHED` status. Link two follows from those publications: every
    `ACTIVE` employee's `compa_ratio` and `range_position` is recomputed
    against the replacement band, bring-to-minimum raises are applied in the
    rollup's `hire_date`-then-`created_at` ordering, salaries above the new
    maximum are frozen by setting `red_circled` true, and each mutated
    employee's `version` increments. Link three follows from the
    range-position mutations: every employee who lands `ABOVE_MAX` receives an
    auto-created exception request of type `ABOVE_MAX_HIRE`, whose
    `requested_salary_cents` equals the employee's current salary, whose
    `created_by_user_id` is the literal `system`, and whose status opens at
    `SUBMITTED`."

    Design: Difficulty/transitive_cascade/refresh_apply_cascade_depth3
    """
    ctx, emps, rc, prog_v = _refresh_scenario(
        [("E1", 10_200_000, "2020-01-15"), ("E2", 10_500_000, "2019-06-01"),
         ("E3", 13_000_000, "2021-03-01"), ("E4", 9_000_000, "2018-01-01")])
    applied = validate_success(api.apply_refresh_cycle(
        rc["id"], {"expected_comp_program_version": prog_v}, MANAGER), 200)
    assert applied["status"] == "APPLIED"
    # Link 1: old band superseded; replacement published with new midpoint.
    old1 = validate_success(api.get_pay_band(ctx["band1"]["id"], ANALYST), 200)
    assert old1["status"] == "SUPERSEDED"
    assert old1["superseded_by_band_id"]
    replacement = validate_success(
        api.get_pay_band(old1["superseded_by_band_id"], ANALYST), 200)
    assert replacement["status"] == "PUBLISHED"
    assert replacement["midpoint_cents"] == 11_000_000
    assert replacement["min_cents"] == 9_350_000
    assert replacement["max_cents"] == 12_650_000
    # Link 2: E4 raised to min; E1/E2 unchanged; E3 red-circled ABOVE_MAX.
    e4 = validate_success(api.get_employee(emps["E4"]["id"], HRBP), 200)
    assert e4["base_salary_cents"] == 9_350_000
    assert e4["compa_ratio"] == pytest.approx(0.8500, abs=1e-9)
    assert e4["range_position"] == "IN_RANGE"
    e1 = validate_success(api.get_employee(emps["E1"]["id"], HRBP), 200)
    assert e1["base_salary_cents"] == 10_200_000
    e2 = validate_success(api.get_employee(emps["E2"]["id"], HRBP), 200)
    assert e2["base_salary_cents"] == 10_500_000
    e3 = validate_success(api.get_employee(emps["E3"]["id"], HRBP), 200)
    assert e3["base_salary_cents"] == 13_000_000
    assert e3["compa_ratio"] == pytest.approx(1.1818, abs=1e-9)
    assert e3["range_position"] == "ABOVE_MAX"
    assert e3["red_circled"] is True
    # Link 3: auto-created exception for the ABOVE_MAX employee.
    from test_helpers import validate_paginated
    xrs, meta = validate_paginated(api.list_exception_requests(
        ANALYST, params={"employee_id": emps["E3"]["id"]}))
    assert meta["total_count"] == 1
    assert xrs[0]["type"] == "ABOVE_MAX_HIRE"
    assert xrs[0]["requested_salary_cents"] == 13_000_000
    assert xrs[0]["status"] == "SUBMITTED"
    assert xrs[0]["created_by_user_id"] == "system"
    prog_after = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
    assert prog_after["refresh_budget_spent_cents"] == 350_000


def test_refresh_apply_leaves_draft_band_untouched(api):
    """PRD §3.9: "Link one re-prices every `PUBLISHED` band of the program
    through the OFFICIAL variant as of the `effective_date` — with the same
    empty-candidate-set exclusion as the rollup — moves each re-priced band
    from `PUBLISHED` to `SUPERSEDED` with its `superseded_by_band_id` pointing
    at the replacement, and creates each replacement band directly in
    `PUBLISHED` status."
    PRD §3.4: "A new band opens in `DRAFT` with `pricing_variant` null and with
    `market_composite_cents`, `composite_cut_count`, `midpoint_cents`,
    `min_cents`, `max_cents`, `geo_ratio_snapshot`, and `priced_at` all unset
    until the first pricing."

    Design: Corner/state_machines/refresh_apply_leaves_draft_band_untouched
    """
    # Band pair P1/P2 PUBLISHED; a second family hosts a never-priced DRAFT
    # band (PRD §3.4 forbids a duplicate quadruple among non-SUPERSEDED bands).
    ctx = setup_published_program(p1_p50=10_000_000, p2_p50=13_000_000)
    from test_helpers import create_job_family_payload
    fam2 = get_success_data(api_client.create_job_family(
        create_job_family_payload(code="OPS", name="Operations"), ADMIN))
    draft_band = get_success_data(api_client.create_pay_band(
        create_pay_band_payload(ctx["program"]["id"], fam2["id"],
                                ctx["levels"][1]["id"], ctx["zone"]["id"]),
        ANALYST))
    assert draft_band["status"] == "DRAFT"
    emp4 = create_employee(ctx, profile_rank=1, base_salary_cents=8_000_000,
                           hire_date="2020-01-15", employee_ref="E4")
    create_accepted_survey_with_cut(ctx["profiles"][1]["id"], ctx["zone"]["id"],
                                    11_000_000, sample_size=25,
                                    effective_date="2027-01-01", survey_year=2027,
                                    survey_name="S2")
    from test_helpers import validate_paginated
    cuts, _m = validate_paginated(api_client.list_market_cuts(
        ANALYST, params={"job_profile_id": ctx["profiles"][1]["id"]}))
    old_cut = [c for c in cuts if c["p50_cents"] == 10_000_000][0]
    get_success_data(api_client.set_cut_exclusion(
        old_cut["id"], {"excluded_from_composite": True}, ANALYST))
    # Exclude the P2 cut as well so band2's OFFICIAL candidate set is empty
    # (PRD §3.9: such a band "stays PUBLISHED and is not superseded").
    cuts2, _m2 = validate_paginated(api_client.list_market_cuts(
        ANALYST, params={"job_profile_id": ctx["profiles"][2]["id"]}))
    p2_cut = [c for c in cuts2 if c["p50_cents"] == 13_000_000][0]
    get_success_data(api_client.set_cut_exclusion(
        p2_cut["id"], {"excluded_from_composite": True}, ANALYST))
    rc = setup_refresh_approved(ctx)
    set_clock("2027-01-01T00:00:00Z")
    prog_v = current_program_version(ctx["program"]["id"])
    validate_success(api.apply_refresh_cycle(
        rc["id"], {"expected_comp_program_version": prog_v}, MANAGER), 200)
    old1 = validate_success(api.get_pay_band(ctx["band1"]["id"], ANALYST), 200)
    assert old1["status"] == "SUPERSEDED"
    replacement = validate_success(
        api.get_pay_band(old1["superseded_by_band_id"], ANALYST), 200)
    assert replacement["status"] == "PUBLISHED"
    assert replacement["min_cents"] == 9_350_000
    # band2 had OFFICIAL data but its P2 candidate set is now empty (only the
    # P1 replacement cut exists) -> excluded from refresh, stays PUBLISHED.
    band2_after = validate_success(api.get_pay_band(ctx["band2"]["id"], ANALYST), 200)
    assert band2_after["status"] == "PUBLISHED"
    # The never-priced DRAFT band is untouched by the refresh (§3.9 link one
    # re-prices only PUBLISHED bands; §3.4 fields stay unset until pricing).
    draft_after = validate_success(api.get_pay_band(draft_band["id"], ANALYST), 200)
    assert draft_after["status"] == "DRAFT"
    assert draft_after["midpoint_cents"] is None
    assert draft_after["version"] == draft_band["version"]
    e4 = validate_success(api.get_employee(emp4["id"], HRBP), 200)
    assert e4["base_salary_cents"] == 9_350_000


def test_refresh_window_half_open_adjacency(api):
    """PRD §2.6: "First, refresh scheduling: a refresh cycle's planned window
    is a half-open interval that begins at `planned_window_start` and ends at
    `planned_window_end`, with the end required to fall after the start; two
    windows for the same program conflict only when their half-open intervals
    genuinely overlap — one cycle's window beginning exactly where another's
    ends is adjacency, and adjacency is allowed."

    Design: Difficulty/resource_temporal_overlap/refresh_window_half_open_adjacency
    """
    ctx = setup_published_program()
    rc1 = validate_success(api.create_refresh_cycle(
        create_refresh_cycle_payload(ctx["program"]["id"],
                                     planned_window_start="2027-01-01",
                                     planned_window_end="2027-03-01",
                                     effective_date="2027-01-01"),
        MANAGER), 201)
    assert rc1["status"] == "SCHEDULED"
    rc2 = validate_success(api.create_refresh_cycle(
        create_refresh_cycle_payload(ctx["program"]["id"],
                                     planned_window_start="2027-03-01",
                                     planned_window_end="2027-05-01",
                                     effective_date="2027-04-01"),
        MANAGER), 201)
    assert rc2["status"] == "SCHEDULED"


def test_refresh_window_overlap_rejected(api):
    """PRD §3.9: "Scheduling is posture-gated to `PUBLISHED` programs and
    conflict-checked against the program's other cycles: a new window that
    overlaps any non-terminal cycle of the same program — one in `SCHEDULED`,
    `IMPACT_COMPUTED`, or `APPROVED` — is rejected with
    `ERR_REFRESH_WINDOW_CONFLICT` (HTTP 409), while windows that merely touch,
    one beginning exactly where another ends, are adjacency and allowed."

    Design: Difficulty/resource_temporal_overlap/refresh_window_half_open_adjacency
    """
    ctx = setup_published_program()
    validate_success(api.create_refresh_cycle(
        create_refresh_cycle_payload(ctx["program"]["id"]), MANAGER), 201)
    validate_success(api.create_refresh_cycle(
        create_refresh_cycle_payload(ctx["program"]["id"],
                                     planned_window_start="2027-03-01",
                                     planned_window_end="2027-05-01",
                                     effective_date="2027-04-01"),
        MANAGER), 201)
    res = api.create_refresh_cycle(
        create_refresh_cycle_payload(ctx["program"]["id"],
                                     planned_window_start="2027-02-15",
                                     planned_window_end="2027-04-01",
                                     effective_date="2027-03-15"),
        MANAGER)
    validate_error(res, ApiErrorId.ERR_REFRESH_WINDOW_CONFLICT, expected_status=409)


def test_refresh_budget_exact_equality(api):
    """PRD §3.9: "A `FinancePartner` approves a computed cycle, moving it from
    `IMPACT_COMPUTED` to `APPROVED`, only when the `budget_impact_cents` is no
    more than the program's `refresh_budget_cents` — integer cents compared
    exactly, with equality passing — and an overrun is rejected with
    `ERR_BUDGET_IMPACT_EXCEEDS` (HTTP 422)."

    Design: Corner/calculations/refresh_budget_exact_equality
    """
    ctx = setup_published_program(p1_p50=10_000_000, p2_p50=13_000_000,
                                  program_overrides={"refresh_budget_cents": 849_999})
    create_employee(ctx, profile_rank=1, base_salary_cents=8_500_000,
                    hire_date="2020-01-15", employee_ref="E1")
    create_accepted_survey_with_cut(ctx["profiles"][1]["id"], ctx["zone"]["id"],
                                    11_000_000, sample_size=25,
                                    effective_date="2027-01-01", survey_year=2027,
                                    survey_name="S2")
    from test_helpers import validate_paginated
    cuts, _m = validate_paginated(api_client.list_market_cuts(
        ANALYST, params={"job_profile_id": ctx["profiles"][1]["id"]}))
    old_cut = [c for c in cuts if c["p50_cents"] == 10_000_000][0]
    get_success_data(api_client.set_cut_exclusion(
        old_cut["id"], {"excluded_from_composite": True}, ANALYST))
    rc = get_success_data(api_client.create_refresh_cycle(
        create_refresh_cycle_payload(ctx["program"]["id"]), MANAGER))
    rc = get_success_data(api_client.compute_refresh_impact(rc["id"], ANALYST))
    assert rc["budget_impact_cents"] == 850_000
    res = api.approve_refresh_cycle(rc["id"], FINANCE)
    validate_error(res, ApiErrorId.ERR_BUDGET_IMPACT_EXCEEDS, expected_status=422)
    get_success_data(api_client.patch_program(
        ctx["program"]["id"], {"refresh_budget_cents": 850_000}, ADMIN))
    approved = validate_success(api.approve_refresh_cycle(rc["id"], FINANCE), 200)
    assert approved["status"] == "APPROVED"


def test_refresh_apply_before_effective_date(api):
    """PRD §2.6: "Second, refresh timing: a cycle may be applied only when the
    logical clock's current date is on or after the cycle's `effective_date`;
    an earlier attempt is rejected with `ERR_REFRESH_NOT_DUE` (HTTP 409)."

    Design: Corner/errors/refresh_apply_before_effective_date
    """
    ctx = setup_published_program()
    rc = setup_refresh_approved(ctx)
    prog_v = current_program_version(ctx["program"]["id"])
    # Logical clock still at the 2026-08-01 startup default.
    res = api.apply_refresh_cycle(
        rc["id"], {"expected_comp_program_version": prog_v}, MANAGER)
    validate_error(res, ApiErrorId.ERR_REFRESH_NOT_DUE, expected_status=409)
    after = validate_success(api.get_refresh_cycle(rc["id"], MANAGER), 200)
    assert after["status"] == "APPROVED"


def test_occ_refresh_apply_stale_program(api):
    """PRD §2.7: "Applying a refresh cycle requires
    `expected_comp_program_version` matching the program's current `version`;
    a mismatch means band or budget mutations under a newer program version
    invalidate the approved impact rollup, and the apply is refused with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_refresh_apply_stale_program
    """
    ctx = setup_published_program()
    rc = setup_refresh_approved(ctx)
    prog_v = current_program_version(ctx["program"]["id"])
    patched = validate_success(api.patch_program(
        ctx["program"]["id"], {"merit_budget_cents": 60_000_000}, ADMIN), 200)
    assert patched["version"] > prog_v
    res = api.apply_refresh_cycle(
        rc["id"], {"expected_comp_program_version": prog_v}, MANAGER)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = validate_success(api.get_refresh_cycle(rc["id"], MANAGER), 200)
    assert after["status"] == "APPROVED"


def test_comp_manager_cannot_approve_refresh(api):
    """PRD §2.1: "Every endpoint declares the roles permitted to call it; an
    authenticated caller whose role is not listed for the endpoint is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /comp/refresh-cycles/{id}/approve lists only FinancePartner.

    Design: Corner/rbac/comp_manager_cannot_approve_refresh
    """
    ctx = setup_published_program()
    rc = get_success_data(api_client.create_refresh_cycle(
        create_refresh_cycle_payload(ctx["program"]["id"]), MANAGER))
    res = api.approve_refresh_cycle(rc["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
    after = validate_success(api.get_refresh_cycle(rc["id"], MANAGER), 200)
    assert after["status"] == "SCHEDULED"
