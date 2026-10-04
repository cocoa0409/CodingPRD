"""Commodity restriction windows, optimistic concurrency, and list reads (PRD §2.3, §2.6, §3.2, §3.13)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_commodity,
    create_model_line,
    create_order_payload,
    create_restriction,
    create_commodity_restriction_payload,
    get_dealer_allocation,
    get_success_data,
    make_dealer_headers,
    seed_built_order,
    setup_dealer_run,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ALLOC = TEST_USERS["allocator_headers"]
COMM = TEST_USERS["commodity_manager_headers"]


class TestRestrictionOverlap:
    def test_overlapping_window_rejected(self, api):
        """PRD §3.2: "The overlap rule is conservative: a new restriction whose window would be contained within an existing `ACTIVE` restriction's window for the same pair, without fully superseding it, is rejected with `ERR_RESTRICTION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/commodity_restriction_window_overlap_rejection
        """
        line = create_model_line()
        commodity = create_commodity()
        create_restriction(
            commodity["id"], line["id"],
            effective_from="2026-08-01T00:00:00Z", effective_to="2026-10-01T00:00:00Z",
            install_rate_pct=30, allow_partial_build=False,
        )
        resp = api.create_commodity_restriction(
            create_commodity_restriction_payload(
                commodity["id"], line["id"],
                effective_from="2026-09-01T00:00:00Z", effective_to="2026-11-01T00:00:00Z",
                install_rate_pct=40, allow_partial_build=False,
            ),
            COMM,
        )
        validate_error(resp, ApiErrorId.ERR_RESTRICTION_OVERLAP, 422)

    def test_adjacent_window_supersedes(self, api):
        """PRD §3.2: "When a newer restriction is created for the same `(commodity_id, model_line_id)` pair, the prior `ACTIVE` restriction becomes `SUPERSEDED`."
        PRD §3.2: "`effective_to` (open end; null means open-ended)" — the window is end-exclusive, so a new window starting exactly at the old `effective_to` does not overlap.

        Design: Difficulty/resource_temporal_overlap/commodity_restriction_window_overlap_rejection
        """
        line = create_model_line()
        commodity = create_commodity()
        old = create_restriction(
            commodity["id"], line["id"],
            effective_from="2026-08-01T00:00:00Z", effective_to="2026-10-01T00:00:00Z",
            install_rate_pct=30, allow_partial_build=False,
        )
        new = validate_success(api.create_commodity_restriction(
            create_commodity_restriction_payload(
                commodity["id"], line["id"],
                effective_from="2026-10-01T00:00:00Z", effective_to="2026-12-01T00:00:00Z",
                install_rate_pct=40, allow_partial_build=False,
            ),
            COMM,
        ), 201)
        assert new["status"] == "ACTIVE"
        old_after = get_success_data(api.get_commodity_restriction(old["id"], COMM))
        assert old_after["status"] == "SUPERSEDED"


class TestStaleAllocationVersion:
    def test_replay_with_stale_version_rejected(self, api):
        """PRD §2.6: "If another writer (a prior order accept, a trade execution, or an appeal grant) has advanced that `DealerAllocation`'s `version` since the client last read it, the request is rejected with `ERR_STALE_ALLOCATION_VERSION` (HTTP 412)."

        Design: Corner/errors/stale_allocation_version_returns_412
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5)
        dealer = fx["dealers"][0]
        run = fx["run"]
        line = fx["model_line"]
        da = get_dealer_allocation(run["id"], dealer["id"])
        payload = create_order_payload(dealer["id"], line["id"], run["id"], da["version"])
        headers = make_dealer_headers(dealer["id"])
        first = api.create_order(payload, headers)
        validate_success(first, 201)
        # Replay with the same (now stale) version.
        resp = api.create_order(payload, headers)
        validate_error(resp, ApiErrorId.ERR_STALE_ALLOCATION_VERSION, 412)

    def test_current_version_accepted(self, api):
        """PRD §2.6: "A dealer creating an order must carry `expected_dealer_allocation_version` equal to the current `version` of the `DealerAllocation` for the order's `(run_id, dealer_id)` pair."

        Design: Corner/errors/stale_allocation_version_returns_412
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5)
        dealer = fx["dealers"][0]
        resp = submit_order(dealer["id"], fx["model_line"]["id"], fx["run"]["id"])
        order = validate_success(resp, 201)
        assert order["state"] == "ACCEPTED"


class TestVersionMonotonicity:
    def test_dealer_allocation_version_increments_on_mutations(self, api):
        """PRD §2.4: "an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that entity".
        PRD §2.6: "an accepted order bumps the `DealerAllocation`'s `version`".

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3)
        dealer = fx["dealers"][0]
        run = fx["run"]
        da_after_publish = get_dealer_allocation(run["id"], dealer["id"])
        order = submit_order(dealer["id"], fx["model_line"]["id"], run["id"])
        validate_success(order, 201)
        da_after_order = get_dealer_allocation(run["id"], dealer["id"])
        assert da_after_order["version"] == da_after_publish["version"] + 1


class TestListReads:
    def test_orders_list_pagination_defaults(self, api):
        """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0, with a minimum of 0. List results are always sorted by `created_at` ascending. The `meta` object on a list response includes the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reports the full count of matching records before pagination is applied and `has_more` reports whether any records exist beyond the current window."

        Design: Corner/endpoints/orders_list_pagination_defaults
        """
        fx = setup_dealer_run(num_dealers=1, base_units=20)
        dealer = fx["dealers"][0]
        run = fx["run"]
        line = fx["model_line"]
        for _ in range(12):
            seed_built_order(dealer["id"], line["id"], run["id"], scheduled_week="2026-W30")
        page1, meta1 = validate_paginated(api.list_orders(ALLOC, params={"dealer_id": dealer["id"]}))
        assert len(page1) == 10
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_orders(
            ALLOC, params={"dealer_id": dealer["id"], "limit": 10, "offset": 10}
        ))
        assert len(page2) == 2
        assert meta2["has_more"] is False

    def test_dealer_model_lines_subresource_matches_filtered_list(self, api):
        """PRD §3.13: "A dealer sees its own `DealerModelLine` rows through the dealer-scoped sub-resource listing".

        Design: Corner/endpoints/dealer_model_lines_filtered_list_reverse_reachability
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3)
        dealer = fx["dealers"][0]
        line = fx["model_line"]
        # Trigger DealerModelLine creation by entering one order.
        submit_order(dealer["id"], line["id"], fx["run"]["id"])
        sub_rows, _ = validate_paginated(api.list_dealer_model_lines_for_dealer(dealer["id"], ALLOC))
        filtered, _ = validate_paginated(api.list_dealer_model_lines(
            ALLOC, params={"dealer_id": dealer["id"], "model_line_id": line["id"]}
        ))
        assert len(filtered) == 1
        assert {row["id"] for row in sub_rows} == {row["id"] for row in filtered}
