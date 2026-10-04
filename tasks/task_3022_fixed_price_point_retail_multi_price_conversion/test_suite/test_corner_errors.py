"""Error identifiers reachable on the nested read surface."""

from test_helpers import (
    ANALYST_HEADERS,
    E,
    IMPORT_HEADERS,
    validate_error,
    fixtures,
)

NOT_FOUND_QUOTE = (
    "The rejection carries an HTTP 404 and an error id specific to the resource type that failed"
)
PATH_ORDER_QUOTE = (
    "For any request whose path names more than one resource identifier, the system resolves "
    "those identifiers in the order the path declares them, left to right, and rejects the "
    "request at the first identifier that does not resolve."
)
SUB_RESOURCE_QUOTE = (
    "A request against a sub-resource of a non-existent parent therefore fails on the parent, "
    "before the child is ever looked up."
)


def test_the_nested_item_reads_report_the_item_specific_not_found(api):
    """Both nested item sub-resources report ERR_ITEM_NOT_FOUND for an unknown parent.

    PRD §2.8: "For any request whose path names more than one resource identifier, the system
    resolves those identifiers in the order the path declares them, left to right, and rejects
    the request at the first identifier that does not resolve."
    PRD §2.8: "The rejection carries an HTTP 404 and an error id specific to the resource type
    that failed"
    PRD §2.8: "A request against a sub-resource of a non-existent parent therefore fails on the
    parent, before the child is ever looked up."

    Design: Corner/errors/error_item_not_found_is_reachable_on_a_nested_update_path
    """
    fixtures.set_clock()
    unknown = "00000000-0000-4000-8000-000000000000"

    break_even = api.get_break_even(unknown, ANALYST_HEADERS)
    validate_error(break_even, E.ERR_ITEM_NOT_FOUND.value)
    assert break_even.json()["response_type"] == "error"
    assert set(break_even.json()["data"]) >= {"error_id", "message"}

    history = api.list_item_landed_costs(unknown, ANALYST_HEADERS)
    validate_error(history, E.ERR_ITEM_NOT_FOUND.value)
    assert history.json()["data"]["message"].strip(), "the envelope carries a readable message"

    cost_write = fixtures.apply_landed_cost(unknown, applied_amount_cents=105)
    validate_error(cost_write, E.ERR_ITEM_NOT_FOUND.value)


def test_a_nested_container_sub_resource_fails_on_the_missing_parent(api):
    """An unknown container id is reported before the nested collection is ever read.

    PRD §2.8: "A request against a sub-resource of a non-existent parent therefore fails on the
    parent, before the child is ever looked up."
    PRD §2.8: "The rejection carries an HTTP 404 and an error id specific to the resource type
    that failed"
    PRD §5: "The table below lists every error identifier this API may return and its HTTP status."

    Design: Corner/errors/error_item_not_found_is_reachable_on_a_nested_update_path
    """
    fixtures.set_clock()
    unknown = "00000000-0000-4000-8000-000000000000"

    lines = api.list_container_allocation_lines(unknown, ANALYST_HEADERS)
    validate_error(lines, E.ERR_CONTAINER_NOT_FOUND.value)

    costs = api.list_container_landed_costs(unknown, ANALYST_HEADERS)
    validate_error(costs, E.ERR_CONTAINER_NOT_FOUND.value)

    missing = api.get_container("00000000-0000-4000-8000-000000000001", IMPORT_HEADERS)
    validate_error(missing, E.ERR_CONTAINER_NOT_FOUND.value)
    assert missing.json()["response_type"] == "error"