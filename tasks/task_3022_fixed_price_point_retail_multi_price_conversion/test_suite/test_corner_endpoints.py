"""Guarded writes, derived reads and batch actions on the conversion surface."""


from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    E,
    SOM_HEADERS,
    factories,
    validate_error,
    validate_success,
    fixtures,
)

OCC_QUOTE = (
    "A conversion project created against a store must supply `expected_store_version`, and a "
    "conversion project adjusted after creation must supply `expected_store_version` as well."
)
OCC_REJECT_QUOTE = (
    "If the store's version has advanced since that observation — because the store's "
    "price-point binding moved, because one of its conversion artefact flags was filed, because "
    "`conversion_price_point_id` was set or cleared, or because an aisle reset began under it — "
    "the request is rejected with `ERR_STALE_VERSION` and HTTP 412."
)
OCC_VERSION_BUMP_QUOTE = (
    "When a project is created it begins `DRAFT` and the store's `version` is incremented by one."
)
PATCH_BUMP_QUOTE = (
    "It carries the new `to_price_point_id` and `expected_store_version`, updates the "
    "destination, and increments the store's `version` by one when accepted; a stale token is "
    "rejected with `ERR_STALE_VERSION` and HTTP 412 for the same reason as at creation, because "
    "the completion gate reads the store's artefact flags and those flags are only meaningful "
    "against the observed store version."
)
COVERAGE_READ_QUOTE = (
    "The same aggregate is exposed for reading on the project alongside `completed_aisle_count`, "
    "`projected_convertible_aisle_count`, `adjusted_baseline`, `coverage_delta_pct` and the "
    "boolean `shortfall`."
)
BATCH_QUOTE = (
    "Every item in the batch must currently sit at the batch's own source price point: an item "
    "whose current `price_point_id` differs from the batch's `from_price_point_id` is rejected "
    "with `ERR_ITEM_NOT_AT_SOURCE_PRICE_POINT` and HTTP 409."
)
BATCH_RESULT_QUOTE = (
    "The batch answers with the `store_id`, an `issued_item_count`, the `to_price_point_id`, and "
    "a `rejected_item_ids` array identifying the items that could not be issued, and it opens a "
    "conversion project whose source is set to the request's `from_price_point_id`."
)


def _converting_store_with_project(api):
    """An ACTIVE pair of price points, a CONVERTING store and a started project."""
    fixtures.set_clock()
    origin = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    target = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR_25")
    store = fixtures.create_store()
    began = validate_success(api.begin_conversion(store["id"], target["id"], SOM_HEADERS), 200)
    project = validate_success(fixtures.open_conversion_project(
        store["id"], origin["id"], target["id"], expected_store_version=began["version"]), 201)
    validate_success(fixtures.api_client.start_conversion_project(project["id"], SOM_HEADERS), 200)
    return origin, target, store, began, project


def test_a_replayed_store_version_token_is_rejected_after_the_create_advanced_it(api):
    """The guarded create advances the store version, so its own token is stale on replay.

    PRD §2.7: "A conversion project created against a store must supply `expected_store_version`,
    and a conversion project adjusted after creation must supply `expected_store_version` as well."
    PRD §2.7: "If the store's version has advanced since that observation — because the store's
    price-point binding moved, because one of its conversion artefact flags was filed, because
    `conversion_price_point_id` was set or cleared, or because an aisle reset began under it — the
    request is rejected with `ERR_STALE_VERSION` and HTTP 412."
    PRD §3.8: "When a project is created it begins `DRAFT` and the store's `version` is
    incremented by one."

    Design: Corner/endpoints/conversion_project_create_increments_the_store_version_under_occ
    """
    origin, target, store, began, _ = _converting_store_with_project(api)
    store_now = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    observed = store_now["version"]

    projects_before = validate_success(
        api.list_store_conversion_projects(store["id"], ANALYST_HEADERS), 200)

    first = validate_success(
        fixtures.open_conversion_project(store["id"], origin["id"], target["id"],
                                         expected_store_version=observed),
        201,
    )
    assert first["status"] == "DRAFT"

    replayed = fixtures.open_conversion_project(
        store["id"], origin["id"], target["id"], expected_store_version=observed)
    validate_error(replayed, E.ERR_STALE_VERSION.value)

    store_after = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert store_after["version"] > observed, "the successful create advanced the store version"

    projects_after = validate_success(
        api.list_store_conversion_projects(store["id"], ANALYST_HEADERS), 200)
    assert len(projects_after) == len(projects_before) + 1, "the loser persisted nothing"


def test_a_stale_patch_token_is_refused_and_a_fresh_one_succeeds(api):
    """PATCH is the second guarded write, and it advances the store version too.

    PRD §2.7: "A conversion project created against a store must supply `expected_store_version`,
    and a conversion project adjusted after creation must supply `expected_store_version` as well."
    PRD §3.8: "It carries the new `to_price_point_id` and `expected_store_version`, updates the
    destination, and increments the store's `version` by one when accepted; a stale token is
    rejected with `ERR_STALE_VERSION` and HTTP 412 for the same reason as at creation, because the
    completion gate reads the store's artefact flags and those flags are only meaningful against
    the observed store version."

    Design: Corner/errors/error_stale_version_is_412_on_a_superseded_store_token
    """
    origin, target, store, began, project = _converting_store_with_project(api)

    stale = api.patch_conversion_project(
        project["id"],
        {"to_price_point_id": target["id"], "expected_store_version": began["version"]},
        SOM_HEADERS,
    )
    validate_error(stale, E.ERR_STALE_VERSION.value)

    fresh_store = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    # The adjustment must name a destination different from the project's source;
    # `origin` is the source, so the distinguishing move here is a no-op-in-value
    # second price point that still differs from the source.
    third = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR_25")
    patched = validate_success(
        api.patch_conversion_project(
            project["id"],
            {"to_price_point_id": third["id"], "expected_store_version": fresh_store["version"]},
            SOM_HEADERS),
        200,
    )
    assert patched["to_price_point_id"] == third["id"]

    after = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert after["version"] > fresh_store["version"], "the accepted patch advanced the store again"
    assert patched["status"] == "IN_PROGRESS", (
        "the guarded adjustment never changed the project's lifecycle"
    )


def test_the_coverage_read_is_recomputed_on_every_call(api):
    """Executing one more reset changes the derived projection with no write to the project.

    PRD §3.8: "A shortfall is declared exactly when the rounded delta is below negative one half,
    and the same aggregate is exposed for reading on the project alongside `completed_aisle_count`,
    `projected_convertible_aisle_count`, `adjusted_baseline`, `coverage_delta_pct` and the boolean
    `shortfall`."
    PRD §2.8: "The rejection carries an HTTP 404 and an error id specific to the resource type
    that failed"
    PRD §3.10: "A reset moves from `PLANNED` to `EXECUTING` only when three conditions hold
    together: the reset is currently `PLANNED`, otherwise `ERR_AISLE_RESET_NOT_PLANNED`; its
    season window is `OPEN`, otherwise `ERR_SEASON_WINDOW_NOT_OPEN`; and the logical clock has
    reached the reset's `starts_at`, otherwise `ERR_RESET_OUTSIDE_CALENDAR`."

    Design: Corner/endpoints/coverage_read_returns_the_computed_shortfall_projection
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    target = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store(shelf_facing_capacity_sqft=400.0)
    window = fixtures.create_open_season_window()
    # Executing a reset requires at least one ACTIVE item resting on the reset's own
    # price point (PRD §3.10), so the target point carries an ACTIVE item throughout.
    fixtures.create_active_item(target["id"], vendor["id"], sku="4001",
                                unit_retail_cents=300, base_landed_cost_cents=264)
    state = fixtures.conversion_in_progress(store["id"], price_point["id"], target["id"])

    missing = api.get_project_coverage(
        "00000000-0000-4000-8000-000000000000", SOM_HEADERS)
    validate_error(missing, E.ERR_CONVERSION_PROJECT_NOT_FOUND.value)

    plan = dict(store_id=store["id"], price_point_id=target["id"],
                season_window_id=window["id"], starts_at="2026-09-01T00:00:00Z",
                ends_at="2026-09-06T00:00:00Z", allocated_shelf_sqft=50.0)
    first = fixtures.plan_reset_ok(aisle_code="A11", **plan)
    fixtures.plan_reset_ok(aisle_code="A12", **plan)

    before = validate_success(api.get_project_coverage(state["conversion_id"], SOM_HEADERS), 200)
    assert before["completed_aisle_count"] == 0
    assert before["projected_convertible_aisle_count"] == 2
    assert before["coverage_delta_pct"] == -1.000
    assert before["shortfall"] is True

    validate_success(fixtures.begin_reset(first["id"]), 200)
    fixtures.execute_reset(first["id"])

    after = validate_success(api.get_project_coverage(state["conversion_id"], SOM_HEADERS), 200)
    assert after["completed_aisle_count"] == 1
    assert after["projected_convertible_aisle_count"] == 1
    assert after["coverage_delta_pct"] == 0.000
    assert after["shortfall"] is False

    resets = validate_success(api.list_store_aisle_resets(store["id"], ANALYST_HEADERS), 200)
    assert sorted(row["status"] for row in resets) == ["EXECUTED", "PLANNED"]


def test_a_multi_price_batch_rejects_items_foreign_to_its_source_point(api):
    """The batch issues only items resting at its own source point and reports the count.

    PRD §3.8: "Every item in the batch must currently sit at the batch's own source price point:
    an item whose current `price_point_id` differs from the batch's `from_price_point_id` is
    rejected with `ERR_ITEM_NOT_AT_SOURCE_PRICE_POINT` and HTTP 409."
    PRD §3.8: "The batch answers with the `store_id`, an `issued_item_count`, the
    `to_price_point_id`, and a `rejected_item_ids` array identifying the items that could not be
    issued, and it opens a conversion project whose source is set to the request's
    `from_price_point_id`."

    Design: Corner/endpoints/multi_price_issues_rejects_items_foreign_to_the_store_price_point
    """
    fixtures.set_clock()
    origin = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    target = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    validate_success(api.begin_conversion(store["id"], target["id"], SOM_HEADERS), 200)

    at_origin = fixtures.create_price_assigned_item(
        origin["id"], vendor["id"], sku="1001", unit_retail_cents=125, base_landed_cost_cents=105)
    at_target = fixtures.create_price_assigned_item(
        target["id"], vendor["id"], sku="1002", unit_retail_cents=300, base_landed_cost_cents=264)

    foreign = api.create_multi_price_issue(
        factories.create_multi_price_issue_payload(
            store["id"], origin["id"], [at_target["id"]], target["id"]),
        BUYER_HEADERS,
    )
    validate_error(foreign, E.ERR_ITEM_NOT_AT_SOURCE_PRICE_POINT.value)

    issued = validate_success(
        api.create_multi_price_issue(
            factories.create_multi_price_issue_payload(
                store["id"], origin["id"], [at_origin["id"]], target["id"]),
            BUYER_HEADERS),
        201,
    )
    assert issued["issued_item_count"] == 1
    assert issued["to_price_point_id"] == target["id"]
    assert issued["rejected_item_ids"] == []

    read = validate_success(api.get_item(at_origin["id"], ANALYST_HEADERS), 200)
    assert read["price_point_id"] == origin["id"], (
        "the batch records the issue; it does not rebind the item"
    )