"""Corner coverage: entity creation, retrieval, listing and field contracts.

Breadth file (queue B).
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_open_region,
    create_referential_integration_payload,
    create_region_payload,
    enroll_member,
    get_success_data,
    set_logical_clock,
    setup_basic_scenario,
    setup_region_site_department_provider,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]
_QRB = TEST_USERS["quality_review_board_headers"]
_BAC = TEST_USERS["budget_appropriations_committee_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


def test_region_create_returns_every_declared_field_and_starts_open(api):
    """PRD §1: "Creating a region starts its `posture` at `OPEN` and both
    `premium_revenue_cents` and `operating_margin_cents` at zero."
    PRD §2.7: "`version` (integer): a system-managed counter that starts at its
    creation value and increments by one on every mutation of the resource."

    Design: Corner/entities/region_create_returns_every_declared_field_and_starts_open
    """
    set_logical_clock()
    res = api_client.create_region(create_region_payload(), _ADMIN)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")

    region = body["data"]
    assert region["posture"] == "OPEN"
    assert region["capitation_index"] == 1.0
    assert region["premium_revenue_cents"] == 0
    assert region["operating_margin_cents"] == 0
    assert region["version"] == 1
    assert region["member_count"] == 0
    assert region["id"]
    assert region["created_at"]
    assert region["updated_at"]


def test_member_get_returns_the_stored_capitation_and_region(api):
    """PRD §3.1: "The new member receives `region_id` from the region of record,
    and `status` begins at `ACTIVE`."
    PRD §3.1: "The raw rate is the adjusted base plus the risk component."

    Design: Corner/entities/member_get_returns_the_stored_capitation_and_region
    """
    region, care_site, department, provider, member = setup_basic_scenario()

    res = api_client.get_member(member["id"], _RFO)
    retrieved = get_success_data(res)
    assert retrieved["member_ref"] == "M-T-1"
    assert retrieved["plan_product"] == "COMMERCIAL_HMO"
    assert retrieved["benefit_tier"] == "TIER_1"
    assert retrieved["risk_score"] == 1.0
    assert retrieved["capitation_rate_cents"] == 84000
    assert retrieved["region_id"] == region["id"]
    assert retrieved["attributed_provider_id"] == provider["id"]
    assert retrieved["status"] == "ACTIVE"


def test_members_list_paginates_and_reports_total_count_and_has_more(api):
    """PRD §2.3: "`limit` defaults to 10; its minimum is 1 and its maximum is
    100. `offset` defaults to 0."
    PRD §2.3: "`total_count` reflects the size of the full filtered set rather
    than the page, and `has_more` is true when further items remain beyond the
    current page."

    Design: Corner/entities/members_list_paginates_and_reports_total_count_and_has_more
    """
    from test_helpers import validate_paginated

    region, care_site, department, provider = setup_region_site_department_provider()
    enroll_member(region["id"], provider["id"], member_ref="M-T-1", risk_score=1.0)
    enroll_member(
        region["id"], provider["id"], member_ref="M-T-2",
        plan_product="MEDICARE_ADVANTAGE", benefit_tier="TIER_2", risk_score=1.0,
    )
    enroll_member(
        region["id"], provider["id"], member_ref="M-T-3",
        plan_product="MEDICAID_MANAGED", benefit_tier="TIER_3", risk_score=1.0,
    )

    page = api_client.list_region_members(region["id"], _RFO, {"limit": 2, "offset": 0})
    rows, meta = validate_paginated(page)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    tail = api_client.list_region_members(region["id"], _RFO, {"limit": 2, "offset": 2})
    tail_rows, tail_meta = validate_paginated(tail)
    assert len(tail_rows) == 1
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False

    filtered = api_client.list_region_members(
        region["id"], _RFO, {"plan_product": "MEDICARE_ADVANTAGE"}
    )
    assert len(filtered.json()["data"]) == 1

    default_page, default_meta = validate_paginated(
        api_client.list_region_members(region["id"], _RFO)
    )
    assert len(default_page) == 3
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0


def test_provider_get_with_an_unknown_id_returns_provider_not_found(api):
    """PRD §2.5: "Each resource has its own not-found identifier, and the full
    set is enumerated in §5."
    PRD §5: "`ERR_PROVIDER_NOT_FOUND` | 404".

    Design: Corner/entities/provider_get_with_an_unknown_id_returns_provider_not_found
    """
    set_logical_clock()
    res = api_client.get_provider(NON_EXISTENT_UUID, _RFO)
    assert res.status_code == 404, res.text
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_PROVIDER_NOT_FOUND"
    assert body["data"]["message"]


def test_care_site_create_defaults_the_server_computed_counters_to_zero(api):
    """PRD §3.3: "The site's `staffing_fte_filled` and
    `facility_investment_spent_cents` both begin at zero".
    PRD §2.6: "`staffing_and_facility_cents` is the sum, over the region's care
    sites, of filled full-time-equivalents multiplied by one million two hundred
    fifty thousand cents plus the site's `facility_investment_spent_cents`."

    Design: Corner/entities/care_site_create_omitting_staffing_fte_filled_defaults_to_zero
    """
    set_logical_clock()
    region = create_open_region()
    res = api_client.create_care_site(
        region["id"],
        {
            "site_name": "Zero Staff Site",
            "site_type": "MEDICAL_OFFICE",
            "licensed_beds": 0,
            "staffing_fte_budget": 8.0,
            "facility_investment_budget_cents": 500000,
        },
        _RFO,
    )
    assert res.status_code == 201, res.text
    site = res.json()["data"]
    assert site["staffing_fte_filled"] == 0
    assert site["facility_investment_spent_cents"] == 0
    assert site["staffing_fte_budget"] == 8.0

    region_after = get_success_data(api_client.get_region(region["id"], _RFO))
    assert region_after["staffing_and_facility_cents"] == 0


def test_department_patch_ignores_client_supplied_slots_committed(api):
    """PRD §3.3: "a department may be written to any of the three through a
    capacity-flag adjustment that also accepts `accepting_internal_referrals`
    and `wait_threshold_days`."
    PRD §3.3: "The department's `appointment_slots_committed` starts at zero".

    Design: Corner/entities/department_patch_ignores_client_supplied_slots_committed
    """
    region, care_site, department = setup_region_site_department_provider()[:3]

    res = api_client.adjust_department(
        department["id"],
        {"wait_threshold_days": 10, "accepting_internal_referrals": False},
        _AS,
    )
    assert res.status_code == 200, res.text
    updated = res.json()["data"]
    assert updated["wait_threshold_days"] == 10
    assert updated["accepting_internal_referrals"] is False
    assert updated["appointment_slots_committed"] == 0
    assert updated["appointment_slots_budgeted"] == 200


def test_entity_ids_and_timestamps_are_server_generated(api):
    """PRD §2.7: "`id` (string): a server-minted opaque identifier formatted as
    a UUID. Identifiers carry no type prefix and no domain-specific prefix".
    PRD §2.7: "`created_at` (string): an ISO 8601 UTC instant with three
    fractional digits, assigned at creation and never changed thereafter."

    Design: Corner/entities/entity_ids_and_timestamps_are_server_generated
    """
    from test_helpers import is_iso8601_timestamp, is_valid_uuid

    set_logical_clock()
    region = create_open_region()

    res = api_client.get_region(region["id"], _ADMIN)
    fetched = get_success_data(res)
    assert fetched["version"] == 1
    assert is_valid_uuid(fetched["id"]), f"id must be a bare UUID, got {fetched['id']!r}"
    assert fetched["created_at"] == fetched["updated_at"], (
        "a freshly created row has equal creation and update instants"
    )
    assert is_iso8601_timestamp(fetched["created_at"])


def test_quality_metric_create_requires_an_existing_provider(api):
    """PRD §2.5: "Identifiers that arrive in a request body rather than in the
    path are validated separately: an unresolvable body reference is rejected
    with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 422) rather than a 404."
    PRD §3.10: "Quality and access accountability is expressed through
    `QualityMetric` rows opened by a `QualityReviewBoard`".

    Design: Corner/entities/quality_metric_create_requires_an_existing_region_and_provider
    """
    set_logical_clock()
    region = create_open_region()
    res = api_client.create_quality_metric(
        region["id"],
        {
            "metric_code": "QUALITY_COMPOSITE",
            "period": "2026-09",
            "target_value": 80,
            "accountable_provider_id": NON_EXISTENT_UUID,
        },
        _QRB,
    )
    assert res.status_code == 422, res.text
    assert res.json()["data"]["error_id"] == "ERR_REFERENCED_RESOURCE_NOT_FOUND"