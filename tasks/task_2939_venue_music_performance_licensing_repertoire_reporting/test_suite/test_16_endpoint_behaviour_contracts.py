"""
Endpoint behaviour contracts of the venue music licensing service.

This file pins what each endpoint actually does to the rows behind it: that a
survey revision advances the venue's revision counter and throws its exemption
verdict away, that re-running the exemption analysis re-derives the same verdict
while still counting as a write, that a nested coverage-window list is scoped to
the licence in its path, that a venue read projects the derived coverage posture
and the four ledger totals, that the setlist-entry listing narrows on the match
verdict and the coverage verdict independently, which licence and application
states the terminal exits may be reached from, and that moving the logical clock
is not itself a write.
"""

from test_helpers import (
    APPLICATION_STATUS_DRAFT,
    APPLICATION_STATUS_WITHDRAWN,
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_STATUS_VOIDED,
    BILLING_INVOICED,
    BILLING_WRITTEN_OFF,
    CLOCK_START_INSTANT,
    COVERAGE_ACTIVE,
    COVERAGE_EXPIRED,
    COVERAGE_PENDING_ACTIVATION,
    COVERAGE_SUSPENDED,
    COVERAGE_TERMINATED,
    ERR_APPLICATION_STATE_INVALID,
    ERR_LICENSE_NOT_FOUND,
    ERR_LICENSE_STATE_INVALID,
    EXEMPTION_EXEMPT,
    EXEMPTION_NOT_ANALYZED,
    POSTURE_PARTIALLY_COVERED,
    POSTURE_UNCOVERED,
    REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS,
    REPORT_STATUS_SUBMITTED,
    SHARE_BMI_BP,
    SUSPENSION_REASON_OPERATOR_REQUEST,
    TERM_LENGTH_DAYS,
    UNUSED_UUID,
    WINDOW_KIND_ANNUAL_TERM,
    WINDOW_KIND_SEASONAL_EVENT_RIDER,
    WINDOW_STATUS_ACTIVE,
    WINDOW_STATUS_VOIDED,
    activate,
    admin_headers,
    application_row,
    ascap_payload,
    assert_assessment,
    assert_count,
    assert_coverage,
    assert_days_apart,
    assert_empty_list,
    assert_instant_equals,
    assert_license_dimensions,
    assert_money,
    assert_pct,
    assert_venue_ledger,
    assert_version,
    assert_version_unchanged,
    assessments_of_license,
    bar_grill_venue_payload,
    bgm_survey_fields,
    find_row,
    get_success_data,
    given_active_license,
    given_approved_application,
    given_coverage_window,
    given_draft_application,
    given_draft_report,
    given_effective_schedule,
    given_licensed_venue,
    given_setlist,
    given_society,
    given_venue,
    given_work,
    ids_of,
    license_of_application,
    license_row,
    move_clock,
    read_rows,
    renew_payload,
    suspend_payload,
    terminate_payload,
    validate_error,
    validate_success,
    venue_operator_headers,
    venue_payload,
    venue_row,
    windows_of_license,
)

# Enum members of PRD §3.2's venue category list and §3.3's music use profiles
# that have no dedicated constant in the shared helpers.
_CATEGORY_BAR_GRILL = "BAR_GRILL"
_CATEGORY_HOTEL = "HOTEL"
_PROFILE_BACKGROUND_ONLY = "BACKGROUND_ONLY"

# Members of the setlist entry's society affiliation enum (PRD §3.8).
_AFFILIATION_BMI = "BMI"
_AFFILIATION_ASCAP = "ASCAP"
_AFFILIATION_UNAFFILIATED = "UNAFFILIATED"

# The verified annual fee a 4600 bp society charges the 180-occupancy bar and
# grill of the shared venue builder on a default rate schedule.
_BAR_GRILL_ANNUAL_FEE_CENTS = 90017

# A rider window that starts inside the term and runs over the new year.
_RIDER_START = "2026-12-20T00:00:00Z"
_RIDER_END = "2027-01-04T00:00:00Z"
_RIDER_DAY_COUNT = 15


def test_endpoint_venue_patch_bumps_version_and_clears_exemption_verdict(api):
    """A survey revision advances the venue's revision counter and throws away
    any background-music exemption verdict computed against the old survey.

    PRD §3.3: "The venue's `version` increments by 1 — which is what makes the
    venue the optimistic-concurrency parent of §2.7, since a survey revision
    silently invalidates any application create the client had prepared. And the
    exemption verdict is discarded: `bgm_exemption_status` returns to
    `NOT_ANALYZED` and `bgm_exemption_reason` returns to null, because a verdict
    computed against superseded floor-area or speaker data is worthless."

    Design: Corner/endpoints/corner_endpoint_venue_patch_bumps_version_and_resets_exemption
    """
    venue = given_venue(
        api,
        venue_payload(
            "Quiet Corner Grill",
            _CATEGORY_BAR_GRILL,
            40,
            0,
            60,
            _PROFILE_BACKGROUND_ONLY,
            0,
            0,
            **bgm_survey_fields(
                gross_square_feet=3000,
                speaker_count=4,
                max_speakers_per_room=2,
                uses_licensed_bgm_service=False,
            ),
        ),
    )
    assert venue["bgm_exemption_status"] == EXEMPTION_NOT_ANALYZED
    assert venue["bgm_exemption_reason"] is None

    analysed = validate_success(api.run_exemption_analysis(venue["id"], admin_headers()))
    assert analysed["bgm_exemption_status"] == EXEMPTION_EXEMPT
    assert analysed["bgm_exemption_reason"] == REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS
    assert_version(analysed, venue["version"] + 1, "venue after the analysis")

    revised = validate_success(
        api.update_venue(venue["id"], {"speaker_count": 5}, admin_headers())
    )
    assert_count(revised["speaker_count"], 5, "speaker_count after the revision")
    assert_version(revised, analysed["version"] + 1, "venue after the revision")
    assert revised["bgm_exemption_status"] == EXEMPTION_NOT_ANALYZED
    assert revised["bgm_exemption_reason"] is None
    # `legal_name` is outside the revisable set, so it survives untouched.
    assert revised["legal_name"] == venue["legal_name"]

    reread = venue_row(api, venue["id"])
    assert_version(reread, analysed["version"] + 1, "re-read venue")
    assert reread["bgm_exemption_status"] == EXEMPTION_NOT_ANALYZED
    assert reread["bgm_exemption_reason"] is None

    # Re-running the analysis against the revised survey re-derives the verdict.
    reanalysed = validate_success(
        api.run_exemption_analysis(venue["id"], admin_headers())
    )
    assert reanalysed["bgm_exemption_status"] == EXEMPTION_EXEMPT
    assert reanalysed["bgm_exemption_reason"] == REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS
    assert_version(reanalysed, revised["version"] + 1, "venue after the re-analysis")


def test_endpoint_exemption_analysis_rerun_repeats_verdict_and_bumps_version(api):
    """Re-running the exemption analysis over unchanged survey data re-derives
    exactly the same verdict, yet each run is itself a write on the venue.

    PRD §3.3: "It writes `bgm_exemption_status` — one of `NOT_ANALYZED`,
    `EXEMPT`, `NOT_EXEMPT` or `INCONCLUSIVE` — together with
    `bgm_exemption_reason`, and increments the venue's `version`."

    Design: Corner/endpoints/corner_endpoint_exemption_analysis_rerun_is_stable_but_bumps_version
    """
    # 2000 gross square feet is exactly the limit for a non-food-service
    # category, and six speakers with four in a room are exactly the two
    # speaker limits, so every comparison lands on its inclusive boundary.
    venue = given_venue(
        api,
        venue_payload(
            "Harbour Lights Hotel",
            _CATEGORY_HOTEL,
            150,
            0,
            180,
            _PROFILE_BACKGROUND_ONLY,
            0,
            0,
            **bgm_survey_fields(
                gross_square_feet=2000,
                speaker_count=6,
                max_speakers_per_room=4,
                uses_licensed_bgm_service=False,
            ),
        ),
    )

    first = validate_success(api.run_exemption_analysis(venue["id"], admin_headers()))
    assert first["bgm_exemption_status"] == EXEMPTION_EXEMPT
    assert first["bgm_exemption_reason"] == REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS
    assert_version(first, venue["version"] + 1, "venue after the first analysis")

    second = validate_success(api.run_exemption_analysis(venue["id"], admin_headers()))
    assert second["bgm_exemption_status"] == EXEMPTION_EXEMPT
    assert second["bgm_exemption_reason"] == REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS
    assert_version(second, first["version"] + 1, "venue after the second analysis")

    third = validate_success(api.run_exemption_analysis(venue["id"], admin_headers()))
    assert third["bgm_exemption_status"] == EXEMPTION_EXEMPT
    assert third["bgm_exemption_reason"] == REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS
    assert_version(third, venue["version"] + 3, "venue after the third analysis")

    reread = venue_row(api, venue["id"])
    assert reread["bgm_exemption_status"] == EXEMPTION_EXEMPT
    assert reread["bgm_exemption_reason"] == REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS
    assert_version(reread, venue["version"] + 3, "re-read venue")
    # The survey inputs the verdict was computed from are untouched by a rerun.
    assert_count(reread["gross_square_feet"], 2000, "gross_square_feet")
    assert_count(reread["speaker_count"], 6, "speaker_count")
    assert_count(reread["max_speakers_per_room"], 4, "max_speakers_per_room")


def test_endpoint_nested_coverage_window_list_is_scoped_to_its_licence(api):
    """The coverage-window list nested under one licence returns that licence's
    windows only, while the cross-licence list sees every window; an unknown
    licence in the path is a not-found rather than an empty page.

    PRD §3.6: "Windows can be listed for one licence, and also listed across
    licences narrowing on `license_id`, `window_kind` and `status`; a single
    window read exposes its computed `rider_fee_cents`."

    Design: Corner/endpoints/corner_endpoint_nested_coverage_window_list_scoped_to_its_license
    """
    bmi = given_society(api)
    ascap = given_society(api, ascap_payload())
    given_effective_schedule(api, bmi["id"], _CATEGORY_BAR_GRILL)
    given_effective_schedule(api, ascap["id"], _CATEGORY_BAR_GRILL)
    venue = given_venue(api)

    first_licence = given_active_license(api, venue, bmi["id"], CLOCK_START_INSTANT)
    # Activation moved the venue on, so the second filing needs a fresh read.
    second_licence = given_active_license(
        api, venue_row(api, venue["id"]), ascap["id"], CLOCK_START_INSTANT
    )
    rider = given_coverage_window(
        api,
        first_licence["id"],
        _RIDER_START,
        _RIDER_END,
        WINDOW_KIND_SEASONAL_EVENT_RIDER,
    )

    first_windows = read_rows(
        api.list_license_coverage_windows(first_licence["id"], admin_headers()),
        expected_total=2,
    )
    assert all(w["license_id"] == first_licence["id"] for w in first_windows), (
        "the nested list must not leak another licence's windows"
    )
    annual = find_row(first_windows, window_kind=WINDOW_KIND_ANNUAL_TERM)
    assert_count(annual["covered_day_count"], TERM_LENGTH_DAYS, "annual covered_day_count")
    assert_money(annual["rider_fee_cents"], 0, "annual rider_fee_cents")
    assert annual["status"] == WINDOW_STATUS_ACTIVE
    assert_instant_equals(
        annual["window_start"], first_licence["term_start"], "annual window_start"
    )
    assert_instant_equals(
        annual["window_end"], first_licence["term_end"], "annual window_end"
    )
    assert_days_apart(
        annual["window_start"], annual["window_end"], TERM_LENGTH_DAYS, "annual window"
    )
    listed_rider = find_row(first_windows, window_kind=WINDOW_KIND_SEASONAL_EVENT_RIDER)
    assert listed_rider["id"] == rider["id"]
    assert_count(
        listed_rider["covered_day_count"], _RIDER_DAY_COUNT, "rider covered_day_count"
    )

    second_windows = read_rows(
        api.list_license_coverage_windows(second_licence["id"], admin_headers()),
        expected_total=1,
    )
    assert second_windows[0]["license_id"] == second_licence["id"]
    assert second_windows[0]["window_kind"] == WINDOW_KIND_ANNUAL_TERM
    assert rider["id"] not in ids_of(second_windows)

    # PRD §3.6 names `license_id`, `window_kind` and `status` as narrowing
    # filters on the cross-licence listing only — "Windows can be listed for one
    # licence, and also listed across licences narrowing on `license_id`,
    # `window_kind` and `status`" — so the filters are exercised there and not
    # against the nested route, which the PRD gives no filters at all.
    all_windows = read_rows(api.list_coverage_windows(admin_headers()), expected_total=3)
    assert set(ids_of(all_windows)) == {
        annual["id"],
        rider["id"],
        second_windows[0]["id"],
    }
    filtered = read_rows(
        api.list_coverage_windows(admin_headers(), {"license_id": first_licence["id"]}),
        expected_total=2,
    )
    assert set(ids_of(filtered)) == {annual["id"], rider["id"]}
    by_kind = read_rows(
        api.list_coverage_windows(
            admin_headers(),
            {
                "license_id": first_licence["id"],
                "window_kind": WINDOW_KIND_ANNUAL_TERM,
            },
        ),
        expected_total=1,
    )
    assert by_kind[0]["id"] == annual["id"]

    validate_error(
        api.list_license_coverage_windows(UNUSED_UUID, admin_headers()),
        ERR_LICENSE_NOT_FOUND,
    )


def test_endpoint_venue_read_projects_posture_and_ledger(api):
    """A single venue read exposes the derived coverage roll-ups and the four
    money totals, and the listing narrows on the derived posture.

    PRD §3.3: "Venues can be listed with the results, and the listing narrows on
    `venue_category`, on `coverage_posture`, on `audit_hold` and on `status`; a
    single venue read exposes `covered_share_bp`, `coverage_posture`,
    `gap_risk_score`, `audit_hold` and the four ledger totals."

    Design: Corner/endpoints/corner_endpoint_venue_read_returns_derived_posture_and_ledger
    """
    setup = given_licensed_venue(api, requested_term_start=CLOCK_START_INSTANT)
    venue = setup["venue"]

    assert_coverage(venue, SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)
    assert_venue_ledger(
        venue, _BAR_GRILL_ANNUAL_FEE_CENTS, 0, 0, _BAR_GRILL_ANNUAL_FEE_CENTS
    )
    assert_pct(venue["gap_risk_score"], 0.00, "gap_risk_score")
    assert venue["audit_hold"] is False

    # The venue's own operator reads the same derived projection.
    own_read = validate_success(
        api.get_venue(venue["id"], venue_operator_headers(venue["id"]))
    )
    assert_coverage(own_read, SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)
    assert_venue_ledger(
        own_read, _BAR_GRILL_ANNUAL_FEE_CENTS, 0, 0, _BAR_GRILL_ANNUAL_FEE_CENTS
    )
    assert own_read["audit_hold"] is False

    matched = read_rows(
        api.list_venues(
            admin_headers(), {"coverage_posture": POSTURE_PARTIALLY_COVERED}
        ),
        expected_total=1,
    )
    assert matched[0]["id"] == venue["id"]
    assert_coverage(matched[0], SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)
    assert_money(
        matched[0]["outstanding_balance_cents"],
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        "listed outstanding_balance_cents",
    )
    assert_empty_list(
        api.list_venues(admin_headers(), {"coverage_posture": POSTURE_UNCOVERED})
    )


def test_endpoint_setlist_entry_list_filters_match_and_coverage_independently(api):
    """The setlist-entry listing narrows on the match verdict, on the matched
    work and on the coverage verdict, and those two verdicts are independent:
    a registered work whose society does not license this venue is matched but
    not covered.

    PRD §3.8: "Setlist entries can be listed for one report and also across
    reports, narrowing on `performance_report_id`, on `matched_work_id`, on
    `is_matched` and on `is_covered`; a single entry read exposes its match and
    coverage verdict."

    Design: Corner/endpoints/corner_endpoint_setlist_entry_list_filters_on_match_and_coverage
    """
    bmi = given_society(api)
    ascap = given_society(api, ascap_payload())
    given_effective_schedule(api, bmi["id"], _CATEGORY_BAR_GRILL)
    venue = given_venue(api)
    licence = given_active_license(api, venue, bmi["id"], CLOCK_START_INSTANT)

    given_work(api, bmi["id"], "Blue Horizon", "A. Rivera")
    unlicensed_work = given_work(api, ascap["id"], "Cedar Waltz", "B. Stone")

    report = given_draft_report(
        api,
        licence["id"],
        venue["id"],
        CLOCK_START_INSTANT,
        "2026-09-01T00:00:00Z",
    )
    covered_entry, matched_only_entry, unmatched_entry = given_setlist(
        api,
        report["id"],
        venue["id"],
        [
            {
                "title": "Blue Horizon",
                "writer": "A. Rivera",
                "affiliation": _AFFILIATION_BMI,
                "when": "2026-08-10T20:00:00Z",
                "seconds": 240,
            },
            {
                "title": "Cedar Waltz",
                "writer": "B. Stone",
                "affiliation": _AFFILIATION_ASCAP,
                "when": "2026-08-10T20:30:00Z",
                "seconds": 240,
            },
            {
                "title": "Unlisted Jam",
                "writer": "C. Vale",
                "affiliation": _AFFILIATION_UNAFFILIATED,
                "when": "2026-08-10T21:00:00Z",
                "seconds": 240,
            },
        ],
    )

    submitted = validate_success(
        api.submit_performance_report(report["id"], venue_operator_headers(venue["id"]))
    )
    assert submitted["status"] == REPORT_STATUS_SUBMITTED
    assert_count(submitted["reported_entry_count"], 3, "reported_entry_count")
    assert_count(submitted["matched_entry_count"], 2, "matched_entry_count")
    assert_count(submitted["uncovered_entry_count"], 2, "uncovered_entry_count")

    matched_rows = read_rows(
        api.list_setlist_entries(
            admin_headers(),
            {"performance_report_id": report["id"], "is_matched": "true"},
        ),
        expected_total=2,
    )
    assert set(ids_of(matched_rows)) == {
        covered_entry["id"],
        matched_only_entry["id"],
    }

    covered_rows = read_rows(
        api.list_setlist_entries(
            admin_headers(),
            {"performance_report_id": report["id"], "is_covered": "true"},
        ),
        expected_total=1,
    )
    assert covered_rows[0]["id"] == covered_entry["id"]
    assert covered_rows[0]["is_matched"] is True
    assert covered_rows[0]["is_covered"] is True

    by_work = read_rows(
        api.list_setlist_entries(
            admin_headers(), {"matched_work_id": unlicensed_work["id"]}
        ),
        expected_total=1,
    )
    assert by_work[0]["id"] == matched_only_entry["id"]
    assert by_work[0]["is_matched"] is True
    assert by_work[0]["is_covered"] is False

    unmatched_rows = read_rows(
        api.list_setlist_entries(
            admin_headers(),
            {"performance_report_id": report["id"], "is_matched": "false"},
        ),
        expected_total=1,
    )
    assert unmatched_rows[0]["id"] == unmatched_entry["id"]
    assert unmatched_rows[0]["matched_work_id"] is None

    uncovered_rows = read_rows(
        api.list_setlist_entries(
            admin_headers(),
            {"performance_report_id": report["id"], "is_covered": "false"},
        ),
        expected_total=2,
    )
    assert set(ids_of(uncovered_rows)) == {
        matched_only_entry["id"],
        unmatched_entry["id"],
    }

    single = validate_success(api.get_setlist_entry(matched_only_entry["id"], admin_headers()))
    assert single["is_matched"] is True
    assert single["matched_work_id"] == unlicensed_work["id"]
    assert single["is_covered"] is False

    assert_empty_list(
        api.list_setlist_entries(
            admin_headers(), {"performance_report_id": UNUSED_UUID}
        )
    )


def test_endpoint_terminate_departs_from_suspended_but_not_pending_activation(api):
    """Termination is reachable from a suspended licence and writes off its
    unpaid money, but a licence still awaiting activation cannot be terminated
    and the refusal writes nothing.

    PRD §3.7: "Termination is the terminal exit on the coverage dimension,
    available from `ACTIVE` and from `SUSPENDED`, and it carries a compensating
    switch."

    Design: Corner/endpoints/corner_endpoint_terminate_allowed_from_suspended_not_from_pending
    """
    setup = given_licensed_venue(api, requested_term_start=CLOCK_START_INSTANT)
    venue = setup["created_venue"]
    licence = setup["license"]

    suspended = validate_success(
        api.suspend_license(
            licence["id"],
            suspend_payload(SUSPENSION_REASON_OPERATOR_REQUEST),
            admin_headers(),
        )
    )
    assert_license_dimensions(suspended, COVERAGE_SUSPENDED, BILLING_INVOICED)

    terminated = validate_success(
        api.terminate_license(
            licence["id"],
            terminate_payload(void_unpaid_assessments=True),
            admin_headers(),
        )
    )
    assert_license_dimensions(terminated, COVERAGE_TERMINATED, BILLING_WRITTEN_OFF)
    assert_version(terminated, suspended["version"] + 1, "terminated licence")

    windows = windows_of_license(api, licence["id"])
    assert windows, "the activated licence must still expose its annual window"
    assert all(w["status"] == WINDOW_STATUS_VOIDED for w in windows), (
        "every window of a terminated licence must be VOIDED"
    )

    assessments = assessments_of_license(api, licence["id"])
    assert len(assessments) == 1, "activation raised exactly one assessment"
    assert_assessment(
        assessments[0],
        ASSESSMENT_KIND_INITIAL,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_VOIDED,
        paid=0,
    )

    after_termination = venue_row(api, venue["id"])
    assert_venue_ledger(
        after_termination,
        0,
        0,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
    )
    assert_coverage(after_termination, 0, POSTURE_UNCOVERED)

    # A licence that has never been activated is not a legal departure point.
    other_venue = given_venue(api, bar_grill_venue_payload("Second Street Tavern"))
    application = given_approved_application(
        api, other_venue, setup["society"]["id"], CLOCK_START_INSTANT
    )
    pending = license_of_application(api, application["id"])
    assert pending["coverage_status"] == COVERAGE_PENDING_ACTIVATION

    validate_error(
        api.terminate_license(pending["id"], terminate_payload(), admin_headers()),
        ERR_LICENSE_STATE_INVALID,
    )
    assert_version_unchanged(
        license_row(api, pending["id"]), pending, "licence awaiting activation"
    )


def test_endpoint_withdraw_moves_a_draft_application_to_terminal_withdrawn(api):
    """Withdrawal takes a draft application to its terminal withdrawn state with
    one revision increment, mints no licence, and cannot be repeated once the
    application has reached a terminal state.

    PRD §3.4: "An application may be withdrawn by its operator (or by a
    `LicensingAdmin`) from `DRAFT`, from `SUBMITTED` or from
    `RETURNED_FOR_REVISION`, moving it to the terminal `WITHDRAWN` state with a
    `version` increment."

    Design: Corner/endpoints/corner_endpoint_withdraw_only_departs_from_draft
    """
    society = given_society(api)
    given_effective_schedule(api, society["id"], _CATEGORY_BAR_GRILL)
    venue = given_venue(api)

    draft = given_draft_application(api, venue, society["id"], CLOCK_START_INSTANT)
    assert draft["status"] == APPLICATION_STATUS_DRAFT

    withdrawn = validate_success(
        api.withdraw_application(draft["id"], venue_operator_headers(venue["id"]))
    )
    assert withdrawn["status"] == APPLICATION_STATUS_WITHDRAWN
    assert_version(withdrawn, draft["version"] + 1, "withdrawn application")

    # `WITHDRAWN` is terminal, so the same call a second time is refused and
    # leaves the row exactly as the first withdrawal left it.
    validate_error(
        api.withdraw_application(draft["id"], venue_operator_headers(venue["id"])),
        ERR_APPLICATION_STATE_INVALID,
    )
    assert_version_unchanged(
        application_row(api, draft["id"]), withdrawn, "withdrawn application"
    )

    # Withdrawal is not an approval: no licence was ever minted for this venue.
    assert_empty_list(api.list_licenses(admin_headers(), {"venue_id": venue["id"]}))
    listed = read_rows(
        api.list_applications(admin_headers(), {"venue_id": venue["id"]}),
        expected_total=1,
    )
    assert listed[0]["id"] == draft["id"]
    assert listed[0]["status"] == APPLICATION_STATUS_WITHDRAWN

    # An approved application is terminal too, so it is no departure point.
    other_venue = given_venue(api, bar_grill_venue_payload("Riverside Tap"))
    approved = given_approved_application(
        api, other_venue, society["id"], CLOCK_START_INSTANT
    )
    validate_error(
        api.withdraw_application(
            approved["id"], venue_operator_headers(other_venue["id"])
        ),
        ERR_APPLICATION_STATE_INVALID,
    )
    assert_version_unchanged(
        application_row(api, approved["id"]), approved, "approved application"
    )


def test_endpoint_clock_advance_writes_no_rows(api):
    """Advancing the logical clock past a licence's term end leaves every row
    exactly as it was; only a business call can retire the term.

    PRD §2.4: "Moving the clock writes no row and mutates no state on its own: a
    licence whose term has elapsed does not become `EXPIRED` merely because the
    clock advanced past `term_end`, and a schedule whose `effective_from` has
    passed does not become `EFFECTIVE` merely because the clock advanced past
    it."

    Design: Corner/endpoints/corner_endpoint_clock_advance_writes_no_rows
    """
    setup = given_licensed_venue(api, requested_term_start=CLOCK_START_INSTANT)
    licence = setup["license"]
    venue = setup["venue"]

    before_licence = license_row(api, licence["id"])
    before_windows = windows_of_license(api, licence["id"])
    assert before_licence["coverage_status"] == COVERAGE_ACTIVE

    move_clock(api, "2027-09-01T00:00:00Z")

    after_licence = license_row(api, licence["id"])
    assert after_licence["coverage_status"] == COVERAGE_ACTIVE, (
        "an elapsed term does not expire itself when the clock moves"
    )
    assert_version_unchanged(after_licence, before_licence, "licence")

    after_venue = venue_row(api, venue["id"])
    assert_version_unchanged(after_venue, venue, "venue")
    assert_coverage(after_venue, SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)
    assert_venue_ledger(
        after_venue, _BAR_GRILL_ANNUAL_FEE_CENTS, 0, 0, _BAR_GRILL_ANNUAL_FEE_CENTS
    )

    after_windows = windows_of_license(api, licence["id"])
    assert len(after_windows) == len(before_windows), (
        "the clock move must not create or remove a coverage window"
    )
    for after_window, before_window in zip(after_windows, before_windows):
        assert after_window["status"] == WINDOW_STATUS_ACTIVE
        assert_version_unchanged(after_window, before_window, "coverage window")

    assert len(assessments_of_license(api, licence["id"])) == 1, (
        "the clock move must not raise a fee assessment"
    )
    read_rows(
        api.list_licenses(admin_headers(), {"venue_id": venue["id"]}),
        expected_total=1,
    )

    # The corresponding business call is what finally retires the term.
    successor = get_success_data(
        api.renew_license(
            licence["id"],
            renew_payload(
                after_licence["term_end"],
                expected_license_version=after_licence["version"],
            ),
            admin_headers(),
        )
    )
    assert successor["renewal_of_license_id"] == licence["id"]
    assert successor["coverage_status"] == COVERAGE_PENDING_ACTIVATION
    assert_instant_equals(
        successor["term_start"], after_licence["term_end"], "successor term_start"
    )
    activate(api, successor["id"])
    assert license_row(api, licence["id"])["coverage_status"] == COVERAGE_EXPIRED
