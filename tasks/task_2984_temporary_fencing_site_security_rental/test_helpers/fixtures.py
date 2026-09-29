"""Composite state builders and pytest fixtures.

Every builder drives the real endpoints of PRD §4 in the order the PRD
prescribes, and uses the lenient ``get_success_data`` validator so that a broken
setup step reports its own error identifier rather than an opaque KeyError.

Because a quote supersedes the open quotes of *its own jobsite* (PRD §3.2),
every builder that needs an independent contract takes its own jobsite, and
every quote creation re-reads the jobsite's live ``version`` first so that the
non-optional ``expected_jobsite_version`` of PRD §2.8 is always current.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from . import test_users as U
from .api_client import FenceRentalsClient


# ---------------------------------------------------------------------------
# Tier 1 — single rows
# ---------------------------------------------------------------------------


def set_clock(api: FenceRentalsClient, instant: str) -> None:
    """Move the logical clock of PRD §2.6; the hook needs no identity headers."""
    get_success_data(api.set_clock(instant, U.NO_HEADERS))


def seed_municipality(api: FenceRentalsClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_municipality(F.municipality_payload(**overrides), U.PLATFORM_ADMIN)
    )


def seed_account(api: FenceRentalsClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_account(F.account_payload(**overrides), U.ACCOUNT_MANAGER)
    )


def seed_event_account(api: FenceRentalsClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_account(F.event_account_payload(**overrides), U.ACCOUNT_MANAGER)
    )


def seed_panel_product(api: FenceRentalsClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_product(F.panel_product_payload(**overrides), U.PLATFORM_ADMIN)
    )


def seed_gate_product(api: FenceRentalsClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_product(F.gate_product_payload(**overrides), U.PLATFORM_ADMIN)
    )


def seed_barricade_product(api: FenceRentalsClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_product(F.barricade_product_payload(**overrides), U.PLATFORM_ADMIN)
    )


def seed_water_barrier_product(
    api: FenceRentalsClient, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_product(F.water_barrier_product_payload(**overrides), U.PLATFORM_ADMIN)
    )


def seed_crew(api: FenceRentalsClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_crew(F.crew_payload(**overrides), U.DISPATCH_COORDINATOR)
    )


def seed_jobsite(
    api: FenceRentalsClient, account_id: str, municipality_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_jobsite(
            F.jobsite_payload(account_id, municipality_id, **overrides),
            U.ACCOUNT_MANAGER,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — the reference-data world every scenario starts from
# ---------------------------------------------------------------------------

ADDON_SEEDERS = {
    C.GATE_CODE: seed_gate_product,
    C.BARRICADE_CODE: seed_barricade_product,
    C.WATER_BARRIER_CODE: seed_water_barrier_product,
}


def seed_world(
    api: FenceRentalsClient,
    *,
    clock: str = C.DEFAULT_CLOCK,
    municipality: Optional[Dict[str, Any]] = None,
    account: Optional[Dict[str, Any]] = None,
    panel: Optional[Dict[str, Any]] = None,
    addons: Sequence[str] = (),
    crews: Sequence[str] = (C.CREW_A,),
    crew_overrides: Optional[Dict[str, Any]] = None,
    jobsite: Optional[Dict[str, Any]] = None,
    event_account: bool = False,
) -> Dict[str, Any]:
    """Build jurisdiction, account, fleet, crews and one jobsite.

    Keyword dicts are payload overrides, not entities: ``municipality={...}``
    overrides the jurisdiction payload, and so on.
    """
    set_clock(api, clock)
    muni = seed_municipality(api, **(municipality or {}))
    acct = (
        seed_event_account(api, **(account or {}))
        if event_account
        else seed_account(api, **(account or {}))
    )
    panel_product = seed_panel_product(api, **(panel or {}))
    products: Dict[str, Dict[str, Any]] = {panel_product["code"]: panel_product}
    for code in addons:
        products[code] = ADDON_SEEDERS[code](api)
    crew_rows: Dict[str, Dict[str, Any]] = {}
    for code in crews:
        crew_rows[code] = seed_crew(
            api, crew_code=code, **(crew_overrides or {})
        )
    site = seed_jobsite(api, acct["id"], muni["id"], **(jobsite or {}))
    return {
        "municipality": muni,
        "account": acct,
        "panel": panel_product,
        "products": products,
        "crews": crew_rows,
        "crew": crew_rows[crews[0]] if crews else None,
        "jobsite": site,
        "customer": U.make_customer_contact_headers(acct["id"]),
    }


def add_jobsite(world: Dict[str, Any], api: FenceRentalsClient, **overrides: Any):
    """Register one more jobsite under the same account and jurisdiction."""
    return seed_jobsite(
        api, world["account"]["id"], world["municipality"]["id"], **overrides
    )


def add_crew(world: Dict[str, Any], api: FenceRentalsClient, crew_code: str, **overrides: Any):
    crew = seed_crew(api, crew_code=crew_code, **overrides)
    world["crews"][crew_code] = crew
    return crew


# ---------------------------------------------------------------------------
# Tier 3 — quote / contract lifecycle shortcuts
# ---------------------------------------------------------------------------


def jobsite_version(api: FenceRentalsClient, jobsite_id: str) -> int:
    """The jobsite's live ``version``, for the concurrency token of PRD §2.8."""
    return get_success_data(api.get_jobsite(jobsite_id, U.ACCOUNT_MANAGER))["version"]


def contract_version(api: FenceRentalsClient, contract_id: str) -> int:
    return get_success_data(api.get_contract(contract_id, U.ACCOUNT_MANAGER))["version"]


def seed_quote(
    api: FenceRentalsClient, jobsite_id: str, *, event: bool = False, **overrides: Any
) -> Dict[str, Any]:
    """Price a configuration on ``jobsite_id``, reading the live jobsite version."""
    version = overrides.pop("expected_jobsite_version", None)
    if version is None:
        version = jobsite_version(api, jobsite_id)
    builder = F.event_quote_payload if event else F.quote_payload
    return get_success_data(
        api.create_quote(jobsite_id, builder(version, **overrides), U.ACCOUNT_MANAGER)
    )


def issue_quote(api: FenceRentalsClient, quote_id: str) -> Dict[str, Any]:
    return get_success_data(api.issue_quote(quote_id, U.ACCOUNT_MANAGER))


def accept_quote(
    api: FenceRentalsClient,
    quote_id: str,
    account_id: str,
    accepted_by: str = C.ACCEPTOR_CONSTRUCTION,
) -> Dict[str, Any]:
    return get_success_data(
        api.accept_quote(
            quote_id,
            F.accept_payload(accepted_by),
            U.make_customer_contact_headers(account_id),
        )
    )


def seed_accepted_quote(
    api: FenceRentalsClient,
    jobsite_id: str,
    account_id: str,
    *,
    event: bool = False,
    accepted_by: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """DRAFT → ISSUED → ACCEPTED, returning the accepted quote."""
    quote = seed_quote(api, jobsite_id, event=event, **overrides)
    issue_quote(api, quote["id"])
    name = accepted_by or (C.ACCEPTOR_EVENT if event else C.ACCEPTOR_CONSTRUCTION)
    return accept_quote(api, quote["id"], account_id, name)


def seed_contract(
    api: FenceRentalsClient,
    jobsite_id: str,
    account_id: str,
    *,
    event: bool = False,
    accepted_by: Optional[str] = None,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Full quote-to-contract chain; returns ``(contract, accepted_quote)``."""
    accepted = seed_accepted_quote(
        api, jobsite_id, account_id, event=event, accepted_by=accepted_by, **overrides
    )
    name = accepted_by or (C.ACCEPTOR_EVENT if event else C.ACCEPTOR_CONSTRUCTION)
    contract = get_success_data(
        api.create_contract(
            F.contract_payload(accepted["id"], name), U.ACCOUNT_MANAGER
        )
    )
    return contract, accepted


def plan_work_order(
    api: FenceRentalsClient,
    contract_id: str,
    work_order_type: str,
    ordered_linear_feet: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_work_order(
            contract_id,
            F.work_order_payload(work_order_type, ordered_linear_feet, **overrides),
            U.DISPATCH_COORDINATOR,
        )
    )


def dispatch(
    api: FenceRentalsClient,
    work_order_id: str,
    crew_id: str,
    scheduled_start_utc: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.dispatch_work_order(
            work_order_id,
            F.dispatch_payload(crew_id, scheduled_start_utc),
            headers or U.DISPATCH_COORDINATOR,
        )
    )


def complete(
    api: FenceRentalsClient,
    work_order_id: str,
    completed_linear_feet: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.complete_work_order(
            work_order_id,
            F.complete_payload(completed_linear_feet),
            headers or U.DISPATCH_COORDINATOR,
        )
    )


# ---------------------------------------------------------------------------
# Tier 4 — mobilized / active worlds
# ---------------------------------------------------------------------------


def seed_installed_contract(
    api: FenceRentalsClient,
    world: Dict[str, Any],
    *,
    jobsite: Optional[Dict[str, Any]] = None,
    crew: Optional[Dict[str, Any]] = None,
    linear_feet: int = 500,
    install_clock: str = C.CLOCK_AUG_20,
    install_start: str = "2026-08-20T08:00:00Z",
    completed_linear_feet: Optional[int] = None,
    installer: Optional[Dict[str, str]] = None,
    event: bool = False,
    **quote_overrides: Any,
) -> Dict[str, Any]:
    """Drive a contract all the way to ``ACTIVE`` through a completed install.

    Returns the contract, the accepted quote, the install visit and the
    ``MOBILIZATION`` invoice raised by the cascade of PRD §3.6.
    """
    site = jobsite or world["jobsite"]
    crew_row = crew or world["crew"]
    quote_overrides.setdefault("linear_feet", linear_feet)
    contract, quote = seed_contract(
        api, site["id"], world["account"]["id"], event=event, **quote_overrides
    )
    install = plan_work_order(
        api, contract["id"], C.WO_DELIVERY_INSTALL, quote["linear_feet"]
    )
    set_clock(api, install_clock)
    dispatch(api, install["id"], crew_row["id"], install_start)
    done = complete(
        api,
        install["id"],
        quote["linear_feet"] if completed_linear_feet is None else completed_linear_feet,
        headers=installer,
    )
    invoices, _ = _list_invoices(api, contract["id"])
    mobilization = next(
        (inv for inv in invoices if inv["invoice_kind"] == C.KIND_MOBILIZATION), None
    )
    return {
        "contract": contract,
        "quote": quote,
        "install": done,
        "mobilization_invoice": mobilization,
        "jobsite": site,
        "crew": crew_row,
    }


def _list_invoices(api: FenceRentalsClient, contract_id: str, **params: Any):
    query = {"contract_id": contract_id, "limit": C.MAX_LIMIT}
    query.update(params)
    body = api.list_invoices(U.ACCOUNT_MANAGER, params=query).json()
    return body["data"], body["meta"]


def invoices_for(api: FenceRentalsClient, contract_id: str, **params: Any) -> List[Dict]:
    rows, _ = _list_invoices(api, contract_id, **params)
    return rows


def seed_demobilizing_contract(
    api: FenceRentalsClient,
    world: Dict[str, Any],
    *,
    removal_clock: str = C.CLOCK_AUG_25,
    removal_start: str = "2026-08-25T08:00:00Z",
    remover: Optional[Dict[str, str]] = None,
    **install_kwargs: Any,
) -> Dict[str, Any]:
    """Extend an installed contract through a completed removal visit.

    The removal completion opens the reconciliation of PRD §3.7, so the returned
    mapping also carries it.
    """
    state = seed_installed_contract(api, world, **install_kwargs)
    contract = state["contract"]
    removal = plan_work_order(
        api, contract["id"], C.WO_REMOVAL, state["quote"]["linear_feet"]
    )
    set_clock(api, removal_clock)
    dispatch(api, removal["id"], state["crew"]["id"], removal_start)
    complete(
        api, removal["id"], state["quote"]["linear_feet"], headers=remover
    )
    body = api.list_reconciliations(
        U.YARD_AUDITOR, params={"contract_id": contract["id"], "limit": C.MAX_LIMIT}
    ).json()
    reconciliations = body["data"]
    state["removal"] = removal
    state["reconciliation"] = reconciliations[0] if reconciliations else None
    return state


def seed_scheduled_install(
    api: FenceRentalsClient,
    world: Dict[str, Any],
    *,
    jobsite: Optional[Dict[str, Any]] = None,
    crew: Optional[Dict[str, Any]] = None,
    dispatch_clock: str = C.CLOCK_AUG_20,
    scheduled_start: str = "2026-08-24T09:00:00Z",
    event: bool = False,
    **quote_overrides: Any,
) -> Dict[str, Any]:
    """A ``PENDING_MOBILIZATION`` contract whose install is ``SCHEDULED``."""
    site = jobsite or world["jobsite"]
    crew_row = crew or world["crew"]
    contract, quote = seed_contract(
        api, site["id"], world["account"]["id"], event=event, **quote_overrides
    )
    install = plan_work_order(
        api, contract["id"], C.WO_DELIVERY_INSTALL, quote["linear_feet"]
    )
    set_clock(api, dispatch_clock)
    scheduled = dispatch(api, install["id"], crew_row["id"], scheduled_start)
    return {
        "contract": contract,
        "quote": quote,
        "install": scheduled,
        "jobsite": site,
        "crew": crew_row,
    }


# ---------------------------------------------------------------------------
# Tier 5 — permits and reconciliations
# ---------------------------------------------------------------------------


def seed_permit(
    api: FenceRentalsClient, jobsite_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_permit(F.permit_payload(jobsite_id, **overrides), U.MUNICIPAL_LIAISON)
    )


def submit_permit(
    api: FenceRentalsClient, permit_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_permit(permit_id, U.MUNICIPAL_LIAISON, F.submit_payload(**overrides))
    )


def decide_permit(
    api: FenceRentalsClient, permit_id: str, decision: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_permit(
            permit_id, F.decision_payload(decision, **overrides), U.MUNICIPAL_LIAISON
        )
    )


def seed_approved_permit(
    api: FenceRentalsClient, jobsite_id: str, **overrides: Any
) -> Dict[str, Any]:
    """DRAFT → SUBMITTED → APPROVED, so a dispatch may pass rung 10 of PRD §2.7."""
    permit = seed_permit(api, jobsite_id, **overrides)
    submit_permit(api, permit["id"])
    return decide_permit(
        api, permit["id"], C.DECISION_APPROVE, reviewer_note="approved as drawn"
    )


def finalize_reconciliation(
    api: FenceRentalsClient,
    reconciliation_id: str,
    unit_returns: List[Dict[str, Any]],
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.finalize_reconciliation(
            reconciliation_id,
            F.finalize_payload(unit_returns, **overrides),
            headers or U.YARD_AUDITOR,
        )
    )


def pay_account(
    api: FenceRentalsClient,
    account_id: str,
    amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_payment(
            account_id, F.payment_payload(amount_cents), headers or U.ACCOUNT_MANAGER_2
        )
    )


def read_account(api: FenceRentalsClient, account_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_account(account_id, U.ACCOUNT_MANAGER))


def read_product(api: FenceRentalsClient, product_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_product(product_id, U.DISPATCH_COORDINATOR))


def read_contract(api: FenceRentalsClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contract(contract_id, U.ACCOUNT_MANAGER))


def read_work_order(api: FenceRentalsClient, work_order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_work_order(work_order_id, U.DISPATCH_COORDINATOR)
    )


def read_quote(api: FenceRentalsClient, quote_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_quote(quote_id, U.ACCOUNT_MANAGER))


def read_permit(api: FenceRentalsClient, permit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_permit(permit_id, U.MUNICIPAL_LIAISON))


def read_invoice(api: FenceRentalsClient, invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_invoice(invoice_id, U.ACCOUNT_MANAGER))


def read_reconciliation(api: FenceRentalsClient, rec_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_reconciliation(rec_id, U.YARD_AUDITOR))


def read_municipality(api: FenceRentalsClient, municipality_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_municipality(municipality_id, U.MUNICIPAL_LIAISON)
    )


def read_jobsite(api: FenceRentalsClient, jobsite_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_jobsite(jobsite_id, U.ACCOUNT_MANAGER))


def read_crew(api: FenceRentalsClient, crew_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_crew(crew_id, U.DISPATCH_COORDINATOR))


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> FenceRentalsClient:
    """A client bound to the server under test."""
    return FenceRentalsClient()


@pytest.fixture
def base_world(api: FenceRentalsClient) -> Dict[str, Any]:
    """Jurisdiction HRB-01, one account, the panel fleet, one crew, one jobsite."""
    return seed_world(api)


@pytest.fixture
def addon_world(api: FenceRentalsClient) -> Dict[str, Any]:
    """The base world plus the gate, barricade and water-barrier fleets."""
    return seed_world(
        api, addons=(C.GATE_CODE, C.BARRICADE_CODE, C.WATER_BARRIER_CODE)
    )
