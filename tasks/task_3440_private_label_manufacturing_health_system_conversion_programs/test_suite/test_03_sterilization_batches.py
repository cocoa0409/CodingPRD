"""Sterilization batches: temporal window, uniqueness, chamber overlap,
quarantine cascade, and lot listing/pagination."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_batch,
    create_lot,
    create_registered_product,
    create_sterilization_batch_payload,
    get_success_data,
    make_planner_headers,
    make_quality_headers,
    record_qa_disposition,
    record_sterility_result,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
QUALITY = TEST_USERS["quality_headers"]


def _sterile_registered_product(sku):
    return create_registered_product(
        sku=sku,
        brand_type="PRIVATE_LABEL",
        sterile=True,
        category="STERILIZATION_SUPPLIES",
        each_price_cents=10,
    )


def test_sterilization_window_in_past_422(api):
    """PRD §3.2: "the window must not lie in the past, meaning `scheduled_start`
    must be at or after the current logical clock and `scheduled_end` must be
    strictly after `scheduled_start`; violations are rejected with
    `ERR_STERILIZATION_IN_PAST` (HTTP 422)."

    Design: Corner/validations/sterilization_window_in_past_rejected
    """
    product = _sterile_registered_product("SP-P")
    lot = create_lot(product["id"], lot_code="LOT-PW")
    resp = api.create_sterilization_batch(
        {
            "batch_code": "B-PAST",
            "chamber_id": "CH-1",
            "scheduled_start": "2026-08-10T08:00:00Z",
            "scheduled_end": "2026-08-10T10:00:00Z",
            "lot_ids": [lot["id"]],
        },
        headers=PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_STERILIZATION_IN_PAST.value, 422)


def test_duplicate_batch_code_409(api):
    """PRD §3.2: "A `ManufacturingPlanner` schedules a `SterilizationBatch` with
    a globally unique `batch_code` (collisions rejected with
    `ERR_DUPLICATE_BATCH_CODE`)".

    Design: Corner/validations/duplicate_batch_code_rejected
    """
    product = _sterile_registered_product("DB-1")
    lot1 = create_lot(product["id"], lot_code="LOT-DB1")
    lot2 = create_lot(product["id"], lot_code="LOT-DB2")
    create_batch(
        [lot1["id"]],
        batch_code="B-DUP",
        chamber_id="CH-1",
        scheduled_start="2026-09-10T08:00:00Z",
        scheduled_end="2026-09-10T10:00:00Z",
    )
    # Different chamber and window: only the code collides.
    resp = api.create_sterilization_batch(
        {
            "batch_code": "B-DUP",
            "chamber_id": "CH-9",
            "scheduled_start": "2026-09-11T08:00:00Z",
            "scheduled_end": "2026-09-11T10:00:00Z",
            "lot_ids": [lot2["id"]],
        },
        headers=PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BATCH_CODE.value)


def test_lot_already_batched_409(api):
    """PRD §3.2: "must not already carry a `sterilization_batch_id` (otherwise
    `ERR_LOT_ALREADY_BATCHED`, HTTP 409)". PRD §3.2: "a lot belongs to at most
    one batch across its lifetime".

    Design: Corner/validations/lot_already_batched_rejected
    """
    product = _sterile_registered_product("LB-1")
    lot = create_lot(product["id"], lot_code="LOT-LB1")
    create_batch(
        [lot["id"]],
        batch_code="B-LB1",
        chamber_id="CH-1",
        scheduled_start="2026-09-10T08:00:00Z",
        scheduled_end="2026-09-10T10:00:00Z",
    )
    resp = api.create_sterilization_batch(
        {
            "batch_code": "B-LB2",
            "chamber_id": "CH-2",
            "scheduled_start": "2026-09-12T08:00:00Z",
            "scheduled_end": "2026-09-12T10:00:00Z",
            "lot_ids": [lot["id"]],
        },
        headers=PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_ALREADY_BATCHED.value)


def test_sterility_result_recording_twice_409(api):
    """PRD §3.2: "the batch must still be `SCHEDULED`, otherwise
    `ERR_INVALID_STATE`". PRD §3.2: "Recording completes the batch: its `status`
    becomes `COMPLETED`, `sterility_result` takes the payload value".

    Design: Corner/state_machines/sterility_result_recording_twice_rejected
    """
    product = _sterile_registered_product("TS-1")
    lot = create_lot(product["id"], lot_code="LOT-TS1")
    batch = create_batch(
        [lot["id"]],
        batch_code="B-TS-1",
        chamber_id="CH-2",
        scheduled_start="2026-09-10T08:00:00Z",
        scheduled_end="2026-09-10T10:00:00Z",
    )
    record_sterility_result(batch["id"], "PASSED", qm_id="qm-1")
    resp = api.record_sterility_result(batch["id"], {"result": "FAILED"}, QUALITY)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    # The second write did not land: a FAILED landing would have quarantined the
    # lot; instead it still shows the PASSED outcome.
    lot_after = get_success_data(api.get_manufacturing_lot(lot["id"], QUALITY))
    assert lot_after["status"] == "AWAITING_QA"
    assert lot_after["sterility_status"] == "PASSED"


def test_chamber_overlap_rejected(api):
    """PRD §3.2: "a new batch is rejected with `ERR_CHAMBER_WINDOW_OVERLAP`
    (HTTP 409) exactly when an existing batch on that chamber starts before the
    new window ends and the new window starts before the existing window ends".

    Design: Difficulty/resource_temporal_overlap/chamber_windows_half_open_adjacency
    """
    product = _sterile_registered_product("CH-P")
    lot1 = create_lot(product["id"], lot_code="LOT-C1")
    lot2 = create_lot(product["id"], lot_code="LOT-C2")
    create_batch(
        [lot1["id"]],
        batch_code="B-CH-1",
        chamber_id="CH-1",
        scheduled_start="2026-09-10T08:00:00Z",
        scheduled_end="2026-09-10T12:00:00Z",
    )
    resp = api.create_sterilization_batch(
        {
            "batch_code": "B-CH-2",
            "chamber_id": "CH-1",
            "scheduled_start": "2026-09-10T10:00:00Z",
            "scheduled_end": "2026-09-10T14:00:00Z",
            "lot_ids": [lot2["id"]],
        },
        headers=PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_CHAMBER_WINDOW_OVERLAP.value, 409)


def test_chamber_adjacent_window_allowed(api):
    """PRD §3.2: "touching windows, where one batch's end equals the other's
    start, are allowed." PRD §3.2: "each listed lot has its
    `sterilization_batch_id` set to the new batch's id and its `version`
    incremented by 1."

    Design: Difficulty/resource_temporal_overlap/chamber_windows_half_open_adjacency
    """
    product = _sterile_registered_product("CH-Q")
    lot1 = create_lot(product["id"], lot_code="LOT-C4")
    lot2 = create_lot(product["id"], lot_code="LOT-C5")
    create_batch(
        [lot1["id"]],
        batch_code="B-CH-4",
        chamber_id="CH-1",
        scheduled_start="2026-09-10T08:00:00Z",
        scheduled_end="2026-09-10T12:00:00Z",
    )
    resp = api.create_sterilization_batch(
        {
            "batch_code": "B-CH-5",
            "chamber_id": "CH-1",
            "scheduled_start": "2026-09-10T12:00:00Z",
            "scheduled_end": "2026-09-10T14:00:00Z",
            "lot_ids": [lot2["id"]],
        },
        headers=PLANNER,
    )
    batch3 = validate_success(resp, 201)
    lot2_after = get_success_data(api.get_manufacturing_lot(lot2["id"], QUALITY))
    assert lot2_after["sterilization_batch_id"] == batch3["id"]
    assert lot2_after["version"] == 2


def test_quarantine_cascade_skips_terminal_lots(api):
    """PRD §3.2: "On `FAILED`, a quarantine cascade fires: every lot in the batch
    still `AWAITING_QA` transitions to `QUARANTINED` with `sterility_status` set
    to `FAILED`, each cascaded lot's `version` incrementing by 1; lots already
    `RELEASED` or `REJECTED` are untouched by the cascade."

    Design: Corner/complexity_layers/quarantine_cascade_skips_terminal_lots
    """
    product = _sterile_registered_product("QC-P")
    lot1 = create_lot(product["id"], lot_code="LOT-Q1", planner_id="planner-1")
    lot2 = create_lot(product["id"], lot_code="LOT-Q2", planner_id="planner-1")
    batch = create_batch(
        [lot1["id"], lot2["id"]],
        batch_code="B-QC",
        chamber_id="CH-3",
        scheduled_start="2026-09-10T08:00:00Z",
        scheduled_end="2026-09-10T10:00:00Z",
    )
    # L2 is dispositioned to its terminal REJECTED state while batched.
    record_qa_disposition(lot2["id"], "REJECT", qm_id="qm-1")
    record_sterility_result(batch["id"], "FAILED", qm_id="qm-1")
    lot1_after = get_success_data(api.get_manufacturing_lot(lot1["id"], QUALITY))
    assert lot1_after["status"] == "QUARANTINED"
    assert lot1_after["sterility_status"] == "FAILED"
    lot2_after = get_success_data(api.get_manufacturing_lot(lot2["id"], QUALITY))
    assert lot2_after["status"] == "REJECTED"
    assert lot2_after["qa_disposition_by"] == "qm-1"


def test_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return; when not provided it defaults to 10, and it accepts values from a
    minimum of 1 to a maximum of 100. The `offset` parameter specifies the
    number of items to skip and defaults to 0."

    Design: Corner/endpoints/list_pagination_defaults
    """
    product = create_registered_product(
        sku="PG-P", brand_type="PRIVATE_LABEL", sterile=False
    )
    for i in range(1, 12):
        create_lot(product["id"], lot_code=f"LOT-PG-{i:02d}", quantity=10)
    data, meta = validate_paginated(api.list_manufacturing_lots(QUALITY))
    assert len(data) == 10
    assert meta["total_count"] == 11
    assert meta["has_more"] is True
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    data2, meta2 = validate_paginated(
        api.list_manufacturing_lots(QUALITY, params={"limit": 5, "offset": 10})
    )
    assert len(data2) == 1
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 11


def test_lots_filter_by_product(api):
    """PRD §3.2: "Lots may be listed and read back by `SupplyChainAdmin`,
    `ManufacturingPlanner`, and `QualityManager`, with optional filters on
    `product_id`, `status`, and `sterilization_batch_id`."

    Design: Corner/endpoints/fk_reverse_lookup_lots_by_product
    """
    product_a = create_registered_product(sku="FK-A", brand_type="PRIVATE_LABEL")
    product_b = create_registered_product(sku="FK-B", brand_type="PRIVATE_LABEL")
    create_lot(product_a["id"], lot_code="LOT-FKA1", quantity=10)
    create_lot(product_a["id"], lot_code="LOT-FKA2", quantity=10)
    create_lot(product_b["id"], lot_code="LOT-FKB1", quantity=10)
    data, meta = validate_paginated(
        api.list_manufacturing_lots(PLANNER, params={"product_id": product_a["id"]})
    )
    assert meta["total_count"] == 2
    assert len(data) == 2
    assert all(lot["product_id"] == product_a["id"] for lot in data)
