"""Every aggregate read answers with its own entity-specific 404 identifier."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AGREEMENT_NOT_FOUND,
    ERR_ALLOWANCE_RULE_NOT_FOUND,
    ERR_BRAND_NOT_FOUND,
    ERR_GRANT_NOT_FOUND,
    ERR_ITINERARY_NOT_FOUND,
    ERR_MOVEMENT_NOT_FOUND,
    ERR_PRE_ORDER_NOT_FOUND,
    ERR_SALE_LINE_NOT_FOUND,
    ERR_SEALED_BAG_NOT_FOUND,
)
from test_helpers.assertions import ok
from test_helpers.constants import MISSING_UUIDS
from test_helpers.test_users import (
    SALES_ASSOCIATE_HEADERS,
    STOCK_CONTROLLER_HEADERS,
    TERMINAL_ADMIN_HEADERS,
)


def _refused_as_missing(response, error_id):
    """Assert a 404 carrying this identifier and a non-empty operator message."""
    validate_error(response, error_id)
    payload = response.json()["data"]
    assert payload["error_id"] == error_id, f"error_id should be {error_id} but was {payload['error_id']}"
    assert isinstance(payload["message"], str) and payload["message"].strip(), (
        f"{error_id} should carry a non-empty message but carried {payload['message']!r}"
    )


def test_each_aggregate_read_names_the_entity_the_caller_actually_asked_for(api):
    """One terminal exists, so a blanket empty-database answer cannot pass for the nine
    remaining reads, each of which must name its own aggregate.

    PRD 2.8: "Each identifier has its own 404: `terminal_id` yields `ERR_TERMINAL_NOT_FOUND`, `brand_id` yields `ERR_BRAND_NOT_FOUND`, `product_id` yields `ERR_PRODUCT_NOT_FOUND`, `grant_id` yields `ERR_GRANT_NOT_FOUND`, `allowance_rule_id` yields `ERR_ALLOWANCE_RULE_NOT_FOUND`, `stock_item_id` yields `ERR_STOCK_ITEM_NOT_FOUND`, `movement_id` yields `ERR_MOVEMENT_NOT_FOUND`, `itinerary_id` yields `ERR_ITINERARY_NOT_FOUND`, `sale_id` yields `ERR_SALE_NOT_FOUND`, `sale_line_id` yields `ERR_SALE_LINE_NOT_FOUND`, `sealed_bag_id` yields `ERR_SEALED_BAG_NOT_FOUND`, `pre_order_id` yields `ERR_PRE_ORDER_NOT_FOUND`, `agreement_id` yields `ERR_AGREEMENT_NOT_FOUND` and `audit_id` yields `ERR_AUDIT_NOT_FOUND`."

    Design: Corner/errors/each_remaining_aggregate_read_returns_its_own_entity_specific_not_found
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")

    _refused_as_missing(
        api.get_brand(MISSING_UUIDS["brand"], TERMINAL_ADMIN_HEADERS), ERR_BRAND_NOT_FOUND
    )
    _refused_as_missing(
        api.get_grant(MISSING_UUIDS["grant"], TERMINAL_ADMIN_HEADERS), ERR_GRANT_NOT_FOUND
    )
    _refused_as_missing(
        api.get_allowance_rule(MISSING_UUIDS["allowance_rule"], TERMINAL_ADMIN_HEADERS),
        ERR_ALLOWANCE_RULE_NOT_FOUND,
    )
    _refused_as_missing(
        api.get_movement(MISSING_UUIDS["movement"], STOCK_CONTROLLER_HEADERS), ERR_MOVEMENT_NOT_FOUND
    )
    _refused_as_missing(
        api.get_itinerary(MISSING_UUIDS["itinerary"], SALES_ASSOCIATE_HEADERS), ERR_ITINERARY_NOT_FOUND
    )
    _refused_as_missing(
        api.get_sale_line(MISSING_UUIDS["sale_line"], SALES_ASSOCIATE_HEADERS), ERR_SALE_LINE_NOT_FOUND
    )
    _refused_as_missing(
        api.get_sealed_bag(MISSING_UUIDS["sealed_bag"], SALES_ASSOCIATE_HEADERS), ERR_SEALED_BAG_NOT_FOUND
    )
    _refused_as_missing(
        api.get_pre_order(MISSING_UUIDS["pre_order"], STOCK_CONTROLLER_HEADERS), ERR_PRE_ORDER_NOT_FOUND
    )
    _refused_as_missing(
        api.get_agreement(MISSING_UUIDS["agreement"], TERMINAL_ADMIN_HEADERS), ERR_AGREEMENT_NOT_FOUND
    )

    survivor = ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert survivor["id"] == terminal["id"]
    assert survivor["iata_code"] == "SIN"
