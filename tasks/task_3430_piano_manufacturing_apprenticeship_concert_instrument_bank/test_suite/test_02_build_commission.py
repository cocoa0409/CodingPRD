"""Build commissioning: required fields, FK resolution, pagination, batch-state gate."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    condition_wood_batch,
    create_build_order,
    create_build_order_payload,
    create_wood_batch,
    get_wood_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

WM = TEST_USERS["workshop_manager_headers"]


def test_create_build_order_missing_wood_batch_id_returns_400(api):
    """PRD section 3.2: "A `WorkshopManager` commissions a build order by naming a
    `model` — `MODEL_D`, `MODEL_B`, `MODEL_O`, or `ART_CASE` — and a `wood_batch_id`".
    PRD section 2.8: priority (3) covers "required fields present, types valid, enum
    members valid".

    Design: Corner/entities/create_build_order_missing_required_wood_batch_id_returns_400
    """
    resp = api.create_build_order({"model": "MODEL_B"}, WM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_get_build_order_not_found_returns_error_envelope(api):
    """PRD section 2.9: "the first path identifier that does not resolve to an
    existing resource fails the whole request with `ERR_NOT_FOUND` (HTTP 404)."
    PRD section 2.2: "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/entities/get_build_order_not_found_returns_error_envelope
    """
    resp = api.get_build_order(NON_EXISTENT_UUID, WM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


def test_list_build_orders_paginates_with_limit_and_offset(api):
    """PRD section 2.3: "`limit` specifies the maximum number of items to return" and
    "`offset` specifies the number of items to skip"; "The `meta` object of a list
    response carries the pagination fields `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/list_build_orders_paginates_with_limit_and_offset
    """
    wb1 = condition_wood_batch(create_wood_batch("MAPLE", 12.0))
    wb2 = condition_wood_batch(create_wood_batch("BIRCH", 11.0), ready_moisture=7.9)
    create_build_order("MODEL_O", wb1["id"])
    create_build_order("MODEL_O", wb2["id"])
    page1, meta1 = validate_paginated(api.list_build_orders(WM, params={"limit": 1, "offset": 0}))
    page2, meta2 = validate_paginated(api.list_build_orders(WM, params={"limit": 1, "offset": 1}))
    assert len(page1) == 1 and meta1["total_count"] == 2 and meta1["has_more"] is True
    assert len(page2) == 1 and meta2["total_count"] == 2 and meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"]


def test_build_create_unknown_batch_returns_404(api):
    """PRD section 2.9: "Identifiers carried in request bodies — `wood_batch_id`,
    `apprentice_id`, `supervising_craftsman_id`, `instrument_id`, `technician_id`,
    and `lead_craftsman_id` — must likewise resolve to existing resources, failing
    with the same `ERR_NOT_FOUND` when they do not."

    Design: Corner/validations/build_create_unknown_batch_returns_404
    """
    resp = api.create_build_order(
        create_build_order_payload("MODEL_B", NON_EXISTENT_UUID), WM
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_build_create_drying_batch_rejected(api):
    """PRD section 3.2: "The named batch must be `CONDITIONED`: a batch still in
    `DRYING`, or already `REJECTED` or `CONSUMED`, fails the create with
    `ERR_WOOD_NOT_CONDITIONED`".

    Design: Difficulty/cross_entity_state_dependency/build_create_requires_conditioned_batch
    """
    wb = create_wood_batch("BIRCH", 12.9)
    resp = api.create_build_order(create_build_order_payload("MODEL_O", wb["id"]), WM)
    validate_error(resp, ApiErrorId.ERR_WOOD_NOT_CONDITIONED)


def test_build_create_after_conditioning_succeeds(api):
    """PRD section 3.2: "On a successful create the batch moves to `ALLOCATED` with
    its `version` incremented, the order starts in `COMMISSIONED`".

    Design: Difficulty/cross_entity_state_dependency/build_create_requires_conditioned_batch
    """
    wb = condition_wood_batch(create_wood_batch("BIRCH", 12.9))
    assert wb["status"] == "CONDITIONED"
    build = create_build_order("MODEL_O", wb["id"])
    assert build["status"] == "COMMISSIONED"
    assert build["wood_batch_id"] == wb["id"]
    assert get_wood_batch(wb["id"])["status"] == "ALLOCATED"


def test_wood_already_allocated_rejected(api):
    """PRD section 3.2: "a batch already `ALLOCATED` to another build fails with
    `ERR_WOOD_ALREADY_ALLOCATED`."

    Design: Corner/errors/wood_already_allocated_rejected
    """
    wb = condition_wood_batch(create_wood_batch("MAPLE", 12.0))
    create_build_order("MODEL_O", wb["id"])
    assert get_wood_batch(wb["id"])["status"] == "ALLOCATED"
    resp = api.create_build_order(create_build_order_payload("MODEL_D", wb["id"]), WM)
    validate_error(resp, ApiErrorId.ERR_WOOD_ALREADY_ALLOCATED)
    rows, meta = validate_paginated(api.list_build_orders(WM))
    assert meta["total_count"] == 1
