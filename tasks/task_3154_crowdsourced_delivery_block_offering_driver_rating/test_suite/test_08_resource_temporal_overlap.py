"""Resource temporal overlap: half-open assignment windows; buffered offer gap."""

from test_helpers import (
    TEST_USERS,
    api_client,
    set_clock,
    create_station,
    create_published_block,
    onboard_active_driver,
    accept_block,
    create_offer,
    list_driver_assignments,
    make_driver_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

STATION_OPS_HEADERS = TEST_USERS["station_ops_headers"]


class TestAssignmentWindowOverlap:
    def test_adjacent_windows_allowed_true_overlap_rejected(self, api):
        """PRD §3.3: "Finally, the claim must not double-book the driver: if the driver
        already holds a non-terminal assignment — one in `ASSIGNED`, `CHECKED_IN`,
        `ROUTE_ASSIGNED`, or `IN_DELIVERY` — whose block window overlaps the new block's
        window, the claim is rejected with `ERR_BLOCK_WINDOW_OVERLAP`. Windows are
        compared as half-open intervals, so a block that ends exactly when another
        begins is allowed."

        Design: Difficulty/resource_temporal_overlap/assignment_window_overlap_half_open_adjacency_allowed
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block_a = create_published_block(
            station["id"],
            starts_at="2026-09-01T10:00:00Z",
            ends_at="2026-09-01T12:00:00Z",
            base_pay_cents=4000,
        )
        block_b = create_published_block(
            station["id"],
            starts_at="2026-09-01T12:00:00Z",
            ends_at="2026-09-01T14:00:00Z",
            base_pay_cents=4000,
        )
        block_c = create_published_block(
            station["id"],
            starts_at="2026-09-01T11:00:00Z",
            ends_at="2026-09-01T13:00:00Z",
            base_pay_cents=4000,
        )
        set_clock("2026-09-01T08:00:00Z")

        # A [10:00,12:00): succeeds.
        accept_block(block_a["id"], driver["id"], vehicle["id"])
        # B [12:00,14:00): adjacency (end == start) allowed.
        accept_block(block_b["id"], driver["id"], vehicle["id"])
        # C [11:00,13:00): true overlap with both A and B.
        resp = api_client.accept_block(
            block_c["id"],
            {"vehicle_id": vehicle["id"]},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BLOCK_WINDOW_OVERLAP)

        open_assignments = list_driver_assignments(driver["id"])
        non_terminal = [
            a
            for a in open_assignments
            if a["status"] in {"ASSIGNED", "CHECKED_IN", "ROUTE_ASSIGNED", "IN_DELIVERY"}
        ]
        assert len(non_terminal) == 2

    def test_relisted_block_can_be_accepted_again_by_same_driver(self, api):
        """PRD §3.7: "The forfeit stamps `forfeited_at`, records `forfeit_cause` as
        `DRIVER_INITIATED`, leaves `strike_reversed` false, and immediately relists the
        block: the block returns from `ASSIGNED` to `PUBLISHED` with
        `assigned_driver_id` cleared …"
        PRD §3.3: "Windows are compared as half-open intervals, so a block that ends
        exactly when another begins is allowed."

        Design: Difficulty/resource_temporal_overlap/assignment_window_overlap_half_open_adjacency_allowed
        """
        from test_helpers import forfeit, get_block

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
        first = accept_block(block["id"], driver["id"], vehicle["id"])
        forfeit(first["id"], driver["id"])

        assert get_block(block["id"])["status"] == "PUBLISHED"
        # After the forfeit the assignment is terminal, so the same window no
        # longer double-books the driver.
        second = accept_block(block["id"], driver["id"], vehicle["id"])
        assert second["status"] == "ASSIGNED"
        assert second["id"] != first["id"]


class TestReservedOfferBufferGap:
    def test_twenty_minute_gap_rejected_thirty_minute_gap_allowed(self, api):
        """PRD §3.3: "Reserved offers also enforce a buffered gap: if the offered
        block's window sits less than 30 minutes — in either direction — from any
        existing non-terminal assignment window of that driver, creation is rejected
        with `ERR_OFFER_BUFFER_CONFLICT`; a gap of exactly 30 minutes is allowed."

        Design: Difficulty/resource_temporal_overlap/reserved_offer_requires_thirty_minute_buffer_gap
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block_a = create_published_block(
            station["id"],
            starts_at="2026-09-01T10:00:00Z",
            ends_at="2026-09-01T12:00:00Z",
            base_pay_cents=4000,
        )
        block_d = create_published_block(
            station["id"],
            starts_at="2026-09-01T12:20:00Z",
            ends_at="2026-09-01T14:00:00Z",
            base_pay_cents=4000,
        )
        block_e = create_published_block(
            station["id"],
            starts_at="2026-09-01T12:30:00Z",
            ends_at="2026-09-01T14:30:00Z",
            base_pay_cents=4000,
        )
        set_clock("2026-09-01T08:00:00Z")
        accept_block(block_a["id"], driver["id"], vehicle["id"])

        # D leaves only a 20-minute gap after A: rejected.
        resp_d = api_client.create_offer(
            block_d["id"],
            {
                "driver_id": driver["id"],
                "tier_floor": "STANDARD",
                "expires_at": "2026-09-01T11:00:00Z",
            },
            STATION_OPS_HEADERS,
        )
        validate_error(resp_d, ApiErrorId.ERR_OFFER_BUFFER_CONFLICT)

        # E leaves exactly a 30-minute gap after A: allowed (inclusive boundary).
        offer_e = create_offer(
            block_e["id"],
            driver["id"],
            tier_floor="STANDARD",
            expires_at="2026-09-01T11:30:00Z",
        )
        assert offer_e["status"] == "OFFERED"

    def test_offer_creation_without_conflicts_succeeds(self, api):
        """PRD §3.3: "A `StationOps` operator creates an offer on a `PUBLISHED` block
        (otherwise `ERR_BLOCK_NOT_PUBLISHED`) by naming a `driver_id`, a `tier_floor`,
        and an `expires_at` instant. The target driver's current tier must rank at or
        above the `tier_floor` at creation time. Reserved offers also enforce a buffered
        gap: if the offered block's window sits less than 30 minutes — in either
        direction — from any existing non-terminal assignment window of that driver,
        creation is rejected with `ERR_OFFER_BUFFER_CONFLICT`; a gap of exactly 30
        minutes is allowed."

        Design: Difficulty/resource_temporal_overlap/reserved_offer_requires_thirty_minute_buffer_gap
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block_a = create_published_block(
            station["id"],
            starts_at="2026-09-01T10:00:00Z",
            ends_at="2026-09-01T12:00:00Z",
            base_pay_cents=4000,
        )
        block_far = create_published_block(
            station["id"],
            starts_at="2026-09-01T13:00:00Z",
            ends_at="2026-09-01T15:00:00Z",
            base_pay_cents=4000,
        )
        set_clock("2026-09-01T08:00:00Z")
        accept_block(block_a["id"], driver["id"], vehicle["id"])

        # 60-minute gap: comfortably over the 30-minute buffer.
        offer = create_offer(
            block_far["id"],
            driver["id"],
            tier_floor="STANDARD",
            expires_at="2026-09-01T12:00:00Z",
        )
        assert offer["status"] == "OFFERED"
        assert offer["driver_id"] == driver["id"]
