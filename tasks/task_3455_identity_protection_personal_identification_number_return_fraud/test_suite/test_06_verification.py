"""Identity-verification lifecycle tests: the FAILED retry loop, document
coverage, the deadline gate, channel restrictions, case uniqueness, verified
release of held refunds, and the third-failure fraud cascade.

PRD section 3.5 (with the fraud cascade of section 3.8 and the conflict
forfeit of section 3.6).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_case_to_docs_submitted,
    assert_verification_document,
    create_active_config,
    create_dependent_payload,
    create_taxpayer,
    create_verification_case_payload,
    fail_case_attempt,
    fail_case_until_expired,
    file_return,
    get_conflict_by_tin,
    get_return,
    get_return_hold,
    get_verification_case,
    list_claims,
    make_taxpayer_headers,
    mark_false_positive,
    next_dependent_tin,
    open_verification_case,
    request_documents,
    set_clock,
    setup_held_return,
    setup_held_return_with_case,
    submit_document,
    submit_document_payload,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["fraud_analyst_headers"]
AGENT = TEST_USERS["verification_agent_headers"]


# ─── Retry loop: FAILED -> DOCS_REQUESTED ────────────

def _setup_phone_case_with_partial_docs():
    """Held FULL return (score 60) with a PHONE case (required docs
    PHOTO_ID + SSA_CARD); documents requested, then only PHOTO_ID filed."""
    set_clock("2027-02-01T00:00:00Z")
    taxpayer, rtn, hold = setup_held_return(
        w_bank_product=60, gray_zone_threshold=25, hold_threshold=50,
        claimed_refund_cents=80000,
    )
    case = open_verification_case(
        taxpayer["id"], return_id=rtn["id"], channel="PHONE"
    )
    request_documents(case["id"])
    submit_document(case["id"], "PHOTO_ID", taxpayer_id=taxpayer["id"])
    return taxpayer, rtn, hold, case


def test_failed_case_reenters_document_request_loop(api):
    """PRD section 3.5: "A `VerificationAgent` moves a case into document
    collection by requesting documents, which is permitted from `OPENED` and
    from `FAILED` alike — this is the retry-loop entry — and lands the case
    in `DOCS_REQUESTED`."
    PRD section 3.5: "The first and second failures increment
    `attempts_count` by 1 and move the case to `FAILED`, from which another
    document request re-enters the loop."
    PRD section 3.5: "Coverage is computed over the set of received
    `doc_type` values: the moment that set covers `required_document_types`,
    the case auto-advances from `DOCS_REQUESTED` to `DOCS_SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/verification_case_retry_cycle
    """
    taxpayer, _rtn, _hold, case = _setup_phone_case_with_partial_docs()

    mid = get_verification_case(case["id"])
    assert mid["status"] == "DOCS_REQUESTED", (
        "PHOTO_ID alone must not cover the PHONE requirement "
        "[PHOTO_ID, SSA_CARD]"
    )

    failed = fail_case_attempt(case["id"])
    assert failed["status"] == "FAILED"
    assert failed["attempts_count"] == 1

    reentered = request_documents(case["id"])
    assert reentered["status"] == "DOCS_REQUESTED"


def test_verified_case_passes_return_and_resolves_hold(api):
    """PRD section 3.5: "A successful verification moves the case to
    `VERIFIED`, and when the case is return-linked and the return is still
    `FILTER_HELD`, the return passes the filter — `FILTER_HELD` to
    `FILTER_PASSED` — and its `OPEN` hold resolves as `RESOLVED_VERIFIED`."

    Design: Difficulty/non_linear_state_machine/verification_case_retry_cycle
    """
    taxpayer, rtn, _hold, case = _setup_phone_case_with_partial_docs()
    fail_case_attempt(case["id"])
    request_documents(case["id"])
    # SSA_CARD completes the required set (PHOTO_ID was received earlier).
    submit_document(case["id"], "SSA_CARD", taxpayer_id=taxpayer["id"])

    submitted = get_verification_case(case["id"])
    assert submitted["status"] == "DOCS_SUBMITTED"

    verified = validate_success(api.verify_case(case["id"], AGENT), 200)
    assert verified["status"] == "VERIFIED"
    assert get_return(rtn["id"])["status"] == "FILTER_PASSED"
    assert get_return_hold(rtn["id"])["status"] == "RESOLVED_VERIFIED"


# ─── Release gate on VERIFIED case ───────────────────

def _setup_held_with_docs_submitted():
    """Held FULL return with an ONLINE case driven to DOCS_SUBMITTED."""
    set_clock("2027-02-01T00:00:00Z")
    taxpayer, rtn, hold, case = setup_held_return_with_case(
        channel="ONLINE", w_bank_product=60, gray_zone_threshold=25,
        hold_threshold=50, claimed_refund_cents=70000,
    )
    advance_case_to_docs_submitted(case, taxpayer_id=taxpayer["id"])
    return taxpayer, rtn, hold, case


def test_release_held_return_rejected_until_case_verified(api):
    """PRD section 3.8: "Scheduling from `FILTER_HELD` is also possible but
    guarded: a linked identity-verification case in `VERIFIED` must exist for
    the return, else the request is rejected with
    `ERR_VERIFICATION_INCOMPLETE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/release_requires_verified_case
    """
    _taxpayer, rtn, _hold, case = _setup_held_with_docs_submitted()
    assert get_verification_case(case["id"])["status"] == "DOCS_SUBMITTED"

    resp = api.release_refund(rtn["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_INCOMPLETE)


def test_verified_case_enables_refund_scheduling(api):
    """PRD section 3.5: "A successful verification moves the case to
    `VERIFIED`, and when the case is return-linked and the return is still
    `FILTER_HELD`, the return passes the filter — `FILTER_HELD` to
    `FILTER_PASSED` — and its `OPEN` hold resolves as `RESOLVED_VERIFIED`."
    PRD section 3.8: "Scheduling moves the return to `REFUND_SCHEDULED` and
    creates the return's one and only `RefundDisbursement` — exactly one
    disbursement ever exists per return — in `SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/release_requires_verified_case
    """
    _taxpayer, rtn, _hold, case = _setup_held_with_docs_submitted()

    rejected = api.release_refund(rtn["id"], ANALYST)
    validate_error(rejected, ApiErrorId.ERR_VERIFICATION_INCOMPLETE)

    verified = validate_success(api.verify_case(case["id"], AGENT), 200)
    assert verified["status"] == "VERIFIED"
    assert get_return(rtn["id"])["status"] == "FILTER_PASSED"

    scheduled = validate_success(api.release_refund(rtn["id"], ANALYST), 201)
    assert scheduled["status"] == "SCHEDULED"
    assert get_return(rtn["id"])["status"] == "REFUND_SCHEDULED"


# ─── Third failure: expiry and fraud-forfeit cascade ──

def _setup_conflict_with_held_second_filer():
    """MV-FORF (w_dependent_conflict 20, gray 10, hold 50): A passes with a
    CLAIMED dependent; B's filing on the same dependent flips both claims to
    CONTESTED, opens the conflict, and scores 20 -> FILTER_HELD (GRAY)."""
    set_clock("2027-02-01T00:00:00Z")
    create_active_config(
        model_version="MV-FORF", w_dependent_conflict=20,
        gray_zone_threshold=10, hold_threshold=50,
    )
    dep_tin = next_dependent_tin()
    taxpayer_a = create_taxpayer()
    taxpayer_b = create_taxpayer()
    return_a = file_return(
        taxpayer_a["id"], claimed_refund_cents=50000,
        filing_status="HEAD_OF_HOUSEHOLD", bank_product="NONE",
        dependents=[create_dependent_payload(dep_tin)],
    )
    return_b = file_return(
        taxpayer_b["id"], claimed_refund_cents=50000, bank_product="NONE",
        dependents=[create_dependent_payload(dep_tin)],
    )
    assert return_b["risk_score"] == 20
    assert return_b["status"] == "FILTER_HELD"
    case = open_verification_case(
        taxpayer_b["id"], return_id=return_b["id"], channel="ONLINE"
    )
    return dep_tin, taxpayer_a, return_a, taxpayer_b, return_b, case


def test_third_failed_attempt_expires_case_and_confirms_fraud(api):
    """PRD section 3.5: "The third failure is terminal and severe: with
    `attempts_count` reaching its maximum of 3, the case lands in `EXPIRED`
    instead of `FAILED` with `attempts_count` set to 3, and — when the case
    is return-linked to a `FILTER_HELD` return — the expiry cascades the
    return to `FRAUD_CONFIRMED`, which in turn disallows the return's
    dependent claims, resolves any `OPEN` dependent conflicts involving those
    claims by fraud forfeit, and resolves the return's `OPEN` hold as
    `RESOLVED_FRAUD`, exactly as §3.8's fraud cascade specifies."

    Design: Difficulty/transitive_cascade/case_expiry_fraud_forfeit_cascade
    """
    _dep, _tp_a, _rtn_a, _tp_b, rtn_b, case = (
        _setup_conflict_with_held_second_filer()
    )

    expired = fail_case_until_expired(case["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["attempts_count"] == 3

    assert get_return(rtn_b["id"])["status"] == "FRAUD_CONFIRMED"


def test_expiry_forfeit_resolves_conflict_for_honest_filer(api):
    """PRD section 3.6: "A fraud forfeit fires when one side's return becomes
    `FRAUD_CONFIRMED`: the `resolution` is the filer whose return is not
    fraud-confirmed, with `resolved_reason` `FRAUD_FORFEIT`."
    PRD section 3.6: "Under fraud forfeit the money moves differently: the
    winning claim still moves to `SUSTAINED`, but the losing claim was
    already `DISALLOWED` by the fraud cascade itself, so no credit adjustment
    is applied — no double adjustment — because the fraud confirmation
    denies the losing return's entire refund."

    Design: Difficulty/transitive_cascade/case_expiry_fraud_forfeit_cascade
    """
    dep_tin, _tp_a, rtn_a, _tp_b, rtn_b, case = (
        _setup_conflict_with_held_second_filer()
    )
    fail_case_until_expired(case["id"])

    claim_b = list_claims(rtn_b["id"])[0]
    assert claim_b["status"] == "DISALLOWED"

    claim_a = list_claims(rtn_a["id"])[0]
    assert claim_a["status"] == "SUSTAINED"

    conflict = get_conflict_by_tin(dep_tin)
    assert conflict["status"] == "RESOLVED"
    assert conflict["resolution"] == "FIRST_FILER"
    assert conflict["resolved_reason"] == "FRAUD_FORFEIT"

    # The honest filer's refund is untouched (no credit adjustment on the
    # winner, no double adjustment anywhere).
    assert get_return(rtn_a["id"])["claimed_refund_cents"] == 50000
    assert get_return(rtn_a["id"])["adjustment_cents"] == 0

    assert get_return_hold(rtn_b["id"])["status"] == "RESOLVED_FRAUD"


# ─── Case and hold guards ────────────────────────────

def test_verify_case_from_opened_rejected(api):
    """PRD section 3.5: "Verification itself is a `VerificationAgent`
    decision on a `DOCS_SUBMITTED` case (any other state is rejected with
    `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/verify_case_from_opened_rejected
    """
    set_clock("2027-02-01T00:00:00Z")
    _taxpayer, _rtn, _hold, case = setup_held_return_with_case(channel="ONLINE")
    assert case["status"] == "OPENED"

    resp = api.verify_case(case["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_hold_mark_false_positive_releases_return(api):
    """PRD section 3.8: "A `FraudAnalyst` who judges a hold to be a mistake
    marks it as a false positive, which requires the hold to be `OPEN` (else
    `ERR_INVALID_STATE`): the hold resolves as `RESOLVED_FALSE_POSITIVE` and
    the return passes the filter, moving from `FILTER_HELD` to
    `FILTER_PASSED`."

    Design: Corner/state_machines/hold_mark_false_positive_releases_return
    """
    set_clock("2027-02-01T00:00:00Z")
    _taxpayer, rtn, hold = setup_held_return(
        w_bank_product=60, gray_zone_threshold=25, hold_threshold=50,
        claimed_refund_cents=45000,
    )

    resolved = mark_false_positive(hold["id"])
    assert resolved["status"] == "RESOLVED_FALSE_POSITIVE"
    assert get_return(rtn["id"])["status"] == "FILTER_PASSED"


def test_second_case_on_same_return_rejected(api):
    """PRD section 3.5: "Supplying `return_id` creates a return-linked case,
    and then three requirements bind: the return must currently be
    `FILTER_HELD` (else `ERR_RETURN_NOT_HELD`, HTTP 409); when the return's
    hold is a `GRAY`-zone hold the channel must be `ONLINE` — the
    lighter-touch review is deliberately remote-only — and any other channel
    is rejected with `ERR_CHANNEL_NOT_ALLOWED` (HTTP 422); and no second
    non-terminal case may already exist for that return (else
    `ERR_CASE_ALREADY_OPEN`, HTTP 409)."

    Design: Corner/state_machines/second_case_on_same_return_rejected
    """
    set_clock("2027-02-01T00:00:00Z")
    taxpayer, rtn, _hold, _case = setup_held_return_with_case(channel="ONLINE")

    resp = api.create_verification_case(
        create_verification_case_payload(
            taxpayer["id"], channel="PHONE", return_id=rtn["id"]
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_OPEN)


def test_gray_zone_case_channel_restricted(api):
    """PRD section 3.5: "when the return's hold is a `GRAY`-zone hold the
    channel must be `ONLINE` — the lighter-touch review is deliberately
    remote-only — and any other channel is rejected with
    `ERR_CHANNEL_NOT_ALLOWED` (HTTP 422)".

    Design: Corner/validations/gray_zone_case_channel_restricted
    """
    set_clock("2027-02-01T00:00:00Z")
    taxpayer, rtn, hold = setup_held_return(
        w_bank_product=30, gray_zone_threshold=25, hold_threshold=50,
        claimed_refund_cents=50000,
    )
    assert rtn["risk_score"] == 30
    assert hold["zone"] == "GRAY"

    phone = api.create_verification_case(
        create_verification_case_payload(
            taxpayer["id"], channel="PHONE", return_id=rtn["id"]
        ),
        AGENT,
    )
    validate_error(phone, ApiErrorId.ERR_CHANNEL_NOT_ALLOWED)

    online = api.create_verification_case(
        create_verification_case_payload(
            taxpayer["id"], channel="ONLINE", return_id=rtn["id"]
        ),
        AGENT,
    )
    case = validate_success(online, 201)
    assert case["channel"] == "ONLINE"
    assert case["status"] == "OPENED"


def test_documents_after_case_deadline_rejected(api):
    """PRD section 3.5: "Two guards apply at submission: the case must be in
    `DOCS_REQUESTED` under the general state rule, and the current logical
    time must be at or before the case's `deadline_at` — a document arriving
    after the deadline is rejected with `ERR_VERIFICATION_WINDOW_EXPIRED`
    (HTTP 422)."
    PRD section 2.4: "Verification cases are deliberately not swept: a case
    leaves its open states only through a verification outcome or a third
    failed attempt, which keeps the document-deadline validation reachable at
    any clock position."

    Design: Corner/validations/documents_after_case_deadline_rejected
    """
    set_clock("2027-02-01T00:00:00Z")
    taxpayer, _rtn, _hold, case = setup_held_return_with_case(channel="ONLINE")
    request_documents(case["id"])

    # Case created 2027-02-01 -> deadline_at 2027-03-03T00:00:00Z.
    set_clock("2027-03-04T00:00:00Z")
    resp = api.submit_document(
        case["id"], submit_document_payload("PHOTO_ID"),
        make_taxpayer_headers(taxpayer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_WINDOW_EXPIRED)

    assert get_verification_case(case["id"])["status"] == "DOCS_REQUESTED"


def test_verification_document_immutable_no_version(api):
    """PRD section 2.5: "`VerificationDocument` is the sole exception to this
    convention: as an immutable submission record it carries only `id` and
    `created_at`, and both `updated_at` and `version` are absent from it."

    Design: Corner/entities/verification_document_immutable_no_version
    """
    set_clock("2027-02-01T00:00:00Z")
    taxpayer, _rtn, _hold, case = setup_held_return_with_case(channel="ONLINE")
    request_documents(case["id"])

    resp = api.submit_document(
        case["id"], submit_document_payload("PHOTO_ID"),
        make_taxpayer_headers(taxpayer["id"]),
    )
    doc = validate_success(resp, 201)
    assert_verification_document(doc)
    assert doc["case_id"] == case["id"]
    assert doc["doc_type"] == "PHOTO_ID"
