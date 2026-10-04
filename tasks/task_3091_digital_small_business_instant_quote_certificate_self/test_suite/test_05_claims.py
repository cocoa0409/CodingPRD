"""Claims tests: triage tiers, boundaries, evidence, and state lockdown
(PRD §3.7)."""

from test_helpers import (
    ApiErrorId,
    attach_evidence,
    assert_claim_evidence,
    make_claims_adjuster_headers,
    make_finance_officer_headers,
    make_policyholder_headers,
    make_platform_admin_headers,
    setup_account,
    setup_class_and_rule,
    setup_paid_claim,
    setup_policy,
    setup_quoted,
    submit_claim,
    validate_error,
    validate_success,
)

ADMIN = make_platform_admin_headers("t05-admin")


def _setup_cc_c():
    return setup_class_and_rule(
        code="CC_C", description="Solo trades", keyword="handyman",
        eligible_lines=["GL"], base_rates_cents={"GL": 10000},
        risk_factor=0.5,
    )


def _get_claim(api, claim_id):
    return validate_success(api.get_claim(claim_id, ADMIN))


def test_claim_at_fast_track_cap_tiers_fast_track(api):
    """PRD §3.7: "The boundaries are exact: an amount of exactly 100000 cents
    with one evidence item is `FAST_TRACK`".
    PRD §3.7: "a `STANDARD` claim promoted to `FAST_TRACK` by a late evidence
    attach is not auto-approved; automatic approval exists only at intake."

    Design: Difficulty/boundary_precision_check/fast_track_cap_inclusive_boundary
    """
    _setup_cc_c()
    account = setup_account(legal_name="Cap Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = submit_claim(account, policy, claim_amount_cents=100000)
    assert claim["status"] == "SUBMITTED"

    attach_evidence(account, claim)
    updated = _get_claim(api, claim["id"])
    assert updated["triage_tier"] == "FAST_TRACK", (
        f"Amount exactly 100000 with one evidence must be FAST_TRACK, got "
        f"{updated['triage_tier']}"
    )
    assert updated["status"] == "SUBMITTED", (
        "Automatic approval exists only at intake; the late evidence attach "
        f"must not auto-approve, got {updated['status']}"
    )


def test_claim_one_cent_over_cap_tiers_standard(api):
    """PRD §3.7: "The tier is `FAST_TRACK` when the amount is at most 100000
    cents and at least one photo evidence item is attached; it is `COMPLEX`
    when the amount exceeds 500000 cents or no evidence has been attached;
    otherwise it is `STANDARD`."

    Design: Difficulty/boundary_precision_check/fast_track_cap_inclusive_boundary
    """
    _setup_cc_c()
    account = setup_account(legal_name="Over Co")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = submit_claim(account, policy, claim_amount_cents=100001)
    assert claim["status"] == "SUBMITTED"

    attach_evidence(account, claim)
    updated = _get_claim(api, claim["id"])
    assert updated["triage_tier"] == "STANDARD", (
        f"Amount 100001 (one cent over the cap) with evidence must be "
        f"STANDARD, got {updated['triage_tier']}"
    )
    assert updated["status"] == "SUBMITTED", (
        f"STANDARD claim must await review, got {updated['status']}"
    )


def test_paid_claim_rejects_further_triage(api):
    """PRD §3.7: "Human handling begins when a `ClaimsAdjuster` pulls a
    `SUBMITTED` claim into review, moving it to `IN_REVIEW` and recording their
    own id as `adjuster_owner`."
    PRD §2.7: "then whether the target resource is in a state that permits the
    operation at all (`ERR_INVALID_STATE` and the domain-specific state
    errors)".

    Design: Corner/state_machines/claim_terminal_paid_lockdown_triage_rejected
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = setup_paid_claim(
        account, policy, adjuster_id="adj-1", finance_id="fin-1",
    )
    assert claim["status"] == "PAID"

    adj = make_claims_adjuster_headers("adj-1")
    resp = api.triage_claim(claim["id"], adj)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = _get_claim(api, claim["id"])
    assert after["status"] == "PAID", (
        f"Terminal claim must remain PAID, got {after['status']}"
    )


def test_in_review_claim_drops_claims_free_discount_on_new_quote(api):
    """PRD §3.2: "A derived `claims_free_flag` is true only while
    `open_claim_count` is zero and no claim of the account has ever reached
    `PAID`; once any claim is paid, the flag is false permanently."
    PRD §3.4: "The result is further reduced by the claims-free discount of 5
    percent when the account's `claims_free_flag` is true."

    An IN_REVIEW claim makes the account's open_claim_count 1, so the flag is
    false even though nothing has been PAID.

    Design: Corner/calculations/claims_free_discount_applies_at_threshold_boundary
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = submit_claim(account, policy, claim_amount_cents=150000)
    adj = make_claims_adjuster_headers("adj-1")
    validate_success(api.triage_claim(claim["id"], adj), expected_status=200)
    # Claim is IN_REVIEW: open_claim_count is 1, so claims_free_flag is false
    # (PRD §3.2 requires open_claim_count == 0 for the flag to hold).
    q2 = setup_quoted(account, "handyman", ["GL"], exposure_units=10)
    # CC_C GL at 10 units: 10000 * 10 * 1.00 * 0.5 = 50000, no 5% discount.
    assert q2["annual_premium_cents"] == 50000, (
        "claims_free_flag must be false while a claim is open (IN_REVIEW), so "
        f"no 5% discount applies: expected 50000, got {q2['annual_premium_cents']}"
    )


def test_finance_cannot_triage_claims(api):
    """PRD §2.1: "A request whose role is declared but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST `/ins/claims/{id}/triage` — "Adjuster pulls a claim into
    review" — is authorized for `ClaimsAdjuster` only.

    Design: Corner/rbac/finance_cannot_triage_claims
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = submit_claim(account, policy, claim_amount_cents=150000)
    fin = make_finance_officer_headers("fin-9")
    resp = api.triage_claim(claim["id"], fin)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_claim_evidence_is_append_only_without_version(api):
    """PRD §2.5: "Two resources are deliberately lighter: `ClaimEvidence` and
    `AuditEvent` carry only `id` and `created_at`; both `updated_at` and
    `version` are absent from them, because evidence items are immutable once
    attached and audit events are append-only."
    PRD §3.7: "Each attach recomputes the claim's `evidence_count`".

    Design: Corner/entities/claim_evidence_has_no_version_field_immutable
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = submit_claim(account, policy, claim_amount_cents=150000)
    evidence = attach_evidence(account, claim)
    assert_claim_evidence(evidence)

    updated = _get_claim(api, claim["id"])
    assert updated["evidence_count"] == 1, (
        f"evidence_count must recompute on attach, got {updated['evidence_count']}"
    )


def test_evidence_with_future_exif_rejected(api):
    """PRD §3.7: "an `exif_taken_at` capture instant that must not be later
    than the claim's intake instant (a future capture is
    `ERR_EVIDENCE_FUTURE`)".

    Design: Corner/validations/evidence_future_exif_rejected
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = submit_claim(account, policy, claim_amount_cents=150000)
    ph = make_policyholder_headers(account["id"])
    resp = api.attach_evidence(claim["id"], {
        "photo_ref": "ph://ev-future",
        "exif_taken_at": "2026-09-02T00:00:00Z",
        "file_size_bytes": 2048,
    }, ph)
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_FUTURE)


def test_evidence_below_size_floor_rejected(api):
    """PRD §3.7: "a `file_size_bytes` that must be at least 1024 bytes and at
    most 10 megabytes — 10485760 bytes (outside the range is
    `ERR_EVIDENCE_SIZE`)".

    Design: Corner/errors/error_evidence_size_bounds
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    claim = submit_claim(account, policy, claim_amount_cents=150000)
    ph = make_policyholder_headers(account["id"])
    resp = api.attach_evidence(claim["id"], {
        "photo_ref": "ph://tiny",
        "exif_taken_at": "2026-09-01T00:00:00Z",
        "file_size_bytes": 1023,
    }, ph)
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_SIZE)


def test_claim_below_amount_floor_rejected(api):
    """PRD §3.7: "a `claim_amount_cents` of at least 100 (below the floor is
    `ERR_CLAIM_AMOUNT_FLOOR`)".

    Design: Corner/errors/error_claim_amount_floor
    """
    _setup_cc_c()
    account = setup_account(legal_name="Corner Handy")
    policy = setup_policy(account, "handyman", ["GL"], exposure_units=10)
    ph = make_policyholder_headers(account["id"])
    from test_helpers import create_claim_payload
    resp = api.create_claim(create_claim_payload(
        policy_id=policy["id"], claim_amount_cents=99,
    ), ph)
    validate_error(resp, ApiErrorId.ERR_CLAIM_AMOUNT_FLOOR)
