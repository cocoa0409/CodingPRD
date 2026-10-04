"""The compensate/reopen pair and the station liability ledger."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_bag, get_station, get_report,
    delivered_bag_with_report, report_through_delivered, report_through_compensated,
    compensate_and_reopen, declare_outage, create_bag_payload, create_report_payload,
    weigh_ok, create_assign_makeup_payload, create_arrange_delivery_payload,
    create_special_item_payload,
)


def test_reopening_a_compensated_report_returns_the_delivered_liability(api):
    """PRD §3.11: "Reopening a compensated report is a compensating action, not a
    status edit: besides moving the report to `REOPENED` and setting
    `claim_status` back to `FILED`, it zeroes both `compensation_settled_cents`
    and `approved_cents`, returns `final_liability_cents` to its provisional
    haircut figure"
    PRD §3.11: "While the report's status is `REPORTED`, `INVESTIGATING`,
    `DELIVERY_ARRANGED`, `REOPENED` or `DELIVERED`, the recognised figure is
    three quarters of `compensation_offer_cents`"

    Design: Difficulty/compensating_invariant/report_reopen_restores_delivered_liability
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(
        scenario, report_type="DAMAGED", declared_value_cents=50000, add_item=False)

    delivered = report_through_delivered(report["id"])
    assert delivered["compensation_offer_cents"] == 0, \
        "a bag with no special items offers nothing"

    compensated = report_through_compensated(
        scenario, report["id"], requested_amount_cents=25000, approved_amount_cents=25000)
    assert compensated["status"] == "COMPENSATED"
    assert compensated["compensation_settled_cents"] == 0

    reopened = validate_success(api.reopen_report(
        report["id"], compensated["version"],
        TEST_USERS["baggage_service_agent_headers"]), 200)
    assert reopened["status"] == "REOPENED"
    assert reopened["compensation_settled_cents"] == 0
    assert reopened["approved_cents"] == 0
    assert reopened["final_liability_cents"] == 0, \
        "the recognised figure returns to the haircut branch, which is zero here"
    assert reopened["claim_status"] == "FILED"


def test_the_reopen_moves_the_value_between_the_ledger_halves(api):
    """PRD §2.14: "The open figure is the sum of `final_liability_cents` across
    the station's mishandled reports whose status is one of `REPORTED`,
    `INVESTIGATING`, `DELIVERY_ARRANGED` or `REOPENED`."
    PRD §2.14: "Every report row lands in exactly one of the two halves, so a
    status change moves value between them and never creates or destroys it"

    Design: Difficulty/compensating_invariant/report_reopen_restores_delivered_liability
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(
        scenario, report_type="DAMAGED", declared_value_cents=50000, add_item=False)
    delivered = report_through_delivered(report["id"])

    settled_station = get_station(scenario["st"])
    assert settled_station["settled_liability_cents"] == 0
    assert settled_station["open_liability_cents"] == 0

    compensated = report_through_compensated(
        scenario, report["id"], requested_amount_cents=25000, approved_amount_cents=25000)
    reopened = validate_success(api.reopen_report(
        report["id"], compensated["version"],
        TEST_USERS["baggage_service_agent_headers"]), 200)

    restored = get_station(scenario["st"])
    assert restored["open_liability_cents"] == 0, "a zero-liability report moves no value"
    assert restored["settled_liability_cents"] == 0
    assert restored["open_liability_cents"] + restored["settled_liability_cents"] == \
        delivered["final_liability_cents"], \
        "the two halves together equal the sum of the report's recognised liability"


def test_the_reopen_leaves_the_bag_charge_total_frozen(api):
    """PRD §3.4: "A base term of 700 cents plus 25 cents for each rounded pound is
    formed. A special-item term of 2600 cents for each `SpecialItem` row on the
    bag is added"
    PRD §3.4: "Once the bag's custody status has reached `LOADED`, `DELIVERED` or
    `OFFLOADED` the charge is final, and it is recomputed on load, delivery and
    offload."

    Design: Difficulty/compensating_invariant/post_compensate_reopen_restores_paid_claim_charge
    """
    scenario = base_scenario(airline_overrides={"compensation_cap_cents": 300000})
    # The pipeline runs with the station open — a declared outage forces the
    # posture to SUSPENDED and PRD §2.6 refuses sortation, loading and delivery
    # writes there — and the outage this test asserts on is declared afterwards.
    _, bag, report = delivered_bag_with_report(
        scenario, report_type="DAMAGED", item_type="OVERSIZE",
        declared_value_cents=50000, weight_lb=52, scale_weight_lb=52.4,
        deliver_utc="2026-09-01T13:40:00Z")

    declare_outage(scenario)
    delivered = report_through_delivered(report["id"])
    assert delivered["status"] == "DELIVERED"
    # PRD §3.11: a DAMAGED report applies one half to the highest declared
    # special-item value — 25000 — then clamps against the lowest
    # `liability_cap_cents` among the bag's items, which for the single OVERSIZE
    # item is 50000.  Three quarters of the delivered-branch 31250 offer is 23438.
    assert delivered["final_liability_cents"] == 23438

    charge_after_delivery = get_bag(bag["id"])["handling_charge_cents"]
    assert charge_after_delivery == 4600, \
        "700 + 25*52 plus one 2600 special-item row is 4600, and the outage never held the bag"

    charged_bag = get_bag(bag["id"])
    assert charged_bag["excess_weight_fee_cents"] == 7500, \
        "the fee took its CURRENT variant when the bag was weighed with the station open, and a later outage does not re-price it"


def test_the_round_trip_restores_the_report_side_money_exactly(api):
    """PRD §3.11: "The two branches agree exactly when the settled amount equals
    three quarters of the offer, which is what the settlement rule in §3.12
    produces whenever the approved claim reaches the full offer."
    PRD §2.14: "at every instant the two halves together equal the sum of
    `final_liability_cents` over all the station's reports"

    Design: Difficulty/compensating_invariant/post_compensate_reopen_restores_paid_claim_charge
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(
        scenario, report_type="DAMAGED", item_type="OVERSIZE",
        declared_value_cents=50000, weight_lb=52, scale_weight_lb=52.4,
        deliver_utc="2026-09-01T13:40:00Z")
    declare_outage(scenario)
    delivered = report_through_delivered(report["id"])

    pre_payout_charge = get_bag(bag["id"])["handling_charge_cents"]
    pre_payout_ledger = get_station(scenario["st"])

    compensated, reopened = compensate_and_reopen(
        scenario, report["id"], requested_amount_cents=25000, approved_amount_cents=25000)

    assert compensated["compensation_settled_cents"] == 23438
    assert compensated["final_liability_cents"] == 23438
    # PRD §3.11: reopening "returns `final_liability_cents` to its provisional
    # haircut figure" — three quarters of the 25000 provisional-branch offer,
    # which is the 18750 the report carried before it delivered and re-branched.
    assert reopened["final_liability_cents"] == 18750, \
        "the reopened report sits in the haircut branch, whose offer is the provisional one"
    assert get_bag(bag["id"])["handling_charge_cents"] == pre_payout_charge, \
        "the payout and its reversal move no bag charge"

    restored_ledger = get_station(scenario["st"])
    assert restored_ledger["open_liability_cents"] == pre_payout_ledger["open_liability_cents"] + 18750
    assert restored_ledger["settled_liability_cents"] == 0