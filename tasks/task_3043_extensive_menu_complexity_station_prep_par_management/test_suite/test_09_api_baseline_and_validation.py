"""Baseline envelope/creation corners and the validation ladder."""

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, is_iso8601_timestamp,
    ApiErrorId,
    set_clock, create_restaurant, create_manager, create_cook,
    create_prep_item, create_menu_revision_with_recipes,
    create_restaurant_payload, create_station_payload, create_cook_payload,
    create_demand_forecast_payload, create_forecast,
    make_kitchen_manager_headers, make_line_cook_headers,
    menu_admin_headers, system_admin_headers, build_user_headers,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


class TestRestaurantCreateDefaults:
    def test_create_returns_defaults_and_system_fields(self, api):
        """PRD section 3.1: "A freshly created restaurant starts in `ACTIVE`
        status with `weekly_bakery_budget_spent_cents` at zero and
        `current_waitlist_minutes` at zero; the spent counter is reserved
        against by confirmed bakery orders and released when such an order is
        cancelled, while the waitlist figure is maintained through a
        dedicated `KitchenManager` update operation that supplies
        `waitlist_minutes` and overwrites `current_waitlist_minutes`, feeding
        the peak-load multiplier described in §3.8."
        PRD section 2.5: "All resources in this system carry a standard set
        of system-managed fields:"
        PRD section 2.5: "`version` (integer): a system-managed integer that
        increments with every mutation of the resource, and which serves as
        the basis for optimistic concurrency control."

        Design: Corner/entities/restaurant_create_returns_defaults_and_system_fields
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_restaurant(
            create_restaurant_payload(), system_admin_headers())
        data = validate_success(resp, 201)
        assert data["status"] == "ACTIVE"
        assert data["weekly_bakery_budget_spent_cents"] == 0
        assert data["current_waitlist_minutes"] == 0
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)


class TestPrepItemRoundtrip:
    def test_get_roundtrips_configuration_and_default_status(self, api):
        """PRD section 3.2: "Each prep item is created with a `name`, the
        `station_type` that preps it (again one of `GRILL`, `SAUTE`, `FRY`,
        `BAKERY`, `COLD`), a `shelf_life_hours` describing how long a prepped
        batch remains usable after it is produced, a `min_batch_size` giving
        the smallest producible batch in the item's `batch_unit`, and the
        `batch_unit` itself, one of `OZ`, `EA`, or `ML`. Both
        `shelf_life_hours` and `min_batch_size` must be greater than zero.
        Batch sizing throughout the system rounds to multiples of
        `min_batch_size`, and a prep item begins life `ACTIVE`."

        Design: Corner/entities/prep_item_get_roundtrips_stored_configuration
        """
        set_clock("2026-09-01T00:00:00Z")
        created = validate_success(api.create_prep_item(
            {"name": "Diced Onions", "station_type": "SAUTE",
             "shelf_life_hours": 48, "min_batch_size": 10,
             "batch_unit": "OZ"}, menu_admin_headers()), 201)
        fetched = validate_success(
            api.get_prep_item(created["id"], menu_admin_headers()))
        assert fetched["name"] == "Diced Onions"
        assert fetched["station_type"] == "SAUTE"
        assert fetched["shelf_life_hours"] == 48
        assert fetched["min_batch_size"] == 10
        assert fetched["batch_unit"] == "OZ"
        assert fetched["status"] == "ACTIVE"


class TestCookListPagination:
    def test_cooks_paginate_with_total_count_and_has_more(self, api):
        """PRD section 2.3: "For endpoints that return lists of resources,
        pagination is controlled via query parameters. The `limit` parameter
        specifies the maximum number of items to return. If not provided, it
        defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter specifies the number of items to skip and defaults
        to 0."
        PRD section 3.3: "Cooks may be listed filtered by `restaurant_id` or
        `status`."

        Design: Corner/entities/cooks_list_paginates_with_total_count_and_has_more
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["GRILL"])
        mh = make_kitchen_manager_headers(mgr["id"])
        create_cook(rest["id"], mgr["id"], name="Cook Two",
                    certified_station_types=["GRILL"])
        create_cook(rest["id"], mgr["id"], name="Cook Three",
                    certified_station_types=["SAUTE"])
        page1, meta1 = validate_paginated(api.list_cooks(
            mh, params={"restaurant_id": rest["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_cooks(
            mh, params={"restaurant_id": rest["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        all_rows, meta3 = validate_paginated(api.list_cooks(
            mh, params={"restaurant_id": rest["id"]}))
        assert len(all_rows) == 3
        assert meta3["limit"] == 10
        assert meta3["offset"] == 0


class TestRecipeNotFound:
    def test_unknown_recipe_id_returns_recipe_not_found(self, api):
        """PRD section 2.6: "Fourth, every foreign-key reference in the path
        and body must resolve to an existing resource, validated
        left-to-right, with each entity type carrying its own not-found error"

        Design: Corner/entities/recipe_get_unknown_id_returns_recipe_not_found
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.get_recipe(UNKNOWN_ID, menu_admin_headers())
        validate_error(resp, ApiErrorId.ERR_RECIPE_NOT_FOUND, 404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]


class TestStationMissingCapacity:
    def test_station_create_missing_capacity_invalid_request(self, api):
        """PRD section 2.6: "Second, the request body is validated against
        the endpoint's input schema — required fields present, types correct,
        enum values valid, and integer positivity bounds enforced"
        PRD section 2.6: "any failure here is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/station_create_missing_capacity_returns_invalid_request
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["GRILL"])
        mh = make_kitchen_manager_headers(mgr["id"])
        resp = api.create_station(
            {"restaurant_id": rest["id"], "name": "Grill 1",
             "station_type": "GRILL"}, mh)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        data, meta = validate_paginated(api.list_stations(
            mh, params={"restaurant_id": rest["id"]}))
        assert data == []


class TestForecastFinalizeGate:
    def test_finalize_from_draft_rejected(self, api):
        """PRD section 3.4: "A submitted forecast may be amended, which
        returns it from `SUBMITTED` to `DRAFT` for further editing, or
        finalized, which moves it from `SUBMITTED` to the terminal
        `FINALIZED`; both amendment and finalization require the `SUBMITTED`
        state and reject anything else with `ERR_FORECAST_NOT_SUBMITTED`."

        Design: Corner/state_machines/forecast_finalize_from_draft_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
        mh = make_kitchen_manager_headers(mgr["id"])
        forecast = validate_success(api.create_demand_forecast(
            create_demand_forecast_payload(
                rest["id"], service_date="2026-09-02T00:00:00Z",
                expected_covers=50, item_mix=[]), mh), 201)
        resp = api.finalize_forecast(forecast["id"], mh)
        validate_error(resp, ApiErrorId.ERR_FORECAST_NOT_SUBMITTED, 409)
        now = validate_success(api.get_demand_forecast(forecast["id"], mh))
        assert now["status"] == "DRAFT"


class TestForecastFuturity:
    def test_past_service_date_rejected_future_submits(self, api):
        """PRD section 3.4: "Submission requires the forecast to be `DRAFT`
        (otherwise `ERR_FORECAST_NOT_DRAFT`) and enforces futurity: the
        `service_date` must fall strictly after the logical clock's current
        instant at submit time, failing which the submission is rejected with
        `ERR_FORECAST_DATE_PAST`."

        Design: Corner/validations/forecast_submit_with_past_service_date_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
        mh = make_kitchen_manager_headers(mgr["id"])
        past = validate_success(api.create_demand_forecast(
            create_demand_forecast_payload(
                rest["id"], service_date="2026-08-31T00:00:00Z",
                expected_covers=50, item_mix=[]), mh), 201)
        future = validate_success(api.create_demand_forecast(
            create_demand_forecast_payload(
                rest["id"], service_date="2026-09-02T00:00:00Z",
                expected_covers=50, item_mix=[]), mh), 201)
        resp = api.submit_forecast(past["id"], mh)
        validate_error(resp, ApiErrorId.ERR_FORECAST_DATE_PAST, 422)
        past_now = validate_success(api.get_demand_forecast(past["id"], mh))
        assert past_now["status"] == "DRAFT"
        submitted = validate_success(api.submit_forecast(future["id"], mh))
        assert submitted["status"] == "SUBMITTED"


class TestMissingAuthHeader:
    def test_missing_role_header_rejected(self, api):
        """PRD section 2.1: "A request whose headers are missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_rejected_before_everything
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_restaurant(
            create_restaurant_payload(name="NoRole", code="NOROLE",
                                      weekly_bakery_budget_cents=1000),
            {"X-User-ID": "someone", "Content-Type": "application/json"})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestSchemaBeforeRole:
    def test_schema_error_beats_role_check(self, api):
        """PRD section 2.6: "Every request is evaluated against a fixed
        validation ladder, and earlier rungs mask later ones."
        PRD section 2.6: "First, the presence of the authentication headers is
        checked."
        PRD section 2.6: "Third, role authorization is enforced."
        PRD section 2.6: "any failure here is `ERR_INVALID_REQUEST`."

        Design: Corner/validations/schema_error_beats_role_check_priority
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["GRILL"])
        line = create_cook(rest["id"], mgr["id"], name="Leo Line",
                           certified_station_types=["GRILL"])
        # LineCook is not authorized for station creation AND the required
        # rack_slot_capacity is missing; the schema rung fires first.
        resp = api.create_station(
            {"restaurant_id": rest["id"], "name": "Grill 1",
             "station_type": "GRILL"},
            make_line_cook_headers(line["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestRetiredPrepItemReference:
    def test_recipe_with_retired_component_rejected(self, api):
        """PRD section 3.2: "Every component's prep item must exist and be
        `ACTIVE` at recipe creation; referencing a retired item fails with
        `ERR_PREP_ITEM_NOT_ACTIVE`."

        Design: Corner/validations/recipe_with_retired_prep_item_component_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        item = create_prep_item(name="P", station_type="SAUTE")
        validate_success(api.retire_prep_item(item["id"], menu_admin_headers()))
        revision, _ = create_menu_revision_with_recipes(
            rest["id"], [], label="V1",
            effective_from="2026-09-15T00:00:00Z")
        resp = api.create_recipe(
            {"menu_revision_id": revision["id"], "name": "R",
             "station_type": "SAUTE",
             "components": [{"prep_item_id": item["id"],
                             "quantity_per_portion": 3, "unit": "OZ"}]},
            menu_admin_headers())
        validate_error(resp, ApiErrorId.ERR_PREP_ITEM_NOT_ACTIVE, 422)
        data, meta = validate_paginated(api.list_recipes(
            menu_admin_headers(),
            params={"menu_revision_id": revision["id"]}))
        assert data == []


class TestWasteEntryNotFound:
    def test_unknown_waste_entry_id_returns_not_found(self, api):
        """PRD section 2.6: "Fourth, every foreign-key reference in the path
        and body must resolve to an existing resource, validated
        left-to-right, with each entity type carrying its own not-found error"

        Design: Corner/errors/waste_entry_unknown_id_returns_not_found
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.get_waste_entry(
            UNKNOWN_ID, build_user_headers("km-any", "KitchenManager"))
        validate_error(resp, ApiErrorId.ERR_WASTE_ENTRY_NOT_FOUND, 404)


class TestThroughputSummaryShape:
    def test_idle_station_returns_full_schema_zeroed(self, api):
        """PRD section 3.8: "Kitchen pressure is visible through a computed
        per-station throughput summary available to every role, which reports
        the station's `load_score`, `waste_ratio`, `overprep_penalty_points`,
        `par_health`, and `rack_load`."
        PRD section 3.6: "a station with no active pars at all reports `OK`."
        PRD section 3.8: "Third, the waste ratio is the wasted figure divided
        by the sum of wasted and consumed; if that denominator is zero, the
        ratio is zero."

        Design: Corner/endpoints/throughput_summary_computed_read_shape
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["GRILL"])
        mh = make_kitchen_manager_headers(mgr["id"])
        station = validate_success(api.create_station(
            create_station_payload(rest["id"]), mh), 201)
        summary = validate_success(
            api.get_throughput_summary(station["id"], mh))
        assert summary["station_id"] == station["id"]
        assert summary["load_score"] == 0.0
        assert summary["waste_ratio"] == 0.0
        assert summary["overprep_penalty_points"] == 0
        assert summary["par_health"] == "OK"
        assert summary["rack_load"] == 0
