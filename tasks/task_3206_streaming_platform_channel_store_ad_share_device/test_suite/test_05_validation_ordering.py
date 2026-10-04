"""Validation-ordering tests: when a request fails multiple tiers, the
earliest tier's error is reported."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_published_channel,
    create_active_campaign,
    create_campaign,
    create_placement_booking,
    generate_statement,
    make_publisher_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def test_channel_state_beats_outstanding_balance_fiscal_gate():
    """PRD §2.8: "This ordering is normative. When a request would fail
    multiple checks, the error returned is the one belonging to the earliest
    failing tier."
    PRD §3.5: "the channel must be `PUBLISHED` (`ERR_CHANNEL_NOT_PUBLISHED`
    otherwise) and free of any content-policy hold
    (`ERR_CONTENT_POLICY_BLOCK`); and the publisher's
    `outstanding_balance_cents` must not exceed the campaign credit limit of
    100000 cents — a publisher already owing the platform more than that is
    rejected with `ERR_OUTSTANDING_BALANCE`."

    Design: Difficulty/priority_pair_validation_conflict/channel_state_beats_outstanding_balance_fiscal_gate
    """
    publisher = create_publisher(legal_name="PP Pub")
    channel = create_published_channel(publisher)

    # Drive a 200000-cent negative net so outstanding balance = 200000.
    k1 = create_active_campaign(publisher, channel["id"], budget_cents=200000)
    validate_success(api_client.record_campaign_impressions(
        k1["id"], {"impression_count": 200000, "cpm_cents": 1000}, ADOPS,
    ))
    statement = generate_statement(publisher["id"], "2026-09")
    get_success_data(api_client.finalize_statement(statement["id"], ADMIN))
    assert get_success_data(api_client.get_publisher(publisher["id"], ADMIN))[
        "outstanding_balance_cents"] == 200000

    # Suspend the channel (violates the cross-entity state gate too).
    get_success_data(
        api_client.suspend_channel(channel["id"], {"reason": "OPS"}, ADMIN)
    )

    k2 = create_campaign(publisher, channel["id"], budget_cents=5000)
    resp = api_client.schedule_campaign(
        k2["id"], make_publisher_headers(publisher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CHANNEL_NOT_PUBLISHED, 409)


def test_outstanding_balance_alone_reports_fiscal_error():
    """PRD §3.5: "and the publisher's `outstanding_balance_cents` must not
    exceed the campaign credit limit of 100000 cents — a publisher already
    owing the platform more than that is rejected with
    `ERR_OUTSTANDING_BALANCE`."

    Design: Difficulty/priority_pair_validation_conflict/channel_state_beats_outstanding_balance_fiscal_gate
    """
    publisher = create_publisher(legal_name="Fiscal Pub")
    channel = create_published_channel(publisher)

    k1 = create_active_campaign(publisher, channel["id"], budget_cents=200000)
    validate_success(api_client.record_campaign_impressions(
        k1["id"], {"impression_count": 200000, "cpm_cents": 1000}, ADOPS,
    ))
    statement = generate_statement(publisher["id"], "2026-09")
    get_success_data(api_client.finalize_statement(statement["id"], ADMIN))
    assert get_success_data(api_client.get_publisher(publisher["id"], ADMIN))[
        "outstanding_balance_cents"] == 200000

    # Channel stays PUBLISHED: only the fiscal gate is violated now.
    k2 = create_campaign(publisher, channel["id"], budget_cents=5000)
    resp = api_client.schedule_campaign(
        k2["id"], make_publisher_headers(publisher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE, 422)


def test_content_policy_safety_beats_slot_overlap_temporal():
    """PRD §2.8: "This ordering is normative. When a request would fail
    multiple checks, the error returned is the one belonging to the earliest
    failing tier."
    PRD §3.3: "While a channel's `policy_hold` is true, placement bookings
    and campaign scheduling against that channel are rejected with
    `ERR_CONTENT_POLICY_BLOCK`, and the same code guards any new commercial
    activity against a `REMOVED` channel."
    PRD §3.5: "A conflicting booking is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/content_policy_safety_beats_slot_overlap_temporal
    """
    p1 = create_publisher(legal_name="Safe P1")
    p2 = create_publisher(legal_name="Safe P2")
    c1 = create_published_channel(p1)
    c2 = create_published_channel(p2)
    k1 = create_active_campaign(p1, c1["id"])
    k2 = create_active_campaign(p2, c2["id"])
    b1 = create_placement_booking(
        k1["id"], p1["id"], slot_code="HOME_ROW_2",
        window_start="2026-09-10T09:00:00Z",
        window_end="2026-09-10T12:00:00Z",
    )
    assert b1["status"] == "HELD"

    # Put channel 2 under a policy hold while it remains PUBLISHED.
    get_success_data(api_client.set_channel_policy_hold(
        c2["id"], {"held": True}, ADMIN,
    ))

    # p2's booking window overlaps p1's HELD booking AND p2's channel is
    # policy-held: safety tier (8) must beat the temporal tier (9).
    resp = api_client.create_placement_booking(
        {
            "campaign_id": k2["id"],
            "slot_code": "HOME_ROW_2",
            "window_start": "2026-09-10T11:00:00Z",
            "window_end": "2026-09-10T13:00:00Z",
        },
        make_publisher_headers(p2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONTENT_POLICY_BLOCK, 422)

    c2_state = get_success_data(api_client.get_channel(c2["id"], ADMIN))
    assert c2_state["status"] == "PUBLISHED"
    assert c2_state["policy_hold"] is True


def test_slot_overlap_alone_reports_temporal_error():
    """PRD §3.5: "A conflicting booking is rejected with
    `ERR_SLOT_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/content_policy_safety_beats_slot_overlap_temporal
    """
    p1 = create_publisher(legal_name="Temp P1")
    p2 = create_publisher(legal_name="Temp P2")
    c1 = create_published_channel(p1)
    c2 = create_published_channel(p2)
    k1 = create_active_campaign(p1, c1["id"])
    k2 = create_active_campaign(p2, c2["id"])
    create_placement_booking(
        k1["id"], p1["id"], slot_code="HOME_ROW_2",
        window_start="2026-09-10T09:00:00Z",
        window_end="2026-09-10T12:00:00Z",
    )

    resp = api_client.create_placement_booking(
        {
            "campaign_id": k2["id"],
            "slot_code": "HOME_ROW_2",
            "window_start": "2026-09-10T11:00:00Z",
            "window_end": "2026-09-10T13:00:00Z",
        },
        make_publisher_headers(p2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP, 409)
