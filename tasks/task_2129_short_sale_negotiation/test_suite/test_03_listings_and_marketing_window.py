"""Marketing windows, days on market, price reductions, and the marketing-period gate."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_listing,
    create_case,
    create_listing,
    create_listing_payload,
    price_reduction_payload,
    set_clock,
    setup_case_with_draft_offer,
    validate_error,
    validate_success,
    withdraw_listing_payload,
)

NEG = TEST_USERS["negotiator_headers"]
AGENT = TEST_USERS["listing_agent_headers"]


def test_new_window_inside_an_open_window_is_refused(api):
    """PRD §3.4: "Because a newly created listing always has a null `ended_at`, a new
    window conflicts with an existing one on the same case exactly when the new
    `listed_at` falls strictly before that existing window's `ended_at` — or when that
    existing window has a null `ended_at` of its own, in which case any new window
    conflicts."
    PRD §3.4: "The check considers **every** listing on the case in every marketing
    status, withdrawn ones included. A conflict is refused with
    `ERR_LISTING_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/listing_half_open_window_overlap_rejected_on_case
    """
    set_clock("2026-08-20T00:00:00Z")
    case = create_case(property_address="150 Cottonwood Ter, Reno NV")
    first = create_listing(case["id"])
    assert first["ended_at"] is None, "a newly created listing leaves ended_at null"

    conflicting = api.create_listing(
        case["id"],
        create_listing_payload(
            list_price_cents=24_900_000,
            commission_pct=0.055,
            listed_at="2026-08-20T00:00:00Z",
        ),
        AGENT,
    )
    validate_error(conflicting, ApiErrorId.ERR_LISTING_WINDOW_OVERLAP.value)

    listings = validate_success(api.list_case_listings(case["id"], NEG), 200)
    assert len(listings) == 1, "the refused window must not be persisted"
    assert listings[0]["id"] == first["id"]


def test_refused_window_leaves_the_open_listing_untouched(api):
    """PRD §3.4: "Because a newly created listing always has a null `ended_at`, a new
    window conflicts with an existing one on the same case exactly when the new
    `listed_at` falls strictly before that existing window's `ended_at` — or when that
    existing window has a null `ended_at` of its own, in which case any new window
    conflicts."
    PRD §3.4: "Creation stamps `listing_agent_user_id` from the acting header, starts
    `price_reduction_count` at 0, sets `marketing_status` to `ACTIVE`, and leaves
    `ended_at` null, meaning the window is open-ended."

    Design: Difficulty/resource_temporal_overlap/listing_half_open_window_overlap_rejected_on_case
    """
    set_clock("2026-08-20T00:00:00Z")
    case = create_case(property_address="150 Cottonwood Ter, Reno NV")
    first = create_listing(case["id"])

    # The existing window has a null ended_at, so a window opening even before it
    # still conflicts.
    validate_error(
        api.create_listing(
            case["id"],
            create_listing_payload(
                list_price_cents=24_900_000, listed_at="2026-08-02T00:00:00Z"
            ),
            AGENT,
        ),
        ApiErrorId.ERR_LISTING_WINDOW_OVERLAP.value,
    )

    listings = validate_success(api.list_case_listings(case["id"], NEG), 200)
    assert len(listings) == 1
    stored = listings[0]
    assert stored["id"] == first["id"]
    assert stored["marketing_status"] == "ACTIVE"
    assert stored["ended_at"] is None
    assert stored["list_price_cents"] == 25_900_000
    assert stored["price_reduction_count"] == 0
    assert_listing(stored)


def test_window_starting_exactly_where_a_closed_window_ended_is_admitted(api):
    """PRD §3.4: "Adjacency is deliberately admissible: a new window that starts at
    precisely the instant a prior window ended does not conflict, because the comparison
    is strict."
    PRD §3.4: "Withdrawing a listing closes its window at a supplied `ended_at` instant
    and moves `marketing_status` to the terminal `WITHDRAWN`, from either `ACTIVE` or
    `UNDER_CONTRACT`, freeing the case for a fresh window that may begin at exactly that
    instant."

    Design: Corner/endpoints/listing_withdraw_then_adjacent_listing_admitted
    """
    set_clock("2026-08-20T00:00:00Z")
    case = create_case()
    first = create_listing(case["id"])
    withdrawn = validate_success(
        api.withdraw_listing(
            first["id"], withdraw_listing_payload("2026-08-20T00:00:00Z"), AGENT
        ),
        200,
    )
    assert withdrawn["marketing_status"] == "WITHDRAWN"

    second = validate_success(
        api.create_listing(
            case["id"],
            create_listing_payload(
                list_price_cents=24_900_000,
                commission_pct=0.055,
                listed_at="2026-08-20T00:00:00Z",
            ),
            AGENT,
        ),
        201,
    )

    assert second["marketing_status"] == "ACTIVE"
    assert second["days_on_market"] == 0, (
        "a window opened at the current instant has no elapsed days"
    )
    assert withdrawn["ended_at"].startswith("2026-08-20T00:00:00")

    listings = validate_success(api.list_case_listings(case["id"], NEG), 200)
    assert len(listings) == 2


def test_price_reduction_on_a_withdrawn_listing_is_not_actionable(api):
    """PRD §3.4: "The supplied `ended_at` must fall strictly after `listed_at`; a
    withdrawal that would close the window at or before it opened is refused with
    `ERR_LISTING_NOT_ACTIONABLE`, as is any price reduction or withdrawal addressed at a
    listing already `WITHDRAWN`."

    Design: Corner/state_machines/price_reduction_on_withdrawn_listing_returns_listing_not_actionable
    """
    set_clock("2026-08-20T00:00:00Z")
    case = create_case()
    listing = create_listing(case["id"])
    validate_success(
        api.withdraw_listing(
            listing["id"], withdraw_listing_payload("2026-08-20T00:00:00Z"), AGENT
        ),
        200,
    )

    validate_error(
        api.record_price_reduction(
            listing["id"], price_reduction_payload(24_000_000), AGENT
        ),
        ApiErrorId.ERR_LISTING_NOT_ACTIONABLE.value,
    )

    listings = validate_success(api.list_case_listings(case["id"], NEG), 200)
    stored = listings[0]
    assert stored["marketing_status"] == "WITHDRAWN"
    assert stored["list_price_cents"] == 25_900_000, "the refused reduction changed nothing"
    assert stored["price_reduction_count"] == 0


def test_logical_clock_starts_at_the_declared_instant(api):
    """PRD §2.4: "The clock's startup value is exactly `2026-08-01T00:00:00Z`; until it
    is moved, every read of "now" returns that instant, and the server never falls back
    to the host's real clock."
    PRD §3.4: "Take the window's end — the listing's `ended_at` if it has one, otherwise
    the current logical-clock instant. Take the earlier of the current instant and that
    window end. Subtract `listed_at` from it, divide the elapsed seconds by 86,400, and
    truncate downward to a whole number of days."

    Design: Corner/endpoints/logical_clock_startup_default_is_august_first
    """
    # The clock control endpoint is deliberately never called in this test.
    case = create_case(property_address="11 Larch Ct, Reno NV")
    listing = create_listing(case["id"], listed_at="2026-08-01T00:00:00Z")

    listings = validate_success(api.list_case_listings(case["id"], NEG), 200)
    stored = listings[0]

    assert stored["id"] == listing["id"]
    assert stored["days_on_market"] == 0, (
        "with the clock at its startup instant a window opened then is 0 days old"
    )
    assert stored["listed_at"].startswith("2026-08-01T00:00:00")


def test_fourteen_days_on_market_blocks_offer_submission(api):
    """PRD §3.5: "Second, the case must have a controlling listing and that listing's
    `days_on_market` must be **at least 15** — a property that has been exposed to the
    market for exactly 15 days qualifies, one at 14 does not, and either the missing
    listing or the short exposure is reported as `ERR_MARKETING_PERIOD_NOT_MET`."

    Design: Corner/calculations/days_on_market_fourteen_rejects_submission
    """
    scenario = setup_case_with_draft_offer(clock_at="2026-08-19T00:00:00Z")

    validate_error(
        api.submit_offer(scenario["offer"]["id"], NEG),
        ApiErrorId.ERR_MARKETING_PERIOD_NOT_MET.value,
    )

    listings = validate_success(api.list_case_listings(scenario["case"]["id"], NEG), 200)
    assert listings[0]["days_on_market"] == 14
    assert listings[0]["marketing_status"] == "ACTIVE"

    offer = validate_success(api.get_offer(scenario["offer"]["id"], NEG), 200)
    assert offer["status"] == "DRAFT"

    case_after = validate_success(api.get_case(scenario["case"]["id"], NEG), 200)
    assert case_after["negotiation_status"] == "MARKETED"


def test_exactly_fifteen_days_on_market_permits_submission(api):
    """PRD §3.5: "Second, the case must have a controlling listing and that listing's
    `days_on_market` must be **at least 15** — a property that has been exposed to the
    market for exactly 15 days qualifies, one at 14 does not, and either the missing
    listing or the short exposure is reported as `ERR_MARKETING_PERIOD_NOT_MET`."
    PRD §3.5: "A successful submission moves the offer to `SUBMITTED`, stamps
    `submitted_at` with the current logical-clock instant, moves the controlling listing
    from `ACTIVE` to `UNDER_CONTRACT`, and carries the case's negotiation dimension to
    `OFFER_UNDER_REVIEW` — from `MARKETED` on a first pass, or from `RENEGOTIATION` when
    the file has come back around after an approval was voided."

    Design: Difficulty/boundary_precision_check/marketing_days_exactly_fifteen_permits_submission
    """
    scenario = setup_case_with_draft_offer(clock_at="2026-08-20T00:00:00Z")

    submitted = validate_success(api.submit_offer(scenario["offer"]["id"], NEG), 200)

    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"].startswith("2026-08-20T00:00:00"), (
        "submitted_at is stamped with the current logical-clock instant"
    )

    listings = validate_success(api.list_case_listings(scenario["case"]["id"], NEG), 200)
    assert listings[0]["days_on_market"] == 15


def test_submission_at_the_marketing_boundary_moves_listing_and_case(api):
    """PRD §3.5: "A successful submission moves the offer to `SUBMITTED`, stamps
    `submitted_at` with the current logical-clock instant, moves the controlling listing
    from `ACTIVE` to `UNDER_CONTRACT`, and carries the case's negotiation dimension to
    `OFFER_UNDER_REVIEW` — from `MARKETED` on a first pass, or from `RENEGOTIATION` when
    the file has come back around after an approval was voided."

    Design: Difficulty/boundary_precision_check/marketing_days_exactly_fifteen_permits_submission
    """
    scenario = setup_case_with_draft_offer(clock_at="2026-08-20T00:00:00Z")

    validate_success(api.submit_offer(scenario["offer"]["id"], NEG), 200)

    listings = validate_success(api.list_case_listings(scenario["case"]["id"], NEG), 200)
    assert listings[0]["marketing_status"] == "UNDER_CONTRACT"

    case_after = validate_success(api.get_case(scenario["case"]["id"], NEG), 200)
    assert case_after["negotiation_status"] == "OFFER_UNDER_REVIEW"
