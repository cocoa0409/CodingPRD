"""Offer underwriting tests: pre-approval variants, eligibility gates,
issuance overlap, expiry, renewal, and acceptance constraint errors."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    accept_offer_payload,
    create_eligible_merchant,
    create_eligible_merchant_with_history,
    create_merchant,
    create_merchant_payload,
    create_offer_for,
    create_issued_offer,
    flat_history_entries,
    get_success_data,
    make_merchant_owner_headers,
    migration_risk_history_entries,
    seasonal_history_entries,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN_KEY = "platform_admin_headers"
UW_KEY = "underwriter_headers"


def _iso_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp to an aware instant.

    PRD pins the *instant* (`expires_at` exactly 30 days after `issued_at`),
    not the string rendering, so comparisons go through parsed datetimes.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@pytest.fixture
def admin(platform_admin_headers):
    return platform_admin_headers


@pytest.fixture
def underwriter(underwriter_headers):
    return underwriter_headers


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / offer_preapproval_seasonal_haircut
# ---------------------------------------------------------------------------

def test_seasonal_history_selects_conservative_variant(api, admin, underwriter):
    """PRD Section 3.2: "The STANDARD variant applies no haircut: `preapproved_standard_cents` is the base amount floored down to the nearest whole multiple of 50000 cents (a $500 step). The CONSERVATIVE variant applies a 0.70 haircut before the same flooring: `preapproved_conservative_cents` is the base multiplied by 0.70, floored to the same $500 step. The selected `preapproved_cents` is the CONSERVATIVE amount when `seasonality_index` — the four-decimal rounded value — exceeds 0.75, and the STANDARD amount otherwise; identical processing history therefore yields a lower pre-approval for a seasonal merchant."

    Design: Difficulty/dual_variant_calc/offer_preapproval_seasonal_haircut
    """
    merchant = create_eligible_merchant_with_history(
        seasonal_history_entries(),
        legal_name="Seasonal Co",
        owner_name="Sam Snow",
    )
    offer = create_offer_for(merchant["id"])
    assert offer["seasonality_index_at_generation"] == pytest.approx(1.2)
    assert offer["preapproved_standard_cents"] == 1_550_000
    assert offer["preapproved_conservative_cents"] == 1_050_000
    assert offer["preapproved_cents"] == 1_050_000, (
        "seasonality 1.2 > 0.75 must select the CONSERVATIVE variant"
    )


def test_seasonal_history_offer_snapshots_avg_monthly_net(api, admin, underwriter):
    """PRD Section 3.2: "The offer also snapshots `trailing_12m_avg_net_cents` (the average monthly net at generation time) and `seasonality_index_at_generation` (the merchant's seasonality index at that moment)."

    Design: Difficulty/dual_variant_calc/offer_preapproval_seasonal_haircut
    """
    merchant = create_eligible_merchant_with_history(
        seasonal_history_entries(),
        legal_name="Seasonal Co",
        owner_name="Sam Snow",
    )
    offer = create_offer_for(merchant["id"])
    assert offer["trailing_12m_avg_net_cents"] == 1_250_000, (
        "(6 x 2,000,000 + 6 x 500,000) / 12 = 1,250,000 average monthly net"
    )
    assert offer["seasonality_index_at_generation"] == pytest.approx(1.2)
    assert offer["status"] == "DRAFT"
    assert offer["renewal_count"] == 0


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / offer_formula_tiered_min_max
# ---------------------------------------------------------------------------

def test_flat_history_preapproval_lands_on_rounding_step(api, admin, underwriter):
    """PRD Section 3.2: "First the average monthly net over the trailing twelve months is taken exactly, then truncated to whole cents, and multiplied by 1.25 to form the base amount. The STANDARD variant applies no haircut: `preapproved_standard_cents` is the base amount floored down to the nearest whole multiple of 50000 cents (a $500 step)."

    Design: Difficulty/combinatorial_formula/offer_formula_tiered_min_max
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    offer = create_offer_for(merchant["id"])
    assert offer["seasonality_index_at_generation"] == 0
    assert offer["preapproved_standard_cents"] == 1_250_000
    assert offer["preapproved_cents"] == 1_250_000


def test_flat_history_conservative_variant_floored_to_same_step(api, admin, underwriter):
    """PRD Section 3.2: "The CONSERVATIVE variant applies a 0.70 haircut before the same flooring: `preapproved_conservative_cents` is the base multiplied by 0.70, floored to the same $500 step. The selected `preapproved_cents` is the CONSERVATIVE amount when `seasonality_index` — the four-decimal rounded value — exceeds 0.75, and the STANDARD amount otherwise; identical processing history therefore yields a lower pre-approval for a seasonal merchant."

    Design: Difficulty/combinatorial_formula/offer_formula_tiered_min_max
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    offer = create_offer_for(merchant["id"])
    # base 1,250,000 x 0.70 = 875,000 -> floor to nearest whole multiple of
    # 50,000 cents ($500 step) gives 850,000 (875,000 = 17.5 x 50,000).
    assert offer["preapproved_conservative_cents"] == 850_000
    # Flat seasonality (0) is below the threshold: STANDARD is selected.
    assert offer["preapproved_cents"] == offer["preapproved_standard_cents"]


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / offer_expiry_reunderwriting_cycle
# ---------------------------------------------------------------------------

def test_expired_offer_renews_and_reissues_with_fresh_window(api, admin, underwriter):
    """PRD Section 3.2: "An `EXPIRED` offer may be re-underwritten by an `Underwriter`, moving it to `REUNDERWRITING`; an offer still in `OFFERED` whose clock has passed `expires_at` may be renewed directly, treated as passing through `EXPIRED`."
    PRD Section 3.2: "A renewed offer can then be issued again, carrying refreshed amounts and a fresh 30-day window."

    Design: Difficulty/non_linear_state_machine/offer_expiry_reunderwriting_cycle
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    offer = create_issued_offer(merchant["id"])
    assert offer["status"] == "OFFERED"

    set_clock("2026-10-02T00:00:00Z")
    expired = validate_success(api.get_offer(offer["id"], underwriter))
    assert expired["status"] == "EXPIRED"

    renewed = validate_success(api.renew_offer(offer["id"], underwriter))
    assert renewed["status"] == "REUNDERWRITING"
    assert renewed["renewal_count"] == 1

    reissued = validate_success(api.issue_offer(offer["id"], underwriter))
    assert reissued["status"] == "OFFERED"
    assert _iso_instant(reissued["expires_at"]) == _iso_instant("2026-11-01T00:00:00Z")


def test_renewal_recomputes_amounts_from_current_aggregates(api, admin, underwriter):
    """PRD Section 3.2: "Re-underwriting recomputes `trailing_12m_avg_net_cents`, `seasonality_index_at_generation`, `preapproved_standard_cents`, `preapproved_conservative_cents`, and the selected `preapproved_cents` from the merchant's current aggregates — the same computation as generation — and increments `renewal_count` by 1."

    Design: Difficulty/non_linear_state_machine/offer_expiry_reunderwriting_cycle
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    offer = create_issued_offer(merchant["id"])

    set_clock("2026-10-02T00:00:00Z")
    renewed = validate_success(api.renew_offer(offer["id"], underwriter))
    # Aggregates unchanged since generation: re-underwrite reproduces them.
    assert renewed["preapproved_cents"] == 1_250_000
    assert renewed["trailing_12m_avg_net_cents"] == 1_000_000
    assert renewed["renewal_count"] == 1


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / offer_validity_half_open_overlap
# ---------------------------------------------------------------------------

def test_second_issue_blocked_while_first_offer_open(api, admin, underwriter):
    """PRD Section 3.2: "Issuance is refused with `ERR_OFFER_OVERLAP_ACTIVE` when any other offer for the same merchant is currently `OFFERED` — validity windows being half-open, an offer whose expiry has not yet arrived still blocks."

    Design: Difficulty/resource_temporal_overlap/offer_validity_half_open_overlap
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    first = create_issued_offer(merchant["id"])
    assert first["status"] == "OFFERED"

    second = create_offer_for(merchant["id"])
    resp = api.issue_offer(second["id"], underwriter)
    validate_error(resp, ApiErrorId.ERR_OFFER_OVERLAP_ACTIVE)


def test_issue_at_exact_expiry_boundary_succeeds(api, admin, underwriter):
    """PRD Section 3.2: "Issuance stamps `issued_at` with the clock and sets `expires_at` to exactly 30 days later; the acceptance window is the half-open interval starting at `issued_at` and ending just before `expires_at`."
    PRD Section 3.2: "Whenever an `OFFERED` offer is read, renewed, or accepted and the clock has reached `expires_at`, the offer transitions to `EXPIRED` at that moment."

    Design: Difficulty/resource_temporal_overlap/offer_validity_half_open_overlap
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    first = create_issued_offer(merchant["id"])
    assert _iso_instant(first["expires_at"]) == _iso_instant("2026-10-01T00:00:00Z")

    second = create_offer_for(merchant["id"])
    # At exactly the first offer's expires_at the half-open window is closed.
    set_clock("2026-10-01T00:00:00Z")
    issued = validate_success(api.issue_offer(second["id"], underwriter))
    assert issued["status"] == "OFFERED"
    assert _iso_instant(issued["expires_at"]) == _iso_instant("2026-10-31T00:00:00Z")


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / expired_offer_vs_amount_cap
# ---------------------------------------------------------------------------

def test_expired_accept_reports_state_error_over_fiscal_error(api, admin, underwriter):
    """PRD Section 2.7: "Fourth, state-permission checks — whether the target resource's state allows the operation, including offer expiry against the clock, merchant eligibility and suspension gates, batch-already-swept, bank-inactive, loan active/terminal gates, and the single-active-loan gate. ... Eighth, fiscal limits (principal within pre-approval, catch-up within outstanding balance, volume minimums)."
    PRD Section 3.2: "Acceptance attempted at or after `expires_at` is rejected with `ERR_OFFER_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/expired_offer_vs_amount_cap
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    offer = create_issued_offer(merchant["id"])
    assert offer["preapproved_cents"] == 1_250_000

    set_clock("2026-10-02T00:00:00Z")
    merchant = validate_success(api.get_merchant(merchant["id"], admin))
    payload = accept_offer_payload(
        merchant["version"], selected_principal_cents=2_000_000)
    resp = api.accept_offer(
        offer["id"], payload, make_merchant_owner_headers(merchant["id"]))
    # Both the expiry rule and the fiscal cap are violated; the state error wins.
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)


def test_accept_at_expiry_rejected_even_within_preapproved(api, admin, underwriter):
    """PRD Section 3.2: "Acceptance attempted at or after `expires_at` is rejected with `ERR_OFFER_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/expired_offer_vs_amount_cap
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    offer = create_issued_offer(merchant["id"])

    set_clock("2026-10-01T00:00:00Z")  # exactly expires_at: half-open window closed
    merchant = validate_success(api.get_merchant(merchant["id"], admin))
    payload = accept_offer_payload(
        merchant["version"], selected_principal_cents=500_000)
    resp = api.accept_offer(
        offer["id"], payload, make_merchant_owner_headers(merchant["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)


# ---------------------------------------------------------------------------
# Queue B: validations / offer eligibility gates and accept constraints
# ---------------------------------------------------------------------------

def test_offer_create_onboarding_merchant_rejected(api, admin, underwriter):
    """PRD Section 3.2: "Generation is gated: the merchant must be `ELIGIBLE` — an `ONBOARDING` merchant yields `ERR_MERCHANT_NOT_ELIGIBLE`, a `SUSPENDED` one yields `ERR_MERCHANT_SUSPENDED` — and the merchant must have recorded processing in all twelve trailing months: `trailing_12m_months_recorded` must be at least 12, otherwise `ERR_MERCHANT_VOLUME_INSUFFICIENT`."

    Design: Corner/validations/offer_create_onboarding_merchant_rejected
    """
    merchant = create_merchant(legal_name="Onboard Co", owner_name="On Board")
    assert merchant["status"] == "ONBOARDING"
    resp = api.create_offer(merchant["id"], underwriter)
    validate_error(resp, ApiErrorId.ERR_MERCHANT_NOT_ELIGIBLE)


def test_offer_create_suspended_merchant_rejected(api, admin, underwriter):
    """PRD Section 3.1: "While a merchant is `SUSPENDED`, new offer generation for that merchant is blocked with `ERR_MERCHANT_SUSPENDED`; existing loans are unaffected."

    Design: Corner/validations/offer_create_suspended_merchant_rejected
    """
    merchant = create_eligible_merchant_with_history(
        migration_risk_history_entries(),
        legal_name="Migrator Inc",
        owner_name="Mig Rator",
    )
    from test_helpers import TEST_USERS
    servicer = TEST_USERS["servicer_agent_headers"]
    signal = validate_success(api.evaluate_migration(merchant["id"], servicer))
    assert signal["triggered"] is True
    validate_success(api.confirm_migration_signal(signal["id"], servicer))

    resp = api.create_offer(merchant["id"], underwriter)
    validate_error(resp, ApiErrorId.ERR_MERCHANT_SUSPENDED)


def test_holdback_pct_outside_offered_set_rejected(api, admin, underwriter):
    """PRD Section 3.2: "the chosen `accepted_holdback_pct` must be one of the offered holdback options 0.08, 0.10, or 0.14, else `ERR_HOLDBACK_PCT_NOT_OFFERED`"

    Design: Corner/validations/holdback_pct_not_offered_rejected
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    offer = create_issued_offer(merchant["id"])

    merchant = validate_success(api.get_merchant(merchant["id"], admin))
    payload = accept_offer_payload(
        merchant["version"], accepted_holdback_pct=0.12)
    resp = api.accept_offer(
        offer["id"], payload, make_merchant_owner_headers(merchant["id"]))
    validate_error(resp, ApiErrorId.ERR_HOLDBACK_PCT_NOT_OFFERED)

    offer_after = validate_success(api.get_offer(offer["id"], underwriter))
    assert offer_after["status"] == "OFFERED", "no loan may be created on rejection"


def test_principal_one_cent_over_preapproved_rejected(api, admin, underwriter):
    """PRD Section 3.2: "and `selected_principal_cents` must not exceed the offer's selected `preapproved_cents`, else `ERR_OFFER_AMOUNT_EXCEEDS_PREAPPROVED`."

    Design: Corner/validations/offer_amount_exceeds_preapproved_rejected
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    offer = create_issued_offer(merchant["id"])
    assert offer["preapproved_cents"] == 1_250_000

    merchant = validate_success(api.get_merchant(merchant["id"], admin))
    payload = accept_offer_payload(
        merchant["version"], selected_principal_cents=1_250_001)
    resp = api.accept_offer(
        offer["id"], payload, make_merchant_owner_headers(merchant["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_AMOUNT_EXCEEDS_PREAPPROVED)


def test_second_acceptance_while_loan_non_terminal_rejected(api, admin, underwriter):
    """PRD Section 3.2: "the merchant must not already carry a non-terminal loan — `active_loan_id` must be null, else `ERR_MERCHANT_HAS_ACTIVE_LOAN`"

    Design: Corner/errors/second_accept_with_active_loan_rejected
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    first = create_issued_offer(merchant["id"])
    merchant = validate_success(api.get_merchant(merchant["id"], admin))
    first_accepted = validate_success(api.accept_offer(
        first["id"], accept_offer_payload(merchant["version"]),
        make_merchant_owner_headers(merchant["id"])))
    assert first_accepted["status"] == "ACCEPTED"

    second = create_issued_offer(merchant["id"])
    merchant = validate_success(api.get_merchant(merchant["id"], admin))
    assert merchant["active_loan_id"] is not None
    resp = api.accept_offer(
        second["id"], accept_offer_payload(merchant["version"]),
        make_merchant_owner_headers(merchant["id"]))
    validate_error(resp, ApiErrorId.ERR_MERCHANT_HAS_ACTIVE_LOAN)

    second_after = validate_success(api.get_offer(second["id"], underwriter))
    assert second_after["status"] == "OFFERED", "no second loan may be created"
