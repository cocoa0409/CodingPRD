"""The money rules: compensation offer, liability branches and settlement clamping."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_bag, get_station, list_rows,
    delivered_bag_with_report, report_through_delivered, cycle_report_to_closed,
    create_bag_payload, create_special_item_payload, create_report_payload,
    weigh_ok, screen_ok, create_assign_makeup_payload, create_arrange_delivery_payload,
    base_scenario as _scenario, declare_outage,
)


def test_compensation_offer_is_provisional_until_the_report_delivers(api):
    """PRD §3.11: "While the report's status is `REPORTED`, `INVESTIGATING` or
    `DELIVERY_ARRANGED` the fraction is used as declared. Once the report reaches
    `DELIVERED` or `COMPENSATED` the fraction is multiplied by 1.25 before the
    caps are applied"
    PRD §3.11: "a `DAMAGED` report on a bag whose highest declared special-item
    value is 120000 cents, with a carrier cap of 300000, offers 60000 while
    provisional and 75000 once the report has delivered."

    Design: Difficulty/dual_variant_calc/compensation_offer_provisional_versus_final_on_a_damaged_bag
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(
        scenario, report_type="DAMAGED", declared_value_cents=120000)

    investigating = get_success_data(api.investigate_report(
        report["id"], TEST_USERS["baggage_service_agent_headers"]))
    assert investigating["compensation_offer_cents"] == 60000, \
        "the DAMAGED half applied as declared and unclamped"

    arranged = get_success_data(api.arrange_delivery(
        report["id"],
        create_arrange_delivery_payload(delivery_method="COURIER",
                                        scheduled_utc="2026-09-01T14:20:00Z"),
        TEST_USERS["baggage_service_agent_headers"]))
    assert arranged["compensation_offer_cents"] == 60000

    delivered = get_success_data(api.mark_report_delivered(
        report["id"], TEST_USERS["baggage_service_agent_headers"]))
    assert delivered["compensation_offer_cents"] == 75000, \
        "the delivered branch multiplies the DAMAGED fraction by 1.25"


def test_the_offer_variant_is_selected_by_the_report_status_not_the_inputs(api):
    """PRD §3.11: "The order is pinned — the fraction is applied first and the
    two caps second, and since a minimum is commutative the two caps' relative
    order makes no difference."

    Design: Difficulty/dual_variant_calc/compensation_offer_provisional_versus_final_on_a_damaged_bag
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(
        scenario, report_type="DAMAGED", declared_value_cents=120000)
    delivered = report_through_delivered(report["id"])

    assert delivered["status"] == "DELIVERED"
    assert delivered["compensation_offer_cents"] == 75000, \
        "the offer moved purely because the branch changed"


def test_final_liability_carries_the_haircut_while_the_report_is_unsent(api):
    """PRD §3.11: "While the report's status is `REPORTED`, `INVESTIGATING`,
    `DELIVERY_ARRANGED`, `REOPENED` or `DELIVERED`, the recognised figure is three
    quarters of `compensation_offer_cents`, rounded half-up to a whole cent"

    Design: Difficulty/combinatorial_formula/final_liability_branches_on_the_entity_state_before_clamping
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(
        scenario, report_type="DAMAGED", declared_value_cents=120000)

    investigating = get_success_data(api.investigate_report(
        report["id"], TEST_USERS["baggage_service_agent_headers"]))
    assert investigating["compensation_offer_cents"] == 60000
    assert investigating["final_liability_cents"] == 45000, \
        "three quarters of the provisional 60000 offer"

    delivered = report_through_delivered(report["id"])
    assert delivered["compensation_offer_cents"] == 75000
    assert delivered["final_liability_cents"] == 56250, \
        "three quarters of the moved 75000 offer"


def test_delivered_liability_stays_in_the_open_ledger_half(api):
    """PRD §3.11: "note that `DELIVERED` sits in this branch, so a
    delivered-but-unsettled report still carries the haircut."
    PRD §2.14: "A report that has been `DELIVERED` is not yet settled money, and
    it belongs to the settled half only because the delivery leg is complete"

    Design: Difficulty/combinatorial_formula/final_liability_branches_on_the_entity_state_before_clamping
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(
        scenario, report_type="DAMAGED", declared_value_cents=120000)
    delivered = report_through_delivered(report["id"])

    station = get_station(scenario["st"])
    assert station["open_liability_cents"] == 0, "DELIVERED is not in the open status set"
    assert station["settled_liability_cents"] == 56250


def test_oversize_fee_rounds_each_item_before_summing(api):
    """PRD §3.4: "three `FRAGILE` items on a bag measuring 120 inches give a raw
    25218.75 cents per item, which rounds per item to 25219 and sums to 75657,
    whereas summing first gives 75656.25 and rounds once to 75656 — a one-cent
    divergence in which the per-item order is the specified one."

    Design: Difficulty/combinatorial_formula/oversize_fee_rounds_per_item_before_summing
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], weight_lb=48, length_in=40,
                           width_in=40, height_in=40),
        TEST_USERS["acceptance_agent_headers"]))
    assert bag["linear_in"] == 120

    item_ids = []
    for _ in range(3):
        item = get_success_data(api.add_special_item(
            bag["id"], create_special_item_payload(item_type="FRAGILE",
                                                   declared_value_cents=30000),
            TEST_USERS["acceptance_agent_headers"]))
        item_ids.append(item["id"])

    last = list_rows(api.list_bag_special_items(
        bag["id"], TEST_USERS["acceptance_agent_headers"]))[-1]
    assert last["handling_fee_cents"] == 25219, \
        "6725 times 1.25 times scale 3 is 25218.75, rounded per item"

    weighed = weigh_ok(bag["id"], 48.0)
    assert weighed["oversize_handling_fee_cents"] == 75657, \
        "three per-item-rounded 25219s, never the summed-first 75656"


def test_oversize_fee_is_zero_for_a_bag_with_no_special_items(api):
    """PRD §3.4: "A bag carrying no special items has an oversize handling fee of
    zero, and the field is not recomputed during weighing for such a bag."

    Design: Difficulty/combinatorial_formula/oversize_fee_rounds_per_item_before_summing
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], weight_lb=48, length_in=40,
                           width_in=40, height_in=40),
        TEST_USERS["acceptance_agent_headers"]))
    weighed = weigh_ok(bag["id"], 48.0)
    assert weighed["oversize_handling_fee_cents"] == 0


def test_item_size_scale_follows_the_baggage_linear_measure(api):
    """PRD §3.4: "scale 1 when the baggage linear measure is 62 inches or less,
    scale 2 when it is greater than 62 and at most 115 inches, and scale 3 when it
    exceeds 115 inches."

    Design: Difficulty/combinatorial_formula/oversize_fee_rounds_per_item_before_summing
    """
    scenario = base_scenario()
    small = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], length_in=20, width_in=14, height_in=16),
        TEST_USERS["acceptance_agent_headers"]))
    assert small["linear_in"] == 50

    item = get_success_data(api.add_special_item(
        small["id"], create_special_item_payload(item_type="OVERSIZE",
                                                 declared_value_cents=50000),
        TEST_USERS["acceptance_agent_headers"]))
    assert item["handling_fee_cents"] == 4500, \
        "an OVERSIZE item on a scale-1 bag carries the raw per-item fee"


def test_compensation_settlement_clamps_the_applied_amount_to_the_liability(api):
    """PRD §3.12: "the amount actually applied — the figure written to the
    report's `compensation_settled_cents` — is the approved figure further
    limited by the report's `final_liability_cents` as that field stood before
    the transition began."

    Design: Difficulty/combinatorial_formula/compensation_settlement_pins_the_pre_transition_liability
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(
        scenario, report_type="DAMAGED", declared_value_cents=120000)
    delivered = report_through_delivered(report["id"])
    assert delivered["final_liability_cents"] == 56250

    claim = get_success_data(api.file_claim(
        report["id"], 100000, TEST_USERS["baggage_service_agent_headers"]))
    decided = get_success_data(api.decide_claim(
        claim["id"], {"decision": "APPROVED", "approved_amount_cents": 100000},
        TEST_USERS["baggage_service_agent_headers"]))
    assert decided["decision"] == "APPROVED"

    compensated = validate_success(api.compensate_report(
        report["id"], TEST_USERS["baggage_service_agent_headers"]), 200)
    assert compensated["status"] == "COMPENSATED"
    assert compensated["approved_cents"] == 75000, \
        "the filing of 100000 was clamped by the 75000 offer first"
    assert compensated["compensation_settled_cents"] == 56250, \
        "the applied amount is clamped by the pre-transition recognised liability"


def test_the_settled_amount_and_the_approved_amount_legitimately_disagree(api):
    """PRD §3.12: "The clamp in the second step can legitimately leave the two
    report fields disagreeing, and that disagreement is specified behaviour rather
    than a bug: when the approved figure exceeds the pre-transition recognised
    liability, the applied amount is held down to the liability while the approved
    amount keeps its higher value."

    Design: Difficulty/combinatorial_formula/compensation_settlement_pins_the_pre_transition_liability
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(
        scenario, report_type="DAMAGED", declared_value_cents=120000)
    report_through_delivered(report["id"])
    claim = get_success_data(api.file_claim(
        report["id"], 100000, TEST_USERS["baggage_service_agent_headers"]))
    api.decide_claim(claim["id"],
                     {"decision": "APPROVED", "approved_amount_cents": 100000},
                     TEST_USERS["baggage_service_agent_headers"])
    compensated = validate_success(api.compensate_report(
        report["id"], TEST_USERS["baggage_service_agent_headers"]), 200)

    assert compensated["approved_cents"] != compensated["compensation_settled_cents"]
    assert compensated["final_liability_cents"] == 56250, \
        "the realised branch records the settled amount in full"


def test_the_station_ledger_moves_fully_into_the_settled_half(api):
    """PRD §2.14: "The settled figure is the sum over reports whose status is one
    of `DELIVERED`, `COMPENSATED` or `CLOSED`."

    Design: Difficulty/combinatorial_formula/compensation_settlement_pins_the_pre_transition_liability
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(
        scenario, report_type="DAMAGED", declared_value_cents=120000)
    report_through_delivered(report["id"])
    claim = get_success_data(api.file_claim(
        report["id"], 100000, TEST_USERS["baggage_service_agent_headers"]))
    api.decide_claim(claim["id"],
                     {"decision": "APPROVED", "approved_amount_cents": 100000},
                     TEST_USERS["baggage_service_agent_headers"])
    api.compensate_report(report["id"], TEST_USERS["baggage_service_agent_headers"])

    station = get_station(scenario["st"])
    assert station["open_liability_cents"] == 0
    assert station["settled_liability_cents"] == 56250