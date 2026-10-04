"""Validation ordering across competing checks (PRD §2.9)."""
from test_helpers import (
    ApiErrorId,
    create_comment_payload,
    create_draft_plan_with_basics,
    create_plan,
    add_forecast,
    add_portfolio,
    commission_review,
    compute_snapshot,
    drive_plan_to_under_review,
    issue_commitment,
    list_plan_conditions,
    register_candidate,
    register_resource,
    set_clock,
    validate_error,
)
from test_helpers.constants import CLOCK_AUG_01, CLOCK_AUG_31, CLOCK_SEP_05, CLOCK_OCT_01
from test_helpers.fixtures import PLANNER, COMMENTER


def test_state_gate_beats_temporal_window_on_comment(api):
    """PRD §2.9: "then existence of every path and body-referenced identifier (the 404
    family, validated left to right), then optimistic-concurrency staleness (the 412
    family) on the two guarded endpoints, then state gates (the 409 state family:
    plan-status gates, frozen portfolios, locked forecasts, commitment and testimony
    state), then temporal window checks (comment window, retirement lead time, cycle
    deadline, candidate online year, forecast horizon — the 422 temporal family), then
    structural uniqueness constraints (duplicate snapshot, report, forecast,
    preferred-portfolio conflict, duplicate names, nameplate overcommit, duplicate
    position), then cross-entity referential checks (eligible-candidate, snapshot-plan
    mismatch, intervenor standing, referential integrity), and finally the reliability
    and fiscal gates on plan transitions (preferred-portfolio presence, reliability
    met, reopen limit, base-forecast and portfolio presence). A call failing an earlier
    check never surfaces a later one."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_comment
    """
    set_clock(CLOCK_AUG_01)
    plan, _portfolio = create_draft_plan_with_basics(plan_name="IRP Prio1")
    drive_plan_to_under_review(plan["id"], clock_submit_date=CLOCK_SEP_05)

    # Plan is UNDER_REVIEW AND the clock is past the comment window: both the state
    # gate and the temporal check could reject; the earlier state gate wins.
    resp = api.create_comment(
        plan["id"],
        create_comment_payload(commenter_name="Jane Public",
                               commenter_email="jane@example.org",
                               body="Too much gas."),
        COMMENTER,
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_OPEN_FOR_COMMENT)


def test_state_gate_beats_temporal_window_on_comment_late_clock(api):
    """PRD §2.9: "When several checks could reject the same call, they are evaluated in
    a fixed priority order so that the surfaced error is deterministic."
    PRD §3.10: "Filing is gated twice: the plan must be in `OPEN_FOR_COMMENT` status
    (otherwise `ERR_PLAN_NOT_OPEN_FOR_COMMENT`, HTTP 409), and the clock's calendar date
    must fall within the comment window inclusive of both ends — a comment filed on the
    closing date itself is accepted, while one filed before the window opens or after it
    closes is rejected with `ERR_COMMENT_WINDOW_CLOSED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_comment
    """
    set_clock(CLOCK_AUG_01)
    plan, _portfolio = create_draft_plan_with_basics(plan_name="IRP Prio1b")
    # Window [2026-08-01, 2026-08-31]; submit on 2026-08-31, then move past it.
    drive_plan_to_under_review(plan["id"], clock_submit_date=CLOCK_AUG_31)
    set_clock(CLOCK_SEP_05)

    resp = api.create_comment(plan["id"], create_comment_payload(), COMMENTER)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_OPEN_FOR_COMMENT)
    assert resp.status_code == 409


def _approve_plan(name, cycle_year, forecast_year=2031, load=400, conditions=None):
    """Drive one plan to an approved state and return (plan, portfolio).

    Clock discipline: the cycle filing deadline is September 1 of the plan's
    `cycle_year` (PRD §2.4), and the logical clock only ever moves forward across
    the calls in one test — so the plan opens at Jan 1 of its cycle year when the
    clock has not passed it, and at the current clock date otherwise; submission
    follows thirty days later.
    """
    from datetime import date as _date, timedelta as _td
    from test_helpers.fixtures import _current_clock_date
    now = _current_clock_date()
    open_date = max(_date(cycle_year, 1, 1), now)
    submit_date = open_date + _td(days=30)
    set_clock(f"{open_date.isoformat()}T00:00:00Z")
    plan = create_plan(plan_name=name, cycle_year=cycle_year, planning_horizon_years=15)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=forecast_year,
                 residential_mw=load)
    portfolio = add_portfolio(plan["id"], preferred_flag=True)
    register_resource(resource_type="SOLAR", nameplate_mw=1150, in_service_year=2020,
                      fuel_type="SUN")
    snapshot = compute_snapshot(portfolio["id"], forecast_year=forecast_year)
    assert snapshot["meets_requirement"] is True, f"Setup failed: {snapshot}"
    drive_plan_to_under_review(plan["id"],
                               clock_submit_date=f"{submit_date.isoformat()}T00:00:00Z")
    decision = "APPROVE_WITH_CONDITIONS" if conditions else "APPROVE"
    resp = commission_review(plan["id"], decision, conditions=conditions)
    assert resp.status_code == 200, f"Setup failed: review -> {resp.text}"
    return plan, portfolio


def test_nameplate_breach_beats_cross_plan_condition_reference(api):
    """PRD §2.8: "Body-referenced identifiers (`snapshot_id`, `candidate_id`, `plan_id`,
    condition ids) are validated for existence in the same pass."
    PRD §2.9: "then existence of every path and body-referenced identifier (the 404
    family, validated left to right), then optimistic-concurrency staleness (the 412
    family) on the two guarded endpoints, then state gates (the 409 state family:
    plan-status gates, frozen portfolios, locked forecasts, commitment and testimony
    state), then temporal window checks (comment window, retirement lead time, cycle
    deadline, candidate online year, forecast horizon — the 422 temporal family), then
    structural uniqueness constraints (duplicate snapshot, report, forecast,
    preferred-portfolio conflict, duplicate names, nameplate overcommit, duplicate
    position), then cross-entity referential checks (eligible-candidate, snapshot-plan
    mismatch, intervenor standing, referential integrity), and finally the reliability
    and fiscal gates on plan transitions (preferred-portfolio presence, reliability met,
    reopen limit, base-forecast and portfolio presence). A call failing an earlier check
    never surfaces a later one."
    PRD §3.9: "Every listed condition must belong to the same plan as the commitment; a
    condition id that does not exist or belongs to a different plan is rejected with
    `ERR_CONDITION_NOT_FOUND` (HTTP 404), and other cross-plan referential failures
    surface as `ERR_REFERENTIAL_INTEGRITY`."

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_referential_on_commitment
    """
    set_clock(CLOCK_AUG_01)
    candidate = register_candidate(
        candidate_name="K-LIMITED", resource_type="GAS_CT", nameplate_mw=300,
        online_year=2028, capex_usd_per_kw=700, fixed_om_usd_per_kw_year=12,
        fuel_type="NATURAL_GAS", build_lead_years=2,
    )
    plan_a, _pfa = _approve_plan(
        "IRP A", 2026,
        conditions=[{"description": "B-condition misfiled here",
                     "required_procurement_mw": 50}],
    )
    cond_a = list_plan_conditions(plan_a["id"])[0]
    plan_b, _pfb = _approve_plan("IRP B", 2027)

    # 250 MW of the candidate's 300 MW nameplate is already ISSUED under plan A.
    issue_commitment(plan_a["id"], candidate_id=candidate["id"], committed_mw=250)

    # This issue both breaches the nameplate cap (250 + 100 > 300) and lists a
    # condition of another plan; the earlier existence check on the body-referenced
    # condition id wins (404 family precedes structural uniqueness, PRD §2.9).
    resp = api.create_commitment(
        plan_b["id"],
        {"candidate_id": candidate["id"], "committed_mw": 100,
         "solicitation_type": "RFP", "condition_discharge_ids": [cond_a["id"]]},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_CONDITION_NOT_FOUND)


def test_nameplate_breach_beats_cross_plan_condition_reference_at_capacity(api):
    """PRD §2.9: "When several checks could reject the same call, they are evaluated in
    a fixed priority order so that the surfaced error is deterministic."
    PRD §3.9: "The aggregate committed megawatts per candidate across all commitments in
    `ISSUED` or `AWARDED` status must never exceed the candidate's `nameplate_mw`; an
    issue that would breach the cap is rejected with `ERR_NAMEPLATE_EXCEEDED`, and an
    issue naming a candidate with no feasible remaining capacity is rejected with
    `ERR_NO_ELIGIBLE_CANDIDATE` (HTTP 422)."
    PRD §3.9: "Every listed condition must belong to the same plan as the commitment; a
    condition id that does not exist or belongs to a different plan is rejected with
    `ERR_CONDITION_NOT_FOUND` (HTTP 404), and other cross-plan referential failures
    surface as `ERR_REFERENTIAL_INTEGRITY`."

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_referential_on_commitment
    """
    set_clock(CLOCK_AUG_01)
    candidate = register_candidate(
        candidate_name="K-LIMITED2", resource_type="GAS_CT", nameplate_mw=300,
        online_year=2028, capex_usd_per_kw=700, fixed_om_usd_per_kw_year=12,
        fuel_type="NATURAL_GAS", build_lead_years=2,
    )
    plan_a, _pfa = _approve_plan(
        "IRP A2", 2026,
        conditions=[{"description": "Cross-plan condition", "required_procurement_mw": 50}],
    )
    cond_a = list_plan_conditions(plan_a["id"])[0]
    plan_b, _pfb = _approve_plan("IRP B2", 2027)

    # Exactly 300 MW already ISSUED — the candidate has zero remaining capacity, so
    # even a 1 MW issue breaches the cap while also listing another plan's condition.
    issue_commitment(plan_a["id"], candidate_id=candidate["id"], committed_mw=300)

    # The body-referenced cross-plan condition id fails the earlier existence check
    # (404 family precedes structural uniqueness, PRD §2.9; PRD §3.9 maps a
    # cross-plan condition to ERR_CONDITION_NOT_FOUND).
    resp = api.create_commitment(
        plan_b["id"],
        {"candidate_id": candidate["id"], "committed_mw": 1,
         "solicitation_type": "RFP", "condition_discharge_ids": [cond_a["id"]]},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_CONDITION_NOT_FOUND)
