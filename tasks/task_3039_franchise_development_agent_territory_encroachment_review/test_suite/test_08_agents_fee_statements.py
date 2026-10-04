"""Development agent underperformance cascade and fee statement dual-variant
split with conservation (PRD §3.1, §3.8, §2.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_franchisee,
    generate_fee_statement,
    get_fee_statement,
    get_impact_study,
    get_site_application,
    get_territory,
    setup_application_in_impact_review,
    setup_statement_scenario,
    validate_error,
    validate_success,
)


def test_underperformance_cascade_depth3(api, franchisor_ops_headers):
    """PRD §3.1: "Recording a strike against an agent already `UNDER_REVIEW` —
    the second strike within the trailing 24 months — increments the count to
    two and flips the agent to `UNDERPERFORMING`, which detonates a three-hop
    cascade: every territory assigned to that agent in `ASSIGNED` status moves
    to `REASSIGNMENT_PENDING`; every site application of such a territory
    sitting in `SUBMITTED` or `IMPACT_REVIEW` moves to `SUSPENDED`; and every
    `PROVISIONAL` impact study of a suspended application is voided."

    Design: Difficulty/transitive_cascade/underperformance_cascade_depth3
    """
    ctx = setup_application_in_impact_review()
    agent = ctx["agent"]
    first = validate_success(api.flag_underperformance(agent["id"], franchisor_ops_headers), 200)
    assert first["status"] == "UNDER_REVIEW"
    assert first["underperformance_strikes"] == 1
    second = validate_success(api.flag_underperformance(agent["id"], franchisor_ops_headers), 200)
    assert second["status"] == "UNDERPERFORMING"
    assert second["underperformance_strikes"] == 2
    territory = get_territory(ctx["territory"]["id"])
    assert territory["status"] == "REASSIGNMENT_PENDING"
    app = get_site_application(ctx["application"]["id"])
    assert app["status"] == "SUSPENDED"
    study = get_impact_study(ctx["study"]["id"])
    assert study["status"] == "VOID"


def test_first_strike_moves_agent_to_under_review_without_cascade(api, franchisor_ops_headers):
    """PRD §3.1: "Recording an underperformance strike against an `ACTIVE`
    agent increments `underperformance_strikes` by one and moves the agent to
    `UNDER_REVIEW`; clearing the review returns the agent to `ACTIVE`."

    Design: Difficulty/transitive_cascade/underperformance_cascade_depth3
    """
    ctx = setup_application_in_impact_review()
    agent = ctx["agent"]
    first = validate_success(api.flag_underperformance(agent["id"], franchisor_ops_headers), 200)
    assert first["status"] == "UNDER_REVIEW"
    assert first["underperformance_strikes"] == 1
    # Hop 1 does not fire on the first strike: the territory stays ASSIGNED.
    territory = get_territory(ctx["territory"]["id"])
    assert territory["status"] == "ASSIGNED"
    app = get_site_application(ctx["application"]["id"])
    assert app["status"] == "IMPACT_REVIEW"
    cleared = validate_success(api.clear_review(agent["id"], franchisor_ops_headers), 200)
    assert cleared["status"] == "ACTIVE"


def test_fee_statement_provisional_variant_includes_pipeline_estimates(api, franchisor_ops_headers):
    """PRD §3.8: "The provisional estimate is forward-looking: it sums over
    the territory's stores in `OPEN` or `PIPELINE` status, each store
    contributing its `estimated_weekly_sales_cents` multiplied by the
    territory's `royalty_rate_pct` multiplied by the number of whole weeks in
    the period, rounded half up to whole cents." and "The statement is born
    `PROVISIONAL` with `variant` set to `PROVISIONAL_ESTIMATE`."

    Design: Difficulty/dual_variant_calc/fee_statement_provisional_vs_final_variants_diverge
    """
    ctx = setup_statement_scenario()
    stmt = generate_fee_statement(ctx["agent"]["id"], ctx["territory"]["id"])
    assert stmt["status"] == "PROVISIONAL"
    assert stmt["variant"] == "PROVISIONAL_ESTIMATE"
    # The PRD pins the OPEN store's contribution exactly — its sales figures
    # are request fields (PRD §3.6): 1,000,000 x 0.08 x 4 weeks = 320,000.
    # The PIPELINE store's estimate is never fixed by the PRD, so the exact
    # gross is indeterminate; it must be at least the OPEN store's line.
    assert stmt["gross_fees_cents"] >= 320_000
    # 2 territory stores < 5 -> 40% tier (PRD §3.8).
    da_share_expected = round(stmt["gross_fees_cents"] * 0.40)
    assert stmt["da_share_cents"] == da_share_expected
    assert stmt["franchisor_share_cents"] == stmt["gross_fees_cents"] - da_share_expected


def test_fee_statement_final_variant_uses_open_actuals_only(api, franchisor_ops_headers):
    """PRD §3.8: "Finalizing the statement moves it to `FINALIZED`, flips
    `variant` to `FINAL_RECONCILIATION`, and recomputes gross fees
    chronologically against actuals: only `OPEN` stores contribute, each on
    its `actual_avg_weekly_sales_cents` under the same rate-and-weeks product
    and rounding; the same period therefore yields a different gross whenever
    estimates diverge from actuals."

    Design: Difficulty/dual_variant_calc/fee_statement_provisional_vs_final_variants_diverge
    """
    ctx = setup_statement_scenario()
    stmt = generate_fee_statement(ctx["agent"]["id"], ctx["territory"]["id"])
    finalized = validate_success(api.finalize_fee_statement(stmt["id"], franchisor_ops_headers), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["variant"] == "FINAL_RECONCILIATION"
    # Only the OPEN store: 1,000,000 x 0.08 x 4 = 320,000.
    assert finalized["gross_fees_cents"] == 320_000
    # The final variant drops the PIPELINE store's estimate (PRD §3.8 pins
    # only the final-variant input set; the provisional variant includes the
    # pipeline estimate, whose value the PRD leaves free), so the final gross
    # can only fall relative to the provisional figure.
    assert finalized["gross_fees_cents"] <= stmt["gross_fees_cents"]


def test_fee_share_conservation_across_finalize_and_settle(api, franchisor_ops_headers):
    """PRD §2.10: "`da_share_cents + franchisor_share_cents ==
    gross_fees_cents` holds at generation, at finalization, and is re-verified
    at settlement."
    PRD §3.8: "Settling a finalized statement re-verifies the invariant and
    moves the statement to terminal `SETTLED`."

    Design: Difficulty/compensating_invariant/fee_share_conservation_across_finalize_and_settle
    """
    ctx = setup_statement_scenario()
    stmt = generate_fee_statement(ctx["agent"]["id"], ctx["territory"]["id"])
    assert stmt["da_share_cents"] + stmt["franchisor_share_cents"] == stmt["gross_fees_cents"]
    finalized = validate_success(api.finalize_fee_statement(stmt["id"], franchisor_ops_headers), 200)
    assert finalized["da_share_cents"] + finalized["franchisor_share_cents"] == finalized["gross_fees_cents"]
    # Final variant: only the OPEN store contributes — 320,000 gross, split
    # 40/60 at the under-5-store tier (PRD §3.8).
    assert finalized["gross_fees_cents"] == 320_000
    assert finalized["da_share_cents"] == 128_000
    assert finalized["franchisor_share_cents"] == 192_000
    settled = validate_success(api.settle_fee_statement(stmt["id"], franchisor_ops_headers), 200)
    assert settled["status"] == "SETTLED"
    assert settled["da_share_cents"] + settled["franchisor_share_cents"] == settled["gross_fees_cents"]


def test_fee_share_conservation_franchisor_takes_rounding_remainder(api, franchisor_ops_headers):
    """PRD §2.10: "Rounding remainders are always allocated to the
    franchisor's share, never to the agent's, so `da_share_cents +
    franchisor_share_cents == gross_fees_cents` holds at generation, at
    finalization, and is re-verified at settlement."
    PRD §3.8: "`da_share_cents` is the gross multiplied by that percentage,
    rounded half up to whole cents, and `franchisor_share_cents` is the gross
    minus the agent's share"

    Design: Difficulty/compensating_invariant/fee_share_conservation_across_finalize_and_settle
    """
    ctx = setup_statement_scenario()
    stmt = generate_fee_statement(ctx["agent"]["id"], ctx["territory"]["id"])
    finalized = validate_success(api.finalize_fee_statement(stmt["id"], franchisor_ops_headers), 200)
    settled = validate_success(api.settle_fee_statement(stmt["id"], franchisor_ops_headers), 200)
    # At every step the conservation invariant holds.
    for snap in (stmt, finalized, settled):
        assert snap["da_share_cents"] + snap["franchisor_share_cents"] == snap["gross_fees_cents"]
    reloaded = get_fee_statement(stmt["id"])
    assert reloaded["status"] == "SETTLED"
    assert reloaded["da_share_cents"] + reloaded["franchisor_share_cents"] == 320_000


def test_fee_statement_overlapping_period_conflict(api, franchisor_ops_headers):
    """PRD §3.8: "no non-settled statement may already overlap the requested
    period for the same agent and territory, otherwise
    `ERR_FISCAL_PERIOD_OVERLAP`."
    PRD §3.8: "`period_start` (inclusive), and `period_end` (exclusive)"

    Design: Corner/validations/fee_statement_overlapping_period_conflict
    """
    ctx = setup_statement_scenario()
    generate_fee_statement(ctx["agent"]["id"], ctx["territory"]["id"],
                           period_start="2026-09-01T00:00:00Z",
                           period_end="2026-09-29T00:00:00Z")
    overlap = api.generate_fee_statement(
        {"development_agent_id": ctx["agent"]["id"], "territory_id": ctx["territory"]["id"],
         "period_start": "2026-09-15T00:00:00Z", "period_end": "2026-10-13T00:00:00Z"},
        franchisor_ops_headers,
    )
    validate_error(overlap, ApiErrorId.ERR_FISCAL_PERIOD_OVERLAP, 409)
    # Half-open semantics: starting exactly at the prior period_end is allowed.
    adjacent = api.generate_fee_statement(
        {"development_agent_id": ctx["agent"]["id"], "territory_id": ctx["territory"]["id"],
         "period_start": "2026-09-29T00:00:00Z", "period_end": "2026-10-27T00:00:00Z"},
        franchisor_ops_headers,
    )
    stmt_b = validate_success(adjacent, 201)
    assert stmt_b["status"] == "PROVISIONAL"
