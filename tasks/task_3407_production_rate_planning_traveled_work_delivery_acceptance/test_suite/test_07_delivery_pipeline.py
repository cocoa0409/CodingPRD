"""Delivery acceptance pipeline: flight tests, configuration, walkthrough (PRD §3.8)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_customer_headers, make_quality_inspector_headers,
    api_client,
    schedule_flight_test_payload, record_outcome_payload, conduct_walkthrough_payload,
    begin_root_cause_payload, disposition_payload,
    create_customer,
    setup_aircraft, add_work_package, complete_work_package, begin_delivery,
    setup_aircraft_in_flight_testing, schedule_flight_test, schedule_and_pass_flight_test,
    setup_aircraft_config_verified,
    create_open_escape, create_escape_in_root_cause,
    close_rework_order,
    setup_negotiation, counter_negotiation,
)

QI1 = make_quality_inspector_headers("insp-1")
QI2 = make_quality_inspector_headers("insp-2")


def test_flight_test_window_end_not_after_start_rejected(api, delivery_manager_headers):
    """PRD §3.8: "the `window_end` must fall strictly after `window_start`
    (`ERR_WINDOW_INVALID`, 422)".

    Design: Corner/validations/flight_test_window_end_not_after_start_rejected
    """
    _program, _customer, aircraft = setup_aircraft_in_flight_testing(line_number=1015)
    resp = api_client.schedule_flight_test(
        aircraft["id"],
        schedule_flight_test_payload(
            range_code="RANGE_ALPHA",
            window_start="2026-10-02T09:00:00Z",
            window_end="2026-10-02T09:00:00Z",
        ),
        delivery_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID)


def test_flight_test_record_outcome_twice_rejected(api, delivery_manager_headers):
    """PRD §3.8: "Recording an outcome (`SCHEDULED` → `COMPLETED`) takes an `outcome` of
    `PASS` or `FAIL`."
    PRD §2.8: "the requested transition must exist from the resource's current state,
    including terminal-state lockdown and the delivery-pipeline stage gates
    (`ERR_INVALID_TRANSITION`, 409)".

    Design: Corner/state_machines/flight_test_record_outcome_twice_rejected
    """
    _program, _customer, aircraft = setup_aircraft_in_flight_testing(line_number=1006)
    flight_test = schedule_flight_test(aircraft["id"])
    flight_test = validate_success(
        api_client.record_flight_test_outcome(
            flight_test["id"], record_outcome_payload("PASS"), delivery_manager_headers
        )
    )
    assert flight_test["outcome"] == "PASS"
    assert flight_test["status"] == "COMPLETED"

    resp = api_client.record_flight_test_outcome(
        flight_test["id"],
        record_outcome_payload("FAIL", rework_estimated_hours=5),
        delivery_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
    tests, meta = validate_paginated(
        api_client.list_flight_tests(aircraft["id"], delivery_manager_headers)
    )
    assert meta["total_count"] == 1
    assert tests[0]["outcome"] == "PASS", "the rejected second recording changes nothing"
    assert tests[0]["status"] == "COMPLETED"


def test_verify_configuration_mismatch_rejected_after_state_gate_passes(api, delivery_manager_headers):
    """PRD §3.8: "Configuration verification (`FLIGHT_TESTING` → `CONFIG_VERIFIED`) demands
    a clean flight-test record: at least one flight test of the aircraft is `COMPLETED`,
    every `COMPLETED` test carries outcome `PASS`, and no `SCHEDULED` test may remain —
    shortfalls are stage violations rejected with `ERR_INVALID_TRANSITION`."
    PRD §3.8: "It also demands that the as-built `configuration_code` equals the contracted
    `ordered_configuration_code`; a mismatch is `ERR_CONFIGURATION_MISMATCH` (HTTP 422)."

    Design: Corner/state_machines/verify_configuration_mismatch_rejected_after_state_gate_passes
    """
    _program, _customer, aircraft = setup_aircraft(
        line_number=1010, aircraft_overrides={"ordered_configuration_code": "CFG-B"}
    )
    work_package = add_work_package(aircraft["id"], planned_hours=5)
    complete_work_package(work_package["id"])
    begin_delivery(aircraft["id"])
    schedule_and_pass_flight_test(aircraft["id"])
    # State gate satisfied (FLIGHT_TESTING, one PASS test); codes CFG-A != CFG-B.
    resp = api_client.verify_configuration(aircraft["id"], delivery_manager_headers)
    validate_error(resp, ApiErrorId.ERR_CONFIGURATION_MISMATCH)


def test_walkthrough_snags_reject_delivery_and_retry_cycle_reopens(api, delivery_manager_headers):
    """PRD §3.8: "One or more snags reject it: `CONFIG_VERIFIED` → `REJECTED`, and a rework
    order with `source` `WALKTHROUGH_SNAG` is created on a hours basis of four hours per
    snag, provisionally priced per §3.5."
    PRD §3.8: "after a rejection, the same action retries the pipeline (`REJECTED` →
    `FLIGHT_TESTING`), but the retry is gated on there being no `OPEN` rework order left on
    the aircraft — attempting the retry while one remains is rejected with
    `ERR_INVALID_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/walkthrough_snags_reject_delivery_and_retry_cycle_reopens
    """
    _program, customer, aircraft, _ft = setup_aircraft_config_verified(line_number=1009)
    aircraft = validate_success(
        api_client.conduct_walkthrough(
            aircraft["id"], conduct_walkthrough_payload(2),
            make_customer_headers(customer["id"]),
        )
    )
    assert aircraft["delivery_status"] == "REJECTED"

    orders, meta = validate_paginated(
        api_client.list_aircraft_rework_orders(aircraft["id"], delivery_manager_headers)
    )
    assert meta["total_count"] == 1, "exactly one snag rework order spawned"
    order = orders[0]
    assert order["source"] == "WALKTHROUGH_SNAG"
    assert order["estimated_cost_cents"] == 120000, "2 snags x 4 hours x 15000 x 1.0"

    close_rework_order(order["id"], actual_hours=8, parts_cents=0)
    aircraft = validate_success(api_client.begin_delivery(aircraft["id"], delivery_manager_headers))
    assert aircraft["delivery_status"] == "FLIGHT_TESTING", (
        "with no OPEN rework left, begin-delivery retries the pipeline"
    )


def test_customer_cannot_record_flight_test_outcomes(api):
    """PRD §2.1: "`DeliveryManager` runs flight tests, storage and preservation, the opening
    and configuration stages of the delivery pipeline, and the airframer side of delivery
    negotiations."
    PRD §2.1: "Attempting an operation outside one's role is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_record_flight_test_outcomes
    """
    _program, customer, aircraft = setup_aircraft_in_flight_testing(line_number=1024)
    flight_test = schedule_flight_test(aircraft["id"])
    resp = api_client.record_flight_test_outcome(
        flight_test["id"], record_outcome_payload("PASS"),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_customer_walkthrough_ownership_mismatch_rejected(api, admin_headers):
    """PRD §3.8: "The customer's walkthrough comes next, performed by the buying `Customer`
    — `X-User-ID` must equal the aircraft's `customer_id` — with a `snag_count` payload."
    PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
    Customer: on customer-scoped writes — the walkthrough, delivery acceptance, and the
    customer side of a negotiation — the comparison is against the `customer_id` of the
    aircraft concerned."

    Design: Corner/rbac/customer_walkthrough_ownership_mismatch_rejected
    """
    _program, _customer, aircraft, _ft = setup_aircraft_config_verified(line_number=1025)
    other_customer = create_customer(
        airline_code="AL2", name="Air Two", credit_standing="WATCH"
    )
    resp = api_client.conduct_walkthrough(
        aircraft["id"], conduct_walkthrough_payload(0),
        make_customer_headers(other_customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_flight_test_blocked_by_quality_hold_then_allowed(api, delivery_manager_headers):
    """PRD §3.8: "the aircraft must be in `FLIGHT_TESTING` (a pipeline-stage violation is
    `ERR_INVALID_TRANSITION`, 409); its `quality_status` must be `CLEAR`
    (`ERR_QUALITY_HOLD`, 409)".
    PRD §3.6: "the escape lands in `OPEN`, the aircraft's `quality_status` moves immediately
    to `HOLD`, and the program's `open_escape_count` and `posture` are recomputed."
    PRD §3.6: "The close recomputes the program's `open_escape_count`, returns the
    aircraft's `quality_status` to `CLEAR` when no escape on it remains in `OPEN`,
    `ROOT_CAUSE`, or `DISPOSITIONED`, and recomputes the program's `posture`."

    Design: Difficulty/cross_entity_state_dependency/flight_test_blocked_by_quality_hold_then_allowed
    """
    _program, _customer, aircraft = setup_aircraft_in_flight_testing(line_number=4002)
    escape = create_open_escape(
        aircraft["id"], severity="MAJOR", description="Hydraulic seep"
    )
    resp = api_client.schedule_flight_test(
        aircraft["id"], schedule_flight_test_payload(), delivery_manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_QUALITY_HOLD)

    get_success_data(api_client.notify_regulator(escape["id"], QI1))
    get_success_data(api_client.begin_root_cause(escape["id"], begin_root_cause_payload(["DOC-2"]), QI1))
    get_success_data(api_client.disposition_escape(escape["id"], disposition_payload("USE_AS_IS"), QI2))
    get_success_data(api_client.close_escape(escape["id"], QI2))

    flight_test = validate_success(
        api_client.schedule_flight_test(
            aircraft["id"], schedule_flight_test_payload(), delivery_manager_headers
        ),
        201,
    )
    assert flight_test["status"] == "SCHEDULED"


def test_flight_test_still_blocked_while_escape_in_root_cause(api, delivery_manager_headers):
    """PRD §3.8: "its `quality_status` must be `CLEAR` (`ERR_QUALITY_HOLD`, 409)".
    PRD §3.6: "The close recomputes the program's `open_escape_count`, returns the
    aircraft's `quality_status` to `CLEAR` when no escape on it remains in `OPEN`,
    `ROOT_CAUSE`, or `DISPOSITIONED`, and recomputes the program's `posture`."

    Design: Difficulty/cross_entity_state_dependency/flight_test_blocked_by_quality_hold_then_allowed
    """
    _program, _customer, aircraft = setup_aircraft_in_flight_testing(line_number=4007)
    escape = create_escape_in_root_cause(
        aircraft["id"], severity="MAJOR", description="Hydraulic seep"
    )
    assert escape["status"] == "ROOT_CAUSE", "still an open escape: quality stays HOLD"
    resp = api_client.schedule_flight_test(
        aircraft["id"], schedule_flight_test_payload(), delivery_manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_QUALITY_HOLD)


def test_range_windows_half_open_adjacency_allowed_overlap_rejected(api, delivery_manager_headers):
    """PRD §3.8: "the half-open interval — from `window_start` up to but not including
    `window_end` — must not intersect any other `SCHEDULED` test on the same range, with
    exact adjacency (one window starting precisely where another ends) permitted
    (`ERR_RANGE_WINDOW_OVERLAP`, 409)."

    Design: Difficulty/resource_temporal_overlap/range_windows_half_open_adjacent_allowed_overlap_rejected
    """
    _program, _customer, aircraft = setup_aircraft_in_flight_testing(line_number=4004)
    validate_success(
        api_client.schedule_flight_test(
            aircraft["id"],
            schedule_flight_test_payload(
                range_code="RANGE_ALPHA",
                window_start="2026-10-01T09:00:00Z",
                window_end="2026-10-01T12:00:00Z",
            ),
            delivery_manager_headers,
        ),
        201,
    )
    validate_success(
        api_client.schedule_flight_test(
            aircraft["id"],
            schedule_flight_test_payload(
                range_code="RANGE_ALPHA",
                window_start="2026-10-01T12:00:00Z",
                window_end="2026-10-01T15:00:00Z",
            ),
            delivery_manager_headers,
        ),
        201,
    )
    resp = api_client.schedule_flight_test(
        aircraft["id"],
        schedule_flight_test_payload(
            range_code="RANGE_ALPHA",
            window_start="2026-10-01T11:00:00Z",
            window_end="2026-10-01T13:00:00Z",
        ),
        delivery_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RANGE_WINDOW_OVERLAP)
    other_range = validate_success(
        api_client.schedule_flight_test(
            aircraft["id"],
            schedule_flight_test_payload(
                range_code="RANGE_BRAVO",
                window_start="2026-10-01T11:00:00Z",
                window_end="2026-10-01T13:00:00Z",
            ),
            delivery_manager_headers,
        ),
        201,
    )
    assert other_range["status"] == "SCHEDULED", "overlap is per-range, not global"


def test_range_windows_leading_adjacency_allowed_interior_rejected(api, delivery_manager_headers):
    """PRD §3.8: "the half-open interval — from `window_start` up to but not including
    `window_end` — must not intersect any other `SCHEDULED` test on the same range, with
    exact adjacency (one window starting precisely where another ends) permitted
    (`ERR_RANGE_WINDOW_OVERLAP`, 409)."

    Design: Difficulty/resource_temporal_overlap/range_windows_half_open_adjacent_allowed_overlap_rejected
    """
    _program, _customer, aircraft = setup_aircraft_in_flight_testing(line_number=4008)
    validate_success(
        api_client.schedule_flight_test(
            aircraft["id"],
            schedule_flight_test_payload(
                range_code="RANGE_ALPHA",
                window_start="2026-10-01T09:00:00Z",
                window_end="2026-10-01T12:00:00Z",
            ),
            delivery_manager_headers,
        ),
        201,
    )
    # [06:00, 09:00) ends exactly where the existing window starts: adjacency is permitted.
    validate_success(
        api_client.schedule_flight_test(
            aircraft["id"],
            schedule_flight_test_payload(
                range_code="RANGE_ALPHA",
                window_start="2026-10-01T06:00:00Z",
                window_end="2026-10-01T09:00:00Z",
            ),
            delivery_manager_headers,
        ),
        201,
    )
    # [10:00, 11:00) sits strictly inside [09:00, 12:00): a real intersection.
    resp = api_client.schedule_flight_test(
        aircraft["id"],
        schedule_flight_test_payload(
            range_code="RANGE_ALPHA",
            window_start="2026-10-01T10:00:00Z",
            window_end="2026-10-01T11:00:00Z",
        ),
        delivery_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RANGE_WINDOW_OVERLAP)


def test_flight_test_fail_rejects_delivery_spawns_rework_and_expires_negotiation(
    api, delivery_manager_headers
):
    """PRD §3.8: "A `FAIL` detonates three effects at once: the aircraft's `delivery_status`
    drops to `REJECTED`; a rework order with `source` `FLIGHT_TEST_FAILURE` is created,
    provisionally priced from the request's optional `rework_estimated_hours`; and every
    live negotiation of the aircraft — any in `PROPOSED` or `COUNTERED` — auto-expires to
    `EXPIRED`, because the delivery state changed underneath it."
    PRD §3.5: "for `FLIGHT_TEST_FAILURE`, the optional `rework_estimated_hours` payload of
    the failed flight test" and "The multiplier is 1.5 for quality escapes, 1.25 for
    flight-test failures, and 1.0 for both traveled work and walkthrough snags."

    Design: Difficulty/transitive_cascade/flight_test_fail_rework_and_negotiation_expiry_chain
    """
    _program, _customer, aircraft = setup_aircraft_in_flight_testing(line_number=3004)
    negotiation = setup_negotiation(aircraft["id"])
    assert negotiation["status"] == "PROPOSED"
    flight_test = schedule_flight_test(aircraft["id"])

    validate_success(
        api_client.record_flight_test_outcome(
            flight_test["id"],
            record_outcome_payload("FAIL", rework_estimated_hours=6),
            delivery_manager_headers,
        )
    )

    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], delivery_manager_headers))
    assert aircraft["delivery_status"] == "REJECTED"

    orders, meta = validate_paginated(
        api_client.list_aircraft_rework_orders(aircraft["id"], delivery_manager_headers)
    )
    assert meta["total_count"] == 1
    assert orders[0]["source"] == "FLIGHT_TEST_FAILURE"
    assert orders[0]["estimated_cost_cents"] == 112500, "6 x 15000 x 1.25"

    negotiations, _meta = validate_paginated(
        api_client.list_delivery_negotiations(aircraft["id"], delivery_manager_headers)
    )
    assert negotiations[0]["id"] == negotiation["id"]
    assert negotiations[0]["status"] == "EXPIRED", (
        "expired by the delivery-state flip, not by any negotiation call"
    )


def test_flight_test_fail_expires_countered_negotiation(api, delivery_manager_headers):
    """PRD §3.8: "every live negotiation of the aircraft — any in `PROPOSED` or `COUNTERED`
    — auto-expires to `EXPIRED`, because the delivery state changed underneath it."
    PRD §3.8: "A `FAIL` detonates three effects at once: the aircraft's `delivery_status`
    drops to `REJECTED`; a rework order with `source` `FLIGHT_TEST_FAILURE` is created,
    provisionally priced from the request's optional `rework_estimated_hours`; and every
    live negotiation of the aircraft — any in `PROPOSED` or `COUNTERED` — auto-expires to
    `EXPIRED`, because the delivery state changed underneath it."

    Design: Difficulty/transitive_cascade/flight_test_fail_rework_and_negotiation_expiry_chain
    """
    _program, customer, aircraft = setup_aircraft_in_flight_testing(line_number=3009)
    negotiation = setup_negotiation(aircraft["id"])
    negotiation = counter_negotiation(
        negotiation, customer["id"], proposed_delivery_date="2026-10-12"
    )
    assert negotiation["status"] == "COUNTERED"
    flight_test = schedule_flight_test(aircraft["id"])

    validate_success(
        api_client.record_flight_test_outcome(
            flight_test["id"],
            record_outcome_payload("FAIL", rework_estimated_hours=6),
            delivery_manager_headers,
        )
    )

    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], delivery_manager_headers))
    assert aircraft["delivery_status"] == "REJECTED"
    negotiations, _meta = validate_paginated(
        api_client.list_delivery_negotiations(aircraft["id"], delivery_manager_headers)
    )
    assert negotiations[0]["status"] == "EXPIRED", "a COUNTERED negotiation is live and expires too"
