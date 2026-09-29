"""Provisioning the department, its products, ingredients and ovens."""

from test_helpers import (
    BAKER,
    CAKE_DESK,
    NON_EXISTENT_UUID,
    REGIONAL_ADMIN,
    api_client,
    assert_bake_day,
    assert_cents,
    assert_department,
    assert_instant,
    assert_minutes,
    assert_null,
    assert_oven,
    assert_pickup_slot,
    assert_product,
    assert_ratio,
    complete_run,
    create_bake_day_payload,
    create_cake_order_payload,
    create_department_payload,
    create_oven_payload,
    create_pickup_slot_payload,
    create_product_payload,
    create_production_run_payload,
    create_waste_record_payload,
    drive_run_to_baking,
    forecast_line_payload,
    is_valid_uuid,
    make_department_manager_headers,
    open_pickup_slot,
    oven_status_payload,
    provision_department,
    provision_oven,
    provision_product,
    provision_second_department,
    read_bake_day,
    read_oven,
    read_run,
    schedule_par_baked_run,
    set_oven_status,
    setup_draft_day,
    setup_planned_day,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_department_created_with_only_its_required_inputs_takes_the_defaults():
    """The optional freight surcharge and donation flag fall back to their defaults.

    PRD §3.1: "`freight_surcharge_pct` is the per-line surcharge applied inside
    ingredient-order costing; it is optional, defaults to 0.05".  The donation
    partner defaults to true and the derived purchase commitment opens at zero.

    Design: Corner/entities/create_department_with_only_required_fields_applies_declared_defaults
    """
    payload = create_department_payload()
    payload.pop("freight_surcharge_pct")

    department = validate_success(
        api_client.create_department(payload, REGIONAL_ADMIN), 201
    )
    assert_department(department)
    assert department["name"] == payload["name"]
    assert department["store_number"] == payload["store_number"]
    assert_ratio(department["freight_surcharge_pct"], 0.05, "freight_surcharge_pct")
    assert_ratio(department["shrink_budget_pct"], 0.03, "shrink_budget_pct")
    assert department["donation_partner_enabled"] is True
    assert_cents(
        department["open_purchase_commitment_cents"],
        0,
        "open_purchase_commitment_cents",
    )
    assert department["version"] == 1
    assert is_valid_uuid(department["id"])


def test_a_product_created_without_its_optional_inputs_takes_the_defaults():
    """Markdown, allergens, recipe and cake-base flag all have declared defaults.

    PRD §3.1: "`markdown_pct` is the fraction taken off the shelf price when a batch
    is discounted; it defaults to 0.5".  The three timing figures "are optional,
    default to 0", the recipe "defaults to empty", and "`is_custom_cake_base`
    defaults to false".

    Design: Corner/entities/product_optional_inputs_fall_back_to_declared_defaults
    """
    department = provision_department()
    payload = create_product_payload(
        department["id"],
        sku="PLAIN-1",
        name="Plain Sheet Cake",
        production_method="THAW_AND_SERVE",
        units_per_rack=12,
        unit_retail_cents=250,
        shelf_life_hours=24,
    )
    for optional in (
        "proof_minutes",
        "bake_minutes",
        "cool_minutes",
        "base_labor_minutes_per_rack",
        "setup_labor_minutes",
        "allergen_tags",
    ):
        payload.pop(optional)

    product = validate_success(api_client.create_product(payload, REGIONAL_ADMIN), 201)
    assert_product(product)
    assert product["sku"] == "PLAIN-1"
    assert product["production_method"] == "THAW_AND_SERVE"
    assert_ratio(product["markdown_pct"], 0.5, "markdown_pct")
    assert product["allergen_tags"] == []
    assert product["allergen_free_claim"] is False
    assert product["recipe_lines"] == []
    assert product["is_custom_cake_base"] is False
    assert product["proof_minutes"] == 0
    assert product["bake_minutes"] == 0
    assert product["cool_minutes"] == 0
    assert_minutes(
        product["base_labor_minutes_per_rack"], 0.00, "base_labor_minutes_per_rack"
    )
    assert_minutes(product["setup_labor_minutes"], 0.00, "setup_labor_minutes")
    assert product["version"] == 1


def test_a_product_without_units_per_rack_is_rejected_as_a_bad_request():
    """A required input cannot be defaulted away.

    PRD §2.10 band 5 is "**Request shape** — required fields present, enum values
    inside their declared sets" and reports `ERR_INVALID_REQUEST`.  PRD §3.1 makes
    `units_per_rack` a required figure that "is how many sellable units one rack
    yields and lies between 1 and 500", so no row may be minted without it.

    Design: Corner/entities/create_product_missing_required_units_per_rack_rejected
    """
    department = provision_department()
    payload = create_product_payload(department["id"])
    payload.pop("units_per_rack")

    rejected = api_client.create_product(payload, REGIONAL_ADMIN)
    validate_error(rejected, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(
        api_client.list_products(REGIONAL_ADMIN, {"department_id": department["id"]})
    )
    assert meta["total_count"] == 0, "The rejected create minted no product"
    assert rows == []

    accepted = validate_success(
        api_client.create_product(
            create_product_payload(department["id"]), REGIONAL_ADMIN
        ),
        201,
    )
    assert accepted["units_per_rack"] == 40


def test_reading_an_oven_back_returns_what_the_create_call_reported():
    """The single-resource GET is the stored representation, defaults included.

    PRD §3.1: "`oven_status` starts at `AVAILABLE`, and a `DepartmentManager` moves
    it by submitting the desired `oven_status` together with an optional
    `status_reason`, which defaults to null".

    Design: Corner/entities/get_oven_returns_the_stored_representation
    """
    department = provision_department()
    created = provision_oven(create_oven_payload(department["id"]))
    assert_oven(created)
    assert created["oven_status"] == "AVAILABLE"
    assert_null(created["status_reason"], "status_reason")

    stored = read_oven(created["id"])
    for field in (
        "id",
        "department_id",
        "name",
        "deck_count",
        "rack_capacity_per_deck",
        "changeover_buffer_minutes",
        "allergen_mode",
        "oven_status",
        "status_reason",
        "version",
        "created_at",
        "updated_at",
    ):
        assert stored[field] == created[field], (
            f"Oven.{field} must read back exactly as the create call reported it"
        )
    assert stored["deck_count"] == 2
    assert stored["rack_capacity_per_deck"] == 4
    assert stored["changeover_buffer_minutes"] == 20
    assert stored["allergen_mode"] == "SHARED"
    assert stored["version"] == 1


def test_a_sku_is_unique_inside_one_department_and_reusable_in_another():
    """Two stores may both stock a PAR-CROIS; one store may not stock it twice.

    PRD §3.1: "`sku` is a 1-to-20-character code that must be unique inside the
    department", and "A `sku` that duplicates one already in the department is
    rejected with `ERR_DUPLICATE_SKU`."  The scope of that uniqueness is the
    department, not the whole chain.

    Design: Corner/validations/sku_uniqueness_is_scoped_to_the_department_so_another_store_may_reuse_it
    """
    home = provision_department()
    other = provision_second_department()
    provision_product(create_product_payload(home["id"]))

    duplicate = api_client.create_product(
        create_product_payload(home["id"], name="Second Croissant Line"),
        REGIONAL_ADMIN,
    )
    validate_error(duplicate, "ERR_DUPLICATE_SKU", 409)

    _, home_meta = validate_paginated(
        api_client.list_products(REGIONAL_ADMIN, {"department_id": home["id"]})
    )
    assert home_meta["total_count"] == 1, "The duplicate minted nothing"

    elsewhere = validate_success(
        api_client.create_product(create_product_payload(other["id"]), REGIONAL_ADMIN),
        201,
    )
    assert elsewhere["sku"] == "PAR-CROIS"
    assert elsewhere["department_id"] == other["id"]


def test_listing_a_departments_products_pages_with_the_standard_envelope():
    """The listing carries limit, offset, total_count and has_more.

    PRD §2.4: "The `meta` block of a list response carries `limit` and `offset` as
    they were applied, `total_count` as the number of rows matching the filter before
    the page window is applied, and `has_more` as a boolean that is true exactly when
    rows remain beyond the current window."  Three products read two at a time show
    `has_more` true on the first page and false on the second.

    Design: Corner/entities/list_products_filtered_by_department_paginates_with_envelope_fields
    """
    department = provision_department()
    for sku, name in (
        ("PAGE-1", "Sourdough Boule"),
        ("PAGE-2", "Rye Boule"),
        ("PAGE-3", "Seeded Boule"),
    ):
        provision_product(create_product_payload(department["id"], sku=sku, name=name))

    first_rows, first_meta = validate_paginated(
        api_client.list_products(
            REGIONAL_ADMIN,
            {"department_id": department["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(first_rows) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api_client.list_products(
            REGIONAL_ADMIN,
            {"department_id": department["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(second_rows) == 1
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    seen = {row["id"] for row in first_rows} | {row["id"] for row in second_rows}
    assert len(seen) == 3, "The two pages together cover every product exactly once"
    for row in first_rows + second_rows:
        assert row["department_id"] == department["id"]


def test_the_day_of_week_is_derived_from_the_business_date():
    """A supplied day-of-week is ignored in favour of the computed one.

    PRD §3.2: "From `business_date` the system derives `day_of_week` under the
    proleptic Gregorian calendar, as one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`
    or `SUN`."  2026-08-12 is a Wednesday however the client labels it.

    Design: Corner/entities/bake_day_day_of_week_is_computed_and_supplied_value_input_ignored
    """
    department = provision_department()
    manager = make_department_manager_headers(department["id"])
    payload = create_bake_day_payload(department["id"], day_of_week="MON")

    day = validate_success(api_client.create_bake_day(payload, manager), 201)
    assert_bake_day(day)
    assert day["business_date"] == "2026-08-12"
    assert day["day_of_week"] == "WED", (
        "The derived Wednesday must win over the smuggled Monday"
    )
    assert day["plan_posture"] == "DRAFT"
    assert day["forecast_lines"] == []
    assert day["planned_units_total"] == 0
    assert day["waste_units_total"] == 0
    assert day["markdown_authorization"] == "AUTO"
    assert day["version"] == 1


def test_a_new_pickup_window_mints_its_own_identity_and_opens_empty():
    """The client supplies the times; the server supplies everything else.

    PRD §3.7: "A new window opens with a `slot_status` of `OPEN` and
    `reserved_decoration_units` of 0."  Its id, version and audit stamps are server
    generated, and the two instants it does carry are the ones that were asked for.

    Design: Corner/entities/pickup_slot_identity_and_audit_fields_are_server_generated
    """
    setup = setup_planned_day()
    payload = create_pickup_slot_payload(
        setup["bake_day"]["id"],
        slot_start_utc="2026-08-12T14:00:00Z",
        slot_end_utc="2026-08-12T16:00:00Z",
        decorator_capacity_units=12,
    )
    payload["id"] = NON_EXISTENT_UUID
    payload["reserved_decoration_units"] = 9
    payload["slot_status"] = "CLOSED"

    window = validate_success(
        api_client.create_pickup_slot(payload, CAKE_DESK), 201
    )
    assert_pickup_slot(window)
    assert is_valid_uuid(window["id"])
    assert window["id"] != NON_EXISTENT_UUID, "The id is minted by the server"
    assert window["bake_day_id"] == setup["bake_day"]["id"]
    assert_instant(window["slot_start_utc"], "2026-08-12T14:00:00Z", "slot_start_utc")
    assert_instant(window["slot_end_utc"], "2026-08-12T16:00:00Z", "slot_end_utc")
    assert window["decorator_capacity_units"] == 12
    assert window["slot_status"] == "OPEN", "A new window always opens OPEN"
    assert window["reserved_decoration_units"] == 0
    assert window["version"] == 1


def test_out_of_range_and_off_enum_inputs_are_all_bad_requests():
    """A fifth tier, a zero-length window and an invented daypart all fail the shape band.

    PRD §3.6 bounds a cake at "a `tier_count` between 1 and 4", PRD §3.7 requires "a
    `slot_end_utc` strictly after it", and PRD §3.2 fixes the daypart: "`daypart` is
    one of `MORNING`, `MIDDAY` or `EVENING`."  All three are shape violations, so all
    three report `ERR_INVALID_REQUEST`.

    Design: Corner/entities/cake_order_and_pickup_slot_type_constraints_rejected
    """
    setup = setup_draft_day()
    day = setup["bake_day"]
    slot = open_pickup_slot(
        day, slot_start_utc="2026-08-12T14:00:00Z", slot_end_utc="2026-08-12T16:00:00Z"
    )

    five_tiers = api_client.create_cake_order(
        create_cake_order_payload(
            day["id"], slot["id"], setup["cake_base"]["id"], tier_count=5
        ),
        CAKE_DESK,
    )
    validate_error(five_tiers, "ERR_INVALID_REQUEST", 400)

    empty_window = api_client.create_pickup_slot(
        create_pickup_slot_payload(
            day["id"],
            slot_start_utc="2026-08-12T18:00:00Z",
            slot_end_utc="2026-08-12T18:00:00Z",
        ),
        CAKE_DESK,
    )
    validate_error(empty_window, "ERR_INVALID_REQUEST", 400)

    unknown_daypart = api_client.append_forecast_line(
        day["id"],
        forecast_line_payload(setup["croissant"]["id"], "AFTERNOON", 40),
        setup["manager"],
    )
    validate_error(unknown_daypart, "ERR_INVALID_REQUEST", 400)

    _, order_meta = validate_paginated(
        api_client.list_cake_orders(CAKE_DESK, {"bake_day_id": day["id"]})
    )
    assert order_meta["total_count"] == 0, "The five-tier order was never minted"
    _, slot_meta = validate_paginated(
        api_client.list_pickup_slots(CAKE_DESK, {"bake_day_id": day["id"]})
    )
    assert slot_meta["total_count"] == 1, "Only the good window exists"
    assert read_bake_day(day["id"])["forecast_lines"] == []


def test_each_read_endpoint_names_its_own_entity_when_the_id_is_unknown():
    """Ten reads, ten distinct not-found identifiers.

    PRD §2.10 band 4 resolves existence "in this fixed order: `department_id`
    (`ERR_DEPARTMENT_NOT_FOUND`), then `bake_day_id` (`ERR_BAKE_DAY_NOT_FOUND`), then
    `product_id` (`ERR_PRODUCT_NOT_FOUND`), then `ingredient_id`
    (`ERR_INGREDIENT_NOT_FOUND`), then `oven_id` (`ERR_OVEN_NOT_FOUND`), then
    `production_run_id` or `runId` (`ERR_PRODUCTION_RUN_NOT_FOUND`), then
    `pickup_slot_id` or `pickupSlotId` (`ERR_PICKUP_SLOT_NOT_FOUND`), then `orderId`
    (`ERR_CAKE_ORDER_NOT_FOUND`), then `ingredientOrderId`
    (`ERR_INGREDIENT_ORDER_NOT_FOUND`), then `wasteRecordId`
    (`ERR_WASTE_RECORD_NOT_FOUND`)", so each single-resource GET reports the entity it
    failed to find rather than a shared code.

    Design: Corner/entities/unknown_ids_on_every_read_endpoint_return_entity_specific_not_found
    """
    setup_reference_data()

    for getter, expected_error_id in (
        (api_client.get_department, "ERR_DEPARTMENT_NOT_FOUND"),
        (api_client.get_bake_day, "ERR_BAKE_DAY_NOT_FOUND"),
        (api_client.get_product, "ERR_PRODUCT_NOT_FOUND"),
        (api_client.get_ingredient, "ERR_INGREDIENT_NOT_FOUND"),
        (api_client.get_oven, "ERR_OVEN_NOT_FOUND"),
        (api_client.get_production_run, "ERR_PRODUCTION_RUN_NOT_FOUND"),
        (api_client.get_pickup_slot, "ERR_PICKUP_SLOT_NOT_FOUND"),
        (api_client.get_cake_order, "ERR_CAKE_ORDER_NOT_FOUND"),
        (api_client.get_ingredient_order, "ERR_INGREDIENT_ORDER_NOT_FOUND"),
        (api_client.get_waste_record, "ERR_WASTE_RECORD_NOT_FOUND"),
    ):
        missing = getter(NON_EXISTENT_UUID, REGIONAL_ADMIN)
        validate_error(missing, expected_error_id, 404)


def test_forecasting_another_departments_product_is_refused_at_the_referential_band():
    """An unknown product is a 404; a real product in the wrong store is a 422.

    PRD §3.2: "A `product_id` naming nothing is rejected with
    `ERR_PRODUCT_NOT_FOUND`; one naming a product owned by a different department is
    rejected with `ERR_INGREDIENT_NOT_IN_DEPARTMENT`."  Existence is band 4 and the
    referential check is band 12, so the two failures are reported differently.

    Design: Corner/entities/forecast_line_naming_a_product_of_another_department_returns_not_found
    """
    setup = setup_draft_day()
    day = setup["bake_day"]
    other_department = provision_second_department()
    foreign_product = provision_product(create_product_payload(other_department["id"]))

    unknown = api_client.append_forecast_line(
        day["id"],
        forecast_line_payload(NON_EXISTENT_UUID, "MORNING", 40),
        setup["manager"],
    )
    validate_error(unknown, "ERR_PRODUCT_NOT_FOUND", 404)

    trespassing = api_client.append_forecast_line(
        day["id"],
        forecast_line_payload(foreign_product["id"], "MORNING", 40),
        setup["manager"],
    )
    validate_error(trespassing, "ERR_INGREDIENT_NOT_IN_DEPARTMENT", 422)

    assert read_bake_day(day["id"])["forecast_lines"] == []

    own = validate_success(
        api_client.append_forecast_line(
            day["id"],
            forecast_line_payload(setup["croissant"]["id"], "MORNING", 40),
            setup["manager"],
        ),
        200,
    )
    assert len(own["forecast_lines"]) == 1
    assert own["forecast_lines"][0]["product_id"] == setup["croissant"]["id"]


def test_attesting_waste_against_an_unknown_batch_is_a_not_found():
    """The run behind a waste record is resolved on the write, before any costing.

    PRD §2.10 band 4 resolves "`production_run_id` or `runId`
    (`ERR_PRODUCTION_RUN_NOT_FOUND`)", and "Within this band, path variables resolve
    before body identifiers" — all of it long before the §3.6 shrink recomputation, so
    a record naming a batch that was never scheduled books nothing at all.

    Design: Corner/entities/waste_record_against_an_unknown_production_run_returns_not_found
    """
    setup = setup_planned_day()

    orphan = api_client.create_waste_record(
        create_waste_record_payload(NON_EXISTENT_UUID, 5, "DAMAGED"), BAKER
    )
    validate_error(orphan, "ERR_PRODUCTION_RUN_NOT_FOUND", 404)

    _, meta = validate_paginated(
        api_client.list_waste_records(
            REGIONAL_ADMIN, {"bake_day_id": setup["bake_day"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "No record was booked against the unknown batch"

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["waste_units_total"] == 0
    assert day["shrink_cost_cents"] == 0


def test_an_oven_cannot_go_into_maintenance_under_a_loaded_deck():
    """The guard is directional: a live batch blocks the toggle, then the toggle blocks new batches.

    PRD §3.1: "Moving `AVAILABLE → MAINTENANCE` is refused with
    `ERR_INVALID_RUN_STATE` while any production run referencing that oven is in
    `PROOFING` or `BAKING`", and "Once the oven reads `MAINTENANCE`, every run write
    that names it is rejected with `ERR_OVEN_UNAVAILABLE`; runs already sitting in
    `SCHEDULED` are deliberately left in place rather than cancelled".

    Design: Corner/endpoints/oven_maintenance_toggle_is_blocked_by_live_runs_then_blocks_new_ones
    """
    setup = setup_planned_day(clock="2026-08-12T04:00:00Z")
    oven = setup["oven"]
    manager = setup["manager"]
    loaded = drive_run_to_baking(schedule_par_baked_run(setup), "PAR_BAKED")
    assert loaded["execution_status"] == "BAKING"
    standing = schedule_par_baked_run(setup, bake_start_utc="2026-08-12T06:00:00Z")
    assert standing["execution_status"] == "SCHEDULED"

    blocked = api_client.set_oven_status(
        oven["id"], oven_status_payload("MAINTENANCE", "Deck seal"), manager
    )
    validate_error(blocked, "ERR_INVALID_RUN_STATE", 409)
    still_available = read_oven(oven["id"])
    assert still_available["oven_status"] == "AVAILABLE"
    assert still_available["version"] == oven["version"], (
        "A refused toggle may not advance the oven's version"
    )

    complete_run(loaded, 80)
    pulled = set_oven_status(oven["id"], setup["department"], "MAINTENANCE", "Deck seal")
    assert pulled["oven_status"] == "MAINTENANCE"
    assert pulled["status_reason"] == "Deck seal"
    assert pulled["version"] == oven["version"] + 1

    refused_new = api_client.create_production_run(
        create_production_run_payload(
            setup["bake_day"]["id"],
            setup["croissant"]["id"],
            rack_count=2,
            oven_id=oven["id"],
            deck_index=1,
            bake_start_utc="2026-08-12T08:00:00Z",
        ),
        BAKER,
    )
    validate_error(refused_new, "ERR_OVEN_UNAVAILABLE", 409)

    refused_load = api_client.start_bake(standing["id"], BAKER)
    validate_error(refused_load, "ERR_OVEN_UNAVAILABLE", 409)
    assert read_run(standing["id"])["execution_status"] == "SCHEDULED", (
        "The standing batch is blocked at the deck, not cancelled"
    )

    returned = set_oven_status(oven["id"], setup["department"], "AVAILABLE", "Reseated")
    assert returned["oven_status"] == "AVAILABLE"
    assert returned["version"] == oven["version"] + 2
    resumed = validate_success(api_client.start_bake(standing["id"], BAKER), 200)
    assert resumed["execution_status"] == "BAKING"
