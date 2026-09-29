"""Catalog registration, resource shapes and the flat collections' filtered reads.

Every test in this module builds its own world from an empty database through the
public API only, because the harness restarts the service before each test with
the logical clock back at its process-start value.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    ApiErrorId,
    assert_consignment_line,
    assert_food_type,
    assert_recipe,
    assert_shift,
    assert_site,
    assert_tracking_station,
    assert_waste_entry,
    factories,
    fixtures,
    make_kitchen_staff_headers,
    make_site_sustainability_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    DEFAULT_CAPTURE_LOCK_SECONDS,
    DEFAULT_TARE_GRAMS,
    DEFAULT_TARGET_INTENSITY_KG_PER_1K_MEALS,
    MAX_WEIGHT_GRAMS,
)

WORKING_CLOCK = "2026-08-01T12:00:00Z"


class TestSiteRegistration:
    """Registering a kitchen site and the scoreboard it starts life with."""

    def test_registering_a_site_persists_its_inputs_and_zeroes_every_aggregate(
        self, api, platform_admin_headers
    ):
        """A newly registered kitchen echoes its inputs and starts with a blank scoreboard.

        PRD Coverage: "Registering a site takes a human-readable `name`, an operator-assigned short code in `site_code` that must be between 2 and 12 characters long and must be unique across every site in the platform, and a `region_code` naming the corporate reporting region the site rolls up into." "A freshly registered site is a clean slate: `total_captured_weight_grams`, `valued_waste_cost_cents`, `diverted_weight_grams_settled` and `open_alert_count` all read 0, `diversion_rate_pct` reads null because there is no captured weight to divide by, and `coaching_posture` reads `MONITORING`." "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increases by exactly 1 each time the row is mutated."

        Design: Corner/entities/site_creation_persists_inputs_and_zeroed_aggregates
        """
        payload = factories.create_site_payload(target_intensity_kg_per_1k_meals=11.5)

        response = api.create_site(payload, platform_admin_headers)

        site = validate_success(response, 201)
        assert response.json()["response_type"] == "object"
        assert_site(site)
        assert site["name"] == TEST_DEFAULTS["site_name"]
        assert site["site_code"] == TEST_DEFAULTS["site_code"]
        assert site["region_code"] == TEST_DEFAULTS["region_code"]
        assert site["target_intensity_kg_per_1k_meals"] == pytest.approx(11.5, abs=0.01)
        assert site["total_captured_weight_grams"] == 0
        assert site["valued_waste_cost_cents"] == 0
        assert site["diverted_weight_grams_settled"] == 0
        assert site["diversion_rate_pct"] is None
        assert site["open_alert_count"] == 0
        assert site["coaching_posture"] == "MONITORING"
        assert site["version"] == 1
        assert site["id"] and site["created_at"] and site["updated_at"]

    def test_omitting_the_intensity_goal_defaults_it_to_ten_kilograms_per_thousand_meals(
        self, api, platform_admin_headers
    ):
        """The site's own operating intensity goal falls back to 10.000 when it is not supplied.

        PRD Coverage: "An optional `target_intensity_kg_per_1k_meals` sets the site's own operating intensity goal — the figure the shift leaderboard measures each service period against — expressed to 3 decimal places, required to be greater than zero, and defaulting to 10.000 when omitted."

        Design: Corner/entities/site_defaults_target_intensity_to_ten_when_omitted
        """
        payload = factories.create_site_payload(
            name="Riverside Kitchen", site_code="RK-02", region_code="MW"
        )
        assert "target_intensity_kg_per_1k_meals" not in payload

        response = api.create_site(payload, platform_admin_headers)

        site = validate_success(response, 201)
        assert site["target_intensity_kg_per_1k_meals"] == pytest.approx(
            DEFAULT_TARGET_INTENSITY_KG_PER_1K_MEALS, abs=0.01
        )


class TestStationInstallation:
    """Installing a scale and terminal at a place in the kitchen."""

    def test_installing_a_station_defaults_its_tare_lock_and_availability(
        self, api, platform_admin_headers
    ):
        """The three optional parts of a station profile fall back to 0 grams, 30 seconds and ACTIVE.

        PRD Coverage: "Three optional inputs complete the profile: `tare_grams`, the container tare the scale firmware subtracts before a capture is posted, which must be zero or greater and defaults to 0; `capture_lock_seconds`, the length in seconds of the station occupation interval that each capture creates, which must be at least 0 and at most 600 and defaults to 30; and `status`, which defaults to `ACTIVE`."

        Design: Corner/entities/tracking_station_defaults_tare_lock_and_active_status
        """
        site = fixtures.create_site()
        payload = factories.create_tracking_station_payload(
            site["id"], station_code="PREP-1", station_kind="PREP"
        )
        for optional in ("tare_grams", "capture_lock_seconds", "status"):
            assert optional not in payload

        response = api.create_tracking_station(payload, platform_admin_headers)

        station = validate_success(response, 201)
        assert_tracking_station(station)
        assert station["tare_grams"] == DEFAULT_TARE_GRAMS
        assert station["capture_lock_seconds"] == DEFAULT_CAPTURE_LOCK_SECONDS
        assert station["status"] == "ACTIVE"
        assert station["site_id"] == site["id"]
        assert station["station_code"] == "PREP-1"

    def test_installing_a_station_at_an_unknown_site_reports_the_site_as_not_found(
        self, api, platform_admin_headers
    ):
        """The site a station is installed at is carried as a body identifier, so an unresolvable one is a site not-found.

        PRD Coverage: "Existence of every foreign key supplied in the request body, including every member of a `site_ids` array — the referenced entity's not-found error."

        Design: Corner/entities/tracking_station_for_an_unknown_site_returns_not_found
        """
        payload = factories.create_tracking_station_payload(
            NON_EXISTENT_UUID, station_code="PREP-1", station_kind="PREP"
        )

        response = api.create_tracking_station(payload, platform_admin_headers)

        validate_error(response, ApiErrorId.SITE_NOT_FOUND.value)


class TestCatalogValuationShapes:
    """The catalog of discardable food and the fully-loaded cost of a recipe."""

    def test_omitting_the_donation_shelf_life_defaults_it_to_zero_hours(
        self, api, platform_admin_headers
    ):
        """A food type left without a stated shelf life carries zero hours, not null.

        PRD Coverage: "Finally, `donation_shelf_life_hours` states how many hours after capture a donation pickup may still legally collect this food type; it must be zero or greater and defaults to 0, which in practice means a food type left at the default can never satisfy the donation timing rule unless the pickup begins at the very instant of capture."

        Design: Corner/entities/food_type_defaults_donation_shelf_life_hours_to_zero
        """
        payload = factories.create_food_type_payload(
            name="Day-Old Bread",
            category="BAKERY",
            default_cost_per_kg_cents=210,
            donation_eligible=True,
            animal_feed_eligible=True,
            compostable=True,
        )
        payload.pop("donation_shelf_life_hours")

        response = api.create_food_type(payload, platform_admin_headers)

        food_type = validate_success(response, 201)
        assert_food_type(food_type)
        assert food_type["donation_shelf_life_hours"] == 0
        assert food_type["default_cost_per_kg_cents"] == 210

    def test_creating_a_recipe_computes_its_cost_fields_and_leaves_the_published_cost_null(
        self, api, platform_admin_headers
    ):
        """A one-line recipe of 2.0 kilograms at 500 cents costs 1000 cents over a 2.000 kilogram yield, and its frozen basis stays empty in draft.

        PRD Coverage: "The costing pass runs in four steps and its step boundaries are normative. First, for each ingredient element taken in array order, the line's gross cost is the exact decimal product of `quantity_kg` and `unit_cost_cents_per_kg`, and that product is immediately rounded half up to a whole number of cents to become the line's cost; separately, the line's usable kilograms are the exact decimal product of `quantity_kg` and the fraction that survives trimming, which is one minus `trim_loss_pct`, and this product is not rounded at this step. Second, `total_ingredient_cost_cents` is the plain integer sum of those already-rounded per-line cent figures. Third, `usable_yield_kg` is the sum of the per-line usable kilograms, rounded half up to 3 decimal places once, at the end. Fourth, `cost_per_kg_cents` is `total_ingredient_cost_cents` divided by that rounded `usable_yield_kg`, rounded half up to a whole number of cents." "While it is `DRAFT`, `published_cost_per_kg_cents` and `published_at` are both null and no capture may reference it."

        Design: Corner/entities/recipe_creation_computes_cost_fields_and_leaves_published_cost_null
        """
        payload = factories.create_recipe_payload(
            ingredients=[factories.recipe_ingredient("Stock Base", 2.0, 500, 0.00)],
            recipe_code="STK-PLN",
            name="Plain Stock",
        )

        response = api.create_recipe(payload, platform_admin_headers)

        recipe = validate_success(response, 201)
        assert_recipe(recipe)
        assert recipe["total_ingredient_cost_cents"] == 1000
        assert recipe["usable_yield_kg"] == pytest.approx(2.000, abs=0.01)
        assert recipe["cost_per_kg_cents"] == 500
        assert recipe["status"] == "DRAFT"
        assert recipe["published_cost_per_kg_cents"] is None
        assert recipe["published_at"] is None


class TestCaptureAndAllocationShapes:
    """What the server owns on a weighed loss, and the immutability of an allocation line."""

    def test_capture_status_site_stream_and_operator_are_server_owned(self, api):
        """The terminal cannot dictate a capture's status, site, stream or capturing operator.

        PRD Coverage: "Once the guards pass, the capture is written in status `RECORDED` and a substantial amount of derivation follows. Its `site_id` is copied from the station's own `site_id` and is never changed afterwards. Its `stream` is derived from placement and cause together: `POST_CONSUMER` when the station's `station_kind` is `DISH_RETURN` or when the `loss_reason` is `PLATE_WASTE`, and `PRE_CONSUMER` in every other case — which means a dish-return station always produces post-consumer records regardless of stated reason, and plate waste is post-consumer wherever it is weighed." "`captured_by_user_id` records the capturing operator's `X-User-ID`, which is the comparison target of the void duty separation." "`provisional_cost_cents` is that product taken against `catalog_cost_basis_cents`, ignoring recipe attribution entirely." "Routing starts empty: `routed_weight_grams` is 0 and `unrouted_weight_grams` equals the full `weight_grams`."

        Design: Corner/entities/waste_entry_system_and_computed_fields_are_server_owned_input_ignored
        """
        fixtures.set_clock(WORKING_CLOCK)
        world = fixtures.site_with_open_shift()

        payload = factories.create_waste_entry_payload(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            weight_grams=1000,
            loss_reason="OVERPRODUCTION",
            captured_at="2026-08-01T10:00:00Z",
            status="VOIDED",
            stream="POST_CONSUMER",
            captured_by_user_id="someone-else",
        )

        response = api.create_waste_entry(payload, make_kitchen_staff_headers("ks-1"))

        entry = validate_success(response, 201)
        assert_waste_entry(entry)
        assert entry["status"] == "RECORDED"
        assert entry["stream"] == "PRE_CONSUMER"
        assert entry["captured_by_user_id"] == "ks-1"
        assert entry["site_id"] == world["site"]["id"]
        assert entry["provisional_cost_cents"] == 640
        assert entry["routed_weight_grams"] == 0
        assert entry["unrouted_weight_grams"] == 1000

    def test_an_allocation_line_carries_neither_version_nor_updated_at(self, api):
        """Routing grams onto a draft consignment writes an immutable event record.

        PRD Coverage: "`ConsignmentLine` is the one exception: an allocation line is an immutable event record, so it carries only `id` and `created_at` — it has neither `updated_at` nor `version`, and nothing in the system ever bumps a line's version because it has none." "A line is an immutable event record: it carries only `id` and `created_at`, with no `updated_at` and no `version` of its own." "The platform stamps `created_by_user_id` with the acting `X-User-ID`."

        Design: Corner/entities/consignment_line_carries_no_version_and_has_no_update_endpoint
        """
        fixtures.set_clock(WORKING_CLOCK)
        world = fixtures.site_with_open_shift()
        entry = fixtures.capture_entry(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            weight_grams=1000,
            loss_reason="OVERPRODUCTION",
            captured_at="2026-08-01T10:00:00Z",
        )
        hauler = fixtures.create_hauler(channels=["COMPOST", "DONATION"])
        consignment = fixtures.open_consignment(
            world["site"]["id"],
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-08-02T09:00:00Z",
            pickup_window_end="2026-08-02T11:00:00Z",
        )

        response = api.create_consignment_line(
            factories.create_consignment_line_payload(consignment["id"], entry["id"], 400),
            make_site_sustainability_manager_headers(world["site"]["id"]),
        )

        line = validate_success(response, 201)
        assert_consignment_line(line)
        assert line["id"] and line["created_at"]
        assert "version" not in line
        assert "updated_at" not in line
        assert line["allocated_weight_grams"] == 400
        assert line["created_by_user_id"] == world["site"]["id"]


class TestReadsAndFilteredNavigation:
    """Single-resource reads, paginated listings and the filtered reverse-navigation read."""

    def test_reading_a_site_by_id_returns_the_stored_row(self, api, corporate_lead_headers):
        """A corporate lead who never wrote the row reads back exactly what registration stored.

        PRD Coverage: "An optional `target_intensity_kg_per_1k_meals` sets the site's own operating intensity goal — the figure the shift leaderboard measures each service period against — expressed to 3 decimal places, required to be greater than zero, and defaulting to 10.000 when omitted." "A freshly registered site is a clean slate: `total_captured_weight_grams`, `valued_waste_cost_cents`, `diverted_weight_grams_settled` and `open_alert_count` all read 0, `diversion_rate_pct` reads null because there is no captured weight to divide by, and `coaching_posture` reads `MONITORING`."

        Design: Corner/entities/site_retrieval_returns_the_stored_row
        """
        site = fixtures.create_site(target_intensity_kg_per_1k_meals=11.5)

        response = api.get_site(site["id"], corporate_lead_headers)

        read_back = validate_success(response, 200)
        assert_site(read_back)
        assert read_back["id"] == site["id"]
        assert read_back["site_code"] == TEST_DEFAULTS["site_code"]
        assert read_back["target_intensity_kg_per_1k_meals"] == pytest.approx(11.5, abs=0.01)
        assert read_back["coaching_posture"] == "MONITORING"

    def test_listing_sites_reports_the_unpaginated_total_and_whether_rows_remain(
        self, api, platform_admin_headers
    ):
        """Three registered kitchens read two at a time expose the total count and the remaining-rows flag.

        PRD Coverage: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the returned page."

        Design: Corner/entities/sites_listing_reports_total_count_and_has_more
        """
        fixtures.create_site(name="Harbor Kitchen", site_code="HK-01", region_code="NE")
        fixtures.create_site(name="Riverside Kitchen", site_code="RK-02", region_code="NE")
        fixtures.create_site(name="Uptown Kitchen", site_code="UK-03", region_code="NE")

        first_response = api.list_sites(platform_admin_headers, limit=2, offset=0)
        second_response = api.list_sites(platform_admin_headers, limit=2, offset=2)

        first_page, first_meta = validate_paginated(first_response)
        assert first_response.json()["response_type"] == "array"
        assert len(first_page) == 2
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(second_response)
        assert len(second_page) == 1
        assert second_meta["offset"] == 2
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

    def test_listing_shifts_by_site_and_status_returns_only_the_rows_matching_both(self, api):
        """Site and status combine on one read, selecting the single open period of the first kitchen.

        PRD Coverage: "Service periods may be listed filtered by `site_id`, `shift_date`, `shift_code` or `status`, and that list read doubles as the shift-level leaderboard." "Filters on the same read combine conjunctively — supplying both `site_id` and `status` returns only rows matching both — and an unrecognised filter value for an enum-typed parameter is a schema violation reported as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/shifts_listing_filtered_by_site_and_status_returns_only_matching_rows
        """
        site_a = fixtures.create_site(name="Harbor Kitchen", site_code="HK-01", region_code="NE")
        site_b = fixtures.create_site(name="Riverside Kitchen", site_code="RK-02", region_code="NE")
        shift_a_am = fixtures.open_shift(
            site_a["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250
        )
        shift_a_pm = fixtures.open_shift(
            site_a["id"], shift_date="2026-08-01", shift_code="PM", meals_served=300
        )
        fixtures.close_shift(shift_a_pm["id"])
        fixtures.open_shift(site_b["id"], shift_date="2026-08-01", shift_code="AM", meals_served=180)

        response = api.list_shifts(
            make_site_sustainability_manager_headers(site_a["id"]),
            site_id=site_a["id"],
            status="OPEN",
        )

        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert_shift(rows[0])
        assert rows[0]["id"] == shift_a_am["id"]
        assert rows[0]["shift_code"] == "AM"
        assert rows[0]["status"] == "OPEN"


class TestRequestShapeRejections:
    """Unresolvable identifiers and malformed bodies, refused before any row is written."""

    def test_reading_a_site_that_was_never_registered_reports_not_found(
        self, api, platform_admin_headers
    ):
        """An identifier on the path that names no kitchen is a not-found, never an empty success.

        PRD Coverage: "That single identifier is resolved before any body content is inspected, and a path identifier that names no existing row yields that entity's not-found error."

        Design: Corner/entities/site_read_with_unknown_id_returns_not_found
        """
        response = api.get_site(NON_EXISTENT_UUID, platform_admin_headers)

        error = validate_error(response, ApiErrorId.SITE_NOT_FOUND.value)
        assert response.json()["response_type"] == "error"
        assert error["error_id"] == ApiErrorId.SITE_NOT_FOUND.value

    def test_registering_a_site_without_its_short_code_is_rejected_and_writes_nothing(
        self, api, platform_admin_headers
    ):
        """The short code has no default, so omitting it fails the body check before any uniqueness test.

        PRD Coverage: "Body schema: parseability, presence of required fields, declared JSON types, enum membership, non-negativity where declared, decimal scale, `YYYY-MM-DD` dates, RFC 3339 UTC timestamps with a trailing `Z`, and the declared range invariants (`start_date` no later than `end_date`, `window_start` no later than `window_end`, `period_start` no later than `period_end`, `pickup_window_start` strictly before `pickup_window_end`, a non-empty `ingredients` array, a non-empty `site_ids` array) — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/site_creation_missing_required_site_code_is_rejected
        """
        payload = factories.create_site_payload()
        payload.pop("site_code")

        response = api.create_site(payload, platform_admin_headers)

        validate_error(response, ApiErrorId.INVALID_REQUEST.value)
        _, meta = validate_paginated(api.list_sites(platform_admin_headers))
        assert meta["total_count"] == 0

    @pytest.mark.parametrize(
        "overrides",
        [
            {"name": "Tiny", "site_code": "H"},
            {"name": "Long", "site_code": "HARBOR-KITCHEN-01"},
            {"name": "Zero", "site_code": "ZK-04", "target_intensity_kg_per_1k_meals": 0},
        ],
        ids=["short_code", "long_code", "non_positive_intensity"],
    )
    def test_a_short_code_outside_two_to_twelve_characters_or_a_non_positive_goal_is_rejected(
        self, api, platform_admin_headers, overrides
    ):
        """A one-character code, a seventeen-character code and a zero intensity goal all fail the body check.

        PRD Coverage: "Registering a site takes a human-readable `name`, an operator-assigned short code in `site_code` that must be between 2 and 12 characters long and must be unique across every site in the platform, and a `region_code` naming the corporate reporting region the site rolls up into." "An optional `target_intensity_kg_per_1k_meals` sets the site's own operating intensity goal — the figure the shift leaderboard measures each service period against — expressed to 3 decimal places, required to be greater than zero, and defaulting to 10.000 when omitted."

        Design: Corner/entities/site_code_outside_the_declared_length_range_is_rejected
        """
        response = api.create_site(
            factories.create_site_payload(**overrides), platform_admin_headers
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    def test_a_food_category_outside_the_five_reporting_categories_is_rejected(
        self, api, platform_admin_headers
    ):
        """A category the catalog does not declare is a body failure, never a stored value.

        PRD Coverage: "A food type carries a `name` that must be globally unique — a duplicate is refused with `ERR_DUPLICATE_FOOD_TYPE_NAME` — and a reporting `category` drawn from `PRODUCE`, `PROTEIN`, `PREPARED`, `BAKERY` and `DAIRY`."

        Design: Corner/entities/food_type_category_enum_rejects_an_undeclared_member
        """
        payload = factories.create_food_type_payload(
            name="Frozen Peas",
            category="FROZEN",
            default_cost_per_kg_cents=180,
            donation_eligible=False,
            animal_feed_eligible=True,
            compostable=True,
        )

        response = api.create_food_type(payload, platform_admin_headers)

        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    def test_one_unknown_kitchen_among_the_rollup_scope_reports_the_site_as_not_found(
        self, api, corporate_lead_headers
    ):
        """Every member of the reporting scope is resolved, so a single unknown kitchen sinks the whole request.

        PRD Coverage: "That array is a list of site identifiers rather than a single foreign key: it must hold at least one element, every element must be an existing site, order is irrelevant, and a repeated site is refused with `ERR_DUPLICATE_SITE_IN_SCOPE`." "Existence of every foreign key supplied in the request body, including every member of a `site_ids` array — the referenced entity's not-found error."

        Design: Corner/entities/rollup_site_ids_must_all_resolve_or_the_request_is_not_found
        """
        site = fixtures.create_site()
        payload = factories.create_rollup_payload([site["id"], NON_EXISTENT_UUID])

        response = api.create_rollup(payload, corporate_lead_headers)

        validate_error(response, ApiErrorId.SITE_NOT_FOUND.value)
        _, meta = validate_paginated(api.list_rollups(corporate_lead_headers))
        assert meta["total_count"] == 0

    def test_a_baseline_window_ending_before_it_starts_is_rejected(self, api):
        """The inclusive baseline window must not run backwards, and that is a body failure rather than an overlap.

        PRD Coverage: "Opening one is the owning `SiteSustainabilityManager`'s duty and takes the `site_id`, a `start_date` and an `end_date`, both calendar dates in `YYYY-MM-DD` form, with `end_date` no earlier than `start_date`."

        Design: Corner/entities/baseline_period_end_date_before_start_date_is_rejected
        """
        site = fixtures.create_site()
        payload = factories.create_baseline_period_payload(
            site["id"], start_date="2026-08-10", end_date="2026-08-01"
        )

        response = api.create_baseline_period(
            payload, make_site_sustainability_manager_headers(site["id"])
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    def test_registering_a_hauler_with_an_empty_channel_list_is_rejected(
        self, api, platform_admin_headers
    ):
        """A recipient organisation contracted for nothing at all cannot be registered.

        PRD Coverage: "A hauler or recipient organisation is registered by a `PlatformAdmin` with a globally unique `name`, refused on collision with `ERR_DUPLICATE_HAULER_NAME`, and a `channels` array of at least one entry, without duplicates, drawn from `DONATION`, `ANIMAL_FEED`, `COMPOST` and `LANDFILL` — these are the channels the organisation is contracted for."

        Design: Corner/entities/hauler_channels_must_be_a_non_empty_list_rejected_when_empty
        """
        payload = factories.create_hauler_payload(channels=[])

        response = api.create_hauler(payload, platform_admin_headers)

        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    def test_a_capture_above_two_hundred_kilograms_is_rejected_while_the_boundary_is_valued(
        self, api
    ):
        """200001 grams fails the body check; exactly 200000 grams is accepted and valued at 128000 cents.

        PRD Coverage: "The request names the `station_id` that weighed the loss, the `shift_id` the loss is booked to, the `food_type_id` of the discarded item, the net `weight_grams` which must be greater than 0 and no more than 200000, and a `loss_reason` drawn from `OVERPRODUCTION`, `SPOILAGE`, `TRIM`, `EXPIRATION`, `PLATE_WASTE` and `CONTAMINATION`." "The weight is converted to kilograms by dividing `weight_grams` by 1000, an exact decimal that is never rounded, and the cost is that kilogram figure multiplied by the chosen basis in cents per kilogram, rounded half up to a whole number of cents."

        Design: Corner/entities/waste_entry_weight_above_two_hundred_kilograms_is_rejected
        """
        fixtures.set_clock(WORKING_CLOCK)
        world = fixtures.site_with_open_shift()
        staff_headers = make_kitchen_staff_headers("ks-1")

        over_limit = api.create_waste_entry(
            factories.create_waste_entry_payload(
                world["station"]["id"],
                world["shift"]["id"],
                world["food_type"]["id"],
                weight_grams=MAX_WEIGHT_GRAMS + 1,
                loss_reason="SPOILAGE",
                captured_at="2026-08-01T09:00:00Z",
            ),
            staff_headers,
        )
        validate_error(over_limit, ApiErrorId.INVALID_REQUEST.value)

        at_limit = api.create_waste_entry(
            factories.create_waste_entry_payload(
                world["station"]["id"],
                world["shift"]["id"],
                world["food_type"]["id"],
                weight_grams=MAX_WEIGHT_GRAMS,
                loss_reason="SPOILAGE",
                captured_at="2026-08-01T10:00:00Z",
            ),
            staff_headers,
        )

        entry = validate_success(at_limit, 201)
        assert_waste_entry(entry)
        assert entry["weight_grams"] == MAX_WEIGHT_GRAMS
        assert entry["provisional_cost_cents"] == 128000
