"""Compensating invariants: stuffing-gram ledger conservation across consume and
abandon, and gift-card cents conservation across debit and exhaustion."""
from test_helpers import (
    ASSOCIATE,
    ApiErrorId,
    advance_session,
    create_gift_card,
    create_walk_in_session,
    get_success_data,
    make_customer_headers,
    setup_workshop_env,
    validate_error,
    validate_success,
    advance_to_dressed,
)


class TestStuffingGramsConserved:
    def _setup(self, api):
        env = setup_workshop_env(
            store_name="Gram Store",
            fiber_qty=10000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Gram Goat",
                "sku": "GG-01",
                "base_price_cents": 2500,
                "required_stuffing_grams": 320,
            },
        )
        return env

    def test_stuff_advance_consumes_exactly_required_grams(self, api):
        """PRD §3.3: "On success the ledger's `on_hand_qty` decreases by exactly
        `required_stuffing_grams` and the session records the same amount as
        `stuffing_grams_used` (zero until this point)."

        Design: Difficulty/compensating_invariant/stuffing_grams_conserved_across_consume_and_abandon
        """
        env = self._setup(api)
        fiber_id = env["consumables"]["fiber"]["id"]
        session = create_walk_in_session(env)
        advance_session(session["id"])  # SELECT -> SELECTED
        advance_session(session["id"])  # SELECTED -> STUFFED
        fiber = get_success_data(api.get_consumable(fiber_id, ASSOCIATE))
        assert fiber["on_hand_qty"] == 10000 - 320, (
            f"expected 9680 after consuming 320g, got {fiber['on_hand_qty']}"
        )

    def test_abandon_from_stuffed_restores_consumed_fiber(self, api):
        """PRD §3.1: "The governing invariant for the stuffing ledger is that the
        opening quantity plus all restocks, minus fiber consumed by sessions, plus
        fiber restored by abandonments, always equals `on_hand_qty`"

        Design: Difficulty/compensating_invariant/stuffing_grams_conserved_across_consume_and_abandon
        """
        env = self._setup(api)
        fiber_id = env["consumables"]["fiber"]["id"]
        session = create_walk_in_session(env)
        advance_session(session["id"])
        advance_session(session["id"])
        validate_success(api.abandon_workshop(session["id"], ASSOCIATE))
        fiber = get_success_data(api.get_consumable(fiber_id, ASSOCIATE))
        assert fiber["on_hand_qty"] == 10000, (
            f"forward consume + compensating abandon must restore exactly, got "
            f"{fiber['on_hand_qty']}"
        )


class TestGiftCardCentsConserved:
    def _setup(self, api):
        env = setup_workshop_env(
            store_name="Exact Store",
            fiber_qty=5000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Exact Eel",
                "sku": "EE-01",
                "base_price_cents": 4000,
                "required_stuffing_grams": 200,
            },
        )
        card = create_gift_card(code="GC-EXACT", initial_balance_cents=4000)
        session = create_walk_in_session(env)
        advance_to_dressed(session["id"])
        return env, card, session

    def test_exact_balance_debit_zeroes_card_and_exhausts(self, api):
        """PRD §3.5: "For gift-card tenders, the card's `balance_cents` decreases by
        the payment amount; a card whose balance reaches exactly zero transitions
        from `ACTIVE` to `EXHAUSTED`."

        Design: Difficulty/compensating_invariant/gift_card_cents_conserved_across_debit_and_exhaustion
        """
        env, card, session = self._setup(api)
        customer = env["customer"]
        validate_success(
            api.pay_workshop(
                session["id"],
                {
                    "payment_amount_cents": 4000,
                    "pay_tender": "GIFT_CARD",
                    "gift_card_id": card["id"],
                },
                make_customer_headers(customer["id"]),
            )
        )
        card_after = validate_success(
            api.get_gift_card(card["id"], make_customer_headers(customer["id"]))
        )
        assert card_after["balance_cents"] == 0
        assert card_after["status"] == "EXHAUSTED"

    def test_exhausted_card_cannot_fund_second_payment(self, api):
        """PRD §3.9: "Redemption at payment time is the only operation that reduces
        the balance, and a card driven to zero becomes `EXHAUSTED`. A manager may
        also disable a card, moving it to `DISABLED`; neither an exhausted nor a
        disabled card can fund a payment."

        Design: Difficulty/compensating_invariant/gift_card_cents_conserved_across_debit_and_exhaustion
        """
        env, card, session = self._setup(api)
        customer = env["customer"]
        validate_success(
            api.pay_workshop(
                session["id"],
                {
                    "payment_amount_cents": 4000,
                    "pay_tender": "GIFT_CARD",
                    "gift_card_id": card["id"],
                },
                make_customer_headers(customer["id"]),
            )
        )
        # A second DRESSED session at the same total cannot draw on the spent card.
        session2 = create_walk_in_session(env)
        advance_to_dressed(session2["id"])
        validate_error(
            api.pay_workshop(
                session2["id"],
                {
                    "payment_amount_cents": 4000,
                    "pay_tender": "GIFT_CARD",
                    "gift_card_id": card["id"],
                },
                make_customer_headers(customer["id"]),
            ),
            ApiErrorId.ERR_GIFT_CARD_INSUFFICIENT,
        )
        card_after = validate_success(
            api.get_gift_card(card["id"], make_customer_headers(customer["id"]))
        )
        assert card_after["balance_cents"] == 0, (
            "the failed redemption must not drift the balance below zero"
        )
