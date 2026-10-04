"""Consignment settlement: aggregate rounding vs per-shipment, pinned evaluation
order, and window filtering (queue A: dual_variant_calc, combinatorial_formula,
transitive_cascade; queue B: calculations consignment corner)."""
from test_helpers import (
    ASSOCIATE,
    advance_to_dressed,
    assemble_order,
    create_build_ship_order,
    hand_over_order,
    pay_session_cash,
    run_settlement,
    set_clock,
    setup_handed_over_orders,
    setup_workshop_env,
    validate_success,
)


class TestAggregateCommissionVsPerShipment:
    def test_ten_orders_aggregate_rounding(self, api):
        """PRD §3.8: "then `commission_cents`, the gross merchandise value multiplied
        by 18 percent and rounded half up to the nearest cent; then `store_bonus_cents`,
        the commission divided by the number of eligible orders — with a zero-eligible
        count treated as one for the division — rounded half up to the nearest cent."

        Design: Difficulty/dual_variant_calc/build_ship_consignment_per_shipment_vs_store_aggregate
        """
        env = setup_workshop_env(
            store_name="Mall Kiosk",
            fiber_qty=100000,
            chip_qty=10,
            station_capacity=4,
            model_overrides={
                "name": "Classic Bear",
                "sku": "CB-01",
                "base_price_cents": 4999,
                "required_stuffing_grams": 320,
            },
        )
        set_clock("2026-10-20T00:00:00Z")
        setup_handed_over_orders(env, 10)
        settlement = run_settlement(
            env["store"]["id"], "2026-10-01T00:00:00Z", "2026-11-02T00:00:00Z"
        )
        assert settlement["eligible_order_count"] == 10
        assert settlement["gmv_cents"] == 49990
        # Aggregate: round_half_up(49990*18/100) = round(8998.2) = 8998;
        # per-shipment rounding would give 10 * 900 = 9000.
        assert settlement["commission_cents"] == 8998, (
            f"aggregate rounding expected 8998, got {settlement['commission_cents']}"
        )
        # round_half_up(8998/10) = round(899.8) = 900
        assert settlement["store_bonus_cents"] == 900

    def test_four_orders_aggregate_differs_from_per_shipment(self, api):
        """PRD §3.8: "first `gmv_cents`, the sum of the eligible orders' workshop
        session `total_price_cents` (session totals are already per-line rounded, so
        this summation introduces no new rounding); then `commission_cents`, the gross
        merchandise value multiplied by 18 percent and rounded half up to the nearest
        cent"

        Design: Difficulty/dual_variant_calc/build_ship_consignment_per_shipment_vs_store_aggregate
        """
        env = setup_workshop_env(
            store_name="Aggregate Kiosk",
            fiber_qty=100000,
            chip_qty=10,
            station_capacity=4,
            model_overrides={
                "name": "Aggregate Ape",
                "sku": "AG-01",
                "base_price_cents": 4999,
                "required_stuffing_grams": 320,
            },
        )
        set_clock("2026-10-20T00:00:00Z")
        setup_handed_over_orders(env, 4)
        settlement = run_settlement(
            env["store"]["id"], "2026-10-01T00:00:00Z", "2026-11-02T00:00:00Z"
        )
        assert settlement["eligible_order_count"] == 4
        assert settlement["gmv_cents"] == 19996
        # Aggregate: round(19996*0.18)=round(3599.28)=3599; per-shipment would be
        # 4 * round(4999*0.18) = 4 * 900 = 3600.
        assert settlement["commission_cents"] == 3599, (
            f"aggregate rounding expected 3599, got {settlement['commission_cents']}"
        )
        # round_half_up(3599/4) = round(899.75) = 900
        assert settlement["store_bonus_cents"] == 900


class TestConsignmentEvaluationOrder:
    def test_three_orders_gmv_commission_bonus_chain(self, api):
        """PRD §3.8: "The settlement evaluates three figures in a pinned order, each
        depending on the previous: first `gmv_cents`, the sum of the eligible orders'
        workshop session `total_price_cents` ... then `commission_cents` ... then
        `store_bonus_cents`, the commission divided by the number of eligible orders —
        with a zero-eligible count treated as one for the division — rounded half up
        to the nearest cent."

        Design: Difficulty/combinatorial_formula/consignment_circular_evaluation_order_gmv_commission_bonus
        """
        env = setup_workshop_env(
            store_name="Consign Corner",
            fiber_qty=20000,
            chip_qty=None,
            station_capacity=3,
            model_overrides={
                "name": "Deluxe Dino",
                "sku": "DD-01",
                "base_price_cents": 5999,
                "required_stuffing_grams": 300,
            },
        )
        set_clock("2026-10-15T00:00:00Z")
        setup_handed_over_orders(env, 3, recipient_prefix="X")
        settlement = run_settlement(
            env["store"]["id"], "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"
        )
        assert settlement["eligible_order_count"] == 3
        assert settlement["gmv_cents"] == 17997
        # round_half_up(17997*18/100) = round(3239.46) = 3239
        assert settlement["commission_cents"] == 3239, (
            f"expected commission 3239, got {settlement['commission_cents']}"
        )
        # round_half_up(3239/3) = round(1079.67) = 1080
        assert settlement["store_bonus_cents"] == 1080, (
            f"expected bonus 1080, got {settlement['store_bonus_cents']}"
        )

    def test_zero_eligible_orders_yields_zero_settlement(self, api):
        """PRD §3.8: "then `store_bonus_cents`, the commission divided by the number
        of eligible orders — with a zero-eligible count treated as one for the
        division — rounded half up to the nearest cent."

        Design: Difficulty/combinatorial_formula/consignment_circular_evaluation_order_gmv_commission_bonus
        """
        env = setup_workshop_env(
            store_name="Empty Corner",
            fiber_qty=20000,
            chip_qty=None,
            station_capacity=3,
            model_overrides={"base_price_cents": 5999, "required_stuffing_grams": 300},
        )
        set_clock("2026-10-15T00:00:00Z")
        settlement = run_settlement(
            env["store"]["id"], "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"
        )
        assert settlement["eligible_order_count"] == 0
        assert settlement["gmv_cents"] == 0
        assert settlement["commission_cents"] == 0
        assert settlement["store_bonus_cents"] == 0


class TestPaymentCascadeIntoHandoffWindow:
    def test_payment_ready_then_handoff_timestamps_window_inclusion(self, api):
        """PRD §3.8: "When the session is eventually paid, the order auto-transitions
        from `IN_ASSEMBLY` to `READY_FOR_PICKUP`. Handoff to the carrier is performed
        by an associate supplying a `carrier_code` and a `tracking_number`, both
        required; the order moves to `HANDED_TO_CARRIER` and stamps `handed_over_at`
        from the logical clock."

        Design: Difficulty/transitive_cascade/build_ship_payment_cascades_order_ready_then_handoff_window
        """
        env = setup_workshop_env(
            store_name="Ship Store",
            fiber_qty=10000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Ship Seal",
                "sku": "SS-01",
                "base_price_cents": 4000,
                "required_stuffing_grams": 280,
            },
        )
        customer = env["customer"]
        set_clock("2026-10-31T20:00:00Z")
        order = create_build_ship_order(
            env["store"]["id"], customer, env["model"]["id"], recipient_name="Receiver"
        )
        _, session_id = assemble_order(order["id"])
        advance_to_dressed(session_id)
        pay_session_cash(session_id, customer["id"])
        handed = validate_success(
            api.handoff_build_ship_order(
                order["id"], {"carrier_code": "UPS", "tracking_number": "1Z888"}, ASSOCIATE
            )
        )
        assert handed["status"] == "HANDED_TO_CARRIER"
        settle_in = run_settlement(
            env["store"]["id"], "2026-10-01T00:00:00Z", "2026-10-31T23:00:00Z"
        )
        assert settle_in["eligible_order_count"] == 1, (
            "handoff at 2026-10-31T20:00:00Z must fall inside the window ending 23:00"
        )

    def test_settlement_window_keys_on_handed_over_at_not_payment_time(self, api):
        """PRD §3.8: "Eligible orders are the store's build-and-ship orders in
        `HANDED_TO_CARRIER` status whose `handed_over_at` falls inside the window —
        start inclusive, end exclusive."

        Design: Difficulty/transitive_cascade/build_ship_payment_cascades_order_ready_then_handoff_window
        """
        env = setup_workshop_env(
            store_name="Ship Store",
            fiber_qty=10000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Ship Seal",
                "sku": "SS-01",
                "base_price_cents": 4000,
                "required_stuffing_grams": 280,
            },
        )
        customer = env["customer"]
        # Session is paid at 20:00 but the handoff (and its timestamp) happens at 22:00.
        set_clock("2026-10-31T20:00:00Z")
        order = create_build_ship_order(
            env["store"]["id"], customer, env["model"]["id"], recipient_name="Receiver"
        )
        _, session_id = assemble_order(order["id"])
        advance_to_dressed(session_id)
        pay_session_cash(session_id, customer["id"])
        set_clock("2026-10-31T22:00:00Z")
        hand_over_order(order["id"], customer["id"])
        # Window ending after payment (20:30) but before handoff (22:00): excluded.
        settle_out = run_settlement(
            env["store"]["id"], "2026-10-01T00:00:00Z", "2026-10-31T20:30:00Z"
        )
        assert settle_out["eligible_order_count"] == 0, (
            "the window filter must read handed_over_at, not the payment time"
        )
        settle_in = run_settlement(
            env["store"]["id"], "2026-10-01T00:00:00Z", "2026-10-31T23:00:00Z"
        )
        assert settle_in["eligible_order_count"] == 1


class TestConsignmentWindowFiltering:
    def test_window_excludes_unhanded_orders(self, api):
        """PRD §3.8: "Eligible orders are the store's build-and-ship orders in
        `HANDED_TO_CARRIER` status whose `handed_over_at` falls inside the window —
        start inclusive, end exclusive."

        Design: Corner/calculations/consignment_window_excludes_unhanded_and_out_of_window_orders
        """
        env = setup_workshop_env(
            store_name="Filter Store",
            fiber_qty=10000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Filter Finch",
                "sku": "FFI-01",
                "base_price_cents": 3000,
                "required_stuffing_grams": 200,
            },
        )
        customer = env["customer"]
        set_clock("2026-10-15T00:00:00Z")
        done = create_build_ship_order(
            env["store"]["id"], customer, env["model"]["id"], recipient_name="Done"
        )
        hand_over_order(done["id"], customer["id"])
        # A second order that is only PLACED contributes nothing.
        create_build_ship_order(
            env["store"]["id"], customer, env["model"]["id"], recipient_name="Pending"
        )
        settlement = run_settlement(
            env["store"]["id"], "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"
        )
        assert settlement["eligible_order_count"] == 1
        assert settlement["gmv_cents"] == 3000
