"""Application review pipeline, private fundraising, and the endorser quorum
(PRD §3.3, §3.4)."""
from test_helpers import (
    TEST_USERS,
    approve_application,
    create_application,
    create_private_fundraising_application,
    create_submittable_borrower,
    create_trustee,
    get_application,
    make_borrower_headers,
    make_lender_headers,
    open_public,
    set_clock,
    submit_application,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_QUORUM_NOT_MET,
    ERR_SCORE_TOO_LOW,
)

ADMIN = TEST_USERS["admin_headers"]


def test_approve_from_draft_returns_invalid_state(api):
    """PRD §3.3: "Approval requires the borrower's
    `social_underwriting_score` to be at least 60 — a score below the
    threshold rejects the approval with `ERR_SCORE_TOO_LOW` (HTTP 409) — and
    moves the application to `APPROVED_PENDING_FUNDRAISE`."
    PRD §2.9: "Fourth, state permissibility of the target resource
    (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/approve_from_draft_returns_invalid_state
    """
    set_clock()
    borrower = create_submittable_borrower()
    application = create_application(borrower)
    resp = client.approve_application(application["id"], ADMIN)
    validate_error(resp, ERR_INVALID_STATE, expected_status=409)
    assert get_application(application["id"])["status"] == "DRAFT"


def test_withdraw_from_rejected_returns_invalid_state(api):
    """PRD §3.5: "Withdrawal is available from `DRAFT`, `IN_REVIEW`,
    `APPROVED_PENDING_FUNDRAISE`, and `PRIVATE_FUNDRAISING`, moving the
    application to `WITHDRAWN` with `terminal_at` stamped"
    PRD §3.5: "Attempting either action from any other state is
    `ERR_INVALID_STATE`."
    PRD §3.3: "Rejection moves it to `REJECTED` and stamps `terminal_at`."

    Design: Corner/state_machines/withdraw_from_rejected_returns_invalid_state
    """
    set_clock()
    ns = fx.create_submitted_application()
    rejected = validate_success(
        client.reject_application(ns.application["id"], ADMIN, {"notes": "No"})
    )
    assert rejected["status"] == "REJECTED"

    resp = client.withdraw_application(
        ns.application["id"], make_borrower_headers(ns.borrower["id"])
    )
    validate_error(resp, ERR_INVALID_STATE, expected_status=409)
    assert get_application(ns.application["id"])["status"] == "REJECTED"


def test_application_initial_state_is_draft(api):
    """PRD §3.3: "The draft starts in `DRAFT` with all fundraising counters —
    `distinct_endorser_count`, `private_total_cents`, `public_total_cents`,
    and `funded_total_cents` — at 0 and all lifecycle timestamps null."
    PRD §2.5: "an integer `version` that starts low and increments by exactly
    1 on every mutation of that resource"

    Design: Corner/state_machines/application_initial_state_is_draft
    """
    set_clock()
    borrower = create_submittable_borrower()
    application = validate_success(
        client.create_application(
            {
                "borrower_id": borrower["id"],
                "requested_amount_cents": 100_000,
                "term_months": 3,
                "business_purpose": "x",
            },
            make_borrower_headers(borrower["id"]),
        ),
        expected_status=201,
    )
    assert application["status"] == "DRAFT"
    assert application["version"] == 1
    assert application["private_started_at"] is None
    assert application["public_started_at"] is None
    assert application["funded_at"] is None
    assert application["terminal_at"] is None


def test_revision_loop_resubmit_requires_fresh_version(api):
    """PRD §3.3: "Requesting changes sends the application `IN_REVIEW` →
    `DRAFT` for revision."
    PRD §2.7: "If the application's current `version` has advanced since that
    observation — for example because the draft was edited, and each edit
    bumps the version — the submission is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.3: "All three actions accept optional `notes`, recorded into the
    application's `review_notes`."

    Design: Difficulty/non_linear_state_machine/application_revision_loop_draft_review_draft
    """
    set_clock()
    ns = fx.create_submitted_application()
    assert ns.application["status"] == "IN_REVIEW"
    v1 = ns.application["version"]

    returned = validate_success(
        client.request_changes(
            ns.application["id"], ADMIN, {"notes": "Clarify kiln supplier"}
        )
    )
    assert returned["status"] == "DRAFT", "request-changes loops back to DRAFT"

    edited = validate_success(
        client.update_application(
            ns.application["id"],
            {"business_purpose": "Kiln (supplier: Axner)"},
            make_borrower_headers(ns.borrower["id"]),
        )
    )
    assert edited["version"] > v1, "the PATCH bumps the application version"

    resubmitted = submit_application(edited, ns.borrower)
    assert resubmitted["status"] == "IN_REVIEW", "second pass through the cycle"
    assert resubmitted["review_notes"] == "Clarify kiln supplier"
    assert resubmitted["version"] > edited["version"]


def test_revision_loop_recomputes_score_on_each_submit(api):
    """PRD §3.3: "A successful submission moves the application `DRAFT` →
    `IN_REVIEW`, recomputes the borrower's score and variant as in §3.2, and
    bumps the application's `version`."
    PRD §3.3: "Requesting changes sends the application `IN_REVIEW` →
    `DRAFT` for revision."

    Design: Difficulty/non_linear_state_machine/application_revision_loop_draft_review_draft
    """
    set_clock()
    borrower = create_submittable_borrower(
        accepts=3, business_tenure_months=24, prior_repaid_loans_count=0
    )
    application = create_application(borrower, requested_amount_cents=100_000)
    first = submit_application(application, borrower)
    # 20 (tenure) + 9 (3 accepts) + 0 + 0 = 29 under STANDARD.
    assert fx.get_borrower(borrower["id"])["social_underwriting_score"] == 29

    validate_success(client.request_changes(first["id"], ADMIN, {}))
    # Edit tenure upward, then resubmit: the score must be recomputed.
    edited = validate_success(
        client.update_application(
            first["id"],
            {"business_purpose": "revised"},
            make_borrower_headers(borrower["id"]),
        )
    )
    validate_success(
        client.update_borrower(
            borrower["id"],
            {"business_tenure_months": 12},
            make_borrower_headers(borrower["id"]),
        )
    )
    second = submit_application(edited, borrower)
    assert second["status"] == "IN_REVIEW"
    # 20*12/24 + 9 = 10 + 9 = 19 on the second pass.
    assert fx.get_borrower(borrower["id"])["social_underwriting_score"] == 19


def test_quorum_exactly_met_passes_and_one_short_fails(api):
    """PRD §3.4: "When the borrower opens the public campaign — moving the
    application `PRIVATE_FUNDRAISING` → `PUBLIC_FUNDRAISING` — the count must
    meet the `required_endorser_count` pinned at submission (15
    self-endorsed, 5 trustee-vouched); meeting it exactly suffices, and
    falling short is rejected with `ERR_QUORUM_NOT_MET` (HTTP 409)."
    PRD §3.4: "The quorum itself is a count of distinct endorsers: the number
    of distinct lenders holding `ACTIVE` non-trustee endorsements, plus the
    number of `ACTIVE` trustee endorsements."

    Design: Difficulty/boundary_precision_check/quorum_exactly_met_vs_one_short
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=5_000_000)

    # App A: 4 lender endorsements + 1 trustee endorsement = 5 == quorum.
    ns_a = create_private_fundraising_application(trustee=trustee)
    app_a, _ = fx.meet_quorum_with_endorsements(
        ns_a, [25_000, 25_000, 25_000, 25_000], trustee_amount=50_000
    )
    opened = open_public(app_a, ns_a.borrower)
    assert opened["status"] == "PUBLIC_FUNDRAISING"

    # App B: only 4 lender endorsements -> 4 < 5.
    ns_b = create_private_fundraising_application(trustee=trustee)
    app_b, _ = fx.meet_quorum_with_endorsements(
        ns_b, [25_000, 25_000, 25_000, 25_000]
    )
    resp = client.open_public(app_b["id"], make_borrower_headers(ns_b.borrower["id"]))
    validate_error(resp, ERR_QUORUM_NOT_MET, expected_status=409)
    assert get_application(app_b["id"])["status"] == "PRIVATE_FUNDRAISING"


def test_quorum_counts_distinct_endorsers_not_endorsements(api):
    """PRD §3.4: "The quorum itself is a count of distinct endorsers: the
    number of distinct lenders holding `ACTIVE` non-trustee endorsements,
    plus the number of `ACTIVE` trustee endorsements."
    PRD §2.8: "the pair (`loan_application_id`, `lender_id`) may have at most
    one `ACTIVE` endorsement — a lender who already holds a live endorsement
    on an application cannot place a second one"

    Design: Difficulty/boundary_precision_check/quorum_exactly_met_vs_one_short
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=5_000_000)
    ns = create_private_fundraising_application(trustee=trustee)
    # One lender cannot fill the quorum twice: a second ACTIVE endorsement
    # from the same lender is rejected, so 4 distinct lenders + trustee = 5.
    lenders = [fx.create_lender(deposit_cents=500_000) for _ in range(4)]
    for lender in lenders:
        fx.endorse(ns.application, lender, 25_000)
    dup = client.create_endorsement(
        ns.application["id"],
        {"lender_id": lenders[0]["id"], "amount_cents": 25_000},
        make_lender_headers(lenders[0]["id"]),
    )
    assert dup.status_code == 409
    fx.trustee_endorse(ns.application, trustee, 50_000)

    application = get_application(ns.application["id"])
    assert application["distinct_endorser_count"] == 5
    opened = open_public(application, ns.borrower)
    assert opened["status"] == "PUBLIC_FUNDRAISING"


def test_approve_gated_by_borrower_score(api):
    """PRD §3.3: "Approval requires the borrower's
    `social_underwriting_score` to be at least 60 — a score below the
    threshold rejects the approval with `ERR_SCORE_TOO_LOW` (HTTP 409) — and
    moves the application to `APPROVED_PENDING_FUNDRAISE`."

    Design: Difficulty/cross_entity_state_dependency/approve_gated_by_borrower_score
    """
    set_clock()
    # tenure 0, 3 accepts, prior 0 -> 0 + 9 + 0 + 0 = 9, below the 60 floor.
    ns = fx.create_submitted_application(
        borrower=create_submittable_borrower(
            accepts=3, business_tenure_months=0, prior_repaid_loans_count=0
        ),
        requested_amount_cents=200_000,
        term_months=3,
    )
    resp = client.approve_application(ns.application["id"], ADMIN)
    validate_error(resp, ERR_SCORE_TOO_LOW, expected_status=409)
    assert get_application(ns.application["id"])["status"] == "IN_REVIEW"
    assert fx.get_borrower(ns.borrower["id"])["social_underwriting_score"] == 9


def test_approve_at_exactly_60_passes(api):
    """PRD §3.3: "Approval requires the borrower's
    `social_underwriting_score` to be at least 60 — a score below the
    threshold rejects the approval with `ERR_SCORE_TOO_LOW` (HTTP 409) — and
    moves the application to `APPROVED_PENDING_FUNDRAISE`."

    Design: Difficulty/cross_entity_state_dependency/approve_gated_by_borrower_score
    """
    set_clock()
    # Exact-60 profile in trustee mode: tenure 24 (20) + 5 accepts (15) +
    # trustee component (25) + repayment ignored (0) = 60, which passes the
    # "at least 60" gate.
    trustee = create_trustee(endorsement_limit_cents=5_000_000)
    ns = fx.create_submitted_application(
        borrower=create_submittable_borrower(
            accepts=5, business_tenure_months=24, prior_repaid_loans_count=0
        ),
        trustee=trustee,
        requested_amount_cents=200_000,
        term_months=3,
    )
    assert fx.get_borrower(ns.borrower["id"])["social_underwriting_score"] == 60
    approved = approve_application(ns.application)
    assert approved["status"] == "APPROVED_PENDING_FUNDRAISE"


def test_submit_gated_by_trustee_status(api):
    """PRD §3.3: "when the submission names a `trustee_id`, the trustee must
    exist, must be `ACTIVE` (a suspended trustee yields
    `ERR_TRUSTEE_SUSPENDED`, HTTP 409)"
    PRD §3.8: "While `SUSPENDED`, the trustee cannot vouch: new trustee
    endorsements referencing it are rejected with `ERR_TRUSTEE_SUSPENDED`,
    and submissions naming it fail the same way."

    Design: Difficulty/cross_entity_state_dependency/submit_gated_by_trustee_status
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=2_000_000)
    borrower = create_submittable_borrower(
        accepts=3, business_tenure_months=24, prior_repaid_loans_count=1
    )
    application = create_application(
        borrower, requested_amount_cents=300_000, term_months=6
    )
    # Trustee is suspended after the draft exists but before submission.
    validate_success(client.suspend_trustee(trustee["id"], ADMIN))

    resp = client.submit_application(
        application["id"],
        {
            "expected_application_version": application["version"],
            "trustee_id": trustee["id"],
        },
        make_borrower_headers(borrower["id"]),
    )
    from test_helpers.api_errors import ERR_TRUSTEE_SUSPENDED

    validate_error(resp, ERR_TRUSTEE_SUSPENDED, expected_status=409)
    assert get_application(application["id"])["status"] == "DRAFT"


def test_submit_to_reinstated_trustee_succeeds(api):
    """PRD §3.8: "Reinstatement is manual only — a `PlatformAdmin` returns a
    `SUSPENDED` trustee to `ACTIVE` and resets `suspension_reason` to `NONE`."
    PRD §3.3: "when the submission names a `trustee_id`, the trustee must
    exist, must be `ACTIVE` (a suspended trustee yields
    `ERR_TRUSTEE_SUSPENDED`, HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/submit_gated_by_trustee_status
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=2_000_000)
    validate_success(client.suspend_trustee(trustee["id"], ADMIN))
    reinstated = validate_success(client.reinstate_trustee(trustee["id"], ADMIN))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] == "NONE"

    borrower = create_submittable_borrower(
        accepts=3, business_tenure_months=24, prior_repaid_loans_count=1
    )
    application = create_application(
        borrower, requested_amount_cents=300_000, term_months=6
    )
    submitted = submit_application(application, borrower, trustee_id=trustee["id"])
    assert submitted["status"] == "IN_REVIEW"
    assert submitted["endorsement_mode"] == "TRUSTEE_VOUCHED"
    assert submitted["required_endorser_count"] == 5
