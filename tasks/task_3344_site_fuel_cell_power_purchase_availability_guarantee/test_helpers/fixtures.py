"""Composite setup helpers.

The server is killed and re-launched before every individual test, so every
helper here builds its precondition from scratch through PRD-declared
endpoints — nothing is carried over between tests and nothing is seeded
server-side.

Callers that need a late lifecycle state (an applied settlement line, a
frozen site with a blocked replacement, a reconciled accrual) call one of the
`setup_*` helpers rather than replaying the chain inline.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS as D
from .factories import (
    create_accrual_payload,
    create_customer_payload,
    create_fuel_delivery_payload,
    create_ppa_payload,
    create_settlement_line_payload,
    create_site_payload,
    issue_allowance_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_settlement_analyst_headers,
)

OPERATOR = TEST_USERS["site_operator_headers"]
CUSTOMER_SERVICE = TEST_USERS["customer_service_headers"]
FUEL_COORDINATOR = TEST_USERS["fuel_coordinator_headers"]
SERVICE_ENGINEER = TEST_USERS["service_engineer_headers"]
ANALYST = TEST_USERS["settlement_analyst_headers"]
APPROVER = TEST_USERS["settlement_approver_headers"]


def _data(response, step):
    try:
        return get_success_data(response)
    except AssertionError as exc:  # pragma: no cover - surfaces setup failures clearly
        raise AssertionError(f"Setup step '{step}' failed: {exc}") from exc


# =============================================================================
# Tier 0 — logical clock
# =============================================================================
def set_clock(current_utc=D["CLOCK"]):
    """Set the logical clock (PRD §2.10)."""
    return _data(api_client.set_current_utc(OPERATOR, current_utc), "set clock")


# =============================================================================
# Tier 1 — single-entity construction
# =============================================================================
def create_site(**overrides):
    """Register a facility. Returns the created Site. Defaults to the standard
    site whose opening fuel inventory is 100,000 therms."""
    payload = create_site_payload(**overrides)
    return _data(api_client.create_site(payload, OPERATOR), "create site")


def create_customer(**overrides):
    """Create a customer offtaker. Returns the created Customer."""
    payload = create_customer_payload(**overrides)
    return _data(api_client.create_customer(payload, CUSTOMER_SERVICE), "create customer")


def create_ppa(site_id, customer_id, **overrides):
    """Draft a contract. Returns the drafted Ppa."""
    payload = create_ppa_payload(site_id=site_id, customer_id=customer_id, **overrides)
    return _data(api_client.create_ppa(payload, OPERATOR), "create ppa")


def activate_ppa(ppa_id):
    """Activate a drafted contract — the densest cascade in the system (PRD §3.2)."""
    return _data(api_client.activate_ppa(ppa_id, OPERATOR), "activate ppa")


def get_site(site_id):
    return _data(api_client.get_site(site_id, OPERATOR), "get site")


def get_ppa(ppa_id):
    return _data(api_client.get_ppa(ppa_id, OPERATOR), "get ppa")


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, CUSTOMER_SERVICE))


def get_service_plan(ppa_id, plan_id):
    return _data(
        api_client.get_service_plan(ppa_id, plan_id, SERVICE_ENGINEER), "get service plan"
    )


def get_delivery(site_id, delivery_id):
    return _data(
        api_client.get_fuel_delivery(site_id, delivery_id, FUEL_COORDINATOR),
        "get delivery",
    )


def list_deliveries(site_id, **params):
    return _data(
        api_client.list_site_fuel_deliveries(site_id, FUEL_COORDINATOR, params or None),
        "list deliveries",
    )


def list_transitions(ppa_id):
    return _data(
        api_client.list_ppa_transitions(ppa_id, OPERATOR), "list ppa transitions"
    )


# =============================================================================
# Tier 2 — entity hierarchies
# =============================================================================
def setup_site_with_customer(**site_overrides):
    """A registered facility and a customer offtaker, no contract yet."""
    set_clock()
    return create_site(**site_overrides), create_customer()


def setup_active_ppa(
    site_overrides=None,
    customer_overrides=None,
    ppa_overrides=None,
):
    """The most common preamble: facility + offtaker + one live contract.

    Returns a dict with the site, the customer, the PPA, the site's post-
    activation version and the service plan the activation cascade created.
    """
    set_clock()
    site = create_site(**(site_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    ppa = create_ppa(site["id"], customer["id"], **(ppa_overrides or {}))
    activated = activate_ppa(ppa["id"])
    return {
        "site": get_site(site["id"]),
        "customer": customer,
        "ppa": activated,
        "site_id": site["id"],
        "customer_id": customer["id"],
        "ppa_id": ppa["id"],
        "plan_id": activated.get("assigned_service_plan_id"),
    }


def setup_draft_ppa(site_overrides=None, customer_overrides=None, ppa_overrides=None):
    """Facility + offtaker + one contract still in PPA_DRAFT."""
    set_clock()
    site = create_site(**(site_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    ppa = create_ppa(site["id"], customer["id"], **(ppa_overrides or {}))
    return {
        "site": get_site(site["id"]),
        "customer": customer,
        "ppa": ppa,
        "site_id": site["id"],
        "customer_id": customer["id"],
        "ppa_id": ppa["id"],
    }


def setup_site_with_ppas_and_delivery(site_overrides=None, delivery_overrides=None):
    """Facility + offtaker + one live contract + one scheduled delivery."""
    ctx = setup_active_ppa(site_overrides=site_overrides)
    delivery = schedule_delivery(ctx["site_id"], **(
        delivery_overrides if delivery_overrides is not None else {"volume_therms": 8000}
    ))
    ctx["delivery"] = delivery
    ctx["delivery_id"] = delivery["id"]
    ctx["site"] = get_site(ctx["site_id"])
    return ctx


# =============================================================================
# Tier 3 — full lifecycle shortcuts
# =============================================================================
def schedule_delivery(site_id, **overrides):
    """Schedule a delivery against a site, carrying the site's current version."""
    site = get_site(site_id)
    payload = create_fuel_delivery_payload(
        expected_site_version=site["version"], **overrides
    )
    return _data(
        api_client.create_fuel_delivery(site_id, FUEL_COORDINATOR, payload),
        "schedule delivery",
    )


def schedule_indexed_delivery(site_id, **overrides):
    """Schedule an index-priced delivery against a site."""
    site = get_site(site_id)
    defaults = dict(
        sourcing_mode="INDEXED_BLEND",
        index_rate_cents_per_therm=4.00,
        fixed_price_cents_per_therm=4.20,
        hedged_fraction=0.5,
    )
    defaults.update(overrides)
    payload = create_fuel_delivery_payload(
        expected_site_version=site["version"], **defaults
    )
    return _data(
        api_client.create_fuel_delivery(site_id, FUEL_COORDINATOR, payload),
        "schedule indexed delivery",
    )


def take_resource_hold(site_id, **overrides):
    """Consume the site's allocatable pool into an in-service hold (PRD §3.3)."""
    payload = {
        "requested_therms": 25000,
        "window_start_iso8601": "2026-04-01T00:00:00Z",
        "window_end_iso8601": "2026-04-04T00:00:00Z",
    }
    payload.update(overrides)
    return _data(
        api_client.take_resource_hold(site_id, OPERATOR, payload), "take resource hold"
    )


def dispatch_delivery(site_id, delivery_id):
    return _data(
        api_client.dispatch_fuel_delivery(site_id, delivery_id, FUEL_COORDINATOR),
        "dispatch delivery",
    )


def confirm_delivery(site_id, delivery_id):
    return _data(
        api_client.confirm_fuel_delivery(site_id, delivery_id, FUEL_COORDINATOR),
        "confirm delivery",
    )


def cancel_delivery(site_id, delivery_id):
    return _data(
        api_client.cancel_fuel_delivery(site_id, delivery_id, FUEL_COORDINATOR),
        "cancel delivery",
    )


def post_accrual(ppa_id, site_id, **overrides):
    """Post an accrual directly (PRD §3.3)."""
    payload = create_accrual_payload(ppa_id=ppa_id, site_id=site_id, **overrides)
    return _data(api_client.create_accrual(payload, ANALYST), "post accrual")


def issue_allowance(ppa_id, **overrides):
    """Issue a settlement allowance against a contract (PRD §3.6)."""
    ppa = get_ppa(ppa_id)
    payload = issue_allowance_payload(expected_ppa_version=ppa["version"], **overrides)
    return _data(
        api_client.issue_allowance(ppa_id, ANALYST, payload), "issue allowance"
    )


def create_settlement_line(ppa_id, **overrides):
    """Prepare a settlement period line (PRD §3.4)."""
    ppa = get_ppa(ppa_id)
    payload = create_settlement_line_payload(
        expected_ppa_version=ppa["version"], **overrides
    )
    return _data(
        api_client.create_settlement_line(ppa_id, ANALYST, payload),
        "create settlement line",
    )


def validate_settlement_line(ppa_id, line_id):
    return _data(
        api_client.validate_settlement_line(ppa_id, line_id, ANALYST),
        "validate settlement line",
    )


def approve_settlement_line(ppa_id, line_id):
    return _data(
        api_client.approve_settlement_line(ppa_id, line_id, APPROVER),
        "approve settlement line",
    )


def settle_settlement_line(ppa_id, line_id):
    return _data(
        api_client.settle_settlement_line(ppa_id, line_id, APPROVER),
        "settle settlement line",
    )


def reverse_settlement_line(ppa_id, line_id):
    return _data(
        api_client.reverse_settlement_line(ppa_id, line_id, APPROVER),
        "reverse settlement line",
    )


def setup_approved_line(
    accrual_amount_cents=100000,
    line_overrides=None,
    accrual_type="CHARGE_ACCRUAL",
    site_overrides=None,
    ppa_overrides=None,
    allowance_amount_cents=185000,
):
    """Facility + live contract + an open accrual + an issued capacity allowance
    + a settlement line walked to SETTLEMENT_APPROVED.

    Returns the composite context. Used as the preamble for every settle,
    reverse and rollover test.
    """
    ctx = setup_active_ppa(site_overrides=site_overrides, ppa_overrides=ppa_overrides)
    accrual = post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        accrual_type=accrual_type,
        amount_cents=accrual_amount_cents,
    )
    allowance = issue_allowance(ctx["ppa_id"], amount_cents=allowance_amount_cents)
    line = create_settlement_line(ctx["ppa_id"], **(line_overrides or {}))
    line = validate_settlement_line(ctx["ppa_id"], line["id"])
    line = approve_settlement_line(ctx["ppa_id"], line["id"])
    ctx.update(
        {
            "accrual": accrual,
            "allowance": allowance,
            "line": line,
            "line_id": line["id"],
            "site": get_site(ctx["site_id"]),
            "ppa": get_ppa(ctx["ppa_id"]),
        }
    )
    return ctx


def setup_validated_line(
    accrual_amount_cents=100000,
    line_overrides=None,
    allowance_amount_cents=185000,
    site_overrides=None,
    ppa_overrides=None,
):
    """Facility + live contract + open accrual + issued allowance + a line at
    SETTLEMENT_VALIDATED."""
    ctx = setup_active_ppa(site_overrides=site_overrides, ppa_overrides=ppa_overrides)
    accrual = post_accrual(ctx["ppa_id"], ctx["site_id"], amount_cents=accrual_amount_cents)
    allowance = issue_allowance(ctx["ppa_id"], amount_cents=allowance_amount_cents)
    line = create_settlement_line(ctx["ppa_id"], **(line_overrides or {}))
    line = validate_settlement_line(ctx["ppa_id"], line["id"])
    ctx.update(
        {
            "accrual": accrual,
            "allowance": allowance,
            "line": line,
            "line_id": line["id"],
            "site": get_site(ctx["site_id"]),
            "ppa": get_ppa(ctx["ppa_id"]),
        }
    )
    return ctx


def setup_applied_line(
    accrual_amount_cents=100000,
    line_overrides=None,
    allowance_amount_cents=185000,
    site_overrides=None,
    ppa_overrides=None,
):
    """Full settlement lifecycle through SETTLEMENT_APPLIED."""
    ctx = setup_approved_line(
        accrual_amount_cents=accrual_amount_cents,
        line_overrides=line_overrides,
        allowance_amount_cents=allowance_amount_cents,
        site_overrides=site_overrides,
        ppa_overrides=ppa_overrides,
    )
    line = settle_settlement_line(ctx["ppa_id"], ctx["line_id"])
    ctx["line"] = line
    ctx["site"] = get_site(ctx["site_id"])
    ctx["ppa"] = get_ppa(ctx["ppa_id"])
    return ctx


def setup_terminated_ppa(cure_deadline_days=30, site_overrides=None):
    """A contract terminated after an uncured exit, with its customer at
    RENEWAL_OFFERED. Returns the context.

    PRD §3.8: "A `CustomerService` operator offers a renewal to a customer
    whose `status` is `CUSTOMER_ACTIVE` and whose `active_ppa_count` is at
    least 1". Terminating the customer's only contract would drop that count
    to zero and make the offer itself illegal, so the customer offtaker holds
    a second, untouched live contract at its own facility.
    """
    ctx = setup_active_ppa(
        site_overrides=site_overrides,
        ppa_overrides={"customer_cure_deadline_days": cure_deadline_days},
    )
    other_site = create_site(name="Second Facility")
    other_ppa = create_ppa(other_site["id"], ctx["customer_id"])
    activate_ppa(other_ppa["id"])

    api_client.request_exit(ctx["ppa_id"], OPERATOR)
    set_clock("2026-04-20T00:00:00Z")
    terminated = _data(
        api_client.terminate_ppa(ctx["ppa_id"], OPERATOR), "terminate ppa"
    )
    offered = _data(
        api_client.offer_renewal(ctx["customer_id"], CUSTOMER_SERVICE), "offer renewal"
    )
    ctx.update(
        {
            "ppa": terminated,
            "customer": offered,
            "site": get_site(ctx["site_id"]),
            "other_site_id": other_site["id"],
            "other_ppa_id": other_ppa["id"],
        }
    )
    return ctx


def setup_frozen_site_with_blocked_replacement(site_overrides=None):
    """Facility + live contract + a scheduled module replacement, then frozen.

    Returns the context with the plan's replacement stage advanced to
    REPLACEMENT_BLOCKED and the plan's lifecycle suspended.
    """
    ctx = setup_active_ppa(site_overrides=site_overrides)
    plan_id = ctx["plan_id"]
    _data(
        api_client.schedule_replacement(ctx["ppa_id"], plan_id, SERVICE_ENGINEER),
        "schedule replacement",
    )
    _data(
        api_client.freeze_site(ctx["site_id"], OPERATOR, "GRID_INTERCONNECT_FAILURE"),
        "freeze site",
    )
    ctx["plan"] = get_service_plan(ctx["ppa_id"], plan_id)
    ctx["site"] = get_site(ctx["site_id"])
    ctx["ppa"] = get_ppa(ctx["ppa_id"])
    return ctx


def setup_delivery_at_confirmation_window(site_id=None, **delivery_overrides):
    """A dispatched delivery awaiting confirmation at a known clock instant."""
    if site_id is None:
        ctx = setup_active_ppa()
        site_id = ctx["site_id"]
    delivery = schedule_delivery(site_id, **delivery_overrides)
    dispatched = dispatch_delivery(site_id, delivery["id"])
    return {
        "site_id": site_id,
        "delivery": dispatched,
        "delivery_id": delivery["id"],
        "site": get_site(site_id),
    }