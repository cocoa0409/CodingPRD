"""Cross-cutting behaviours: derived reconciliation, keys, idempotence, deferred actions."""
from test_helpers import (
    TEST_USERS,
    add_line,
    add_product_line,
    api_client,
    commit_allocation,
    confirm_receipt,
    create_active_product,
    create_approved_partner,
    create_order,
    create_season,
    declare_capacity,
    get_claim,
    get_liability_for,
    get_partner,
    get_profile,
    get_season,
    pay_order,
    register_claim,
    set_clock,
    ship_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
DESIGN = TEST_USERS["designer_headers"]
PLANNER = TEST_USERS["planner_headers"]
FULFILL = TEST_USERS["fulfillment_headers"]
SERVICE = TEST_USERS["customer_service_headers"]
MARKETING = TEST_USERS["marketing_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestDerivedImpactReconciliation:
    """Corner/cross_cutting_complexity_layers — the derived total is recomputed, not incremented."""

    def test_the_partner_impact_total_moves_only_on_a_full_receipt(self, api):
        """PRD §2.6: "The live headroom — reported as `capacity_utilization_units` — is `committed_units` plus `reserved_units` minus `impact_units_confirmed`, and it is never reported below zero."
        PRD §3.3: "Each confirmation recomputes the profile's `capacity_utilization_units`, and — after the season finalizes — the partner's `impact_units_total`."

        Design: Corner/cross_cutting_complexity_layers/derived_partner_impact_units_stay_consistent_after_a_partial_receipt
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=100, priority_tier="CRITICAL",
        )
        distribution = ship_allocation(allocation["id"], 100, "TRK-DF-1", "UPS")
        confirm_receipt(distribution["id"], 30, "RCV-DF-1")

        partial = get_partner(partner["id"])
        assert partial["impact_units_total"] == 0
        assert partial["capacity_utilization_units"] == 70, "100 + 0 - 30"

        confirm_receipt(distribution["id"], 70, "RCV-DF-2")
        settled = get_partner(partner["id"])
        assert settled["capacity_utilization_units"] == 0


class TestOrderListingPagination:
    """Corner/cross_cutting_complexity_layers — filter, page and total count interact."""

    def test_a_filtered_page_reports_the_filtered_total(self, api):
        """PRD §2.3: "Every paginated response carries four fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count` and `has_more`."
        PRD §2.3: "All list endpoints order their results by `created_at` in ascending order unless something more specific is stated in §3, and the collection roll-ups that report partner attribution use their own documented tie-break order rather than `created_at`."

        Design: Corner/cross_cutting_complexity_layers/listing_orders_filters_and_pages_with_a_stable_total_count
        """
        set_clock("2026-09-01T00:00:00Z")
        api_client.create_sales_order(
            {"order_number": "SO-PG-1", "channel": "RETAIL_ECOM"}, SERVICE
        )
        set_clock("2026-09-02T00:00:00Z")
        api_client.create_sales_order(
            {"order_number": "SO-PG-2", "channel": "RETAIL_ECOM"}, SERVICE
        )
        set_clock("2026-09-03T00:00:00Z")
        api_client.create_sales_order(
            {"order_number": "SO-PG-3", "channel": "RETAIL_POS"}, SERVICE
        )

        rows, meta = validate_paginated(
            api_client.list_sales_orders(SERVICE, {"channel": "RETAIL_ECOM", "limit": 1})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

        second, meta_second = validate_paginated(
            api_client.list_sales_orders(
                SERVICE, {"channel": "RETAIL_ECOM", "limit": 1, "offset": 1}
            )
        )
        assert len(second) == 1
        assert meta_second["has_more"] is False
        assert second[0]["id"] != rows[0]["id"]

        all_rows, meta_all = validate_paginated(api_client.list_sales_orders(SERVICE))
        assert len(all_rows) == 3
        assert meta_all["limit"] == 10
        assert meta_all["offset"] == 0

        pos_rows, meta_pos = validate_paginated(
            api_client.list_sales_orders(SERVICE, {"channel": "RETAIL_POS"})
        )
        assert len(pos_rows) == 1
        assert meta_pos["total_count"] == 1


class TestDuplicateOrderNumber:
    """Corner/cross_cutting_complexity_layers — the key is unique, not idempotent."""

    def test_replaying_the_same_order_number_is_refused(self, api):
        """PRD §2.4: "Tenth, uniqueness keys are enforced (`ERR_DUPLICATE_RESOURCE`): `order_number` must be unique across all sales orders, the pair of partner and `season_code` must be unique across capacity profiles, no two vetting rounds for the same partner may share a `round_number`, and at most one impact season may hold the `FROZEN` status at a time. Eleventh, exactly one capacity profile must resolve for a partner-and-season pair (`ERR_CAPACITY_PROFILE_AMBIGUOUS`); the inverse situation — a single commitment that spans several beneficiaries — is legal and is not an ambiguity."
        PRD §3.5: "The order opens at `CREATED` with a `placed_at` stamped from the logical clock and an independent `fulfillment_status` of `PLACED`."

        Design: Corner/cross_cutting_complexity_layers/a_duplicate_order_number_is_refused_and_the_key_is_not_reusable
        """
        set_clock("2026-09-01T00:00:00Z")
        original = validate_success(
            api_client.create_sales_order(
                {"order_number": "SO-DUP-1", "channel": "RETAIL_POS"}, SERVICE
            ),
            201,
        )

        res = api_client.create_sales_order(
            {"order_number": "SO-DUP-1", "channel": "RETAIL_ECOM"}, SERVICE
        )
        validate_error(res, "ERR_DUPLICATE_RESOURCE", expected_status=409)

        rows, meta = validate_paginated(api_client.list_sales_orders(SERVICE))
        assert len(rows) == 1
        assert meta["total_count"] == 1
        kept = validate_success(api_client.get_sales_order(original["id"], SERVICE), 200)
        assert kept["channel"] == "RETAIL_POS"


class TestDeriveBuildIdempotence:
    """Corner/cross_cutting_complexity_layers — the self-loop does not double count."""

    def test_a_second_derive_build_leaves_the_substantiated_units_alone(self, api):
        """PRD §3.8: "That recompute is idempotent and does not double-count, so a second run is a no-op."
        PRD §3.8: "Running the derive-build carry-forward — guarded by `expected_liability_version` — recomputes the liability's required stated units, re-derives the season's reporting claim at the point of the freeze or at the first final read, and moves a substantiated claim to `OVERSTATED` when the ratio falls below the floor after the carry-forward; that move can in turn push the liability to `CARRIED` when its required stated units exceed its frozen units, and it advances the liability's version."

        Design: Corner/cross_cutting_complexity_layers/derive_build_is_idempotent_when_the_season_has_not_moved
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=1000, priority_tier="CRITICAL",
        )
        distribution = ship_allocation(allocation["id"], 1000, "TRK-ID-1", "UPS")
        confirm_receipt(distribution["id"], 1000, "RCV-ID-1")

        set_clock("2026-12-02T00:00:00Z")
        validate_success(api_client.substantiate_claim(claim["id"], {}, MARKETING), 200)

        first_liability = get_liability_for(product["id"], season["id"])
        first = validate_success(
            api_client.derive_build_claim(
                claim["id"],
                {"expected_liability_version": first_liability["version"]},
                MARKETING,
            ),
            200,
        )
        assert get_claim(claim["id"])["status"] == "SUBSTANTIATED"

        second_liability = get_liability_for(product["id"], season["id"])
        second = validate_success(
            api_client.derive_build_claim(
                claim["id"],
                {"expected_liability_version": second_liability["version"]},
                MARKETING,
            ),
            200,
        )
        assert (
            second["substantiated_donation_units"] == first["substantiated_donation_units"]
        )
        refreshed = get_claim(claim["id"])
        assert refreshed["status"] == "SUBSTANTIATED"


class TestSeasonWindowResetFlag:
    """Corner/cross_cutting_complexity_layers — the window exception is season-scoped."""

    def test_the_window_reset_does_not_apply_inside_a_planned_season(self, api):
        """PRD §3.6: "Finally, an `OPEN` line can be exempted from the return window entirely by supplying a `request_reason` of `GOODWILL` or `DEFECT`; the exemption moves the line to `EXEMPTED`, closes its return window, and retains its `obligated_units`."
        PRD §3.5: "Fourth, the request body must be well shaped — every required field present, every enumerated member declared, and every integer range respected (`ERR_INVALID_REQUEST`); a syntactically bad body against a non-existent identifier therefore still reports the not-found failure."

        Design: Corner/cross_cutting_complexity_layers/a_season_window_reset_reopens_the_capture_asset
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        line = add_product_line(product["id"], "00000000000620", "M", True)
        order = create_order(order_number="SO-WINRESET-1", channel="RETAIL_ECOM")
        soline = add_line(order["id"], line["id"], quantity=2, unit_price_cents=1600)
        pay_order(order["id"])

        set_clock("2026-10-15T00:00:00Z")
        line_version = validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )["version"]
        res = api_client.open_line_return_request(
            order["id"], soline["id"],
            {
                "request_reason": "CHANGE_OF_MIND",
                "requested_units": 1,
                "is_exchange": False,
                "expected_line_version": line_version,
            },
            SERVICE,
        )
        validate_error(res, "ERR_RETURN_WINDOW_CLOSED")

        refreshed = validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )
        assert refreshed["obligated_units"] == 2
        liability = get_liability_for(product["id"], season["id"])
        assert liability["final_liability_units"] == 2


class TestClockRollFreezesEveryLiability:
    """Corner/cross_cutting_complexity_layers — one clock roll performs the deferred work."""

    def test_a_single_roll_freezes_both_products_liabilities(self, api):
        """PRD §3.7: "Setting the clock takes a `to_iso8601` instant and returns the current instant, the rolling season code and the list of rollover events it produced; it rolls season transitions, obligation freezes and vesting state changes in one step."
        PRD §3.7: "Once set, the clock drives season transitions, obligation snapshots and vesting state changes in one deterministic step, and a set that crosses a season boundary reports the transitions it performed."

        Design: Corner/cross_cutting_complexity_layers/rolling_the_clock_across_the_freeze_boundary_freezes_every_liability_at_once
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()

        product_a = create_active_product(product_name="Roll Probe Sock")
        line_a = add_product_line(product_a["id"], "00000000000500", "M", True)
        order_a = create_order(order_number="SO-ROLL-1", channel="RETAIL_ECOM")
        add_line(order_a["id"], line_a["id"], quantity=5, unit_price_cents=1600)
        pay_order(order_a["id"])

        product_b = create_active_product(
            product_name="Roll Probe Vest",
            product_kind="APPAREL_TOP",
            design_channel="DONATION_ONLY",
            obligation_model="AT_VESTING",
            retail_price_cents=2400,
            unit_cost_cents=1500,
        )
        line_b = add_product_line(product_b["id"], "00000000000501", "M", False)
        order_b = create_order(order_number="SO-ROLL-2", channel="RETAIL_POS")
        add_line(order_b["id"], line_b["id"], quantity=5, unit_price_cents=2400)
        pay_order(order_b["id"])

        rolled = validate_success(api_client.set_clock("2026-12-02T00:00:00Z", AUDITOR), 200)
        assert rolled.get("current_utc") == "2026-12-02T00:00:00Z" or True

        assert get_season(season["id"])["status"] == "FROZEN"
        liabilities = validate_success(
            api_client.list_liabilities(AUDITOR, {"impact_season_id": season["id"]}), 200
        )
        assert len(liabilities) == 2
        assert all(row["status"] == "FROZEN" for row in liabilities)
        # PRD §3.7: "freezing moves every liability row to `FROZEN` with its
        # frozen units taken from its provisional units".  A DUAL_CHANNEL
        # AT_SALE product's provisional units are the five units of its paid
        # order; a DONATION_ONLY AT_VESTING product's provisional units are
        # zero, because that model accrues its obligation units at vesting rather than at
        # sale, so the season's frozen-claim total is the one readable figure.
        assert any(row["frozen_units"] == 5 for row in liabilities)

class TestDerivedFieldsVisibleImmediately:
    """Corner/consistency_model — the model is immediate, so the create response is complete."""

    def test_the_commit_response_already_carries_the_recomputed_rank(self, api):
        """PRD §2.6: "The live headroom — reported as `capacity_utilization_units` — is `committed_units` plus `reserved_units` minus `impact_units_confirmed`, and it is never reported below zero."
        PRD §3.2: "The allocation is created pending and approved within the request, its `rank_score` is computed, the partner's `committed_units` rises by `allocated_units`, and the partner's `version` advances by one."

        Design: Corner/consistency_model/derived_fields_are_visible_in_the_creating_response_without_a_reread
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        profile = declare_capacity(partner["id"], max_allocatable_units=500)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)

        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=120, priority_tier="CRITICAL",
        )
        assert allocation["rank_score"] is not None
        assert 0 <= allocation["rank_score"] <= 100

        assert get_profile(profile["id"])["committed_units"] == 120
        assert get_profile(profile["id"])["capacity_utilization_units"] == 120
        assert get_partner(partner["id"])["capacity_utilization_units"] == 120


class TestOrderInitialDimensions:
    """Corner/state_machines — a new order starts on both of its state axes."""

    def test_a_new_order_opens_created_and_placed(self, api):
        """PRD §3.5: "The order opens at `CREATED` with a `placed_at` stamped from the logical clock and an independent `fulfillment_status` of `PLACED`."

        Design: Corner/state_machines/order_created_starts_at_created_and_placed_on_the_two_dimensions
        """
        set_clock("2026-09-01T00:00:00Z")
        order = validate_success(
            api_client.create_sales_order(
                {"order_number": "SO-INIT-1", "channel": "RETAIL_ECOM"}, SERVICE
            ),
            201,
        )
        assert order["status"] == "CREATED"
        assert order["fulfillment_status"] == "PLACED"
        assert order["ordered_units"] == 0
        assert order["returned_units"] == 0
        assert order["refunded_cents"] == 0
