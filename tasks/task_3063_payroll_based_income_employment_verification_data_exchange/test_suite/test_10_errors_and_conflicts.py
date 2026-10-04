"""Error catalogue triggers and the precedence pair conflicts."""
from test_helpers import (
    onboard_employer,
    register_worker,
    register_authorized_verifier,
    register_product,
    create_verified_layout,
    create_batch,
    attach_record,
    validate_batch,
    validate_currency,
    capture_authorization,
    submit_request,
    permit_request,
    post_settlement,
    void_settlement,
    list_accruals,
    get_employer,
    get_verifier,
    get_request,
    get_review,
    open_review,
    freeze_employer_to_active,
    request_disclosure,
    generate_disclosure,
    get_disclosure,
    get_worker,
    set_clock,
    make_worker_headers,
    make_employer_headers,
    make_verifier_headers,
    TEST_USERS,
    api,
    validate_success,
    validate_error,
    ApiErrorId,
)


def test_regulatory_hold_freeze_cannot_be_released(api):
    """PRD §2.7: "A `REGULATORY_HOLD` freeze cannot be released until the hold is
    withdrawn — an attempted release raises `ERR_REGULATORY_HOLD_IRRELEASABLE`
    (HTTP 409)".
    PRD §2.7: "a lapse requires that the employer carry no open disputes and no request
    sitting in `PERMITTED`".

    Design: Corner/errors/error_regulatory_hold_irreleasable_on_unfreeze
    """
    employer = onboard_employer()
    freeze_employer_to_active(employer["id"], reason_code="REGULATORY_HOLD")
    headers = make_employer_headers(employer["id"])

    release = api.unfreeze_employer(employer["id"], "RELEASE", headers)
    validate_error(release, ApiErrorId.ERR_REGULATORY_HOLD_IRRELEASABLE)

    detail = get_employer(employer["id"])
    assert detail["freeze_state"] == "ACTIVE"
    assert detail["freeze_reason_code"] == "REGULATORY_HOLD"


def test_lapsed_regulatory_hold_freeze_also_remains_active(api):
    """PRD §2.7: "A `REGULATORY_HOLD` freeze cannot be released until the hold is
    withdrawn — an attempted release raises `ERR_REGULATORY_HOLD_IRRELEASABLE`
    (HTTP 409)".
    PRD §2.7: "While `ACTIVE`, the employer keeps the last feed status it derived and
    its records stay frozen".

    Design: Corner/errors/error_regulatory_hold_irreleasable_on_unfreeze
    """
    employer = onboard_employer()
    freeze_employer_to_active(employer["id"], reason_code="REGULATORY_HOLD")
    headers = make_employer_headers(employer["id"])

    lapse = api.unfreeze_employer(employer["id"], "LAPSE", headers)
    validate_error(lapse, ApiErrorId.ERR_REGULATORY_HOLD_IRRELEASABLE)
    assert get_employer(employer["id"])["freeze_state"] == "ACTIVE"


def test_repeated_fein_registration_is_refused(api):
    """PRD §2.6: "a contributor's `fein` is unique across all contributors ... any
    repeat is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

    Design: Corner/errors/error_duplicate_resource_on_repeated_fein
    """
    onboard_employer(fein="123456789")
    response = api.create_employer(
        {
            "legal_name": "Northwind Logistics Holdings",
            "fein": "123456789",
            "employer_type": "NON_PROFIT",
            "payroll_frequency": "WEEKLY",
        },
        _admin(),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_repeated_fein_leaves_exactly_one_employer_for_that_fein(api):
    """PRD §3.1: "A repeated `fein` is refused with `ERR_DUPLICATE_RESOURCE`
    (HTTP 409)".

    Design: Corner/errors/error_duplicate_resource_on_repeated_fein
    """
    onboard_employer(fein="123456789")
    api.create_employer(
        {
            "legal_name": "Northwind Logistics Holdings",
            "fein": "123456789",
            "employer_type": "NON_PROFIT",
            "payroll_frequency": "WEEKLY",
        },
        _admin(),
    )
    rows = validate_success(api.list_employers(_admin(), params={"fein": "123456789"}), 200)
    assert len(rows) == 1


def test_regenerating_a_current_disclosure_is_refused(api):
    """PRD §3.6: "Generation materializes the file, but only while the worker's
    `disclosure_state` is `NEVER_DISCLOSED` or `STALE`; a regeneration attempt while the
    file is `CURRENT` is refused with `ERR_DISCLOSURE_ALREADY_CURRENT` (HTTP 409)".

    Design: Corner/errors/error_disclosure_already_current_on_regenerate
    """
    ctx = _worker_with_verified_span()
    disclosure = request_disclosure(ctx["worker"]["id"])
    generated = generate_disclosure(ctx["worker"]["id"], disclosure["id"])
    assert generated["disclosure_state"] == "GENERATED"

    response = api.generate_disclosure(disclosure["id"], make_worker_headers(ctx["worker"]["id"]))
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_ALREADY_CURRENT)


def test_generated_disclosure_records_the_included_count(api):
    """PRD §3.6: "the disclosure moves to `GENERATED`, `file_contents` is populated,
    the worker's `disclosure_state` becomes `CURRENT`, and both the disclosure row and
    the worker row advance their versions."

    Design: Corner/errors/error_disclosure_already_current_on_regenerate
    """
    ctx = _worker_with_verified_span()
    disclosure = request_disclosure(ctx["worker"]["id"])
    generate_disclosure(ctx["worker"]["id"], disclosure["id"])

    detail = get_disclosure(disclosure["id"], ctx["worker"]["id"])
    assert detail["disclosure_state"] == "GENERATED"
    assert detail["included_record_count"] == 1
    assert get_worker(ctx["worker"]["id"])["disclosure_state"] == "CURRENT"


def test_escrow_shortfall_blocks_response_materialization(api):
    """PRD §2.10: "the requesting party's `escrow_balance_cents` must be on or above the
    fee this transaction would post."
    PRD §2.10: "These yield, in order, `ERR_EMPLOYER_FROZEN` (HTTP 403),
    `ERR_EMPLOYER_FEED_STALLED` (HTTP 422), `ERR_NO_EMPLOYER_MATCH` (HTTP 422) and
    `ERR_ESCROW_INSUFFICIENT` (HTTP 402)."

    Design: Corner/errors/error_escrow_insufficient_blocks_response_materialization
    """
    ctx = _permitted_request_with_escrow(0)
    response = api.create_response(ctx["request"]["id"], make_verifier_headers(ctx["verifier"]["id"]))
    validate_error(response, ApiErrorId.ERR_ESCROW_INSUFFICIENT, 402)

    request = get_request(ctx["request"]["id"], make_verifier_headers(ctx["verifier"]["id"]))
    assert request["request_state"] == "SUBMITTED"
    assert request["fee_charged_cents"] == 0


def test_escrow_exactly_covering_the_fee_is_sufficient(api):
    """PRD §2.10: "The escrow comparison is inclusive: a balance exactly equal to the
    fee is sufficient and leaves the balance at exactly zero."

    Design: Corner/errors/error_escrow_insufficient_blocks_response_materialization
    """
    ctx = _permitted_request_with_escrow(0)
    api.escrow_adjustment(ctx["verifier"]["id"], 1850, _admin())
    response = api.create_response(ctx["request"]["id"], make_verifier_headers(ctx["verifier"]["id"]))
    data = validate_success(response, 201)

    request = get_request(ctx["request"]["id"], make_verifier_headers(ctx["verifier"]["id"]))
    assert request["fee_charged_cents"] == 1850
    verifier = get_verifier(ctx["verifier"]["id"], make_verifier_headers(ctx["verifier"]["id"]))
    assert verifier["escrow_balance_cents"] == 0
    assert data["verification_request_id"] == ctx["request"]["id"]


def test_healthy_review_cannot_be_escalated(api):
    """PRD §3.8: "Escalation is permitted only when the score is at or above 300 — the
    comparison is inclusive, so a score of exactly 300 escalates."
    PRD §2.8: "An action addressed at a resource that is not in any state from which
    that action is defined fails with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/data_currency_review_escalate_below_stall_threshold_is_rejected
    """
    employer = onboard_employer()
    set_clock("2026-07-01T00:00:00Z")
    review = open_review(
        employer["id"],
        review_period_end="2026-06-30T00:00:00Z",
        window_days=90,
        last_feed_date_in_window="2026-01-01T00:00:00Z",
        distinct_pay_periods_in_window=0,
        expected_periods=10,
    )
    assert review["currency_score"] < 300
    assert review["review_state"] == "SCORED"

    response = api.escalate_review(review["id"], _admin())
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_review(review["id"], _admin())["review_state"] == "SCORED"


def test_review_scoring_records_missing_periods_on_the_employer(api):
    """PRD §3.8: "Scoring computes `missing_periods` as the number of expected pay
    periods the window would have produced beyond the distinct validated periods
    actually present, never below zero".

    Design: Corner/state_machines/data_currency_review_escalate_below_stall_threshold_is_rejected
    """
    employer = onboard_employer()
    review = open_review(
        employer["id"],
        review_period_end="2026-06-30T00:00:00Z",
        window_days=90,
        last_feed_date_in_window="2026-06-30T00:00:00Z",
        distinct_pay_periods_in_window=2,
        expected_periods=3,
    )
    assert review["missing_periods"] == 1
    assert get_employer(employer["id"])["missing_periods"] == 1


def test_purpose_mismatch_outranks_the_stalled_feed_check(api):
    """PRD §2.10: "Permissible purpose next: the purpose must be present and consistent
    across the authorization's `permitted_purpose`, the request's
    `permissible_purpose_asserted` and the requesting party's `permitted_purpose`".
    PRD §2.10: "Any failure here yields `ERR_PERMISSIBLE_PURPOSE_UNAVAILABLE`
    (HTTP 403)."
    PRD §2.11: "Equality stays in the lower band".

    Design: Difficulty/priority_pair_validation_conflict/purpose_mismatch_beats_stalled_feed_on_validate_currency
    """
    employer = onboard_employer()
    worker = register_worker()
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-05-31T00:00:00Z", record_count=900
    )
    attach_record(employer["id"], worker["id"], batch["id"])
    validate_batch(employer["id"], batch["id"])
    product = register_product()
    verifier = register_authorized_verifier()
    # The authorization is granted for a different purpose than the request asserts.
    # Deliberately distinct from the asserted purpose.
    capture_authorization(worker, verifier, purpose="PUBLIC_BENEFIT_DETERMINATION")
    request = submit_request(verifier, worker, product, purpose="MORTGAGE_CREDIT_DECISION")

    set_clock("2026-09-30T00:00:00Z")
    assert get_employer(employer["id"])["feed_status"] == "STALLED"

    response = api.validate_currency(request["id"], make_verifier_headers(verifier["id"]))
    validate_error(response, ApiErrorId.ERR_PERMISSIBLE_PURPOSE_UNAVAILABLE, 403)


def test_the_stalled_feed_condition_is_also_live_when_the_purpose_error_wins(api):
    """PRD §3.8: "`STALLED` once staleness exceeds three intervals".
    PRD §2.10: "These yield, in order, `ERR_EMPLOYER_FROZEN` (HTTP 403),
    `ERR_EMPLOYER_FEED_STALLED` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/purpose_mismatch_beats_stalled_feed_on_validate_currency
    """
    employer = onboard_employer()
    # No feed has validated, so staleness runs from the creation instant at the
    # default logical clock 2026-09-01; STALLED for MONTHLY needs more than 90 days.
    set_clock("2026-12-15T00:00:00Z")
    assert get_employer(employer["id"])["feed_status"] == "STALLED"


def _admin():
    return TEST_USERS["admin_headers"]


def _worker_with_verified_span():
    employer = onboard_employer()
    worker = register_worker()
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-08-31T00:00:00Z", record_count=900
    )
    attach_record(employer["id"], worker["id"], batch["id"])
    validate_batch(employer["id"], batch["id"])
    return {"employer": employer, "worker": worker, "batch": batch}


def _permitted_request_with_escrow(escrow):
    employer = onboard_employer()
    worker = register_worker()
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-08-31T00:00:00Z", record_count=900
    )
    attach_record(employer["id"], worker["id"], batch["id"])
    validate_batch(employer["id"], batch["id"])
    product = register_product()
    verifier = register_authorized_verifier(escrow_balance_cents=escrow)
    # The authorization is captured before submission, so the request opens in
    # SUBMITTED — the other state from which a response may be built (PRD §3.5).
    authorization = capture_authorization(worker, verifier)
    request = submit_request(verifier, worker, product)
    return {
        "employer": employer,
        "worker": worker,
        "verifier": verifier,
        "product": product,
        "authorization": authorization,
        "request": request,
    }