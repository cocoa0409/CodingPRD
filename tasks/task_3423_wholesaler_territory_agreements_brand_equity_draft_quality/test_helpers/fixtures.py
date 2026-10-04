"""Composite setup helpers.

Each helper builds a multi-call precondition chain using only PRD-declared
endpoints, so tests can focus on assertions. Setup calls use the lenient
``get_success_data`` validator: a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_allocation_event_payload,
    create_draft_audit_payload,
    create_pos_grant_payload,
    create_promotion_payload,
    create_retail_account_payload,
    create_review_payload,
    create_territory_payload,
    create_transfer_payload,
    create_wholesaler_payload,
    critical_keg,
)
from .test_users import TEST_USERS, make_wholesaler_headers

ADMIN = TEST_USERS["admin_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _fail(step: str, resp) -> AssertionError:
    body = resp.text[:400] if hasattr(resp, "text") else repr(resp)
    return AssertionError(f"Setup failed at {step}: HTTP {resp.status_code} {body}")


# --- Tier 1/2: market-opening primitives -------------------------------------

def make_territory(name="Test Territory", state_code="TX") -> dict:
    resp = api_client.create_territory(
        create_territory_payload(name=name, state_code=state_code), ADMIN
    )
    if resp.status_code != 201:
        raise _fail("create_territory", resp)
    return get_success_data(resp)


def make_wholesaler(**overrides) -> dict:
    resp = api_client.create_wholesaler(create_wholesaler_payload(**overrides), ADMIN)
    if resp.status_code != 201:
        raise _fail("create_wholesaler", resp)
    return get_success_data(resp)


def make_agreement(territory_id: str, wholesaler_id: str, **overrides) -> dict:
    resp = api_client.create_agreement(
        create_agreement_payload(territory_id, wholesaler_id, **overrides), ADMIN
    )
    if resp.status_code != 201:
        raise _fail("create_agreement", resp)
    return get_success_data(resp)


def setup_awarded_territory(territory_name="Award Territory", state_code="TX",
                            wholesaler_overrides=None, agreement_overrides=None):
    """VACANT territory + APPLICANT wholesaler + ACTIVE agreement.

    Returns (territory, wholesaler, agreement) with the territory AWARDED and
    the wholesaler APPOINTED.
    """
    territory = make_territory(name=territory_name, state_code=state_code)
    wholesaler = make_wholesaler(**(wholesaler_overrides or {}))
    agreement = make_agreement(
        territory["id"], wholesaler["id"], **(agreement_overrides or {})
    )
    return territory, wholesaler, agreement


def make_account(wholesaler_id: str, name="Test Bar", state_code="TX", **overrides) -> dict:
    resp = api_client.create_retail_account(
        create_retail_account_payload(wholesaler_id, name=name, state_code=state_code,
                                      **overrides),
        ADMIN,
    )
    if resp.status_code != 201:
        raise _fail("create_retail_account", resp)
    return get_success_data(resp)


# --- Tier 3: draft-quality lifecycle ------------------------------------------

def post_audit(account_id: str, conducted_at: str, line_cleaning_last_at: str,
               kegs: list, expect_status: int = 201):
    """Record a draft audit; returns the raw response."""
    return api_client.create_draft_audit(
        create_draft_audit_payload(
            account_id,
            conducted_at=conducted_at,
            line_cleaning_last_at=line_cleaning_last_at,
            kegs=kegs,
        ),
        AUDITOR,
    )


def post_critical_audit(account_id: str, conducted_at: str = "2026-09-01T00:00:00Z",
                        keg_filled_at: str = "2026-05-03T00:00:00Z") -> dict:
    """Record an audit that computes CRITICAL_FAIL (one 121-day keg)."""
    resp = post_audit(
        account_id,
        conducted_at=conducted_at,
        line_cleaning_last_at="2026-08-25T00:00:00Z",
        kegs=[critical_keg(filled_at=keg_filled_at)],
    )
    if resp.status_code != 201:
        raise _fail("post_critical_audit", resp)
    return get_success_data(resp)


def setup_suspended_wholesaler(territory_name="Suspension Territory"):
    """Territory + appointed wholesaler + three accounts, each hit with a
    CRITICAL_FAIL audit, flipping the wholesaler APPOINTED -> SUSPENDED.

    Returns (wholesaler, agreement, [accounts]).
    """
    _, wholesaler, agreement = setup_awarded_territory(
        territory_name=territory_name,
        agreement_overrides={"brand_scope": ["BUD-LTD"]},
    )
    accounts = [
        make_account(wholesaler["id"], name=f"{territory_name} Bar {i}")
        for i in range(1, 4)
    ]
    for acct in accounts:
        post_critical_audit(acct["id"])
    return wholesaler, agreement, accounts


# --- Tier 3/4: allocation events ----------------------------------------------

def make_event(brand_code="BUD-LTD", total_qty_cases=400, **overrides) -> dict:
    resp = api_client.create_allocation_event(
        create_allocation_event_payload(
            brand_code=brand_code, total_qty_cases=total_qty_cases, **overrides
        ),
        ADMIN,
    )
    if resp.status_code != 201:
        raise _fail("create_allocation_event", resp)
    return get_success_data(resp)


def request_allocation(event_id: str, wholesaler_id: str, requested_qty_cases: int):
    """File a request as the wholesaler principal; returns the raw response."""
    return api_client.request_allocation(
        event_id,
        {"requested_qty_cases": requested_qty_cases},
        make_wholesaler_headers(wholesaler_id),
    )


def setup_locked_event_single_requester(total_qty_cases: int, requested_qty_cases: int,
                                        territory_name="Ledger Territory",
                                        tier="GOLD", brand_code="BUD-LTD"):
    """Awarded territory (scope includes brand), one request, locked event.

    Returns (wholesaler, agreement, event_dict_after_lock).
    """
    _, wholesaler, agreement = setup_awarded_territory(
        territory_name=territory_name,
        wholesaler_overrides={"tier": tier},
        agreement_overrides={"brand_scope": [brand_code]},
    )
    event = make_event(brand_code=brand_code, total_qty_cases=total_qty_cases)
    resp = request_allocation(event["id"], wholesaler["id"], requested_qty_cases)
    if resp.status_code != 201:
        raise _fail("request_allocation", resp)
    lock = api_client.lock_event(event["id"], ADMIN)
    if lock.status_code != 200:
        raise _fail("lock_event", lock)
    return wholesaler, agreement, get_success_data(lock)


# --- Tier 3: transfers ----------------------------------------------------------

def make_transfer(agreement_id: str, seller_id: str, buyer_id: str,
                  purchase_price_cents=1_000_000):
    resp = api_client.create_transfer(
        create_transfer_payload(agreement_id, buyer_id,
                                purchase_price_cents=purchase_price_cents),
        make_wholesaler_headers(seller_id),
    )
    if resp.status_code != 201:
        raise _fail("create_transfer", resp)
    return get_success_data(resp)


def qualification_review(transfer_id: str) -> dict:
    resp = api_client.qualification_review(transfer_id, COMPLIANCE)
    if resp.status_code != 200:
        raise _fail("qualification_review", resp)
    return get_success_data(resp)


def setup_qualified_transfer(rofr: bool = False, buyer_scores=80, seller_tier="SILVER"):
    """Territory awarded to a seller; clean APPLICANT buyer; transfer created
    and qualification-reviewed.

    With rofr=False the application ends QUALIFIED; with rofr=True the
    agreement names a ROFR holder and the application ends ROFR_OPEN.
    Returns a dict of the interesting entities.
    """
    seller = make_wholesaler(
        legal_name="Transfer Seller", tier=seller_tier,
        financial_capacity_score=70, warehouse_capacity_score=70,
        market_coverage_score=70)
    buyer = make_wholesaler(
        legal_name="Qualified Buyer",
        financial_capacity_score=buyer_scores,
        warehouse_capacity_score=buyer_scores,
        market_coverage_score=buyer_scores,
    )
    holder = None
    agreement_overrides = {}
    if rofr:
        holder = make_wholesaler(legal_name="ROFR Holder", tier="GOLD",
                                 financial_capacity_score=85,
                                 warehouse_capacity_score=85,
                                 market_coverage_score=85)
        agreement_overrides["rofr_holder_wholesaler_id"] = holder["id"]
    territory = make_territory(name="Transfer Territory")
    agreement = make_agreement(territory["id"], seller["id"], **agreement_overrides)
    transfer = make_transfer(agreement["id"], seller["id"], buyer["id"])
    reviewed = qualification_review(transfer["id"])
    return {
        "seller": seller,
        "buyer": buyer,
        "holder": holder,
        "agreement": agreement,
        "transfer": reviewed,
    }


# --- Tier 3/5: reviews & corrective plans -------------------------------------

def make_review(wholesaler_id: str, **overrides) -> dict:
    resp = api_client.create_review(create_review_payload(wholesaler_id, **overrides), ADMIN)
    if resp.status_code != 201:
        raise _fail("create_review", resp)
    return get_success_data(resp)


def list_plans(review_id: str) -> list:
    resp = api_client.list_review_plans(review_id, ADMIN)
    if resp.status_code != 200:
        raise _fail("list_review_plans", resp)
    return get_success_data(resp)


def setup_review_with_plan(territory_name="Plan Territory",
                           distribution_pct=50, share_pct=30,
                           weighting_profile="STANDARD"):
    """Awarded wholesaler whose review scores below the 70.00 corrective floor,
    spawning a PROPOSED plan. No audits, so freshness_index is 100.00.

    Returns (wholesaler, agreement, review, plan).
    """
    _, wholesaler, agreement = setup_awarded_territory(
        territory_name=territory_name,
        agreement_overrides={"weighting_profile": weighting_profile},
    )
    review = make_review(wholesaler["id"],
                         distribution_pct=distribution_pct, share_pct=share_pct)
    plans = list_plans(review["id"])
    if len(plans) != 1:
        raise AssertionError(
            f"Setup failed: expected exactly one auto-created plan, got {len(plans)}"
        )
    return wholesaler, agreement, review, plans[0]


# --- Tier 4: POS grants ---------------------------------------------------------

def issue_grant(account_id: str, value_cents: int, item_description="sign") -> dict:
    resp = api_client.create_pos_grant(
        create_pos_grant_payload(account_id, item_description=item_description,
                                 value_cents=value_cents),
        ADMIN,
    )
    if resp.status_code != 201:
        raise _fail("create_pos_grant", resp)
    return get_success_data(resp)


def setup_account_with_grants(grant_values, territory_name="POS Territory",
                              state_code="TX"):
    """Awarded wholesaler + account + N ISSUED grants of the given values.

    Returns (wholesaler, account, [grants]).
    """
    _, wholesaler, _ = setup_awarded_territory(territory_name=territory_name)
    account = make_account(wholesaler["id"], name=f"{territory_name} Bar",
                           state_code=state_code)
    grants = [
        issue_grant(account["id"], v, item_description=f"grant-{i}")
        for i, v in enumerate(grant_values)
    ]
    return wholesaler, account, grants


# --- Tier 2: promotions ---------------------------------------------------------

def make_promotion(brand_code="BUD", starts_at="2026-10-01T00:00:00Z",
                   ends_at="2026-11-01T00:00:00Z", **overrides) -> dict:
    resp = api_client.create_promotion(
        create_promotion_payload(brand_code=brand_code, starts_at=starts_at,
                                 ends_at=ends_at, **overrides),
        ADMIN,
    )
    if resp.status_code != 201:
        raise _fail("create_promotion", resp)
    return get_success_data(resp)
