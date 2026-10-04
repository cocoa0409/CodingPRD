"""Breadth coverage for endpoint behaviours and action-endpoint idempotence."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_freeze_in_state,
    create_itinerary,
    create_route,
    get_success_data,
    observe,
    publish_curve,
    read_freeze,
    read_itinerary,
    read_route,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_third_activation_after_the_freeze_is_frozen_is_refused():
    """PRD §3.3: "A second activation against a fully-custodied freeze drives it
    to `FROZEN`, and a freeze still `HELD` when its expiry passes is driven to
    `FROZEN` by the scheduled sweep instead".

    Design: Corner/endpoints/corner_action_endpoint_refuses_a_repeated_activation
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    assert freeze["status"] == "FROZEN"
    reserved = read_route(route["id"])["reserved_exposure_cents"]

    res = api_client.activate_freeze(freeze["id"], {"expected_freeze_version": freeze["version"]},
                                     TEST_USERS["traveler_headers"])
    assert res.status_code >= 400, "the activation endpoint is not idempotent"
    unchanged = read_freeze(freeze["id"])
    assert unchanged["status"] == "FROZEN"
    assert unchanged["version"] == freeze["version"], (
        "the refused call did not advance the freeze's version"
    )
    assert read_route(route["id"])["reserved_exposure_cents"] == pytest.approx(reserved, abs=0.02), (
        "the reservation was booked exactly once"
    )


def test_nested_and_flat_freeze_creation_both_bind_to_the_named_itinerary():
    """PRD §2.4: "The resource hierarchy is flat. Child resources reference
    their parents through an identifier field rather than a nested path, and the
    API never models containment by URL depth."

    Design: Corner/endpoints/corner_nested_creation_endpoints_place_the_child_under_the_named_parent
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    headers = TEST_USERS["traveler_headers"]

    nested = validate_success(
        api_client.open_freeze(
            itinerary["id"],
            {"deposit_cents": 250, "disclosure_version": 1, "disclosure_acknowledged": True,
             "expected_itinerary_version": itinerary["version"]},
            headers),
        201,
    )
    refreshed = read_itinerary(itinerary["id"])
    flat = validate_success(
        api_client.open_freeze_flat(
            {"itinerary_id": itinerary["id"], "deposit_cents": 300, "disclosure_version": 1,
             "disclosure_acknowledged": True,
             "expected_itinerary_version": refreshed["version"]},
            headers),
        201,
    )
    assert nested["itinerary_id"] == itinerary["id"]
    assert flat["itinerary_id"] == itinerary["id"]

    page, meta = validate_paginated(
        api_client.list_itinerary_freezes(itinerary["id"], headers)
    )
    assert meta["total_count"] == 2
    assert all(row["itinerary_id"] == itinerary["id"] for row in page)


def test_the_pagination_defaults_bound_the_limit_range_on_the_route_list():
    """PRD §2.3: "`limit` caps how many items are returned in one page; it
    defaults to 10, and may be set no lower than 1 and no higher than 100."

    Design: Corner/endpoints/corner_pagination_bounds_are_enforced_on_the_route_list
    """
    set_clock()
    create_route()
    # `limit` is clamped into its permitted band ["no lower than 1 and no higher
    # than 100"], so the bounds are enforced by clamping, not by an error.
    zero = api_client.list_routes(TEST_USERS["ops_headers"], params={"limit": 0})
    assert zero.status_code == 200
    _, zero_meta = validate_paginated(zero)
    assert zero_meta["limit"] == 1
    over = api_client.list_routes(TEST_USERS["ops_headers"], params={"limit": 101})
    assert over.status_code == 200
    _, over_meta = validate_paginated(over)
    assert over_meta["limit"] == 100

    page, meta = validate_paginated(
        api_client.list_routes(TEST_USERS["ops_headers"], params={"limit": 1, "offset": 0})
    )
    assert len(page) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_the_clock_sweep_expires_a_freeze_once_its_window_has_passed():
    """PRD §2.13: "Advancing the clock is what expires freezes past their
    `freeze_expires_at`".

    Design: Corner/endpoints/corner_clock_advance_runs_the_sweep_but_leaves_the_default_absent
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    assert freeze["freeze_expires_at"] == "2026-09-15T00:00:00.000Z", (
        "the window is the activation instant plus fourteen days on the logical clock"
    )
    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-16T00:00:00Z"},
                                              TEST_USERS["admin_headers"]))
    assert read_freeze(freeze["id"])["status"] == "EXPIRED"


def test_setting_the_clock_returns_no_resource_payload():
    """PRD §2.8: "The function is stateless and order-independent" PRD §2.2:
    "For 2xx responses with no data, it contains an empty object."

    Design: Corner/endpoints/corner_clock_advance_runs_the_sweep_but_leaves_the_default_absent
    """
    set_clock()
    response = api_client.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"},
                                    TEST_USERS["admin_headers"])
    body = response.json()
    assert response.status_code == 200
    assert body["response_type"] == "object"
    assert body["data"] in ({}, None)
    assert is_present(body["meta"]["api_request_id"])


def is_present(value) -> bool:
    return isinstance(value, str) and len(value) > 0
