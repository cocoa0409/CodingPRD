"""Loan activation gates, guarantor acknowledgment, and disclosure compliance."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    acknowledge_guarantor,
    create_accepted_loan,
    deliver_disclosure,
    get_loan_disclosure,
    get_loan_guarantor,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SERVICER = TEST_USERS["servicer_agent_headers"]


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / loan_activation_requires_disclosure_ack
# ---------------------------------------------------------------------------

def test_mandate_activation_blocked_until_disclosure_acknowledged(api):
    """PRD Section 3.3: "For a mandate-state loan (`PENDING_DISCLOSURE`), the disclosure statement must be `ACKNOWLEDGED`, otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`."

    Design: Difficulty/cross_entity_state_dependency/loan_activation_requires_disclosure_ack
    """
    bundle = create_accepted_loan(
        principal_cents=1_050_000,
        legal_name="Cali Co",
        owner_name="Cal Lew",
        state_code="CA",
    )
    loan_id = bundle["loan"]["id"]
    assert bundle["loan"]["disclosure_required"] is True
    assert bundle["loan"]["status"] == "PENDING_DISCLOSURE"

    acknowledge_guarantor(loan_id)
    disclosure = deliver_disclosure(loan_id)
    set_clock("2026-09-03T00:00:00Z")  # 24h cooling elapsed

    # Guarantor ACTIVE but disclosure only DELIVERED: activation blocked.
    resp = api.activate_loan(loan_id, SERVICER)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED)

    from test_helpers import acknowledge_disclosure
    acknowledge_disclosure(bundle["merchant"]["id"], disclosure["id"])
    activated = validate_success(api.activate_loan(loan_id, SERVICER))
    assert activated["status"] == "ACTIVE"


def test_mandate_acknowledgment_enables_activation_after_cooling(api):
    """PRD Section 3.3: "When `cooling_required` is true, acknowledgment is only allowed at or after 24 hours past `delivered_at`; an earlier attempt is rejected with `ERR_DISCLOSURE_COOLING_NOT_ELAPSED`."
    PRD Section 3.3: "Activation stamps `activated_at` with the clock, sets `repayment_period_index` to 0, and moves the loan to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/loan_activation_requires_disclosure_ack
    """
    bundle = create_accepted_loan(
        principal_cents=1_050_000,
        legal_name="Cali Co",
        owner_name="Cal Lew",
        state_code="CA",
    )
    loan_id = bundle["loan"]["id"]
    acknowledge_guarantor(loan_id)
    disclosure = deliver_disclosure(loan_id)

    from test_helpers import acknowledge_disclosure, make_merchant_owner_headers
    # Acknowledge exactly at delivered_at + 24h: allowed.
    set_clock("2026-09-02T00:00:00Z")
    acked = validate_success(api.acknowledge_disclosure(
        disclosure["id"], make_merchant_owner_headers(bundle["merchant"]["id"])))
    assert acked["status"] == "ACKNOWLEDGED"

    activated = validate_success(api.activate_loan(loan_id, SERVICER))
    assert activated["status"] == "ACTIVE"
    assert activated["repayment_period_index"] == 0


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / disclosure_ack_vs_guarantor_active
# ---------------------------------------------------------------------------

def test_activation_reports_disclosure_gate_before_guarantor_gate(api):
    """PRD Section 2.7: "Fifth, regulatory disclosure gates on activation and acknowledgment. Sixth, uniqueness, overlap, and segregation-of-duties constraints. Seventh, cross-entity referential state (guarantor active before activation; batch finalized before sweeping)."
    PRD Section 3.3: "For a mandate-state loan (`PENDING_DISCLOSURE`), the disclosure statement must be `ACKNOWLEDGED`, otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`."

    Design: Difficulty/priority_pair_validation_conflict/disclosure_ack_vs_guarantor_active
    """
    bundle = create_accepted_loan(
        principal_cents=1_050_000,
        legal_name="Cali Co",
        owner_name="Cal Lew",
        state_code="CA",
    )
    loan_id = bundle["loan"]["id"]
    deliver_disclosure(loan_id)
    set_clock("2026-09-03T00:00:00Z")  # cooling elapsed, but not acknowledged

    guarantor = get_loan_guarantor(loan_id)
    assert guarantor["status"] == "LINKED"

    resp = api.activate_loan(loan_id, SERVICER)
    # Disclosure gate (earlier in validation order) wins over the guarantor gate.
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED)
    loan_after = validate_success(api.get_loan(loan_id, ADMIN))
    assert loan_after["status"] == "PENDING_DISCLOSURE"


def test_mandate_activation_blocked_by_guarantor_after_disclosure_ack(api):
    """PRD Section 3.3: "The guarantee gate is identical for both paths: the loan's guarantor must be `ACTIVE`, otherwise activation is rejected with `ERR_GUARANTOR_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/disclosure_ack_vs_guarantor_active
    """
    bundle = create_accepted_loan(
        principal_cents=1_050_000,
        legal_name="Cali Co",
        owner_name="Cal Lew",
        state_code="CA",
    )
    loan_id = bundle["loan"]["id"]
    disclosure = deliver_disclosure(loan_id)
    set_clock("2026-09-03T00:00:00Z")

    from test_helpers import acknowledge_disclosure
    acknowledge_disclosure(bundle["merchant"]["id"], disclosure["id"])

    # Disclosure ACKNOWLEDGED but guarantor still LINKED.
    assert get_loan_guarantor(loan_id)["status"] == "LINKED"
    resp = api.activate_loan(loan_id, SERVICER)
    validate_error(resp, ApiErrorId.ERR_GUARANTOR_NOT_ACTIVE)


# ---------------------------------------------------------------------------
# Queue B: state_machines — guarantor and disclosure transition rules
# ---------------------------------------------------------------------------

def test_guarantor_acknowledge_twice_rejected(api):
    """PRD Section 3.3: "The guarantee becomes enforceable when the `GuarantorPrincipal` acknowledges it: the caller's `X-User-ID` must equal the guarantor's `id`, and acknowledgment stamps `acknowledged_at` and moves the guarantor to `ACTIVE`."

    Design: Corner/state_machines/guarantor_acknowledge_twice_rejected
    """
    bundle = create_accepted_loan(principal_cents=500_000, holdback_pct=0.08,
                                  guarantee_cap_cents=1_000_000)
    guarantor = bundle["guarantor"]
    from test_helpers import make_guarantor_principal_headers
    acked = validate_success(api.acknowledge_guarantor(
        guarantor["id"], make_guarantor_principal_headers(guarantor["id"])))
    assert acked["status"] == "ACTIVE"

    resp = api.acknowledge_guarantor(
        guarantor["id"], make_guarantor_principal_headers(guarantor["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert validate_success(
        api.get_guarantor(guarantor["id"], ADMIN))["status"] == "ACTIVE"


def test_disclosure_acknowledge_before_deliver_rejected(api):
    """PRD Section 3.3: "A `ServicerAgent` delivers the statement, moving it from `GENERATED` to `DELIVERED` and stamping `delivered_at`. The `MerchantOwner` of the loan's merchant then acknowledges it — `X-User-ID` must equal the loan's `merchant_id` — moving it to `ACKNOWLEDGED` and stamping `acknowledged_at`."

    Design: Corner/state_machines/disclosure_acknowledge_before_deliver_rejected
    """
    bundle = create_accepted_loan(principal_cents=500_000, holdback_pct=0.08,
                                  guarantee_cap_cents=1_000_000)
    disclosure = bundle["disclosure"]
    assert disclosure["status"] == "GENERATED"

    from test_helpers import make_merchant_owner_headers
    resp = api.acknowledge_disclosure(
        disclosure["id"], make_merchant_owner_headers(bundle["merchant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert validate_success(
        api.get_disclosure(disclosure["id"], ADMIN))["status"] == "GENERATED"


# ---------------------------------------------------------------------------
# Queue B: endpoints — non-mandate disclosure gate both directions
# ---------------------------------------------------------------------------

def test_non_mandate_activation_blocked_when_guarantor_not_active(api):
    """PRD Section 3.3: "The guarantee gate is identical for both paths: the loan's guarantor must be `ACTIVE`, otherwise activation is rejected with `ERR_GUARANTOR_NOT_ACTIVE`."

    Design: Corner/errors/guarantor_not_active_error
    """
    bundle = create_accepted_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]
    assert bundle["loan"]["disclosure_required"] is False
    deliver_disclosure(loan_id)
    # Guarantor never acknowledged: still LINKED, disclosure already DELIVERED.
    assert get_loan_guarantor(loan_id)["status"] == "LINKED"

    resp = api.activate_loan(loan_id, SERVICER)
    validate_error(resp, ApiErrorId.ERR_GUARANTOR_NOT_ACTIVE)
    assert validate_success(api.get_loan(loan_id, ADMIN))["status"] == "PENDING_ACK"


def test_non_mandate_activation_before_deliver_rejected(api):
    """PRD Section 3.3: "For a non-mandate loan (`PENDING_ACK`), the disclosure statement must be at least `DELIVERED` — `DELIVERED` or `ACKNOWLEDGED` both pass — otherwise `ERR_DISCLOSURE_NOT_DELIVERED`."

    Design: Corner/endpoints/non_mandate_activation_before_deliver_rejected
    """
    bundle = create_accepted_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]
    assert bundle["loan"]["disclosure_required"] is False
    assert bundle["loan"]["status"] == "PENDING_ACK"

    acknowledge_guarantor(loan_id)
    # Disclosure still GENERATED (never delivered).
    resp = api.activate_loan(loan_id, SERVICER)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_DELIVERED)
    assert validate_success(api.get_loan(loan_id, ADMIN))["status"] == "PENDING_ACK"


def test_non_mandate_activation_without_ack_succeeds(api):
    """PRD Section 3.3: "In non-mandate states no cooling applies, and activation does not require acknowledgment at all — delivery suffices."
    PRD Section 3.3: "For a non-mandate loan (`PENDING_ACK`), the disclosure statement must be at least `DELIVERED` — `DELIVERED` or `ACKNOWLEDGED` both pass — otherwise `ERR_DISCLOSURE_NOT_DELIVERED`."

    Design: Corner/validations/non_mandate_activation_without_ack_succeeds
    """
    bundle = create_accepted_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]
    assert bundle["loan"]["disclosure_required"] is False

    acknowledge_guarantor(loan_id)
    deliver_disclosure(loan_id)
    activated = validate_success(api.activate_loan(loan_id, SERVICER))
    assert activated["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Queue B: calculations — fee tiers and disclosure APR variants
# ---------------------------------------------------------------------------

def test_fee_tier_mid_band_minimum_floor(api):
    """PRD Section 3.3: "The tiered `fee_rate` is 0.11 when `principal_cents` is at most 2500000 cents, 0.13 when it is at most 10000000 cents, and 0.15 above that. `fee_cents` is the principal multiplied by the fee rate, rounded half-up to whole cents. `total_repayment_cents` is principal plus fee. `per_period_minimum_cents` — the minimum due per 60-day repayment period — is `total_repayment_cents` divided by 18, floored to whole cents."

    Design: Corner/calculations/fee_tier_mid_band_minimum_floor
    """
    from test_helpers import (
        create_eligible_merchant_with_history,
        flat_history_entries,
    )
    # 3,000,000/mo history -> pre-approval 3,750,000, so 3,000,000 fits.
    entries = [dict(e, gross_cents=3_000_000) for e in flat_history_entries()]
    merchant = create_eligible_merchant_with_history(entries, legal_name="Flat Co")
    from test_helpers import accept_offer_payload, create_issued_offer, make_merchant_owner_headers
    offer = create_issued_offer(merchant["id"])
    merchant = validate_success(api.get_merchant(merchant["id"], ADMIN))
    accepted = validate_success(api.accept_offer(
        offer["id"],
        accept_offer_payload(
            merchant["version"],
            selected_principal_cents=3_000_000,
            guarantee_cap_cents=5_000_000,
        ),
        make_merchant_owner_headers(merchant["id"])))

    loan = validate_success(api.get_loan(accepted["accepted_loan_id"], ADMIN))
    assert loan["fee_rate"] == pytest.approx(0.13)
    assert loan["fee_cents"] == 390_000
    assert loan["total_repayment_cents"] == 3_390_000
    assert loan["per_period_minimum_cents"] == 188_333


def test_disclosure_apr_dual_variant_values(api):
    """PRD Section 3.3: "`apr_scheduled` is the loan's `fee_rate` multiplied by 365 over a scheduled term of 1080 days, at four decimal places rounded half-up."
    PRD Section 3.3: "`disclosed_apr_basis` is `PROJECTED` when the loan's `disclosure_required` is true (mandate states CA, NY, UT, VA) and `SCHEDULED` otherwise, and `estimated_term_days` is the projected term in mandate states and 1080 days otherwise."
    PRD Section 3.3: "The loan's `disclosure_required` flag is true when the merchant's `state_code` at acceptance is one of CA, NY, UT, or VA."

    Design: Corner/calculations/disclosure_apr_dual_variant_values
    """
    bundle = create_accepted_loan(
        principal_cents=1_050_000,
        legal_name="Cali Co",
        owner_name="Cal Lew",
        state_code="CA",
    )
    loan = bundle["loan"]
    assert loan["disclosure_required"] is True
    assert loan["status"] == "PENDING_DISCLOSURE"

    disclosure = bundle["disclosure"]
    assert disclosure["apr_scheduled"] == pytest.approx(0.0372), (
        "0.11 x 365/1080 at four decimal places"
    )
    assert disclosure["apr_projected"] == pytest.approx(0.0765), (
        "projected term from trailing-90d pace"
    )
    assert disclosure["disclosed_apr_basis"] == "PROJECTED"
    assert disclosure["estimated_term_days"] == 525


# ---------------------------------------------------------------------------
# Queue B: validations — mandate cooling boundary
# ---------------------------------------------------------------------------

def test_mandate_acknowledge_before_cooling_rejected(api):
    """PRD Section 3.3: "When `cooling_required` is true, acknowledgment is only allowed at or after 24 hours past `delivered_at`; an earlier attempt is rejected with `ERR_DISCLOSURE_COOLING_NOT_ELAPSED`."

    Design: Corner/validations/mandate_acknowledge_before_cooling_rejected
    """
    bundle = create_accepted_loan(
        principal_cents=500_000,
        legal_name="Cali Co",
        owner_name="Cal Lew",
        state_code="CA",
    )
    disclosure = deliver_disclosure(bundle["loan"]["id"])

    from test_helpers import make_merchant_owner_headers
    owner = make_merchant_owner_headers(bundle["merchant"]["id"])

    set_clock("2026-09-01T12:00:00Z")  # 12h after delivery at 2026-09-01T00:00:00Z
    resp = api.acknowledge_disclosure(disclosure["id"], owner)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_COOLING_NOT_ELAPSED)

    set_clock("2026-09-02T00:00:00Z")  # exactly delivered_at + 24h
    acked = validate_success(api.acknowledge_disclosure(disclosure["id"], owner))
    assert acked["status"] == "ACKNOWLEDGED"


# ---------------------------------------------------------------------------
# Queue B: state_machines — offer terminal-state lockdown
# ---------------------------------------------------------------------------

def test_offer_withdraw_from_accepted_rejected(api):
    """PRD Section 3.2: "An `Underwriter` may also withdraw an offer from any non-terminal pre-acceptance state — `DRAFT`, `OFFERED`, `EXPIRED`, or `REUNDERWRITING` — moving it to `WITHDRAWN`. `ACCEPTED` and `WITHDRAWN` are terminal."

    Design: Corner/state_machines/offer_withdraw_from_accepted_rejected
    """
    bundle = create_accepted_loan(principal_cents=500_000, holdback_pct=0.08,
                                  guarantee_cap_cents=1_000_000)
    offer = bundle["offer"]
    assert offer["status"] == "ACCEPTED"

    resp = api.withdraw_offer(offer["id"], TEST_USERS["underwriter_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert validate_success(
        api.get_offer(offer["id"], TEST_USERS["underwriter_headers"]))["status"] == "ACCEPTED"
