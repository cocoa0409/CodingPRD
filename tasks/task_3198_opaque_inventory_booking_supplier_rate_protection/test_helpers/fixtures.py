"""Composite setup helpers for the opaque inventory booking domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as api
from .constants import TEST_DEFAULTS
from .factories import (
    create_complaint_case_payload,
    create_customer_payload,
    create_disclosure_zone_payload,
    create_fraud_flag_payload,
    create_opaque_bid_payload,
    create_property_payload,
    create_rate_window_payload,
    create_settlement_batch_payload,
    create_supplier_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
CS = TEST_USERS["customer_service_headers"]
FO = TEST_USERS["finance_ops_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic entity setup
# ---------------------------------------------------------------------------

def reset_clock(to="2026-09-01T00:00:00Z"):
    return get_success_data(api.set_clock({"current_utc": to}, ADMIN))


def create_supplier(**overrides):
    return get_success_data(api.create_supplier(create_supplier_payload(**overrides), ADMIN))


def create_property(supplier_id, **overrides):
    return get_success_data(api.create_property(create_property_payload(supplier_id, **overrides), ADMIN))


def create_rate_window(property_id, **overrides):
    return get_success_data(api.create_rate_window(create_rate_window_payload(property_id, **overrides), ADMIN))


def create_disclosure_zone(**overrides):
    return get_success_data(api.create_disclosure_zone(create_disclosure_zone_payload(**overrides), ADMIN))


def create_customer(**overrides):
    return get_success_data(api.create_customer(create_customer_payload(**overrides), ADMIN))


def create_customer_headers(customer):
    return make_customer_headers(customer["id"])


def place_bid(customer, **overrides):
    """Place an opaque bid as the customer themselves. Returns the PENDING bid."""
    payload = create_opaque_bid_payload(customer["id"], **overrides)
    return get_success_data(api.create_opaque_bid(payload, make_customer_headers(customer["id"])))


# ---------------------------------------------------------------------------
# Tier 2: neighborhood inventory setup
# ---------------------------------------------------------------------------

def setup_inventory(neighborhood, *, supplier_overrides=None, property_overrides=None,
                    window_overrides=None, zone_overrides=None):
    """Supplier + property + disclosure zone + one OPEN rate window in a
    neighborhood. Returns (supplier, property, window, zone)."""
    reset_clock()
    supplier = create_supplier(**(supplier_overrides or {}))
    create_disclosure_zone(neighborhood_code=neighborhood, **(zone_overrides or {}))
    prop = create_property(
        supplier["id"], neighborhood_code=neighborhood, **(property_overrides or {})
    )
    window = create_rate_window(prop["id"], **(window_overrides or {}))
    return supplier, prop, window


def evaluate_bid(bid, customer, *, fail_on_reject=None, expected_status=None):
    """Evaluate a PENDING bid with the customer's CURRENT version.
    Returns the response data (OpaqueBid) or the raw response on error."""
    fresh = get_success_data(api.get_customer(customer["id"], ADMIN))
    payload = {"expected_customer_version": fresh["version"]}
    if fail_on_reject is not None:
        payload["fail_on_reject"] = fail_on_reject
    resp = api.evaluate_opaque_bid(bid["id"], payload, ADMIN)
    if expected_status is not None:
        assert resp.status_code == expected_status, (
            f"evaluate expected {expected_status}, got {resp.status_code}: {resp.text}"
        )
    return resp


def accept_bid(bid, customer):
    """Evaluate a bid expecting acceptance. Returns the ACCEPTED bid."""
    resp = evaluate_bid(bid, customer)
    data = get_success_data(resp)
    assert data["status"] == "ACCEPTED", f"expected ACCEPTED, got {data['status']}"
    return data


def booking_for_customer(customer):
    """Return the (single) booking listed for a customer."""
    resp = api.list_bookings(ADMIN, params={"customer_id": customer["id"]})
    rows, _meta = validate_paginated(resp)
    assert len(rows) == 1, f"expected exactly 1 booking, got {len(rows)}"
    return rows[0]


def setup_accepted_booking(neighborhood, *, supplier_overrides=None,
                           property_overrides=None, window_overrides=None,
                           zone_overrides=None, bid_overrides=None,
                           customer_overrides=None):
    """Full happy path: inventory + customer + FIXED bid accepted.
    Returns (supplier, prop, window, customer, bid, booking)."""
    supplier, prop, window = setup_inventory(
        neighborhood,
        supplier_overrides=supplier_overrides,
        property_overrides=property_overrides,
        window_overrides=window_overrides,
        zone_overrides=zone_overrides,
    )
    customer = create_customer(**(customer_overrides or {}))
    bid = place_bid(customer, neighborhood_code=neighborhood, **(bid_overrides or {}))
    accepted = accept_bid(bid, customer)
    booking = booking_for_customer(customer)
    return supplier, prop, window, customer, accepted, booking


# ---------------------------------------------------------------------------
# Tier 3: complaint lifecycle shortcuts
# ---------------------------------------------------------------------------

def open_complaint(customer, booking, **overrides):
    payload = create_complaint_case_payload(booking["id"], **overrides)
    return get_success_data(api.create_complaint_case(payload, make_customer_headers(customer["id"])))


def resolve_case(case_id, resolution, goodwill_credit_cents=None):
    """start-review + resolve. Returns the RESOLVED case."""
    get_success_data(api.start_review_complaint_case(case_id, CS))
    payload = {"resolution": resolution}
    if goodwill_credit_cents is not None:
        payload["goodwill_credit_cents"] = goodwill_credit_cents
    return get_success_data(api.resolve_complaint_case(case_id, payload, CS))


def setup_booking_with_goodwill(neighborhood, goodwill_cents, **kwargs):
    """Accepted booking + DISSATISFIED_REVEAL case resolved GOODWILL_CREDIT
    + grant-goodwill applied. Returns the full tuple plus the case."""
    supplier, prop, window, customer, bid, booking = setup_accepted_booking(neighborhood, **kwargs)
    case = open_complaint(customer, booking, category="DISSATISFIED_REVEAL",
                          description="disappointed with reveal")
    resolve_case(case["id"], "GOODWILL_CREDIT", goodwill_credit_cents=goodwill_cents)
    get_success_data(api.grant_goodwill(booking["id"], CS))
    booking = get_success_data(api.get_booking(booking["id"], ADMIN))
    return supplier, prop, window, customer, bid, booking, case


def setup_booking_with_service_failure(neighborhood, **kwargs):
    """Accepted booking + SERVICE_FAILURE case resolved FULL_REFUND (not yet
    marked). Returns tuple plus the case."""
    supplier, prop, window, customer, bid, booking = setup_accepted_booking(neighborhood, **kwargs)
    case = open_complaint(customer, booking, category="SERVICE_FAILURE",
                          description="no reservation on arrival")
    resolve_case(case["id"], "FULL_REFUND")
    return supplier, prop, window, customer, bid, booking, case


# ---------------------------------------------------------------------------
# Tier 4: settlement shortcuts
# ---------------------------------------------------------------------------

def create_batch(supplier_id, period_start="2026-10-01T00:00:00Z",
                 period_end="2026-11-01T00:00:00Z"):
    payload = create_settlement_batch_payload(
        supplier_id, period_start_date=period_start, period_end_date=period_end
    )
    return get_success_data(api.create_settlement_batch(payload, FO))


def approve_batch(batch):
    return get_success_data(api.approve_settlement_batch(
        batch["id"], {"expected_settlement_batch_version": batch["version"]}, FO
    ))


# ---------------------------------------------------------------------------
# Tier 5: fraud shortcuts
# ---------------------------------------------------------------------------

def create_manual_flag(customer_id, score_delta=30, reason_code="MANUAL_REVIEW"):
    payload = create_fraud_flag_payload(customer_id, score_delta=score_delta, reason_code=reason_code)
    return get_success_data(api.create_fraud_flag(payload, ADMIN))


def block_customer(customer_id, delta=30):
    """Drive a customer to BLOCKED via two upheld manual flags of `delta` each
    (30 + 30 = 60 >= BLOCKED_THRESHOLD)."""
    f1 = create_manual_flag(customer_id, score_delta=delta)
    get_success_data(api.uphold_fraud_flag(f1["id"], ADMIN))
    f2 = create_manual_flag(customer_id, score_delta=delta)
    get_success_data(api.uphold_fraud_flag(f2["id"], ADMIN))
    return get_success_data(api.get_customer(customer_id, ADMIN))
