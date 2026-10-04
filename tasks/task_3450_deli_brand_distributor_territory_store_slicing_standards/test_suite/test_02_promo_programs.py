"""Promotional pricing programs: reserves, settlement rounding, fiscal gates (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_promo_reserve_consistency,
    authorize_promo,
    create_product,
    create_promo_program,
    redemption_line,
    setup_approved_account,
    setup_authorized_promo,
    setup_draft_promo,
    settle_promo,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["brand_admin_headers"]


def _setup_promo_999(estimated_units):
    """Approved account + product base 999 + DRAFT program at price 900."""
    ctx = setup_approved_account()
    ctx["product"] = create_product(code="P1", name="Promo Item", base_price_cents=999)
    ctx["program"] = create_promo_program(
        ctx["account"], ctx["distributor"], ctx["product"],
        promo_price_cents=900, budget_cents=40000, estimated_units=estimated_units,
    )
    return ctx


def test_promo_authorization_locks_forecast_reserve(api):
    """PRD §3.7: "Approval locks the provisional reserve: `reserved_cents` is set to
    the estimated units multiplied by the unit allowance, and the program moves
    `DRAFT` → `AUTHORIZED`." and "take the markdown — the product's `base_price_cents`
    minus the program's `promo_price_cents` — multiply it by the brand's 60 percent
    share of the markdown, and round half up to whole cents."

    Base 999, promo 900 -> markdown 99, unit allowance round_half_up(99*0.6) = 59;
    forecast 500 units -> reserve 500 * 59 = 29500 (the provisional variant prices
    FORECAST units).

    Design: Difficulty/dual_variant_calc/promo_reserve_provisional_vs_final_settlement
    """
    ctx = _setup_promo_999(estimated_units=500)
    program = authorize_promo(ctx["program"]["id"], "APPROVE")
    assert program["status"] == "AUTHORIZED"
    assert program["unit_allowance_cents"] == 59, (
        f"unit allowance: expected 59, got {program['unit_allowance_cents']}"
    )
    assert program["reserved_cents"] == 29500, (
        f"provisional reserve over 500 forecast units: expected 29500, "
        f"got {program['reserved_cents']}"
    )


def test_promo_settlement_prices_actual_redemptions(api):
    """PRD §3.7: "On settlement the program moves to the terminal `SETTLED`,
    `spent_cents` records the final amount, and `released_cents` records the reserve
    returned, `reserved_cents` minus `spent_cents`."

    Same program: the final variant prices 420 ACTUAL redeemed units,
    round_half_up(420*99*0.6) = 24948 spent against the 29500 forecast reserve,
    releasing 4552 — different money from the provisional reading of the same program.

    Design: Difficulty/dual_variant_calc/promo_reserve_provisional_vs_final_settlement
    """
    ctx = _setup_promo_999(estimated_units=500)
    authorize_promo(ctx["program"]["id"], "APPROVE")
    program = settle_promo(ctx["program"]["id"], [redemption_line("2026-10-01", 420)])
    assert program["status"] == "SETTLED"
    assert program["reserved_cents"] == 29500
    assert program["spent_cents"] == 24948, (
        f"final settlement over 420 actual units: expected 24948, "
        f"got {program['spent_cents']}"
    )
    assert program["released_cents"] == 4552
    assert_promo_reserve_consistency(program)


def test_promo_settlement_rounds_each_line_before_summing(api):
    """PRD §3.7: "The final settlement amount is built line by line: for each line,
    multiply its `units` by the markdown and by the brand's 60 percent share, round
    that line's amount half up to whole cents, and only then sum the rounded line
    amounts."

    Three one-unit redemption lines at markdown 99: 3 x round_half_up(1*99*0.6)
    = 3 x 59 = 177. The rejected sum-then-round order would give
    round_half_up(3*59.4) = 178.

    Design: Difficulty/combinatorial_formula/promo_settlement_per_line_rounding_order
    """
    ctx = _setup_promo_999(estimated_units=10)
    authorize_promo(ctx["program"]["id"], "APPROVE")
    program = settle_promo(ctx["program"]["id"], [
        redemption_line("2026-10-01", 1),
        redemption_line("2026-10-02", 1),
        redemption_line("2026-10-03", 1),
    ])
    assert program["spent_cents"] == 177, (
        f"per-line rounding is pinned: expected 177 (3 x 59), "
        f"got {program['spent_cents']} (178 would mean sum-then-round)"
    )
    assert program["spent_cents"] != 178


def test_promo_per_line_rounding_releases_remaining_reserve(api):
    """PRD §3.7: "Rounding each line first and summing second is pinned; summing
    units across lines and rounding once is explicitly not the rule." and
    "`released_cents` records the reserve returned, `reserved_cents` minus
    `spent_cents`."

    The same three-line settlement: reserve 10 * 59 = 590 locked at authorization,
    177 spent, so 590 - 177 = 413 released.

    Design: Difficulty/combinatorial_formula/promo_settlement_per_line_rounding_order
    """
    ctx = _setup_promo_999(estimated_units=10)
    authorize_promo(ctx["program"]["id"], "APPROVE")
    program = settle_promo(ctx["program"]["id"], [
        redemption_line("2026-10-01", 1),
        redemption_line("2026-10-02", 1),
        redemption_line("2026-10-03", 1),
    ])
    assert program["reserved_cents"] == 590
    assert program["released_cents"] == 413, (
        f"expected released 413 (590 - 177), got {program['released_cents']}"
    )
    assert_promo_reserve_consistency(program)


def test_promo_reserve_locked_at_authorization(api):
    """PRD §3.7: "Approval locks the provisional reserve: `reserved_cents` is set to
    the estimated units multiplied by the unit allowance, and the program moves
    `DRAFT` → `AUTHORIZED`."

    Forecast 300 units at allowance 59 -> reserve 17700 locked by the forward action.

    Design: Difficulty/compensating_invariant/promo_reserve_conserved_across_authorize_and_settle
    """
    ctx = _setup_promo_999(estimated_units=300)
    program = authorize_promo(ctx["program"]["id"], "APPROVE")
    assert program["status"] == "AUTHORIZED"
    assert program["reserved_cents"] == 17700, (
        f"forward action must lock the reserve: expected 17700, "
        f"got {program['reserved_cents']}"
    )
    assert program["budget_cents"] == 40000


def test_promo_settlement_repartitions_reserve_exactly(api):
    """PRD §3.7: "On settlement the program moves to the terminal `SETTLED`,
    `spent_cents` records the final amount, and `released_cents` records the reserve
    returned, `reserved_cents` minus `spent_cents`."

    The locked 17700 is exactly repartitioned by the compensating settle of 250
    units: spent round_half_up(250*99*0.6) = 14850, released 17700 - 14850 = 2850;
    the budget cap (40000) is untouched by the forward+compensating pair.

    Design: Difficulty/compensating_invariant/promo_reserve_conserved_across_authorize_and_settle
    """
    ctx = _setup_promo_999(estimated_units=300)
    authorize_promo(ctx["program"]["id"], "APPROVE")
    program = settle_promo(ctx["program"]["id"], [redemption_line("2026-10-01", 250)])
    assert program["spent_cents"] == 14850, (
        f"expected spent 14850, got {program['spent_cents']}"
    )
    assert program["released_cents"] == 2850
    assert program["reserved_cents"] == (
        program["spent_cents"] + program["released_cents"]
    ), "reserve conservation: 17700 == 14850 + 2850"
    assert program["budget_cents"] == 40000, "budget cap must be untouched"
    assert_promo_reserve_consistency(program)


def test_promo_below_floor_rejected_when_budget_would_pass(api):
    """PRD §3.7: "the promotional price must respect the regulatory floor, being at
    least 85 percent of the product's `base_price_cents` rounded half up to whole
    cents — a price exactly on the floor is allowed, anything lower fails with
    `ERR_PROMO_BELOW_FLOOR`".

    Isolated floor failure: base 1000 -> floor 850; price 800 is below it while the
    reserve (10 x 120 = 1200) fits the 40000 budget, so only the floor can fire.
    (The dual-failure precedence between the floor and the budget is not asserted:
    PRD §2.8 places both under one fiscal tier and pins no order within it.)

    Design: Difficulty/priority_pair_validation_conflict/safety_floor_beats_fiscal_budget_on_promo_authorize
    """
    ctx = setup_approved_account()
    product = create_product(code="P1", name="Item", base_price_cents=1000)
    program = create_promo_program(
        ctx["account"], ctx["distributor"], product,
        promo_price_cents=800, budget_cents=40000, estimated_units=10,
    )
    resp = api.authorize_promo_program(program["id"], "APPROVE", ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROMO_BELOW_FLOOR)
    reread = validate_success(api.get_promo_program(program["id"], ADMIN))
    assert reread["status"] == "DRAFT", "a failed authorization leaves the program DRAFT"


def test_promo_over_budget_rejected_when_floor_would_pass(api):
    """PRD §3.7: "the provisional reserve, the program's `estimated_units` multiplied
    by its `unit_allowance_cents`, must fit within `budget_cents`, else
    `ERR_PROMO_BUDGET_EXCEEDED`".

    Isolated budget failure: price 900 respects the floor (850) but the reserve
    100000 x 60 = 6000000 exceeds the 100-cent budget, so only the budget can fire.

    Design: Difficulty/priority_pair_validation_conflict/safety_floor_beats_fiscal_budget_on_promo_authorize
    """
    ctx = setup_approved_account()
    product = create_product(code="P1", name="Item", base_price_cents=1000)
    program = create_promo_program(
        ctx["account"], ctx["distributor"], product,
        promo_price_cents=900, budget_cents=100, estimated_units=100000,
    )
    resp = api.authorize_promo_program(program["id"], "APPROVE", ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROMO_BUDGET_EXCEEDED)
    reread = validate_success(api.get_promo_program(program["id"], ADMIN))
    assert reread["status"] == "DRAFT", "a failed authorization leaves the program DRAFT"


def test_rejected_promo_program_cannot_be_settled(api):
    """PRD §3.7: "A `REJECT` decision moves it `DRAFT` → `REJECTED`, terminal."
    PRD §2.8: "an entity already in a terminal state (`TERMINATED`, `REJECTED`,
    `CLOSED`, `SETTLED`, `RECALLED`, `EXHAUSTED`, `CONFIRMED`, `DELIVERED`,
    `PULLED_ON_TIME`, `PULLED_LATE`, `FORCE_PULLED`, `DECOMMISSIONED`, `EXPIRED`,
    `REVOKED`) rejects every further transition with `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/rejected_promo_cannot_settle
    """
    ctx = setup_draft_promo()
    authorize_promo(ctx["program"]["id"], "REJECT")
    resp = api.settle_promo_program(
        ctx["program"]["id"], [redemption_line("2026-10-01", 5)], ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_promo_windows_touching_on_closed_interval_rejected(api):
    """PRD §3.7: "Collision is judged on closed intervals: the new program overlaps
    when its `start_date` falls on or before the existing program's `end_date` while
    the existing program's `start_date` falls on or before the new `end_date` — so a
    program starting the day after the existing one ends is allowed, while starting
    on the existing program's final day is not — and a collision is rejected with
    `ERR_PROMO_WINDOW_OVERLAP`."

    Existing AUTHORIZED program runs 2026-10-01..2026-10-07: a second program
    starting 2026-10-07 collides; one starting 2026-10-08 authorizes cleanly.

    Design: Corner/validations/promo_window_closed_interval_touching_rejected
    """
    ctx = setup_authorized_promo()  # 2026-10-01..2026-10-07, AUTHORIZED
    touching = create_promo_program(
        ctx["account"], ctx["distributor"], ctx["product"],
        start_date="2026-10-07", end_date="2026-10-14",
    )
    resp = api.authorize_promo_program(touching["id"], "APPROVE", ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROMO_WINDOW_OVERLAP)

    adjacent = create_promo_program(
        ctx["account"], ctx["distributor"], ctx["product"],
        start_date="2026-10-08", end_date="2026-10-14",
    )
    authorized = validate_success(
        api.authorize_promo_program(adjacent["id"], "APPROVE", ADMIN)
    )
    assert authorized["status"] == "AUTHORIZED", (
        "a program starting the day after the existing one ends is allowed"
    )
