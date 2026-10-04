"""Menu revision review loop and the publish cascade."""

from test_helpers import (
    validate_success, get_success_data,
    set_clock, create_restaurant, create_manager, create_cook,
    create_prep_item, create_menu_revision_with_recipes, publish_menu_revision,
    create_station, create_station_par, create_finalized_forecast,
    create_prep_list_payload, create_prep_batch, create_locked_prep_list,
    make_kitchen_manager_headers, make_prep_cook_headers, menu_admin_headers,
)


class TestMenuRevisionReviewCycleLoop:
    def test_request_changes_increments_review_cycle_count(self, api):
        """PRD section 3.2: "From `IN_REVIEW`, the administrator may either
        send the revision back to `DRAFT` by requesting changes — each such
        loop increments the revision's `review_cycle_count` by one — or
        approve it, moving it to `APPROVED`; both operations reject any other
        starting state with `ERR_REVISION_NOT_IN_REVIEW`."

        Design: Difficulty/non_linear_state_machine/menu_revision_review_cycle_loop
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        revision, _ = create_menu_revision_with_recipes(
            rest["id"], [], label="2026-Fall",
            effective_from="2026-09-15T00:00:00Z")
        rid = revision["id"]
        validate_success(api.submit_review(rid, menu_admin_headers()))
        back = validate_success(api.request_changes(rid, menu_admin_headers()))
        assert back["status"] == "DRAFT"
        assert back["review_cycle_count"] == 1

    def test_full_loop_lands_published_with_cards_complete(self, api):
        """PRD section 3.2: "Finally, the revision's
        `retraining_required_count` — the count of the restaurant's cooks
        whose certification does not match this revision — is recomputed, and
        its `recipe_card_redistribution_status`, which began at
        `NOT_STARTED`, flips to `COMPLETE` to reflect that recipe cards have
        been redistributed to stations."

        Design: Difficulty/non_linear_state_machine/menu_revision_review_cycle_loop
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        revision, _ = create_menu_revision_with_recipes(
            rest["id"], [], label="2026-Fall",
            effective_from="2026-09-15T00:00:00Z")
        rid = revision["id"]
        validate_success(api.submit_review(rid, menu_admin_headers()))
        validate_success(api.request_changes(rid, menu_admin_headers()))
        validate_success(api.submit_review(rid, menu_admin_headers()))
        validate_success(api.approve_revision(rid, menu_admin_headers()))
        published = validate_success(api.publish_revision(rid, menu_admin_headers()))
        assert published["status"] == "PUBLISHED"
        assert published["recipe_card_redistribution_status"] == "COMPLETE"
        assert published["review_cycle_count"] == 1


class TestPublishCascadeDepth3:
    def _cascade_setup(self, api):
        """V1 published with R1 referencing P; par on P; LOCKED list with one
        PLANNED batch of P; V2 in APPROVED referencing only Q."""
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
        mh = make_kitchen_manager_headers(mgr["id"])
        prep_cook = create_cook(rest["id"], mgr["id"], name="Paula Prep",
                                certified_station_types=["SAUTE"])
        item_p = create_prep_item(name="P", station_type="SAUTE")
        v1, recipes_v1 = create_menu_revision_with_recipes(
            rest["id"],
            [{"name": "R1", "station_type": "SAUTE",
              "components": [{"prep_item_id": item_p["id"],
                              "quantity_per_portion": 3, "unit": "OZ"}]}],
            label="V1", effective_from="2026-09-01T00:00:00Z", publish=True)
        station = create_station(rest["id"], mgr["id"], rack_slot_capacity=1000)
        par = create_station_par(station["id"], item_p["id"], mgr["id"],
                                 par_quantity=20)
        forecast = create_finalized_forecast(
            rest["id"], mgr["id"],
            [{"recipe_id": recipes_v1["R1"]["id"], "expected_count": 10}],
            expected_covers=10)
        prep_list, _ = create_locked_prep_list(rest["id"], mgr["id"],
                                               forecast["id"])
        batch = create_prep_batch(prep_list["id"], item_p["id"],
                                  station["id"], prep_cook["id"], 20)
        # Q is created only after V1's publish: an item unreferenced by any
        # ACTIVE recipe at publish time is retired by the publish cascade
        # (PRD section 3.2), and a recipe may not reference a RETIRED item.
        item_q = create_prep_item(name="Q", station_type="SAUTE")
        v2, recipes_v2 = create_menu_revision_with_recipes(
            rest["id"],
            [{"name": "R2", "station_type": "SAUTE",
              "components": [{"prep_item_id": item_q["id"],
                              "quantity_per_portion": 5, "unit": "OZ"}]}],
            label="V2", effective_from="2026-10-01T00:00:00Z")
        get_success_data(api.submit_review(v2["id"], menu_admin_headers()))
        get_success_data(api.approve_revision(v2["id"], menu_admin_headers()))
        return {
            "rest": rest, "mgr": mgr, "mh": mh, "item_p": item_p,
            "item_q": item_q, "v1": v1, "r1": recipes_v1["R1"],
            "station": station, "par": par, "prep_list": prep_list,
            "batch": batch, "v2": v2, "r2": recipes_v2["R2"],
        }

    def test_publish_retires_unreferenced_item_and_cascades_to_batch(self, api):
        """PRD section 3.2: "Every prep item that is no longer referenced by
        any `ACTIVE` recipe of that restaurant — traced through each recipe's
        `components` entries — is retired to `RETIRED`. Every station par in
        `ACTIVE` status whose prep item was just retired moves to `SUSPENDED`
        (this link is caused by the retirement, not directly by the publish).
        Every `PLANNED` prep batch whose prep item belongs to a
        just-suspended par is cancelled to `CANCELLED`, releasing its rack
        load (this link is caused by the suspension)."

        Design: Difficulty/transitive_cascade/menu_publish_cascade_depth3
        """
        ctx = self._cascade_setup(api)
        mh = ctx["mh"]
        validate_success(api.publish_revision(ctx["v2"]["id"],
                                              menu_admin_headers()))
        item_p = validate_success(api.get_prep_item(ctx["item_p"]["id"],
                                                    menu_admin_headers()))
        item_q = validate_success(api.get_prep_item(ctx["item_q"]["id"],
                                                    menu_admin_headers()))
        assert item_p["status"] == "RETIRED"
        assert item_q["status"] == "ACTIVE"
        par = validate_success(api.get_station_par(ctx["par"]["id"], mh))
        assert par["status"] == "SUSPENDED"
        batch = validate_success(api.get_prep_batch(ctx["batch"]["id"], mh))
        assert batch["status"] == "CANCELLED"
        summary = validate_success(
            api.get_throughput_summary(ctx["station"]["id"], mh))
        assert summary["rack_load"] == 0

    def test_publish_supersedes_prior_revision_and_its_recipes(self, api):
        """PRD section 3.2: "The restaurant's previously published revision,
        if any, moves to `SUPERSEDED`, and its `ACTIVE` recipes move to
        `SUPERSEDED` with it. The new revision's `DRAFT` recipes become
        `ACTIVE`."

        Design: Difficulty/transitive_cascade/menu_publish_cascade_depth3
        """
        ctx = self._cascade_setup(api)
        validate_success(api.publish_revision(ctx["v2"]["id"],
                                              menu_admin_headers()))
        v1 = validate_success(api.get_menu_revision(ctx["v1"]["id"],
                                                    menu_admin_headers()))
        r1 = validate_success(api.get_recipe(ctx["r1"]["id"],
                                             menu_admin_headers()))
        v2 = validate_success(api.get_menu_revision(ctx["v2"]["id"],
                                                    menu_admin_headers()))
        r2 = validate_success(api.get_recipe(ctx["r2"]["id"],
                                             menu_admin_headers()))
        assert v1["status"] == "SUPERSEDED"
        assert r1["status"] == "SUPERSEDED"
        assert v2["status"] == "PUBLISHED"
        assert r2["status"] == "ACTIVE"


class TestRetrainingCountComputedAtPublish:
    def test_retraining_required_count_counts_uncertified_cooks(self, api):
        """PRD section 3.2: "Every cook of the restaurant whose
        `certification_menu_revision_id` does not equal the newly published
        revision's id is flagged `RETRAINING_REQUIRED`. Finally, the
        revision's `retraining_required_count` — the count of the
        restaurant's cooks whose certification does not match this revision —
        is recomputed, and its `recipe_card_redistribution_status`, which
        began at `NOT_STARTED`, flips to `COMPLETE` to reflect that recipe
        cards have been redistributed to stations."

        Design: Corner/entities/menu_revision_retraining_count_computed_at_publish
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["GRILL"])
        cook = create_cook(rest["id"], mgr["id"], name="Chris Cook",
                           certified_station_types=["GRILL"])
        item = create_prep_item(name="Butter", station_type="GRILL",
                                shelf_life_hours=48, min_batch_size=1,
                                batch_unit="EA")
        revision, _ = create_menu_revision_with_recipes(
            rest["id"],
            [{"name": "Steak", "station_type": "GRILL",
              "components": [{"prep_item_id": item["id"],
                              "quantity_per_portion": 1, "unit": "EA"}]}],
            label="V1", effective_from="2026-09-15T00:00:00Z")
        get_success_data(api.submit_review(revision["id"], menu_admin_headers()))
        get_success_data(api.approve_revision(revision["id"], menu_admin_headers()))
        published = validate_success(api.publish_revision(
            revision["id"], menu_admin_headers()))
        assert published["retraining_required_count"] == 2
        assert published["recipe_card_redistribution_status"] == "COMPLETE"
        cook_now = validate_success(api.get_cook(
            cook["id"], make_kitchen_manager_headers(mgr["id"])))
        assert cook_now["status"] == "RETRAINING_REQUIRED"
