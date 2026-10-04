"""Difficulty queue — cross-entity state dependencies.

A write on one entity is gated on the lifecycle state of a DIFFERENT entity:
shelf-recommendation creation requires an ACCEPTED CategoryAnalysis on the
plan (PRD §3.3/§3.4), and forecast publication requires the owning plan to be
ACTIVATED (PRD §3.7). Each test translates one difficulty-design instance and
cites the PRD rule it pins.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_forecast,
    assert_shelf_recommendation,
    create_submitted_analysis,
    get_plan_version,
    setup_activated_plan,
    setup_proposed_plan,
    validate_error,
    validate_success,
)

_WEEK_START = "2027-03-01T00:00:00Z"  # a Monday

_SHELF_REC_BODY = {"title": "Reset A", "space_change_pct": 5, "target_store_count": 100}


def test_shelf_rec_blocked_while_analysis_submitted(api, category_advisor_headers):
    """PRD §3.3: "Acceptance is more than courtesy: a plan must hold at least one `ACCEPTED` analysis before any shelf recommendation may be created against it (§3.4), and the plan's analysis list can be browsed filtered by `status`."
    PRD §3.4: "After authentication, scope, body shape, and existence have passed, the server first checks `expected_plan_version` against the plan's current `version` and answers `ERR_STALE_VERSION` (HTTP 412) on a mismatch; only then does it check that the plan's status is `ACCEPTED` or `ACTIVATED` — anything else fails with `ERR_PLAN_NOT_ACTIVATED` — and only then that the plan holds at least one `ACCEPTED` category analysis, failing with `ERR_ANALYSIS_NOT_ACCEPTED` (HTTP 409) when none exists."

    With the plan ACTIVATED and its only analysis still SUBMITTED, a create
    carrying the plan's live version is rejected ERR_ANALYSIS_NOT_ACCEPTED and
    persists nothing.

    Design: Difficulty/cross_entity_state_dependency/shelf_rec_requires_accepted_analysis
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    plan_version = get_plan_version(plan_id)
    create_submitted_analysis(plan_id)

    body = {"expected_plan_version": plan_version, **_SHELF_REC_BODY}
    validate_error(
        api.create_shelf_recommendation(plan_id, body, category_advisor_headers),
        ApiErrorId.ERR_ANALYSIS_NOT_ACCEPTED,
    )

    recs = validate_success(api.list_shelf_recommendations(plan_id, category_advisor_headers), 200)
    assert recs == [], f"the rejected create must persist nothing, got {recs}"


def test_analysis_acceptance_unlocks_identical_shelf_rec(api, category_advisor_headers):
    """PRD §3.3: "a `decision` of `ACCEPT` moves it `SUBMITTED → ACCEPTED`, a `decision` of `RETURN` moves it `SUBMITTED → RETURNED`, and either way the record's `version` increments."
    PRD §3.3: "Every analysis carries a computed `competitor_share_pct`, derived as 100 minus the `manufacturer_share_pct`, so the manufacturer's view of the category always accounts for the full hundred points."
    PRD §2.8: "That request must carry `expected_plan_version`, set to the `version` of the owning `JointBusinessPlan` the client last observed. If the plan's current `version` has advanced past the submitted value, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is created."

    Flipping the analysis SUBMITTED -> ACCEPTED touches only the analysis
    record, so the identical create — same expected_plan_version — now passes
    and lands PROPOSED.

    Design: Difficulty/cross_entity_state_dependency/shelf_rec_requires_accepted_analysis
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    plan_version = get_plan_version(plan_id)
    analysis = create_submitted_analysis(plan_id, manufacturer_share_pct=55)

    body = {"expected_plan_version": plan_version, **_SHELF_REC_BODY}
    validate_error(
        api.create_shelf_recommendation(plan_id, dict(body), category_advisor_headers),
        ApiErrorId.ERR_ANALYSIS_NOT_ACCEPTED,
    )

    accepted = validate_success(
        api.decide_category_analysis(analysis["id"], {"decision": "ACCEPT"}, scenario["buyer_headers"]),
        200,
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["competitor_share_pct"] == pytest.approx(45, abs=1e-6), (
        f"100 - 55 must read 45, got {accepted['competitor_share_pct']}"
    )
    assert get_plan_version(plan_id) == plan_version, (
        "accepting the analysis increments the analysis record's version only — "
        "the plan's version must be unmoved"
    )

    rec = validate_success(api.create_shelf_recommendation(plan_id, body, category_advisor_headers), 201)
    assert_shelf_recommendation(rec)
    assert rec["status"] == "PROPOSED"


def test_forecast_create_blocked_on_proposed_plan(api, supply_chain_planner_headers):
    """PRD §3.7: "A `SupplyChainPlanner` publishes a **Forecast** under a plan — the plan must be `ACTIVATED`, else `ERR_PLAN_NOT_ACTIVATED` — naming a `week_start` and a strictly positive `baseline_cases`, the manufacturer's statistical demand for that week."

    While the plan is still PROPOSED the publish is rejected
    ERR_PLAN_NOT_ACTIVATED and no forecast is persisted.

    Design: Difficulty/cross_entity_state_dependency/forecast_create_requires_activated_plan
    """
    scenario = setup_proposed_plan()
    plan_id = scenario["plan"]["id"]

    validate_error(
        api.create_forecast(
            plan_id, {"week_start": _WEEK_START, "baseline_cases": 1000}, supply_chain_planner_headers
        ),
        ApiErrorId.ERR_PLAN_NOT_ACTIVATED,
    )

    forecasts = validate_success(api.list_forecasts(plan_id, supply_chain_planner_headers), 200)
    assert forecasts == [], f"the rejected publish must persist nothing, got {forecasts}"


def test_forecast_create_unlocked_by_activation(api, supply_chain_planner_headers, manufacturer_planner_headers):
    """PRD §3.7: "A `SupplyChainPlanner` publishes a **Forecast** under a plan — the plan must be `ACTIVATED`, else `ERR_PLAN_NOT_ACTIVATED` — naming a `week_start` and a strictly positive `baseline_cases`, the manufacturer's statistical demand for that week."
    PRD §3.7: "Its publication axis, `pub_status`, begins at `PUBLISHED` and can end at `SUPERSEDED`; its commitment axis, `commit_status`, begins at `UNCOMMITTED` — with `committed_cases` and `committed_at` both null — and can reach `COMMITTED`."

    The identical publish fails while PROPOSED, then succeeds once the plan
    has moved PROPOSED -> ACCEPTED -> ACTIVATED, landing PUBLISHED /
    UNCOMMITTED.

    Design: Difficulty/cross_entity_state_dependency/forecast_create_requires_activated_plan
    """
    scenario = setup_proposed_plan()
    plan_id = scenario["plan"]["id"]
    payload = {"week_start": _WEEK_START, "baseline_cases": 1000}

    validate_error(
        api.create_forecast(plan_id, dict(payload), supply_chain_planner_headers),
        ApiErrorId.ERR_PLAN_NOT_ACTIVATED,
    )

    validate_success(
        api.decide_plan(plan_id, {"decision": "ACCEPT"}, scenario["buyer_headers"]), 200
    )
    validate_success(
        api.activate_plan(
            plan_id, {"accrual_rate_pct": 4, "edlp_split_pct": 60}, manufacturer_planner_headers
        ),
        200,
    )

    forecast = validate_success(
        api.create_forecast(plan_id, payload, supply_chain_planner_headers), 201
    )
    assert_forecast(forecast)
    assert forecast["pub_status"] == "PUBLISHED"
    assert forecast["commit_status"] == "UNCOMMITTED"
