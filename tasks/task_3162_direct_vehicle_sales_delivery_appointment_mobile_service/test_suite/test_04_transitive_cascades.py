"""Multi-hop cascades: one write reaching several orders and several aggregates."""
from test_helpers import (
    TEST_USERS,
    create_and_enact_jurisdiction,
    create_and_start_batch,
    create_appraisal_payload,
    create_center,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    dispatch_and_arrive,
    get_order,
    get_success_data,
    lock_order,
    next_vin,
    place_order,
    set_clock,
    settle_order_fee,
    walk_order_to_at_delivery_center,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADVISOR = TEST_USERS["delivery_advisor_headers"]
TRADEIN = TEST_USERS["trade_in_specialist_headers"]


def _two_orders_on_one_batch(api):
    """Two verified buyers, two sites, two orders allocated from one batch."""
    jur = create_and_enact_jurisdiction()
    center_a = create_center(center_name="Austin Delivery")
    center_b = create_center(center_name="Dallas Delivery", van_count=2)
    config, _ = create_published_configuration()

    buyer_a = create_verified_buyer(full_name="Eli Cascade",
                                    email="eli.cascade@example.com")
    buyer_b = create_verified_buyer(full_name="Faye Cascade",
                                    email="faye.cascade@example.com")

    order_a = create_order(buyer_a["id"], config["id"], jur["id"], center_a["id"])
    order_b = create_order(buyer_b["id"], config["id"], jur["id"], center_b["id"])

    settle_order_fee(order_a["id"])
    placed_a = place_order(order_a["id"], order_a["version"], buyer_a["id"])
    locked_a = lock_order(order_a["id"], placed_a["version"])

    settle_order_fee(order_b["id"])
    placed_b = place_order(order_b["id"], order_b["version"], buyer_b["id"])
    locked_b = lock_order(order_b["id"], placed_b["version"])

    batch, _unit = create_and_start_batch(
        unit_capacity=3, planned_completion_at="2026-09-10T00:00:00Z")
    get_success_data(api.mint_allocation_unit(batch["id"], next_vin(), ADMIN))
    get_success_data(api.mint_allocation_unit(batch["id"], next_vin(), ADMIN))

    get_success_data(api.allocate_order(order_a["id"], batch["id"], locked_a["version"], ADMIN))
    get_success_data(api.allocate_order(order_b["id"], batch["id"], locked_b["version"], ADMIN))
    dispatch_and_arrive(order_a["id"])
    dispatch_and_arrive(order_b["id"])
    return jur, center_a, center_b, batch, buyer_a, buyer_b, order_a, order_b


class TestProductionDelayCascade:
    """PRD §3.4: a batch delay propagates through estimates and appointments."""

    def test_delay_propagates_a_shifted_window_to_every_affected_order(self, api):
        """PRD §3.4: "It then propagates to every order holding a unit of that
        batch whose status is `ALLOCATED`, `IN_TRANSIT`, or `ARRIVED`."
        PRD §3.4: "For each affected order the current `PROVISIONAL` or `FIRM`
        estimate is superseded and a fresh estimate is created whose window start
        is the prior estimate's start plus the delay and whose window end is the
        prior estimate's end plus the delay"

        Design: Difficulty/transitive_cascade/production_delay_three_hop_cascade_across_two_orders
        """
        set_clock()
        jur, center_a, center_b, batch, buyer_a, buyer_b, order_a, order_b = \
            _two_orders_on_one_batch(api)

        before_a = get_success_data(api.list_order_estimates(order_a["id"], ADMIN))
        live_a = [e for e in before_a if e["estimate_state"] in ("PROVISIONAL", "FIRM")][0]

        delayed = get_success_data(api.delay_batch(batch["id"], 9, ADMIN))
        assert delayed["status"] == "DELAYED"

        after_a = get_success_data(api.list_order_estimates(order_a["id"], ADMIN))
        fresh = [e for e in after_a
                 if e["estimate_state"] in ("PROVISIONAL", "FIRM")][0]
        assert after_a != before_a
        assert fresh["prior_estimate_id"] == live_a["id"]

        after_b = get_success_data(api.list_order_estimates(order_b["id"], ADMIN))
        assert len([e for e in after_b if e["estimate_state"] in ("PROVISIONAL", "FIRM")]) == 1

    def test_shifted_window_pushes_a_confirmed_appointment_to_at_risk(self, api):
        """PRD §3.4: "Finally, any `CONFIRMED` handover appointment at that order
        whose `scheduled_start` is now passed by the shifted window end moves to
        `AT_RISK`, and each appointment that moves to `AT_RISK` returns its order
        to `AT_DELIVERY_CENTER`."
        PRD §3.6: "An appointment moves to `AT_RISK` without anyone asking, when a
        delivery estimate on its linked order pushes the projected window past the
        appointment's `scheduled_start`."

        Design: Difficulty/transitive_cascade/production_delay_three_hop_cascade_across_two_orders
        """
        set_clock()
        jur, center_a, center_b, batch, buyer_a, buyer_b, order_a, order_b = \
            _two_orders_on_one_batch(api)

        appointment = get_success_data(api.book_delivery_appointment(
            {"order_id": order_a["id"], "delivery_center_id": center_a["id"],
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-18T15:00:00Z",
             "scheduled_end": "2026-09-18T16:00:00Z",
             "expected_order_version": get_order(order_a["id"])["version"]},
            ADVISOR))
        get_success_data(api.confirm_delivery_appointment(appointment["id"], ADVISOR))

        get_success_data(api.delay_batch(batch["id"], 9, ADMIN))

        risky = get_success_data(api.get_delivery_appointment(appointment["id"], ADVISOR))
        assert risky["status"] == "AT_RISK"
        assert get_order(order_a["id"])["status"] == "AT_DELIVERY_CENTER"


class TestTradeInOfferExpiryCompensation:
    """PRD §3.3: an offer that lapses owes a compensating reversal."""

    def test_lapsed_offer_moves_to_expired_and_reverses_its_credit(self, api):
        """PRD §3.3: "An `OFFERED` appraisal that is not accepted before its
        validity instant lapses to `EXPIRED`, and lapse owes a compensation: a
        `TRADE_IN_CREDIT_REVERSAL` entry for the negated `net_credit_cents` is
        written so that the buyer's balance returns to exactly its pre-offer value."

        Design: Difficulty/transitive_cascade/trade_in_offer_expiry_compensating_two_hop_chain
        """
        set_clock()
        ctx = walk_order_to_at_delivery_center(buyer_name="Faye Chain")
        order = ctx["order"]

        appraisal = get_success_data(api.create_appraisal(
            order["id"],
            create_appraisal_payload(trade_vin="5YJ3E1EA7PF000901", mileage=90000,
                                     gross_offer_cents=1200000,
                                     reconditioning_estimate_cents=60000,
                                     offer_valid_until="2026-09-22T00:00:00Z"),
            TRADEIN))
        get_success_data(api.appraise(order["id"], appraisal["id"], TRADEIN))
        offered = get_success_data(api.offer_appraisal(order["id"], appraisal["id"], TRADEIN))
        credit = offered["net_credit_cents"]
        assert credit == 940000, "90000 miles binds the 200000-cent mileage cap"

        get_success_data(api.set_current_utc("2026-09-23T00:00:00Z", ADMIN))

        expired = get_success_data(api.get_appraisal(appraisal["id"], TRADEIN))
        assert expired["status"] == "EXPIRED"

    def test_compensating_reversal_restores_the_buyer_balance(self, api):
        """PRD §3.3: "a `TRADE_IN_CREDIT_REVERSAL` entry for the negated
        `net_credit_cents` is written so that the buyer's balance returns to exactly
        its pre-offer value"
        PRD §2.8: "Every ledger write recomputes the affected `Buyer`'s
        `order_credit_balance_cents` — the sum of `amount_cents` across all entries
        whose `buyer_id` is that buyer"

        Design: Difficulty/transitive_cascade/trade_in_offer_expiry_compensating_two_hop_chain
        """
        set_clock()
        ctx = walk_order_to_at_delivery_center(buyer_name="Faye Chain")
        order = ctx["order"]
        buyer_id = ctx["buyer"]["id"]

        balance_before = get_success_data(api.get_buyer(buyer_id, ADMIN))
        assert balance_before["order_credit_balance_cents"] == 25000, (
            "the 25000-cent order fee is the buyer's only ledger entry at this point"
        )

        appraisal = get_success_data(api.create_appraisal(
            order["id"],
            create_appraisal_payload(trade_vin="5YJ3E1EA7PF000901", mileage=90000,
                                     gross_offer_cents=1200000,
                                     reconditioning_estimate_cents=60000,
                                     offer_valid_until="2026-09-22T00:00:00Z"),
            TRADEIN))
        get_success_data(api.appraise(order["id"], appraisal["id"], TRADEIN))
        get_success_data(api.offer_appraisal(order["id"], appraisal["id"], TRADEIN))

        after_offer = get_success_data(api.get_buyer(buyer_id, ADMIN))
        assert after_offer["order_credit_balance_cents"] == 25000 + 940000

        get_success_data(api.set_current_utc("2026-09-23T00:00:00Z", ADMIN))

        restored = get_success_data(api.get_buyer(buyer_id, ADMIN))
        assert restored["order_credit_balance_cents"] == 25000, (
            "the reversal returns the balance to exactly its pre-offer value"
        )
