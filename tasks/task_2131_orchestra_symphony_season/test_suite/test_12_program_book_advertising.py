"""Program book advertising: the pinned invoice waterfall and the decide fork."""

from test_helpers import (
    ADVERTISING_SALES,
    ApiErrorId,
    assert_ad_booking,
    create_ad_booking,
    create_season,
    read_ad_booking,
    read_season,
    set_clock,
    validate_error,
    validate_success,
)


def _season_with_booking(**booking_overrides):
    set_clock("2026-09-01T00:00:00Z", ADVERTISING_SALES)
    season = create_season()
    booking = create_ad_booking(season["id"], **booking_overrides)
    assert_ad_booking(booking)
    return season, booking


def test_invoice_applies_the_volume_discount_before_the_placement_fee(api):
    """PRD 3.8: "Second, `volume_discount_bp` is keyed on that **undiscounted**
    subtotal and never on any later figure: a subtotal of at least 500,000 cents
    earns 1200 basis points, otherwise at least 250,000 cents earns 800, otherwise
    at least 100,000 cents earns 400, otherwise nothing."
    PRD 3.8: "Fourth, `placement_fee_cents` is a percentage of that **discounted**
    subtotal rather than of `ad_subtotal_cents`: the discounted subtotal multiplied
    by the placement rate, divided by 10,000, rounded half up, where the back cover
    carries 2500 basis points, the inside front cover 1500, and run-of-book nothing
    at all."

    Design: Difficulty/combinatorial_formula/ad_invoice_discount_then_placement_fee_order
    """
    season, booking = _season_with_booking(
        advertiser_name="Harborline Bank", ad_size="FULL_PAGE",
        placement="BACK_COVER", insertion_count=4,
    )

    approved = validate_success(
        api.decide_ad_booking(booking["id"], "APPROVE", ADVERTISING_SALES)
    )

    assert approved["status"] == "APPROVED"
    assert approved["ad_subtotal_cents"] == 480000, "120000 per insertion times four"
    assert approved["volume_discount_bp"] == 800, "keyed on the undiscounted 480000"
    assert approved["placement_fee_cents"] == 110400, (
        "2500bp of the discounted 441600, not of the raw subtotal"
    )


def test_invoice_total_is_the_discounted_subtotal_plus_that_fee(api):
    """PRD 3.8: "Third, the discounted subtotal is `ad_subtotal_cents` multiplied by
    10000 less `volume_discount_bp`, divided by 10,000, rounded half up."
    PRD 3.8: "Fifth, `invoice_total_cents` is the discounted subtotal plus
    `placement_fee_cents`, with no further rounding."
    PRD 3.8: "Approval finally increases the season's `program_book_revenue_cents`
    by the new `invoice_total_cents`."

    Design: Difficulty/combinatorial_formula/ad_invoice_discount_then_placement_fee_order
    """
    season, booking = _season_with_booking(
        advertiser_name="Harborline Bank", ad_size="FULL_PAGE",
        placement="BACK_COVER", insertion_count=4,
    )
    assert read_season(season["id"])["program_book_revenue_cents"] == 0

    validate_success(api.decide_ad_booking(booking["id"], "APPROVE", ADVERTISING_SALES))

    invoiced = read_ad_booking(booking["id"])
    assert invoiced["invoice_total_cents"] == 552000, "441600 discounted plus a 110400 fee"
    assert invoiced["invoice_total_cents"] != 561600, (
        "charging the placement fee on the undiscounted subtotal is wrong"
    )
    assert read_season(season["id"])["program_book_revenue_cents"] == 552000


def test_subtotal_below_the_first_tier_earns_no_discount_and_no_fee(api):
    """PRD 3.8: "First, `ad_subtotal_cents` is the rate for the chosen size
    multiplied by `insertion_count`, where a full page is 120,000 cents per
    insertion, a half page 70,000 cents and a quarter page 40,000 cents."
    PRD 3.8: "Second, `volume_discount_bp` is keyed on that **undiscounted**
    subtotal and never on any later figure: a subtotal of at least 500,000 cents
    earns 1200 basis points, otherwise at least 250,000 cents earns 800, otherwise
    at least 100,000 cents earns 400, otherwise nothing."

    Design: Corner/calculations/ad_volume_discount_is_zero_below_the_first_tier
    """
    season, booking = _season_with_booking(
        advertiser_name="Kestrel Motors", ad_size="QUARTER_PAGE",
        placement="RUN_OF_BOOK", insertion_count=2,
    )

    approved = validate_success(
        api.decide_ad_booking(booking["id"], "APPROVE", ADVERTISING_SALES)
    )

    assert approved["ad_subtotal_cents"] == 80000
    assert approved["volume_discount_bp"] == 0, "80000 sits under the 100000 first tier"
    assert approved["placement_fee_cents"] == 0, "run-of-book carries no placement rate"
    assert approved["invoice_total_cents"] == 80000
    assert read_season(season["id"])["program_book_revenue_cents"] == 80000


def test_rejection_leaves_every_invoice_field_null(api):
    """PRD 3.8: "A rejection moves the booking to `REJECTED` and computes nothing:
    all four invoice fields stay null."
    PRD 3.8: "The booking opens in `SUBMITTED` with `ad_subtotal_cents`,
    `volume_discount_bp`, `placement_fee_cents` and `invoice_total_cents` all null."

    Design: Corner/state_machines/reject_ad_booking_leaves_invoice_fields_null
    """
    season, booking = _season_with_booking(
        advertiser_name="Kestrel Motors", ad_size="HALF_PAGE",
        placement="RUN_OF_BOOK", insertion_count=2,
    )
    assert booking["status"] == "SUBMITTED"
    assert booking["invoice_total_cents"] is None

    rejected = validate_success(
        api.decide_ad_booking(booking["id"], "REJECT", ADVERTISING_SALES)
    )

    assert rejected["status"] == "REJECTED"
    assert rejected["ad_subtotal_cents"] is None
    assert rejected["volume_discount_bp"] is None
    assert rejected["placement_fee_cents"] is None
    assert rejected["invoice_total_cents"] is None
    assert read_season(season["id"])["program_book_revenue_cents"] == 0


def test_deciding_an_already_approved_booking_is_refused(api):
    """PRD 3.8: "Either way the booking must currently be `SUBMITTED`, else
    `ERR_AD_BOOKING_NOT_SUBMITTED`, and the booking's season must not have reached
    `CLOSED`, else `ERR_INVALID_SEASON_TRANSITION`."
    PRD 3.8: "Approval finally increases the season's `program_book_revenue_cents`
    by the new `invoice_total_cents`."

    Design: Corner/state_machines/decide_ad_booking_twice_returns_not_submitted
    """
    season, booking = _season_with_booking(
        advertiser_name="Kestrel Motors", ad_size="QUARTER_PAGE",
        placement="RUN_OF_BOOK", insertion_count=2,
    )
    validate_success(api.decide_ad_booking(booking["id"], "APPROVE", ADVERTISING_SALES))

    response = api.decide_ad_booking(booking["id"], "REJECT", ADVERTISING_SALES)
    validate_error(response, ApiErrorId.ERR_AD_BOOKING_NOT_SUBMITTED.value, 409)

    settled = read_ad_booking(booking["id"])
    assert settled["status"] == "APPROVED"
    assert settled["invoice_total_cents"] == 80000
    assert read_season(season["id"])["program_book_revenue_cents"] == 80000, (
        "the refused second decision must not add the invoice twice"
    )
