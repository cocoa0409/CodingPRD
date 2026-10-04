"""Tooling orders, MOQ rounding, factory capacity and the utilization tier."""
from test_helpers import (
    ApiErrorId,
    BRAND,
    assert_tooling_order,
    create_evergreen_line,
    create_factory,
    create_sku,
    create_tooling_order,
    set_clock,
    validate_error,
    validate_success,
)


def test_tooling_allocation_moq_rounding_and_utilization_tier(api):
    """PRD §3.5: "The `allocated_units` are the requested units rounded up to a
    whole multiple of the SKU's `moq_units`."
    PRD §3.5: "The overtime multiplier depends on factory utilization after this
    order: when the post-order load is at most 80% of monthly capacity the tier is
    0 and there is no overtime uplift — a load of exactly 80% still falls in
    tier 0 — while any utilization above 80% and up to 100% is tier 1, adding 15%
    to the production-cost component."

    Design: Difficulty/combinatorial_formula/tooling_allocation_moq_rounding_and_utilization_tier
    """
    set_clock("2026-10-01T00:00:00Z")
    factory = create_factory(name="Shenzhen Plastics", capacity_units_per_month=1000, tooling_lead_weeks=8)
    line = create_evergreen_line(street="2027-06-01T00:00:00Z")
    sku = create_sku(line["id"], moq_units=300, unit_cost_cents=100, tooling_cost_cents=10000)

    first = validate_success(
        api.create_tooling_order(
            {
                "toy_line_id": line["id"],
                "sku_id": sku["id"],
                "factory_id": factory["id"],
                "production_month": "2027-01",
                "units": 500,
            },
            BRAND,
        ),
        expected_status=201,
    )
    assert first["allocated_units"] == 600  # ceil(500/300)*300

    second = validate_success(
        api.create_tooling_order(
            {
                "toy_line_id": line["id"],
                "sku_id": sku["id"],
                "factory_id": factory["id"],
                "production_month": "2027-01",
                "units": 250,
            },
            BRAND,
        ),
        expected_status=201,
    )
    assert second["allocated_units"] == 300  # ceil(250/300)*300
    # utilization (600+300)/1000 = 0.90 > 0.80 -> tier 1: 10000 + round(300*100*1.15)
    assert second["tooling_charge_cents"] == 44500


def test_tooling_moq_rounding_exact_multiple_no_uplift(api):
    """PRD §3.5: "The order's `tooling_charge_cents` is the SKU's
    `tooling_cost_cents` added whole, plus a production-cost component:
    `unit_cost_cents` multiplied by `allocated_units`, multiplied by an overtime
    multiplier, with the component rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/tooling_allocation_moq_rounding_and_utilization_tier
    """
    set_clock("2026-10-01T00:00:00Z")
    factory = create_factory(capacity_units_per_month=1000)
    line = create_evergreen_line(street="2027-06-01T00:00:00Z")
    sku = create_sku(line["id"], moq_units=300, unit_cost_cents=100, tooling_cost_cents=10000)

    order = validate_success(
        api.create_tooling_order(
            {
                "toy_line_id": line["id"],
                "sku_id": sku["id"],
                "factory_id": factory["id"],
                "production_month": "2027-01",
                "units": 500,
            },
            BRAND,
        ),
        expected_status=201,
    )
    # utilization 600/1000 = 0.60 <= 0.80 -> tier 0: 10000 + 600*100
    assert order["tooling_charge_cents"] == 70000


def test_factory_utilization_tier_boundary_at_exactly_080(api):
    """PRD §3.5: "when the post-order load is at most 80% of monthly capacity the
    tier is 0 and there is no overtime uplift — a load of exactly 80% still falls
    in tier 0 — while any utilization above 80% and up to 100% is tier 1, adding
    15% to the production-cost component."

    Design: Difficulty/boundary_precision_check/factory_utilization_tier_boundary_at_exactly_080
    """
    set_clock("2026-10-01T00:00:00Z")
    factory = create_factory(name="F1", capacity_units_per_month=1000, tooling_lead_weeks=4)
    line = create_evergreen_line(street="2027-06-01T00:00:00Z")
    sku = create_sku(line["id"], moq_units=1, unit_cost_cents=100, tooling_cost_cents=10000)
    create_tooling_order(line["id"], sku["id"], factory["id"], production_month="2027-01", units=600)

    at_boundary = validate_success(
        api.create_tooling_order(
            {
                "toy_line_id": line["id"],
                "sku_id": sku["id"],
                "factory_id": factory["id"],
                "production_month": "2027-01",
                "units": 200,
            },
            BRAND,
        ),
        expected_status=201,
    )
    # (600+200)/1000 = 0.80 exactly -> tier 0: 10000 + 200*100*1.00
    assert at_boundary["tooling_charge_cents"] == 30000

    above_boundary = validate_success(
        api.create_tooling_order(
            {
                "toy_line_id": line["id"],
                "sku_id": sku["id"],
                "factory_id": factory["id"],
                "production_month": "2027-01",
                "units": 1,
            },
            BRAND,
        ),
        expected_status=201,
    )
    # (800+1)/1000 = 0.801 -> tier 1: 10000 + round_half_up(1*100*1.15) = 10115
    assert above_boundary["tooling_charge_cents"] == 10115


def test_factory_utilization_tier_boundary_just_below_080(api):
    """PRD §3.5: "when the post-order load is at most 80% of monthly capacity the
    tier is 0 and there is no overtime uplift".

    Design: Difficulty/boundary_precision_check/factory_utilization_tier_boundary_at_exactly_080
    """
    set_clock("2026-10-01T00:00:00Z")
    factory = create_factory(name="F1", capacity_units_per_month=1000, tooling_lead_weeks=4)
    line = create_evergreen_line(street="2027-06-01T00:00:00Z")
    sku = create_sku(line["id"], moq_units=1, unit_cost_cents=100, tooling_cost_cents=10000)
    create_tooling_order(line["id"], sku["id"], factory["id"], production_month="2027-01", units=600)

    below = validate_success(
        api.create_tooling_order(
            {
                "toy_line_id": line["id"],
                "sku_id": sku["id"],
                "factory_id": factory["id"],
                "production_month": "2027-01",
                "units": 199,
            },
            BRAND,
        ),
        expected_status=201,
    )
    # (600+199)/1000 = 0.799 -> tier 0: 10000 + 199*100
    assert below["tooling_charge_cents"] == 29900


def test_factory_month_capacity_aggregate_overlap(api):
    """PRD §3.5: "The factory's month load is the sum of `allocated_units` across
    that factory's `APPROVED` tooling orders in the same `production_month` bucket —
    scrapped orders free their capacity and are excluded — and if the month load
    plus this order's `allocated_units` would exceed `capacity_units_per_month`, the
    order is rejected with `ERR_FACTORY_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/factory_month_capacity_aggregate_overlap
    """
    set_clock("2026-10-01T00:00:00Z")
    factory = create_factory(name="F1", capacity_units_per_month=1000, tooling_lead_weeks=4)
    line = create_evergreen_line(street="2027-06-01T00:00:00Z")
    sku = create_sku(line["id"], moq_units=100, unit_cost_cents=100, tooling_cost_cents=10000)
    create_tooling_order(line["id"], sku["id"], factory["id"], production_month="2027-01", units=800)

    resp = api.create_tooling_order(
        {
            "toy_line_id": line["id"],
            "sku_id": sku["id"],
            "factory_id": factory["id"],
            "production_month": "2027-01",
            "units": 250,
        },
        BRAND,
    )
    # 800 + ceil(250/100)*100=300 > 1000 -> rejected
    validate_error(resp, ApiErrorId.ERR_FACTORY_CAPACITY_EXCEEDED, expected_status=409)

    # A different production-month bucket is unaffected.
    feb = validate_success(
        api.create_tooling_order(
            {
                "toy_line_id": line["id"],
                "sku_id": sku["id"],
                "factory_id": factory["id"],
                "production_month": "2027-02",
                "units": 250,
            },
            BRAND,
        ),
        expected_status=201,
    )
    assert feb["allocated_units"] == 300


def test_factory_month_capacity_sums_across_lines(api):
    """PRD §3.5: "The factory's month load is the sum of `allocated_units` across
    that factory's `APPROVED` tooling orders in the same `production_month`
    bucket".

    Design: Difficulty/resource_temporal_overlap/factory_month_capacity_aggregate_overlap
    """
    set_clock("2026-10-01T00:00:00Z")
    factory = create_factory(name="F1", capacity_units_per_month=1000, tooling_lead_weeks=4)
    line_a = create_evergreen_line(name="Line A", street="2027-06-01T00:00:00Z")
    sku_a = create_sku(line_a["id"], moq_units=100)
    line_b = create_evergreen_line(name="Line B", street="2027-06-01T00:00:00Z")
    sku_b = create_sku(line_b["id"], moq_units=100)
    create_tooling_order(line_a["id"], sku_a["id"], factory["id"], production_month="2027-01", units=800)

    resp = api.create_tooling_order(
        {
            "toy_line_id": line_b["id"],
            "sku_id": sku_b["id"],
            "factory_id": factory["id"],
            "production_month": "2027-01",
            "units": 250,
        },
        BRAND,
    )
    validate_error(resp, ApiErrorId.ERR_FACTORY_CAPACITY_EXCEEDED, expected_status=409)


def test_scrapped_tooling_order_frees_capacity(api):
    """PRD §3.5: "A `BrandManager` may scrap an `APPROVED` order, moving it to
    `SCRAPPED` and freeing its factory month capacity".

    Design: Corner/endpoints/scrapped_tooling_order_frees_capacity
    """
    factory = create_factory(name="F1", capacity_units_per_month=1000, tooling_lead_weeks=4)
    line = create_evergreen_line(name="L", street="2027-06-01T00:00:00Z")
    sku = create_sku(line["id"], moq_units=100)
    first = create_tooling_order(line["id"], sku["id"], factory["id"], production_month="2027-01", units=800)

    resp = api.create_tooling_order(
        {
            "toy_line_id": line["id"],
            "sku_id": sku["id"],
            "factory_id": factory["id"],
            "production_month": "2027-01",
            "units": 300,
        },
        BRAND,
    )
    validate_error(resp, ApiErrorId.ERR_FACTORY_CAPACITY_EXCEEDED, expected_status=409)

    validate_success(api.scrap_tooling_order(first["id"], {}, BRAND))

    after = validate_success(
        api.create_tooling_order(
            {
                "toy_line_id": line["id"],
                "sku_id": sku["id"],
                "factory_id": factory["id"],
                "production_month": "2027-01",
                "units": 300,
            },
            BRAND,
        ),
        expected_status=201,
    )
    assert_tooling_order(after)
    assert after["allocated_units"] == 300


def test_tooling_order_sku_must_belong_to_line(api):
    """PRD §3.5: "The SKU must actually belong to the named line; a mismatch is a
    structural violation rejected with `ERR_CONSTRAINT_VIOLATION` (HTTP 422)".

    Design: Corner/validations/tooling_order_sku_must_belong_to_line
    """
    factory = create_factory(capacity_units_per_month=100000)
    line1 = create_evergreen_line(name="L1")
    line2 = create_evergreen_line(name="L2")
    sku2 = create_sku(line2["id"], name="Other")

    resp = api.create_tooling_order(
        {
            "toy_line_id": line1["id"],
            "sku_id": sku2["id"],
            "factory_id": factory["id"],
            "production_month": "2027-01",
            "units": 100,
        },
        BRAND,
    )
    validate_error(resp, ApiErrorId.ERR_CONSTRAINT_VIOLATION, expected_status=422)
