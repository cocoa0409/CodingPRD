"""Immediate consistency: the transition response already carries the new numbers."""
from test_helpers import (
    MID_REGULAR_CLOCK_UTC,
    api_client,
    create_registration,
    get_order,
    host_headers,
    setup_open_order,
)


def test_submit_response_already_carries_the_recomputed_fee_and_window():
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.2: "Submission prices the order: `order_fee_cents` is set to the provisional variant of the dual-variant order fee"
    PRD §2.9: "Counter recomputation is visible to the client: after any transition that changes registrations, the order's `registration_count` reflects the count of its registrations"

    Design: Corner/consistency_model/submit_response_carries_immediately_consistent_computed_fields
    """
    bundle = setup_open_order(clock=MID_REGULAR_CLOCK_UTC)
    create_registration(
        bundle["order"], bundle["student"], bundle["school"], exam_subject="AP-SEMINAR"
    )
    order = get_order(bundle["order"]["id"])

    submitted = api_client.transition_exam_order(
        order["id"],
        {"to_status": "SUBMITTED", "expected_exam_order_version": order["version"]},
        host_headers(bundle["school"]),
    ).json()["data"]

    assert submitted["status"] == "SUBMITTED"
    assert submitted["ordering_window"] == "REGULAR"
    assert submitted["registration_count"] == 1
    assert submitted["order_fee_cents"] == 18000
    assert submitted["provisional_order_fee_cents"] == 18000

    read_back = get_order(order["id"])
    assert read_back["order_fee_cents"] == submitted["order_fee_cents"]
    assert read_back["unused_exam_charge_cents"] == 0
