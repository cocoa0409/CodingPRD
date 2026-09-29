"""Two contended resources with deliberately opposite interval semantics.

PRD 3.2: a published board window is half-open, and "because the windows are
half-open two cards whose windows merely touch at an endpoint - one ending exactly
where the next begins - do not intersect and both may be published".
PRD 2.8 rank 10: a route window "must be separated from every other scheduled or
in-transit window on the same route by at least 45 minutes - transport windows are
closed, including both window_start and window_end, so windows that merely touch do
conflict".
"""

from test_helpers import (
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)


def _board_world(api):
    """A branch whose EUR board already carries a PUBLISHED card over
    [2026-08-01, 2026-08-15)."""
    branch = fx.register_branch(api, vault_limit_usd_cents=20_000_000)
    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)
    incumbent = fx.published_rate_card(
        api,
        branch["id"],
        wholesale["id"],
        board_display_label="EUR Euro window 1",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-08-15T00:00:00Z",
    )
    assert incumbent["status"] == "PUBLISHED"
    return {"branch": branch, "wholesale": wholesale, "incumbent": incumbent}


def test_a_board_window_overlapping_the_incumbent_by_five_days_cannot_publish(
    api, treasury_headers
):
    """A card over [2026-08-10, 2026-08-20) intersects the incumbent's half-open
    window, so publishing it is refused with ERR_RATE_WINDOW_OVERLAP and it stays
    DRAFT while the incumbent keeps its 2026-08-15 close.

    Design: Difficulty/resource_temporal_overlap/rate_card_board_window_half_open_touching_endpoints_allowed
    """
    world = _board_world(api)
    overlapping = fx.draft_rate_card(
        api,
        world["branch"]["id"],
        world["wholesale"]["id"],
        board_display_label="EUR Euro overlapping",
        effective_from="2026-08-10T00:00:00Z",
        effective_to="2026-08-20T00:00:00Z",
    )

    validate_error(
        api.publish_rate_card(overlapping["id"], treasury_headers),
        ApiErrorId.ERR_RATE_WINDOW_OVERLAP,
    )

    still_draft = validate_success(
        api.get_rate_card(overlapping["id"], treasury_headers)
    )
    a.assert_rate_card(still_draft)
    assert still_draft["status"] == "DRAFT"
    assert still_draft["published_at"] is None

    incumbent = validate_success(
        api.get_rate_card(world["incumbent"]["id"], treasury_headers)
    )
    assert incumbent["status"] == "PUBLISHED"
    a.assert_timestamp_equals(incumbent["effective_to"], "2026-08-15T00:00:00Z")


def test_board_windows_that_touch_at_an_endpoint_both_publish(api, treasury_headers, teller_headers):
    """A card opening at exactly 2026-08-15T00:00:00Z - the instant the incumbent's
    window closes - publishes, as does one closing exactly at the incumbent's
    2026-08-01 open, and at a clock of 2026-08-15 the board shows the successor line
    rather than the incumbent.

    Design: Difficulty/resource_temporal_overlap/rate_card_board_window_half_open_touching_endpoints_allowed
    """
    world = _board_world(api)

    successor = fx.published_rate_card(
        api,
        world["branch"]["id"],
        world["wholesale"]["id"],
        board_display_label="EUR Euro window 2",
        effective_from="2026-08-15T00:00:00Z",
        effective_to="2026-08-25T00:00:00Z",
    )
    assert successor["status"] == "PUBLISHED"

    predecessor = fx.published_rate_card(
        api,
        world["branch"]["id"],
        world["wholesale"]["id"],
        board_display_label="EUR Euro window 0",
        effective_from="2026-07-20T00:00:00Z",
        effective_to="2026-08-01T00:00:00Z",
    )
    assert predecessor["status"] == "PUBLISHED"

    fx.set_clock(api, "2026-08-15T00:00:00Z")
    board = fx.read_board(api, world["branch"]["id"], teller_headers)

    a.assert_rate_board(board)
    a.assert_timestamp_equals(board["as_of"], "2026-08-15T00:00:00Z")
    assert board["line_count"] == 1
    assert board["lines"][0]["board_display_label"] == "EUR Euro window 2"


def _route_day_world(api):
    """One southern route holding a 09:00-10:00 booking of 43478 cents, plus two
    unscheduled shipments worth 43478 and 130435 cents."""
    branch = fx.register_branch(api, code="BR-CDG", name="Paris CDG")
    fx.register_currency(api)
    fx.record_wholesale_rate(api)
    route = fx.register_route(api, daily_capacity_usd_cents=200_000)
    first = fx.raise_shipment(api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 4)])
    fx.schedule_shipment(
        api, first["id"], route["id"], "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"
    )
    second = fx.raise_shipment(api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 4)])
    third = fx.raise_shipment(api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 12)])
    assert third["manifest_usd_equivalent_cents"] == 130435
    return {"branch": branch, "route": route, "first": first, "second": second, "third": third}


def test_a_touching_transport_window_conflicts_and_exactly_45_minutes_does_not(
    api, treasury_headers
):
    """Booking 10:00-11:00 against the closed 09:00-10:00 incumbent leaves a
    zero-minute gap and is refused with ERR_ROUTE_WINDOW_CONFLICT, while the same
    shipment moved to 10:45-11:45 - exactly the 45-minute separation - is SCHEDULED.

    Design: Difficulty/resource_temporal_overlap/armored_route_closed_window_gap_buffer_and_day_capacity
    """
    world = _route_day_world(api)

    validate_error(
        api.schedule_cash_shipment(
            world["second"]["id"],
            f.schedule_shipment_payload(
                world["route"]["id"], "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT,
    )
    assert fx.read_shipment(api, world["second"]["id"])["status"] == "REQUESTED"

    scheduled = fx.schedule_shipment(
        api,
        world["second"]["id"],
        world["route"]["id"],
        "2026-08-05T10:45:00Z",
        "2026-08-05T11:45:00Z",
    )
    a.assert_cash_shipment(scheduled)
    assert scheduled["status"] == "SCHEDULED"
    a.assert_timestamp_equals(scheduled["window_start"], "2026-08-05T10:45:00Z")
    a.assert_timestamp_equals(scheduled["window_end"], "2026-08-05T11:45:00Z")


def test_a_gap_respecting_booking_still_fails_the_routes_day_capacity(api, treasury_headers):
    """A third shipment at 12:30-13:30 is 45 minutes clear of the 10:45-11:45 booking
    and is still refused with ERR_ROUTE_CAPACITY_EXCEEDED, because 43478 + 43478 +
    130435 = 217391 overruns the route's 200000-cent day; the route itself is untouched.

    Design: Difficulty/resource_temporal_overlap/armored_route_closed_window_gap_buffer_and_day_capacity
    """
    world = _route_day_world(api)
    fx.schedule_shipment(
        api,
        world["second"]["id"],
        world["route"]["id"],
        "2026-08-05T10:45:00Z",
        "2026-08-05T11:45:00Z",
    )

    validate_error(
        api.schedule_cash_shipment(
            world["third"]["id"],
            f.schedule_shipment_payload(
                world["route"]["id"], "2026-08-05T12:30:00Z", "2026-08-05T13:30:00Z"
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED,
    )

    untouched = fx.read_shipment(api, world["third"]["id"])
    assert untouched["status"] == "REQUESTED"
    assert untouched["armored_route_id"] is None

    route = validate_success(api.get_armored_route(world["route"]["id"], treasury_headers))
    assert route["daily_capacity_usd_cents"] == 200000
