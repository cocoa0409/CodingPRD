"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the server restarts before every test, so each test starts
against an empty database and the default logical clock
2026-09-01T00:00:00Z). Setup calls use the lenient get_success_data()
validator so a failed setup reports a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_publisher_payload,
    create_channel_payload,
    create_channel_version_payload,
    create_viewer_account_payload,
    create_subscription_payload,
    create_ad_slot_grant_payload,
    create_campaign_payload,
    create_placement_booking_payload,
    create_manufacturer_payload,
    create_device_model_payload,
    create_lab_booking_payload,
    create_os_update_payload,
    create_device_unit_payload,
)
from .test_users import (
    TEST_USERS,
    make_publisher_headers,
    make_viewer_headers,
    make_manufacturer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


# ---------------------------------------------------------------------------
# Tier 1: leaf entity creation
# ---------------------------------------------------------------------------

def create_publisher(**overrides):
    """Create a publisher (PlatformAdmin). Returns the publisher dict."""
    resp = api_client.create_publisher(create_publisher_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_viewer(**overrides):
    """Create a viewer account (PlatformAdmin). Returns the viewer dict."""
    resp = api_client.create_viewer_account(
        create_viewer_account_payload(**overrides), ADMIN,
    )
    return get_success_data(resp)


def create_manufacturer(**overrides):
    """License a manufacturer (PlatformAdmin). Returns the manufacturer dict."""
    resp = api_client.create_manufacturer(
        create_manufacturer_payload(**overrides), ADMIN,
    )
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def get_channel(channel_id):
    return get_success_data(api_client.get_channel(channel_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: channel certification chain
# ---------------------------------------------------------------------------

def create_channel(publisher, **overrides):
    """Create a channel owned by the given publisher dict. Returns channel."""
    resp = api_client.create_channel(
        create_channel_payload(publisher["id"], **overrides),
        make_publisher_headers(publisher["id"]),
    )
    return get_success_data(resp)


def submit_channel_version(channel_id, publisher_id, **overrides):
    """Submit a certification version for the channel (owner publisher).

    Reads the channel first so expected_channel_version is current.
    Returns the created ChannelVersion dict.
    """
    channel = get_channel(channel_id)
    payload = create_channel_version_payload(channel["version"], **overrides)
    resp = api_client.create_channel_version(
        channel_id, payload, make_publisher_headers(publisher_id),
    )
    return get_success_data(resp)


def certify_channel(channel_id, publisher_id, **version_overrides):
    """Walk the channel to CERTIFIED: submit version, review, decide PASS.

    Returns the PASSED ChannelVersion dict.
    """
    version = submit_channel_version(
        channel_id, publisher_id, **version_overrides
    )
    get_success_data(api_client.review_channel_version(version["id"], ADMIN))
    return get_success_data(
        api_client.decide_channel_version(
            version["id"], {"outcome": "PASS"}, ADMIN,
        )
    )


def publish_channel(channel_id):
    """Publish a CERTIFIED channel (PlatformAdmin). Returns channel dict."""
    return get_success_data(api_client.publish_channel(channel_id, ADMIN))


def create_published_channel(publisher, **channel_overrides):
    """Create a channel for the publisher and carry it to PUBLISHED.

    Returns the channel dict in PUBLISHED state.
    """
    channel = create_channel(publisher, **channel_overrides)
    certify_channel(channel["id"], publisher["id"])
    publish_channel(channel["id"])
    return get_channel(channel["id"])


def setup_publisher_with_published_channel(**publisher_overrides):
    """Publisher + one PUBLISHED channel. Returns (publisher, channel)."""
    publisher = create_publisher(**publisher_overrides)
    channel = create_published_channel(publisher)
    return publisher, channel


# ---------------------------------------------------------------------------
# Tier 3: subscriptions
# ---------------------------------------------------------------------------

def create_subscription(channel_id, viewer_id, **overrides):
    """Subscribe the viewer to a PUBLISHED channel. Returns subscription."""
    resp = api_client.create_subscription(
        create_subscription_payload(channel_id, **overrides),
        make_viewer_headers(viewer_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: ad slot grants
# ---------------------------------------------------------------------------

def create_ad_slot_grant(channel_id, **overrides):
    """Grant + split a channel's ad inventory (PlatformAdmin)."""
    resp = api_client.create_ad_slot_grant(
        create_ad_slot_grant_payload(channel_id, **overrides), ADMIN,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: campaigns and placements
# ---------------------------------------------------------------------------

def create_campaign(publisher, channel_id, **overrides):
    """Create a DRAFT campaign owned by the publisher. Returns campaign."""
    resp = api_client.create_campaign(
        create_campaign_payload(publisher["id"], channel_id, **overrides),
        make_publisher_headers(publisher["id"]),
    )
    return get_success_data(resp)


def schedule_campaign(campaign_id, publisher_id):
    return get_success_data(
        api_client.schedule_campaign(
            campaign_id, make_publisher_headers(publisher_id),
        )
    )


def start_campaign(campaign_id):
    return get_success_data(api_client.start_campaign(campaign_id, ADOPS))


def create_active_campaign(publisher, channel_id, **overrides):
    """Create a campaign, schedule it, start it. Returns ACTIVE campaign."""
    campaign = create_campaign(publisher, channel_id, **overrides)
    schedule_campaign(campaign["id"], publisher["id"])
    start_campaign(campaign["id"])
    return get_success_data(api_client.get_campaign(campaign["id"], ADMIN))


def create_placement_booking(campaign_id, publisher_id, **overrides):
    """Book a placement window against an ACTIVE campaign."""
    resp = api_client.create_placement_booking(
        create_placement_booking_payload(campaign_id, **overrides),
        make_publisher_headers(publisher_id),
    )
    return get_success_data(resp)


def setup_active_campaign_scenario(**overrides):
    """Publisher + PUBLISHED channel + ACTIVE campaign.

    Returns (publisher, channel, campaign).
    """
    publisher, channel = setup_publisher_with_published_channel()
    campaign = create_active_campaign(publisher, channel["id"], **overrides)
    return publisher, channel, campaign


# ---------------------------------------------------------------------------
# Tier 6: device certification chain
# ---------------------------------------------------------------------------

def create_device_model(manufacturer, **overrides):
    """Submit a device model (owner manufacturer). Returns the model dict."""
    resp = api_client.create_device_model(
        create_device_model_payload(manufacturer["id"], **overrides),
        make_manufacturer_headers(manufacturer["id"]),
    )
    return get_success_data(resp)


def book_lab(model_id, manufacturer_id, **overrides):
    """Book a certification lab bench for the model. Returns LabBooking."""
    resp = api_client.create_lab_booking(
        model_id,
        create_lab_booking_payload(**overrides),
        make_manufacturer_headers(manufacturer_id),
    )
    return get_success_data(resp)


def certify_device_model(model_id, manufacturer_id, bench_code="LAB_BENCH_1",
                         certify_clock="2026-09-02T00:00:00Z", **lab_overrides):
    """Book a lab bench, advance the clock past the window, then certify.

    Returns the model dict in CERTIFIED state. NOTE: advances the logical
    clock to certify_clock (default 2026-09-02T00:00:00Z).
    """
    lab_overrides.setdefault("bench_code", bench_code)
    book_lab(model_id, manufacturer_id, **lab_overrides)
    set_clock(certify_clock)
    get_success_data(api_client.certify_device_model(model_id, ADMIN))
    return get_success_data(api_client.get_device_model(model_id, ADMIN))


def create_certified_model(manufacturer, bench_code="LAB_BENCH_1", **overrides):
    """Create a device model and carry it to CERTIFIED.

    Advances the logical clock to 2026-09-02T00:00:00Z (unless overridden via
    certify_clock in overrides is not supported here — see
    certify_device_model). Returns the CERTIFIED model dict.
    """
    model = create_device_model(manufacturer, **overrides)
    return certify_device_model(model["id"], manufacturer["id"], bench_code)


def create_device_unit(manufacturer, model_id, **overrides):
    """Manufacture a device unit (owner manufacturer). Returns unit dict."""
    resp = api_client.create_device_unit(
        create_device_unit_payload(model_id, **overrides),
        make_manufacturer_headers(manufacturer["id"]),
    )
    return get_success_data(resp)


def create_activated_unit(manufacturer, model_id, viewer_id, **overrides):
    """Create, sell, and activate a device unit for the viewer.

    Returns the unit dict in ACTIVATED state.
    """
    unit = create_device_unit(manufacturer, model_id, **overrides)
    get_success_data(api_client.sell_device_unit(unit["id"], ADMIN))
    return get_success_data(
        api_client.activate_device_unit(unit["id"], make_viewer_headers(viewer_id))
    )


# ---------------------------------------------------------------------------
# Tier 7: OS updates
# ---------------------------------------------------------------------------

def create_os_update(**overrides):
    resp = api_client.create_os_update(create_os_update_payload(**overrides), ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 8: statements
# ---------------------------------------------------------------------------

def generate_statement(publisher_id, period):
    """Generate statements for the period and return this publisher's row."""
    get_success_data(api_client.generate_statements({"period": period}, ADMIN))
    resp = api_client.list_statements(
        ADMIN, params={"publisher_id": publisher_id, "period": period},
    )
    rows = get_success_data(resp)
    assert isinstance(rows, list) and len(rows) >= 1, (
        f"Setup failed: no statement found for publisher {publisher_id} "
        f"period {period}"
    )
    return rows[0]


def finalize_statement(publisher_id, period):
    """Generate (if needed) and finalize the publisher's statement.

    Returns the FINALIZED statement dict.
    """
    statement = generate_statement(publisher_id, period)
    get_success_data(api_client.finalize_statement(statement["id"], ADMIN))
    return get_success_data(api_client.get_statement(statement["id"], ADMIN))
