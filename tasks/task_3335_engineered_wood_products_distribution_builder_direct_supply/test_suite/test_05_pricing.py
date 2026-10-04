"""Order pricing tests: INDEX price selection and volume discount tiers."""
from test_helpers import (
    create_order,
    create_price_index_entry,
    set_clock,
    setup_builder_with_job,
    create_product,
    create_branch,
    receive_lot,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.fixtures import ACCT


def _setup_index_scenario(credit_limit=9000000):
    """Product + stocked branch + ACTIVE builder + job. No index entries."""
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 100, 40000)
    builder, job = setup_builder_with_job(credit_limit)
    return product, branch, builder, job


def test_index_price_selector_picks_latest_effective_week_not_later():
    """PRD §3.2: "When an INDEX-priced order line is priced, the applicable
    entry is the one matching the line product's family and species whose
    effective_week_start is on or before the pricing week; the latest such
    effective_week_start wins". PRD §3.6: "The pricing week is the Monday of
    the week containing the confirm date when pricing_week_mode is
    LOCK_AT_ACCEPT, and confirm pins priced_week_start to that week".

    Design: Corner/calculations/index_price_selector_picks_latest_effective_week_not_later
    """
    set_clock("2026-09-01T00:00:00Z")
    product, branch, builder, job = _setup_index_scenario()
    create_price_index_entry(effective_week_start="2026-08-31",
                             index_price_cents_per_mbf=70000)
    create_price_index_entry(effective_week_start="2026-09-07",
                             index_price_cents_per_mbf=72000)
    create_price_index_entry(effective_week_start="2026-09-14",
                             index_price_cents_per_mbf=75000)

    order = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=10, price_basis="INDEX", product_id=product["id"],
    )
    set_clock("2026-09-08T10:00:00Z")
    confirmed = validate_success(api.confirm_sales_order(order["id"], ACCT))
    assert confirmed["order_total_cents"] == 725000, (
        f"10 mbf * (72000 + 500 premium) = 725000, got {confirmed['order_total_cents']}"
    )
    assert confirmed["priced_week_start"] == "2026-09-07"


def test_volume_discount_tier_boundary_at_fifty_mbf():
    """PRD §3.6: "A volume discount applies per line: no discount when
    qty_mbf is below 50, three percent when qty_mbf is at least 50 but below
    100, and five percent when qty_mbf is 100 or more."

    Design: Corner/calculations/volume_discount_tier_boundary_at_fifty_mbf
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 200, 40000)
    builder, job = setup_builder_with_job(90000000)

    o49 = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=49, unit_price_cents=100000, product_id=product["id"],
    )
    o50 = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=50, unit_price_cents=100000, product_id=product["id"],
    )

    c49 = validate_success(api.confirm_sales_order(o49["id"], ACCT))
    assert c49["order_total_cents"] == 4900000

    c50 = validate_success(api.confirm_sales_order(o50["id"], ACCT))
    assert c50["order_total_cents"] == 4850000, (
        f"50 mbf hits the 3% tier inclusively: 5000000 * 0.97 = 4850000, "
        f"got {c50['order_total_cents']}"
    )


def test_confirm_response_reflects_all_mutations_immediately():
    """PRD §3.6: "The pricing week is the Monday of the week containing the
    confirm date when pricing_week_mode is LOCK_AT_ACCEPT, and confirm pins
    priced_week_start to that week" and "A successful confirm moves the order
    to CONFIRMED". The confirm response body itself carries all three.

    Design: Corner/consistency_model/confirm_response_reflects_all_mutations_immediately
    """
    set_clock("2026-09-01T00:00:00Z")
    product, branch, builder, job = _setup_index_scenario()
    create_price_index_entry(effective_week_start="2026-09-07",
                             index_price_cents_per_mbf=72000)

    order = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=10, price_basis="INDEX", product_id=product["id"],
    )
    set_clock("2026-09-07T10:00:00Z")
    confirmed = validate_success(api.confirm_sales_order(order["id"], ACCT))
    assert confirmed["order_status"] == "CONFIRMED"
    assert confirmed["order_total_cents"] == 725000
    assert confirmed["priced_week_start"] == "2026-09-07"
