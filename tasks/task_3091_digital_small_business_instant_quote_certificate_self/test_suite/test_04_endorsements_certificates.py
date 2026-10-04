"""Endorsement, certificate, and account-credit-ledger tests (PRD §3.5, §3.8)."""

from test_helpers import (
    ApiErrorId,
    create_effective_endorsement,
    get_account,
    get_success_data,
    list_policy_certificates,
    make_platform_admin_headers,
    make_policyholder_headers,
    refresh_policy,
    set_clock,
    setup_account,
    setup_class_and_rule,
    setup_policy,
    setup_policy_with_certificate,
    submit_claim,
    validate_error,
    validate_success,
)

ADMIN = make_platform_admin_headers("t04-admin")


def _setup_cc_c():
    return setup_class_and_rule(
        code="CC_C", description="Solo trades", keyword="handyman",
        eligible_lines=["GL"], base_rates_cents={"GL": 10000},
        risk_factor=0.5,
    )


def _setup_cc_a():
    return setup_class_and_rule(
        code="CC_A", description="Contractor", keyword="contractor",
        eligible_lines=["GL", "PL", "TOOLS"],
        base_rates_cents={"GL": 12000, "PL": 18000, "TOOLS": 6000},
        risk_factor=1.0,
    )


def test_endorsement_effective_immediately_and_bumps_policy_version(api):
    """PRD §3.5: "Endorsements take effect on submission: after validation the
    endorsement moves from `DRAFT` to `EFFECTIVE` immediately".
    PRD §3.5: "every effective endorsement refreshes the policy's `updated_at`
    and increments its `version` by 1".

    Design: Corner/state_machines/endorsement_from_effective_cannot_transition_again
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    endorsement = create_effective_endorsement(account, policy, {
        "endorsement_type": "ADDITIONAL_INSURED",
        "effective_at": "2026-09-01T00:00:00Z",
        "ai_holder_name": "Landlord LP",
    })
    assert endorsement["status"] == "EFFECTIVE", (
        f"Endorsement must be EFFECTIVE on creation, got {endorsement['status']}"
    )
    updated = refresh_policy(policy["id"])
    assert updated["version"] == policy["version"] + 1, (
        f"Policy version must increment by 1: {policy['version']} -> "
        f"{updated['version']}"
    )


def test_certificate_on_wrong_endorsement_type_rejected(api):
    """PRD §3.8: "The referenced endorsement must be an `EFFECTIVE`
    `ADDITIONAL_INSURED` endorsement on that same policy; anything else is
    rejected with `ERR_CERT_ENDORSEMENT_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/certificate_requires_effective_endorsement
    """
    _setup_cc_a()
    account = setup_account(legal_name="Cert Co")
    policy = setup_policy(account, "contractor", ["GL"], exposure_units=10)
    wrong_type = create_effective_endorsement(account, policy, {
        "endorsement_type": "COVERAGE_ADJUST",
        "effective_at": "2026-09-01T00:00:00Z",
        "new_exposure_units": 12,
    })
    assert wrong_type["status"] == "EFFECTIVE"

    ph = make_policyholder_headers(account["id"])
    resp = api.create_certificate(
        {"policy_id": policy["id"], "endorsement_id": wrong_type["id"]}, ph,
    )
    validate_error(resp, ApiErrorId.ERR_CERT_ENDORSEMENT_INVALID)


def test_certificate_on_non_ai_endorsement_rejected_corner(api):
    """PRD §3.8: "The referenced endorsement must be an `EFFECTIVE`
    `ADDITIONAL_INSURED` endorsement on that same policy; anything else is
    rejected with `ERR_CERT_ENDORSEMENT_INVALID`."

    Design: Corner/errors/error_cert_endorsement_invalid
    """
    _setup_cc_a()
    account = setup_account(legal_name="Corner GC")
    policy = setup_policy(account, "contractor", ["GL"], exposure_units=10)
    coverage_adjust = create_effective_endorsement(account, policy, {
        "endorsement_type": "COVERAGE_ADJUST",
        "effective_at": "2026-09-01T00:00:00Z",
        "new_exposure_units": 12,
    })
    ph = make_policyholder_headers(account["id"])
    resp = api.create_certificate(
        {"policy_id": policy["id"], "endorsement_id": coverage_adjust["id"]}, ph,
    )
    validate_error(resp, ApiErrorId.ERR_CERT_ENDORSEMENT_INVALID)


def test_endorsement_rejected_on_cancelled_policy(api):
    """PRD §3.5: "Mid-term change is expressed through **endorsements**,
    created by a `Policyholder` or an `Agent` against an `ACTIVE` policy."
    PRD §2.7: "then whether the target resource is in a state that permits the
    operation at all (`ERR_INVALID_STATE` and the domain-specific state
    errors)".

    Design: Difficulty/cross_entity_state_dependency/endorsement_requires_active_policy
    """
    _setup_cc_c()
    account = setup_account(legal_name="Endo Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    ph = make_policyholder_headers(account["id"])
    validate_success(api.cancel_policy(policy["id"], ph), expected_status=200)
    current = refresh_policy(policy["id"])

    resp = api.create_endorsement(policy["id"], {
        "endorsement_type": "ADDITIONAL_INSURED",
        "effective_at": "2026-09-01T00:00:00Z",
        "expected_policy_version": current["version"],
        "ai_holder_name": "Too Late LLC",
    }, ph)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_endorsement_backdated_before_term_start_rejected(api):
    """PRD §3.5: "The `effective_at` must fall on or after the policy's
    `term_start` day at 00:00:00Z and no later than the end of the current
    clock day — outside that window the request is rejected with
    `ERR_ENDORSEMENT_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/endorsement_backdating_blocked_beyond_term_start
    """
    _setup_cc_c()
    account = setup_account(legal_name="Backdate Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    set_clock("2026-09-10T00:00:00Z")
    ph = make_policyholder_headers(account["id"])
    resp = api.create_endorsement(policy["id"], {
        "endorsement_type": "ADDITIONAL_INSURED",
        "effective_at": "2026-08-31T23:59:59Z",
        "expected_policy_version": policy["version"],
        "ai_holder_name": "Backdated Holder",
    }, ph)
    validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_WINDOW)


def test_endorsement_before_term_start_day_rejected_corner(api):
    """PRD §3.5: "The `effective_at` must fall on or after the policy's
    `term_start` day at 00:00:00Z and no later than the end of the current
    clock day — outside that window the request is rejected with
    `ERR_ENDORSEMENT_WINDOW`."

    Design: Corner/errors/error_endorsement_window_before_term_start
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    ph = make_policyholder_headers(account["id"])
    resp = api.create_endorsement(policy["id"], {
        "endorsement_type": "ADDITIONAL_INSURED",
        "effective_at": "2026-08-15T00:00:00Z",
        "expected_policy_version": policy["version"],
        "ai_holder_name": "Early Bird LLC",
    }, ph)
    validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_WINDOW)


def test_last_line_removal_rejected(api):
    """PRD §3.5: "a removal that would leave zero lines is
    `ERR_LAST_LINE_REMOVAL`."

    Design: Corner/errors/error_last_line_removal
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    ph = make_policyholder_headers(account["id"])
    resp = api.create_endorsement(policy["id"], {
        "endorsement_type": "LIMIT_CHANGE",
        "effective_at": "2026-09-01T00:00:00Z",
        "expected_policy_version": policy["version"],
        "removed_lines": ["GL"],
    }, ph)
    validate_error(resp, ApiErrorId.ERR_LAST_LINE_REMOVAL)


def test_line_overlap_between_add_and_remove_rejected(api):
    """PRD §3.5: "intersecting add/remove sets or re-adding an in-force line
    are `ERR_LINE_OVERLAP`,"

    Design: Corner/errors/error_line_overlap_add_and_remove
    """
    _setup_cc_a()
    account = setup_account(legal_name="Corner GC")
    policy = setup_policy(account, "contractor", ["GL", "TOOLS"], exposure_units=10)
    ph = make_policyholder_headers(account["id"])
    resp = api.create_endorsement(policy["id"], {
        "endorsement_type": "LIMIT_CHANGE",
        "effective_at": "2026-09-01T00:00:00Z",
        "expected_policy_version": policy["version"],
        "added_lines": ["PL"],
        "removed_lines": ["PL"],
    }, ph)
    validate_error(resp, ApiErrorId.ERR_LINE_OVERLAP)


def test_cancel_voids_certificate_but_keeps_effective_endorsement(api):
    """PRD §3.6: "Cancellation cascades: every certificate of the policy still
    `ISSUED` is voided to `VOIDED`, every endorsement still in `DRAFT` moves to
    `VOID`, and the policy itself moves to `CANCELLED`."

    Design: Corner/state_machines/cancel_cascades_void_certificates_and_draft_endorsements
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy, endorsement, cert = setup_policy_with_certificate(
        account, "handyman", ["GL"], ai_holder_name="Landlord LP",
    )
    ph = make_policyholder_headers(account["id"])
    validate_success(api.cancel_policy(policy["id"], ph), expected_status=200)

    certs = list_policy_certificates(policy["id"])
    by_id = {c["id"]: c for c in certs}
    assert by_id[cert["id"]]["status"] == "VOIDED", (
        f"ISSUED certificate must be voided on cancel; got "
        f"{by_id[cert['id']]['status']}"
    )

    from test_helpers import api_client
    endorsements = get_success_data(
        api_client.list_policy_endorsements(policy["id"], ADMIN)
    )
    eff = {e["id"]: e for e in endorsements}
    assert eff[endorsement["id"]]["status"] == "EFFECTIVE", (
        "Cancellation voids DRAFT endorsements and ISSUED certificates only; "
        f"the EFFECTIVE endorsement must remain, got "
        f"{eff[endorsement['id']]['status']}"
    )

    updated = refresh_policy(policy["id"])
    assert updated["status"] == "CANCELLED", (
        f"Policy must be CANCELLED, got {updated['status']}"
    )


def test_certificate_numbers_monotonic_across_endorsements(api):
    """PRD §3.8: "receives a display `certificate_no` of the form
    `CERT-<policy ordinal>-<n>`, where the policy ordinal is the zero-padded
    creation order of the policy within its account (determined by `created_at`
    ascending, never by `id`) and `n` is the count of certificates ever created
    for the policy — in any status — plus one. Certificate numbers are
    monotonic and never reused, even after voiding."

    Design: Corner/calculations/certificate_sequence_never_reuses_numbers_after_void
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    ph = make_policyholder_headers(account["id"])

    e1 = create_effective_endorsement(account, policy, {
        "endorsement_type": "ADDITIONAL_INSURED",
        "effective_at": "2026-09-01T00:00:00Z",
        "ai_holder_name": "Holder One",
    })
    cert_1 = validate_success(api.create_certificate(
        {"policy_id": policy["id"], "endorsement_id": e1["id"]}, ph,
    ), expected_status=201)

    e2 = create_effective_endorsement(account, policy, {
        "endorsement_type": "ADDITIONAL_INSURED",
        "effective_at": "2026-09-01T00:00:00Z",
        "ai_holder_name": "Holder Two",
    })
    cert_2 = validate_success(api.create_certificate(
        {"policy_id": policy["id"], "endorsement_id": e2["id"]}, ph,
    ), expected_status=201)

    assert cert_1["certificate_no"].endswith("-1"), (
        f"First certificate must carry n=1, got {cert_1['certificate_no']}"
    )
    assert cert_2["certificate_no"].endswith("-2"), (
        f"Second certificate must carry n=2, got {cert_2['certificate_no']}"
    )
    assert cert_1["certificate_no"] != cert_2["certificate_no"]


def test_occ_endorsement_happy_path_increments_version(api):
    """PRD §2.8: "Creating an endorsement against a policy requires
    `expected_policy_version` matching the policy's current `version`; a
    mismatch — because an earlier endorsement or a cancellation advanced the
    proration baseline the client computed against — is rejected with
    `ERR_STALE_POLICY_VERSION` (HTTP 412)."
    PRD §3.5: "every effective endorsement refreshes the policy's `updated_at`
    and increments its `version` by 1".
    PRD §3.5: "A `COVERAGE_ADJUST` additionally replaces the policy's
    `exposure_units` with `new_exposure_units`".

    Design: Corner/cross_cutting_layers/occ_endorsement_happy_path_version_increments
    """
    _setup_cc_a()
    account = setup_account(legal_name="Corner GC")
    policy = setup_policy(account, "contractor", ["GL"], exposure_units=10)
    ph = make_policyholder_headers(account["id"])
    resp = api.create_endorsement(policy["id"], {
        "endorsement_type": "COVERAGE_ADJUST",
        "effective_at": "2026-09-01T00:00:00Z",
        "expected_policy_version": policy["version"],
        "new_exposure_units": 12,
    }, ph)
    validate_success(resp, expected_status=201)

    updated = refresh_policy(policy["id"])
    assert updated["version"] == policy["version"] + 1, (
        f"Correct expected version must succeed and increment by 1: "
        f"{policy['version']} -> {updated['version']}"
    )
    assert updated["exposure_units"] == 12, (
        f"COVERAGE_ADJUST must replace exposure_units, got {updated['exposure_units']}"
    )


def test_earned_premium_invariant_after_downgrade(api):
    """PRD §3.8: "Earned premium is the sum, over the segments intersecting the
    span from `term_start` through the current clock day — or through the
    cancellation day when the policy is `CANCELLED` — of each segment's annual
    basis multiplied by the number of its days inside that span and divided by
    365, with the final sum rounded half-up to integer cents."
    PRD §3.8: "The books must always balance: earned premium plus the unearned
    remainder — the last segment's basis times its remaining days over 365,
    rounded half-up — equals the base annual premium plus the sum of all
    positive endorsement deltas minus the sum of the absolute values of all
    negative endorsement deltas."

    Design: Difficulty/compensating_invariant/earned_premium_invariant
    """
    setup_class_and_rule(
        code="CC_I", description="Invariant", keyword="invariant",
        eligible_lines=["GL"], base_rates_cents={"GL": 100},
        risk_factor=1.0,
    )
    account = setup_account(legal_name="Invariant Co")
    policy = setup_policy(account, "invariant", ["GL"], exposure_units=3650)
    # Base: round_half_up(100 * 3650 * 1.3 * 0.95) = 450775.
    assert policy["base_annual_premium_cents"] == 450775, (
        f"Expected base 450775, got {policy['base_annual_premium_cents']}"
    )

    set_clock("2026-10-01T00:00:00Z")  # day 273; remaining 335
    endorsement = create_effective_endorsement(account, policy, {
        "endorsement_type": "COVERAGE_ADJUST",
        "effective_at": "2026-10-01T00:00:00Z",
        "new_exposure_units": 1825,
    })
    # New premium 225388; delta = round_half_up(-225387 * 335 / 365) = -206862.
    assert endorsement["premium_delta_cents"] == -206862, (
        f"Expected delta -206862, got {endorsement['premium_delta_cents']}"
    )

    set_clock("2026-10-31T00:00:00Z")  # day 303
    updated = refresh_policy(policy["id"])
    # Segments (span is term_start day 243 THROUGH clock day 303, inclusive):
    # 450775 * 30/365 -> 37050 (days 243..272); 225388 * 31/365 -> 19142.7
    # (days 273..303); sum 56192.7 -> round_half_up 56193.
    assert updated["earned_premium_cents"] == 56193, (
        f"Expected earned 56193, got {updated['earned_premium_cents']}"
    )
    unearned = 187720  # round_half_up(225388 * (607 - 304 + 1) / 365)
    assert updated["earned_premium_cents"] + unearned == (
        policy["base_annual_premium_cents"] + endorsement["premium_delta_cents"]
    ), "Earned plus unearned must equal base plus signed endorsement deltas"


def test_account_credit_conservation_across_renewal(api):
    """PRD §3.5: "`account_credit_cents` accrues the absolute value of negative
    endorsement deltas and short-rate cancellation credits, with accrual events
    applied in creation order. Credit is consumed only at renewal bind — never
    mid-term — where it is applied first against the successor policy's
    premium: the consumed amount is the lesser of the available credit and the
    renewal premium, the remainder is payable, and the pool floors at 0 and
    never goes negative."

    Design: Difficulty/compensating_invariant/account_credit_conservation_invariant
    """
    setup_class_and_rule(
        code="CC_I", description="Invariant", keyword="invariant",
        eligible_lines=["GL"], base_rates_cents={"GL": 100},
        risk_factor=1.0,
    )
    setup_class_and_rule(
        code="CC_J", description="Adjunct", keyword="adjunct",
        eligible_lines=["PL"], base_rates_cents={"PL": 200},
        risk_factor=1.0,
    )
    account = setup_account(legal_name="Credit Co")
    p_a = setup_policy(account, "invariant", ["GL"], exposure_units=3650)
    p_b = setup_policy(account, "adjunct", ["PL"], exposure_units=1000)
    # P_B base: round_half_up(200 * 1000 * 1.3 * 0.95) = 247000.
    assert p_b["base_annual_premium_cents"] == 247000

    set_clock("2026-10-01T00:00:00Z")
    create_effective_endorsement(account, p_a, {
        "endorsement_type": "COVERAGE_ADJUST",
        "effective_at": "2026-10-01T00:00:00Z",
        "new_exposure_units": 1825,
    })  # credits 206862

    set_clock("2026-10-31T00:00:00Z")  # day 303
    ph = make_policyholder_headers(account["id"])
    validate_success(api.cancel_policy(p_b["id"], ph), expected_status=200)
    # Short-rate credit round_half_up(247000 * 0.9 * 305 / 365) = 185758.
    acct_pre = get_account(account["id"])
    assert acct_pre["account_credit_cents"] == 392620, (
        f"Expected accrued credit 392620, got {acct_pre['account_credit_cents']}"
    )

    set_clock("2027-07-03T00:00:00Z")  # day 548; inside P_A renewal window
    current = refresh_policy(p_a["id"])
    resp = api.renew_policy(
        p_a["id"], {"expected_policy_version": current["version"]}, ph,
    )
    successor = validate_success(resp, expected_status=201)
    # Final variant on current exposure (downgrade lineage: no 3% uplift),
    # claims_free still true: 225388.
    assert successor["base_annual_premium_cents"] == 225388, (
        f"Expected renewal premium 225388, got "
        f"{successor['base_annual_premium_cents']}"
    )
    acct_post = get_account(account["id"])
    # consumed = min(392620, 225388) = 225388; balance = 167232.
    assert acct_post["account_credit_cents"] == 167232, (
        f"Credit conservation violated: expected 167232, got "
        f"{acct_post['account_credit_cents']}"
    )


def test_earned_premium_recomputed_on_read_after_downgrade_to_zero(api):
    """PRD §3.8: "the policy's `earned_premium_cents` is a derived figure
    reconciled to the clock whenever the policy is read and after every
    premium-affecting mutation."

    Design: Corner/calculations/earned_premium_reconciles_on_every_read
    """
    setup_class_and_rule(
        code="CC_I", description="Invariant", keyword="invariant",
        eligible_lines=["GL"], base_rates_cents={"GL": 100},
        risk_factor=1.0,
    )
    account = setup_account(legal_name="Invariant Co")
    policy = setup_policy(account, "invariant", ["GL"], exposure_units=730)
    # Base: round_half_up(100 * 730 * 1.3 * 0.95) = 90155; daily exactly 247.
    assert policy["base_annual_premium_cents"] == 90155, (
        f"Expected base 90155, got {policy['base_annual_premium_cents']}"
    )

    set_clock("2026-10-01T00:00:00Z")  # day 273
    create_effective_endorsement(account, policy, {
        "endorsement_type": "COVERAGE_ADJUST",
        "effective_at": "2026-10-01T00:00:00Z",
        "new_exposure_units": 0,
    })

    set_clock("2026-10-31T00:00:00Z")  # day 303; 60 days in force
    updated = refresh_policy(policy["id"])
    # 30 days at 247/day + 30 days at 0 = 7410.
    assert updated["earned_premium_cents"] == 7410, (
        f"Expected earned 7410 reconciled on read, got "
        f"{updated['earned_premium_cents']}"
    )


def test_policy_read_returns_derived_bundle(api):
    """PRD §3.8: "the policy's `earned_premium_cents` is a derived figure
    reconciled to the clock whenever the policy is read".
    PRD §3.7: "Intake recomputes `open_claim_count` on both the policy and the
    account."
    PRD §3.6: "Renewal opens 120 days before `term_end` — the policy's
    `renewal_window_start` is `term_end` minus 120 days".

    Design: Corner/endpoints/computed_read_returns_derived_fields
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = submit_claim(account, policy, claim_amount_cents=150000)
    assert claim["status"] == "SUBMITTED"

    set_clock("2026-10-31T00:00:00Z")  # day 303; 61 days in force (243..303)
    updated = refresh_policy(policy["id"])
    assert updated["open_claim_count"] == 1, (
        f"Expected one open claim, got {updated['open_claim_count']}"
    )
    # Base 47500 (10000 * 10 * 1.00 * 0.5 * 0.95);
    # round_half_up(47500 * 61 / 365) = 7938.
    assert updated["earned_premium_cents"] == 7938, (
        f"Expected earned 7938, got {updated['earned_premium_cents']}"
    )
    assert updated["renewal_window_start"] == "2027-05-04T00:00:00.000Z", (
        f"renewal_window_start must be term_end - 120 days, got "
        f"{updated['renewal_window_start']}"
    )


def test_policy_list_status_filter_excludes_cancelled(api):
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.6: "the policy itself moves to `CANCELLED`."

    Design: Corner/endpoints/policy_list_filter_by_status_and_pagination
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    p_a = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    ph = make_policyholder_headers(account["id"])
    validate_success(api.cancel_policy(p_a["id"], ph), expected_status=200)
    p_b = setup_policy(account, "handyman", ["GL"], exposure_units=10)

    from test_helpers import api_client
    resp = api_client.list_account_policies(
        account["id"], ADMIN, params={"status": "ACTIVE"},
    )
    policies = validate_success(resp)
    assert isinstance(policies, list)
    ids = [p["id"] for p in policies]
    assert ids == [p_b["id"]], (
        f"Status filter must return only the ACTIVE policy; got {ids}"
    )
    assert p_a["id"] not in ids, "CANCELLED policy must be excluded"


def test_certificate_on_endorsement_from_other_policy_rejected(api):
    """PRD §3.8: "The referenced endorsement must be an `EFFECTIVE`
    `ADDITIONAL_INSURED` endorsement on that same policy; anything else is
    rejected with `ERR_CERT_ENDORSEMENT_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/certificate_requires_effective_endorsement
    """
    _setup_cc_c()
    account = setup_account(legal_name="Cert Co")
    p_one = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    p_two = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    ai = create_effective_endorsement(account, p_two, {
        "endorsement_type": "ADDITIONAL_INSURED",
        "effective_at": "2026-09-01T00:00:00Z",
        "ai_holder_name": "Other Policy Holder",
    })
    assert ai["status"] == "EFFECTIVE"
    ph = make_policyholder_headers(account["id"])
    # EFFECTIVE and ADDITIONAL_INSURED, but on a different policy.
    resp = api.create_certificate(
        {"policy_id": p_one["id"], "endorsement_id": ai["id"]}, ph,
    )
    validate_error(resp, ApiErrorId.ERR_CERT_ENDORSEMENT_INVALID)


def test_endorsement_rejected_on_cancelled_policy_as_agent(api):
    """PRD §3.5: "Mid-term change is expressed through **endorsements**,
    created by a `Policyholder` or an `Agent` against an `ACTIVE` policy."
    PRD §2.7: "then whether the target resource is in a state that permits the
    operation at all (`ERR_INVALID_STATE` and the domain-specific state
    errors)".

    Design: Difficulty/cross_entity_state_dependency/endorsement_requires_active_policy
    """
    from test_helpers import make_agent_headers

    _setup_cc_c()
    account = setup_account(legal_name="Endo Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    ph = make_policyholder_headers(account["id"])
    validate_success(api.cancel_policy(policy["id"], ph), expected_status=200)
    current = refresh_policy(policy["id"])

    agent = make_agent_headers("agent-1")
    resp = api.create_endorsement(policy["id"], {
        "endorsement_type": "COVERAGE_ADJUST",
        "effective_at": "2026-09-01T00:00:00Z",
        "expected_policy_version": current["version"],
        "new_exposure_units": 5,
    }, agent)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_endorsement_future_effective_rejected(api):
    """PRD §3.5: "The `effective_at` must fall on or after the policy's
    `term_start` day at 00:00:00Z and no later than the end of the current
    clock day — outside that window the request is rejected with
    `ERR_ENDORSEMENT_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/endorsement_backdating_blocked_beyond_term_start
    """
    _setup_cc_c()
    account = setup_account(legal_name="Future Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    set_clock("2026-09-10T00:00:00Z")
    ph = make_policyholder_headers(account["id"])
    resp = api.create_endorsement(policy["id"], {
        "endorsement_type": "ADDITIONAL_INSURED",
        "effective_at": "2026-09-11T00:00:00Z",  # beyond the clock day
        "expected_policy_version": policy["version"],
        "ai_holder_name": "Future Holder",
    }, ph)
    validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_WINDOW)


def test_earned_premium_invariant_on_clean_term(api):
    """PRD §3.8: "The books must always balance: earned premium plus the
    unearned remainder — the last segment's basis times its remaining days over
    365, rounded half-up — equals the base annual premium plus the sum of all
    positive endorsement deltas minus the sum of the absolute values of all
    negative endorsement deltas."

    Design: Difficulty/compensating_invariant/earned_premium_invariant
    """
    setup_class_and_rule(
        code="CC_I", description="Invariant", keyword="invariant",
        eligible_lines=["GL"], base_rates_cents={"GL": 100},
        risk_factor=1.0,
    )
    account = setup_account(legal_name="Invariant Co")
    policy = setup_policy(account, "invariant", ["GL"], exposure_units=3650)
    assert policy["base_annual_premium_cents"] == 450775

    set_clock("2026-10-31T00:00:00Z")  # day 303; 61 days in force (243..303)
    updated = refresh_policy(policy["id"])
    # Single segment: 450775 * 61 / 365 = 75335 exactly.
    assert updated["earned_premium_cents"] == 75335, (
        f"Expected earned 75335, got {updated['earned_premium_cents']}"
    )
    unearned = 375440  # 450775 * 304 / 365 exactly (days 304..607)
    assert updated["earned_premium_cents"] + unearned == (
        policy["base_annual_premium_cents"]
    ), "With no endorsements the invariant reduces to earned + unearned == base"


def test_credit_not_consumed_before_renewal(api):
    """PRD §3.5: "Credit is consumed only at renewal bind — never mid-term —
    where it is applied first against the successor policy's premium: the
    consumed amount is the lesser of the available credit and the renewal
    premium, the remainder is payable, and the pool floors at 0 and never goes
    negative."

    Design: Difficulty/compensating_invariant/account_credit_conservation_invariant
    """
    setup_class_and_rule(
        code="CC_I", description="Invariant", keyword="invariant",
        eligible_lines=["GL"], base_rates_cents={"GL": 100},
        risk_factor=1.0,
    )
    account = setup_account(legal_name="Credit Co")
    policy = setup_policy(account, "invariant", ["GL"], exposure_units=3650)

    set_clock("2026-10-01T00:00:00Z")
    endorsement = create_effective_endorsement(account, policy, {
        "endorsement_type": "COVERAGE_ADJUST",
        "effective_at": "2026-10-01T00:00:00Z",
        "new_exposure_units": 1825,
    })
    assert endorsement["premium_delta_cents"] == -206862
    acct = get_account(account["id"])
    assert acct["account_credit_cents"] == 206862, (
        f"Negative delta must accrue credit: got {acct['account_credit_cents']}"
    )

    # A mid-term read after further clock movement: credit is NOT consumed.
    set_clock("2026-10-31T00:00:00Z")
    acct_mid = get_account(account["id"])
    assert acct_mid["account_credit_cents"] == 206862, (
        "Credit must not be consumed mid-term; only renewal bind consumes it: "
        f"got {acct_mid['account_credit_cents']}"
    )
