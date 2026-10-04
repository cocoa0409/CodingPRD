"""Endpoint-shape tests: existence checks and the campaign read model."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_publisher,
    create_published_channel,
    create_campaign,
    make_publisher_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_booking_with_unknown_campaign_returns_not_found():
    """PRD §2.8: "Existence of path identifiers and body foreign-key
    references, validated left-to-right — else `ERR_NOT_FOUND`."

    Design: Corner/endpoints/booking_with_unknown_campaign_returns_not_found
    """
    publisher = create_publisher(legal_name="Fk Pub")

    resp = api_client.create_placement_booking(
        {
            "campaign_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            "slot_code": "HOME_ROW_1",
            "window_start": "2026-09-10T09:00:00Z",
            "window_end": "2026-09-10T12:00:00Z",
        },
        make_publisher_headers(publisher["id"]),
    )
    assert resp.status_code == 404
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_campaign_get_returns_pacing_and_measurement_fields():
    """PRD §3.5: "Every campaign read exposes a live pacing projection."
    PRD §3.5: "Campaigns begin in `DRAFT` with `spent_cents` and
    `impressions_delivered` at zero."

    Design: Corner/endpoints/campaign_get_returns_pacing_and_measurement_fields
    """
    publisher = create_publisher(legal_name="Read Pub")
    channel = create_published_channel(publisher)
    campaign = create_campaign(publisher, channel["id"], budget_cents=40000)

    read = validate_success(api_client.get_campaign(
        campaign["id"], make_publisher_headers(publisher["id"]),
    ))
    assert read["spent_cents"] == 0
    assert read["impressions_delivered"] == 0
    assert read["expected_spend_cents"] == 0
    assert read["pacing_delta_cents"] == 0
    assert read["status"] == "DRAFT"
    assert read["budget_cents"] == 40000
