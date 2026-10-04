"""Difficulty queue A: boundary precision — refill cadence day boundary and
warranty failure-day-index boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_order,
    create_order,
    set_clock,
    setup_claim_in_data_review,
    setup_supply_pipeline,
    validate_error,
    validate_success,
)

FULFILL = TEST_USERS["fulfillment_agent_headers"]
WARRANTY = TEST_USERS["warranty_reviewer_headers"]


def _refill_boundary_setup():
    """quantity 2 x wear 14 -> supply 28; ceil(28 * 0.75) = 21 ->
    earliest_refill_date = 2026-09-01 + 21 = 2026-09-22 (computed from the
    prior order's fill_date; PRD §3.5 defines the stamp only when a prior
    order exists)."""
    ctx = setup_supply_pipeline(quantity_per_fill=2, lot_quantity=30)
    first = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    adjudicate_order(first)
    assert first["fill_date"] == "2026-09-01"
    return ctx


def _second_order_attempt(api, ctx):
    return api.create_sensor_order(
        ctx["patient"]["id"],
        {
            "prescription_id": ctx["prescription"]["id"],
            "coverage_verification_id": ctx["verification"]["id"],
            "lot_id": ctx["lot"]["id"],
            "quantity": 2,
        },
        FULFILL,
    )


def test_refill_rejected_one_day_before_earliest_refill_date(api):
    """PRD §3.5: "The refill is permitted when the logical date is on or after
    `earliest_refill_date`; the rejection boundary is exactly one day before
    it. Attempting to create the order earlier yields `ERR_REFILL_TOO_EARLY`."

    Design: Difficulty/boundary_precision_check/refill_boundary_at_exact_earliest_refill_date
    """
    ctx = _refill_boundary_setup()
    set_clock("2026-09-21T00:00:00Z")
    resp = _second_order_attempt(api, ctx)
    validate_error(resp, ApiErrorId.ERR_REFILL_TOO_EARLY, expected_status=409)


def test_refill_permitted_exactly_on_earliest_refill_date(api):
    """PRD §3.5: "The refill is permitted when the logical date is on or after
    `earliest_refill_date`; the rejection boundary is exactly one day before
    it."
    PRD §3.5: "The new order is created with `fill_date` set to the current
    logical date, `fulfillment_status` of `PENDING_PICK`, `billing_status` of
    `UNBILLED`"

    Design: Difficulty/boundary_precision_check/refill_boundary_at_exact_earliest_refill_date
    """
    ctx = _refill_boundary_setup()
    set_clock("2026-09-22T00:00:00Z")
    resp = _second_order_attempt(api, ctx)
    order = validate_success(resp, expected_status=201)
    assert order["fulfillment_status"] == "PENDING_PICK"


def test_failure_day_index_at_wear_days_minus_one_is_approvable(api):
    """PRD §3.8: "critically — requires the `reported_failure_day_index` to be
    strictly less than the product's `wear_days`. The strict less-than is the
    formal definition of "early failure" for warranty purposes"

    wear_days 14, index 13 -> approvable.

    Design: Difficulty/boundary_precision_check/warranty_failure_day_index_at_wear_days_minus_one_vs_equal
    """
    ctx = setup_claim_in_data_review(failure_day_index=13)
    resp = api.decide_warranty_claim(
        ctx["claim"]["id"],
        {"decision": "APPROVED", "review_notes": "boundary minus one approved"},
        WARRANTY,
    )
    approved = validate_success(resp)
    assert approved["status"] == "APPROVED"


def test_failure_day_index_equal_to_wear_days_rejected(api):
    """PRD §3.8: "a failure reported on or after the labeled wear-day count is
    not an early failure and the approval is rejected with
    `ERR_NOT_EARLY_FAILURE`."

    wear_days 14, index 14 -> rejected; claim stays in DATA_REVIEW.

    Design: Difficulty/boundary_precision_check/warranty_failure_day_index_at_wear_days_minus_one_vs_equal
    """
    ctx = setup_claim_in_data_review(failure_day_index=14)
    resp = api.decide_warranty_claim(
        ctx["claim"]["id"],
        {"decision": "APPROVED", "review_notes": "boundary equal rejected"},
        WARRANTY,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_EARLY_FAILURE, expected_status=422)
    claim = validate_success(api.get_warranty_claim(ctx["claim"]["id"], TEST_USERS["platform_admin_headers"]))
    assert claim["status"] == "DATA_REVIEW"
