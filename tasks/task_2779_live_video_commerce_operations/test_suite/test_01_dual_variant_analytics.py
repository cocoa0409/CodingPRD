"""The two computations that exist in two variants: show margin and host effectiveness."""

from test_helpers import (
    api_client,
    adjust_inventory,
    approved_question,
    base_scenario,
    capture_order,
    checkout_cart_of,
    end_scenario,
    hold_line,
    host_action,
    make_show_producer_headers,
    open_cart,
    publish_marker,
    read_order,
    read_show,
    record_conversion,
    set_clock,
    set_marker,
    validate_success,
)

PRODUCER_HEADERS = make_show_producer_headers()


def _two_orders_one_captured():
    """Two in-stream orders on one live show: the first captured, the second left authorised."""
    scenario = base_scenario()
    hold_line(scenario, 2, cart_index=0)
    hold_line(scenario, 1, cart_index=1)
    order_one = checkout_cart_of(scenario, 0)
    order_two = checkout_cart_of(scenario, 1)
    capture_order(order_one["id"])
    return scenario, order_one, order_two


def _analytics(show_id, variant):
    response = api_client.get_show_analytics(show_id, PRODUCER_HEADERS, params={"variant": variant})
    return validate_success(response)


def _performance(host_id, show_id, variant):
    response = api_client.get_host_performance(
        host_id, PRODUCER_HEADERS, params={"variant": variant, "show_id": show_id}
    )
    return validate_success(response)


def test_two_baskets_price_and_tax_independently_at_checkout():
    """Two units of a 3500-cent offer reach the 50-dollar bundle tier and one unit does not.

    The PRD pins the four-step order: the tier is selected from the undiscounted
    subtotal, the effective unit price is "the line's offer_unit_price_cents
    multiplied by one minus bundle_discount_pct, rounded half up to a whole cent",
    the line gross is computed from the already-rounded per-unit figure, and
    shipping "is a flat 5.99 dollars, except that it is zero when
    merchandise_cents reaches at least 75 dollars".

    Design: Difficulty/dual_variant_calc/show_margin_provisional_vs_final_diverge
    """
    scenario, order_one, order_two = _two_orders_one_captured()

    two_unit_order = read_order(order_one["id"])
    assert two_unit_order["merchandise_cents"] == 6650
    assert two_unit_order["tax_cents"] == 582
    assert two_unit_order["shipping_cents"] == 599
    assert two_unit_order["total_cents"] == 7831

    one_unit_order = read_order(order_two["id"])
    assert one_unit_order["merchandise_cents"] == 3500
    assert one_unit_order["tax_cents"] == 306
    assert one_unit_order["shipping_cents"] == 599
    assert one_unit_order["total_cents"] == 4405


def test_capture_accrues_commission_on_merchandise_at_the_primary_host_rate():
    """Capture stamps the host's commission on the order's merchandise figure.

    The PRD: capture "stamps host_commission_accrued_cents as the order's
    merchandise_cents multiplied by the commission_pct of the host holding this
    show's PRIMARY booking, rounded half up to a whole cent" — 6650 at 8 percent
    is 532 cents.

    Design: Difficulty/dual_variant_calc/show_margin_provisional_vs_final_diverge
    """
    scenario, order_one, order_two = _two_orders_one_captured()

    captured = read_order(order_one["id"])
    assert captured["payment_state"] == "CAPTURED"
    assert captured["host_commission_accrued_cents"] == 532

    still_authorised = read_order(order_two["id"])
    assert still_authorised["payment_state"] == "AUTHORIZED"
    assert still_authorised["host_commission_accrued_cents"] == 0


def test_provisional_margin_counts_authorised_revenue_at_the_slot_cost_snapshot():
    """The provisional variant is the in-flight view and stamps itself onto the show.

    The PRD: provisional "merchandise_revenue_cents is the sum of
    merchandise_cents across this show's orders whose payment_state is AUTHORIZED
    or CAPTURED", cogs uses "the cost frozen when the slot was created",
    "return_provision_cents is 0", and "requesting the provisional variant stamps
    its result into Show.margin_provisional_cents as a side effect". The show's
    gross_merchandise_cents meanwhile counts only captured orders.

    Design: Difficulty/dual_variant_calc/show_margin_provisional_vs_final_diverge
    """
    scenario, order_one, order_two = _two_orders_one_captured()

    provisional = _analytics(scenario.show_id, "PROVISIONAL")
    assert provisional["order_count"] == 2
    assert provisional["merchandise_revenue_cents"] == 10150
    assert provisional["cogs_cents"] == 4500
    assert provisional["return_provision_cents"] == 0
    assert provisional["host_commission_cents"] == 812
    assert provisional["margin_cents"] == 4838
    assert provisional["gross_merchandise_cents"] == 6650

    assert read_show(scenario.show_id)["margin_provisional_cents"] == 4838


def test_final_margin_drops_authorised_revenue_and_revalues_cost_after_a_revision():
    """The final variant reads the current catalogue cost and takes a return provision.

    The PRD: the final variant "counts only orders whose payment_state is
    CAPTURED", "cogs_cents revalues the same committed lines at the product's
    current unit_cost_cents rather than at the slot snapshot", net of returns is
    "merchandise_revenue_cents multiplied by one minus a return provision of 6
    percent, rounded half up", commission is taken on "the rounded
    net_of_returns_cents", and "margin_cents is net_of_returns_cents less
    cogs_cents less host_commission_cents".

    Design: Difficulty/dual_variant_calc/show_margin_provisional_vs_final_diverge
    """
    scenario, order_one, order_two = _two_orders_one_captured()

    _analytics(scenario.show_id, "PROVISIONAL")
    adjust_inventory(scenario.product_id, reason="COST_REVISION", unit_cost_cents=1800)

    final = _analytics(scenario.show_id, "FINAL")
    assert final["order_count"] == 1
    assert final["merchandise_revenue_cents"] == 6650
    assert final["cogs_cents"] == 3600
    assert final["return_provision_cents"] == 399
    assert final["host_commission_cents"] == 500
    assert final["margin_cents"] == 2151


def test_the_two_margin_variants_diverge_on_identical_order_rows():
    """On one unchanged pair of orders the provisional margin exceeds the final one.

    The PRD: "Because the provisional variant counts unsettled revenue, values
    cost at the older snapshot, and takes no return provision, it reports a higher
    margin than the final variant for identical data."

    Design: Difficulty/dual_variant_calc/show_margin_provisional_vs_final_diverge
    """
    scenario, order_one, order_two = _two_orders_one_captured()

    provisional = _analytics(scenario.show_id, "PROVISIONAL")
    adjust_inventory(scenario.product_id, reason="COST_REVISION", unit_cost_cents=1800)
    final = _analytics(scenario.show_id, "FINAL")

    assert provisional["margin_cents"] == 4838
    assert final["margin_cents"] == 2151
    assert final["margin_cents"] < provisional["margin_cents"]


def _show_with_replay_history():
    """One aired show with two authorised orders, four carts, one answered question
    and two decay-weighted replay conversions."""
    scenario = base_scenario()
    hold_line(scenario, 2, cart_index=0)
    hold_line(scenario, 1, cart_index=1)
    checkout_cart_of(scenario, 0)
    checkout_cart_of(scenario, 1)
    open_cart(scenario.show_id, scenario.viewers[0]["id"])
    open_cart(scenario.show_id, scenario.viewers[1]["id"])

    question = approved_question(scenario, viewer_index=0, route=True)
    host_action(
        question["id"], "ANSWER", scenario.host_id, answer_body="Cold wash only, no shrinkage."
    )

    end_scenario(scenario, "2026-08-10T19:30:00Z")
    set_marker(scenario.slot_id, marker_offset_sec=600)
    publish_marker(scenario.slot_id)

    set_clock("2026-08-13T00:00:00Z")
    record_conversion(
        scenario.slot_id,
        scenario.viewers[0]["id"],
        net_revenue_cents=4000,
        occurred_at="2026-08-10T23:30:00Z",
    )
    record_conversion(
        scenario.slot_id,
        scenario.viewers[1]["id"],
        net_revenue_cents=4000,
        occurred_at="2026-08-12T01:30:00Z",
    )
    return scenario


def test_both_effectiveness_variants_gather_the_same_seven_raw_quantities():
    """The variants differ only in the order count, so every raw quantity matches.

    The PRD: "The two variants differ only in the effective order count feeding
    the conversion component", over the seven quantities live_orders_count,
    unique_cart_count, replay_conversions_count, answered_questions_count,
    poll_votes_count, late_ack_count and the unsubstantiated-claim indicator.

    Design: Difficulty/dual_variant_calc/host_score_live_window_vs_attributed_72h
    """
    scenario = _show_with_replay_history()

    live = _performance(scenario.host_id, scenario.show_id, "LIVE_WINDOW")
    attributed = _performance(scenario.host_id, scenario.show_id, "ATTRIBUTED_72H")

    for report in (live, attributed):
        assert report["live_orders_count"] == 2
        assert report["unique_cart_count"] == 4
        assert report["replay_conversions_count"] == 2
        assert report["answered_questions_count"] == 1
        assert report["poll_votes_count"] == 0
        assert report["late_ack_count"] == 0


def test_live_window_effectiveness_ignores_replay_conversions_entirely():
    """Two live orders over four carts convert at 50 percent and score 48.

    The PRD: the LIVE_WINDOW variant "uses live_orders_count alone and ignores
    replay conversions entirely"; the conversion component "divides the effective
    order count by the larger of unique_cart_count and 1, multiplies by 100,
    rounds half up", engagement "awards 10 points per answered question and 2
    points per poll vote", compliance "starts at 100", and the score is the
    weighted sum at 0.5, 0.3 and 0.2 "rounded half up exactly once at the end".

    Design: Difficulty/dual_variant_calc/host_score_live_window_vs_attributed_72h
    """
    scenario = _show_with_replay_history()

    live = _performance(scenario.host_id, scenario.show_id, "LIVE_WINDOW")
    assert live["conversion_component"] == 50
    assert live["engagement_component"] == 10
    assert live["compliance_component"] == 100
    assert live["effectiveness_score"] == 48


def test_attributed_variant_adds_half_an_order_for_each_replay_conversion():
    """Two replay conversions lift the effective order count from 2 to 3 and the score to 61.

    The PRD: the ATTRIBUTED_72H variant "adds half an order for each replay
    conversion: the effective count is live_orders_count plus
    replay_conversions_count multiplied by 0.5", and "For identical data the
    attributed variant therefore yields a score greater than or equal to the
    live-window variant, never lower."

    Design: Difficulty/dual_variant_calc/host_score_live_window_vs_attributed_72h
    """
    scenario = _show_with_replay_history()

    live = _performance(scenario.host_id, scenario.show_id, "LIVE_WINDOW")
    attributed = _performance(scenario.host_id, scenario.show_id, "ATTRIBUTED_72H")

    assert attributed["conversion_component"] == 75
    assert attributed["engagement_component"] == 10
    assert attributed["compliance_component"] == 100
    assert attributed["effectiveness_score"] == 61
    assert attributed["effectiveness_score"] > live["effectiveness_score"]


def test_each_effectiveness_read_stamps_its_own_variant_onto_the_host():
    """The host carries one field per variant, each holding the latest value computed.

    The PRD: "Requesting the live-window variant stamps its result into the host's
    effectiveness_score_live; requesting the attributed variant stamps it into
    effectiveness_score_attributed."

    Design: Difficulty/dual_variant_calc/host_score_live_window_vs_attributed_72h
    """
    scenario = _show_with_replay_history()

    _performance(scenario.host_id, scenario.show_id, "LIVE_WINDOW")
    _performance(scenario.host_id, scenario.show_id, "ATTRIBUTED_72H")

    host = validate_success(api_client.get_host(scenario.host_id, PRODUCER_HEADERS))
    assert host["effectiveness_score_live"] == 48
    assert host["effectiveness_score_attributed"] == 61


def test_replay_revenue_accumulates_per_conversion_at_its_own_decay_weight():
    """A conversion four hours after the close weights fully; one thirty hours later weights 0.6.

    The PRD: "Within the first day — an elapsed figure of 24 hours or fewer — the
    conversion carries full weight of 1.0. Beyond that but within two days — 48
    hours or fewer — it carries 0.6", each product "rounded half up to a whole cent
    per conversion before it is added to the running total", and the show's figure
    "is then recomputed as the sum of replay_attributed_revenue_cents across all of
    that show's slots".

    Design: Difficulty/dual_variant_calc/host_score_live_window_vs_attributed_72h
    """
    scenario = _show_with_replay_history()

    slot = validate_success(api_client.get_lineup_slot(scenario.slot_id, PRODUCER_HEADERS))
    assert slot["replay_conversions_count"] == 2
    assert slot["replay_attributed_revenue_cents"] == 6400

    assert read_show(scenario.show_id)["replay_attributed_revenue_cents"] == 6400
