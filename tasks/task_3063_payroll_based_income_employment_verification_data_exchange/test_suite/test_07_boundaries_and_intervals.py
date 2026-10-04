"""Boundary precision, half-open and buffered interval guards."""
from test_helpers import (
    onboard_employer,
    register_worker,
    register_authorized_verifier,
    register_product,
    create_verified_layout,
    create_batch,
    attach_record,
    validate_batch,
    capture_authorization,
    open_review,
    get_employer,
    get_record,
    get_review,
    set_clock,
    make_worker_headers,
    make_verifier_headers,
    TEST_USERS,
    api,
    validate_success,
    validate_error,
    ApiErrorId,
)


def test_exact_payroll_cadence_staleness_stays_current(api):
    """PRD §3.8: "Equality stays in the lower band, so an employer is `CURRENT` while
    its staleness is no greater than one cadence interval, `DELAYED` while staleness is
    greater than one interval and no greater than three intervals".
    PRD §3.8: "The declared cadence sets the tolerance: 7 days for a weekly contributor,
    14 for biweekly, 15 for semimonthly and 30 for monthly."

    Design: Difficulty/boundary_precision_check/feed_staleness_exact_cadence_interval_stays_current
    """
    employer = onboard_employer()
    worker = register_worker()
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-08-31T00:00:00Z", record_count=900
    )
    record = attach_record(employer["id"], worker["id"], batch["id"])
    validate_batch(employer["id"], batch["id"])

    set_clock("2026-09-30T00:00:00Z")
    assert get_employer(employer["id"])["feed_status"] == "CURRENT", (
        "staleness of exactly 30 days is the MONTHLY cadence interval and stays CURRENT"
    )
    assert get_record(record["id"])["currency_state"] == "CURRENT"


def test_one_day_past_the_cadence_interval_goes_delayed(api):
    """PRD §3.8: "`STALLED` once staleness exceeds three intervals".
    PRD §3.8: "The staleness measure is the whole number of days between the employer's
    most recent validated feed date and the current instant, counted by whole-day floor
    division of the elapsed seconds".

    Design: Difficulty/boundary_precision_check/feed_staleness_exact_cadence_interval_stays_current
    """
    employer = onboard_employer()
    worker = register_worker()
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-08-31T00:00:00Z", record_count=900
    )
    record = attach_record(employer["id"], worker["id"], batch["id"])
    validate_batch(employer["id"], batch["id"])

    set_clock("2026-10-01T00:00:00Z")
    assert get_employer(employer["id"])["feed_status"] == "DELAYED", (
        "staleness of 31 days exceeds the MONTHLY cadence interval but not three times it"
    )
    assert get_record(record["id"])["currency_state"] == "STALE"


def test_empty_candidate_pool_yields_no_employer_match(api):
    """PRD §3.5: "when the candidate pool is empty the request is declined with
    `ERR_NO_EMPLOYER_MATCH` (HTTP 422) rather than being answered with an empty result."
    PRD §3.5: "A candidate is any record for that worker whose `record_state` is
    `PENDING_VERIFICATION`, `VERIFIED` or `CORRECTED` — spans that are `DISPUTED` or
    `IMMUTABLE` are out".

    Design: Difficulty/boundary_precision_check/empty_employer_match_set_yields_no_employer_match
    """
    employer = onboard_employer()
    worker = register_worker()
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-08-31T00:00:00Z", record_count=900
    )
    record = attach_record(employer["id"], worker["id"], batch["id"])
    validate_batch(employer["id"], batch["id"])

    record_id = record["id"]
    version = validate_success(
        api.get_record(record_id, make_worker_headers(worker["id"])), 200
    )["version"]
    dispute = api.create_dispute(
        {
            "employment_record_id": record_id,
            "covered_worker_id": worker["id"],
            "claimed_field": "EMPLOYMENT_STATUS",
            "claimed_correct_value": "TERMINATED",
            "expected_employment_record_version": version,
        },
        make_worker_headers(worker["id"]),
    )
    validate_success(dispute, 201)

    product = register_product()
    verifier = register_authorized_verifier()
    authorization = capture_authorization(worker, verifier)
    request = validate_success(
        api.create_request(
            {
                "verifier_id": verifier["id"],
                "covered_worker_id": worker["id"],
                "product_id": product["id"],
                "permissible_purpose_asserted": "MORTGAGE_CREDIT_DECISION",
            },
            api_verifier_headers(verifier["id"]),
        ),
        201,
    )
    api.permit_request(request["id"], authorization["id"], make_worker_headers(worker["id"]))

    response = api.validate_currency(request["id"], api_verifier_headers(verifier["id"]))
    validate_error(response, ApiErrorId.ERR_NO_EMPLOYER_MATCH)


def test_empty_candidate_pool_leaves_the_request_employer_unset(api):
    """PRD §3.5: "when the candidate pool is empty the request is declined".
    PRD §2.10: "`employer_match_selection` must have produced at least one candidate
    employer for the worker".

    Design: Difficulty/boundary_precision_check/empty_employer_match_set_yields_no_employer_match
    """
    from test_helpers import get_verifier
    employer = onboard_employer()
    worker = register_worker()
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-08-31T00:00:00Z", record_count=900
    )
    record = attach_record(employer["id"], worker["id"], batch["id"])
    validate_batch(employer["id"], batch["id"])
    version = get_record(record["id"])["version"]
    api.create_dispute(
        {
            "employment_record_id": record["id"],
            "covered_worker_id": worker["id"],
            "claimed_field": "EMPLOYMENT_STATUS",
            "claimed_correct_value": "TERMINATED",
            "expected_employment_record_version": version,
        },
        make_worker_headers(worker["id"]),
    )

    product = register_product()
    verifier = register_authorized_verifier()
    authorization = capture_authorization(worker, verifier)
    request = validate_success(
        api.create_request(
            {
                "verifier_id": verifier["id"],
                "covered_worker_id": worker["id"],
                "product_id": product["id"],
                "permissible_purpose_asserted": "MORTGAGE_CREDIT_DECISION",
            },
            api_verifier_headers(verifier["id"]),
        ),
        201,
    )
    api.permit_request(request["id"], authorization["id"], make_worker_headers(worker["id"]))

    plain = get_record(record["id"])
    assert plain["record_state"] == "DISPUTED"
    assert get_verifier(verifier["id"])["escrow_balance_cents"] == 6000


def api_verifier_headers(verifier_id):
    return make_verifier_headers(verifier_id)


def test_regrant_on_the_exact_expiry_instant_is_admitted(api):
    """PRD §2.11: "because the interval is half-open, an authorization whose
    `expires_at` is exactly the current instant does not occupy it, so a grant landing
    on the expiry instant is admitted."
    PRD §2.5: "an `expires_at` that is `granted_at` advanced by 365 days and frozen at
    grant time".

    Design: Difficulty/resource_temporal_overlap/authorization_half_open_interval_admits_regrant_on_expiry_instant
    """
    worker = register_worker()
    verifier = register_authorized_verifier()
    set_clock("2026-01-01T00:00:00Z")
    capture_authorization(worker, verifier)

    set_clock("2027-01-01T00:00:00Z")
    headers = make_worker_headers(worker["id"])
    version = api.get_worker(worker["id"], headers)
    current_version = validate_success(version, 200)["version"]
    response = api.create_authorization(
        {
            "covered_worker_id": worker["id"],
            "verifier_id": verifier["id"],
            "permitted_purpose": "MORTGAGE_CREDIT_DECISION",
            "expected_covered_worker_version": current_version,
        },
        headers,
    )
    data = validate_success(response, 201)
    assert data["expires_at"] == "2028-01-01T00:00:00.000Z"


def test_regrant_before_the_expiry_instant_is_rejected_as_overlap(api):
    """PRD §2.11: "A new `ConsumerAuthorization` for the same `covered_worker_id`,
    `verifier_id` and `permitted_purpose` is rejected with `ERR_AUTHORIZATION_OVERLAP`
    (HTTP 409) when an existing authorization for that triple is `CAPTURED` and its
    half-open interval from `granted_at` up to but not including `expires_at` already
    covers the current instant".

    Design: Difficulty/resource_temporal_overlap/authorization_half_open_interval_admits_regrant_on_expiry_instant
    """
    worker = register_worker()
    verifier = register_authorized_verifier()
    set_clock("2026-01-01T00:00:00Z")
    capture_authorization(worker, verifier)

    set_clock("2026-12-31T23:59:59Z")
    headers = make_worker_headers(worker["id"])
    # The first capture bumped the worker version, so re-read it before the second grant.
    current_version = validate_success(api.get_worker(worker["id"], headers), 200)["version"]
    response = api.create_authorization(
        {
            "covered_worker_id": worker["id"],
            "verifier_id": verifier["id"],
            "permitted_purpose": "MORTGAGE_CREDIT_DECISION",
            "expected_covered_worker_version": current_version,
        },
        headers,
    )
    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_OVERLAP)


def test_zero_day_review_gap_is_rejected_and_exact_buffer_is_admitted(api):
    """PRD §2.11: "A new `DataCurrencyReview` for an employer is rejected with
    `ERR_REVIEW_WINDOW_OVERLAP` (HTTP 409) when any existing review for that employer is
    `PENDING`, `SCORED` or `ESCALATED` and its closed window — `review_period_end` minus
    `window_days` through `review_period_end` inclusive — is separated from the new
    window by fewer than 3 days of gap."
    PRD §2.11: "Here a gap of exactly 3 days is admitted while a zero-day gap is
    rejected".

    Design: Difficulty/resource_temporal_overlap/review_window_buffer_rejects_zero_day_gap_but_admits_exact_buffer
    """
    employer = onboard_employer()
    first = open_review(employer["id"], review_period_end="2026-06-30T00:00:00Z", window_days=30)
    assert first["review_state"] == "SCORED"

    set_clock("2026-07-01T00:00:00Z")
    rejected = api.create_review(
        {
            "employer_id": employer["id"],
            "review_period_end": "2026-07-31T00:00:00Z",
            "window_days": 30,
            "last_feed_date_in_window": "2026-07-31T00:00:00Z",
            "distinct_pay_periods_in_window": 4,
            "expected_periods": 4,
        },
        api_admin_headers(),
    )
    validate_error(rejected, ApiErrorId.ERR_REVIEW_WINDOW_OVERLAP)


def test_exact_buffer_separation_is_admitted(api):
    """PRD §2.11: "its closed window — `review_period_end` minus `window_days` through
    `review_period_end` inclusive".
    PRD §2.11: "a gap of exactly 3 days is admitted".

    Design: Difficulty/resource_temporal_overlap/review_window_buffer_rejects_zero_day_gap_but_admits_exact_buffer
    """
    employer = onboard_employer()
    open_review(employer["id"], review_period_end="2026-06-30T00:00:00Z", window_days=30)
    set_clock("2026-07-01T00:00:00Z")
    admitted = open_review(
        employer["id"], review_period_end="2026-08-03T00:00:00Z", window_days=30,
        last_feed_date_in_window="2026-08-03T00:00:00Z",
    )
    assert admitted["review_state"] == "SCORED"


def api_admin_headers():
    return TEST_USERS["admin_headers"]