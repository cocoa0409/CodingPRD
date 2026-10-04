"""Composite setup helpers for the holdback-financing API.

Every helper builds its preconditions from scratch via public endpoints,
using the lenient setup validator so failures surface as "Setup failed".
The logical clock defaults to 2026-09-01T00:00:00Z; helpers that need a
different clock call the clock endpoint explicitly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import FLAT_HISTORY_DATES, HOLDBACK_10, PERIOD_END_CLOCKS
from .factories import (
    accept_offer_payload,
    create_bank_payload,
    create_batch_payload,
    create_catch_up_payload,
    create_merchant_payload,
    create_sweep_payload,
    quote_sale_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_bank_officer_headers,
    make_guarantor_principal_headers,
    make_merchant_owner_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
SERVICER = TEST_USERS["servicer_agent_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Low-level building blocks
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (PlatformAdmin-only endpoint)."""
    get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def create_merchant(**overrides) -> dict:
    resp = api_client.create_merchant(create_merchant_payload(**overrides), ADMIN)
    return get_success_data(resp)


def record_finalized_batch(merchant_id: str, processing_date: str,
                           gross_cents: int, refunds_cents: int = 0,
                           chargebacks_cents: int = 0) -> dict:
    """Create a batch and finalize it (counts toward merchant aggregates)."""
    payload = create_batch_payload(
        processing_date=processing_date,
        gross_cents=gross_cents,
        refunds_cents=refunds_cents,
        chargebacks_cents=chargebacks_cents,
    )
    batch = get_success_data(api_client.create_batch(merchant_id, payload, ADMIN))
    return get_success_data(api_client.finalize_batch(batch["id"], SERVICER))


def record_open_batch(merchant_id: str, processing_date: str,
                      gross_cents: int, refunds_cents: int = 0,
                      chargebacks_cents: int = 0) -> dict:
    """Create a batch and leave it OPEN."""
    payload = create_batch_payload(
        processing_date=processing_date,
        gross_cents=gross_cents,
        refunds_cents=refunds_cents,
        chargebacks_cents=chargebacks_cents,
    )
    return get_success_data(api_client.create_batch(merchant_id, payload, ADMIN))


def build_processing_history(merchant_id: str, entries: list):
    """Finalize a list of daily batches.

    entries: list of dicts with processing_date, gross_cents and optional
    refunds_cents / chargebacks_cents. Returns the finalized batch dicts.
    """
    batches = []
    for e in entries:
        batches.append(record_finalized_batch(
            merchant_id,
            e["processing_date"],
            e["gross_cents"],
            e.get("refunds_cents", 0),
            e.get("chargebacks_cents", 0),
        ))
    return batches


def flat_history_entries() -> list:
    """Twelve monthly batches of 1,000,000 net cents each (flat profile:
    seasonality index 0, avg 1,000,000/mo, pre-approval 1,250,000)."""
    return [
        {"processing_date": d, "gross_cents": 1_000_000}
        for d in FLAT_HISTORY_DATES
    ]


def seasonal_history_entries() -> list:
    """Seasonal profile: Sep 2025-Feb 2026 net 2,000,000; Mar-Aug 2026 net
    500,000 -> avg 1,250,000/mo, seasonality index 1.2, pre-approval selects
    the conservative variant (1,050,000)."""
    entries = [
        {"processing_date": f"2025-{m:02d}-01", "gross_cents": 2_000_000}
        for m in (9, 10, 11, 12)
    ]
    entries += [
        {"processing_date": f"2026-{m:02d}-01", "gross_cents": 2_000_000}
        for m in (1, 2)
    ]
    entries += [
        {"processing_date": f"2026-{m:02d}-01", "gross_cents": 500_000}
        for m in (3, 4, 5, 6, 7, 8)
    ]
    return entries


def migration_risk_history_entries() -> list:
    """Migration-risk profile: 10 monthly batches of 1,000,000
    (Sep 2025-Jun 2026), a 4,000,000 batch in the prior 30-day window
    (2026-07-15), and a 1,800,000-net batch with 100,000 chargebacks in the
    trailing window (2026-08-15)."""
    entries = [
        {"processing_date": d, "gross_cents": 1_000_000}
        for d in FLAT_HISTORY_DATES[:10]
    ]
    entries.append({"processing_date": "2026-07-15", "gross_cents": 4_000_000})
    entries.append({
        "processing_date": "2026-08-15",
        "gross_cents": 2_000_000,
        "refunds_cents": 100_000,
        "chargebacks_cents": 100_000,
    })
    return entries


# ---------------------------------------------------------------------------
# Tier 1/2: merchant state progression
# ---------------------------------------------------------------------------

def create_eligible_merchant(**overrides) -> dict:
    """Merchant with a full flat 12-month history, activated to ELIGIBLE."""
    merchant = create_merchant(**overrides)
    build_processing_history(merchant["id"], flat_history_entries())
    return get_success_data(api_client.activate_merchant(merchant["id"], ADMIN))


def create_eligible_merchant_with_history(entries: list, **overrides) -> dict:
    """Merchant with a caller-supplied history, activated to ELIGIBLE."""
    merchant = create_merchant(**overrides)
    build_processing_history(merchant["id"], entries)
    return get_success_data(api_client.activate_merchant(merchant["id"], ADMIN))


def create_seasonal_eligible_merchant(**overrides) -> dict:
    kwargs = {"legal_name": "Seasonal Co", "owner_name": "Sam Snow"}
    kwargs.update(overrides)
    return create_eligible_merchant_with_history(seasonal_history_entries(), **kwargs)


# ---------------------------------------------------------------------------
# Tier 3: offer lifecycle
# ---------------------------------------------------------------------------

def create_offer_for(merchant_id: str) -> dict:
    """Generate an offer (born DRAFT) for an ELIGIBLE merchant."""
    return get_success_data(api_client.create_offer(merchant_id, UNDERWRITER))


def create_issued_offer(merchant_id: str) -> dict:
    """Generate + issue an offer (OFFERED, 30-day window from the clock)."""
    offer = create_offer_for(merchant_id)
    return get_success_data(api_client.issue_offer(offer["id"], UNDERWRITER))


def accept_offer(merchant: dict, offer_id: str,
                 principal_cents: int = 500_000,
                 holdback_pct: float = HOLDBACK_10,
                 guarantee_cap_cents: int = 2_000_000,
                 guarantor_email: str = "g@x.com") -> dict:
    """Accept an offer as the merchant's owner; returns the ACCEPTED offer."""
    merchant = get_success_data(api_client.get_merchant(merchant["id"], ADMIN))
    payload = accept_offer_payload(
        merchant["version"],
        selected_principal_cents=principal_cents,
        accepted_holdback_pct=holdback_pct,
        guarantee_cap_cents=guarantee_cap_cents,
        guarantor_email=guarantor_email,
    )
    return get_success_data(
        api_client.accept_offer(offer_id, payload, make_merchant_owner_headers(merchant["id"]))
    )


# ---------------------------------------------------------------------------
# Tier 3/4: loan lifecycle
# ---------------------------------------------------------------------------

def get_loan(loan_id: str) -> dict:
    return get_success_data(api_client.get_loan(loan_id, ADMIN))


def get_loan_guarantor(loan_id: str) -> dict:
    guarantors = get_success_data(api_client.list_guarantors(loan_id, ADMIN))
    assert len(guarantors) == 1, f"Setup failed: expected 1 guarantor, got {len(guarantors)}"
    return guarantors[0]


def get_loan_disclosure(loan_id: str) -> dict:
    disclosures = get_success_data(api_client.list_disclosures(loan_id, ADMIN))
    assert len(disclosures) == 1, f"Setup failed: expected 1 disclosure, got {len(disclosures)}"
    return disclosures[0]


def acknowledge_guarantor(loan_id: str) -> dict:
    guarantor = get_loan_guarantor(loan_id)
    return get_success_data(api_client.acknowledge_guarantor(
        guarantor["id"], make_guarantor_principal_headers(guarantor["id"])))


def deliver_disclosure(loan_id: str) -> dict:
    disclosure = get_loan_disclosure(loan_id)
    return get_success_data(api_client.deliver_disclosure(disclosure["id"], SERVICER))


def acknowledge_disclosure(merchant_id: str, disclosure_id: str) -> dict:
    return get_success_data(api_client.acknowledge_disclosure(
        disclosure_id, make_merchant_owner_headers(merchant_id)))


def create_accepted_loan(merchant: dict = None,
                         principal_cents: int = 500_000,
                         holdback_pct: float = HOLDBACK_10,
                         guarantee_cap_cents: int = 2_000_000,
                         guarantor_email: str = "g@x.com",
                         **merchant_overrides) -> dict:
    """Flat eligible merchant + issued offer + acceptance.

    Returns a bundle dict: merchant, offer, loan, guarantor, disclosure.
    The loan is PENDING_ACK (non-mandate state) unless a mandate state_code
    is passed via merchant_overrides.
    """
    if merchant is None:
        merchant = create_eligible_merchant(**merchant_overrides)
    offer = create_issued_offer(merchant["id"])
    accepted = accept_offer(
        merchant, offer["id"],
        principal_cents=principal_cents,
        holdback_pct=holdback_pct,
        guarantee_cap_cents=guarantee_cap_cents,
        guarantor_email=guarantor_email,
    )
    loan = get_loan(accepted["accepted_loan_id"])
    return {
        "merchant": get_success_data(api_client.get_merchant(merchant["id"], ADMIN)),
        "offer": get_success_data(api_client.get_offer(offer["id"], UNDERWRITER)),
        "loan": loan,
        "guarantor": get_loan_guarantor(loan["id"]),
        "disclosure": get_loan_disclosure(loan["id"]),
    }


def create_active_loan(merchant: dict = None,
                       principal_cents: int = 500_000,
                       holdback_pct: float = HOLDBACK_10,
                       guarantee_cap_cents: int = 2_000_000,
                       guarantor_email: str = "g@x.com",
                       **merchant_overrides) -> dict:
    """Full loan-activation chain for a NON-mandate (e.g. TX) merchant:
    accept -> guarantor acknowledge -> disclosure deliver -> loan activate.
    Returns the same bundle as create_accepted_loan, with loan ACTIVE.
    """
    bundle = create_accepted_loan(
        merchant=merchant,
        principal_cents=principal_cents,
        holdback_pct=holdback_pct,
        guarantee_cap_cents=guarantee_cap_cents,
        guarantor_email=guarantor_email,
        **merchant_overrides,
    )
    loan_id = bundle["loan"]["id"]
    acknowledge_guarantor(loan_id)
    deliver_disclosure(loan_id)
    bundle["loan"] = get_success_data(api_client.activate_loan(loan_id, SERVICER))
    bundle["guarantor"] = get_loan_guarantor(loan_id)
    bundle["disclosure"] = get_loan_disclosure(loan_id)
    return bundle


# ---------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------

def post_sweep(loan_id: str, batch_id: str) -> dict:
    """Post a sweep with a fresh OCC version read; returns the APPLIED sweep."""
    loan = get_loan(loan_id)
    return get_success_data(api_client.create_sweep(
        loan_id, create_sweep_payload(batch_id, loan["version"]), SERVICER))


def sweep_batch_for(loan: dict, merchant_id: str, processing_date: str,
                    net_cents: int) -> dict:
    """Finalize a batch and sweep it against the loan. Returns the sweep."""
    batch = record_finalized_batch(merchant_id, processing_date, net_cents)
    return post_sweep(loan["id"], batch["id"])


# ---------------------------------------------------------------------------
# Catch-up payments
# ---------------------------------------------------------------------------

def initiate_and_settle_catch_up(bundle: dict, amount_cents: int) -> dict:
    """Merchant initiates a catch-up; servicer settles it. Returns APPLIED."""
    payment = get_success_data(api_client.create_catch_up(
        bundle["loan"]["id"], create_catch_up_payload(amount_cents),
        make_merchant_owner_headers(bundle["merchant"]["id"])))
    return get_success_data(api_client.settle_catch_up(payment["id"], SERVICER))


# ---------------------------------------------------------------------------
# Period evaluation / delinquency progression
# ---------------------------------------------------------------------------

def evaluate_period_at(loan_id: str, clock_iso: str) -> dict:
    """Advance the clock and close the loan's current period."""
    set_clock(clock_iso)
    return get_success_data(api_client.evaluate_period(loan_id, SERVICER))


def drive_loan_missed_periods(loan_id: str, count: int) -> dict:
    """Evaluate `count` consecutive periods with zero payments.

    Uses the standard 60-day clock schedule (periods close at
    2026-10-31, 2026-12-30, 2027-02-28, 2027-04-29). Returns the loan
    after the final evaluation.
    """
    assert 1 <= count <= len(PERIOD_END_CLOCKS)
    loan = None
    for i in range(count):
        loan = evaluate_period_at(loan_id, PERIOD_END_CLOCKS[i])
    return loan


def create_delinquent_loan(**kwargs) -> dict:
    """Active loan driven to DELINQUENT via two consecutive missed periods."""
    bundle = create_active_loan(**kwargs)
    bundle["loan"] = drive_loan_missed_periods(bundle["loan"]["id"], 2)
    return bundle


def create_defaulted_loan(**kwargs) -> dict:
    """Active loan driven to DEFAULTED via four consecutive missed periods;
    the default cascade auto-creates an EnforcementAction in DRAFT."""
    bundle = create_active_loan(**kwargs)
    bundle["loan"] = drive_loan_missed_periods(bundle["loan"]["id"], 4)
    actions = get_success_data(
        api_client.list_loan_enforcement_actions(bundle["loan"]["id"], ADMIN))
    assert len(actions) == 1, f"Setup failed: expected 1 enforcement action, got {len(actions)}"
    bundle["enforcement_action"] = actions[0]
    return bundle


# ---------------------------------------------------------------------------
# Repayment to terminal
# ---------------------------------------------------------------------------

def repay_loan_fully(bundle: dict, first_date: str = "2026-09-02",
                     first_net: int = 5_545_000,
                     second_date: str = "2026-09-03",
                     second_net: int = 10_000) -> dict:
    """Repay a 500,000 @ 0.10 loan (total 555,000) with two sweeps:
    554,500 then a clipped 500. Returns (first_sweep, second_sweep)."""
    loan_id = bundle["loan"]["id"]
    merchant_id = bundle["merchant"]["id"]
    first = sweep_batch_for(bundle["loan"], merchant_id, first_date, first_net)
    second = sweep_batch_for(get_loan(loan_id), merchant_id, second_date, second_net)
    return first, second


# ---------------------------------------------------------------------------
# Bank / sale lifecycle
# ---------------------------------------------------------------------------

OFFICER_A = "officer_a"
OFFICER_B = "officer_b"


def create_active_bank(discount_pct: float = 0.04, **overrides) -> dict:
    return get_success_data(api_client.create_bank(
        create_bank_payload(purchase_discount_pct=discount_pct, **overrides), ADMIN))


def create_quoted_sale(loan_id: str, bank_id: str,
                       officer: str = OFFICER_A) -> dict:
    return get_success_data(api_client.quote_sale(
        loan_id, quote_sale_payload(bank_id), make_bank_officer_headers(officer)))


def create_committed_sale(bundle: dict, bank: dict = None,
                          officer: str = OFFICER_A) -> dict:
    """Quote + commit a sale of the bundle's loan to a bank. Returns the
    COMMITTED sale."""
    if bank is None:
        bank = create_active_bank()
    sale = create_quoted_sale(bundle["loan"]["id"], bank["id"], officer=officer)
    return get_success_data(api_client.commit_sale(sale["id"], make_bank_officer_headers(officer)))
