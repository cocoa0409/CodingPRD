"""
The temporal and money-bearing guards of the licensing contract.

Where the previous file stops at the shape of a request, these tests pin the
rules that read the world before they answer: a renewal term must abut its
predecessor and may be issued only once, a performance must fall inside the
period that reports it, an approval needs a published price list, a negotiation
has a dispute bound and a floor, renewal and non-payment reinstatement are gated
on the venue's outstanding balance, and a payment may not exceed what is still
unpaid.  Every refusal here is also checked for having written nothing.
"""

from test_helpers import (
    APPLICATION_STATUS_APPROVED,
    APPLICATION_STATUS_UNDER_REVIEW,
    ASSESSMENT_KIND_AUDIT_BACK_LICENSE,
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_STATUS_ISSUED,
    ASSESSMENT_STATUS_PAID,
    AUDITOR_USER_ID,
    BILLING_DELINQUENT,
    BILLING_INVOICED,
    BILLING_PAID,
    CASE_STATUS_FINDINGS_ISSUED,
    CASE_STATUS_SETTLED,
    CASE_STATUS_SETTLEMENT_PROPOSED,
    CLOCK_START_INSTANT,
    COVERAGE_ACTIVE,
    COVERAGE_PENDING_ACTIVATION,
    COVERAGE_SUSPENDED,
    ERR_ASSESSMENT_NOT_ISSUED,
    ERR_DISPUTE_LIMIT_REACHED,
    ERR_ENTRY_OUTSIDE_PERIOD,
    ERR_LICENSE_ALREADY_RENEWED,
    ERR_NO_EFFECTIVE_RATE_SCHEDULE,
    ERR_OUTSTANDING_BALANCE_BLOCKS_REINSTATEMENT,
    ERR_OUTSTANDING_BALANCE_BLOCKS_RENEWAL,
    ERR_PAYMENT_EXCEEDS_BALANCE,
    ERR_RENEWAL_TERM_MISMATCH,
    ERR_SETTLEMENT_BELOW_FLOOR,
    POSTURE_PARTIALLY_COVERED,
    POSTURE_UNCOVERED,
    REPORT_STATUS_DRAFT,
    SETTLEMENT_USER_ID,
    SHARE_BMI_BP,
    SUSPENSION_REASON_AUDIT_FINDINGS,
    SUSPENSION_REASON_NONPAYMENT,
    SUSPENSION_REASON_OPERATOR_REQUEST,
    accept_for_review,
    admin_headers,
    application_row,
    approve_payload,
    assert_assessment,
    assert_count,
    assert_coverage,
    assert_days_apart,
    assert_empty_list,
    assert_instant_equals,
    assert_license_dimensions,
    assert_money,
    assert_venue_ledger,
    assert_version_unchanged,
    assessment_row,
    assessments_of_case,
    assessments_of_venue,
    auditor_headers,
    case_row,
    concert_hall_venue_payload,
    get_success_data,
    given_draft_report,
    given_draft_schedule,
    given_effective_schedule,
    given_licensed_venue,
    given_open_case,
    given_society,
    given_submitted_application,
    given_venue,
    ids_of,
    license_row,
    mid_concert_hall_venue_payload,
    payment_payload,
    read_rows,
    renew_payload,
    report_row,
    setlist_entries_of,
    setlist_entry_payload,
    settlement_headers,
    settlement_offer_payload,
    suspend_payload,
    validate_error,
    venue_operator_headers,
    venue_row,
)

# Every licence in this file is issued for the term that opens at the logical
# clock's own start-up instant, so its half-open term is
# [2026-08-01T00:00:00Z, 2027-08-01T00:00:00Z) and a legal renewal must start at
# the closing instant exactly.
TERM_START = "2026-08-01T00:00:00Z"
TERM_END = "2027-08-01T00:00:00Z"

# Verified annual fees, derived from PRD §3.5 against a default schedule for a
# society holding 4600 basis points of the repertoire.
BAR_GRILL_ANNUAL_FEE_CENTS = 90017
MID_CONCERT_HALL_ANNUAL_FEE_CENTS = 463761

# The audit waterfall of the 1200-occupancy concert hall over the sixteen whole
# months of [2025-01-01T00:00:00Z, 2026-05-01T00:00:00Z).
AUDIT_LOOKBACK_START = "2025-01-01T00:00:00Z"
AUDIT_LOOKBACK_END = "2026-05-01T00:00:00Z"
UNLICENSED_MONTHS = 16
BACK_LICENSE_EXPOSURE_CENTS = 1780608
PENALTY_CENTS = 890304
PRE_CREDIT_TOTAL_CENTS = 2670912
GOODWILL_CREDIT_CENTS = 267091
SETTLEMENT_TOTAL_CENTS = 2403821
SETTLEMENT_FLOOR_CENTS = 1442293


def test_guard_renewal_term_must_abut_predecessor(api):
    """A successor term must open at the instant the predecessor's term closes:
    a month late and a second early are both refused, and neither refusal marks
    the predecessor as renewed.

    PRD §3.7: "The supplied `requested_term_start` must equal the predecessor's
    `term_end` exactly, to the instant, otherwise `ERR_RENEWAL_TERM_MISMATCH` — no
    gap and no overlap is tolerated in the chain of terms."

    Design: Corner/validations/corner_validation_renewal_term_mismatch_rejected
    """
    world = given_licensed_venue(api, requested_term_start=TERM_START)
    licence = world["license"]
    assert_instant_equals(licence["term_start"], TERM_START, "term_start")
    assert_instant_equals(licence["term_end"], TERM_END, "term_end")

    validate_error(
        api.renew_license(
            licence["id"],
            renew_payload(
                "2027-09-01T00:00:00Z", expected_license_version=licence["version"]
            ),
            admin_headers(),
        ),
        ERR_RENEWAL_TERM_MISMATCH,
    )
    validate_error(
        api.renew_license(
            licence["id"],
            renew_payload(
                "2027-07-31T23:59:59Z", expected_license_version=licence["version"]
            ),
            admin_headers(),
        ),
        ERR_RENEWAL_TERM_MISMATCH,
    )

    refused = license_row(api, licence["id"])
    assert refused["renewal_issued_at"] is None
    assert_version_unchanged(refused, licence, "license")
    assert_empty_list(
        api.list_licenses(admin_headers(), {"renewal_of_license_id": licence["id"]})
    )

    # The one instant the chain allows is the predecessor's own term_end.
    successor = get_success_data(
        api.renew_license(
            licence["id"],
            renew_payload(TERM_END, expected_license_version=licence["version"]),
            admin_headers(),
        )
    )
    assert successor["coverage_status"] == COVERAGE_PENDING_ACTIVATION
    assert successor["renewal_of_license_id"] == licence["id"]
    assert_instant_equals(successor["term_start"], TERM_END, "successor term_start")
    assert_days_apart(
        successor["term_start"], successor["term_end"], 365, "successor term"
    )


def test_guard_setlist_entry_inside_report_period(api):
    """A reported performance must fall inside the report's half-open period, so
    the closing instant itself is out and the second before the period opens is
    out; the last second inside is in and it advances the reported count.

    PRD §3.8: "The entry's `performance_report_id` is the report it is appended
    to, and `performance_datetime` must fall inside that report's half-open period
    or the append is rejected with `ERR_ENTRY_OUTSIDE_PERIOD`."

    PRD §3.8: "Appending increments the report's `reported_entry_count`."

    Design: Corner/validations/corner_validation_setlist_entry_outside_period_rejected
    """
    world = given_licensed_venue(api, requested_term_start=TERM_START)
    licence = world["license"]
    venue_id = world["venue"]["id"]
    report = given_draft_report(
        api, licence["id"], venue_id, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
    )

    # The excluded end instant of the period.
    validate_error(
        api.create_setlist_entry(
            report["id"],
            setlist_entry_payload(
                "Closing Number", "R. Wright", "BMI", "2026-10-01T00:00:00Z", 300
            ),
            venue_operator_headers(venue_id),
        ),
        ERR_ENTRY_OUTSIDE_PERIOD,
    )
    # One second before the period opens.
    validate_error(
        api.create_setlist_entry(
            report["id"],
            setlist_entry_payload(
                "Warm Up", "R. Wright", "BMI", "2026-08-31T23:59:59Z", 300
            ),
            venue_operator_headers(venue_id),
        ),
        ERR_ENTRY_OUTSIDE_PERIOD,
    )

    untouched = report_row(api, report["id"])
    assert untouched["status"] == REPORT_STATUS_DRAFT
    assert_count(untouched["reported_entry_count"], 0, "reported_entry_count")
    assert_version_unchanged(untouched, report, "performance report")
    assert setlist_entries_of(api, report["id"]) == []

    # The last second inside the period is accepted.
    entry = get_success_data(
        api.create_setlist_entry(
            report["id"],
            setlist_entry_payload(
                "Last Set", "R. Wright", "BMI", "2026-09-30T23:59:59Z", 300
            ),
            venue_operator_headers(venue_id),
        )
    )
    assert entry["is_matched"] is False
    assert entry["matched_work_id"] is None

    appended = report_row(api, report["id"])
    assert appended["status"] == REPORT_STATUS_DRAFT
    assert_count(appended["reported_entry_count"], 1, "reported_entry_count")
    rows = read_rows(
        api.list_setlist_entries(
            admin_headers(), {"performance_report_id": report["id"]}
        ),
        expected_total=1,
    )
    assert ids_of(rows) == [entry["id"]]


def test_guard_second_renewal_of_same_licence_refused(api):
    """A licence may be renewed exactly once: with `renewal_issued_at` stamped, a
    second renewal of the same predecessor is refused even when the requested term
    is the one legal term, and only the first successor exists.

    PRD §3.7: "And the predecessor's `renewal_issued_at` must still be null,
    otherwise `ERR_LICENSE_ALREADY_RENEWED`; a licence may be renewed once, and
    the successor that already exists is discoverable through its own
    `renewal_of_license_id`."

    PRD §3.7: "On success the predecessor's `renewal_issued_at` is set to the
    logical clock instant at which the renewal was issued and its `version`
    increments by 1."

    Design: Corner/validations/corner_validation_second_renewal_of_same_license_rejected
    """
    world = given_licensed_venue(api, requested_term_start=TERM_START)
    licence = world["license"]

    first_successor = get_success_data(
        api.renew_license(
            licence["id"],
            renew_payload(TERM_END, expected_license_version=licence["version"]),
            admin_headers(),
        )
    )

    renewed = license_row(api, licence["id"])
    assert_instant_equals(
        renewed["renewal_issued_at"], CLOCK_START_INSTANT, "renewal_issued_at"
    )

    # The concurrency guard is satisfied against the freshly read version, so the
    # refusal can only come from the already-renewed rule.
    validate_error(
        api.renew_license(
            licence["id"],
            renew_payload(TERM_END, expected_license_version=renewed["version"]),
            admin_headers(),
        ),
        ERR_LICENSE_ALREADY_RENEWED,
    )

    after = license_row(api, licence["id"])
    assert_version_unchanged(after, renewed, "predecessor license")
    assert_instant_equals(
        after["renewal_issued_at"], CLOCK_START_INSTANT, "renewal_issued_at"
    )

    successors = read_rows(
        api.list_licenses(admin_headers(), {"renewal_of_license_id": licence["id"]}),
        expected_total=1,
    )
    assert ids_of(successors) == [first_successor["id"]]
    successor = license_row(api, first_successor["id"])
    assert successor["coverage_status"] == COVERAGE_PENDING_ACTIVATION
    assert_instant_equals(successor["term_start"], TERM_END, "successor term_start")
    assert_days_apart(
        successor["term_start"], successor["term_end"], 365, "successor term"
    )


def test_guard_approve_requires_effective_schedule(api):
    """Approval prices the application, so it cannot proceed while the only price
    list for the society and venue category is still a draft; publishing that same
    schedule lets the very same approval through.

    PRD §3.2: "`DRAFT` and `SUPERSEDED` schedules are never eligible."

    PRD §3.2: "When the candidate set is empty the request that needed a schedule
    is rejected with `ERR_NO_EFFECTIVE_RATE_SCHEDULE`."

    Design: Corner/validations/corner_validation_approve_without_effective_schedule_rejected
    """
    society = given_society(api)
    draft_schedule = given_draft_schedule(api, society["id"], "BAR_GRILL")
    venue = given_venue(api)
    application = given_submitted_application(
        api, venue, society["id"], requested_term_start=TERM_START
    )
    under_review = accept_for_review(api, application["id"])
    assert under_review["status"] == APPLICATION_STATUS_UNDER_REVIEW

    validate_error(
        api.review_application(application["id"], approve_payload(), admin_headers()),
        ERR_NO_EFFECTIVE_RATE_SCHEDULE,
    )

    refused = application_row(api, application["id"])
    assert refused["status"] == APPLICATION_STATUS_UNDER_REVIEW
    assert refused["assigned_license_type"] is None
    assert refused["provisional_annual_fee_cents"] is None
    assert_version_unchanged(refused, under_review, "application")
    assert_empty_list(
        api.list_licenses(admin_headers(), {"application_id": application["id"]})
    )

    get_success_data(api.publish_rate_schedule(draft_schedule["id"], admin_headers()))

    approved = get_success_data(
        api.review_application(application["id"], approve_payload(), admin_headers())
    )
    assert approved["status"] == APPLICATION_STATUS_APPROVED
    assert_money(
        approved["provisional_annual_fee_cents"],
        BAR_GRILL_ANNUAL_FEE_CENTS,
        "provisional_annual_fee_cents",
    )
    licences = read_rows(
        api.list_licenses(admin_headers(), {"application_id": application["id"]}),
        expected_total=1,
    )
    assert licences[0]["coverage_status"] == COVERAGE_PENDING_ACTIVATION


def _venue_with_findings_issued_case(api):
    """An unlicensed 1200-occupancy concert hall with findings already issued.

    The venue holds no licence at all, so every one of the sixteen whole months
    of the lookback interval is uncovered for the single society in scope, and the
    whole exposure-and-settlement waterfall of PRD §3.9 is observable on the case.
    """
    society = given_society(api)
    assert society["repertoire_share_bp"] == SHARE_BMI_BP
    given_effective_schedule(api, society["id"], "CONCERT_HALL")
    venue = given_venue(api, concert_hall_venue_payload())
    case = given_open_case(
        api,
        venue["id"],
        [society["id"]],
        AUDIT_LOOKBACK_START,
        AUDIT_LOOKBACK_END,
    )
    issued = get_success_data(api.issue_findings(case["id"], auditor_headers()))
    return venue, issued


def test_guard_third_dispute_refused(api):
    """The venue may push back on an offer twice and no more: after two disputes a
    third is refused, leaving the standing offer, its payment plan and the audit
    hold exactly where the second round left them.

    PRD §3.9: "A `VenueOperator` acting for that venue, or a `LicensingAdmin`,
    disputes a `SETTLEMENT_PROPOSED` case provided `dispute_round` is still
    strictly below the maximum of 2 disputes; a third attempt is rejected with
    `ERR_DISPUTE_LIMIT_REACHED`."

    Design: Corner/validations/corner_validation_third_dispute_rejected
    """
    venue, case = _venue_with_findings_issued_case(api)
    assert case["status"] == CASE_STATUS_FINDINGS_ISSUED
    assert_money(
        case["settlement_floor_cents"], SETTLEMENT_FLOOR_CENTS, "settlement_floor_cents"
    )

    get_success_data(
        api.propose_settlement(
            case["id"], settlement_offer_payload(1500000), settlement_headers()
        )
    )
    get_success_data(
        api.dispute_settlement(case["id"], venue_operator_headers(venue["id"]))
    )
    get_success_data(
        api.propose_settlement(
            case["id"], settlement_offer_payload(1480000), settlement_headers()
        )
    )
    get_success_data(
        api.dispute_settlement(case["id"], venue_operator_headers(venue["id"]))
    )
    standing = get_success_data(
        api.propose_settlement(
            case["id"],
            settlement_offer_payload(1460000, payment_plan_months=6),
            settlement_headers(),
        )
    )
    assert standing["status"] == CASE_STATUS_SETTLEMENT_PROPOSED
    assert_count(standing["dispute_round"], 2, "dispute_round")

    validate_error(
        api.dispute_settlement(case["id"], venue_operator_headers(venue["id"])),
        ERR_DISPUTE_LIMIT_REACHED,
    )

    after = case_row(api, case["id"])
    assert after["status"] == CASE_STATUS_SETTLEMENT_PROPOSED
    assert_count(after["dispute_round"], 2, "dispute_round")
    assert_money(after["offered_amount_cents"], 1460000, "offered_amount_cents")
    assert_count(after["payment_plan_months"], 6, "payment_plan_months")
    assert_version_unchanged(after, standing, "audit case")
    assert venue_row(api, venue["id"])["audit_hold"] is True

    assessments = assessments_of_case(api, case["id"])
    assert_count(len(assessments), 1, "assessment count")
    assert_assessment(
        assessments[0],
        ASSESSMENT_KIND_AUDIT_BACK_LICENSE,
        PRE_CREDIT_TOTAL_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )

    # The standing offer is still acceptable once the disputes are exhausted.
    settled = get_success_data(api.settle_audit_case(case["id"], settlement_headers()))
    assert settled["status"] == CASE_STATUS_SETTLED


def test_guard_settlement_offer_at_or_above_floor(api):
    """One cent below the computed settlement floor is refused and the floor itself
    is accepted, and the whole waterfall the floor is derived from is pinned; the
    refused offer records neither an amount nor a proposing officer.

    PRD §3.9: "Finally, `settlement_floor_cents` — the minimum offer the societies
    will entertain — is `settlement_total_cents` multiplied by 6000 basis points,
    divided by 10000, rounded half up to whole cents, which is sixty percent of
    the settlement target."

    PRD §3.9: "The offer must be at least the case's `settlement_floor_cents`,
    otherwise `ERR_SETTLEMENT_BELOW_FLOOR`."

    Design: Corner/validations/corner_validation_offer_below_settlement_floor_rejected
    """
    _venue, case = _venue_with_findings_issued_case(api)
    assert_count(
        case["unlicensed_month_count"], UNLICENSED_MONTHS, "unlicensed_month_count"
    )
    assert_money(
        case["back_license_exposure_cents"],
        BACK_LICENSE_EXPOSURE_CENTS,
        "back_license_exposure_cents",
    )
    assert_money(case["penalty_cents"], PENALTY_CENTS, "penalty_cents")
    assert_money(
        case["pre_credit_total_cents"], PRE_CREDIT_TOTAL_CENTS, "pre_credit_total_cents"
    )
    assert_money(
        case["goodwill_credit_cents"], GOODWILL_CREDIT_CENTS, "goodwill_credit_cents"
    )
    assert_money(
        case["settlement_total_cents"], SETTLEMENT_TOTAL_CENTS, "settlement_total_cents"
    )
    assert_money(
        case["settlement_floor_cents"], SETTLEMENT_FLOOR_CENTS, "settlement_floor_cents"
    )

    validate_error(
        api.propose_settlement(
            case["id"],
            settlement_offer_payload(SETTLEMENT_FLOOR_CENTS - 1),
            settlement_headers(),
        ),
        ERR_SETTLEMENT_BELOW_FLOOR,
    )

    refused = case_row(api, case["id"])
    assert refused["status"] == CASE_STATUS_FINDINGS_ISSUED
    assert refused["offered_amount_cents"] is None
    assert refused["payment_plan_months"] is None
    assert refused["settlement_proposed_by_user_id"] is None
    assert_version_unchanged(refused, case, "audit case")

    proposed = get_success_data(
        api.propose_settlement(
            case["id"],
            settlement_offer_payload(SETTLEMENT_FLOOR_CENTS, payment_plan_months=12),
            settlement_headers(),
        )
    )
    assert proposed["status"] == CASE_STATUS_SETTLEMENT_PROPOSED
    assert_money(
        proposed["offered_amount_cents"],
        SETTLEMENT_FLOOR_CENTS,
        "offered_amount_cents",
    )
    assert_count(proposed["payment_plan_months"], 12, "payment_plan_months")
    # The officer who negotiates is not the auditor who issued the findings.
    assert proposed["settlement_proposed_by_user_id"] == SETTLEMENT_USER_ID
    assert proposed["findings_issued_by_user_id"] == AUDITOR_USER_ID


def test_guard_outstanding_balance_blocks_renewal(api):
    """A venue that owes 463761 cents cannot renew its licence; a part payment
    that brings the debt down to exactly the tolerated 100000 cents unblocks the
    very same renewal, and the refused attempt marks nothing as renewed.

    PRD §3.7: "The venue's `outstanding_balance_cents` must be at most 100000
    cents, otherwise `ERR_OUTSTANDING_BALANCE_BLOCKS_RENEWAL`."

    PRD §3.7: "And the predecessor's `renewal_issued_at` must still be null,
    otherwise `ERR_LICENSE_ALREADY_RENEWED`; a licence may be renewed once, and
    the successor that already exists is discoverable through its own
    `renewal_of_license_id`."

    Design: Corner/validations/corner_validation_outstanding_balance_blocks_renewal_rejected
    """
    world = given_licensed_venue(
        api,
        mid_concert_hall_venue_payload(),
        venue_category="CONCERT_HALL",
        requested_term_start=TERM_START,
    )
    licence = world["license"]
    venue_id = world["venue"]["id"]
    assert world["venue"]["audit_hold"] is False
    assert_license_dimensions(licence, COVERAGE_ACTIVE, BILLING_DELINQUENT)
    assert_venue_ledger(
        world["venue"],
        MID_CONCERT_HALL_ANNUAL_FEE_CENTS,
        0,
        0,
        MID_CONCERT_HALL_ANNUAL_FEE_CENTS,
    )

    validate_error(
        api.renew_license(
            licence["id"],
            renew_payload(TERM_END, expected_license_version=licence["version"]),
            admin_headers(),
        ),
        ERR_OUTSTANDING_BALANCE_BLOCKS_RENEWAL,
    )

    refused = license_row(api, licence["id"])
    assert refused["renewal_issued_at"] is None
    assert_version_unchanged(refused, licence, "license")
    assert_empty_list(
        api.list_licenses(admin_headers(), {"renewal_of_license_id": licence["id"]})
    )

    assessments = assessments_of_venue(api, venue_id)
    assert_count(len(assessments), 1, "assessment count")
    initial = assessments[0]
    assert_assessment(
        initial,
        ASSESSMENT_KIND_INITIAL,
        MID_CONCERT_HALL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )

    # A part payment down to the tolerated ceiling exactly, not a cent further.
    part_paid = get_success_data(
        api.pay_assessment(initial["id"], payment_payload(363761), admin_headers())
    )
    assert_assessment(
        part_paid,
        ASSESSMENT_KIND_INITIAL,
        MID_CONCERT_HALL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=363761,
    )
    assert_venue_ledger(
        venue_row(api, venue_id),
        100000,
        363761,
        0,
        MID_CONCERT_HALL_ANNUAL_FEE_CENTS,
    )

    # The part payment moved the licence's billing dimension, so the renewal is
    # re-attempted against the licence's current version.
    current = license_row(api, licence["id"])
    assert_license_dimensions(current, COVERAGE_ACTIVE, BILLING_INVOICED)

    successor = get_success_data(
        api.renew_license(
            licence["id"],
            renew_payload(TERM_END, expected_license_version=current["version"]),
            admin_headers(),
        )
    )
    assert successor["renewal_of_license_id"] == licence["id"]
    assert successor["coverage_status"] == COVERAGE_PENDING_ACTIVATION
    assert_instant_equals(successor["term_start"], TERM_END, "successor term_start")
    assert license_row(api, licence["id"])["renewal_issued_at"] is not None


def test_guard_nonpayment_reinstatement_blocked_by_balance(api):
    """A licence suspended for non-payment cannot come back while the venue still
    owes more than the tolerated 100000 cents; paying the debt down to exactly that
    ceiling lets it back to active and restores the venue's covered share.

    PRD §3.7: "And when the licence carries `suspension_reason` `NONPAYMENT`, the
    venue's `outstanding_balance_cents` must be at most 100000 cents, or the
    request is rejected with `ERR_OUTSTANDING_BALANCE_BLOCKS_REINSTATEMENT`; a
    licence suspended for `AUDIT_FINDINGS` or `OPERATOR_REQUEST` faces no balance
    gate at all, so it can be reinstated while the venue still owes a great deal."

    Design: Corner/validations/corner_validation_nonpayment_reinstatement_blocked_by_balance
    """
    world = given_licensed_venue(
        api,
        mid_concert_hall_venue_payload(),
        venue_category="CONCERT_HALL",
        requested_term_start=TERM_START,
    )
    licence = world["license"]
    venue_id = world["venue"]["id"]
    assert_coverage(world["venue"], SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)

    suspended = get_success_data(
        api.suspend_license(
            licence["id"],
            suspend_payload(SUSPENSION_REASON_NONPAYMENT),
            admin_headers(),
        )
    )
    assert_license_dimensions(suspended, COVERAGE_SUSPENDED, BILLING_DELINQUENT)
    assert suspended["suspension_reason"] == SUSPENSION_REASON_NONPAYMENT
    assert_coverage(venue_row(api, venue_id), 0, POSTURE_UNCOVERED)

    validate_error(
        api.reinstate_license(licence["id"], admin_headers()),
        ERR_OUTSTANDING_BALANCE_BLOCKS_REINSTATEMENT,
    )

    still_suspended = license_row(api, licence["id"])
    assert_license_dimensions(still_suspended, COVERAGE_SUSPENDED, BILLING_DELINQUENT)
    assert still_suspended["suspension_reason"] == SUSPENSION_REASON_NONPAYMENT
    assert_version_unchanged(still_suspended, suspended, "license")
    assert_coverage(venue_row(api, venue_id), 0, POSTURE_UNCOVERED)

    initial = assessments_of_venue(api, venue_id)[0]
    get_success_data(
        api.pay_assessment(initial["id"], payment_payload(363761), admin_headers())
    )
    assert_venue_ledger(
        venue_row(api, venue_id),
        100000,
        363761,
        0,
        MID_CONCERT_HALL_ANNUAL_FEE_CENTS,
    )

    reinstated = get_success_data(
        api.reinstate_license(licence["id"], admin_headers())
    )
    assert reinstated["coverage_status"] == COVERAGE_ACTIVE
    assert reinstated["suspension_reason"] is None
    assert_coverage(
        venue_row(api, venue_id), SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED
    )


def test_guard_reinstatement_balance_gate_only_for_nonpayment(api):
    """The balance gate on reinstatement is keyed on the reason for the suspension:
    the same venue owing the same 463761 cents is reinstated without objection when
    it was suspended for audit findings, and again when suspended by request.

    PRD §2.12: "**Reinstatement balance gate.** When the suspended licence carries
    `suspension_reason` `NONPAYMENT`, the venue's `outstanding_balance_cents` is at
    most 100000 cents; a licence suspended for `AUDIT_FINDINGS` or
    `OPERATOR_REQUEST` is not balance-gated at all."

    Design: Corner/validations/corner_validation_reinstatement_balance_gate_only_for_nonpayment
    """
    world = given_licensed_venue(
        api,
        mid_concert_hall_venue_payload(),
        venue_category="CONCERT_HALL",
        requested_term_start=TERM_START,
    )
    licence = world["license"]
    venue_id = world["venue"]["id"]
    initial = assessments_of_venue(api, venue_id)[0]

    for reason in (
        SUSPENSION_REASON_AUDIT_FINDINGS,
        SUSPENSION_REASON_OPERATOR_REQUEST,
    ):
        suspended = get_success_data(
            api.suspend_license(
                licence["id"], suspend_payload(reason), admin_headers()
            )
        )
        assert suspended["coverage_status"] == COVERAGE_SUSPENDED
        assert suspended["suspension_reason"] == reason

        reinstated = get_success_data(
            api.reinstate_license(licence["id"], admin_headers())
        )
        assert reinstated["coverage_status"] == COVERAGE_ACTIVE
        assert reinstated["suspension_reason"] is None
        assert_coverage(
            venue_row(api, venue_id), SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED
        )

        # The debt that would have blocked a non-payment reinstatement is
        # untouched throughout, and no money moved either way.
        assert_venue_ledger(
            venue_row(api, venue_id),
            MID_CONCERT_HALL_ANNUAL_FEE_CENTS,
            0,
            0,
            MID_CONCERT_HALL_ANNUAL_FEE_CENTS,
        )
        assert_assessment(
            assessment_row(api, initial["id"]),
            ASSESSMENT_KIND_INITIAL,
            MID_CONCERT_HALL_ANNUAL_FEE_CENTS,
            ASSESSMENT_STATUS_ISSUED,
            paid=0,
        )


def test_guard_payment_may_not_exceed_unpaid_remainder(api):
    """A payment is bounded by what is still unpaid, not by the original bill: after
    40000 cents of a 90017-cent assessment, 50018 is refused and so is a fresh
    90017, while 50017 exactly settles it and closes the licence's billing.

    PRD §3.9: "The payment may not exceed the unpaid remainder — the assessment's
    `amount_cents` less its `paid_amount_cents` — or it is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."

    PRD §3.9: "**A payment for exactly the remainder** sets `paid_amount_cents` to
    the assessment's full `amount_cents`, moves `status` to the terminal `PAID`, and
    increments `version`."

    Design: Corner/validations/corner_validation_payment_over_remaining_balance_rejected
    """
    world = given_licensed_venue(api, requested_term_start=TERM_START)
    licence = world["license"]
    venue_id = world["venue"]["id"]
    initial = assessments_of_venue(api, venue_id)[0]
    assert_assessment(
        initial,
        ASSESSMENT_KIND_INITIAL,
        BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )
    assert_license_dimensions(licence, COVERAGE_ACTIVE, BILLING_INVOICED)

    part_paid = get_success_data(
        api.pay_assessment(initial["id"], payment_payload(40000), admin_headers())
    )
    assert_assessment(
        part_paid,
        ASSESSMENT_KIND_INITIAL,
        BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=40000,
    )

    # One cent over the remainder, and then the whole original bill again.
    validate_error(
        api.pay_assessment(initial["id"], payment_payload(50018), admin_headers()),
        ERR_PAYMENT_EXCEEDS_BALANCE,
    )
    validate_error(
        api.pay_assessment(
            initial["id"],
            payment_payload(BAR_GRILL_ANNUAL_FEE_CENTS),
            admin_headers(),
        ),
        ERR_PAYMENT_EXCEEDS_BALANCE,
    )

    unmoved = assessment_row(api, initial["id"])
    assert_assessment(
        unmoved,
        ASSESSMENT_KIND_INITIAL,
        BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=40000,
    )
    assert_version_unchanged(unmoved, part_paid, "fee assessment")
    assert_venue_ledger(
        venue_row(api, venue_id), 50017, 40000, 0, BAR_GRILL_ANNUAL_FEE_CENTS
    )

    settled = get_success_data(
        api.pay_assessment(initial["id"], payment_payload(50017), admin_headers())
    )
    assert_assessment(
        settled,
        ASSESSMENT_KIND_INITIAL,
        BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_PAID,
        paid=BAR_GRILL_ANNUAL_FEE_CENTS,
    )
    assert_venue_ledger(
        venue_row(api, venue_id), 0, BAR_GRILL_ANNUAL_FEE_CENTS, 0,
        BAR_GRILL_ANNUAL_FEE_CENTS,
    )
    assert_license_dimensions(
        license_row(api, licence["id"]), COVERAGE_ACTIVE, BILLING_PAID
    )

    # A terminal assessment takes no further money at all.
    validate_error(
        api.pay_assessment(initial["id"], payment_payload(1), admin_headers()),
        ERR_ASSESSMENT_NOT_ISSUED,
    )
