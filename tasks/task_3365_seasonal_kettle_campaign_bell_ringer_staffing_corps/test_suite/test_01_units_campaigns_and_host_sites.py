"""Units, campaign governance and host site permissions."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    create_host_site,
    create_unit_payload,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


def test_unit_creation_returns_201_with_server_minted_uuid(api, platform_admin_headers):
    """PRD §4: "Operations that bring a new stand-alone resource into existence
    — a unit, a campaign, a host site, a kettle location, a bell ringer, a
    shift, a kettle collection, a digital gift, an assistance program, an
    assistance application, a corps program, a disaster deployment or a
    reallocation decision — return `201 Created`."
    PRD §2.5: "The `id` is a server-minted UUID string with no type prefix and
    no embedded meaning".

    Design: Corner/entities/unit_creation_returns_201_with_server_minted_uuid
    """
    set_clock(DEFAULT_CLOCK)
    resp = api.create_unit(create_unit_payload(), platform_admin_headers)
    unit = validate_success(resp, expected_status=201)

    assert is_valid_uuid(unit["id"]), "id must be a server-minted UUID"
    assert unit["version"] == 1, "a freshly created resource starts at its initial version"
    assert unit["unit_type"] == "CORPS"
    assert unit["canteen_pool_size"] == 4
    assert unit["territory_code"] == "NT"


def test_campaign_missing_required_goal_cents_returns_invalid_request(api, platform_admin_headers):
    """PRD §2.9: "The request body carries every required input declared for
    the operation and every supplied value matches its declared type."

    Design: Corner/entities/campaign_missing_required_goal_cents_returns_invalid_request
    """
    set_clock(DEFAULT_CLOCK)
    resp = api.create_campaign(
        {
            "name": "Incomplete Campaign",
            "season_year": 2026,
            "starts_on": "2026-11-01T00:00:00Z",
            "ends_on": "2026-12-24T23:59:59Z",
        },
        platform_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    listed = api.list_campaigns(platform_admin_headers)
    data, meta = validate_paginated(listed)
    assert meta["total_count"] == 0, "a rejected create must not persist a Campaign row"
    assert data == []


def test_campaign_creation_defaults_status_to_planning(api, platform_admin_headers):
    """PRD §3.2: "Every campaign is born in `PLANNING`, a posture in which host
    site permissions may be negotiated but no kettle may operate."
    PRD §3.2: "a territory-approved `goal_cents`, and an optional
    `labor_budget_cents` that defaults to 0".

    Design: Corner/entities/campaign_creation_defaults_status_to_planning
    """
    set_clock(DEFAULT_CLOCK)
    resp = api.create_campaign(
        {
            "name": "2026 Christmas Kettle Campaign",
            "season_year": 2026,
            "starts_on": "2026-11-01T00:00:00Z",
            "ends_on": "2026-12-24T23:59:59Z",
            "goal_cents": 5000000,
        },
        platform_admin_headers,
    )
    campaign = validate_success(resp, expected_status=201)

    assert campaign["status"] == "PLANNING"
    assert campaign["labor_budget_cents"] == 0
    assert campaign["total_raised_cents"] == 0


def test_campaign_status_input_ignored_on_create(api, platform_admin_headers):
    """PRD §3.2: "Every campaign is born in `PLANNING`, a posture in which host
    site permissions may be negotiated but no kettle may operate."
    PRD §3.9: "The campaign's `total_raised_cents` is the sum of the two
    components".

    Design: Corner/entities/campaign_status_input_ignored_on_create
    """
    set_clock(DEFAULT_CLOCK)
    resp = api.create_campaign(
        {
            "name": "Seeded Campaign",
            "season_year": 2026,
            "starts_on": "2026-11-01T00:00:00Z",
            "ends_on": "2026-12-24T23:59:59Z",
            "goal_cents": 5000000,
            "status": "ACTIVE",
            "total_raised_cents": 999999,
        },
        platform_admin_headers,
    )
    campaign = validate_success(resp, expected_status=201)

    assert campaign["status"] == "PLANNING", "a campaign cannot be seeded into ACTIVE"
    assert campaign["total_raised_cents"] == 0, "the derived total is not client-seedable"


def test_host_site_listing_supports_filter_and_pagination(api, platform_admin_headers,
                                                          kettle_coordinator_headers):
    """PRD §2.3: "The `meta` object of every list response carries `limit`,
    `offset`, `total_count` and `has_more`".
    PRD §2.3: "The `limit` parameter caps how many items are returned and
    defaults to 10 when omitted; its minimum accepted value is 1 and its
    maximum is 100."

    Design: Corner/entities/host_site_listing_supports_filter_and_pagination
    """
    set_clock(DEFAULT_CLOCK)
    campaign = validate_success(
        api.create_campaign(
            {
                "name": "2026 Christmas Kettle Campaign",
                "season_year": 2026,
                "starts_on": "2026-11-01T00:00:00Z",
                "ends_on": "2026-12-24T23:59:59Z",
                "goal_cents": 5000000,
            },
            platform_admin_headers,
        ),
        expected_status=201,
    )
    host_a = create_host_site(campaign["id"])
    create_host_site(campaign["id"], retailer_name="Riverside Pharmacy", store_number="208")

    from test_helpers import approve_host_site
    approve_host_site(host_a["id"])

    page = api.list_host_sites(kettle_coordinator_headers,
                               params={"campaign_id": campaign["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(page)
    assert len(data) == 1, "limit=1 must return exactly one element"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    filtered = api.list_host_sites(
        kettle_coordinator_headers,
        params={"campaign_id": campaign["id"], "permission_status": "APPROVED",
                "limit": 10, "offset": 0})
    fdata, fmeta = validate_paginated(filtered)
    assert fmeta["total_count"] == 1, "the permission_status filter must narrow the set"
    assert fdata[0]["permission_status"] == "APPROVED"


def test_host_site_create_with_unknown_campaign_returns_reference_not_found(
        api, kettle_coordinator_headers):
    """PRD §2.9: "Every body foreign key resolves to an existing row; otherwise
    `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/host_site_create_with_unknown_campaign_returns_reference_not_found
    """
    set_clock(DEFAULT_CLOCK)
    resp = api.create_host_site(
        {
            "campaign_id": "3c9b7e21-5d44-4a08-9f13-0b6a2e8d7c55",
            "retailer_name": "Ghost Market",
            "store_number": "001",
            "city": "Springfield",
            "state_code": "IL",
            "permission_starts_on": "2026-11-01T00:00:00Z",
            "permission_ends_on": "2026-12-24T23:59:59Z",
            "exclusivity_scope": "NON_EXCLUSIVE",
            "max_kettles": 1,
        },
        kettle_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    listed = api.list_host_sites(kettle_coordinator_headers,
                                 params={"retailer_name": "Ghost Market"})
    _data, meta = validate_paginated(listed)
    assert meta["total_count"] == 0, "the rejected host site must not be persisted"


def test_campaign_activate_without_approved_host_site_rejected(api, platform_admin_headers,
                                                               kettle_coordinator_headers,
                                                               territorial_commander_headers):
    """PRD §3.2: "Activation requires that at least one host site belonging to
    the campaign already hold an `APPROVED` permission".
    PRD §2.6: "an operation that targets a resource whose current state does not
    permit it is refused with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)".

    Design: Corner/state_machines/campaign_activate_without_approved_host_site_rejected
    """
    set_clock(DEFAULT_CLOCK)
    campaign = validate_success(
        api.create_campaign(
            {
                "name": "2026 Christmas Kettle Campaign",
                "season_year": 2026,
                "starts_on": "2026-11-01T00:00:00Z",
                "ends_on": "2026-12-24T23:59:59Z",
                "goal_cents": 5000000,
            },
            platform_admin_headers,
        ),
        expected_status=201,
    )
    create_host_site(campaign["id"])  # remains PENDING

    resp = api.activate_campaign(
        campaign["id"], {"expected_campaign_version": campaign["version"]},
        territorial_commander_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    after = validate_success(api.get_campaign(campaign["id"], platform_admin_headers))
    assert after["status"] == "PLANNING", "the rejected activation must not move the campaign"


def test_campaign_activate_requires_ends_on_after_logical_clock(api, platform_admin_headers,
                                                                kettle_coordinator_headers,
                                                                territorial_commander_headers):
    """PRD §3.2: "and that the campaign's `ends_on` instant still lie in the
    future relative to the logical clock."
    PRD §2.6: "an operation that targets a resource whose current state does not
    permit it is refused with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)".

    Design: Corner/state_machines/campaign_activate_requires_ends_on_after_logical_clock
    """
    set_clock(DEFAULT_CLOCK)
    campaign = validate_success(
        api.create_campaign(
            {
                "name": "Expired Window Campaign",
                "season_year": 2026,
                "starts_on": "2026-09-01T00:00:00Z",
                "ends_on": "2026-10-01T00:00:00Z",
                "goal_cents": 5000000,
            },
            platform_admin_headers,
        ),
        expected_status=201,
    )
    host = create_host_site(
        campaign["id"],
        permission_starts_on="2026-09-01T00:00:00Z",
        permission_ends_on="2026-10-01T00:00:00Z")
    from test_helpers import approve_host_site
    approve_host_site(host["id"])

    resp = api.activate_campaign(
        campaign["id"], {"expected_campaign_version": campaign["version"]},
        territorial_commander_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    after = validate_success(api.get_campaign(campaign["id"], platform_admin_headers))
    assert after["status"] == "PLANNING", "the clock guard must hold despite the APPROVED host site"


def test_host_site_denied_is_terminal_lockdown(api, platform_admin_headers,
                                               kettle_coordinator_headers):
    """PRD §3.1: "supplying `DENY` moves a `PENDING` permission to `DENIED`,
    which is terminal".
    PRD §2.6: "an operation that targets a resource already sitting in one of
    its declared terminal states is refused with `ERR_ALREADY_TERMINAL` (HTTP
    409) rather than being silently ignored."

    Design: Corner/state_machines/host_site_denied_is_terminal_lockdown
    """
    set_clock(DEFAULT_CLOCK)
    campaign = validate_success(
        api.create_campaign(
            {
                "name": "2026 Christmas Kettle Campaign",
                "season_year": 2026,
                "starts_on": "2026-11-01T00:00:00Z",
                "ends_on": "2026-12-24T23:59:59Z",
                "goal_cents": 5000000,
            },
            platform_admin_headers,
        ),
        expected_status=201,
    )
    host = create_host_site(campaign["id"])

    denied = validate_success(
        api.decide_host_site(host["id"],
                             {"decision": "DENY", "expected_host_site_version": host["version"]},
                             kettle_coordinator_headers))
    assert denied["permission_status"] == "DENIED"

    replay = api.decide_host_site(host["id"], {"decision": "APPROVE"},
                                  kettle_coordinator_headers)
    # Both the state check (PRD §2.9 step 10) and the terminal check (step 11)
    # are failed by a DENIED site, so either catalogued refusal is faithful.
    validate_error_is_one_of(replay, [ApiErrorId.ERR_ALREADY_TERMINAL,
                                      ApiErrorId.ERR_INVALID_STATE_TRANSITION])

    after = validate_success(api.get_host_site(host["id"], kettle_coordinator_headers))
    assert after["permission_status"] == "DENIED", "DENIED must not be reversible"


def test_bell_ringer_invalid_ringer_type_rejected(api, platform_admin_headers,
                                                  volunteer_coordinator_headers):
    """PRD §3.3: "A `VolunteerCoordinator` records a ringer with a `full_name`,
    an `email` that must be unique for the campaign season, a `ringer_type` of
    either `VOLUNTEER` or `PAID_SEASONAL`".
    PRD §2.9: "The request body carries every required input declared for the
    operation and every supplied value matches its declared type."

    Design: Corner/entities/bell_ringer_invalid_ringer_type_rejected
    """
    set_clock(DEFAULT_CLOCK)
    unit = validate_success(api.create_unit(create_unit_payload(), platform_admin_headers),
                            expected_status=201)

    resp = api.create_bell_ringer(
        {
            "full_name": "Ada Kim",
            "email": "ada.kim@example.org",
            "ringer_type": "CONTRACTOR",
            "corps_id": unit["id"],
            "date_of_birth": "1991-03-14T00:00:00Z",
            "hourly_rate_cents": 0,
        },
        volunteer_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    listed = api.list_bell_ringers(volunteer_coordinator_headers,
                                   params={"corps_id": unit["id"], "limit": 100})
    _data, meta = validate_paginated(listed)
    assert meta["total_count"] == 0, "no BellRinger row may be created for an unknown type"
