"""Case creation, response envelopes, request-shape validation, listing,
and immediate consistency (PRD §2.1-2.4, §2.6, §3.1, §3.3, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_class,
    add_data_request,
    add_entry,
    add_intervenor,
    add_rate_base_item,
    add_regulatory_asset,
    assert_instant_equals,
    assert_rate_base_item,
    assert_rate_case,
    assert_test_year_entry,
    create_case,
    create_rate_case_payload,
    create_regulatory_asset_payload,
    create_test_year_entry_payload,
    create_adjustment_payload,
    create_intervenor_payload,
    create_customer_class_payload,
    get_case,
    setup_discovery_case,
    setup_filed_case,
    validate_error,
    validate_paginated,
    validate_success,
    DEFAULT_CLOCK_ISO,
)
from test_helpers import TEST_USERS, make_intervenor_rep_headers

UF = TEST_USERS["utility_filer_alice"]


def test_rate_case_creation_defaults_and_envelope(api, filer_headers):
    """PRD §3.1: "A new case enters `DRAFT`, and the two aggregate counters
    `overdue_data_request_count` and `assented_proposal_count` initialize to zero."
    PRD §2.6: "At startup, before any call, the clock reads exactly
    `2026-08-01T00:00:00Z`; it never falls back to wall-clock time."

    Design: Corner/entities/rate_case_creation_defaults_and_envelope
    """
    res = api.create_rate_case(create_rate_case_payload(), filer_headers)
    assert res.status_code == 201
    body = res.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    case = body["data"]
    assert_rate_case(case)
    assert case["status"] == "DRAFT"
    assert case["overdue_data_request_count"] == 0
    assert case["assented_proposal_count"] == 0
    assert_instant_equals(case["created_at"], DEFAULT_CLOCK_ISO, "created_at")
    assert case.get("discovery_close_at") is None
    assert case.get("authorized_revenue_requirement_cents") is None


def test_missing_required_field_returns_invalid_request(api, filer_headers):
    """PRD §2.9: "First, request-shape checks (required fields present, no
    unknown fields, enum members valid, integer ranges respected, tier arrays
    well-formed) — failures are `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/missing_required_field_returns_invalid_request
    """
    payload = create_rate_case_payload()
    del payload["case_number"]
    res = api.create_rate_case(payload, filer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_invalid_enum_value_returns_invalid_request(api, filer_headers):
    """PRD §2.9: "First, request-shape checks (required fields present, no
    unknown fields, enum members valid, integer ranges respected, tier arrays
    well-formed) — failures are `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/invalid_enum_value_returns_invalid_request
    """
    case = create_case()
    res = api.create_test_year_entry(
        create_test_year_entry_payload(case["id"], category="CAPEX", booked_amount_cents=100),
        filer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    data, meta = validate_paginated(api.list_test_year_entries(
        filer_headers, params={"rate_case_id": case["id"]}))
    assert meta["total_count"] == 0, "no TestYearEntry row may be persisted"


def test_duplicate_case_number_rejected(api, filer_headers):
    """PRD §3.1: "`case_number` (the unique docket number, for example
    `UR-2026-104`, unique across all cases — a duplicate is
    `ERR_CASE_NUMBER_NOT_UNIQUE`)"

    Design: Corner/entities/duplicate_case_number_rejected
    """
    first = create_case()
    res = api.create_rate_case(
        create_rate_case_payload(
            utility_name="Duplicate Docket Co", return_on_rate_base_bp=800,
            proposed_revenue_requirement_cents=100000000,
            allocation_method="ENERGY_AVERAGE"),
        filer_headers)
    validate_error(res, ApiErrorId.ERR_CASE_NUMBER_NOT_UNIQUE, expected_status=422)
    res2 = api.create_rate_case(
        create_rate_case_payload(
            case_number="UR-2026-105", utility_name="Other State Gas",
            return_on_rate_base_bp=800, proposed_revenue_requirement_cents=100000000,
            allocation_method="ENERGY_AVERAGE"),
        filer_headers)
    second = validate_success(res2, 201)
    assert second["id"] != first["id"]


def test_duplicate_class_code_within_case_rejected(api, filer_headers):
    """PRD §3.7: "`class_code` (unique within the case — a duplicate is
    `ERR_CLASS_CODE_NOT_UNIQUE`)"

    Design: Corner/entities/duplicate_class_code_within_case_rejected
    """
    case_a = create_case()
    case_b = create_case(case_number="UR-2026-999", utility_name="Other State Gas",
                         return_on_rate_base_bp=800,
                         proposed_revenue_requirement_cents=100000000,
                         allocation_method="ENERGY_AVERAGE")
    add_class(case_a["id"])
    small = dict(customer_count=5, monthly_kwh_per_customer=100, annual_kwh=6000,
                 coincident_peak_kw=10, average_demand_kw=5,
                 present_customer_charge_cents=100,
                 present_tiers=[{"up_to_kwh": None, "rate_mills": 500}])
    res = api.create_customer_class(
        create_customer_class_payload(case_a["id"], **small), filer_headers)
    validate_error(res, ApiErrorId.ERR_CLASS_CODE_NOT_UNIQUE, expected_status=422)
    res_b = api.create_customer_class(
        create_customer_class_payload(case_b["id"], **small), filer_headers)
    cls_b = validate_success(res_b, 201)
    assert cls_b["rate_case_id"] == case_b["id"]


def test_computed_and_system_fields_on_create(api, filer_headers):
    """PRD §3.3: "The item's net rate base is computed as
    `plant_in_service_cents` minus `accumulated_depreciation_cents` plus
    `working_capital_cents` minus `accumulated_deferred_taxes_cents`; this
    `net_rate_base_cents` is stored on the item."
    PRD §3.1: "On creation, `adjusted_amount_cents` equals `booked_amount_cents`
    and the entry's status is `DRAFT`."

    Design: Corner/entities/computed_and_system_fields_on_create
    """
    case = create_case()
    item = validate_success(api.create_rate_base_item(
        {
            "rate_case_id": case["id"], "label": "Generation plant",
            "plant_in_service_cents": 3000000000,
            "accumulated_depreciation_cents": 500000000,
            "working_capital_cents": 100000000,
            "accumulated_deferred_taxes_cents": 200000000,
        }, filer_headers), 201)
    assert_rate_base_item(item)
    assert item["net_rate_base_cents"] == 2400000000
    assert item["status"] == "DRAFT"
    entry = validate_success(api.create_test_year_entry(
        create_test_year_entry_payload(case["id"]), filer_headers), 201)
    assert_test_year_entry(entry)
    assert entry["adjusted_amount_cents"] == 1000000000
    assert entry["status"] == "DRAFT"
    assert_instant_equals(entry["created_at"], DEFAULT_CLOCK_ISO, "entry created_at")


def test_invalid_date_ranges_return_invalid_date_range(api, filer_headers):
    """PRD §3.1: "The test-year window is a closed interval: `test_year_end`
    must be strictly after `test_year_start`, otherwise `ERR_INVALID_DATE_RANGE`."
    PRD §3.6: "`incurrence_end` must be greater than or equal to
    `incurrence_start`, otherwise `ERR_INVALID_DATE_RANGE`"

    Design: Corner/validations/invalid_date_ranges_return_invalid_date_range
    """
    case = create_case()
    res1 = api.create_rate_case(
        create_rate_case_payload(
            case_number="UR-2026-200", utility_name="Bad Dates Utility",
            test_year_start="2025-12-31T00:00:00Z",
            test_year_end="2025-12-31T00:00:00Z",
            proposed_revenue_requirement_cents=100000000),
        filer_headers)
    validate_error(res1, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=400)
    res2 = api.create_regulatory_asset(
        create_regulatory_asset_payload(
            case["id"], asset_name="Inverted window", principal_cents=1000,
            incurrence_start="2024-06-30T00:00:00Z",
            incurrence_end="2024-01-01T00:00:00Z", amortization_months=2),
        filer_headers)
    validate_error(res2, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=400)


def test_zero_amount_adjustment_returns_invalid_request(api, filer_headers):
    """PRD §3.2: "a signed `amount_cents` (which must not equal zero)"
    PRD §2.9: "First, request-shape checks (required fields present, no unknown
    fields, enum members valid, integer ranges respected, tier arrays
    well-formed) — failures are `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/zero_amount_adjustment_returns_invalid_request
    """
    case = create_case()
    entry = add_entry(case["id"])
    res = api.create_adjustment(
        create_adjustment_payload(case["id"], entry["id"], amount_cents=0,
                                  reason="Zero adjustment"),
        filer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    data, meta = validate_paginated(api.list_adjustments(
        filer_headers, params={"rate_case_id": case["id"]}))
    assert meta["total_count"] == 0, "no Adjustment row may be persisted"


def test_error_envelope_shape_on_failures(api, filer_headers):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
    unique, machine-readable string that identifies the specific error."

    Design: Corner/errors/error_envelope_shape_on_failures
    """
    res404 = api.get_rate_case(NON_EXISTENT_UUID, filer_headers)
    err1 = validate_error(res404, ApiErrorId.ERR_RATE_CASE_NOT_FOUND, expected_status=404)
    assert err1["message"].strip()
    res403 = api.submit_filing(NON_EXISTENT_UUID, make_intervenor_rep_headers("ir_any"))
    err2 = validate_error(res403, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                          expected_status=403)
    assert err2["message"].strip()
    for res in (res404, res403):
        body = res.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
            "error meta must contain only api_request_id and api_request_timestamp"
        )


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
    `X-User-Role`. Either header missing or empty is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_rate_cases(headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                   expected_status=400)


def test_role_check_beats_existence_returns_forbidden(api):
    """PRD §2.1: "Once headers are present, the role named in `X-User-Role` is
    checked against the endpoint's authorized role list; a caller whose role is
    not listed is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.9: "After shape and date checks, authentication header presence, then
    role authorization, then ownership scope, then segregation of duties. After
    auth come existence checks (each `ERR_*_NOT_FOUND`)"

    Design: Corner/validations/role_check_beats_existence_returns_forbidden
    """
    res = api.submit_filing(NON_EXISTENT_UUID, make_intervenor_rep_headers("ir_any"))
    assert res.status_code == 403
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_get_nonexistent_case_child_resources_returns_not_found(api, filer_headers):
    """PRD §2.7: "Each identifier must reference an existing resource, otherwise
    the request is rejected with the resource-type-specific not-found error
    listed in §5 (for example, an unknown case id on any
    `/api/v1/rate-cases/{caseId}/...` path is `ERR_RATE_CASE_NOT_FOUND`)."

    Design: Corner/entities/get_nonexistent_case_child_resources_returns_not_found
    """
    res1 = api.get_rate_case("11111111-1111-4111-8111-111111111111", filer_headers)
    validate_error(res1, ApiErrorId.ERR_RATE_CASE_NOT_FOUND, expected_status=404)
    res2 = api.get_adjustment("22222222-2222-4222-8222-222222222222", filer_headers)
    validate_error(res2, ApiErrorId.ERR_ADJUSTMENT_NOT_FOUND, expected_status=404)
    res3 = api.get_compliance_filing("33333333-3333-4333-8333-333333333333", filer_headers)
    validate_error(res3, ApiErrorId.ERR_FILING_NOT_FOUND, expected_status=404)


def test_get_nonexistent_remaining_resources_returns_not_found(api, filer_headers):
    """PRD §2.7: "Each identifier must reference an existing resource, otherwise
    the request is rejected with the resource-type-specific not-found error
    listed in §5 (for example, an unknown case id on any
    `/api/v1/rate-cases/{caseId}/...` path is `ERR_RATE_CASE_NOT_FOUND`)."

    Design: Corner/entities/get_nonexistent_remaining_resources_returns_not_found
    """
    checks = [
        (api.get_intervenor("11111111-1111-4111-8111-111111111111", filer_headers),
         ApiErrorId.ERR_INTERVENOR_NOT_FOUND),
        (api.get_test_year_entry("22222222-2222-4222-8222-222222222222", filer_headers),
         ApiErrorId.ERR_ENTRY_NOT_FOUND),
        (api.get_rate_base_item("33333333-3333-4333-8333-333333333333", filer_headers),
         ApiErrorId.ERR_ITEM_NOT_FOUND),
        (api.get_customer_class("44444444-4444-4444-8444-444444444444", filer_headers),
         ApiErrorId.ERR_CLASS_NOT_FOUND),
        (api.get_data_request("55555555-5555-4555-8555-555555555555", filer_headers),
         ApiErrorId.ERR_DATA_REQUEST_NOT_FOUND),
        (api.get_settlement_proposal("66666666-6666-4666-8666-666666666666", filer_headers),
         ApiErrorId.ERR_PROPOSAL_NOT_FOUND),
        (api.get_settlement_signatory("77777777-7777-4777-8777-777777777777", filer_headers),
         ApiErrorId.ERR_SIGNATORY_NOT_FOUND),
        (api.get_regulatory_asset("88888888-8888-4888-8888-888888888888", filer_headers),
         ApiErrorId.ERR_ASSET_NOT_FOUND),
        (api.get_amortization_entry("99999999-9999-4999-8999-999999999999", filer_headers),
         ApiErrorId.ERR_AMORT_ENTRY_NOT_FOUND),
    ]
    for res, err_id in checks:
        validate_error(res, err_id, expected_status=404)


def test_pagination_limit_offset_has_more(api, filer_headers):
    """PRD §2.3: "All list endpoints accept `limit` and `offset` query
    parameters." and "The `meta` block of every list response carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/pagination_limit_offset_has_more
    """
    case = create_case()
    ids = set()
    for party, rep, mail in (
        ("AAA Industrial Group", "Rae Torres", "rae@aaa.example"),
        ("BBB Consumer Advocates", "Sam Cho", "sam@bbb.example"),
        ("CCC Farmers Cooperative", "Lee Park", "lee@ccc.example"),
    ):
        iv = add_intervenor(case["id"], party, rep, mail)
        ids.add(iv["id"])
    page1, meta1 = validate_paginated(api.list_intervenors(
        filer_headers, params={"rate_case_id": case["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(api.list_intervenors(
        filer_headers, params={"rate_case_id": case["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert {r["id"] for r in page1} | {r["id"] for r in page2} == ids
    assert not ({r["id"] for r in page1} & {r["id"] for r in page2}), (
        "pages must not overlap"
    )


def test_fk_reverse_reachability_filtered_lists(api, filer_headers):
    """PRD §4: "List adjustments; filterable by rate_case_id, test_year_entry_id,
    status" and "List data requests; filterable by rate_case_id,
    issuing_intervenor_id, referenced_adjustment_id, status".

    Design: Corner/entities/fk_reverse_reachability_filtered_lists
    """
    s = setup_discovery_case()
    i1 = add_intervenor(s.case["id"])
    i2 = add_intervenor(s.case["id"], "BBB Consumer Advocates", "Sam Cho", "sam@bbb.example")
    dr1 = add_data_request(s.case["id"], intervenor_id=i1["id"])
    data, meta = validate_paginated(api.list_adjustments(
        filer_headers, params={"test_year_entry_id": s.e1["id"]}))
    assert meta["total_count"] == 1 and data[0]["id"] == s.a1["id"]
    assert data[0]["status"] == "ACCEPTED", "A1 cascaded to ACCEPTED at submit-filing"
    data, meta = validate_paginated(api.list_adjustments(
        filer_headers, params={"test_year_entry_id": s.e2["id"]}))
    assert meta["total_count"] == 0
    data, meta = validate_paginated(api.list_data_requests(
        filer_headers, params={"issuing_intervenor_id": i1["id"]}))
    assert meta["total_count"] == 1 and data[0]["id"] == dr1["id"]
    data, meta = validate_paginated(api.list_data_requests(
        filer_headers, params={"issuing_intervenor_id": i2["id"]}))
    assert meta["total_count"] == 0


def test_immediate_consistency_on_create_and_read(api, filer_headers):
    """PRD §3.7: "On creation the server computes `present_revenue_cents` and
    `allocated_cost_cents`, and refreshes the case's `present_revenue_total_cents`
    as the sum of `present_revenue_cents` over all classes of the case."

    Design: Corner/consistency_model/immediate_consistency_on_create_and_read
    """
    case = create_case()
    res = api.create_customer_class(create_customer_class_payload(case["id"]), filer_headers)
    cls = validate_success(res, 201)
    assert cls["present_revenue_cents"] == 1128000000, (
        "12 * 20000 * (800 + 300*7 + 200*9) computed in the create response itself"
    )
    case_after = get_case(case["id"])
    assert case_after["present_revenue_total_cents"] == 1128000000, (
        "aggregate refreshed synchronously on the immediately-following read"
    )
