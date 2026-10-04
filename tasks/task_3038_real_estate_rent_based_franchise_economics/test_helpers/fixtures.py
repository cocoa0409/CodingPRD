"""Composite setup helpers.

These helpers build multi-step preconditions (site -> operator -> capacity
review -> approve -> store -> agreement -> fee payment -> sublease -> open)
so tests can focus on assertions. Setup calls use get_success_data() so
failures surface as clear "Setup failed" errors.
"""
import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_site_payload,
    create_operator_payload,
    create_capacity_review_payload,
    create_store_payload,
    create_agreement_payload,
    create_sublease_payload,
    create_sales_report_payload,
    create_rent_charge_payload,
    create_reinvestment_obligation_payload,
    create_advertising_fund_payload,
    create_coop_assessment_payload,
    declare_default_payload,
)
from .test_users import (
    make_admin_headers,
    make_finance_headers,
    make_coop_headers,
    make_operator_headers,
)

ADMIN = make_admin_headers()
FIN = make_finance_headers()
COOP = make_coop_headers()


def _ok(resp, step: str):
    data = get_success_data(resp)
    if not isinstance(data, dict) or "id" not in data:
        pytest.fail(f"Setup failed at step '{step}': status={resp.status_code} body={resp.text}")
    return data


def set_clock(current_utc: str):
    """Advance the logical clock (FranchisorAdmin-only, PRD §2.5)."""
    resp = api_client.set_clock({"current_utc": current_utc}, ADMIN)
    assert resp.status_code == 200, f"Setup failed setting clock: {resp.text}"


def create_site(**overrides) -> dict:
    return _ok(api_client.create_site(create_site_payload(**overrides), ADMIN), "create_site")


def create_operator(**overrides) -> dict:
    return _ok(api_client.create_operator(create_operator_payload(**overrides), ADMIN), "create_operator")


def create_and_submit_capacity_review(operator_id: str, review_period: str = "2026") -> dict:
    review = _ok(
        api_client.create_capacity_review(create_capacity_review_payload(operator_id, review_period=review_period), FIN),
        "create_capacity_review",
    )
    return _ok(api_client.submit_capacity_review(review["id"], FIN), "submit_capacity_review")


def create_strong_approved_operator(**overrides) -> dict:
    """Operator graded STRONG (defaults: net worth 400M cents, op income 100M
    cents -> composite 100) and approved. Returns the operator dict."""
    overrides.setdefault("fy_net_worth_cents", 400_000_000)
    overrides.setdefault("fy_operating_income_cents", 100_000_000)
    op = create_operator(**overrides)
    create_and_submit_capacity_review(op["id"])
    op = _ok(api_client.approve_operator(op["id"], ADMIN), "approve_operator")
    return op


def get_operator_version(operator_id: str) -> int:
    op = _ok(api_client.get_operator(operator_id, FIN), "get_operator")
    return op["version"]


def get_sublease_version(sublease_id: str) -> int:
    sub = _ok(api_client.get_sublease(sublease_id, FIN), "get_sublease")
    return sub["version"]


def create_store_for(operator: dict, site: dict | None = None, **overrides) -> dict:
    """Create a SETUP store for an APPROVED operator; threads the OCC field."""
    site = site or create_site()
    version = get_operator_version(operator["id"])
    return _ok(
        api_client.create_store(
            create_store_payload(site["id"], operator["id"], version, **overrides), ADMIN
        ),
        "create_store",
    )


def activate_agreement(store: dict, operator: dict, **overrides) -> dict:
    """Draft -> submit -> record full fee payment -> ACTIVE agreement."""
    ag = _ok(
        api_client.create_agreement(create_agreement_payload(store["id"], operator["id"], **overrides), ADMIN),
        "create_agreement",
    )
    _ok(api_client.submit_agreement(ag["id"], ADMIN), "submit_agreement")
    return _ok(
        api_client.record_fee_payment(ag["id"], {"amount_cents": ag["initial_fee_cents"]}, FIN),
        "record_fee_payment",
    )


def activate_sublease(store: dict, operator: dict, **overrides) -> dict:
    """Draft -> activate -> ACTIVE sublease."""
    sub = _ok(
        api_client.create_sublease(create_sublease_payload(store["id"], operator["id"], **overrides), ADMIN),
        "create_sublease",
    )
    return _ok(api_client.activate_sublease(sub["id"], ADMIN), "activate_sublease")


def setup_open_store(operator_overrides=None, site_overrides=None,
                     agreement_overrides=None, sublease_overrides=None) -> dict:
    """Full happy path: STRONG approved operator + site + SETUP store +
    ACTIVE agreement + ACTIVE sublease + OPEN store.

    Returns dict with keys: site, operator, store, agreement, sublease.
    """
    site = create_site(**(site_overrides or {}))
    operator = create_strong_approved_operator(**(operator_overrides or {}))
    store = create_store_for(operator, site)
    agreement = activate_agreement(store, operator, **(agreement_overrides or {}))
    sublease = activate_sublease(store, operator, **(sublease_overrides or {}))
    store = _ok(api_client.open_store(store["id"], ADMIN), "open_store")
    return {
        "site": site,
        "operator": operator,
        "store": store,
        "agreement": agreement,
        "sublease": sublease,
    }


def deposit_escrow(operator_id: str, amount_cents: int) -> dict:
    return _ok(
        api_client.deposit_escrow(operator_id, {"amount_cents": amount_cents}, FIN),
        "deposit_escrow",
    )


def post_rent_charge(store_id: str, sublease_id: str,
                     billing_period: str = "2026",
                     period_start: str = "2026-04-01",
                     period_end: str = "2027-03-31") -> dict:
    """Post an annual rent charge, threading expected_sublease_version."""
    version = get_sublease_version(sublease_id)
    return _ok(
        api_client.create_rent_charge(
            create_rent_charge_payload(
                store_id, version,
                billing_period=billing_period,
                period_start=period_start,
                period_end=period_end,
            ),
            FIN,
        ),
        "create_rent_charge",
    )


def create_locked_sales_month(store: dict, operator: dict, period_month: str,
                              gross_sales_cents: int) -> dict:
    """Create + submit + billing-run one month, leaving the report LOCKED and
    returning the emitted FundAssessment."""
    headers = make_operator_headers(operator["id"])
    report = _ok(
        api_client.create_sales_report(
            create_sales_report_payload(store["id"], period_month, gross_sales_cents), headers
        ),
        "create_sales_report",
    )
    _ok(api_client.submit_sales_report(report["id"], headers), "submit_sales_report")
    return _ok(
        api_client.post_billing_run({"store_id": store["id"], "period_month": period_month}, FIN),
        "post_billing_run",
    )


def declare_store_default(ctx: dict, reason: str = "RENT_NONPAYMENT", cure_fee_cents: int = 15_000) -> dict:
    """Declare default on the ctx sublease; returns the DECLARED DefaultEvent."""
    return _ok(
        api_client.declare_default(
            ctx["sublease"]["id"], declare_default_payload(reason=reason, cure_fee_cents=cure_fee_cents), ADMIN
        ),
        "declare_default",
    )


def setup_defaulted_store(escrow_cents: int = 0, charge_amounts=None,
                          cure_fee_cents: int = 15_000) -> dict:
    """OPEN store + optional rent charges + declared default.

    charge_amounts is a list of (billing_period, period_start, period_end)
    triples to post before the default. Returns the setup ctx plus
    'default_event' and 'charges'.
    """
    ctx = setup_open_store()
    if escrow_cents:
        deposit_escrow(ctx["operator"]["id"], escrow_cents)
    charges = []
    for period, start, end in (charge_amounts or [("2026", "2026-04-01", "2027-03-31")]):
        charges.append(post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"], period, start, end))
    event = declare_store_default(ctx, cure_fee_cents=cure_fee_cents)
    ctx["charges"] = charges
    ctx["default_event"] = event
    return ctx


def setup_repossessed_store() -> dict:
    """Full unwind: OPEN store + one OPEN rent charge + a PENDING reinvestment
    obligation + an ASSESSED co-op assessment + declared default, then
    repossessed. Returns ctx with all affected entities."""
    ctx = setup_open_store()
    charge = post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"])
    obligation = _ok(
        api_client.create_reinvestment_obligation(
            create_reinvestment_obligation_payload(ctx["store"]["id"], ctx["agreement"]["id"]), ADMIN
        ),
        "create_reinvestment_obligation",
    )
    fund = _ok(
        api_client.create_advertising_fund(
            create_advertising_fund_payload(
                name="Local Coop", fund_type="LOCAL_COOP", admin_fee_rate=0.02, region_code="MW"
            ),
            ADMIN,
        ),
        "create_advertising_fund",
    )
    coop_assessment = _ok(
        api_client.create_coop_assessment(
            create_coop_assessment_payload(fund["id"], ctx["store"]["id"]), COOP
        ),
        "create_coop_assessment",
    )
    event = declare_store_default(ctx)
    repossessed = _ok(api_client.repossess_default(event["id"], ADMIN), "repossess_default")
    ctx.update({
        "charges": [charge],
        "obligation": obligation,
        "fund": fund,
        "coop_assessment": coop_assessment,
        "default_event": repossessed,
    })
    return ctx


def create_and_open_second_store(operator: dict, **overrides) -> dict:
    """Create another OPEN store for an already-approved operator."""
    site = create_site(**(overrides.pop("site_overrides", {}) or {}))
    store = create_store_for(operator, site, **overrides)
    activate_agreement(store, operator)
    activate_sublease(store, operator)
    return _ok(api_client.open_store(store["id"], ADMIN), "open_store")
