"""Validation corners: each failure in an isolated scenario, one rule at a time."""

from test_helpers import (
    ADMIN,
    CURATOR,
    DCM,
    PICKER,
    ApiErrorId,
    account_headers,
    setup_account,
    setup_center,
    setup_clock,
    setup_curated_items,
    setup_draft_order,
    setup_order_scenario,
    setup_released_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ABSENT_ORDER = "00000000-0000-4000-8000-000000000042"


def test_a_request_carrying_no_role_header_is_unauthenticated(api):
    """PRD §2.1: "Every request carries two headers, and only two: `X-User-ID`,
    identifying the caller, and `X-User-Role`, naming the role the caller is acting in.
    If either header is absent, or if `X-User-Role` does not name one of the five declared
    roles, the request is rejected before anything else is evaluated with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    setup_clock(api)
    setup_account(api)

    response = api.list_orders({}, {"limit": 10, "offset": 0})
    error_data = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)

    assert error_data["error_id"] != ApiErrorId.ERR_UNAUTHORIZED
    body = response.json()
    assert body["response_type"] == "error"
    assert error_data["message"]


def test_an_unrelated_role_is_denied_before_existence_is_consulted(api):
    """PRD §2.9: "Authentication precedes authorization, existence precedes ownership,
    and state legality precedes the version precondition".
    PRD §2.9: "This check guards order release, order allocation, pick start, pick
    completion, cutoff certification, order cancellation, return approval, return
    receiving and claim resumption."

    Design: Corner/validations/unrelated_role_is_denied_before_existence_is_checked
    """
    setup_clock(api)
    setup_account(api)

    response = api.release_order(ABSENT_ORDER, PICKER)
    error_data = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    assert error_data["error_id"] != ApiErrorId.ERR_ORDER_NOT_FOUND


def test_ownership_is_checked_before_the_order_state(api):
    """PRD §2.1: "ownership checks on any resource that references a `CustomerAccount`
    compare the resource's `account_id` (the account recorded on the order, or the account
    named when an order is opened) to `X-User-ID`, and a mismatch is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/validations/item_ownership_is_checked_before_the_order_state
    """
    scenario = setup_draft_order(
        api,
        lines_spec=[{"price": 1500, "qty": 1, "bundle": 4, "on_hand": 10, "sku": "OW-1001"}],
    )
    rival = setup_account(api, account_name="School Street Supply")
    order = scenario["order"]

    denied = api.release_order(order["id"], account_headers(rival))
    validate_error(denied, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    released = validate_success(api.release_order(order["id"], scenario["acct_headers"]))
    assert released["order_status"] == "RELEASED"
    version_after_owner = released["version"]

    again = api.release_order(order["id"], scenario["acct_headers"])
    validate_error(again, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_order(order["id"], scenario["acct_headers"]))
    assert after["order_status"] == "RELEASED"
    assert after["version"] == version_after_owner, (
        "the rival never mutated the order and the second release was refused"
    )


def test_cutoff_certification_checks_state_before_the_window_rules(api):
    """PRD §2.9: "State legality. The target resource must be in a state that permits the
    operation, and the transition must be one the state machine lists for that state;
    otherwise `ERR_INVALID_STATE` (409). This guards every state-transition operation."
    PRD §3.7: "Four conditions gate the operation: the order's `fulfillment_status` must be
    `PICKED`; its shipment must be in state `STAGED`".

    Design: Corner/validations/confirm_cutoff_checks_state_before_the_windows_and_the_quota
    """
    scenario = setup_order_scenario(
        api,
        lines_spec=[{"price": 1500, "qty": 1, "bundle": 4, "on_hand": 5, "sku": "PR-1001"}],
        target="ALLOCATED",
        utc="2026-09-14T10:05:00Z",
    )
    order = scenario["order"]

    response = api.confirm_cutoff(
        order["id"],
        {"expected_order_version": order["version"], "service_level": "GROUND"}, DCM)
    error_data = validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    assert error_data["error_id"] != ApiErrorId.ERR_PROMISE_DATE_IN_PAST
    after = validate_success(api.get_order(order["id"], scenario["acct_headers"]))
    assert after["fulfillment_status"] == "ALLOCATED"

    shipments, _meta = validate_paginated(api.list_shipments(
        ADMIN, {"order_id": order["id"], "limit": 10, "offset": 0}))
    assert shipments == [], "no shipment was minted by the refused certification"


def test_inbound_capacity_admits_within_the_limit_and_refuses_beyond_it(api):
    """PRD §3.4: "before the order is committed the center's remaining inbound headroom is
    checked: if the allocation would push the center's `inbound_reserved_units` past its
    `inbound_capacity_units`, the allocation is refused with
    `ERR_INBOUND_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/inbound_capacity_is_a_fiscal_check_that_runs_last
    """
    setup_clock(api)
    dc = setup_center(api, inbound_capacity_units=10)
    acct = setup_account(api)
    catalog = setup_curated_items(
        api, specs=[{"sku": "FC-1001", "price": 1000, "bundle": 20, "on_hand": 30}],
        account=acct, dc=dc, sku_prefix="FC")
    item = catalog["items"][0]
    headers = account_headers(acct)

    first = validate_success(api.create_order(
        {"account_id": acct["id"], "lines": [{"item_id": item["id"], "quantity": 9}]},
        headers), 201)
    first_released = validate_success(api.release_order(first["id"], headers))
    validate_success(api.allocate_order(
        first["id"], {"expected_order_version": first_released["version"]}, headers))

    after_first = validate_success(api.get_distribution_center(dc["id"], DCM))
    assert after_first["inbound_reserved_units"] == 9

    second = validate_success(api.create_order(
        {"account_id": acct["id"], "lines": [{"item_id": item["id"], "quantity": 2}]},
        headers), 201)
    second_released = validate_success(api.release_order(second["id"], headers))

    response = api.allocate_order(
        second["id"], {"expected_order_version": second_released["version"]}, headers)
    validate_error(response, ApiErrorId.ERR_INBOUND_CAPACITY_EXCEEDED)

    blocked = validate_success(api.get_order(second["id"], headers))
    assert blocked["fulfillment_status"] == "AWAITING_RELEASE"
    assert blocked["allocated_dc_id"] is None

    after_second = validate_success(api.get_distribution_center(dc["id"], DCM))
    assert after_second["inbound_reserved_units"] == 9, (
        "the refused allocation reserved nothing"
    )