"""Risk score and class-of-business routing boundary tests (PRD §3.1, §3.3)."""

from test_helpers import (
    api_client,
    create_quote_payload,
    get_quote,
    get_success_data,
    make_policyholder_headers,
    make_platform_admin_headers,
    make_underwriter_headers,
    set_clock,
    setup_account,
    setup_class_and_rule,
    setup_referred_quote,
    validate_success,
)

ADMIN = make_platform_admin_headers("t02-admin")


def _setup_cc_c():
    return setup_class_and_rule(
        code="CC_C", description="Solo trades", keyword="handyman",
        eligible_lines=["GL"], base_rates_cents={"GL": 10000},
        risk_factor=0.5,
    )


def _inject_signals(account_id, severities):
    for sev in severities:
        resp = api_client.create_risk_signal(
            {
                "business_account_id": account_id,
                "signal_type": "LOSS_HISTORY",
                "severity": sev,
                "detail": f"sig-{sev}",
            }, ADMIN,
        )
        assert resp.status_code == 201, f"Setup failed (risk signal): {resp.text}"


def test_risk_score_below_refer_floor_routes_quoted(api):
    """PRD §3.3: "Routing follows the score. A score below 60 moves the quote
    from `CLASSIFYING` to `QUOTED`:"
    PRD §3.3: "To that base the system adds signal points from every `PENDING`
    risk signal report on the account: severity 80 or above contributes 25
    points, 50 through 79 contributes 15, 20 through 49 contributes 8, and 1
    through 19 contributes 3."

    Design: Difficulty/boundary_precision_check/refer_floor_inclusive_risk_score_boundary
    """
    _setup_cc_c()
    account = setup_account(legal_name="Floor Below")
    # base = round(0.5 * 20) = 10; signals 25+8+8+3+3 = 47 -> score 57.
    _inject_signals(account["id"], [80, 30, 25, 10, 5])
    ph = make_policyholder_headers(account["id"])
    resp = api.create_quote(create_quote_payload(
        business_account_id=account["id"], raw_description="handyman",
        selected_lines=["GL"],
    ), ph)
    quote = validate_success(resp, expected_status=201)
    assert quote["risk_score"] == 57, (
        f"Expected risk_score 57, got {quote['risk_score']}"
    )
    assert quote["status"] == "QUOTED", (
        f"Score below the 60 floor must route QUOTED, got {quote['status']}"
    )


def test_risk_score_at_refer_floor_routes_referred(api):
    """PRD §3.3: "A score of 60 or above but below 85 — or any matched appetite
    rule with disposition `REFER` — moves the quote to `REFERRED` and the
    system creates an `UnderwriterReferral` in status `OPEN` with `decision`
    `PENDING`,"

    Design: Difficulty/boundary_precision_check/refer_floor_inclusive_risk_score_boundary
    """
    _setup_cc_c()
    account = setup_account(legal_name="Floor At")
    # base 10; signals 25+8+8+3+3+3 = 50 -> score 60 (inclusive floor).
    _inject_signals(account["id"], [80, 30, 25, 10, 5, 1])
    ph = make_policyholder_headers(account["id"])
    resp = api.create_quote(create_quote_payload(
        business_account_id=account["id"], raw_description="handyman",
        selected_lines=["GL"],
    ), ph)
    quote = validate_success(resp, expected_status=201)
    assert quote["risk_score"] == 60, (
        f"Expected risk_score 60, got {quote['risk_score']}"
    )
    assert quote["status"] == "REFERRED", (
        f"Score at the inclusive 60 floor must route REFERRED, got {quote['status']}"
    )


def test_referred_quote_approval_loops_back_to_quoted(api):
    """PRD §3.3: "When an underwriter later approves the referral, the
    referral's `decision` becomes `APPROVED` and its status `RESOLVED`, and the
    quote moves from `REFERRED` to `QUOTED` — provided the referral is still
    `OPEN` and the quote's `expires_at` has not passed;"

    Design: Difficulty/non_linear_state_machine/quote_referral_loop_back_to_quoted
    """
    setup_class_and_rule(
        code="CC_A", description="Contractor", keyword="contractor",
        eligible_lines=["GL", "PL", "TOOLS"],
        base_rates_cents={"GL": 12000, "PL": 18000, "TOOLS": 6000},
        risk_factor=1.0,
    )
    account = setup_account(legal_name="Risky GC")
    # base 20 + severity-80 signal (+25) + two "yes" answers (+20) = 65.
    quote, referral = setup_referred_quote(
        account, "contractor", ["GL"], [80], {"q1": "yes", "q2": "yes"},
    )
    assert quote["risk_score"] == 65, (
        f"Expected risk_score 65, got {quote['risk_score']}"
    )
    uw = make_underwriter_headers("uw-1")
    resp = api.approve_referral(referral["id"], uw)
    validate_success(resp, expected_status=200)
    updated = get_quote(quote["id"])
    assert updated["status"] == "QUOTED", (
        f"Approved referral must move quote to QUOTED, got {updated['status']}"
    )


def test_referral_resolved_approved_after_loop(api):
    """PRD §3.3: "When an underwriter later approves the referral, the
    referral's `decision` becomes `APPROVED` and its status `RESOLVED`,"

    Design: Difficulty/non_linear_state_machine/quote_referral_loop_back_to_quoted
    """
    setup_class_and_rule(
        code="CC_A", description="Contractor", keyword="contractor",
        eligible_lines=["GL", "PL", "TOOLS"],
        base_rates_cents={"GL": 12000, "PL": 18000, "TOOLS": 6000},
        risk_factor=1.0,
    )
    account = setup_account(legal_name="Risky GC")
    quote, referral = setup_referred_quote(
        account, "contractor", ["GL"], [80], {"q1": "yes", "q2": "yes"},
    )
    uw = make_underwriter_headers("uw-1")
    resp = api.approve_referral(referral["id"], uw)
    resolved = validate_success(resp, expected_status=200)
    assert resolved["status"] == "RESOLVED", (
        f"Referral must be RESOLVED after approval, got {resolved['status']}"
    )
    assert resolved["decision"] == "APPROVED", (
        f"Referral decision must be APPROVED, got {resolved['decision']}"
    )


def test_second_decision_on_resolved_referral_rejected(api):
    """PRD §3.3: "only an `OPEN` referral may be decided, anything else being
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/referral_resolved_cannot_be_decided_twice
    """
    from test_helpers import ApiErrorId, validate_error

    setup_class_and_rule(
        code="CC_A", description="Contractor", keyword="contractor",
        eligible_lines=["GL", "PL", "TOOLS"],
        base_rates_cents={"GL": 12000, "PL": 18000, "TOOLS": 6000},
        risk_factor=1.0,
    )
    account = setup_account(legal_name="Corner GC")
    quote, referral = setup_referred_quote(
        account, "contractor", ["GL"], [80], {"q1": "yes", "q2": "yes"},
    )
    uw = make_underwriter_headers("uw-1")
    validate_success(api.approve_referral(referral["id"], uw), expected_status=200)

    resp = api.approve_referral(referral["id"], uw)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    uw_read = make_underwriter_headers("uw-reader")
    refreshed = validate_success(api.get_referral(referral["id"], uw_read))
    assert refreshed["decision"] == "APPROVED", (
        f"Second decision must not change the referral; got {refreshed['decision']}"
    )


def test_quote_declines_when_rule_window_expired_at_effective_to(api):
    """PRD §3.1: "each rule pairs a lowercase `keyword` with a `class_code` it
    admits, a `disposition` of exactly one of `ADMIT`, `REFER`, or `DECLINE`,
    an active window from `effective_from` (inclusive) to `effective_to`
    (exclusive)".
    PRD §3.1: "If exactly zero classes are admitted the quote is declined
    (`ERR_CLASS_DECLINED`)".

    Design: Difficulty/resource_temporal_overlap/appetite_rule_window_boundary_exclusivity
    """
    setup_class_and_rule(
        code="CC_E", description="Catering", keyword="caterer",
        eligible_lines=["GL"], base_rates_cents={"GL": 5000},
        risk_factor=1.0,
    )
    # Narrow matching: disable the horizon-wide default rule and add the
    # boundary rule as the only in-window rule for this class.
    resp = api_client.list_appetite_rules(ADMIN, params={"class_code": "CC_E"})
    rules = get_success_data(resp)
    assert len(rules) == 1
    resp = api_client.patch_appetite_rule(rules[0]["id"], {"is_enabled": False}, ADMIN)
    assert resp.status_code == 200, f"Setup failed (disable rule): {resp.text}"
    resp = api_client.create_appetite_rule({
        "keyword": "caterer", "class_code": "CC_E", "disposition": "ADMIT",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2026-10-01T00:00:00Z",
        "priority_rank": 1, "is_enabled": True,
    }, ADMIN)
    assert resp.status_code == 201, f"Setup failed (boundary rule): {resp.text}"

    account = setup_account(legal_name="Late Bite")
    set_clock("2026-10-01T00:00:00Z")
    ph = make_policyholder_headers(account["id"])
    resp = api.create_quote(create_quote_payload(
        business_account_id=account["id"],
        raw_description="caterer for events",
        selected_lines=["GL"],
        requested_effective_at="2026-10-01T00:00:00Z",
    ), ph)
    # At clock == effective_to the [from, to) window excludes the rule; with
    # zero admitted classes the quote declines with ERR_CLASS_DECLINED (PRD
    # §3.1 names the error; the error catalog maps it to 422).
    from test_helpers import ApiErrorId, validate_error
    validate_error(resp, ApiErrorId.ERR_CLASS_DECLINED)


def test_quote_matches_one_second_before_window_end(api):
    """PRD §3.1: "an active window from `effective_from` (inclusive) to
    `effective_to` (exclusive)".
    PRD §3.3: "A score below 60 moves the quote from `CLASSIFYING` to
    `QUOTED`:"

    Design: Difficulty/resource_temporal_overlap/appetite_rule_window_boundary_exclusivity
    """
    setup_class_and_rule(
        code="CC_E", description="Catering", keyword="caterer",
        eligible_lines=["GL"], base_rates_cents={"GL": 5000},
        risk_factor=1.0,
    )
    account = setup_account(legal_name="Early Bite")
    set_clock("2026-09-30T23:59:59Z")
    ph = make_policyholder_headers(account["id"])
    resp = api.create_quote(create_quote_payload(
        business_account_id=account["id"],
        raw_description="caterer for events",
        selected_lines=["GL"],
        requested_effective_at="2026-09-30T23:59:59Z",
    ), ph)
    quote = validate_success(resp, expected_status=201)
    # The default rule window (2026-01-01 .. 2027-01-01) still covers the
    # clock one second before 2026-10-01, so the class is admitted.
    assert quote["status"] == "QUOTED", (
        f"In-window classification must quote, got {quote['status']}"
    )
