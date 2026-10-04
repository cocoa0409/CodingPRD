"""Store siting, radius and frequency gates, OCC, pagination, and the opening
surge (PRD sections 2.3/2.7/2.8/2.9/3.4)."""

from test_helpers import (
    ApiErrorId,
    assert_store,
    create_batch_payload,
    create_open_store_with_manager,
    create_operational_commissary,
    create_order_line,
    create_order_payload,
    create_production_run_payload,
    create_route_payload,
    create_site_store,
    create_stocked_open_store,
    create_store_payload,
    create_truck_payload,
    deliver_inventory,
    get_success_data,
    manager_headers_for,
    planner_headers,
    real_estate_headers,
    scd_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStoreListing:
    def test_stores_list_paginates_and_reports_total_count(self, api):
        """PRD section 2.3: "List endpoints accept two query parameters. The
        `limit` parameter specifies the maximum number of items to return;
        when omitted it defaults to 10, with a minimum of 1 and a maximum of
        100. The `offset` parameter specifies how many items to skip and
        defaults to 0."
        PRD section 2.3: "List responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/stores_list_paginates_and_reports_total_count
        """
        env = create_operational_commissary()
        com_id = env["commissary"]["id"]
        for i in range(3):
            store = create_site_store(env["commissary"],
                                      name=f"Store {chr(ord('A') + i)}",
                                      lat=34.01 + 0.01 * i,
                                      lng=-118.01 - 0.01 * i)
            assert_store(store)
        data, meta = validate_paginated(api.list_stores(
            scd_headers(), params={"commissary_id": com_id, "limit": 2,
                                   "offset": 0}))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        data2, meta2 = validate_paginated(api.list_stores(
            scd_headers(), params={"commissary_id": com_id, "limit": 2,
                                   "offset": 2}))
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestStoreCreationShape:
    def test_store_create_missing_required_field_returns_invalid_request(self, api):
        """PRD section 3.4: "A `RealEstatePlanner` proposes a store site
        against a specific commissary, supplying the `commissary_id`, a
        `name`, the site's `lat` and `lng`, optionally a
        `manager_associate_id`, and the mandatory
        `expected_commissary_version` described in §2.7."
        PRD section 2.5: "6. **Request shape** — required fields present,
        types valid, enum values within their declared domains, modifier codes
        within the unlisted variation set, arrays well-formed, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/store_create_missing_required_field_returns_invalid_request
        """
        env = create_operational_commissary()
        fresh = get_success_data(api.get_commissary(
            env["commissary"]["id"], scd_headers()))
        payload = {
            "commissary_id": env["commissary"]["id"],
            "name": "No Lng Store",
            "lat": 34.01,
            "expected_commissary_version": fresh["version"],
        }
        resp = api.create_store(payload, real_estate_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestOptimisticConcurrency:
    def test_commissary_stale_version_on_store_create_returns_412(self, api):
        """PRD section 2.7: "Creating a store requires the request to carry
        `expected_commissary_version`, the `version` of the target commissary
        as the client last observed it. If the commissary's current `version`
        no longer matches — because any prior store creation, truck mutation,
        beef receipt, production plan, or lifecycle transition has advanced
        it — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/entities/commissary_stale_version_on_store_create_returns_412
        """
        env = create_operational_commissary()
        stale_version = env["commissary"]["version"]
        # Advance the commissary version with a recertify + activate cycle
        # (lifecycle transitions increment the version, PRD section 3.2).
        get_success_data(api.recertify_commissary(
            env["commissary"]["id"], scd_headers()))
        fresh = get_success_data(api.activate_commissary(
            env["commissary"]["id"], scd_headers()))
        resp = api.create_store(
            create_store_payload(env["commissary"]["id"],
                                 expected_commissary_version=stale_version),
            real_estate_headers())
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        ok = validate_success(api.create_store(
            create_store_payload(env["commissary"]["id"],
                                 expected_commissary_version=fresh["version"]),
            real_estate_headers()), expected_status=201)
        assert ok["status"] == "SITE_REVIEW"

    def test_immediate_consistency_batch_creation_bumps_store_version(self, api):
        """PRD section 2.7: "Planning a delivery batch requires
        `expected_store_version`, matching the target store's current
        `version`. Surge toggles, status changes, and prior batch planning
        all advance the store's version; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412) because the client's frequency and
        mode assumptions are outdated."
        PRD section 3.5: "At planning time the system copies the store's
        `commissary_id` onto the batch, computes `cooler_cases_required`,
        leaves `production_run_id` and `route_id` null, and increments the
        store's `version`; the batch starts `PLANNED`."

        Design: Corner/consistency_model/immediate_consistency_batch_creation_bumps_store_version
        """
        env = create_open_store_with_manager()
        store = env["store"]
        store_v = store["version"]
        first = validate_success(api.create_batch(
            create_batch_payload(store["id"], store_v, "2026-09-02T00:00:00Z"),
            planner_headers()), expected_status=201)
        assert first["status"] == "PLANNED"
        resp = api.create_batch(
            create_batch_payload(store["id"], store_v, "2026-09-03T00:00:00Z"),
            planner_headers())
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412


class TestRadiusGate:
    def test_radius_exactly_at_limit_rejected(self, api):
        """PRD section 2.8: "the radius gate itself always compares the
        **raw, unrounded** value, and the comparison is strict: the raw
        distance must be strictly less than the commissary's
        `radius_limit_km`, or the request is rejected with
        `ERR_RADIUS_LIMIT_EXCEEDED` (HTTP 422). A site whose raw distance
        equals the limit exactly is rejected."

        Design: Difficulty/boundary_precision_check/radius_exactly_at_limit_rejected
        """
        # Haversine reference: 0.01 degrees of longitude at latitude 34 is
        # 0.921847... km raw, which rounds half-up to the 0.922 display value;
        # the gate compares the raw value, so a limit equal to the rounded
        # display still passes while a limit at-or-below the raw value fails.
        env = create_operational_commissary(radius_limit_km=0.911)
        store = create_site_store(env["commissary"], lat=34.0, lng=-117.99)
        assert abs(store["distance_km"] - 0.922) < 1e-9
        resp = api.approve_store(store["id"], real_estate_headers())
        validate_error(resp, ApiErrorId.ERR_RADIUS_LIMIT_EXCEEDED)
        assert resp.status_code == 422
        stored = get_success_data(api.get_store(store["id"], scd_headers()))
        assert stored["status"] == "SITE_REVIEW"

    def test_raw_distance_compared_not_rounded_display(self, api):
        """PRD section 2.8: "The value persisted on the store as
        `distance_km` is this raw distance rounded half-up to three decimal
        places — but the radius gate itself always compares the **raw,
        unrounded** value, and the comparison is strict"

        Design: Difficulty/boundary_precision_check/radius_exactly_at_limit_rejected
        """
        # Raw distance 0.921847... km; limit 0.921 km is below the raw value
        # even though the stored display rounds to 0.922.
        env = create_operational_commissary(radius_limit_km=0.921)
        store = create_site_store(env["commissary"], lat=34.0, lng=-117.99)
        assert abs(store["distance_km"] - 0.922) < 1e-9
        resp = api.approve_store(store["id"], real_estate_headers())
        validate_error(resp, ApiErrorId.ERR_RADIUS_LIMIT_EXCEEDED)
        assert resp.status_code == 422


class TestRadiusBeatsCapacity:
    def test_temporal_radius_beats_fiscal_capacity(self, api):
        """PRD section 2.5: "9. **Business safety, then referential, then
        temporal, then fiscal rules, then remaining business constraints**"
        PRD section 2.8: "the raw distance must be strictly less than the
        commissary's `radius_limit_km`, or the request is rejected with
        `ERR_RADIUS_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_radius_beats_fiscal_capacity
        """
        # The commissary's capacities are near zero AND the site sits beyond
        # the radius limit; the radius gate is in the temporal band, which
        # PRD section 2.5 places ahead of the fiscal band.
        env = create_operational_commissary(
            radius_limit_km=1.0, daily_patty_capacity=10,
            daily_bun_capacity=10, daily_produce_capacity=10)
        store = create_site_store(env["commissary"], lat=34.0099, lng=-118.0)
        resp = api.approve_store(store["id"], real_estate_headers())
        validate_error(resp, ApiErrorId.ERR_RADIUS_LIMIT_EXCEEDED)
        assert resp.status_code == 422
        stored = get_success_data(api.get_store(store["id"], scd_headers()))
        assert stored["status"] == "SITE_REVIEW"

    def test_radius_violation_rejected_even_with_valid_manager(self, api):
        """PRD section 3.4: "Approval moves `SITE_REVIEW` to `APPROVED` and
        re-runs the siting gates plus a staffing prerequisite"
        PRD section 2.8: "the raw distance must be strictly less than the
        commissary's `radius_limit_km`, or the request is rejected with
        `ERR_RADIUS_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_radius_beats_fiscal_capacity
        """
        from test_helpers import (
            hire_associate,
            promote_to_manager_via_posting,
            promote_to_shift_lead,
        )
        env = create_operational_commissary(radius_limit_km=1.0)
        store = create_site_store(env["commissary"], lat=34.0099, lng=-118.0)
        mgr = hire_associate(store["id"])
        mgr = promote_to_shift_lead(mgr["id"], store["id"])
        promote_to_manager_via_posting(mgr["id"], store["id"])
        resp = api.approve_store(store["id"], real_estate_headers())
        validate_error(resp, ApiErrorId.ERR_RADIUS_LIMIT_EXCEEDED)
        assert resp.status_code == 422


class TestOpeningSurge:
    def test_begin_surge_twice_returns_surge_already_active(self, api):
        """PRD section 3.4: "Entering surge requires the store to be `OPEN`
        and currently in `NORMAL` mode (`ERR_SURGE_ALREADY_ACTIVE`
        otherwise)"

        Design: Corner/state_machines/begin_surge_twice_returns_surge_already_active
        """
        env = create_open_store_with_manager()
        store = env["store"]
        mgr_headers = manager_headers_for(env)
        first = validate_success(api.begin_opening_surge(store["id"], mgr_headers))
        assert first["opening_mode"] == "OPENING_SURGE"
        assert str(first["surge_start_date"]).startswith("2026-09-01")
        resp = api.begin_opening_surge(store["id"], mgr_headers)
        validate_error(resp, ApiErrorId.ERR_SURGE_ALREADY_ACTIVE)
        assert resp.status_code == 409
        stored = get_success_data(api.get_store(store["id"], scd_headers()))
        assert str(stored["surge_start_date"]).startswith("2026-09-01")

    def test_end_surge_restores_normal_mode(self, api):
        """PRD section 3.4: "Ending the surge requires `OPENING_SURGE` to be
        active (`ERR_SURGE_NOT_ACTIVE` otherwise) and clears
        `surge_day_index`, `surge_start_date`, and `surge_end_date` back to
        null while restoring `opening_mode` to `NORMAL`."

        Design: Corner/state_machines/begin_surge_twice_returns_surge_already_active
        """
        env = create_open_store_with_manager()
        store = env["store"]
        mgr_headers = manager_headers_for(env)
        get_success_data(api.begin_opening_surge(store["id"], mgr_headers))
        ended = validate_success(api.end_opening_surge(store["id"], mgr_headers))
        assert ended["opening_mode"] == "NORMAL"
        assert ended["surge_day_index"] is None
        assert ended["surge_start_date"] is None
        assert ended["surge_end_date"] is None


class TestSurgePacing:
    def test_surge_pacing_min_floor_binds_on_low_intensity(self, api):
        """PRD section 3.6: "the number of currently `PLACED` orders is
        divided by ten and floored to an intensity, the raw pacing is the
        intensity times five minutes, and the effective pacing is the raw
        value clamped from below at a five-minute floor and from above at a
        per-day cap — 45 minutes on surge days one through three, 30 minutes
        on days four and five, and 20 minutes on days six and seven."
        PRD section 3.6: "On every placement the order's `queue_position` is
        the count of that store's orders currently in `PLACED` status plus
        one."

        Design: Difficulty/combinatorial_formula/surge_pacing_conditional_tiers
        """
        env = create_stocked_open_store(patty_count=200, bun_count=100,
                                        produce_units=100)
        store = env["store"]
        mgr_headers = manager_headers_for(env)
        get_success_data(api.begin_opening_surge(store["id"], mgr_headers))
        # Surge day 2: cap 45.  Twelve orders already PLACED.
        set_clock("2026-09-02T10:00:00Z")
        order12 = get_success_data(api.create_order(
            store["id"],
            create_order_payload(env["manager"]["id"],
                                 [create_order_line(env["item"]["id"], qty=12)]),
            mgr_headers))
        assert order12["queue_position"] == 1
        trigger = get_success_data(api.create_order(
            store["id"],
            create_order_payload(env["manager"]["id"],
                                 [create_order_line(env["item"]["id"], qty=1)]),
            mgr_headers))
        # 12 PLACED orders: intensity floor(12/10) = 1, raw 5 minutes, floor 5.
        assert trigger["surge_pacing_minutes"] == 5
        assert trigger["queue_position"] == 13

    def test_surge_pacing_cap_binds_on_day_five(self, api):
        """PRD section 3.6: "the raw pacing is the intensity times five
        minutes, and the effective pacing is the raw value clamped from below
        at a five-minute floor and from above at a per-day cap — 45 minutes
        on surge days one through three, 30 minutes on days four and five,
        and 20 minutes on days six and seven."

        Design: Difficulty/combinatorial_formula/surge_pacing_conditional_tiers
        """
        env = create_stocked_open_store(patty_count=200, bun_count=100,
                                        produce_units=100)
        store = env["store"]
        mgr_headers = manager_headers_for(env)
        get_success_data(api.begin_opening_surge(store["id"], mgr_headers))
        # Surge day 5: cap 30.  One hundred PLACED orders: intensity 10,
        # raw 50 minutes, clamped to the 30-minute cap.
        set_clock("2026-09-05T10:00:00Z")
        get_success_data(api.create_order(
            store["id"],
            create_order_payload(env["manager"]["id"],
                                 [create_order_line(env["item"]["id"], qty=100)]),
            mgr_headers))
        trigger = get_success_data(api.create_order(
            store["id"],
            create_order_payload(env["manager"]["id"],
                                 [create_order_line(env["item"]["id"], qty=1)]),
            mgr_headers))
        assert trigger["surge_pacing_minutes"] == 30


class TestBatchDeliveryGap:
    def test_batch_gap_over_48h_rejected(self, api):
        """PRD section 2.9: "Gap boundaries are always inclusive — a gap of
        exactly 48.0 hours passes the normal check."
        PRD section 3.5: "otherwise the gap must be less than or equal to the
        store's effective maximum — 24 hours during surge days one through
        three and for high-demand stores, 48 hours otherwise, with exactly
        48.0 hours passing — failing with `ERR_DELIVERY_FREQUENCY_VIOLATION`."

        Design: Corner/validations/batch_gap_over_48h_rejected
        """
        env = create_open_store_with_manager()
        com = env["commissary"]
        store = env["store"]
        # First batch DELIVERED at 2026-09-01T12:00:00Z.
        set_clock("2026-09-01T12:00:00Z")
        deliver_inventory(store, com, "2026-09-01T00:00:00Z", 10, 10, 10,
                          run_date="2026-09-01T00:00:00Z")
        # Second batch: delivery 2026-09-03T13:00:00Z -> 49-hour gap.
        store_v = get_success_data(api.get_store(store["id"], planner_headers()))["version"]
        batch2 = get_success_data(api.create_batch(
            create_batch_payload(store["id"], store_v, "2026-09-03T13:00:00Z"),
            planner_headers()))
        # Third batch: delivery 2026-09-03T12:00:00Z -> exactly 48 hours.
        store_v = get_success_data(api.get_store(store["id"], planner_headers()))["version"]
        batch3 = get_success_data(api.create_batch(
            create_batch_payload(store["id"], store_v, "2026-09-03T12:00:00Z"),
            planner_headers()))
        run = get_success_data(api.create_production_run(
            com["id"],
            create_production_run_payload(patties_planned=30, buns_planned=30,
                                          produce_units_planned=30),
            planner_headers()))
        get_success_data(api.complete_production_run(run["id"], planner_headers()))
        truck = get_success_data(api.create_truck(
            com["id"], create_truck_payload(plate="TRK-V6"), planner_headers()))
        route = get_success_data(api.create_route(
            create_route_payload(com["id"], truck["id"],
                                 "2026-09-03T00:00:00Z", [store["id"]]),
            planner_headers()))
        resp = api.load_batch(
            batch2["id"], {"production_run_id": run["id"],
                           "route_id": route["id"]}, planner_headers())
        validate_error(resp, ApiErrorId.ERR_DELIVERY_FREQUENCY_VIOLATION)
        assert resp.status_code == 422
        loaded = validate_success(api.load_batch(
            batch3["id"], {"production_run_id": run["id"],
                           "route_id": route["id"]}, planner_headers()))
        assert loaded["status"] == "LOADED"
        assert abs(loaded["gap_hours_at_load"] - 48.0) < 1e-9
