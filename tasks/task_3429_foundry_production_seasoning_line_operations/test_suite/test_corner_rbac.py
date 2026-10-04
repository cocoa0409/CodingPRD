"""Corner queue (rbac): exclusive-endpoint denials and shared read access."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_melt_batch_payload,
    create_product,
    make_headers,
    setup_released_order,
    validate_error,
    validate_paginated,
)

_FM = TEST_USERS["foundry_manager_headers"]


def test_seasoning_lead_cannot_create_melt_batch(api):
    """PRD §2.1: "The `MeltOperator` runs the furnace and the floor: melt-batch
    creation, charges, chemistry readings, taps, pours, shakeout, and rework
    completion."
    PRD §2.1: "A request whose authenticated role is not listed among the roles
    authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    A SeasoningLead calling melt-batch creation is denied even with a valid
    payload, and no batch persists.

    Design: Corner/rbac/seasoning_lead_cannot_create_melt_batch
    """
    ctx = setup_released_order()
    payload = create_melt_batch_payload(ctx["order"]["id"],
                                        ctx["order"]["version"])
    resp = api.create_melt_batch(payload, TEST_USERS["seasoning_lead_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    _, meta = validate_paginated(api.list_melt_batches(
        _FM, params={"production_order_id": ctx["order"]["id"]}))
    assert meta["total_count"] == 0


def test_foundry_manager_cannot_record_outlet_sale(api):
    """PRD §2.1: "The `OutletManager` runs the factory outlet and museum store:
    recording on-site sales."
    PRD §2.1: "A request whose authenticated role is not listed among the roles
    authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    Even the plant manager has no override: the role model is peer roles with
    segregation.

    Design: Corner/rbac/foundry_manager_cannot_record_outlet_sale
    """
    product = create_product()
    resp = api.create_outlet_sale(
        {"product_id": product["id"], "channel": "FACTORY_OUTLET", "qty": 1,
         "unit_price_cents": 3000}, _FM)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


@pytest.mark.parametrize("role", [
    "FoundryManager", "MeltOperator", "QualityInspector", "SeasoningLead",
    "EnvironmentalOfficer", "RetailPlanner", "OutletManager",
])
def test_rbac_shared_get_endpoints_allowed_for_all_roles(api, role):
    """PRD §2.1: "All seven roles may call every read (list and get) endpoint."
    Listing products as each role returns the same 200 array envelope.

    Design: Corner/rbac/rbac_shared_get_endpoints_allowed_for_all_roles
    """
    product = create_product()
    data, meta = validate_paginated(api.list_products(
        make_headers(f"{role.lower()}-reader", role)))
    assert meta["total_count"] == 1
    assert data[0]["id"] == product["id"]
