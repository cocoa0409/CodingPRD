"""Batch creation shape, one-batch-per-campaign, and the provisional/final yield variants."""
from test_helpers import (
    ApiErrorId, USER_IDS,
    validate_success, validate_error, validate_paginated,
    setup_campaign_in_production, setup_batch_upstream, setup_batch_downstream,
    setup_batch_process_complete,
    create_batch_payload, create_batch_entity, get_batch_entity,
    record_and_verify_test, advance_batch, submit_batch_for_review, disposition_batch,
    make_manufacturing_operator_headers,
    assert_batch,
)


def test_batch_create_initializes_parallel_dimensions_and_provisional_yield(
        api, platform_admin_headers):
    """PRD §3.4: "Its process dimension `process_status` begins at `UPSTREAM` and runs toward `DOWNSTREAM` and `PROCESS_COMPLETE` (or `TERMINATED`). Its quality dimension `quality_status` begins at `IN_TESTING`."
    PRD §3.4: "`provisional_yield_units` is the train's `capacity_liters` multiplied by the design titer of 2.0 grams per liter, multiplied by 125 units per gram, multiplied by the provisional recovery factor 0.8, rounded down to a whole unit; `quantity_units` starts equal to `provisional_yield_units`."
    PRD §3.4: "stamps `manufactured_by_user_id` with the operator's `X-User-ID`"

    Design: Corner/entities/batch_create_initializes_parallel_dimensions_and_provisional_yield
    """
    env = setup_campaign_in_production()
    headers = make_manufacturing_operator_headers(USER_IDS["operator"])
    resp = api.create_batch(env["campaign"]["id"], create_batch_payload(lot_number="LOT-0001"),
                            headers)
    data = validate_success(resp, expected_status=201)
    assert_batch(data)
    assert data["process_status"] == "UPSTREAM" and data["quality_status"] == "IN_TESTING"
    assert data["provisional_yield_units"] == 400000
    assert data["quantity_units"] == 400000
    assert data["available_to_ship_units"] == 400000
    assert data["final_yield_units"] is None
    assert data["expiry_utc"] is None and data["process_completed_at"] is None
    assert data["manufactured_by_user_id"] == "op-1"


def test_second_batch_for_same_campaign_rejected(api, platform_admin_headers):
    """PRD §3.4: "a campaign carries at most one batch — a second creation is rejected with `ERR_BATCH_ALREADY_EXISTS` (HTTP 409)."

    Design: Corner/validations/second_batch_for_same_campaign_rejected
    """
    env = setup_batch_upstream()
    headers = make_manufacturing_operator_headers(USER_IDS["operator"])
    resp = api.create_batch(env["campaign"]["id"], create_batch_payload(lot_number="LOT-0002"),
                            headers)
    validate_error(resp, ApiErrorId.ERR_BATCH_ALREADY_EXISTS)
    rows, meta = validate_paginated(
        api.list_batches(env["campaign"]["id"], platform_admin_headers))
    assert meta["total_count"] == 1 and len(rows) == 1


def _complete_with_titers(env):
    """Drive a DOWNSTREAM batch through the 2.4/2.6 titer pair to PROCESS_COMPLETE."""
    version = env["batch"]["version"]
    for value in (2.4, 2.6):
        _test, version = record_and_verify_test(
            env["batch"]["id"], batch_version=version, test_type="TITER", phase="DOWNSTREAM",
            measured_value=value, unit="G/L", spec_min=2.0, spec_max=4.0)
    return advance_batch(env["batch"]["id"], "PROCESS_COMPLETE")


def test_yield_provisional_while_downstream_then_final_replaces(api, platform_admin_headers):
    """PRD §3.4: "`final_yield_units` is that average multiplied by the train's `capacity_liters` and by 125 units per gram, rounded down to a whole unit; and `quantity_units` is replaced by `final_yield_units`, re-deriving `available_to_ship_units`."
    PRD §3.4: "the average titer is the mean of `measured_value` over the batch's `VERIFIED` tests of type `TITER` in phase `DOWNSTREAM`, rounded half-up to four decimal places"

    Design: Difficulty/dual_variant_calc/batch_yield_provisional_then_final_diverge
    """
    env = setup_batch_downstream()
    assert env["batch"]["quantity_units"] == 400000, "provisional variant while DOWNSTREAM"
    batch = _complete_with_titers(env)
    assert batch["provisional_yield_units"] == 400000
    assert batch["final_yield_units"] == 625000, "2.5 x 2000 x 125"
    assert batch["quantity_units"] == 625000, "final variant replaces provisional at completion"


def test_process_complete_sets_quality_review_and_completes_campaign(
        api, platform_admin_headers):
    """PRD §3.4: "Completion also stamps `process_completed_at` with the logical clock, sets `expiry_utc` to `process_completed_at` plus the product's `shelf_life_hours`, moves `quality_status` from `IN_TESTING` to `READY_FOR_REVIEW`, completes the parent campaign, and increments the batch's `version` by one."
    PRD §3.4: "a campaign in `PRODUCTION_IN_PROGRESS` moves to `COMPLETED` by the system the moment its batch's process dimension enters `PROCESS_COMPLETE` or `TERMINATED`."

    Design: Difficulty/dual_variant_calc/batch_yield_provisional_then_final_diverge
    """
    env = setup_batch_downstream()
    batch = _complete_with_titers(env)
    assert batch["process_status"] == "PROCESS_COMPLETE"
    assert batch["quality_status"] == "READY_FOR_REVIEW"
    campaign = validate_success(api.get_campaign(env["campaign"]["id"], platform_admin_headers))
    assert campaign["status"] == "COMPLETED"


def test_process_dimension_moves_while_quality_stays_in_testing(api):
    """PRD §3.4: "A batch evolves along two parallel dimensions. Its process dimension `process_status` begins at `UPSTREAM` and runs toward `DOWNSTREAM` and `PROCESS_COMPLETE` (or `TERMINATED`). Its quality dimension `quality_status` begins at `IN_TESTING`."

    Design: Difficulty/non_linear_state_machine/batch_parallel_dimensions_evolve_independently
    """
    env = setup_batch_upstream()
    assert env["batch"]["process_status"] == "UPSTREAM"
    assert env["batch"]["quality_status"] == "IN_TESTING"
    # Second independent env in the same server state: PRD §3.2 requires a
    # unique product_code, so the second chain must not reuse the default.
    env = setup_batch_downstream(product_overrides={"product_code": "MAB-002"})
    assert env["batch"]["process_status"] == "DOWNSTREAM"
    assert env["batch"]["quality_status"] == "IN_TESTING", \
        "the process advance does not move the quality dimension"


def test_process_complete_freezes_while_quality_walks_to_released(api):
    """PRD §3.5: "Submitting a batch record for review moves `quality_status` from `READY_FOR_REVIEW` to `PENDING_DISPOSITION`"
    PRD §3.5: "A successful release moves `quality_status` to `RELEASED` and increments the batch's `version`."

    Design: Difficulty/non_linear_state_machine/batch_parallel_dimensions_evolve_independently
    """
    env = setup_batch_process_complete()
    batch_id = env["batch"]["id"]
    assert env["batch"]["process_status"] == "PROCESS_COMPLETE"
    assert env["batch"]["quality_status"] == "READY_FOR_REVIEW"
    submitted = submit_batch_for_review(batch_id)
    assert submitted["quality_status"] == "PENDING_DISPOSITION"
    assert submitted["process_status"] == "PROCESS_COMPLETE"
    released = disposition_batch(batch_id, decision="RELEASED",
                                 rationale="All specifications met")
    assert released["quality_status"] == "RELEASED"
    assert released["process_status"] == "PROCESS_COMPLETE", "process dimension frozen"
