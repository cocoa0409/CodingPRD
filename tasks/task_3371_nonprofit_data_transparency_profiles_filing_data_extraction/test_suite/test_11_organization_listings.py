"""Response envelope shape and list-endpoint pagination."""
from test_helpers import (
    assert_pagination_meta,
    create_filing,
    create_org,
    make_admin_headers,
    scenario_org_with_normalized_filing,
    set_clock,
    validate_paginated,
    void_filing,
)


def test_response_envelope_shape_is_stable_across_object_and_array_responses(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body".
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/endpoints/response_envelope_shape_is_stable_across_object_and_array_responses
    """
    set_clock()
    org = create_org("Willow Creek Collective", "900100200", state_code="IL")

    object_resp = api.get_organization(org["id"], make_admin_headers())
    assert object_resp.status_code == 200
    object_body = object_resp.json()
    assert object_body["response_type"] == "object"
    assert isinstance(object_body["meta"]["api_request_id"], str)
    assert object_body["meta"]["api_request_id"]
    assert isinstance(object_body["meta"]["api_request_timestamp"], str)

    array_resp = api.list_organizations(make_admin_headers(), {"limit": 100, "offset": 0})
    array_body = array_resp.json()
    assert array_body["response_type"] == "array"
    assert isinstance(array_body["meta"]["api_request_id"], str)
    assert isinstance(array_body["meta"]["api_request_timestamp"], str)

    rows, meta = validate_paginated(array_resp)
    assert_pagination_meta(meta, limit=100, offset=0, total_count=1, has_more=False)
    assert len(rows) == 1


def test_filing_list_paginates_and_keeps_voided_revisions_visible(api):
    """PRD §2.3: "`total_count` is the number of resources matching the filter
    across all pages, not the number in the current page, and `has_more` is true
    exactly when `offset` plus the number of items in the current page is less
    than `total_count`."
    PRD §4: "GET /nonprofits/organizations/{id}/filings — List the organization's
    information-return filings, including superseded revisions".

    Design: Corner/cross_cutting_layers/filing_list_filters_by_status_and_tax_year_and_paginates
    """
    set_clock()
    org, filing_2025 = scenario_org_with_normalized_filing()

    filing_2024 = create_filing(org["id"], tax_year=2024,
                                coverage_start="2024-01-01T00:00:00Z",
                                coverage_end="2024-12-31T00:00:00Z")
    filing_2023 = create_filing(org["id"], tax_year=2023,
                                coverage_start="2023-01-01T00:00:00Z",
                                coverage_end="2023-12-31T00:00:00Z")
    void_filing(filing_2023["id"])

    page_one = api.list_organization_filings(
        org["id"], make_admin_headers(), {"limit": 2, "offset": 0})
    rows, meta = validate_paginated(page_one)
    assert len(rows) == 2
    assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)

    page_two = api.list_organization_filings(
        org["id"], make_admin_headers(), {"limit": 2, "offset": 2})
    rows_two, meta_two = validate_paginated(page_two)
    assert len(rows_two) == 1
    assert_pagination_meta(meta_two, limit=2, offset=2, total_count=3, has_more=False)

    everything = api.list_organization_filings(
        org["id"], make_admin_headers(), {"limit": 100})
    all_rows, _ = validate_paginated(everything)
    by_id = {row["id"]: row for row in all_rows}
    assert by_id[filing_2025["id"]]["status"] == "NORMALIZED"
    assert by_id[filing_2024["id"]]["status"] == "RECEIVED"
    assert by_id[filing_2023["id"]]["status"] == "VOIDED", (
        "a voided revision stays visible in the list"
    )
