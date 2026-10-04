"""Error triggerability: per-entity 404 codes on single reads, and the
priority-1 authentication gate.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_BASELINE,
    TEST_USERS,
    api_client,
    set_clock,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_single_gets_with_unknown_ids_return_per_entity_not_found(api):
    """PRD §2.8 priority 3: "identifiers in the URL path resolve to existing
    resources, validated left to right ... The first miss produces that
    entity's not-found error, one of `ERR_PROGRAM_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DISPOSITION_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND`, each at HTTP 404."

    Design: Corner/errors/single_gets_with_unknown_ids_return_per_entity_not_found
    """
    set_clock(CLOCK_BASELINE)
    cases = [
        (api_client.get_heat_claim, "00000000-0000-4000-8000-000000000001",
         ApiErrorId.ERR_CLAIM_NOT_FOUND),
        (api_client.get_commitment, "00000000-0000-4000-8000-000000000002",
         ApiErrorId.ERR_COMMITMENT_NOT_FOUND),
        (api_client.get_commodity_contract, "00000000-0000-4000-8000-000000000003",
         ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api_client.get_disposition_order, "00000000-0000-4000-8000-000000000004",
         ApiErrorId.ERR_DISPOSITION_NOT_FOUND),
        (api_client.get_inventory_lot, "00000000-0000-4000-8000-000000000005",
         ApiErrorId.ERR_LOT_NOT_FOUND),
        (api_client.get_sell_through_report, "00000000-0000-4000-8000-000000000006",
         ApiErrorId.ERR_REPORT_NOT_FOUND),
        (api_client.get_production_run, "00000000-0000-4000-8000-000000000007",
         ApiErrorId.ERR_RUN_NOT_FOUND),
        (api_client.get_warehouse, "00000000-0000-4000-8000-000000000008",
         ApiErrorId.ERR_WAREHOUSE_NOT_FOUND),
        (api_client.get_retailer_account, "00000000-0000-4000-8000-000000000009",
         ApiErrorId.ERR_RETAILER_NOT_FOUND),
    ]
    for getter, unknown_id, expected_error in cases:
        resp = getter(unknown_id, ADMIN)
        validate_error(resp, expected_error)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == expected_error.value
        assert body["data"]["message"]


def test_create_warehouse_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the role under
    which the user acts. If either header is missing, or if the value of
    `X-User-Role` is not one of the declared roles, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/create_warehouse_missing_auth_headers_returns_unauthenticated
    """
    resp = api_client.create_warehouse(
        {"name": "NoAuth Warehouse", "temp_controlled": True, "capacity_units": 100},
        None,  # no X-User-ID / X-User-Role headers at all
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
