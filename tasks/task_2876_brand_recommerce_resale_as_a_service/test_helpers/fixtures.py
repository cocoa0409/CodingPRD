"""Composite setup helpers.

Every test starts against an empty database, so every helper here builds its
preconditions from scratch using only PRD endpoints. Setup calls go through the
lenient ``get_success_data`` validator so a broken precondition reports itself
as a setup failure rather than as a confusing assertion.

Two conventions matter throughout:

* A unit that will be refurbished always originates from an ``IN_STORE``
  trade-in, because a refurbishment bay must belong to the store that took
  physical custody of that unit's trade-in — a mail-in trade-in has no store.
* A ``Customer`` caller's identity is a real ``Customer.id``, so every
  ownership-gated call uses ``make_customer_headers(customer["id"])``.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BAY_CLEANING,
    CHANNEL_RESALE_MP,
    CREDIT_POLICY_CORE,
    GRADE_POLICY_OUTERWEAR_B,
    STORE_ST_01,
    TEST_DEFAULTS,
    WINDOW_09_11,
)
from .factories import (
    appeal_trade_in_payload,
    authenticate_trade_in_payload,
    create_channel_payload,
    create_credit_policy_payload,
    create_customer_payload,
    create_diversion_report_payload,
    create_grade_policy_payload,
    create_markdown_campaign_payload,
    create_refurb_bay_payload,
    create_refurb_order_payload,
    create_refurb_task_payload,
    create_resale_order_payload,
    create_store_location_payload,
    create_trade_in_payload,
    disposition_payload,
    list_unit_payload,
    qc_decision_payload,
    return_request_payload,
    settle_return_payload,
)
from .test_users import (
    ADMIN,
    AUTH1,
    INTAKE,
    MERCH,
    TECH1,
    TECH2,
    make_customer_headers,
)


# ==========================================================================
# Clock
# ==========================================================================
def set_clock(current_utc: str, headers: Optional[Dict[str, str]] = None) -> dict:
    """Move the logical clock and return the echoed payload."""
    return get_success_data(api_client.set_clock(current_utc, headers or ADMIN))


# ==========================================================================
# Configuration primitives (ProgramAdmin surface)
# ==========================================================================
def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def patch_customer(customer_id: str, payload: Dict[str, Any]) -> dict:
    return get_success_data(api_client.patch_customer(customer_id, payload, ADMIN))


def create_grade_policy(spec: Optional[Dict[str, Any]] = None, **overrides) -> dict:
    body = dict(spec or GRADE_POLICY_OUTERWEAR_B)
    body.update(overrides)
    return get_success_data(
        api_client.create_grade_policy(create_grade_policy_payload(**body), ADMIN)
    )


def create_credit_policy(spec: Optional[Dict[str, Any]] = None, **overrides) -> dict:
    body = dict(spec or CREDIT_POLICY_CORE)
    body.update(overrides)
    return get_success_data(
        api_client.create_credit_policy(create_credit_policy_payload(**body), ADMIN)
    )


def create_store_location(spec: Optional[Dict[str, Any]] = None, **overrides) -> dict:
    body = dict(spec or STORE_ST_01)
    body.update(overrides)
    return get_success_data(
        api_client.create_store_location(create_store_location_payload(**body), ADMIN)
    )


def create_refurb_bay(
    store_location_id: str, spec: Optional[Dict[str, Any]] = None, **overrides
) -> dict:
    body = dict(spec or BAY_CLEANING)
    body.update(overrides)
    return get_success_data(
        api_client.create_refurb_bay(
            store_location_id, create_refurb_bay_payload(**body), ADMIN
        )
    )


def create_channel(spec: Optional[Dict[str, Any]] = None, **overrides) -> dict:
    body = dict(spec or CHANNEL_RESALE_MP)
    body.update(overrides)
    return get_success_data(
        api_client.create_channel(create_channel_payload(**body), ADMIN)
    )


def pause_channel(channel_id: str) -> dict:
    return get_success_data(api_client.patch_channel(channel_id, {"status": "PAUSED"}, ADMIN))


def close_store_location(store_location_id: str) -> dict:
    return get_success_data(
        api_client.patch_store_location(store_location_id, {"status": "CLOSED"}, ADMIN)
    )


def take_bay_out_of_service(refurb_bay_id: str) -> dict:
    return get_success_data(
        api_client.patch_refurb_bay(refurb_bay_id, {"status": "OUT_OF_SERVICE"}, ADMIN)
    )


# ==========================================================================
# Reads
# ==========================================================================
def fetch_customer(customer_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.get_customer(customer_id, headers or ADMIN))


def fetch_trade_in(trade_in_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.get_trade_in(trade_in_id, headers or ADMIN))


def fetch_unit(resale_unit_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.get_resale_unit(resale_unit_id, headers or ADMIN))


def fetch_refurb_order(refurb_order_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.get_refurb_order(refurb_order_id, headers or ADMIN)
    )


def fetch_grant(credit_grant_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.get_credit_grant(credit_grant_id, headers or ADMIN))


def fetch_order(resale_order_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.get_resale_order(resale_order_id, headers or ADMIN)
    )


def fetch_campaign(campaign_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.get_markdown_campaign(campaign_id, headers or MERCH)
    )


def fetch_report(report_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.get_diversion_report(report_id, headers or ADMIN)
    )


def units_of_trade_in(trade_in_id: str, headers: Optional[Dict[str, str]] = None) -> List[dict]:
    return get_success_data(
        api_client.list_resale_units(headers or ADMIN, {"trade_in_id": trade_in_id})
    )


def grants_of_trade_in(trade_in_id: str, headers: Optional[Dict[str, str]] = None) -> List[dict]:
    return get_success_data(
        api_client.list_credit_grants(headers or ADMIN, {"trade_in_id": trade_in_id})
    )


def unit_of_trade_in(trade_in_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    rows = units_of_trade_in(trade_in_id, headers)
    assert rows, f"Setup step failed: no resale unit for trade-in {trade_in_id}"
    return rows[0]


def grant_of_trade_in(trade_in_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    rows = grants_of_trade_in(trade_in_id, headers)
    assert rows, f"Setup step failed: no credit grant for trade-in {trade_in_id}"
    return rows[0]


def grant_ledger_entries(
    credit_grant_id: str, headers: Optional[Dict[str, str]] = None, params=None
) -> List[dict]:
    return get_success_data(
        api_client.list_credit_grant_ledger_entries(
            credit_grant_id, headers or ADMIN, params
        )
    )


def order_ledger_entries(
    resale_order_id: str, headers: Optional[Dict[str, str]] = None, params=None
) -> List[dict]:
    return get_success_data(
        api_client.list_resale_order_ledger_entries(
            resale_order_id, headers or ADMIN, params
        )
    )


# ==========================================================================
# Intake / grading / disposition primitives
# ==========================================================================
def create_trade_in(
    customer: dict,
    channel: str = "MAIL_IN",
    store_location_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> dict:
    """Submit a trade-in as its own participant unless headers say otherwise."""
    payload = create_trade_in_payload(
        customer["id"], channel=channel, store_location_id=store_location_id, **overrides
    )
    return get_success_data(
        api_client.create_trade_in(
            payload, headers or make_customer_headers(customer["id"])
        )
    )


def receive_trade_in(trade_in_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.receive_trade_in(trade_in_id, headers or INTAKE))


def authenticate_trade_in(
    trade_in_id: str,
    authenticity_result: str = "GENUINE",
    assessed_grade: Optional[str] = "B",
    headers: Optional[Dict[str, str]] = None,
) -> dict:
    return get_success_data(
        api_client.authenticate_trade_in(
            trade_in_id,
            authenticate_trade_in_payload(authenticity_result, assessed_grade),
            headers or AUTH1,
        )
    )


def appeal_trade_in(
    trade_in_id: str, customer: dict, headers: Optional[Dict[str, str]] = None, **overrides
) -> dict:
    return get_success_data(
        api_client.appeal_trade_in(
            trade_in_id,
            appeal_trade_in_payload(**overrides),
            headers or make_customer_headers(customer["id"]),
        )
    )


def disposition_trade_in(
    trade_in_id: str,
    decision: str = "ACCEPT",
    ownership_treatment: Optional[str] = "OWNED_INVENTORY",
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.disposition_trade_in(
            trade_in_id,
            disposition_payload(decision, ownership_treatment, **overrides),
            headers or AUTH1,
        )
    )


# ==========================================================================
# Tier 2: the programme estate
# ==========================================================================
def setup_estate(
    grade_policies: Sequence[Dict[str, Any]] = (GRADE_POLICY_OUTERWEAR_B,),
    credit_policy: Optional[Dict[str, Any]] = CREDIT_POLICY_CORE,
    store: Optional[Dict[str, Any]] = STORE_ST_01,
    bays: Sequence[Dict[str, Any]] = (BAY_CLEANING,),
    channels: Sequence[Dict[str, Any]] = (CHANNEL_RESALE_MP,),
) -> Dict[str, Any]:
    """Configuration estate: tier policies, brand-currency policy, store, bays, channels.

    Returns a dict whose singular keys (``grade_policy``, ``bay``, ``channel``)
    hold the first row of each collection for the common single-row case.
    """
    estate: Dict[str, Any] = {
        "grade_policies": [create_grade_policy(spec) for spec in grade_policies],
        "credit_policy": create_credit_policy(credit_policy) if credit_policy else None,
        "store": create_store_location(store) if store else None,
        "bays": [],
        "channels": [create_channel(spec) for spec in channels],
    }
    if estate["store"] is not None:
        estate["bays"] = [
            create_refurb_bay(estate["store"]["id"], spec) for spec in bays
        ]
    estate["grade_policy"] = estate["grade_policies"][0] if estate["grade_policies"] else None
    estate["bay"] = estate["bays"][0] if estate["bays"] else None
    estate["channel"] = estate["channels"][0] if estate["channels"] else None
    return estate


# ==========================================================================
# Tier 3: accepted trade-in → grant + unit
# ==========================================================================
def setup_accepted_trade_in(
    estate: Dict[str, Any],
    customer: Optional[dict] = None,
    email: str = "ava@example.com",
    full_name: str = "Ava Reyes",
    loyalty_tier: Optional[str] = None,
    channel: str = "IN_STORE",
    product_category: str = "OUTERWEAR",
    declared_grade: str = "B",
    assessed_grade: Optional[str] = "B",
    authenticity_result: str = "GENUINE",
    msrp_minor: int = TEST_DEFAULTS["OUTERWEAR_MSRP_MINOR"],
    item_mass_grams: int = TEST_DEFAULTS["OUTERWEAR_MASS_GRAMS"],
    ownership_treatment: Optional[str] = "OWNED_INVENTORY",
    store: Optional[dict] = None,
) -> Dict[str, Any]:
    """Walk one item from submission to ACCEPTED and collect what it produced.

    ``channel="IN_STORE"`` is the default because an in-store item has a custody
    store, which every downstream refurbishment booking needs. Returns
    ``{"customer", "trade_in", "grant", "unit"}``; ``unit`` is None when the
    acceptance produced no unit.
    """
    if customer is None:
        overrides: Dict[str, Any] = {"email": email, "full_name": full_name}
        if loyalty_tier is not None:
            overrides["loyalty_tier"] = loyalty_tier
        customer = create_customer(**overrides)

    store_row = store if store is not None else estate.get("store")
    store_location_id = store_row["id"] if (channel == "IN_STORE" and store_row) else None

    trade_in = create_trade_in(
        customer,
        channel=channel,
        store_location_id=store_location_id,
        product_category=product_category,
        declared_grade=declared_grade,
        msrp_minor=msrp_minor,
        item_mass_grams=item_mass_grams,
    )
    receive_trade_in(trade_in["id"])
    authenticate_trade_in(
        trade_in["id"],
        authenticity_result=authenticity_result,
        assessed_grade=assessed_grade,
    )
    trade_in = disposition_trade_in(
        trade_in["id"], "ACCEPT", ownership_treatment
    )

    units = units_of_trade_in(trade_in["id"])
    grants = grants_of_trade_in(trade_in["id"])
    return {
        "customer": fetch_customer(customer["id"]),
        "trade_in": trade_in,
        "grant": grants[0] if grants else None,
        "unit": units[0] if units else None,
    }


def setup_credit_source_grant(
    estate: Dict[str, Any],
    customer: Optional[dict] = None,
    email: str = "ben@example.com",
    full_name: str = "Ben Ortiz",
    loyalty_tier: Optional[str] = None,
    product_category: str = "OUTERWEAR",
    declared_grade: str = "B",
    assessed_grade: str = "B",
    msrp_minor: int = TEST_DEFAULTS["OUTERWEAR_MSRP_MINOR"],
    item_mass_grams: int = TEST_DEFAULTS["OUTERWEAR_MASS_GRAMS"],
) -> Dict[str, Any]:
    """A mail-in trade-in accepted purely to mint brand currency for a buyer.

    The mail-in channel bonus applies here, and the unit this produces is left
    in INTAKE — it is never refurbished, so no custody store is needed.
    """
    return setup_accepted_trade_in(
        estate,
        customer=customer,
        email=email,
        full_name=full_name,
        loyalty_tier=loyalty_tier,
        channel="MAIL_IN",
        product_category=product_category,
        declared_grade=declared_grade,
        assessed_grade=assessed_grade,
        msrp_minor=msrp_minor,
        item_mass_grams=item_mass_grams,
    )


# ==========================================================================
# Refurbishment primitives
# ==========================================================================
def schedule_refurb_order(
    unit: dict,
    bay: dict,
    window: Sequence[str] = WINDOW_09_11,
    expected_resale_unit_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> dict:
    """Book a unit into a bay for a window, quoting the unit's expected version."""
    payload = create_refurb_order_payload(
        unit["id"],
        bay["id"],
        window[0],
        window[1],
        unit["version"]
        if expected_resale_unit_version is None
        else expected_resale_unit_version,
    )
    return get_success_data(api_client.create_refurb_order(payload, headers or TECH1))


def start_refurb_order(refurb_order_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.start_refurb_order(refurb_order_id, headers or TECH1)
    )


def log_refurb_task(
    refurb_order_id: str,
    task_type: str = "REPAIR",
    labor_minutes: int = 2,
    parts_cost_minor: int = 0,
    headers: Optional[Dict[str, str]] = None,
) -> dict:
    return get_success_data(
        api_client.create_refurb_task(
            refurb_order_id,
            create_refurb_task_payload(task_type, labor_minutes, parts_cost_minor),
            headers or TECH1,
        )
    )


def submit_refurb_qc(refurb_order_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.submit_refurb_order_qc(refurb_order_id, headers or TECH1)
    )


def decide_refurb_qc(
    refurb_order_id: str,
    decision: str = "PASS",
    viability_override_reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> dict:
    """Sign off QC. The default signer is the second technician, because the
    technician who performed the work may not decide their own order."""
    return get_success_data(
        api_client.decide_refurb_order_qc(
            refurb_order_id,
            qc_decision_payload(decision, viability_override_reason),
            headers or TECH2,
        )
    )


def setup_qc_pending_order(
    unit: dict,
    bay: dict,
    tasks: Iterable[Dict[str, Any]] = (),
    window: Sequence[str] = WINDOW_09_11,
    start_headers: Optional[Dict[str, str]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> dict:
    """Schedule → start → log every task line → submit for quality control."""
    order = schedule_refurb_order(unit, bay, window, headers=headers or TECH1)
    start_refurb_order(order["id"], start_headers or TECH1)
    for task in tasks:
        log_refurb_task(order["id"], headers=start_headers or TECH1, **task)
    return submit_refurb_qc(order["id"], start_headers or TECH1)


def refurbish_unit(
    unit: dict,
    bay: dict,
    tasks: Iterable[Dict[str, Any]] = (),
    window: Sequence[str] = WINDOW_09_11,
    decision: str = "PASS",
    viability_override_reason: Optional[str] = None,
    start_headers: Optional[Dict[str, str]] = None,
    qc_headers: Optional[Dict[str, str]] = None,
) -> dict:
    """Take a unit all the way through quality control. Returns the order."""
    order = setup_qc_pending_order(
        unit, bay, tasks=tasks, window=window, start_headers=start_headers
    )
    return decide_refurb_qc(
        order["id"], decision, viability_override_reason, qc_headers or TECH2
    )


# ==========================================================================
# Tier 3: a unit that has cleared quality control
# ==========================================================================
def setup_refurbished_unit(
    estate: Dict[str, Any],
    tasks: Iterable[Dict[str, Any]] = (),
    bay: Optional[dict] = None,
    window: Sequence[str] = WINDOW_09_11,
    **accepted_kwargs,
) -> Dict[str, Any]:
    """Accepted in-store trade-in → refurbishment order passed at QC.

    Returns ``{"customer", "trade_in", "grant", "unit", "refurb_order"}`` with
    ``unit`` re-read after the pass so its lifecycle and accounting states are
    the post-QC ones.
    """
    scenario = setup_accepted_trade_in(estate, **accepted_kwargs)
    target_bay = bay or estate["bay"]
    order = refurbish_unit(scenario["unit"], target_bay, tasks=tasks, window=window)
    scenario["refurb_order"] = order
    scenario["unit"] = fetch_unit(scenario["unit"]["id"])
    return scenario


# ==========================================================================
# Listing and markdown
# ==========================================================================
def list_unit(
    resale_unit_id: str, channel_id: str, headers: Optional[Dict[str, str]] = None
) -> dict:
    return get_success_data(
        api_client.list_resale_unit(
            resale_unit_id, list_unit_payload(channel_id), headers or MERCH
        )
    )


def setup_listed_unit(
    estate: Dict[str, Any],
    tasks: Iterable[Dict[str, Any]] = (),
    bay: Optional[dict] = None,
    channel: Optional[dict] = None,
    window: Sequence[str] = WINDOW_09_11,
    **accepted_kwargs,
) -> Dict[str, Any]:
    """A refurbished unit put on sale in a channel. Adds ``unit`` LISTED."""
    scenario = setup_refurbished_unit(
        estate, tasks=tasks, bay=bay, window=window, **accepted_kwargs
    )
    target_channel = channel or estate["channel"]
    scenario["unit"] = list_unit(scenario["unit"]["id"], target_channel["id"])
    scenario["channel"] = target_channel
    return scenario


def create_campaign(
    channel_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> dict:
    return get_success_data(
        api_client.create_markdown_campaign(
            create_markdown_campaign_payload(channel_id, **overrides), headers or MERCH
        )
    )


def run_campaign(campaign_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.run_markdown_cadence(campaign_id, headers or MERCH)
    )


# ==========================================================================
# Purchase and after-sale
# ==========================================================================
def place_order(
    customer: dict,
    channel: dict,
    unit: dict,
    requested_credit_minor: int = 0,
    expected_customer_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> dict:
    """Buy a listed unit as the buyer themself, quoting their live version."""
    version = (
        fetch_customer(customer["id"])["version"]
        if expected_customer_version is None
        else expected_customer_version
    )
    payload = create_resale_order_payload(
        customer["id"], channel["id"], unit["id"], requested_credit_minor, version
    )
    return get_success_data(
        api_client.create_resale_order(
            payload, headers or make_customer_headers(customer["id"])
        )
    )


def fulfill_order(resale_order_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.fulfill_resale_order(resale_order_id, headers or MERCH)
    )


def request_return(
    resale_order_id: str,
    customer: dict,
    reason_type: str = "BUYER_REMORSE",
    headers: Optional[Dict[str, str]] = None,
) -> dict:
    return get_success_data(
        api_client.request_resale_order_return(
            resale_order_id,
            return_request_payload(reason_type),
            headers or make_customer_headers(customer["id"]),
        )
    )


def settle_return(
    resale_order_id: str, resolution: str = "REFUND", headers: Optional[Dict[str, str]] = None
) -> dict:
    return get_success_data(
        api_client.settle_resale_order_return(
            resale_order_id, settle_return_payload(resolution), headers or MERCH
        )
    )


def setup_placed_order(
    estate: Dict[str, Any],
    requested_credit_minor: int = 0,
    buyer: Optional[dict] = None,
    seller_kwargs: Optional[Dict[str, Any]] = None,
    tasks: Iterable[Dict[str, Any]] = (),
    channel: Optional[dict] = None,
    bay: Optional[dict] = None,
) -> Dict[str, Any]:
    """A listed unit bought by ``buyer`` (the seller themself when omitted).

    Returns the listed-unit scenario plus ``{"buyer", "order"}``.
    """
    scenario = setup_listed_unit(
        estate, tasks=tasks, bay=bay, channel=channel, **(seller_kwargs or {})
    )
    the_buyer = buyer or scenario["customer"]
    scenario["buyer"] = the_buyer
    scenario["order"] = place_order(
        the_buyer, scenario["channel"], scenario["unit"], requested_credit_minor
    )
    scenario["unit"] = fetch_unit(scenario["unit"]["id"])
    return scenario


def setup_fulfilled_order(
    estate: Dict[str, Any], **overrides
) -> Dict[str, Any]:
    """A placed order handed over, so its warranty clock is running."""
    scenario = setup_placed_order(estate, **overrides)
    scenario["order"] = fulfill_order(scenario["order"]["id"])
    scenario["unit"] = fetch_unit(scenario["unit"]["id"])
    return scenario


def setup_return_requested_order(
    estate: Dict[str, Any], reason_type: str = "BUYER_REMORSE", **overrides
) -> Dict[str, Any]:
    """A fulfilled order with a live after-sale claim of the given reason."""
    scenario = setup_fulfilled_order(estate, **overrides)
    scenario["order"] = request_return(
        scenario["order"]["id"], scenario["buyer"], reason_type
    )
    return scenario


# ==========================================================================
# Expiry sweep and diversion reporting
# ==========================================================================
def run_expiry_sweep(headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.run_credit_grant_expiry(headers or ADMIN))


def create_report(headers: Optional[Dict[str, str]] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_diversion_report(
            create_diversion_report_payload(**overrides), headers or ADMIN
        )
    )


def publish_report(report_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(
        api_client.publish_diversion_report(report_id, headers or ADMIN)
    )
