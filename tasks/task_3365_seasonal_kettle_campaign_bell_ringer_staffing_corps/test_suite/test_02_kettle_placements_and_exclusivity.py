"""Kettle placement discipline: placement windows, exclusivity and location codes."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    approve_host_site,
    create_host_site,
    create_kettle_location,
    get_kettle_location,
    set_clock,
    assert_same_instant,
    setup_campaign_with_approved_host_site,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_kettle_location_not_found_returns_404(api, kettle_coordinator_headers):
    """PRD §2.9: "The resource addressed by the path identifier exists;
    otherwise `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/kettle_location_not_found_returns_404
    """
    set_clock(DEFAULT_CLOCK)
    resp = api.get_kettle_location(NON_EXISTENT_UUID, kettle_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_duplicate_location_code_within_campaign_rejected(api, platform_admin_headers,
                                                          kettle_coordinator_headers):
    """PRD §2.7: "Within a single campaign, the operator-facing `location_code`
    is unique, and a duplicate is refused with `ERR_DUPLICATE_LOCATION_CODE`
    (HTTP 409)".
    PRD §2.9: "The `location_code` is unique within the campaign; otherwise
    `ERR_DUPLICATE_LOCATION_CODE` (HTTP 409)."

    Design: Corner/validations/duplicate_location_code_within_campaign_rejected
    """
    _unit, campaign, host = setup_campaign_with_approved_host_site()
    create_kettle_location(host["id"], campaign["id"], location_code="K-114-A")

    resp = api.create_kettle_location(
        {
            "host_site_id": host["id"],
            "campaign_id": campaign["id"],
            "location_code": "K-114-A",
            "placement": "INDOOR",
            "placement_starts_on": "2026-11-01T00:00:00Z",
            "placement_ends_on": "2026-12-24T00:00:00Z",
            "daily_required_minutes": 480,
        },
        kettle_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOCATION_CODE)

    listed = api.list_kettle_locations(kettle_coordinator_headers,
                                       params={"campaign_id": campaign["id"], "limit": 100})
    _data, meta = validate_paginated(listed)
    assert meta["total_count"] == 1, "exactly one location may hold the code in the campaign"


def test_duplicate_location_code_allowed_in_other_campaign(api, kettle_coordinator_headers):
    """PRD §2.7: "Within a single campaign, the operator-facing `location_code`
    is unique, and a duplicate is refused with `ERR_DUPLICATE_LOCATION_CODE`
    (HTTP 409)".

    Design: Corner/validations/duplicate_location_code_within_campaign_rejected
    """
    _unit, campaign_a, host_a = setup_campaign_with_approved_host_site()
    create_kettle_location(host_a["id"], campaign_a["id"], location_code="K-114-A")

    _unit_b, campaign_b, host_b = setup_campaign_with_approved_host_site(
        unit_overrides={"name": "Corps 42"},
        campaign_overrides={"name": "2027 Christmas Kettle Campaign", "season_year": 2027,
                            "starts_on": "2027-11-01T00:00:00Z",
                            "ends_on": "2027-12-24T23:59:59Z"})
    resp = api.create_kettle_location(
        {
            "host_site_id": host_b["id"],
            "campaign_id": campaign_b["id"],
            "location_code": "K-114-A",
            "placement": "OUTDOOR",
            "placement_starts_on": "2027-11-01T00:00:00Z",
            "placement_ends_on": "2027-12-24T00:00:00Z",
            "daily_required_minutes": 480,
        },
        kettle_coordinator_headers,
    )
    location = validate_success(resp, expected_status=201)
    assert location["location_code"] == "K-114-A"
    assert location["campaign_id"] == campaign_b["id"]


def test_activation_at_pending_host_site_rejected(api, kettle_coordinator_headers):
    """PRD §3.1: "Moving a location from `DRAFT` to `ACTIVE` requires that the
    host site's permission be `APPROVED`".
    PRD §2.9: "The host site referenced by the request holds an `APPROVED`
    permission; otherwise `ERR_HOST_SITE_NOT_PERMITTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/location_activation_depends_on_host_site_permission
    """
    _unit, campaign, host_a = setup_campaign_with_approved_host_site()
    host_b = create_host_site(campaign["id"], retailer_name="Riverside Pharmacy",
                              store_number="208")

    location_b = create_kettle_location(host_b["id"], campaign["id"],
                                        location_code="K-208-A", placement="INDOOR")

    resp = api.activate_kettle_location(
        location_b["id"], {"expected_kettle_location_version": location_b["version"]},
        kettle_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_HOST_SITE_NOT_PERMITTED)

    after = get_kettle_location(location_b["id"])
    assert after["status"] == "DRAFT", "a rejected activation must leave the location DRAFT"
    assert after["host_site_id"] == host_b["id"]
    assert host_a["permission_status"] == "APPROVED"
    still_pending = validate_success(
        api.get_host_site(host_b["id"], kettle_coordinator_headers))
    assert still_pending["permission_status"] == "PENDING"


def test_activation_at_approved_host_site_succeeds(api, kettle_coordinator_headers):
    """PRD §3.1: "Moving a location from `DRAFT` to `ACTIVE` requires that the
    host site's permission be `APPROVED`, that the location's placement window
    be fully contained in that permission window, and that the owning campaign
    be `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/location_activation_depends_on_host_site_permission
    """
    _unit, campaign, host = setup_campaign_with_approved_host_site()
    location = create_kettle_location(host["id"], campaign["id"])

    resp = api.activate_kettle_location(
        location["id"], {"expected_kettle_location_version": location["version"]},
        kettle_coordinator_headers)
    activated = validate_success(resp)

    assert activated["status"] == "ACTIVE"
    assert activated["version"] == location["version"] + 1


def test_exclusive_site_touching_placement_window_rejected(api, kettle_coordinator_headers):
    """PRD §2.7: "at an exclusive site the organization may not operate a second
    kettle, and an overlapping placement — including one whose window merely
    touches the existing placement's window at a single instant — is refused
    with `ERR_EXCLUSIVITY_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/exclusive_host_site_closed_interval_no_touch
    """
    _unit, campaign, host_1 = setup_campaign_with_approved_host_site(
        host_overrides={"exclusivity_scope": "EXCLUSIVE", "max_kettles": 3})
    host_2 = create_host_site(campaign["id"], exclusivity_scope="EXCLUSIVE", max_kettles=3)
    approve_host_site(host_2["id"])

    create_kettle_location(host_1["id"], campaign["id"], location_code="K-114-A",
                           placement_ends_on="2026-11-30T00:00:00Z")

    resp = api.create_kettle_location(
        {
            "host_site_id": host_2["id"],
            "campaign_id": campaign["id"],
            "location_code": "K-114-B",
            "placement": "INDOOR",
            "placement_starts_on": "2026-11-30T00:00:00Z",
            "placement_ends_on": "2026-12-24T00:00:00Z",
            "daily_required_minutes": 480,
        },
        kettle_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_EXCLUSIVITY_CONFLICT)

    listed = api.list_kettle_locations(kettle_coordinator_headers,
                                       params={"campaign_id": campaign["id"], "limit": 100})
    _data, meta = validate_paginated(listed)
    assert meta["total_count"] == 1, "the touching placement must not be stored"


def test_exclusive_site_disjoint_placement_window_accepted(api, kettle_coordinator_headers):
    """PRD §2.7: "at an exclusive site the organization may not operate a second
    kettle, and an overlapping placement — including one whose window merely
    touches the existing placement's window at a single instant — is refused
    with `ERR_EXCLUSIVITY_CONFLICT` (HTTP 409)."
    PRD §2.7: "the placement window must be fully contained in the permission
    window".

    Design: Difficulty/resource_temporal_overlap/exclusive_host_site_closed_interval_no_touch
    """
    _unit, campaign, host_1 = setup_campaign_with_approved_host_site(
        host_overrides={"exclusivity_scope": "EXCLUSIVE", "max_kettles": 3})
    host_2 = create_host_site(campaign["id"], exclusivity_scope="EXCLUSIVE", max_kettles=3)
    approve_host_site(host_2["id"])

    create_kettle_location(host_1["id"], campaign["id"], location_code="K-114-A",
                           placement_ends_on="2026-11-30T00:00:00Z")

    resp = api.create_kettle_location(
        {
            "host_site_id": host_2["id"],
            "campaign_id": campaign["id"],
            "location_code": "K-114-C",
            "placement": "INDOOR",
            "placement_starts_on": "2026-12-01T00:00:00Z",
            "placement_ends_on": "2026-12-24T00:00:00Z",
            "daily_required_minutes": 480,
        },
        kettle_coordinator_headers,
    )
    location = validate_success(resp, expected_status=201)
    assert location["status"] == "DRAFT"
    assert_same_instant(location["placement_starts_on"], "2026-12-01T00:00:00Z")
