"""Calculated-field and capacity tests: campaign pacing projection and the
lab capacity boundary."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_published_channel,
    create_active_campaign,
    create_manufacturer,
    create_device_model,
    book_lab,
    set_clock,
    make_manufacturer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def test_campaign_pacing_projection_at_midpoint():
    """PRD §3.5: "The total flight length is the difference between
    `flight_end` and `flight_start` in whole hours (at least one); elapsed
    time is the difference between the logical clock now and `flight_start`
    in whole hours, clamped to lie between zero and the total. The
    `expected_spend_cents` is the budget multiplied by elapsed hours, divided
    by total hours, rounded half-up; `pacing_delta_cents` is `spent_cents`
    minus that expectation — positive when the campaign is running hot."

    Design: Corner/calculations/campaign_pacing_projection_midpoint_and_clamps
    """
    publisher = create_publisher(legal_name="Pace Pub")
    channel = create_published_channel(publisher)
    campaign = create_active_campaign(
        publisher, channel["id"],
        flight_start="2026-09-01T00:00:00Z",
        flight_end="2026-09-11T00:00:00Z",
        budget_cents=50000,
    )
    validate_success(api_client.record_campaign_impressions(
        campaign["id"], {"impression_count": 2500, "cpm_cents": 1000},
        ADOPS,
    ))

    set_clock("2026-09-06T00:00:00Z")
    read = get_success_data(api_client.get_campaign(campaign["id"], ADOPS))
    assert read["expected_spend_cents"] == 25000, (
        f"round_half_up(50000 * 120/240) = 25000, got "
        f"{read['expected_spend_cents']}"
    )
    assert read["pacing_delta_cents"] == -22500


def test_campaign_pacing_projection_clamps_after_flight_end():
    """PRD §3.5: "elapsed time is the difference between the logical clock
    now and `flight_start` in whole hours, clamped to lie between zero and
    the total."

    Design: Corner/calculations/campaign_pacing_projection_midpoint_and_clamps
    """
    publisher = create_publisher(legal_name="Pace Pub 2")
    channel = create_published_channel(publisher)
    campaign = create_active_campaign(
        publisher, channel["id"],
        flight_start="2026-09-01T00:00:00Z",
        flight_end="2026-09-11T00:00:00Z",
        budget_cents=50000,
    )

    set_clock("2026-09-12T00:00:00Z")
    read = get_success_data(api_client.get_campaign(campaign["id"], ADOPS))
    assert read["expected_spend_cents"] == 50000, (
        "elapsed must clamp to total_hours after the flight ends, so the "
        "expected spend is the full budget"
    )


def test_lab_capacity_third_allowed_fourth_rejected():
    """PRD §3.8: "Overlap is checked before capacity: independent of any
    overlap, a manufacturer may have at most 3 models in `LAB_TESTING` at
    once — booking the bench for a fourth is rejected with
    `ERR_LAB_CAPACITY_EXCEEDED`."

    Design: Corner/calculations/lab_capacity_third_allowed_fourth_rejected
    """
    manufacturer = create_manufacturer(legal_name="Cap TV")
    headers = make_manufacturer_headers(manufacturer["id"])
    models = [
        create_device_model(manufacturer, model_code=f"CAP-{i}",
                            recovery_policy="STRAIGHT_LINE")
        for i in range(1, 5)
    ]
    for i, model in enumerate(models[:3]):
        book_lab(
            model["id"], manufacturer["id"], bench_code=f"B{i + 1}",
            window_start="2026-09-02T09:00:00Z",
            window_end="2026-09-02T17:00:00Z",
        )

    for model in models[:3]:
        state = get_success_data(api_client.get_device_model(model["id"], ADMIN))
        assert state["cert_status"] == "LAB_TESTING"

    resp = api_client.create_lab_booking(
        models[3]["id"],
        {
            "bench_code": "B4",
            "window_start": "2026-09-02T09:00:00Z",
            "window_end": "2026-09-02T17:00:00Z",
        },
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_LAB_CAPACITY_EXCEEDED, 409)
    state = get_success_data(api_client.get_device_model(models[3]["id"], ADMIN))
    assert state["cert_status"] == "SUBMITTED"
