"""Every read path resolves its own id space and names its own 404."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BAY_NOT_FOUND,
    ERR_CATALOG_ITEM_NOT_FOUND,
    ERR_CHANNEL_NOT_FOUND,
    ERR_DISPOSITION_ORDER_NOT_FOUND,
    ERR_FRAUD_CHECK_NOT_FOUND,
    ERR_PRICING_FEEDBACK_NOT_FOUND,
    ERR_RECEIPT_NOT_FOUND,
    ERR_REFUND_RELEASE_NOT_FOUND,
    ERR_RETURN_LINE_NOT_FOUND,
    ERR_RMA_LINE_NOT_FOUND,
    ERR_RMA_NOT_FOUND,
    ERR_SHRINK_LEDGER_ENTRY_NOT_FOUND,
    ERR_WORK_ORDER_NOT_FOUND,
)
from test_helpers.test_users import ADMIN


def test_each_inbound_pipeline_read_names_its_own_missing_resource(api):
    """PRD §2.5: "A path parameter naming a resource that does not exist is
    `404 Not Found` with that resource's own not-found error identifier."

    Design: Corner/errors/corner_err_pipeline_entity_ids_all_return_not_found
    """
    client = fx.make_client(api, name="Probe Client", client_code="VE1")

    validate_error(
        api.get_catalog_item(NON_EXISTENT_UUID, ADMIN), ERR_CATALOG_ITEM_NOT_FOUND, 404
    )
    validate_error(
        api.get_processing_bay(NON_EXISTENT_UUID, ADMIN), ERR_BAY_NOT_FOUND, 404
    )
    validate_error(
        api.get_channel(NON_EXISTENT_UUID, ADMIN), ERR_CHANNEL_NOT_FOUND, 404
    )
    validate_error(api.get_rma(NON_EXISTENT_UUID, ADMIN), ERR_RMA_NOT_FOUND, 404)
    validate_error(
        api.get_rma_line(NON_EXISTENT_UUID, ADMIN), ERR_RMA_LINE_NOT_FOUND, 404
    )
    validate_error(
        api.get_receipt(NON_EXISTENT_UUID, ADMIN), ERR_RECEIPT_NOT_FOUND, 404
    )
    validate_error(
        api.get_return_line(NON_EXISTENT_UUID, ADMIN), ERR_RETURN_LINE_NOT_FOUND, 404
    )

    # The store was non-empty throughout, so each miss was a genuine lookup.
    still_there = validate_success(api.get_client(client["id"], ADMIN), 200)
    assert still_there["id"] == client["id"]


def test_each_downstream_read_names_its_own_missing_resource(api):
    """PRD §2.6: "Priority 5 resolves every foreign key the request names —
    `client_id`, `catalog_item_id`, `rma_id`, `rma_line_id`, `receipt_id`,
    `return_line_id`, `bay_id`, `channel_id`, `work_order_id` — and returns the
    matching `ERR_*_NOT_FOUND` at 404 when one of them names nothing."

    Design: Corner/errors/corner_err_downstream_entity_ids_all_return_not_found
    """
    client = fx.make_client(api, name="Probe Client Two", client_code="VE2")

    validate_error(
        api.get_work_order(NON_EXISTENT_UUID, ADMIN), ERR_WORK_ORDER_NOT_FOUND, 404
    )
    validate_error(
        api.get_disposition_order(NON_EXISTENT_UUID, ADMIN),
        ERR_DISPOSITION_ORDER_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_fraud_check(NON_EXISTENT_UUID, ADMIN), ERR_FRAUD_CHECK_NOT_FOUND, 404
    )
    validate_error(
        api.get_refund_release(NON_EXISTENT_UUID, ADMIN),
        ERR_REFUND_RELEASE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_pricing_feedback(NON_EXISTENT_UUID, ADMIN),
        ERR_PRICING_FEEDBACK_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_shrink_ledger_entry(NON_EXISTENT_UUID, ADMIN),
        ERR_SHRINK_LEDGER_ENTRY_NOT_FOUND,
        404,
    )

    # A missing single row and an empty collection are reported differently.
    _, meta = validate_paginated(
        api.list_shrink_ledger_entries(
            ADMIN, {"client_id": client["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0
