"""Composite setup helpers for the route-model domain (PRD §2.4, §3).

The test harness restarts the server before every test, so every test begins
against an empty database with the logical clock at 2026-09-01T00:00:00Z.
These helpers build multi-step preconditions using only PRD-declared
endpoints, threading distributor identity through every ownership-gated call
via make_distributor_headers (PRD §2.1). Setup calls use the lenient
get_success_data() so a setup failure surfaces as a clear setup error.

Composite setups return a context dict:
    {"bakery": Bakery, "territory": Territory, "distributor": Distributor,
     "agreement": RouteAgreement}            # plus "plan" when financed
"""
from datetime import date, timedelta
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_UTC,
    FINANCED_AMOUNT_CENTS,
    TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS,
    make_distributor_headers,
)

_ADMIN = TEST_USERS["company_admin_headers"]
_ROUTE_OPS = TEST_USERS["route_ops_manager_headers"]
_CREDIT = TEST_USERS["credit_analyst_headers"]


def add_days(iso_date: str, days: int) -> str:
    """Pure date arithmetic helper for window/boundary computations."""
    year, month, day = (int(part) for part in iso_date.split("-"))
    return (date(year, month, day) + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Tier 0: logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(current_utc: str) -> dict:
    """Move the logical clock; returns the echoed current_utc payload."""
    return get_success_data(
        api_client.set_clock(factories.clock_payload(current_utc), _ADMIN)
    )


def reset_clock_to_default() -> dict:
    return set_clock(DEFAULT_CLOCK_UTC)


# ---------------------------------------------------------------------------
# Tier 1: base entities and single transitions
# ---------------------------------------------------------------------------

def create_bakery(**overrides) -> dict:
    resp = api_client.create_bakery(factories.create_bakery_payload(**overrides),
                                    _ADMIN)
    return get_success_data(resp)


def create_territory(**overrides) -> dict:
    """Create a territory (starts AVAILABLE)."""
    resp = api_client.create_territory(
        factories.create_territory_payload(**overrides), _ADMIN
    )
    return get_success_data(resp)


def list_territory_for_sale(territory_id: str) -> dict:
    return get_success_data(api_client.list_territory_for_sale(territory_id, _ADMIN))


def create_listed_territory(**overrides) -> dict:
    """Create a territory and move it AVAILABLE -> LISTED."""
    territory = create_territory(**overrides)
    return list_territory_for_sale(territory["id"])


def create_distributor(**overrides) -> dict:
    """Create a distributor (PROSPECT / INDEPENDENT_CONTRACTOR / GOOD / 0)."""
    resp = api_client.create_distributor(
        factories.create_distributor_payload(**overrides), _ADMIN
    )
    return get_success_data(resp)


def get_distributor(distributor_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_distributor(distributor_id, headers or _ADMIN)
    )


def get_territory(territory_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_territory(territory_id, headers or _ADMIN)
    )


def create_production_day(bakery_id: str, date_: str,
                          capacity_override_units: Optional[int] = None) -> dict:
    """Create a production day (opens PLANNING)."""
    resp = api_client.create_production_day(
        bakery_id,
        factories.create_production_day_payload(date_, capacity_override_units),
        _ADMIN,
    )
    return get_success_data(resp)


def close_production_day(production_day_id: str) -> dict:
    return get_success_data(api_client.close_production_day(production_day_id, _ADMIN))


def list_production_days(bakery_id: str, params: Optional[dict] = None) -> list:
    return get_success_data(api_client.list_production_days(bakery_id, _ADMIN, params))


def find_production_day(bakery_id: str, date_: str) -> dict:
    """There is no single-day GET; locate the day through the date-filtered list."""
    days = list_production_days(bakery_id, {"date": date_})
    assert len(days) == 1, (
        f"expected exactly one production day for bakery {bakery_id} on {date_}, "
        f"got {len(days)}"
    )
    return days[0]


def create_draft_agreement(territory_id: str, distributor_id: str,
                           bakery_id: str, **overrides) -> dict:
    resp = api_client.create_agreement(
        factories.create_agreement_payload(
            territory_id, distributor_id, bakery_id, **overrides
        ),
        _ROUTE_OPS,
    )
    return get_success_data(resp)


def get_agreement(agreement_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_agreement(agreement_id, headers or _ADMIN)
    )


def activate_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.activate_agreement(agreement_id, _ROUTE_OPS))


def suspend_agreement(agreement_id: str, reason: str = "SERVICE_DEFAULT") -> dict:
    return get_success_data(
        api_client.suspend_agreement(
            agreement_id, factories.suspend_agreement_payload(reason), _ROUTE_OPS
        )
    )


def reinstate_agreement(agreement_id: str,
                        resolution: Optional[str] = None,
                        as_company_admin: bool = False) -> dict:
    headers = _ADMIN if as_company_admin else _ROUTE_OPS
    return get_success_data(
        api_client.reinstate_agreement(
            agreement_id, factories.reinstate_agreement_payload(resolution), headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: agreement contexts (cash and financed)
# ---------------------------------------------------------------------------

def setup_active_cash_agreement(
    clock: str = DEFAULT_CLOCK_UTC,
    credit_limit_cents: int = TEST_DEFAULTS["DISTRIBUTOR_CREDIT_LIMIT_CENTS"],
    area_code: str = TEST_DEFAULTS["TERRITORY_AREA_CODE"],
    **agreement_overrides,
) -> dict:
    """Bakery + LISTED territory + distributor + cash agreement walked to ACTIVE.

    Returns {"bakery", "territory", "distributor", "agreement"} with the
    distributor promoted to ACTIVE by activation.
    """
    set_clock(clock)
    bakery = create_bakery()
    territory = create_listed_territory(area_code=area_code)
    distributor = create_distributor(credit_limit_cents=credit_limit_cents)
    agreement = create_draft_agreement(
        territory["id"], distributor["id"], bakery["id"],
        financed_amount_cents=0, **agreement_overrides,
    )
    agreement = activate_agreement(agreement["id"])
    return {
        "bakery": bakery,
        "territory": territory,
        "distributor": get_distributor(distributor["id"]),
        "agreement": agreement,
    }


def create_financing_plan(agreement: dict, **overrides) -> dict:
    """Create a plan against a DRAFT agreement; OCC version defaults to the
    agreement dict's current version (re-read the agreement first if it may
    have advanced)."""
    expected = overrides.pop("expected_agreement_version", agreement["version"])
    resp = api_client.create_financing_plan(
        agreement["id"],
        factories.create_financing_plan_payload(expected, **overrides),
        _CREDIT,
    )
    return get_success_data(resp)


def disburse_financing_plan(plan_id: str) -> dict:
    return get_success_data(api_client.disburse_financing_plan(plan_id, _CREDIT))


def list_financing_plans(agreement_id: str,
                         params: Optional[dict] = None) -> list:
    return get_success_data(
        api_client.list_financing_plans(agreement_id, _CREDIT, params)
    )


def find_financing_plan(agreement_id: str, plan_id: str) -> dict:
    """There is no single-plan GET; locate the plan through the agreement list."""
    plans = list_financing_plans(agreement_id)
    matches = [p for p in plans if p["id"] == plan_id]
    assert len(matches) == 1, (
        f"plan {plan_id} not found under agreement {agreement_id}"
    )
    return matches[0]


def setup_active_financed_agreement(
    clock: str = DEFAULT_CLOCK_UTC,
    financed_amount_cents: int = FINANCED_AMOUNT_CENTS,
    **agreement_overrides,
) -> dict:
    """Bakery + LISTED territory + distributor + financed agreement walked to
    ACTIVE with a disbursed (ACTIVE) financing plan.

    Returns {"bakery", "territory", "distributor", "agreement", "plan"}.
    """
    set_clock(clock)
    bakery = create_bakery()
    territory = create_listed_territory()
    distributor = create_distributor()
    agreement = create_draft_agreement(
        territory["id"], distributor["id"], bakery["id"],
        financed_amount_cents=financed_amount_cents, **agreement_overrides,
    )
    plan = create_financing_plan(
        agreement, principal_cents=financed_amount_cents
    )
    plan = disburse_financing_plan(plan["id"])
    agreement = activate_agreement(agreement["id"])
    return {
        "bakery": bakery,
        "territory": territory,
        "distributor": get_distributor(distributor["id"]),
        "agreement": agreement,
        "plan": plan,
    }


# ---------------------------------------------------------------------------
# Tier 2: retail accounts and audits (PRD §3.5)
# ---------------------------------------------------------------------------

def create_retail_account(distributor: dict, as_role: str = "distributor",
                          **overrides) -> dict:
    """Create a retail account. as_role "distributor" threads the owning
    distributor's identity (PRD §2.1); "route_ops" uses the RouteOpsManager."""
    if as_role == "distributor":
        headers = make_distributor_headers(distributor["id"])
    elif as_role == "route_ops":
        headers = _ROUTE_OPS
    else:
        raise ValueError(f"unknown as_role {as_role!r}")
    resp = api_client.create_retail_account(
        distributor["id"], factories.create_retail_account_payload(**overrides),
        headers,
    )
    return get_success_data(resp)


def list_retail_accounts(distributor_id: str,
                         params: Optional[dict] = None) -> list:
    return get_success_data(
        api_client.list_retail_accounts(distributor_id, _ADMIN, params)
    )


def post_audit(account_id: str, audit_date: str, shelf_stock_score: int,
               rotation_score: int, display_score: int) -> dict:
    """Post a service audit; returns the updated RetailAccount."""
    resp = api_client.post_audit(
        account_id,
        factories.audit_payload(
            audit_date, shelf_stock_score, rotation_score, display_score
        ),
        _ROUTE_OPS,
    )
    return get_success_data(resp)


def post_violation_audit(account_id: str, audit_date: str,
                         failing_component: str = "shelf_stock_score") -> dict:
    """Post an audit that is a component-level violation (one score < 70)."""
    scores = {"shelf_stock_score": 90, "rotation_score": 90, "display_score": 90}
    scores[failing_component] = 60
    return post_audit(account_id, audit_date, scores["shelf_stock_score"],
                      scores["rotation_score"], scores["display_score"])


def post_passing_audit(account_id: str, audit_date: str,
                       scores: tuple = (80, 90, 90)) -> dict:
    return post_audit(account_id, audit_date, scores[0], scores[1], scores[2])


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------

def create_order(distributor: dict, delivery_date: str, lines: List[dict]) -> dict:
    """Create a DRAFT order as the owning distributor."""
    resp = api_client.create_order(
        distributor["id"],
        factories.create_order_payload(delivery_date, lines),
        make_distributor_headers(distributor["id"]),
    )
    return get_success_data(resp)


def submit_order(order: dict) -> dict:
    return get_success_data(
        api_client.submit_order(
            order["id"], make_distributor_headers(order["distributor_id"])
        )
    )


def confirm_order(order: dict, production_day: Optional[dict] = None,
                  expected_version: Optional[int] = None) -> dict:
    """Confirm a SUBMITTED order; OCC version defaults to the given day's
    current version."""
    if expected_version is None:
        assert production_day is not None, "pass production_day or expected_version"
        expected_version = production_day["version"]
    resp = api_client.confirm_order(
        order["id"], factories.confirm_order_payload(expected_version), _ROUTE_OPS
    )
    return get_success_data(resp)


def cancel_order(order: dict) -> dict:
    return get_success_data(
        api_client.cancel_order(
            order["id"], make_distributor_headers(order["distributor_id"])
        )
    )


def record_delivery(order: dict, delivered_lines: List[dict]) -> dict:
    return get_success_data(
        api_client.record_delivery(
            order["id"], factories.record_delivery_payload(delivered_lines),
            make_distributor_headers(order["distributor_id"]),
        )
    )


def reconcile_order(order: dict, verified_lines: List[dict]) -> dict:
    return get_success_data(
        api_client.reconcile_order(
            order["id"], factories.reconcile_payload(verified_lines), _ROUTE_OPS
        )
    )


def list_orders(distributor_id: str, params: Optional[dict] = None,
                headers: Optional[dict] = None) -> list:
    return get_success_data(
        api_client.list_orders(
            distributor_id,
            headers or make_distributor_headers(distributor_id),
            params,
        )
    )


def setup_confirmed_order(ctx: dict, delivery_date: str, lines: List[dict],
                          capacity_override_units: Optional[int] = None) -> tuple:
    """Production day for delivery_date + a CONFIRMED order against it.
    Returns (production_day, order). The day is left PLANNING."""
    day = create_production_day(
        ctx["bakery"]["id"], delivery_date, capacity_override_units
    )
    order = create_order(ctx["distributor"], delivery_date, lines)
    order = submit_order(order)
    order = confirm_order(order, day)
    return day, order


def setup_delivered_order(ctx: dict, delivery_date: str, lines: List[dict],
                          delivered_lines: Optional[List[dict]] = None,
                          close_clock: Optional[str] = None,
                          capacity_override_units: Optional[int] = None) -> tuple:
    """Confirmed order whose production day is then CLOSED (clock advanced to
    the delivery date) and whose delivery is recorded. Returns
    (production_day, order) with the order DELIVERED and the charge posted to
    the trade ledger. close_clock defaults to 08:00 on the delivery date."""
    day, order = setup_confirmed_order(
        ctx, delivery_date, lines, capacity_override_units
    )
    set_clock(close_clock or f"{delivery_date}T08:00:00Z")
    day = close_production_day(day["id"])
    order = record_delivery(order, delivered_lines or lines)
    return day, order


# ---------------------------------------------------------------------------
# Tier 3/4: stale return claims (PRD §3.6)
# ---------------------------------------------------------------------------

def create_stale_claim(distributor: dict, items: List[dict]) -> dict:
    resp = api_client.create_stale_claim(
        distributor["id"], factories.create_claim_payload(items),
        make_distributor_headers(distributor["id"]),
    )
    return get_success_data(resp)


def decide_claim(claim_id: str, decision: str,
                 decision_note: Optional[str] = None) -> dict:
    resp = api_client.decide_claim(
        claim_id, factories.decide_claim_payload(decision, decision_note),
        _ROUTE_OPS,
    )
    return get_success_data(resp)


def resubmit_claim(claim: dict, items: List[dict]) -> dict:
    resp = api_client.resubmit_claim(
        claim["id"], factories.resubmit_claim_payload(items),
        make_distributor_headers(claim["distributor_id"]),
    )
    return get_success_data(resp)


def issue_credit(claim_id: str) -> dict:
    return get_success_data(api_client.issue_credit(claim_id, _CREDIT))


def list_stale_claims(distributor_id: str,
                      params: Optional[dict] = None) -> list:
    return get_success_data(
        api_client.list_stale_claims(distributor_id, _ADMIN, params)
    )


def setup_submitted_claim(ctx: dict, delivery_date: str, order_lines: List[dict],
                          claim_items: List[dict], file_clock: str,
                          delivered_lines: Optional[List[dict]] = None) -> tuple:
    """Delivered order, then a SUBMITTED stale claim filed at file_clock.
    Returns (production_day, order, claim)."""
    day, order = setup_delivered_order(
        ctx, delivery_date, order_lines, delivered_lines
    )
    set_clock(file_clock)
    claim = create_stale_claim(ctx["distributor"], claim_items)
    return day, order, claim


def setup_approved_claim(ctx: dict, delivery_date: str, order_lines: List[dict],
                         claim_items: List[dict], file_clock: str,
                         delivered_lines: Optional[List[dict]] = None) -> tuple:
    """SUBMITTED claim approved by route ops (approved_credit_cents frozen).
    Returns (production_day, order, claim) with the claim APPROVED."""
    day, order, claim = setup_submitted_claim(
        ctx, delivery_date, order_lines, claim_items, file_clock, delivered_lines
    )
    claim = decide_claim(claim["id"], "APPROVE")
    return day, order, claim


# ---------------------------------------------------------------------------
# Tier 5: exit and settlement pipeline (PRD §3.8)
# ---------------------------------------------------------------------------

def exit_agreement(agreement_id: str, mode: str = "VOLUNTARY") -> dict:
    return get_success_data(
        api_client.exit_agreement(
            agreement_id, factories.exit_agreement_payload(mode), _ROUTE_OPS
        )
    )


def list_transfers(agreement_id: str, params: Optional[dict] = None) -> list:
    return get_success_data(
        api_client.list_transfers(agreement_id, _CREDIT, params)
    )


def get_agreement_transfer(agreement_id: str) -> Optional[dict]:
    """An agreement's transfer list holds at most one row (PRD §3.8)."""
    transfers = list_transfers(agreement_id)
    assert len(transfers) <= 1, (
        f"agreement {agreement_id} should have at most one transfer, "
        f"got {len(transfers)}"
    )
    return transfers[0] if transfers else None


def settle_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.settle_transfer(transfer_id, _CREDIT))


def setup_exiting_agreement(financed: bool = False, mode: str = "VOLUNTARY",
                            exit_clock: str = "2026-09-08T10:00:00Z",
                            **setup_overrides) -> dict:
    """Agreement (cash or financed) walked to EXITING with a PENDING transfer.
    Returns the context dict with an added "transfer" key."""
    if financed:
        ctx = setup_active_financed_agreement(**setup_overrides)
    else:
        ctx = setup_active_cash_agreement(**setup_overrides)
    set_clock(exit_clock)
    ctx["agreement"] = exit_agreement(ctx["agreement"]["id"], mode)
    transfer = get_agreement_transfer(ctx["agreement"]["id"])
    assert transfer is not None, "exit must create a PENDING territory transfer"
    ctx["transfer"] = transfer
    return ctx


def setup_settled_transfer(financed: bool = False, mode: str = "VOLUNTARY",
                           exit_clock: str = "2026-09-08T10:00:00Z",
                           **setup_overrides) -> dict:
    """Full exit pipeline: agreement EXITED, transfer SETTLED, territory back
    to AVAILABLE. Returns the context dict with "transfer" SETTLED."""
    ctx = setup_exiting_agreement(
        financed=financed, mode=mode, exit_clock=exit_clock, **setup_overrides
    )
    ctx["transfer"] = settle_transfer(ctx["transfer"]["id"])
    ctx["agreement"] = get_agreement(ctx["agreement"]["id"])
    ctx["territory"] = get_territory(ctx["territory"]["id"])
    ctx["distributor"] = get_distributor(ctx["distributor"]["id"])
    return ctx
