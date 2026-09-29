"""Ordered-validation pairs: the higher-priority refusal must be the one reported."""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import (
    DEV_ACTIVE_DEVELOPMENT,
    EXCLUSIVITY_FREE,
    EXCLUSIVITY_HOLDING_DEAL,
    GUILD_TIER_LOW,
    HOLDING_ACTIVE,
    STEP_FIRST_DRAFT,
    STEP_STORY,
    TERM_IN_TERM,
)
from test_helpers import fixtures as fx
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    agency_rep_headers,
    business_affairs_headers,
    development_exec_headers,
)

# A slate deliberately too poor to fund the 33000000 pilot the tests attempt.
POOR_SLATE = {"total_dev_budget_cents": 30000000}
NIGHT_SHIFT_AGENCY = {"name": "Northgate Agency", "agency_code": "NGA"}
NIGHT_SHIFT_PITCH = {
    "title": "Night Shift",
    "logline": "An ER nurse moonlights as an arbitrator for the dead.",
    "underlying_ip_key": "IP-NIGHT-SHIFT",
}
NIGHT_SHIFT_RIGHTS = {"underlying_ip_key": "IP-NIGHT-SHIFT"}
NIGHT_SHIFT_WRITER = {
    "full_name": "Cleo Nunes",
    "guild_minimum_tier": GUILD_TIER_LOW,
    "quote_per_step_cents": 4000000,
}


def _night_shift(api, stage="project"):
    return build_scenario(
        api,
        stage,
        agency=dict(NIGHT_SHIFT_AGENCY),
        slate=dict(POOR_SLATE),
        writer=dict(NIGHT_SHIFT_WRITER),
        pitch=dict(NIGHT_SHIFT_PITCH),
        rights=dict(NIGHT_SHIFT_RIGHTS),
        coverage={"coverage_score": 74.0},
        deal={"steps": [f.step_spec(STEP_STORY, 4000000)], "guaranteed_step_count": 1},
    )


def test_the_project_state_refusal_outranks_the_pilot_budget_shortfall(api):
    """A pilot ordered on an ACTIVE_DEVELOPMENT project reports the state error, not the money.

    PRD 2.11: "authentication and authorisation first, then existence, then request
    shape, then state preconditions, then the two version checks, then rights and
    talent-safety rules, then temporal windows, then capacity and coherence constraints,
    and fiscal checks last of all."

    Design: Difficulty/priority_pair_validation_conflict/pilot_order_project_state_error_outranks_slate_budget_shortfall
    """
    ctx = _night_shift(api, "project")

    before = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert before["dev_status"] == DEV_ACTIVE_DEVELOPMENT

    response = api.create_pilot_order(
        f.pilot_order_payload(ctx.project_id, budget_cents=33000000),
        development_exec_headers(),
    )
    validate_error(response, e.ERR_INVALID_PROJECT_STATE, 409)

    pilots = validate_success(
        api.list_project_pilot_orders(ctx.project_id, business_affairs_headers())
    )
    assert pilots == [], "the refused order created no pilot row"

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=0, available=30000000)

    after = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert after["dev_status"] == DEV_ACTIVE_DEVELOPMENT
    assert after["version"] == before["version"], "a refused request moves no version"


def test_the_same_pilot_reports_the_shortfall_once_the_state_gate_clears(api):
    """With the project at SCRIPT_COMPLETE the lower-priority fiscal refusal surfaces.

    PRD 3.5: "the slate's `available_dev_cents` must cover the `budget_cents`
    (`ERR_SLATE_DEV_BUDGET_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/pilot_order_project_state_error_outranks_slate_budget_shortfall
    """
    ctx = _night_shift(api, "script_complete")

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=4000000, available=26000000)

    response = api.create_pilot_order(
        f.pilot_order_payload(ctx.project_id, budget_cents=33000000),
        development_exec_headers(),
    )
    validate_error(response, e.ERR_SLATE_DEV_BUDGET_EXCEEDED, 422)

    pilots = validate_success(
        api.list_project_pilot_orders(ctx.project_id, business_affairs_headers())
    )
    assert pilots == [], "no pilot row survives the fiscal refusal either"
    unchanged = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(unchanged, committed=4000000, available=26000000)


def _held_writer(api):
    """A HIGH-tier writer held IN_TERM by a rival slate, and a poor project slate."""
    ctx = build_scenario(
        api,
        "project",
        agency={"name": "Ridgeline Talent", "agency_code": "RDG"},
        slate={"total_dev_budget_cents": 5000000},
        writer={
            "full_name": "Ilya Marsh",
            "quote_per_step_cents": 7000000,
        },
        pitch={
            "title": "Hollow Point",
            "logline": "A ballistics examiner recognises her own rifle in a cold case.",
            "underlying_ip_key": "IP-HOLLOW-POINT",
        },
        rights={"underlying_ip_key": "IP-HOLLOW-POINT"},
        coverage={"coverage_score": 80.0},
    )
    ctx.slate2_id = fx.create_slate(
        api,
        {
            "platform": "CABLE",
            "season_year": 2027,
            "total_dev_budget_cents": 400000000,
            "pattern_budget_per_episode_cents": 28000000,
            "license_fee_cap_per_episode_cents": 26000000,
            "max_deficit_per_episode_cents": 6000000,
        },
    )["id"]
    ctx.holding_deal_id = fx.add_holding_deal(
        api,
        ctx,
        slate_id=ctx.slate2_id,
        start_date="2026-07-01",
        end_date="2027-07-01",
    )["id"]
    return ctx


def test_the_exclusivity_conflict_outranks_the_slate_dollar_shortfall(api):
    """A held writer on another slate's project reports exclusivity, never the budget.

    PRD 2.11: "A script deal against a writer held by another slate on a slate with no
    money left reports `ERR_WRITER_EXCLUSIVITY_CONFLICT`, not
    `ERR_SLATE_DEV_BUDGET_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/script_deal_writer_exclusivity_outranks_slate_budget_shortfall
    """
    ctx = _held_writer(api)

    hold = validate_success(
        api.get_holding_deal(ctx.holding_deal_id, business_affairs_headers())
    )
    assert hold["status"] == HOLDING_ACTIVE
    assert hold["term_state"] == TERM_IN_TERM
    writer = validate_success(
        api.get_writer(ctx.writer_id, agency_rep_headers(ctx.agency_id))
    )
    assert writer["exclusivity_status"] == EXCLUSIVITY_HOLDING_DEAL

    response = api.create_script_deal(
        f.script_deal_payload(
            ctx.project_id, ctx.writer_id, steps=[f.step_spec(STEP_FIRST_DRAFT, 8000000)]
        ),
        business_affairs_headers(),
    )
    validate_error(response, e.ERR_WRITER_EXCLUSIVITY_CONFLICT, 422)

    deals = validate_success(
        api.list_script_deals(business_affairs_headers(), {"project_id": ctx.project_id})
    )
    assert deals == [], "the refused deal created no row"

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=0, available=5000000)


def test_releasing_the_hold_exposes_the_dollar_shortfall_underneath(api):
    """Once the hold is terminated the writer is FREE and the same deal fails on money.

    PRD 3.4: "the slate's `available_dev_cents` must cover the deal's
    `guaranteed_commitment_cents`, else `ERR_SLATE_DEV_BUDGET_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/script_deal_writer_exclusivity_outranks_slate_budget_shortfall
    """
    ctx = _held_writer(api)

    validate_success(
        api.terminate_holding_deal(
            ctx.holding_deal_id,
            f.terminate_holding_deal_payload(),
            business_affairs_headers(),
        )
    )
    writer = validate_success(
        api.get_writer(ctx.writer_id, agency_rep_headers(ctx.agency_id))
    )
    assert writer["exclusivity_status"] == EXCLUSIVITY_FREE

    response = api.create_script_deal(
        f.script_deal_payload(
            ctx.project_id, ctx.writer_id, steps=[f.step_spec(STEP_FIRST_DRAFT, 8000000)]
        ),
        business_affairs_headers(),
    )
    validate_error(response, e.ERR_SLATE_DEV_BUDGET_EXCEEDED, 422)

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=0, available=5000000)
