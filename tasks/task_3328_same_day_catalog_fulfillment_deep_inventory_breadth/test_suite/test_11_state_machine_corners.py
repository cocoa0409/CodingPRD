"""State-machine corners: invalid transitions, initial states and revoke idempotency."""

from test_helpers import (
    ADMIN,
    CURATOR,
    DCM,
    ApiErrorId,
    setup_account,
    setup_clock,
    setup_order_scenario,
    setup_released_order,
    validate_error,
    validate_success,
)


def test_a_released_order_cannot_be_released_a_second_time(api):
    """PRD §3.3: "the release is gated twice over: the order's `order_status` must
    currently be `DRAFT`, and every line's item must have `curation_review_state`
    `APPROVED`."
    PRD §2.9: "State legality. The target resource must be in a state that permits the
    operation, and the transition must be one the state machine lists for that state;
    otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/released_order_cannot_be_released_twice
    """
    scenario = setup_released_order(
        api,
        lines_spec=[{"price": 1500, "qty": 1, "bundle": 4, "on_hand": 10, "sku": "SM-1001"}],
    )
    order = scenario["order"]
    assert order["order_status"] == "RELEASED"

    response = api.release_order(order["id"], scenario["acct_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_order(order["id"], scenario["acct_headers"]))
    assert after["order_status"] == "RELEASED"
    assert after["version"] == order["version"], (
        "the rejected second release did not advance the order"
    )


def test_new_resources_enter_their_state_machines_without_a_client_call(api):
    """PRD §3.1: "A newly created item starts with `catalog_status` `ACTIVE` and with
    `curation_review_state` `UNREVIEWED`; its `curation_last_reviewed_by` is empty until a
    curator first approves it."
    PRD §3.8: "A center is `OPEN` when it has no open quality or damage hold and its
    `inbound_reserved_units` is below a threshold".

    Design: Corner/state_machines/automatic_transitions_fire_without_a_client_call
    """
    setup_clock(api)
    dc = validate_success(api.create_distribution_center(
        {"code": "BOS", "region": "NORTHEAST", "local_zone": "America/New_York",
         "local_cutoff_time": "06:00:00", "utc_offset_minutes": -240,
         "inbound_capacity_units": 900, "transit_seconds": 86400}, ADMIN), 201)
    item = validate_success(api.create_item(
        {"sku": "IN-1001", "description": "Initial state probe", "material_spec": "steel",
         "long_tail": False, "unit_price_cents": 1500, "unit_weight_kg": 0.10,
         "curation_bundle_size": 4,
         "curated_dimension_json": {"nominal_length_mm": 10, "nominal_width_mm": 10,
                                    "nominal_height_mm": 10, "drawing_revision": 1}},
        CURATOR), 201)

    assert dc["operations_posture"] == "OPEN"
    assert item["curation_review_state"] == "UNREVIEWED"
    assert item["catalog_status"] == "ACTIVE"
    assert item["curation_last_reviewed_by"] is None


def test_a_second_revoke_of_the_same_batch_is_refused(api):
    """PRD §3.1: "A curator may revoke a batch's approval, which moves `review_status` to
    `REVOKED` and returns every item in the batch to `curation_review_state` `UNREVIEWED`".
    PRD §2.9: "State legality. The target resource must be in a state that permits the
    operation, and the transition must be one the state machine lists for that state;
    otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/curation_review_revoke_is_idempotent_in_effect
    """
    scenario = setup_order_scenario(
        api,
        lines_spec=[{"price": 1500, "qty": 1, "bundle": 4, "on_hand": 10, "sku": "ID-1001"}],
        target="DRAFT",
    )
    review = scenario["review"]
    item = scenario["items"][0]

    first = validate_success(api.revoke_curation_review(review["id"], CURATOR))
    assert first["review_status"] == "REVOKED"
    assert validate_success(api.get_item(item["id"], CURATOR))["curation_review_state"] == "UNREVIEWED"

    response = api.revoke_curation_review(review["id"], CURATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_curation_review(review["id"], CURATOR))
    assert after["version"] == first["version"], (
        "the rejected second revoke did not advance the batch"
    )
    assert validate_success(api.get_item(item["id"], CURATOR))["curation_review_state"] == "UNREVIEWED"