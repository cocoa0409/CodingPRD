"""Prep-list generation: dual variants, pinned rounding order, cross-entity
forecast gate, and OCC on regeneration."""

import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, create_restaurant, create_manager, create_cook,
    create_prep_item, create_menu_revision_with_recipes,
    create_forecast, create_finalized_forecast, finalize_forecast,
    create_prep_list_payload, create_locked_prep_list,
    make_kitchen_manager_headers, menu_admin_headers, find_line,
)


def _variant_setup(api, shelf_life_hours=48, quantity_per_portion=3,
                   expected_count=100, item_name="Diced Onions"):
    """Restaurant + manager + prep item + DRAFT revision recipe + FINALIZED
    forecast + DRAFT prep list.  Returns the context dict."""
    set_clock("2026-09-01T00:00:00Z")
    rest = create_restaurant()
    mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
    mh = make_kitchen_manager_headers(mgr["id"])
    item = create_prep_item(name=item_name, station_type="SAUTE",
                            shelf_life_hours=shelf_life_hours,
                            min_batch_size=10, batch_unit="OZ")
    revision, recipes = create_menu_revision_with_recipes(
        rest["id"],
        [{"name": "Pasta A", "station_type": "SAUTE",
          "components": [{"prep_item_id": item["id"],
                          "quantity_per_portion": quantity_per_portion,
                          "unit": "OZ"}]}],
        label="2026-Fall", effective_from="2026-09-15T00:00:00Z")
    forecast = create_finalized_forecast(
        rest["id"], mgr["id"],
        [{"recipe_id": recipes["Pasta A"]["id"],
          "expected_count": expected_count}])
    prep_list = validate_success(api.create_prep_list(
        create_prep_list_payload(rest["id"], forecast["id"]), mh), 201)
    return {"rest": rest, "mgr": mgr, "mh": mh, "item": item,
            "recipe": recipes["Pasta A"], "forecast": forecast,
            "prep_list": prep_list}


class TestDualVariantPrepQuantity:
    def test_optimistic_generation_line_math(self, api):
        """PRD section 3.4: "Under the `OPTIMISTIC` variant, each surviving
        item's buffered quantity is its raw quantity increased by five
        percent. The batch count is the buffered quantity divided by the
        item's `min_batch_size`, rounded up to a whole number, and the line's
        rounded quantity is that batch count multiplied back by
        `min_batch_size` — always a full-batch multiple, with no shelf-life
        cap applied, so the line's `capped_by_shelf_life` flag reads false."

        Design: Difficulty/dual_variant_calc/prep_quantity_optimistic_vs_conservative_variants
        """
        ctx = _variant_setup(api)
        pl, mh, item = ctx["prep_list"], ctx["mh"], ctx["item"]
        generated = validate_success(api.generate_prep_list(
            pl["id"], {"generation_variant": "OPTIMISTIC"}, mh))
        line = find_line(generated, item["id"])
        assert line["raw_quantity"] == 300
        assert line["buffered_quantity"] == pytest.approx(315)
        assert line["batch_count"] == 32
        assert line["rounded_quantity"] == 320
        assert line["capped_by_shelf_life"] is False
        assert generated["total_rounded_quantity"] == 320
        assert generated["generation_variant"] == "OPTIMISTIC"

    def test_conservative_regeneration_diverges_with_cap(self, api):
        """PRD section 3.4: "Under the `CONSERVATIVE` variant, the buffered
        quantity is instead the raw quantity increased by fifteen percent."
        and "The cap is the raw quantity multiplied by this cover factor,
        divided by `min_batch_size`, rounded down to a whole number, and
        multiplied back by `min_batch_size`. The line's rounded quantity is
        then the smaller of the usual round-up of the buffered quantity to a
        full batch and this cap. The line's `capped_by_shelf_life` flag is
        true exactly when the capped result is smaller than the uncapped
        round-up of the buffered quantity would have been."

        Design: Difficulty/dual_variant_calc/prep_quantity_optimistic_vs_conservative_variants
        """
        ctx = _variant_setup(api)
        pl, mh, item = ctx["prep_list"], ctx["mh"], ctx["item"]
        generated = validate_success(api.generate_prep_list(
            pl["id"], {"generation_variant": "OPTIMISTIC"}, mh))
        regenerated = validate_success(api.regenerate_prep_list(
            pl["id"],
            {"generation_variant": "CONSERVATIVE",
             "expected_prep_list_version": generated["version"]}, mh))
        line = find_line(regenerated, item["id"])
        assert line["raw_quantity"] == 300
        assert line["buffered_quantity"] == pytest.approx(345)
        assert line["rounded_quantity"] == 300
        assert line["capped_by_shelf_life"] is True
        assert regenerated["total_rounded_quantity"] == 300
        assert regenerated["generation_variant"] == "CONSERVATIVE"

    def test_variants_diverge_for_identical_forecast(self, api):
        """PRD section 3.4: "The generation request names a
        `generation_variant` of `OPTIMISTIC` or `CONSERVATIVE`, and that
        choice is recorded on the list."  Same forecast, same components:
        OPTIMISTIC totals 320, CONSERVATIVE totals 300.

        Design: Difficulty/dual_variant_calc/prep_quantity_optimistic_vs_conservative_variants
        """
        ctx = _variant_setup(api)
        pl, mh = ctx["prep_list"], ctx["mh"]
        generated = validate_success(api.generate_prep_list(
            pl["id"], {"generation_variant": "OPTIMISTIC"}, mh))
        assert generated["total_rounded_quantity"] == 320
        regenerated = validate_success(api.regenerate_prep_list(
            pl["id"],
            {"generation_variant": "CONSERVATIVE",
             "expected_prep_list_version": generated["version"]}, mh))
        assert regenerated["total_rounded_quantity"] == 300
        assert (generated["total_rounded_quantity"]
                != regenerated["total_rounded_quantity"])


class TestPinnedRoundingOrder:
    def _rounding_setup(self, api):
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
        mh = make_kitchen_manager_headers(mgr["id"])
        item_a = create_prep_item(name="Item A", station_type="SAUTE",
                                  shelf_life_hours=48, min_batch_size=10,
                                  batch_unit="OZ")
        item_b = create_prep_item(name="Item B", station_type="SAUTE",
                                  shelf_life_hours=48, min_batch_size=10,
                                  batch_unit="OZ")
        revision, recipes = create_menu_revision_with_recipes(
            rest["id"],
            [{"name": "RA", "station_type": "SAUTE",
              "components": [{"prep_item_id": item_a["id"],
                              "quantity_per_portion": 11, "unit": "OZ"}]},
             {"name": "RB", "station_type": "SAUTE",
              "components": [{"prep_item_id": item_b["id"],
                              "quantity_per_portion": 13, "unit": "OZ"}]}],
            label="2026-Fall", effective_from="2026-09-15T00:00:00Z")
        forecast = create_finalized_forecast(
            rest["id"], mgr["id"],
            [{"recipe_id": recipes["RA"]["id"], "expected_count": 1},
             {"recipe_id": recipes["RB"]["id"], "expected_count": 1}],
            expected_covers=10)
        prep_list = validate_success(api.create_prep_list(
            create_prep_list_payload(rest["id"], forecast["id"]), mh), 201)
        return mh, item_a, item_b, prep_list

    def test_per_line_round_then_sum(self, api):
        """PRD section 2.7: "Rounding order inside prep-list generation is
        pinned and non-negotiable: each line is rounded up to its own batch
        granularity first, and only then are the per-line rounded quantities
        summed. Summing raw or buffered quantities across lines and rounding
        once at the end is forbidden, because batch granularity differs per
        item and the two orders yield different totals."

        Design: Difficulty/combinatorial_formula/per_line_round_then_sum_mode_b
        """
        mh, item_a, item_b, prep_list = self._rounding_setup(api)
        generated = validate_success(api.generate_prep_list(
            prep_list["id"], {"generation_variant": "OPTIMISTIC"}, mh))
        line_a = find_line(generated, item_a["id"])
        line_b = find_line(generated, item_b["id"])
        assert line_a["raw_quantity"] == 11
        assert line_a["buffered_quantity"] == pytest.approx(11.55)
        assert line_a["batch_count"] == 2
        assert line_a["rounded_quantity"] == 20
        assert line_b["raw_quantity"] == 13
        assert line_b["buffered_quantity"] == pytest.approx(13.65)
        assert line_b["batch_count"] == 2
        assert line_b["rounded_quantity"] == 20
        # Per-line round then sum: 20 + 20 == 40; the forbidden
        # sum-then-round would have produced 30.
        assert generated["total_rounded_quantity"] == 40

    def test_total_is_sum_of_rounded_lines_not_rounded_total(self, api):
        """PRD section 3.4: "The list's `total_rounded_quantity` is the sum
        of the per-line rounded quantities — and, per the pinned rounding
        discipline of §2.7, each line is rounded up to its own batch multiple
        first and only then summed; the system never sums raw quantities and
        rounds once at the end."

        Design: Difficulty/combinatorial_formula/per_line_round_then_sum_mode_b
        """
        mh, item_a, item_b, prep_list = self._rounding_setup(api)
        generated = validate_success(api.generate_prep_list(
            prep_list["id"], {"generation_variant": "OPTIMISTIC"}, mh))
        per_line = sum(l["rounded_quantity"] for l in generated["lines"])
        assert generated["total_rounded_quantity"] == per_line == 40
        assert generated["total_rounded_quantity"] != 30


class TestConservativeShelfLifeCap:
    def _cap_setup(self, api):
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
        mh = make_kitchen_manager_headers(mgr["id"])
        item = create_prep_item(name="P6", station_type="SAUTE",
                                shelf_life_hours=6, min_batch_size=10,
                                batch_unit="OZ")
        revision, recipes = create_menu_revision_with_recipes(
            rest["id"],
            [{"name": "R6", "station_type": "SAUTE",
              "components": [{"prep_item_id": item["id"],
                              "quantity_per_portion": 10, "unit": "OZ"}]}],
            label="V1", effective_from="2026-09-15T00:00:00Z")
        forecast = create_finalized_forecast(
            rest["id"], mgr["id"],
            [{"recipe_id": recipes["R6"]["id"], "expected_count": 10}],
            expected_covers=10)
        prep_list = validate_success(api.create_prep_list(
            create_prep_list_payload(rest["id"], forecast["id"]), mh), 201)
        return mh, item, prep_list

    def test_optimistic_uncapped_for_short_shelf_life(self, api):
        """PRD section 3.4: "Under the `OPTIMISTIC` variant, each surviving
        item's buffered quantity is its raw quantity increased by five
        percent. The batch count is the buffered quantity divided by the
        item's `min_batch_size`, rounded up to a whole number, and the line's
        rounded quantity is that batch count multiplied back by
        `min_batch_size` — always a full-batch multiple, with no shelf-life
        cap applied, so the line's `capped_by_shelf_life` flag reads false."

        Design: Corner/calculations/conservative_cap_below_raw_for_short_shelf_life
        """
        mh, item, prep_list = self._cap_setup(api)
        generated = validate_success(api.generate_prep_list(
            prep_list["id"], {"generation_variant": "OPTIMISTIC"}, mh))
        line = find_line(generated, item["id"])
        assert line["raw_quantity"] == 100
        assert line["rounded_quantity"] == 110
        assert line["capped_by_shelf_life"] is False

    def test_conservative_cap_binds_below_raw_for_short_shelf_life(self, api):
        """PRD section 3.4: "A cover factor is computed as the smaller of one
        and the item's `shelf_life_hours` divided by the twelve-hour service
        window — in other words, an item whose shelf life meets or exceeds
        the full service window is uncapped, while a shorter-lived item may
        only prep the fraction of the forecast it could plausibly sell
        through within one window."

        Design: Corner/calculations/conservative_cap_below_raw_for_short_shelf_life
        """
        mh, item, prep_list = self._cap_setup(api)
        generated = validate_success(api.generate_prep_list(
            prep_list["id"], {"generation_variant": "OPTIMISTIC"}, mh))
        regenerated = validate_success(api.regenerate_prep_list(
            prep_list["id"],
            {"generation_variant": "CONSERVATIVE",
             "expected_prep_list_version": generated["version"]}, mh))
        line = find_line(regenerated, item["id"])
        # cap = floor(100 * (6/12) / 10) * 10 = 50; binds below
        # ceil(115/10) * 10 = 120.
        assert line["rounded_quantity"] == 50
        assert line["capped_by_shelf_life"] is True
        assert regenerated["total_rounded_quantity"] == 50


class TestGenerateCrossEntityGate:
    def _submitted_not_finalized_setup(self, api):
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
        mh = make_kitchen_manager_headers(mgr["id"])
        item = create_prep_item(name="Onions", station_type="SAUTE",
                                shelf_life_hours=48, min_batch_size=10,
                                batch_unit="OZ")
        revision, recipes = create_menu_revision_with_recipes(
            rest["id"],
            [{"name": "Pasta A", "station_type": "SAUTE",
              "components": [{"prep_item_id": item["id"],
                              "quantity_per_portion": 3, "unit": "OZ"}]}],
            label="V1", effective_from="2026-09-15T00:00:00Z")
        forecast = create_forecast(
            rest["id"], mgr["id"],
            [{"recipe_id": recipes["Pasta A"]["id"], "expected_count": 100}])
        get_success_data(api.submit_forecast(forecast["id"], mh))
        prep_list = validate_success(api.create_prep_list(
            create_prep_list_payload(rest["id"], forecast["id"]), mh), 201)
        return mh, forecast, prep_list

    def test_generate_with_submitted_forecast_rejected(self, api):
        """PRD section 3.4: "It requires the list to be `DRAFT` (otherwise
        `ERR_PREP_LIST_NOT_DRAFT`) and the referenced forecast to be
        `FINALIZED` — a cross-entity state dependency that rejects generation
        against a merely submitted or drafted forecast with
        `ERR_FORECAST_NOT_FINALIZED`."

        Design: Difficulty/cross_entity_state_dependency/prep_list_generate_requires_finalized_forecast
        """
        mh, forecast, prep_list = self._submitted_not_finalized_setup(api)
        resp = api.generate_prep_list(
            prep_list["id"], {"generation_variant": "OPTIMISTIC"}, mh)
        validate_error(resp, ApiErrorId.ERR_FORECAST_NOT_FINALIZED, 409)
        now = validate_success(api.get_prep_list(prep_list["id"], mh))
        assert now["status"] == "DRAFT"
        assert now["lines"] == []
        assert now["total_rounded_quantity"] == 0

    def test_generate_with_draft_forecast_rejected(self, api):
        """PRD section 3.4: "It requires the list to be `DRAFT` (otherwise
        `ERR_PREP_LIST_NOT_DRAFT`) and the referenced forecast to be
        `FINALIZED` — a cross-entity state dependency that rejects generation
        against a merely submitted or drafted forecast with
        `ERR_FORECAST_NOT_FINALIZED`."

        Design: Difficulty/cross_entity_state_dependency/prep_list_generate_requires_finalized_forecast
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
        mh = make_kitchen_manager_headers(mgr["id"])
        forecast = create_forecast(rest["id"], mgr["id"], [])
        prep_list = validate_success(api.create_prep_list(
            create_prep_list_payload(rest["id"], forecast["id"]), mh), 201)
        resp = api.generate_prep_list(
            prep_list["id"], {"generation_variant": "OPTIMISTIC"}, mh)
        validate_error(resp, ApiErrorId.ERR_FORECAST_NOT_FINALIZED, 409)
        now = validate_success(api.get_prep_list(prep_list["id"], mh))
        assert now["status"] == "DRAFT"


class TestRegenerateOcc:
    def _generated_list_setup(self, api):
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
        mh = make_kitchen_manager_headers(mgr["id"])
        item = create_prep_item(name="P", station_type="SAUTE",
                                shelf_life_hours=48, min_batch_size=10,
                                batch_unit="OZ")
        revision, recipes = create_menu_revision_with_recipes(
            rest["id"],
            [{"name": "R", "station_type": "SAUTE",
              "components": [{"prep_item_id": item["id"],
                              "quantity_per_portion": 3, "unit": "OZ"}]}],
            label="V1", effective_from="2026-09-15T00:00:00Z")
        forecast = create_finalized_forecast(
            rest["id"], mgr["id"],
            [{"recipe_id": recipes["R"]["id"], "expected_count": 100}])
        created = validate_success(api.create_prep_list(
            create_prep_list_payload(rest["id"], forecast["id"]), mh), 201)
        generated = validate_success(api.generate_prep_list(
            created["id"], {"generation_variant": "OPTIMISTIC"}, mh))
        return mh, created, generated

    def test_stale_version_regenerate_rejected(self, api):
        """PRD section 2.8: "Regenerating a prep list requires the request to
        carry `expected_prep_list_version` holding the client-observed
        `version` of the target prep list; if that value no longer equals the
        list's current `version` — because another legitimate write, such as
        a lock or a prior regeneration that replaced the line set, has
        advanced the version since the client last read it — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client
        from overwriting a line set it has not observed."

        Design: Corner/cross_cutting_complexity_layers/occ_prep_list_regenerate_stale_version
        """
        mh, created, generated = self._generated_list_setup(api)
        resp = api.regenerate_prep_list(
            created["id"],
            {"generation_variant": "CONSERVATIVE",
             "expected_prep_list_version": created["version"]}, mh)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_current_version_regenerate_succeeds_and_advances_version(self, api):
        """PRD section 2.5: "`version` (integer): a system-managed integer
        that increments with every mutation of the resource, and which serves
        as the basis for optimistic concurrency control."
        PRD section 3.4: "Regeneration first cancels every child batch still
        in `PLANNED`, releasing its rack load, then re-runs the full quantity
        computation with the new variant, replacing `lines`,
        `total_rounded_quantity`, and `generation_variant`, and advances the
        list's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_prep_list_regenerate_stale_version
        """
        mh, created, generated = self._generated_list_setup(api)
        regenerated = validate_success(api.regenerate_prep_list(
            created["id"],
            {"generation_variant": "CONSERVATIVE",
             "expected_prep_list_version": generated["version"]}, mh))
        assert regenerated["generation_variant"] == "CONSERVATIVE"
        assert regenerated["version"] == generated["version"] + 1
        assert generated["version"] > created["version"]


class TestRegenerateOnDraftList:
    def test_regenerate_on_draft_prep_list_rejected(self, api):
        """PRD section 3.4: "A generated list can be regenerated, from either
        `GENERATED` or `LOCKED`, to reflect a corrected forecast reading or a
        change of heart on the variant; regeneration against a list in any
        other state is rejected with `ERR_PREP_LIST_NOT_REGENERABLE`."

        Design: Corner/errors/regenerate_on_draft_prep_list_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
        mh = make_kitchen_manager_headers(mgr["id"])
        forecast = create_finalized_forecast(rest["id"], mgr["id"], [],
                                             expected_covers=10)
        prep_list = validate_success(api.create_prep_list(
            create_prep_list_payload(rest["id"], forecast["id"]), mh), 201)
        resp = api.regenerate_prep_list(
            prep_list["id"],
            {"generation_variant": "OPTIMISTIC",
             "expected_prep_list_version": prep_list["version"]}, mh)
        validate_error(resp, ApiErrorId.ERR_PREP_LIST_NOT_REGENERABLE, 409)
        now = validate_success(api.get_prep_list(prep_list["id"], mh))
        assert now["status"] == "DRAFT"


class TestPrepListFiltering:
    def test_prep_list_filter_by_forecast_and_status(self, api):
        """PRD section 3.4: "Prep lists may be listed filtered by
        `restaurant_id`, `demand_forecast_id`, or `status`, and the terminal
        states of the machine are `COMPLETED` and `SUPERSEDED`."

        Design: Corner/endpoints/prep_list_filter_by_forecast_and_status
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
        mh = make_kitchen_manager_headers(mgr["id"])
        item = create_prep_item(name="P", station_type="SAUTE",
                                shelf_life_hours=48, min_batch_size=10,
                                batch_unit="OZ")
        revision, recipes = create_menu_revision_with_recipes(
            rest["id"],
            [{"name": "R", "station_type": "SAUTE",
              "components": [{"prep_item_id": item["id"],
                              "quantity_per_portion": 3, "unit": "OZ"}]}],
            label="V1", effective_from="2026-09-15T00:00:00Z", publish=True)
        fc1 = create_finalized_forecast(
            rest["id"], mgr["id"],
            [{"recipe_id": recipes["R"]["id"], "expected_count": 10}],
            expected_covers=10)
        fc2 = create_forecast(
            rest["id"], mgr["id"],
            [{"recipe_id": recipes["R"]["id"], "expected_count": 10}],
            service_date="2026-09-03T00:00:00Z", expected_covers=10)
        pl1 = validate_success(api.create_prep_list(
            create_prep_list_payload(rest["id"], fc1["id"]), mh), 201)
        validate_success(api.generate_prep_list(
            pl1["id"], {"generation_variant": "OPTIMISTIC"}, mh))
        pl2 = validate_success(api.create_prep_list(
            create_prep_list_payload(rest["id"], fc2["id"]), mh), 201)

        data, meta = validate_paginated(
            api.list_prep_lists(mh, params={"demand_forecast_id": fc1["id"],
                                            "status": "GENERATED"}))
        assert len(data) == 1 and data[0]["id"] == pl1["id"]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

        data2, meta2 = validate_paginated(
            api.list_prep_lists(mh, params={"demand_forecast_id": fc1["id"],
                                            "status": "LOCKED"}))
        assert data2 == []
        assert meta2["total_count"] == 0
        assert meta2["has_more"] is False

        data3, meta3 = validate_paginated(
            api.list_prep_lists(mh, params={"restaurant_id": rest["id"]}))
        assert len(data3) == 2
