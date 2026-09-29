"""Composite state builders.

The server is restarted before every test, so each test starts against an empty
database and every scenario is built from scratch through the public API. All
setup calls go through get_success_data(), which raises a readable AssertionError
naming the failing step's error id, so a broken fixture is never mistaken for a
failing assertion.

The builders are layered:

  tier 1  clock control
  tier 2  single-row creators (property, outlet, business date, folio, ...)
  tier 3  small composites (a standard property, a folio checked in, ...)
  tier 4  pipeline drivers that walk a business date through the close sequence
  tier 5  named scenarios reused by whole groups of tests
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import NightAuditApiClient
from .constants import (
    BUSINESS_DATE_D1,
    BUSINESS_DATE_D2,
)
from .test_users import (
    ADMIN,
    AUDITOR,
    AUDITOR_2,
    CONTROLLER,
    FRONT_DESK,
    REVENUE_MANAGER,
    make_outlet_manager_headers,
)
from .types import Headers, Payload

# ---------------------------------------------------------------------------
# tier 1 - the logical clock
# ---------------------------------------------------------------------------


def set_clock(api: NightAuditApiClient, current_utc: str, headers: Headers = ADMIN) -> None:
    """Pin the logical clock. Every aging, grace and expiry rule reads it."""
    get_success_data(api.set_clock(current_utc, headers))


# ---------------------------------------------------------------------------
# tier 2 - single-row creators
# ---------------------------------------------------------------------------


def create_property(api: NightAuditApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = f.build_property_payload(**overrides)
    return get_success_data(api.create_property(payload, ADMIN))


def create_outlet(api: NightAuditApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.build_outlet_payload(property_id, **overrides)
    return get_success_data(api.create_outlet(payload, ADMIN))


def create_business_date(
    api: NightAuditApiClient,
    property_id: str,
    business_date: str = BUSINESS_DATE_D1,
    headers: Headers = AUDITOR,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.build_business_date_payload(property_id, business_date, **overrides)
    return get_success_data(api.create_business_date(payload, headers))


def create_folio(
    api: NightAuditApiClient,
    property_id: str,
    business_date_id: str,
    headers: Headers = FRONT_DESK,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.build_folio_payload(property_id, business_date_id, **overrides)
    return get_success_data(api.create_folio(payload, headers))


def check_in(
    api: NightAuditApiClient, folio_id: str, headers: Headers = FRONT_DESK
) -> Dict[str, Any]:
    return get_success_data(api.check_in(folio_id, headers))


def check_out(
    api: NightAuditApiClient,
    folio_id: str,
    business_date_id: str,
    headers: Headers = FRONT_DESK,
) -> Dict[str, Any]:
    return get_success_data(
        api.check_out(folio_id, f.build_check_out_payload(business_date_id), headers)
    )


def create_ledger_account(
    api: NightAuditApiClient,
    property_id: str,
    ledger_type: str = "CITY_LEDGER",
    headers: Headers = CONTROLLER,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.build_ledger_account_payload(property_id, ledger_type, **overrides)
    return get_success_data(api.create_ledger_account(payload, headers))


def create_card_authorization(
    api: NightAuditApiClient,
    folio_id: str,
    authorized_amount: float = 500.00,
    obtained_at: str = "2026-08-01T08:00:00.000Z",
    headers: Headers = FRONT_DESK,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.build_card_authorization_payload(
        folio_id, authorized_amount, obtained_at, **overrides
    )
    return get_success_data(api.create_card_authorization(payload, headers))


def create_outlet_ticket(
    api: NightAuditApiClient,
    outlet_id: str,
    business_date_id: str,
    gross_amount: float = 120.00,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.build_outlet_ticket_payload(
        outlet_id, business_date_id, gross_amount, **overrides
    )
    return get_success_data(
        api.create_outlet_ticket(payload, make_outlet_manager_headers(outlet_id))
    )


def close_outlet_ticket(
    api: NightAuditApiClient,
    ticket_id: str,
    outlet_id: str,
    transmitted_at: str = "2026-08-01T18:00:00.000Z",
) -> Dict[str, Any]:
    return get_success_data(
        api.close_outlet_ticket(
            ticket_id,
            make_outlet_manager_headers(outlet_id),
            f.build_close_ticket_payload(transmitted_at),
        )
    )


def create_settlement_batch(
    api: NightAuditApiClient,
    business_date_id: str,
    outlet_id: str,
    declared_amount: float,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.build_settlement_batch_payload(
        business_date_id, outlet_id, declared_amount, **overrides
    )
    return get_success_data(
        api.create_settlement_batch(payload, make_outlet_manager_headers(outlet_id))
    )


def create_allowance(
    api: NightAuditApiClient,
    folio_id: str,
    business_date_id: str,
    requested_amount: float = 100.00,
    headers: Headers = FRONT_DESK,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.build_allowance_payload(
        folio_id, business_date_id, requested_amount, **overrides
    )
    return get_success_data(api.create_allowance(payload, headers))


def create_authorization_document(
    api: NightAuditApiClient,
    property_id: str,
    headers: Headers = FRONT_DESK,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.build_authorization_document_payload(property_id, **overrides)
    return get_success_data(api.create_authorization_document(payload, headers))


def review_document(
    api: NightAuditApiClient,
    document_id: str,
    decision: str = "APPROVE",
    headers: Headers = REVENUE_MANAGER,
) -> Dict[str, Any]:
    return get_success_data(
        api.review_authorization_document(
            document_id, f.build_review_payload(decision), headers
        )
    )


def post_journal_line(
    api: NightAuditApiClient,
    business_date_id: str,
    charge_type: str = "MISC_CHARGE",
    amount: float = 25.00,
    headers: Headers = AUDITOR,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.build_journal_posting_payload(
        business_date_id, charge_type, amount, **overrides
    )
    return get_success_data(api.create_journal_posting(payload, headers))


# ---------------------------------------------------------------------------
# tier 3 - small composites
# ---------------------------------------------------------------------------


@dataclass
class StandardProperty:
    """A registered property plus its first business date and that date's period."""

    property_id: str
    business_date_id: str
    accounting_period_id: str
    business_date: str
    property_row: Dict[str, Any] = field(default_factory=dict)
    business_date_row: Dict[str, Any] = field(default_factory=dict)


def standard_property(
    api: NightAuditApiClient,
    clock: str = "2026-08-01T09:00:00.000Z",
    business_date: str = BUSINESS_DATE_D1,
    property_overrides: Optional[Payload] = None,
    date_overrides: Optional[Payload] = None,
) -> StandardProperty:
    """Pin the clock, register the standard property and open one business date."""
    set_clock(api, clock)
    prop = create_property(api, **(property_overrides or {}))
    bd = create_business_date(
        api, prop["id"], business_date, **(date_overrides or {})
    )
    return StandardProperty(
        property_id=prop["id"],
        business_date_id=bd["id"],
        accounting_period_id=bd["accounting_period_id"],
        business_date=bd["business_date"],
        property_row=prop,
        business_date_row=bd,
    )


def add_business_date(
    api: NightAuditApiClient, scenario: StandardProperty, business_date: str = BUSINESS_DATE_D2, **overrides: Any
) -> Dict[str, Any]:
    return create_business_date(api, scenario.property_id, business_date, **overrides)


def in_house_folio(
    api: NightAuditApiClient,
    scenario: StandardProperty,
    contracted_rate_amount: float = 200.00,
    **overrides: Any,
) -> Dict[str, Any]:
    """A folio created against the scenario's business date and checked in."""
    folio = create_folio(
        api,
        scenario.property_id,
        scenario.business_date_id,
        contracted_rate_amount=contracted_rate_amount,
        **overrides,
    )
    check_in(api, folio["id"])
    return folio


def active_outlet(
    api: NightAuditApiClient,
    scenario: StandardProperty,
    requires_shift_settlement: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    return create_outlet(
        api,
        scenario.property_id,
        requires_shift_settlement=requires_shift_settlement,
        **overrides,
    )


def submitted_allowance(
    api: NightAuditApiClient,
    folio_id: str,
    business_date_id: str,
    requested_amount: float = 100.00,
    requester: Headers = FRONT_DESK,
    **overrides: Any,
) -> Dict[str, Any]:
    """An allowance raised and submitted by the same requester."""
    allowance = create_allowance(
        api, folio_id, business_date_id, requested_amount, requester, **overrides
    )
    return get_success_data(api.submit_allowance(allowance["id"], requester))


def posted_allowance(
    api: NightAuditApiClient,
    folio_id: str,
    business_date_id: str,
    requested_amount: float = 60.00,
    requester: Headers = FRONT_DESK,
    approver: Headers = AUDITOR_2,
    approved_amount: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An allowance driven all the way to POSTED by a different user than the requester."""
    allowance = submitted_allowance(
        api, folio_id, business_date_id, requested_amount, requester, **overrides
    )
    amount = requested_amount if approved_amount is None else approved_amount
    return get_success_data(
        api.approve_allowance(
            allowance["id"], f.build_approve_payload(amount), approver
        )
    )


def active_comp_document(
    api: NightAuditApiClient,
    scenario: StandardProperty,
    folio_id: str,
    valid_from_date: str = BUSINESS_DATE_D1,
    valid_to_date: str = BUSINESS_DATE_D1,
    **overrides: Any,
) -> Dict[str, Any]:
    """A COMP_ROOM document filed by the desk and approved by a revenue manager."""
    doc = create_authorization_document(
        api,
        scenario.property_id,
        FRONT_DESK,
        doc_type="COMP_ROOM",
        valid_from_date=valid_from_date,
        valid_to_date=valid_to_date,
        folio_id=folio_id,
        **overrides,
    )
    return review_document(api, doc["id"], "APPROVE")


def comp_folio_with_paperwork(
    api: NightAuditApiClient,
    scenario: StandardProperty,
    nights_count: int = 1,
    valid_to_date: str = BUSINESS_DATE_D1,
    **overrides: Any,
) -> Dict[str, Any]:
    """A comp folio whose comp nights are covered by an ACTIVE COMP_ROOM document."""
    folio = create_folio(
        api,
        scenario.property_id,
        scenario.business_date_id,
        is_comp=True,
        market_segment="COMP",
        rate_plan_code="COMP",
        nights_count=nights_count,
        **overrides,
    )
    active_comp_document(
        api, scenario, folio["id"], BUSINESS_DATE_D1, valid_to_date
    )
    check_in(api, folio["id"])
    return folio


# ---------------------------------------------------------------------------
# tier 4 - pipeline drivers
# ---------------------------------------------------------------------------


def post_room_and_tax(
    api: NightAuditApiClient, business_date_id: str, headers: Headers = AUDITOR
) -> Dict[str, Any]:
    return get_success_data(api.post_room_and_tax(business_date_id, headers))


def seal_charges(
    api: NightAuditApiClient, business_date_id: str, headers: Headers = AUDITOR
) -> Dict[str, Any]:
    return get_success_data(api.seal_charges(business_date_id, headers))


def verify_settlements(
    api: NightAuditApiClient, business_date_id: str, headers: Headers = AUDITOR
) -> Dict[str, Any]:
    return get_success_data(api.verify_settlements(business_date_id, headers))


def balance_business_date(
    api: NightAuditApiClient, business_date_id: str, headers: Headers = AUDITOR
) -> Dict[str, Any]:
    return get_success_data(api.balance_business_date(business_date_id, headers))


def close_business_date(
    api: NightAuditApiClient, business_date_id: str, headers: Headers = AUDITOR
) -> Dict[str, Any]:
    return get_success_data(api.close_business_date(business_date_id, headers))


def read_business_date(
    api: NightAuditApiClient, business_date_id: str, headers: Headers = AUDITOR
) -> Dict[str, Any]:
    return get_success_data(api.get_business_date(business_date_id, headers))


def business_date_version(
    api: NightAuditApiClient, business_date_id: str, headers: Headers = AUDITOR
) -> int:
    return read_business_date(api, business_date_id, headers)["version"]


def drive_to_room_posting(api: NightAuditApiClient, business_date_id: str) -> Dict[str, Any]:
    return post_room_and_tax(api, business_date_id)


def drive_to_charges_sealed(api: NightAuditApiClient, business_date_id: str) -> Dict[str, Any]:
    post_room_and_tax(api, business_date_id)
    return seal_charges(api, business_date_id)


def drive_to_settlement_review(api: NightAuditApiClient, business_date_id: str) -> Dict[str, Any]:
    drive_to_charges_sealed(api, business_date_id)
    return verify_settlements(api, business_date_id)


def create_report(
    api: NightAuditApiClient,
    business_date_id: str,
    recipient_role_list: Optional[List[str]] = None,
    headers: Headers = REVENUE_MANAGER,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a revenue report, reading the current business-date version first."""
    version = business_date_version(api, business_date_id)
    payload = f.build_revenue_report_payload(
        business_date_id, version, recipient_role_list, **overrides
    )
    return get_success_data(api.create_revenue_report(payload, headers))


def distribute_report(
    api: NightAuditApiClient,
    report_id: str,
    headers: Headers = REVENUE_MANAGER,
    payload: Optional[Payload] = None,
) -> Dict[str, Any]:
    return get_success_data(api.distribute_revenue_report(report_id, headers, payload))


def distributed_report(
    api: NightAuditApiClient,
    business_date_id: str,
    recipient_role_list: Optional[List[str]] = None,
) -> Dict[str, Any]:
    report = create_report(api, business_date_id, recipient_role_list)
    return distribute_report(api, report["id"])


def drive_to_balanced(api: NightAuditApiClient, business_date_id: str) -> Dict[str, Any]:
    """Walk a date to BALANCED, distributing a report on the way so it can close."""
    drive_to_settlement_review(api, business_date_id)
    distributed_report(api, business_date_id)
    return balance_business_date(api, business_date_id)


def drive_to_closed(api: NightAuditApiClient, business_date_id: str) -> Dict[str, Any]:
    drive_to_balanced(api, business_date_id)
    return close_business_date(api, business_date_id)


def drive_to_reopened(api: NightAuditApiClient, business_date_id: str) -> Dict[str, Any]:
    drive_to_closed(api, business_date_id)
    return get_success_data(api.reopen_business_date(business_date_id, CONTROLLER))


def tie_out_period(
    api: NightAuditApiClient,
    period_id: str,
    gl_control_total_amount: float,
    headers: Headers = CONTROLLER,
) -> Dict[str, Any]:
    return get_success_data(
        api.tie_out_period(
            period_id, f.build_tie_out_payload(gl_control_total_amount), headers
        )
    )


# ---------------------------------------------------------------------------
# tier 5 - named scenarios
# ---------------------------------------------------------------------------


@dataclass
class FolioScenario:
    """A standard property with one business date and one in-house folio."""

    property_id: str
    business_date_id: str
    accounting_period_id: str
    business_date: str
    folio_id: str
    folio_row: Dict[str, Any] = field(default_factory=dict)


def folio_scenario(
    api: NightAuditApiClient,
    clock: str = "2026-08-01T09:00:00.000Z",
    contracted_rate_amount: float = 200.00,
    property_overrides: Optional[Payload] = None,
    date_overrides: Optional[Payload] = None,
    folio_overrides: Optional[Payload] = None,
) -> FolioScenario:
    base = standard_property(
        api,
        clock=clock,
        property_overrides=property_overrides,
        date_overrides=date_overrides,
    )
    folio = in_house_folio(
        api,
        base,
        contracted_rate_amount=contracted_rate_amount,
        **(folio_overrides or {}),
    )
    return FolioScenario(
        property_id=base.property_id,
        business_date_id=base.business_date_id,
        accounting_period_id=base.accounting_period_id,
        business_date=base.business_date,
        folio_id=folio["id"],
        folio_row=folio,
    )


def room_posted_folio_scenario(
    api: NightAuditApiClient, **kwargs: Any
) -> FolioScenario:
    """One in-house 200.00 folio whose room and tax have been posted.

    The folio then reads charges 217.75 / credits 0.00 / balance 217.75 and the
    business date sits in ROOM_POSTING.
    """
    scenario = folio_scenario(api, **kwargs)
    post_room_and_tax(api, scenario.business_date_id)
    return scenario


def sealed_folio_scenario(api: NightAuditApiClient, **kwargs: Any) -> FolioScenario:
    """One in-house 200.00 folio on a date driven to CHARGES_SEALED."""
    scenario = folio_scenario(api, **kwargs)
    drive_to_charges_sealed(api, scenario.business_date_id)
    return scenario


@dataclass
class OutletScenario:
    """A standard property with one business date and one active outlet."""

    property_id: str
    business_date_id: str
    accounting_period_id: str
    business_date: str
    outlet_id: str
    outlet_row: Dict[str, Any] = field(default_factory=dict)

    @property
    def manager(self) -> Headers:
        """Headers for the OutletManager who is this outlet."""
        return make_outlet_manager_headers(self.outlet_id)


def outlet_scenario(
    api: NightAuditApiClient,
    clock: str = "2026-08-01T20:00:00.000Z",
    requires_shift_settlement: bool = True,
    property_overrides: Optional[Payload] = None,
    date_overrides: Optional[Payload] = None,
    outlet_overrides: Optional[Payload] = None,
) -> OutletScenario:
    base = standard_property(
        api,
        clock=clock,
        property_overrides=property_overrides,
        date_overrides=date_overrides,
    )
    outlet = create_outlet(
        api,
        base.property_id,
        requires_shift_settlement=requires_shift_settlement,
        **(outlet_overrides or {}),
    )
    return OutletScenario(
        property_id=base.property_id,
        business_date_id=base.business_date_id,
        accounting_period_id=base.accounting_period_id,
        business_date=base.business_date,
        outlet_id=outlet["id"],
        outlet_row=outlet,
    )


def closed_cash_ticket(
    api: NightAuditApiClient,
    scenario: OutletScenario,
    gross_amount: float = 120.00,
    transmitted_at: str = "2026-08-01T18:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A CASH ticket closed inside the standard [14:00, 22:00) shift window.

    At gross 120.00 the standard property prices it to a total of 150.45.
    """
    ticket = create_outlet_ticket(
        api,
        scenario.outlet_id,
        scenario.business_date_id,
        gross_amount,
        opened_at="2026-08-01T17:30:00.000Z",
        **overrides,
    )
    return close_outlet_ticket(api, ticket["id"], scenario.outlet_id, transmitted_at)


def declared_batch(
    api: NightAuditApiClient,
    scenario: OutletScenario,
    declared_amount: float,
    **overrides: Any,
) -> Dict[str, Any]:
    return create_settlement_batch(
        api, scenario.business_date_id, scenario.outlet_id, declared_amount, **overrides
    )


def flagged_batch_scenario(
    api: NightAuditApiClient, declared_amount: float = 225.68
) -> Dict[str, Any]:
    """An outlet with one closed 120.00 CASH ticket and one over-declared batch,
    on a date driven to SETTLEMENT_REVIEW so the batch has been reconciled."""
    scenario = outlet_scenario(api)
    closed_cash_ticket(api, scenario)
    batch = declared_batch(api, scenario, declared_amount)
    drive_to_settlement_review(api, scenario.business_date_id)
    return {"scenario": scenario, "batch_id": batch["id"]}


@dataclass
class LedgerScenario:
    property_id: str
    business_date_id: str
    accounting_period_id: str
    ledger_account_id: str


def ledger_scenario(
    api: NightAuditApiClient,
    ledger_type: str = "CITY_LEDGER",
    clock: str = "2026-08-01T09:00:00.000Z",
    **overrides: Any,
) -> LedgerScenario:
    base = standard_property(api, clock=clock)
    account = create_ledger_account(
        api, base.property_id, ledger_type, **overrides
    )
    return LedgerScenario(
        property_id=base.property_id,
        business_date_id=base.business_date_id,
        accounting_period_id=base.accounting_period_id,
        ledger_account_id=account["id"],
    )


def list_postings(
    api: NightAuditApiClient, headers: Headers = AUDITOR, **params: Any
) -> List[Dict[str, Any]]:
    body = api.list_journal_postings(headers, **params)
    return get_success_data(body)


def read_folio(
    api: NightAuditApiClient, folio_id: str, headers: Headers = FRONT_DESK
) -> Dict[str, Any]:
    return get_success_data(api.get_folio(folio_id, headers))


def read_allowance(
    api: NightAuditApiClient, allowance_id: str, headers: Headers = AUDITOR
) -> Dict[str, Any]:
    return get_success_data(api.get_allowance(allowance_id, headers))


def read_batch(
    api: NightAuditApiClient, batch_id: str, headers: Headers = AUDITOR
) -> Dict[str, Any]:
    return get_success_data(api.get_settlement_batch(batch_id, headers))


def read_ticket(
    api: NightAuditApiClient, ticket_id: str, headers: Headers = AUDITOR
) -> Dict[str, Any]:
    return get_success_data(api.get_outlet_ticket(ticket_id, headers))


def read_card_authorization(
    api: NightAuditApiClient, authorization_id: str, headers: Headers = AUDITOR
) -> Dict[str, Any]:
    return get_success_data(api.get_card_authorization(authorization_id, headers))


def read_document(
    api: NightAuditApiClient, document_id: str, headers: Headers = AUDITOR
) -> Dict[str, Any]:
    return get_success_data(api.get_authorization_document(document_id, headers))


def read_report(
    api: NightAuditApiClient, report_id: str, headers: Headers = REVENUE_MANAGER
) -> Dict[str, Any]:
    return get_success_data(api.get_revenue_report(report_id, headers))


def read_period(
    api: NightAuditApiClient, period_id: str, headers: Headers = CONTROLLER
) -> Dict[str, Any]:
    return get_success_data(api.get_accounting_period(period_id, headers))


def read_ledger_account(
    api: NightAuditApiClient, account_id: str, headers: Headers = CONTROLLER
) -> Dict[str, Any]:
    return get_success_data(api.get_ledger_account(account_id, headers))
