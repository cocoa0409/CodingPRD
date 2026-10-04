"""Verification request lifecycle: quotes, payment, expiry, fulfillment."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error,
    advance_clock, setup_student_with_file, setup_vetted_requester,
    create_requester, create_degree_request, pay_request,
    create_verification_request_payload, create_request,
    make_requester_headers, make_learner_headers, get_requester_balance,
)

OPS = TEST_USERS["ops_headers"]


def _commerce_scene(api):
    """Student at a compliant institution; period OPEN at the default
    clock."""
    return setup_student_with_file(
        advance_to=None, term_label="Early Fall 2026", term_start="2026-08-01",
        submission_opens_at="2026-08-15",
    )


def _expired_quote_scene(api, credit):
    """A DEGREE request created at the default clock 2026-09-01 whose quote
    then expires at 2026-09-03T00:00:00Z."""
    ctx = _commerce_scene(api)
    rq = setup_vetted_requester(credit=credit)
    req = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    ctx["requester_id"] = rq["id"]
    ctx["request"] = req
    return ctx


def test_quote_expiry_timestamp_is_48_hours(api):
    """PRD section 3.7: "The quote also stamps `quote_expires_at` at 48
    hours after creation; the tier, the fee, and the expiry never move
    afterward".
    PRD section 2.4: "Before any clock operation has been called, the
    logical clock reads exactly 2026-09-01T00:00:00Z."

    Design: Difficulty/priority_pair_validation_conflict/pay_expired_quote_preempts_insufficient_credit
    """
    ctx = _expired_quote_scene(api, credit=0)
    assert ctx["request"]["quote_expires_at"] == "2026-09-03T00:00:00Z", (
        "created at the pinned default 2026-09-01T00:00:00Z plus 48 hours"
    )
    assert ctx["request"]["status"] == "QUOTED"


def test_pay_on_expired_quote_reports_expiry(api):
    """PRD section 3.7: "Paying requires the request still be `QUOTED` — a
    request that has already expired reports the specific cause,
    `ERR_QUOTE_EXPIRED` (HTTP 409) — and requires the current instant to be
    strictly before `quote_expires_at`. The requester's
    `credit_balance_cents` must be at least `fee_cents`, otherwise
    `ERR_INSUFFICIENT_CREDIT` (HTTP 402)".
    PRD section 2.8: "Every request is evaluated against an ordered cascade
    of checks, and the first failure wins: its error is the response."

    Design: Difficulty/priority_pair_validation_conflict/pay_expired_quote_preempts_insufficient_credit
    """
    ctx = _expired_quote_scene(api, credit=0)
    advance_clock("2026-09-03T00:00:00Z")
    resp = api_client.pay_verification_request(
        ctx["request"]["id"], make_requester_headers(ctx["requester_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)


def test_quote_expires_at_ttl_boundary(api):
    """PRD section 3.7: "Should the clock reach `quote_expires_at` first, a
    still-`QUOTED` request moves to `EXPIRED` instead."

    Design: Corner/state_machines/quote_expires_at_ttl_boundary
    """
    ctx = _expired_quote_scene(api, credit=100000)
    assert ctx["request"]["quote_expires_at"] == "2026-09-03T00:00:00Z"
    advance_clock("2026-09-03T00:00:00Z")
    req = validate_success(
        api_client.get_verification_request(ctx["request"]["id"], OPS), 200,
    )
    assert req["status"] == "EXPIRED", "at exactly the expiry instant"


def test_expired_quote_allows_identical_new_request(api):
    """PRD section 3.7: "Duplicate suppression comes next: an in-flight
    request — `QUOTED` or `PAID` — with the same (`requester_id`,
    `student_id`, `institution_id`, `product_type`, `purpose`) is rejected
    with `ERR_DUPLICATE_REQUEST` (HTTP 409)."
    PRD section 3.7: "the fee is never re-quoted, and an expired quote
    forces a brand-new request."

    Design: Corner/endpoints/expired_quote_allows_identical_new_request
    """
    ctx = _expired_quote_scene(api, credit=100000)
    advance_clock("2026-09-03T00:00:00Z")
    stale = validate_success(
        api_client.get_verification_request(ctx["request"]["id"], OPS), 200,
    )
    assert stale["status"] == "EXPIRED"
    fresh = create_degree_request(
        ctx["inst_id"], ctx["student_id"], ctx["requester_id"],
    )
    assert fresh["status"] == "QUOTED"
    assert fresh["id"] != ctx["request"]["id"], (
        "EXPIRED is not in-flight, so no duplicate rejection fires"
    )


def test_err_insufficient_credit_on_pay(api):
    """PRD section 3.7: "The requester's `credit_balance_cents` must be at
    least `fee_cents`, otherwise `ERR_INSUFFICIENT_CREDIT` (HTTP 402)".

    Design: Corner/errors/err_insufficient_credit_on_pay
    """
    ctx = _commerce_scene(api)
    rq = setup_vetted_requester(credit=1000)
    req = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    assert req["fee_cents"] == 2599
    resp = api_client.pay_verification_request(
        req["id"], make_requester_headers(rq["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)
    current = validate_success(
        api_client.get_verification_request(req["id"], OPS), 200,
    )
    assert current["status"] == "QUOTED"
    assert get_requester_balance(rq["id"]) == 1000, "no debit on failure"


def test_pay_already_paid_request_rejected(api):
    """PRD section 3.7: "Paying requires the request still be `QUOTED`".
    PRD section 2.9: "an action fired against a resource in the wrong state
    — including re-firing an action whose effect has already been applied,
    or acting on a resource in a terminal state — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/pay_already_paid_request_rejected
    """
    ctx = _commerce_scene(api)
    rq = setup_vetted_requester(credit=100000)
    req = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    pay_request(req["id"], rq["id"])
    resp = api_client.pay_verification_request(
        req["id"], make_requester_headers(rq["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_requester_balance(rq["id"]) == 97401, (
        "the balance is debited exactly once"
    )


def test_fulfill_quoted_request_rejected(api):
    """PRD section 3.7: "When both gates pass, the request moves `PAID` →
    `RELEASED`".
    PRD section 2.9: "an action fired against a resource in the wrong state
    — including re-firing an action whose effect has already been applied,
    or acting on a resource in a terminal state — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/fulfill_quoted_request_rejected
    """
    ctx = _commerce_scene(api)
    rq = setup_vetted_requester(credit=100000)
    req = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    resp = api_client.fulfill_verification_request(req["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = validate_success(
        api_client.get_verification_request(req["id"], OPS), 200,
    )
    assert current["status"] == "QUOTED"


def test_err_duplicate_request_while_quoted_and_paid(api):
    """PRD section 3.7: "Duplicate suppression comes next: an in-flight
    request — `QUOTED` or `PAID` — with the same (`requester_id`,
    `student_id`, `institution_id`, `product_type`, `purpose`) is rejected
    with `ERR_DUPLICATE_REQUEST` (HTTP 409)."

    Design: Corner/errors/err_duplicate_request_while_quoted_and_paid
    """
    ctx = _commerce_scene(api)
    rq = setup_vetted_requester(credit=100000)
    req = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    while_quoted = api_client.create_verification_request(
        create_verification_request_payload(
            ctx["student_id"], ctx["inst_id"], requester_id=rq["id"],
        ),
        make_requester_headers(rq["id"]),
    )
    validate_error(while_quoted, ApiErrorId.ERR_DUPLICATE_REQUEST)
    pay_request(req["id"], rq["id"])
    while_paid = api_client.create_verification_request(
        create_verification_request_payload(
            ctx["student_id"], ctx["inst_id"], requester_id=rq["id"],
        ),
        make_requester_headers(rq["id"]),
    )
    validate_error(while_paid, ApiErrorId.ERR_DUPLICATE_REQUEST)


def test_transcript_release_sets_artifact_expiry(api):
    """PRD section 3.7: "The base fee is 2599 cents for `DEGREE`, 1599 cents
    for `ENROLLMENT`, and 0 cents for `TRANSCRIPT`."
    PRD section 3.7: "When both gates pass, the request moves `PAID` →
    `RELEASED`: `released_at` is stamped; `result_status` becomes
    `VERIFIED`".
    PRD section 3.7: "a `TRANSCRIPT` release stamps `artifact_expires_at` at
    72 hours after release — the informational expiry of the electronic
    delivery artifact."

    Design: Corner/state_machines/transcript_release_sets_artifact_expiry
    """
    ctx = _commerce_scene(api)
    payload = create_verification_request_payload(
        ctx["student_id"], ctx["inst_id"],
        product_type="TRANSCRIPT", purpose="SELF",
    )
    resp = create_request(payload, as_student_id=ctx["student_id"])
    req = validate_success(resp, 201)
    assert req["fee_cents"] == 0
    paid = pay_request(req["id"], ctx["student_id"], learner=True)
    assert paid["status"] == "PAID"
    released = validate_success(
        api_client.fulfill_verification_request(req["id"], OPS), 200,
    )
    assert released["status"] == "RELEASED"
    assert released["result_status"] == "VERIFIED"
    assert released["released_at"] == "2026-09-01T00:00:00Z"
    assert released["artifact_expires_at"] == "2026-09-04T00:00:00Z", (
        "released at the pinned default clock plus 72 hours"
    )


def test_err_request_not_found(api):
    """PRD section 2.8: "Each kind of unresolved reference reports its own
    error — `ERR_INSTITUTION_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_DEGREE_NOT_FOUND`, `ERR_REQUESTER_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, or
    `ERR_DATASET_NOT_FOUND`, each HTTP 404".

    Design: Corner/errors/err_request_not_found
    """
    rq = create_requester()
    resp = api_client.pay_verification_request(
        NON_EXISTENT_UUID, make_requester_headers(rq["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_FOUND)
