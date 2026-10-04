"""Lifecycle tests: publisher creation defaults, invalid transitions,
terminal lockdowns, auto-completion, and compensating write-offs."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_channel,
    create_published_channel,
    create_campaign,
    create_viewer,
    create_subscription,
    create_active_campaign,
    create_manufacturer,
    create_certified_model,
    create_activated_unit,
    create_device_unit,
    submit_channel_version,
    get_channel,
    make_viewer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def test_publisher_create_applies_defaults_and_system_fields():
    """PRD §3.1: "A new publisher begins with `standing` of `GOOD`,
    `revenue_tier` of `STANDARD`, and an `outstanding_balance_cents` of
    zero."
    PRD §2.5: "`version` (integer): starts at creation and increments by
    exactly 1 on every mutation of the resource."

    Design: Corner/entities/publisher_create_applies_defaults_and_system_fields
    """
    resp = api_client.create_publisher(
        {
            "legal_name": "Default Pub",
            "default_ad_share_bps": 6500,
            "billing_model": "NET_OF_FEES",
        },
        ADMIN,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    data = body["data"]
    assert data["standing"] == "GOOD"
    assert data["revenue_tier"] == "STANDARD"
    assert data["outstanding_balance_cents"] == 0
    assert data["default_ad_share_bps"] == 6500
    assert data["billing_model"] == "NET_OF_FEES"
    assert data["version"] == 1
    assert data["id"] and data["created_at"] and data["updated_at"]


def test_viewer_create_defaults_ad_consent_when_omitted():
    """PRD §3.6: "Viewer accounts are created by the platform with a unique
    `email` — a duplicate address is rejected with `ERR_DUPLICATE_EMAIL` —
    and two privacy controls: `ad_consent`, one of `PERSONALIZED`,
    `NON_PERSONALIZED`, or `OPTED_OUT` (defaulting to `NON_PERSONALIZED`),
    and `data_retention_opt_out`, a boolean defaulting to false. Accounts
    begin `ACTIVE`."

    Design: Corner/entities/viewer_create_defaults_ad_consent_when_omitted
    """
    resp = api_client.create_viewer_account({"email": "default@x.com"}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["ad_consent"] == "NON_PERSONALIZED"
    assert data["data_retention_opt_out"] is False
    assert data["status"] == "ACTIVE"


def test_channel_get_with_unknown_id_returns_not_found():
    """PRD §2.8: "Existence of path identifiers and body foreign-key
    references, validated left-to-right — else `ERR_NOT_FOUND`."

    Design: Corner/entities/channel_get_with_unknown_id_returns_not_found
    """
    resp = api_client.get_channel(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN,
    )
    assert resp.status_code == 404
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_device_unit_computed_subsidy_and_base_os_at_creation():
    """PRD §3.10: "The unit begins `MANUFACTURED` with `os_version_tag` of
    `BASE` and no `viewer_id`. At creation the platform's subsidy is computed:
    `subsidy_cents` is the positive part of `hardware_cost_cents` minus
    `sale_price_cents`, or zero when the sale price meets or exceeds cost."

    Design: Corner/entities/device_unit_computed_subsidy_and_base_os_at_creation
    """
    manufacturer = create_manufacturer(legal_name="Comp TV")
    model = create_certified_model(
        manufacturer, recovery_policy="MONETIZATION", model_code="C-1",
    )
    unit = create_device_unit(
        manufacturer, model["id"], serial_number="C-1-001",
        hardware_cost_cents=20000, sale_price_cents=9999,
    )
    assert unit["subsidy_cents"] == 10001
    assert unit["subsidy_recovered_cents"] == 0
    assert unit["subsidy_written_off_cents"] == 0
    assert unit["subsidy_outstanding_cents"] == 10001
    assert unit["os_version_tag"] == "BASE"
    assert unit["status"] == "MANUFACTURED"
    assert unit["viewer_id"] is None


def test_campaigns_list_paginates_with_total_count_and_has_more():
    """PRD §2.3: "The `meta` object of every list response carries the
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/campaigns_list_paginates_with_total_count_and_has_more
    """
    publisher = create_publisher(legal_name="List Pub")
    channel = create_published_channel(publisher)
    create_campaign(publisher, channel["id"], budget_cents=1000)
    create_campaign(publisher, channel["id"], budget_cents=2000)
    create_campaign(publisher, channel["id"], budget_cents=3000,
                    targeting_mode="PERSONALIZED")

    resp = api_client.list_campaigns(
        ADMIN, params={"publisher_id": publisher["id"], "limit": 2,
                       "offset": 0},
    )
    rows, meta = validate_paginated(resp)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    resp = api_client.list_campaigns(
        ADMIN, params={"publisher_id": publisher["id"], "limit": 2,
                       "offset": 2},
    )
    rows, meta = validate_paginated(resp)
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    resp = api_client.list_campaigns(
        ADMIN, params={"publisher_id": publisher["id"], "status": "DRAFT"},
    )
    rows, meta = validate_paginated(resp)
    assert len(rows) == 3

    resp = api_client.list_campaigns(
        ADMIN, params={"channel_id": channel["id"]},
    )
    rows, meta = validate_paginated(resp)
    assert len(rows) == 3


def test_channel_version_superseded_when_new_version_submitted():
    """PRD §3.2: "If the publisher submits again while the channel is
    `SUBMITTED`, the submission self-loops: the prior version still in
    `SUBMITTED` is set to `SUPERSEDED`, a fresh version is created in
    `SUBMITTED`, and the channel's `version` increments again — this is the
    legitimate supersession the OCC guard protects."

    Design: Corner/entities/channel_version_superseded_when_new_version_submitted
    """
    publisher = create_publisher(legal_name="Sup Pub")
    channel = create_channel(publisher, name="Sup Channel", category="KIDS")

    v1 = submit_channel_version(channel["id"], publisher["id"],
                                version_label="1.0.0")
    after_first = get_channel(channel["id"])
    v2 = submit_channel_version(channel["id"], publisher["id"],
                                version_label="1.0.1")

    first = get_success_data(api_client.get_channel_version(v1["id"], ADMIN))
    assert first["review_status"] == "SUPERSEDED"
    assert v2["review_status"] == "SUBMITTED"
    current = get_channel(channel["id"])
    assert current["status"] == "SUBMITTED"
    assert current["version"] == after_first["version"] + 1

    resp = api_client.list_channel_versions(channel["id"], ADMIN)
    rows = get_success_data(resp)
    assert len(rows) == 2


def test_channel_publish_from_draft_returns_invalid_state():
    """PRD §3.3: "A `CERTIFIED` channel is made commercially live when a
    `PlatformAdmin` publishes it, moving it to `PUBLISHED`."
    PRD §2.8: "The target resource's own state machine permits the transition
    from its current state (a grant must be `OPEN`, a statement `OPEN` or
    `FINALIZED` as appropriate, a dispute in the right stage, a campaign
    `ACTIVE` for impression recording, a channel non-terminal) — else
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/channel_publish_from_draft_returns_invalid_state
    """
    publisher = create_publisher(legal_name="Inv Pub")
    channel = create_channel(publisher, name="Inv Channel")

    resp = api_client.publish_channel(channel["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_success_data(api_client.get_channel(channel["id"], ADMIN))[
        "status"] == "DRAFT"


def test_subscription_second_cancel_hits_terminal_lockdown():
    """PRD §3.6: "The billing dimension moves from `ACTIVE` to `CANCELLED`
    when the owning viewer cancels, or to `REFUNDED` when a `PlatformAdmin`
    issues a refund; both are terminal."

    Design: Corner/state_machines/subscription_second_cancel_hits_terminal_lockdown
    """
    publisher = create_publisher(legal_name="TL Pub")
    channel = create_published_channel(publisher)
    viewer = create_viewer(email="tl@x.com")
    subscription = create_subscription(channel["id"], viewer["id"],
                                       price_cents=1200)

    first = validate_success(api_client.cancel_subscription(
        subscription["id"], make_viewer_headers(viewer["id"]),
    ))
    assert first["billing_status"] == "CANCELLED"
    assert first["entitlement_status"] == "REVOKED"

    resp = api_client.cancel_subscription(
        subscription["id"], make_viewer_headers(viewer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_campaign_auto_completes_at_exact_budget_boundary():
    """PRD §3.5: "Before anything is applied, the guard checks that the
    current `spent_cents` plus this batch cost does not exceed `budget_cents`
    — spending to exactly the budget is allowed and completes the campaign;
    one cent over is rejected with `ERR_BUDGET_EXHAUSTED`."
    PRD §3.5: "An `ACTIVE` campaign completes itself: the moment a
    measurement entry brings `spent_cents` to exactly `budget_cents`, the
    campaign moves to `COMPLETED`."

    Design: Corner/state_machines/campaign_auto_completes_at_exact_budget_boundary
    """
    publisher = create_publisher(legal_name="Auto Pub")
    channel = create_published_channel(publisher)
    campaign = create_active_campaign(publisher, channel["id"],
                                      budget_cents=10000)

    completed = validate_success(api_client.record_campaign_impressions(
        campaign["id"], {"impression_count": 10000, "cpm_cents": 1000},
        ADOPS,
    ))
    assert completed["spent_cents"] == 10000
    assert completed["impressions_delivered"] == 10000
    assert completed["status"] == "COMPLETED"

    resp = api_client.record_campaign_impressions(
        campaign["id"], {"impression_count": 1, "cpm_cents": 1000}, ADOPS,
    )
    # PRD §3.5: "Impression recording against a campaign that is not `ACTIVE`
    # is rejected with `ERR_CAMPAIGN_NOT_ACTIVE`."
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE, 409)


def test_device_deactivate_writes_off_outstanding_subsidy():
    """PRD §3.10: "Deactivation writes off whatever subsidy remains
    outstanding: `subsidy_written_off_cents` grows by the outstanding amount,
    `subsidy_outstanding_cents` becomes zero, and the invariant is
    conserved."

    Design: Corner/state_machines/device_deactivate_writes_off_outstanding_subsidy
    """
    manufacturer = create_manufacturer(legal_name="WO TV")
    model = create_certified_model(
        manufacturer, recovery_policy="STRAIGHT_LINE", model_code="W-1",
    )
    viewer = create_viewer(email="wo@x.com")
    unit = create_activated_unit(
        manufacturer, model["id"], viewer["id"], serial_number="W-1-001",
        hardware_cost_cents=20000, sale_price_cents=9999,
    )
    get_success_data(api_client.accrue_straight_line(unit["id"], ADOPS))

    deactivated = validate_success(api_client.deactivate_device_unit(
        unit["id"], make_viewer_headers(viewer["id"]),
    ))
    assert deactivated["status"] == "DEACTIVATED"
    assert deactivated["subsidy_recovered_cents"] == 416
    assert deactivated["subsidy_written_off_cents"] == 9585
    assert deactivated["subsidy_outstanding_cents"] == 0
    assert (
        deactivated["subsidy_cents"]
        == deactivated["subsidy_recovered_cents"]
        + deactivated["subsidy_written_off_cents"]
        + deactivated["subsidy_outstanding_cents"]
    )
