"""Scheduling a work order: the guard order, the two occupancy geometries."""

from test_helpers import (
    ApiErrorId,
    api_client,
    certify_bar_lot,
    machine_version,
    make_shop_planner_headers,
    read_bar_lot,
    read_work_order,
    receive_bar_lot,
    register_machine,
    schedule_work_order,
    setup_shared_lot_on_two_machines,
    setup_shop_floor,
    setup_two_part_shop,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = make_shop_planner_headers()


def _work_order_body(release_id, machine_id, lot_id, version, start, end, qty=200, lights_out=0):
    return {
        "release_id": release_id,
        "machine_id": machine_id,
        "bar_lot_id": lot_id,
        "qty_ordered": qty,
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "expected_machine_version": version,
        "lights_out_hours": lights_out,
    }


class TestOccupancyCheckOrder:
    """A candidate that violates both occupancy rules reports the machine one."""

    def test_machine_window_conflict_is_reported_before_the_feeder_conflict(self):
        """PRD 3.5: "The two occupancy checks come next, and they use
        deliberately different interval arithmetic."
        PRD 3.5: "Machine occupancy is evaluated first."
        PRD 3.5: "A conflict is rejected with `ERR_MACHINE_WINDOW_CONFLICT` (HTTP
        409)."

        Design: Difficulty/priority_pair_validation_conflict/machine_window_beats_feeder_capacity
        """
        shop = setup_shop_floor(committed_qty=400, release_qty=400)
        schedule_work_order(
            shop.release_id,
            shop.machine_id,
            shop.lot_id,
            qty_ordered=200,
            lights_out_hours=0,
            scheduled_start_at="2026-09-02T06:00:00Z",
            scheduled_end_at="2026-09-02T14:00:00Z",
        )
        version = machine_version(shop.machine_id)

        response = api_client.create_work_order(
            _work_order_body(
                shop.release_id,
                shop.machine_id,
                shop.lot_id,
                version,
                "2026-09-02T13:00:00Z",
                "2026-09-02T20:00:00Z",
            ),
            PLANNER,
        )
        error = validate_error(response, ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT.value)
        assert error["error_id"] != ApiErrorId.ERR_BAR_LOT_FEEDER_CONFLICT.value

    def test_schedule_refused_on_a_window_conflict_reserves_no_bar_length(self):
        """PRD 3.5: "Bar-lot feeder occupancy is evaluated second"
        PRD 3.5: "When every gate passes, the reservation is booked: the reserved
        length is subtracted from the lot's `available_length_mm` and added to its
        `reserved_length_mm`, leaving the conserved total of §2.7 intact."

        Design: Difficulty/priority_pair_validation_conflict/machine_window_beats_feeder_capacity
        """
        shop = setup_shop_floor(committed_qty=400, release_qty=400)
        schedule_work_order(
            shop.release_id,
            shop.machine_id,
            shop.lot_id,
            qty_ordered=200,
            lights_out_hours=0,
            scheduled_start_at="2026-09-02T06:00:00Z",
            scheduled_end_at="2026-09-02T14:00:00Z",
        )
        version = machine_version(shop.machine_id)
        api_client.create_work_order(
            _work_order_body(
                shop.release_id,
                shop.machine_id,
                shop.lot_id,
                version,
                "2026-09-02T13:00:00Z",
                "2026-09-02T20:00:00Z",
            ),
            PLANNER,
        )

        lot = read_bar_lot(shop.lot_id)
        assert lot["reserved_length_mm"] == 7200
        assert lot["available_length_mm"] == 64800


class TestMachineWindowGeometry:
    """Half-open intervals plus a changeover buffer keyed on bar diameter."""

    def test_changeover_buffer_blocks_a_candidate_inside_the_buffered_window(self):
        """PRD 3.5: "That buffer is 45 minutes when the existing job's part and
        the candidate's part call for different bar diameters — the guide bushing
        and collets must be swapped — and is zero minutes when the two bar
        diameters are equal."
        PRD 3.5: "A conflict exists when the candidate's start falls strictly
        before the buffered end of an existing job and that existing job's start
        falls strictly before the candidate's end."

        Design: Difficulty/resource_temporal_overlap/machine_window_half_open_with_changeover_buffer
        """
        shop = setup_two_part_shop()
        schedule_work_order(
            shop.release_a_id,
            shop.machine_id,
            shop.lot_a_id,
            qty_ordered=200,
            lights_out_hours=0,
            scheduled_start_at="2026-09-02T06:00:00Z",
            scheduled_end_at="2026-09-02T14:00:00Z",
        )
        version = machine_version(shop.machine_id)

        response = api_client.create_work_order(
            _work_order_body(
                shop.release_b_id,
                shop.machine_id,
                shop.lot_b_id,
                version,
                "2026-09-02T14:30:00Z",
                "2026-09-02T20:00:00Z",
                qty=100,
            ),
            PLANNER,
        )
        validate_error(response, ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT.value)

    def test_candidate_starting_at_the_buffered_end_is_admitted(self):
        """PRD 3.5: "Because the geometry is half-open, exact adjacency is legal:
        a candidate beginning at the very instant a buffered interval ends does
        not conflict."
        PRD 3.5: "The buffer is appended only to the earlier interval's end and is
        never prepended to the candidate's start."

        Design: Difficulty/resource_temporal_overlap/machine_window_half_open_with_changeover_buffer
        """
        shop = setup_two_part_shop()
        schedule_work_order(
            shop.release_a_id,
            shop.machine_id,
            shop.lot_a_id,
            qty_ordered=200,
            lights_out_hours=0,
            scheduled_start_at="2026-09-02T06:00:00Z",
            scheduled_end_at="2026-09-02T14:00:00Z",
        )
        version = machine_version(shop.machine_id)

        admitted = validate_success(
            api_client.create_work_order(
                _work_order_body(
                    shop.release_b_id,
                    shop.machine_id,
                    shop.lot_b_id,
                    version,
                    "2026-09-02T14:45:00Z",
                    "2026-09-02T20:00:00Z",
                    qty=100,
                ),
                PLANNER,
            ),
            201,
        )
        assert admitted["machining_status"] == "SCHEDULED"
        assert admitted["bars_reserved"] == 2
        assert read_bar_lot(shop.lot_b_id)["reserved_length_mm"] == 6000


class TestBarLotFeederGeometry:
    """Closed intervals counted against an aggregate feeder capacity."""

    def test_a_candidate_touching_an_existing_staging_interval_collides(self):
        """PRD 3.5: "Because the geometry is closed, touching endpoints do
        collide — a candidate beginning at the exact instant an existing job ends
        is counted as overlapping, which is the opposite of the machine rule."
        PRD 3.5: "A conflict is rejected with `ERR_BAR_LOT_FEEDER_CONFLICT` (HTTP
        409)."

        Design: Difficulty/resource_temporal_overlap/bar_lot_feeder_closed_interval_aggregate_capacity
        """
        shop = setup_shared_lot_on_two_machines()
        schedule_work_order(
            shop.release_id,
            shop.machine_id,
            shop.lot_id,
            qty_ordered=200,
            lights_out_hours=0,
            scheduled_start_at="2026-09-02T06:00:00Z",
            scheduled_end_at="2026-09-02T14:00:00Z",
        )
        version = machine_version(shop.machine2_id)

        response = api_client.create_work_order(
            _work_order_body(
                shop.release_id,
                shop.machine2_id,
                shop.lot_id,
                version,
                "2026-09-02T14:00:00Z",
                "2026-09-02T20:00:00Z",
            ),
            PLANNER,
        )
        validate_error(response, ApiErrorId.ERR_BAR_LOT_FEEDER_CONFLICT.value)

    def test_a_candidate_one_second_after_the_existing_job_ends_is_admitted(self):
        """PRD 3.5: "Capacity is aggregate: the conflict fires when that count
        plus one exceeds the lot's `feeder_slots`, so on a lot declaring two slots
        the first intersecting job is admitted and only the second is refused."
        PRD 3.5: "Every existing work order naming the same `bar_lot_id` whose
        `machining_status` is not `CANCELLED` occupies its own closed interval,
        with no buffer of any kind, and jobs on other lots never participate
        regardless of machine."

        Design: Difficulty/resource_temporal_overlap/bar_lot_feeder_closed_interval_aggregate_capacity
        """
        shop = setup_shared_lot_on_two_machines()
        schedule_work_order(
            shop.release_id,
            shop.machine_id,
            shop.lot_id,
            qty_ordered=200,
            lights_out_hours=0,
            scheduled_start_at="2026-09-02T06:00:00Z",
            scheduled_end_at="2026-09-02T14:00:00Z",
        )
        version = machine_version(shop.machine2_id)

        admitted = validate_success(
            api_client.create_work_order(
                _work_order_body(
                    shop.release_id,
                    shop.machine2_id,
                    shop.lot_id,
                    version,
                    "2026-09-02T14:00:01Z",
                    "2026-09-02T20:00:00Z",
                ),
                PLANNER,
            ),
            201,
        )
        assert admitted["machine_id"] == shop.machine2_id

        lot = read_bar_lot(shop.lot_id)
        assert lot["reserved_length_mm"] == 14400
        assert lot["available_length_mm"] == 57600


def test_bar_diameter_mismatch_is_reported_before_insufficient_stock():
    """PRD 3.5: "The lot's `bar_diameter_mm` must equal the part's
    `bar_diameter_mm` and must also be less than or equal to the machine's
    `max_bar_diameter_mm`; a failure of either half is
    `ERR_BAR_DIAMETER_MISMATCH` (HTTP 422)."
    PRD 3.5: "Next comes material fit, in two steps."
    PRD 3.5: "Finally the material must actually be on the rack, which requires
    the reservation arithmetic to be run."

    Design: Corner/validations/bar_diameter_mismatch_outranks_bar_stock_insufficient
    """
    shop = setup_shop_floor()
    wide_lot = receive_bar_lot(
        heat_number="H-77001", bar_diameter_mm=16.0, bars_received=1, mass_kg_per_meter=1.58
    )
    certify_bar_lot(wide_lot["id"], "CERT-B")
    version = machine_version(shop.machine_id)

    response = api_client.create_work_order(
        _work_order_body(
            shop.release_id,
            shop.machine_id,
            wide_lot["id"],
            version,
            "2026-09-02T06:00:00Z",
            "2026-09-02T14:00:00Z",
        ),
        PLANNER,
    )
    error = validate_error(response, ApiErrorId.ERR_BAR_DIAMETER_MISMATCH.value)
    assert error["error_id"] != ApiErrorId.ERR_BAR_STOCK_INSUFFICIENT.value

    lot = read_bar_lot(wide_lot["id"])
    assert lot["available_length_mm"] == 3600
    assert lot["reserved_length_mm"] == 0


def test_lot_alloy_must_match_the_parts_alloy():
    """PRD 3.5: "Then the lot's `alloy_code` must equal the part's `alloy_code`,
    failing which the request is rejected with `ERR_ALLOY_MISMATCH` (HTTP 422)."

    Design: Corner/errors/alloy_mismatch_between_lot_and_part_is_rejected
    """
    shop = setup_shop_floor()
    other_alloy = receive_bar_lot(heat_number="H-77002", alloy_code="316SS")
    certify_bar_lot(other_alloy["id"], "CERT-X")
    version = machine_version(shop.machine_id)

    response = api_client.create_work_order(
        _work_order_body(
            shop.release_id,
            shop.machine_id,
            other_alloy["id"],
            version,
            "2026-09-02T06:00:00Z",
            "2026-09-02T14:00:00Z",
        ),
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_ALLOY_MISMATCH.value)


def test_lights_out_permission_is_only_checked_when_hours_are_positive():
    """PRD 3.5: "Next, if `lights_out_hours` is greater than zero, both the
    part's `lights_out_eligible` flag and the machine's `lights_out_certified`
    flag must be true; if either is false, the request is rejected with
    `ERR_LIGHTS_OUT_NOT_PERMITTED` (HTTP 422)."

    Design: Corner/validations/lights_out_rules_apply_only_when_lights_out_hours_is_positive
    """
    shop = setup_shop_floor(
        part_overrides={"part_number": "P-4471-NLO", "lights_out_eligible": False}
    )
    version = machine_version(shop.machine_id)

    refused = api_client.create_work_order(
        _work_order_body(
            shop.release_id,
            shop.machine_id,
            shop.lot_id,
            version,
            "2026-09-02T06:00:00Z",
            "2026-09-02T14:00:00Z",
            lights_out=4,
        ),
        PLANNER,
    )
    validate_error(refused, ApiErrorId.ERR_LIGHTS_OUT_NOT_PERMITTED.value)

    admitted = validate_success(
        api_client.create_work_order(
            _work_order_body(
                shop.release_id,
                shop.machine_id,
                shop.lot_id,
                version,
                "2026-09-02T06:00:00Z",
                "2026-09-02T14:00:00Z",
                lights_out=0,
            ),
            PLANNER,
        ),
        201,
    )
    assert admitted["lights_out_hours"] == 0
    assert admitted["machining_status"] == "SCHEDULED"


def test_release_quantity_gate_aggregates_over_sibling_work_orders():
    """PRD 3.5: "The candidate's `qty_ordered`, added to the `qty_ordered` of
    every non-cancelled sibling work order already on the same release, must not
    exceed the release's `qty`; exceeding it is `ERR_RELEASE_QTY_EXCEEDED` (HTTP
    409)."

    Design: Corner/validations/release_qty_exceeded_aggregates_over_sibling_work_orders
    """
    shop = setup_shop_floor(committed_qty=400, release_qty=200)
    first = schedule_work_order(
        shop.release_id,
        shop.machine_id,
        shop.lot_id,
        qty_ordered=150,
        lights_out_hours=0,
        scheduled_start_at="2026-09-02T06:00:00Z",
        scheduled_end_at="2026-09-02T14:00:00Z",
    )
    version = machine_version(shop.machine_id)

    response = api_client.create_work_order(
        _work_order_body(
            shop.release_id,
            shop.machine_id,
            shop.lot_id,
            version,
            "2026-09-03T06:00:00Z",
            "2026-09-03T12:00:00Z",
            qty=100,
        ),
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_RELEASE_QTY_EXCEEDED.value)

    assert read_bar_lot(shop.lot_id)["reserved_length_mm"] == 7200
    assert read_work_order(first["id"])["qty_ordered"] == 150


def test_schedule_authored_against_a_stale_machine_version_is_refused():
    """PRD 2.5: "If that value does not equal the machine's current `version`,
    the create is rejected with `ERR_STALE_MACHINE_VERSION` (HTTP 412), and it is
    rejected before any window arithmetic is attempted."

    Design: Corner/cross_cutting_complexity_layers/stale_machine_version_on_work_order_returns_412
    """
    shop = setup_shop_floor(committed_qty=400, release_qty=400)
    schedule_work_order(
        shop.release_id,
        shop.machine_id,
        shop.lot_id,
        qty_ordered=200,
        lights_out_hours=0,
        scheduled_start_at="2026-09-02T06:00:00Z",
        scheduled_end_at="2026-09-02T14:00:00Z",
    )
    version = machine_version(shop.machine_id)

    stale = api_client.create_work_order(
        _work_order_body(
            shop.release_id,
            shop.machine_id,
            shop.lot_id,
            version - 1,
            "2026-09-05T06:00:00Z",
            "2026-09-05T14:00:00Z",
        ),
        PLANNER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_MACHINE_VERSION.value)

    fresh = validate_success(
        api_client.create_work_order(
            _work_order_body(
                shop.release_id,
                shop.machine_id,
                shop.lot_id,
                version,
                "2026-09-05T06:00:00Z",
                "2026-09-05T14:00:00Z",
            ),
            PLANNER,
        ),
        201,
    )
    assert fresh["machining_status"] == "SCHEDULED"
    assert read_bar_lot(shop.lot_id)["reserved_length_mm"] == 14400


def test_work_order_list_filters_by_machine_and_windows_the_result():
    """PRD 2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100.
    `offset` defaults to 0 and has a minimum of 0."
    PRD 2.3: "`limit` and `offset` echo the effective values used, `total_count`
    reports the number of rows matching the filter before the window was applied,
    and `has_more` is true when rows remain beyond the current window."

    Design: Corner/endpoints/list_work_orders_filtered_by_machine_with_limit_and_offset
    """
    shop = setup_shop_floor(committed_qty=600, release_qty=600)
    second_machine = register_machine(asset_tag="SW-02")

    windows = [
        ("2026-09-02T06:00:00Z", "2026-09-02T14:00:00Z"),
        ("2026-09-04T06:00:00Z", "2026-09-04T14:00:00Z"),
    ]
    on_first = []
    for start, end in windows:
        on_first.append(
            schedule_work_order(
                shop.release_id,
                shop.machine_id,
                shop.lot_id,
                qty_ordered=200,
                lights_out_hours=0,
                scheduled_start_at=start,
                scheduled_end_at=end,
            )["id"]
        )
    on_second = schedule_work_order(
        shop.release_id,
        second_machine["id"],
        shop.lot_id,
        qty_ordered=200,
        lights_out_hours=0,
        scheduled_start_at="2026-09-06T06:00:00Z",
        scheduled_end_at="2026-09-06T14:00:00Z",
    )["id"]

    rows, meta = validate_paginated(
        api_client.list_work_orders(
            PLANNER, {"machine_id": shop.machine_id, "limit": 1, "offset": 1}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] in on_first
    assert rows[0]["id"] != on_second
