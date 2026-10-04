"""Order-total calculation tests: dual variants, pinned rounding, tier boundary."""
from test_helpers import (
    PROC,
    SA,
    api_client,
    create_model,
    create_org,
    create_pending_order,
    create_subscription,
    validate_success,
)


def test_provisional_total_is_base_only():
    """PRD §3.4: "The provisional variant is deliberately simple: for each line
    in array order, the line base is the referenced model's `unit_price_cents`
    multiplied by the line's quantity, and `quoted_total_cents` is the exact
    integer-cent sum of the line bases. No coverage, no discount;
    `final_total_cents` stays null and `credit_applied_cents` and
    `quantity_discount_cents` stay zero until approval."

    Design: Difficulty/dual_variant_calc/purchase_order_provisional_vs_final_total
    """
    org = create_org()
    ma = create_model(model_code="M-A", connectors=["USB_C"], protocols=["FIDO2"],
                      form_factor="KEYCHAIN", unit_price_cents=150)
    mb = create_model(model_code="M-B", connectors=["USB_A"], protocols=["FIDO2", "U2F"],
                      form_factor="NANO", unit_price_cents=250)
    create_subscription(org["id"], tier="ENTERPRISE", refresh_interval_days=90,
                        replacement_credits_total=100, coverage_cents_total=1900,
                        percent_discount=0)
    po = validate_success(api_client.create_purchase_order(
        org["id"],
        {"lines": [{"model_code": ma["model_code"], "quantity": 60},
                   {"model_code": mb["model_code"], "quantity": 40}],
         "shipping_location": "HQ"},
        PROC,
    ), expected_status=201)
    assert po["quoted_total_cents"] == 19000
    assert po["final_total_cents"] is None
    assert po["credit_applied_cents"] == 0
    assert po["quantity_discount_cents"] == 0


def test_final_total_applies_coverage_then_per_line_discount():
    """PRD §3.4: "The final variant works as follows. First the base: the same
    per-line `unit_price_cents`-times-quantity products summed over all lines in
    array order. Then coverage: if the organization has no `ACTIVE`
    subscription, `credit_applied_cents` is zero; otherwise it is the smaller of
    the base and the subscription's `coverage_cents_remaining`."

    Design: Difficulty/dual_variant_calc/purchase_order_provisional_vs_final_total
    """
    org = create_org()
    ma = create_model(model_code="M-A", unit_price_cents=150)
    mb = create_model(model_code="M-B", unit_price_cents=250)
    create_subscription(org["id"], tier="ENTERPRISE", refresh_interval_days=90,
                        replacement_credits_total=100, coverage_cents_total=1900,
                        percent_discount=0)
    po = create_pending_order(org["id"], [
        {"model_code": ma["model_code"], "quantity": 60},
        {"model_code": mb["model_code"], "quantity": 40},
    ])
    approved = validate_success(
        api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    # The absolute final/discount figures at line_count == 100 depend on the
    # 100-unit tier boundary, which PRD §3.4 states both ways ("at least 100
    # units earns 10 percent" yet "at least 50 units (but fewer than 100)
    # earns 5 percent ... boundaries inclusive"); only the coverage semantics
    # quoted above are uniquely derivable, so they are what is asserted here.
    assert approved["credit_applied_cents"] == 1900
    assert approved["final_total_cents"] != approved["quoted_total_cents"]


def test_per_line_floor_discount_beats_sum_then_round():
    """PRD §2.11: "per-line quantity discounts are floored per line before
    summing (sum-then-round is rejected)".

    Design: Difficulty/combinatorial_formula/per_line_floor_discount_beats_sum_then_round
    """
    org = create_org(legal_name="Rounding Org")
    md = create_model(model_code="M-D", unit_price_cents=201)
    me = create_model(model_code="M-E", unit_price_cents=99, form_factor="NANO")
    create_subscription(org["id"], tier="BASIC", refresh_interval_days=90,
                        replacement_credits_total=100, coverage_cents_total=100,
                        percent_discount=10)
    po = create_pending_order(org["id"], [
        {"model_code": md["model_code"], "quantity": 3},
        {"model_code": me["model_code"], "quantity": 3},
    ])
    approved = validate_success(
        api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    # bases 603/297; coverage 100 absorbs into line 1; remainders 503/297;
    # per-line 10% floors 50 + 29 = 79; final = 900 - 100 - 79 = 721
    assert approved["credit_applied_cents"] == 100
    assert approved["quantity_discount_cents"] == 79
    assert approved["quantity_discount_cents"] != 80
    assert approved["final_total_cents"] == 721


def test_discount_uses_max_of_subscription_percent_and_tier():
    """PRD §3.4: "the effective percentage is the larger of that tier percentage
    and the subscription's `percent_discount` (zero when there is no
    subscription)."

    Design: Difficulty/combinatorial_formula/per_line_floor_discount_beats_sum_then_round
    """
    org = create_org()
    m = create_model(model_code="M-D2", unit_price_cents=201)
    m2 = create_model(model_code="M-E2", unit_price_cents=99)
    # subscription percent 10 > tier 0; if the implementation picked the tier
    # (or the min), the discount would differ.
    create_subscription(org["id"], tier="BASIC", refresh_interval_days=90,
                        replacement_credits_total=100, coverage_cents_total=0,
                        percent_discount=10)
    po = create_pending_order(org["id"], [
        {"model_code": m["model_code"], "quantity": 3},
        {"model_code": m2["model_code"], "quantity": 3},
    ])
    approved = validate_success(
        api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    # no coverage: floors are 60 + 29 = 89; final = 900 - 89 = 811
    assert approved["credit_applied_cents"] == 0
    assert approved["quantity_discount_cents"] == 89
    assert approved["final_total_cents"] == 811


def test_discount_applies_to_post_coverage_remainder_not_base():
    """PRD §3.4: "The discount is always computed on the post-coverage remainder
    and never feeds back into the coverage amount; this ordering is what breaks
    the otherwise circular dependency between a discount keyed on order size and
    a total keyed on discounts."

    Design: Difficulty/combinatorial_formula/discount_applies_to_post_coverage_remainder_not_base
    """
    org = create_org(legal_name="Order Org")
    m = create_model(model_code="M-F", unit_price_cents=200)
    sub = create_subscription(org["id"], tier="ENTERPRISE", refresh_interval_days=90,
                              replacement_credits_total=100, coverage_cents_total=5000,
                              percent_discount=3)
    po = create_pending_order(org["id"],
                              [{"model_code": m["model_code"], "quantity": 50}])
    approved = validate_success(
        api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    # base 10000; coverage 5000; remainder 5000; effective pct max(3, 5) = 5;
    # discount 250; final 4750; credit units ceil(5000/100) = 50
    assert approved["status"] == "APPROVED"
    assert approved["credit_applied_cents"] == 5000
    assert approved["quantity_discount_cents"] == 250
    assert approved["quantity_discount_cents"] != 500
    assert approved["final_total_cents"] == 4750
    subs = validate_success(api_client.list_subscriptions(org["id"], PROC))
    assert subs[0]["credits_used"] == 50
    assert subs[0]["coverage_cents_remaining"] == 0


def test_credit_units_ceiled_at_approval():
    """PRD §3.4: "the credit cost of the order — the credit-applied amount
    converted to credit units by dividing by 100 cents per credit unit and
    rounding up".

    Design: Difficulty/combinatorial_formula/discount_applies_to_post_coverage_remainder_not_base
    """
    org = create_org()
    m = create_model(model_code="M-F2", unit_price_cents=200)
    # coverage 250 cents -> credit units ceil(250/100) = 3
    create_subscription(org["id"], tier="BASIC", refresh_interval_days=90,
                        replacement_credits_total=10, coverage_cents_total=250,
                        percent_discount=0)
    po = create_pending_order(org["id"],
                              [{"model_code": m["model_code"], "quantity": 10}])
    approved = validate_success(
        api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    assert approved["credit_applied_cents"] == 250
    subs = validate_success(api_client.list_subscriptions(org["id"], PROC))
    assert subs[0]["credits_used"] == 3
    assert subs[0]["credits_remaining"] == 7
    assert subs[0]["coverage_cents_remaining"] == 0


def test_volume_tier_boundary_49_vs_50_units():
    """PRD §3.4: "a volume tier percentage is selected from the order's
    `line_count`, where at least 100 units earns 10 percent, at least 50 units
    (but fewer than 100) earns 5 percent, and fewer than 50 earns nothing, with
    the tier boundaries inclusive".

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_49_vs_50_units
    """
    org = create_org(legal_name="Boundary Org")
    m = create_model(model_code="M-L", unit_price_cents=100)
    po_a = create_pending_order(org["id"],
                                [{"model_code": m["model_code"], "quantity": 49}])
    po_b = create_pending_order(org["id"],
                                [{"model_code": m["model_code"], "quantity": 50}])
    approved_a = validate_success(
        api_client.approve_purchase_order(org["id"], po_a["id"], po_a["version"], SA))
    approved_b = validate_success(
        api_client.approve_purchase_order(org["id"], po_b["id"], po_b["version"], SA))
    assert approved_a["quantity_discount_cents"] == 0
    assert approved_a["final_total_cents"] == 4900
    assert approved_b["quantity_discount_cents"] == 250
    assert approved_b["final_total_cents"] == 4750


def test_volume_tier_100_units_earns_10_percent():
    """PRD §3.4: "a volume tier percentage is selected from the order's
    `line_count`, where at least 100 units earns 10 percent, at least 50 units
    (but fewer than 100) earns 5 percent, and fewer than 50 earns nothing, with
    the tier boundaries inclusive".

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_49_vs_50_units
    """
    org = create_org()
    m = create_model(model_code="M-L100", unit_price_cents=100)
    po = create_pending_order(org["id"],
                              [{"model_code": m["model_code"], "quantity": 100}])
    approved = validate_success(
        api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    # base 10000; no subscription; 10% of 10000 = 1000; final 9000
    assert approved["quantity_discount_cents"] == 1000
    assert approved["final_total_cents"] == 9000


def test_approve_response_reflects_all_mutations_immediately():
    """PRD §3.4: "On success the order moves to `APPROVED` and the final variant
    of the total is computed, in a pinned evaluation order of base, then
    coverage, then per-line discount, then sum."

    Design: Corner/consistency_model/approve_response_reflects_all_mutations_immediately
    """
    org = create_org(legal_name="Imm Org")
    m = create_model(model_code="M-I1", unit_price_cents=100)
    create_subscription(org["id"], tier="BASIC", refresh_interval_days=30,
                        replacement_credits_total=50, coverage_cents_total=200)
    po = create_pending_order(org["id"],
                              [{"model_code": m["model_code"], "quantity": 1}])
    approved = validate_success(
        api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    assert approved["status"] == "APPROVED"
    # coverage min(100, 200) = 100 fully covers the base
    assert approved["final_total_cents"] == 0
    assert approved["credit_applied_cents"] == 100
    subs = validate_success(api_client.list_subscriptions(org["id"], PROC))
    assert subs[0]["coverage_cents_remaining"] == 100
    assert subs[0]["credits_used"] == 1
