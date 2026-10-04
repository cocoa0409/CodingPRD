"""Composite setup helpers.

Every helper builds its preconditions from scratch through the PRD-declared
endpoints (the server restarts against an empty database before every test).
Creation calls assert the PRD's 201 status; transitions and reads assert 200.
Identity threading rule: after a Customer entity is created, every
ownership-gated call uses make_customer_headers(customer["id"]) — never the
shared fallback header constant.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    create_facility_payload,
    create_room_payload,
    create_strain_payload,
    create_protocol_payload,
    create_colony_payload,
    create_cohort_payload,
    create_health_screen_payload,
    create_customer_payload,
    create_order_payload,
    create_allocation_payload,
    create_shipment_payload,
    create_inspection_payload,
    create_finding,
    create_contract_payload,
)
from .test_users import (
    TEST_USERS,
    FACILITY_MANAGER_USER_ID,
    IACUC_REVIEWER_USER_ID,
    WELFARE_INSPECTOR_USER_ID,
    make_customer_headers,
    make_facility_manager_headers,
    make_iacuc_reviewer_headers,
    make_inspector_headers,
)

_ADMIN = TEST_USERS["admin_headers"]
_FM = TEST_USERS["facility_manager_headers"]
_VET = TEST_USERS["veterinarian_headers"]
_LOGI = TEST_USERS["logistics_headers"]


# ---------------------------------------------------------------------------
# Read helpers (allocations / shipments / screens / inspections have no
# single-object GET in PRD Section 4; they are read through sublists)
# ---------------------------------------------------------------------------

def read_facility(facility_id: str, headers=None) -> dict:
    return validate_success(api_client.get_facility(facility_id, headers or _ADMIN))


def read_room(room_id: str, headers=None) -> dict:
    return validate_success(api_client.get_room(room_id, headers or _ADMIN))


def read_strain(strain_id: str, headers=None) -> dict:
    return validate_success(api_client.get_strain(strain_id, headers or _ADMIN))


def read_colony(colony_id: str, headers=None) -> dict:
    return validate_success(api_client.get_colony(colony_id, headers or _ADMIN))


def read_cohort(cohort_id: str, headers=None) -> dict:
    return validate_success(api_client.get_cohort(cohort_id, headers or _ADMIN))


def read_customer(customer_id: str, headers=None) -> dict:
    return validate_success(api_client.get_customer(customer_id, headers or _ADMIN))


def read_order(order_id: str, headers=None) -> dict:
    return validate_success(api_client.get_order(order_id, headers or _ADMIN))


def read_protocol(protocol_id: str, facility_id: str, headers=None) -> dict:
    # No single-protocol GET exists; read through the facility sublist.
    return find_protocol_in_facility(protocol_id, facility_id, headers=headers)


def read_shipment(shipment_id: str, order_id: str, headers=None) -> dict:
    return find_shipment_in_order(order_id, shipment_id, headers=headers)


def read_allocation(allocation_id: str, order_id: str, headers=None) -> dict:
    return find_allocation_in_order(order_id, allocation_id, headers=headers)


def read_health_screen(screen_id: str, room_id: str, headers=None) -> dict:
    return find_screen_in_room(room_id, screen_id, headers=headers)


def list_allocations_for_order(order_id: str, headers=None) -> list:
    data, _meta = validate_paginated(
        api_client.list_order_allocations(order_id, headers or _ADMIN, params={"limit": 100})
    )
    return data


def list_allocations_for_cohort(cohort_id: str, headers=None) -> list:
    data, _meta = validate_paginated(
        api_client.list_cohort_allocations(cohort_id, headers or _ADMIN, params={"limit": 100})
    )
    return data


def list_shipments_for_order(order_id: str, headers=None) -> list:
    data, _meta = validate_paginated(
        api_client.list_order_shipments(order_id, headers or _ADMIN, params={"limit": 100})
    )
    return data


def list_screens_for_room(room_id: str, headers=None) -> list:
    data, _meta = validate_paginated(
        api_client.list_room_health_screens(room_id, headers or _ADMIN, params={"limit": 100})
    )
    return data


def list_inspections_for_facility(facility_id: str, headers=None) -> list:
    data, _meta = validate_paginated(
        api_client.list_facility_inspections(facility_id, headers or _ADMIN, params={"limit": 100})
    )
    return data


def list_inspections_for_customer(customer_id: str, headers=None) -> list:
    data, _meta = validate_paginated(
        api_client.list_customer_inspections(customer_id, headers or _ADMIN, params={"limit": 100})
    )
    return data


def find_allocation_in_order(order_id: str, allocation_id: str, headers=None) -> dict:
    for alloc in list_allocations_for_order(order_id, headers=headers):
        if alloc["id"] == allocation_id:
            return alloc
    raise AssertionError(f"Allocation {allocation_id} not found under order {order_id}")


def find_shipment_in_order(order_id: str, shipment_id: str, headers=None) -> dict:
    for ship in list_shipments_for_order(order_id, headers=headers):
        if ship["id"] == shipment_id:
            return ship
    raise AssertionError(f"Shipment {shipment_id} not found under order {order_id}")


def find_screen_in_room(room_id: str, screen_id: str, headers=None) -> dict:
    for screen in list_screens_for_room(room_id, headers=headers):
        if screen["id"] == screen_id:
            return screen
    raise AssertionError(f"HealthScreen {screen_id} not found under room {room_id}")


def find_protocol_in_facility(protocol_id: str, facility_id: str = None, headers=None) -> dict:
    """Locate a protocol via its facility's sublist. facility_id may be omitted
    only if the caller already holds a protocol dict with facility_id — prefer
    passing facility_id explicitly."""
    if facility_id is None:
        raise AssertionError("find_protocol_in_facility requires facility_id")
    data, _meta = validate_paginated(
        api_client.list_facility_protocols(facility_id, headers or _ADMIN, params={"limit": 100})
    )
    for proto in data:
        if proto["id"] == protocol_id:
            return proto
    raise AssertionError(f"Protocol {protocol_id} not found under facility {facility_id}")


def find_inspection_in_facility(facility_id: str, inspection_id: str, headers=None) -> dict:
    for insp in list_inspections_for_facility(facility_id, headers=headers):
        if insp["id"] == inspection_id:
            return insp
    raise AssertionError(f"Inspection {inspection_id} not found under facility {facility_id}")


def find_inspection_in_customer(customer_id: str, inspection_id: str, headers=None) -> dict:
    for insp in list_inspections_for_customer(customer_id, headers=headers):
        if insp["id"] == inspection_id:
            return insp
    raise AssertionError(f"Inspection {inspection_id} not found under customer {customer_id}")


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creators and state progression
# ---------------------------------------------------------------------------

def create_registered_facility(**overrides) -> dict:
    """Create a facility (born REGISTERED). Returns the facility."""
    resp = api_client.create_facility(create_facility_payload(**overrides), _ADMIN)
    return get_success_data(resp, 201)


def create_active_room(facility_id: str, **overrides) -> dict:
    """Create a barrier room (born ACTIVE). Returns the room."""
    resp = api_client.create_room(create_room_payload(facility_id, **overrides), _FM)
    return get_success_data(resp, 201)


def create_catalog_strain(**overrides) -> dict:
    """Register a strain in the catalog. Returns the strain."""
    resp = api_client.create_strain(create_strain_payload(**overrides), _ADMIN)
    return get_success_data(resp, 201)


def create_draft_protocol(facility_id: str, submitter_id: str = FACILITY_MANAGER_USER_ID, **overrides) -> dict:
    """Create an IACUC protocol (born DRAFT). Returns the protocol."""
    resp = api_client.create_protocol(
        create_protocol_payload(facility_id, **overrides),
        make_facility_manager_headers(submitter_id),
    )
    return get_success_data(resp, 201)


def transition_protocol(protocol_id: str, target_state: str, headers, **extra_payload) -> dict:
    payload = {"target_state": target_state}
    payload.update(extra_payload)
    resp = api_client.transition_protocol(protocol_id, payload, headers)
    return get_success_data(resp, 200)


def create_approved_protocol(
    facility_id: str,
    submitter_id: str = FACILITY_MANAGER_USER_ID,
    reviewer_id: str = IACUC_REVIEWER_USER_ID,
    **overrides,
) -> dict:
    """Drive a protocol DRAFT -> SUBMITTED -> UNDER_REVIEW -> APPROVED.

    Segregation of duties (PRD Sections 2.1 / 3.9): the approving reviewer
    identity must differ from the submitting operator identity; the defaults
    already differ.
    """
    protocol = create_draft_protocol(facility_id, submitter_id=submitter_id, **overrides)
    transition_protocol(
        protocol["id"], "SUBMITTED", make_facility_manager_headers(submitter_id)
    )
    transition_protocol(
        protocol["id"], "UNDER_REVIEW", make_iacuc_reviewer_headers(reviewer_id)
    )
    transition_protocol(
        protocol["id"], "APPROVED", make_iacuc_reviewer_headers(reviewer_id)
    )
    return find_protocol_in_facility(protocol["id"], facility_id)


def create_active_customer(**overrides) -> dict:
    """Onboard a customer (born ACTIVE). Returns the customer."""
    resp = api_client.create_customer(create_customer_payload(**overrides), _ADMIN)
    return get_success_data(resp, 201)


def customer_headers_for(customer: dict) -> dict:
    """Ownership-correct headers for an entity-backed Customer role."""
    return make_customer_headers(customer["id"])


# ---------------------------------------------------------------------------
# Tier 2 — production-site hierarchy (facility + room + strain + protocol)
# ---------------------------------------------------------------------------

def setup_production_site(
    *,
    facility_overrides=None,
    room_overrides=None,
    strain_overrides=None,
    protocol_overrides=None,
    protocol_quota: int = None,
    submitter_id: str = FACILITY_MANAGER_USER_ID,
    reviewer_id: str = IACUC_REVIEWER_USER_ID,
) -> dict:
    """Facility (REGISTERED) + barrier room (ACTIVE) + catalog strain +
    APPROVED protocol. Returns {"facility", "room", "strain", "protocol"}."""
    facility = create_registered_facility(**(facility_overrides or {}))
    room = create_active_room(facility["id"], **(room_overrides or {}))
    strain = create_catalog_strain(**(strain_overrides or {}))
    proto_over = dict(protocol_overrides or {})
    if protocol_quota is not None:
        proto_over["approved_animal_quota"] = protocol_quota
    protocol = create_approved_protocol(
        facility["id"], submitter_id=submitter_id, reviewer_id=reviewer_id, **proto_over
    )
    return {
        "facility": facility,
        "room": room,
        "strain": strain,
        "protocol": protocol,
    }


# ---------------------------------------------------------------------------
# Tier 3 — colony + cohort lifecycles
# ---------------------------------------------------------------------------

def create_colony_in_room(site: dict, **colony_overrides) -> dict:
    """Found a colony (FOUNDING) in the site's room under its protocol."""
    resp = api_client.create_colony(
        create_colony_payload(
            site["room"]["id"], site["strain"]["id"], site["protocol"]["id"],
            **colony_overrides,
        ),
        _FM,
    )
    return get_success_data(resp, 201)


def transition_colony(colony_id: str, target_state: str, headers=None) -> dict:
    resp = api_client.transition_colony(
        colony_id, {"target_state": target_state}, headers or _FM
    )
    return get_success_data(resp, 200)


def create_cohort_in_colony(colony_id: str, **cohort_overrides) -> dict:
    """Record a weaned cohort (born WEANED) under the colony."""
    resp = api_client.create_cohort(
        create_cohort_payload(colony_id, **cohort_overrides), _FM
    )
    return get_success_data(resp, 201)


def transition_cohort(cohort_id: str, target_state: str, headers=None, **extra_payload) -> dict:
    payload = {"target_state": target_state}
    payload.update(extra_payload)
    resp = api_client.transition_cohort(cohort_id, payload, headers or _FM)
    return get_success_data(resp, 200)


def hold_cohort(cohort_id: str) -> dict:
    """WEANED -> HOLD (requires colony EXPANDING|PRODUCTION and genetic CLEAR)."""
    return transition_cohort(cohort_id, "HOLD", _FM)


def setup_colony_with_cohorts(
    site: dict = None,
    *,
    breeding_pair_count: int = 10,
    cohorts=None,
    advance_to_production: bool = True,
    colony_overrides=None,
) -> dict:
    """Colony FOUNDING -> EXPANDING, then each requested cohort is recorded
    (WEANED), then optionally -> PRODUCTION (requires a live cohort), then any
    cohort spec with hold=True is moved WEANED -> HOLD.

    ``cohorts`` is a list of per-cohort override dicts; each may set
    count_male, count_female, birth_date, avg_weight_g_male,
    avg_weight_g_female, and hold (bool, default False).
    Returns {"site", "colony", "cohorts"}.
    """
    if site is None:
        site = setup_production_site()
    colony_overrides = dict(colony_overrides or {})
    colony_overrides.setdefault("breeding_pair_count", breeding_pair_count)
    colony = create_colony_in_room(site, **colony_overrides)
    transition_colony(colony["id"], "EXPANDING")

    cohort_specs = cohorts if cohorts is not None else [{"count_male": 10, "count_female": 10}]
    created = []
    for spec in cohort_specs:
        spec = dict(spec)
        hold = spec.pop("hold", False)
        cohort = create_cohort_in_colony(colony["id"], **spec)
        created.append({"cohort": cohort, "hold": hold})

    if advance_to_production:
        transition_colony(colony["id"], "PRODUCTION")

    cohorts_out = []
    for entry in created:
        cohort = entry["cohort"]
        if entry["hold"]:
            cohort = hold_cohort(cohort["id"])
        cohorts_out.append(cohort)

    colony = read_colony(colony["id"])
    return {"site": site, "colony": colony, "cohorts": cohorts_out}


def record_snp_panel_result(colony_id: str, result: str, headers=None) -> dict:
    """Record a SNP panel result (CLEAR or DRIFT_DETECTED) as a Veterinarian."""
    resp = api_client.record_snp_panel(colony_id, {"result": result}, headers or _VET)
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 4 — order intake, sourcing, allocation (OCC-aware)
# ---------------------------------------------------------------------------

def create_order_submitted(customer: dict, strain_id: str, **order_overrides) -> dict:
    """Place an order as the owning Customer (customer_id comes from the
    X-User-ID header, never the body). Returns the SUBMITTED order."""
    resp = api_client.create_order(
        create_order_payload(strain_id, **order_overrides),
        make_customer_headers(customer["id"]),
    )
    return get_success_data(resp, 201)


def transition_order(order_id: str, target_state: str, headers, **extra_payload) -> dict:
    """Drive the order machine; returns the updated order."""
    payload = {"target_state": target_state}
    payload.update(extra_payload)
    resp = api_client.transition_order(order_id, payload, headers)
    return get_success_data(resp, 200)


def source_order(order: dict) -> dict:
    """SUBMITTED -> SOURCING as FacilityManager (locks the quote)."""
    return transition_order(order["id"], "SOURCING", _FM)


def backorder_order(order: dict) -> dict:
    """-> BACKORDERED as FacilityManager."""
    return transition_order(order["id"], "BACKORDERED", _FM)


def allocate_order_to_cohort(order: dict, cohort: dict, qty_male: int, qty_female: int) -> tuple:
    """Create a RESERVED allocation with the OCC token taken from the order
    dict's current ``version``. Returns (allocation, refreshed_order) — the
    refreshed order carries the post-create version for the next OCC write."""
    resp = api_client.create_allocation(
        create_allocation_payload(
            order["id"], cohort["id"], order["version"],
            qty_male=qty_male, qty_female=qty_female,
        ),
        _FM,
    )
    allocation = get_success_data(resp, 201)
    return allocation, read_order(order["id"])


def release_allocation_and_refresh(allocation_id: str, order_id: str) -> tuple:
    """Release a RESERVED allocation. Returns (allocation, refreshed_order)."""
    resp = api_client.release_allocation(allocation_id, _FM)
    get_success_data(resp, 200)
    return find_allocation_in_order(order_id, allocation_id), read_order(order_id)


def setup_sourcing_order(
    site: dict = None,
    customer: dict = None,
    *,
    quantity_male: int = 10,
    quantity_female: int = 10,
    cohorts=None,
    breeding_pair_count: int = 10,
    order_overrides=None,
    colony_overrides=None,
    site_kwargs=None,
) -> dict:
    """Full chain: production site + PRODUCTION colony + cohort(s) in HOLD +
    ACTIVE customer + order in SOURCING (quote locked). The default cohort is
    10M/10F at standard weight born at the clock default.

    Returns {"site", "colony", "cohorts", "customer", "order"}."""
    if site is None:
        site = setup_production_site(**(site_kwargs or {}))
    if customer is None:
        customer = create_active_customer()
    cohort_specs = cohorts
    if cohort_specs is None:
        cohort_specs = [{"count_male": 10, "count_female": 10, "hold": True}]
    bundle = setup_colony_with_cohorts(
        site,
        breeding_pair_count=breeding_pair_count,
        cohorts=cohort_specs,
        colony_overrides=colony_overrides,
    )
    over = {"quantity_male": quantity_male, "quantity_female": quantity_female}
    over.update(order_overrides or {})
    order = create_order_submitted(customer, site["strain"]["id"], **over)
    order = source_order(order)
    return {
        "site": site,
        "colony": bundle["colony"],
        "cohorts": bundle["cohorts"],
        "customer": customer,
        "order": order,
    }


def setup_allocated_order(
    site: dict = None,
    customer: dict = None,
    *,
    quantity_male: int = 10,
    quantity_female: int = 10,
    cohorts=None,
    allocations=None,
    order_overrides=None,
    colony_overrides=None,
    site_kwargs=None,
) -> dict:
    """Sourcing chain plus allocation(s) that fully cover the order, so it
    auto-transitions to ALLOCATED.

    ``allocations`` is a list of (cohort_index, qty_male, qty_female) tuples;
    the default allocates the full requested quantity from cohort 0.
    Returns {"site", "colony", "cohorts", "customer", "order", "allocations"}.
    """
    bundle = setup_sourcing_order(
        site,
        customer,
        quantity_male=quantity_male,
        quantity_female=quantity_female,
        cohorts=cohorts,
        order_overrides=order_overrides,
        colony_overrides=colony_overrides,
        site_kwargs=site_kwargs,
    )
    order = bundle["order"]
    alloc_specs = allocations
    if alloc_specs is None:
        alloc_specs = [(0, quantity_male, quantity_female)]
    created = []
    for cohort_index, qty_male, qty_female in alloc_specs:
        allocation, order = allocate_order_to_cohort(
            order, bundle["cohorts"][cohort_index], qty_male, qty_female
        )
        created.append(allocation)
    bundle["order"] = order
    bundle["allocations"] = created
    return bundle


# ---------------------------------------------------------------------------
# Tier 5 — shipment lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_shipment_for_order(order: dict, **shipment_overrides) -> tuple:
    """Plan a shipment for an ALLOCATED order (OCC token from the order dict's
    current version). Returns (shipment, refreshed_order) — the order is now
    SCHEDULED with the version bumped by exactly 1."""
    resp = api_client.create_shipment(
        create_shipment_payload(order["id"], order["version"], **shipment_overrides),
        _LOGI,
    )
    shipment = get_success_data(resp, 201)
    return shipment, read_order(order["id"])


def transition_shipment(shipment_id: str, target_state: str, headers, **extra_payload) -> dict:
    payload = {"target_state": target_state}
    payload.update(extra_payload)
    resp = api_client.transition_shipment(shipment_id, payload, headers)
    return get_success_data(resp, 200)


def setup_scheduled_order(*, shipment_overrides=None, **kwargs) -> dict:
    """Allocated chain plus a PLANNED shipment; the order is SCHEDULED.
    Returns the allocated bundle plus "shipment"."""
    bundle = setup_allocated_order(**kwargs)
    shipment, order = create_shipment_for_order(
        bundle["order"], **(shipment_overrides or {})
    )
    bundle["shipment"] = shipment
    bundle["order"] = order
    return bundle


def drive_shipment_to_in_transit(shipment_id: str) -> dict:
    """PLANNED -> LOADED -> IN_TRANSIT (consumes the order's allocations)."""
    transition_shipment(shipment_id, "LOADED", _LOGI)
    return transition_shipment(shipment_id, "IN_TRANSIT", _LOGI)


def setup_shipped_order(*, shipment_overrides=None, **kwargs) -> dict:
    """Scheduled chain advanced to IN_TRANSIT; the order is SHIPPED and its
    allocations are CONSUMED. Returns the bundle with refreshed "shipment"
    and "order"."""
    bundle = setup_scheduled_order(shipment_overrides=shipment_overrides, **kwargs)
    shipment = drive_shipment_to_in_transit(bundle["shipment"]["id"])
    bundle["shipment"] = shipment
    bundle["order"] = read_order(bundle["order"]["id"])
    return bundle


def accept_shipment(shipment_id: str, order: dict, received_male: int, received_female: int) -> dict:
    """ARRIVED -> ACCEPTED by the owning Customer (receiving protocol)."""
    resp = api_client.transition_shipment(
        shipment_id,
        {
            "target_state": "ACCEPTED",
            "received_male": received_male,
            "received_female": received_female,
        },
        make_customer_headers(order["customer_id"]),
    )
    return get_success_data(resp, 200)


def setup_delivered_order(*, shipment_overrides=None, **kwargs) -> dict:
    """Full lifecycle through receipt acceptance: shipment ACCEPTED, order
    DELIVERED, billing posted. Returns the refreshed bundle."""
    bundle = setup_shipped_order(shipment_overrides=shipment_overrides, **kwargs)
    transition_shipment(bundle["shipment"]["id"], "ARRIVED", _LOGI)
    order = bundle["order"]
    shipment = accept_shipment(
        bundle["shipment"]["id"], order, order["quantity_male"], order["quantity_female"]
    )
    bundle["shipment"] = shipment
    bundle["order"] = read_order(order["id"])
    return bundle


# ---------------------------------------------------------------------------
# Surveillance and inspections
# ---------------------------------------------------------------------------

def create_scheduled_health_screen(room_id: str, **overrides) -> dict:
    """Schedule a health screen (born SCHEDULED) as a Veterinarian."""
    resp = api_client.create_health_screen(
        create_health_screen_payload(room_id, **overrides), _VET
    )
    return get_success_data(resp, 201)


def result_health_screen(screen_id: str, results: list, headers=None) -> dict:
    """Record agent results on a screen as a Veterinarian."""
    resp = api_client.result_health_screen(screen_id, {"results": results}, headers or _VET)
    return get_success_data(resp, 200)


def create_scheduled_inspection(
    *,
    facility_id: str = None,
    customer_id: str = None,
    reporter_id: str = WELFARE_INSPECTOR_USER_ID,
    **overrides,
) -> dict:
    """Schedule a welfare inspection at exactly one site (born SCHEDULED)."""
    payload = create_inspection_payload(**overrides)
    if facility_id is not None:
        payload["facility_id"] = facility_id
    if customer_id is not None:
        payload["customer_id"] = customer_id
    resp = api_client.create_inspection(payload, make_inspector_headers(reporter_id))
    return get_success_data(resp, 201)


def report_inspection_findings(
    inspection_id: str,
    findings: list,
    corrective_deadline: str = None,
    reporter_id: str = WELFARE_INSPECTOR_USER_ID,
) -> dict:
    """File the report as the named inspector. Empty findings close the
    inspection (CLOSED_VERIFIED); non-empty findings open CORRECTIVE_ACTION."""
    payload = {"findings": findings}
    if corrective_deadline is not None:
        payload["corrective_deadline"] = corrective_deadline
    resp = api_client.report_inspection(
        inspection_id, payload, make_inspector_headers(reporter_id)
    )
    return get_success_data(resp, 200)


def verify_inspection(inspection_id: str, outcome: str, verifier_id: str) -> dict:
    """Verify corrective action as a different inspector (segregation of
    duties: verifier identity must differ from the reporter)."""
    resp = api_client.verify_inspection(
        inspection_id, {"outcome": outcome}, make_inspector_headers(verifier_id)
    )
    return get_success_data(resp, 200)


def create_inspection_in_corrective_action(
    *,
    facility_id: str = None,
    customer_id: str = None,
    reporter_id: str = WELFARE_INSPECTOR_USER_ID,
    findings=None,
    corrective_deadline: str = None,
    **overrides,
) -> dict:
    """Inspection driven to CORRECTIVE_ACTION: scheduled then reported with a
    non-empty findings array (a SIGNIFICANT finding requires the deadline)."""
    inspection = create_scheduled_inspection(
        facility_id=facility_id, customer_id=customer_id, reporter_id=reporter_id,
        **overrides,
    )
    if findings is None:
        findings = [create_finding()]
    return report_inspection_findings(
        inspection["id"], findings,
        corrective_deadline=corrective_deadline, reporter_id=reporter_id,
    )


# ---------------------------------------------------------------------------
# Service contracts
# ---------------------------------------------------------------------------

def create_draft_contract(customer: dict, source_strain_id: str, **overrides) -> dict:
    """Create a service contract (born DRAFT) as PlatformAdmin."""
    resp = api_client.create_contract(
        create_contract_payload(customer["id"], source_strain_id, **overrides), _ADMIN
    )
    return get_success_data(resp, 201)


def transition_contract(contract_id: str, target_state: str, headers, **extra_payload) -> dict:
    payload = {"target_state": target_state}
    payload.update(extra_payload)
    resp = api_client.transition_contract(contract_id, payload, headers)
    return get_success_data(resp, 200)


def execute_contract(contract_id: str, customer_id: str) -> dict:
    """DRAFT -> EXECUTED by the owning Customer."""
    return transition_contract(
        contract_id, "EXECUTED", make_customer_headers(customer_id)
    )


# ---------------------------------------------------------------------------
# Logical clock (PRD Section 2.5)
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601: str) -> None:
    """Advance the logical clock as PlatformAdmin; runs the time sweep."""
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601}, _ADMIN)
    get_success_data(resp, 200)


__all__ = [
    # reads
    "read_facility", "read_room", "read_strain", "read_colony", "read_cohort",
    "read_customer", "read_order", "read_protocol", "read_shipment",
    "read_allocation", "read_health_screen",
    "list_allocations_for_order", "list_allocations_for_cohort",
    "list_shipments_for_order", "list_screens_for_room",
    "list_inspections_for_facility", "list_inspections_for_customer",
    "find_allocation_in_order", "find_shipment_in_order", "find_screen_in_room",
    "find_protocol_in_facility", "find_inspection_in_facility",
    "find_inspection_in_customer",
    # tier 1
    "create_registered_facility", "create_active_room", "create_catalog_strain",
    "create_draft_protocol", "transition_protocol", "create_approved_protocol",
    "create_active_customer", "customer_headers_for",
    # tier 2
    "setup_production_site",
    # tier 3
    "create_colony_in_room", "transition_colony", "create_cohort_in_colony",
    "transition_cohort", "hold_cohort", "setup_colony_with_cohorts",
    "record_snp_panel_result",
    # tier 4
    "create_order_submitted", "transition_order", "source_order",
    "backorder_order", "allocate_order_to_cohort",
    "release_allocation_and_refresh", "setup_sourcing_order",
    "setup_allocated_order",
    # tier 5
    "create_shipment_for_order", "transition_shipment", "setup_scheduled_order",
    "drive_shipment_to_in_transit", "setup_shipped_order", "accept_shipment",
    "setup_delivered_order",
    # surveillance / inspections
    "create_scheduled_health_screen", "result_health_screen",
    "create_scheduled_inspection", "report_inspection_findings",
    "verify_inspection", "create_inspection_in_corrective_action",
    # contracts
    "create_draft_contract", "transition_contract", "execute_contract",
    # clock
    "advance_clock",
]
