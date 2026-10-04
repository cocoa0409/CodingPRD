"""Corner queue — endpoint surface: envelopes, pagination, filtering, nesting.

Each test translates one corner-design `endpoints` instance and cites the PRD
sentence that pins the asserted rule.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_trade_fund,
    create_category,
    create_launch_with_phases,
    create_plan,
    create_retailer_payload,
    file_deduction,
    is_iso8601_timestamp,
    setup_activated_plan,
    setup_proposed_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

_FUND_COMPUTED_FIELDS = (
    "edlp_accrued_cents",
    "event_accrued_cents",
    "edlp_cash_cents",
    "event_cash_cents",
    "event_reserved_cents",
    "edlp_settled_cents",
    "event_settled_cents",
    "total_invoiced_cents",
    "edlp_available_cents",
    "event_available_cents",
)


def test_success_envelope_carries_meta_and_object_type(api, platform_admin_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    A create success body carries `meta.api_request_id`, an ISO 8601
    `meta.api_request_timestamp`, `response_type` "object", and the created
    resource in `data`.

    Design: Corner/endpoints/response_envelope_success_shape
    """
    resp = api.create_retailer(
        create_retailer_payload(name="Retailer Alpha", country_code="US", channels=["MASS"]),
        platform_admin_headers,
    )
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object", (
        f"a single-resource create must answer response_type 'object', got {body['response_type']!r}"
    )
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta.get('api_request_id')!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp must be ISO 8601, got {meta.get('api_request_timestamp')!r}"
    )
    assert body["data"]["id"] == data["id"]


def test_error_envelope_carries_error_type_and_message(api, manufacturer_planner_headers):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §2.6: "an unresolvable plan id in a path yields `ERR_PLAN_NOT_FOUND` (HTTP 404)"

    A 404 body reads `response_type` "error" with `data.error_id` /
    `data.message`, and `meta` carries only the two request fields.

    Design: Corner/endpoints/error_envelope_shape
    """
    resp = api.get_plan(NON_EXISTENT_UUID, manufacturer_planner_headers)
    err = validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must contain only the two request fields, got {sorted(body['meta'].keys())}"
    )
    assert err["error_id"] == "ERR_PLAN_NOT_FOUND"
    assert isinstance(err["message"], str) and err["message"].strip(), "message must be non-empty"


def test_deduction_list_without_limit_returns_default_page(api, finance_analyst_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100"
    PRD §2.3: "Paginated list responses carry four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Twelve filed deductions, no `limit`: the first page holds 10, with
    `total_count` 12 and `has_more` true.

    Design: Corner/endpoints/pagination_defaults_limit_10
    """
    scenario = setup_activated_plan()
    fund_id = scenario["fund"]["id"]
    retailer_id = scenario["retailer"]["id"]
    for i in range(12):
        file_deduction(fund_id, retailer_id, f"CL-{i + 1:02d}", bucket="EDLP", amount_cents=100)

    data, meta = validate_paginated(api.list_deductions(fund_id, finance_analyst_headers))
    assert len(data) == 10, f"default page must hold 10 items, got {len(data)}"
    assert meta["limit"] == 10, f"omitted limit must default to 10, got {meta['limit']}"
    assert meta["offset"] == 0
    assert meta["total_count"] == 12
    assert meta["has_more"] is True


def test_plan_list_limit_above_max_rejected(api, manufacturer_planner_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100 — a `limit` outside the range 1 to 100 is a body-shape violation rejected with `ERR_VALIDATION` (HTTP 400)."

    `limit=101` exceeds the maximum 100.

    Design: Corner/endpoints/pagination_limit_out_of_range_returns_400
    """
    setup_proposed_plan()
    validate_error(
        api.list_plans(manufacturer_planner_headers, params={"limit": 101}),
        ApiErrorId.ERR_VALIDATION,
    )


def test_plan_list_status_filter_returns_only_matches(api, manufacturer_planner_headers):
    """PRD §4: "| GET | `/jbp/plans` | List plans, filterable by `retailer_id`, `category_id`, `status`, `fiscal_year` | All six roles |"

    With one ACTIVATED and one PROPOSED plan, `?status=ACTIVATED` returns
    exactly the ACTIVATED one.

    Design: Corner/endpoints/list_filter_by_status
    """
    scenario = setup_activated_plan()
    activated_plan = scenario["plan"]
    other_category = create_category(name="Paper Care")
    create_plan(scenario["retailer"]["id"], other_category["id"], growth_target_pct=5)

    data, meta = validate_paginated(
        api.list_plans(manufacturer_planner_headers, params={"status": "ACTIVATED"})
    )
    assert len(data) == 1, f"the status filter must return only matches, got {len(data)}"
    assert data[0]["id"] == activated_plan["id"]
    assert data[0]["status"] == "ACTIVATED"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_phase_id_from_other_launch_is_not_found(api, manufacturer_planner_headers):
    """PRD §2.6: "a deeper child id — an event, analysis, shelf recommendation, launch, phase, fund, deduction, forecast, price-pack decision, or review — that does not resolve under its named parent yields `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."
    PRD §2.6: "A child id that exists but belongs to a different parent is reported as not found under the requested parent, never as a cross-parent leak."

    A phase id minted under launch L2 PATCHed beneath launch L1 is a 404.

    Design: Corner/endpoints/nested_child_not_found_under_wrong_parent
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    launch_one, _ = create_launch_with_phases(
        plan_id, product_name="UltraTabs", pack_family="tabs", launch_date="2027-03-01T00:00:00Z"
    )
    launch_two, phases_two = create_launch_with_phases(
        plan_id, product_name="MegaPods", pack_family="pods", launch_date="2027-06-01T00:00:00Z"
    )
    foreign_phase_id = phases_two[0]["id"]

    validate_error(
        api.patch_launch_phase(
            launch_one["id"],
            foreign_phase_id,
            {"distribution_target_pct": 10},
            manufacturer_planner_headers,
        ),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND,
    )


def test_fund_list_plan_id_filter_locates_single_zeroed_fund(api, finance_analyst_headers):
    """PRD §3.6: "Anyone can inspect the resulting fund — all six roles read funds, and the fund list accepts a `plan_id` filter that locates a plan's single fund."
    PRD §3.1: "On success the server creates the plan's one and only **TradeFund** — stamped with the plan's id, the locked `accrual_rate_pct` and `edlp_split_pct`, and every computed balance at zero"

    The `plan_id` filter returns the plan's one fund as a length-1 page, with
    the locked activation parameters and every computed balance at zero.

    Design: Corner/endpoints/funds_filter_by_plan_id_returns_single_fund
    """
    scenario = setup_activated_plan()  # accrual_rate_pct 4, edlp_split_pct 60
    plan_id = scenario["plan"]["id"]

    data, meta = validate_paginated(
        api.list_funds(finance_analyst_headers, params={"plan_id": plan_id})
    )
    assert len(data) == 1, f"exactly one fund per plan, got {len(data)}"
    assert meta["total_count"] == 1
    fund = data[0]
    assert_trade_fund(fund)
    assert fund["id"] == scenario["fund"]["id"]
    assert fund["plan_id"] == plan_id
    assert fund["accrual_rate_pct"] == 4
    assert fund["edlp_split_pct"] == 60
    for field in _FUND_COMPUTED_FIELDS:
        assert fund[field] == 0, f"fresh fund must zero {field}, got {fund[field]}"
