"""Validation-ordering conflicts (each pair is PRD-pinned) and gift-card tender
gating (queue A: priority_pair_validation_conflict, cross_entity_state_dependency;
queue B: validations corners)."""
from test_helpers import (
    ASSOCIATE,
    MANAGER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_session,
    advance_to_dressed,
    create_collection_drop_payload,
    create_customer,
    create_gift_card,
    create_party,
    create_registry,
    create_store,
    create_walk_in_session,
    get_success_data,
    make_customer_headers,
    set_clock,
    setup_workshop_env,
    validate_error,
    validate_success,
)


class TestStateBeatsTemporalOnDeposit:
    def test_cancelled_party_deposit_inside_lead_window_is_invalid_state(self, api):
        """PRD §2.7: "Only after all references resolve does the server evaluate
        whether the target resource is in a state that permits the requested action
        (`ERR_INVALID_STATE`). Temporal rules — lead time, drop windows, finalize
        timing — come next (`ERR_OUTSIDE_TIME_WINDOW`)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_party_deposit
        """
        store = create_store(name="Priority Store", party_room_count=1)
        customer = create_customer(email="c9@example.com", full_name="Casey Nine")
        set_clock("2026-10-01T00:00:00Z")
        party = create_party(
            customer,
            store["id"],
            party_start="2026-10-08T00:00:00Z",
            guest_count=6,
            package_tier="BASIC",
            staffing_mode="SELF_GUIDED",
        )
        validate_success(api.cancel_party(party["id"], make_customer_headers(customer["id"])))
        # Now 48h before party_start: inside the 72h lead window (temporal failure)
        # AND the party is CANCELLED (state failure). State is evaluated first.
        set_clock("2026-10-06T00:00:00Z")
        validate_error(
            api.pay_party_deposit(
                party["id"],
                {"payment_amount_cents": 10000},
                make_customer_headers(customer["id"]),
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )

    def test_pay_deposit_inside_lead_window_on_live_party_is_temporal(self, api):
        """PRD §3.6: "First, lead time: the deposit must be paid at least 72 hours
        before `party_start`, otherwise `ERR_OUTSIDE_TIME_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_party_deposit
        """
        store = create_store(name="Priority Store", party_room_count=1)
        customer = create_customer(email="c9@example.com", full_name="Casey Nine")
        set_clock("2026-10-01T00:00:00Z")
        party = create_party(
            customer,
            store["id"],
            party_start="2026-10-08T00:00:00Z",
            guest_count=6,
            package_tier="BASIC",
            staffing_mode="SELF_GUIDED",
        )
        set_clock("2026-10-06T00:00:00Z")  # 48h lead: temporal fails, state fine
        validate_error(
            api.pay_party_deposit(
                party["id"],
                {"payment_amount_cents": 10000},
                make_customer_headers(customer["id"]),
            ),
            ApiErrorId.ERR_OUTSIDE_TIME_WINDOW,
        )


class TestLinkedGiftCardOrderingAndGating:
    def _setup_dressed_with_registry(self, api, card_balance):
        env = setup_workshop_env(
            store_name="Fiscal Store",
            fiber_qty=5000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Fiscal Fox",
                "sku": "FF-01",
                "base_price_cents": 2000,
                "required_stuffing_grams": 150,
            },
        )
        customer = env["customer"]
        card = create_gift_card(code="GC-500", initial_balance_cents=card_balance)
        registry = create_registry(customer, name="Ten's List")
        session = create_walk_in_session(env)
        advance_to_dressed(session["id"])
        return env, customer, card, registry, session

    def test_not_linked_and_underfunded_surfaces_not_linked(self, api):
        """PRD §3.5: "A linkage failure is rejected with `ERR_GIFT_CARD_NOT_LINKED`,
        while an insufficient or non-`ACTIVE` card is rejected with
        `ERR_GIFT_CARD_INSUFFICIENT`. In the global validation order, linkage (a
        referential-integrity check) is evaluated before balance sufficiency (a
        fiscal check), so a tender that fails both surfaces `ERR_GIFT_CARD_NOT_LINKED`."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_linked_gift_card_payment
        """
        _, customer, card, registry, session = self._setup_dressed_with_registry(api, 500)
        validate_error(
            api.pay_workshop(
                session["id"],
                {
                    "payment_amount_cents": 2000,
                    "pay_tender": "GIFT_CARD_LINKED",
                    "gift_card_id": card["id"],
                    "registry_id": registry["id"],
                },
                make_customer_headers(customer["id"]),
            ),
            ApiErrorId.ERR_GIFT_CARD_NOT_LINKED,
        )

    def test_fully_linked_but_underfunded_surfaces_insufficient(self, api):
        """PRD §3.5: "the card's balance must cover the full payment amount — split
        tender is not supported. A linkage failure is rejected with
        `ERR_GIFT_CARD_NOT_LINKED`, while an insufficient or non-`ACTIVE` card is
        rejected with `ERR_GIFT_CARD_INSUFFICIENT`."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_linked_gift_card_payment
        """
        env, customer, card, registry, session = self._setup_dressed_with_registry(api, 500)
        headers = make_customer_headers(customer["id"])
        current = validate_success(api.get_workshop(session["id"], headers))
        animal_id = current["stuffed_animal_id"]
        validate_success(
            api.link_registry_gift_card(
                registry["id"], {"gift_card_id": card["id"]}, headers
            )
        )
        validate_success(
            api.link_registry_animal(
                registry["id"], {"stuffed_animal_id": animal_id}, headers
            )
        )
        validate_error(
            api.pay_workshop(
                session["id"],
                {
                    "payment_amount_cents": 2000,
                    "pay_tender": "GIFT_CARD_LINKED",
                    "gift_card_id": card["id"],
                    "registry_id": registry["id"],
                },
                headers,
            ),
            ApiErrorId.ERR_GIFT_CARD_INSUFFICIENT,
        )


class TestGiftCardStateGating:
    def test_disabled_card_rejected_despite_sufficient_balance(self, api):
        """PRD §3.5: "With `GIFT_CARD`, the request carries a `gift_card_id`; the
        referenced card must be `ACTIVE` and hold a `balance_cents` of at least the
        payment amount, or the payment is rejected with `ERR_GIFT_CARD_INSUFFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/workshop_payment_requires_gift_card_active_state
        """
        env = setup_workshop_env(
            store_name="Card State Store",
            fiber_qty=5000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Card Crane",
                "sku": "CCR-01",
                "base_price_cents": 3000,
                "required_stuffing_grams": 200,
            },
        )
        customer = env["customer"]
        card = create_gift_card(code="GC-DIS", initial_balance_cents=10000)

        validate_success(api.disable_gift_card(card["id"], MANAGER))
        session = create_walk_in_session(env)
        advance_to_dressed(session["id"])
        validate_error(
            api.pay_workshop(
                session["id"],
                {
                    "payment_amount_cents": 3000,
                    "pay_tender": "GIFT_CARD",
                    "gift_card_id": card["id"],
                },
                make_customer_headers(customer["id"]),
            ),
            ApiErrorId.ERR_GIFT_CARD_INSUFFICIENT,
        )

    def test_active_card_with_sufficient_balance_pays(self, api):
        """PRD §3.5: "A successful payment moves the session to `PAID` and completes
        the minted animal, whose status becomes `COMPLETED`"

        Design: Difficulty/cross_entity_state_dependency/workshop_payment_requires_gift_card_active_state
        """
        env = setup_workshop_env(
            store_name="Card State Store",
            fiber_qty=5000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Card Crane",
                "sku": "CCR-01",
                "base_price_cents": 3000,
                "required_stuffing_grams": 200,
            },
        )
        customer = env["customer"]
        card = create_gift_card(code="GC-OK", initial_balance_cents=10000)
        session = create_walk_in_session(env)
        advance_to_dressed(session["id"])
        paid = validate_success(
            api.pay_workshop(
                session["id"],
                {
                    "payment_amount_cents": 3000,
                    "pay_tender": "GIFT_CARD",
                    "gift_card_id": card["id"],
                },
                make_customer_headers(customer["id"]),
            )
        )
        assert paid["status"] == "PAID"
        card_after = validate_success(
            api.get_gift_card(card["id"], make_customer_headers(customer["id"]))
        )
        assert card_after["balance_cents"] == 7000
        animal = validate_success(
            api.get_animal(paid["stuffed_animal_id"], make_customer_headers(customer["id"]))
        )
        assert animal["status"] == "COMPLETED"


class TestValidationCornerOrdering:
    def test_existence_beats_state_on_missing_party(self, api):
        """PRD §2.7: "Authentication (§2.1) comes first, followed by role
        authorization, then existence of path parameters validated left-to-right,
        then existence of body-referenced resources. Only after all references
        resolve does the server evaluate whether the target resource is in a state
        that permits the requested action (`ERR_INVALID_STATE`)."

        Design: Corner/validations/existence_beats_state_when_party_missing
        """
        customer = create_customer(email="exist@example.com", full_name="Ex Ist")
        validate_error(
            api.cancel_party(NON_EXISTENT_UUID, make_customer_headers(customer["id"])),
            ApiErrorId.ERR_NOT_FOUND,
        )

    def test_temporal_beats_drop_limit_on_licensed_select(self, api):
        """PRD §3.3: "For licensed models it is where the drop window, per-customer
        limit, and total-units checks all fire — in the global validation order, the
        temporal window is evaluated first, then the drop-limit rails"

        Design: Corner/validations/temporal_window_beats_drop_limit_on_licensed_select
        """

        env = setup_workshop_env(
            store_name="Prio Drop Store",
            fiber_qty=10000,
            chip_qty=None,
            station_capacity=4,
            station_types=("STUFF",),
            model_overrides={
                "name": "Prio Panda",
                "sku": "PPA-01",
                "base_price_cents": 5000,
                "is_licensed": True,
                "required_stuffing_grams": 300,
            },
        )
        customer = env["customer"]
        set_clock("2026-10-01T00:00:00Z")
        drop = get_success_data(
            api.create_collection_drop(
                create_collection_drop_payload(
                    env["model"]["id"],
                    name="Expired Drop",
                    drop_start="2026-10-01T00:00:00Z",
                    drop_end="2026-10-02T00:00:00Z",
                    per_customer_limit=1,
                    total_units=10,
                ),
                MANAGER,
            )
        )
        w1 = create_walk_in_session(env, collection_drop_id=drop["id"])

        advance_session(w1["id"])  # customer reaches per_customer_limit 1
        set_clock("2026-10-05T00:00:00Z")  # drop window expired
        w2 = create_walk_in_session(env, collection_drop_id=drop["id"])
        validate_error(
            api.advance_workshop(w2["id"], ASSOCIATE),
            ApiErrorId.ERR_OUTSIDE_TIME_WINDOW,
        )
