"""Scheduling fences: instrument half-open overlap and technician buffer days."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_loan,
    confirm_loan_payload,
    create_artist,
    create_craftsman,
    create_loan,
    get_concert_loan,
    get_instrument,
    setup_bank_instrument,
    setup_on_tour_loan,
    validate_error,
)

LIAISON = TEST_USERS["artist_liaison_headers"]


def test_instrument_adjacent_tour_allowed(api):
    """PRD section 3.6: "the existing loan's `tour_end` must fall at or before the
    new loan's `tour_start`, or the new `tour_end` must fall at or before the
    existing `tour_start` — adjacency, where one tour ends exactly as another
    begins, is allowed".
    PRD section 3.6: "a chained confirm on an instrument already `ON_LOAN` for an
    adjacent tour leaves the status `ON_LOAN`."

    Design: Difficulty/resource_temporal_overlap/instrument_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = setup_on_tour_loan("MODEL_B", "2029-07-01T00:00:00Z", "2029-07-22T00:00:00Z")
    voi2 = create_craftsman("VOICING", "Voi Two")
    loan2 = create_loan(
        ctx["artist"], "MODEL_B", "2029-07-22T00:00:00Z", "2029-08-05T00:00:00Z"
    )
    confirmed = confirm_loan(loan2["id"], voi2["id"], ctx["instrument"]["id"])
    assert confirmed["status"] == "ON_TOUR"  # tour_start == loan1 tour_end is legal
    assert get_instrument(ctx["instrument"]["id"])["status"] == "ON_LOAN"


def test_instrument_true_overlap_rejected(api):
    """PRD section 3.6: "adjacency, where one tour ends exactly as another begins,
    is allowed — and any true overlap is rejected with `ERR_LOAN_WINDOW_CONFLICT`."
    Loan3 [2029-08-04, 2029-08-20) overlaps the bound loan2 [2029-07-22,
    2029-08-05) on the same instrument.

    Design: Difficulty/resource_temporal_overlap/instrument_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = setup_on_tour_loan("MODEL_B", "2029-07-01T00:00:00Z", "2029-07-22T00:00:00Z")
    voi2 = create_craftsman("VOICING", "Voi Two")
    voi3 = create_craftsman("VOICING", "Voi Three")
    loan2 = create_loan(
        ctx["artist"], "MODEL_B", "2029-07-22T00:00:00Z", "2029-08-05T00:00:00Z"
    )
    confirm_loan(loan2["id"], voi2["id"], ctx["instrument"]["id"])
    loan3 = create_loan(
        ctx["artist"], "MODEL_B", "2029-08-04T00:00:00Z", "2029-08-20T00:00:00Z"
    )
    resp = api.confirm_concert_loan(
        loan3["id"], confirm_loan_payload(voi3["id"], ctx["instrument"]["id"]), LIAISON
    )
    validate_error(resp, ApiErrorId.ERR_LOAN_WINDOW_CONFLICT)
    assert get_concert_loan(loan3["id"])["status"] == "REQUESTED"
    assert get_instrument(ctx["instrument"]["id"])["status"] == "ON_LOAN"


def _two_instruments_with_technician_on_tour():
    """i1 ON_LOAN [2030-07-01, 2030-07-22) under one VOICING technician; i2 in BANK."""
    ctx1 = setup_bank_instrument("MODEL_B")
    ctx2 = setup_bank_instrument("MODEL_B")
    technician = ctx1["craftsmen"]["VOICING"]
    artist = create_artist("Art A", "STANDARD", 2)
    loan1 = create_loan(artist, "MODEL_B", "2030-07-01T00:00:00Z", "2030-07-22T00:00:00Z")
    confirm_loan(loan1["id"], technician["id"], ctx1["instrument"]["id"])
    return ctx1, ctx2, technician, artist


def test_technician_buffer_day_conflict(api):
    """PRD section 3.6: "the same technician may not be bound to another `ON_TOUR`
    loan unless the new `tour_start` falls after the existing `tour_end` plus one
    buffer day ... a one-day buffer is added on both sides of every existing tour —
    and a violation is rejected with `ERR_TECHNICIAN_WINDOW_CONFLICT`."
    Existing tour ends 2030-07-22; a 2030-07-23 start is inside the buffer.

    Design: Difficulty/resource_temporal_overlap/technician_one_day_buffer_closed_interval
    """
    ctx1, ctx2, technician, artist = _two_instruments_with_technician_on_tour()
    loan2 = create_loan(artist, "MODEL_B", "2030-07-23T00:00:00Z", "2030-08-05T00:00:00Z")
    resp = api.confirm_concert_loan(
        loan2["id"], confirm_loan_payload(technician["id"], ctx2["instrument"]["id"]),
        LIAISON,
    )
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_WINDOW_CONFLICT)
    assert get_concert_loan(loan2["id"])["status"] == "REQUESTED"
    assert get_instrument(ctx2["instrument"]["id"])["status"] == "BANK"


def test_technician_buffer_cleared_after_buffer_day(api):
    """PRD section 3.6: "unless the new `tour_start` falls after the existing
    `tour_end` plus one buffer day" — a 2030-07-24 start clears the buffer after
    the 2030-07-22 tour end and confirms.

    Design: Difficulty/resource_temporal_overlap/technician_one_day_buffer_closed_interval
    """
    ctx1, ctx2, technician, artist = _two_instruments_with_technician_on_tour()
    loan3 = create_loan(artist, "MODEL_B", "2030-07-24T00:00:00Z", "2030-08-05T00:00:00Z")
    confirmed = confirm_loan(loan3["id"], technician["id"], ctx2["instrument"]["id"])
    assert confirmed["status"] == "ON_TOUR"
    assert confirmed["technician_id"] == technician["id"]
    assert get_instrument(ctx2["instrument"]["id"])["status"] == "ON_LOAN"
