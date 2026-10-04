"""Fountain supply: maintenance gating, syrup delivery quantity boundary."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_error,
    get_success_data,
    seed_active_agreement,
    create_customer,
    create_fountain_account,
    set_clock,
    ops_headers,
)

PA = TEST_USERS["platform_admin_headers"]
FT = TEST_USERS["field_technician_headers"]


def _seed_fountain(env, name="Fizz Cinema"):
    cust = create_customer(env, name=name, channel="FOUNTAIN", local_price_cents=190)
    fa = create_fountain_account(env, cust)
    return cust, fa


def test_syrup_delivery_zero_gallons_rejected_one_gallon_ok(api):
    """PRD §3.5: "**Syrup deliveries** are recorded by a `BottlerOps` operator
    against a fountain account — the account is the delivery's
    `fountain_account_id` parent — with a `gallons` quantity that must be
    strictly greater than zero — a zero or negative delivery is rejected with
    `ERR_ZERO_QUANTITY` (HTTP 400)."
    PRD §3.5: "Each accepted delivery is stamped with `delivered_at`, the
    logical-clock timestamp of the delivery, and its `gallons` is added into
    the account's `syrup_on_hand_gallons`."

    Design: Difficulty/boundary_precision_check/syrup_delivery_zero_gallons_rejected_one_gallon_ok
    """
    env = seed_active_agreement()
    cust, fa = _seed_fountain(env)
    r = api_client.record_maintenance(fa["id"], FT)
    assert r.status_code == 200
    r = api_client.create_syrup_delivery(fa["id"], {"gallons": 0}, ops_headers(env))
    validate_error(r, ApiErrorId.ERR_ZERO_QUANTITY.value)
    assert r.status_code == 400
    r = api_client.create_syrup_delivery(fa["id"], {"gallons": 0.5}, ops_headers(env))
    assert r.status_code == 201, f"positive delivery must be accepted: {r.text}"
    account = get_success_data(api_client.get_fountain_account(fa["id"], PA))
    assert account["syrup_on_hand_gallons"] == pytest.approx(0.5)


def test_syrup_delivery_negative_gallons_rejected(api):
    """PRD §3.5: "**Syrup deliveries** are recorded by a `BottlerOps` operator
    against a fountain account — the account is the delivery's
    `fountain_account_id` parent — with a `gallons` quantity that must be
    strictly greater than zero — a zero or negative delivery is rejected with
    `ERR_ZERO_QUANTITY` (HTTP 400)."

    Design: Difficulty/boundary_precision_check/syrup_delivery_zero_gallons_rejected_one_gallon_ok
    """
    env = seed_active_agreement()
    cust, fa = _seed_fountain(env)
    r = api_client.record_maintenance(fa["id"], FT)
    assert r.status_code == 200
    r = api_client.create_syrup_delivery(fa["id"], {"gallons": -1}, ops_headers(env))
    validate_error(r, ApiErrorId.ERR_ZERO_QUANTITY.value)
    assert r.status_code == 400
    account = get_success_data(api_client.get_fountain_account(fa["id"], PA))
    assert account["syrup_on_hand_gallons"] == 0, "rejected delivery must add nothing"


def test_maintenance_overdue_gates_syrup_delivery_and_resets(api):
    """PRD §3.5: "`maintenance_overdue` is a derived boolean: it is true
    whenever no maintenance visit has been recorded for the account within the
    trailing 90 days as measured against the logical clock."
    PRD §3.5: "A delivery is refused outright while `maintenance_overdue` is
    true, rejected with `ERR_FOUNTAIN_MAINTENANCE_OVERDUE` (HTTP 409); the
    bottler must first get a technician on site."
    PRD §3.5: "A `FieldTechnician` records a **maintenance visit** against the
    account, which clears `maintenance_overdue` to false — and, by refreshing
    the trailing-90-day window against the logical clock, re-enables syrup
    deliveries."

    Design: Corner/calculations/maintenance_overdue_gates_syrup_delivery_and_resets
    """
    env = seed_active_agreement()
    cust, fa = _seed_fountain(env)
    # fresh account: no visit within trailing 90 days -> overdue
    r = api_client.create_syrup_delivery(fa["id"], {"gallons": 10}, ops_headers(env))
    validate_error(r, ApiErrorId.ERR_FOUNTAIN_MAINTENANCE_OVERDUE.value)
    assert r.status_code == 409
    r = api_client.record_maintenance(fa["id"], FT)
    assert r.status_code == 200
    r = api_client.create_syrup_delivery(fa["id"], {"gallons": 10}, ops_headers(env))
    assert r.status_code == 201
    # advance clock 100 days past the visit: overdue again
    set_clock("2026-12-10T00:00:00Z")
    r = api_client.create_syrup_delivery(fa["id"], {"gallons": 5}, ops_headers(env))
    validate_error(r, ApiErrorId.ERR_FOUNTAIN_MAINTENANCE_OVERDUE.value)
    assert r.status_code == 409
    account = get_success_data(api_client.get_fountain_account(fa["id"], PA))
    assert account["syrup_on_hand_gallons"] == pytest.approx(10), (
        "rejected delivery must add nothing to syrup_on_hand_gallons"
    )
