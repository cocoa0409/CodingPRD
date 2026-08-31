"""Sponsorship identification grading and the submission gate."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_order,
    hourly_spots,
    make_advertiser_agent_headers,
    read_order,
    setup_issue_order,
    validate_error,
    validate_success,
)

OFFICER_ALPHA = TEST_USERS["officer_alpha_headers"]


def test_disclosure_without_the_paid_for_by_prefix_is_nonconforming(api):
    """PRD §3.5: "Otherwise, if the text does not begin with the exact prefix `PAID FOR
    BY ` — those four words followed by a single space, matched case-sensitively — the
    status is `NONCONFORMING`."
    PRD §3.5: "And the freshly recomputed `disclosure_status` must read `CONFORMING`; a
    status of `MISSING` or `NONCONFORMING` is refused with
    `ERR_DISCLOSURE_NONCONFORMING` (HTTP 422)."

    Design: Corner/calculations/disclosure_without_the_paid_for_by_prefix_is_nonconforming_and_blocks_submit
    """
    built = setup_issue_order(
        call_sign="WDIS-TV",
        market_code="DMA-116",
        station_overrides={"licensee_name": "Disclosure Media LLC", "daily_political_seconds_cap": 300},
        classification=None,
        order_overrides={"sponsorship_disclosure_text": "Sponsored by Empire Growth Fund"},
        spots=hourly_spots(1),
    )
    order, advertiser = built["order"], built["advertiser"]

    assert order["disclosure_status"] == "NONCONFORMING", (
        "grading runs when the order is first opened"
    )

    validate_error(
        api.submit_order(order["id"], make_advertiser_agent_headers(advertiser["id"])),
        ApiErrorId.ERR_DISCLOSURE_NONCONFORMING,
    )

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["status"] == "DRAFT"
    assert refreshed["spot_count"] == 1


def test_disclosure_shorter_than_four_seconds_is_nonconforming(api):
    """PRD §3.5: "Otherwise, if `disclosure_duration_seconds` is less than the
    four-second statutory minimum, the status is `NONCONFORMING`. Only when all four
    branches are passed does the status read `CONFORMING`."

    Design: Corner/calculations/disclosure_shorter_than_four_seconds_is_nonconforming
    """
    built = setup_issue_order(
        call_sign="WDUR-TV",
        market_code="DMA-117",
        station_overrides={"licensee_name": "Duration Media Group"},
        classification=None,
        order_overrides={"disclosure_duration_seconds": 3},
    )
    short_order = built["order"]
    assert short_order["disclosure_status"] == "NONCONFORMING"
    assert short_order["disclosure_duration_seconds"] == 3

    at_minimum = create_order(
        built["station"]["id"],
        built["advertiser"]["id"],
        built["rate_class"]["id"],
        sponsorship_disclosure_text="PAID FOR BY Empire Growth Fund",
        disclosure_duration_seconds=4,
    )
    assert at_minimum["disclosure_status"] == "CONFORMING", (
        "exactly four seconds meets the statutory minimum"
    )
    assert at_minimum["disclosure_duration_seconds"] == 4


def test_submitting_an_order_that_holds_no_spot_is_refused(api):
    """PRD §3.5: "The order must carry at least one spot — a `spot_count` of zero is
    refused with `ERR_ORDER_HAS_NO_SPOTS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/submit_with_empty_spot_collection_rejected_at_zero_boundary
    """
    built = setup_issue_order(
        call_sign="WEMP-TV",
        market_code="DMA-808",
        station_overrides={"licensee_name": "Empty Slate Media"},
        classification=None,
    )
    order, advertiser = built["order"], built["advertiser"]

    assert order["spot_count"] == 0

    validate_error(
        api.submit_order(order["id"], make_advertiser_agent_headers(advertiser["id"])),
        ApiErrorId.ERR_ORDER_HAS_NO_SPOTS,
    )


def test_order_refused_at_the_zero_spot_boundary_stays_draft_and_priced_at_zero(api):
    """PRD §3.5: "The order must carry at least one spot — a `spot_count` of zero is
    refused with `ERR_ORDER_HAS_NO_SPOTS` (HTTP 422). And the freshly recomputed
    `disclosure_status` must read `CONFORMING`; a status of `MISSING` or
    `NONCONFORMING` is refused with `ERR_DISCLOSURE_NONCONFORMING` (HTTP 422)."
    PRD §3.5: "Submission moves the order `DRAFT → SUBMITTED` and is performed by the
    `AdvertiserAgent` acting for the order's advertiser."

    Design: Difficulty/boundary_precision_check/submit_with_empty_spot_collection_rejected_at_zero_boundary
    """
    built = setup_issue_order(
        call_sign="WEM2-TV",
        market_code="DMA-809",
        station_overrides={"licensee_name": "Empty Slate Media"},
        classification=None,
    )
    order, advertiser = built["order"], built["advertiser"]

    validate_error(
        api.submit_order(order["id"], make_advertiser_agent_headers(advertiser["id"])),
        ApiErrorId.ERR_ORDER_HAS_NO_SPOTS,
    )

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["status"] == "DRAFT", "the refused submission leaves the order in DRAFT"
    assert refreshed["spot_count"] == 0
    assert refreshed["disclosure_status"] == "CONFORMING", (
        "the disclosure check one rung earlier passes cleanly"
    )
    assert refreshed["gross_charge_cents"] == 0


def test_second_submission_on_the_same_order_is_refused(api):
    """PRD §3.5: "The order must still be in `DRAFT`, or the submission is refused with
    `ERR_ORDER_NOT_DRAFT` (HTTP 409) — the same error that guards spot addition."
    PRD §2.4: "Most resources additionally carry an `updated_at` timestamp in the same
    format and an integer `version` that starts at 1 on creation and increments by
    exactly 1 on every mutation of that resource; `updated_at` is refreshed to the
    logical clock on each such mutation."

    Design: Corner/state_machines/second_submit_on_the_same_order_rejected_as_not_draft
    """
    built = setup_issue_order(
        call_sign="WIDM-TV",
        market_code="DMA-106",
        station_overrides={"licensee_name": "Idempotent Media LLC"},
        classification=None,
        spots=hourly_spots(1),
        submit=True,
    )
    order, advertiser = built["order"], built["advertiser"]
    version_after_submit = order["version"]
    assert order["status"] == "SUBMITTED"

    validate_error(
        api.submit_order(order["id"], make_advertiser_agent_headers(advertiser["id"])),
        ApiErrorId.ERR_ORDER_NOT_DRAFT,
    )

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["status"] == "SUBMITTED"
    assert refreshed["version"] == version_after_submit, (
        "a refused submission mutates nothing, so the version does not move"
    )


def test_adding_a_spot_to_a_submitted_order_is_refused(api):
    """PRD §3.4: "Spots are added to the order one at a time, and only while the order
    is still `DRAFT`; an attempt on an order that has left `DRAFT` fails with
    `ERR_ORDER_NOT_DRAFT` (HTTP 409)."

    Design: Corner/state_machines/second_submit_on_the_same_order_rejected_as_not_draft
    """
    built = setup_issue_order(
        call_sign="WID2-TV",
        market_code="DMA-148",
        station_overrides={"licensee_name": "Idempotent Media LLC", "daily_political_seconds_cap": 300},
        classification=None,
        spots=hourly_spots(1),
        submit=True,
    )
    order, advertiser = built["order"], built["advertiser"]

    validate_error(
        api.add_spot(
            order["id"],
            {
                "air_date": "2026-08-20",
                "start_offset_seconds": 3600,
                "duration_seconds": 30,
                "program_code": "EN-2",
            },
            make_advertiser_agent_headers(advertiser["id"]),
        ),
        ApiErrorId.ERR_ORDER_NOT_DRAFT,
    )

    assert read_order(order["id"], advertiser["id"])["spot_count"] == 1
