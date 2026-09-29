"""Binding and advisory variants computed side by side on the same inputs."""

from test_helpers import (
    MARKDOWN_POLICY_FLAT_STEP,
    MARKDOWN_POLICY_PRORATED,
    PACK_MARKED_DOWN,
    REVENUE_SHARE_GROSS_SALES,
    REVENUE_SHARE_NET_OF_MARKDOWN,
    add_approved_rice_batch,
    add_draft_statement,
    add_pack_lot,
    add_reconciled_feed,
    base_world,
    packed_world,
    set_clock,
    validate_success,
)


def test_the_gross_sales_base_bills_the_higher_of_the_two_ladders(api):
    """A gross-sales agreement bills 296000 and reports 254000 for information only.

    "Under the `GROSS_SALES` model `settlement_base_cents` is the full
    `gross_sales_cents` … The identical ladder is then run a second time over the
    *other* model's base, and that result is `advisory_share_cents`;
    `variance_cents` is `binding_share_cents` minus `advisory_share_cents`, which
    is positive when the binding model is `GROSS_SALES`."

    Design: Difficulty/dual_variant_calc/settlement_gross_vs_net_of_markdown_share_divergence
    """
    world = base_world()
    agreement = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert agreement["revenue_share_model"] == REVENUE_SHARE_GROSS_SALES

    add_reconciled_feed(world)
    statement = add_draft_statement(world)

    assert statement["gross_sales_cents"] == 2400000
    assert statement["markdown_sales_cents"] == 300000
    assert statement["settlement_base_cents"] == 2400000
    assert statement["binding_share_cents"] == 296000
    assert statement["advisory_share_cents"] == 254000
    assert statement["variance_cents"] == 42000
    assert statement["binding_variant"] == REVENUE_SHARE_GROSS_SALES
    assert statement["space_shortfall_credit_cents"] == 0
    assert statement["discard_credit_cents"] == 0
    assert statement["net_due_cents"] == 296000


def test_the_net_of_markdown_base_reverses_the_variance_sign(api):
    """The same feed under the net model bills 254000 and reports a negative variance.

    "under `NET_OF_MARKDOWN` it is `gross_sales_cents` minus
    `markdown_sales_cents`" and the variance "is positive when the binding model is
    `GROSS_SALES` and negative when it is `NET_OF_MARKDOWN`. `binding_variant`
    records which model was binding."

    Design: Difficulty/dual_variant_calc/settlement_gross_vs_net_of_markdown_share_divergence
    """
    world = base_world(
        agreement_overrides={"revenue_share_model": REVENUE_SHARE_NET_OF_MARKDOWN}
    )
    add_reconciled_feed(world)
    statement = add_draft_statement(world)

    assert statement["gross_sales_cents"] == 2400000
    assert statement["markdown_sales_cents"] == 300000
    assert statement["settlement_base_cents"] == 2100000
    assert statement["binding_share_cents"] == 254000
    assert statement["advisory_share_cents"] == 296000
    assert statement["variance_cents"] == -42000
    assert statement["binding_variant"] == REVENUE_SHARE_NET_OF_MARKDOWN
    assert statement["net_due_cents"] == 254000

    accrued = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert accrued["lifetime_share_accrued_cents"] == 0

    issued = validate_success(
        api.issue_settlement_statement(statement["id"], world["ops_issuer_headers"])
    )
    assert issued["binding_share_cents"] == 254000
    booked = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert booked["lifetime_share_accrued_cents"] == 254000


def test_a_midday_markdown_prices_higher_under_proration_than_under_the_flat_step(api):
    """With three quarters of the window left, proration beats the flat half-price step.

    "The prorated variant is `list_price_cents` scaled by `remaining_minutes`
    divided by 720, rounded half up to whole cents, then raised to the floor if it
    fell below it. The flat-step variant is 50 percent of `list_price_cents` …
    with more than half the window left the prorated price is the higher of the
    two."

    Design: Difficulty/dual_variant_calc/pack_markdown_prorated_vs_flat_step_divergence
    """
    world = packed_world()
    agreement = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert agreement["markdown_policy"] == MARKDOWN_POLICY_PRORATED

    marked = validate_success(
        api.markdown_pack_lot(world["pack_lot_id"], world["chef_headers"])
    )
    assert marked["status"] == PACK_MARKED_DOWN
    assert marked["markdown_variant_applied"] == MARKDOWN_POLICY_PRORATED
    assert marked["markdown_price_cents"] == 675
    assert marked["advisory_markdown_price_cents"] == 450
    assert marked["markdown_price_cents"] - marked["advisory_markdown_price_cents"] == 225
    assert marked["list_price_cents"] == 900
    assert marked["unsold_count"] == 160


def test_the_flat_step_policy_binds_the_lower_price_at_midday(api):
    """Naming FLAT_STEP swaps which of the two numbers is billable.

    "The binding number is the variant named by `markdown_policy` on the license
    agreement reached from the lot through its rice batch, that batch's plan, the
    plan's kiosk and the kiosk's agreement; it is written to
    `markdown_price_cents`, the other variant is written to
    `advisory_markdown_price_cents`."

    Design: Difficulty/dual_variant_calc/pack_markdown_prorated_vs_flat_step_divergence
    """
    world = packed_world(
        agreement_overrides={"markdown_policy": MARKDOWN_POLICY_FLAT_STEP}
    )

    marked = validate_success(
        api.markdown_pack_lot(world["pack_lot_id"], world["chef_headers"])
    )
    assert marked["status"] == PACK_MARKED_DOWN
    assert marked["markdown_variant_applied"] == MARKDOWN_POLICY_FLAT_STEP
    assert marked["markdown_price_cents"] == 450
    assert marked["advisory_markdown_price_cents"] == 675
    assert marked["markdown_price_cents"] - marked["advisory_markdown_price_cents"] == (
        -225
    )


def test_late_in_the_shelf_window_the_prorated_price_is_pinned_to_the_floor(api):
    """Ninety minutes from expiry the prorated variant falls under the floor and reverses.

    "`floor_price_cents` is 30 percent of `list_price_cents`, rounded half up to
    whole cents — the absolute floor no markdown may go beneath … and late in the
    window, pinned to the 30 percent floor, it is the lower."

    Design: Difficulty/dual_variant_calc/pack_markdown_prorated_vs_flat_step_divergence
    """
    world = packed_world(pack_overrides={"pack_count": 60})
    midday = validate_success(
        api.markdown_pack_lot(world["pack_lot_id"], world["chef_headers"])
    )
    assert midday["markdown_price_cents"] > midday["advisory_markdown_price_cents"]

    late_batch = add_approved_rice_batch(
        world,
        world["plan_id"],
        hold_start_at="2026-08-03T07:00:00Z",
        hold_end_at="2026-08-03T09:00:00Z",
    )
    late_lot = add_pack_lot(
        world, late_batch["id"], world["fish_lot_id"], pack_count=100
    )
    assert late_lot["shelf_expiry_at"].startswith("2026-08-03T20:00:00")

    set_clock("2026-08-03T18:30:00Z")
    at_the_floor = validate_success(
        api.markdown_pack_lot(late_lot["id"], world["chef_headers"])
    )
    assert at_the_floor["status"] == PACK_MARKED_DOWN
    assert at_the_floor["markdown_variant_applied"] == MARKDOWN_POLICY_PRORATED
    assert at_the_floor["markdown_price_cents"] == 270
    assert at_the_floor["advisory_markdown_price_cents"] == 450
    assert at_the_floor["markdown_price_cents"] < (
        at_the_floor["advisory_markdown_price_cents"]
    )

    untouched = validate_success(
        api.get_pack_lot(world["pack_lot_id"], world["ops_headers"])
    )
    assert untouched["markdown_price_cents"] == 675
