"""State registrations: grant fee stamping, lapse and renewal with late
penalties, the due-date carryover rule, duplicate handling, terminal lockdown,
and list filtering (PRD §3.9).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    apply_state_registration,
    assert_iso_instant_equal,
    assert_state_registration,
    create_certification,
    create_registered_product,
    get_state_registration,
    grant_state_registration,
    make_renewal_payload,
    make_state_decision_payload,
    make_state_registration_payload,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]
STATE_AGENCY = TEST_USERS["state_agency_headers"]


def test_renewal_fee_late_penalty_and_due_date_carryover(api):
    """PRD §3.9: "When the clock is at or before `renewal_due_at`, the
    registration is zero months overdue; otherwise the count of months overdue is
    the whole days between `renewal_due_at` and the clock, divided by thirty and
    rounded down, plus one."
    PRD §3.9: "Only after the fee is fixed does the anniversary move:
    `renewal_due_at` advances by exactly 365 days from its previous value — never
    from the payment date, so chronically late renewals do not reset the
    anniversary — while `last_renewal_at` is stamped from the clock and
    `renewal_count` increments by one."
    PRD §3.9: "plus a restricted-use surcharge of 10,000 cents when the product is
    `RESTRICTED_USE` at grant time"

    Design: Difficulty/combinatorial_formula/renewal_fee_late_penalty_and_due_date_carryover
    """
    ctx = create_registered_product(use_pattern="FOOD_USE",
                                    final_classification="RESTRICTED_USE")
    product_id = ctx["product"]["id"]
    create_certification("TX", "2030-01-01T00:00:00Z")
    sreg = apply_state_registration(product_id, "TX", REGISTRANT)

    set_clock("2026-12-15T00:00:00Z")
    granted = grant_state_registration(sreg["id"], agency_headers=STATE_AGENCY)
    # 25,000 TX base + 10,000 RUP surcharge; due exactly 365 days after grant.
    assert granted["annual_fee_cents"] == 35000
    assert_iso_instant_equal(granted["renewal_due_at"], "2027-12-15T00:00:00Z",
                             "renewal_due_at")

    # 2028-01-10 is 26 days overdue: one started 30-day month, inside the grace.
    set_clock("2028-01-10T00:00:00Z")
    assert get_state_registration(sreg["id"])["status"] == "GRANTED"

    # Fee: 35000 subtotal + round_half_up(35000 * 0.10 * 1) = 38500.
    renewed = validate_success(api_client.renew_state_registration(
        sreg["id"], make_renewal_payload(38500), REGISTRANT))
    assert_state_registration(renewed)
    assert renewed["status"] == "GRANTED"
    assert renewed["renewal_count"] == 1
    assert_iso_instant_equal(renewed["last_renewal_at"], "2028-01-10T00:00:00Z",
                             "last_renewal_at")
    # Old due 2027-12-15 + 365 days — NOT clock + 365 (which would be 2029-01-10).
    assert_iso_instant_equal(renewed["renewal_due_at"], "2028-12-14T00:00:00Z",
                             "renewal_due_at")


def test_lapsed_state_registration_renewed_with_late_fee_restores_granted(api):
    """PRD §3.9: "Renewal requires the registration in `GRANTED` or `LAPSED` (else
    `ERR_STATE_REG_NOT_DECIDABLE`) and the product in `REGISTERED` or
    `UNDER_REVIEW`"
    PRD §3.9: "A renewed `LAPSED` registration returns to `GRANTED`; a `GRANTED`
    one stays `GRANTED`."
    PRD §2.4: "Every state registration in `GRANTED` whose grace period has fully
    elapsed — the instant exactly thirty days after its `renewal_due_at` is
    strictly earlier than the new time — becomes `LAPSED`."

    Design: Corner/state_machines/lapsed_state_registration_renewed_with_late_fee_restores_granted
    """
    ctx = create_registered_product()
    sreg = apply_state_registration(ctx["product"]["id"], "TX", REGISTRANT)
    set_clock("2026-12-15T00:00:00Z")
    grant_state_registration(sreg["id"], agency_headers=STATE_AGENCY)

    # renewal_due_at 2027-12-15 + 30 days grace = 2028-01-14 < 2028-02-01.
    set_clock("2028-02-01T00:00:00Z")
    assert get_state_registration(sreg["id"])["status"] == "LAPSED"

    # 48 overdue days = 2 started months: 25000 + round_half_up(25000*0.10*2).
    renewed = validate_success(api_client.renew_state_registration(
        sreg["id"], make_renewal_payload(30000), REGISTRANT))
    assert renewed["status"] == "GRANTED"
    assert renewed["renewal_count"] == 1
    assert_iso_instant_equal(renewed["renewal_due_at"], "2028-12-14T00:00:00Z",
                             "renewal_due_at")


def test_renewal_overpayment_returns_incorrect_fee(api):
    """PRD §3.9: "The fee due is the subtotal plus the penalty, and the
    representative's `payment_cents` must equal it exactly, failing
    `ERR_INCORRECT_FEE_PAYMENT` (HTTP 402) on any difference."

    Design: Corner/validations/renewal_overpayment_returns_incorrect_fee
    """
    ctx = create_registered_product()
    sreg = apply_state_registration(ctx["product"]["id"], "TX", REGISTRANT)
    set_clock("2026-12-15T00:00:00Z")
    grant_state_registration(sreg["id"], agency_headers=STATE_AGENCY)

    # On-time renewal: months_overdue 0, fee due is exactly the 25000 subtotal.
    resp = api_client.renew_state_registration(
        sreg["id"], make_renewal_payload(25001), REGISTRANT)
    validate_error(resp, ApiErrorId.ERR_INCORRECT_FEE_PAYMENT)

    sreg = get_state_registration(sreg["id"])
    assert sreg["renewal_count"] == 0
    assert_iso_instant_equal(sreg["renewal_due_at"], "2027-12-15T00:00:00Z",
                             "renewal_due_at")


def test_state_reg_revoke_after_denial_returns_not_decidable(api):
    """PRD §3.9: "The agency may also revoke a registration in `GRANTED` or
    `LAPSED`, optionally recording a `reason`; revoking from any other status
    fails `ERR_STATE_REG_NOT_DECIDABLE`."
    PRD §3.9: "`DENIED` and `REVOKED` are terminal."

    Design: Corner/state_machines/state_reg_revoke_after_denial_returns_not_decidable
    """
    ctx = create_registered_product()
    sreg = apply_state_registration(ctx["product"]["id"], "IA", REGISTRANT)
    validate_success(api_client.decide_state_registration(
        sreg["id"], make_state_decision_payload("DENY"), STATE_AGENCY))

    resp = api_client.revoke_state_registration(sreg["id"], STATE_AGENCY, payload={})
    validate_error(resp, ApiErrorId.ERR_STATE_REG_NOT_DECIDABLE)
    assert get_state_registration(sreg["id"])["status"] == "DENIED"


def test_duplicate_state_registration_rejected_but_reapply_after_denial_allowed(api):
    """PRD §3.9: "at most one non-terminal registration — one in `SUBMITTED`,
    `GRANTED`, or `LAPSED` — may exist per product-and-state pair, with a
    collision failing `ERR_DUPLICATE_STATE_REGISTRATION` (HTTP 409)."
    PRD §3.9: "`DENIED` and `REVOKED` are terminal."

    Design: Corner/validations/duplicate_state_registration_rejected_but_reapply_after_denial_allowed
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    first = apply_state_registration(product_id, "IA", REGISTRANT)

    resp = api_client.create_state_registration(
        make_state_registration_payload(product_id, "IA"), REGISTRANT)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATE_REGISTRATION)

    validate_success(api_client.decide_state_registration(
        first["id"], make_state_decision_payload("DENY"), STATE_AGENCY))
    # DENIED is terminal, so the pair is free for a fresh application.
    reapplied = validate_success(api_client.create_state_registration(
        make_state_registration_payload(product_id, "IA"), REGISTRANT), 201)
    assert reapplied["status"] == "SUBMITTED"
