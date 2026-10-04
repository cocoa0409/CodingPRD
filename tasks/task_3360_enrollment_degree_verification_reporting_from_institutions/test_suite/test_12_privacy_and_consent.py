"""Verification privacy gates, consent matrix, and ownership scoping."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error, validate_paginated,
    setup_student_with_file, setup_uploaded_file, setup_vetted_requester,
    create_degree_request, pay_request, fulfill_request, place_directive,
    get_requester_balance, create_verification_request_payload,
    create_request, enrollment_row, get_student_version,
    create_directive_payload,
    make_requester_headers, make_learner_headers,
)

OPS = TEST_USERS["ops_headers"]


def _commerce_scene(api):
    return setup_student_with_file(
        advance_to=None, term_label="Early Fall 2026", term_start="2026-08-01",
        submission_opens_at="2026-08-15",
    )


def test_full_block_preempts_duplicate_request(api):
    """PRD section 3.7: "Privacy is checked at creation, before money moves.
    The creation-time privacy gate rejects with `ERR_PRIVACY_BLOCKED`
    (HTTP 422) when an active `FULL_BLOCK` directive covers the student —
    for any product other than the learner's own `TRANSCRIPT` self-order,
    which is exempt — or when an active `DIRECTORY_BLOCK` covers a `DEGREE`
    request."
    PRD section 3.7: "Duplicate suppression comes next: an in-flight request
    — `QUOTED` or `PAID` — with the same (`requester_id`, `student_id`,
    `institution_id`, `product_type`, `purpose`) is rejected with
    `ERR_DUPLICATE_REQUEST` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/create_privacy_block_preempts_duplicate_request
    """
    ctx = _commerce_scene(api)
    rq = setup_vetted_requester(credit=100000)
    create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    place_directive(ctx["student_id"], directive_type="FULL_BLOCK")
    resp = api_client.create_verification_request(
        create_verification_request_payload(
            ctx["student_id"], ctx["inst_id"], requester_id=rq["id"],
        ),
        make_requester_headers(rq["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRIVACY_BLOCKED)


def test_full_block_alone_blocks_create(api):
    """PRD section 3.8: "A `FULL_BLOCK` blocks all non-self verification of
    the student."
    PRD section 3.7: "The creation-time privacy gate rejects with
    `ERR_PRIVACY_BLOCKED` (HTTP 422) when an active `FULL_BLOCK` directive
    covers the student".

    Design: Difficulty/priority_pair_validation_conflict/create_privacy_block_preempts_duplicate_request
    """
    ctx = _commerce_scene(api)
    rq = setup_vetted_requester(credit=100000)
    place_directive(ctx["student_id"], directive_type="FULL_BLOCK")
    resp = api_client.create_verification_request(
        create_verification_request_payload(
            ctx["student_id"], ctx["inst_id"], requester_id=rq["id"],
        ),
        make_requester_headers(rq["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRIVACY_BLOCKED)


def _blocked_privacy_scene(api):
    """A PAID DEGREE request (10000 balance, fee 2599 debited) with a
    DIRECTORY_BLOCK placed on the student after payment."""
    ctx = _commerce_scene(api)
    rq = setup_vetted_requester(credit=10000)
    req = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    pay_request(req["id"], rq["id"])
    place_directive(ctx["student_id"], directive_type="DIRECTORY_BLOCK")
    ctx["requester_id"] = rq["id"]
    ctx["request_id"] = req["id"]
    return ctx


def test_blocked_privacy_refunds_full_fee(api):
    """PRD section 3.7: "The privacy gate fails — moving the request `PAID`
    → `BLOCKED_PRIVACY` — when an active `FULL_BLOCK` covers the student
    (the learner's own `TRANSCRIPT` self-order is exempt), when an active
    `DIRECTORY_BLOCK` covers a `DEGREE` request".
    PRD section 3.7: "Both failure branches refund in full: `refund_cents`
    is set to `fee_cents` and credited back to the requester's
    `credit_balance_cents`".

    Design: Difficulty/compensating_invariant/failed_fulfillment_refund_conserves_balance
    """
    ctx = _blocked_privacy_scene(api)
    assert get_requester_balance(ctx["requester_id"]) == 7401, (
        "10000 minus the 2599 fee"
    )
    resp = api_client.fulfill_verification_request(ctx["request_id"], OPS)
    req = validate_success(resp, 200)
    assert req["status"] == "BLOCKED_PRIVACY"
    assert req["refund_cents"] == 2599


def test_blocked_privacy_conserves_balance(api):
    """PRD section 3.7: "Both failure branches refund in full: `refund_cents`
    is set to `fee_cents` and credited back to the requester's
    `credit_balance_cents`".
    PRD section 3.7: "The balance is a simple ledger: `credit_balance_cents`
    begins at `initial_credit_cents`, is debited by payments, and is
    credited by refunds".

    Design: Difficulty/compensating_invariant/failed_fulfillment_refund_conserves_balance
    """
    ctx = _blocked_privacy_scene(api)
    validate_success(
        api_client.fulfill_verification_request(ctx["request_id"], OPS), 200,
    )
    assert get_requester_balance(ctx["requester_id"]) == 10000, (
        "the debit and the compensating credit conserve the balance"
    )


def test_consent_required_for_employment_enrollment(api):
    """PRD section 3.7: "The consent gate follows, rejecting with
    `ERR_CONSENT_REQUIRED` (HTTP 422) when an `ENROLLMENT` request for
    purpose `EMPLOYMENT` or `BACKGROUND_SCREEN` lacks `consent_artifact` set
    to true — even with no directive on the student".
    PRD section 3.7: "The `consent_artifact` flag itself defaults to false,
    as does `rush`."

    Design: Corner/validations/consent_required_for_employment_enrollment
    """
    ctx = _commerce_scene(api)
    rq = setup_vetted_requester(credit=100000)
    omitted = api_client.create_verification_request(
        create_verification_request_payload(
            ctx["student_id"], ctx["inst_id"], requester_id=rq["id"],
            product_type="ENROLLMENT", purpose="EMPLOYMENT",
        ),
        make_requester_headers(rq["id"]),
    )
    validate_error(omitted, ApiErrorId.ERR_CONSENT_REQUIRED)
    explicit_false = api_client.create_verification_request(
        create_verification_request_payload(
            ctx["student_id"], ctx["inst_id"], requester_id=rq["id"],
            product_type="ENROLLMENT", purpose="EMPLOYMENT",
            consent_artifact=False,
        ),
        make_requester_headers(rq["id"]),
    )
    validate_error(explicit_false, ApiErrorId.ERR_CONSENT_REQUIRED)


def test_purpose_matrix_denials(api):
    """PRD section 3.7: "an `EMPLOYER` may purchase for purposes
    `EMPLOYMENT` and `INSURANCE`; a `BACKGROUND_SCREENER` may purchase for
    `EMPLOYMENT` and `BACKGROUND_SCREEN`; `LOAN_DEFERMENT` is purchasable by
    neither kind; `TRANSCRIPT` with `SELF` is Learner-only, while `DEGREE`
    and `ENROLLMENT` are Requester-only — any other combination of role,
    product, and purpose is rejected with `ERR_PURPOSE_NOT_PERMITTED`
    (HTTP 422)."

    Design: Corner/validations/purpose_matrix_denials
    """
    ctx = _commerce_scene(api)
    employer = setup_vetted_requester(credit=100000, org="Acme Hiring")
    screener = setup_vetted_requester(
        credit=100000, kind="BACKGROUND_SCREENER", org="Screen Co",
    )

    def attempt(requester_id, purpose, product="DEGREE"):
        return api_client.create_verification_request(
            create_verification_request_payload(
                ctx["student_id"], ctx["inst_id"], requester_id=requester_id,
                product_type=product, purpose=purpose,
            ),
            make_requester_headers(requester_id),
        )

    validate_error(
        attempt(employer["id"], "BACKGROUND_SCREEN"),
        ApiErrorId.ERR_PURPOSE_NOT_PERMITTED,
    )
    validate_error(
        attempt(screener["id"], "INSURANCE"),
        ApiErrorId.ERR_PURPOSE_NOT_PERMITTED,
    )
    validate_error(
        attempt(employer["id"], "LOAN_DEFERMENT", product="ENROLLMENT"),
        ApiErrorId.ERR_PURPOSE_NOT_PERMITTED,
    )


def test_product_role_mismatch_denied(api):
    """PRD section 3.7: "`TRANSCRIPT` with `SELF` is Learner-only, while
    `DEGREE` and `ENROLLMENT` are Requester-only — any other combination of
    role, product, and purpose is rejected with `ERR_PURPOSE_NOT_PERMITTED`
    (HTTP 422)."

    Design: Corner/validations/product_role_mismatch_denied
    """
    ctx = _commerce_scene(api)
    rq = setup_vetted_requester(credit=100000)
    as_requester = api_client.create_verification_request(
        create_verification_request_payload(
            ctx["student_id"], ctx["inst_id"], requester_id=rq["id"],
            product_type="TRANSCRIPT", purpose="SELF",
        ),
        make_requester_headers(rq["id"]),
    )
    validate_error(as_requester, ApiErrorId.ERR_PURPOSE_NOT_PERMITTED)
    as_learner = api_client.create_verification_request(
        create_verification_request_payload(
            ctx["student_id"], ctx["inst_id"], product_type="DEGREE",
            purpose="EMPLOYMENT",
        ),
        make_learner_headers(ctx["student_id"]),
    )
    validate_error(as_learner, ApiErrorId.ERR_PURPOSE_NOT_PERMITTED)


def test_directory_block_blocks_degree_but_not_consented_enrollment(api):
    """PRD section 3.8: "A `DIRECTORY_BLOCK` blocks the `DEGREE` product
    outright and blocks `ENROLLMENT` unless the requester attests signed
    consent via `consent_artifact`."
    PRD section 3.7: "The creation-time privacy gate rejects with
    `ERR_PRIVACY_BLOCKED` (HTTP 422) when an active `FULL_BLOCK` directive
    covers the student — for any product other than the learner's own
    `TRANSCRIPT` self-order, which is exempt — or when an active
    `DIRECTORY_BLOCK` covers a `DEGREE` request."

    Design: Corner/validations/directory_block_blocks_degree_create_but_not_consented_enrollment
    """
    ctx = _commerce_scene(api)
    rq = setup_vetted_requester(credit=100000)
    place_directive(ctx["student_id"], directive_type="DIRECTORY_BLOCK")
    degree = api_client.create_verification_request(
        create_verification_request_payload(
            ctx["student_id"], ctx["inst_id"], requester_id=rq["id"],
        ),
        make_requester_headers(rq["id"]),
    )
    validate_error(degree, ApiErrorId.ERR_PRIVACY_BLOCKED)
    enrollment = api_client.create_verification_request(
        create_verification_request_payload(
            ctx["student_id"], ctx["inst_id"], requester_id=rq["id"],
            product_type="ENROLLMENT", purpose="EMPLOYMENT",
            consent_artifact=True,
        ),
        make_requester_headers(rq["id"]),
    )
    req = validate_success(enrollment, 201)
    assert req["status"] == "QUOTED", (
        "DIRECTORY_BLOCK plus ENROLLMENT passes when consent is attested"
    )


def test_err_max_active_transcripts(api):
    """PRD section 3.7: "The rule applies to `DEGREE` and `ENROLLMENT` only,
    because `TRANSCRIPT` self-orders are repeat-orderable and are governed
    instead by the active-transcript cap: a learner who already holds two
    `TRANSCRIPT` requests in `QUOTED` or `PAID` status is rejected with
    `ERR_MAX_ACTIVE_TRANSCRIPTS` (HTTP 409)."

    Design: Corner/errors/err_max_active_transcripts
    """
    ctx = _commerce_scene(api)

    def transcript():
        return api_client.create_verification_request(
            create_verification_request_payload(
                ctx["student_id"], ctx["inst_id"],
                product_type="TRANSCRIPT", purpose="SELF",
            ),
            make_learner_headers(ctx["student_id"]),
        )

    t1 = validate_success(transcript(), 201)
    validate_success(transcript(), 201)
    third = transcript()
    validate_error(third, ApiErrorId.ERR_MAX_ACTIVE_TRANSCRIPTS)
    pay_request(t1["id"], ctx["student_id"], learner=True)
    fulfill_request(t1["id"])
    after_release = transcript()
    assert validate_success(after_release, 201)["status"] == "QUOTED", (
        "with T1 RELEASED, only one active transcript remains"
    )


def test_rbac_requester_cannot_pay_others_request(api):
    """PRD section 2.1: "A requester reads its own account only and acts
    only on its own verification requests: any request whose `requester_id`
    does not equal `X-User-ID` is out of scope and is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/rbac_requester_cannot_pay_others_request
    """
    ctx = _commerce_scene(api)
    ra = setup_vetted_requester(credit=100000, org="A Corp")
    rb = setup_vetted_requester(credit=100000, org="B Corp")
    req_b = create_degree_request(ctx["inst_id"], ctx["student_id"], rb["id"])
    resp = api_client.pay_verification_request(
        req_b["id"], make_requester_headers(ra["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    current = validate_success(
        api_client.get_verification_request(req_b["id"], OPS), 200,
    )
    assert current["status"] == "QUOTED"


def test_rbac_requester_list_scoped_to_own(api):
    """PRD section 3.7: "Verification requests are listed in `created_at`
    ascending order, filtered by `requester_id`, `student_id`,
    `institution_id`, or `status`; a `Requester` caller sees only its own
    requests, and a `Learner` caller only their own."

    Design: Corner/rbac/rbac_requester_list_scoped_to_own
    """
    ctx = _commerce_scene(api)
    ra = setup_vetted_requester(credit=100000, org="A Corp")
    rb = setup_vetted_requester(credit=100000, org="B Corp")
    req_a = create_degree_request(ctx["inst_id"], ctx["student_id"], ra["id"])
    create_degree_request(ctx["inst_id"], ctx["student_id"], rb["id"])
    own, meta_own = validate_paginated(
        api_client.list_verification_requests(make_requester_headers(ra["id"])),
    )
    assert meta_own["total_count"] == 1
    assert own[0]["id"] == req_a["id"]
    _all, meta_all = validate_paginated(
        api_client.list_verification_requests(OPS),
    )
    assert meta_all["total_count"] == 2


def test_rbac_learner_scope_on_other_student(api):
    """PRD section 2.1: "The learner acts only on their own student record,
    whether that record is identified in the path or in the request body's
    `student_id`."
    PRD section 3.8: "A learner reads their own student record and places
    directives only on it — a path or body `student_id` other than the
    caller's own is rejected with `ERR_UNAUTHORIZED`".

    Design: Corner/rbac/rbac_learner_scope_on_other_student
    """
    ctx = setup_uploaded_file(rows=[
        enrollment_row(student_ref="S1", full_name="Ada Lovelace"),
        enrollment_row(student_ref="S2", full_name="Bob Student",
                       date_of_birth="2004-07-01"),
    ])
    s1 = ctx["entries"][0]["student_id"]
    s2 = ctx["entries"][1]["student_id"]
    read = api_client.get_student(s2, make_learner_headers(s1))
    validate_error(read, ApiErrorId.ERR_UNAUTHORIZED)
    s2_version = get_student_version(s2)
    directive = api_client.create_privacy_directive(
        s2,
        create_directive_payload(s2_version),
        make_learner_headers(s1),
    )
    validate_error(directive, ApiErrorId.ERR_UNAUTHORIZED)
