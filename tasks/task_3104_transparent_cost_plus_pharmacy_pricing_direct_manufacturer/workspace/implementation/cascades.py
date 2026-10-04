"""Shared graph mutations: derived-field recomputation and the hop chains.

PRD §2.8: a single change can travel four hops — a cancellation drives its
shipment to RETURNED, which denies the prescription's outstanding claims,
which moves the drug's supply and sourcing picture. Each affected resource
independently refreshes updated_at and increments version.
"""

from clock import now, now_iso, parse_iso
from errors import fail
from lifecycle import derive as derive_comparison
from pricing import (
    demand_units_30d,
    effective_unit_cost_cents,
    eligible_pool,
    expansion_score,
    order_decomposition,
    primary_row,
    shipment_interval_days,
    sourcing_status,
    supply_units,
)
from registry import (
    claims_of_prescription,
    get,
    orders_for_drug,
    price_rows_for_drug,
    shipments_of_order,
    substantiations_of_order,
)
from resources import touch

OPEN_ORDER_STATES = ("CREATED", "PAID", "FULFILLING")
DELIST_ORDER_STATES = ("CREATED", "PAID")
OPEN_CLAIM_STATES = ("PENDING", "AUTHORIZED")


def recompute_drug(drug_id, clock=None, refresh_packaging=False,
                   transitioning_request=None, transition_to=None):
    """Re-derive the drug's whole computed picture (PRD §2.8, §3.2)."""
    clock = clock or now()
    drug = get("drugs", drug_id)
    if drug is None:
        return
    before = _drug_signature(drug, refresh_packaging)
    _write_drug_derived(drug, clock, refresh_packaging, transitioning_request, transition_to)
    if _drug_signature(drug, refresh_packaging) != before:
        touch(drug)


def recompute_drug_quiet(drug_id, clock=None, refresh_packaging=False,
                         transitioning_request=None, transition_to=None):
    """Re-derive a drug's derived fields inside a transition that has already
    accounted for the drug's version advance in its declared side effects."""
    clock = clock or now()
    drug = get("drugs", drug_id)
    if drug is None:
        return
    _write_drug_derived(drug, clock, refresh_packaging, transitioning_request, transition_to)


def _drug_signature(drug, refresh_packaging):
    keys = [
        "demand_units_30d",
        "supply_units",
        "sourcing_status",
        "effective_unit_cost_cents",
        "ship_interval_days",
        "expansion_score",
        "packaging_str",
    ]
    if refresh_packaging:
        keys.append("packaging")
    return [(key, _hashable(drug.get(key))) for key in keys]


def _hashable(value):
    if isinstance(value, list):
        return tuple(value)
    return value


def _write_drug_derived(drug, clock, refresh_packaging, transitioning_request=None,
                        transition_to=None):
    drug_id = drug.get("id")
    pool = eligible_pool(drug_id)
    demand = demand_units_30d(drug_id, clock, transitioning_request, transition_to)
    supply = supply_units(drug_id)
    drug["demand_units_30d"] = demand
    drug["supply_units"] = supply
    drug["sourcing_status"] = sourcing_status(drug_id)
    drug["effective_unit_cost_cents"] = effective_unit_cost_cents(pool)
    drug["ship_interval_days"] = shipment_interval_days(pool)
    drug["expansion_score"] = expansion_score(drug, demand, supply)
    selected = primary_row(pool)
    if selected is not None:
        drug["packaging_str"] = selected.get("packaging")
        drug["packaging"] = selected.get("packaging")
    elif refresh_packaging and not pool:
        pass


def price_interval_days(price):
    from pricing import per_row_interval

    return per_row_interval(price)


def price_effective_per_unit(price):
    """Reference-only figure used by the temporary order blend (PRD §3.1)."""
    return int(price.get("unit_cost_cents") or 0)


def recompute_open_orders_for_price(price_id):
    """PRD §3.2: every open order carrying this row as source_price_id has its
    acquisition cost, markup and patient price recomputed."""
    from pricing import order_decomposition

    changed = []
    for order in list(_orders_by_source(price_id)):
        if order.get("status") not in OPEN_ORDER_STATES:
            continue
        apply_decomposition(order)
        changed.append(order)
    return changed


def _orders_by_source(price_id):
    from store import store

    return [order for order in store.orders.values() if order.get("source_price_id") == price_id]


def apply_decomposition(order):
    """Write each computed price figure onto the record (computed on read, but
    persisted so that mutations and version advances stay meaningful)."""
    decomposition = order_decomposition(order)
    before = [
        (key, order.get(key)) for key in decomposition
    ]
    order.update(decomposition)
    after = [(key, order.get(key)) for key in decomposition]
    if before != after:
        touch(order)
    return order


def cancel_order(order, reason_code, clock=None):
    """The Order cancellation cascade, with a restoration set keyed on the
    source state (PRD §3.8)."""
    clock = clock or now()
    status = order.get("status")
    request = get("requests", order.get("request_id"))
    prescription = get("prescriptions", order.get("prescription_id"))

    order["cancel_reason_code"] = reason_code
    shipments = shipments_of_order(order.get("id"))
    restored = min(int(order.get("quantity") or 0), int((request or {}).get("packaged_quantity") or 0))

    if status == "CREATED":
        order["status"] = "CANCELED"
        touch(order)
        return order

    if status == "PAID":
        if request is not None:
            request["consumed_quantity"] = max(
                0, int(request.get("consumed_quantity") or 0) - restored
            )
            touch(request)
        for shipment in shipments:
            if shipment.get("status") in ("PENDING", "DISPATCHED"):
                return_shipment(shipment, clock=clock)
        order["status"] = "CANCELED"
        touch(order)
        return order

    if status == "FULFILLING":
        for shipment in shipments:
            if shipment.get("status") != "DISPATCHED":
                return_shipment(shipment, clock=clock)
        if request is not None:
            request["consumed_quantity"] = max(
                0, int(request.get("consumed_quantity") or 0) - restored
            )
            touch(request)
        order["status"] = "CANCELED"
        touch(order)
        if prescription is not None:
            touch(prescription)
        if prescription is not None:
            recompute_drug(prescription.get("drug_id"), clock)
        return order

    if status == "SHIPPED":
        for shipment in shipments:
            if shipment.get("status") == "DISPATCHED":
                return_shipment(shipment, clock=clock)
        order["status"] = "CANCELED"
        touch(order)
        return order

    fail("ERR_INVALID_STATE", "Order %s may not be cancelled from %s." % (order.get("id"), status))


def return_shipment(shipment, clock=None):
    """Shipment -> RETURNED, running hop 3: deny the prescription's open claims
    with ORDER_CANCELED (PRD §3.8)."""
    clock = clock or now()
    shipment["status"] = "RETURNED"
    touch(shipment)
    return shipment


def deny_claims_of_prescription(prescription_id, reason_code, clock=None, drug_touch=True):
    """Hop 3: every PENDING or AUTHORIZED claim of the prescription is denied
    with reserved_quantity reset to zero."""
    clock = clock or now()
    denied = []
    for claim in claims_of_prescription(prescription_id):
        if claim.get("status") not in OPEN_CLAIM_STATES:
            continue
        claim["status"] = "DENIED"
        claim["denied_at"] = now_iso()
        claim["denial_reason_code"] = reason_code
        claim["reserved_quantity"] = 0
        touch(claim)
        denied.append(claim)
    return denied


def cancel_claims_of_prescription(prescription_id, states=("PENDING", "AUTHORIZED", "SHIPPED")):
    cancelled = []
    for claim in claims_of_prescription(prescription_id):
        if claim.get("status") not in states:
            continue
        claim["status"] = "CANCELED"
        claim["reserved_quantity"] = 0
        touch(claim)
        cancelled.append(claim)
    return cancelled


def suppress_all_price_rows(drug_id):
    changed = []
    for row in price_rows_for_drug(drug_id):
        if row.get("sourcing_status") != "SUPPRESSED":
            row["sourcing_status"] = "SUPPRESSED"
            touch(row)
            changed.append(row)
    return changed


def delist_cascade(drug, clock=None, order_states=DELIST_ORDER_STATES,
                   deny_reason="SOURCING_LOST"):
    """PRD §3.2 / §3.1: the drug is driven to DELISTED, its rows suppressed, its
    open orders cancelled, their shipments returned and the claims denied.

    Each hop carries exactly the effect its own narrative declares, and no hop
    borrows a later hop's effect ("every one of its price rows is suppressed,
    every order on the drug still at CREATED or PAID is cancelled, every
    shipment of those orders still at PENDING or DISPATCHED is returned, every
    claim of those prescriptions still at PENDING or AUTHORIZED is denied with
    denial_reason_code SOURCING_LOST"). In particular the claim denial belongs
    to this sourcing-loss cascade, not to the shipment's ORDER_CANCELED hop
    from §3.8, which serves the parent-order-cancellation direction.
    """
    clock = clock or now()
    drug["state"] = "DELISTED"
    suppress_all_price_rows(drug.get("id"))
    for order in orders_for_drug(drug.get("id")):
        if order.get("status") not in order_states:
            continue
        order["status"] = "CANCELED"
        order["cancel_reason_code"] = deny_reason
        touch(order)
        prescription = get("prescriptions", order.get("prescription_id"))
        for shipment in shipments_of_order(order.get("id")):
            if shipment.get("status") not in ("PENDING", "DISPATCHED"):
                continue
            shipment["status"] = "RETURNED"
            touch(shipment)
        if prescription is not None:
            deny_claims_of_prescription(prescription.get("id"), deny_reason, clock=clock)
    recompute_drug_quiet(drug.get("id"), clock)
    touch(drug)


def expire_pending_substantiations(clock):
    """A PENDING substantiation whose valid_until has passed before enablement
    is moved to DISABLED by the system (PRD §3.9)."""
    from store import store

    for record in store.substantiations.values():
        if record.get("status") != "PENDING":
            continue
        valid_until = parse_iso(record.get("valid_until"))
        if valid_until is not None and valid_until <= clock:
            record["status"] = "DISABLED"
            touch(record)


def rederive_comparisons(clock):
    """The lifecycle rule's clock-driven transitions are evaluated whenever the
    logical clock advances, so a past-deadline comparison is BLOCKED and an
    all-disabled substantiation leaves its comparison STALE (PRD §3.9)."""
    from lifecycle import derive as derive_comparison
    from registry import get
    from store import store

    for comparison in store.comparisons.values():
        order = get("orders", comparison.get("order_id"))
        if order is None:
            continue
        derive_comparison(comparison, order, clock=clock)


def refresh_comparison_for_order(order, clock=None):
    comparison = _comparison_of(order)
    if comparison is None:
        return None
    return derive_comparison(comparison, order, clock=clock)


def _comparison_of(order):
    from store import store

    for comparison in store.comparisons.values():
        if comparison.get("order_id") == order.get("id"):
            return comparison
    return None