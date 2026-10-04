"""Boundary-precision tests: floor split at exact divisibility vs off-by-one,
and half-open interval adjacency on placement bookings."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_published_channel,
    create_active_campaign,
    create_placement_booking,
    make_publisher_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def test_ad_slot_split_exactly_divisible_boundary():
    """PRD §3.4: "`publisher_slots` is the floor of `total_slots` multiplied
    by the effective share in basis points and divided by 10000, and
    `platform_slots` — the platform-retained share of publisher inventory — is
    `total_slots` minus `publisher_slots`."

    Design: Difficulty/boundary_precision_check/ad_slot_split_floor_at_exactly_divisible_vs_off_by_one
    """
    publisher = create_publisher(legal_name="Bnd Pub",
                                 default_ad_share_bps=7000)
    channel = create_published_channel(publisher)

    resp = api_client.create_ad_slot_grant(
        {"channel_id": channel["id"], "period": "2026-09",
         "total_slots": 1000},
        ADMIN,
    )
    grant = validate_success(resp, expected_status=201)
    assert grant["publisher_slots"] == 700
    assert grant["platform_slots"] == 300
    assert grant["publisher_slots"] + grant["platform_slots"] == 1000


def test_ad_slot_split_off_by_one_floor():
    """PRD §3.4: "`publisher_slots` is the floor of `total_slots` multiplied
    by the effective share in basis points and divided by 10000, and
    `platform_slots` — the platform-retained share of publisher inventory — is
    `total_slots` minus `publisher_slots`."

    Design: Difficulty/boundary_precision_check/ad_slot_split_floor_at_exactly_divisible_vs_off_by_one
    """
    publisher = create_publisher(legal_name="Bnd Pub 2",
                                 default_ad_share_bps=7000)
    channel = create_published_channel(publisher)

    resp = api_client.create_ad_slot_grant(
        {"channel_id": channel["id"], "period": "2026-09",
         "total_slots": 1001},
        ADMIN,
    )
    grant = validate_success(resp, expected_status=201)
    assert grant["publisher_slots"] == 700, (
        f"floor(1001 * 7000/10000) = floor(700.7) = 700, got "
        f"{grant['publisher_slots']}"
    )
    assert grant["platform_slots"] == 301
    assert grant["publisher_slots"] + grant["platform_slots"] == 1001


def _setup_campaign_with_booking():
    publisher = create_publisher(legal_name="Adj Pub")
    channel = create_published_channel(publisher)
    campaign = create_active_campaign(publisher, channel["id"])
    booking = create_placement_booking(
        campaign["id"], publisher["id"], slot_code="HOME_ROW_3",
        window_start="2026-09-10T09:00:00Z",
        window_end="2026-09-10T12:00:00Z",
    )
    return publisher, campaign, booking


def test_placement_booking_pure_adjacency_allowed():
    """PRD §3.5: "pure adjacency, where the new start equals an existing end
    or the new end equals an existing start, does not conflict."

    Design: Difficulty/boundary_precision_check/placement_booking_half_open_adjacency_and_zero_length
    """
    publisher, campaign, _ = _setup_campaign_with_booking()

    resp = api_client.create_placement_booking(
        {
            "campaign_id": campaign["id"],
            "slot_code": "HOME_ROW_3",
            "window_start": "2026-09-10T12:00:00Z",
            "window_end": "2026-09-10T14:00:00Z",
        },
        make_publisher_headers(publisher["id"]),
    )
    adjacent = validate_success(resp, expected_status=201)
    assert adjacent["status"] == "HELD"


def test_placement_booking_overlap_and_zero_length_rejected():
    """PRD §3.5: "Booking windows use half-open interval semantics: a
    conflict exists exactly when another booking on the same `slot_code` in
    `HELD` or `CONFIRMED` status satisfies both that the new start is strictly
    before the existing end and the new end is strictly after the existing
    start — and pure adjacency, where the new start equals an existing end or
    the new end equals an existing start, does not conflict. A conflicting
    booking is rejected with `ERR_SLOT_OVERLAP`. Zero-length windows fail
    earlier as shape errors, and a window whose end is not after the logical
    clock now is rejected with `ERR_BOOKING_WINDOW_PAST`."

    Design: Difficulty/boundary_precision_check/placement_booking_half_open_adjacency_and_zero_length
    """
    publisher, campaign, _ = _setup_campaign_with_booking()

    resp = api_client.create_placement_booking(
        {
            "campaign_id": campaign["id"],
            "slot_code": "HOME_ROW_3",
            "window_start": "2026-09-10T11:00:00Z",
            "window_end": "2026-09-10T13:00:00Z",
        },
        make_publisher_headers(publisher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP, 409)

    resp = api_client.create_placement_booking(
        {
            "campaign_id": campaign["id"],
            "slot_code": "HOME_ROW_3",
            "window_start": "2026-09-10T15:00:00Z",
            "window_end": "2026-09-10T15:00:00Z",
        },
        make_publisher_headers(publisher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
