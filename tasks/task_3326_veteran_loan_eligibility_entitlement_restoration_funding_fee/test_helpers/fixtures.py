"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before each test, so the database
is empty at test start).  All setup calls use the lenient ``get_success_data``
validator so a setup failure surfaces as a clear ``Setup failed`` error.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    STANDARD_CLOSE_DATE,
    STANDARD_DECISION_PAYLOAD,
    STANDARD_FIRST_PAYMENT,
    STANDARD_PERIOD_END,
    STANDARD_PERIOD_START,
)
from .factories import (
    create_appraiser_payload,
    create_coe_request_payload,
    create_close_payload,
    create_loan_payload,
    create_service_period_payload,
    create_underwriting_decision_payload,
    create_veteran_payload,
)
from .test_users import (
    LOAN_OFFICER,
    PROGRAM_ADMIN,
    UNDERWRITER,
    make_appraiser_headers,
    make_loan_officer_headers,
    make_underwriter_headers,
)


def _ok(resp, what: str):
    data = get_success_data(resp)
    assert data is not None, f"Setup failed: {what} -> {resp.status_code} {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 1/2: veteran + service + COE
# ---------------------------------------------------------------------------

def create_veteran(**overrides: Any) -> Dict[str, Any]:
    """Register a veteran; returns the Veteran resource."""
    payload = create_veteran_payload(**overrides)
    return _ok(api_client.create_veteran(payload), "create veteran")


def add_standard_service_period(veteran_id: str, **overrides: Any) -> Dict[str, Any]:
    """Attach the canonical 888-qualifying-day HONORABLE period."""
    payload = create_service_period_payload(
        start_date=STANDARD_PERIOD_START, end_date=STANDARD_PERIOD_END, **overrides
    )
    return _ok(api_client.create_service_period(veteran_id, payload), "add service period")


def setup_veteran_with_issued_coe(
    with_service_period: bool = True,
    veteran_overrides: Optional[Dict[str, Any]] = None,
    entitlement_code: str = "ERA_GULF",
) -> Dict[str, Any]:
    """Veteran + (optional) standard service period + ISSUED COE."""
    veteran = create_veteran(**(veteran_overrides or {}))
    if with_service_period:
        add_standard_service_period(veteran["id"])
    coe = _ok(
        api_client.create_coe_request(veteran["id"], create_coe_request_payload(
            entitlement_code=entitlement_code)),
        "create COE request",
    )
    issued = _ok(api_client.issue_coe(coe["id"]), "issue COE")
    return {"veteran": veteran, "coe": issued}


# ---------------------------------------------------------------------------
# Tier 2/3: loans
# ---------------------------------------------------------------------------

def setup_submitted_loan(
    loan_overrides: Optional[Dict[str, Any]] = None,
    veteran_overrides: Optional[Dict[str, Any]] = None,
    officer_user_id: str = "lo-1",
) -> Dict[str, Any]:
    """Veteran with ISSUED COE + one loan in (SUBMITTED, NOT_CLOSED)."""
    ctx = setup_veteran_with_issued_coe(veteran_overrides=veteran_overrides)
    headers = make_loan_officer_headers(officer_user_id)
    loan = _ok(
        api_client.create_loan(
            ctx["veteran"]["id"],
            create_loan_payload(ctx["coe"]["id"], **(loan_overrides or {})),
            headers=headers,
        ),
        "create loan",
    )
    return {**ctx, "loan": loan, "officer_user_id": officer_user_id}


def create_south_appraiser(name: str = "App South", **overrides: Any) -> Dict[str, Any]:
    return _ok(
        api_client.create_appraiser(create_appraiser_payload(name=name, **overrides)),
        "create appraiser",
    )


def order_assigned_appraisal(loan_id: str, appraiser: Dict[str, Any]) -> Dict[str, Any]:
    """Order an appraisal and require that the selector assigned it."""
    appraisal = _ok(api_client.create_appraisal_request(loan_id), "order appraisal")
    assert appraisal["status"] == "ASSIGNED", (
        f"Setup failed: appraisal not assigned (status {appraisal['status']})"
    )
    assert appraisal["appraiser_id"] == appraiser["id"], (
        f"Setup failed: appraisal assigned to {appraisal['appraiser_id']}, "
        f"expected {appraiser['id']}"
    )
    return appraisal


def submit_value_issued_report(appraisal_id: str, appraiser_id: str,
                               value_cents: int) -> Dict[str, Any]:
    return _ok(
        api_client.submit_appraisal_report(
            appraisal_id,
            {"outcome": "VALUE_ISSUED", "appraised_value_cents": value_cents},
            headers=make_appraiser_headers(appraiser_id),
        ),
        "submit VALUE_ISSUED report",
    )


def approve_underwriting(loan_id: str, decision_overrides: Optional[Dict[str, Any]] = None,
                         underwriter_user_id: str = "uw-1") -> Dict[str, Any]:
    return _ok(
        api_client.create_underwriting_decision(
            loan_id,
            create_underwriting_decision_payload(**(decision_overrides or {})),
            headers=make_underwriter_headers(underwriter_user_id),
        ),
        "underwriting decision",
    )


def setup_loan_with_value_issued_appraisal(
    price_cents: int = 30000000,
    appraisal_value_cents: Optional[int] = None,
    loan_overrides: Optional[Dict[str, Any]] = None,
    officer_user_id: str = "lo-1",
) -> Dict[str, Any]:
    """Submitted loan + SOUTH appraiser + VALUE_ISSUED appraisal at value >= price."""
    merged = {"purchase_price_cents": price_cents}
    merged.update(loan_overrides or {})
    ctx = setup_submitted_loan(loan_overrides=merged, officer_user_id=officer_user_id)
    appraiser = create_south_appraiser()
    appraisal = order_assigned_appraisal(ctx["loan"]["id"], appraiser)
    submit_value_issued_report(
        appraisal["id"], appraiser["id"], appraisal_value_cents or price_cents,
    )
    return {**ctx, "appraiser": appraiser, "appraisal": appraisal}


def setup_approved_loan(**kwargs: Any) -> Dict[str, Any]:
    """Loan in (APPROVED, NOT_CLOSED) with VALUE_ISSUED appraisal."""
    ctx = setup_loan_with_value_issued_appraisal(**kwargs)
    approve_underwriting(ctx["loan"]["id"])
    return ctx


def close_loan(loan_id: str, closing_date: str = STANDARD_CLOSE_DATE,
               first_payment_due_date: str = STANDARD_FIRST_PAYMENT,
               officer_user_id: str = "lo-1") -> Dict[str, Any]:
    return _ok(
        api_client.close_loan(
            loan_id,
            create_close_payload(
                closing_date=closing_date, first_payment_due_date=first_payment_due_date
            ),
            headers=make_loan_officer_headers(officer_user_id),
        ),
        "close loan",
    )


def setup_closed_loan(
    price_cents: int = 30000000,
    closing_date: str = STANDARD_CLOSE_DATE,
    first_payment_due_date: str = STANDARD_FIRST_PAYMENT,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Loan walked to (APPROVED, CLOSED); entitlement charged, fee collected."""
    ctx = setup_approved_loan(price_cents=price_cents, **kwargs)
    closed = close_loan(
        ctx["loan"]["id"], closing_date=closing_date,
        first_payment_due_date=first_payment_due_date,
        officer_user_id=ctx["officer_user_id"],
    )
    return {**ctx, "loan": closed}


def setup_paid_off_loan(payoff_type: str = "SALE", **kwargs: Any) -> Dict[str, Any]:
    """Loan walked to (APPROVED, PAID_IN_FULL)."""
    ctx = setup_closed_loan(**kwargs)
    paid = _ok(
        api_client.record_payoff(ctx["loan"]["id"], payoff_type),
        "record payoff",
    )
    return {**ctx, "loan": paid}


# ---------------------------------------------------------------------------
# Singleton readers (arrays of 0-1)
# ---------------------------------------------------------------------------

def get_entitlement_account(veteran_id: str) -> Dict[str, Any]:
    data = _ok(api_client.get_entitlement_account(veteran_id), "read entitlement account")
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: entitlement account list has {len(data) if isinstance(data, list) else '?'} entries"
    )
    return data[0]


def get_funding_fee_assessment(loan_id: str) -> Dict[str, Any]:
    data = _ok(api_client.list_funding_fee_assessments(loan_id), "read fee assessment")
    assert isinstance(data, list) and len(data) == 1, (
        "Setup failed: funding fee assessment list must have exactly one entry"
    )
    return data[0]


def get_occupancy_certificate(loan_id: str) -> Dict[str, Any]:
    data = _ok(api_client.list_occupancy_certificates(loan_id), "read occupancy certificate")
    assert isinstance(data, list) and len(data) == 1, (
        "Setup failed: occupancy certificate list must have exactly one entry"
    )
    return data[0]


def get_loan(loan_id: str) -> Dict[str, Any]:
    return _ok(api_client.get_loan(loan_id), "read loan")


def get_appraisal(appraisal_id: str) -> Dict[str, Any]:
    return _ok(api_client.get_appraisal(appraisal_id), "read appraisal")


def list_repairs(appraisal_id: str) -> List[Dict[str, Any]]:
    return _ok(api_client.list_repair_requirements(appraisal_id), "list repairs")


def list_refinance_requests(loan_id: str) -> List[Dict[str, Any]]:
    return _ok(api_client.list_refinance_requests(loan_id), "list refinance requests")


# ---------------------------------------------------------------------------
# Tier 4: repairs
# ---------------------------------------------------------------------------

def setup_loan_with_repairs_required(
    repairs: Optional[List[Dict[str, Any]]] = None,
    price_cents: int = 20000000,
) -> Dict[str, Any]:
    """Submitted loan + SOUTH appraiser + appraisal in REPAIRS_REQUIRED.

    Returns the context plus ``repairs`` (the created RepairRequirements).
    """
    ctx = setup_submitted_loan(loan_overrides={"purchase_price_cents": price_cents})
    appraiser = create_south_appraiser()
    appraisal = order_assigned_appraisal(ctx["loan"]["id"], appraiser)
    updated = _ok(
        api_client.submit_appraisal_report(
            appraisal["id"],
            {"outcome": "REPAIRS_REQUIRED",
             "repairs": repairs or [{"description": "Roof repair",
                                     "required_for_clearance": True}]},
            headers=make_appraiser_headers(appraiser["id"]),
        ),
        "submit REPAIRS_REQUIRED report",
    )
    created = list_repairs(appraisal["id"])
    return {**ctx, "appraiser": appraiser, "appraisal": updated, "repairs": created}


# ---------------------------------------------------------------------------
# Tier 4/5: refinance
# ---------------------------------------------------------------------------

def setup_closed_loan_with_refinance(
    clock_iso: Optional[str] = None,
    closing_date: str = "2026-01-15",
    first_payment_due_date: str = "2026-03-01",
    refinance_overrides: Optional[Dict[str, Any]] = None,
    price_cents: int = 20000000,
) -> Dict[str, Any]:
    """CLOSED loan + one SUBMITTED refinance request created at a valid version.

    Optionally advances the logical clock before the refinance is filed.
    """
    ctx = setup_closed_loan(
        price_cents=price_cents,
        closing_date=closing_date,
        first_payment_due_date=first_payment_due_date,
    )
    if clock_iso is not None:
        _ok(api_client.set_clock(clock_iso), "set logical clock")
    loan = get_loan(ctx["loan"]["id"])
    payload: Dict[str, Any] = {
        "refinance_type": "IRRRL",
        "new_rate_percent": 5.5,
        "new_rate_type": "FIXED",
        "flat_costs_cents": 150000,
        "expected_loan_version": loan["version"],
    }
    payload.update(refinance_overrides or {})
    refi = _ok(
        api_client.create_refinance_request(ctx["loan"]["id"], payload),
        "create refinance request",
    )
    return {**ctx, "loan": loan, "refinance": refi}
