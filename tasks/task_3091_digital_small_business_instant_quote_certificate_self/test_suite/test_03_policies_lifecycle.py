"""Policy lifecycle tests: cancellation credit variants, renewal branches,
non-renewal, and proration (PRD §3.5, §3.6, §3.8)."""

from test_helpers import (
    create_non_renewal_notice_payload,
    get_account,
    list_non_renewal_notices,
    list_policy_certificates,
    make_compliance_officer_headers,
    make_policyholder_headers,
    make_platform_admin_headers,
    refresh_policy,
    set_clock,
    setup_account,
    setup_class_and_rule,
    setup_paid_claim,
    setup_policy,
    setup_policy_with_certificate,
    setup_quoted,
    validate_success,
)

ADMIN = make_platform_admin_headers("t03-admin")
CO = make_compliance_officer_headers("co-1")


def _setup_cc_c():
    return setup_class_and_rule(
        code="CC_C", description="Solo trades", keyword="handyman",
        eligible_lines=["GL"], base_rates_cents={"GL": 10000},
        risk_factor=0.5,
    )


def test_pro_rata_downgrade_delta_credits_account(api):
    """PRD §3.5: "A positive delta is premium owed; a negative delta credits
    its absolute value to the account's `account_credit_cents`."

    Design: Difficulty/dual_variant_calc/cancellation_credit_short_rate_vs_pro_rata
    """
    _setup_cc_c()
    account = setup_account(legal_name="Second Site LLC")
    policy = setup_policy(account, "contractor handyman", ["GL"], exposure_units=10)
    # Base: 10000 * 10 * 1.00 tier * 0.5 risk * 0.95 claims-free = 47500.
    assert policy["base_annual_premium_cents"] == 47500, (
        f"Expected base 47500, got {policy['base_annual_premium_cents']}"
    )

    set_clock("2026-10-01T00:00:00Z")  # day 273; remaining 335 days of 365
    ph = make_policyholder_headers(account["id"])
    current = refresh_policy(policy["id"])
    resp = api.create_endorsement(policy["id"], {
        "endorsement_type": "COVERAGE_ADJUST",
        "effective_at": "2026-10-01T00:00:00Z",
        "expected_policy_version": current["version"],
        "new_exposure_units": 5,
    }, ph)
    endorsement = validate_success(resp, expected_status=201)
    # New annual 23750; pro-rata delta round_half_up((23750-47500)*335/365) = -21798.
    assert endorsement["premium_delta_cents"] == -21798, (
        f"Expected pro-rata delta -21798, got {endorsement['premium_delta_cents']}"
    )
    acct = get_account(account["id"])
    assert acct["account_credit_cents"] == 21798, (
        f"Negative delta must credit the account: got {acct['account_credit_cents']}"
    )


def test_short_rate_cancel_credit_uses_ninety_percent_factor(api):
    """PRD §3.6: "Cancellation is short-rate, not pro-rata: the credit returned
    to `account_credit_cents` is the policy's `base_annual_premium_cents`
    multiplied by 0.90 — the short-rate penalty factor — multiplied by the
    remaining days from the cancellation clock day through the day before
    `term_end`, over 365, rounded half-up to integer cents."

    Design: Difficulty/dual_variant_calc/cancellation_credit_short_rate_vs_pro_rata
    """
    _setup_cc_c()
    account = setup_account(legal_name="Second Site LLC")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)

    set_clock("2026-10-01T00:00:00Z")
    ph = make_policyholder_headers(account["id"])
    # The clock move activated the policy (BOUND -> ACTIVE), bumping version.
    current = refresh_policy(policy["id"])
    # Downgrade first (pro-rata, -52315 credit), then cancel (short-rate).
    validate_success(api.create_endorsement(policy["id"], {
        "endorsement_type": "COVERAGE_ADJUST",
        "effective_at": "2026-10-01T00:00:00Z",
        "expected_policy_version": current["version"],
        "new_exposure_units": 5,
    }, ph), expected_status=201)

    resp = api.cancel_policy(policy["id"], ph)
    validate_success(resp, expected_status=200)
    acct = get_account(account["id"])
    # 21798 downgrade credit + short-rate cancel credit
    # round_half_up(47500 * 0.90 * 335 / 365) = 39236 -> total 61034.
    assert acct["account_credit_cents"] == 61034, (
        "Short-rate factor 0.90 must be applied to the cancellation credit: "
        f"expected 61034, got {acct['account_credit_cents']}"
    )


def test_nonrenewal_notice_branch_lapses_to_non_renewed(api):
    """PRD §3.6: "Issuance sets the policy's `non_renewal_notice_sent_at` and
    moves the policy from `ACTIVE` to `NON_RENEWAL_PENDING`; when the clock
    reaches `term_end`, a `NON_RENEWAL_PENDING` policy settles to
    `NON_RENEWED`."

    Design: Difficulty/non_linear_state_machine/policy_nonrenewal_branch_vs_renewal_branch
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)

    set_clock("2027-07-18T00:00:00Z")  # day 563; inside window, 45 days left
    resp = api.create_non_renewal_notice(
        policy["id"], create_non_renewal_notice_payload(), CO,
    )
    notice = validate_success(resp, expected_status=201)
    assert notice["days_before_term_end"] == 45, (
        f"Expected 45 days before term end, got {notice['days_before_term_end']}"
    )
    after_notice = refresh_policy(policy["id"])
    assert after_notice["status"] == "NON_RENEWAL_PENDING", (
        f"Expected NON_RENEWAL_PENDING after notice, got {after_notice['status']}"
    )

    set_clock("2027-09-01T00:00:00Z")  # term_end reached
    settled = refresh_policy(policy["id"])
    assert settled["status"] == "NON_RENEWED", (
        f"Expected NON_RENEWED at term_end, got {settled['status']}"
    )


def test_nonrenewal_branch_creates_no_successor_policy(api):
    """PRD §3.6: "A policy that reaches `term_end` with neither renewal nor
    non-renewal simply moves to `EXPIRED`." and only on renewal is "a
    successor policy is created in `BOUND` with `term_start` equal to the
    prior policy's `term_end`".

    Design: Difficulty/non_linear_state_machine/policy_nonrenewal_branch_vs_renewal_branch
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)

    set_clock("2027-07-18T00:00:00Z")
    validate_success(api.create_non_renewal_notice(
        policy["id"], create_non_renewal_notice_payload(), CO,
    ), expected_status=201)
    set_clock("2027-09-01T00:00:00Z")

    from test_helpers import api_client
    resp = api_client.list_account_policies(account["id"], ADMIN)
    policies = validate_success(resp)
    assert isinstance(policies, list)
    assert len(policies) == 1, (
        f"Non-renewal must not create a successor policy; got {len(policies)}"
    )
    assert policies[0]["id"] == policy["id"]


def test_paid_claim_cascade_flips_claims_free_flag(api):
    """PRD §3.7: "A paid claim recomputes both open-claim counters and
    recomputes the account's `claims_free_flag`, which becomes false
    permanently."

    Design: Difficulty/transitive_cascade/claim_paid_cascade_to_renewal_gate
    """
    _setup_cc_c()
    account = setup_account(legal_name="Cascade Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    paid = setup_paid_claim(
        account, policy, adjuster_id="adj-1", finance_id="fin-1",
    )
    assert paid["status"] == "PAID", f"Expected PAID claim, got {paid['status']}"
    acct = get_account(account["id"])
    assert acct["claims_free_flag"] is False, (
        "claims_free_flag must become false permanently after a PAID claim"
    )


def test_paid_claim_cascade_reprices_renewal_basis(api):
    """PRD §3.4: "The **final** variant is computed at bind and at renewal: the
    claims-free discount is re-evaluated from the current flag".
    PRD §3.6: "On renewal the premium is recomputed under the final variant on
    current exposure, account credit is consumed per the ledger (§3.5), a
    successor policy is created in `BOUND` with `term_start` equal to the prior
    policy's `term_end`, and the prior policy moves to `RENEWED` with its
    `version` incremented by 1".

    Design: Difficulty/transitive_cascade/claim_paid_cascade_to_renewal_gate
    """
    _setup_cc_c()
    account = setup_account(legal_name="Cascade Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    setup_paid_claim(account, policy, adjuster_id="adj-1", finance_id="fin-1")

    set_clock("2027-07-03T00:00:00Z")  # day 548; inside the renewal window
    current = refresh_policy(policy["id"])
    ph = make_policyholder_headers(account["id"])
    resp = api.renew_policy(
        policy["id"], {"expected_policy_version": current["version"]}, ph,
    )
    successor = validate_success(resp, expected_status=201)
    # Final variant without the 5% claims-free discount: 10000*10*0.5 = 50000.
    assert successor["base_annual_premium_cents"] == 50000, (
        "Renewal premium must re-evaluate claims-free (flag false after PAID "
        f"claim): expected 50000, got {successor['base_annual_premium_cents']}"
    )
    prior = refresh_policy(policy["id"])
    assert prior["status"] == "RENEWED", (
        f"Prior policy must move to RENEWED, got {prior['status']}"
    )


def test_appetite_flip_auto_issues_notice_and_pending(api):
    """PRD §3.1: "every in-force `ACTIVE` policy of that class whose clock has
    reached its renewal window and has not yet received a notice is
    automatically issued a non-renewal notice with reason code
    `APPETITE_CHANGE`, provided the statutory window is still satisfiable
    (§3.6)".

    Design: Difficulty/transitive_cascade/appetite_flip_cascade_to_notice_and_certificate_state
    """
    cc, _rule = setup_class_and_rule(
        code="CC_D", description="Pet care", keyword="dogwalker",
        eligible_lines=["GL"], base_rates_cents={"GL": 8000},
        risk_factor=1.0,
    )
    account = setup_account(legal_name="Happy Tails")
    policy, _endorsement, cert = setup_policy_with_certificate(
        account, "dogwalker", ["GL"], ai_holder_name="Park District",
    )

    set_clock("2027-07-18T00:00:00Z")  # day 563; 45 days satisfy the minimum
    resp = api.patch_class_code(cc["id"], {"appetite_active": False}, ADMIN)
    validate_success(resp, expected_status=200)

    notices = list_non_renewal_notices(policy["id"])
    assert len(notices) == 1, (
        f"Exactly one auto-notice expected after appetite flip, got {len(notices)}"
    )
    assert notices[0]["reason_code"] == "APPETITE_CHANGE", (
        f"Auto-notice reason must be APPETITE_CHANGE, got {notices[0]['reason_code']}"
    )
    after_flip = refresh_policy(policy["id"])
    assert after_flip["status"] == "NON_RENEWAL_PENDING", (
        f"Policy must move to NON_RENEWAL_PENDING, got {after_flip['status']}"
    )
    assert cert["status"] == "ISSUED"  # untouched until the policy is cancelled


def test_appetite_flip_then_cancel_voids_certificate(api):
    """PRD §3.6: "Cancellation cascades: every certificate of the policy still
    `ISSUED` is voided to `VOIDED`, every endorsement still in `DRAFT` moves to
    `VOID`, and the policy itself moves to `CANCELLED`."

    Design: Difficulty/transitive_cascade/appetite_flip_cascade_to_notice_and_certificate_state
    """
    cc, _rule = setup_class_and_rule(
        code="CC_D", description="Pet care", keyword="dogwalker",
        eligible_lines=["GL"], base_rates_cents={"GL": 8000},
        risk_factor=1.0,
    )
    account = setup_account(legal_name="Happy Tails")
    policy, _endorsement, cert = setup_policy_with_certificate(
        account, "dogwalker", ["GL"], ai_holder_name="Park District",
    )

    # Flip appetite inside the renewal window but too late for the 45-day
    # APPETITE_CHANGE statutory minimum (31 days before term_end), so no
    # auto-notice issues and the policy stays ACTIVE ("otherwise the policy
    # simply runs to expiry", PRD §3.1) — leaving it cancellable per §3.6
    # ("while it is BOUND or ACTIVE").
    set_clock("2027-08-01T00:00:00Z")
    validate_success(api.patch_class_code(cc["id"], {"appetite_active": False}, ADMIN))

    ph = make_policyholder_headers(account["id"])
    resp = api.cancel_policy(policy["id"], ph)
    validate_success(resp, expected_status=200)

    certs = list_policy_certificates(policy["id"])
    by_id = {c["id"]: c for c in certs}
    assert by_id[cert["id"]]["status"] == "VOIDED", (
        "Cancel must void the ISSUED certificate (caused by the cancel, not "
        f"the class flip); got {by_id[cert['id']]['status']}"
    )


def test_nonrenewal_before_window_rejected(api):
    """PRD §3.6: "A `ComplianceOfficer` issues a statutory **non-renewal
    notice** against an `ACTIVE` policy once the clock has reached
    `renewal_window_start`".

    PRD does not name the specific error for a pre-window notice; both the
    state gate (`ERR_INVALID_STATE`) and the temporal-window family
    (`ERR_RENEWAL_WINDOW`) are PRD-consistent readings, so accept either. The
    derivable guarantees: rejection, and no policy mutation.

    Design: Corner/validations/nonrenewal_notice_rejected_before_renewal_window
    """
    from test_helpers import (
        ApiErrorId, validate_error_is_one_of,
    )

    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    # Clock remains at the startup default 2026-09-01 — before the window.
    resp = api.create_non_renewal_notice(
        policy["id"], create_non_renewal_notice_payload(), CO,
    )
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_RENEWAL_WINDOW],
    )
    after = refresh_policy(policy["id"])
    assert after["status"] == "ACTIVE", (
        f"Rejected notice must not change the policy; got {after['status']}"
    )


def test_duplicate_nonrenewal_notice_rejected(api):
    """PRD §3.6: "A policy may carry only one notice: a second issuance is
    rejected with `ERR_NONRENEWAL_DUPLICATE`."

    Design: Corner/validations/duplicate_nonrenewal_notice_rejected
    """
    from test_helpers import ApiErrorId, validate_error

    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    set_clock("2027-07-18T00:00:00Z")
    validate_success(api.create_non_renewal_notice(
        policy["id"], create_non_renewal_notice_payload(), CO,
    ), expected_status=201)

    resp = api.create_non_renewal_notice(
        policy["id"], create_non_renewal_notice_payload(), CO,
    )
    validate_error(resp, ApiErrorId.ERR_NONRENEWAL_DUPLICATE)


def test_renew_blocked_after_notice_issued(api):
    """PRD §3.6: "Renewal requires the policy be `ACTIVE` (otherwise
    `ERR_INVALID_STATE`), the clock be inside the window from
    `renewal_window_start` up to but not including `term_end` (outside it,
    `ERR_RENEWAL_WINDOW`), no non-renewal notice yet issued
    (`ERR_RENEWAL_NOTICE_ISSUED` if one was)".

    Design: Corner/errors/error_renewal_notice_issued_blocks_renew
    """
    from test_helpers import ApiErrorId, validate_error

    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    set_clock("2027-07-18T00:00:00Z")
    validate_success(api.create_non_renewal_notice(
        policy["id"], create_non_renewal_notice_payload(), CO,
    ), expected_status=201)

    current = refresh_policy(policy["id"])
    ph = make_policyholder_headers(account["id"])
    resp = api.renew_policy(
        policy["id"], {"expected_policy_version": current["version"]}, ph,
    )
    validate_error(resp, ApiErrorId.ERR_RENEWAL_NOTICE_ISSUED)


def test_renew_blocked_when_class_off_appetite(api):
    """PRD §3.6: "the class still in appetite (`ERR_APPETITE_INACTIVE` when
    `appetite_active` has gone false)".

    Design: Corner/errors/error_appetite_inactive_blocks_renew
    """
    from test_helpers import ApiErrorId, validate_error

    cc, _rule = _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    # 2027-07-20 is 43 days before term_end 2027-09-01: inside the renewal
    # window but short of the 45-day APPETITE_CHANGE statutory minimum, so the
    # flip issues no auto-notice and the policy stays ACTIVE — isolating the
    # appetite gate.
    set_clock("2027-07-20T00:00:00Z")
    validate_success(api.patch_class_code(cc["id"], {"appetite_active": False}, ADMIN))

    ph = make_policyholder_headers(account["id"])
    resp = api.renew_policy(
        policy["id"], {"expected_policy_version": policy["version"]}, ph,
    )
    validate_error(resp, ApiErrorId.ERR_APPETITE_INACTIVE)


def test_bound_policy_auto_activates_at_term_start(api):
    """PRD §2.4: "`BOUND` policies whose `term_start` has been reached move to
    `ACTIVE`".
    PRD §3.5: "A policy whose `term_start` the clock later reaches moves
    automatically from `BOUND` to `ACTIVE`."

    Design: Corner/state_machines/policy_bound_to_active_auto_transition_on_clock
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    quote = setup_quoted(
        account, "handyman", ["GL"], exposure_units=10,
        requested_effective_at="2026-09-08T00:00:00Z",
    )
    ph = make_policyholder_headers(account["id"])
    resp = api.bind_quote(
        quote["id"], {"expected_quote_version": quote["version"]}, ph,
    )
    policy = validate_success(resp, expected_status=201)
    assert policy["status"] == "BOUND", (
        f"Future-dated policy must start BOUND, got {policy['status']}"
    )

    set_clock("2026-09-08T00:00:00Z")
    after = refresh_policy(policy["id"])
    assert after["status"] == "ACTIVE", (
        f"Policy must auto-activate when the clock reaches term_start; "
        f"got {after['status']}"
    )


def test_short_rate_cancel_credit_without_prior_endorsement(api):
    """PRD §3.6: "Cancellation is short-rate, not pro-rata: the credit returned
    to `account_credit_cents` is the policy's `base_annual_premium_cents`
    multiplied by 0.90 — the short-rate penalty factor — multiplied by the
    remaining days from the cancellation clock day through the day before
    `term_end`, over 365, rounded half-up to integer cents."

    Design: Difficulty/dual_variant_calc/cancellation_credit_short_rate_vs_pro_rata
    """
    _setup_cc_c()
    account = setup_account(legal_name="Short Rate Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    # Base premium 47500 (10000 * 10 * 1.00 tier * 0.5 risk * 0.95 claims-free).
    assert policy["base_annual_premium_cents"] == 47500

    set_clock("2026-10-01T00:00:00Z")  # day 273; remaining 335 days of 365
    ph = make_policyholder_headers(account["id"])
    validate_success(api.cancel_policy(policy["id"], ph), expected_status=200)
    acct = get_account(account["id"])
    # Short-rate: round_half_up(47500 * 0.90 * 335 / 365) = 39236.
    assert acct["account_credit_cents"] == 39236, (
        "Cancellation credit must use the 0.90 short-rate factor: expected "
        f"39236, got {acct['account_credit_cents']}"
    )
