"""
Optimistic concurrency guards and immediately derived reads.

Two guards protect the two places where a client's stale view of a parent row
would otherwise change the outcome silently: the venue revision a filing is
prepared against, and the licence revision a renewal is quoted against. Both
refuse with a precondition failure and leave the parent exactly as it was. The
same immediacy runs the other way on the read side: the delinquency tolerance is
re-evaluated on the way back down as soon as a payment lands, and an activation's
response already carries every field the activation derived.
"""

from test_helpers import (
    APPLICATION_STATUS_DRAFT,
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_STATUS_ISSUED,
    BILLING_DELINQUENT,
    BILLING_INVOICED,
    BILLING_UNBILLED,
    CLOCK_START_INSTANT,
    COVERAGE_ACTIVE,
    COVERAGE_PENDING_ACTIVATION,
    DELINQUENCY_TOLERANCE_CENTS,
    ERR_STALE_LICENSE_VERSION,
    ERR_STALE_VENUE_VERSION,
    POSTURE_PARTIALLY_COVERED,
    SHARE_BMI_BP,
    TERM_LENGTH_DAYS,
    WINDOW_KIND_ANNUAL_TERM,
    WINDOW_STATUS_ACTIVE,
    admin_headers,
    application_row,
    assert_assessment,
    assert_count,
    assert_coverage,
    assert_days_apart,
    assert_empty_list,
    assert_instant_equals,
    assert_license_dimensions,
    assert_money,
    assert_venue_ledger,
    assert_version,
    assert_version_unchanged,
    assessments_of_license,
    get_success_data,
    given_active_license,
    given_approved_application,
    given_effective_schedule,
    given_licensed_venue,
    given_society,
    given_venue,
    license_of_application,
    license_row,
    matching_application_payload,
    mid_concert_hall_venue_payload,
    payment_payload,
    read_rows,
    renew_payload,
    validate_error,
    validate_success,
    venue_operator_headers,
    venue_row,
    windows_of_license,
)

# Members of PRD §3.2's venue category enum, which has no dedicated constant in
# the shared helpers.
_CATEGORY_BAR_GRILL = "BAR_GRILL"
_CATEGORY_CONCERT_HALL = "CONCERT_HALL"

# Verified annual fees on a default rate schedule for a 4600 bp society: the
# 180-occupancy bar and grill, and the 800-occupancy concert hall whose fee is
# large enough to put the venue over the delinquency tolerance on its own.
_BAR_GRILL_ANNUAL_FEE_CENTS = 90017
_CONCERT_HALL_ANNUAL_FEE_CENTS = 463761


def test_layer_stale_venue_version_blocks_application_filing(api):
    """A filing prepared against a superseded venue survey is refused and writes
    nothing; only a client that has re-read the venue can file, and a revision
    made afterwards cannot be superseded by the stale copy either.

    PRD §2.7: "A request to `POST /licensing/license-applications` must carry
    `expected_venue_version` as a required, non-optional body field, holding the
    client's last observed `version` of the `Venue` named by `venue_id`. If that
    value does not equal the venue's current `version`, the create is rejected
    with `ERR_STALE_VENUE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_venue_version_rejected
    """
    society = given_society(api)
    given_effective_schedule(api, society["id"], _CATEGORY_BAR_GRILL)
    venue = given_venue(api)
    operator = venue_operator_headers(venue["id"])

    # The client's copy of the venue is made stale by a survey revision.
    revised = validate_success(
        api.update_venue(
            venue["id"], {"annual_cover_revenue_cents": 5000000}, admin_headers()
        )
    )
    assert_version(revised, venue["version"] + 1, "revised venue")

    stale_filing = matching_application_payload(
        venue, society["id"], CLOCK_START_INSTANT
    )
    assert_count(
        stale_filing["expected_venue_version"], venue["version"], "expected_venue_version"
    )
    validate_error(
        api.create_application(stale_filing, operator), ERR_STALE_VENUE_VERSION
    )
    assert_empty_list(
        api.list_applications(admin_headers(), {"venue_id": venue["id"]})
    )
    assert_version_unchanged(venue_row(api, venue["id"]), revised, "venue")

    # A revision the client has not seen yet is just as wrong as one it missed.
    ahead_filing = matching_application_payload(
        revised,
        society["id"],
        CLOCK_START_INSTANT,
        expected_venue_version=revised["version"] + 1,
    )
    validate_error(
        api.create_application(ahead_filing, operator), ERR_STALE_VENUE_VERSION
    )
    assert_empty_list(
        api.list_applications(admin_headers(), {"venue_id": venue["id"]})
    )
    assert_version_unchanged(venue_row(api, venue["id"]), revised, "venue")

    # Re-reading the venue first is what makes the same filing land.
    fresh_filing = matching_application_payload(
        revised, society["id"], CLOCK_START_INSTANT
    )
    application = get_success_data(api.create_application(fresh_filing, operator))
    assert application["status"] == APPLICATION_STATUS_DRAFT
    assert application["venue_id"] == venue["id"]
    read_rows(
        api.list_applications(admin_headers(), {"venue_id": venue["id"]}),
        expected_total=1,
    )
    # PRD §3.4: "Filing has two side effects beyond creating the row. The named
    # venue's `version` increments by 1." — so the accepted filing above moved
    # the very counter the guard reads, and the client's copy is stale again the
    # instant its own filing lands.
    filed_against = venue_row(api, venue["id"])
    assert_version(filed_against, revised["version"] + 1, "venue after the filing")

    # The guard is what stops a stale client from silently superseding the
    # application it never saw: the survey moves again, so the prepared second
    # filing is refused and the first application stays in DRAFT.
    revised_again = validate_success(
        api.update_venue(
            venue["id"], {"weekly_live_performance_nights": 5}, admin_headers()
        )
    )
    assert_version(
        revised_again, filed_against["version"] + 1, "twice-revised venue"
    )
    validate_error(
        api.create_application(fresh_filing, operator), ERR_STALE_VENUE_VERSION
    )
    surviving = application_row(api, application["id"])
    assert surviving["status"] == APPLICATION_STATUS_DRAFT
    assert_version_unchanged(surviving, application, "first application")
    read_rows(
        api.list_applications(admin_headers(), {"venue_id": venue["id"]}),
        expected_total=1,
    )


def test_layer_stale_license_version_blocks_renewal(api):
    """A renewal quoted against a superseded licence revision is refused, mints
    no successor and leaves the predecessor untouched; the guard bites again once
    the successful renewal has advanced the predecessor.

    PRD §2.7: "If that value does not equal the predecessor licence's current
    `version`, the renewal is rejected with `ERR_STALE_LICENSE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_license_version_rejected
    """
    setup = given_licensed_venue(api, requested_term_start=CLOCK_START_INSTANT)
    licence = setup["license"]
    term_end = licence["term_end"]

    validate_error(
        api.renew_license(
            licence["id"],
            renew_payload(term_end, expected_license_version=licence["version"] - 1),
            admin_headers(),
        ),
        ERR_STALE_LICENSE_VERSION,
    )
    after_first_refusal = license_row(api, licence["id"])
    assert_version_unchanged(after_first_refusal, licence, "licence")
    assert after_first_refusal["renewal_issued_at"] is None
    assert_empty_list(
        api.list_licenses(
            admin_headers(), {"renewal_of_license_id": licence["id"]}
        )
    )

    validate_error(
        api.renew_license(
            licence["id"],
            renew_payload(term_end, expected_license_version=licence["version"] + 1),
            admin_headers(),
        ),
        ERR_STALE_LICENSE_VERSION,
    )
    after_second_refusal = license_row(api, licence["id"])
    assert_version_unchanged(after_second_refusal, licence, "licence")
    assert after_second_refusal["renewal_issued_at"] is None
    assert_empty_list(
        api.list_licenses(
            admin_headers(), {"renewal_of_license_id": licence["id"]}
        )
    )

    # The current revision is accepted, and issuing the successor advances the
    # predecessor — which makes the client's own value stale in its turn.
    successor = get_success_data(
        api.renew_license(
            licence["id"],
            renew_payload(term_end, expected_license_version=licence["version"]),
            admin_headers(),
        )
    )
    assert successor["renewal_of_license_id"] == licence["id"]
    assert_license_dimensions(successor, COVERAGE_PENDING_ACTIVATION, BILLING_UNBILLED)
    assert_instant_equals(successor["term_start"], term_end, "successor term_start")
    assert_days_apart(
        successor["term_start"], successor["term_end"], TERM_LENGTH_DAYS, "successor term"
    )

    renewed_predecessor = license_row(api, licence["id"])
    assert_version(renewed_predecessor, licence["version"] + 1, "predecessor licence")
    assert renewed_predecessor["renewal_issued_at"] is not None
    read_rows(
        api.list_licenses(admin_headers(), {"renewal_of_license_id": licence["id"]}),
        expected_total=1,
    )

    validate_error(
        api.renew_license(
            licence["id"],
            renew_payload(term_end, expected_license_version=licence["version"]),
            admin_headers(),
        ),
        ERR_STALE_LICENSE_VERSION,
    )
    assert_version_unchanged(
        license_row(api, licence["id"]), renewed_predecessor, "predecessor licence"
    )
    read_rows(
        api.list_licenses(admin_headers(), {"renewal_of_license_id": licence["id"]}),
        expected_total=1,
    )


def test_layer_delinquency_threshold_is_inclusive_on_the_way_back(api):
    """Coming back down, the delinquency tolerance is inclusive: an outstanding
    balance of exactly 250000 cents clears the delinquency, while one cent more
    does not.

    PRD §2.9: "A venue is treated as **delinquent** when
    `outstanding_balance_cents` is strictly greater than a delinquency tolerance
    of 250000 cents — that is, when it owes more than two thousand five hundred
    dollars; owing exactly 250000 cents is *not* delinquent."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_delinquency_threshold_is_inclusive_on_the_way_back
    """
    society = given_society(api)
    given_effective_schedule(api, society["id"], _CATEGORY_CONCERT_HALL)
    venue = given_venue(api, mid_concert_hall_venue_payload())
    licence = given_active_license(
        api, venue, society["id"], CLOCK_START_INSTANT
    )

    # The single annual fee is on its own larger than the tolerance.
    assert_license_dimensions(
        license_row(api, licence["id"]), COVERAGE_ACTIVE, BILLING_DELINQUENT
    )
    after_activation = venue_row(api, venue["id"])
    assert_venue_ledger(
        after_activation,
        _CONCERT_HALL_ANNUAL_FEE_CENTS,
        0,
        0,
        _CONCERT_HALL_ANNUAL_FEE_CENTS,
    )

    assessment = assessments_of_license(api, licence["id"])[0]
    one_cent_above = DELINQUENCY_TOLERANCE_CENTS + 1
    part_payment = _CONCERT_HALL_ANNUAL_FEE_CENTS - one_cent_above

    # One cent above the tolerance is still delinquent.
    paid_once = get_success_data(
        api.pay_assessment(
            assessment["id"], payment_payload(part_payment), admin_headers()
        )
    )
    assert_assessment(
        paid_once,
        ASSESSMENT_KIND_INITIAL,
        _CONCERT_HALL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=part_payment,
    )
    at_one_cent_above = venue_row(api, venue["id"])
    assert_venue_ledger(
        at_one_cent_above,
        one_cent_above,
        part_payment,
        0,
        _CONCERT_HALL_ANNUAL_FEE_CENTS,
    )
    assert_license_dimensions(
        license_row(api, licence["id"]), COVERAGE_ACTIVE, BILLING_DELINQUENT
    )

    # One more cent lands exactly on the tolerance, which is inside it.
    paid_twice = get_success_data(
        api.pay_assessment(assessment["id"], payment_payload(1), admin_headers())
    )
    assert_assessment(
        paid_twice,
        ASSESSMENT_KIND_INITIAL,
        _CONCERT_HALL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=part_payment + 1,
    )
    at_tolerance = venue_row(api, venue["id"])
    assert_money(
        at_tolerance["outstanding_balance_cents"],
        DELINQUENCY_TOLERANCE_CENTS,
        "outstanding_balance_cents at the tolerance",
    )
    assert_venue_ledger(
        at_tolerance,
        DELINQUENCY_TOLERANCE_CENTS,
        part_payment + 1,
        0,
        _CONCERT_HALL_ANNUAL_FEE_CENTS,
    )
    assert_license_dimensions(
        license_row(api, licence["id"]), COVERAGE_ACTIVE, BILLING_INVOICED
    )


def test_consistency_activation_response_carries_every_derived_field(api):
    """Activation's own response already carries the re-rated fee and both state
    dimensions, and the rows it recomputed — the venue's coverage and ledger, the
    society's licensed count, the annual window and the assessment — are readable
    immediately afterwards.

    PRD §3.6: "Fourth, it recomputes the venue: `lifetime_assessed_cents` and
    `outstanding_balance_cents` each increase by the created assessment's
    `amount_cents`, `covered_share_bp` and `coverage_posture` are recomputed per
    §2.10, and `Venue.version` increments by 1."

    Design: Corner/consistency_model/corner_consistency_immediate_derived_fields_in_the_same_response
    """
    society = given_society(api)
    given_effective_schedule(api, society["id"], _CATEGORY_BAR_GRILL)
    venue = given_venue(api)
    application = given_approved_application(
        api, venue, society["id"], CLOCK_START_INSTANT
    )
    minted = license_of_application(api, application["id"])
    assert_license_dimensions(minted, COVERAGE_PENDING_ACTIVATION, BILLING_UNBILLED)

    activated = validate_success(api.activate_license(minted["id"], admin_headers()))
    assert_license_dimensions(activated, COVERAGE_ACTIVE, BILLING_INVOICED)
    assert_money(
        activated["annual_fee_cents"], _BAR_GRILL_ANNUAL_FEE_CENTS, "annual_fee_cents"
    )
    assert_money(
        activated["provisional_annual_fee_cents"],
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        "provisional_annual_fee_cents",
    )
    # The declarations mirrored the survey, so the two variants agree.
    assert_money(
        activated["verified_fee_delta_cents"], 0, "verified_fee_delta_cents"
    )
    assert_version(activated, minted["version"] + 1, "activated licence")
    assert_days_apart(
        activated["term_start"], activated["term_end"], TERM_LENGTH_DAYS, "term"
    )

    # Everything the activation recomputed is visible in the next read.
    venue_after = venue_row(api, venue["id"])
    assert_coverage(venue_after, SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)
    assert_venue_ledger(
        venue_after,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        0,
        0,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
    )

    society_after = validate_success(api.get_society(society["id"], admin_headers()))
    assert_count(society_after["licensed_venue_count"], 1, "licensed_venue_count")

    windows = windows_of_license(api, minted["id"])
    assert len(windows) == 1, "activation creates exactly one annual window"
    assert windows[0]["window_kind"] == WINDOW_KIND_ANNUAL_TERM
    assert windows[0]["status"] == WINDOW_STATUS_ACTIVE
    assert_count(windows[0]["covered_day_count"], TERM_LENGTH_DAYS, "covered_day_count")
    assert_money(windows[0]["rider_fee_cents"], 0, "rider_fee_cents")
    assert_instant_equals(
        windows[0]["window_start"], activated["term_start"], "window_start"
    )
    assert_instant_equals(
        windows[0]["window_end"], activated["term_end"], "window_end"
    )

    assessments = assessments_of_license(api, minted["id"])
    assert len(assessments) == 1, "activation raises exactly one assessment"
    assert_assessment(
        assessments[0],
        ASSESSMENT_KIND_INITIAL,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )
    assert assessments[0]["license_id"] == minted["id"]
    assert assessments[0]["venue_id"] == venue["id"]
    assert assessments[0]["audit_case_id"] is None

    # The re-read licence agrees with the response the activation returned.
    reread = license_row(api, minted["id"])
    assert_license_dimensions(reread, COVERAGE_ACTIVE, BILLING_INVOICED)
    assert_version(reread, activated["version"], "re-read licence")
    assert_money(
        reread["annual_fee_cents"], _BAR_GRILL_ANNUAL_FEE_CENTS, "annual_fee_cents"
    )
