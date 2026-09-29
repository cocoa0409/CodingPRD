"""
The front of the licensing API's rejection ladder: who is allowed to speak, what
the request is allowed to say, and which rows it is allowed to name.

These tests pin the first thirteen rungs of PRD §2.12 as they apply to the
licensing surface — authentication, operator ownership, path-identifier
existence, body foreign-key existence, request shape, interval strictness,
reporting-period overlap and coverage-window placement — and in every rejection
case they also prove the refused call wrote nothing at all.
"""

from test_helpers import (
    APPLICATION_STATUS_DRAFT,
    APPLICATION_STATUS_SUBMITTED,
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_STATUS_ISSUED,
    AUDIT_TRIGGER_ROUTINE,
    BILLING_INVOICED,
    CLOCK_START_INSTANT,
    CLOSED_REASON_NO_GAP_FOUND,
    COVERAGE_ACTIVE,
    ERR_AUDIT_CASE_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_REQUEST,
    ERR_LICENSE_NOT_FOUND,
    ERR_REPORT_NOT_FOUND,
    ERR_REPORT_PERIOD_OVERLAP,
    ERR_SOCIETY_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_VENUE_NOT_FOUND,
    ERR_WINDOW_OUTSIDE_TERM,
    NON_EXISTENT_UUID,
    REPORT_STATUS_DRAFT,
    UNUSED_UUID,
    UNUSED_UUID_ALT,
    UNUSED_UUID_THIRD,
    WINDOW_KIND_ANNUAL_TERM,
    WINDOW_KIND_SEASONAL_EVENT_RIDER,
    WINDOW_STATUS_ACTIVE,
    admin_headers,
    application_payload,
    application_row,
    assert_assessment,
    assert_count,
    assert_days_apart,
    assert_empty_list,
    assert_license_dimensions,
    assert_money,
    assert_venue_ledger,
    assert_version_unchanged,
    assessments_of_venue,
    audit_case_payload,
    auditor_headers,
    bar_grill_venue_payload,
    clock_payload,
    close_case_payload,
    coverage_window_payload,
    get_success_data,
    given_coverage_window,
    given_draft_application,
    given_draft_report,
    given_licensed_venue,
    given_society,
    given_venue,
    headers_empty_role,
    headers_missing_user_id,
    headers_none,
    headers_unknown_role,
    ids_of,
    license_row,
    performance_report_payload,
    rate_schedule_payload,
    read_rows,
    report_row,
    setlist_entry_payload,
    validate_error,
    venue_operator_headers,
    venue_payload,
    venue_row,
    windows_of_license,
)

# The licence term used throughout this file starts at the logical clock's own
# start-up instant, so the term is [2026-08-01T00:00:00Z, 2027-08-01T00:00:00Z).
TERM_START = "2026-08-01T00:00:00Z"
TERM_END = "2027-08-01T00:00:00Z"

# The verified annual fee of the 180-occupancy MIXED bar and grill for a
# 4600 bp society on a default schedule.
BAR_GRILL_ANNUAL_FEE_CENTS = 90017


def test_reject_missing_or_malformed_auth_headers_unauthenticated(api):
    """Every licensing endpoint refuses a caller whose two identity headers are
    absent, empty or name a role outside the recognised four, while the clock
    endpoint stays deliberately open; the refused create writes no venue.

    PRD §2.1: "A request missing either header, carrying an empty value for
    either, or naming a role outside that set of four is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD §2.4: "Any of the four roles may invoke it, and it is the one endpoint
    exempt from the header checks in §2.1."

    Design: Corner/validations/corner_validation_missing_auth_headers_returns_unauthenticated
    """
    venue = given_venue(api)

    validate_error(
        api.get_venue(venue["id"], headers_missing_user_id()), ERR_UNAUTHENTICATED
    )
    validate_error(
        api.get_venue(venue["id"], headers_empty_role()), ERR_UNAUTHENTICATED
    )
    validate_error(
        api.get_venue(venue["id"], headers_unknown_role()), ERR_UNAUTHENTICATED
    )
    validate_error(
        api.create_venue(bar_grill_venue_payload("Ghost Room"), headers_none()),
        ERR_UNAUTHENTICATED,
    )

    # The rejected create wrote nothing: the only venue is the one built above.
    rows = read_rows(api.list_venues(admin_headers()), expected_total=1)
    assert ids_of(rows) == [venue["id"]]

    # The clock endpoint is the single exception to the header checks.
    get_success_data(api.set_clock(clock_payload(CLOCK_START_INSTANT), headers_none()))


def test_reject_operator_acting_on_another_venues_application(api):
    """A venue operator may only touch rows that resolve back to its own venue,
    and may not reach an administrator-only endpoint at all; the foreign
    operator's two attempts leave the application untouched in DRAFT.

    PRD §2.1: "When the addressed row does not resolve to the `Venue` whose `id`
    equals `X-User-ID`, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/validations/corner_validation_operator_cross_venue_access_forbidden
    """
    society = given_society(api)
    own_venue = given_venue(api)
    other_venue = given_venue(
        api,
        venue_payload(
            "Rival Room", "NIGHTCLUB", 0, 300, 320, "RECORDED_ONLY", 0, 900000
        ),
    )
    application = given_draft_application(api, own_venue, society["id"])

    validate_error(
        api.submit_application(
            application["id"], venue_operator_headers(other_venue["id"])
        ),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.update_application(
            application["id"],
            {"declared_live_nights": 2},
            venue_operator_headers(other_venue["id"]),
        ),
        ERR_FORBIDDEN_ROLE,
    )
    # Registering a venue survey is a society-side act, closed to any operator.
    validate_error(
        api.create_venue(
            bar_grill_venue_payload("Operator Built"),
            venue_operator_headers(own_venue["id"]),
        ),
        ERR_FORBIDDEN_ROLE,
    )

    unchanged = application_row(api, application["id"])
    assert unchanged["status"] == APPLICATION_STATUS_DRAFT
    assert_version_unchanged(unchanged, application, "application")
    assert_count(unchanged["declared_live_nights"], 4, "declared_live_nights")

    # The venue's own operator gets through on the very same call.
    submitted = get_success_data(
        api.submit_application(
            application["id"], venue_operator_headers(own_venue["id"])
        )
    )
    assert submitted["status"] == APPLICATION_STATUS_SUBMITTED


def test_reject_unknown_path_identifier_before_body_shape(api):
    """An identifier in the path that names no row decides the rejection before
    the body is ever inspected, and each 404 names the resource type of the
    identifier that failed to resolve.

    PRD §2.8: "Identifiers embedded in a URL path are resolved strictly left to
    right, and the path's own addressed resource is checked last."

    PRD §2.12: "**Path existence.** Every identifier in the URL path exists,
    validated left to right with the addressed resource checked last — otherwise
    the matching 404 from the `ERR_*_NOT_FOUND` family in §2.8. Applies to every
    endpoint with a path identifier."

    Design: Corner/validations/corner_validation_path_ids_resolved_before_body_returns_not_found
    """
    venue = given_venue(api)

    validate_error(api.get_license(UNUSED_UUID, admin_headers()), ERR_LICENSE_NOT_FOUND)

    well_formed_entry = setlist_entry_payload(
        "Blue Room Waltz", "A. Writer", "BMI", "2026-09-10T21:00:00Z", 240
    )
    validate_error(
        api.create_setlist_entry(UNUSED_UUID_ALT, well_formed_entry, admin_headers()),
        ERR_REPORT_NOT_FOUND,
    )
    # The same unknown report still decides the answer when the body is invalid.
    shapeless_entry = dict(well_formed_entry)
    shapeless_entry.pop("work_title")
    validate_error(
        api.create_setlist_entry(UNUSED_UUID_ALT, shapeless_entry, admin_headers()),
        ERR_REPORT_NOT_FOUND,
    )

    validate_error(
        api.close_audit_case(
            UNUSED_UUID_THIRD,
            close_case_payload(CLOSED_REASON_NO_GAP_FOUND),
            auditor_headers(),
        ),
        ERR_AUDIT_CASE_NOT_FOUND,
    )
    validate_error(
        api.run_exemption_analysis(NON_EXISTENT_UUID, admin_headers()),
        ERR_VENUE_NOT_FOUND,
    )

    assert_version_unchanged(venue_row(api, venue["id"]), venue, "venue")
    assert_empty_list(api.list_licenses(admin_headers()))
    assert_empty_list(api.list_performance_reports(admin_headers()))
    assert_empty_list(api.list_setlist_entries(admin_headers()))
    assert_empty_list(api.list_audit_cases(admin_headers()))


def test_reject_body_foreign_key_that_names_no_row(api):
    """A foreign key supplied in a request body is checked for existence before
    any business rule consults the referenced row, and the `society_ids` array is
    checked element by element, so nothing at all is created.

    PRD §2.8: "The same existence discipline extends to foreign keys supplied in
    a request **body**, which are checked before any business rule that would
    consult the referenced row: `venue_id`, `society_id`, `license_id`,
    `audit_case_id`, and every element of the `society_ids` array."

    PRD §3.9: "That array holds between 1 and 4 elements with no duplicates, and
    each element must reference an existing `Society` row; elements are validated
    left to right, so the first element naming no society determines the
    rejection."

    Design: Corner/validations/corner_validation_body_foreign_keys_missing_required_referent_not_found
    """
    society = given_society(api)
    venue = given_venue(api)

    validate_error(
        api.create_rate_schedule(
            rate_schedule_payload(UNUSED_UUID, "BAR_GRILL"), admin_headers()
        ),
        ERR_SOCIETY_NOT_FOUND,
    )
    validate_error(
        api.create_application(
            application_payload(
                UNUSED_UUID_ALT,
                society["id"],
                "BLANKET",
                120,
                180,
                4200000,
                4,
                "MIXED",
                "2026-09-01T00:00:00Z",
                expected_venue_version=venue["version"],
            ),
            admin_headers(),
        ),
        ERR_VENUE_NOT_FOUND,
    )
    # The second element of society_ids is the one that names no society.
    validate_error(
        api.create_audit_case(
            audit_case_payload(
                venue["id"],
                AUDIT_TRIGGER_ROUTINE,
                "2025-01-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
                [society["id"], UNUSED_UUID_THIRD],
            ),
            auditor_headers(),
        ),
        ERR_SOCIETY_NOT_FOUND,
    )
    validate_error(
        api.create_performance_report(
            performance_report_payload(NON_EXISTENT_UUID), admin_headers()
        ),
        ERR_LICENSE_NOT_FOUND,
    )

    assert_empty_list(api.list_rate_schedules(admin_headers()))
    assert_empty_list(api.list_applications(admin_headers()))
    assert_empty_list(api.list_audit_cases(admin_headers()))
    assert_empty_list(api.list_performance_reports(admin_headers()))
    # A refused application create never bumps the venue it named either.
    assert_version_unchanged(venue_row(api, venue["id"]), venue, "venue")
    assert venue_row(api, venue["id"])["audit_hold"] is False


def test_reject_request_shape_enum_and_negative_money(api):
    """A missing required field, an undeclared enum value, a negative money
    figure and a date-only instant are all request-shape failures, and none of
    them leaves a row behind.

    PRD §2.12: "**Request shape.** The body parses; every required field is
    present and non-null; every enum-typed field carries a declared value; every
    field whose name ends in `_cents` or `_bp` and every count field is a JSON
    integer of at least 0; every instant-valued field is an RFC 3339 UTC instant
    ending in `Z`; a disposition arrives with its mandatory companion reason; and
    a supplied `limit` lies within 1 to 100 — otherwise `ERR_INVALID_REQUEST`
    (422)."

    Design: Corner/validations/corner_validation_invalid_request_rejects_shape_enum_and_sign
    """
    society = given_society(api)

    missing_profile = bar_grill_venue_payload("Profileless Room")
    missing_profile.pop("music_use_profile")
    validate_error(
        api.create_venue(missing_profile, admin_headers()), ERR_INVALID_REQUEST
    )

    validate_error(
        api.create_venue(
            venue_payload("Arena Room", "ARENA", 120, 180, 200, "MIXED", 4, 4200000),
            admin_headers(),
        ),
        ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_venue(
            venue_payload("Negative Room", "BAR_GRILL", 120, 180, 200, "MIXED", 4, -1),
            admin_headers(),
        ),
        ERR_INVALID_REQUEST,
    )
    # A bare calendar date is not an RFC 3339 UTC instant ending in Z.
    validate_error(
        api.create_rate_schedule(
            rate_schedule_payload(society["id"], "BAR_GRILL", "2026-01-01"),
            admin_headers(),
        ),
        ERR_INVALID_REQUEST,
    )

    assert_empty_list(api.list_venues(admin_headers()))
    assert_empty_list(api.list_rate_schedules(admin_headers()))


def test_reject_zero_length_and_inverted_intervals(api):
    """A half-open interval must be non-empty in the strict sense, so a period
    that starts where it ends and a window whose bounds are the wrong way round
    are both refused; putting the same window's bounds in order is accepted.

    PRD §2.8: "An interval whose start equals or exceeds its end is rejected with
    `ERR_INVALID_INTERVAL` (HTTP 422)."

    Design: Corner/validations/corner_validation_interval_start_must_precede_end_rejected
    """
    world = given_licensed_venue(api, requested_term_start=TERM_START)
    licence = world["license"]
    venue_id = world["venue"]["id"]

    validate_error(
        api.create_performance_report(
            performance_report_payload(
                licence["id"], "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"
            ),
            venue_operator_headers(venue_id),
        ),
        ERR_INVALID_INTERVAL,
    )
    validate_error(
        api.create_coverage_window(
            licence["id"],
            coverage_window_payload(
                "2026-12-20T00:00:00Z",
                "2026-12-10T00:00:00Z",
                WINDOW_KIND_SEASONAL_EVENT_RIDER,
            ),
            admin_headers(),
        ),
        ERR_INVALID_INTERVAL,
    )
    validate_error(
        api.create_audit_case(
            audit_case_payload(
                venue_id,
                AUDIT_TRIGGER_ROUTINE,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                [world["society"]["id"]],
            ),
            auditor_headers(),
        ),
        ERR_INVALID_INTERVAL,
    )

    assert_empty_list(api.list_performance_reports(admin_headers()))
    assert_empty_list(api.list_audit_cases(admin_headers()))
    # Only the annual window activation created survives, and no case took hold.
    windows = windows_of_license(api, licence["id"])
    assert_count(len(windows), 1, "coverage window count")
    assert windows[0]["window_kind"] == WINDOW_KIND_ANNUAL_TERM
    assert venue_row(api, venue_id)["audit_hold"] is False

    # The very same bounds, in order, describe a legal ten-day rider.
    accepted = given_coverage_window(
        api,
        licence["id"],
        "2026-12-10T00:00:00Z",
        "2026-12-20T00:00:00Z",
        WINDOW_KIND_SEASONAL_EVENT_RIDER,
    )
    assert accepted["window_kind"] == WINDOW_KIND_SEASONAL_EVENT_RIDER
    assert accepted["status"] == WINDOW_STATUS_ACTIVE
    assert_count(accepted["covered_day_count"], 10, "covered_day_count")


def test_reject_overlapping_report_period(api):
    """A second reporting period on the same licence may not overlap a live one,
    whether it straddles the boundary or repeats it exactly, but a period that
    begins precisely where the first ends is accepted.

    PRD §3.8: "The period must not overlap the period of any other report on the
    same `license_id` whose `status` is `DRAFT`, `SUBMITTED` or `ACCEPTED`; a
    rejected period is excluded from that comparison and may therefore be
    re-reported."

    Design: Corner/validations/corner_validation_overlapping_report_period_rejected
    """
    world = given_licensed_venue(api, requested_term_start=TERM_START)
    licence = world["license"]
    venue_id = world["venue"]["id"]

    first = given_draft_report(
        api, licence["id"], venue_id, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
    )

    validate_error(
        api.create_performance_report(
            performance_report_payload(
                licence["id"], "2026-09-15T00:00:00Z", "2026-10-15T00:00:00Z"
            ),
            venue_operator_headers(venue_id),
        ),
        ERR_REPORT_PERIOD_OVERLAP,
    )
    validate_error(
        api.create_performance_report(
            performance_report_payload(
                licence["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
            ),
            venue_operator_headers(venue_id),
        ),
        ERR_REPORT_PERIOD_OVERLAP,
    )
    assert_version_unchanged(report_row(api, first["id"]), first, "performance report")

    # Exact adjacency is not an overlap under the half-open convention.
    adjacent = given_draft_report(
        api, licence["id"], venue_id, "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"
    )

    rows = read_rows(
        api.list_performance_reports(admin_headers(), {"license_id": licence["id"]}),
        expected_total=2,
    )
    assert ids_of(rows) == [first["id"], adjacent["id"]]
    for row in rows:
        assert row["status"] == REPORT_STATUS_DRAFT


def test_accept_rider_window_spanning_whole_term(api):
    """A seasonal rider may span the licence's entire annual term: it coexists
    with the annual-term window because the overlap rule looks only at windows of
    the same kind, and it is priced across all 365 covered days.

    PRD §3.6: "For a `SEASONAL_EVENT_RIDER` or a `FESTIVAL_RIDER`,
    `rider_fee_cents` is derived from the owning licence's `annual_fee_cents` as
    it stands **at the moment the rider is created**: multiply that
    `annual_fee_cents` by the window's `covered_day_count`, multiply by the
    seasonal peak factor of 13500 basis points, divide by the product of 365
    term-days and 10000, and round half up to whole cents — a **single** rounding
    step at the very end, with the day fraction and the peak factor combined
    inside one expression rather than rounded independently."

    Design: Corner/validations/corner_validation_rider_window_spanning_whole_term_accepted
    """
    world = given_licensed_venue(api, requested_term_start=TERM_START)
    licence = world["license"]
    venue_id = world["venue"]["id"]
    assert_money(
        licence["annual_fee_cents"], BAR_GRILL_ANNUAL_FEE_CENTS, "annual_fee_cents"
    )

    rider = given_coverage_window(
        api, licence["id"], TERM_START, TERM_END, WINDOW_KIND_SEASONAL_EVENT_RIDER
    )
    assert rider["window_kind"] == WINDOW_KIND_SEASONAL_EVENT_RIDER
    assert rider["status"] == WINDOW_STATUS_ACTIVE
    assert_count(rider["covered_day_count"], 365, "covered_day_count")
    assert_days_apart(rider["window_start"], rider["window_end"], 365, "rider window")
    assert_money(rider["rider_fee_cents"], 121523, "rider_fee_cents")

    windows = windows_of_license(api, licence["id"])
    assert_count(len(windows), 2, "coverage window count")
    assert sorted(w["window_kind"] for w in windows) == [
        WINDOW_KIND_ANNUAL_TERM,
        WINDOW_KIND_SEASONAL_EVENT_RIDER,
    ]
    for window in windows:
        assert window["status"] == WINDOW_STATUS_ACTIVE

    # The rider is billed on top of the annual fee, still inside the tolerance.
    assert_venue_ledger(venue_row(api, venue_id), 211540, 0, 0, 211540)
    assert_license_dimensions(
        license_row(api, licence["id"]), COVERAGE_ACTIVE, BILLING_INVOICED
    )


def test_reject_window_outside_licence_term(api):
    """A coverage window that pokes out beyond the licence's own half-open term at
    either end is refused, and the refusal bills nothing and leaves the annual
    window as the licence's only coverage.

    PRD §3.6: "The window must sit inside the licence's own half-open term and
    must not overlap an existing `ACTIVE` window of the same `license_id` *and the
    same* `window_kind`, with exact adjacency permitted; §2.12 gives the two
    rejection codes and their position in the ladder."

    Design: Corner/validations/corner_validation_window_outside_term_rejected
    """
    world = given_licensed_venue(api, requested_term_start=TERM_START)
    licence = world["license"]
    venue_id = world["venue"]["id"]
    before = license_row(api, licence["id"])

    # One day past term_end.
    validate_error(
        api.create_coverage_window(
            licence["id"],
            coverage_window_payload(
                "2027-07-01T00:00:00Z",
                "2027-08-02T00:00:00Z",
                WINDOW_KIND_SEASONAL_EVENT_RIDER,
            ),
            admin_headers(),
        ),
        ERR_WINDOW_OUTSIDE_TERM,
    )
    # Starting a month before term_start.
    validate_error(
        api.create_coverage_window(
            licence["id"],
            coverage_window_payload(
                "2026-07-01T00:00:00Z",
                "2026-08-15T00:00:00Z",
                WINDOW_KIND_SEASONAL_EVENT_RIDER,
            ),
            admin_headers(),
        ),
        ERR_WINDOW_OUTSIDE_TERM,
    )

    windows = windows_of_license(api, licence["id"])
    assert_count(len(windows), 1, "coverage window count")
    assert windows[0]["window_kind"] == WINDOW_KIND_ANNUAL_TERM
    assert_version_unchanged(license_row(api, licence["id"]), before, "license")

    assert_venue_ledger(
        venue_row(api, venue_id),
        BAR_GRILL_ANNUAL_FEE_CENTS,
        0,
        0,
        BAR_GRILL_ANNUAL_FEE_CENTS,
    )
    assessments = assessments_of_venue(api, venue_id)
    assert_count(len(assessments), 1, "assessment count")
    assert_assessment(
        assessments[0],
        ASSESSMENT_KIND_INITIAL,
        BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )
