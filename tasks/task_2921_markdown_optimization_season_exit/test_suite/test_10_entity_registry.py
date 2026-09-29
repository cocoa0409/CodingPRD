"""Registry entities: what a create returns, what a read derives, which fields
the server owns, and which identifier an unresolvable reference reports.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_append_only_fields, assert_common_fields
from test_helpers.factories import (
    chain_zone_payload,
    item_payload,
    markdown_plan_payload,
    region_zone_payload,
    sales_week_payload,
    season_payload,
    store_patch_payload,
    store_payload,
    store_zone_payload,
)


class TestSeasonRegistry:
    """Registration is the only way a season enters the system."""

    def test_season_create_returns_its_declared_fields_with_zeroed_counters(
        self, api, director
    ):
        """PRD 3.1: "A newly registered season opens in `PLANNING`, with
        `reserved_clearance_units`, `committed_clearance_units` and
        `projected_exit_units` all at 0, and a duplicate `code` is refused with
        `ERR_DUPLICATE_RESOURCE`." PRD 2.4 fixes the version dimension:
        "`version` starts at 1 when the row is created and increases by exactly 1
        on every mutation of that row, whether the mutation came from a direct
        request or from a cascade triggered elsewhere; `updated_at` is refreshed
        on the same occasions."

        Design: Corner/entities/season_create_returns_declared_and_computed_defaults
        """
        season = validate_success(api.create_season(season_payload(), director), 201)

        assert season["code"] == "FW26-APPAREL"
        assert season["category"] == "APPAREL"
        assert season["season_start_date"] == "2026-08-15"
        assert season["season_end_date"] == "2027-01-31"
        assert season["exit_target_date"] == "2027-01-15"
        assert season["exit_units_target"] == 1000
        assert season["sell_through_target_pct"] == pytest.approx(82.00, abs=0.01)
        assert season["clearance_space_units"] == 900

        assert season["status"] == "PLANNING"
        assert season["version"] == 1
        assert season["reserved_clearance_units"] == 0
        assert season["committed_clearance_units"] == 0
        assert season["projected_exit_units"] == 0
        assert_common_fields(season, "season")

    def test_season_create_refuses_an_unlisted_enum_and_out_of_range_fields(
        self, api, director
    ):
        """PRD 3.1: "Registration carries a human-readable `code` of between 1 and
        32 characters that must be unique across seasons as an exact,
        case-sensitive match, the merchandise `category` the season governs (one
        of `APPAREL`, `FOOTWEAR`, `ACCESSORIES` or `SEASONAL_DECOR`), the calendar
        bracket formed by `season_start_date` and `season_end_date`, the
        `exit_target_date` by which residual inventory must be gone, an
        `exit_units_target` of at least one unit, a `sell_through_target_pct`
        between 0.01 and 100.00, and the chain-level `clearance_space_units`
        budget of at least one unit." The calendar is constrained too:
        "`season_end_date` must fall strictly after `season_start_date`, and
        `exit_target_date` must fall strictly after `season_start_date` while
        landing on or before `season_end_date`." Each is a payload violation, and
        PRD 2.7 rule 3 reports those: "Payload shape: every required field is
        present with its declared type, enum membership and numeric range —
        including unit counts of at least 1, a `depth_pct` inside 0.01 through
        70.00, and a pagination `limit` inside 1 through 100 — else
        `ERR_VALIDATION` (400)."

        Design: Corner/entities/season_create_rejects_bad_enum_and_out_of_range_fields
        """
        validate_error(
            api.create_season(season_payload(category="OUTERWEAR"), director),
            "ERR_VALIDATION",
            400,
        )
        validate_error(
            api.create_season(season_payload(sell_through_target_pct=0.00), director),
            "ERR_VALIDATION",
            400,
        )
        validate_error(
            api.create_season(season_payload(exit_target_date="2027-02-15"), director),
            "ERR_VALIDATION",
            400,
        )

        rows, meta = validate_paginated(api.list_seasons(director))
        assert meta["total_count"] == 0
        assert rows == []


class TestPriceZoneAndStoreRegistry:
    """Zone breadth decides the signage lead, and a store's derived capacity
    follows its declared cap."""

    def test_omitted_signage_lead_days_defaults_by_zone_breadth(self, api, director):
        """PRD 3.1: "When `signage_lead_days` is omitted it defaults by breadth —
        ten days for a `CHAIN` zone, one week for a `REGION` zone, three days for a
        `STORE` zone — because signage takes longer to reach every door of the
        chain than to reach one region or one shop." The nesting is fixed as well:
        "a `REGION` zone must name a `CHAIN` zone as its parent, a `STORE` zone
        must name a `REGION` zone as its parent, and a `CHAIN` zone must name no
        parent at all." A store's own defaults are declared too: "optionally an
        operating `status` drawn from `OPEN`, `REMODEL` and `CLOSING`, defaulting
        to `OPEN`" and "On registration `committed_clearance_units` starts at 0
        and `available_clearance_units` starts equal to `clearance_bay_units`."

        Design: Corner/entities/price_zone_and_store_defaults_derive_from_zone_type
        """
        chain = validate_success(
            api.create_price_zone(chain_zone_payload(signage_lead_days=None), director),
            201,
        )
        assert chain["signage_lead_days"] == 10
        assert chain.get("parent_zone_id") is None

        region = validate_success(
            api.create_price_zone(
                region_zone_payload(chain["id"], signage_lead_days=None), director
            ),
            201,
        )
        assert region["signage_lead_days"] == 7
        assert region["parent_zone_id"] == chain["id"]

        store_zone = validate_success(
            api.create_price_zone(
                store_zone_payload(region["id"], signage_lead_days=None), director
            ),
            201,
        )
        assert store_zone["signage_lead_days"] == 3
        assert store_zone["parent_zone_id"] == region["id"]

        store = validate_success(
            api.create_store(store_payload(store_zone["id"]), director), 201
        )
        assert store["status"] == "OPEN"
        assert store["committed_clearance_units"] == 0
        assert store["available_clearance_units"] == 300

    def test_store_patch_bumps_the_version_and_rederives_available_capacity(
        self, api, director
    ):
        """PRD 3.1: "A director may later revise a store's `status` or its
        `clearance_bay_units`; either revision recomputes `available_clearance_units`
        from the new capacity and bumps the store's `version`." PRD 2.4 fixes what
        a mutation may not touch: "Every resource is addressed by an `id` that the
        server mints as a UUID." And: "`version` starts at 1 when the row is
        created and increases by exactly 1 on every mutation of that row, whether
        the mutation came from a direct request or from a cascade triggered
        elsewhere; `updated_at` is refreshed on the same occasions."

        Design: Corner/entities/store_patch_bumps_version_and_refreshes_updated_at
        """
        chain = fx.create_chain_zone(api)
        west = fx.create_region_zone(api, chain["id"])
        store = fx.create_store(api, west["id"])
        assert store["version"] == 1

        patched = validate_success(
            api.update_store(
                store["id"],
                store_patch_payload(status="REMODEL", clearance_bay_units=250),
                director,
            )
        )

        assert patched["id"] == store["id"]
        assert patched["created_at"] == store["created_at"]
        assert patched["version"] == 2
        assert patched["updated_at"] >= store["updated_at"]
        assert patched["status"] == "REMODEL"
        assert patched["clearance_bay_units"] == 250
        assert patched["committed_clearance_units"] == 0
        assert patched["available_clearance_units"] == 250


class TestItemRegistration:
    """Registration derives the protected window and initialises every computed
    field; a missing required money field persists nothing."""

    def test_item_registration_derives_the_protected_window_and_the_sentinel_cover(
        self, api, analyst
    ):
        """PRD 3.2: "`protected_until_date` is `first_receipt_date` advanced by the
        category's protected period: six weeks for `APPAREL`, eight weeks for
        `FOOTWEAR`, four weeks for `ACCESSORIES` and three weeks for
        `SEASONAL_DECOR` — that is, 42, 56, 28 and 21 days respectively." And:
        "Registration also initialises `current_retail_cents` to
        `original_retail_cents`, sets `on_hand_units` to `units_received_total`,
        and leaves `units_sold_total`, `units_committed_disposition`,
        `units_disposed_total` and `sample_weeks` at 0, `sell_through_pct` at 0.00,
        `weeks_of_supply` at 999.99, `permanent_markdown_reserve_cents` and
        `promo_discount_cents` at 0, `lifecycle_stage` at `NEW_ARRIVAL` and
        `markdown_state` at `FULL_PRICE`." PRD 3.3 rule 2 keeps it there:
        "Otherwise it is `NEW_ARRIVAL` when the current date is on or before its
        `protected_until_date`."

        Design: Corner/entities/item_computed_fields_initialised_from_registration
        """
        season = fx.create_season(api)
        fx.set_clock(api, "2026-08-25T00:00:00Z")

        item = validate_success(
            api.create_item(item_payload(season["id"]), analyst), 201
        )

        assert item["protected_until_date"] == "2026-10-01"
        assert item["current_retail_cents"] == 4999
        assert item["on_hand_units"] == 600
        assert item["units_sold_total"] == 0
        assert item["units_committed_disposition"] == 0
        assert item["units_disposed_total"] == 0
        assert item["sample_weeks"] == 0
        assert item["sell_through_pct"] == pytest.approx(0.00, abs=0.01)
        assert item["weeks_of_supply"] == pytest.approx(999.99, abs=0.01)
        assert item["permanent_markdown_reserve_cents"] == 0
        assert item["promo_discount_cents"] == 0
        assert item["lifecycle_stage"] == "NEW_ARRIVAL"
        assert item["markdown_state"] == "FULL_PRICE"

    def test_item_create_without_a_unit_cost_is_a_payload_violation(
        self, api, analyst, director
    ):
        """PRD 3.2 declares the required inputs: "An item carries a `sku` unique
        across items, the `season_id` it belongs to, its own `category`, a
        `cluster_code` naming the store cluster whose peers it may pool elasticity
        with, a `vendor_code` identifying the supplier that allowance agreements
        will be matched against, the `first_receipt_date` on which its first units
        landed, an `original_retail_cents` ticket of at least one cent, a landed
        `unit_cost_cents` of zero or more, and `units_received_total` of at least
        one unit." PRD 2.7 rule 3: "Payload shape: every required field is present
        with its declared type, enum membership and numeric range — including unit
        counts of at least 1, a `depth_pct` inside 0.01 through 70.00, and a
        pagination `limit` inside 1 through 100 — else `ERR_VALIDATION` (400)."

        Design: Corner/entities/item_create_missing_unit_cost_cents_rejected
        """
        season = fx.create_season(api)
        fx.set_clock(api, "2026-10-10T00:00:00Z")

        response = api.create_item(
            item_payload(season["id"], unit_cost_cents=None), analyst
        )
        validate_error(response, "ERR_VALIDATION", 400)

        rows, meta = validate_paginated(
            api.list_items(analyst, {"season_id": season["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert validate_success(api.get_season(season["id"], director))["status"] == (
            "PLANNING"
        )


class TestItemReadAndListing:
    """A read serves the derived inventory position; a list reports the filtered
    total beside the page window."""

    def test_item_read_serves_the_computed_inventory_position(self, api, analyst):
        """PRD 3.2: "`units_sold_total` grows by the week's `units_sold` and the
        on-hand count falls by the same amount; `sample_weeks` grows by one;
        `sell_through_pct` is recomputed as units sold as a percentage of units
        received, rounded half up to two decimals; and `weeks_of_supply` is
        recomputed as the on-hand units divided by the average weekly sales rate,
        rounded half up to two decimals, where that average rate is itself
        `units_sold_total` divided by `sample_weeks` rounded half up to four
        decimals." The stage follows from PRD 3.3: "An item counts as a slow seller
        when its `sell_through_pct` is strictly below 45.00 percent and it has been
        on hand for at least six weeks."

        Design: Corner/entities/item_get_returns_computed_inventory_position
        """
        sc = fx.base_scenario(api)

        item = validate_success(api.get_item(sc.item["id"], analyst))

        assert item["units_sold_total"] == 257
        assert item["on_hand_units"] == 343
        assert item["sample_weeks"] == 4
        assert item["sell_through_pct"] == pytest.approx(42.83, abs=0.01)
        assert item["weeks_of_supply"] == pytest.approx(5.34, abs=0.01)
        assert item["protected_until_date"] == "2026-10-01"
        assert item["current_retail_cents"] == 4999
        assert item["permanent_markdown_reserve_cents"] == 0
        assert item["promo_discount_cents"] == 0
        assert item["lifecycle_stage"] == "AGING"
        assert item["markdown_state"] == "FULL_PRICE"

    def test_items_list_reports_the_filtered_total_beside_a_one_row_page(
        self, api, director
    ):
        """PRD 2.3: "Every paginated response carries `limit`, `offset`,
        `total_count` and `has_more` inside `meta`, where `total_count` is the
        number of rows matching the filters before the page window is applied and
        `has_more` indicates whether rows remain beyond the current window." And:
        "`limit` is the page size: it defaults to 10 when omitted, may not be
        smaller than 1 and may not be larger than 100." Items are filterable:
        "Items filter on `season_id`, `cluster_code`, `lifecycle_stage`,
        `markdown_state`, `vendor_code` and `category`."

        Design: Corner/entities/items_list_filters_and_paginates_with_total_count
        """
        sc = fx.base_scenario(api)
        newcomer = fx.create_item(
            api, sc.season["id"], sku="N-9009", first_receipt_date="2026-09-15"
        )
        assert newcomer["lifecycle_stage"] == "NEW_ARRIVAL"

        first_page, first_meta = validate_paginated(
            api.list_items(
                director, {"season_id": sc.season["id"], "limit": 1, "offset": 0}
            )
        )
        assert first_meta["total_count"] == 2
        assert first_meta["has_more"] is True
        assert len(first_page) == 1

        second_page, second_meta = validate_paginated(
            api.list_items(
                director, {"season_id": sc.season["id"], "limit": 1, "offset": 1}
            )
        )
        assert second_meta["total_count"] == 2
        assert second_meta["has_more"] is False
        assert len(second_page) == 1

        filtered, filtered_meta = validate_paginated(
            api.list_items(
                director,
                {"season_id": sc.season["id"], "lifecycle_stage": "NEW_ARRIVAL"},
            )
        )
        assert filtered_meta["total_count"] == 1
        assert [row["sku"] for row in filtered] == ["N-9009"]

        every, every_meta = validate_paginated(
            api.list_items(director, {"season_id": sc.season["id"]})
        )
        assert every_meta["limit"] == 10
        assert every_meta["offset"] == 0
        assert every_meta["has_more"] is False
        assert len(every) == 2


class TestSalesWeekHistory:
    """A posted week is append-only history hanging off exactly one item."""

    def test_a_posted_week_carries_no_version_dimension_at_all(self, api, analyst):
        """PRD 2.4: "Two resources are deliberately append-only and therefore carry
        only `id` and `created_at`, with no `updated_at` and no `version` field at
        all: a posted `SalesWeek` and a generated `SeasonExitReview`." And: "A sales
        week is a historical reading and an exit review is a snapshot; neither is
        ever edited in place, and a caller must not expect either field to appear on
        them." PRD 3.2 fixes the one derived field: "Each reading stores its own
        `price_relative_pct`, the posted ticket price as a percentage of the item's
        original retail, rounded half up to two decimals."

        Design: Corner/entities/sales_week_row_is_immutable_with_no_version_dimension
        """
        season = fx.create_season(api)
        item = fx.create_item(api, season["id"])
        fx.transition_season(api, season["id"], "ACTIVE")
        fx.set_clock(api, "2026-10-10T00:00:00Z")

        first = validate_success(
            api.post_sales_week(
                item["id"], sales_week_payload("2026-09-05", 60, 4999), analyst
            ),
            201,
        )
        second = validate_success(
            api.post_sales_week(
                item["id"], sales_week_payload("2026-09-19", 68, 4499), analyst
            ),
            201,
        )

        for week in (first, second):
            assert_append_only_fields(week, "sales_week")
            assert "version" not in week
            assert "updated_at" not in week

        assert first["price_relative_pct"] == pytest.approx(100.00, abs=0.01)
        assert second["price_relative_pct"] == pytest.approx(90.00, abs=0.01)

        weeks, meta = validate_paginated(api.list_item_sales_weeks(item["id"], analyst))
        assert meta["total_count"] == 2
        assert [row["week_ending_date"] for row in weeks] == ["2026-09-05", "2026-09-19"]

        item_after = validate_success(api.get_item(item["id"], analyst))
        assert item_after["units_sold_total"] == 128
        assert item_after["sample_weeks"] == 2

    def test_a_week_posted_under_an_unknown_item_reports_the_item_not_found_code(
        self, api, analyst
    ):
        """PRD 2.7 rule 4: "Path existence: every identifier in the URL resolves,
        checked left to right, else the corresponding 404 code from §2.4." PRD 2.4
        names which one: "Each maps to its own not-found code:
        `ERR_SEASON_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_STEP_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_STORE_NOT_FOUND`,
        `ERR_ESTIMATE_NOT_FOUND`, `ERR_EXECUTION_NOT_FOUND`,
        `ERR_RESERVATION_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND` and `ERR_DISPOSITION_NOT_FOUND`, all at HTTP 404."

        Design: Corner/entities/sales_weeks_posted_under_unknown_item_returns_item_not_found
        """
        season = fx.create_season(api)
        item = fx.create_item(api, season["id"])
        fx.transition_season(api, season["id"], "ACTIVE")
        fx.set_clock(api, "2026-10-10T00:00:00Z")

        response = api.post_sales_week(
            NON_EXISTENT_UUID, sales_week_payload("2026-09-05", 60, 4999), analyst
        )
        validate_error(response, "ERR_ITEM_NOT_FOUND", 404)

        weeks, meta = validate_paginated(api.list_item_sales_weeks(item["id"], analyst))
        assert meta["total_count"] == 0
        assert weeks == []

        untouched = validate_success(api.get_item(item["id"], analyst))
        assert untouched["units_sold_total"] == 0
        assert untouched["sample_weeks"] == 0


class TestUnresolvableReferences:
    """A well-formed identifier that names nothing reports its own 404, whether it
    arrives in the path or in the body."""

    def test_plan_read_with_an_unknown_identifier_reports_the_plan_not_found_code(
        self, api, analyst
    ):
        """PRD 2.4: "Path identifiers are resolved strictly left to right, so the
        outer segment is validated before the inner one and the error reported is
        always the one belonging to the leftmost unresolvable segment." And:
        "Every resource is addressed by an `id` that the server mints as a UUID."
        PRD 2.7 rule 4: "Path existence: every identifier in the URL resolves,
        checked left to right, else the corresponding 404 code from §2.4."

        Design: Corner/entities/markdown_plan_get_with_unknown_id_returns_not_found
        """
        response = api.get_markdown_plan(NON_EXISTENT_UUID, analyst)
        validate_error(response, "ERR_PLAN_NOT_FOUND", 404)

        rows, meta = validate_paginated(api.list_markdown_plans(analyst))
        assert meta["total_count"] == 0
        assert rows == []

    def test_each_unresolvable_body_foreign_key_reports_its_own_not_found_code(
        self, api, analyst
    ):
        """PRD 2.7 rule 5: "Body existence: every foreign key in the request body
        resolves, else the corresponding 404 code." PRD 2.4 extends the not-found
        codes to bodies: "The same codes govern foreign keys carried in a request
        body: an `item_id`, `season_id`, `price_zone_id`, `parent_zone_id`,
        `store_id`, `elasticity_estimate_id`, `markdown_plan_id`,
        `markdown_step_id` or `allowance_agreement_id` that resolves to nothing
        produces the matching 404, and a `price_zone_id` or `parent_zone_id` with
        no matching zone reports `ERR_ZONE_NOT_FOUND`."

        Design: Corner/entities/markdown_plan_with_unresolvable_body_foreign_key_rejected
        """
        sc = fx.certified_scenario(api)
        item_version = validate_success(api.get_item(sc.item["id"], analyst))["version"]

        unknown_estimate = api.create_markdown_plan(
            markdown_plan_payload(
                sc.season["id"], sc.item["id"], NON_EXISTENT_UUID, item_version
            ),
            analyst,
        )
        validate_error(unknown_estimate, "ERR_ESTIMATE_NOT_FOUND", 404)

        unknown_season = api.create_markdown_plan(
            markdown_plan_payload(
                NON_EXISTENT_UUID, sc.item["id"], sc.estimate["id"], item_version
            ),
            analyst,
        )
        validate_error(unknown_season, "ERR_SEASON_NOT_FOUND", 404)

        rows, meta = validate_paginated(
            api.list_markdown_plans(analyst, {"item_id": sc.item["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

        estimate = validate_success(
            api.get_elasticity_estimate(sc.estimate["id"], analyst)
        )
        assert estimate["status"] == "CERTIFIED"
