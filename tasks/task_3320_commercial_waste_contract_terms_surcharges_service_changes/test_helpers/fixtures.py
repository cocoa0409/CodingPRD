"""Composite setup helpers.

Every test starts against an empty database (the server is relaunched per test),
so each helper builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls use get_success_data so failures surface as clear
"Setup failed" messages.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_cancellation_request_payload,
    create_competing_offer_payload,
    create_fixed_surcharge_config_payload,
    create_pickup_event_payload,
    create_rate_notice_payload,
    create_rolloff_order_payload,
    create_service_change_request_payload,
    create_service_credit_payload,
    create_service_line_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
HAULER = TEST_USERS["hauler_agent_headers"]


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup failed: clock set -> {resp.text}"


def make_customer(legal_name="Test Co", billing_email="t@example.com"):
    resp = api_client.create_customer(
        {"legal_name": legal_name, "billing_email": billing_email}, ADMIN
    )
    assert resp.status_code == 201, f"Setup failed: create customer -> {resp.text}"
    return get_success_data(resp)


def make_contract(customer_id, start_date="2026-09-01T00:00:00Z", term_months=12, **extra):
    payload = {
        "customer_id": customer_id,
        "start_date": start_date,
        "term_months": term_months,
    }
    payload.update(extra)
    resp = api_client.create_contract(payload, OPS)
    assert resp.status_code == 201, f"Setup failed: create contract -> {resp.text}"
    return get_success_data(resp)


def add_service_line(contract_id, container_size="CY_4", frequency_per_week=2,
                     base_rate_cents=100000):
    resp = api_client.create_service_line(
        contract_id,
        create_service_line_payload(
            container_size=container_size,
            frequency_per_week=frequency_per_week,
            base_rate_cents=base_rate_cents,
        ),
        OPS,
    )
    assert resp.status_code == 201, f"Setup failed: add service line -> {resp.text}"
    return get_success_data(resp)


def activate_contract(contract_id):
    resp = api_client.activate_contract(contract_id, OPS)
    assert resp.status_code == 200, f"Setup failed: activate contract -> {resp.text}"
    return get_success_data(resp)


def make_active_contract(customer_id=None, base_rate_cents=100000, **contract_overrides):
    """Create customer (if not given) + contract + one line, then activate.

    Returns (customer, contract, line)."""
    frequency_per_week = contract_overrides.pop("frequency_per_week", 2)
    container_size = contract_overrides.pop("container_size", "CY_4")
    if customer_id is None:
        customer = make_customer()
        customer_id = customer["id"]
    else:
        customer = get_success_data(api_client.get_customer(customer_id, ADMIN))
    contract = make_contract(customer_id, **contract_overrides)
    line = add_service_line(
        contract["id"], base_rate_cents=base_rate_cents,
        frequency_per_week=frequency_per_week,
        container_size=container_size,
    )
    contract = activate_contract(contract["id"])
    return customer, contract, line


def make_fixed_config(effective_from="2026-09-01T00:00:00Z", **overrides):
    resp = api_client.create_surcharge_config(
        create_fixed_surcharge_config_payload(effective_from=effective_from, **overrides),
        ADMIN,
    )
    assert resp.status_code == 201, f"Setup failed: create surcharge config -> {resp.text}"
    return get_success_data(resp)


def make_rate_notice(contract_id, pct_increase=0.05,
                     effective_date="2026-09-10T00:00:00Z", reason="CPI"):
    resp = api_client.create_rate_notice(
        create_rate_notice_payload(
            contract_id=contract_id, reason=reason,
            pct_increase=pct_increase, effective_date=effective_date,
        ),
        OPS,
    )
    assert resp.status_code == 201, f"Setup failed: create rate notice -> {resp.text}"
    return get_success_data(resp)


def make_service_change(customer_id, line_id, new_frequency_per_week=3,
                        new_container_size="CY_6",
                        effective_date="2026-09-10T00:00:00Z"):
    resp = api_client.create_service_change_request(
        create_service_change_request_payload(
            service_line_id=line_id,
            new_container_size=new_container_size,
            new_frequency_per_week=new_frequency_per_week,
            effective_date=effective_date,
        ),
        make_customer_headers(customer_id),
    )
    assert resp.status_code == 201, f"Setup failed: create service change -> {resp.text}"
    return get_success_data(resp)


def approve_service_change(change_id):
    resp = api_client.approve_service_change(change_id, OPS)
    assert resp.status_code == 200, f"Setup failed: approve service change -> {resp.text}"
    return get_success_data(resp)


def make_competing_offer(customer_id, contract_id, competitor_monthly_cents=90000):
    resp = api_client.create_competing_offer(
        create_competing_offer_payload(
            contract_id=contract_id,
            competitor_monthly_cents=competitor_monthly_cents,
        ),
        make_customer_headers(customer_id),
    )
    assert resp.status_code == 201, f"Setup failed: create competing offer -> {resp.text}"
    return get_success_data(resp)


def make_pickup_event(line_id, occurred_date, outcome, photo_evidence_url=None):
    payload = create_pickup_event_payload(
        service_line_id=line_id, occurred_date=occurred_date, outcome=outcome,
    )
    if photo_evidence_url is not None:
        payload["photo_evidence_url"] = photo_evidence_url
    resp = api_client.create_pickup_event(payload, HAULER)
    assert resp.status_code == 201, f"Setup failed: create pickup event -> {resp.text}"
    return get_success_data(resp)


def make_service_credit(customer_id, line_id, pickup_event_id):
    resp = api_client.create_service_credit(
        create_service_credit_payload(
            service_line_id=line_id, pickup_event_id=pickup_event_id,
        ),
        make_customer_headers(customer_id),
    )
    assert resp.status_code == 201, f"Setup failed: create service credit -> {resp.text}"
    return get_success_data(resp)


def make_cancellation(customer_id, contract_id, requested_end_date):
    resp = api_client.create_cancellation_request(
        create_cancellation_request_payload(
            contract_id=contract_id, requested_end_date=requested_end_date,
        ),
        make_customer_headers(customer_id),
    )
    assert resp.status_code == 201, f"Setup failed: create cancellation -> {resp.text}"
    return get_success_data(resp)


def make_rolloff_order(customer_id, delivery_date="2026-09-05T00:00:00Z", **overrides):
    resp = api_client.create_rolloff_order(
        create_rolloff_order_payload(
            customer_id=customer_id, delivery_date=delivery_date, **overrides,
        ),
        make_customer_headers(customer_id),
    )
    assert resp.status_code == 201, f"Setup failed: create rolloff order -> {resp.text}"
    return get_success_data(resp)


def get_contract_version(contract_id):
    return get_success_data(api_client.get_contract(contract_id, OPS))["version"]


def get_customer_balance(customer_id):
    return get_success_data(api_client.get_customer(customer_id, ADMIN))[
        "credit_balance_cents"
    ]


def make_timely_terminated_contract(notice_days=60, base_rate_cents=200000):
    """ACTIVE 12mo contract (end 2027-09-01), then a timely cancellation
    (requested_end 2026-11-01) approved, terminating the contract immediately.

    Returns (customer, contract, line, cancellation)."""
    set_clock("2026-09-01T00:00:00Z")
    customer = make_customer(legal_name="Reinstate Co", billing_email="ri@x.example")
    customer_id = customer["id"]
    contract = make_contract(
        customer_id, term_months=12, cancellation_notice_days=notice_days,
    )
    line = add_service_line(contract["id"], base_rate_cents=base_rate_cents)
    activate_contract(contract["id"])
    cancellation = make_cancellation(
        customer_id, contract["id"], "2026-11-01T00:00:00Z"
    )
    resp = api_client.approve_cancellation(cancellation["id"], OPS)
    assert resp.status_code == 200, f"Setup failed: approve cancellation -> {resp.text}"
    return customer, contract, line, get_success_data(resp)
