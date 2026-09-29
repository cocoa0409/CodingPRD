"""
Two temporal calendars of the licensing contract and the overlap rules on each.

The first calendar belongs to a single licence's coverage windows, where the
overlap test is scoped to one ``window_kind`` at a time and every window must sit
inside the licence's own half-open term: the annual window spanning the whole
term is harmless, a second seasonal rider over days another seasonal rider
already holds is fatal, and a festival rider over exactly those same days is
legal again.  The second calendar belongs to the licences themselves, keyed by
venue and society, where the test fires at approval time and adjacency at
``term_end`` is what makes the renewal calendar workable at all.
"""

from test_helpers import (
    APPLICATION_STATUS_APPROVED,
    APPLICATION_STATUS_UNDER_REVIEW,
    APPLICATION_STATUS_WITHDRAWN,
    COVERAGE_ACTIVE,
    COVERAGE_PENDING_ACTIVATION,
    ERR_COVERAGE_WINDOW_OVERLAP,
    ERR_DUPLICATE_ACTIVE_LICENSE,
    ERR_WINDOW_OUTSIDE_TERM,
    WINDOW_KIND_ANNUAL_TERM,
    WINDOW_KIND_FESTIVAL_RIDER,
    WINDOW_KIND_SEASONAL_EVENT_RIDER,
    WINDOW_STATUS_ACTIVE,
    admin_headers,
    application_row,
    accept_for_review,
    approve,
    approve_payload,
    assert_count,
    assert_days_apart,
    assert_instant_equals,
    assert_money,
    assert_venue_ledger,
    bar_grill_venue_payload,
    bmi_payload,
    coverage_window_payload,
    find_row,
    given_active_license,
    given_coverage_window,
    given_effective_schedule,
    given_society,
    given_submitted_application,
    given_venue,
    license_of_application,
    license_row,
    read_rows,
    validate_error,
    validate_success,
    venue_row,
    windows_of_license,
)

_VENUE_CATEGORY = "BAR_GRILL"
_SCHEDULE_FROM = "2026-01-01T00:00:00Z"

# The licence term every window in this file is measured against.
_TERM_START = "2026-08-01T00:00:00Z"
_TERM_END = "2027-08-01T00:00:00Z"
_FEE_CENTS = 90017

# The two abutting seasonal riders: fifteen days of holiday programming handing
# straight over to seven more at the stroke of the new year.
_W1_START = "2026-12-20T00:00:00Z"
_W1_END = "2027-01-04T00:00:00Z"
_W1_DAYS = 15
_W1_FEE_CENTS = 4994

_W2_START = "2027-01-04T00:00:00Z"
_W2_END = "2027-01-11T00:00:00Z"
_W2_DAYS = 7
_W2_FEE_CENTS = 2331

# Three days straddling the hand-over, so they intersect both riders above.
_CLASH_START = "2027-01-03T00:00:00Z"
_CLASH_END = "2027-01-06T00:00:00Z"
_CLASH_DAYS = 3
_CLASH_FEE_CENTS = 999

# A rider that starts inside the term but runs a few days past its end.
_PAST_TERM_START = "2027-07-25T00:00:00Z"
_PAST_TERM_END = "2027-08-05T00:00:00Z"

_LEDGER_AFTER_THREE_RIDERS = _FEE_CENTS + _W1_FEE_CENTS + _W2_FEE_CENTS + _CLASH_FEE_CENTS

# The second licence term on the same venue-and-society calendar.
_SUCCESSOR_TERM_START = "2027-08-01T00:00:00Z"
# PRD §3.4: "`term_end` exactly 365 days after `term_start`".  2028 is a leap
# year, so 365 days on from 2027-08-01 lands on 2028-07-31, not 2028-08-01.
_SUCCESSOR_TERM_END = "2028-07-31T00:00:00Z"

# A term that starts seven months into the incumbent's, so the two intersect.
_OVERLAPPING_TERM_START = "2027-03-01T00:00:00Z"


def _build_licence_with_two_abutting_riders(api):
    """One ACTIVE BMI licence over a full year, carrying three coverage windows.

    Activation supplies the ``ANNUAL_TERM`` window over the whole term; the two
    seasonal riders are then attached back to back, the second beginning at the
    exact instant the first ends.
    """
    bmi = given_society(api, bmi_payload())
    given_effective_schedule(api, bmi["id"], _VENUE_CATEGORY, _SCHEDULE_FROM)
    venue = given_venue(api, bar_grill_venue_payload())
    licence = given_active_license(
        api, venue_row(api, venue["id"]), bmi["id"], _TERM_START
    )
    assert_money(licence["annual_fee_cents"], _FEE_CENTS, "annual_fee_cents")
    window_one = given_coverage_window(
        api, licence["id"], _W1_START, _W1_END, WINDOW_KIND_SEASONAL_EVENT_RIDER
    )
    window_two = given_coverage_window(
        api, licence["id"], _W2_START, _W2_END, WINDOW_KIND_SEASONAL_EVENT_RIDER
    )
    return {
        "bmi": bmi,
        "venue": venue,
        "license": licence,
        "window_one": window_one,
        "window_two": window_two,
    }


def test_overlap_window_abutting_seasonal_riders_are_each_priced_for_their_own_days(api):
    """Handing over at the exact instant one rider ends is not an overlap.

    PRD §3.6: "`covered_day_count` is computed as the whole days from
    `window_start` up to `window_end`; because the interval is half-open, a window
    that ends exactly where the next begins contributes its days once and only
    once."

    PRD §3.6: "For a `SEASONAL_EVENT_RIDER` or a `FESTIVAL_RIDER`,
    `rider_fee_cents` is derived from the owning licence's `annual_fee_cents` as it
    stands **at the moment the rider is created**: multiply that
    `annual_fee_cents` by the window's `covered_day_count`, multiply by the
    seasonal peak factor of 13500 basis points, divide by the product of 365
    term-days and 10000, and round half up to whole cents — a **single** rounding
    step at the very end, with the day fraction and the peak factor combined
    inside one expression rather than rounded independently."

    Design: Difficulty/resource_temporal_overlap/overlap_rider_windows_scoped_by_window_kind_inside_the_term
    """
    world = _build_licence_with_two_abutting_riders(api)

    first = world["window_one"]
    assert_count(first["covered_day_count"], _W1_DAYS, "W1 covered_day_count")
    assert_money(first["rider_fee_cents"], _W1_FEE_CENTS, "W1 rider_fee_cents")
    assert_days_apart(_W1_START, _W1_END, _W1_DAYS, "W1 span")

    second = world["window_two"]
    assert_count(second["covered_day_count"], _W2_DAYS, "W2 covered_day_count")
    assert_money(second["rider_fee_cents"], _W2_FEE_CENTS, "W2 rider_fee_cents")
    assert_instant_equals(second["window_start"], first["window_end"], "hand-over instant")

    windows = windows_of_license(api, world["license"]["id"])
    assert len(windows) == 3, (
        f"expected the annual window plus two riders, got {len(windows)}"
    )
    for window in windows:
        assert window["status"] == WINDOW_STATUS_ACTIVE, (
            f"every window here should still be ACTIVE, got {window['status']!r}"
        )


def test_overlap_window_the_annual_term_window_never_clashes_with_a_rider(api):
    """The window covering the whole term coexists with riders inside it.

    PRD §3.6: "The window must sit inside the licence's own half-open term and
    must not overlap an existing `ACTIVE` window of the same `license_id` *and the
    same* `window_kind`, with exact adjacency permitted; §2.12 gives the two
    rejection codes and their position in the ladder."

    PRD §3.6: "An `ANNUAL_TERM` window always has `rider_fee_cents` of 0."

    Design: Difficulty/resource_temporal_overlap/overlap_rider_windows_scoped_by_window_kind_inside_the_term
    """
    world = _build_licence_with_two_abutting_riders(api)

    windows = windows_of_license(api, world["license"]["id"])
    annual = find_row(windows, window_kind=WINDOW_KIND_ANNUAL_TERM)
    assert_instant_equals(annual["window_start"], _TERM_START, "annual window_start")
    assert_instant_equals(annual["window_end"], _TERM_END, "annual window_end")
    assert_count(annual["covered_day_count"], 365, "annual covered_day_count")
    assert_money(annual["rider_fee_cents"], 0, "annual rider_fee_cents")
    assert annual["status"] == WINDOW_STATUS_ACTIVE, (
        f"the annual window should be ACTIVE, got {annual['status']!r}"
    )

    riders = [
        row for row in windows if row["window_kind"] == WINDOW_KIND_SEASONAL_EVENT_RIDER
    ]
    assert len(riders) == 2, (
        f"the two riders should have been accepted inside the annual span, got {len(riders)}"
    )


def test_overlap_window_a_same_kind_intersection_is_refused(api):
    """Three days straddling the hand-over intersect both riders, so they are refused.

    PRD §2.12: "13. **Coverage-window placement.** The new window's half-open span
    lies inside the owning licence's own half-open term and does not overlap any
    `ACTIVE` window of the same `license_id` **and the same `window_kind`**; exact
    adjacency, where the new `window_start` equals a prior window's `window_end`,
    is allowed — otherwise `ERR_WINDOW_OUTSIDE_TERM` or
    `ERR_COVERAGE_WINDOW_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/overlap_rider_windows_scoped_by_window_kind_inside_the_term
    """
    world = _build_licence_with_two_abutting_riders(api)

    validate_error(
        api.create_coverage_window(
            world["license"]["id"],
            coverage_window_payload(
                _CLASH_START, _CLASH_END, WINDOW_KIND_SEASONAL_EVENT_RIDER
            ),
            admin_headers(),
        ),
        ERR_COVERAGE_WINDOW_OVERLAP,
    )

    assert len(windows_of_license(api, world["license"]["id"])) == 3, (
        "a refused window must not have been stored"
    )
    assert_venue_ledger(
        venue_row(api, world["venue"]["id"]),
        _FEE_CENTS + _W1_FEE_CENTS + _W2_FEE_CENTS,
        0,
        0,
        _FEE_CENTS + _W1_FEE_CENTS + _W2_FEE_CENTS,
    )


def test_overlap_window_the_same_days_under_a_different_kind_are_accepted_and_priced(api):
    """The very interval refused as a seasonal rider is legal as a festival rider.

    PRD §3.6: "Beyond the annual term, a `LicensingAdmin` may attach further
    coverage windows to an `ACTIVE` licence by supplying `window_kind` — one of
    `ANNUAL_TERM`, `SEASONAL_EVENT_RIDER` or `FESTIVAL_RIDER` — with
    `window_start` and `window_end`."

    PRD §3.6: "Creating a priced rider issues a `FeeAssessment` with
    `assessment_kind` `SEASONAL_RIDER` for exactly that `rider_fee_cents`, in
    `ISSUED` status with `paid_amount_cents` at 0 and `due_date` 30 days after the
    logical clock instant."

    Design: Difficulty/resource_temporal_overlap/overlap_rider_windows_scoped_by_window_kind_inside_the_term
    """
    world = _build_licence_with_two_abutting_riders(api)

    # PRD §4: a coverage window is a brand-new row, so the create answers 201.
    festival = validate_success(
        api.create_coverage_window(
            world["license"]["id"],
            coverage_window_payload(
                _CLASH_START, _CLASH_END, WINDOW_KIND_FESTIVAL_RIDER
            ),
            admin_headers(),
        ),
        201,
    )
    assert festival["window_kind"] == WINDOW_KIND_FESTIVAL_RIDER, (
        f"window_kind: expected FESTIVAL_RIDER, got {festival['window_kind']!r}"
    )
    assert_count(festival["covered_day_count"], _CLASH_DAYS, "covered_day_count")
    assert_money(festival["rider_fee_cents"], _CLASH_FEE_CENTS, "rider_fee_cents")

    assert len(windows_of_license(api, world["license"]["id"])) == 4, (
        "the festival rider should have joined the annual window and the two seasonal riders"
    )
    assert_venue_ledger(
        venue_row(api, world["venue"]["id"]),
        _LEDGER_AFTER_THREE_RIDERS,
        0,
        0,
        _LEDGER_AFTER_THREE_RIDERS,
    )


def test_overlap_window_a_rider_running_past_the_term_end_is_refused(api):
    """A rider must be contained in the term, not merely start inside it.

    PRD §2.12: "13. **Coverage-window placement.** The new window's half-open span
    lies inside the owning licence's own half-open term and does not overlap any
    `ACTIVE` window of the same `license_id` **and the same `window_kind`**; exact
    adjacency, where the new `window_start` equals a prior window's `window_end`,
    is allowed — otherwise `ERR_WINDOW_OUTSIDE_TERM` or
    `ERR_COVERAGE_WINDOW_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/overlap_rider_windows_scoped_by_window_kind_inside_the_term
    """
    world = _build_licence_with_two_abutting_riders(api)

    validate_error(
        api.create_coverage_window(
            world["license"]["id"],
            coverage_window_payload(
                _PAST_TERM_START, _PAST_TERM_END, WINDOW_KIND_SEASONAL_EVENT_RIDER
            ),
            admin_headers(),
        ),
        ERR_WINDOW_OUTSIDE_TERM,
    )

    assert len(windows_of_license(api, world["license"]["id"])) == 3, (
        "a window reaching past term_end must not have been stored"
    )


# ─── The per-venue, per-society licence calendar ──────────────────────────


def _build_active_licence_and_overlapping_application(api):
    """One ACTIVE BMI licence for 2026-08-01 to 2027-08-01, plus a rival under review.

    The rival application asks for a term starting seven months into the
    incumbent's, so the term it implies intersects the licence that already
    exists on this venue-and-society calendar.  The venue row is re-read before
    the second filing because the first filing and the activation both advanced
    its revision counter.
    """
    bmi = given_society(api, bmi_payload())
    given_effective_schedule(api, bmi["id"], _VENUE_CATEGORY, _SCHEDULE_FROM)
    venue = given_venue(api, bar_grill_venue_payload())
    first_licence = given_active_license(
        api, venue_row(api, venue["id"]), bmi["id"], _TERM_START
    )
    rival = given_submitted_application(
        api, venue_row(api, venue["id"]), bmi["id"], _OVERLAPPING_TERM_START
    )
    under_review = accept_for_review(api, rival["id"])
    assert under_review["status"] == APPLICATION_STATUS_UNDER_REVIEW, (
        f"expected the rival to be UNDER_REVIEW, got {under_review['status']!r}"
    )
    return {
        "bmi": bmi,
        "venue": venue,
        "first_license": first_licence,
        "rival": rival,
    }


def test_overlap_term_approving_an_overlapping_second_term_is_refused(api):
    """The duplicate-licence test fires at approval, leaving the application under review.

    PRD §2.12: "17. **Declared uniqueness.** No other `License` exists for the
    same `venue_id` and `society_id` pair with `coverage_status` in
    `PENDING_ACTIVATION`, `ACTIVE` or `SUSPENDED` whose term overlaps the term
    being created or activated — a renewal starting exactly at the predecessor's
    `term_end` is therefore legal — and no other `Society` already uses the
    requested `society_code`."

    Design: Difficulty/resource_temporal_overlap/overlap_license_terms_per_venue_and_society
    """
    world = _build_active_licence_and_overlapping_application(api)

    validate_error(
        api.review_application(
            world["rival"]["id"], approve_payload(), admin_headers()
        ),
        ERR_DUPLICATE_ACTIVE_LICENSE,
    )

    still_under_review = application_row(api, world["rival"]["id"])
    assert still_under_review["status"] == APPLICATION_STATUS_UNDER_REVIEW, (
        "a refused approval must leave the application UNDER_REVIEW, got "
        f"{still_under_review['status']!r}"
    )

    rows = read_rows(
        api.list_licenses(admin_headers(), {"venue_id": world["venue"]["id"]}),
        expected_total=1,
    )
    assert rows[0]["id"] == world["first_license"]["id"], (
        "the only licence on this venue should still be the incumbent"
    )


def test_overlap_term_an_adjacent_successor_term_is_approved_and_activates(api):
    """A term starting exactly where the incumbent's ends is legal and can be activated.

    PRD §3.4: "And **every other application for the same `venue_id` and
    `society_id` combination whose `status` is `DRAFT`, `SUBMITTED`,
    `UNDER_REVIEW` or `RETURNED_FOR_REVISION` transitions to `WITHDRAWN`**, each
    with its own `version` increment."

    PRD §3.6: "A licence created by approval sits in `PENDING_ACTIVATION` and
    covers nothing at all until a `LicensingAdmin` activates it, moving
    `coverage_status` to `ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/overlap_license_terms_per_venue_and_society
    """
    world = _build_active_licence_and_overlapping_application(api)
    validate_error(
        api.review_application(
            world["rival"]["id"], approve_payload(), admin_headers()
        ),
        ERR_DUPLICATE_ACTIVE_LICENSE,
    )

    successor_application = given_submitted_application(
        api, venue_row(api, world["venue"]["id"]), world["bmi"]["id"],
        _SUCCESSOR_TERM_START,
    )

    superseded = application_row(api, world["rival"]["id"])
    assert superseded["status"] == APPLICATION_STATUS_WITHDRAWN, (
        "filing again should have superseded the rival, got "
        f"{superseded['status']!r}"
    )
    original = application_row(api, world["first_license"]["application_id"])
    assert original["status"] == APPLICATION_STATUS_APPROVED, (
        "a terminal APPROVED application is never superseded, got "
        f"{original['status']!r}"
    )

    accept_for_review(api, successor_application["id"])
    approved = approve(api, successor_application["id"])
    assert approved["status"] == APPLICATION_STATUS_APPROVED, (
        f"the adjacent term should be approvable, got {approved['status']!r}"
    )

    successor = license_of_application(api, successor_application["id"])
    assert successor["coverage_status"] == COVERAGE_PENDING_ACTIVATION, (
        f"a freshly minted licence starts PENDING_ACTIVATION, got {successor['coverage_status']!r}"
    )
    assert_instant_equals(successor["term_start"], _SUCCESSOR_TERM_START, "term_start")
    assert_instant_equals(successor["term_end"], _SUCCESSOR_TERM_END, "term_end")
    assert_instant_equals(
        successor["term_start"],
        license_row(api, world["first_license"]["id"])["term_end"],
        "hand-over instant on the licence calendar",
    )

    read_rows(
        api.list_licenses(admin_headers(), {"venue_id": world["venue"]["id"]}),
        expected_total=2,
    )

    activated = validate_success(
        api.activate_license(successor["id"], admin_headers())
    )
    assert activated["coverage_status"] == COVERAGE_ACTIVE, (
        "activating the adjacent term must succeed, got "
        f"{activated['coverage_status']!r}"
    )
    incumbent = license_row(api, world["first_license"]["id"])
    assert incumbent["coverage_status"] == COVERAGE_ACTIVE, (
        "the incumbent licence is untouched by its successor's activation, got "
        f"{incumbent['coverage_status']!r}"
    )
