"""Boundary and terminal behaviour: window attainment at the exact requirement,
extension caps, the empty orphan selector pool, credit voiding and the office
close guard."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    fetch_advisor,
    fetch_credits,
    fetch_policy,
    fetch_window,
    get_success_data,
    new_candidate,
    new_office,
    new_policy,
    open_validation_window,
    any_headers,
    md_headers,
    ro_headers,
    set_clock,
    setup_contracted_rep,
    setup_orphaned_policy,
    validate_error,
    validate_success,
)


def _contracted_with_credit(office_id: str, premium: int, requirement: int):
    """A contracted, licensed representative plus a window and a policy."""
    ctx = setup_contracted_rep(office_id, name=f"Boundary {premium}", mode="PRODUCTION_DRAW",
                               validation_requirement_cents=300000)
    window = open_validation_window(ctx["contract"]["id"], period_number=1,
                                    start_date="2026-01-08T00:00:00Z",
                                    end_date="2026-12-31T00:00:00Z",
                                    required_production_cents=requirement)
    policy = new_policy(ctx["advisor"]["id"], annual_premium_cents=premium,
                        policy_number=f"NM-BND-{premium}", issue_date="2026-02-01T00:00:00Z")
    ctx.update({"window": window, "policy": policy})
    return ctx


def test_attainment_equal_to_the_requirement_is_met():
    """PRD §3.4: "Evaluating an `OPEN` window whose attainment reaches or
    exceeds its `required_production_cents` passes it."

    Design: Difficulty/boundary_precision_check/duplicated_live_credit_boolean_boundary_at_validation
    """
    set_clock()
    office = new_office()
    ctx = _contracted_with_credit(office["id"], premium=510000, requirement=204000)

    evaluated = validate_success(api_client.evaluate_validation_period(ctx["window"]["id"], md_headers))
    assert evaluated["achieved_production_cents"] == 204000
    assert evaluated["status"] == "PASSED"

    advisor = fetch_advisor(ctx["advisor"]["id"])
    assert advisor["contract_status"] == "VALIDATED"
    assert advisor["validation_posture"] == "VALIDATED"


def test_voiding_the_credit_removes_it_from_the_live_set():
    """PRD §3.6: "voiding sets it to `VOIDED`, sets its `gross_commission_cents`
    to zero, and recomputes the advisor's `team_production_cents`."
    PRD §3.4: "`CHARGED_BACK` credits count here, unlike in the
    training-allowance test."

    Design: Difficulty/boundary_precision_check/duplicated_live_credit_boolean_boundary_at_validation
    """
    set_clock()
    office = new_office()
    ctx = _contracted_with_credit(office["id"], premium=510000, requirement=204000)

    validate_success(api_client.evaluate_validation_period(ctx["window"]["id"], md_headers))
    primary = [c for c in fetch_credits(ctx["policy"]["id"])
               if c["credit_type"] == "PRIMARY"][0]

    voided = validate_success(api_client.void_commission_credit(primary["id"], md_headers))
    assert voided["status"] == "VOIDED"
    assert voided["gross_commission_cents"] == 0

    advisor = fetch_advisor(ctx["advisor"]["id"])
    assert advisor["team_production_cents"] == 0

    passed_windows = validate_success(api_client.list_advisor_validation_periods(
        ctx["advisor"]["id"], any_headers, {"status": "PASSED"}))
    passed_windows = passed_windows if isinstance(passed_windows, list) else passed_windows.get("data", [])
    assert len(passed_windows) == 1, "a passed window is not retroactively re-evaluated"


def test_an_empty_orphan_pool_is_rejected_and_the_policy_stays_orphaned():
    """PRD §3.8: "When the pool is empty, the operation does not silently no-op
    and never falls back to the terminated advisor: the assignment's `status`
    becomes `REJECTED`, its `rejection_reason` is recorded as
    `NO_ELIGIBLE_ADVISOR`, and the policy's `orphaned` flag remains true."

    Design: Difficulty/boundary_precision_check/empty_orphan_candidate_pool_returns_422
    """
    set_clock()
    office = new_office()
    ctx = setup_orphaned_policy(office["id"], annual_premium_cents=510000, activate_policy=True)

    assignment = ctx["assignment"]
    assert assignment["status"] == "PENDING"
    assert assignment["to_advisor_id"] is None

    refused = api_client.assign_orphan_policy(assignment["id"], md_headers)
    validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_ADVISOR.value)

    after = get_success_data(api_client.get_orphan_assignment(assignment["id"], any_headers))
    assert after["status"] == "REJECTED"
    assert after["rejection_reason"] == "NO_ELIGIBLE_ADVISOR"
    assert after["to_advisor_id"] is None

    assert fetch_policy(ctx["policy"]["id"])["orphaned"] is True


def test_the_substitute_is_excluded_from_the_pool_because_it_is_not_contracted():
    """PRD §3.8: "an eligible advisor is one whose `district_office_id` equals
    the writing office of the policy being reassigned; whose `contract_status`
    is `VALIDATING` or `VALIDATED`; whose `validation_posture` is `VALIDATING`
    or `VALIDATED`; whose `appointment_status` is `APPROVED`; and whose `id`
    differs from the assignment's `from_advisor_id`."

    Design: Difficulty/boundary_precision_check/empty_orphan_candidate_pool_returns_422
    """
    set_clock()
    office = new_office()
    ctx = setup_orphaned_policy(office["id"], annual_premium_cents=510000, activate_policy=True)

    substitute = fetch_advisor(ctx["substitute"]["id"])
    assert substitute["contract_status"] == "NOT_CONTRACTED"
    assert substitute["orphan_pool_access"] is False

    refused = api_client.assign_orphan_policy(ctx["assignment"]["id"], md_headers)
    validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_ADVISOR.value)


def test_the_validation_window_extension_loop_is_capped():
    """PRD §3.4: "Attempting to extend a window whose `extension_count` has
    reached the maximum of two is refused with
    `ERR_EXTENSION_LIMIT_REACHED`."

    Design: Corner/state_machines/validation_period_extension_loop_is_capped
    """
    set_clock()
    office = new_office()
    ctx = setup_contracted_rep(office["id"], name="Sara Extend", mode="FLAT_MONTHLY")
    window = open_validation_window(ctx["contract"]["id"], period_number=1,
                                    start_date="2026-09-04T00:00:00Z",
                                    end_date="2026-12-31T00:00:00Z",
                                    required_production_cents=100000)

    first = validate_success(api_client.extend_validation_period(
        window["id"], "2027-03-31T00:00:00Z", md_headers))
    assert first["status"] == "EXTENDED"
    assert first["extension_count"] == 1
    assert first["end_date"].startswith("2027-03-31")
    assert first["extended_end_date"].startswith("2027-03-31")

    second = validate_success(api_client.extend_validation_period(
        window["id"], "2027-06-30T00:00:00Z", md_headers))
    assert second["status"] == "EXTENDED"
    assert second["extension_count"] == 2

    refused = api_client.extend_validation_period(window["id"], "2027-09-30T00:00:00Z", md_headers)
    validate_error(refused, ApiErrorId.ERR_EXTENSION_LIMIT_REACHED.value)

    unchanged = fetch_window(window["id"])
    assert unchanged["extension_count"] == 2, "the refused call did not increment the counter"


def test_a_second_overlapping_validation_window_is_rejected():
    """PRD §2.8: "A new window must not overlap an existing `OPEN` or
    `EXTENDED` window of the same contract, and a violation is refused with
    `ERR_VALIDATION_WINDOW_OVERLAP`. Because the convention is half-open, two
    windows that merely touch at a shared boundary instant are adjacent rather
    than overlapping and are allowed."

    Design: Corner/validations/second_overlapping_validation_window_is_rejected
    """
    set_clock()
    office = new_office()
    ctx = setup_contracted_rep(office["id"], name="Gus Window", mode="FLAT_MONTHLY")
    first = open_validation_window(ctx["contract"]["id"], period_number=1,
                                   start_date="2026-01-08T00:00:00Z",
                                   end_date="2026-06-30T00:00:00Z",
                                   required_production_cents=100000)

    touching = open_validation_window(ctx["contract"]["id"], period_number=2,
                                      start_date="2026-06-30T00:00:00Z",
                                      end_date="2026-12-31T00:00:00Z",
                                      required_production_cents=100000)
    assert touching["status"] == "OPEN"

    contract = get_success_data(api_client.get_employment_contract(ctx["contract"]["id"], any_headers))
    overlapping = api_client.open_validation_period({
        "contract_id": ctx["contract"]["id"],
        "period_number": 3,
        "start_date": "2026-06-29T23:59:59Z",
        "end_date": "2026-12-31T00:00:00Z",
        "required_production_cents": 100000,
        "expected_contract_version": contract["version"],
    }, md_headers)
    validate_error(overlapping, ApiErrorId.ERR_VALIDATION_WINDOW_OVERLAP.value)

    open_windows = validate_success(api_client.list_contract_validation_periods(
        ctx["contract"]["id"], any_headers, {"status": "OPEN"}))
    open_windows = open_windows if isinstance(open_windows, list) else open_windows.get("data", [])
    assert len(open_windows) == 2

    unchanged = fetch_window(first["id"])
    assert unchanged["end_date"].startswith("2026-06-30")


def test_advance_to_interview_is_blocked_by_a_failing_latest_assessment():
    """PRD §3.1: "When that outcome is `FAIL`, the advance is refused with
    `ERR_ASSESSMENT_NOT_PASSED`."

    Design: Corner/state_machines/advance_to_interview_blocked_by_a_failing_latest_assessment
    """
    set_clock()
    office = new_office()
    candidate = new_candidate(office["id"], name="Owen Fail")
    candidate = validate_success(api_client.screen_candidate(candidate["id"], ro_headers))
    assessment = validate_success(api_client.schedule_assessment(
        candidate["id"], {"assessment_version": "V2", "scheduled_date": "2026-09-02T00:00:00Z"},
        ro_headers))
    scored = validate_success(api_client.score_assessment(
        assessment["id"],
        {"raw_score": 30, "competency_scores": {"MARKET_KNOWLEDGE": 2, "RELATIONSHIP": 3,
                                                "RESILIENCE": 4, "ETHICS": 3}}, ro_headers))
    assert scored["outcome"] == "FAIL"

    refused = api_client.advance_to_interview(candidate["id"], ro_headers)
    validate_error(refused, ApiErrorId.ERR_ASSESSMENT_NOT_PASSED.value)

    assert get_success_data(api_client.get_candidate(candidate["id"], any_headers))["stage"] == "ASSESSED"