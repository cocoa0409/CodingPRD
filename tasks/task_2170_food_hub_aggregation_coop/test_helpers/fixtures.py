"""Composite setup helpers.

These encapsulate the multi-step preambles the workflows in the PRD require so
that individual tests can concentrate on the behaviour under assertion.  Every
helper builds its preconditions from scratch through declared operations only.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ALL_DOC_TYPES,
    APPROVER_USER_ID,
    CLOCK_BASE,
    HUB_ADMIN_USER_ID,
    REQUIRED_DOC_TYPES,
    TEST_DEFAULTS,
    VERIFIER_USER_ID,
)
from .factories import (
    create_buyer_order_payload,
    create_buyer_payload,
    create_delivery_route_payload,
    create_dock_appointment_payload,
    create_dock_slot_payload,
    create_order_line_payload,
    create_producer_document_payload,
    create_producer_payload,
    create_product_payload,
    create_rejection_claim_payload,
    create_route_stop_payload,
    publish_offer_payload,
)
from .test_users import (
    make_board_director_headers,
    make_buyer_headers,
    make_compliance_officer_headers,
    make_hub_admin_headers,
    make_producer_headers,
)

HUB = make_hub_admin_headers(HUB_ADMIN_USER_ID)


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers=None):
    """Move the logical hub clock.  Every temporal assertion is driven here."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or HUB))


def read_producer(producer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_producer(producer_id, headers or HUB))


def read_product(product_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_product(product_id, headers or HUB))


def read_buyer(buyer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_buyer(buyer_id, headers or HUB))


def read_order(order_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_buyer_order(order_id, headers or HUB))


def read_allocation(allocation_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_allocation(allocation_id, headers or HUB))


def read_dock_slot(dock_slot_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_dock_slot(dock_slot_id, headers or HUB))


def read_dock_appointment(appointment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_dock_appointment(appointment_id, headers or HUB)
    )


def read_route(route_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_delivery_route(route_id, headers or HUB))


def read_cycle(cycle_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_patronage_cycle(cycle_id, headers or HUB))


def read_order_line(order_id: str, line_id: str, headers=None) -> dict:
    body = get_success_data(api_client.list_order_lines(order_id, headers or HUB,
                                                        params={"limit": 100}))
    for line in body:
        if line["id"] == line_id:
            return line
    raise AssertionError(f"Setup failed: order line {line_id} not found on {order_id}")


def product_version(product_id: str) -> int:
    return read_product(product_id)["version"]


def dock_slot_version(dock_slot_id: str) -> int:
    return read_dock_slot(dock_slot_id)["version"]


def route_version(route_id: str) -> int:
    return read_route(route_id)["version"]


def allocations_for_line(order_line_id: str) -> list:
    return get_success_data(
        api_client.list_allocations(HUB, params={"order_line_id": order_line_id,
                                                 "limit": 100})
    )


def allocations_for_product(product_id: str) -> list:
    return get_success_data(
        api_client.list_allocations(HUB, params={"product_id": product_id,
                                                 "limit": 100})
    )


# ---------------------------------------------------------------------------
# Tier 1: producer onboarding state progression
# ---------------------------------------------------------------------------
def create_draft_producer(**overrides) -> dict:
    """Register a prospective member; it lands in DRAFT."""
    return get_success_data(
        api_client.create_producer(create_producer_payload(**overrides), HUB)
    )


def attach_document(producer_id: str, doc_type: str, **overrides) -> dict:
    """Attach one food-safety document; it enters SUBMITTED."""
    payload = create_producer_document_payload(doc_type=doc_type, **overrides)
    return get_success_data(
        api_client.create_producer_document(
            producer_id, payload, make_producer_headers(producer_id)
        )
    )


def onboard_active_producer(
    legal_name="Green Acres Farm",
    region_code="NEV",
    contact_email="ga@example.org",
    doc_types=None,
    expiries=None,
    verifier_user_id=VERIFIER_USER_ID,
    approver_user_id=APPROVER_USER_ID,
) -> dict:
    """Walk one producer all the way from registration to ACTIVE.

    Returns {"producer": <Producer>, "documents": {doc_type: <ProducerDocument>}}.
    ``expiries`` maps a doc_type to a non-default ``expires_on`` instant.
    """
    doc_types = list(doc_types or REQUIRED_DOC_TYPES)
    expiries = expiries or {}
    producer = create_draft_producer(
        legal_name=legal_name, region_code=region_code, contact_email=contact_email
    )
    pid = producer["id"]

    documents = {}
    for doc_type in doc_types:
        kwargs = {}
        if doc_type in expiries:
            kwargs["expires_on"] = expiries[doc_type]
        documents[doc_type] = attach_document(pid, doc_type, **kwargs)

    get_success_data(
        api_client.submit_application(pid, make_producer_headers(pid))
    )
    for doc_type in doc_types:
        get_success_data(
            api_client.adjudicate_document(
                documents[doc_type]["id"],
                {"decision": "VERIFY"},
                make_compliance_officer_headers(verifier_user_id),
            )
        )
    producer = get_success_data(
        api_client.review_producer(
            pid, {"decision": "APPROVE"},
            make_compliance_officer_headers(approver_user_id),
        )
    )
    return {"producer": producer, "producer_id": pid, "documents": documents}


def onboard_audited_producer(**kwargs) -> dict:
    """An ACTIVE producer holding a counting document for all five categories,
    so its food_safety_tier is TIER_AUDITED."""
    kwargs.setdefault("doc_types", ALL_DOC_TYPES)
    return onboard_active_producer(**kwargs)


# ---------------------------------------------------------------------------
# Tier 2: catalog, buyer and demand
# ---------------------------------------------------------------------------
def create_listed_product(
    producer_id: str,
    quantity_offered=None,
    offer_window_start=None,
    offer_window_end=None,
    **product_overrides,
) -> dict:
    """Create a catalog item and publish its first offer, moving it to LISTED."""
    headers = make_producer_headers(producer_id)
    product = get_success_data(
        api_client.create_product(
            create_product_payload(producer_id, **product_overrides), headers
        )
    )
    offer = publish_offer_payload(product["version"])
    if quantity_offered is not None:
        offer["quantity_offered"] = quantity_offered
    if offer_window_start is not None:
        offer["offer_window_start"] = offer_window_start
    if offer_window_end is not None:
        offer["offer_window_end"] = offer_window_end
    return get_success_data(
        api_client.publish_offer(product["id"], offer, headers)
    )


def create_buyer(**overrides) -> dict:
    return get_success_data(
        api_client.create_buyer(create_buyer_payload(**overrides), HUB)
    )


def create_draft_order(buyer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_buyer_order(
            create_buyer_order_payload(buyer_id, **overrides),
            make_buyer_headers(buyer_id),
        )
    )


def add_order_line(order_id: str, buyer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_order_line(
            order_id, create_order_line_payload(**overrides),
            make_buyer_headers(buyer_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: cross-dock and routing
# ---------------------------------------------------------------------------
def create_dock_slot(**overrides) -> dict:
    return get_success_data(
        api_client.create_dock_slot(create_dock_slot_payload(**overrides), HUB)
    )


def book_appointment(dock_slot_id: str, producer_id: str, **overrides) -> dict:
    payload = create_dock_appointment_payload(
        dock_slot_id, producer_id, dock_slot_version(dock_slot_id), **overrides
    )
    return get_success_data(
        api_client.create_dock_appointment(payload, make_producer_headers(producer_id))
    )


def close_appointment(appointment_id: str, outcome: str, **payload_extra) -> dict:
    payload = {"outcome": outcome}
    payload.update(payload_extra)
    return get_success_data(
        api_client.close_appointment(appointment_id, payload, HUB)
    )


def create_route(**overrides) -> dict:
    return get_success_data(
        api_client.create_delivery_route(create_delivery_route_payload(**overrides), HUB)
    )


def add_route_stop(route_id: str, order_id: str, **overrides) -> dict:
    payload = create_route_stop_payload(
        order_id, route_version(route_id), **overrides
    )
    return get_success_data(api_client.create_route_stop(route_id, payload, HUB))


def dispatch_route(route_id: str) -> dict:
    return get_success_data(api_client.dispatch_route(route_id, HUB))


def record_delivery(order_id: str, line_receipts: list) -> dict:
    return get_success_data(
        api_client.record_delivery(order_id, {"line_receipts": line_receipts}, HUB)
    )


def invoice_order(order_id: str) -> dict:
    return get_success_data(api_client.invoice_order(order_id, HUB))


def pay_order(order_id: str, buyer_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.create_payment(
            order_id, {"amount_cents": amount_cents}, make_buyer_headers(buyer_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 4: the standard end-to-end scenario, stopped at a named stage
# ---------------------------------------------------------------------------
STAGES = [
    "draft",
    "aggregated",
    "scheduled",
    "booked",
    "staged",
    "in_transit",
    "delivered",
    "invoiced",
    "paid",
]


def _stage_at_least(stage: str, target: str) -> bool:
    return STAGES.index(stage) >= STAGES.index(target)


def setup_scenario(
    stage="aggregated",
    clock=CLOCK_BASE,
    producer_doc_types=None,
    producer_expiries=None,
    product_price_cents=None,
    quantity_offered=None,
    units_per_pallet=None,
    offer_window_start=None,
    offer_window_end=None,
    credit_limit_cents=None,
    payment_terms_days=None,
    requested_delivery_date=None,
    line_quantity=None,
    max_unit_price_cents=None,
    route_storage_class=None,
    route_pallet_capacity=None,
    planned_arrival_at=None,
    service_minutes=None,
    temp_setpoint_c=None,
    recorded_temp_c=None,
    appointment_pallets=None,
    delivered_quantity=None,
) -> dict:
    """Build the canonical one-producer / one-buyer / one-line pipeline and stop
    at ``stage``.

    Stages, in order: draft, aggregated, scheduled, booked, staged, in_transit,
    delivered, invoiced, paid.  Returns a dict of the ids and the latest read of
    every entity involved.
    """
    assert stage in STAGES, f"Unknown scenario stage {stage!r}"

    set_clock(clock)

    onboarded = onboard_active_producer(
        doc_types=producer_doc_types, expiries=producer_expiries
    )
    producer_id = onboarded["producer_id"]

    product_kwargs = {}
    if product_price_cents is not None:
        product_kwargs["producer_unit_price_cents"] = product_price_cents
    if units_per_pallet is not None:
        product_kwargs["units_per_pallet"] = units_per_pallet
    product = create_listed_product(
        producer_id,
        quantity_offered=quantity_offered,
        offer_window_start=offer_window_start,
        offer_window_end=offer_window_end,
        **product_kwargs,
    )

    buyer_kwargs = {}
    if credit_limit_cents is not None:
        buyer_kwargs["credit_limit_cents"] = credit_limit_cents
    if payment_terms_days is not None:
        buyer_kwargs["payment_terms_days"] = payment_terms_days
    buyer = create_buyer(**buyer_kwargs)
    buyer_id = buyer["id"]

    order_kwargs = {}
    if requested_delivery_date is not None:
        order_kwargs["requested_delivery_date"] = requested_delivery_date
    order = create_draft_order(buyer_id, **order_kwargs)
    order_id = order["id"]

    line_kwargs = {}
    if line_quantity is not None:
        line_kwargs["quantity_requested"] = line_quantity
    if max_unit_price_cents is not None:
        line_kwargs["max_unit_price_cents"] = max_unit_price_cents
    line = add_order_line(order_id, buyer_id, **line_kwargs)

    scenario = {
        "producer": onboarded["producer"],
        "producer_id": producer_id,
        "documents": onboarded["documents"],
        "product": product,
        "product_id": product["id"],
        "buyer": buyer,
        "buyer_id": buyer_id,
        "order": order,
        "order_id": order_id,
        "line": line,
        "line_id": line["id"],
        "producer_headers": make_producer_headers(producer_id),
        "buyer_headers": make_buyer_headers(buyer_id),
    }

    if not _stage_at_least(stage, "aggregated"):
        return scenario

    scenario["order"] = get_success_data(api_client.aggregate_order(order_id, HUB))
    allocations = allocations_for_line(line["id"])
    assert allocations, "Setup failed: aggregation produced no allocation"
    scenario["allocations"] = allocations
    scenario["allocation"] = allocations[0]
    scenario["allocation_id"] = allocations[0]["id"]

    if not _stage_at_least(stage, "scheduled"):
        return scenario

    route = create_route(
        storage_class=route_storage_class or TEST_DEFAULTS["STORAGE_CLASS"],
        pallet_capacity=route_pallet_capacity
        or TEST_DEFAULTS["ROUTE_PALLET_CAPACITY"],
    )
    scenario["route"] = route
    scenario["route_id"] = route["id"]
    stop_kwargs = {}
    if planned_arrival_at is not None:
        stop_kwargs["planned_arrival_at"] = planned_arrival_at
    if service_minutes is not None:
        stop_kwargs["service_minutes"] = service_minutes
    scenario["order"] = add_route_stop(route["id"], order_id, **stop_kwargs)

    if not _stage_at_least(stage, "booked"):
        return scenario

    dock_slot = create_dock_slot(
        temp_setpoint_c=(
            temp_setpoint_c if temp_setpoint_c is not None
            else TEST_DEFAULTS["TEMP_SETPOINT_C"]
        )
    )
    scenario["dock_slot"] = dock_slot
    scenario["dock_slot_id"] = dock_slot["id"]
    appointment = book_appointment(
        dock_slot["id"],
        producer_id,
        pallets=(
            appointment_pallets if appointment_pallets is not None
            else TEST_DEFAULTS["APPOINTMENT_PALLETS"]
        ),
    )
    scenario["appointment"] = appointment
    scenario["appointment_id"] = appointment["id"]

    if not _stage_at_least(stage, "staged"):
        return scenario

    scenario["appointment"] = close_appointment(
        appointment["id"],
        "RECEIVED",
        received_pallets=appointment["pallets"],
        recorded_temp_c=(
            recorded_temp_c if recorded_temp_c is not None
            else TEST_DEFAULTS["RECORDED_TEMP_C"]
        ),
    )

    if not _stage_at_least(stage, "in_transit"):
        return scenario

    scenario["route"] = dispatch_route(route["id"])

    if not _stage_at_least(stage, "delivered"):
        return scenario

    receipts = []
    for allocation in scenario["allocations"]:
        qty = (
            allocation["quantity"] if delivered_quantity is None
            else delivered_quantity
        )
        receipts.append(
            {"allocation_id": allocation["id"], "delivered_quantity": qty}
        )
    scenario["order"] = record_delivery(order_id, receipts)

    if not _stage_at_least(stage, "invoiced"):
        return scenario

    scenario["order"] = invoice_order(order_id)

    if not _stage_at_least(stage, "paid"):
        return scenario

    order_now = scenario["order"]
    outstanding = (
        order_now["invoiced_total_cents"]
        - order_now["paid_total_cents"]
        - order_now["credit_memo_cents"]
    )
    scenario["order"] = pay_order(order_id, buyer_id, outstanding)
    return scenario


# ---------------------------------------------------------------------------
# Tier 5: shrink claims and cooperative governance
# ---------------------------------------------------------------------------
def file_claim(allocation_id: str, buyer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rejection_claim(
            create_rejection_claim_payload(allocation_id, **overrides),
            make_buyer_headers(buyer_id),
        )
    )


def approve_claim(claim_id: str, officer_user_id="co-claims-3") -> dict:
    return get_success_data(
        api_client.adjudicate_rejection_claim(
            claim_id, {"decision": "APPROVE"},
            make_compliance_officer_headers(officer_user_id),
        )
    )


def propose_cycle(**overrides) -> dict:
    payload = {"fiscal_year": 2026, "distributable_pool_cents": 1_000_000}
    payload.update(overrides)
    return get_success_data(api_client.create_patronage_cycle(payload, HUB))


def ratify_cycle(cycle_id: str, director_user_id="director-7") -> dict:
    return get_success_data(
        api_client.ratify_patronage_cycle(
            cycle_id, {"decision": "RATIFY"},
            make_board_director_headers(director_user_id),
        )
    )


def distribute_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.distribute_patronage_cycle(cycle_id, HUB))


def setup_paid_order_with_shrink(
    quantity_rejected=5,
    reason_code="TEMP_ABUSE",
    recorded_temp_c=5.5,
    **scenario_kwargs,
) -> dict:
    """An order carried all the way to PAID with one approved rejection claim in
    between, so the producer carries both a gross patronage volume and a shrink
    charge."""
    scenario = setup_scenario(
        stage="invoiced", recorded_temp_c=recorded_temp_c, **scenario_kwargs
    )
    claim = file_claim(
        scenario["allocation_id"],
        scenario["buyer_id"],
        quantity_rejected=quantity_rejected,
        reason_code=reason_code,
    )
    scenario["claim"] = approve_claim(claim["id"])
    scenario["claim_id"] = claim["id"]
    order_now = read_order(scenario["order_id"])
    outstanding = (
        order_now["invoiced_total_cents"]
        - order_now["paid_total_cents"]
        - order_now["credit_memo_cents"]
    )
    scenario["order"] = pay_order(
        scenario["order_id"], scenario["buyer_id"], outstanding
    )
    return scenario


__all__ = [
    "HUB",
    "set_clock",
    "read_producer",
    "read_product",
    "read_buyer",
    "read_order",
    "read_allocation",
    "read_dock_slot",
    "read_dock_appointment",
    "read_route",
    "read_cycle",
    "read_order_line",
    "product_version",
    "dock_slot_version",
    "route_version",
    "allocations_for_line",
    "allocations_for_product",
    "create_draft_producer",
    "attach_document",
    "onboard_active_producer",
    "onboard_audited_producer",
    "create_listed_product",
    "create_buyer",
    "create_draft_order",
    "add_order_line",
    "create_dock_slot",
    "book_appointment",
    "close_appointment",
    "create_route",
    "add_route_stop",
    "dispatch_route",
    "record_delivery",
    "invoice_order",
    "pay_order",
    "setup_scenario",
    "file_claim",
    "approve_claim",
    "propose_cycle",
    "ratify_cycle",
    "distribute_cycle",
    "setup_paid_order_with_shrink",
    "STAGES",
]
