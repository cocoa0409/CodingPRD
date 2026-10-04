"""Corner queue — application, invoice, dispute, scam-report and ad-review
lifecycle: invoice overdue/void cascade, terminal-state lockdowns, the
reapplication cooling cycle, the dispute/appeal pipeline, and the 183-day
age boundary (PRD §3.2, §3.3, §3.7, §3.8)."""

from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    PREPAID_TOTAL_FEE0_CENTS,
    TEST_USERS,
    business_respond,
    compute_snapshot,
    conclude_advertising_review,
    conclude_review_deceptive_payload,
    consumer_accept,
    create_application,
    create_application_payload,
    create_bureau,
    create_business,
    create_consumer,
    decide_appeal,
    decide_application_payload,
    deny_application,
    file_and_forward_complaint,
    file_rating_dispute,
    file_scam_report,
    get_application,
    get_business,
    get_invoice,
    ledger_entry_payload,
    make_business_rep_headers,
    open_advertising_review,
    parse_iso,
    publish_scam_report,
    run_daily_close,
    set_clock,
    setup_approved_application,
    setup_world,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
REVIEWER = TEST_USERS["standards_reviewer_headers"]


def _micro_world():
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    business = create_business(legal_name="Deadbeat Micro LLC",
                               home_state_code="IA", employee_count=2,
                               founded_on="2020-01-01T00:00:00Z")
    return bureau, business


def _large_world_with_consumer():
    world = setup_world(business_overrides={
        "legal_name": "BigBox Services Inc", "employee_count": 250,
        "founded_on": "2018-01-01T00:00:00Z"})
    return world["bureau"], world["consumer"], world["business"]


def _unanswered_large_business():
    """LARGE business whose single complaint has expired to UNANSWERED at the
    2026-09-16 sweep."""
    bureau, consumer, business = _large_world_with_consumer()
    file_and_forward_complaint(consumer, business, category="SERVICE",
                               description="never answered")
    set_clock("2026-09-16T00:00:00Z")
    run_daily_close(bureau["id"])
    return bureau, consumer, business


def _rows_by_id(rows, row_id):
    for row in rows:
        if row["id"] == row_id:
            return row
    raise AssertionError(f"row {row_id} missing")


def test_invoice_overdue_then_void_expires_application_and_blocks_payment(
        api):
    """PRD §3.3: "An invoice whose `due_date` has passed flips from `ISSUED`
    — or from `PARTIALLY_PAID` — to `OVERDUE`."
    PRD §3.3: "An invoice still unpaid more than 15 days after its `due_date`
    is voided by the daily close: its status becomes `VOID`, `voided_at` is
    stamped, the linked application falls from `APPROVED_PENDING_DUES` to
    `EXPIRED`, and the unpaid balance counts against the business's future
    accreditation applications for the next 365 days through the approval
    gate of §3.2."
    PRD §3.3: "Ledger entries against a `VOID` or `REFUNDED` invoice are
    rejected with `ERR_INVOICE_INVALID_STATE`"

    Design: Corner/state_machines/invoice_overdue_then_void_expires_application_and_blocks_payment
    """
    bureau, business = _micro_world()
    app, invoice = setup_approved_application(business)
    assert invoice["amount_due_cents"] == \
        PREPAID_TOTAL_FEE0_CENTS["MICRO"] == 40375
    assert parse_iso(invoice["due_date"]) == parse_iso(
        invoice["issued_at"]) + timedelta(days=30)
    assert parse_iso(invoice["due_date"]) == parse_iso("2026-10-01T00:00:00Z")

    set_clock("2026-10-02T00:00:00Z")  # past due_date
    run_daily_close(bureau["id"])
    assert get_invoice(business["id"], invoice["id"])["status"] == "OVERDUE"

    set_clock("2026-10-17T00:00:00Z")  # more than 15 days past due_date
    run_daily_close(bureau["id"])
    voided = get_invoice(business["id"], invoice["id"])
    assert voided["status"] == "VOID"
    assert parse_iso(voided["voided_at"]) == parse_iso("2026-10-17T00:00:00Z")
    assert get_application(business["id"], app["id"])["status"] == "EXPIRED"

    resp = api.post_ledger_entry(
        invoice["id"], ledger_entry_payload("PAYMENT", 40375),
        make_business_rep_headers(business["id"]))
    validate_error(resp, ApiErrorId.ERR_INVOICE_INVALID_STATE)
    assert get_business(business["id"])["accreditation_status"] == \
        "NOT_ACCREDITED"


def test_expired_application_rejects_submit_and_decision(api):
    """PRD §3.2: "Submitting an application that is not in `DRAFT` is rejected
    with `ERR_APPLICATION_INVALID_STATE`."
    PRD §3.2: "Deciding an application that is not in `SUBMITTED` is rejected
    with `ERR_APPLICATION_INVALID_STATE`."

    Design: Corner/state_machines/expired_application_rejects_submit_and_decision
    """
    bureau, business = _micro_world()
    app, _invoice = setup_approved_application(business)
    set_clock("2026-10-17T00:00:00Z")  # invoice voids; application EXPIRED
    run_daily_close(bureau["id"])
    assert get_application(business["id"], app["id"])["status"] == "EXPIRED"
    resp = api.submit_application(
        app["id"], make_business_rep_headers(business["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)
    resp = api.decide_application(app["id"], decide_application_payload(),
                                  REVIEWER)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)
    assert get_application(business["id"], app["id"])["status"] == "EXPIRED"


def test_denied_application_reapply_cooling_then_reset_to_draft(api):
    """PRD §3.2: "The reset requires that at least 30 days have elapsed since
    the application's `decided_at` — earlier attempts are rejected with
    `ERR_REAPPLICATION_COOLING` — and is likewise ownership-gated."
    PRD §3.2: "On reset, `reapplication_count` increments by 1,
    `billing_plan` and `license_number` are overwritten from the payload, and
    `submitted_at`, `decided_at`, `denial_reason`, and all three checklist
    results are cleared to null."

    Design: Corner/state_machines/denied_application_reapply_cooling_then_reset_to_draft
    """
    _bureau, business = _micro_world()
    app = create_application(business, billing_plan="ANNUAL_PREPAID",
                             license_number="LIC-X-1")
    app = submit_application(app)
    denied = deny_application(app, denial_reason="license unverifiable",
                              licensing_result="FAIL")
    assert denied["status"] == "DENIED"

    def reapply():
        return api.create_accreditation_application(
            business["id"],
            create_application_payload(billing_plan="QUARTERLY",
                                       license_number="LIC-X-2",
                                       application_id=app["id"]),
            make_business_rep_headers(business["id"]))

    set_clock("2026-09-30T00:00:00Z")  # 29 days after decided_at
    validate_error(reapply(), ApiErrorId.ERR_REAPPLICATION_COOLING)

    set_clock("2026-10-01T00:00:00Z")  # exactly decided_at + 30 days
    reset = validate_success(reapply(), 201)
    assert reset["id"] == app["id"], "reapplication resets the same row"
    assert reset["status"] == "DRAFT"
    assert reset["reapplication_count"] == 1
    assert reset["billing_plan"] == "QUARTERLY"
    assert reset["license_number"] == "LIC-X-2"
    for field in ("submitted_at", "decided_at", "denial_reason",
                  "advertising_practices_result", "complaint_history_result",
                  "licensing_result"):
        assert reset[field] is None, field


def test_rating_dispute_overruled_recomputes_snapshot_excluding_complaint(
        api):
    """PRD §3.7: "A `decision` of `OVERRULED` requires `disputed_complaint_id`
    to name a complaint of the disputing business (else
    `ERR_SNAPSHOT_BUSINESS_MISMATCH`) and rewrites the record: the rating is
    recomputed with the disputed complaint excluded from every input set of
    §3.6, a fresh `PUBLISHED` snapshot is written with `published_at` stamped
    and `excluded_complaint_id` naming the excluded complaint, the superseded
    snapshot's `superseded_by_id` is set to the replacement snapshot's id, the
    business's `current_published_score` and `current_published_grade` update
    to the new values, and the business's `version` increments by 1."

    Design: Corner/state_machines/rating_dispute_overruled_recomputes_snapshot_excluding_complaint
    """
    bureau, consumer, business = _large_world_with_consumer()
    c1 = file_and_forward_complaint(consumer, business, category="SERVICE",
                                    description="c1 expires")
    set_clock("2026-09-16T00:00:00Z")
    run_daily_close(bureau["id"])  # c1 -> UNANSWERED
    c2 = file_and_forward_complaint(consumer, business, category="BILLING",
                                    description="c2 resolves")
    c2 = business_respond(c2, business, body="fixed")
    consumer_accept(c2, consumer, body="ok")
    snap1 = compute_snapshot(business, variant="PUBLISHED")
    assert snap1["score"] == 88 and snap1["grade"] == "B_PLUS"
    version_after_publish = get_business(business["id"])["version"]

    dispute = file_rating_dispute(
        business, snap1["id"], reason="we never received complaint c1",
        disputed_complaint_id=c1["id"],
        expected_business_version=version_after_publish)
    assert dispute["status"] == "UNDER_APPEAL_REVIEW"
    version_after_filing = get_business(business["id"])["version"]
    assert version_after_filing == version_after_publish + 1

    resp = api.decide_appeal(dispute["id"], {"decision": "OVERRULED"}, ADMIN)
    ruled = validate_success(resp, 200)
    assert ruled["status"] == "OVERRULED"

    rows, _meta = validate_paginated(
        api.list_rating_snapshots(business["id"], ADMIN))
    replacement = [r for r in rows
                   if r.get("excluded_complaint_id") == c1["id"]]
    assert len(replacement) == 1
    replacement = replacement[0]
    assert replacement["variant"] == "PUBLISHED"
    assert replacement["score"] == 100  # c2 RESOLVED alone deducts nothing
    assert replacement["grade"] == "A_PLUS"
    assert _rows_by_id(rows, snap1["id"])["superseded_by_id"] == \
        replacement["id"]
    mirror = get_business(business["id"])
    assert mirror["current_published_score"] == 100
    assert mirror["current_published_grade"] == "A_PLUS"
    assert mirror["version"] == version_after_filing + 1


def test_rating_dispute_upheld_keeps_snapshot_and_repeat_appeal_rejected(
        api):
    """PRD §3.7: "A `decision` of `UPHELD` closes the dispute with the
    contested snapshot unchanged."
    PRD §3.7: "Appeal rulings belong to `BureauAdmin` and require the dispute
    to be in `UNDER_APPEAL_REVIEW`; ruling on a dispute in any other state is
    rejected with `ERR_DISPUTE_INVALID_STATE`."

    Design: Corner/state_machines/rating_dispute_upheld_keeps_snapshot_and_repeat_appeal_rejected
    """
    _bureau, _consumer, business = _unanswered_large_business()
    snap = compute_snapshot(business, variant="PUBLISHED")
    assert snap["score"] == 88
    dispute = file_rating_dispute(business, snap["id"],
                                  reason="score is unfair")
    resp = api.decide_appeal(dispute["id"], {"decision": "UPHELD"}, ADMIN)
    assert validate_success(resp, 200)["status"] == "UPHELD"
    assert get_business(business["id"])["current_published_score"] == 88, \
        "an upheld dispute leaves the published record untouched"
    resp = api.decide_appeal(dispute["id"], {"decision": "OVERRULED"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_INVALID_STATE)


def test_dispute_filed_eleven_days_after_publish_rejected(api):
    """PRD §3.7: "The dispute must be filed no later than 10 days after the
    snapshot's `published_at`; a later filing is rejected with
    `ERR_DISPUTE_WINDOW_EXPIRED`."

    Design: Corner/state_machines/dispute_filed_eleven_days_after_publish_rejected
    """
    _bureau, _consumer, business = _large_world_with_consumer()
    snap = compute_snapshot(business, variant="PUBLISHED")
    assert parse_iso(snap["published_at"]) == parse_iso(CLOCK_START_ISO)
    set_clock("2026-09-12T00:00:00Z")  # published_at + 11 days
    resp = api.create_rating_dispute(
        business["id"],
        {"snapshot_id": snap["id"], "reason": "late dispute",
         "expected_business_version": get_business(business["id"])["version"]},
        make_business_rep_headers(business["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)
    rows, meta = validate_paginated(api.list_rating_disputes(
        business["id"], make_business_rep_headers(business["id"])))
    assert rows == [] and meta["total_count"] == 0


def test_scam_report_publish_twice_rejected(api):
    """PRD §3.8: "A `BureauAdmin` publishes a report that is in `RECEIVED` —
    publishing from any other state is rejected with
    `ERR_SCAM_REPORT_INVALID_STATE` — at which point the report becomes
    `PUBLISHED` with `published_at` stamped, the business's
    `published_scam_count_12m` (the count of its `PUBLISHED` reports whose
    `published_at` falls within the trailing 365 days) recomputes, and the
    provisional rating regenerates."

    Design: Corner/state_machines/scam_report_publish_twice_rejected
    """
    _bureau, consumer, business = _large_world_with_consumer()
    report = publish_scam_report(file_scam_report(consumer, business))
    assert report["status"] == "PUBLISHED"
    first_published_at = report["published_at"]
    resp = api.publish_scam_report(report["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_SCAM_REPORT_INVALID_STATE)
    rows, _meta = validate_paginated(
        api.list_scam_reports(business["id"], ADMIN))
    current = _rows_by_id(rows, report["id"])
    assert current["published_at"] == first_published_at
    assert get_business(business["id"])["published_scam_count_12m"] == 1


def test_ad_review_conclude_twice_rejected(api):
    """PRD §3.8: "Concluding a review belongs to `StandardsReviewer` alone and
    requires the review to be in `UNDER_REVIEW`; concluding from any other
    state is rejected with `ERR_AD_REVIEW_INVALID_STATE`."

    Design: Corner/state_machines/ad_review_conclude_twice_rejected
    """
    _bureau, _consumer, business = _large_world_with_consumer()
    review = open_advertising_review(business, claim_description="eco claim")
    conclude_advertising_review(review, outcome="CLEARED")
    resp = api.conclude_advertising_review(
        review["id"], conclude_review_deceptive_payload(regulator_name="FTC"),
        REVIEWER)
    validate_error(resp, ApiErrorId.ERR_AD_REVIEW_INVALID_STATE)
    rows, _meta = validate_paginated(
        api.list_advertising_reviews(business["id"], ADMIN))
    current = _rows_by_id(rows, review["id"])
    assert current["status"] == "CLEARED"
    assert current["regulator_name"] is None


def test_second_active_application_rejected(api):
    """PRD §3.2: "A business may have at most one live application: while any
    application of the business sits in `DRAFT`, `SUBMITTED`, or
    `APPROVED_PENDING_DUES`, creating another is rejected with
    `ERR_APPLICATION_ALREADY_ACTIVE`."

    Design: Corner/state_machines/second_active_application_rejected
    """
    _bureau, business = _micro_world()
    create_application(business, billing_plan="ANNUAL_PREPAID",
                       license_number="LIC-M-1")
    resp = api.create_accreditation_application(
        business["id"],
        create_application_payload(billing_plan="QUARTERLY",
                                   license_number="LIC-M-2"),
        make_business_rep_headers(business["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_ALREADY_ACTIVE)
    rows, meta = validate_paginated(api.list_accreditation_applications(
        business["id"], make_business_rep_headers(business["id"])))
    assert len(rows) == 1 and meta["total_count"] == 1


def test_submit_boundary_business_age_exactly_183_days(api):
    """PRD §3.2: "Eligibility is gated on age: the business must be at least
    183 days old at the submit instant, meaning `founded_on` falls no later
    than 183 days before now; a younger business is rejected with
    `ERR_BUSINESS_TOO_YOUNG` (HTTP 422)."

    Design: Corner/state_machines/submit_boundary_business_age_exactly_183_days
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    # 2026-03-02 -> 2026-09-01 is exactly 183 days; 2026-03-03 is 182.
    exact = create_business(legal_name="Exact Age LLC", home_state_code="IA",
                            employee_count=3,
                            founded_on="2026-03-02T00:00:00Z")
    younger = create_business(legal_name="One Day Younger LLC",
                              home_state_code="IA", employee_count=3,
                              founded_on="2026-03-03T00:00:00Z")
    app_exact = create_application(exact, license_number="LIC-Y")
    app_younger = create_application(younger, license_number="LIC-X")
    resp = api.submit_application(
        app_younger["id"], make_business_rep_headers(younger["id"]))
    validate_error(resp, ApiErrorId.ERR_BUSINESS_TOO_YOUNG)
    resp = api.submit_application(
        app_exact["id"], make_business_rep_headers(exact["id"]))
    assert validate_success(resp, 200)["status"] == "SUBMITTED"
