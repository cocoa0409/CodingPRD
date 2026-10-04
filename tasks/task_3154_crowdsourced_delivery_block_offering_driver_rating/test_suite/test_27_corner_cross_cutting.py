"""Corner — cross-cutting: optimistic concurrency, pagination envelope, surge expiry cascade, liability reconciliation, immediate consistency."""

from test_helpers import (
    TEST_USERS,
    api_client,
    set_clock,
    create_station,
    create_block,
    publish_block,
    get_station,
    onboard_active_driver,
    create_offer,
    run_surge_cycle,
    get_block,
    get_offer,
    accept_block,
    create_published_block,
    complete_block_flow,
    settle_pay_statement,
    make_driver_headers,
    validate_error,
    validate_success,
    validate_paginated,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["platform_admin_headers"]
STATION_OPS = TEST_USERS["station_ops_headers"]


class TestOptimisticConcurrency:
    def test_block_revise_stale_version_rejected(self, api):
        """PRD §2.7: "Revising a delivery block requires the request to include
        `expected_block_version` carrying the client's last observed `version` of the
        block; if another writer has advanced the block's version since the client last
        read it, the revision is rejected with `ERR_STALE_VERSION` (HTTP 412), because
        each revision legitimately supersedes the prior block configuration of pay,
        window, and vehicle class."
        PRD §3.2: "While a block is in `DRAFT` or `PUBLISHED`, the station may revise
        its window, required vehicle class, or base pay — each revision supersedes the
        prior configuration, recomputes `estimated_pay_cents`, and is protected by the
        optimistic concurrency rule on `expected_block_version` described in §2.7."

        Design: Corner/cross_cutting/block_revise_stale_version_rejected
        """
        set_clock()
        station = create_station()
        block = create_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        published = publish_block(block["id"])
        observed_version = published["version"]

        # First revise with the observed version: succeeds, supersedes configuration.
        resp1 = api_client.revise_block(
            block["id"],
            {"expected_block_version": observed_version, "base_pay_cents": 4500},
            STATION_OPS,
        )
        revised = validate_success(resp1)
        assert revised["base_pay_cents"] == 4500
        assert revised["estimated_pay_cents"] == 4500
        assert revised["version"] == observed_version + 1

        # Replay with a stale version: rejected.
        resp2 = api_client.revise_block(
            block["id"],
            {"expected_block_version": observed_version - 1, "base_pay_cents": 9999},
            STATION_OPS,
        )
        validate_error(resp2, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        assert get_block(block["id"])["base_pay_cents"] == 4500

    def test_surge_cycle_stale_station_version_rejected(self, api):
        """PRD §2.7: "Running a surge cycle against a station requires
        `expected_station_version` matching the station's current `version`; a mismatch
        is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because each cycle
        advances the station epoch — expirations, no-show sweeps, and escalations — and
        a cycle run from a stale epoch would double-apply time-based effects."
        PRD §3.7: "the station's `version` increments exactly once per cycle."

        Design: Corner/cross_cutting/surge_cycle_stale_station_version_rejected
        """
        set_clock()
        station = create_station()

        resp1 = api_client.run_surge_cycle(
            station["id"],
            {"expected_station_version": station["version"]},
            STATION_OPS,
        )
        cycled = validate_success(resp1)
        assert cycled["version"] == station["version"] + 1

        # Replay with a stale epoch: rejected.
        resp2 = api_client.run_surge_cycle(
            station["id"],
            {"expected_station_version": station["version"] - 1},
            STATION_OPS,
        )
        validate_error(resp2, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestPagination:
    def test_paginated_block_list_envelope_and_windowing(self, api):
        """PRD §2.3: "List endpoints are paginated through two query parameters.
        `limit` sets the maximum number of items returned; it defaults to 10 when
        omitted, with a minimum of 1 and a maximum of 100. `offset` sets how many items
        to skip and defaults to 0. Unless a list endpoint states its own ordering, all
        list endpoints return resources sorted by `created_at` ascending. Paginated list
        responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta`
        object of the response envelope."
        PRD §3.2: "A station's own block listing is likewise ordered by `starts_at`
        ascending then `created_at` ascending and supports a `status` filter."

        Design: Corner/cross_cutting/paginated_block_list_envelope_and_windowing
        """
        set_clock()
        station = create_station()
        early = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        late = create_published_block(
            station["id"],
            starts_at="2026-09-01T05:00:00Z",
            ends_at="2026-09-01T07:00:00Z",
            base_pay_cents=4000,
        )

        page1, meta1 = validate_paginated(
            api_client.list_station_blocks(
                station["id"], STATION_OPS, params={"limit": 1, "offset": 0}
            )
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["id"] == early["id"]

        page2, meta2 = validate_paginated(
            api_client.list_station_blocks(
                station["id"], STATION_OPS, params={"limit": 1, "offset": 1}
            )
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page2[0]["id"] == late["id"]


class TestSurgeCycleExpiryCascade:
    def test_surge_cycle_expires_unfilled_block_and_its_offers(self, api):
        """PRD §3.7: "Third, every `PUBLISHED` block whose `starts_at` has been reached
        while still unfilled moves to `EXPIRED`, and its remaining `OFFERED` offers
        expire with it."

        Design: Corner/cross_cutting/surge_cycle_expires_unfilled_block_and_its_offers
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        offer = create_offer(
            block["id"],
            driver["id"],
            tier_floor="STANDARD",
            expires_at="2026-09-03T00:00:00Z",
        )

        # Clock reaches starts_at with the block still unfilled.
        set_clock("2026-09-01T02:00:00Z")
        run_surge_cycle(station["id"], station["version"])

        assert get_block(block["id"])["status"] == "EXPIRED"
        assert get_offer(offer["id"])["status"] == "EXPIRED"


class TestDerivedPayLiabilities:
    def test_derived_pay_liabilities_reconcile_after_settle(self, api):
        """PRD §3.6: "settling adds the statement's `final_pay_cents` to the station's
        `pay_liabilities_cents`, which is defined as the sum of `final_pay_cents` over
        all `SETTLED` statements belonging to that station's blocks — `OPEN` and
        `VOIDED` statements are excluded."

        Design: Corner/cross_cutting/derived_pay_liabilities_reconcile_after_settle
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()

        _b, _a, ps, _pkgs = complete_block_flow(
            station,
            driver,
            vehicle,
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            package_specs=[
                {
                    "tracking_code": "PW-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-09-01T02:30:00Z",
                }
            ],
        )
        # OPEN statements are excluded from the liability.
        assert ps["status"] == "OPEN"
        assert get_station(station["id"])["pay_liabilities_cents"] == 0

        settle_pay_statement(ps["id"])
        assert get_station(station["id"])["pay_liabilities_cents"] == 4155


class TestImmediateConsistency:
    def test_mutations_visible_in_same_request_and_immediate_rereads(self, api):
        """PRD §3.3: "acceptance freezes two snapshots onto the new assignment:
        `surge_multiplier_snapshot_bp` copies the block's `surge_multiplier_bp` at that
        moment, and `tier_at_accept` copies the driver's `rating_tier`. The block's
        `assigned_driver_id` is set to the claiming driver and is null whenever the
        block is unassigned."
        PRD §3.3: "The assignment's `provisional_pay_cents` is the provisional pay
        variant: the block's base pay multiplied by the frozen surge snapshot and
        divided by 10000, rounded half-up to whole cents."

        Design: Corner/consistency/mutations_visible_in_same_request_and_immediate_rereads
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T10:00:00Z",
            ends_at="2026-09-01T12:00:00Z",
            base_pay_cents=4000,
        )
        set_clock("2026-09-01T08:00:00Z")

        resp = api_client.accept_block(
            block["id"],
            {"vehicle_id": vehicle["id"]},
            make_driver_headers(driver["id"]),
        )
        assignment = validate_success(resp, expected_status=201)
        assert assignment["status"] == "ASSIGNED"
        assert assignment["surge_multiplier_snapshot_bp"] == 10000
        assert assignment["tier_at_accept"] == "STANDARD"
        assert assignment["provisional_pay_cents"] == 4000

        # Immediate re-read shows the block flip with the driver attached.
        block_after = get_block(block["id"])
        assert block_after["status"] == "ASSIGNED"
        assert block_after["assigned_driver_id"] == driver["id"]
