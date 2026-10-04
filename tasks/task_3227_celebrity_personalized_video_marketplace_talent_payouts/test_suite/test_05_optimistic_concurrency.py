"""Optimistic concurrency on the two guarded write endpoints."""

from test_helpers import (
    ApiErrorId,
    create_active_talent,
    create_delivered_order,
    make_buyer_headers,
    make_moderator_headers,
    make_talent_headers,
    moderate_video_clear,
    moderate_video_flag,
    read_order,
    read_talent,
    register_buyer,
    validate_error,
    validate_success,
)


def test_dispute_open_with_stale_order_version_rejected(api):
    """PRD §2.7: "Opening a dispute on an order requires the request to carry
    `expected_order_version` holding the buyer's last-observed `version` of
    that order. If the order's current `version` no longer matches — for
    example because the video snapshot or the auto-confirm clock has advanced
    since the buyer last read the order — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.4: "Flagging requires a `flagged_reason` and moves the video to
    `FLAGGED`; when the flagged video's order is currently `DELIVERED`, the
    flag forks the order back into a re-record loop — the order transitions
    to `RE_RECORD_REQUESTED`, an `OPEN` re-record request is created whose
    `notes` are the `flagged_reason`, and the order's `re_record_count` is
    incremented."

    Design: Corner/endpoints/occ_stale_version_on_dispute_open
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, video = create_delivered_order(api, talent, buyer, moderate=None)

    # The buyer's last-observed version, then moderation advances the order.
    stale_version = read_order(api, order["id"])["version"]
    moderate_video_flag(api, video, flagged_reason="bump the order",
                        headers=make_moderator_headers())

    response = api.open_dispute(
        order["id"], "stale dispute", stale_version,
        headers=make_buyer_headers(buyer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)


def test_dispute_open_with_current_version_succeeds(api):
    """PRD §2.7: "Opening a dispute on an order requires the request to carry
    `expected_order_version` holding the buyer's last-observed `version` of
    that order. If the order's current `version` no longer matches — for
    example because the video snapshot or the auto-confirm clock has advanced
    since the buyer last read the order — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.6: "When a delivered video does not match the request, the buyer
    opens a dispute with a `reason` of 1 to 1000 characters. From
    `DELIVERED`, the open requires the logical time to be strictly before
    `auto_confirm_at`; from `CONFIRMED` a dispute may still be opened —
    video mismatch remains actionable after confirmation — and no
    buyer-window deadline applies there. Either way the order transitions to
    `REFUND_PENDING`, and the request is OCC-guarded by
    `expected_order_version` as described in §2.7."

    Design: Corner/endpoints/occ_stale_version_on_dispute_open
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")

    current_version = read_order(api, order["id"])["version"]
    response = api.open_dispute(
        order["id"], "not what I asked for", current_version,
        headers=make_buyer_headers(buyer["id"]),
    )
    dispute = validate_success(response, expected_status=201)
    assert dispute["status"] == "OPEN"
    assert read_order(api, order["id"])["status"] == "REFUND_PENDING"


def test_rate_write_with_stale_talent_version_rejected(api):
    """PRD §2.7: "Setting or changing a talent's rates requires the request
    to carry `expected_talent_version` holding the caller's last-observed
    `version` of the talent record; a mismatch is likewise rejected with
    `ERR_STALE_VERSION` (HTTP 412), so a rate write never silently overwrites
    a tier recompute or a suggestion refresh that landed in between."

    Design: Corner/endpoints/occ_stale_version_on_rate_change
    """
    talent = create_active_talent(api)
    headers = make_talent_headers(talent["id"])
    stale_version = read_talent(api, talent["id"])["version"]

    # Pause and resume each increment the talent version.
    validate_success(api.pause_talent(talent["id"], headers=headers))
    validate_success(api.resume_talent(talent["id"], headers=headers))

    response = api.set_rates(
        talent["id"],
        {
            "personal_rate_cents": 12000,
            "business_rate_cents": 48000,
            "advertising_rate_cents": 96000,
            "turnaround_hours": 72,
            "expected_talent_version": stale_version,
        },
        headers=headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    assert read_talent(api, talent["id"])["personal_rate_cents"] == 10000


def test_rate_write_with_current_version_succeeds(api):
    """PRD §2.7: "Setting or changing a talent's rates requires the request
    to carry `expected_talent_version` holding the caller's last-observed
    `version` of the talent record; a mismatch is likewise rejected with
    `ERR_STALE_VERSION` (HTTP 412), so a rate write never silently overwrites
    a tier recompute or a suggestion refresh that landed in between."

    Design: Corner/endpoints/occ_stale_version_on_rate_change
    """
    talent = create_active_talent(api)
    headers = make_talent_headers(talent["id"])
    current = read_talent(api, talent["id"])

    response = api.set_rates(
        talent["id"],
        {
            "personal_rate_cents": 12000,
            "business_rate_cents": 48000,
            "advertising_rate_cents": 96000,
            "turnaround_hours": 72,
            "expected_talent_version": current["version"],
        },
        headers=headers,
    )
    updated = validate_success(response)
    assert updated["personal_rate_cents"] == 12000
    assert updated["version"] == current["version"] + 1
