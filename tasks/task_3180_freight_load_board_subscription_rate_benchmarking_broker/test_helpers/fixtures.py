"""Composite setup helpers (multi-API-call preconditions).

Every fixture builds state from scratch via PRD-declared endpoints; the
server is restarted per test so nothing carries over.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_CLOCK
from .factories import (
    create_broker_org_payload, create_carrier_org_payload,
    create_subscription_plan_payload, create_load_post_payload,
    create_truck_post_payload, create_booking_payload,
    create_rate_transaction_payload, create_credit_report_event_payload,
    create_authority_verification_payload,
)
from .test_users import (
    TEST_USERS, make_broker_admin_headers, make_carrier_admin_headers,
)

_mc_counter = itertools.count(9000)
_dot_counter = itertools.count(9000)
_plan_code_cycle = itertools.cycle(("BASIC", "PRO", "ENTERPRISE"))


def set_test_clock(to_iso8601=TEST_CLOCK):
    return get_success_data(api_client.set_clock(to_iso8601, TEST_USERS["platform_admin_headers"]))


def create_broker(mc_number=None, legal_name="Test Brokerage"):
    payload = create_broker_org_payload(
        legal_name=legal_name, mc_number=mc_number or f"MC-{next(_mc_counter)}")
    return get_success_data(api_client.create_broker_org(payload, TEST_USERS["platform_admin_headers"]))


def create_carrier(dot_number=None, legal_name="Test Carriers"):
    payload = create_carrier_org_payload(
        legal_name=legal_name, dot_number=dot_number or f"DOT-{next(_dot_counter)}")
    return get_success_data(api_client.create_carrier_org(payload, TEST_USERS["platform_admin_headers"]))


def create_plan(**overrides):
    # PRD §3.2 requires each plan's `code` to be unique. A single test often
    # builds several orgs (broker + carrier), each with its own plan, so cycle
    # through the three allowed codes when the caller does not pin one.
    overrides.setdefault("code", next(_plan_code_cycle))
    return get_success_data(api_client.create_subscription_plan(
        create_subscription_plan_payload(**overrides), TEST_USERS["platform_admin_headers"]))


def create_broker_subscription(plan_id, broker_id):
    return get_success_data(api_client.create_subscription(
        {"plan_id": plan_id, "broker_org_id": broker_id},
        TEST_USERS["platform_admin_headers"]))


def create_carrier_subscription(plan_id, carrier_id):
    return get_success_data(api_client.create_subscription(
        {"plan_id": plan_id, "carrier_org_id": carrier_id},
        TEST_USERS["platform_admin_headers"]))


def create_verified_authority(org_kind, org_id):
    """Submit + verify an authority record with contiguous full-year coverage."""
    av = get_success_data(api_client.create_authority_verification(
        create_authority_verification_payload(org_kind, org_id),
        (make_broker_admin_headers(org_id) if org_kind == "broker"
         else make_carrier_admin_headers(org_id))))
    return get_success_data(api_client.verify_authority(
        av["id"], TEST_USERS["compliance_analyst_headers"]))


def setup_verified_broker(plan_overrides=None, mc_number=None):
    """Broker + plan + subscription + VERIFIED authority. Returns dict."""
    plan = create_plan(**(plan_overrides or {}))
    broker = create_broker(mc_number=mc_number)
    sub = create_broker_subscription(plan["id"], broker["id"])
    av = create_verified_authority("broker", broker["id"])
    return {"plan": plan, "broker": broker, "subscription": sub, "authority": av,
            "broker_headers": make_broker_admin_headers(broker["id"])}


def setup_verified_carrier(plan_overrides=None, dot_number=None):
    plan = create_plan(**(plan_overrides or {}))
    carrier = create_carrier(dot_number=dot_number)
    sub = create_carrier_subscription(plan["id"], carrier["id"])
    av = create_verified_authority("carrier", carrier["id"])
    return {"plan": plan, "carrier": carrier, "subscription": sub, "authority": av,
            "carrier_headers": make_carrier_admin_headers(carrier["id"])}


def post_load(broker_ctx, **overrides):
    return get_success_data(api_client.create_load_post(
        create_load_post_payload(**overrides), broker_ctx["broker_headers"]))


def post_truck(carrier_ctx, **overrides):
    return get_success_data(api_client.create_truck_post(
        create_truck_post_payload(**overrides), carrier_ctx["carrier_headers"]))


def setup_broker_carrier_booked():
    """Verified+subscribed broker & carrier, one OPEN load, one AVAILABLE truck,
    one BOOKED booking. Returns a context dict."""
    bctx = setup_verified_broker()
    cctx = setup_verified_carrier()
    load = post_load(bctx)
    truck = post_truck(cctx)
    booking = get_success_data(api_client.create_booking(
        create_booking_payload(load["id"], truck["id"]), cctx["carrier_headers"]))
    return {"bctx": bctx, "cctx": cctx, "load": load, "truck": truck, "booking": booking}


def contribute_rate(org_kind, org_id, **overrides):
    """Post a contributed rate transaction as the org's admin."""
    headers = (make_broker_admin_headers(org_id) if org_kind == "broker"
               else make_carrier_admin_headers(org_id))
    return get_success_data(api_client.create_rate_transaction(
        create_rate_transaction_payload(**overrides), headers))


def create_credit_event(broker_id, reporter_carrier_id, **overrides):
    return get_success_data(api_client.create_credit_report_event(
        create_credit_report_event_payload(broker_id, **overrides),
        make_carrier_admin_headers(reporter_carrier_id)))


def get_broker(broker_id):
    return get_success_data(api_client.get_broker_org(
        broker_id, TEST_USERS["platform_admin_headers"]))


def get_subscription(sub_id):
    return get_success_data(api_client.get_subscription(
        sub_id, TEST_USERS["platform_admin_headers"]))


def get_load(load_id):
    return get_success_data(api_client.get_load_post(
        load_id, TEST_USERS["platform_admin_headers"]))


def get_truck(truck_id):
    return get_success_data(api_client.get_truck_post(
        truck_id, TEST_USERS["platform_admin_headers"]))


def get_booking(booking_id):
    return get_success_data(api_client.get_booking(
        booking_id, TEST_USERS["platform_admin_headers"]))


def get_fraud_alert(alert_id):
    return get_success_data(api_client.get_fraud_alert(
        alert_id, TEST_USERS["compliance_analyst_headers"]))


def get_rate_transaction(rt_id):
    return get_success_data(api_client.get_rate_transaction(
        rt_id, TEST_USERS["platform_admin_headers"]))


def get_credit_event(event_id):
    return get_success_data(api_client.get_credit_report_event(
        event_id, TEST_USERS["platform_admin_headers"]))


def get_dispute(dispute_id):
    return get_success_data(api_client.get_credit_dispute(
        dispute_id, TEST_USERS["platform_admin_headers"]))


def list_broker_subscriptions(broker_id):
    from prd_bench_local_runner.testing import validate_paginated
    data, _meta = validate_paginated(
        api_client.list_subscriptions(TEST_USERS["platform_admin_headers"],
                                      params={"broker_org_id": broker_id}))
    return data
