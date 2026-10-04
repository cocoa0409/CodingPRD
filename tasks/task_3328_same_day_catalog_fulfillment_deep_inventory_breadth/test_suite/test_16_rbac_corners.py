"""RBAC corners: peer-role exclusivity on writes and shared reads."""

from test_helpers import (
    CURATOR,
    DCM,
    PICKER,
    ApiErrorId,
    create_item_payload,
    setup_draft_order,
    setup_released_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_picker_cannot_create_catalog_items(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to
    invoke the operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`CatalogCurator` — owns product data curation, standardized attributes,
    cross-references and supplier records."

    Design: Corner/rbac/picker_role_cannot_create_catalog_items
    """
    payload = create_item_payload(
        sku="RB-1001", description="Role probe item", material_spec="steel",
        long_tail=False, unit_price_cents=1500, unit_weight_kg=0.10, curation_bundle_size=4,
        curated_dimension_json={"nominal_length_mm": 10, "nominal_width_mm": 10,
                                "nominal_height_mm": 10, "drawing_revision": 1})

    denied = api.create_item(payload, PICKER)
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED)

    rows, _meta = validate_paginated(api.list_items(CURATOR, {"limit": 10, "offset": 0}))
    assert rows == [], "the denied request created nothing"

    created = validate_success(api.create_item(payload, CURATOR), 201)
    assert created["sku"] == "RB-1001", "the payload itself was valid"


def test_a_curator_cannot_place_or_allocate_orders(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to
    invoke the operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`CustomerAccount` — the purchasing account that searches the catalog, places
    orders and files returns."

    Design: Corner/rbac/curators_cannot_place_or_allocate_orders
    """
    scenario = setup_released_order(
        api,
        lines_spec=[{"price": 1500, "qty": 1, "bundle": 4, "on_hand": 10, "sku": "RB-1101"}],
    )
    order = scenario["order"]

    place = api.create_order(
        {"account_id": scenario["acct"]["id"],
         "lines": [{"item_id": scenario["items"][0]["id"], "quantity": 1}]}, CURATOR)
    validate_error(place, ApiErrorId.ERR_UNAUTHORIZED)

    allocate = api.allocate_order(
        order["id"], {"expected_order_version": order["version"]}, CURATOR)
    validate_error(allocate, ApiErrorId.ERR_UNAUTHORIZED)

    after = validate_success(api.get_order(order["id"], scenario["acct_headers"]))
    assert after["fulfillment_status"] == "AWAITING_RELEASE"

    orders, _meta = validate_paginated(api.list_orders(
        scenario["acct_headers"],
        {"account_id": scenario["acct"]["id"], "limit": 10, "offset": 0}))
    assert len(orders) == 1, "the denied order creation added nothing"


def test_shared_reads_are_open_to_both_peer_roles_while_the_write_is_not(api):
    """PRD §2.1: "For the other four roles — `PlatformAdmin`, `CatalogCurator`,
    `WarehousePicker` and `DCManager` — `X-User-ID` is an opaque operator identifier that
    is not tied to any persisted entity."
    PRD §2.1: "If the headers are well-formed but the named role is not permitted to
    invoke the operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/shared_read_operations_are_open_to_both_peer_roles
    """
    scenario = setup_draft_order(
        api,
        lines_spec=[{"price": 1500, "qty": 1, "bundle": 4, "on_hand": 10, "sku": "RB-1201"}],
    )
    order = scenario["order"]

    owned = validate_success(api.get_order(order["id"], scenario["acct_headers"]))
    assert owned["order_status"] == "DRAFT"

    shared = validate_success(api.get_order(order["id"], DCM))
    assert shared["order_status"] == owned["order_status"]
    assert shared["line_count"] == owned["line_count"]

    denied = api.release_order(order["id"], DCM)
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED)

    after = validate_success(api.get_order(order["id"], scenario["acct_headers"]))
    assert after["version"] == order["version"], "the denied release mutated nothing"