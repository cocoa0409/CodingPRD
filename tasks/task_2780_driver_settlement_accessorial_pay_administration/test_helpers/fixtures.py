"""
Composite setup helpers.

Every test starts against an empty database with the logical clock at its epoch,
so any scenario deeper than a single create has to be built up call by call.
These helpers do that building, using get_success_data() so that a setup step is
only checked for having succeeded, never for the exact status code — the
assertions that matter belong in the test body.

Money passed through these helpers is always an integer number of cents.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import CLOCK_EPOCH
from .test_users import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    CLERK_HEADERS,
)
from .types import (
    AccessorialType,
    AdvanceType,
    DriverType,
    EmploymentStatus,
    MileageGuide,
    PerDiemMethod,
)

# The reference movement used across the suite: the practical guide reports 780
# miles and the household-goods guide 742 for the same haul, billed at 180,000
# cents of linehaul revenue.
REF_PRACTICAL_MILES = 780
REF_HHG_MILES = 742
REF_REVENUE_CENTS = 180000
REF_PER_MILE_RATE = 58
REF_REVENUE_BPS = 2500

# Reference instants on the logical clock.
TS_DISPATCH = "2026-08-03T08:00:00Z"
TS_DELIVER = "2026-08-04T18:00:00Z"
TS_SETTLE = "2026-08-10T09:00:00Z"
PERIOD_START = "2026-08-03T00:00:00Z"
PERIOD_END = "2026-08-10T00:00:00Z"


# ── Logical clock ────────────────────────────────────
def set_clock(instant: str, headers: Optional[Dict[str, str]] = None) -> None:
    """Move the logical clock to the given instant."""
    response = api_client.set_clock(instant, headers or ADMIN_HEADERS)
    get_success_data(response)


def reset_clock(headers: Optional[Dict[str, str]] = None) -> None:
    """Return the logical clock to the instant the server starts from."""
    set_clock(CLOCK_EPOCH, headers)


# ── Pay packages ─────────────────────────────────────
def create_package(
    components: Optional[List[Dict[str, Any]]] = None,
    activate: bool = False,
    **package_overrides: Any,
) -> Dict[str, Any]:
    """
    Create a pay package, append the given components, and optionally activate it.
    Returns the package as last read from the server.
    """
    payload = f.pay_package_payload(**package_overrides)
    package = get_success_data(api_client.create_pay_package(payload, ADMIN_HEADERS))
    for component in components or []:
        get_success_data(api_client.add_component(package["id"], component, ADMIN_HEADERS))
    if activate:
        get_success_data(api_client.activate_pay_package(package["id"], ADMIN_HEADERS))
    return get_success_data(api_client.get_pay_package(package["id"], ADMIN_HEADERS))


def linehaul_components(
    per_mile_rate: int = REF_PER_MILE_RATE, revenue_bps: int = REF_REVENUE_BPS
) -> List[Dict[str, Any]]:
    """The two competing linehaul legs: a per-mile component and a revenue share."""
    return [
        f.per_mile_component(rate_value=per_mile_rate, sequence=1),
        f.revenue_percent_component(rate_value=revenue_bps, sequence=2),
    ]


def active_package(
    driver_type: str = DriverType.LEASED_OPERATOR,
    mileage_guide: str = MileageGuide.PRACTICAL,
    per_diem_method: str = PerDiemMethod.DAY_BASED,
    per_mile_rate: int = REF_PER_MILE_RATE,
    revenue_bps: Optional[int] = REF_REVENUE_BPS,
    components: Optional[List[Dict[str, Any]]] = None,
    escrow_required: bool = False,
    escrow_target_cents: Optional[int] = None,
    escrow_monthly_deduction_cents: Optional[int] = None,
    **package_overrides: Any,
) -> Dict[str, Any]:
    """An ACTIVE package carrying at least one linehaul-capable component."""
    if components is None:
        components = [f.per_mile_component(rate_value=per_mile_rate, sequence=1)]
        if revenue_bps is not None:
            components.append(f.revenue_percent_component(rate_value=revenue_bps, sequence=2))
    overrides: Dict[str, Any] = dict(package_overrides)
    if escrow_required:
        overrides["escrow_required"] = True
        overrides["escrow_target_cents"] = (
            250000 if escrow_target_cents is None else escrow_target_cents
        )
        overrides["escrow_monthly_deduction_cents"] = (
            40000 if escrow_monthly_deduction_cents is None else escrow_monthly_deduction_cents
        )
    else:
        overrides["escrow_required"] = False
        if escrow_target_cents is not None:
            overrides["escrow_target_cents"] = escrow_target_cents
        if escrow_monthly_deduction_cents is not None:
            overrides["escrow_monthly_deduction_cents"] = escrow_monthly_deduction_cents
    return create_package(
        components=components,
        activate=True,
        driver_type=driver_type,
        mileage_guide=mileage_guide,
        per_diem_method=per_diem_method,
        **overrides,
    )


# ── Drivers ──────────────────────────────────────────
def create_driver(
    driver_type: str = DriverType.LEASED_OPERATOR,
    per_diem_elected: bool = True,
    **driver_overrides: Any,
) -> Dict[str, Any]:
    """Register a driver; it starts ONBOARDING with no package."""
    payload = f.driver_payload(
        driver_type=driver_type, per_diem_elected=per_diem_elected, **driver_overrides
    )
    return get_success_data(api_client.create_driver(payload, ADMIN_HEADERS))


def active_driver(
    package_id: str,
    driver_type: str = DriverType.LEASED_OPERATOR,
    per_diem_elected: bool = True,
    **driver_overrides: Any,
) -> Dict[str, Any]:
    """
    A driver assigned the given ACTIVE package and driven ONBOARDING -> ACTIVE, so
    that loads, claims, advances and settlements may be booked against it.
    """
    driver = create_driver(
        driver_type=driver_type, per_diem_elected=per_diem_elected, **driver_overrides
    )
    get_success_data(
        api_client.assign_pay_package(
            driver["id"], f.assign_package_payload(package_id), ADMIN_HEADERS
        )
    )
    get_success_data(
        api_client.set_driver_status(
            driver["id"], f.driver_status_payload(EmploymentStatus.ACTIVE), ADMIN_HEADERS
        )
    )
    return read_driver(driver["id"])


def read_driver(driver_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_driver(driver_id, ADMIN_HEADERS))


def set_driver_status(driver_id: str, new_status: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_driver_status(
            driver_id, f.driver_status_payload(new_status, **overrides), ADMIN_HEADERS
        )
    )


# ── Loads ────────────────────────────────────────────
def tender_load(
    driver_id: str,
    practical_miles: int = REF_PRACTICAL_MILES,
    hhg_miles: int = REF_HHG_MILES,
    linehaul_revenue_cents: int = REF_REVENUE_CENTS,
    **load_overrides: Any,
) -> Dict[str, Any]:
    payload = f.load_payload(
        driver_id,
        linehaul_revenue_cents=linehaul_revenue_cents,
        practical_miles=practical_miles,
        hhg_miles=hhg_miles,
        **load_overrides,
    )
    return get_success_data(api_client.create_load(payload, ADMIN_HEADERS))


def read_load(load_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_load(load_id, ADMIN_HEADERS))


def dispatch(load_id: str, dispatched_at: Optional[str] = None) -> Dict[str, Any]:
    payload = f.dispatch_payload() if dispatched_at is None else f.dispatch_payload(dispatched_at)
    return get_success_data(api_client.dispatch_load(load_id, payload, ADMIN_HEADERS))


def deliver(
    load_id: str,
    delivered_at: Optional[str] = None,
    hours_worked_minutes: Optional[int] = None,
    stop_count: Optional[int] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if delivered_at is not None:
        kwargs["delivered_at"] = delivered_at
    if hours_worked_minutes is not None:
        kwargs["hours_worked_minutes"] = hours_worked_minutes
    if stop_count is not None:
        kwargs["stop_count"] = stop_count
    return get_success_data(
        api_client.deliver_load(load_id, f.deliver_payload(**kwargs), ADMIN_HEADERS)
    )


def delivered_load(
    driver_id: str,
    dispatched_at: str = TS_DISPATCH,
    delivered_at: str = TS_DELIVER,
    hours_worked_minutes: Optional[int] = None,
    stop_count_on_delivery: Optional[int] = None,
    **load_overrides: Any,
) -> Dict[str, Any]:
    """
    Tender, dispatch and deliver one load, moving the logical clock forward to each
    step so that dispatched_at and delivered_at are stamped from it. The returned
    load carries its computed paid miles and linehaul pay.
    """
    load = tender_load(driver_id, **load_overrides)
    set_clock(dispatched_at)
    dispatch(load["id"])
    set_clock(delivered_at)
    deliver(
        load["id"],
        hours_worked_minutes=hours_worked_minutes,
        stop_count=stop_count_on_delivery,
    )
    return read_load(load["id"])


# ── Accessorial claims ───────────────────────────────
def submit_claim(
    load_id: str,
    driver_id: str,
    accessorial_type: str,
    start_at: str,
    end_at: str,
    document_ref: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if document_ref is not None:
        kwargs["document_ref"] = document_ref
    payload = f.accessorial_claim_payload(
        load_id, driver_id, accessorial_type, start_at, end_at, **kwargs
    )
    return get_success_data(
        api_client.create_accessorial_claim(payload, headers or ADMIN_HEADERS)
    )


def approved_claim(
    load_id: str,
    driver_id: str,
    accessorial_type: str,
    start_at: str,
    end_at: str,
    document_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """A claim submitted and then approved, so that it is priced and sweepable."""
    if document_ref is None and accessorial_type in (
        AccessorialType.DETENTION,
        AccessorialType.TARPING,
        AccessorialType.BREAKDOWN,
    ):
        document_ref = "DOC-ACC-1"
    claim = submit_claim(
        load_id, driver_id, accessorial_type, start_at, end_at, document_ref
    )
    return get_success_data(
        api_client.approve_accessorial_claim(claim["id"], ADMIN_HEADERS)
    )


def read_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_accessorial_claim(claim_id, ADMIN_HEADERS))


# ── Advances ─────────────────────────────────────────
def issue_advance(
    driver_id: str,
    amount_cents: int,
    advance_type: str = AdvanceType.CASH_ADVANCE,
    installment_cents: Optional[int] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if installment_cents is not None:
        kwargs["installment_cents"] = installment_cents
    payload = f.advance_payload(driver_id, amount_cents, advance_type, **kwargs)
    return get_success_data(api_client.create_advance(payload, ADMIN_HEADERS))


def read_advance(advance_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_advance(advance_id, ADMIN_HEADERS))


# ── Settlements ──────────────────────────────────────
def open_settlement(
    driver_id: str,
    period_start: str = PERIOD_START,
    period_end: str = PERIOD_END,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = f.settlement_payload(driver_id, period_start, period_end)
    return get_success_data(
        api_client.create_settlement(payload, headers or ADMIN_HEADERS)
    )


def read_settlement(settlement_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_settlement(settlement_id, ADMIN_HEADERS))


def read_settlement_lines(settlement_id: str, **params: Any) -> List[Dict[str, Any]]:
    response = api_client.list_settlement_lines(
        settlement_id, ADMIN_HEADERS, params=params or None
    )
    return get_success_data(response)


def prepare(settlement_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Prepare a settlement. The preparer defaults to the settlement clerk."""
    return get_success_data(
        api_client.prepare_settlement(settlement_id, None, headers or CLERK_HEADERS)
    )


def approve(settlement_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Approve a prepared settlement with an identity that is not the preparer."""
    return get_success_data(
        api_client.approve_settlement(settlement_id, headers or APPROVER_HEADERS)
    )


def pay(
    settlement_id: str,
    payment_reference: str = "ACH-SETTLEMENT-1",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record payment with an identity that is not the approver."""
    return get_success_data(
        api_client.pay_settlement(
            settlement_id, f.pay_payload(payment_reference), headers or ADMIN_HEADERS
        )
    )


def prepared_settlement(
    driver_id: str,
    period_start: str = PERIOD_START,
    period_end: str = PERIOD_END,
    prepared_at: Optional[str] = TS_SETTLE,
) -> Dict[str, Any]:
    """A settlement opened over the period and swept into PREPARED by the clerk."""
    if prepared_at is not None:
        set_clock(prepared_at)
    settlement = open_settlement(driver_id, period_start, period_end)
    prepare(settlement["id"])
    return read_settlement(settlement["id"])


def approved_settlement(
    driver_id: str,
    period_start: str = PERIOD_START,
    period_end: str = PERIOD_END,
    prepared_at: Optional[str] = TS_SETTLE,
) -> Dict[str, Any]:
    """A settlement carried through prepare and approve by two distinct identities."""
    settlement = prepared_settlement(driver_id, period_start, period_end, prepared_at)
    approve(settlement["id"])
    return read_settlement(settlement["id"])


def paid_settlement(
    driver_id: str,
    period_start: str = PERIOD_START,
    period_end: str = PERIOD_END,
    prepared_at: Optional[str] = TS_SETTLE,
    payment_reference: str = "ACH-SETTLEMENT-1",
) -> Dict[str, Any]:
    """
    A settlement carried the whole way through prepare, approve and pay, each step
    by a different identity so that no segregation-of-duties rule is tripped.
    """
    settlement = approved_settlement(driver_id, period_start, period_end, prepared_at)
    pay(settlement["id"], payment_reference)
    return read_settlement(settlement["id"])


# ── Disputes and corrections ─────────────────────────
def file_mileage_dispute(
    driver_id: str,
    load_id: str,
    claimed_guide: str,
    claimed_miles: int,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.mileage_dispute_payload(
        driver_id, load_id, claimed_guide, claimed_miles, **overrides
    )
    return get_success_data(api_client.create_dispute(payload, headers or ADMIN_HEADERS))


def file_pay_dispute(
    driver_id: str,
    settlement_id: str,
    claimed_amount_cents: int,
    disputed_line_type: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.pay_dispute_payload(
        driver_id, settlement_id, claimed_amount_cents, disputed_line_type, **overrides
    )
    return get_success_data(api_client.create_dispute(payload, headers or ADMIN_HEADERS))


def review(dispute_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.review_dispute(dispute_id, headers or CLERK_HEADERS)
    )


def resolve(
    dispute_id: str,
    outcome: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Resolve a dispute with an identity that is not the reviewer."""
    return get_success_data(
        api_client.resolve_dispute(
            dispute_id, f.resolve_payload(outcome, **overrides), headers or APPROVER_HEADERS
        )
    )


def read_dispute(dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_dispute(dispute_id, ADMIN_HEADERS))


def list_corrections(**params: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_retro_corrections(ADMIN_HEADERS, params=params or None)
    )


def read_correction(correction_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_retro_correction(correction_id, ADMIN_HEADERS))


# ── Escrow ───────────────────────────────────────────
def record_escrow_deduction(
    driver_id: str,
    amount_cents: int,
    expected_driver_version: int,
    reason_code: Optional[str] = None,
    document_ref: str = "DOC-ESCROW-1",
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if reason_code is not None:
        kwargs["reason_code"] = reason_code
    payload = f.escrow_deduction_payload(
        amount_cents, expected_driver_version, document_ref=document_ref, **kwargs
    )
    return get_success_data(
        api_client.create_escrow_deduction(driver_id, payload, ADMIN_HEADERS)
    )


def list_escrow_transactions(**params: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_escrow_transactions(ADMIN_HEADERS, params=params or None)
    )


# ── Whole-scenario bundles ───────────────────────────
def leased_operator_environment(
    per_diem_method: str = PerDiemMethod.DAY_BASED,
    mileage_guide: str = MileageGuide.PRACTICAL,
    per_diem_elected: bool = True,
    escrow_required: bool = False,
    **package_overrides: Any,
) -> Dict[str, Any]:
    """
    The reference environment: an ACTIVE leased-operator package with both linehaul
    legs, an ACTIVE driver on it, and one delivered load over the reference period.
    """
    package = active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=mileage_guide,
        per_diem_method=per_diem_method,
        escrow_required=escrow_required,
        **package_overrides,
    )
    driver = active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=per_diem_elected,
    )
    load = delivered_load(driver["id"])
    return {
        "package": package,
        "driver": read_driver(driver["id"]),
        "load": load,
    }
