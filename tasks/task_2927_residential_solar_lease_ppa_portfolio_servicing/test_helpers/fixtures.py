"""Fixtures and setup helpers.

The server under test is restarted before every individual test, so every test
starts against an empty database. Nothing here assumes pre-seeded data: each
helper builds the state it needs through the API's own endpoints, including the
logical-clock control endpoint of §2.5.

All setup calls go through ``get_success_data`` so that a broken setup step
reports the API's own error identifier instead of a bare KeyError.
"""

from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from . import test_users as U
from .api_client import ApiClient
from .types import Headers, Payload, Resource


# ---------------------------------------------------------------------------
# Tier 1: the client and the clock
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the running server (base URL from the environment)."""
    return ApiClient()


def set_clock(api: ApiClient, current_utc: str) -> str:
    """Move the logical clock and return the instant the server echoed back."""
    data = get_success_data(api.set_clock(current_utc))
    return data["current_utc"]


@pytest.fixture
def clock(api: ApiClient):
    """Expose a clock mover; the server already starts at the §2.5 default."""

    def _move(current_utc: str) -> str:
        return set_clock(api, current_utc)

    return _move


# ---------------------------------------------------------------------------
# Tier 2: independent root entities
# ---------------------------------------------------------------------------
def make_homeowner(
    api: ApiClient, headers: Optional[Headers] = None, **overrides
) -> Resource:
    return get_success_data(
        api.create_homeowner(
            F.homeowner_payload(**overrides), headers or U.agent_headers()
        ),
        201,
    )


def make_buyer(
    api: ApiClient, headers: Optional[Headers] = None, **overrides
) -> Resource:
    return get_success_data(
        api.create_homeowner(
            F.buyer_payload(**overrides), headers or U.agent_headers()
        ),
        201,
    )


def make_tariff(
    api: ApiClient, headers: Optional[Headers] = None, **overrides
) -> Resource:
    """Publishing to the tariff book is a `PortfolioAdmin` operation (§3.1)."""
    return get_success_data(
        api.create_tariff(F.tariff_payload(**overrides), headers or U.admin_headers()),
        201,
    )


def make_successor_tariff(
    api: ApiClient, headers: Optional[Headers] = None, **overrides
) -> Resource:
    return get_success_data(
        api.create_tariff(
            F.successor_tariff_payload(**overrides), headers or U.admin_headers()
        ),
        201,
    )


@pytest.fixture
def homeowner(api: ApiClient) -> Resource:
    return make_homeowner(api)


@pytest.fixture
def tariff(api: ApiClient) -> Resource:
    return make_tariff(api)


# ---------------------------------------------------------------------------
# Tier 3: agreements
# ---------------------------------------------------------------------------
def book_ppa(
    api: ApiClient,
    homeowner_id: str,
    tariff_id: str,
    headers: Optional[Headers] = None,
    **overrides,
) -> Resource:
    return get_success_data(
        api.create_agreement(
            F.ppa_agreement_payload(homeowner_id, tariff_id, **overrides),
            headers or U.agent_headers(),
        ),
        201,
    )


def book_lease(
    api: ApiClient,
    homeowner_id: str,
    tariff_id: str,
    headers: Optional[Headers] = None,
    **overrides,
) -> Resource:
    return get_success_data(
        api.create_agreement(
            F.lease_agreement_payload(homeowner_id, tariff_id, **overrides),
            headers or U.agent_headers(),
        ),
        201,
    )


def activate(
    api: ApiClient, agreement_id: str, headers: Optional[Headers] = None
) -> Resource:
    return get_success_data(
        api.activate_agreement(agreement_id, headers or U.agent_headers()), 200
    )


def read_agreement(
    api: ApiClient, agreement_id: str, headers: Optional[Headers] = None
) -> Resource:
    return get_success_data(
        api.get_agreement(agreement_id, headers or U.agent_headers()), 200
    )


class Scenario:
    """A booked site: the homeowner, the schedule it is billed on, the deal."""

    def __init__(self, api: ApiClient, homeowner: Resource, tariff: Resource,
                 agreement: Resource):
        self.api = api
        self.homeowner = homeowner
        self.tariff = tariff
        self.agreement = agreement

    @property
    def homeowner_id(self) -> str:
        return self.homeowner["id"]

    @property
    def tariff_id(self) -> str:
        return self.tariff["id"]

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def owner_headers(self) -> Headers:
        return U.homeowner_headers(self.homeowner["id"])

    def refresh(self, headers: Optional[Headers] = None) -> Resource:
        self.agreement = read_agreement(self.api, self.agreement_id, headers)
        return self.agreement

    @property
    def version(self) -> int:
        return self.agreement["version"]


def build_ppa_scenario(
    api: ApiClient,
    activate_it: bool = True,
    tariff_overrides: Optional[Dict[str, Any]] = None,
    homeowner_overrides: Optional[Dict[str, Any]] = None,
    **agreement_overrides,
) -> Scenario:
    """Register a homeowner, publish a schedule, book a PPA, optionally go live."""
    owner = make_homeowner(api, **(homeowner_overrides or {}))
    schedule = make_tariff(api, **(tariff_overrides or {}))
    agreement = book_ppa(api, owner["id"], schedule["id"], **agreement_overrides)
    if activate_it:
        agreement = activate(api, agreement["id"])
    return Scenario(api, owner, schedule, agreement)


def build_lease_scenario(
    api: ApiClient,
    activate_it: bool = True,
    tariff_overrides: Optional[Dict[str, Any]] = None,
    homeowner_overrides: Optional[Dict[str, Any]] = None,
    **agreement_overrides,
) -> Scenario:
    owner = make_homeowner(api, **(homeowner_overrides or {}))
    schedule = make_tariff(api, **(tariff_overrides or {}))
    agreement = book_lease(api, owner["id"], schedule["id"], **agreement_overrides)
    if activate_it:
        agreement = activate(api, agreement["id"])
    return Scenario(api, owner, schedule, agreement)


@pytest.fixture
def draft_ppa(api: ApiClient) -> Scenario:
    """A booked PPA still in `DRAFT`."""
    return build_ppa_scenario(api, activate_it=False)


@pytest.fixture
def active_ppa(api: ApiClient) -> Scenario:
    """An `ACTIVE` PPA on the shared scenario terms."""
    return build_ppa_scenario(api)


@pytest.fixture
def active_lease(api: ApiClient) -> Scenario:
    """An `ACTIVE` lease on the shared scenario terms."""
    return build_lease_scenario(api)


# ---------------------------------------------------------------------------
# Tier 4: metered months, true-ups
# ---------------------------------------------------------------------------
def record_period(
    api: ApiClient,
    agreement_id: str,
    period_year: int,
    period_month: int,
    metered_kwh: int,
    headers: Optional[Headers] = None,
    **overrides,
) -> Resource:
    return get_success_data(
        api.create_period(
            F.period_payload(
                agreement_id, period_year, period_month, metered_kwh, **overrides
            ),
            headers or U.agent_headers(),
        ),
        201,
    )


def reconcile(
    api: ApiClient,
    period_id: str,
    issue_credit: bool = False,
    headers: Optional[Headers] = None,
) -> Resource:
    """Reconciliation is "a `ServicingAgent`-only step" (§3.3)."""
    return get_success_data(
        api.reconcile_period(
            period_id,
            F.reconcile_payload(issue_credit),
            headers or U.agent_headers(),
        ),
        200,
    )


def record_twelve_months(
    api: ApiClient,
    agreement_id: str,
    period_year: int,
    metered_kwh: int = 700,
    headers: Optional[Headers] = None,
    auto_reconcile: bool = False,
    auto_issue_credit: bool = False,
) -> list:
    """Record a full contract year of months for a January-start agreement."""
    months = []
    for month in range(1, 13):
        extra: Payload = {}
        if auto_reconcile:
            extra["auto_reconcile"] = True
            extra["auto_issue_credit"] = auto_issue_credit
        months.append(
            record_period(
                api, agreement_id, period_year, month, metered_kwh, headers, **extra
            )
        )
    return months


def create_true_up(
    api: ApiClient,
    agreement_id: str,
    contract_year: int,
    method: str,
    expected_agreement_version: int,
    headers: Optional[Headers] = None,
) -> Resource:
    return get_success_data(
        api.create_true_up(
            F.true_up_payload(
                agreement_id, contract_year, method, expected_agreement_version
            ),
            headers or U.agent_headers(),
        ),
        201,
    )


def post_true_up(
    api: ApiClient, true_up_id: str, headers: Optional[Headers] = None
) -> Resource:
    return get_success_data(
        api.post_true_up(true_up_id, headers or U.agent_headers(U.AGENT_1)), 200
    )


# ---------------------------------------------------------------------------
# Tier 5: monitoring, dispatch, diagnosis, warranty
# ---------------------------------------------------------------------------
def open_outage(
    api: ApiClient,
    agreement_id: str,
    detected_at: str,
    headers: Optional[Headers] = None,
    **overrides,
) -> Resource:
    """Recording an alarm belongs to `FieldOpsCoordinator` or `PortfolioAdmin`."""
    return get_success_data(
        api.create_outage_event(
            F.outage_event_payload(agreement_id, detected_at, **overrides),
            headers or U.ops_headers(),
        ),
        201,
    )


def triage(
    api: ApiClient, outage_event_id: str, headers: Optional[Headers] = None
) -> Resource:
    """Triage is "exclusive to the `FieldOpsCoordinator`" (§3.5)."""
    return get_success_data(
        api.triage_outage_event(outage_event_id, headers or U.ops_headers()), 200
    )


def dispatch(
    api: ApiClient,
    outage_event: Resource,
    scheduled_window_start: str,
    scheduled_window_end: str,
    headers: Optional[Headers] = None,
    **overrides,
) -> Resource:
    """Dispatch a technician, threading the event's own current `version`."""
    return get_success_data(
        api.create_truck_roll(
            F.truck_roll_payload(
                outage_event["id"],
                scheduled_window_start,
                scheduled_window_end,
                outage_event["version"],
                **overrides,
            ),
            headers or U.ops_headers(U.OPS_1),
        ),
        201,
    )


def triage_and_dispatch(
    api: ApiClient,
    agreement_id: str,
    detected_at: str,
    window_start: str,
    window_end: str,
    dispatcher: str = U.OPS_1,
    **outage_overrides,
) -> Dict[str, Resource]:
    """Open an alarm, triage it, and dispatch a technician against it."""
    event = open_outage(api, agreement_id, detected_at, **outage_overrides)
    event = triage(api, event["id"])
    roll = dispatch(
        api, event, window_start, window_end, U.ops_headers(dispatcher)
    )
    return {"event": event, "roll": roll}


def complete_roll(
    api: ApiClient,
    truck_roll_id: str,
    disposition: str,
    root_cause: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> Resource:
    """Close out a dispatch; the closer must differ from the dispatcher."""
    return get_success_data(
        api.complete_truck_roll(
            truck_roll_id,
            F.complete_payload(disposition, root_cause),
            headers or U.ops_headers(U.OPS_2),
        ),
        200,
    )


def make_claim(
    api: ApiClient,
    truck_roll_id: str,
    headers: Optional[Headers] = None,
    **overrides,
) -> Resource:
    """Opening a manufacturer claim is "exclusive to the `FieldOpsCoordinator`"."""
    return get_success_data(
        api.create_warranty_claim(
            F.warranty_claim_payload(truck_roll_id, **overrides),
            headers or U.ops_headers(U.OPS_1),
        ),
        201,
    )


def submit_claim(
    api: ApiClient, claim_id: str, headers: Optional[Headers] = None
) -> Resource:
    return get_success_data(
        api.submit_warranty_claim(claim_id, headers or U.ops_headers(U.OPS_1)), 200
    )


# ---------------------------------------------------------------------------
# Tier 5: roof work
# ---------------------------------------------------------------------------
def open_roof_order(
    api: ApiClient,
    agreement_id: str,
    requested_removal_date: str,
    reinstall_target_date: str,
    headers: Optional[Headers] = None,
    **overrides,
) -> Resource:
    return get_success_data(
        api.create_roof_work_order(
            F.roof_work_order_payload(
                agreement_id,
                requested_removal_date,
                reinstall_target_date,
                **overrides,
            ),
            headers or U.agent_headers(),
        ),
        201,
    )


def quote_roof_order(
    api: ApiClient,
    roof_work_order_id: str,
    quote_cents: int = 480000,
    headers: Optional[Headers] = None,
) -> Resource:
    return get_success_data(
        api.quote_roof_work_order(
            roof_work_order_id,
            F.quote_payload(quote_cents),
            headers or U.agent_headers(),
        ),
        200,
    )


def approve_roof_order(
    api: ApiClient, roof_work_order_id: str, headers: Optional[Headers] = None
) -> Resource:
    return get_success_data(
        api.approve_roof_work_order(roof_work_order_id, headers or U.agent_headers()),
        200,
    )


def approved_roof_order(
    api: ApiClient,
    agreement_id: str,
    requested_removal_date: str,
    reinstall_target_date: str,
    quote_cents: int = 480000,
    **overrides,
) -> Resource:
    """Walk a roof-work order from `REQUESTED` through to `APPROVED`."""
    order = open_roof_order(
        api, agreement_id, requested_removal_date, reinstall_target_date, **overrides
    )
    quote_roof_order(api, order["id"], quote_cents)
    return approve_roof_order(api, order["id"])


def complete_roof_cycle(
    api: ApiClient,
    agreement_id: str,
    requested_removal_date: str,
    reinstall_target_date: str,
    remove_on: Optional[str] = None,
    reinstall_on: Optional[str] = None,
    quote_cents: int = 480000,
    **overrides,
) -> Resource:
    """Approve, take the panels off, sign the roofer off, and reinstall."""
    order = approved_roof_order(
        api,
        agreement_id,
        requested_removal_date,
        reinstall_target_date,
        quote_cents,
        **overrides,
    )
    if remove_on is not None:
        set_clock(api, remove_on)
    get_success_data(api.remove_panels(order["id"], U.ops_headers()), 200)
    get_success_data(api.roof_complete(order["id"], U.ops_headers()), 200)
    if reinstall_on is not None:
        set_clock(api, reinstall_on)
    return get_success_data(api.reinstall(order["id"], U.ops_headers()), 200)


# ---------------------------------------------------------------------------
# Tier 5: transfers, filings, elections
# ---------------------------------------------------------------------------
def open_assumption(
    api: ApiClient,
    agreement_id: str,
    closing_date: str,
    buyer_homeowner_id: str,
    headers: Optional[Headers] = None,
) -> Resource:
    """Opening a case is "exclusive to the `ServicingAgent`" (§3.8)."""
    return get_success_data(
        api.create_transfer_case(
            F.assumption_payload(agreement_id, closing_date, buyer_homeowner_id),
            headers or U.agent_headers(),
        ),
        201,
    )


def open_prepayment(
    api: ApiClient,
    agreement_id: str,
    closing_date: str,
    headers: Optional[Headers] = None,
) -> Resource:
    return get_success_data(
        api.create_transfer_case(
            F.prepayment_payload(agreement_id, closing_date),
            headers or U.agent_headers(),
        ),
        201,
    )


def open_relocation(
    api: ApiClient,
    agreement_id: str,
    closing_date: str,
    headers: Optional[Headers] = None,
    **overrides,
) -> Resource:
    return get_success_data(
        api.create_transfer_case(
            F.relocation_payload(agreement_id, closing_date, **overrides),
            headers or U.agent_headers(),
        ),
        201,
    )


def run_credit_review(
    api: ApiClient, transfer_case_id: str, headers: Optional[Headers] = None
) -> Resource:
    """The credit review is "exclusive to the `CreditUnderwriter`" (§3.8)."""
    return get_success_data(
        api.run_credit_review(transfer_case_id, headers or U.underwriter_headers()),
        200,
    )


def clear_title(
    api: ApiClient, transfer_case_id: str, headers: Optional[Headers] = None
) -> Resource:
    """Title clearance is "exclusive to the `TitleAgent`" (§3.8)."""
    return get_success_data(
        api.clear_title(transfer_case_id, headers or U.title_headers()), 200
    )


def close_transfer(
    api: ApiClient, transfer_case_id: str, headers: Optional[Headers] = None
) -> Resource:
    return get_success_data(
        api.close_transfer_case(transfer_case_id, headers or U.agent_headers()), 200
    )


def make_filing(
    api: ApiClient,
    agreement_id: str,
    filed_date: str,
    headers: Optional[Headers] = None,
    **overrides,
) -> Resource:
    return get_success_data(
        api.create_ucc_filing(
            F.ucc_filing_payload(agreement_id, filed_date, **overrides),
            headers or U.title_headers(),
        ),
        201,
    )


def terminated_filing(
    api: ApiClient,
    agreement_id: str,
    filed_date: str,
    **overrides,
) -> Resource:
    """Record a filing and walk it all the way to `TERMINATED`."""
    filing = make_filing(api, agreement_id, filed_date, **overrides)
    get_success_data(api.request_termination(filing["id"], U.title_headers(U.TITLE_1)), 200)
    return get_success_data(
        api.terminate_ucc_filing(filing["id"], U.title_headers(U.TITLE_2)), 200
    )


def submit_election(
    api: ApiClient,
    agreement_id: str,
    election_type: str,
    headers: Optional[Headers] = None,
) -> Resource:
    return get_success_data(
        api.create_election(
            F.election_payload(agreement_id, election_type),
            headers or U.agent_headers(),
        ),
        201,
    )


def accept_election(
    api: ApiClient, election_id: str, headers: Optional[Headers] = None
) -> Resource:
    return get_success_data(
        api.accept_election(election_id, headers or U.agent_headers()), 200
    )


def execute_election(
    api: ApiClient, election_id: str, headers: Optional[Headers] = None
) -> Resource:
    """Execution is "exclusive to the `PortfolioAdmin`" (§3.10)."""
    return get_success_data(
        api.execute_election(election_id, headers or U.admin_headers()), 200
    )
