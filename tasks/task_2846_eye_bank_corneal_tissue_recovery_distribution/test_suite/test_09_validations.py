"""
Declared field and request-level guards, driven at the exact instant or figure where the
rule flips.

Each pair of assertions pins the refusal and, wherever the boundary is inclusive on one
side, the neighbouring value that is accepted.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_CLOCK_REWIND_FORBIDDEN,
    ERR_DEATH_TIME_IN_FUTURE,
    ERR_DUPLICATE_DONOR_CODE,
    ERR_DUPLICATE_SCREENING_ANSWER,
    ERR_INVALID_PAGINATION,
    ERR_SURGERY_DATE_IN_PAST,
    T_NOW,
    assert_instant_equals,
    assert_total_count,
    factories,
    fixtures,
    get_success_data,
    page_of,
    total_count_of,
    validate_error,
    validate_success,
)


def test_donor_list_with_limit_one_hundred_and_one_yields_err_invalid_pagination(
    pinned_api,
):
    """
    The pagination bound is a range check rather than a silent clamp: 101 is refused outright
    while the upper bound itself, 100, serves the page.

    PRD 2.3: "`limit` defaults to 10 when omitted, may not be smaller than 1, and may not
    exceed 100."

    PRD 2.3: "A `limit` outside the inclusive range 1 through 100, or a negative `offset`, is
    rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    PRD 2.10: "Pagination parameters are in range — otherwise `ERR_INVALID_PAGINATION` (400).
    Applies to the eight paginated collections listed in section 2.3."

    Design: Corner/validations/donor_list_with_limit_one_hundred_and_one_yields_err_invalid_pagination
    """
    fixtures.create_donor(pinned_api, donor_code="D-2846-V01")

    response = pinned_api.list_donors(COORDINATOR_HEADERS, limit=101, offset=0)

    validate_error(response, ERR_INVALID_PAGINATION, 400)

    accepted = pinned_api.list_donors(COORDINATOR_HEADERS, limit=100, offset=0)

    assert_total_count(accepted, 1)
    accepted_rows, _accepted_meta = page_of(accepted)
    assert len(accepted_rows) == 1


def test_reusing_a_donor_code_yields_err_duplicate_donor_code(pinned_api):
    """
    Uniqueness is global rather than scoped to the referral source or the death date, so a
    second referral quoting the same code is refused and no second row appears.

    PRD 3.1: "The coordinator taking the call supplies a `donor_code` — the bank-assigned
    identifier printed on every recovery label, between 1 and 32 characters long and globally
    unique across the bank, so that a code already in use by another donor is refused with
    `ERR_DUPLICATE_DONOR_CODE` — together with the `referral_source`, which is one of
    `HOSPITAL`, `HOSPICE`, `MEDICAL_EXAMINER` or `FUNERAL_HOME`."

    PRD 2.10: "The submitted `donor_code` is not already used by another donor — otherwise
    `ERR_DUPLICATE_DONOR_CODE` (409). Applies to donor registration."

    Design: Corner/validations/reusing_a_donor_code_yields_err_duplicate_donor_code
    """
    first = fixtures.create_donor(
        pinned_api,
        donor_code="D-2846-V02",
        referral_source="HOSPITAL",
        death_at="2026-08-03T02:00:00.000Z",
        death_time_basis="ASYSTOLE",
        age_years=52,
        cause_of_death_category="CARDIAC",
    )

    response = pinned_api.create_donor(
        factories.donor_payload(
            donor_code="D-2846-V02",
            referral_source="MEDICAL_EXAMINER",
            death_at="2026-08-03T01:00:00.000Z",
            death_time_basis="PRONOUNCED",
            age_years=68,
            cause_of_death_category="TRAUMA",
        ),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_DUPLICATE_DONOR_CODE, 409)
    listing = pinned_api.list_donors(COORDINATOR_HEADERS)
    assert_total_count(listing, 1)
    listing_rows, _listing_meta = page_of(listing)
    assert [row["id"] for row in listing_rows] == [first["id"]]


def test_answering_the_same_screening_question_twice_yields_err_duplicate_screening_answer(
    pinned_api,
):
    """
    The uniqueness key is the donor and question code alone, so changing the response and the
    historian does not make it a new answer, and the rejected write neither re-scores the
    donor nor bumps its version.

    PRD 3.1: "The record is append-only and each question may be answered at most once per
    donor: a second answer to the same `question_code` for the same donor is refused with
    `ERR_DUPLICATE_SCREENING_ANSWER`."

    PRD 2.10: "No screening record already exists for this donor and `question_code` —
    otherwise `ERR_DUPLICATE_SCREENING_ANSWER` (409). Applies to screening-record creation."

    PRD 3.1: "Rows answered `NO` contribute nothing to either total."

    Design: Corner/validations/answering_the_same_screening_question_twice_yields_err_duplicate_screening_answer
    """
    donor = fixtures.create_donor(pinned_api, donor_code="D-2846-V03")
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")

    response = pinned_api.create_screening_record(
        donor["id"],
        factories.screening_payload("TATTOO_12M", "YES", "SIBLING"),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_DUPLICATE_SCREENING_ANSWER, 409)
    reread = fixtures.read_donor(pinned_api, donor["id"])
    assert reread["screening_risk_score"] == 0
    assert reread["version"] == 2
    records = get_success_data(
        pinned_api.list_screening_records(donor["id"], COORDINATOR_HEADERS)
    )
    assert len(records) == 1
    assert records[0]["response"] == "NO"
    assert records[0]["historian_relationship"] == "SPOUSE"


def test_a_donor_whose_death_at_is_after_now_yields_err_death_time_in_future(pinned_api):
    """
    The comparison is against the logical clock, so a death two hours ahead of the pinned
    instant is refused even though that instant is in the real-world past.

    PRD 2.4: "The server does not consult real wall-clock time."

    PRD 3.1: "The clinical anchor of the whole record is `death_at`, the instant of death,
    from which every recovery time limit is measured; a `death_at` later than the current
    logical instant is nonsense and is refused with `ERR_DEATH_TIME_IN_FUTURE`."

    PRD 2.10: "The donor's `death_at` is no later than the logical clock — otherwise
    `ERR_DEATH_TIME_IN_FUTURE` (422). Applies to donor registration."

    Design: Corner/validations/a_donor_whose_death_at_is_after_now_yields_err_death_time_in_future
    """
    clock = fixtures.set_clock(pinned_api, T_NOW)
    assert_instant_equals(clock["current_utc"], T_NOW, "current_utc")

    response = pinned_api.create_donor(
        factories.donor_payload(
            donor_code="D-2846-V04",
            referral_source="HOSPITAL",
            death_at="2026-08-03T08:00:00.000Z",
            death_time_basis="ASYSTOLE",
            # The factory default body_cooled_at sits before this death_at, and PRD 3.1
            # makes that inversion an invalid request, which rung 6 would report ahead of
            # the rung-30 future-death check under test. Send no cooling instant at all.
            body_cooled_at=None,
            age_years=52,
            cause_of_death_category="CARDIAC",
        ),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_DEATH_TIME_IN_FUTURE, 422)
    assert total_count_of(pinned_api.list_donors(COORDINATOR_HEADERS)) == 0


def test_a_death_at_exactly_equal_to_now_is_accepted_and_earns_the_full_cooling_credit(
    pinned_api,
):
    """
    The satisfaction side of the same rule at its exact boundary: a death recorded at the
    current instant passes, and cooling begun in the same instant is a delay of zero minutes,
    which sits inside the fast band for the full four-hour credit.

    PRD 2.10: "The donor's `death_at` is no later than the logical clock — otherwise
    `ERR_DEATH_TIME_IN_FUTURE` (422). Applies to donor registration."

    PRD 3.1: "The base window is **twelve hours — 720 minutes — when `death_time_basis` is
    `ASYSTOLE`, and eleven hours (660 minutes) when it is `PRONOUNCED`**, reflecting the
    greater confidence attached to an observed asystole."

    PRD 3.1: "Otherwise the cooling delay is the number of whole minutes from `death_at` to
    `body_cooled_at`, floored; a delay of at most four hours (240 minutes) earns a credit of
    four hours, a delay of more than four hours but at most eight hours (480 minutes) earns a
    credit of two hours (120 minutes), and a delay beyond eight hours earns nothing."

    PRD 3.1: "Finally `recovery_deadline_at` is `death_at` advanced by
    `recovery_window_minutes`, and it is the hard cut-off past which the cornea may not be
    preserved."

    Design: Corner/validations/a_death_at_exactly_equal_to_now_is_accepted_and_earns_the_full_cooling_credit
    """
    response = pinned_api.create_donor(
        factories.donor_payload(
            donor_code="D-2846-V05",
            referral_source="HOSPITAL",
            death_at=T_NOW,
            death_time_basis="ASYSTOLE",
            body_cooled_at=T_NOW,
            age_years=52,
            cause_of_death_category="CARDIAC",
        ),
        COORDINATOR_HEADERS,
    )

    donor = validate_success(response, 201)
    assert donor["status"] == "REFERRED"
    assert donor["recovery_window_minutes"] == 960
    # death_at is T_NOW (2026-08-03T06:00:00.000Z) advanced by the 960-minute window.
    assert_instant_equals(
        donor["recovery_deadline_at"], "2026-08-03T22:00:00.000Z", "recovery_deadline_at"
    )


def test_rewinding_the_logical_clock_yields_err_clock_rewind_forbidden_while_a_reset_to_now_passes(
    pinned_api,
):
    """
    The monotonicity guard separates two instants one millisecond apart: one millisecond
    earlier is refused, while re-setting the clock to exactly the current instant is accepted
    and leaves the clock where it stood.

    PRD 2.4: "The clock never rewinds: `to_iso8601` must be greater than or equal to the
    current logical instant, and a strictly earlier target is rejected with
    `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP 422)."

    PRD 2.10: "The requested logical instant is at or after the current logical instant —
    otherwise `ERR_CLOCK_REWIND_FORBIDDEN` (422). Applies to the clock capability."

    Design: Corner/validations/rewinding_the_logical_clock_yields_err_clock_rewind_forbidden_while_a_reset_to_now_passes
    """
    response = pinned_api.set_clock(
        "2026-08-03T05:59:59.999Z", COORDINATOR_HEADERS
    )

    validate_error(response, ERR_CLOCK_REWIND_FORBIDDEN, 422)

    again = pinned_api.set_clock(T_NOW, COORDINATOR_HEADERS)

    unchanged = validate_success(again, 200)
    assert_instant_equals(unchanged["current_utc"], T_NOW, "current_utc")


def test_a_surgeon_request_whose_surgery_date_equals_now_yields_err_surgery_date_in_past(
    pinned_api,
):
    """
    The surgery-date rule is strict, so equality with the clock fails and one millisecond
    later succeeds, scoring as a same-day booking.

    PRD 3.6: "A request names `surgeon_id`; `procedure_type`, one of `PK`, `DSAEK`, `DMEK` or
    `THERAPEUTIC`; `surgery_date`, the scheduled surgery instant, which must be strictly later
    than the current logical instant, an equal or earlier instant being refused with
    `ERR_SURGERY_DATE_IN_PAST`; `min_ecd`, the minimum acceptable endothelial cell density, a
    whole number from 500 through 4000; `max_donor_age_years`, the maximum acceptable donor age
    in whole years, from 0 through 110; `laterality_preference`, one of `OD`, `OS` or `ANY`;
    and `urgency`, either `ROUTINE` or `URGENT`."

    PRD 2.10: "`surgery_date` is strictly later than the logical clock — otherwise
    `ERR_SURGERY_DATE_IN_PAST` (422). Applies to surgeon-request creation."

    PRD 3.6: "In step one, an urgency weight of 30 is credited for `URGENT` and 10 for
    `ROUTINE`; separately, the number of whole days from the current logical instant to
    `surgery_date` is computed by flooring, and this figure may be negative for a request whose
    surgery date has already passed."

    PRD 3.6: "Surgery-proximity points are then awarded from that day count: 40 points when it
    is 2 or fewer, 25 points when it is between 3 and 7 inclusive, 10 points when it is between
    8 and 21 inclusive, and 0 points otherwise."

    PRD 3.6: "In step two, `priority_tier` is selected **from `base_score` alone**: `PLATINUM`
    when `base_score` is 60 or more, `GOLD` when it is at least 40 but less than 60, and
    `STANDARD` otherwise."

    PRD 3.6: "In step three a tier bonus of 15 for `PLATINUM`, 8 for `GOLD` and 0 for
    `STANDARD` is added to `base_score` to produce `priority_score`."

    Design: Corner/validations/a_surgeon_request_whose_surgery_date_equals_now_yields_err_surgery_date_in_past
    """
    surgeon = fixtures.create_surgeon(pinned_api, "Dr Imani Rho", "CTR-01", "PK")

    response = pinned_api.create_surgeon_request(
        factories.request_payload(surgeon["id"], surgery_date=T_NOW), COORDINATOR_HEADERS
    )

    validate_error(response, ERR_SURGERY_DATE_IN_PAST, 422)

    accepted = pinned_api.create_surgeon_request(
        factories.request_payload(
            surgeon["id"], surgery_date="2026-08-03T06:00:00.001Z"
        ),
        COORDINATOR_HEADERS,
    )

    request = validate_success(accepted, 201)
    assert request["status"] == "OPEN"
    assert request["base_score"] == 50
    assert request["priority_tier"] == "GOLD"
    assert request["priority_score"] == 58
    listing = pinned_api.list_surgeon_requests(COORDINATOR_HEADERS)
    assert_total_count(listing, 1)
    listing_rows, _listing_meta = page_of(listing)
    assert [row["id"] for row in listing_rows] == [request["id"]]
