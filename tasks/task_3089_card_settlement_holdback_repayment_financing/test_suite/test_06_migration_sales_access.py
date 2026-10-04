"""Migration risk monitoring, bank funding/loan sales, access control, and
guarantor reachability."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_offer_payload,
    assert_bank_exposure_invariant,
    create_accepted_loan,
    create_active_bank,
    create_active_loan,
    create_batch_payload,
    create_committed_sale,
    create_eligible_merchant,
    create_eligible_merchant_with_history,
    create_merchant,
    create_issued_offer,
    evaluate_period_at,
    get_loan,
    make_bank_officer_headers,
    make_merchant_owner_headers,
    migration_risk_history_entries,
    quote_sale_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
SERVICER = TEST_USERS["servicer_agent_headers"]
OFFICER_A = make_bank_officer_headers("officer_a")
OFFICER_B = make_bank_officer_headers("officer_b")


def _migrator_merchant():
    return create_eligible_merchant_with_history(
        migration_risk_history_entries(),
        legal_name="Migrator Inc",
        owner_name="Mig Rator",
    )


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / migration_risk_variant_divergence
# ---------------------------------------------------------------------------

def test_chargeback_spike_triggers_despite_subthreshold_drop(api):
    """PRD Section 3.7: "The evaluation computes a `drop_ratio`: one minus the ratio of `trailing_30d_net_cents` to `prior_30d_net_cents`, at four decimal places rounded half-up, and 0 when the prior window's net is 0. Two variant verdicts are computed. The VOLUME_ONLY diagnostic variant — reported on the signal as `volume_only_would_trigger` — is true when the drop ratio is at least 0.60 (inclusive) and the trailing 30-day net is strictly above 0. The active VOLUME_AND_CHARGEBACK variant — reported as `triggered` — is true when the volume-only condition holds or the `trailing_30d_chargeback_ratio` is strictly above 0.03, so a chargeback spike alone triggers even when the volume drop is below threshold."

    Design: Difficulty/dual_variant_calc/migration_risk_variant_divergence
    """
    merchant = _migrator_merchant()
    signal = validate_success(api.evaluate_migration(merchant["id"], SERVICER))
    assert signal["drop_ratio"] == pytest.approx(0.55)
    assert signal["volume_only_would_trigger"] is False
    assert signal["triggered"] is True
    assert signal["status"] == "DETECTED"


def test_triggered_evaluation_creates_detected_signal_row(api):
    """PRD Section 3.7: "A `MigrationSignal` row is created in `DETECTED` status — with `merchant_id` attached and `evaluated_at` stamped — only when `triggered` is true; when it is false, no row is created, the response reports `triggered` as false inline, and listing the merchant's migration signals returns an empty array for that evaluation."

    Design: Difficulty/dual_variant_calc/migration_risk_variant_divergence
    """
    merchant = _migrator_merchant()
    signal = validate_success(api.evaluate_migration(merchant["id"], SERVICER))
    assert signal["merchant_id"] == merchant["id"]

    listed, _meta = validate_paginated(
        api.list_migration_signals(merchant["id"], SERVICER))
    assert len(listed) == 1
    assert listed[0]["id"] == signal["id"]
    assert listed[0]["status"] == "DETECTED"


# ---------------------------------------------------------------------------
# Queue B: state_machines — migration signal cascade
# ---------------------------------------------------------------------------

def test_migration_confirm_suspends_merchant_side_effect(api):
    """PRD Section 3.7: "Confirmation moves it to `CONFIRMED` and cascades the merchant to `SUSPENDED`, blocking new offer creation while leaving existing loans untouched."

    Design: Corner/state_machines/migration_confirm_suspends_merchant_side_effect
    """
    merchant = _migrator_merchant()
    signal = validate_success(api.evaluate_migration(merchant["id"], SERVICER))

    confirmed = validate_success(api.confirm_migration_signal(signal["id"], SERVICER))
    assert confirmed["status"] == "CONFIRMED"

    merchant_after = validate_success(api.get_merchant(merchant["id"], ADMIN))
    assert merchant_after["status"] == "SUSPENDED"


# ---------------------------------------------------------------------------
# Queue B: validations — migration signal exclusivity
# ---------------------------------------------------------------------------

def test_migration_evaluate_open_signal_rejected(api):
    """PRD Section 3.7: "A `ServicerAgent` requests an evaluation for a merchant; the merchant must be `ELIGIBLE`, otherwise `ERR_MERCHANT_NOT_ELIGIBLE`, and evaluation is refused with `ERR_MIGRATION_SIGNAL_OPEN` while any signal for the merchant is in `DETECTED` or `CONFIRMED` status."

    Design: Corner/validations/migration_evaluate_open_signal_rejected
    """
    merchant = _migrator_merchant()
    validate_success(api.evaluate_migration(merchant["id"], SERVICER))

    resp = api.evaluate_migration(merchant["id"], SERVICER)
    validate_error(resp, ApiErrorId.ERR_MIGRATION_SIGNAL_OPEN)


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / sale_settle_requires_loan_active
# ---------------------------------------------------------------------------

def test_committed_sale_cannot_settle_while_loan_delinquent(api):
    """PRD Section 3.8: "Settlement additionally requires the loan to be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE`) and the bank to be `ACTIVE` (`ERR_BANK_INACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/sale_settle_requires_loan_active
    """
    bundle = create_active_loan(principal_cents=1_050_000)
    bank = create_active_bank()
    sale = create_committed_sale(bundle, bank)

    # Drive the loan DELINQUENT with two missed periods.
    evaluate_period_at(bundle["loan"]["id"], "2026-10-31T00:00:00Z")
    evaluate_period_at(bundle["loan"]["id"], "2026-12-30T00:00:00Z")
    assert get_loan(bundle["loan"]["id"])["status"] == "DELINQUENT"

    resp = api.settle_sale(sale["id"], OFFICER_B)
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_ACTIVE)


def test_sale_settles_after_loan_cures_back_to_active(api):
    """PRD Section 3.5: "Curing works in reverse: when a `DELINQUENT` loan evaluates a period as MET and `cumulative_shortfall_cents` is 0, the loan returns to `ACTIVE` and `consecutive_missed_periods` resets — but the merchant stays `SUSPENDED` until a `PlatformAdmin` explicitly reinstates it."
    PRD Section 3.8: "Settlement additionally requires the loan to be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE`) and the bank to be `ACTIVE` (`ERR_BANK_INACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/sale_settle_requires_loan_active
    """
    bundle = create_active_loan(principal_cents=1_050_000)
    bank = create_active_bank()
    sale = create_committed_sale(bundle, bank)

    evaluate_period_at(bundle["loan"]["id"], "2026-10-31T00:00:00Z")
    evaluate_period_at(bundle["loan"]["id"], "2026-12-30T00:00:00Z")

    from test_helpers import initiate_and_settle_catch_up
    initiate_and_settle_catch_up(bundle, 194_250)
    cured = evaluate_period_at(bundle["loan"]["id"], "2027-02-28T00:00:00Z")
    assert cured["status"] == "ACTIVE"

    settled = validate_success(api.settle_sale(sale["id"], OFFICER_B))
    assert settled["status"] == "SETTLED"


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / sale_commit_fail_exposure_conservation
# ---------------------------------------------------------------------------

def test_commit_adds_purchase_price_to_bank_exposure(api):
    """PRD Section 3.8: "Committing the quote — permitted only while the bank is `ACTIVE`, else `ERR_BANK_INACTIVE` — moves the sale to `COMMITTED`, records the committing operator's `X-User-ID` as `committed_by_user_id`, and adds `purchase_price_cents` to the bank's `committed_exposure_cents`."

    Design: Difficulty/compensating_invariant/sale_commit_fail_exposure_conservation
    """
    bundle = create_active_loan(principal_cents=1_050_000)
    bank = create_active_bank()

    sale = create_committed_sale(bundle, bank)
    assert sale["purchase_price_cents"] == 1_118_880, (
        "round half-up of 1,165,500 x 0.96"
    )
    assert sale["committed_by_user_id"] == "officer_a"

    bank_after = validate_success(api.get_bank(bank["id"], ADMIN))
    assert bank_after["committed_exposure_cents"] == 1_118_880
    assert_bank_exposure_invariant(bank_after)


def test_fail_compensates_bank_exposure_to_zero(api):
    """PRD Section 3.8: "A committed sale that cannot close is failed, moving to `FAILED` and compensating the bank's `committed_exposure_cents` by subtracting `purchase_price_cents`."

    Design: Difficulty/compensating_invariant/sale_commit_fail_exposure_conservation
    """
    bundle = create_active_loan(principal_cents=1_050_000)
    bank = create_active_bank()
    sale = create_committed_sale(bundle, bank)

    failed = validate_success(api.fail_sale(sale["id"], OFFICER_A))
    assert failed["status"] == "FAILED"

    bank_after = validate_success(api.get_bank(bank["id"], ADMIN))
    assert bank_after["committed_exposure_cents"] == 0, (
        "compensating fail restores the conserved exposure exactly"
    )


# ---------------------------------------------------------------------------
# Queue B: calculations — sale waterfall
# ---------------------------------------------------------------------------

def test_sale_waterfall_reserve_remittance_split(api):
    """PRD Section 3.8: "Settlement applies a two-bucket waterfall over the purchase price, reserve first: `reserve_withheld_cents` is the purchase price multiplied by 0.05, rounded half-up, and `bank_remittance_cents` is the remainder — purchase price minus reserve — so reserve and remittance always sum exactly to the purchase price. Settlement moves the sale to `SETTLED`, records the settling operator as `settled_by_user_id`, releases the bank's committed exposure by subtracting `purchase_price_cents` from `committed_exposure_cents`, and leaves the loan's `servicing_retained` flag true — the platform continues to service the loan even after a settled sale."

    Design: Corner/calculations/sale_waterfall_reserve_remittance_split
    """
    bundle = create_active_loan(principal_cents=1_050_000)
    bank = create_active_bank()
    sale = create_committed_sale(bundle, bank)

    settled = validate_success(api.settle_sale(sale["id"], OFFICER_B))
    assert settled["status"] == "SETTLED"
    assert settled["purchase_price_cents"] == 1_118_880
    assert settled["reserve_withheld_cents"] == 55_944
    assert settled["bank_remittance_cents"] == 1_062_936
    assert (settled["reserve_withheld_cents"] + settled["bank_remittance_cents"]
            == settled["purchase_price_cents"])

    loan = get_loan(bundle["loan"]["id"])
    assert loan["servicing_retained"] is True


# ---------------------------------------------------------------------------
# Queue B: validations / errors — bank state and segregation of duties
# ---------------------------------------------------------------------------

def test_sale_quote_bank_inactive_rejected(api):
    """PRD Section 3.8: "Suspending a bank moves it to `SUSPENDED`, after which any new sale quote, commit, settle, or requote against it is rejected with `ERR_BANK_INACTIVE`."

    Design: Corner/validations/sale_quote_bank_inactive_rejected
    """
    bundle = create_active_loan(principal_cents=500_000)
    bank = create_active_bank()
    validate_success(api.suspend_bank(bank["id"], ADMIN))

    resp = api.quote_sale(bundle["loan"]["id"], quote_sale_payload(bank["id"]), OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_BANK_INACTIVE)


def test_sale_settle_same_user_rejected(api):
    """PRD Section 3.8: "Settlement enforces segregation of duties: the settling operator's `X-User-ID` must differ from `committed_by_user_id`, otherwise `ERR_SOD_SAME_USER`."

    Design: Corner/validations/sale_settle_same_user_rejected
    """
    bundle = create_active_loan(principal_cents=1_050_000)
    bank = create_active_bank()
    sale = create_committed_sale(bundle, bank)

    resp = api.settle_sale(sale["id"], OFFICER_A)  # same operator as commit
    validate_error(resp, ApiErrorId.ERR_SOD_SAME_USER)
    assert validate_success(api.get_sale(sale["id"], OFFICER_A))["status"] == "COMMITTED"


# ---------------------------------------------------------------------------
# Queue B: rbac — role denials and identity checks
# ---------------------------------------------------------------------------

def test_merchant_owner_cannot_finalize_batch(api):
    """PRD Section 2.1: "`MerchantOwner` — the borrowing merchant: accepts its own offers, acknowledges its own disclosures, and initiates catch-up payments on its own loans."
    PRD Section 2.1: "If the caller's role is not among the roles authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/merchant_owner_cannot_finalize_batch
    """
    merchant = create_merchant(legal_name="Role Co", owner_name="Ro Le")
    batch = validate_success(api.create_batch(
        merchant["id"],
        create_batch_payload(processing_date="2026-09-01", gross_cents=1000),
        ADMIN), expected_status=201)

    resp = api.finalize_batch(batch["id"], make_merchant_owner_headers(merchant["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert validate_success(api.get_batch(batch["id"], ADMIN))["status"] == "OPEN"


def test_auditor_cannot_generate_offer(api):
    """PRD Section 2.1: "`Auditor` — read-only oversight; every role, including `Auditor`, may call any GET endpoint."
    PRD Section 2.1: "If the caller's role is not among the roles authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/auditor_cannot_generate_offer
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    resp = api.create_offer(merchant["id"], TEST_USERS["auditor_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_bank_officer_cannot_activate_loan(api):
    """PRD Section 2.1: "`BankOfficer` — funding partner bank officer: quotes, commits, settles, fails, and requotes loan sales."
    PRD Section 2.1: "If the caller's role is not among the roles authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/bank_officer_cannot_activate_loan
    """
    bundle = create_accepted_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]

    resp = api.activate_loan(loan_id, OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert validate_success(api.get_loan(loan_id, ADMIN))["status"] == "PENDING_ACK"


def test_guarantor_acknowledge_wrong_identity_forbidden(api):
    """PRD Section 2.1: "When `X-User-Role` is `GuarantorPrincipal`, `X-User-ID` is the `id` of the acting `Guarantor`; acknowledgment of a guarantee requires `X-User-ID` to equal that guarantor's `id`."

    Design: Corner/rbac/guarantor_acknowledge_wrong_identity_forbidden
    """
    bundle = create_accepted_loan(principal_cents=500_000)
    guarantor = bundle["guarantor"]
    assert guarantor["status"] == "LINKED"

    from test_helpers import make_guarantor_principal_headers
    resp = api.acknowledge_guarantor(
        guarantor["id"], make_guarantor_principal_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert validate_success(
        api.get_guarantor(guarantor["id"], ADMIN))["status"] == "LINKED"


# ---------------------------------------------------------------------------
# Queue B: errors / validations — auth and validation priority
# ---------------------------------------------------------------------------

def test_missing_auth_headers_rejected(api):
    """PRD Section 2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the caller's role. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/errors/missing_auth_headers_rejected
    """
    payload = {
        "legal_name": "No Auth Co",
        "state_code": "TX",
        "owner_name": "No Auth",
        "processing_started_at": "2023-01-01T00:00:00Z",
    }
    resp = api.create_merchant(payload, {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                   expected_status=400)


def test_offer_create_forbidden_role_beats_not_found(api):
    """PRD Section 2.7: "First, authentication: the presence and shape of the user-context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_FORBIDDEN_FOR_ROLE`). Second, existence: path-referenced resources are resolved left to right — merchant, then offer, loan, batch, sale, signal, disclosure, guarantor, action, bank, sweep, payment — and the first missing one yields `ERR_NOT_FOUND`."

    Design: Corner/validations/offer_create_forbidden_role_beats_not_found
    """
    merchant = create_merchant(legal_name="Role Co", owner_name="Ro Le")
    # Offer generation is Underwriter-only; MerchantOwner is denied even
    # though the path's merchant id does not exist.
    resp = api.create_offer(
        NON_EXISTENT_UUID, make_merchant_owner_headers(merchant["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)


# ---------------------------------------------------------------------------
# Queue B: entities — guarantor reverse reachability
# ---------------------------------------------------------------------------

def test_guarantor_reverse_reachability_via_loan(api):
    """PRD Section 3.2: "Three records are created in the same operation: a `Loan` (its initial status is `PENDING_DISCLOSURE` when the merchant's `state_code` at this moment is CA, NY, UT, or VA, otherwise `PENDING_ACK`), a `Guarantor` in `LINKED` status, and a `DisclosureStatement` in `GENERATED` status carrying both APR variants."
    PRD Section 4: "GET `/lending/loans/{id}/guarantors` — List a loan's guarantors (0 or 1)."

    Design: Corner/entities/guarantor_reverse_reachability_via_loan
    """
    bundle = create_accepted_loan(
        principal_cents=500_000, holdback_pct=0.08, guarantee_cap_cents=1_000_000)

    guarantors = validate_success(
        api.list_guarantors(bundle["loan"]["id"], ADMIN))
    assert isinstance(guarantors, list) and len(guarantors) == 1
    assert guarantors[0]["loan_id"] == bundle["loan"]["id"]
    assert guarantors[0]["status"] == "LINKED"
