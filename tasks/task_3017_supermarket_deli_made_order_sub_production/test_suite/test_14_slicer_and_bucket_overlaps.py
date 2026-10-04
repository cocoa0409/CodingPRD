"""Two different aggregate/interval overlap rules: slicer occupancy and buckets."""

from test_helpers import (
    ApiErrorId,
    api_client,
    clerk_headers,
    create_catering_order_payload,
    get_success_data,
    platform_admin_headers,
    set_clock,
    setup_deli_master_data,
    store_version,
    validate_error,
    validate_success,
)


def _setup_two_batches_on_one_slicer():
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=0)
    slicer = get_success_data(
        api_client.create_slicer(
            {"store_id": master.s, "asset_tag": "SL-8", "sanitation_cycle_limit": 25,
             "assigned_operator_id": master.a1["id"]},
            platform_admin_headers(),
        )
    )
    first = get_success_data(
        api_client.create_batch(
            {"store_id": master.s, "deli_item_id": master.j2["id"], "slicer_id": slicer["id"],
             "produced_by_associate_id": master.a1["id"], "batch_code": "B-A", "planned_lbs": 10},
            clerk_headers(master.a1["id"]),
        )
    )
    second = get_success_data(
        api_client.create_batch(
            {"store_id": master.s, "deli_item_id": master.j2["id"], "slicer_id": slicer["id"],
             "produced_by_associate_id": master.a1["id"], "batch_code": "B-B", "planned_lbs": 10},
            clerk_headers(master.a1["id"]),
        )
    )
    validate_success(api_client.start_batch(
        first["id"], store_version(master.s), clerk_headers(master.a1["id"])
    ))
    return master, slicer, first, second


def test_a_covering_slicer_interval_rejects_the_second_claim():
    """PRD §3.1: "the slicer must not already be committed anywhere in the
    half-open interval running from the logical clock to the clock plus the
    item's `case_life_minutes`, or the start is refused with
    `ERR_SLICER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/slicer_commitment_overlap_disjoint_intervals
    """
    master, slicer, first, second = _setup_two_batches_on_one_slicer()
    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    response = api_client.start_batch(second["id"], store["version"], clerk_headers(master.a1["id"]))
    validate_error(response, ApiErrorId.ERR_SLICER_WINDOW_CONFLICT)

    untouched = validate_success(api_client.get_batch(second["id"], platform_admin_headers()))
    assert untouched["production_status"] == "PLANNED"
    slicer_now = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert slicer_now["sanitation_status"] == "IN_USE", (
        "the rejected claim left the first batch's occupancy in place"
    )


def test_the_committed_slicer_interval_is_released_by_a_completed_cycle():
    """PRD §3.2: "A successful completion moves the cycle to `COMPLETE` and stamps
    its `completed_at`, moves the slicer's `sanitation_status` back to `CLEAN`."

    The claimed slicer was blocked for the whole covering interval, but once a
    sanitation cycle for that asset has run its course and returned it to CLEAN,
    the batch that was refused earlier starts.

    Design: Difficulty/resource_temporal_overlap/slicer_commitment_overlap_disjoint_intervals
    """
    master, slicer, first, second = _setup_two_batches_on_one_slicer()
    backup = get_success_data(
        api_client.create_slicer(
            {"store_id": master.s, "asset_tag": "SL-9", "sanitation_cycle_limit": 25,
             "assigned_operator_id": master.a1["id"]},
            platform_admin_headers(),
        )
    )
    assert backup["sanitation_status"] == "CLEAN"
    slicer_now = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert slicer_now["sanitation_status"] == "IN_USE", (
        "the second start must see the interval kept by the first claim"
    )

    validate_success(api_client.complete_batch(first["id"], 10, clerk_headers(master.a1["id"])))
    after_completion = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert after_completion["sanitation_status"] == "NEEDS_SANITATION"
    assert after_completion["cuts_since_sanitation"] == 2, "ceil(10 / 5) cuts from one 10 lb run"


def _setup_two_orders_sharing_a_bucket():
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)
    big = get_success_data(
        api_client.create_catering_order(
            create_catering_order_payload(
                store_id=master.s, platter_deli_item_id=master.p1["id"], customer_name="Northside PTA",
                platter_count=20, headcount=30, lead_time_hours=30,
                pickup_window_start="2026-09-03T15:00:00Z", pickup_window_end="2026-09-03T15:45:00Z",
                certified_planner_associate_id=master.a1["id"], request_id="REQ-K1",
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    confirmed = validate_success(
        api_client.confirm_catering_order(big["id"], clerk_headers(master.a1["id"]))
    )
    small = get_success_data(
        api_client.create_catering_order(
            create_catering_order_payload(
                store_id=master.s, platter_deli_item_id=master.p1["id"], customer_name="Riverside HOA",
                platter_count=5, headcount=15, lead_time_hours=30,
                pickup_window_start="2026-09-03T15:05:00Z", pickup_window_end="2026-09-03T16:00:00Z",
                certified_planner_associate_id=master.a1["id"], request_id="REQ-K2",
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    return master, confirmed, small


def test_the_staging_buffer_floors_a_pickup_window_into_a_quarter_hour_bucket():
    """PRD §3.7: "The order's `pickup_bucket_key` is computed by subtracting a
    10-minute pre-window staging buffer from the `pickup_window_start` and then
    truncating the result to the quarter hour."

    Design: Difficulty/resource_temporal_overlap/pickup_bucket_overlap_aggregate_capacity_with_buffer
    """
    _, confirmed, _ = _setup_two_orders_sharing_a_bucket()
    assert confirmed["pickup_bucket_key"].startswith("2026-09-03T14:45:00"), (
        "15:00 minus 10 minutes floors to 14:50 and truncates back to the 14:45 bucket"
    )


def test_the_aggregate_bucket_capacity_refuses_the_second_order():
    """PRD §3.7: "The bucket's capacity rule is aggregate rather than per-order:
    the sum of `headcount` over every catering order sharing one bucket key must
    stay within a bucket headcount limit of 40."
    PRD §3.7: "An individual order can therefore pass every check in isolation and
    still be refused because of the company it keeps in its bucket."

    Design: Difficulty/resource_temporal_overlap/pickup_bucket_overlap_aggregate_capacity_with_buffer
    """
    master, confirmed, small = _setup_two_orders_sharing_a_bucket()
    response = api_client.confirm_catering_order(small["id"], clerk_headers(master.a1["id"]))
    validate_error(response, ApiErrorId.ERR_PICKUP_CAPACITY_EXCEEDED)

    unchanged = validate_success(api_client.get_catering_order(small["id"], platform_admin_headers()))
    assert unchanged["status"] == "INQUIRY", (
        "the rejection landed on the aggregate rather than on either order alone"
    )
    assert confirmed["status"] == "CONFIRMED"