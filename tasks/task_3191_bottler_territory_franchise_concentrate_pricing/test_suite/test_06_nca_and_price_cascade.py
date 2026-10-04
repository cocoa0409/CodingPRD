"""National customer agreements: window exclusivity, enrollment, cascade, expiry."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_error,
    validate_success,
    get_success_data,
    seed_active_agreement,
    create_customer,
    create_dsd_order,
    create_nca_payload,
    set_clock,
    ops_headers,
)

PA = TEST_USERS["platform_admin_headers"]
BOA = TEST_USERS["brand_owner_admin_headers"]


def _create_nca(env, code, price, start, end):
    r = api_client.create_nca(
        create_nca_payload(
            brand_owner_id=env["bo"]["id"],
            nca_code=code,
            national_price_cents=price,
            effective_start=start,
            effective_end=end,
        ),
        BOA,
    )
    assert r.status_code == 201, f"Setup failed (nca {code}): {r.text}"
    return get_success_data(r)


def test_nca_overlapping_window_rejected_adjacent_allowed(api):
    """PRD §3.3: "Both publications enforce a window exclusivity rule: no other
    `PUBLISHED` NCA for the same brand owner may have a closed effective
    interval that overlaps this one; overlapping intervals trigger
    `ERR_NCA_WINDOW_OVERLAP` (HTTP 409)."
    PRD §3.3: "an `effective_start` and `effective_end` that together define a
    closed date interval — both endpoints inclusive."

    Design: Corner/validations/nca_overlapping_window_rejected_adjacent_allowed
    """
    env = seed_active_agreement()
    nca1 = _create_nca(env, "NCA-1", 200, "2026-09-01", "2026-09-30")
    r = api_client.publish_nca(nca1["id"], BOA)
    assert r.status_code == 200
    nca2 = _create_nca(env, "NCA-2", 210, "2026-09-15", "2026-10-15")
    nca3 = _create_nca(env, "NCA-3", 220, "2026-10-01", "2026-10-31")
    r = api_client.publish_nca(nca2["id"], BOA)
    validate_error(r, ApiErrorId.ERR_NCA_WINDOW_OVERLAP.value)
    assert r.status_code == 409
    r = api_client.publish_nca(nca3["id"], BOA)
    assert r.status_code == 200, (
        "NCA3 starting the day after NCA1's inclusive end shares no date and must publish"
    )


def test_nca_suspend_republish_cycle_and_expire_lockdown(api):
    """PRD §3.3: "Publishing moves an NCA from `DRAFT` to `PUBLISHED`, and a
    `SUSPENDED` NCA may be re-published back to `PUBLISHED`."
    PRD §3.3: "Once the clock's current date is strictly after `effective_end`,
    the brand owner's staff may expire an NCA in `PUBLISHED` or `SUSPENDED`
    status, moving it to the terminal `EXPIRED` state."
    PRD §2.7: "Any action attempted on an entity already in a terminal state is
    rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) where no more specific
    state error applies."

    Design: Corner/state_machines/nca_suspend_republish_cycle_and_expire_lockdown
    """
    env = seed_active_agreement()
    nca = _create_nca(env, "NCA-2026-01", 200, "2026-09-01", "2026-09-30")
    r = api_client.publish_nca(nca["id"], BOA)
    assert r.status_code == 200
    r = api_client.suspend_nca(nca["id"], BOA)
    assert r.status_code == 200
    r = api_client.publish_nca(nca["id"], BOA)
    assert r.status_code == 200, "republish after suspend must succeed"
    assert get_success_data(r)["status"] == "PUBLISHED"
    set_clock("2026-10-02T00:00:00Z")
    r = api_client.expire_nca(nca["id"], BOA)
    assert r.status_code == 200
    assert get_success_data(r)["status"] == "EXPIRED"
    r = api_client.publish_nca(nca["id"], BOA)
    validate_error(r, ApiErrorId.ERR_ALREADY_TERMINAL.value)
    assert r.status_code == 409


def test_nca_price_band_exactly_five_percent_allowed(api):
    """PRD §3.3: "Before binding, a price-band check compares the customer's
    `local_price_cents` against the NCA's `national_price_cents`: the absolute
    deviation between the two, divided by the national price, must not exceed
    five percent. The comparison is computed in exact rational arithmetic over
    integer cents, and it is strict — a deviation of exactly five percent is
    allowed, while anything strictly greater is rejected with
    `ERR_PRICE_DEVIATION_EXCEEDS_BAND` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/nca_price_band_exactly_five_percent_allowed
    """
    env = seed_active_agreement()
    c_ok = create_customer(env, name="BandMart OK", local_price_cents=190)
    nca = _create_nca(env, "NCA-2026-01", 200, "2026-09-01", "2026-12-31")
    r = api_client.publish_nca(nca["id"], BOA)
    assert r.status_code == 200
    r = api_client.enroll_nca(c_ok["id"], {"nca_id": nca["id"]}, BOA)
    assert r.status_code == 200, "deviation 10/200 == 0.05 exactly must be allowed"
    assert get_success_data(r)["bound_price_cents"] == 200


def test_nca_price_band_above_five_percent_rejected(api):
    """PRD §3.3: "The comparison is computed in exact rational arithmetic over
    integer cents, and it is strict — a deviation of exactly five percent is
    allowed, while anything strictly greater is rejected with
    `ERR_PRICE_DEVIATION_EXCEEDS_BAND` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/nca_price_band_exactly_five_percent_allowed
    """
    env = seed_active_agreement()
    c_bad = create_customer(env, name="BandMart Bad", local_price_cents=189)
    nca = _create_nca(env, "NCA-2026-01", 200, "2026-09-01", "2026-12-31")
    r = api_client.publish_nca(nca["id"], BOA)
    assert r.status_code == 200
    r = api_client.enroll_nca(c_bad["id"], {"nca_id": nca["id"]}, BOA)
    validate_error(r, ApiErrorId.ERR_PRICE_DEVIATION_EXCEEDS_BAND.value)
    assert r.status_code == 422


def test_enroll_nca_against_draft_nca_rejected(api):
    """PRD §3.3: "the referenced NCA must be `PUBLISHED`; enrolling against an
    NCA in any other state is rejected with `ERR_NCA_NOT_PUBLISHED`
    (HTTP 409)."
    PRD §3.4: "At registration, `bound_price_cents` is initialized to the local
    price and `nca_id` is null; the bound price is the effective per-case price
    — the NCA national price while the customer is NCA-bound and the NCA
    remains published, otherwise the local price."

    Design: Corner/errors/enroll_nca_against_draft_nca_rejected
    """
    env = seed_active_agreement()
    cust = create_customer(env, local_price_cents=190)
    nca = _create_nca(env, "NCA-2026-01", 200, "2026-09-01", "2026-12-31")
    r = api_client.enroll_nca(cust["id"], {"nca_id": nca["id"]}, BOA)
    validate_error(r, ApiErrorId.ERR_NCA_NOT_PUBLISHED.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_customer(cust["id"], PA))
    assert after["nca_id"] is None


def test_enroll_nca_reprices_booked_order_and_margin_ledger(api):
    """PRD §3.3: "A successful enrollment is a three-stage mutation cascade.
    First, the customer's `nca_id` is set and its `bound_price_cents` becomes
    the NCA's `national_price_cents`. Second, that price change triggers
    recomputation of `invoice_total_cents` on every direct-store-delivery order
    of this customer whose `fulfillment_status` is still `BOOKED` — delivered
    or voided orders are historical and untouched. Third, each such recomputed
    invoice pushes the difference between the new total and the old total into
    the `margin_ledger_cents` of the customer's agreement, adding the signed
    delta so the ledger tracks the margin impact of the national price
    binding."

    Design: Difficulty/transitive_cascade/enroll_nca_reprices_booked_order_and_margin_ledger
    """
    env = seed_active_agreement()
    ag_id = env["agreement"]["id"]
    cust = create_customer(env, local_price_cents=190)
    order = create_dsd_order(
        env, cust,
        lines=[{"product_line_id": env["line"]["id"], "quantity_cases": 2, "discount_pct": 0}],
    )
    assert order["invoice_total_cents"] == 380
    nca = _create_nca(env, "NCA-2026-01", 200, "2026-09-01", "2026-12-31")
    r = api_client.publish_nca(nca["id"], BOA)
    assert r.status_code == 200
    r = api_client.enroll_nca(cust["id"], {"nca_id": nca["id"]}, BOA)
    assert r.status_code == 200
    customer = get_success_data(api_client.get_customer(cust["id"], PA))
    assert customer["bound_price_cents"] == 200
    order_after = get_success_data(api_client.get_dsd_order(order["id"], PA))
    assert order_after["invoice_total_cents"] == 400
    agreement = get_success_data(api_client.get_agreement(ag_id, PA))
    assert agreement["margin_ledger_cents"] == 20


def test_enroll_nca_cascade_leaves_delivered_orders_untouched(api):
    """PRD §3.3: "Second, that price change triggers recomputation of
    `invoice_total_cents` on every direct-store-delivery order of this customer
    whose `fulfillment_status` is still `BOOKED` — delivered or voided orders
    are historical and untouched."

    Design: Difficulty/transitive_cascade/enroll_nca_reprices_booked_order_and_margin_ledger
    """
    env = seed_active_agreement()
    cust = create_customer(env, local_price_cents=190)
    order = create_dsd_order(
        env, cust,
        lines=[{"product_line_id": env["line"]["id"], "quantity_cases": 2, "discount_pct": 0}],
    )
    r = api_client.deliver_dsd_order(order["id"], ops_headers(env))
    assert r.status_code == 200
    nca = _create_nca(env, "NCA-2026-01", 200, "2026-09-01", "2026-12-31")
    r = api_client.publish_nca(nca["id"], BOA)
    assert r.status_code == 200
    r = api_client.enroll_nca(cust["id"], {"nca_id": nca["id"]}, BOA)
    assert r.status_code == 200
    order_after = get_success_data(api_client.get_dsd_order(order["id"], PA))
    assert order_after["invoice_total_cents"] == 380, (
        "delivered orders are historical and untouched by the enrollment cascade"
    )


def test_nca_expire_reverts_bound_price_derived_field(api):
    """PRD §3.3: "Expiry fires a revert cascade: every customer whose `nca_id`
    references this NCA has its `bound_price_cents` set back to that customer's
    own `local_price_cents`."
    PRD §3.3: "Once the clock's current date is strictly after `effective_end`,
    the brand owner's staff may expire an NCA in `PUBLISHED` or `SUSPENDED`
    status, moving it to the terminal `EXPIRED` state."

    Design: Corner/cross_cutting_complexity_layers/nca_expire_reverts_bound_price_derived_field
    """
    env = seed_active_agreement()
    cust = create_customer(env, local_price_cents=190)
    nca = _create_nca(env, "NCA-2026-01", 200, "2026-09-01", "2026-09-30")
    r = api_client.publish_nca(nca["id"], BOA)
    assert r.status_code == 200
    r = api_client.enroll_nca(cust["id"], {"nca_id": nca["id"]}, BOA)
    assert r.status_code == 200
    assert get_success_data(r)["bound_price_cents"] == 200
    set_clock("2026-10-02T00:00:00Z")
    r = api_client.expire_nca(nca["id"], BOA)
    assert r.status_code == 200
    assert get_success_data(r)["status"] == "EXPIRED"
    customer = get_success_data(api_client.get_customer(cust["id"], PA))
    assert customer["bound_price_cents"] == 190
