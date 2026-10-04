"""Institution suspension, reinstatement, and the request-cancellation cascade."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error, validate_paginated,
    create_institution_with_registrars, create_agreement_payload,
    add_agreement, add_period, advance_clock, get_period_version,
    upload_file, certify_file, list_file_entries, setup_student_with_file,
    setup_sealed_degree, setup_vetted_requester, create_degree_request,
    pay_request, get_requester_balance, enrollment_row,
    create_enrollment_file_payload, make_submitter_headers,
    setup_period_scenario,
)

OPS = TEST_USERS["ops_headers"]


def test_institution_suspend_reinstate_guards(api):
    """PRD section 3.1: "An operator may suspend an `ACTIVE` institution
    directly — the request is rejected with `ERR_INVALID_STATE` against
    anything else: the institution becomes `SUSPENDED` with
    `suspension_reason` of `OPS`, its `version` increments".
    PRD section 3.1: "An operator may reinstate a `SUSPENDED` institution
    only when an `ACTIVE` agreement covers the current instant — otherwise
    the reinstatement is rejected with `ERR_AGREEMENT_LAPSED` (HTTP 409) —
    and reinstatement returns the institution to `ACTIVE` with
    `suspension_reason` cleared to `NONE`."
    PRD section 2.9: "an action fired against a resource in the wrong state
    — including re-firing an action whose effect has already been applied,
    or acting on a resource in a terminal state — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/institution_suspend_reinstate_guards
    """
    ctx = create_institution_with_registrars()
    add_agreement(ctx["inst_id"])

    s1 = validate_success(api_client.suspend_institution(ctx["inst_id"], OPS), 200)
    assert s1["status"] == "SUSPENDED"
    assert s1["suspension_reason"] == "OPS"

    again = api_client.suspend_institution(ctx["inst_id"], OPS)
    validate_error(again, ApiErrorId.ERR_INVALID_STATE)

    s2 = validate_success(api_client.reinstate_institution(ctx["inst_id"], OPS), 200)
    assert s2["status"] == "ACTIVE"
    assert s2["suspension_reason"] == "NONE"

    again2 = api_client.reinstate_institution(ctx["inst_id"], OPS)
    validate_error(again2, ApiErrorId.ERR_INVALID_STATE)


def _build_expiry_scene(api):
    # Build manually (not via setup_period_scenario) so the agreement window
    # ends 2027-02-01. All dates sit at or after the pinned default clock
    # (2026-09-01T00:00:00Z, PRD §2.4) so every clock advance moves forward.
    ctx = create_institution_with_registrars()
    add_agreement(ctx["inst_id"],
                  effective_from="2026-08-01", effective_to="2027-02-01")
    ctx["period"] = add_period(
        ctx["inst_id"], term_label="Fall 2026", term_start="2026-10-01",
        term_end="2027-01-15", submission_opens_at="2026-10-01",
        submission_due_at="2026-11-20",
    )
    ctx["period_id"] = ctx["period"]["id"]
    advance_clock("2026-10-10T00:00:00Z")
    ctx["file"] = upload_file(ctx, [enrollment_row(
        term_start="2026-10-01", term_end="2027-01-15",
    )])
    ctx["file_id"] = ctx["file"]["id"]
    ctx["file"] = certify_file(ctx, ctx["file_id"])
    ctx["entries"] = list_file_entries(ctx["file_id"])
    ctx["student_id"] = ctx["entries"][0]["student_id"]
    setup_sealed_degree(ctx, ctx["student_id"])
    rq = setup_vetted_requester(credit=2599)
    ctx["requester_id"] = rq["id"]
    req = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    ctx["request_id"] = req["id"]
    pay_request(req["id"], rq["id"])
    return ctx


def test_agreement_expiry_suspends_institution(api):
    """PRD section 3.1: "an `ACTIVE` agreement whose `effective_to` has been
    reached flips to `EXPIRED`".
    PRD section 3.1: "The same cascade fires automatically when clock
    processing expires an institution's last `ACTIVE` agreement and no other
    `ACTIVE` agreement covers the current instant: the institution flips from
    `ACTIVE` to `SUSPENDED` with `suspension_reason` of `AGREEMENT_LAPSE`,
    followed by the identical request-cancellation cascade."

    Design: Difficulty/transitive_cascade/agreement_expiry_cascades_suspension_and_request_cancellation
    """
    ctx = _build_expiry_scene(api)
    advance_clock("2027-02-01T00:00:00Z")
    data, _m = validate_paginated(api_client.list_agreements(ctx["inst_id"], OPS))
    assert data[0]["status"] == "EXPIRED", (
        "now 2027-02-01 >= effective_to 2027-02-01 (half-open window)"
    )
    inst = validate_success(api_client.get_institution(ctx["inst_id"], OPS), 200)
    assert inst["status"] == "SUSPENDED"
    assert inst["suspension_reason"] == "AGREEMENT_LAPSE"


def test_agreement_expiry_cancels_paid_request_with_refund(api):
    """PRD section 3.1: "Every VerificationRequest targeting that institution
    in `QUOTED` or `PAID` status moves to `CANCELLED`, processed in
    `created_at` ascending order, and each `PAID` request refunds its full
    `fee_cents` to the requester's `credit_balance_cents`, recording the
    amount in the request's `refund_cents`."
    PRD section 3.1: "an institution suspended with reason `AGREEMENT_LAPSE`
    is reinstated automatically, again with `suspension_reason` cleared to
    `NONE`, the moment a `SCHEDULED` agreement flips to `ACTIVE` on clock
    advance or a newly created agreement is already `ACTIVE`."

    Design: Difficulty/transitive_cascade/agreement_expiry_cascades_suspension_and_request_cancellation
    """
    ctx = _build_expiry_scene(api)
    assert get_requester_balance(ctx["requester_id"]) == 0, (
        "2599 seed minus 2599 fee leaves zero"
    )
    advance_clock("2027-02-01T00:00:00Z")
    req = validate_success(
        api_client.get_verification_request(ctx["request_id"], OPS), 200,
    )
    assert req["status"] == "CANCELLED"
    assert req["refund_cents"] == 2599
    assert get_requester_balance(ctx["requester_id"]) == 2599, (
        "the refund restores the prepaid balance"
    )
    resp = api_client.create_agreement(
        ctx["inst_id"],
        create_agreement_payload(effective_from="2026-11-01",
                                 effective_to="2027-06-30"),
        OPS,
    )
    validate_success(resp, 201)
    inst = validate_success(api_client.get_institution(ctx["inst_id"], OPS), 200)
    assert inst["status"] == "ACTIVE", (
        "a newly created already-ACTIVE agreement reinstates an "
        "AGREEMENT_LAPSE suspension"
    )


def test_ops_suspend_cancels_quoted_and_paid_requests(api):
    """PRD section 3.7: "Institution suspension reaches into this pipeline
    from §3.1: requests targeting the institution in `QUOTED` move to
    `CANCELLED` untouched, while `PAID` ones move to `CANCELLED` with the
    same full-refund mechanics."
    PRD section 3.7: "`refund_cents` begins at zero."

    Design: Corner/state_machines/ops_suspend_cancels_quoted_and_paid_requests
    """
    ctx = setup_student_with_file(
        advance_to=None, term_label="Early Fall 2026", term_start="2026-08-01",
        term_end="2026-12-15", submission_opens_at="2026-08-15",
        submission_due_at="2026-12-20",
    )
    rq = setup_vetted_requester(credit=10000)
    r1 = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"],
                               purpose="EMPLOYMENT")
    r2 = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"],
                               purpose="INSURANCE")
    pay_request(r2["id"], rq["id"])
    assert get_requester_balance(rq["id"]) == 7401

    validate_success(api_client.suspend_institution(ctx["inst_id"], OPS), 200)

    q = validate_success(api_client.get_verification_request(r1["id"], OPS), 200)
    assert q["status"] == "CANCELLED"
    assert q["refund_cents"] == 0, "a QUOTED request is cancelled untouched"
    p = validate_success(api_client.get_verification_request(r2["id"], OPS), 200)
    assert p["status"] == "CANCELLED"
    assert p["refund_cents"] == 2599
    assert get_requester_balance(rq["id"]) == 10000


def test_err_agreement_lapsed_upload_and_reinstate(api):
    """PRD section 3.3: "the institution must be `ACTIVE`
    (`ERR_INSTITUTION_SUSPENDED`); an `ACTIVE` agreement must cover now
    (`ERR_AGREEMENT_LAPSED`)".
    PRD section 3.1: "An operator may reinstate a `SUSPENDED` institution
    only when an `ACTIVE` agreement covers the current instant — otherwise
    the reinstatement is rejected with `ERR_AGREEMENT_LAPSED` (HTTP 409)".

    Design: Corner/errors/err_agreement_lapsed_upload_and_reinstate
    """
    ctx = setup_period_scenario(
        advance_to=None, with_agreement=False,
        term_label="Early Fall 2026", term_start="2026-08-01",
        term_end="2026-12-15", submission_opens_at="2026-08-15",
        submission_due_at="2026-12-20",
    )
    version = get_period_version(ctx["inst_id"])
    payload = create_enrollment_file_payload(
        ctx["inst_id"], ctx["period_id"], version,
        [enrollment_row(term_start="2026-08-01")],
    )
    resp = api_client.create_enrollment_file(
        payload, make_submitter_headers(ctx["sub_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_LAPSED)

    validate_success(api_client.suspend_institution(ctx["inst_id"], OPS), 200)
    reinstate = api_client.reinstate_institution(ctx["inst_id"], OPS)
    validate_error(reinstate, ApiErrorId.ERR_AGREEMENT_LAPSED)
