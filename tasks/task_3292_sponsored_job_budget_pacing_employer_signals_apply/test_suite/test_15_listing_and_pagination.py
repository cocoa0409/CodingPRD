"""List endpoints: filtering, pagination and ordering.

Page metadata reports the filtered total rather than the unfiltered one, and
`has_more` is true exactly when further items remain after the returned page.
"""
import pytest

from test_helpers import (
    api_client, validate_paginated, get_success_data, TEST_USERS,
    make_employer_headers, set_clock, create_employer, create_posting,
    create_active_campaign, create_sponsored_job, create_hold, get_posting,
    record_click, assert_budget_ledger_entry,
)

ADMIN = TEST_USERS["admin_headers"]


def test_job_postings_list_filters_before_paginating(api):
    """PRD §2.3: "Filters narrow the result set before pagination is applied, so
    `total_count` reflects the filtered set rather than the unfiltered one."
    PRD §2.3: "A page response echoes `limit`, `offset`, `total_count` — the total
    number of items matching the filter, ignoring pagination — and `has_more`, a
    boolean that is true exactly when further items remain after the returned
    page."

    Design: Corner/entities/job_postings_list_paginates_and_filters_by_employer
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Paged Co", domain="paged.example")
    headers = make_employer_headers(employer["id"])

    created = [
        create_posting(employer, title="First One", location="Fargo, ND",
                       description_text="First posting."),
        create_posting(employer, title="Fresh One", location="Fargo, ND",
                       description_text="Fresh one."),
        create_posting(employer, title="Fresh Two", location="Fargo, ND",
                       description_text="Fresh two."),
    ]

    page1, meta1 = validate_paginated(api.list_job_postings(
        ADMIN, params={"employer_id": employer["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_job_postings(
        ADMIN, params={"employer_id": employer["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["has_more"] is False

    active, active_meta = validate_paginated(api.list_job_postings(
        ADMIN, params={"employer_id": employer["id"], "state": "ACTIVE"}))
    assert active_meta["total_count"] == 3
    assert {row["id"] for row in active} == {p["id"] for p in created}


def test_budget_ledger_supports_entry_type_filtering(api):
    """PRD §2.3: "When a caller supplies a filter parameter that the endpoint
    does not define, or a value that is not a member of the relevant enumeration,
    the request fails general request-shape validation with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/cross_cutting_complexity_layers/budget_ledger_filters_and_paginates
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Ledger Co", domain="ldg.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Ledger Engineer")
    campaign = create_active_campaign(employer, name="LG")
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=500)

    create_hold(sponsored_job, employer, 200)
    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-lg-1")

    everything, _ = validate_paginated(api.list_campaign_budget_ledger(
        campaign["id"], headers, params={"limit": 1, "offset": 0}))
    assert len(everything) == 1

    holds, _ = validate_paginated(api.list_campaign_budget_ledger(
        campaign["id"], headers, params={"entry_type": "HOLD"}))
    assert len(holds) >= 1
    assert all(entry["entry_type"] == "HOLD" for entry in holds)

    commits, _ = validate_paginated(api.list_campaign_budget_ledger(
        campaign["id"], headers, params={"entry_type": "COMMIT"}))
    assert len(commits) >= 1
    assert all(entry["entry_type"] == "COMMIT" for entry in commits)
    for entry in commits:
        assert_budget_ledger_entry(entry)