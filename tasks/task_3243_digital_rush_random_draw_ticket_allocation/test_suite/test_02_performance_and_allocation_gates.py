"""Performance scheduling, allocation readiness and the lifecycle gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
)
from test_helpers import constants as C
from test_helpers import fixtures as X


def _queue_rows(api, performance_id):
    data = get_success_data(api.list_queue_positions(
        performance_id, X.OPS, params={"limit": 100}))
    return data.get("data", data) if isinstance(data, dict) else data


def test_scheduling_a_released_allocation_is_refused_and_stamps_nothing(api):
    """PRD §3.2: "The move is `DRAFT` to `SCHEDULED` and is available while the
    performance is in `SCHEDULED` or `ONSALE`."
    PRD §2.6: "Second, the transition test: the target row must be in a state
    from which the requested move is defined, and a row that is not receives
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/allocation_scheduling_from_released_returns_invalid_state
    """
    production, performance, allocation = X.setup_released_allocation()
    released = X.get_allocation(performance, allocation["id"])
    assert released["status"] == "RELEASED"

    response = api.schedule_allocation(
        released["id"],
        {"expected_allocation_version": released["version"]},
        X.COORD,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    after = X.get_allocation(performance, released["id"])
    assert after["status"] == "RELEASED", \
        "the rejected call must leave the allocation RELEASED"
    assert after["quantity_released_today"] == 6, \
        "the released counters must be untouched by the rejected call"


def test_release_requires_the_performance_to_be_on_sale(api):
    """PRD §3.3: "Three states must line up simultaneously. The allocation
    itself must be `SCHEDULED`; the performance must be `ONSALE`; and the
    production behind the performance must be `ACTIVE`. A partnership that has
    been suspended between scheduling and release stops the release, and so does
    a performance that has not yet gone on sale."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_allocation_release_requires_performance_onsale
    """
    production, performance, allocation = X.setup_scheduled_allocation(
        on_sale=False, daily_quantity=5, per_order_limit=2,
    )

    response = api.release_allocation(
        allocation["id"], C.BASE_CLOCK_DAY,
        {"expected_production_version": production["version"],
         "expected_performance_version": performance["version"],
         "expected_allocation_version": allocation["version"]},
        X.OPS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    blocked = X.get_allocation(performance, allocation["id"])
    assert blocked["status"] == "SCHEDULED", \
        "the guard must fire before any release stamping"
    assert blocked["quantity_released_today"] == 0


def test_release_succeeds_once_the_performance_goes_on_sale(api):
    """PRD §3.3: "An allocation that has been scheduled still sells nothing
    until an `OpsManager` releases it on its epoch."
    PRD §3.2: "Going on sale is what makes the performance's rush allocations
    eligible for release."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_allocation_release_requires_performance_onsale
    """
    production, performance, allocation = X.setup_scheduled_allocation(
        on_sale=False, daily_quantity=5, per_order_limit=2,
    )

    on_sale = X.move_performance(performance, "ONSALE")
    released = X.release_allocation(allocation, production, on_sale)

    assert released["status"] == "RELEASED", \
        f"the same release call must succeed once on sale, got {released['status']}"
    assert released["quantity_released_today"] == 5, \
        f"expected five seats opened, got {released['quantity_released_today']}"


def test_cancelling_a_performance_is_terminal_for_further_moves(api):
    """PRD §3.2: "Attempting to cancel a performance that is already `CANCELLED`
    is refused with `ERR_INVALID_STATE` (HTTP 409), and the important property of
    that refusal is that none of the cascades fire a second time — a cancelled
    performance's inventory is not re-swept."
    PRD §3.2: "Cancellation is available out of `SCHEDULED` or `ONSALE` and is
    the only terminal state a performance has."

    Design: Corner/state_machines/performance_cancellation_is_terminal_for_further_lifecycle_moves
    """
    production, performance, allocation = X.setup_released_allocation(
        daily_quantity=5, per_order_limit=2,
    )
    cancelled = X.cancel_performance(performance)
    assert cancelled["status"] == "CANCELLED"
    closed_once = X.get_allocation(performance, allocation["id"])
    assert closed_once["status"] == "CLOSED", \
        "cancellation must sweep the allocation to CLOSED"

    repeat = api.transition_performance(
        performance["id"],
        {"to_status": "CANCELLED",
         "expected_performance_version": cancelled["version"]},
        X.OPS,
    )
    validate_error(repeat, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    back_on_sale = api.transition_performance(
        performance["id"],
        {"to_status": "ONSALE",
         "expected_performance_version": cancelled["version"]},
        X.OPS,
    )
    validate_error(back_on_sale, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    still = X.get_performance(performance["id"])
    assert still["status"] == "CANCELLED"
    assert X.get_allocation(performance, allocation["id"])["status"] == "CLOSED"


def test_unknown_market_code_is_a_body_reference_failure(api):
    """PRD §3.2: "The `market_code` supplied must be the code of a market the
    platform already knows, and an unrecognised code is rejected with
    `ERR_REFERENCE_NOT_FOUND` (HTTP 404) — this is a body-reference failure, so
    it is reported only after the path has fully resolved."

    Design: Corner/entities/performance_creation_rejects_unknown_market_code
    """
    X.set_clock(C.BASE_CLOCK)
    production = X.activate_production(X.register_production())

    response = api.create_performance(
        {
            "production_id": production["id"],
            "market_code": "ZZZ",
            "venue_name": "Nowhere",
            "starts_at": "2026-10-05T19:00:00Z",
            "face_value_cents": 10000,
            "total_seat_capacity": 20,
        },
        X.OPS,
    )
    validate_error(response, ApiErrorId.ERR_REFERENCE_NOT_FOUND, expected_status=404)


def test_unknown_performance_id_reports_the_entity_specific_error(api):
    """PRD §2.6: "Every resource named in a path segment must resolve, walked
    left to right, and a miss yields the 404 error that names that resource
    type: an unresolvable production segment is `ERR_PRODUCTION_NOT_FOUND`, a
    performance `ERR_PERFORMANCE_NOT_FOUND`."

    Design: Corner/endpoints/performance_get_with_an_unknown_id_returns_performance_not_found
    """
    X.set_clock(C.BASE_CLOCK)

    response = api.get_performance(C.NON_EXISTENT_PERFORMANCE_ID, X.PRODUCER)
    error = validate_error(response, ApiErrorId.ERR_PERFORMANCE_NOT_FOUND,
                           expected_status=404)

    assert response.json()["response_type"] == "error"
    assert response.json()["meta"]["api_request_id"]
    assert error["message"], "an error response carries a human-readable explanation"


def test_unknown_performance_id_is_reported_on_the_path_rung(api):
    """PRD §2.6: "Rungs three and four — existence. Every resource named in a
    path segment must resolve, walked left to right, and a miss yields the 404
    error that names that resource type."
    PRD §2.4: "Every resource in the system is identified by an `id`: a
    server-minted UUID string with no embedded type prefix."

    Design: Corner/validations/performance_get_with_an_unknown_id_is_entity_specific_404
    """
    X.set_clock(C.BASE_CLOCK)

    response = api.get_performance(C.NON_EXISTENT_PERFORMANCE_ID, X.DESK)
    validate_error(response, ApiErrorId.ERR_PERFORMANCE_NOT_FOUND, expected_status=404)