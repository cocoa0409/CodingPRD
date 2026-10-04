"""Validation-priority, quote-validation, RBAC, and audit-trail tests
(PRD §2.1, §2.7, §2.9, §3.1–§3.3)."""

from test_helpers import (
    ApiErrorId,
    create_appetite_rule_payload,
    create_business_account_payload,
    create_class_code_payload,
    create_quote_payload,
    get_quote,
    get_success_data,
    make_claims_adjuster_headers,
    make_policyholder_headers,
    make_platform_admin_headers,
    make_underwriter_headers,
    set_clock,
    setup_account,
    setup_class_and_rule,
    setup_policy,
    setup_quoted,
    setup_referred_quote,
    submit_claim,
    validate_error,
    validate_success,
)

ADMIN = make_platform_admin_headers("t06-admin")


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


# --- Validation priority pairs ----------------------------------------------

def test_role_error_precedes_fiscal_gate_on_cancel(api):
    """PRD §2.7: "Authentication (missing headers, `ERR_UNAUTHENTICATED`) is
    checked first, then role authorization (`ERR_FORBIDDEN_ROLE`), then
    path-id existence and cross-account resolution (`ERR_NOT_FOUND`), then
    whether the target resource is in a state that permits the operation at
    all (`ERR_INVALID_STATE` and the domain-specific state errors), then
    regulatory and compliance gates (`ERR_COMPLIANCE_VIOLATION` family:
    non-renewal statutory minimums, segregation of duties, claim loss
    windows), then temporal-window rules (`ERR_TEMPORAL_WINDOW_VIOLATION`
    family: expired quotes, endorsement windows, appetite-rule windows, renewal
    windows), then shape constraints (`ERR_BUSINESS_CONSTRAINT_VIOLATION`
    family: line eligibility, exposure floors, claim amount floors, evidence
    size, underwriting answer completeness), then referential integrity
    (`ERR_REFERENTIAL_INTEGRITY` family: policy ownership,
    certificate-to-endorsement linkage, channel matching), and finally fiscal
    gates (`ERR_FISCAL_GATE_VIOLATION` family: stale quote basis at bind, open
    claims at cancel or renew, off-appetite class at renew)."
    PRD §4: POST `/ins/policies/{id}/cancel` — "Cancel a policy" — is
    authorized for `Policyholder` only.

    Design: Difficulty/priority_pair_validation_conflict/cancel_with_open_claims_and_agent_role
    """
    _setup_cc_c()
    account = setup_account(legal_name="Priority Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = submit_claim(account, policy, claim_amount_cents=150000)
    assert claim["status"] == "SUBMITTED"  # an open claim exists

    resp = api.cancel_policy(
        policy["id"],
        {"X-User-ID": "agent-1", "X-User-Role": "Agent",
         "Content-Type": "application/json"},
    )
    err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert err["error_id"] == "ERR_FORBIDDEN_ROLE", (
        f"Role authorization precedes the fiscal gate, got {err['error_id']}"
    )


def test_temporal_error_precedes_constraint_error_on_evidence(api):
    """PRD §2.7: "then temporal-window rules (`ERR_TEMPORAL_WINDOW_VIOLATION`
    family: expired quotes, endorsement windows, appetite-rule windows, renewal
    windows), then shape constraints (`ERR_BUSINESS_CONSTRAINT_VIOLATION`
    family: line eligibility, exposure floors, claim amount floors, evidence
    size, underwriting answer completeness)".

    Design: Difficulty/priority_pair_validation_conflict/evidence_size_and_future_exif_conflict
    """
    _setup_cc_c()
    account = setup_account(legal_name="Evidence Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = submit_claim(account, policy, claim_amount_cents=150000)

    ph = make_policyholder_headers(account["id"])
    resp = api.attach_evidence(claim["id"], {
        "photo_ref": "ph://bad",
        "exif_taken_at": "2026-09-05T00:00:00Z",  # after intake (temporal)
        "file_size_bytes": 20971520,  # oversize (constraint)
    }, ph)
    err = validate_error(resp, ApiErrorId.ERR_EVIDENCE_FUTURE)
    assert err["error_id"] == "ERR_EVIDENCE_FUTURE", (
        f"Temporal rules precede shape constraints, got {err['error_id']}"
    )


# --- Quote / onboarding validations -----------------------------------------

def test_quote_with_backdated_effective_rejected(api):
    """PRD §3.3: "the `requested_effective_at` coverage start (which must not
    be earlier than the current clock instant)".

    PRD names no concrete error id for a backdated requested_effective_at
    (§2.7's temporal-window family enumerates expired quotes, endorsement
    windows, appetite-rule windows, and renewal windows — none of which is
    this case). The uniquely derivable guarantee is rejection; the only
    catalog id covering malformed/invalid request values is ERR_VALIDATION.

    Design: Corner/validations/quote_temporal_violation_backdated_effective
    """
    from test_helpers import validate_error_is_one_of

    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    ph = make_policyholder_headers(account["id"])
    resp = api.create_quote(create_quote_payload(
        business_account_id=account["id"],
        raw_description="handyman",
        selected_lines=["GL"],
        requested_effective_at="2026-08-01T00:00:00Z",
    ), ph)
    validate_error_is_one_of(resp, [ApiErrorId.ERR_VALIDATION])


def test_non_partner_account_with_channel_partner_id_rejected(api):
    """PRD §3.3: "When the account's channel is `PARTNER`, the payload must
    also carry a `channel_partner_id` matching the account's `partner_tenant`;
    a partner-channel quote missing it, or a non-partner quote supplying one,
    is rejected with `ERR_CHANNEL_MISMATCH`."

    Design: Corner/validations/non_partner_account_supplying_channel_partner_id_rejected
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")  # DIRECT channel
    ph = make_policyholder_headers(account["id"])
    resp = api.create_quote(create_quote_payload(
        business_account_id=account["id"],
        raw_description="handyman",
        selected_lines=["GL"],
        channel_partner_id="tenant-xyz",
    ), ph)
    validate_error(resp, ApiErrorId.ERR_CHANNEL_MISMATCH)


def test_partner_account_without_partner_tenant_rejected(api):
    """PRD §3.2: "Partner-channel accounts must declare the `partner_tenant`
    slug of the platform tenant they arrived through; for any other channel
    `partner_tenant` is null."
    PRD §3.3: "a partner-channel quote missing it, or a non-partner quote
    supplying one, is rejected with `ERR_CHANNEL_MISMATCH`."

    Design: Corner/entities/partner_channel_account_requires_partner_tenant

    PRD names ERR_CHANNEL_MISMATCH only for quote creation (§3.3); the error
    for account onboarding without partner_tenant is unnamed, so accept either
    the channel-mismatch reading or the generic malformed-body reading.
    """
    from test_helpers import validate_error_is_one_of

    resp = api.create_business_account(create_business_account_payload(
        legal_name="Embedded Co",
        contact_email="embedded@example.com",
        channel="PARTNER",
    ), {"X-User-ID": "partner-1", "X-User-Role": "PartnerPlatform",
        "Content-Type": "application/json"})
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_CHANNEL_MISMATCH, ApiErrorId.ERR_VALIDATION],
    )


def test_negative_exposure_rejected(api):
    """PRD §3.5: "A `COVERAGE_ADJUST` carries `new_exposure_units`, an absolute
    replacement exposure of at least 0; negative exposure anywhere — here or at
    quote time — is `ERR_EXPOSURE_NEGATIVE`."

    Design: Corner/errors/error_exposure_negative
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    ph = make_policyholder_headers(account["id"])
    resp = api.create_quote(create_quote_payload(
        business_account_id=account["id"],
        raw_description="handyman",
        selected_lines=["GL"],
        exposure_units=-1,
    ), ph)
    validate_error(resp, ApiErrorId.ERR_EXPOSURE_NEGATIVE)


def test_line_not_eligible_for_class_rejected(api):
    """PRD §3.5: "Ineligible or empty selections are `ERR_LINE_NOT_ELIGIBLE`,"
    PRD §3.3: "the `selected_lines` the applicant wants (a non-empty subset of
    the resolved class's `eligible_lines`)".

    Design: Corner/errors/error_line_not_eligible_for_class
    """
    _setup_cc_c()  # eligible GL only
    account = setup_account(legal_name="Corner Handy")
    ph = make_policyholder_headers(account["id"])
    resp = api.create_quote(create_quote_payload(
        business_account_id=account["id"],
        raw_description="handyman",
        selected_lines=["GL", "PL"],
    ), ph)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_ELIGIBLE)


def test_inverted_appetite_rule_window_rejected(api):
    """PRD §3.1: "A rule whose `effective_from` is not strictly before its
    `effective_to` is rejected with `ERR_APPETITE_WINDOW_INVALID`."

    Design: Corner/validations/appetite_rule_inverted_window_rejected
    """
    setup_class_and_rule(
        code="CC_C", description="Solo trades", keyword="handyman",
        eligible_lines=["GL"], base_rates_cents={"GL": 10000},
        risk_factor=0.5,
    )
    resp = api.create_appetite_rule(create_appetite_rule_payload(
        keyword="handyman",
        class_code="CC_C",
        effective_from="2027-01-01T00:00:00Z",
        effective_to="2026-01-01T00:00:00Z",
    ), ADMIN)
    validate_error(resp, ApiErrorId.ERR_APPETITE_WINDOW_INVALID)


def test_risk_factor_out_of_range_rejected(api):
    """PRD §3.1: "a `risk_factor` multiplier that must be at least 0.25 and at
    most 4.00".

    PRD names no concrete error id for an out-of-range risk_factor (§2.7's
    shape-constraint family lists line eligibility, exposure floors, claim
    amount floors, evidence size, and underwriting answer completeness — not
    class-code field ranges). The uniquely derivable guarantee is rejection;
    ERR_VALIDATION is the catalog id covering invalid request values.

    Design: Corner/entities/class_code_risk_factor_out_of_range_rejected
    """
    resp = api.create_class_code(create_class_code_payload(
        code="CC_BAD", description="Too risky",
        eligible_lines=["GL"], base_rates_cents={"GL": 10000},
        risk_factor=4.5,
    ), ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_unknown_field_rejected_as_malformed(api):
    """PRD §2.7: "A malformed request body — wrong types, unknown fields — is
    rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/errors/error_invalid_request_unknown_field
    """
    resp = api.create_business_account(
        {"legal_name": "X", "contact_email": "x@x.com", "channel": "DIRECT",
         "bogus_field": 1},
        {"X-User-ID": "agent-x", "X-User-Role": "Agent",
         "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_computed_quote_fields_rejected_as_unknown(api):
    """PRD §3.3: "Inside the same request, classification (§3.1) resolves the
    class — recorded on the quote as `class_code_id`, never client-supplied".
    PRD §2.7: "A malformed request body — wrong types, unknown fields — is
    rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/computed_quote_fields_ignore_client_supplied_values
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    ph = make_policyholder_headers(account["id"])
    payload = create_quote_payload(
        business_account_id=account["id"], raw_description="handyman",
        selected_lines=["GL"],
    )
    payload.update({
        "risk_score": 0,
        "annual_premium_cents": 1,
        "class_code_id": "spoof",
    })
    resp = api.create_quote(payload, ph)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_unknown_policy_returns_not_found(api):
    """PRD §2.5: "the system first resolves the outermost identifier, then each
    inner identifier within that context, and rejects with `ERR_NOT_FOUND`
    (HTTP 404) at the first identifier that does not resolve."

    Design: Corner/errors/error_not_found_for_unknown_policy
    """
    resp = api.get_policy(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_bind_blocked_when_quote_basis_stale(api):
    """PRD §3.4: "Because a bind must price against exactly what was quoted,
    binding requires the fingerprint to be unchanged since issuance; if new
    signals were applied or any answer drifted, the bind is rejected with
    `ERR_QUOTE_BASIS_STALE` (HTTP 409) and the applicant must requote."

    Design: Corner/errors/error_quote_basis_stale_blocks_bind
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    # A pre-quote signal keeps the quote's basis hash tied to a known signal
    # set; the second signal (arriving after issuance) changes the basis.
    from test_helpers import create_risk_signal_payload
    validate_success(api.create_risk_signal(create_risk_signal_payload(
        business_account_id=account["id"],
        signal_type="FRAUD_SCREEN", severity=15, detail="Flag",
    ), ADMIN), expected_status=201)
    quote = validate_success(api.create_quote(create_quote_payload(
        business_account_id=account["id"], raw_description="handyman",
        selected_lines=["GL"],
    ), make_policyholder_headers(account["id"])), expected_status=201)
    assert quote["status"] == "QUOTED"

    validate_success(api.create_risk_signal(create_risk_signal_payload(
        business_account_id=account["id"],
        signal_type="LOSS_HISTORY", severity=15, detail="Late signal",
    ), ADMIN), expected_status=201)

    ph = make_policyholder_headers(account["id"])
    resp = api.bind_quote(
        quote["id"], {"expected_quote_version": quote["version"]}, ph,
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_BASIS_STALE)
    after = get_quote(quote["id"])
    assert after["status"] == "QUOTED", (
        f"Rejected bind must not advance the quote, got {after['status']}"
    )


# --- RBAC -------------------------------------------------------------------

def test_adjuster_cannot_issue_nonrenewal_notice(api):
    """PRD §2.1: "A request whose role is declared but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST `/ins/policies/{id}/non-renewal-notices` — "Issue a statutory
    non-renewal notice" — is authorized for `ComplianceOfficer` only.

    Design: Corner/rbac/adjuster_cannot_issue_nonrenewal_notice
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    set_clock("2027-07-18T00:00:00Z")
    adj = make_claims_adjuster_headers("adj-2")
    resp = api.create_non_renewal_notice(
        policy["id"], {"reason_code": "RISK_ESCALATION"}, adj,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_policyholder_cannot_administer_appetite_rules(api):
    """PRD §2.1: "A request whose role is declared but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST `/ins/appetite-rules` — "Create an appetite keyword rule" —
    is authorized for `PlatformAdmin` only.

    Design: Corner/rbac/policyholder_cannot_administer_appetite_rules
    """
    setup_class_and_rule(
        code="CC_C", description="Solo trades", keyword="handyman",
        eligible_lines=["GL"], base_rates_cents={"GL": 10000},
        risk_factor=0.5,
    )
    account = setup_account(legal_name="Corner Handy")
    ph = make_policyholder_headers(account["id"])
    resp = api.create_appetite_rule(create_appetite_rule_payload(
        keyword="handyman", class_code="CC_C",
    ), ph)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_underwriter_cannot_bind_quote(api):
    """PRD §2.1: "A request whose role is declared but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.5: "Binding is the `Policyholder`'s act of converting their own
    `QUOTED` quote into a policy; the caller's `X-User-ID` must equal the
    quote's `business_account_id`."

    Design: Corner/rbac/underwriter_cannot_bind_quote
    """
    _setup_cc_a()
    account = setup_account(legal_name="Corner GC")
    quote, referral = setup_referred_quote(
        account, "contractor", ["GL"], [80], {"q1": "yes", "q2": "yes"},
    )
    uw = make_underwriter_headers("uw-1")
    validate_success(api.approve_referral(referral["id"], uw), expected_status=200)
    refreshed = get_quote(quote["id"])

    resp = api.bind_quote(
        quote["id"], {"expected_quote_version": refreshed["version"]}, uw,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


# --- Audit trail --------------------------------------------------------------

def test_audit_trail_records_cancel_with_actor_and_snapshots(api):
    """PRD §2.9: "Each event records the `actor_role` (the caller's
    `X-User-Role`), the `actor_id` (the caller's `X-User-ID`, opaque
    identifiers permitted), the `entity_type` and `entity_id` of the mutated
    resource, the `action` naming the transition or mutation performed, and
    `before_snapshot` and `after_snapshot` objects capturing the field values
    relevant to that action before and after the mutation."

    Design: Corner/cross_cutting_layers/audit_trail_records_mutation_with_actor_and_snapshots
    """
    from test_helpers import api_client, make_compliance_officer_headers

    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    ph = make_policyholder_headers(account["id"])
    validate_success(api.cancel_policy(policy["id"], ph), expected_status=200)

    co = make_compliance_officer_headers("co-audit")
    resp = api_client.list_audit_events(co, params={
        "entity_type": "Policy", "entity_id": policy["id"],
    })
    events = get_success_data(resp)
    assert isinstance(events, list) and events, (
        "Audit trail must contain events for the cancelled policy"
    )
    cancels = [
        e for e in events
        if e.get("after_snapshot", {}).get("status") == "CANCELLED"
    ]
    assert cancels, f"No audit event captures the cancel transition: {events}"
    entry = cancels[0]
    assert entry["actor_role"] == "Policyholder"
    assert entry["actor_id"] == account["id"]
    assert entry["before_snapshot"]["status"] == "ACTIVE"
    assert entry["after_snapshot"]["status"] == "CANCELLED"


def test_claims_adjuster_denied_bind_before_fiscal_gate(api):
    """PRD §2.7: "Authentication (missing headers, `ERR_UNAUTHENTICATED`) is
    checked first, then role authorization (`ERR_FORBIDDEN_ROLE`), then
    path-id existence and cross-account resolution (`ERR_NOT_FOUND`), then
    whether the target resource is in a state that permits the operation at
    all (`ERR_INVALID_STATE` and the domain-specific state errors), then
    regulatory and compliance gates (`ERR_COMPLIANCE_VIOLATION` family:
    non-renewal statutory minimums, segregation of duties, claim loss
    windows), then temporal-window rules (`ERR_TEMPORAL_WINDOW_VIOLATION`
    family: expired quotes, endorsement windows, appetite-rule windows, renewal
    windows), then shape constraints (`ERR_BUSINESS_CONSTRAINT_VIOLATION`
    family: line eligibility, exposure floors, claim amount floors, evidence
    size, underwriting answer completeness), then referential integrity
    (`ERR_REFERENTIAL_INTEGRITY` family: policy ownership,
    certificate-to-endorsement linkage, channel matching), and finally fiscal
    gates (`ERR_FISCAL_GATE_VIOLATION` family: stale quote basis at bind, open
    claims at cancel or renew, off-appetite class at renew)."
    PRD §3.5: "Binding is the `Policyholder`'s act of converting their own
    `QUOTED` quote into a policy".

    Design: Difficulty/priority_pair_validation_conflict/cancel_with_open_claims_and_agent_role
    """
    _setup_cc_c()
    account = setup_account(legal_name="Priority Co")
    quote = setup_quoted(account, "handyman", ["GL"], exposure_units=10)
    adj = make_claims_adjuster_headers("adj-9")
    resp = api.bind_quote(
        quote["id"], {"expected_quote_version": quote["version"]}, adj,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_future_exif_only_rejected_by_temporal_rule(api):
    """PRD §2.7: "then temporal-window rules (`ERR_TEMPORAL_WINDOW_VIOLATION`
    family: expired quotes, endorsement windows, appetite-rule windows, renewal
    windows), then shape constraints (`ERR_BUSINESS_CONSTRAINT_VIOLATION`
    family: line eligibility, exposure floors, claim amount floors, evidence
    size, underwriting answer completeness)".
    PRD §3.7: "an `exif_taken_at` capture instant that must not be later than
    the claim's intake instant (a future capture is `ERR_EVIDENCE_FUTURE`)".

    Design: Difficulty/priority_pair_validation_conflict/evidence_size_and_future_exif_conflict
    """
    _setup_cc_c()
    account = setup_account(legal_name="Evidence Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = submit_claim(account, policy, claim_amount_cents=150000)

    ph = make_policyholder_headers(account["id"])
    # Valid size, future exif: the temporal rule alone rejects.
    resp = api.attach_evidence(claim["id"], {
        "photo_ref": "ph://future-only",
        "exif_taken_at": "2026-09-05T00:00:00Z",
        "file_size_bytes": 2048,
    }, ph)
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_FUTURE)


# --- Account onboarding defaults --------------------------------------------

def test_new_account_starts_with_zero_credit_and_claims_free(api):
    """PRD §3.2: "Two fiscal counters live on the account and evolve over its
    lifetime: `account_credit_cents`, a credit pool fed by mid-term downgrades
    and cancellations that floors at 0 (§3.5), and `open_claim_count`, the
    number of the account's claims currently in `SUBMITTED`, `IN_REVIEW`, or
    `APPROVED`. A derived `claims_free_flag` is true only while
    `open_claim_count` is zero and no claim of the account has ever reached
    `PAID`".

    Design: Corner/entities/business_account_creation_defaults_applied
    """
    account = setup_account(legal_name="Corner Bakery LLC")
    assert account["account_credit_cents"] == 0, (
        f"New account must start with zero credit, got "
        f"{account['account_credit_cents']}"
    )
    assert account["open_claim_count"] == 0, (
        f"New account must start with zero open claims, got "
        f"{account['open_claim_count']}"
    )
    assert account["claims_free_flag"] is True, (
        "New account must be claims-free"
    )
    assert account["version"] == 1, (
        f"Newly created resource must carry version 1, got {account['version']}"
    )
