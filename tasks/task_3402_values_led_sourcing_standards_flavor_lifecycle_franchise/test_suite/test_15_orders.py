"""Supply orders: pricing, confirm gates, precedence (PRD §3.8, §2.6)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    make_flavor, make_limited_run_flavor,
    make_shop, make_operating_shop, make_supply_order,
    make_shop_operator_headers,
)

FA = TEST_USERS["franchise_admin_headers"]




def test_order_total_nonpartner_no_discount(api):
    """PRD §3.8: "for each line it multiplies the flavor's current `pint_price_cents` by the line's `quantity_pints` and, for a `NONPROFIT_PARTNER` shop only, applies the 15 percent partner discount (franchisees receive no discount), rounding each line's amount to integer cents half-up; the order's `total_cents` is the sum of those rounded line amounts — per-line rounding pinned before summation — and `total_pints` is the sum of the line quantities."

    Design: Corner/calculations/order_total_nonpartner_no_discount
    """
    shop = make_shop(name="Full Price Shop", operator_type="FRANCHISEE",
                     credit_limit_cents=100000)
    fa = make_flavor(name="Price A", pint_price_cents=199)
    fb = make_flavor(name="Price B", base_type="NON_DAIRY", chunk_load_pct=0,
                     swirl_load_pct=0, pint_price_cents=299)
    order = make_supply_order(
        shop["id"],
        [{"flavor_id": fa["id"], "quantity_pints": 3},
         {"flavor_id": fb["id"], "quantity_pints": 1}])
    assert order["total_cents"] == 896  # 3*199 + 1*299, no discount
    assert order["total_pints"] == 4


def test_order_total_round_per_line_then_sum(api):
    """PRD §3.8: "for each line it multiplies the flavor's current `pint_price_cents` by the line's `quantity_pints` and, for a `NONPROFIT_PARTNER` shop only, applies the 15 percent partner discount (franchisees receive no discount), rounding each line's amount to integer cents half-up; the order's `total_cents` is the sum of those rounded line amounts — per-line rounding pinned before summation — and `total_pints` is the sum of the line quantities."

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum
    """
    shop = make_operating_shop(name="Partner Shop One",
                               operator_type="NONPROFIT_PARTNER",
                               credit_limit_cents=10_000_000)
    fa = make_limited_run_flavor(name="Fudge A", pint_price_cents=199)
    fb = make_limited_run_flavor(name="Fudge B", base_type="NON_DAIRY",
                                 chunk_load_pct=0, swirl_load_pct=0,
                                 pint_price_cents=299)
    resp = api.create_supply_order(
        shop["id"],
        {"production_date": "2026-10-05",
         "lines": [{"flavor_id": fa["id"], "quantity_pints": 3},
                   {"flavor_id": fb["id"], "quantity_pints": 1}]},
        make_shop_operator_headers(shop["id"]))
    order = validate_success(resp, expected_status=201)
    # round(597*0.85)=507 + round(299*0.85)=254 = 761; sum-then-round = 762.
    assert order["total_cents"] == 761
    assert order["total_cents"] != 762, "round-per-line-then-sum is pinned"
    assert order["total_pints"] == 4


def test_order_total_round_per_line_single_line(api):
    """PRD §3.8: "for each line it multiplies the flavor's current `pint_price_cents` by the line's `quantity_pints` and, for a `NONPROFIT_PARTNER` shop only, applies the 15 percent partner discount (franchisees receive no discount), rounding each line's amount to integer cents half-up; the order's `total_cents` is the sum of those rounded line amounts — per-line rounding pinned before summation — and `total_pints` is the sum of the line quantities."

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum
    """
    shop = make_operating_shop(name="Partner Shop Two",
                               operator_type="NONPROFIT_PARTNER",
                               credit_limit_cents=10_000_000)
    fa = make_limited_run_flavor(name="Single Scoop", pint_price_cents=199)
    order = make_supply_order(
        shop["id"], [{"flavor_id": fa["id"], "quantity_pints": 1}])
    # round_half_up(199 * 0.85) = round_half_up(169.15) = 169
    assert order["total_cents"] == 169
    assert order["total_pints"] == 1


def test_order_confirm_unavailable_flavor_rejected(api):
    """PRD §3.8: "First, the shop must be `OPERATING`, failing with `ERR_SHOP_NOT_OPERATING` (HTTP 409). Second, every line's flavor must be orderable — in `LIMITED_RUN` or `CORE_LINE` — failing with `ERR_ORDER_FLAVOR_UNAVAILABLE` (HTTP 422). Third, the order's `total_cents` must fit within the shop's `credit_limit_cents`, with equality allowed, failing with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/errors/order_confirm_unavailable_flavor_rejected
    """
    shop = make_operating_shop(name="Flavor Gate Shop")
    flavor = make_flavor(name="Dev Only", pint_price_cents=100)  # DEVELOPMENT
    order = make_supply_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 5}])
    resp = api.confirm_supply_order(order["id"], FA)
    validate_error(resp, ApiErrorId.ERR_ORDER_FLAVOR_UNAVAILABLE)


def test_order_confirm_over_credit_rejected(api):
    """PRD §3.8: "First, the shop must be `OPERATING`, failing with `ERR_SHOP_NOT_OPERATING` (HTTP 409). Second, every line's flavor must be orderable — in `LIMITED_RUN` or `CORE_LINE` — failing with `ERR_ORDER_FLAVOR_UNAVAILABLE` (HTTP 422). Third, the order's `total_cents` must fit within the shop's `credit_limit_cents`, with equality allowed, failing with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/errors/order_confirm_over_credit_rejected
    """
    shop = make_operating_shop(name="Credit Crunch", credit_limit_cents=1000)
    flavor = make_limited_run_flavor(name="Pricey Pecan", pint_price_cents=199)
    order = make_supply_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 100}])
    assert order["total_cents"] == 19900
    resp = api.confirm_supply_order(order["id"], FA)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    after = get_success_data(api.get_supply_order(order["id"], FA))
    assert after["status"] == "PLACED"


def test_order_confirm_requires_shop_operating(api):
    """PRD §3.8: "First, the shop must be `OPERATING`, failing with `ERR_SHOP_NOT_OPERATING` (HTTP 409). Second, every line's flavor must be orderable — in `LIMITED_RUN` or `CORE_LINE` — failing with `ERR_ORDER_FLAVOR_UNAVAILABLE` (HTTP 422). Third, the order's `total_cents` must fit within the shop's `credit_limit_cents`, with equality allowed, failing with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_shop_operating
    """
    shop = make_operating_shop(name="Suspension Shop")
    flavor = make_limited_run_flavor(name="Orderable Oak", pint_price_cents=100)
    order = make_supply_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 10}])
    assert order["status"] == "PLACED"

    validate_success(api.suspend_shop(shop["id"], FA))
    resp = api.confirm_supply_order(order["id"], FA)
    validate_error(resp, ApiErrorId.ERR_SHOP_NOT_OPERATING)
    after = get_success_data(api.get_supply_order(order["id"], FA))
    assert after["status"] == "PLACED"


def test_order_confirm_rejected_before_opening(api):
    """PRD §3.8: "First, the shop must be `OPERATING`, failing with `ERR_SHOP_NOT_OPERATING` (HTTP 409). Second, every line's flavor must be orderable — in `LIMITED_RUN` or `CORE_LINE` — failing with `ERR_ORDER_FLAVOR_UNAVAILABLE` (HTTP 422). Third, the order's `total_cents` must fit within the shop's `credit_limit_cents`, with equality allowed, failing with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_shop_operating
    """
    # SITE_APPROVED (never opened) is not OPERATING either.
    shop = make_shop(name="Not Yet Open", credit_limit_cents=10_000_000)
    validate_success(api.approve_site(shop["id"], FA))
    flavor = make_limited_run_flavor(name="Early Bird", pint_price_cents=100)
    order = make_supply_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 10}])
    resp = api.confirm_supply_order(order["id"], FA)
    validate_error(resp, ApiErrorId.ERR_SHOP_NOT_OPERATING)


def test_state_beats_fiscal_on_order_confirm(api):
    """PRD §2.6: "the server evaluates them in one fixed precedence ladder, and the earliest failing rung determines the error returned". State-machine legality is rung 8: "the requested transition must be defined for the resource's current state, failing with `ERR_INVALID_STATE` (HTTP 409)". Business rules are rung 9: "the domain-specific checks of §3, each endpoint applying its own ordered list as stated in its subsection".
    PRD §3.8: "First, the shop must be `OPERATING`, failing with `ERR_SHOP_NOT_OPERATING` (HTTP 409). Second, every line's flavor must be orderable — in `LIMITED_RUN` or `CORE_LINE` — failing with `ERR_ORDER_FLAVOR_UNAVAILABLE` (HTTP 422). Third, the order's `total_cents` must fit within the shop's `credit_limit_cents`, with equality allowed, failing with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_confirm
    """
    shop = make_operating_shop(name="Tight Credit Shop", credit_limit_cents=100)
    flavor = make_limited_run_flavor(name="Priority Pecan", pint_price_cents=199)
    order = make_supply_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 10}])
    assert order["total_cents"] == 1990  # > credit limit 100
    validate_success(api.cancel_supply_order(
        order["id"], make_shop_operator_headers(shop["id"])))

    resp = api.confirm_supply_order(order["id"], FA)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE", \
        "the cancelled-state failure (rung 8) beats the credit-limit failure (rung 9)"


def test_state_beats_fiscal_requires_cancelled_state(api):
    """PRD §2.6: "the server evaluates them in one fixed precedence ladder, and
    the earliest failing rung determines the error returned".
    PRD §3.8: "First, the shop must be `OPERATING`, failing with `ERR_SHOP_NOT_OPERATING` (HTTP 409). Second, every line's flavor must be orderable — in `LIMITED_RUN` or `CORE_LINE` — failing with `ERR_ORDER_FLAVOR_UNAVAILABLE` (HTTP 422). Third, the order's `total_cents` must fit within the shop's `credit_limit_cents`, with equality allowed, failing with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_confirm
    """
    # Mirror image: same shop and totals, but the order stays PLACED, so the
    # state rung passes and the fiscal rung reports its own error.
    shop = make_operating_shop(name="Tight Credit Mirror",
                               credit_limit_cents=100)
    flavor = make_limited_run_flavor(name="Mirror Pecan", pint_price_cents=199)
    order = make_supply_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 10}])
    assert order["total_cents"] == 1990
    resp = api.confirm_supply_order(order["id"], FA)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    after = get_success_data(api.get_supply_order(order["id"], FA))
    assert after["status"] == "PLACED"
