"""Translation effort and localization cost arithmetic."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users


def test_scope_estimate_variant_reads_the_key_tm_match_over_every_non_retired_key(api):
    """Scoping computes the effort estimate from the string keys themselves.

    "Under the `SCOPE_ESTIMATE` variant — computed at scoping, before any
    translation exists — the input set is every string key of the plan's title
    whose `status` is `EXTRACTED` or `LOCKED`, `RETIRED` keys excluded; the match
    percentage read is the key's own `tm_match_pct`, and `source_char_count` and
    `ui_surface` come from the key."

    The four keys carry 125/MENU/96, 250/SUBTITLE/80, 90/LEGAL/40 and
    175/HUD/60, so the per-key contributions are 0.1, 1.4, 1.4 and 1.4 and the
    total is 4.30 units, which at 4,200 cents per unit and the TEXT_ONLY
    multiplier of 1.00 is 18,060 cents.

    Design: Difficulty/dual_variant_calc/localization_effort_scope_estimate_vs_delivered_actual
    """
    world = fx.build_market(api, title_code="NOVA-7", name="Nova Drift 7",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            stage=fx.STAGE_STRINGS_LOCKED)

    plan = validate_success(api.scope_market_plan(world["plan"]["id"], users.PRODUCER))

    assert plan["status"] == "SCOPED"
    A.assert_effort_units(plan["text_effort_units"], 4.30)
    assert plan["text_effort_variant"] == "SCOPE_ESTIMATE"
    A.assert_money_cents(plan["localization_cost_cents"], 18060,
                         "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], 0, "overage_cents")
    assert plan["required_unit_count"] == 4


def test_delivered_actual_variant_reads_the_unit_applied_tm_and_diverges(api):
    """Entering QA recomputes the effort from the delivered units instead.

    "Under the `DELIVERED_ACTUAL` variant — computed when the market enters QA
    and recomputed on every revert out of QA — the input set is every
    translation unit of this market plan whose `translation_status` is
    `DELIVERED`; the match percentage read is the unit's
    `applied_tm_match_pct`, the match the vendor actually reused, while
    `source_char_count` and `ui_surface` still come from the unit's linked
    string key."

    The vendor reused a 60 per cent match on `sub.intro` where extraction had
    predicted 80, which lifts that row from 1.4 to 2.3 units: the same key set
    now totals 5.20 units and 21,840 cents, 0.90 units and 3,780 cents above
    the estimate.

    Design: Difficulty/dual_variant_calc/localization_effort_scope_estimate_vs_delivered_actual
    """
    world = fx.build_market(api, title_code="NOVA-7", name="Nova Drift 7",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            stage=fx.STAGE_DELIVERED)
    scoped_units = 4.30
    scoped_cost = 18060

    plan = validate_success(api.enter_lqa(world["plan"]["id"], users.PRODUCER))

    assert plan["status"] == "LQA"
    A.assert_effort_units(plan["text_effort_units"], 5.20)
    assert plan["text_effort_variant"] == "DELIVERED_ACTUAL"
    A.assert_money_cents(plan["localization_cost_cents"], 21840,
                         "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], 0, "overage_cents")
    assert round(plan["text_effort_units"] - scoped_units, 2) == 0.90
    assert plan["localization_cost_cents"] - scoped_cost == 3780


def test_per_key_rounding_runs_before_the_sum(api):
    """Effort rounds per key first and only then totals the rounded rows.

    "**Each row's raw contribution is rounded half up to one decimal place
    first.** Only then are the rounded per-row values summed, and the sum is
    rounded half up to two decimal places. Summing the unrounded contributions
    and rounding once at the end is incorrect and yields a different result."

    The four raw contributions are 0.125, 1.35, 1.35 and 1.44375. Rounded per
    key they are 0.1, 1.4, 1.4 and 1.4 for a total of 4.30; summed unrounded
    they are 4.26875, which would round to 4.27.

    Design: Difficulty/combinatorial_formula/effort_rounding_pinned_per_key_then_sum
    """
    world = fx.build_market(api, title_code="NOVA-10", name="Nova Drift 10",
                            market_code="US", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            stage=fx.STAGE_STRINGS_LOCKED)

    plan = validate_success(api.scope_market_plan(world["plan"]["id"], users.PRODUCER))

    A.assert_effort_units(plan["text_effort_units"], 4.30)
    assert round(float(plan["text_effort_units"]), 2) != 4.27


def test_pinned_rounding_order_is_visible_in_the_cost_in_cents(api):
    """The rounding order propagates into the money figure.

    "The text component is `text_effort_units` multiplied by a text rate of
    4,200 cents per effort unit, multiplied by a scope multiplier of 1.00 for
    `TEXT_ONLY`, 1.25 for `SUBTITLED`, 1.80 for `FULL_VOICE` or 2.40 for
    `FULL_CULTURAL`, with that product rounded half up to whole cents."

    At 4.30 units the TEXT_ONLY text component is 18,060 cents; the 4.27 that
    the sum-then-round order produces would have yielded 17,934.

    Design: Difficulty/combinatorial_formula/effort_rounding_pinned_per_key_then_sum
    """
    world = fx.build_market(api, title_code="NOVA-10", name="Nova Drift 10",
                            market_code="US", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            stage=fx.STAGE_STRINGS_LOCKED)

    plan = validate_success(api.scope_market_plan(world["plan"]["id"], users.PRODUCER))

    A.assert_money_cents(plan["localization_cost_cents"], 18060,
                         "localization_cost_cents")
    assert plan["localization_cost_cents"] != 17934


def test_cultural_surcharge_floor_beats_the_percentage_and_the_cap_clamps(api):
    """A FULL_CULTURAL market takes the surcharge floor, then meets its cap.

    "A cultural surcharge applies only when `scope_tier` is `FULL_CULTURAL`,
    and it has a hard floor: it is the greater of 1,500,000 cents and fifteen
    per cent of the sum of the text and voice components rounded half up to
    whole cents."

    "`localization_cost_cents` is the lesser of that subtotal and
    `budget_cap_cents`, and `overage_cents` is the subtotal minus
    `budget_cap_cents` when that difference is positive and zero otherwise."

    At 4.30 units the text component is 43,344 cents, fifteen per cent of which
    is 6,502 — far below the floor — so the surcharge is 1,500,000 and the
    subtotal is 1,543,344 against a 200,000-cent cap.

    Design: Difficulty/combinatorial_formula/cultural_cost_conditional_branch_floor_and_budget_clamp
    """
    world = fx.build_market(api, title_code="NOVA-9", name="Nova Drift 9",
                            market_code="DE", scope_tier="FULL_CULTURAL",
                            target_rating="MATURE_15", budget_cap_cents=200000,
                            required_voice_line_count=100,
                            stage=fx.STAGE_STRINGS_LOCKED,
                            media_scope="ALL_MEDIA")

    plan = validate_success(api.scope_market_plan(world["plan"]["id"], users.PRODUCER))

    assert plan["cultural_adaptation_required"] is True
    A.assert_effort_units(plan["text_effort_units"], 4.30)
    A.assert_money_cents(plan["localization_cost_cents"], 200000,
                         "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], 1343344, "overage_cents")
    subtotal = plan["localization_cost_cents"] + plan["overage_cents"]
    assert subtotal == 43344 + 1500000
    assert subtotal != 43344 + 6502


def test_recorded_lines_join_the_voice_component_and_the_floor_still_wins(api):
    """Completing a session adds its line fee to the cost subtotal.

    "The voice component is the sum, over every recording session of this
    market plan whose `status` is `RECORDED`, of that session's
    `recorded_line_count` multiplied by the `per_line_rate_cents` of the talent
    contract the session was booked against; sessions in `SCHEDULED`,
    `IN_PROGRESS` or `CANCELLED` contribute exactly zero."

    120 recorded lines at 250 cents each add 30,000 cents, so text plus voice
    is 73,344 and fifteen per cent of it is 11,002 — still below the
    1,500,000-cent floor, leaving a 1,573,344-cent subtotal.

    Design: Difficulty/combinatorial_formula/cultural_cost_conditional_branch_floor_and_budget_clamp
    """
    world = fx.build_market(api, title_code="NOVA-9", name="Nova Drift 9",
                            market_code="DE", scope_tier="FULL_CULTURAL",
                            target_rating="MATURE_15", budget_cap_cents=200000,
                            required_voice_line_count=100,
                            stage=fx.STAGE_IN_LOCALIZATION,
                            media_scope="ALL_MEDIA")
    session = fx.book_session(api, world["plan"]["id"], world["talent"]["id"],
                              world["booth"]["id"], world["contract"]["id"],
                              start_utc="2026-09-10T09:00:00Z",
                              end_utc="2026-09-10T12:00:00Z",
                              planned_line_count=120)
    fx.set_clock(api, session["start_utc"])
    agent = users.make_talent_agent_headers(world["talent"]["id"])
    validate_success(api.start_voice_session(session["id"], agent))

    recorded = validate_success(
        api.complete_voice_session(session["id"],
                                   f.complete_session_payload(120), agent)
    )

    assert recorded["status"] == "RECORDED"
    A.assert_money_cents(recorded["line_fee_cents"], 30000, "line_fee_cents")
    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["voice_recorded_line_count"] == 120
    A.assert_money_cents(plan["localization_cost_cents"], 200000,
                         "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], 1373344, "overage_cents")
    subtotal = plan["localization_cost_cents"] + plan["overage_cents"]
    assert subtotal == 43344 + 30000 + 1500000
    assert subtotal != 43344 + 30000 + 11002
