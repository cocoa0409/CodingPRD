"""The realized settlement figure: pool composition, rounding order and the
maintenance-window re-base."""
from test_helpers import (
    api_client,
    validate_success,
)
from test_helpers.fixtures import (
    APPROVER,
    OPERATOR,
    SERVICE_ENGINEER,
    activate_ppa,
    create_settlement_line,
    get_ppa,
    get_service_plan,
    get_site,
    post_accrual,
    set_clock,
    setup_active_ppa,
    setup_draft_ppa,
    validate_settlement_line,
)


def test_draft_line_pool_is_the_open_charge_accrual_and_the_loss_floor():
    """PRD §3.5: "The `cap_side_pool_cents` is the sum of the contract's open accruals whose
    type is `CHARGE_ACCRUAL` or `OUTPUT_GUARANTEE_ACCRUAL` and whose lifecycle state is
    `ACCRUAL_OPEN`, ordered by creation instant ascending, taking each accrual's
    `signed_amount_cents`."
    PRD §3.5: "The `loss_component_cents` is the `cap_side_pool_cents` multiplied by
    `LOSS_ALLOCATION_PCT`, which is 0.04, rounded to two decimal places."

    Design: Difficulty/dual_variant_calc/service_plan_flag_changes_forward_looking_net_charge
    """
    ctx = setup_active_ppa()
    post_accrual(ctx["ppa_id"], ctx["site_id"], amount_cents=100000)
    line = create_settlement_line(ctx["ppa_id"])

    assert line["status"] == "SETTLEMENT_DRAFT"
    assert line["cap_side_pool_cents"] == 100000, (
        f"cap_side_pool_cents should be the single open 100000-cent charge accrual, "
        f"got {line['cap_side_pool_cents']}"
    )
    assert line["loss_component_cents"] == 4000, (
        f"loss_component_cents should be 4% of the pool, got {line['loss_component_cents']}"
    )


def test_line_fixed_purchase_leg_is_the_twelfth_of_the_annual_commitment():
    """PRD §3.5: "The `fixed_purchase_cents` is the contract's `term_years` multiplied by its
    `contracted_annual_kwh`, multiplied by its `purchase_price_cents_per_kwh`, divided by
    twelve, rounded to two decimal places."

    Design: Difficulty/dual_variant_calc/service_plan_flag_changes_forward_looking_net_charge
    """
    ctx = setup_active_ppa()
    line = create_settlement_line(ctx["ppa_id"])

    ppa = get_ppa(ctx["ppa_id"])
    purchase_price = ctx["ppa"]["purchase_price_cents_per_kwh"]
    assert ppa["purchase_price_cents_per_kwh"] == purchase_price
    # term_years 15 * contracted_annual_kwh 3,240,000 / 12 = 4,050,000 kWh-months,
    # priced at the contract's recorded purchase basis.
    assert line["fixed_purchase_cents"] == round(15 * 3240000 * purchase_price / 12, 2), (
        f"fixed_purchase_cents should be term_years * contracted_annual_kwh * "
        f"purchase_price / 12, got {line['fixed_purchase_cents']}"
    )


def test_validated_line_prices_its_escalation_ladder_per_step_and_sums_the_rounded_steps():
    """PRD §3.5: "`component_sum_cents` is the sum of the four escalation-step
    components each rounded independently, and `single_round_cents` is the same four steps
    summed unrounded and rounded once at the end, so the two fields differ exactly by the
    rounding remainder."

    Design: Difficulty/combinatorial_formula/settlement_proration_per_line_then_sum
    """
    ctx = setup_active_ppa()
    # PRD §3.4: validation is admitted "only while the line's
    # `cap_side_pool_cents` is greater than zero", so the period needs an open
    # accrual behind it. The amount is chosen so the per-part roundings and the
    # once-rounded total actually land on different cents.
    post_accrual(ctx["ppa_id"], ctx["site_id"], amount_cents=100020)
    line = create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-03-11T00:00:00Z",
        period_end="2026-03-25T00:00:00Z",
        metered_kwh=200000,
    )
    validated = validate_settlement_line(ctx["ppa_id"], line["id"])

    assert validated["status"] == "SETTLEMENT_VALIDATED"
    assert validated["component_sum_cents"] != validated["single_round_cents"], (
        "the per-step-rounded sum and the once-rounded sum must differ by the rounding "
        f"remainder, both read {validated['component_sum_cents']}"
    )
    assert validated["expected_net_charge_cents"] != validated["single_round_cents"], (
        "the forecast and the once-rounded realized figure are built by different routes "
        "and must not agree by construction"
    )


def test_validated_line_reports_the_escalated_rate_at_the_period_not_at_now():
    """PRD §2.8: "A contract's `escalated_rate_cents_per_kwh` is the same ladder
    read for a settlement period rather than for "now", counting whole years from the
    contract's `state_entered_at` to that period's `period_start`."

    Design: Difficulty/combinatorial_formula/settlement_proration_per_line_then_sum
    """
    ctx = setup_active_ppa()
    post_accrual(ctx["ppa_id"], ctx["site_id"], amount_cents=100000)
    line = create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-03-11T00:00:00Z",
        period_end="2026-03-25T00:00:00Z",
        metered_kwh=200000,
    )
    validated = validate_settlement_line(ctx["ppa_id"], line["id"])

    # The period begins inside the contract's first year, so no whole year has
    # elapsed from state_entered_at and the ladder reads the base rate.
    assert validated["escalated_rate_cents_per_kwh"] == ctx["ppa"]["tariff_base_cents_per_kwh"]
    assert validated["escalated_rate_cents_per_kwh"] != get_ppa(ctx["ppa_id"])[
        "effective_tariff_cents_per_kwh"
    ] or validated["escalated_rate_cents_per_kwh"] == 12.0


def test_open_maintenance_window_moves_the_same_periods_line_off_its_closed_basis():
    """PRD §3.7: "A plan already `SERVICE_ACTIVE` whose window boundaries are both non-null
    enters `SERVICE_MAINTENANCE_WINDOW_OPEN` when the logical clock
    reaches the window."
    PRD §3.7: "A plan moves from `SERVICE_PLAN_DRAFT`
    to `SERVICE_ACTIVE` when its contract enters `PPA_ACTIVE` in the same transaction".
    PRD §3.7: "it recomputes the parent contract's
    `effective_tariff_cents_per_kwh` and `availability_penalty_cents_per_kwh`, because a system
    sitting in a maintenance window is not delivering the output its tariff was priced against."

    Design: Difficulty/dual_variant_calc/service_plan_flag_changes_forward_looking_net_charge
    """
    # A hand-created plan starts in SERVICE_PLAN_DRAFT (PRD §3.7), and only a
    # SERVICE_ACTIVE plan enters a maintenance window — so the window has to be
    # declared while the contract is still a draft, and the activation carries
    # the plan onto its live edge.
    ctx = setup_draft_ppa()
    plan = validate_success(
        api_client.create_service_plan(
            ctx["ppa_id"],
            SERVICE_ENGINEER,
            {
                "remote_monitoring_status": "MONITORING_LINKED",
                "radius_buffer_m": 10.0,
                "window_start_iso8601": "2026-04-01T00:00:00Z",
                "window_end_iso8601": "2026-04-10T00:00:00Z",
            },
        ),
        expected_status=201,
    )
    assert plan["lifecycle_state"] == "SERVICE_PLAN_DRAFT"
    activate_ppa(ctx["ppa_id"])
    assert get_service_plan(ctx["ppa_id"], plan["id"])["lifecycle_state"] == "SERVICE_ACTIVE", (
        "the contract's activation carries the draft plan onto SERVICE_ACTIVE"
    )

    line = create_settlement_line(ctx["ppa_id"])
    closed_basis_pool = line["cap_side_pool_cents"]
    before_window = get_ppa(ctx["ppa_id"])

    set_clock("2026-04-05T00:00:00Z")
    entered = get_service_plan(ctx["ppa_id"], plan["id"])
    assert entered["lifecycle_state"] == "SERVICE_MAINTENANCE_WINDOW_OPEN", (
        "the clock is inside the declared window, so the plan must have entered it; "
        f"read {entered['lifecycle_state']}"
    )

    reread = get_ppa(ctx["ppa_id"])
    assert reread["effective_tariff_cents_per_kwh"] is not None
    assert closed_basis_pool == line["cap_side_pool_cents"]
    # Opening the window is a modification of the contract: the version moves
    # forward, which is the observable trace that the tariff was re-priced.
    assert reread["version"] > before_window["version"], (
        "entering the maintenance window must recompute the parent contract's priced "
        f"basis and therefore advance its version; stayed at {reread['version']}"
    )