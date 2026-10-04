"""Artist program: performances, annual review branches, standing counters."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_artist,
    create_loan,
    create_loan_payload,
    get_artist,
    log_performance,
    make_artist_headers,
    performance_payload,
    review_artist,
    return_loan,
    set_clock,
    setup_artist_with_performances,
    setup_on_tour_loan,
    setup_suspended_artist,
    validate_error,
    validate_paginated,
)

WM = TEST_USERS["workshop_manager_headers"]
LIAISON = TEST_USERS["artist_liaison_headers"]


def test_performance_in_future_rejected(api):
    """PRD section 3.5: "a performance dated after the current logical clock is
    rejected with `ERR_PERFORMANCE_IN_FUTURE` (HTTP 422)."
    Startup clock is 2026-09-01T00:00:00Z (section 2.4), so 2026-12-25 is future.

    Design: Corner/validations/performance_in_future_rejected
    """
    artist = create_artist("Art P", "STANDARD", 2)
    resp = api.log_artist_performance(
        artist["id"], performance_payload("Future Hall", "2026-12-25T00:00:00Z"), LIAISON
    )
    validate_error(resp, ApiErrorId.ERR_PERFORMANCE_IN_FUTURE)
    assert get_artist(artist["id"])["performances_logged"] == 0


def test_review_before_due_date_rejected(api):
    """PRD section 3.5: "New artists start `ACTIVE` with `performances_logged` at 0
    and a `next_review_date` exactly 365 days after creation."
    PRD section 3.5: "The annual review is the liaison's standing check, allowed
    only once the logical clock has reached the artist's `next_review_date`; an
    early review fails with `ERR_REVIEW_NOT_DUE`."

    Design: Corner/validations/review_before_due_date_rejected
    """
    artist = create_artist("Art R", "STANDARD", 2)
    assert artist["next_review_date"] == "2027-09-01T00:00:00Z"
    resp = api.review_artist(artist["id"], {}, LIAISON)
    validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_DUE)
    assert get_artist(artist["id"])["status"] == "ACTIVE"


def test_artist_review_suspend_met_and_reinstate_branches(api):
    """PRD section 3.5: "An `ACTIVE` artist who met quota stays `ACTIVE`, resets
    `performances_logged` to 0, and pushes `next_review_date` forward by 365 days.
    An `ACTIVE` artist who fell short moves to `SUSPENDED` with `performances_logged`
    retained and `next_review_date` unchanged, so a re-review is allowed after
    catch-up. A `SUSPENDED` artist who has since caught up to quota returns to
    `ACTIVE`, resets `performances_logged` to 0, and re-arms `next_review_date` to
    365 days from the clock now."
    Exact re-armed dates are asserted as the 365-day window both faithful readings
    of "365 days" agree on across the 2028 leap day.

    Design: Corner/state_machines/artist_review_suspend_met_and_reinstate_branches
    """
    art_a = create_artist("Art A", "STANDARD", 2)
    art_b = create_artist("Art B", "STANDARD", 1)
    log_performance(art_b["id"], "Opener")  # performed_at defaults to clock start
    set_clock("2027-09-01T00:00:00Z")  # exactly both artists' next_review_date
    rev_a = review_artist(art_a["id"])
    assert rev_a["status"] == "SUSPENDED"
    assert rev_a["performances_logged"] == 0
    assert rev_a["next_review_date"] == art_a["next_review_date"]  # unchanged
    rev_b = review_artist(art_b["id"])
    assert rev_b["status"] == "ACTIVE"
    assert rev_b["performances_logged"] == 0  # reset
    assert "2028-08-31T00:00:00Z" <= rev_b["next_review_date"] <= "2028-09-01T00:00:00Z"
    set_clock("2027-12-01T00:00:00Z")
    log_performance(art_a["id"], "Catchup 1", "2027-10-01T00:00:00Z")
    log_performance(art_a["id"], "Catchup 2", "2027-10-02T00:00:00Z")
    reinstated = review_artist(art_a["id"])
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["performances_logged"] == 0
    assert "2028-11-30T00:00:00Z" <= reinstated["next_review_date"] <= "2028-12-01T00:00:00Z"


def test_standing_realized_and_forward_diverge(api):
    """PRD section 3.5: "`standing_realized` is simply `performances_logged`.
    `standing_forward` adds projected tour-week credit: for each of the artist's
    loans currently `ON_TOUR`, that loan's tour weeks — its whole-day length
    divided by 7 and rounded up, the same measure the loan fee uses — is added to
    the realized count."
    Two logged performances plus a 21-day ON_TOUR loan: 2 and 2 + 3 = 5.

    Design: Difficulty/dual_variant_calc/artist_standing_realized_vs_forward_diverge
    """
    artist = setup_artist_with_performances(2, "Art A", "STANDARD", 3)
    setup_on_tour_loan(
        "MODEL_B", "2028-06-01T00:00:00Z", "2028-06-22T00:00:00Z", artist=artist
    )
    data = get_artist(artist["id"])
    assert data["standing_realized"] == 2
    assert data["standing_forward"] == 5
    assert data["performances_logged"] == 2
    assert data["status"] == "ACTIVE"


def test_standing_forward_converges_after_return(api):
    """PRD section 3.5: "Identical data always yields `standing_forward` at least
    equal to `standing_realized`, and strictly greater while any tour is on the
    road." Once the only loan returns, no tour is on the road and the counters
    agree again.

    Design: Difficulty/dual_variant_calc/artist_standing_realized_vs_forward_diverge
    """
    artist = setup_artist_with_performances(2, "Art A", "STANDARD", 3)
    ctx = setup_on_tour_loan(
        "MODEL_B", "2028-06-01T00:00:00Z", "2028-06-22T00:00:00Z", artist=artist
    )
    return_loan(ctx["loan"]["id"], "A")
    data = get_artist(artist["id"])
    assert data["standing_realized"] == 2
    assert data["standing_forward"] == 2


def test_suspended_artist_loan_create_rejected(api):
    """PRD section 3.6: "the artist must be `ACTIVE` at request time, else
    `ERR_ARTIST_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/loan_create_requires_active_artist
    """
    artist = setup_suspended_artist(3)
    assert artist["status"] == "SUSPENDED"
    resp = api.create_concert_loan(
        create_loan_payload("MODEL_D", "2027-10-01T00:00:00Z", "2027-10-15T00:00:00Z"),
        make_artist_headers(artist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ARTIST_NOT_ACTIVE)
    rows, meta = validate_paginated(
        api.list_concert_loans(LIAISON, params={"artist_id": artist["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_reinstated_artist_loan_create_succeeds(api):
    """PRD section 3.5: "A `SUSPENDED` artist who has since caught up to quota
    returns to `ACTIVE`".
    PRD section 3.6: "The loan opens in `REQUESTED` with `instrument_id`,
    `technician_id`, and `fee_cents` all null."

    Design: Difficulty/cross_entity_state_dependency/loan_create_requires_active_artist
    """
    artist = setup_suspended_artist(3)
    for index in range(3):
        log_performance(artist["id"], f"Catchup {index + 1}")
    revived = review_artist(artist["id"])
    assert revived["status"] == "ACTIVE"
    assert revived["performances_logged"] == 0
    loan = create_loan(revived, "MODEL_D", "2027-10-01T00:00:00Z", "2027-10-15T00:00:00Z")
    assert loan["status"] == "REQUESTED"
    assert loan["artist_id"] == artist["id"]
    assert loan["instrument_id"] is None
    assert loan["technician_id"] is None
    assert loan["fee_cents"] is None
