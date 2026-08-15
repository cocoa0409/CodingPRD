"""List endpoints: pagination envelope, filters, FK reverse-reachability, and the
success/error response envelope shape."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    complete_work_order,
    file_service_request,
    issue_chargeback,
    list_reserve_entries,
    setup_dispatched_work_order,
    setup_home,
    validate_error,
    validate_paginated,
    validate_success,
    get_reserve_for_home,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["rep_headers"]
FINANCE = TEST_USERS["finance_headers"]


def test_service_request_list_pagination_and_filters(api):
    """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
    `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
    defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD §3.2: "Requests may be listed with `home_id`, `homeowner_id`, `status`, or
    `severity` filters."

    Design: Corner/endpoints/service_request_list_pagination_and_filters
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    file_service_request(
        home["id"], homeowner["id"], item_category="HVAC",
        severity="STANDARD", description="A",
    )
    file_service_request(
        home["id"], homeowner["id"], item_category="PLUMBING",
        severity="STANDARD", description="B",
    )
    file_service_request(
        home["id"], homeowner["id"], item_category="ELECTRICAL",
        severity="URGENT", description="C",
    )

    page0, meta0 = validate_paginated(
        api.list_service_requests(
            REP, params={"home_id": home["id"], "limit": 2, "offset": 0}
        )
    )
    assert meta0["total_count"] == 3
    assert meta0["has_more"] is True
    assert len(page0) == 2

    page2, meta2 = validate_paginated(
        api.list_service_requests(
            REP, params={"home_id": home["id"], "limit": 2, "offset": 2}
        )
    )
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert len(page2) == 1

    urgent, meta_urgent = validate_paginated(
        api.list_service_requests(
            REP, params={"home_id": home["id"], "severity": "URGENT"}
        )
    )
    assert meta_urgent["total_count"] == 1
    assert len(urgent) == 1 and urgent[0]["severity"] == "URGENT"


def test_fk_reverse_filtered_lists(api):
    """PRD §3.2: "Requests may be listed with `home_id`, `homeowner_id`, `status`,
    or `severity` filters."
    PRD §3.3: "Work orders may be listed with `service_request_id`,
    `trade_partner_id`, or `status` filters."
    PRD §3.6: "Chargebacks may be listed with `work_order_id`, `trade_partner_id`,
    or `status` filters."
    PRD §2.8: "Because a home's reserve is one-to-one, filtering the reserve
    collection by `home_id` yields an array of length zero or one, never more."
    PRD §3.7: "Reserves may be listed with `home_id` or `alert_status` filters,
    and a reserve's ledger may be read with a `kind` filter."

    Design: Corner/endpoints/fk_reverse_filtered_lists
    """
    ctx = setup_dispatched_work_order(estimated_cost_cents=110_000)
    ctx["chargeback"] = issue_chargeback(ctx["work_order"]["id"])
    complete_work_order(ctx["work_order"]["id"], ctx["partner"]["id"], 110_000)

    requests, meta = validate_paginated(
        api.list_service_requests(REP, params={"home_id": ctx["home"]["id"]})
    )
    assert meta["total_count"] == 1
    assert [r["id"] for r in requests] == [ctx["request"]["id"]]

    orders, meta = validate_paginated(
        api.list_work_orders(REP, params={"trade_partner_id": ctx["partner"]["id"]})
    )
    assert meta["total_count"] == 1
    assert [o["id"] for o in orders] == [ctx["work_order"]["id"]]

    chargebacks, meta = validate_paginated(
        api.list_chargebacks(REP, params={"work_order_id": ctx["work_order"]["id"]})
    )
    assert meta["total_count"] == 1
    assert [c["id"] for c in chargebacks] == [ctx["chargeback"]["id"]]

    reserve = get_reserve_for_home(ctx["home"]["id"])  # exactly one, by contract
    draws = list_reserve_entries(reserve["id"], kind="DRAW")
    assert len(draws) == 1
    assert draws[0]["amount_cents"] == -110_000
    assert draws[0]["work_order_ref"] == ctx["work_order"]["id"]


def test_response_envelope_shape(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/response_envelope_shape
    """
    _homeowner, home = setup_home(closing_date="2026-06-01")

    ok_resp = api.get_home(home["id"], MANAGER)
    data = validate_success(ok_resp, 200)
    body = ok_resp.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    assert data["id"] == home["id"]

    err_resp = api.get_home(NON_EXISTENT_UUID, MANAGER)
    validate_error(err_resp, ApiErrorId.ERR_HOME_NOT_FOUND)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_HOME_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str)
    assert err_body["data"]["message"].strip(), "message must be non-empty"
    assert set(err_body["meta"].keys()) == {
        "api_request_id",
        "api_request_timestamp",
    }, "error meta carries only the request id and timestamp"
