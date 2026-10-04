"""Throughput measurement: window spacing, closability, provisional vs final
attainment variants, PASS/BREACH boundary, and the breach counter."""
from test_helpers import (
    ApiErrorId,
    RM,
    build_item_ready,
    authorize_order,
    create_region,
    create_stand,
    create_window_payload,
    list_items_of_order,
    make_crew_member_headers,
    make_shift_lead_headers,
    place_window_order,
    serve_window_order,
    set_clock,
    setup_open_stand_with_menu,
    stand_version,
    validate_error,
    validate_success,
)


def _create_window(api, stand_id, **overrides):
    return validate_success(
        api.create_window(create_window_payload(stand_id, **overrides), RM), 201
    )


class TestWindowSpacing:
    def test_throughput_window_gap_buffer_semantics(self, api):
        """PRD §3.1: "Windows on the same stand must be disjoint **and** separated
        by at least fifteen minutes — a window that overlaps an existing one or
        leaves a gap shorter than fifteen minutes to an adjacent one is rejected
        with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/throughput_window_gap_buffer_semantics
        """
        region = create_region()
        stand = create_stand(region["id"])
        _create_window(
            api, stand["id"],
            starts_at="2026-09-01T07:00:00Z",
            ends_at="2026-09-01T08:00:00Z",
            target_cars=5,
        )
        ok = api.create_window(
            create_window_payload(
                stand["id"],
                starts_at="2026-09-01T08:15:00Z",
                ends_at="2026-09-01T09:00:00Z",
                target_cars=5,
            ),
            RM,
        )
        window2 = validate_success(ok, 201)
        assert window2["status"] == "OPEN", "exactly 15 minutes of gap is allowed"

        too_close = api.create_window(
            create_window_payload(
                stand["id"],
                starts_at="2026-09-01T08:05:00Z",
                ends_at="2026-09-01T08:10:00Z",
                target_cars=2,
            ),
            RM,
        )
        validate_error(too_close, ApiErrorId.ERR_WINDOW_OVERLAP, 409)

    def test_window_inside_gap_buffer_rejected_despite_no_overlap(self, api):
        """PRD §3.1: "Windows on the same stand must be disjoint **and** separated
        by at least fifteen minutes"

        Design: Difficulty/resource_temporal_overlap/throughput_window_gap_buffer_semantics
        """
        region = create_region()
        stand = create_stand(region["id"])
        _create_window(
            api, stand["id"],
            starts_at="2026-09-01T07:00:00Z",
            ends_at="2026-09-01T08:00:00Z",
            target_cars=5,
        )
        # Geometrically disjoint (08:05 > 08:00) but only 5 minutes after.
        resp = api.create_window(
            create_window_payload(
                stand["id"],
                starts_at="2026-09-01T08:05:00Z",
                ends_at="2026-09-01T08:10:00Z",
                target_cars=2,
            ),
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP, 409)


class TestWindowClosability:
    def test_window_close_before_end_rejected(self, api):
        """PRD §3.1: "A window may be closed only once the logical clock has
        reached its `ends_at` (earlier attempts fail with
        `ERR_WINDOW_NOT_CLOSABLE`) and only while it is `OPEN` (otherwise
        `ERR_WINDOW_INVALID_STATE`)."
        PRD §3.1: "If `served_count` is at least `target_cars`, the window closes
        as `CLOSED_PASS` and the stand's `consecutive_breach_windows` resets to
        zero"

        Design: Corner/errors/window_close_before_end_rejected
        """
        set_clock("2026-09-01T06:00:00Z")
        region = create_region()
        stand = create_stand(region["id"])
        window = _create_window(
            api, stand["id"],
            starts_at="2026-09-01T07:00:00Z",
            ends_at="2026-09-01T08:00:00Z",
            target_cars=0,
        )
        set_clock("2026-09-01T07:30:00Z")
        early = api.close_window(window["id"], RM)
        validate_error(early, ApiErrorId.ERR_WINDOW_NOT_CLOSABLE, 409)

        set_clock("2026-09-01T08:00:00Z")
        closed = validate_success(api.close_window(window["id"], RM), 200)
        assert closed["status"] == "CLOSED_PASS", (
            f"target 0 with 0 served passes (0 >= 0), got {closed['status']}"
        )
        assert closed["served_count"] == 0

    def test_window_close_at_exact_ends_at_succeeds(self, api):
        """PRD §3.1: "A window may be closed only once the logical clock has
        reached its `ends_at` (earlier attempts fail with
        `ERR_WINDOW_NOT_CLOSABLE`)"

        Design: Corner/errors/window_close_before_end_rejected
        """
        set_clock("2026-09-01T06:00:00Z")
        region = create_region()
        stand = create_stand(region["id"])
        window = _create_window(
            api, stand["id"],
            starts_at="2026-09-01T07:00:00Z",
            ends_at="2026-09-01T08:00:00Z",
            target_cars=3,
        )
        set_clock("2026-09-01T08:00:00Z")
        closed = validate_success(api.close_window(window["id"], RM), 200)
        assert closed["served_count"] == 0
        assert closed["status"] == "CLOSED_BREACH", (
            f"0 served against target 3 breaches, got {closed['status']}"
        )


class TestProvisionalVsFinalAttainment:
    def test_throughput_provisional_projection_diverges_from_final_served_count(
        self, api
    ):
        """PRD §3.1: "While a window is open, any read of it reports
        `provisional_projected_cars`, a forward-looking figure: the count of
        orders at the stand already handed off within the window's half-open
        bounds (from `starts_at` inclusive to `ends_at` exclusive) **plus** the
        orders at that stand still in flight with `queue_status` of `QUEUED`,
        `MERGED`, or `AT_WINDOW`. Because the in-flight queue is included, the
        projection can meet or exceed the target while the final count still
        breaches."
        PRD §3.1: "At close the provisional view is discarded and `served_count`
        is computed chronologically: the count of orders at the stand whose
        `handoff_at` falls within the half-open window bounds."

        Design: Difficulty/dual_variant_calc/throughput_provisional_projection_diverges_from_final_served_count
        """
        ctx = setup_open_stand_with_menu()
        window = _create_window(
            api, ctx["stand"]["id"],
            starts_at="2026-09-01T07:00:00Z",
            ends_at="2026-09-01T08:00:00Z",
            target_cars=2,
        )
        # Order 1: fully served inside the window (handoff at 07:05).
        served = serve_window_order(
            ctx, ctx["recipe"]["id"], lane_code="A", handoff_clock="2026-09-01T07:05:00Z"
        )
        # Order 2: left MERGED and unpaid — in flight at close.
        place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")

        open_window = validate_success(api.get_window(window["id"], RM), 200)
        assert open_window["provisional_projected_cars"] == 2, (
            f"1 served + 1 in flight must project 2, got {open_window['provisional_projected_cars']}"
        )

        set_clock("2026-09-01T08:00:00Z")
        closed = validate_success(api.close_window(window["id"], RM), 200)
        assert closed["served_count"] == 1, (
            f"final count excludes the in-flight order, got {closed['served_count']}"
        )
        assert closed["status"] == "CLOSED_BREACH", "1 < target 2"
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["consecutive_breach_windows"] == 1

    def test_provisional_counts_in_flight_while_final_counts_only_handoffs(self, api):
        """PRD §3.1: "At close the provisional view is discarded and `served_count`
        is computed chronologically: the count of orders at the stand whose
        `handoff_at` falls within the half-open window bounds. If `served_count`
        is at least `target_cars`, the window closes as `CLOSED_PASS` and the
        stand's `consecutive_breach_windows` resets to zero; otherwise it closes
        as `CLOSED_BREACH` and the counter increments by one."

        Design: Difficulty/dual_variant_calc/throughput_provisional_projection_diverges_from_final_served_count
        """
        ctx = setup_open_stand_with_menu()
        window = _create_window(
            api, ctx["stand"]["id"],
            starts_at="2026-09-01T07:00:00Z",
            ends_at="2026-09-01T08:00:00Z",
            target_cars=2,
        )
        serve_window_order(
            ctx, ctx["recipe"]["id"], lane_code="A", handoff_clock="2026-09-01T07:05:00Z"
        )
        place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        projected = validate_success(api.get_window(window["id"], RM), 200)[
            "provisional_projected_cars"
        ]
        set_clock("2026-09-01T08:00:00Z")
        closed = validate_success(api.close_window(window["id"], RM), 200)
        assert projected == 2 and closed["served_count"] == 1, (
            f"provisional {projected} must diverge from final {closed['served_count']}"
        )


class TestWindowCloseBoundary:
    def test_window_close_at_exact_target_count_passes(self, api):
        """PRD §3.1: "If `served_count` is at least `target_cars`, the window
        closes as `CLOSED_PASS` and the stand's `consecutive_breach_windows`
        resets to zero; otherwise it closes as `CLOSED_BREACH` and the counter
        increments by one."

        Design: Difficulty/boundary_precision_check/window_close_at_exact_target_count_passes
        """
        ctx = setup_open_stand_with_menu()
        window = _create_window(
            api, ctx["stand"]["id"],
            starts_at="2026-09-01T07:00:00Z",
            ends_at="2026-09-01T08:00:00Z",
            target_cars=1,
        )
        serve_window_order(
            ctx, ctx["recipe"]["id"], lane_code="A", handoff_clock="2026-09-01T07:30:00Z"
        )
        set_clock("2026-09-01T08:00:00Z")
        closed = validate_success(api.close_window(window["id"], RM), 200)
        assert closed["served_count"] == 1
        assert closed["status"] == "CLOSED_PASS", (
            "the comparison is inclusive: served == target passes"
        )
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["consecutive_breach_windows"] == 0

    def test_one_below_target_count_breaches(self, api):
        """PRD §3.1: "otherwise it closes as `CLOSED_BREACH` and the counter
        increments by one."

        Design: Difficulty/boundary_precision_check/window_close_at_exact_target_count_passes
        """
        ctx = setup_open_stand_with_menu()
        window = _create_window(
            api, ctx["stand"]["id"],
            starts_at="2026-09-01T07:00:00Z",
            ends_at="2026-09-01T08:00:00Z",
            target_cars=2,
        )
        serve_window_order(
            ctx, ctx["recipe"]["id"], lane_code="A", handoff_clock="2026-09-01T07:30:00Z"
        )
        set_clock("2026-09-01T08:00:00Z")
        closed = validate_success(api.close_window(window["id"], RM), 200)
        assert closed["served_count"] == 1
        assert closed["status"] == "CLOSED_BREACH", (
            "target 2 with 1 served (target - 1) must breach"
        )
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["consecutive_breach_windows"] == 1


class TestProvisionalInputSet:
    def test_throughput_provisional_excludes_abandoned_orders(self, api):
        """PRD §3.1: "While a window is open, any read of it reports
        `provisional_projected_cars`, a forward-looking figure: the count of
        orders at the stand already handed off within the window's half-open
        bounds (from `starts_at` inclusive to `ends_at` exclusive) **plus** the
        orders at that stand still in flight with `queue_status` of `QUEUED`,
        `MERGED`, or `AT_WINDOW`."

        Design: Corner/calculations/throughput_provisional_excludes_abandoned_orders
        """
        ctx = setup_open_stand_with_menu()
        window = _create_window(
            api, ctx["stand"]["id"],
            starts_at="2026-09-01T07:00:00Z",
            ends_at="2026-09-01T08:00:00Z",
            target_cars=9,
        )
        kept = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        dropped = place_window_order(ctx, ctx["recipe"]["id"], lane_code="B")
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.abandon_order(dropped["id"], lead), 200)

        open_window = validate_success(api.get_window(window["id"], RM), 200)
        assert open_window["provisional_projected_cars"] == 1, (
            f"only the MERGED order counts; ABANDONED is excluded, "
            f"got {open_window['provisional_projected_cars']}"
        )

    def test_provisional_projection_zero_when_queue_empty(self, api):
        """PRD §3.1: "**plus** the orders at that stand still in flight with
        `queue_status` of `QUEUED`, `MERGED`, or `AT_WINDOW`."

        Design: Corner/calculations/throughput_provisional_excludes_abandoned_orders
        """
        ctx = setup_open_stand_with_menu()
        window = _create_window(
            api, ctx["stand"]["id"],
            starts_at="2026-09-01T07:00:00Z",
            ends_at="2026-09-01T08:00:00Z",
            target_cars=9,
        )
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="B")
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.abandon_order(order["id"], lead), 200)
        open_window = validate_success(api.get_window(window["id"], RM), 200)
        assert open_window["provisional_projected_cars"] == 0, (
            "with the only order ABANDONED the in-flight set is empty"
        )
