"""Composite state builders.

The database is empty before every test, so every fixture here builds the world
it needs from scratch through the public endpoints only - there is no seeding
back door.  Each helper returns the parsed resource (or a dict of resources) and
uses the lenient success reader internally, so a fixture never asserts the exact
status code of a preparatory step that the test under way is not about.

Ordering inside the composites is deliberate.  Rate-card creation and position
creation both increase the branch's version (PRD 3.2 and 3.4), and rate-card
creation must pin the version the branch carries at that moment, so the builders
re-read the branch immediately before they draft a card.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import OPERATORS, TEST_DEFAULTS
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
TREASURY = TEST_USERS["treasury_headers"]
MANAGER = TEST_USERS["manager_headers"]
TELLER = TEST_USERS["teller_headers"]
TELLER2 = TEST_USERS["teller2_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# --------------------------------------------------------------------------- #
# Logical clock (PRD 2.4)                                                      #
# --------------------------------------------------------------------------- #
def set_clock(api: ApiClient, current_utc: str, headers: Optional[Dict] = None) -> dict:
    """Move the logical clock and return {current_utc, expired_contract_count}."""
    return get_success_data(api.set_clock(current_utc, headers or ADMIN))


# --------------------------------------------------------------------------- #
# Static furniture (PRD 3.1)                                                   #
# --------------------------------------------------------------------------- #
def register_branch(api: ApiClient, headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api.create_branch(f.create_branch_payload(**overrides), headers or ADMIN)
    )


def register_currency(
    api: ApiClient, payload: Optional[dict] = None, headers: Optional[Dict] = None, **overrides
) -> dict:
    body = payload if payload is not None else f.create_currency_payload()
    if overrides:
        body = dict(body)
        body.update(overrides)
    return get_success_data(api.create_currency(body, headers or ADMIN))


def register_route(api: ApiClient, headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api.create_armored_route(f.create_armored_route_payload(**overrides), headers or ADMIN)
    )


def read_branch(api: ApiClient, branch_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.get_branch(branch_id, headers or ADMIN))


def branch_version(api: ApiClient, branch_id: str) -> int:
    return read_branch(api, branch_id)["version"]


def read_customer(api: ApiClient, customer_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.get_customer(customer_id, headers or COMPLIANCE))


def customer_version(api: ApiClient, customer_id: str) -> int:
    return read_customer(api, customer_id)["version"]


def read_position(api: ApiClient, position_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.get_inventory_position(position_id, headers or MANAGER))


def read_transaction(api: ApiClient, txn_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.get_exchange_transaction(txn_id, headers or TELLER))


def read_contract(api: ApiClient, contract_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.get_buyback_contract(contract_id, headers or TELLER))


def read_shipment(api: ApiClient, shipment_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.get_cash_shipment(shipment_id, headers or TREASURY))


def read_plan(api: ApiClient, plan_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.get_inventory_plan(plan_id, headers or MANAGER))


# --------------------------------------------------------------------------- #
# Wholesale feed and the board (PRD 3.2)                                       #
# --------------------------------------------------------------------------- #
def record_wholesale_rate(
    api: ApiClient, headers: Optional[Dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.create_wholesale_rate(f.create_wholesale_rate_payload(**overrides), headers or TREASURY)
    )


def draft_rate_card(
    api: ApiClient,
    branch_id: str,
    wholesale_rate_id: str,
    expected_branch_version: Optional[int] = None,
    headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    pin = (
        expected_branch_version
        if expected_branch_version is not None
        else branch_version(api, branch_id)
    )
    payload = f.create_rate_card_payload(branch_id, wholesale_rate_id, pin, **overrides)
    return get_success_data(api.create_rate_card(payload, headers or TREASURY))


def publish_rate_card(api: ApiClient, card_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.publish_rate_card(card_id, headers or TREASURY))


def published_rate_card(
    api: ApiClient,
    branch_id: str,
    wholesale_rate_id: str,
    expected_branch_version: Optional[int] = None,
    headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    """Draft a card and publish it, returning the published row."""
    card = draft_rate_card(
        api,
        branch_id,
        wholesale_rate_id,
        expected_branch_version,
        headers,
        **overrides,
    )
    return publish_rate_card(api, card["id"], headers)


def read_board(
    api: ApiClient,
    branch_id: str,
    headers: Optional[Dict] = None,
    params: Optional[Dict] = None,
) -> dict:
    return get_success_data(api.get_rate_board(branch_id, headers or TELLER, params))


# --------------------------------------------------------------------------- #
# Positions (PRD 3.4)                                                          #
# --------------------------------------------------------------------------- #
def open_position(
    api: ApiClient,
    branch_id: str,
    currency_code: str = "EUR",
    opening_denomination_mix: Optional[List[dict]] = None,
    headers: Optional[Dict] = None,
) -> dict:
    payload = f.create_inventory_position_payload(
        branch_id, currency_code, opening_denomination_mix
    )
    return get_success_data(api.create_inventory_position(payload, headers or MANAGER))


# --------------------------------------------------------------------------- #
# Customers (PRD 3.5)                                                          #
# --------------------------------------------------------------------------- #
def onboard_customer(api: ApiClient, headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api.create_customer(f.create_customer_payload(**overrides), headers or TELLER)
    )


def identified_customer(api: ApiClient, headers: Optional[Dict] = None, **overrides) -> dict:
    """A customer carrying a complete, unexpired document bundle so that the
    identification gates of PRD 3.5 never interfere with the deal under test."""
    bundle = {
        "id_document_type": "PASSPORT",
        "id_document_number": "P-4471902",
        "id_document_expiry": "2031-01-01T00:00:00Z",
        "travel_document_reference": "BP-88213",
    }
    bundle.update(overrides)
    return onboard_customer(api, headers, **bundle)


def apply_hold(
    api: ApiClient, customer_id: str, reason: Optional[str] = None, headers: Optional[Dict] = None
) -> dict:
    return get_success_data(
        api.compliance_hold(
            customer_id, f.compliance_hold_payload("APPLY", reason), headers or COMPLIANCE
        )
    )


def release_hold(
    api: ApiClient, customer_id: str, reason: Optional[str] = None, headers: Optional[Dict] = None
) -> dict:
    return get_success_data(
        api.compliance_hold(
            customer_id, f.compliance_hold_payload("RELEASE", reason), headers or COMPLIANCE
        )
    )


def decide_compliance(
    api: ApiClient,
    txn_id: str,
    decision: str,
    note: Optional[str] = None,
    headers: Optional[Dict] = None,
) -> dict:
    return get_success_data(
        api.compliance_decision(
            txn_id, f.compliance_decision_payload(decision, note), headers or COMPLIANCE
        )
    )


# --------------------------------------------------------------------------- #
# The canonical trading world                                                  #
# --------------------------------------------------------------------------- #
def trading_world(
    api: ApiClient,
    vault_limit_usd_cents: Optional[int] = None,
    branch_overrides: Optional[dict] = None,
    currency_payload: Optional[dict] = None,
    mid_rate_micros: Optional[int] = None,
    wholesale_overrides: Optional[dict] = None,
    card_overrides: Optional[dict] = None,
    position_mix: Optional[List[dict]] = None,
    with_position: bool = True,
    customer_overrides: Optional[dict] = None,
    identified: bool = True,
) -> dict:
    """One branch trading one currency: branch, currency profile, wholesale quote,
    published rate card, seeded inventory position and an on-boarded customer.

    Returns the six rows plus the branch as it reads after the position cascade.
    """
    branch_payload = dict(branch_overrides or {})
    if vault_limit_usd_cents is not None:
        branch_payload["vault_limit_usd_cents"] = vault_limit_usd_cents
    branch = register_branch(api, **branch_payload)

    currency = register_currency(api, currency_payload)
    code = currency["iso_code"]

    rate_payload = {"currency_code": code}
    if mid_rate_micros is not None:
        rate_payload["mid_rate_micros"] = mid_rate_micros
    rate_payload.update(wholesale_overrides or {})
    wholesale = record_wholesale_rate(api, **rate_payload)

    card_payload = {"currency_code": code, "board_display_label": f"{code} board line"}
    card_payload.update(card_overrides or {})
    card = published_rate_card(api, branch["id"], wholesale["id"], **card_payload)

    position = None
    if with_position:
        position = open_position(api, branch["id"], code, position_mix)

    customer = (
        identified_customer(api, **(customer_overrides or {}))
        if identified
        else onboard_customer(api, **(customer_overrides or {}))
    )

    return {
        "branch": read_branch(api, branch["id"]),
        "branch_at_creation": branch,
        "currency": currency,
        "wholesale": wholesale,
        "card": card,
        "position": position,
        "customer": customer,
    }


def add_currency_line(
    api: ApiClient,
    world: dict,
    currency_payload: dict,
    mid_rate_micros: int,
    position_mix: Optional[List[dict]] = None,
    card_overrides: Optional[dict] = None,
    wholesale_overrides: Optional[dict] = None,
) -> dict:
    """Add a second currency - profile, quote, published card and position - to an
    existing world, returning that line's rows."""
    currency = register_currency(api, currency_payload)
    code = currency["iso_code"]
    rate_payload = {"currency_code": code, "mid_rate_micros": mid_rate_micros}
    rate_payload.update(wholesale_overrides or {})
    wholesale = record_wholesale_rate(api, **rate_payload)
    card_payload = {"currency_code": code, "board_display_label": f"{code} board line"}
    card_payload.update(card_overrides or {})
    card = published_rate_card(api, world["branch"]["id"], wholesale["id"], **card_payload)
    position = (
        open_position(api, world["branch"]["id"], code, position_mix)
        if position_mix is not None
        else None
    )
    return {
        "currency": currency,
        "wholesale": wholesale,
        "card": card,
        "position": position,
    }


# --------------------------------------------------------------------------- #
# The counter: quote, authorize, settle (PRD 3.5)                              #
# --------------------------------------------------------------------------- #
def quote_deal(
    api: ApiClient,
    world: dict,
    direction: str = "SELL_FX_TO_CUSTOMER",
    denominations: Optional[List[dict]] = None,
    headers: Optional[Dict] = None,
    branch_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    rate_card_id: Optional[str] = None,
    currency_code: Optional[str] = None,
    **overrides,
) -> dict:
    payload = f.create_exchange_transaction_payload(
        branch_id or world["branch"]["id"],
        customer_id or world["customer"]["id"],
        rate_card_id or world["card"]["id"],
        currency_code or world["currency"]["iso_code"],
        direction,
        denominations,
        **overrides,
    )
    return get_success_data(api.create_exchange_transaction(payload, headers or TELLER))


def authorize_deal(api: ApiClient, txn_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.authorize_transaction(txn_id, headers or TELLER))


def settle_deal(api: ApiClient, txn_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.settle_transaction(txn_id, headers or TELLER))


def authorized_deal(
    api: ApiClient,
    world: dict,
    direction: str = "SELL_FX_TO_CUSTOMER",
    denominations: Optional[List[dict]] = None,
    headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    txn = quote_deal(api, world, direction, denominations, headers, **overrides)
    return authorize_deal(api, txn["id"], headers)


def settled_deal(
    api: ApiClient,
    world: dict,
    direction: str = "SELL_FX_TO_CUSTOMER",
    denominations: Optional[List[dict]] = None,
    headers: Optional[Dict] = None,
    settle_headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    """Quote, authorize and settle one deal, returning the settled transaction."""
    txn = quote_deal(api, world, direction, denominations, headers, **overrides)
    authorize_deal(api, txn["id"], headers)
    return settle_deal(api, txn["id"], settle_headers or headers)


def voided_deal(
    api: ApiClient,
    world: dict,
    direction: str = "SELL_FX_TO_CUSTOMER",
    denominations: Optional[List[dict]] = None,
    headers: Optional[Dict] = None,
) -> dict:
    txn = quote_deal(api, world, direction, denominations, headers)
    return get_success_data(
        api.void_transaction(txn["id"], f.void_payload(), headers or TELLER)
    )


def reverse_deal(
    api: ApiClient, txn_id: str, headers: Optional[Dict] = None, reason: Optional[str] = None
) -> dict:
    payload = f.reverse_payload(reason) if reason is not None else f.reverse_payload()
    return get_success_data(api.reverse_transaction(txn_id, payload, headers or MANAGER))


# --------------------------------------------------------------------------- #
# Corridors and stocking plans (PRD 3.3)                                       #
# --------------------------------------------------------------------------- #
def register_corridor(api: ApiClient, headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api.create_travel_corridor(f.create_travel_corridor_payload(**overrides), headers or TREASURY)
    )


def draft_plan(
    api: ApiClient,
    branch_id: str,
    travel_corridor_id: str,
    season_days: int = 10,
    target_lines: Optional[List[dict]] = None,
    headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    payload = f.create_inventory_plan_payload(
        branch_id, travel_corridor_id, season_days, target_lines, **overrides
    )
    return get_success_data(api.create_inventory_plan(payload, headers or MANAGER))


def submit_plan(
    api: ApiClient,
    plan_id: str,
    target_lines: Optional[List[dict]] = None,
    headers: Optional[Dict] = None,
) -> dict:
    payload = {} if target_lines is None else {"target_lines": target_lines}
    return get_success_data(api.submit_inventory_plan(plan_id, payload, headers or MANAGER))


def review_plan(
    api: ApiClient,
    plan_id: str,
    decision: str = "APPROVE",
    review_note: Optional[str] = None,
    headers: Optional[Dict] = None,
) -> dict:
    return get_success_data(
        api.review_inventory_plan(
            plan_id, f.review_plan_payload(decision, review_note), headers or TREASURY
        )
    )


def activate_plan(api: ApiClient, plan_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.activate_inventory_plan(plan_id, headers or MANAGER))


def active_plan(
    api: ApiClient,
    branch_id: str,
    travel_corridor_id: str,
    target_lines: List[dict],
    season_days: int = 10,
    manager_headers: Optional[Dict] = None,
    treasury_headers: Optional[Dict] = None,
) -> dict:
    """Drive one plan the whole way: DRAFT, SUBMITTED, APPROVED, ACTIVE.

    The reviewer is a different operator from the submitter, so the paired-step
    rule of PRD 3.3 is satisfied.
    """
    plan = draft_plan(
        api, branch_id, travel_corridor_id, season_days, target_lines, manager_headers
    )
    submit_plan(api, plan["id"], target_lines, manager_headers)
    review_plan(api, plan["id"], "APPROVE", None, treasury_headers)
    return activate_plan(api, plan["id"], manager_headers)


# --------------------------------------------------------------------------- #
# Buy-back guarantees (PRD 3.7)                                                #
# --------------------------------------------------------------------------- #
def issue_contract(
    api: ApiClient,
    customer_id: str,
    origin_transaction_id: str,
    expected_customer_version: Optional[int] = None,
    headers: Optional[Dict] = None,
) -> dict:
    pin = (
        expected_customer_version
        if expected_customer_version is not None
        else customer_version(api, customer_id)
    )
    payload = f.create_buyback_contract_payload(customer_id, origin_transaction_id, pin)
    return get_success_data(api.create_buyback_contract(payload, headers or TELLER))


def redeem_contract(
    api: ApiClient,
    contract_id: str,
    returned_denominations: List[dict],
    headers: Optional[Dict] = None,
) -> dict:
    return get_success_data(
        api.redeem_buyback_contract(
            contract_id, f.redeem_payload(returned_denominations), headers or TELLER
        )
    )


def cancel_contract(
    api: ApiClient, contract_id: str, reason: Optional[str] = None, headers: Optional[Dict] = None
) -> dict:
    payload = (
        f.cancel_contract_payload(reason) if reason is not None else f.cancel_contract_payload()
    )
    return get_success_data(api.cancel_buyback_contract(contract_id, payload, headers or MANAGER))


def sale_with_contract(
    api: ApiClient,
    world: dict,
    denominations: Optional[List[dict]] = None,
    headers: Optional[Dict] = None,
) -> dict:
    """A settled sale to the customer plus the buy-back contract written on it."""
    txn = settled_deal(api, world, "SELL_FX_TO_CUSTOMER", denominations, headers)
    contract = issue_contract(api, txn["customer_id"], txn["id"], None, headers)
    return {"transaction": read_transaction(api, txn["id"], headers), "contract": contract}


# --------------------------------------------------------------------------- #
# Detained notes (PRD 3.8)                                                     #
# --------------------------------------------------------------------------- #
def detain_notes(
    api: ApiClient,
    branch_id: str,
    inventory_position_id: str,
    exchange_transaction_id: str,
    denomination_minor_units: int = 10000,
    note_count: int = 1,
    defect_type: str = "DAMAGED",
    headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    payload = f.create_note_assessment_payload(
        branch_id,
        inventory_position_id,
        exchange_transaction_id,
        denomination_minor_units,
        note_count,
        defect_type,
        **overrides,
    )
    return get_success_data(api.create_note_assessment(payload, headers or TELLER))


def assess_notes(
    api: ApiClient,
    assessment_id: str,
    outcome: str,
    note: Optional[str] = None,
    headers: Optional[Dict] = None,
) -> dict:
    return get_success_data(
        api.assess_note_assessment(
            assessment_id, f.assess_payload(outcome, note), headers or MANAGER
        )
    )


# --------------------------------------------------------------------------- #
# Regulatory reports (PRD 3.6) - only ever discovered through the list         #
# --------------------------------------------------------------------------- #
def list_reports(
    api: ApiClient, params: Optional[Dict] = None, headers: Optional[Dict] = None
) -> List[dict]:
    return get_success_data(api.list_compliance_reports(headers or COMPLIANCE, params))


def only_report(
    api: ApiClient, params: Optional[Dict] = None, headers: Optional[Dict] = None
) -> dict:
    rows = list_reports(api, params, headers)
    assert len(rows) == 1, f"expected exactly one report for {params}, got {len(rows)}"
    return rows[0]


def file_report(
    api: ApiClient,
    report_id: str,
    filing_reference: str = "REG-ACK-0001",
    headers: Optional[Dict] = None,
) -> dict:
    return get_success_data(
        api.file_compliance_report(
            report_id, f.file_report_payload(filing_reference), headers or COMPLIANCE
        )
    )


def amend_report(
    api: ApiClient,
    report_id: str,
    amendment_reason: Optional[str] = "restated aggregate",
    headers: Optional[Dict] = None,
) -> dict:
    return get_success_data(
        api.amend_compliance_report(
            report_id, f.amend_report_payload(amendment_reason), headers or COMPLIANCE
        )
    )


# --------------------------------------------------------------------------- #
# Cash logistics (PRD 3.9)                                                     #
# --------------------------------------------------------------------------- #
def raise_shipment(
    api: ApiClient,
    branch_id: str,
    currency_code: str = "EUR",
    direction: str = "REPATRIATION",
    manifest_denominations: Optional[List[dict]] = None,
    headers: Optional[Dict] = None,
) -> dict:
    payload = f.create_cash_shipment_payload(
        branch_id, currency_code, direction, manifest_denominations
    )
    return get_success_data(api.create_cash_shipment(payload, headers or TREASURY))


def schedule_shipment(
    api: ApiClient,
    shipment_id: str,
    armored_route_id: str,
    window_start: str,
    window_end: str,
    headers: Optional[Dict] = None,
) -> dict:
    return get_success_data(
        api.schedule_cash_shipment(
            shipment_id,
            f.schedule_shipment_payload(armored_route_id, window_start, window_end),
            headers or TREASURY,
        )
    )


def dispatch_shipment(api: ApiClient, shipment_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.dispatch_cash_shipment(shipment_id, headers or TREASURY))


def arrive_shipment(
    api: ApiClient,
    shipment_id: str,
    delivered_denominations: List[dict],
    headers: Optional[Dict] = None,
) -> dict:
    return get_success_data(
        api.arrive_cash_shipment(
            shipment_id, f.arrive_payload(delivered_denominations), headers or MANAGER
        )
    )


def reconcile_shipment(api: ApiClient, shipment_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api.reconcile_cash_shipment(shipment_id, headers or TREASURY))


def list_shipments(
    api: ApiClient, params: Optional[Dict] = None, headers: Optional[Dict] = None
) -> List[dict]:
    return get_success_data(api.list_cash_shipments(headers or TREASURY, params))


def auto_repatriation_shipment(api: ApiClient, branch_id: str) -> dict:
    """The single automatically raised repatriation shipment of a branch."""
    rows = list_shipments(
        api, {"branch_id": branch_id, "auto_generated": "true", "direction": "REPATRIATION"}
    )
    assert len(rows) == 1, f"expected exactly one automatic repatriation, got {len(rows)}"
    return rows[0]


def in_transit_shipment(
    api: ApiClient,
    branch_id: str,
    route_id: str,
    currency_code: str = "EUR",
    direction: str = "REPLENISHMENT",
    manifest_denominations: Optional[List[dict]] = None,
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-08-01T02:00:00Z",
) -> dict:
    """Raise, schedule and dispatch one shipment so it is ready to arrive."""
    shipment = raise_shipment(
        api, branch_id, currency_code, direction, manifest_denominations
    )
    schedule_shipment(api, shipment["id"], route_id, window_start, window_end)
    return dispatch_shipment(api, shipment["id"])
