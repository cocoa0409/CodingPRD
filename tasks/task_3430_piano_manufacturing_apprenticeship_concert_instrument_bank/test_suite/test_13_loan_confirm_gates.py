"""Loan confirmation gates: technician specialty, eligibility, selector policy."""
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


def test_technician_must_hold_voicing_specialty(api):
    """PRD section 3.6: "The technician must resolve, else `ERR_NOT_FOUND`, and must
    hold the `VOICING` specialty, else `ERR_TECHNICIAN_NOT_QUALIFIED`."

    Design: Corner/validations/technician_must_hold_voicing_specialty
    """
    ctx = setup_bank_instrument("MODEL_B")
    artist = create_artist("Art Q", "STANDARD", 2)
    loan = create_loan(artist, "MODEL_B", "2029-07-01T00:00:00Z", "2029-07-22T00:00:00Z")
    resp = api.confirm_concert_loan(
        loan["id"],
        confirm_loan_payload(ctx["craftsmen"]["RIM_BENDING"]["id"], ctx["instrument"]["id"]),
        LIAISON,
    )
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_QUALIFIED)
    loan_after = get_concert_loan(loan["id"])
    assert loan_after["status"] == "REQUESTED"
    assert loan_after["instrument_id"] is None


def test_selector_empty_pool_returns_422(api):
    """PRD section 3.6: "an empty pool fails with `ERR_NO_ELIGIBLE_INSTRUMENT`
    (HTTP 422)."

    Design: Corner/endpoints/selector_empty_pool_returns_422
    """
    cr_voi = create_craftsman("VOICING", "Voi Master")
    artist = create_artist("Art Z", "STANDARD", 2)
    loan = create_loan(artist, "MODEL_B", "2027-01-10T00:00:00Z", "2027-01-24T00:00:00Z")
    resp = api.confirm_concert_loan(loan["id"], confirm_loan_payload(cr_voi["id"]), LIAISON)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_INSTRUMENT)
    loan_after = get_concert_loan(loan["id"])
    assert loan_after["status"] == "REQUESTED"
    assert loan_after["instrument_id"] is None


def test_selector_ranking_tiebreak_and_overlap_filter(api):
    """PRD section 3.6: "the pool is ranked by `condition_grade` with `A` before `B`,
    ties broken by `created_at` ascending and never by id".
    Two grade-A MODEL_B instruments: the earlier-created i1 wins loan1; on loan2's
    overlapping window i1 is excluded ("with the tour window free") and i2 is picked.

    Design: Corner/endpoints/selector_ranking_tiebreak_and_overlap_filter
    """
    ctx1 = setup_bank_instrument("MODEL_B")
    ctx2 = setup_bank_instrument("MODEL_B")
    i1 = ctx1["instrument"]["id"]  # minted a full build cycle before i2
    i2 = ctx2["instrument"]["id"]
    assert ctx1["instrument"]["created_at"] < ctx2["instrument"]["created_at"]
    artist = create_artist("Art Sel", "STANDARD", 2)
    loan1 = create_loan(artist, "MODEL_B", "2030-07-01T00:00:00Z", "2030-07-22T00:00:00Z")
    loan2 = create_loan(artist, "MODEL_B", "2030-07-10T00:00:00Z", "2030-07-20T00:00:00Z")
    picked1 = confirm_loan(loan1["id"], ctx1["craftsmen"]["VOICING"]["id"])
    assert picked1["instrument_id"] == i1  # grade tie A==A broken by created_at ASC
    picked2 = confirm_loan(loan2["id"], ctx2["craftsmen"]["VOICING"]["id"])
    assert picked2["instrument_id"] == i2  # i1 excluded by window overlap
    assert picked1["status"] == "ON_TOUR" and picked2["status"] == "ON_TOUR"
    assert get_instrument(i1)["status"] == "ON_LOAN"
    assert get_instrument(i2)["status"] == "ON_LOAN"


def test_model_mismatch_beats_window_overlap(api):
    """PRD section 2.8: tier "(6) business constraints, namely ... instrument
    eligibility and selector fallback" precedes tier "(7) temporal business rules,
    namely ... instrument and technician window conflicts", and the server "reports
    the earliest failure rather than an arbitrary one."
    PRD section 3.6: "An explicitly named instrument must be eligible — status
    `BANK` or `ON_LOAN`, `certified_authentic` true, `condition_grade` `A` or `B`,
    and `model` equal to the loan's `desired_model` — else
    `ERR_INSTRUMENT_NOT_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_model_ineligible_beats_window_overlap
    """
    ctx = setup_on_tour_loan("MODEL_B", "2029-07-01T00:00:00Z", "2029-07-22T00:00:00Z")
    voi2 = create_craftsman("VOICING", "Voi Two")
    loan2 = create_loan(
        ctx["artist"], "MODEL_D", "2029-07-10T00:00:00Z", "2029-07-20T00:00:00Z"
    )
    resp = api.confirm_concert_loan(
        loan2["id"], confirm_loan_payload(voi2["id"], ctx["instrument"]["id"]), LIAISON
    )
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_NOT_ELIGIBLE)
    assert get_concert_loan(loan2["id"])["status"] == "REQUESTED"
    assert get_instrument(ctx["instrument"]["id"])["status"] == "ON_LOAN"


def test_matching_model_surfaces_window_overlap(api):
    """PRD section 3.6: "adjacency, where one tour ends exactly as another begins,
    is allowed — and any true overlap is rejected with `ERR_LOAN_WINDOW_CONFLICT`."
    Same overlapping window as the priority test but with a matching model,
    isolating the tier-7 instrument fence on its own.

    Design: Difficulty/priority_pair_validation_conflict/confirm_model_ineligible_beats_window_overlap
    """
    ctx = setup_on_tour_loan("MODEL_B", "2029-07-01T00:00:00Z", "2029-07-22T00:00:00Z")
    voi2 = create_craftsman("VOICING", "Voi Two")
    loan2 = create_loan(
        ctx["artist"], "MODEL_B", "2029-07-10T00:00:00Z", "2029-07-20T00:00:00Z"
    )
    resp = api.confirm_concert_loan(
        loan2["id"], confirm_loan_payload(voi2["id"], ctx["instrument"]["id"]), LIAISON
    )
    validate_error(resp, ApiErrorId.ERR_LOAN_WINDOW_CONFLICT)
    assert get_concert_loan(loan2["id"])["status"] == "REQUESTED"
    assert get_instrument(ctx["instrument"]["id"])["status"] == "ON_LOAN"
