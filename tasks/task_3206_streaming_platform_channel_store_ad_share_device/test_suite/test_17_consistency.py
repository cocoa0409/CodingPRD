"""Consistency and campaign-state tests: immediate read-after-write
visibility and impression recording gated on ACTIVE."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_channel,
    certify_channel,
    create_published_channel,
    create_active_campaign,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def test_immediate_consistency_mutation_visible_in_same_response():
    """PRD §2.5: "Cascading mutations follow the same discipline: when one
    operation mutates several entities (a channel suspension pausing
    campaigns and releasing bookings, a statement finalization updating the
    publisher's tier and balance), each mutated entity has its own
    `updated_at` refreshed and its own `version` incremented."
    PRD §3.3: "A `CERTIFIED` channel is made commercially live when a
    `PlatformAdmin` publishes it, moving it to `PUBLISHED`."

    Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response
    """
    publisher = create_publisher(legal_name="Imm Pub")
    channel = create_channel(publisher, name="Imm Channel")
    certify_channel(channel["id"], publisher["id"])
    before = get_success_data(api_client.get_channel(channel["id"], ADMIN))

    published = validate_success(
        api_client.publish_channel(channel["id"], ADMIN)
    )
    assert published["status"] == "PUBLISHED", (
        "the publish response itself must show the new state"
    )

    after = get_success_data(api_client.get_channel(channel["id"], ADMIN))
    assert after["status"] == "PUBLISHED"
    assert after["version"] == published["version"]


def test_impression_recording_on_paused_campaign_rejected():
    """PRD §3.5: "Impression recording against a campaign that is not
    `ACTIVE` is rejected with `ERR_CAMPAIGN_NOT_ACTIVE`."

    Design: Corner/consistency_model/impression_recording_on_paused_campaign_rejected
    """
    publisher = create_publisher(legal_name="Paused Pub")
    channel = create_published_channel(publisher)
    campaign = create_active_campaign(publisher, channel["id"])
    validate_success(api_client.record_campaign_impressions(
        campaign["id"], {"impression_count": 1000, "cpm_cents": 1000},
        ADOPS,
    ))
    get_success_data(api_client.pause_campaign(campaign["id"], ADOPS))

    resp = api_client.record_campaign_impressions(
        campaign["id"], {"impression_count": 1000, "cpm_cents": 1000},
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE, 409)
    assert get_success_data(api_client.get_campaign(campaign["id"], ADMIN))[
        "spent_cents"] == 1000

    get_success_data(api_client.resume_campaign(campaign["id"], ADOPS))
    updated = validate_success(api_client.record_campaign_impressions(
        campaign["id"], {"impression_count": 1000, "cpm_cents": 1000},
        ADOPS,
    ))
    assert updated["spent_cents"] == 2000
    assert updated["status"] == "ACTIVE"
