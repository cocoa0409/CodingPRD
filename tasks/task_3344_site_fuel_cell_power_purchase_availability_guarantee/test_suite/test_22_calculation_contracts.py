"""Computed figures and constants: the availability escrow draw, the day-bought
floor, the escalation ladder, and which accruals the pool reads."""
from test_helpers import api_client, validate_success
from test_helpers.fixtures import (
    ANALYST,
    APPROVER,
    OPERATOR,
    create_customer,
    create_ppa,
    create_settlement_line,
    create_site,
    get_ppa,
    get_site,
    issue_allowance,
    post_accrual,
    set_clock,
    setup_active_ppa,
    setup_validated_line,
    validate_settlement_line,
)

# PRD §3.5: "The `availability_credit_cents` on a line is
# `AVAILABILITY_CREDIT_MONTHLY_DRAW_PCT`, which is 0.60, multiplied by the
# contract's `capacity_guarantee_reserve_cents`, rounded to two decimal places."
AVAILABILITY_CREDIT_MONTHLY_DRAW_PCT = 0.60


def test_approving_a_line_draws_sixty_percent_of_the_reserve_target():
    """PRD §3.5: "The `availability_credit_cents` on a line is `AVAILABILITY_CREDIT_MONTHLY_DRAW_PCT`,
    which is 0.60, multiplied by the contract's `capacity_guarantee_reserve_cents`, rounded to two
    decimal places."
    PRD §3.5: "The reserve target from which the contract's reserve is sized is the
    availability shortfall valued at the penalty rate, plus the contract's `loss_floor_cents`".

    Design: Corner/calculations/availability_escrow_draw_is_sixty_percent_of_the_reserve_target
    """
    ctx = setup_validated_line()
    reserve = get_ppa(ctx["ppa_id"])["capacity_guarantee_reserve_cents"]

    approved = validate_success(
        api_client.approve_settlement_line(ctx["ppa_id"], ctx["line_id"], APPROVER)
    )

    assert approved["status"] == "SETTLEMENT_APPROVED"
    assert approved["availability_credit_cents"] == round(
        AVAILABILITY_CREDIT_MONTHLY_DRAW_PCT * reserve, 2
    ), (
        "the draw is `AVAILABILITY_CREDIT_MONTHLY_DRAW_PCT` multiplied by the contract's "
        f"`capacity_guarantee_reserve_cents` ({reserve}); got "
        f"{approved['availability_credit_cents']}"
    )


def test_the_escrow_draw_is_not_credited_to_the_site_until_the_line_is_settled():
    """PRD §3.4: "A line that has been applied is the only thing that ever moves a contract's
    settled totals: draft, validated and approved lines all read the same pool but none of them
    writes to it."

    Design: Corner/calculations/availability_escrow_draw_is_sixty_percent_of_the_reserve_target
    """
    ctx = setup_validated_line()
    before = get_site(ctx["site_id"])["lifetime_availability_credit_cents"]
    reserve = get_ppa(ctx["ppa_id"])["capacity_guarantee_reserve_cents"]

    approved = validate_success(
        api_client.approve_settlement_line(ctx["ppa_id"], ctx["line_id"], APPROVER)
    )

    after = get_site(ctx["site_id"])["lifetime_availability_credit_cents"]
    assert approved["availability_credit_cents"] == round(
        AVAILABILITY_CREDIT_MONTHLY_DRAW_PCT * reserve, 2
    )
    assert after == before == 0, (
        "approval sizes the credit but does not move the site aggregate; got "
        f"{after} where {before} was expected"
    )


def test_an_allowance_smaller_than_a_single_day_still_buys_exactly_one_day():
    """PRD §3.6: "The number of days the allowance buys, `applied_days`, is the applied cap
    divided by the sum of the capped daily energy and the daily fixed figure, truncated toward zero,
    and then floored at one — an allowance whose cap is smaller than a single day still buys
    exactly one day".

    Design: Corner/calculations/ability_boundary_floors_at_one_day_for_a_tiny_allowance
    """
    ctx = setup_active_ppa()
    post_accrual(
        ctx["ppa_id"], ctx["site_id"], accrual_type="CAPACITY_ACCRUAL", amount_cents=400000
    )
    # PRD §3.6: the applied cap is read against "the target line's
    # `net_charge_cents`", so the period the allowance lands in must exist.
    create_settlement_line(ctx["ppa_id"])
    tiny = issue_allowance(ctx["ppa_id"], amount_cents=1)

    applied = validate_success(api_client.apply_allowance(ctx["ppa_id"], tiny["id"], ANALYST))

    assert applied["applied_days"] == 1, (
        "a 1-cent cap would floor to zero days, so the floor-at-one clamp must apply; got "
        f"{applied['applied_days']}"
    )
    assert applied["applied_cap_cents"] == 1, (
        f"the cap is the smaller of the nominal amount and two periods of charge; got "
        f"{applied['applied_cap_cents']}"
    )


def test_the_capped_daily_energy_reads_the_energy_leg_and_the_amount_is_the_day_product():
    """PRD §3.6: "The capped daily energy, `capped_daily_energy_cents`, is that figure capped at
    `DAILY_ENERGY_CAP_CENTS`, which is 250,000 cents — the cap applies to the energy leg only."
    PRD §3.6: "The applied amount, `applied_amount_cents`, is that day count multiplied by
    the sum of the capped daily energy and the daily fixed figure."

    Design: Corner/calculations/ability_boundary_floors_at_one_day_for_a_tiny_allowance
    """
    ctx = setup_active_ppa()
    post_accrual(
        ctx["ppa_id"], ctx["site_id"], accrual_type="CAPACITY_ACCRUAL", amount_cents=400000
    )
    create_settlement_line(ctx["ppa_id"])
    tiny = issue_allowance(ctx["ppa_id"], amount_cents=1)

    applied = validate_success(api_client.apply_allowance(ctx["ppa_id"], tiny["id"], ANALYST))

    # 200,000 metered kWh / 30 = 6,666.67 daily kWh, at the 12.00 c/kWh base rate.
    assert applied["capped_daily_energy_cents"] == 80000, (
        "the daily energy leg is metered_kwh / 30 priced at the effective tariff; got "
        f"{applied['capped_daily_energy_cents']}"
    )
    assert applied["applied_amount_cents"] == applied["applied_days"] * (
        applied["capped_daily_energy_cents"] + applied["daily_fixed_cents"]
    ), "the applied amount is the day count times the two daily legs summed"
    assert applied["applied_amount_cents"] > 0


def test_a_capacity_allowance_increments_the_sites_reserved_hold_count():
    """PRD §3.6: "a `CAPACITY_ALLOWANCE` additionally floors
    the day count at one and, once applied, increments the site's `reserved_capacity_hold_count`".

    Design: Corner/calculations/ability_boundary_floors_at_one_day_for_a_tiny_allowance
    """
    ctx = setup_active_ppa()
    post_accrual(
        ctx["ppa_id"], ctx["site_id"], accrual_type="CAPACITY_ACCRUAL", amount_cents=400000
    )
    before = get_site(ctx["site_id"])["reserved_capacity_hold_count"]
    tiny = issue_allowance(ctx["ppa_id"], amount_cents=1)

    validate_success(api_client.apply_allowance(ctx["ppa_id"], tiny["id"], ANALYST))

    after = get_site(ctx["site_id"])["reserved_capacity_hold_count"]
    assert after == before + 1, (
        "applying a capacity allowance leaves its own trace on the site; expected "
        f"{before + 1}, got {after}"
    )


def _ppa_at_the_anniversary(clock_before_anniversary):
    """A live contract activated at 2025-03-10, read from a supplied clock instant."""
    set_clock("2025-03-10T00:00:00Z")
    site = create_site()
    customer = create_customer()
    ppa = create_ppa(site["id"], customer["id"])
    validate_success(api_client.activate_ppa(ppa["id"], OPERATOR))
    set_clock(clock_before_anniversary)
    validate_success(api_client.recompute_index_bases(OPERATOR))
    return ppa["id"]


def test_one_second_before_the_anniversary_the_ladder_still_reads_the_base_rate():
    """PRD §2.8: "A contract
    that is exactly one second short of its first anniversary still evaluates at the base rate".

    Design: Corner/calculations/escalated_rate_floors_at_the_contract_anniversary
    """
    ppa_id = _ppa_at_the_anniversary("2026-03-09T23:59:59Z")

    ppa = get_ppa(ppa_id)

    assert ppa["effective_tariff_cents_per_kwh"] == 12.00, (
        "no whole year has elapsed, so the ladder reads the base rate; got "
        f"{ppa['effective_tariff_cents_per_kwh']}"
    )
    assert ppa["effective_fuel_adder_cents_per_therm"] == 2.50, (
        "the adder is a separate cap, not a rung of the ladder; got "
        f"{ppa['effective_fuel_adder_cents_per_therm']}"
    )


def test_one_second_past_the_anniversary_the_ladder_applies_one_step():
    """PRD §2.8: "a contract exactly at its first anniversary evaluates at exactly one escalation step; the
    ladder counts whole years and nothing finer."

    Design: Corner/calculations/escalated_rate_floors_at_the_contract_anniversary
    """
    ppa_id = _ppa_at_the_anniversary("2026-03-10T00:00:01Z")

    ppa = get_ppa(ppa_id)

    assert ppa["effective_tariff_cents_per_kwh"] == 12.36, (
        "one whole year has elapsed at 3% on a 12.00 base; got "
        f"{ppa['effective_tariff_cents_per_kwh']}"
    )
    assert ppa["effective_fuel_adder_cents_per_therm"] == 2.50


def _settle_a_prior_period(ctx, accrual_amount_cents=100000):
    """Post an accrual, then run one line through validate, approve and settle."""
    accrual = post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        accrual_type="CHARGE_ACCRUAL",
        amount_cents=accrual_amount_cents,
        period_anchor_iso8601="2026-02-01T00:00:00Z",
    )
    issue_allowance(ctx["ppa_id"], amount_cents=185000)
    line = create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-03-11T00:00:00Z",
        period_end="2026-04-11T00:00:00Z",
    )
    validate_settlement_line(ctx["ppa_id"], line["id"])
    validate_success(api_client.approve_settlement_line(ctx["ppa_id"], line["id"], APPROVER))
    validate_success(api_client.settle_settlement_line(ctx["ppa_id"], line["id"], APPROVER))
    return accrual, line


def test_only_open_accruals_feed_the_cap_side_pool():
    """PRD §3.5: "The `cap_side_pool_cents` is the sum of the contract's open accruals whose
    type is `CHARGE_ACCRUAL` or `OUTPUT_GUARANTEE_ACCRUAL` and whose lifecycle state is
    `ACCRUAL_OPEN`, ordered by creation instant ascending, taking each accrual's
    `signed_amount_cents`."

    Design: Corner/calculations/only_open_accruals_enter_the_pool_and_reconciled_ones_replay
    """
    ctx = setup_active_ppa()
    _settle_a_prior_period(ctx)
    post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        accrual_type="CHARGE_ACCRUAL",
        amount_cents=200000,
        period_anchor_iso8601="2026-03-01T00:00:00Z",
    )

    second = create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-04-11T00:00:00Z",
        period_end="2026-05-11T00:00:00Z",
    )

    assert second["cap_side_pool_cents"] == 200000, (
        "the reconciled accrual is excluded, so only the new open one is read; got "
        f"{second['cap_side_pool_cents']}"
    )


def test_the_settle_reconciles_the_open_accrual_and_advances_the_reconcile_count():
    """PRD §3.4: "Every open accrual of that contract whose creation instant is at or before the settling
    line's own creation instant is reconciled — its `lifecycle_state` becomes `ACCRUAL_RECONCILED`
    — and the count of accruals reconciled in that step is added to the site's
    `lifetime_settle_reconcile_count`."

    Design: Corner/calculations/only_open_accruals_enter_the_pool_and_reconciled_ones_replay
    """
    ctx = setup_active_ppa()
    accrual, _line = _settle_a_prior_period(ctx)
    post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        accrual_type="CHARGE_ACCRUAL",
        amount_cents=200000,
        period_anchor_iso8601="2026-03-01T00:00:00Z",
    )
    second = create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-04-11T00:00:00Z",
        period_end="2026-05-11T00:00:00Z",
    )

    validated = validate_settlement_line(ctx["ppa_id"], second["id"])

    reconciled = validate_success(
        api_client.get_accrual(accrual["id"], ANALYST)
    )
    assert validated["status"] == "SETTLEMENT_VALIDATED"
    assert reconciled["lifecycle_state"] == "ACCRUAL_RECONCILED", (
        "the applied line is what reconciles the accrual; got "
        f"{reconciled['lifecycle_state']}"
    )
    assert get_site(ctx["site_id"])["lifetime_settle_reconcile_count"] == 1, (
        "exactly the one reconciled accrual is counted"
    )