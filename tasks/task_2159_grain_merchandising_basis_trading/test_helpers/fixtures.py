"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only — the database is empty at the start of every test.

Setup calls use get_success_data() so a broken precondition surfaces as a
clear "Setup step failed" rather than a confusing downstream assertion.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLEAN_LOAD, FULL_TIERS, TEST_DEFAULTS
from .factories import (
    create_bid_payload,
    create_delivery_ticket_payload,
    create_discount_schedule_payload,
    create_elevator_location_payload,
    create_freight_booking_payload,
    create_hedge_position_payload,
    create_pricing_order_payload,
    create_purchase_contract_payload,
    create_rail_fleet_payload,
    create_risk_limit_payload,
    create_trading_desk_payload,
)
from .test_users import TEST_USERS

_ADMIN = TEST_USERS["desk_admin_headers"]
_MERCH = TEST_USERS["merchandiser_headers"]
_TRADER = TEST_USERS["futures_trader_headers"]
_RISK = TEST_USERS["risk_officer_headers"]
_INSPECTOR = TEST_USERS["grain_inspector_headers"]
_FREIGHT = TEST_USERS["freight_coordinator_headers"]


# ─────────────────────────────────────────────────────
# Tier 1 — single-entity creation primitives
# ─────────────────────────────────────────────────────

def new_desk(**overrides) -> dict:
    """Register a trading desk. Returns the created desk."""
    payload = create_trading_desk_payload(**overrides)
    return get_success_data(api_client.create_trading_desk(payload, _ADMIN))


def new_location(desk_id, **overrides) -> dict:
    """Register a country elevator under a desk."""
    payload = create_elevator_location_payload(desk_id, **overrides)
    return get_success_data(api_client.create_elevator_location(payload, _ADMIN))


def new_schedule(activate: bool = True, **overrides) -> dict:
    """Draft a quality discount schedule and, by default, put it into force."""
    payload = create_discount_schedule_payload(**overrides)
    schedule = get_success_data(api_client.create_discount_schedule(payload, _ADMIN))
    if activate:
        schedule = get_success_data(
            api_client.activate_discount_schedule(schedule["id"], _ADMIN)
        )
    return schedule


def new_risk_limit(desk_id, expected_desk_version=None, **overrides) -> dict:
    """Publish a risk limit, reading the desk's current version when the
    caller does not pin one."""
    if expected_desk_version is None:
        desk = get_success_data(api_client.get_trading_desk(desk_id, _RISK))
        expected_desk_version = desk["version"]
    payload = create_risk_limit_payload(desk_id, expected_desk_version, **overrides)
    return get_success_data(api_client.create_risk_limit(payload, _RISK))


def new_rail_fleet(home_location_id, **overrides) -> dict:
    payload = create_rail_fleet_payload(home_location_id, **overrides)
    return get_success_data(api_client.create_rail_fleet(payload, _FREIGHT))


def new_bid(location_id, activate: bool = True, **overrides) -> dict:
    """Draft a bid and, by default, post it to the market."""
    payload = create_bid_payload(location_id, **overrides)
    bid = get_success_data(api_client.create_bid(payload, _MERCH))
    if activate:
        bid = get_success_data(api_client.activate_bid(bid["id"], _MERCH))
    return bid


def new_hedge_position(desk_id, **overrides) -> dict:
    payload = create_hedge_position_payload(desk_id, **overrides)
    return get_success_data(api_client.create_hedge_position(payload, _TRADER))


def new_contract(bid_id, hedge_position_id, headers=None, **overrides) -> dict:
    """Strike a purchase contract. Pass `headers` to pin the acting
    X-User-ID that becomes created_by_user_id."""
    payload = create_purchase_contract_payload(bid_id, hedge_position_id, **overrides)
    return get_success_data(
        api_client.create_purchase_contract(payload, headers or _MERCH)
    )


def new_pricing_order(contract_id, headers=None, **overrides) -> dict:
    payload = create_pricing_order_payload(contract_id, **overrides)
    return get_success_data(api_client.create_pricing_order(payload, headers or _MERCH))


def new_ticket(contract_id, location_id, **overrides) -> dict:
    """Grade an inbound load. Defaults to a clean 10,000-bushel load."""
    payload = create_delivery_ticket_payload(contract_id, location_id, **overrides)
    return get_success_data(api_client.create_delivery_ticket(payload, _INSPECTOR))


def new_freight_booking(fleet_id, contract_id, expected_fleet_version=None,
                        **overrides) -> dict:
    """Reserve rail cars, reading the fleet's current version when the caller
    does not pin one."""
    if expected_fleet_version is None:
        fleet = get_success_data(api_client.get_rail_fleet(fleet_id, _FREIGHT))
        expected_fleet_version = fleet["version"]
    payload = create_freight_booking_payload(
        fleet_id, contract_id, expected_fleet_version, **overrides
    )
    return get_success_data(api_client.create_freight_booking(payload, _FREIGHT))


# ─────────────────────────────────────────────────────
# Tier 2 — transitions and reads
# ─────────────────────────────────────────────────────

def advance_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock. Returns {current_utc, expired_bid_ids}."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, _ADMIN))


def mark_position(position_id, settlement_price_cents) -> dict:
    return get_success_data(api_client.mark_to_market(
        position_id, {"settlement_price_cents": settlement_price_cents}, _TRADER
    ))


def apply_ticket(ticket_id) -> dict:
    return get_success_data(api_client.apply_delivery_ticket(ticket_id, _MERCH))


def reverse_ticket(ticket_id, reversal_reason="scale ticket voided") -> dict:
    return get_success_data(api_client.reverse_delivery_ticket(
        ticket_id, {"reversal_reason": reversal_reason}, _INSPECTOR
    ))


def reject_ticket(ticket_id, rejection_reason="sour odour at the pit") -> dict:
    return get_success_data(api_client.reject_delivery_ticket(
        ticket_id, {"rejection_reason": rejection_reason}, _INSPECTOR
    ))


def confirm_booking(booking_id) -> dict:
    return get_success_data(api_client.confirm_freight_booking(booking_id, _FREIGHT))


def cancel_contract(contract_id, damages_method="MARKET_LOSS",
                    cancellation_reason="mutual unwind", headers=None) -> dict:
    return get_success_data(api_client.cancel_purchase_contract(
        contract_id,
        {"damages_method": damages_method, "cancellation_reason": cancellation_reason},
        headers or _RISK,
    ))


def cure_call(margin_call_id, payment_usd) -> dict:
    return get_success_data(api_client.cure_margin_call(
        margin_call_id, {"payment_usd": payment_usd}, _RISK
    ))


def read_desk(desk_id) -> dict:
    return get_success_data(api_client.get_trading_desk(desk_id, _RISK))


def read_location(location_id) -> dict:
    return get_success_data(api_client.get_elevator_location(location_id, _ADMIN))


def read_schedule(schedule_id) -> dict:
    return get_success_data(api_client.get_discount_schedule(schedule_id, _ADMIN))


def read_risk_limit(risk_limit_id) -> dict:
    return get_success_data(api_client.get_risk_limit(risk_limit_id, _RISK))


def read_fleet(fleet_id) -> dict:
    return get_success_data(api_client.get_rail_fleet(fleet_id, _FREIGHT))


def read_bid(bid_id) -> dict:
    return get_success_data(api_client.get_bid(bid_id, _MERCH))


def read_position(position_id) -> dict:
    return get_success_data(api_client.get_hedge_position(position_id, _TRADER))


def read_contract(contract_id) -> dict:
    return get_success_data(api_client.get_purchase_contract(contract_id, _MERCH))


def read_pricing_order(pricing_order_id) -> dict:
    return get_success_data(api_client.get_pricing_order(pricing_order_id, _MERCH))


def read_margin_call(margin_call_id) -> dict:
    return get_success_data(api_client.get_margin_call(margin_call_id, _RISK))


def read_ticket(ticket_id) -> dict:
    return get_success_data(api_client.get_delivery_ticket(ticket_id, _INSPECTOR))


def read_booking(booking_id) -> dict:
    return get_success_data(api_client.get_freight_booking(booking_id, _FREIGHT))


def read_position_report(desk_id, commodity_code=None) -> dict:
    params = {"commodity_code": commodity_code} if commodity_code else None
    return get_success_data(api_client.get_position_report(desk_id, _RISK, params=params))


def open_margin_call_for(position_id) -> dict:
    """Return the single OPEN margin call standing against a position."""
    data = get_success_data(api_client.list_margin_calls(
        _RISK, params={"hedge_position_id": position_id, "status": "OPEN"}
    ))
    assert isinstance(data, list) and len(data) >= 1, (
        f"Setup expected an OPEN margin call on position {position_id}, found none"
    )
    return data[0]


# ─────────────────────────────────────────────────────
# Tier 3 — the standing trading floor
# ─────────────────────────────────────────────────────

def setup_trading_floor(
    desk_code="GD1",
    desk_name="Illinois River Desk",
    credit_line_usd=TEST_DEFAULTS["CREDIT_LINE_USD"],
    location_code="ELV1",
    location_name="Morris Elevator",
    intake_capacity_bushels=TEST_DEFAULTS["INTAKE_CAPACITY_BUSHELS"],
    rail_served=True,
    commodity_code="CORN",
    futures_month=TEST_DEFAULTS["FUTURES_MONTH"],
    with_schedule=True,
    schedule_activate=True,
    schedule_tiers=None,
    schedule_effective_from=TEST_DEFAULTS["SCHEDULE_EFFECTIVE_FROM"],
    moisture_standard_pct=15.0,
    shrink_factor_pct_per_point=1.18,
    with_position=True,
    side="SHORT",
    lots_open=10,
    avg_entry_price_cents=TEST_DEFAULTS["ENTRY_PRICE_CENTS"],
    position_futures_month=None,
    with_bid=True,
    bid_activate=True,
    basis_cents=TEST_DEFAULTS["BID_BASIS_CENTS"],
    bid_max_bushels=TEST_DEFAULTS["BID_MAX_BUSHELS"],
    delivery_period_start=TEST_DEFAULTS["DELIVERY_PERIOD_START"],
    delivery_period_end=TEST_DEFAULTS["DELIVERY_PERIOD_END"],
    bid_expires_at=TEST_DEFAULTS["BID_EXPIRES_AT"],
) -> dict:
    """Desk + elevator + (optional) discount schedule + (optional) hedge
    position + (optional) posted bid — the preamble almost every scenario
    on this API needs.

    Returns {"desk", "location", "schedule", "position", "bid"}; the optional
    members are None when their flag is off.
    """
    desk = new_desk(desk_code=desk_code, name=desk_name, credit_line_usd=credit_line_usd)
    location = new_location(
        desk["id"], location_code=location_code, name=location_name,
        intake_capacity_bushels=intake_capacity_bushels, rail_served=rail_served,
    )

    schedule = None
    if with_schedule:
        schedule = new_schedule(
            activate=schedule_activate,
            commodity_code=commodity_code,
            effective_from=schedule_effective_from,
            moisture_standard_pct=moisture_standard_pct,
            shrink_factor_pct_per_point=shrink_factor_pct_per_point,
            tiers=[dict(t) for t in (schedule_tiers or FULL_TIERS)],
        )

    position = None
    if with_position:
        position = new_hedge_position(
            desk["id"],
            commodity_code=commodity_code,
            futures_month=position_futures_month or futures_month,
            side=side,
            lots_open=lots_open,
            avg_entry_price_cents=avg_entry_price_cents,
        )

    bid = None
    if with_bid:
        bid = new_bid(
            location["id"],
            activate=bid_activate,
            commodity_code=commodity_code,
            futures_month=futures_month,
            delivery_period_start=delivery_period_start,
            delivery_period_end=delivery_period_end,
            basis_cents=basis_cents,
            max_bushels=bid_max_bushels,
            expires_at=bid_expires_at,
        )

    return {"desk": desk, "location": location, "schedule": schedule,
            "position": position, "bid": bid}


def setup_contract_scenario(contract_overrides=None, contract_headers=None,
                            **floor_kwargs) -> dict:
    """A trading floor plus one struck purchase contract.

    `contract_overrides` is passed straight to the contract payload factory;
    `contract_headers` pins the acting X-User-ID recorded as
    created_by_user_id.
    """
    floor = setup_trading_floor(**floor_kwargs)
    contract = new_contract(
        floor["bid"]["id"], floor["position"]["id"],
        headers=contract_headers, **(contract_overrides or {}),
    )
    floor["contract"] = contract
    return floor


def setup_graded_ticket_scenario(ticket_overrides=None, **scenario_kwargs) -> dict:
    """A struck contract plus one GRADED delivery ticket against it."""
    scenario = setup_contract_scenario(**scenario_kwargs)
    scenario["ticket"] = new_ticket(
        scenario["contract"]["id"], scenario["location"]["id"],
        **(ticket_overrides or {}),
    )
    return scenario


def setup_rail_scenario(fleet_overrides=None, booking_overrides=None,
                        with_booking=True, **scenario_kwargs) -> dict:
    """A struck contract at a rail-served elevator, a homed fleet and
    (by default) one REQUESTED booking on it."""
    scenario = setup_contract_scenario(**scenario_kwargs)
    fleet = new_rail_fleet(scenario["location"]["id"], **(fleet_overrides or {}))
    scenario["fleet"] = fleet
    if with_booking:
        scenario["booking"] = new_freight_booking(
            fleet["id"], scenario["contract"]["id"], **(booking_overrides or {})
        )
    return scenario


# ─────────────────────────────────────────────────────
# Tier 4 — margin-call and posture targeting
# ─────────────────────────────────────────────────────

def setup_position_in_margin_call(
    desk_code="GD-MC",
    credit_line_usd=TEST_DEFAULTS["CREDIT_LINE_USD"],
    lots_open=4,
    avg_entry_price_cents=448,
    settlement_price_cents=500,
    commodity_code="CORN",
    futures_month=TEST_DEFAULTS["FUTURES_MONTH"],
) -> dict:
    """Open a SHORT position and mark it hard enough against itself that
    account equity falls below maintenance, raising an OPEN margin call.

    Returns {"desk", "position", "margin_call"} with the position re-read
    after the mark.
    """
    desk = new_desk(desk_code=desk_code, name="Margin Call Desk",
                    credit_line_usd=credit_line_usd)
    position = new_hedge_position(
        desk["id"], commodity_code=commodity_code, futures_month=futures_month,
        side="SHORT", lots_open=lots_open,
        avg_entry_price_cents=avg_entry_price_cents,
    )
    marked = mark_position(position["id"], settlement_price_cents)
    call = open_margin_call_for(position["id"])
    return {"desk": desk, "position": marked, "margin_call": call}


def setup_frozen_desk_with_unpriced_contract(
    desk_code="GD-FROZEN",
    credit_line_usd=16000.00,
    lots_open=4,
    contract_bushels=10000,
    settlement_price_cents=500,
) -> dict:
    """Drive a thin-credit desk into FROZEN posture through a margin call
    while one ACTIVE, not-yet-fully-priced HTA contract sits on its books.

    Returns {"desk", "location", "position", "bid", "contract", "margin_call"}.
    """
    scenario = setup_contract_scenario(
        desk_code=desk_code,
        desk_name="Freeze Cascade Desk",
        credit_line_usd=credit_line_usd,
        with_schedule=False,
        lots_open=lots_open,
        contract_overrides={"contract_type": "HTA", "bushels": contract_bushels},
    )
    mark_position(scenario["position"]["id"], settlement_price_cents)
    scenario["margin_call"] = open_margin_call_for(scenario["position"]["id"])
    return scenario


# ─────────────────────────────────────────────────────
# Tier 5 — settlement-ready and terminal scenarios
# ─────────────────────────────────────────────────────

def setup_settlement_ready(
    desk_code="GD-SETTLE",
    credit_line_usd=100000.00,
    lots_open=2,
    contract_bushels=10000,
    gross_bushels=10000,
) -> dict:
    """A FULLY_PRICED CASH contract whose entire quantity sits on one clean
    GRADED ticket, so a single apply completes delivery and settles it.

    Returns {"desk", "location", "schedule", "position", "bid", "contract",
    "ticket"}.
    """
    return setup_graded_ticket_scenario(
        desk_code=desk_code,
        desk_name="Settlement Desk",
        credit_line_usd=credit_line_usd,
        lots_open=lots_open,
        contract_overrides={"contract_type": "CASH", "bushels": contract_bushels,
                            "settlement_basis": "SHRINK_FIRST"},
        ticket_overrides={"gross_bushels": gross_bushels, **CLEAN_LOAD},
    )


def setup_default_ready(
    desk_code="GD-DEFAULT",
    contract_bushels=20000,
    settlement_price_cents=470,
    clock_to="2026-12-11T00:00:00Z",
) -> dict:
    """A FULLY_PRICED CASH contract with nothing delivered, its hedge marked,
    and the logical clock pushed past delivery_end plus the grace period.

    Returns the contract scenario dict.
    """
    scenario = setup_contract_scenario(
        desk_code=desk_code,
        desk_name="Default Desk",
        with_schedule=False,
        contract_overrides={"contract_type": "CASH", "bushels": contract_bushels},
    )
    mark_position(scenario["position"]["id"], settlement_price_cents)
    advance_clock(clock_to)
    return scenario
