"""Corner queue: validation violations mapped to their error IDs."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_dealer_principal_headers,
    reset_clock, setup_region, setup_dealer, setup_department,
    setup_dealer_env, create_tx, open_wave_and_get_invitations,
    send_invitation, respond, confirm_flag, create_draft_plan,
    file_appeal, create_advisor_payload, create_transaction_payload,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


def test_missing_role_header_rejected_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role
    outside this enumeration, is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_role_header
    """
    reset_clock()
    err = api._request(
        "GET", f"/survey/dealers/{NON_EXISTENT_UUID}",
        headers={"X-User-ID": "nobody", "Content-Type": "application/json"},
    )
    validate_error(err, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_answers_must_cover_question_set_exactly(api):
    """PRD §3.5: "The array must cover every question in the invitation's
    pinned question set exactly once — each entry pairs a question_code with
    an integer score between 1 and 10 — and any deviation (missing questions,
    duplicate question_codes, scores out of range, unknown codes) is rejected
    with ERR_INVALID_REQUEST."

    Design: Corner/validations/response_answers_must_cover_question_set_exactly
    """
    questions = [
        {"question_code": "q1", "prompt": "A", "weight": 1},
        {"question_code": "q2", "prompt": "B", "weight": 1},
    ]
    env = setup_dealer_env(dealer_code="A", customers=1, questions=questions)
    cust = env["customers"][0]
    create_tx(env, cust, margin_cents=100)
    invs = open_wave_and_get_invitations(env)
    send_invitation(invs[0]["id"])
    from test_helpers import make_customer_headers
    err = api.submit_response(
        invs[0]["id"],
        {"answers": [{"question_code": "q1", "score": 5}]},  # missing q2
        make_customer_headers(cust["id"]),
    )
    # §3.5 names ERR_INVALID_REQUEST for coverage deviations; the error
    # catalogue binds structural schema shape to ERR_VALIDATION. Both are
    # 400; accept the PRD's two stated identifiers rather than guessing.
    body = err.json()
    assert body["response_type"] == "error"
    assert err.status_code == 400
    assert body["data"]["error_id"] in ("ERR_INVALID_REQUEST", "ERR_VALIDATION")


def test_advisor_from_wrong_department_cross_reference_mismatch(api):
    """PRD §3.3: "The department must belong to the named dealer, and the
    advisor, when present, must belong to the named department; mismatches
    surface as ERR_CROSS_REFERENCE_MISMATCH."

    Design: Corner/validations/cross_reference_mismatch_advisor_from_wrong_department
    """
    reset_clock()
    region = setup_region()
    dealer = setup_dealer(region["id"], code="A")
    dept_s = setup_department(dealer["id"], kind="SALES", name="Sales")
    dept_v = setup_department(dealer["id"], kind="SERVICE", name="Service")
    adv = validate_success(api.create_advisor(
        create_advisor_payload(dept_v["id"], name="Tech", employee_ref="T1"),
        ADMIN,
    ), 201)
    from test_helpers import setup_customer
    cust = setup_customer()
    payload = create_transaction_payload(
        dealer["id"], dept_s["id"], cust["id"],
        advisor_id=adv["id"], margin_cents=100,
    )
    err = api.create_transaction(payload, ADMIN)
    validate_error(
        err, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH, expected_status=422
    )


def test_second_appeal_while_open_rejected(api):
    """PRD §3.7: "And the response must not already have an open appeal —
    one in FILED or UNDER_REVIEW — which would surface
    ERR_APPEAL_ALREADY_OPEN."
    PRD §2.9: state validity (priority 6) masks the appeal-singleton check
    (priority 15). Because filing an appeal transitions the response to
    FLAGGED, a second appeal on the same response can surface either
    ERR_INVALID_STATE (state check fires first) or ERR_APPEAL_ALREADY_OPEN.

    Design: Corner/validations/appeals_already_open_blocks_second_appeal
    """
    env = setup_dealer_env(dealer_code="A", customers=1)
    cust = env["customers"][0]
    dealer_id = env["dealer"]["id"]
    create_tx(env, cust, margin_cents=100)
    invs = open_wave_and_get_invitations(env)
    send_invitation(invs[0]["id"])
    resp = respond(invs[0], cust, {"q1": 5})
    file_appeal(dealer_id, resp, reason="first")
    current = validate_success(api.get_response(resp["id"], ADMIN))
    err = api.create_appeal(
        {
            "response_id": resp["id"],
            "reason": "second",
            "expected_response_version": current["version"],
        },
        make_dealer_principal_headers(dealer_id),
    )
    validate_error_is_one_of(
        err,
        [ApiErrorId.ERR_APPEAL_ALREADY_OPEN, ApiErrorId.ERR_INVALID_STATE],
    )


def test_suspended_dealer_cannot_submit_draft_plan(api):
    """PRD §3.9: "From DRAFT, the principal submits the plan for review —
    the transition is guarded by ownership (X-User-ID must equal the plan's
    dealer_id, failing with ERR_FORBIDDEN) and by posture: a dealer in
    SUSPENDED may not submit at all, and the request is rejected with
    ERR_DEALER_SUSPENDED."
    PRD §3.6: "Otherwise, if confirmed_flag_count is at least three, posture
    is SUSPENDED."

    Design: Corner/validations/suspended_dealer_submit_blocked
    """
    env = setup_dealer_env(dealer_code="A", customers=1)
    cust = env["customers"][0]
    dealer_id = env["dealer"]["id"]
    dp = make_dealer_principal_headers(dealer_id)
    create_tx(env, cust, margin_cents=100)
    invs = open_wave_and_get_invitations(env)
    send_invitation(invs[0]["id"])
    respond(invs[0], cust, {"q1": 9})
    reset_clock("2026-10-01T00:00:00Z")
    validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
    # Reach SUSPENDED via three confirmed flags.
    confirm_flag(dealer_id, kind="COACHING", evidence="e1")
    confirm_flag(dealer_id, kind="OPT_OUT_SUPPRESSION", evidence="e2")
    confirm_flag(dealer_id, kind="CONTACT_TAMPERING", evidence="e3")
    dealer = validate_success(api.get_dealer(dealer_id, ADMIN))
    assert dealer["posture"] == "SUSPENDED"
    # A plan drafted after suspension lands in DRAFT (the auto-submit cascade
    # fired before it existed); submitting it is rejected.
    plan = create_draft_plan(dealer_id, env["wave"]["id"], title="new plan")
    assert plan["status"] == "DRAFT"
    err = api.submit_action_plan(plan["id"], dp)
    validate_error(err, ApiErrorId.ERR_DEALER_SUSPENDED, expected_status=422)
