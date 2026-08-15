"""Job profile lifecycle, FLSA gates, market survey/cut intake rules, and
uniqueness constraints (PRD §3.1-§3.4)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_approved_profile,
    create_department_payload,
    create_employee_payload,
    create_job_profile_payload,
    create_market_cut_payload,
    create_market_survey_payload,
    create_pay_band_payload,
    create_program,
    create_progression_policy_payload,
    get_success_data,
    setup_framework,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]
HRBP = TEST_USERS["hrbp_headers"]


def test_job_profile_revision_cycle_path_and_versions(api):
    """PRD §3.2: "Alternatively the manager returns the profile, moving it from
    `IN_REVIEW` back to `DRAFT` with an optional `reason`, opening a revision
    loop in which the profile may be re-determined and resubmitted."
    PRD §2.9: "The `version` is a system-managed integer that increments with
    every mutation of the resource, including system-driven mutations such as
    cascade side effects, and it is the field the optimistic-concurrency
    guards of §2.7 compare against."

    Design: Difficulty/non_linear_state_machine/job_profile_revision_cycle
    """
    fw = setup_framework()
    prof = get_success_data(api_client.create_job_profile(
        create_job_profile_payload(fw["family"]["id"], fw["levels"][0]["id"],
                                   title="SWE I", salary_basis_weekly_cents=200_000,
                                   duties_test_passed=True),
        ANALYST))
    assert prof["version"] == 1
    det = get_success_data(api_client.determine_flsa(prof["id"], ANALYST))
    assert det["flsa_classification"] == "EXEMPT"
    assert det["version"] == 2
    sub = get_success_data(api_client.submit_job_profile(prof["id"], ANALYST))
    assert sub["status"] == "IN_REVIEW" and sub["version"] == 3
    ret = get_success_data(api_client.return_job_profile(prof["id"], {"reason": "jd gaps"}, MANAGER))
    assert ret["status"] == "DRAFT" and ret["version"] == 4
    sub2 = get_success_data(api_client.submit_job_profile(prof["id"], ANALYST))
    assert sub2["status"] == "IN_REVIEW" and sub2["version"] == 5
    appr = get_success_data(api_client.approve_job_profile(prof["id"], MANAGER))
    assert appr["status"] == "APPROVED" and appr["version"] == 6


def test_job_profile_revise_resets_flsa(api):
    """PRD §3.2: "An approved profile can be reopened by a `CompAnalyst`
    through revision, which moves it from `APPROVED` back to `IN_REVIEW` and
    resets `flsa_classification` to `PENDING` with `flsa_determined_at` cleared
    to null, forcing the determination to run again before the profile can be
    re-approved; an optional `reason` may accompany the reopening."

    Design: Difficulty/non_linear_state_machine/job_profile_revision_cycle
    """
    fw = setup_framework()
    prof = create_approved_profile(fw["family"]["id"], fw["levels"][0]["id"])
    rev = get_success_data(api_client.revise_job_profile(
        prof["id"], {"reason": "scope update"}, ANALYST))
    assert rev["status"] == "IN_REVIEW"
    assert rev["flsa_classification"] == "PENDING"
    assert rev["flsa_determined_at"] is None
    assert rev["version"] == prof["version"] + 1
    get_success_data(api_client.determine_flsa(prof["id"], ANALYST))
    final = get_success_data(api_client.approve_job_profile(prof["id"], MANAGER))
    assert final["status"] == "APPROVED"
    assert final["version"] == prof["version"] + 3


def test_flsa_tests_incomplete_on_submit(api):
    """PRD §3.2: "Submitting a profile moves it from `DRAFT` to `IN_REVIEW` and
    is refused while `flsa_classification` is still `PENDING`, surfacing
    `ERR_FLSA_TESTS_INCOMPLETE` (HTTP 409)."

    Design: Corner/errors/flsa_tests_incomplete_on_submit
    """
    fw = setup_framework()
    prof = get_success_data(api_client.create_job_profile(
        create_job_profile_payload(fw["family"]["id"], fw["levels"][0]["id"]),
        ANALYST))
    res = api.submit_job_profile(prof["id"], ANALYST)
    validate_error(res, ApiErrorId.ERR_FLSA_TESTS_INCOMPLETE, expected_status=409)
    after = validate_success(api.get_job_profile(prof["id"], ANALYST), 200)
    assert after["status"] == "DRAFT"


def test_survey_rejected_is_terminal(api):
    """PRD §3.3: "A `CompManager` then disposes of it in one of two terminal
    directions: accepting a survey moves it to `ACCEPTED` and admits its cuts
    into the OFFICIAL pricing candidate sets, while rejecting it moves it to
    `REJECTED` and removes its cuts from all pricing candidate sets. Both
    outcomes are final."
    PRD §2.8 tier 7: "The requested action must be declared for the entity's
    current state (`ERR_INVALID_STATE_TRANSITION`, HTTP 409); an entity
    already in a terminal state accepts no further transitions
    (`ERR_ALREADY_TERMINAL`, HTTP 409)."

    Design: Corner/state_machines/survey_rejected_is_terminal
    """
    s = get_success_data(api_client.create_market_survey(
        create_market_survey_payload(name="S"), ANALYST))
    get_success_data(api_client.reject_market_survey(s["id"], MANAGER))
    res = api.accept_market_survey(s["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)
    after = validate_success(api.get_market_survey(s["id"], MANAGER), 200)
    assert after["status"] == "REJECTED"


def test_profile_retire_in_use_rejected(api):
    """PRD §3.2: "Finally, a `CompManager` may retire an approved profile,
    moving it from `APPROVED` to `RETIRED`, but only while no `ACTIVE`
    employee references it — retirement attempted against an in-use profile is
    rejected with `ERR_PROFILE_IN_USE` (HTTP 409)."

    Design: Corner/errors/profile_retire_in_use_rejected
    """
    fw = setup_framework(levels=(("P1", "Engineer I", 1),))
    prof = create_approved_profile(fw["family"]["id"], fw["levels"][0]["id"])
    dept = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    get_success_data(api_client.create_employee(
        create_employee_payload(dept["id"], prof["id"], fw["zone"]["id"],
                                employee_ref="E1"),
        HRBP))
    res = api.retire_job_profile(prof["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_PROFILE_IN_USE, expected_status=409)
    after = validate_success(api.get_job_profile(prof["id"], MANAGER), 200)
    assert after["status"] == "APPROVED"


def test_cut_separation_window_rejected(api):
    """PRD §3.3: "Intake enforces a spacing rule: two cuts for the same pairing
    of `job_profile_id` and `geo_zone_id` must be dated at least thirty days
    apart, and a cut that lands closer to an existing cut for the same pairing
    is rejected with `ERR_CUT_TOO_CLOSE` (HTTP 422)."

    Design: Corner/errors/cut_separation_window_rejected
    """
    fw = setup_framework(levels=(("P2", "Engineer II", 2),))
    prof = create_approved_profile(fw["family"]["id"], fw["levels"][0]["id"])
    survey = get_success_data(api_client.create_market_survey(
        create_market_survey_payload(name="S"), ANALYST))
    get_success_data(api_client.create_market_cut(
        create_market_cut_payload(survey["id"], prof["id"], fw["zone"]["id"],
                                  p50_cents=13_000_000, effective_date="2026-08-01"),
        ANALYST))
    res = api_client.create_market_cut(
        create_market_cut_payload(survey["id"], prof["id"], fw["zone"]["id"],
                                  p50_cents=13_100_000, effective_date="2026-08-10"),
        ANALYST)
    validate_error(res, ApiErrorId.ERR_CUT_TOO_CLOSE, expected_status=422)
    ok = api_client.create_market_cut(
        create_market_cut_payload(survey["id"], prof["id"], fw["zone"]["id"],
                                  p50_cents=13_100_000, effective_date="2026-08-31"),
        ANALYST)
    validate_success(ok, 201)


def test_duplicate_band_rejected(api):
    """PRD §3.4: "Only one band may exist per coordinate quadruple among bands
    that have not reached `SUPERSEDED`; a colliding creation is rejected with
    `ERR_DUPLICATE_BAND` (HTTP 409)."

    Design: Corner/errors/duplicate_band_rejected
    """
    fw = setup_framework()
    prog = create_program()
    validate_success(api_client.create_pay_band(
        create_pay_band_payload(prog["id"], fw["family"]["id"],
                                fw["levels"][0]["id"], fw["zone"]["id"]),
        ANALYST), 201)
    res = api_client.create_pay_band(
        create_pay_band_payload(prog["id"], fw["family"]["id"],
                                fw["levels"][0]["id"], fw["zone"]["id"],
                                target_percentile="P62_5", spread_pct=0.4000),
        ANALYST)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_BAND, expected_status=409)


def test_duplicate_policy_rejected(api):
    """PRD §3.1: "The policy is keyed by `job_family_id`, `from_level_id`, and
    `to_level_id`, where the `to_level_id` level's `rank_order` must exceed the
    `from_level_id` level's rank — a pairing in the wrong rank order is
    rejected with `ERR_INVALID_REQUEST` — and only one policy may exist per
    triple, duplicates failing as `ERR_DUPLICATE_POLICY` (HTTP 409)."

    Design: Corner/errors/duplicate_policy_rejected
    """
    fw = setup_framework()
    validate_success(api_client.create_progression_policy(
        create_progression_policy_payload(fw["family"]["id"], fw["levels"][0]["id"],
                                          fw["levels"][1]["id"]),
        MANAGER), 201)
    res = api_client.create_progression_policy(
        create_progression_policy_payload(fw["family"]["id"], fw["levels"][0]["id"],
                                          fw["levels"][1]["id"],
                                          min_midpoint_progression_pct=0.1500,
                                          max_overlap_pct=0.2000),
        MANAGER)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_POLICY, expected_status=409)
