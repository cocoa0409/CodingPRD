"""The commercial desk: line pricing, the freight and credit waterfall, holds and resumes."""

import pytest

from test_helpers import (
    CLOCK_BASE,
    ApiErrorId,
    TEST_USERS,
    add_order_line,
    apply_credit,
    assert_order_money_chain,
    confirm_order,
    create_active_config,
    create_active_spec,
    create_config,
    create_customer,
    find_order_line,
    open_order,
    read_customer,
    read_order,
    set_clock,
    setup_commercial_world,
    setup_confirmed_order,
    setup_draft_order_with_lines,
    setup_order_with_credit_balance,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]


class TestLinePricing:
    def test_line_total_is_not_the_unit_price_multiplied_by_the_quantity(self, api):
        """PRD 3.8: "The **base rate**, in cents per litre, is fixed by the configuration's
        `package_type`: 320 for `BULK`, 380 for `IBC_1000L`, 425 for `DRUM_205L`, 505 for
        `PAIL_20L` and 640 for `CASE_12X1L` — the smaller the pack, the more the filling costs."
        PRD 3.8: "The **tier discount** is fixed by the account's `contract_tier`: 12.0 percent
        for `TIER_A`, 7.5 percent for `TIER_B` and no discount at all for `TIER_C`."
        PRD 3.8: "The **private-label uplift** is 4.5 percent where the configuration's
        `private_label` flag is true, and zero where it is false."
        PRD 3.8: "Multiply the base rate by one minus the tier discount divided by one hundred,
        then by one plus the uplift divided by one hundred; that product is the line's effective
        rate per litre and it is **never rounded**."
        PRD 3.8: "The two money figures are deliberately not factors of one another:
        `line_total_cents` is never `quantity_units` multiplied by `unit_price_cents`, and the
        two will legitimately disagree on most lines."

        Design: Difficulty/combinatorial_formula/order_pricing_rounds_per_line_then_sums
        """
        world = setup_commercial_world()
        order = open_order(world["customer"]["id"])

        line = validate_success(
            api.create_order_line(
                order["id"],
                {"package_configuration_id": world["cfg_pail"]["id"], "quantity_units": 37},
                SALES,
            ),
            201,
        )
        assert line["status"] == "OPEN"
        assert line["volume_l"] == pytest.approx(740.00, abs=0.005)
        assert line["line_total_cents"] == 361228
        assert line["unit_price_cents"] == 9763
        assert line["quantity_units"] * line["unit_price_cents"] == 361231
        assert line["line_total_cents"] != line["quantity_units"] * line["unit_price_cents"]

    def test_subtotal_rounds_each_line_before_summing(self, api):
        """PRD 3.8: "The line's `line_total_cents` is `volume_l` multiplied by the effective
        rate, rounded half up to whole cents."
        PRD 3.8: "The rounding order at order level is pinned in the same way: round each line
        first, then add."
        PRD 3.8: "The order's `subtotal_cents` is the sum of `line_total_cents` over the lines
        whose status is `OPEN`, taken in ascending `created_at` order, and is never obtained by
        summing unrounded line values."
        PRD 3.8: "The order's `total_volume_l` is the sum of `volume_l` over those same `OPEN`
        lines, rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/order_pricing_rounds_per_line_then_sums
        """
        world = setup_draft_order_with_lines(lines=[("cfg_pail", 37), ("cfg_drum", 6)])
        first, second = world["lines"]

        assert first["line_total_cents"] == 361228
        assert second["volume_l"] == pytest.approx(1230.00, abs=0.005)
        assert second["line_total_cents"] == 483544
        assert second["unit_price_cents"] == 80591

        order = read_order(world["order"]["id"])
        assert order["subtotal_cents"] == 844772
        assert order["subtotal_cents"] != 844777
        assert order["total_volume_l"] == pytest.approx(1970.00, abs=0.005)

    def test_adding_a_second_line_reprices_the_draft_order_immediately(self, api):
        """PRD 3.8: "The order's `subtotal_cents` is the sum of `line_total_cents` over the lines
        whose status is `OPEN`, taken in ascending `created_at` order, and is never obtained by
        summing unrounded line values."
        PRD 3.8: "The order's `total_volume_l` is the sum of `volume_l` over those same `OPEN`
        lines, rounded half up to two decimal places."
        PRD 3.8: "The order opens in `DRAFT` with `subtotal_cents`, `total_volume_l`,
        `freight_surcharge_cents`, `pre_credit_total_cents`, `takeback_credit_applied_cents` and
        `total_cents` all at 0, and `hold_reason` null."
        PRD 3.8: "Confirmation performs steps one to three and step five; drawing credit
        performs steps four and five; voiding resets step four to zero and re-runs step five."

        Design: Corner/cross_cutting_complexity_layers/order_subtotal_recomputed_when_a_second_line_is_added
        """
        world = setup_draft_order_with_lines(lines=[("cfg_pail", 37)])
        before = read_order(world["order"]["id"])
        assert before["subtotal_cents"] == 361228
        assert before["total_volume_l"] == pytest.approx(740.00, abs=0.005)

        second = add_order_line(world["order"]["id"], world["cfg_drum"]["id"], 6)
        assert second["line_total_cents"] == 483544

        after = read_order(world["order"]["id"])
        assert after["status"] == "DRAFT"
        assert after["subtotal_cents"] == 844772
        assert after["total_volume_l"] == pytest.approx(1970.00, abs=0.005)
        assert after["freight_surcharge_cents"] == 0
        assert after["total_cents"] == 0

    def test_line_against_a_draft_configuration_is_refused(self, api):
        """PRD 3.8: "Lines are added to a draft order, each naming the
        `package_configuration_id` being bought and a `quantity_units` count greater than zero —
        packaged units for a packed format, litre-units for bulk."
        PRD 3.8: "The referenced configuration must be `ACTIVE`, or the line is refused with
        `ERR_CONFIG_NOT_ACTIVE`."
        PRD 3.8: "The order opens in `DRAFT` with `subtotal_cents`, `total_volume_l`,
        `freight_surcharge_cents`, `pre_credit_total_cents`, `takeback_credit_applied_cents` and
        `total_cents` all at 0, and `hold_reason` null."

        Design: Corner/errors/order_line_on_draft_configuration_returns_config_not_active
        """
        set_clock(CLOCK_BASE)
        customer = create_customer(
            name="Golf Retail", customer_type="DISTRIBUTOR", contract_tier="TIER_C"
        )
        spec = create_active_spec()
        draft_config = create_config(spec["id"])
        order = open_order(customer["id"])

        response = api.create_order_line(
            order["id"],
            {"package_configuration_id": draft_config["id"], "quantity_units": 5},
            SALES,
        )
        validate_error(response, ApiErrorId.ERR_CONFIG_NOT_ACTIVE.value, 409)

        rows, meta = validate_paginated(api.list_order_lines(order["id"], SALES))
        assert meta["total_count"] == 0 and rows == []
        assert read_order(order["id"])["subtotal_cents"] == 0

    def test_order_lines_are_readable_from_both_directions(self, api):
        """PRD 2.5: "Reads that traverse a relationship backwards are available throughout: the
        draws taken from a component lot, the components of a recipe, the draws, laboratory
        results and retain jars of a batch, the order lines quoting a package configuration,
        and the recipes, claims, configurations and change requests belonging to a
        specification are all reachable, either as a dedicated sub-collection or through a
        filter on the parent's identifier."
        PRD 3.8: "Each line records the `order_id` that owns it and opens with status `OPEN`."
        PRD 3.8: "The order's `subtotal_cents` is the sum of `line_total_cents` over the lines
        whose status is `OPEN`, taken in ascending `created_at` order, and is never obtained by
        summing unrounded line values."

        Design: Corner/endpoints/order_lines_sub_resource_lists_lines_of_one_order
        """
        world = setup_draft_order_with_lines(lines=[("cfg_pail", 37), ("cfg_drum", 6)])
        first, second = world["lines"]

        other_order = open_order(world["customer"]["id"])
        third = add_order_line(other_order["id"], world["cfg_pail"]["id"], 1)

        own_lines, _ = validate_paginated(
            api.list_order_lines(world["order"]["id"], SALES)
        )
        assert sorted(row["id"] for row in own_lines) == sorted([first["id"], second["id"]])

        by_config, _ = validate_paginated(
            api.list_configuration_order_lines(world["cfg_pail"]["id"], SALES)
        )
        assert sorted(row["id"] for row in by_config) == sorted([first["id"], third["id"]])

        assert read_order(world["order"]["id"])["subtotal_cents"] == 844772
        assert read_order(other_order["id"])["subtotal_cents"] == 9763


class TestFreightAndCreditWaterfall:
    def test_packaged_freight_tier_is_keyed_on_the_subtotal_before_any_credit(self, api):
        """PRD 3.8: "For a `PACKAGED` order, freight is a three-step tier keyed on
        `subtotal_cents` **before** freight and **before** any credit: a subtotal of 1,000,000
        cents or more carries no freight at all, a subtotal of at least 500,000 cents but below
        1,000,000 carries 22,500 cents, and anything below 500,000 cents carries 39,500 cents."
        PRD 3.8: "**Step three** sets `pre_credit_total_cents` to `subtotal_cents` plus
        `freight_surcharge_cents`."
        PRD 3.8: "Confirmation performs steps one to three and step five; drawing credit
        performs steps four and five; voiding resets step four to zero and re-runs step five."

        Design: Difficulty/combinatorial_formula/order_credit_cap_pinned_to_pre_credit_total
        """
        world = setup_order_with_credit_balance()
        order = read_order(world["order"]["id"])

        assert order["status"] == "CONFIRMED"
        assert order["subtotal_cents"] == 844772
        assert order["freight_surcharge_cents"] == 22500
        assert order["pre_credit_total_cents"] == 867272
        assert order["takeback_credit_applied_cents"] == 0
        assert_order_money_chain(order)

    def test_credit_cap_is_a_floored_share_of_the_pre_credit_total(self, api):
        """PRD 3.8: "**Step four** settles `takeback_credit_applied_cents`, which is zero
        outright when the order is not take-back linked; where it is linked, compute the cap as
        15 percent of `pre_credit_total_cents` with the fractional part discarded — a floor,
        never a round — and apply the smaller of the account's `takeback_credit_balance_cents`
        and that cap."
        PRD 3.8: "The cap is always a share of `pre_credit_total_cents` and never of
        `total_cents`."
        PRD 3.8: "**Step five** sets `total_cents` to `pre_credit_total_cents` minus
        `takeback_credit_applied_cents`."
        PRD 3.9: "The `ASSAY_ADJUSTED` variant pays a higher headline 25 cents per litre but
        discounts for contamination: compute a net factor of one minus `water_pct` divided by
        one hundred minus `sediment_pct` divided by one hundred, multiply `collected_volume_l`
        by 25 and by that net factor, round half up to whole cents, and then take the greater of
        the result and zero so the credit is never negative."

        Design: Difficulty/combinatorial_formula/order_credit_cap_pinned_to_pre_credit_total
        """
        world = setup_order_with_credit_balance()
        assert world["collection"]["credit_cents"] == 1357500
        assert world["collection"]["credit_variant"] == "ASSAY_ADJUSTED"

        drawn = apply_credit(world)
        assert drawn["takeback_credit_applied_cents"] == 130090
        assert drawn["takeback_credit_applied_cents"] != 126715
        assert drawn["total_cents"] == 737182
        assert_order_money_chain(drawn)

        assert read_customer(world["customer"]["id"])["takeback_credit_balance_cents"] == 1227410

    def test_bulk_freight_is_waived_at_exactly_four_thousand_litres(self, api):
        """PRD 3.8: "For a `BULK_DELIVERY` order, freight is waived entirely once
        `total_volume_l` reaches 4,000 litres — a volume of exactly 4,000 qualifies — and below
        that it is a minimum freight charge of 48,000 cents multiplied by one minus the ratio of
        `total_volume_l` to 4,000, rounded half up to whole cents; a tanker that is half full
        therefore pays half the minimum."
        PRD 3.8: "The line's `volume_l` is `quantity_units` multiplied by the configuration's
        `fill_volume_l`, rounded half up to two decimal places."
        PRD 3.8: "The line's `unit_price_cents` is the configuration's `fill_volume_l`
        multiplied by the same effective rate, rounded half up to whole cents — a display figure
        for one unit."

        Design: Corner/calculations/bulk_freight_is_free_at_exactly_the_four_thousand_litre_threshold
        """
        set_clock(CLOCK_BASE)
        customer = create_customer(
            name="Alpha Fleet",
            customer_type="FLEET",
            contract_tier="TIER_A",
            takeback_agreement_status="ACTIVE",
        )
        spec = create_active_spec()
        bulk_config = create_active_config(
            spec["id"],
            package_type="BULK",
            label_brand="House Bulk",
            fill_volume_l=1.0,
            private_label=False,
            claim_codes=[],
        )

        small = open_order(customer["id"], delivery_mode="BULK_DELIVERY")
        small_line = add_order_line(small["id"], bulk_config["id"], 2500)
        big = open_order(customer["id"], delivery_mode="BULK_DELIVERY")
        big_line = add_order_line(big["id"], bulk_config["id"], 4000)

        confirmed_small = confirm_order(small["id"])
        confirmed_big = confirm_order(big["id"])

        assert small_line["line_total_cents"] == 704000
        assert small_line["unit_price_cents"] == 282
        assert confirmed_small["total_volume_l"] == pytest.approx(2500.00, abs=0.005)
        assert confirmed_small["freight_surcharge_cents"] == 18000
        assert confirmed_small["pre_credit_total_cents"] == 722000
        assert confirmed_small["total_cents"] == 722000

        assert big_line["line_total_cents"] == 1126400
        assert confirmed_big["total_volume_l"] == pytest.approx(4000.00, abs=0.005)
        assert confirmed_big["freight_surcharge_cents"] == 0
        assert confirmed_big["pre_credit_total_cents"] == 1126400
        assert confirmed_big["total_cents"] == 1126400

    def test_credit_limit_is_tested_against_the_pre_credit_total(self, api):
        """PRD 3.8: "The credit-limit gate closes the confirmation: `pre_credit_total_cents`
        must not exceed the account's `credit_limit_cents`, or the confirmation is refused with
        `ERR_CREDIT_LIMIT_EXCEEDED`."
        PRD 3.8: "Note carefully that the ceiling is tested against the pre-credit figure, so an
        account cannot buy its way under its own limit by drawing take-back credit."
        PRD 3.9: "a `credit_limit_cents` of at least zero, capping the `pre_credit_total_cents`
        the account may carry on any single confirmed order."

        Design: Corner/validations/credit_limit_exceeded_blocks_order_confirm
        """
        world = setup_draft_order_with_lines(
            lines=[("cfg_pail", 37)],
            customer_overrides={"name": "Echo Workshops", "credit_limit_cents": 300000},
        )

        # subtotal 361228 plus 39500 freight gives 400728 against a 300000 ceiling.
        response = api.confirm_order(world["order"]["id"], SALES)
        validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, 422)

        assert read_order(world["order"]["id"])["status"] == "DRAFT"
        assert world["lines"][0]["line_total_cents"] == 361228


class TestTakebackAgreementGateAndHolds:
    def test_takeback_linked_confirmation_needs_an_agreement_in_force(self, api):
        """PRD 3.8: "It moves the order `DRAFT → CONFIRMED` and requires at least one line in
        `OPEN` status, every `OPEN` line referencing a configuration that is still `ACTIVE` —
        otherwise `ERR_CONFIG_NOT_ACTIVE` — and, where the order is take-back linked, the
        account's `takeback_agreement_status` being `ACTIVE`, otherwise
        `ERR_TAKEBACK_AGREEMENT_INACTIVE`."
        PRD 3.9: "An optional `takeback_agreement_status` may be supplied and defaults to
        `NONE`; the other permitted values are `ACTIVE` and `SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_depends_on_customer_takeback_agreement
        """
        world = setup_draft_order_with_lines(
            lines=[("cfg_pail", 37)],
            order_overrides={"takeback_linked": True},
            customer_overrides={
                "name": "Charlie Industrial",
                "customer_type": "INDUSTRIAL",
                "takeback_agreement_status": "NONE",
            },
        )

        response = api.confirm_order(world["order"]["id"], SALES)
        validate_error(response, ApiErrorId.ERR_TAKEBACK_AGREEMENT_INACTIVE.value, 409)
        assert read_order(world["order"]["id"])["status"] == "DRAFT"

    def test_confirmation_succeeds_once_the_agreement_is_set_active(self, api):
        """PRD 3.9: "Either a `PlatformAdmin` or a `SalesRep` may later set the agreement in
        force by supplying an `agreement_status`."
        PRD 3.8: "It moves the order `DRAFT → CONFIRMED` and requires at least one line in
        `OPEN` status, every `OPEN` line referencing a configuration that is still `ACTIVE` —
        otherwise `ERR_CONFIG_NOT_ACTIVE` — and, where the order is take-back linked, the
        account's `takeback_agreement_status` being `ACTIVE`, otherwise
        `ERR_TAKEBACK_AGREEMENT_INACTIVE`."
        PRD 3.8: "For a `PACKAGED` order, freight is a three-step tier keyed on `subtotal_cents`
        **before** freight and **before** any credit: a subtotal of 1,000,000 cents or more
        carries no freight at all, a subtotal of at least 500,000 cents but below 1,000,000
        carries 22,500 cents, and anything below 500,000 cents carries 39,500 cents."
        PRD 3.8: "**Step four** settles `takeback_credit_applied_cents`, which is zero outright
        when the order is not take-back linked; where it is linked, compute the cap as 15 percent
        of `pre_credit_total_cents` with the fractional part discarded — a floor, never a round —
        and apply the smaller of the account's `takeback_credit_balance_cents` and that cap."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_depends_on_customer_takeback_agreement
        """
        world = setup_draft_order_with_lines(
            lines=[("cfg_pail", 37)],
            order_overrides={"takeback_linked": True},
            customer_overrides={
                "name": "Charlie Industrial",
                "customer_type": "INDUSTRIAL",
                "takeback_agreement_status": "NONE",
            },
        )
        refused = api.confirm_order(world["order"]["id"], SALES)
        validate_error(refused, ApiErrorId.ERR_TAKEBACK_AGREEMENT_INACTIVE.value, 409)

        updated = validate_success(
            api.set_takeback_agreement(
                world["customer"]["id"], {"agreement_status": "ACTIVE"}, SALES
            )
        )
        assert updated["takeback_agreement_status"] == "ACTIVE"

        confirmed = validate_success(api.confirm_order(world["order"]["id"], SALES))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["subtotal_cents"] == 361228
        assert confirmed["freight_surcharge_cents"] == 39500
        assert confirmed["pre_credit_total_cents"] == 400728
        assert confirmed["takeback_credit_applied_cents"] == 0
        assert confirmed["total_cents"] == 400728

    def test_hold_then_resume_returns_the_order_and_its_lines_to_service(self, api):
        """PRD 3.8: "A confirmed order can be put on hold by a `SalesRep`, supplying a `reason`
        that is recorded into `hold_reason` and moving the order `CONFIRMED → HOLD`."
        PRD 3.8: "Resuming reverses both levels. It moves the order `HOLD → CONFIRMED` and
        requires every line on the order whose status is `OPEN` or `HOLD` to reference a
        configuration that is `ACTIVE` again, otherwise `ERR_CONFIG_NOT_ACTIVE`."
        PRD 3.8: "On success every line in `HOLD` moves `HOLD → OPEN`, `hold_reason` is cleared
        back to null, and the pricing waterfall is recomputed from step one — which means the
        credit-limit gate applies to a resume exactly as it applies to a confirmation, and a
        resume whose recomputed `pre_credit_total_cents` exceeds `credit_limit_cents` is likewise
        refused with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/state_machines/order_hold_then_resume_restores_open_lines
        """
        world = setup_confirmed_order(lines=[("cfg_pail", 37)])
        line = world["lines"][0]

        held = validate_success(
            api.hold_order(world["order"]["id"], {"reason": "CREDIT_REVIEW"}, SALES)
        )
        assert held["status"] == "HOLD"
        assert held["hold_reason"] == "CREDIT_REVIEW"

        resumed = validate_success(api.resume_order(world["order"]["id"], SALES))
        assert resumed["status"] == "CONFIRMED"
        assert resumed["hold_reason"] is None
        assert resumed["subtotal_cents"] == 361228
        assert resumed["freight_surcharge_cents"] == 39500
        assert resumed["pre_credit_total_cents"] == 400728
        assert resumed["total_cents"] == 400728

        assert find_order_line(world["order"]["id"], line["id"])["status"] == "OPEN"
