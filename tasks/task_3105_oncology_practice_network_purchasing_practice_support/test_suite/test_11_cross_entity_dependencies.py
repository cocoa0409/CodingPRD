"""Cross-entity state dependencies and compensating conservation invariants."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, set_clock, create_network, create_practice, create_product,
    get_practice, create_activated_contract, create_approved_agreement,
    receive_new_lot, setup_shortage_network, setup_operational_practice,
    make_practice_admin_headers, create_purchase_order_payload, DEFAULT_CLOCK,
)


def test_order_confirmation_requires_live_affiliation_contract(api, network_admin_headers):
    """PRD §3.5: "requires the practice's `ACTIVE` affiliation contract to cover
    the confirmation instant, failing with `ERR_CONTRACT_LAPSED`".
    PRD §2.6: "an order may only be confirmed while the practice's `ACTIVE`
    affiliation contract covers the confirmation instant — broadly, `term_start`
    at or before the confirmation instant and the instant strictly before
    `term_end`."

    Design: Difficulty/cross_entity_state_dependency/order_confirmation_requires_live_affiliation_contract
    """
    set_clock("2026-08-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=90)
    contract = create_activated_contract(practice["id"],
                                         term_start="2026-06-01T00:00:00Z",
                                         term_end="2026-09-01T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-06-01T00:00:00Z")
    product = create_product(network["id"], unit_type="VIAL",
                             network_base_price_cents=4000)

    practice_headers = make_practice_admin_headers(practice["id"])
    covered = validate_success(
        api.create_purchase_order(
            create_purchase_order_payload(practice["id"], product["id"],
                                          quantity_units=50), practice_headers),
        201)
    confirmed = validate_success(api.confirm_order(covered["id"], network_admin_headers), 200)
    assert confirmed["status"] == "CONFIRMED"

    # The same order shape, submitted inside the window but confirmed after it.
    inside = validate_success(
        api.create_purchase_order(
            create_purchase_order_payload(practice["id"], product["id"],
                                          quantity_units=50), practice_headers),
        201)
    set_clock("2026-10-01T00:00:00Z")

    res = api.confirm_order(inside["id"], network_admin_headers)
    validate_error(res, ApiErrorId.ERR_CONTRACT_LAPSED, expected_status=409)

    contract_after = validate_success(
        api.get_affiliation_contract(contract["id"], network_admin_headers), 200)
    assert contract_after["status"] == "ACTIVE"


def test_shortage_order_confirmation_requires_allocation_grant(api, network_admin_headers):
    """PRD §3.5: "If the product is the subject of a shortage in `REPORTED`,
    `ALLOCATING`, or `ACTIVE` status, the order must name a grant for this
    practice covering its `quantity_units`, failing with
    `ERR_NO_SHORTAGE_ALLOCATION`, and that grant must carry that many uncommitted
    units, failing with `ERR_ALLOCATION_OVERCOMMIT` — the same cap applies when a
    shortage-restricted order is first placed."

    Design: Difficulty/cross_entity_state_dependency/shortage_order_confirmation_requires_allocation_grant
    """
    network, product, practices, shortage, grants = setup_shortage_network(
        baselines=[100, 300], supply_available_units=400,
        product_price_cents=2000, authorization_cents=300000)

    p1 = practices[0]
    grant_p1 = next(g for g in grants if g["practice_id"] == p1["id"])
    assert grant_p1["allocated_units"] == 100
    assert grant_p1["allocation_rank"] == 2

    practice_headers = make_practice_admin_headers(p1["id"])

    # An order beyond the grant's units is refused at placement.
    over = api.create_purchase_order(
        create_purchase_order_payload(p1["id"], product["id"], quantity_units=150),
        practice_headers)
    validate_error(over, ApiErrorId.ERR_ALLOCATION_OVERCOMMIT, expected_status=409)

    # An order inside the grant is accepted and commits its units.
    within = validate_success(
        api.create_purchase_order(
            create_purchase_order_payload(p1["id"], product["id"], quantity_units=60),
            practice_headers),
        201)
    confirmed = validate_success(api.confirm_order(within["id"], network_admin_headers), 200)
    assert confirmed["status"] == "CONFIRMED"

    grant_after = validate_success(
        api.get_shortage_allocation(grant_p1["id"], network_admin_headers), 200)
    assert grant_after["committed_units"] == 60
    assert grant_after["status"] == "PARTIALLY_COMMITTED"


def test_shortage_order_without_a_grant_is_refused(api, network_admin_headers):
    """PRD §3.5: "a shortage-restricted order must name a grant covering both its
    quantity and its dollar value, or it is refused with
    `ERR_NO_SHORTAGE_ALLOCATION`".

    Design: Difficulty/cross_entity_state_dependency/shortage_order_confirmation_requires_allocation_grant
    """
    network, product, practices, shortage, grants = setup_shortage_network(
        baselines=[100], supply_available_units=100, product_price_cents=2000)

    # A practice that the allocation run placed no grant for cannot make a
    # shortage-restricted order at all.
    grantless = create_practice(network["id"], drug_shortage_baseline_units=50)
    create_activated_contract(grantless["id"])
    grantless = get_practice(grantless["id"])
    create_approved_agreement(grantless["id"], grantless["version"])

    res = api.create_purchase_order(
        create_purchase_order_payload(grantless["id"], product["id"],
                                      quantity_units=10, shortage_allocation_id=None),
        make_practice_admin_headers(grantless["id"]))
    validate_error(res, ApiErrorId.ERR_NO_SHORTAGE_ALLOCATION, expected_status=409)


def test_shortage_supply_conserved_across_revoke_and_restore(api, network_admin_headers):
    """PRD §2.9: "The sum of `allocated_units` across a shortage's grants,
    counting every grant that is not in `REVOKED` status, plus the shortage's
    `unallocated_units`, equals the shortage's `supply_available_units`."
    PRD §3.4: "A grant is `REVOKED` when its practice reaches `DEPARTED`, and
    revocation returns the grant's entire `allocated_units` — committed or not —
    to unallocated supply."

    Design: Difficulty/compensating_invariant/shortage_supply_conserved_across_revoke_and_restore
    """
    network, product, practices, shortage, grants = setup_shortage_network(
        baselines=[100, 300], supply_available_units=400, product_price_cents=3000)

    p1, p2 = practices[0], practices[1]
    grant_p1 = next(g for g in grants if g["practice_id"] == p1["id"])
    grant_p2 = next(g for g in grants if g["practice_id"] == p2["id"])
    assert grant_p1["allocated_units"] == 100
    assert grant_p2["allocated_units"] == 300

    noticed = validate_success(
        api.departure_notice(p1["id"], make_practice_admin_headers(p1["id"])), 200)
    assert noticed["affiliation_status"] == "DEPARTING"

    shortage_after = validate_success(
        api.get_drug_shortage(shortage["id"], network_admin_headers), 200)
    # PRD §3.4: revocation returns the grant's entire allocated_units to the
    # shortage's unallocated supply.
    assert shortage_after["unallocated_units"] == 100

    grants_after = get_success_data(
        api.list_shortage_grants(shortage["id"], network_admin_headers))
    live = sum(g["allocated_units"] for g in grants_after if g["status"] != "REVOKED")
    # PRD §2.9 Invariant A: live grant units + unallocated supply equals the
    # shortage's supply.
    assert live == 300
    assert live + shortage_after["unallocated_units"] == shortage_after["supply_available_units"]
    assert next(g for g in grants_after
                if g["practice_id"] == p1["id"])["status"] == "REVOKED"


def test_consumption_authorization_conserved_across_commit_and_cancel(api, network_admin_headers):
    """PRD §3.5: "Cancelling an order that drew on a grant decreases the grant's
    `committed_units` and the shortage's `allocated_units` by the order's
    quantity, restoring `unallocated_units` by exactly the same amount."
    PRD §2.9: "Granting a unit out of unallocated supply and revoking it back are
    a compensating pair that leaves the first invariant intact; committing units
    on confirmation and releasing them on cancellation are a compensating pair
    that leaves the second intact."

    Design: Difficulty/compensating_invariant/consumption_authorization_conserved_across_commit_and_cancel
    """
    network, product, practices, shortage, grants = setup_shortage_network(
        baselines=[200], supply_available_units=10000,
        allocation_method="EQUAL_SPLIT", product_price_cents=2000,
        authorization_cents=600000)

    practice = practices[0]
    grant = grants[0]
    practice_headers = make_practice_admin_headers(practice["id"])

    order = validate_success(
        api.create_purchase_order(
            create_purchase_order_payload(practice["id"], product["id"],
                                          quantity_units=100,
                                          shortage_allocation_id=grant["id"]),
            practice_headers),
        201)
    assert order["unit_price_cents"] == 2000

    confirmed = validate_success(api.confirm_order(order["id"], network_admin_headers), 200)
    assert confirmed["status"] == "CONFIRMED"

    shortage_confirmed = validate_success(
        api.get_drug_shortage(shortage["id"], network_admin_headers), 200)
    grant_confirmed = validate_success(
        api.get_shortage_allocation(grant["id"], network_admin_headers), 200)
    assert grant_confirmed["consumed_authorization_cents"] == 200000
    assert shortage_confirmed["unclaimed_authorization_cents"] == 400000

    cancelled = validate_success(api.cancel_order(order["id"], practice_headers), 200)
    assert cancelled["status"] == "CANCELLED"

    grant_after = validate_success(
        api.get_shortage_allocation(grant["id"], network_admin_headers), 200)
    shortage_after = validate_success(
        api.get_drug_shortage(shortage["id"], network_admin_headers), 200)
    assert grant_after["consumed_authorization_cents"] == 0
    assert shortage_after["unclaimed_authorization_cents"] == 600000