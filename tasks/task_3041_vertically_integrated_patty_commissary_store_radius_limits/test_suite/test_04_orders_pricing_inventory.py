"""Register operations: modifier pricing, inventory waterfall, and the
place/cancel compensation (PRD section 3.6)."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_order_line,
    create_order_payload,
    create_site_store,
    create_stocked_open_store,
    get_success_data,
    hire_associate,
    make_associate_headers,
    manager_headers_for,
    scd_headers,
    validate_error,
    validate_success,
)


class TestModifierPricing:
    def test_provisional_quote_equals_final_charge(self, api):
        """PRD section 3.6: "The response quote computed before placement
        commits and the value persisted on the order use identical arithmetic
        and must always be equal for the same payload."
        PRD section 3.6: "The base total, `base_total_cents`, is the sum over
        lines of the item's `base_price_cents` multiplied by the line's
        `qty`."
        PRD section 3.6: "The total patties are recorded as
        `patties_reserved`."

        Design: Difficulty/dual_variant_calc/order_modifier_charge_provisional_equals_final
        """
        env = create_stocked_open_store(
            patty_count=100, bun_count=60, produce_units=60,
            menu_item={"sku": "DBL-DBL", "name": "Double-Double",
                       "base_price_cents": 495, "patty_count": 2,
                       "produce_units": 2})
        assoc = manager_headers_for(env)
        order = get_success_data(api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"], [create_order_line(
                env["item"]["id"], qty=2,
                modifier_codes=["EXTRA_PATTY", "ANIMAL_STYLE", "WELL_DONE"])]),
            assoc))
        # units = 2 * (1 + 1) = 4; pre-discount = 4*150 + 65 = 665;
        # WELL_DONE: round_half_up(665 * 0.90) = round_half_up(598.5) = 599.
        assert order["base_total_cents"] == 990
        assert order["modifier_charge_cents"] == 599
        assert order["total_price_cents"] == 1589
        assert order["patties_reserved"] == 8
        # The value persisted on the order must equal the placement quote.
        fetched = get_success_data(api.get_order(order["id"], assoc))
        assert fetched["modifier_charge_cents"] == order["modifier_charge_cents"]
        assert fetched["total_price_cents"] == order["total_price_cents"]

    def test_modifier_charge_discount_applies_per_line(self, api):
        """PRD section 3.6: "the line's pre-discount modifier amount is that
        unit count multiplied by each modifier code's unit price — 150 cents
        for `EXTRA_PATTY`, 65 cents for `ANIMAL_STYLE`, and 0 cents for both
        `PROTEIN_STYLE` and `WELL_DONE` — summed across the line's modifier
        codes; and when `WELL_DONE` appears on the line, the pre-discount
        amount is reduced by ten percent."

        Design: Difficulty/dual_variant_calc/order_modifier_charge_provisional_equals_final
        """
        env = create_stocked_open_store(patty_count=100, bun_count=60,
                                        produce_units=60)
        assoc = manager_headers_for(env)
        order = get_success_data(api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"], [create_order_line(
                env["item"]["id"], qty=3,
                modifier_codes=["EXTRA_PATTY", "WELL_DONE"])]),
            assoc))
        # units = 3 * 2 = 6; pre-discount = 6 * 150 = 900; 900 * 0.9 = 810.
        assert order["modifier_charge_cents"] == 810
        assert order["base_total_cents"] == 1050
        assert order["total_price_cents"] == 1860
        assert order["patties_reserved"] == 6


class TestRoundingOrder:
    def test_modifier_rounding_per_line_then_sum(self, api):
        """PRD section 3.6: "Each line's modifier amount is rounded half-up
        to whole cents individually, and `modifier_charge_cents` is the sum
        of those rounded line amounts — rounding only once at the end is
        forbidden."

        Design: Difficulty/combinatorial_formula/modifier_rounding_per_line_then_sum
        """
        env = create_stocked_open_store(patty_count=100, bun_count=60,
                                        produce_units=60)
        assoc = manager_headers_for(env)
        line = create_order_line(
            env["item"]["id"], qty=1,
            modifier_codes=["EXTRA_PATTY", "ANIMAL_STYLE", "WELL_DONE"])
        order = get_success_data(api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"], [line, line]),
            assoc))
        # Per line: units 2, raw = 0.9 * (2*150 + 65) = 328.5 -> 329.
        # Round-per-line-then-sum gives 329 + 329 = 658; rounding only once
        # at the end would give round_half_up(657.0) = 657, which is
        # forbidden.
        assert order["modifier_charge_cents"] == 658
        assert order["base_total_cents"] == 700
        assert order["total_price_cents"] == 1358
        assert order["patties_reserved"] == 4

    def test_single_fractional_line_rounds_half_up(self, api):
        """PRD section 3.6: "Each line's modifier amount is rounded half-up
        to whole cents individually"
        PRD section 3.6: "The order's `total_price_cents` is
        `base_total_cents` plus `modifier_charge_cents`."

        Design: Difficulty/combinatorial_formula/modifier_rounding_per_line_then_sum
        """
        env = create_stocked_open_store(patty_count=100, bun_count=60,
                                        produce_units=60)
        assoc = manager_headers_for(env)
        order = get_success_data(api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"], [create_order_line(
                env["item"]["id"], qty=1,
                modifier_codes=["EXTRA_PATTY", "ANIMAL_STYLE", "WELL_DONE"])]),
            assoc))
        assert order["modifier_charge_cents"] == 329
        assert order["total_price_cents"] == 350 + 329


class TestInventoryWaterfall:
    def test_order_exceeding_store_inventory_rejected(self, api):
        """PRD section 3.6: "The check is an all-or-nothing waterfall: all
        three commodities must be satisfiable, and if any one is short,
        nothing is debited and the order is rejected with
        `ERR_INSUFFICIENT_INVENTORY` (HTTP 422) — there are no partial
        fills."

        Design: Corner/validations/order_exceeding_store_inventory_rejected
        """
        env = create_stocked_open_store(patty_count=10, bun_count=10,
                                        produce_units=10)
        assoc = manager_headers_for(env)
        resp = api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"],
                                 [create_order_line(env["item"]["id"], qty=11)]),
            assoc)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)
        assert resp.status_code == 422
        # Nothing was debited: an order for exactly the 10 delivered units
        # still succeeds.
        ok = validate_success(api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"],
                                 [create_order_line(env["item"]["id"], qty=10)]),
            assoc), expected_status=201)
        assert ok["status"] == "PLACED"

    def test_short_buns_also_rejects_nothing_debited(self, api):
        """PRD section 3.6: "The reservation footprint is computed per line
        and summed: patties as `qty` times the item's `patty_count` plus the
        count of `EXTRA_PATTY` codes on the line; buns as exactly one per
        unit sold, so `qty` per line regardless of modifiers; produce as
        `qty` times the item's `produce_units`."
        PRD section 3.6: "if any one is short, nothing is debited and the
        order is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 422)"

        Design: Corner/validations/order_exceeding_store_inventory_rejected
        """
        # Plenty of patties and produce, only one bun: a two-unit order must
        # fail on the bun leg of the waterfall.
        env = create_stocked_open_store(patty_count=50, bun_count=1,
                                        produce_units=50)
        assoc = manager_headers_for(env)
        resp = api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"],
                                 [create_order_line(env["item"]["id"], qty=2)]),
            assoc)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)
        assert resp.status_code == 422


class TestOrderPlaceCancelInvariant:
    def test_order_place_cancel_restores_inventory(self, api):
        """PRD section 3.6: "Cancelling, likewise restricted to an associate
        of the order's store, performs the compensating action: the store's
        on-hand inventory is credited back by the reserved patties and the
        corresponding bun and produce quantities computed from the lines,
        returning the ledger to its pre-placement value, and `queue_position`
        is cleared."

        Design: Difficulty/compensating_invariant/order_place_cancel_restores_inventory
        """
        env = create_stocked_open_store(patty_count=100, bun_count=60,
                                        produce_units=60)
        assoc = manager_headers_for(env)
        order = get_success_data(api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"], [create_order_line(
                env["item"]["id"], qty=10, modifier_codes=["EXTRA_PATTY"])]),
            assoc))
        assert order["patties_reserved"] == 20
        cancelled = validate_success(api.cancel_order(order["id"], assoc))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["queue_position"] is None
        # The ledger is restored: the full pre-placement footprint fits again.
        full = validate_success(api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"],
                                 [create_order_line(env["item"]["id"], qty=60)]),
            assoc), expected_status=201)
        assert full["patties_reserved"] == 60

    def test_serve_then_cancel_rejected_no_second_compensation(self, api):
        """PRD section 3.6: "An order begins `PLACED` and ends `SERVED` or
        `CANCELLED`; actions on an order no longer `PLACED` are rejected with
        `ERR_ORDER_INVALID_STATE`."

        Design: Difficulty/compensating_invariant/order_place_cancel_restores_inventory
        """
        env = create_stocked_open_store(patty_count=100, bun_count=60,
                                        produce_units=60)
        assoc = manager_headers_for(env)
        order = get_success_data(api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"],
                                 [create_order_line(env["item"]["id"], qty=1)]),
            assoc))
        get_success_data(api.serve_order(order["id"], assoc))
        resp = api.cancel_order(order["id"], assoc)
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
        assert resp.status_code == 409


class TestOrderOwnership:
    def test_serve_terminal_order_returns_invalid_state(self, api):
        """PRD section 3.6: "An order begins `PLACED` and ends `SERVED` or
        `CANCELLED`; actions on an order no longer `PLACED` are rejected with
        `ERR_ORDER_INVALID_STATE`."
        PRD section 3.6: "Serving is performed by an `Associate` whose
        `home_store_id` matches the order's store and whose `active` flag is
        true — anyone else is rejected with `ERR_FORBIDDEN_ROLE` — and clears
        `queue_position` to null."

        Design: Corner/state_machines/serve_terminal_order_returns_invalid_state
        """
        env = create_stocked_open_store(patty_count=100, bun_count=60,
                                        produce_units=60)
        assoc = manager_headers_for(env)
        order = get_success_data(api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"],
                                 [create_order_line(env["item"]["id"], qty=1)]),
            assoc))
        served = validate_success(api.serve_order(order["id"], assoc))
        assert served["status"] == "SERVED"
        assert served["queue_position"] is None
        resp = api.serve_order(order["id"], assoc)
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
        assert resp.status_code == 409
        stored = get_success_data(api.get_order(order["id"], assoc))
        assert stored["status"] == "SERVED"

    def test_associate_cannot_touch_other_store_orders(self, api):
        """PRD section 3.6: "Serving is performed by an `Associate` whose
        `home_store_id` matches the order's store and whose `active` flag is
        true — anyone else is rejected with `ERR_FORBIDDEN_ROLE`"
        PRD section 2.1: "Where an endpoint requires the entity-backed
        identity to match a resource's ownership field — an associate serving
        an order at their own store, a store manager acting on their own
        store, a candidate withdrawing their own application — a mismatch is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/associate_cannot_touch_other_store_orders
        """
        env = create_stocked_open_store(patty_count=100, bun_count=60,
                                        produce_units=60)
        store_a = env["store"]
        assoc_a = manager_headers_for(env)
        # A second store on the same commissary, with its own associate.
        store_b = create_site_store(env["commissary"], name="Store B",
                                    lat=34.02, lng=-118.02)
        crew_b = hire_associate(store_b["id"])
        order = get_success_data(api.create_order(
            store_a["id"],
            create_order_payload(env["manager"]["id"],
                                 [create_order_line(env["item"]["id"], qty=1)]),
            assoc_a))
        resp = api.serve_order(order["id"], make_associate_headers(crew_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403
        stored = get_success_data(api.get_order(order["id"], assoc_a))
        assert stored["status"] == "PLACED"


class TestOrderRequestShape:
    def test_order_unknown_store_returns_not_found(self, api):
        """PRD section 2.5: "4. **Path existence** — every identifier in the
        URL path exists, validated left to right, else `ERR_NOT_FOUND`."
        PRD section 2.5: "6. **Request shape** — required fields present,
        types valid, enum values within their declared domains, modifier
        codes within the unlisted variation set, arrays well-formed, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/order_unknown_modifier_code_returns_invalid_request
        """
        resp = api.create_order(
            NON_EXISTENT_UUID,
            create_order_payload(
                "00000000-0000-0000-0000-000000000001",
                [create_order_line(
                    "00000000-0000-0000-0000-000000000002", qty=1,
                    modifier_codes=["ANIMAL_STYLE", "SUPER_SIZE_ME"])]),
            make_associate_headers("00000000-0000-0000-0000-000000000001"))
        # Path existence (tier 4) precedes request shape (tier 6), so the
        # unknown store id in the path fires ERR_NOT_FOUND first.
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404

    def test_unknown_modifier_code_on_known_store_returns_invalid_request(self, api):
        """PRD section 3.6: "Unlisted variations are handled entirely through
        register modifiers drawn from a fixed set of four codes —
        `EXTRA_PATTY`, `ANIMAL_STYLE`, `PROTEIN_STYLE`, and `WELL_DONE`; any
        other code in an order line is a shape error."
        PRD section 2.5: "6. **Request shape** — required fields present,
        types valid, enum values within their declared domains, modifier codes
        within the unlisted variation set, arrays well-formed, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/order_unknown_modifier_code_returns_invalid_request
        """
        env = create_stocked_open_store(patty_count=100, bun_count=60,
                                        produce_units=60)
        assoc = manager_headers_for(env)
        resp = api.create_order(
            env["store"]["id"],
            create_order_payload(env["manager"]["id"], [create_order_line(
                env["item"]["id"], qty=1, modifier_codes=["SUPER_SIZE_ME"])]),
            assoc)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400
