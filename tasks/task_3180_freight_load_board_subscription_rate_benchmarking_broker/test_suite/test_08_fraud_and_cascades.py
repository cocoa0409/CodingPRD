"""Fraud alerts, suspension cascades, and load visibility dimension."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    TEST_USERS, ApiErrorId,
    set_test_clock, create_broker, create_carrier,
    setup_verified_broker, setup_verified_carrier, setup_broker_carrier_booked,
    post_load, contribute_rate,
    get_broker, get_load, get_truck, get_booking, get_fraud_alert,
    get_rate_transaction, list_broker_subscriptions,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["compliance_analyst_headers"]
DATAOPS = TEST_USERS["data_ops_headers"]


def test_fraud_alert_dismissed_is_terminal_and_confirm_rejected():
    """PRD §3.8: "Dismissing an alert lands it in `DISMISSED` with no further
    effect."

    Design: Corner/state_machines/fraud_alert_dismissed_is_terminal_and_confirm_rejected
    """
    set_test_clock()
    broker = create_broker()
    alert = get_success_data(api_client.create_fraud_alert(
        {"alert_type": "IDENTITY_SPOOFING", "target_broker_org_id": broker["id"],
         "evidence_note": "Lookalike domain registration"}, ANALYST))
    get_success_data(api_client.dismiss_fraud_alert(alert["id"], ANALYST))

    resp = api_client.confirm_fraud_alert(alert["id"], ANALYST)
    assert resp.status_code == 409
    assert get_fraud_alert(alert["id"])["status"] == "DISMISSED"
    assert get_broker(broker["id"])["status"] == "ACTIVE"


def test_data_ops_cannot_confirm_fraud_alert():
    """PRD §2.1: "Only a `ComplianceAnalyst` may open, confirm, or dismiss
    fraud alerts" and "a role that is not permitted for the endpoint is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/roles/data_ops_cannot_confirm_fraud_alert
    """
    set_test_clock()
    broker = create_broker()
    alert = get_success_data(api_client.create_fraud_alert(
        {"alert_type": "IDENTITY_SPOOFING", "target_broker_org_id": broker["id"],
         "evidence_note": "Lookalike domain registration"}, ANALYST))
    resp = api_client.confirm_fraud_alert(alert["id"], DATAOPS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert get_fraud_alert(alert["id"])["status"] == "OPEN"


def test_load_post_parallel_lifecycle_and_visibility_dimensions():
    """PRD §3.2 (§3.3): "Status and visibility are independent parallel
    dimensions: a load is found in search only while `LISTED`, but its
    lifecycle (open, booked, completed, withdrawn, expired) advances
    regardless." and §3.8: "Suspending a broker withdraws every one of its
    `OPEN` loads (status to `WITHDRAWN`) and delists every one of its `BOOKED`
    loads (visibility to `DELISTED`, lifecycle status unchanged, bookings
    untouched)" and "Reinstating a broker re-lists its loads that were
    delisted while `BOOKED` (visibility `DELISTED` → `LISTED`)"

    Design: Difficulty/non_linear_state_machine/load_post_parallel_lifecycle_and_visibility_dimensions
    """
    set_test_clock()
    ctx = setup_broker_carrier_booked()
    bctx, load, booking = ctx["bctx"], ctx["load"], ctx["booking"]
    bid = bctx["broker"]["id"]

    get_success_data(api_client.suspend_broker_org(bid, ADMIN))
    l = get_load(load["id"])
    assert l["status"] == "BOOKED"
    assert l["visibility"] == "DELISTED"
    assert get_booking(booking["id"])["status"] == "BOOKED"

    get_success_data(api_client.reinstate_broker_org(bid, ADMIN))
    l = get_load(load["id"])
    assert l["status"] == "BOOKED"
    assert l["visibility"] == "LISTED"
    assert get_booking(booking["id"])["status"] == "BOOKED"


def test_fraud_confirm_cascades_alert_org_load_booking_truck_and_transactions():
    """PRD §3.8: "Confirming an alert lands it in `CONFIRMED` and suspends
    every targeted org, firing the full cascade described below." and "For a
    targeted broker, everything the administrative cascade does happens, plus:
    every `BOOKED` booking on one of the broker's loads is cancelled, and each
    such booking's truck (if itself `BOOKED`) is released back to `AVAILABLE`;
    additionally, every `ACCEPTED` rate transaction reported by that broker is
    moved to `EXCLUDED`."

    Design: Difficulty/transitive_cascade/fraud_confirm_cascades_alert_org_load_booking_truck_and_transactions
    """
    set_test_clock()
    ctx = setup_broker_carrier_booked()
    bctx, cctx = ctx["bctx"], ctx["cctx"]
    load_booked, truck, booking = ctx["load"], ctx["truck"], ctx["booking"]
    bid = bctx["broker"]["id"]

    l1 = post_load(bctx)  # OPEN load
    rt = contribute_rate("broker", bid, transaction_date="2026-07-15T00:00:00Z")

    alert = get_success_data(api_client.create_fraud_alert(
        {"alert_type": "DOUBLE_BROKERING", "target_broker_org_id": bid,
         "evidence_note": "Same MC reposted under second identity"}, ANALYST))
    r = validate_success(api_client.confirm_fraud_alert(alert["id"], ANALYST))
    assert r["status"] == "CONFIRMED"

    assert get_broker(bid)["status"] == "SUSPENDED"
    l1r = get_load(l1["id"])
    assert l1r["status"] == "WITHDRAWN"
    assert l1r["visibility"] == "DELISTED"
    lb = get_load(load_booked["id"])
    assert lb["status"] == "BOOKED"
    assert lb["visibility"] == "DELISTED"
    assert get_booking(booking["id"])["status"] == "CANCELLED"
    assert get_truck(truck["id"])["status"] == "AVAILABLE"
    assert get_rate_transaction(rt["id"])["status"] == "EXCLUDED"
    subs = list_broker_subscriptions(bid)
    assert len(subs) == 1 and subs[0]["status"] == "SUSPENDED"
