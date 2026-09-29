"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints
only, because each test runs against an empty database. Setup calls go through
`get_success_data` so that a broken precondition reports "Setup failed" rather
than surfacing as a confusing assertion inside the test under exercise.

Ownership-gated calls always thread the real entity id: a `Seller` acts through
`make_seller_headers(seller["id"])` and a `Buyer` through
`make_buyer_headers(buyer["id"])`.
"""
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import ROUTE_DAY_RANK
from .test_users import (
    BROKER_DILIGENCE_USER_ID,
    BROKER_OPS_ALT_USER_ID,
    BROKER_OPS_USER_ID,
    BROKER_VERIFIER_USER_ID,
    ESCROW_FUNDER_USER_ID,
    ESCROW_RELEASER_USER_ID,
    TEST_USERS,
    make_broker_headers,
    make_buyer_headers,
    make_escrow_agent_headers,
    make_seller_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BROKER = TEST_USERS["broker_headers"]

TRAILING_MONTHS = ("2026-05", "2026-06", "2026-07")

# The canonical PHX-NE route every deep chain is built on.
CANONICAL_A1 = dict(
    customer_ref="A1-SUNRISE", service_start_date="2019-03-15", route_day="TUE",
    monthly_service_fee_cents=12000, avg_monthly_chemical_cents=4000,
    avg_monthly_repair_cents=1500, chemical_billing_method="INCLUDED",
    billing_frequency="MONTHLY",
)
CANONICAL_A2 = dict(
    customer_ref="A2-MESA", service_start_date="2023-06-01", route_day="MON",
    monthly_service_fee_cents=15000, avg_monthly_chemical_cents=5000,
    avg_monthly_repair_cents=2000, chemical_billing_method="PASS_THROUGH",
    billing_frequency="MONTHLY",
)
CANONICAL_A3 = dict(
    customer_ref="A3-GILBERT", service_start_date="2025-02-10", route_day="WED",
    monthly_service_fee_cents=9000, avg_monthly_chemical_cents=3000,
    avg_monthly_repair_cents=500, chemical_billing_method="INCLUDED",
    billing_frequency="MONTHLY",
)
CANONICAL_A1_BILLING = dict(billed_service_cents=12000, billed_chemical_cents=4000,
                            billed_repair_cents=1500, collected_cents=17500)
CANONICAL_A2_BILLING = dict(billed_service_cents=15000, billed_chemical_cents=5000,
                            billed_repair_cents=2000, collected_cents=21000)
CANONICAL_A3_BILLING = dict(billed_service_cents=8000, billed_chemical_cents=2000,
                            billed_repair_cents=500, collected_cents=10500)

# Figures the canonical route produces, restated here so tests can name them.
CANONICAL = {
    "listing_claimed_recurring_mrr_cents": 43000,
    "listing_claimed_repair_mrr_cents": 4000,
    "a1_claimed_recurring_mrr_cents": 16000,
    "a2_claimed_recurring_mrr_cents": 15000,
    "a3_claimed_recurring_mrr_cents": 12000,
    "a1_verified_recurring_mrr_cents": 16000,
    "a2_verified_recurring_mrr_cents": 14318,
    "a3_verified_recurring_mrr_cents": 10000,
    "verified_recurring_mrr_cents": 30318,
    "verified_repair_mrr_cents": 3409,
    "listed_basis_valuation_cents": 463500,
    "verified_basis_valuation_cents": 343725,
    "offer_price_cents": 340000,
    "down_payment_cents": 120000,
    "note_principal_cents": 220000,
    "holdback_cents": 51000,
    "escrow_target_amount_cents": 171000,
    "commission_cents": 50000,
    "clawback_cap_cents": 68000,
    "guaranteed_mrr_cents": 30318,
    "allowance_mrr_cents": 1516,
    "effective_multiple_at_close": "11.0",
    "closed_at_utc": "2026-09-01T00:00:00Z",
    "guarantee_end_utc": "2026-11-30T00:00:00Z",
    "holdback_release_utc": "2026-11-30T00:00:00Z",
    "replacement_deadline_utc": "2026-12-14T00:00:00Z",
    "disbursed_to_broker_cents": 50000,
    "disbursed_to_seller_cents": 70000,
}


class RouteContext(dict):
    """Dict of the entities a fixture built, also reachable as attributes."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - developer error only
            raise AttributeError(name) from exc


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def set_clock(api, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock forward (or set it to its present value)."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), ADMIN))


def seed_state_profile(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_state_license_profile(f.state_license_profile_payload(**overrides), ADMIN)
    )


def seed_az_profile(api) -> Dict[str, Any]:
    """AZ: two required permits, reciprocity with NV, 21 processing days, 14 cooling off."""
    return seed_state_profile(api)


def seed_nv_profile(api) -> Dict[str, Any]:
    """NV: one required permit, reciprocity with AZ, 10 processing days, 7 cooling off."""
    return seed_state_profile(
        api,
        state_code="NV",
        required_permit_types=["BUSINESS_TAX"],
        reciprocity_states=["AZ"],
        transfer_processing_days=10,
        cooling_off_days=7,
        provisional_operation_allowed=True,
    )


def seed_seller(api, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_seller(f.seller_payload(**overrides), BROKER))


def suspend_seller(api, seller_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.suspend_seller(seller_id, f.suspend_seller_payload(**overrides), ADMIN)
    )


def seed_buyer(api, decision: Optional[str] = "APPROVE", **overrides) -> Dict[str, Any]:
    """Register a buyer and, unless `decision` is None, decide its qualification."""
    buyer = get_success_data(api.create_buyer(f.buyer_payload(**overrides), BROKER))
    if decision is not None:
        buyer = get_success_data(
            api.qualify_buyer(buyer["id"], f.qualify_buyer_payload(decision), BROKER)
        )
    return buyer


def seed_listing(api, seller_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_route_listing(f.route_listing_payload(seller_id, **overrides), BROKER)
    )


def add_account(api, listing_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_service_account(f.service_account_payload(listing_id, **overrides), BROKER)
    )


def add_billing_months(api, account_id: str, months: Sequence[str] = TRAILING_MONTHS,
                       source: str = "BANK_VERIFIED", **amounts) -> List[Dict[str, Any]]:
    """Append one billing record per month with the same amounts each month."""
    rows = []
    for month in months:
        rows.append(get_success_data(
            api.create_billing_history_record(
                f.billing_history_record_payload(account_id, month, source=source, **amounts),
                BROKER,
            )
        ))
    return rows


def verify_account(api, account_id: str, user_id: str = BROKER_VERIFIER_USER_ID) -> Dict[str, Any]:
    return get_success_data(
        api.verify_service_account(account_id, make_broker_headers(user_id))
    )


def exclude_account(api, account_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.exclude_service_account(account_id, f.exclude_account_payload(**overrides), BROKER)
    )


def listing_version(api, listing_id: str) -> int:
    """Re-read the listing so a valuation can carry a fresh `expected_listing_version`."""
    return get_success_data(api.get_route_listing(listing_id, BROKER))["version"]


def deal_version(api, deal_id: str) -> int:
    """Re-read the deal so an attrition append can carry a fresh `expected_deal_version`."""
    return get_success_data(api.get_deal(deal_id, BROKER))["version"]


def create_valuation(api, listing_id: str, basis: str,
                     expected_listing_version: Optional[int] = None) -> Dict[str, Any]:
    if expected_listing_version is None:
        expected_listing_version = listing_version(api, listing_id)
    return get_success_data(
        api.create_route_valuation(
            listing_id, f.route_valuation_payload(basis, expected_listing_version), BROKER
        )
    )


def publish_listing(api, listing_id: str) -> Dict[str, Any]:
    return get_success_data(api.publish_route_listing(listing_id, BROKER))


def open_deal(api, listing_id: str, buyer: Dict[str, Any], **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_deal(f.deal_payload(listing_id, buyer["id"], **overrides),
                        make_buyer_headers(buyer["id"]))
    )


def accept_deal(api, deal_id: str, seller: Dict[str, Any],
                retention_guarantee_days: int = 90) -> Dict[str, Any]:
    return get_success_data(
        api.accept_deal(deal_id, f.accept_deal_payload(retention_guarantee_days),
                        make_seller_headers(seller["id"]))
    )


def transfers_for_deal(api, deal_id: str, permit_type: Optional[str] = None) -> List[Dict[str, Any]]:
    params = {"deal_id": deal_id}
    if permit_type is not None:
        params["permit_type"] = permit_type
    return get_success_data(api.list_license_transfers(BROKER, params=params))


def transfer_for_permit(api, deal_id: str, permit_type: str) -> Dict[str, Any]:
    rows = transfers_for_deal(api, deal_id, permit_type)
    assert rows, f"Setup failed: no {permit_type} licence transfer exists for deal {deal_id}"
    return rows[0]


def escrow_for_deal(api, deal_id: str) -> Dict[str, Any]:
    rows = get_success_data(api.list_escrow_accounts(BROKER, params={"deal_id": deal_id}))
    assert rows, f"Setup failed: no escrow account exists for deal {deal_id}"
    return rows[0]


def approve_permit(api, transfer_id: str, buyer: Dict[str, Any], applied_on: str,
                   decided_on: Optional[str] = None) -> Dict[str, Any]:
    """File a permit application and have the regulator approve it."""
    get_success_data(
        api.apply_license_transfer(transfer_id, f.apply_license_transfer_payload(applied_on),
                                   make_buyer_headers(buyer["id"]))
    )
    return get_success_data(
        api.decide_license_transfer(
            transfer_id, f.decide_license_transfer_payload("APPROVE", decided_on or applied_on), ADMIN
        )
    )


def waive_permit(api, transfer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.waive_license_transfer(transfer_id, f.waive_license_transfer_payload(**overrides), BROKER)
    )


def fund_escrow(api, escrow_id: str, amount_cents: int,
                user_id: str = ESCROW_FUNDER_USER_ID) -> Dict[str, Any]:
    return get_success_data(
        api.create_escrow_deposit(escrow_id, f.escrow_deposit_payload(amount_cents),
                                  make_escrow_agent_headers(user_id))
    )


def introduce(api, account_id: str, deal_id: str, introduction_date: str,
              seller: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        api.introduce_service_account(
            account_id, f.introduce_account_payload(deal_id, introduction_date),
            make_seller_headers(seller["id"]),
        )
    )


def append_attrition(api, deal_id: str, account_id: str, event_type: str, effective_date: str,
                     mrr_delta_cents: int, attributed_to: str = "NATURAL",
                     expected_deal_version: Optional[int] = None,
                     user_id: str = BROKER_OPS_USER_ID) -> Dict[str, Any]:
    if expected_deal_version is None:
        expected_deal_version = deal_version(api, deal_id)
    return get_success_data(
        api.create_attrition_event(
            f.attrition_event_payload(deal_id, account_id, event_type, effective_date,
                                      mrr_delta_cents, attributed_to, expected_deal_version),
            make_broker_headers(user_id),
        )
    )


def open_settlement(api, deal_id: str, remedy_basis: str = "REPLACEMENT_BASIS",
                    user_id: str = BROKER_OPS_USER_ID, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_clawback_settlement(
            f.clawback_settlement_payload(deal_id, remedy_basis, **overrides),
            make_broker_headers(user_id),
        )
    )


# ---------------------------------------------------------------------------
# The canonical PHX-NE tower — each tier calls the tier below it
# ---------------------------------------------------------------------------

def draft_route_with_three_stops(api, **listing_overrides) -> RouteContext:
    """Draft PHX-NE listing carrying the three canonical service accounts.

    Claimed recurring MRR is 43000 cents (16000 + 15000 + 12000) because the
    PASS_THROUGH stop contributes no chemical revenue.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    profile = seed_az_profile(api)
    seller = seed_seller(api)
    buyer = seed_buyer(api)
    listing = seed_listing(api, seller["id"], **listing_overrides)
    a1 = add_account(api, listing["id"], **CANONICAL_A1)
    a2 = add_account(api, listing["id"], **CANONICAL_A2)
    a3 = add_account(api, listing["id"], **CANONICAL_A3)
    return RouteContext(profile=profile, seller=seller, buyer=buyer, listing=listing,
                        a1=a1, a2=a2, a3=a3)


def route_with_billing_history(api, ctx: Optional[RouteContext] = None) -> RouteContext:
    """Canonical route plus three trailing bank-verified months for every stop.

    The collected-to-billed ratios are 1.0000 for A1, 0.9545 for A2 and 0.8333
    for A3, so only A3 breaches the five percent variance tolerance.
    """
    ctx = ctx or draft_route_with_three_stops(api)
    ctx["a1_billing"] = add_billing_months(api, ctx["a1"]["id"], **CANONICAL_A1_BILLING)
    ctx["a2_billing"] = add_billing_months(api, ctx["a2"]["id"], **CANONICAL_A2_BILLING)
    ctx["a3_billing"] = add_billing_months(api, ctx["a3"]["id"], **CANONICAL_A3_BILLING)
    return ctx


def listed_route(api, ctx: Optional[RouteContext] = None) -> RouteContext:
    """Canonical route with a LISTED_BASIS valuation of 463500 cents, published."""
    ctx = ctx or route_with_billing_history(api)
    ctx["listed_valuation"] = create_valuation(api, ctx["listing"]["id"], "LISTED_BASIS")
    ctx["listing"] = publish_listing(api, ctx["listing"]["id"])
    return ctx


def offer_submitted_deal(api, ctx: Optional[RouteContext] = None, **deal_overrides) -> RouteContext:
    """Published canonical route with a 340000-cent seller-note offer outstanding."""
    ctx = ctx or listed_route(api)
    ctx["deal"] = open_deal(api, ctx["listing"]["id"], ctx["buyer"], **deal_overrides)
    return ctx


def verified_route_with_deal(api, ctx: Optional[RouteContext] = None) -> RouteContext:
    """Offer outstanding, all three stops verified, the disputed stop excluded,
    and a VERIFIED_BASIS valuation of 343725 cents recorded after the offer."""
    ctx = ctx or offer_submitted_deal(api)
    ctx["a1"] = verify_account(api, ctx["a1"]["id"])
    ctx["a2"] = verify_account(api, ctx["a2"]["id"])
    ctx["a3"] = verify_account(api, ctx["a3"]["id"])
    ctx["a3"] = exclude_account(api, ctx["a3"]["id"])
    ctx["verified_valuation"] = create_valuation(api, ctx["listing"]["id"], "VERIFIED_BASIS")
    return ctx


def accepted_deal(api, ctx: Optional[RouteContext] = None,
                  retention_guarantee_days: int = 90) -> RouteContext:
    """Canonical deal accepted by the seller, so both licence transfers now exist."""
    ctx = ctx or verified_route_with_deal(api)
    ctx["deal"] = accept_deal(api, ctx["deal"]["id"], ctx["seller"], retention_guarantee_days)
    ctx["pesticide_transfer"] = transfer_for_permit(api, ctx["deal"]["id"], "PESTICIDE_APPLICATOR")
    ctx["business_tax_transfer"] = transfer_for_permit(api, ctx["deal"]["id"], "BUSINESS_TAX")
    return ctx


def permits_approved_deal(api, ctx: Optional[RouteContext] = None,
                          applied_on: str = "2026-08-01") -> RouteContext:
    """Canonical accepted deal with both required permits approved."""
    ctx = ctx or accepted_deal(api)
    ctx["pesticide_transfer"] = approve_permit(api, ctx["pesticide_transfer"]["id"], ctx["buyer"],
                                               applied_on)
    ctx["business_tax_transfer"] = approve_permit(api, ctx["business_tax_transfer"]["id"],
                                                 ctx["buyer"], applied_on)
    return ctx


def diligence_cleared_deal(api, ctx: Optional[RouteContext] = None) -> RouteContext:
    """Canonical deal signed off against the VERIFIED_BASIS valuation.

    Verified recurring MRR of 30318 cents clears the seventy percent floor on
    the listed 43000 cents.
    """
    ctx = ctx or permits_approved_deal(api)
    ctx["deal"] = get_success_data(
        api.clear_diligence(ctx["deal"]["id"],
                            f.clear_diligence_payload(ctx["verified_valuation"]["id"]),
                            make_broker_headers(BROKER_DILIGENCE_USER_ID))
    )
    return ctx


def financing_approved_deal(api, ctx: Optional[RouteContext] = None,
                            approved_amount_cents: int = 220000) -> RouteContext:
    """Canonical deal with the 220000-cent note approved and escrow opened."""
    ctx = ctx or diligence_cleared_deal(api)
    ctx["deal"] = get_success_data(
        api.approve_financing(ctx["deal"]["id"],
                              f.approve_financing_payload(approved_amount_cents), BROKER)
    )
    ctx["escrow"] = escrow_for_deal(api, ctx["deal"]["id"])
    return ctx


def escrow_funded_deal(api, ctx: Optional[RouteContext] = None,
                       deposit_cents: int = 171000, introduce_accounts: bool = True,
                       introduction_date: str = "2026-08-01") -> RouteContext:
    """Canonical deal fully funded to its 171000-cent escrow target.

    Introductions run in route-day order, so the Monday stop precedes the
    Tuesday stop and the excluded Wednesday stop is never introduced.
    """
    ctx = ctx or financing_approved_deal(api)
    ctx["escrow"] = fund_escrow(api, ctx["escrow"]["id"], deposit_cents)
    # The final deposit cascades the deal to ESCROW_FUNDED (PRD §3.8), so the cached deal
    # copy must be refreshed or callers read a stale FINANCING_APPROVED status.
    ctx["deal"] = get_success_data(api.get_deal(ctx["deal"]["id"], BROKER))
    if introduce_accounts:
        ctx["a2"] = introduce(api, ctx["a2"]["id"], ctx["deal"]["id"], introduction_date,
                              ctx["seller"])
        ctx["a1"] = introduce(api, ctx["a1"]["id"], ctx["deal"]["id"], introduction_date,
                              ctx["seller"])
    return ctx


def closed_deal(api, ctx: Optional[RouteContext] = None,
                close_utc: str = "2026-09-01T00:00:00Z") -> RouteContext:
    """Canonical deal closed on 2026-09-01, opening a ninety-day guarantee window."""
    ctx = ctx or escrow_funded_deal(api)
    set_clock(api, close_utc)
    ctx["deal"] = get_success_data(api.close_deal(ctx["deal"]["id"], BROKER))
    ctx["escrow"] = escrow_for_deal(api, ctx["deal"]["id"])
    ctx["a1"] = get_success_data(api.get_service_account(ctx["a1"]["id"], BROKER))
    ctx["a2"] = get_success_data(api.get_service_account(ctx["a2"]["id"], BROKER))
    ctx["listing"] = get_success_data(api.get_route_listing(ctx["listing"]["id"], BROKER))
    return ctx


def clawback_triggered_deal(api, ctx: Optional[RouteContext] = None,
                            attrition_utc: str = "2026-10-01T00:00:00Z",
                            mrr_delta_cents: int = -14318,
                            event_type: str = "CANCELLED",
                            attributed_to: str = "NATURAL") -> RouteContext:
    """Canonical closed deal whose retained MRR has fallen through the allowance.

    Losing the 14318-cent stop leaves 16000 cents retained against a guaranteed
    30318 cents less a 1516-cent allowance, so the shortfall is real.
    """
    ctx = ctx or closed_deal(api)
    set_clock(api, attrition_utc)
    ctx["attrition_event"] = append_attrition(
        api, ctx["deal"]["id"], ctx["a2"]["id"], event_type,
        attrition_utc[:10], mrr_delta_cents, attributed_to,
    )
    ctx["deal"] = get_success_data(api.get_deal(ctx["deal"]["id"], BROKER))
    ctx["a2"] = get_success_data(api.get_service_account(ctx["a2"]["id"], BROKER))
    return ctx


def replacement_recorded_deal(api, ctx: Optional[RouteContext] = None,
                              **replacement_overrides) -> RouteContext:
    """Clawback-triggered canonical deal with a 12000-cent replacement stop filed."""
    ctx = ctx or clawback_triggered_deal(api)
    ctx["replacement"] = get_success_data(
        api.replace_service_account(ctx["a2"]["id"],
                                    f.replacement_account_payload(**replacement_overrides), BROKER)
    )
    ctx["a2"] = get_success_data(api.get_service_account(ctx["a2"]["id"], BROKER))
    return ctx


def draft_settlement(api, ctx: Optional[RouteContext] = None,
                     remedy_basis: str = "REPLACEMENT_BASIS") -> RouteContext:
    """Clawback-triggered canonical deal with a settlement opened in DRAFT."""
    ctx = ctx or clawback_triggered_deal(api)
    ctx["settlement"] = open_settlement(api, ctx["deal"]["id"], remedy_basis)
    return ctx


def proposed_settlement(api, ctx: Optional[RouteContext] = None,
                        adjustment_cents: int = 20000,
                        remedy_basis: str = "REPLACEMENT_BASIS") -> RouteContext:
    """Canonical settlement moved to PROPOSED with an adjustment on the table."""
    ctx = ctx or draft_settlement(api, remedy_basis=remedy_basis)
    ctx["settlement"] = get_success_data(
        api.propose_clawback_settlement(ctx["settlement"]["id"],
                                        f.propose_settlement_payload(adjustment_cents),
                                        make_broker_headers(BROKER_OPS_USER_ID))
    )
    return ctx


def disputed_settlement(api, ctx: Optional[RouteContext] = None,
                        adjustment_cents: int = 20000) -> RouteContext:
    """Canonical settlement the seller has pushed back into DISPUTED."""
    ctx = ctx or proposed_settlement(api, adjustment_cents=adjustment_cents)
    ctx["settlement"] = get_success_data(
        api.dispute_clawback_settlement(ctx["settlement"]["id"], f.dispute_settlement_payload(),
                                        make_seller_headers(ctx["seller"]["id"]))
    )
    return ctx


# ---------------------------------------------------------------------------
# The NV single-stop tower — a small closed deal with round figures
# ---------------------------------------------------------------------------

NV_ACCOUNT = dict(
    customer_ref="ACCT-D1", service_start_date="2019-03-15", route_day="TUE",
    monthly_service_fee_cents=20000, avg_monthly_chemical_cents=0,
    avg_monthly_repair_cents=0, chemical_billing_method="INCLUDED",
    billing_frequency="MONTHLY",
)
NV_BILLING = dict(billed_service_cents=20000, billed_chemical_cents=0,
                  billed_repair_cents=0, collected_cents=20000)
NV_LISTING = dict(region_code="NV-LV1", state_code="NV", asking_price_cents=200000,
                  listed_mrr_cents=20000, listed_account_count=1,
                  exclusive_start_date="2026-08-01", exclusive_end_date="2026-11-01")
NV_DEAL = dict(offer_price_cents=180000, financing_type="SELLER_NOTE",
               down_payment_cents=60000, note_principal_cents=120000,
               retention_guarantee_days=90)
NV_FIGURES = {
    "guaranteed_mrr_cents": 20000,
    "allowance_mrr_cents": 1000,
    "effective_multiple_at_close": "10.0",
    "clawback_cap_cents": 36000,
    "holdback_cents": 27000,
    "escrow_target_amount_cents": 87000,
}


def nv_route_with_one_stop(api, **listing_overrides) -> RouteContext:
    """Draft NV-LV1 listing with a single 20000-cent stop and clean billing history."""
    set_clock(api, "2026-08-01T00:00:00Z")
    profile = seed_nv_profile(api)
    seller = seed_seller(api)
    buyer = seed_buyer(api, prequalified_amount_cents=30000000)
    payload = dict(NV_LISTING)
    payload.update(listing_overrides)
    listing = seed_listing(api, seller["id"], **payload)
    account = add_account(api, listing["id"], **NV_ACCOUNT)
    billing = add_billing_months(api, account["id"], **NV_BILLING)
    return RouteContext(profile=profile, seller=seller, buyer=buyer, listing=listing,
                        account=account, billing=billing)


def nv_closed_deal(api, ctx: Optional[RouteContext] = None,
                   close_utc: str = "2026-09-01T00:00:00Z") -> RouteContext:
    """NV single-stop deal driven all the way to CLOSED with a waived permit.

    The buyer holds an AZ licence and NV grants reciprocity to AZ, so the only
    required permit is waived rather than applied for.
    """
    ctx = ctx or nv_route_with_one_stop(api)
    ctx["listed_valuation"] = create_valuation(api, ctx["listing"]["id"], "LISTED_BASIS")
    ctx["listing"] = publish_listing(api, ctx["listing"]["id"])
    ctx["deal"] = open_deal(api, ctx["listing"]["id"], ctx["buyer"], **NV_DEAL)
    ctx["account"] = verify_account(api, ctx["account"]["id"])
    ctx["verified_valuation"] = create_valuation(api, ctx["listing"]["id"], "VERIFIED_BASIS")
    ctx["deal"] = accept_deal(api, ctx["deal"]["id"], ctx["seller"])
    ctx["business_tax_transfer"] = transfer_for_permit(api, ctx["deal"]["id"], "BUSINESS_TAX")
    ctx["business_tax_transfer"] = waive_permit(api, ctx["business_tax_transfer"]["id"])
    ctx["deal"] = get_success_data(
        api.clear_diligence(ctx["deal"]["id"],
                            f.clear_diligence_payload(ctx["verified_valuation"]["id"]),
                            make_broker_headers(BROKER_DILIGENCE_USER_ID))
    )
    ctx["deal"] = get_success_data(
        api.approve_financing(ctx["deal"]["id"], f.approve_financing_payload(120000), BROKER)
    )
    ctx["escrow"] = escrow_for_deal(api, ctx["deal"]["id"])
    ctx["escrow"] = fund_escrow(api, ctx["escrow"]["id"], 87000)
    ctx["account"] = introduce(api, ctx["account"]["id"], ctx["deal"]["id"], "2026-08-01",
                               ctx["seller"])
    set_clock(api, close_utc)
    ctx["deal"] = get_success_data(api.close_deal(ctx["deal"]["id"], BROKER))
    ctx["escrow"] = escrow_for_deal(api, ctx["deal"]["id"])
    return ctx


def nv_clawback_triggered_deal(api, ctx: Optional[RouteContext] = None,
                               attrition_utc: str = "2026-10-01T00:00:00Z",
                               event_type: str = "DOWNGRADED",
                               mrr_delta_cents: int = -3000,
                               attributed_to: str = "NATURAL") -> RouteContext:
    """NV closed deal downgraded by 3000 cents, past its 1000-cent allowance."""
    ctx = ctx or nv_closed_deal(api)
    set_clock(api, attrition_utc)
    ctx["attrition_event"] = append_attrition(
        api, ctx["deal"]["id"], ctx["account"]["id"], event_type, attrition_utc[:10],
        mrr_delta_cents, attributed_to,
    )
    ctx["deal"] = get_success_data(api.get_deal(ctx["deal"]["id"], BROKER))
    return ctx


# ---------------------------------------------------------------------------
# Single-purpose variant routes
# ---------------------------------------------------------------------------

def tier_route(api, region_code: str, monthly_service_fee_cents: int,
               service_start_date: str = "2019-03-15", **listing_overrides) -> RouteContext:
    """One-stop AZ route whose recurring MRR lands on a chosen tier figure.

    The stop is verified against a matching bank-verified history so a
    VERIFIED_BASIS valuation can be taken without any variance dispute.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    profile = seed_az_profile(api)
    seller = seed_seller(api)
    payload = dict(region_code=region_code, listed_mrr_cents=monthly_service_fee_cents,
                   listed_account_count=1,
                   asking_price_cents=max(monthly_service_fee_cents * 10, 100000))
    payload.update(listing_overrides)
    listing = seed_listing(api, seller["id"], **payload)
    account = add_account(api, listing["id"], customer_ref=f"{region_code}-S1",
                          service_start_date=service_start_date,
                          monthly_service_fee_cents=monthly_service_fee_cents,
                          avg_monthly_chemical_cents=0, avg_monthly_repair_cents=0)
    billing = add_billing_months(api, account["id"],
                                 billed_service_cents=monthly_service_fee_cents,
                                 billed_chemical_cents=0, billed_repair_cents=0,
                                 collected_cents=monthly_service_fee_cents)
    return RouteContext(profile=profile, seller=seller, listing=listing, account=account,
                        billing=billing)


def collection_ratio_route(api, billed_service_cents: int, collected_cents: int,
                           region_code: str = "BND-01") -> RouteContext:
    """One-stop route with a chosen billed-versus-collected ratio in every month."""
    set_clock(api, "2026-08-01T00:00:00Z")
    profile = seed_az_profile(api)
    seller = seed_seller(api)
    listing = seed_listing(api, seller["id"], region_code=region_code,
                           listed_mrr_cents=billed_service_cents, listed_account_count=1,
                           asking_price_cents=billed_service_cents * 10)
    account = add_account(api, listing["id"], customer_ref=f"{region_code}-S1",
                          monthly_service_fee_cents=billed_service_cents,
                          avg_monthly_chemical_cents=0, avg_monthly_repair_cents=0)
    billing = add_billing_months(api, account["id"],
                                 billed_service_cents=billed_service_cents,
                                 billed_chemical_cents=0, billed_repair_cents=0,
                                 collected_cents=collected_cents)
    return RouteContext(profile=profile, seller=seller, listing=listing, account=account,
                        billing=billing)


def month_varying_route(api, monthly: Sequence[Dict[str, int]],
                        region_code: str = "ROUND-ORDER",
                        monthly_service_fee_cents: int = 10000,
                        avg_monthly_chemical_cents: int = 3000,
                        avg_monthly_repair_cents: int = 2000) -> RouteContext:
    """One-stop route whose three trailing months carry different figures.

    `monthly` supplies one dict of billing amounts per trailing month, which is
    what a per-month rounding order can be observed against.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    profile = seed_az_profile(api)
    seller = seed_seller(api)
    claimed = monthly_service_fee_cents + avg_monthly_chemical_cents
    listing = seed_listing(api, seller["id"], region_code=region_code,
                           listed_mrr_cents=claimed, listed_account_count=1,
                           asking_price_cents=claimed * 10)
    account = add_account(api, listing["id"], customer_ref=f"{region_code}-S1",
                          monthly_service_fee_cents=monthly_service_fee_cents,
                          avg_monthly_chemical_cents=avg_monthly_chemical_cents,
                          avg_monthly_repair_cents=avg_monthly_repair_cents)
    rows = []
    for month, amounts in zip(TRAILING_MONTHS, monthly):
        rows.append(get_success_data(
            api.create_billing_history_record(
                f.billing_history_record_payload(account["id"], month, **amounts), BROKER)
        ))
    return RouteContext(profile=profile, seller=seller, listing=listing, account=account,
                        billing=rows)


def empty_route(api, region_code: str = "EMPTY-01") -> RouteContext:
    """Draft listing that carries no service account at all."""
    set_clock(api, "2026-08-01T00:00:00Z")
    profile = seed_az_profile(api)
    seller = seed_seller(api)
    listing = seed_listing(api, seller["id"], region_code=region_code,
                           listed_mrr_cents=0, listed_account_count=0,
                           asking_price_cents=100000)
    return RouteContext(profile=profile, seller=seller, listing=listing)


def suspended_seller_route(api, region_code: str = "SUS-01") -> RouteContext:
    """Draft listing whose seller has since been suspended."""
    ctx = tier_route(api, region_code, 20000)
    ctx["seller"] = suspend_seller(api, ctx["seller"]["id"])
    return ctx


def second_seller(api) -> Dict[str, Any]:
    """A second AZ seller, for cases that need two distinct sellers."""
    return seed_seller(api, legal_name="Cactus Clear Pools Inc", license_number="AZ-PA-2002")


def reciprocity_route(api, buyer_state_code: str = "NV",
                      region_code: str = "REC-01") -> RouteContext:
    """AZ route with a buyer licensed in a chosen state, for waiver eligibility.

    AZ grants reciprocity to NV only, so a buyer licensed elsewhere cannot be
    waived through.
    """
    ctx = tier_route(api, region_code, 20000)
    ctx["buyer"] = seed_buyer(api, state_code=buyer_state_code,
                              prequalified_amount_cents=30000000)
    return ctx


def two_stop_route(api, region_code: str = "PHX-TWO") -> RouteContext:
    """AZ route with two verified stops of 20000 and 10000 recurring cents."""
    set_clock(api, "2026-08-01T00:00:00Z")
    profile = seed_az_profile(api)
    seller = seed_seller(api)
    buyer = seed_buyer(api, prequalified_amount_cents=30000000)
    listing = seed_listing(api, seller["id"], region_code=region_code,
                           listed_mrr_cents=30000, listed_account_count=2,
                           asking_price_cents=300000)
    first = add_account(api, listing["id"], customer_ref=f"{region_code}-S1",
                        route_day="MON", monthly_service_fee_cents=20000,
                        avg_monthly_chemical_cents=0, avg_monthly_repair_cents=0)
    second = add_account(api, listing["id"], customer_ref=f"{region_code}-S2",
                         route_day="TUE", monthly_service_fee_cents=10000,
                         avg_monthly_chemical_cents=0, avg_monthly_repair_cents=0)
    add_billing_months(api, first["id"], billed_service_cents=20000, billed_chemical_cents=0,
                       billed_repair_cents=0, collected_cents=20000)
    add_billing_months(api, second["id"], billed_service_cents=10000, billed_chemical_cents=0,
                       billed_repair_cents=0, collected_cents=10000)
    return RouteContext(profile=profile, seller=seller, buyer=buyer, listing=listing,
                        first=first, second=second)


def qualified_buyer(api, **overrides) -> Dict[str, Any]:
    """An approved buyer with a large prequalification, ready to make an offer."""
    overrides.setdefault("prequalified_amount_cents", 30000000)
    return seed_buyer(api, **overrides)


def introduction_ready_deal(api, ctx: Optional[RouteContext] = None,
                            applied_on: str = "2026-08-01") -> RouteContext:
    """Canonical AZ route accepted with both permits approved and nothing excluded.

    All three stops therefore sit in the introduction queue in route-day order:
    the Monday stop A2, then the Tuesday stop A1, then the Wednesday stop A3.
    """
    ctx = ctx or draft_route_with_three_stops(api)
    ctx["listed_valuation"] = create_valuation(api, ctx["listing"]["id"], "LISTED_BASIS")
    ctx["listing"] = publish_listing(api, ctx["listing"]["id"])
    ctx["deal"] = open_deal(api, ctx["listing"]["id"], ctx["buyer"])
    ctx["deal"] = accept_deal(api, ctx["deal"]["id"], ctx["seller"])
    ctx["pesticide_transfer"] = approve_permit(
        api, transfer_for_permit(api, ctx["deal"]["id"], "PESTICIDE_APPLICATOR")["id"],
        ctx["buyer"], applied_on)
    ctx["business_tax_transfer"] = approve_permit(
        api, transfer_for_permit(api, ctx["deal"]["id"], "BUSINESS_TAX")["id"],
        ctx["buyer"], applied_on)
    ctx["escrow"] = escrow_for_deal(api, ctx["deal"]["id"])
    return ctx


def nv_stop(customer_ref: str, route_day: str, monthly_service_fee_cents: int,
            **overrides) -> Dict[str, Any]:
    """One NV stop specification whose verified figure equals its claimed figure."""
    spec = dict(customer_ref=customer_ref, route_day=route_day,
                service_start_date="2019-03-15",
                monthly_service_fee_cents=monthly_service_fee_cents,
                avg_monthly_chemical_cents=0, avg_monthly_repair_cents=0,
                chemical_billing_method="INCLUDED", billing_frequency="MONTHLY")
    spec.update(overrides)
    return spec


def nv_deal_route(api, region_code: str = "NV-LV1",
                  stops: Sequence[Dict[str, Any]] = (NV_ACCOUNT,),
                  listed_mrr_cents: int = 20000, asking_price_cents: int = 200000,
                  deal: Optional[Dict[str, Any]] = None,
                  stop_after: str = "closed", waive: bool = True,
                  introduce_on: str = "2026-08-01",
                  close_utc: str = "2026-09-01T00:00:00Z",
                  profile: Optional[Dict[str, Any]] = None,
                  seller: Optional[Dict[str, Any]] = None,
                  buyer: Optional[Dict[str, Any]] = None) -> RouteContext:
    """Build an NV route of one or more stops and drive its deal to `stop_after`.

    NV requires BUSINESS_TAX alone and grants reciprocity to AZ, so the single
    permit is waived rather than filed. `stop_after` is one of `listed`,
    `offer`, `accepted`, `escrow_funded` or `closed`, and every stop is verified
    against bank traces that collect its whole invoice, so each verified figure
    equals its claimed figure and no variance dispute arises.
    """
    if profile is None:
        set_clock(api, "2026-08-01T00:00:00Z")
        profile = seed_nv_profile(api)
    seller = seller or seed_seller(api)
    buyer = buyer or seed_buyer(api, prequalified_amount_cents=30000000)
    listing = seed_listing(api, seller["id"], region_code=region_code, state_code="NV",
                           asking_price_cents=asking_price_cents,
                           listed_mrr_cents=listed_mrr_cents,
                           listed_account_count=len(stops),
                           exclusive_start_date="2026-08-01",
                           exclusive_end_date="2026-11-01")
    accounts = []
    for spec in stops:
        account = add_account(api, listing["id"], **spec)
        billed_total = (spec["monthly_service_fee_cents"] + spec["avg_monthly_chemical_cents"]
                        + spec["avg_monthly_repair_cents"])
        add_billing_months(api, account["id"],
                           billed_service_cents=spec["monthly_service_fee_cents"],
                           billed_chemical_cents=spec["avg_monthly_chemical_cents"],
                           billed_repair_cents=spec["avg_monthly_repair_cents"],
                           collected_cents=billed_total)
        accounts.append(account)
    ctx = RouteContext(profile=profile, seller=seller, buyer=buyer, listing=listing,
                       accounts=accounts, account=accounts[0])
    ctx["listed_valuation"] = create_valuation(api, listing["id"], "LISTED_BASIS")
    ctx["listing"] = publish_listing(api, listing["id"])
    if stop_after == "listed":
        return ctx
    ctx["deal"] = open_deal(api, listing["id"], buyer, **(deal or NV_DEAL))
    if stop_after == "offer":
        return ctx
    ctx["accounts"] = [verify_account(api, a["id"]) for a in accounts]
    ctx["account"] = ctx["accounts"][0]
    ctx["verified_valuation"] = create_valuation(api, listing["id"], "VERIFIED_BASIS")
    ctx["deal"] = accept_deal(api, ctx["deal"]["id"],
                              seller, (deal or NV_DEAL)["retention_guarantee_days"])
    ctx["transfer"] = transfer_for_permit(api, ctx["deal"]["id"], "BUSINESS_TAX")
    ctx["escrow"] = escrow_for_deal(api, ctx["deal"]["id"])
    if stop_after == "accepted":
        return ctx
    if waive:
        ctx["transfer"] = waive_permit(api, ctx["transfer"]["id"])
    ctx["deal"] = get_success_data(
        api.clear_diligence(ctx["deal"]["id"],
                            f.clear_diligence_payload(ctx["verified_valuation"]["id"]),
                            make_broker_headers(BROKER_DILIGENCE_USER_ID))
    )
    ctx["deal"] = get_success_data(
        api.approve_financing(ctx["deal"]["id"],
                              f.approve_financing_payload((deal or NV_DEAL)["note_principal_cents"]),
                              BROKER)
    )
    ctx["escrow"] = fund_escrow(api, ctx["escrow"]["id"], ctx["deal"]["escrow_target_amount_cents"])
    ordered = sorted(ctx["accounts"], key=lambda a: ROUTE_DAY_RANK[a["route_day"]])
    ctx["accounts"] = [introduce(api, a["id"], ctx["deal"]["id"], introduce_on, seller)
                       for a in ordered]
    ctx["account"] = next(a for a in ctx["accounts"] if a["id"] == accounts[0]["id"])
    if stop_after == "escrow_funded":
        ctx["deal"] = get_success_data(api.get_deal(ctx["deal"]["id"], BROKER))
        return ctx
    set_clock(api, close_utc)
    ctx["deal"] = get_success_data(api.close_deal(ctx["deal"]["id"], BROKER))
    ctx["escrow"] = escrow_for_deal(api, ctx["deal"]["id"])
    ctx["accounts"] = [get_success_data(api.get_service_account(a["id"], BROKER))
                       for a in ctx["accounts"]]
    ctx["account"] = next(a for a in ctx["accounts"] if a["id"] == accounts[0]["id"])
    return ctx


def account_by_ref(ctx: RouteContext, customer_ref: str) -> Dict[str, Any]:
    """Pick one stop out of an `nv_deal_route` context by its customer reference."""
    return next(a for a in ctx["accounts"] if a["customer_ref"] == customer_ref)
