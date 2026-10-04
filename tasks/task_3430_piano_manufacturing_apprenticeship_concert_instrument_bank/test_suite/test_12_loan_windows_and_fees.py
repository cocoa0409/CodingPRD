"""Loan window sanity and the tiered weekly fee with its nested clamp."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_loan,
    create_artist,
    create_loan,
    create_loan_payload,
    make_artist_headers,
    return_loan,
    setup_bank_instrument,
    validate_error,
    validate_paginated,
)

LIAISON = TEST_USERS["artist_liaison_headers"]


def test_loan_window_end_not_after_start_rejected(api):
    """PRD section 3.6: "The window must be sane — `tour_end` strictly after
    `tour_start`, and `tour_start` not before the current clock date — else the
    request fails with `ERR_LOAN_WINDOW_INVALID` (HTTP 422)".

    Design: Corner/validations/loan_window_end_not_after_start_rejected
    """
    artist = create_artist("Art W", "STANDARD", 2)
    resp = api.create_concert_loan(
        create_loan_payload("MODEL_D", "2027-01-10T00:00:00Z", "2027-01-10T00:00:00Z"),
        make_artist_headers(artist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LOAN_WINDOW_INVALID)
    rows, meta = validate_paginated(
        api.list_concert_loans(LIAISON, params={"artist_id": artist["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_fee_ceil_weeks_seven_vs_eight_days(api):
    """PRD section 3.6: "the tour's whole-day length is divided by 7 and rounded up
    to give tour weeks, so 7 days make 1 week and 8 days make 2". MODEL_B STANDARD:
    72,000 x 1 = 72,000; 72,000 x 2 = 144,000.

    Design: Corner/calculations/fee_ceil_weeks_seven_vs_eight_days
    """
    ctx = setup_bank_instrument("MODEL_B")
    technician_id = ctx["craftsmen"]["VOICING"]["id"]
    instrument_id = ctx["instrument"]["id"]
    artist = create_artist("Art S", "STANDARD", 2)
    loan1 = create_loan(artist, "MODEL_B", "2029-07-01T00:00:00Z", "2029-07-08T00:00:00Z")
    confirmed1 = confirm_loan(loan1["id"], technician_id, instrument_id)
    assert confirmed1["fee_cents"] == 72_000  # 7 days -> exactly 1 week
    return_loan(loan1["id"], "A")
    loan2 = create_loan(artist, "MODEL_B", "2029-08-01T00:00:00Z", "2029-08-09T00:00:00Z")
    confirmed2 = confirm_loan(loan2["id"], technician_id, instrument_id)
    assert confirmed2["fee_cents"] == 144_000  # 8 days -> ceil to 2 weeks


def test_fee_max_clamp_binds_on_long_tour(api):
    """PRD section 3.6: "the clamp is applied after the tier factor, raising anything
    below 55,000 cents to 55,000 and capping anything above 2,000,000 at 2,000,000."
    PRD section 3.6: "a 24-week `MODEL_D` tour for a `STANDARD` artist, raw
    2,040,000, bills 2,000,000."

    Design: Corner/calculations/fee_max_clamp_binds_on_long_art_case_tour
    """
    ctx = setup_bank_instrument("MODEL_D")
    artist = create_artist("Art D", "STANDARD", 2)
    loan = create_loan(artist, "MODEL_D", "2029-01-01T00:00:00Z", "2029-06-18T00:00:00Z")
    confirmed = confirm_loan(
        loan["id"], ctx["craftsmen"]["VOICING"]["id"], ctx["instrument"]["id"]
    )
    assert confirmed["fee_cents"] == 2_000_000  # 168 days = 24 weeks; raw 2,040,000
    assert confirmed["status"] == "ON_TOUR"


def test_fee_privileged_min_clamp_binds(api):
    """PRD section 3.6: "A one-week `MODEL_O` tour for a `PRIVILEGED` artist, raw
    51,200, therefore bills 55,000".

    Design: Difficulty/combinatorial_formula/loan_fee_tier_factor_nested_clamp_mode_a
    """
    ctx = setup_bank_instrument("MODEL_O")
    privileged = create_artist("Priv Artist", "PRIVILEGED", 2)
    loan = create_loan(
        privileged, "MODEL_O", "2029-07-01T00:00:00Z", "2029-07-08T00:00:00Z"
    )
    confirmed = confirm_loan(
        loan["id"], ctx["craftsmen"]["VOICING"]["id"], ctx["instrument"]["id"]
    )
    # raw 64,000 x 1 week x 0.8 = 51,200 clamps UP to MIN 55,000
    assert confirmed["fee_cents"] == 55_000


def test_fee_standard_three_week_no_clamp(api):
    """PRD section 3.6: "the raw fee is the confirmed instrument model's weekly rate
    ... multiplied by the tour weeks and by the artist's tier factor, 1.0 for
    `STANDARD` and 0.8 for `PRIVILEGED`; the clamp is applied after the tier
    factor". MODEL_O STANDARD 21 days: 64,000 x 3 x 1.0 = 192,000, no clamp binds.

    Design: Difficulty/combinatorial_formula/loan_fee_tier_factor_nested_clamp_mode_a
    """
    ctx = setup_bank_instrument("MODEL_O")
    technician_id = ctx["craftsmen"]["VOICING"]["id"]
    instrument_id = ctx["instrument"]["id"]
    privileged = create_artist("Priv Artist", "PRIVILEGED", 2)
    standard = create_artist("Std Artist", "STANDARD", 2)
    loan1 = create_loan(
        privileged, "MODEL_O", "2029-07-01T00:00:00Z", "2029-07-08T00:00:00Z"
    )
    confirmed1 = confirm_loan(loan1["id"], technician_id, instrument_id)
    assert confirmed1["fee_cents"] == 55_000
    return_loan(loan1["id"], "A")
    loan2 = create_loan(
        standard, "MODEL_O", "2029-09-01T00:00:00Z", "2029-09-22T00:00:00Z"
    )
    confirmed2 = confirm_loan(loan2["id"], technician_id, instrument_id)
    assert confirmed2["fee_cents"] == 192_000
