"""Composite setup helpers.

Every test runs against a freshly launched server with an empty database and a
logical clock reading 2026-08-01T00:00:00Z, so every helper here builds its
preconditions from scratch using only PRD-declared endpoints.

Identity threading: the acting `X-User-ID` for a `Producer` is the Producer id,
for a `DeviceSupplierRep` the DeviceSupplier id and for a `HarvestFacilityOperator`
the harvest Premises id. Helpers always thread the real identifier through.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_SERIAL_START
from .factories import (
    ain_for_serial,
    apply_tag_payload,
    create_device_supplier_payload,
    create_hold_order_payload,
    create_incentive_award_payload,
    create_movement_payload,
    create_premises_payload,
    create_producer_payload,
    create_reconciliation_run_payload,
    create_tag_lot_payload,
    create_trace_request_payload,
    defect_report_payload,
    dispute_movement_payload,
    receive_movement_payload,
    set_clock_payload,
    submit_reconciliation_payload,
)
from .test_users import (
    APPROVING_ADMIN_ID,
    OPENING_ANALYST_ID,
    REGISTERING_ADMIN_ID,
    STATE_OFFICIAL_ID,
    make_harvest_operator_headers,
    make_producer_headers,
    make_program_admin_headers,
    make_state_official_headers,
    make_supplier_rep_headers,
    make_trace_analyst_headers,
)

ADMIN_REG = make_program_admin_headers(REGISTERING_ADMIN_ID)
ADMIN_APR = make_program_admin_headers(APPROVING_ADMIN_ID)
OFFICIAL = make_state_official_headers(STATE_OFFICIAL_ID)
ANALYST = make_trace_analyst_headers(OPENING_ANALYST_ID)


# ==========================================================================
# Tier 0 — primitives
# ==========================================================================
def set_clock(to_iso8601: str) -> str:
    """Drive the logical clock and return the resulting current_utc value."""
    data = get_success_data(api_client.set_current_utc(set_clock_payload(to_iso8601), ADMIN_REG))
    return data["current_utc"]


def register_producer(**overrides) -> dict:
    """Register a producer as a ProgramAdmin."""
    return get_success_data(
        api_client.create_producer(create_producer_payload(**overrides), ADMIN_REG)
    )


def register_premises(producer_id: str, **overrides) -> dict:
    """Register a premises as its owning producer; starts PENDING_REVIEW."""
    return get_success_data(
        api_client.create_premises(
            create_premises_payload(producer_id, **overrides),
            make_producer_headers(producer_id),
        )
    )


def approve_premises(premises_id: str, official_id: str = STATE_OFFICIAL_ID) -> dict:
    """Move a premises PENDING_REVIEW -> ACTIVE as a state official."""
    return get_success_data(
        api_client.approve_premises(premises_id, make_state_official_headers(official_id))
    )


def create_active_premises(producer_id: str, **overrides) -> dict:
    """Register a premises and approve its registration in one step."""
    premises = register_premises(producer_id, **overrides)
    return approve_premises(premises["id"])


def register_supplier(**overrides) -> dict:
    """Register a device supplier; starts PENDING_REVIEW."""
    return get_success_data(
        api_client.create_device_supplier(create_device_supplier_payload(**overrides), ADMIN_REG)
    )


def approve_supplier(supplier_id: str) -> dict:
    """Approve a supplier with a second administrator (segregation of duties)."""
    return get_success_data(api_client.approve_device_supplier(supplier_id, ADMIN_APR))


def create_approved_supplier(**overrides) -> dict:
    supplier = register_supplier(**overrides)
    return approve_supplier(supplier["id"])


def read_supplier(supplier_id: str) -> dict:
    return get_success_data(api_client.get_device_supplier(supplier_id, ADMIN_REG))


def read_supplier_version(supplier_id: str) -> int:
    return read_supplier(supplier_id)["version"]


def read_premises(premises_id: str) -> dict:
    return get_success_data(api_client.get_premises(premises_id, ADMIN_REG))


def read_premises_version(premises_id: str) -> int:
    return read_premises(premises_id)["version"]


def read_producer(producer_id: str) -> dict:
    return get_success_data(api_client.get_producer(producer_id, ADMIN_REG))


def read_animal(animal_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_animal(animal_id, headers or ADMIN_REG))


def read_tag_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_tag_lot(lot_id, ADMIN_REG))


def read_tag(tag_id: str) -> dict:
    return get_success_data(api_client.get_tag(tag_id, ADMIN_REG))


def read_movement(movement_id: str) -> dict:
    return get_success_data(api_client.get_movement_event(movement_id, ADMIN_REG))


def read_trace_request(trace_id: str) -> dict:
    return get_success_data(api_client.get_trace_request(trace_id, ADMIN_REG))


def read_hold_order(hold_id: str) -> dict:
    return get_success_data(api_client.get_hold_order(hold_id, ADMIN_REG))


def report_defects(supplier_id: str, defect_count: int, **overrides) -> dict:
    """File defect reports against a supplier as a state official."""
    return get_success_data(
        api_client.report_device_defects(
            supplier_id, defect_report_payload(defect_count, **overrides), OFFICIAL
        )
    )


def issue_lot(
    supplier_id: str,
    premises_id: str,
    serial_start: int = DEFAULT_SERIAL_START,
    quantity: int = 10,
) -> dict:
    """Issue a serial range, always against a freshly read supplier version."""
    payload = create_tag_lot_payload(
        supplier_id,
        premises_id,
        read_supplier_version(supplier_id),
        serial_start=serial_start,
        quantity=quantity,
    )
    return get_success_data(
        api_client.create_tag_lot(payload, make_supplier_rep_headers(supplier_id))
    )


def apply_device(
    lot_id: str,
    producer_id: str,
    serial: int,
    birth_premises_id: str,
    aid_prefix: str = "840",
    **overrides,
) -> dict:
    """Apply one device from a lot; returns the newly created animal."""
    payload = apply_tag_payload(
        ain_for_serial(serial, aid_prefix), birth_premises_id, **overrides
    )
    return get_success_data(
        api_client.apply_tag(lot_id, payload, make_producer_headers(producer_id))
    )


def tag_of_animal(animal_id: str, headers=None) -> dict:
    """Return the animal's currently APPLIED device."""
    rows = get_success_data(
        api_client.list_tags(headers or ADMIN_REG, params={"animal_id": animal_id})
    )
    applied = [row for row in rows if row["device_status"] == "APPLIED"]
    assert applied, f"expected an APPLIED device for animal {animal_id}, got {rows}"
    return applied[0]


def sightings_of_animal(animal_id: str, include_reversed: bool = False, headers=None) -> list:
    params = {"animal_id": animal_id}
    if include_reversed:
        params["include_reversed"] = "true"
    return get_success_data(api_client.list_sightings(headers or ADMIN_REG, params=params))


def enroll_producer(producer_id: str) -> dict:
    return get_success_data(
        api_client.enroll_producer(producer_id, make_producer_headers(producer_id))
    )


def report_departure(
    producer_id: str,
    animal_id: str,
    origin_premises_id: str,
    destination_premises_id: str,
    departed_at: str,
    **overrides,
) -> dict:
    payload = create_movement_payload(
        animal_id, origin_premises_id, destination_premises_id, departed_at, **overrides
    )
    return get_success_data(
        api_client.create_movement_event(payload, make_producer_headers(producer_id))
    )


def receive_arrival(movement_id: str, producer_id: str, arrived_at: str) -> dict:
    return get_success_data(
        api_client.receive_movement_event(
            movement_id, receive_movement_payload(arrived_at), make_producer_headers(producer_id)
        )
    )


def dispute_movement(movement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.dispute_movement_event(
            movement_id, dispute_movement_payload(**overrides), OFFICIAL
        )
    )


def open_reconciliation_run(
    premises_id: str,
    producer_id: str,
    period_start: str = "2026-08-01",
    period_end: str = "2026-08-31",
) -> dict:
    """Open a reconciliation run against a freshly read premises version."""
    payload = create_reconciliation_run_payload(
        premises_id, read_premises_version(premises_id), period_start, period_end
    )
    return get_success_data(
        api_client.create_reconciliation_run(payload, make_producer_headers(producer_id))
    )


def submit_reconciliation_run(run_id: str, producer_id: str, physical_unapplied_count: int) -> dict:
    return get_success_data(
        api_client.submit_reconciliation_run(
            run_id,
            submit_reconciliation_payload(physical_unapplied_count),
            make_producer_headers(producer_id),
        )
    )


def approve_reconciliation_run(run_id: str, official_id: str = STATE_OFFICIAL_ID) -> dict:
    return get_success_data(
        api_client.approve_reconciliation_run(run_id, make_state_official_headers(official_id))
    )


def propose_hold(
    premises_id: str,
    effective_from: str = "2026-08-01T00:00:00Z",
    effective_until: str = "2026-08-30T00:00:00Z",
    official_id: str = STATE_OFFICIAL_ID,
    **overrides,
) -> dict:
    """Propose a quarantine hold against a freshly read premises version."""
    payload = create_hold_order_payload(
        premises_id,
        read_premises_version(premises_id),
        effective_from=effective_from,
        effective_until=effective_until,
        **overrides,
    )
    return get_success_data(
        api_client.create_hold_order(payload, make_state_official_headers(official_id))
    )


def activate_hold(hold_id: str, official_id: str = STATE_OFFICIAL_ID) -> dict:
    return get_success_data(
        api_client.activate_hold_order(hold_id, make_state_official_headers(official_id))
    )


def release_hold(hold_id: str, official_id: str = STATE_OFFICIAL_ID) -> dict:
    return get_success_data(
        api_client.release_hold_order(hold_id, make_state_official_headers(official_id))
    )


def open_trace(index_animal_id: str, analyst_id: str = OPENING_ANALYST_ID, **overrides) -> dict:
    payload = create_trace_request_payload(index_animal_id, **overrides)
    return get_success_data(
        api_client.create_trace_request(payload, make_trace_analyst_headers(analyst_id))
    )


def run_trace(trace_id: str, analyst_id: str = OPENING_ANALYST_ID) -> dict:
    return get_success_data(
        api_client.run_trace_request(trace_id, make_trace_analyst_headers(analyst_id))
    )


def accrue_award(producer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_incentive_award(
            create_incentive_award_payload(producer_id, **overrides), ADMIN_REG
        )
    )


def pay_award(award_id: str) -> dict:
    return get_success_data(api_client.pay_incentive_award(award_id, ADMIN_REG))


def clawback_award(award_id: str) -> dict:
    return get_success_data(api_client.clawback_incentive_award(award_id, ADMIN_REG))


def retire_device(tag_id: str, harvest_premises_id: str, harvested_at: str, **overrides) -> dict:
    from .factories import retire_tag_payload

    payload = retire_tag_payload(harvest_premises_id, harvested_at, **overrides)
    return get_success_data(
        api_client.retire_tag(tag_id, payload, make_harvest_operator_headers(harvest_premises_id))
    )


# ==========================================================================
# Tier 1/2 — entity hierarchy scenarios
# ==========================================================================
def setup_lot_scenario(
    operation_type: str = "COW_CALF",
    state_code: str = "CO",
    capacity: int = 10,
    quantity: int = 10,
    serial_start: int = DEFAULT_SERIAL_START,
    privacy_level: str = None,
    legal_name: str = "Test Cattle Company",
) -> dict:
    """An ACTIVE premises owned by one producer, an APPROVED supplier, and one
    issued lot. The most common preamble in the suite.

    Returns producer, premises, supplier, lot plus the role headers threaded
    with the real entity identifiers.
    """
    producer_overrides = {"legal_name": legal_name, "state_code": state_code}
    if privacy_level is not None:
        producer_overrides["privacy_level"] = privacy_level
    producer = register_producer(**producer_overrides)
    premises = create_active_premises(
        producer["id"],
        operation_type=operation_type,
        state_code=state_code,
        capacity=capacity,
    )
    supplier = create_approved_supplier()
    lot = issue_lot(supplier["id"], premises["id"], serial_start, quantity)
    return {
        "producer": producer,
        "premises": premises,
        "supplier": supplier,
        "lot": lot,
        "serial_start": serial_start,
        "producer_headers": make_producer_headers(producer["id"]),
        "supplier_headers": make_supplier_rep_headers(supplier["id"]),
    }


def setup_animal_scenario(**kwargs) -> dict:
    """A lot scenario with one device already applied to one animal."""
    scenario = setup_lot_scenario(**kwargs)
    animal = apply_device(
        scenario["lot"]["id"],
        scenario["producer"]["id"],
        scenario["serial_start"],
        scenario["premises"]["id"],
    )
    scenario["animal"] = animal
    scenario["tag"] = tag_of_animal(animal["id"])
    return scenario


def setup_two_premises_scenario(
    origin_type: str = "COW_CALF",
    destination_type: str = "FEEDLOT",
    origin_state: str = "CO",
    destination_state: str = "CO",
    capacity: int = 10,
    quantity: int = 10,
    serial_start: int = DEFAULT_SERIAL_START,
    with_animal: bool = True,
) -> dict:
    """One producer, two ACTIVE premises, an APPROVED supplier and a lot issued
    to the origin premises; optionally one animal already tagged at the origin.
    """
    producer = register_producer(state_code=origin_state)
    origin = create_active_premises(
        producer["id"], operation_type=origin_type, state_code=origin_state, capacity=capacity
    )
    destination = create_active_premises(
        producer["id"],
        operation_type=destination_type,
        state_code=destination_state,
        capacity=capacity,
    )
    supplier = create_approved_supplier()
    lot = issue_lot(supplier["id"], origin["id"], serial_start, quantity)
    scenario = {
        "producer": producer,
        "origin": origin,
        "destination": destination,
        "supplier": supplier,
        "lot": lot,
        "serial_start": serial_start,
        "producer_headers": make_producer_headers(producer["id"]),
        "supplier_headers": make_supplier_rep_headers(supplier["id"]),
    }
    if with_animal:
        animal = apply_device(lot["id"], producer["id"], serial_start, origin["id"])
        scenario["animal"] = animal
        scenario["tag"] = tag_of_animal(animal["id"])
    return scenario


# ==========================================================================
# Tier 3 — supplier conformance targeting
# ==========================================================================
def setup_supplier_with_defects(
    lot_quantity: int,
    defect_count: int,
    premises_capacity: int = 900,
    operation_type: str = "FEEDLOT",
    serial_start: int = DEFAULT_SERIAL_START,
) -> dict:
    """An APPROVED supplier holding one lot of `lot_quantity` devices, then
    `defect_count` defect reports filed against it. Used to drive the
    conformance score onto a chosen threshold band.

    Returns the scenario plus the supplier state as it stood immediately after
    the defect reports were filed.
    """
    scenario = setup_lot_scenario(
        operation_type=operation_type,
        capacity=premises_capacity,
        quantity=lot_quantity,
        serial_start=serial_start,
    )
    supplier_after = report_defects(scenario["supplier"]["id"], defect_count)
    scenario["supplier_after_defects"] = supplier_after
    return scenario


# ==========================================================================
# Tier 4 — sighting-graph targeting for the traceback engine
# ==========================================================================
def setup_environmental_contact_graph() -> dict:
    """Build the two-animal contact graph the traceback tests replay.

    Index animal A is tagged at P1 on 2026-08-01, departs on 2026-08-09 and is
    received at P2 on 2026-08-10, where it still stands. Animal B is tagged at
    P2 on 2026-08-05 and leaves for P3 on 2026-08-07, so B's residency at P2
    closes three days before A arrives. The clock is left at 2026-08-12.
    """
    producer = register_producer(legal_name="Brazos Feeders", state_code="TX")
    p1 = create_active_premises(
        producer["id"], operation_type="COW_CALF", state_code="TX", capacity=50
    )
    p2 = create_active_premises(
        producer["id"], operation_type="FEEDLOT", state_code="TX", capacity=50
    )
    p3 = create_active_premises(
        producer["id"], operation_type="FEEDLOT", state_code="TX", capacity=50
    )
    supplier = create_approved_supplier()
    lot = issue_lot(supplier["id"], p1["id"], DEFAULT_SERIAL_START, 100)

    index_animal = apply_device(
        lot["id"], producer["id"], DEFAULT_SERIAL_START, p1["id"], birth_date="2026-02-01"
    )

    set_clock("2026-08-05T00:00:00Z")
    contact_animal = apply_device(
        lot["id"], producer["id"], DEFAULT_SERIAL_START + 1, p2["id"], birth_date="2026-02-02"
    )

    set_clock("2026-08-07T00:00:00Z")
    contact_move = report_departure(
        producer["id"], contact_animal["id"], p2["id"], p3["id"], "2026-08-07T00:00:00Z"
    )
    receive_arrival(contact_move["id"], producer["id"], "2026-08-07T00:00:00Z")

    set_clock("2026-08-09T00:00:00Z")
    index_move = report_departure(
        producer["id"], index_animal["id"], p1["id"], p2["id"], "2026-08-09T00:00:00Z"
    )

    set_clock("2026-08-10T00:00:00Z")
    receive_arrival(index_move["id"], producer["id"], "2026-08-10T00:00:00Z")

    set_clock("2026-08-12T00:00:00Z")
    return {
        "producer": producer,
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "supplier": supplier,
        "lot": lot,
        "index_animal": index_animal,
        "contact_animal": contact_animal,
        "index_move": index_move,
        "contact_move": contact_move,
        "producer_headers": make_producer_headers(producer["id"]),
    }


def setup_isolated_animal_for_trace() -> dict:
    """One animal that has never moved, so no other animal can be co-located
    with it. The clock is left at 2026-08-12."""
    scenario = setup_animal_scenario(capacity=20, quantity=10)
    set_clock("2026-08-12T00:00:00Z")
    return scenario


# ==========================================================================
# Tier 4 — harvest / retirement targeting
# ==========================================================================
def setup_harvest_ready_animal(
    lot_quantity: int = 10,
    defect_count: int = 0,
    extra_harvest_premises: bool = False,
) -> dict:
    """One animal tagged at a COW_CALF premises, moved to the producer's own
    HARVEST_FACILITY premises and received there. The clock is left at
    2026-08-04, one day after the arrival, so a harvest may be recorded.
    """
    producer = register_producer(legal_name="High Plains Pack", state_code="NE")
    source = create_active_premises(
        producer["id"], operation_type="COW_CALF", state_code="NE", capacity=30
    )
    harvest = create_active_premises(
        producer["id"], operation_type="HARVEST_FACILITY", state_code="NE", capacity=30
    )
    second_harvest = None
    if extra_harvest_premises:
        second_harvest = create_active_premises(
            producer["id"], operation_type="HARVEST_FACILITY", state_code="NE", capacity=30
        )
    supplier = create_approved_supplier()
    lot = issue_lot(supplier["id"], source["id"], DEFAULT_SERIAL_START, lot_quantity)

    supplier_before_retire = None
    if defect_count:
        supplier_before_retire = report_defects(supplier["id"], defect_count)

    animal = apply_device(
        lot["id"], producer["id"], DEFAULT_SERIAL_START, source["id"], birth_date="2026-01-15"
    )

    set_clock("2026-08-02T00:00:00Z")
    movement = report_departure(
        producer["id"], animal["id"], source["id"], harvest["id"], "2026-08-02T00:00:00Z"
    )
    set_clock("2026-08-03T00:00:00Z")
    receive_arrival(movement["id"], producer["id"], "2026-08-03T00:00:00Z")

    tag = tag_of_animal(animal["id"])
    set_clock("2026-08-04T00:00:00Z")
    return {
        "producer": producer,
        "source_premises": source,
        "harvest_premises": harvest,
        "second_harvest_premises": second_harvest,
        "supplier": supplier,
        "supplier_before_retire": supplier_before_retire,
        "lot": lot,
        "animal": animal,
        "movement": movement,
        "tag": tag,
        "producer_headers": make_producer_headers(producer["id"]),
    }


# ==========================================================================
# Tier 5 — enrolment / incentive targeting
# ==========================================================================
def setup_enrolled_producer_with_head(
    premises_count: int = 1,
    animals_per_premises: int = 2,
    capacity: int = 60,
    state_code: str = "AZ",
    legal_name: str = "Verde Valley Beef",
) -> dict:
    """An ENROLLED producer owning `premises_count` ACTIVE premises, each holding
    `animals_per_premises` ACTIVE animals, with no movement events reported (so
    on_time_movement_pct stands at 100.00 and the compliance multiplier is 1.25).
    """
    producer = register_producer(legal_name=legal_name, state_code=state_code)
    premises_list = [
        create_active_premises(
            producer["id"], operation_type="COW_CALF", state_code=state_code, capacity=capacity
        )
        for _ in range(premises_count)
    ]
    supplier = create_approved_supplier()
    total_needed = max(1, premises_count * animals_per_premises)
    lot = issue_lot(
        supplier["id"], premises_list[0]["id"], DEFAULT_SERIAL_START, max(10, total_needed)
    )

    serial = DEFAULT_SERIAL_START
    animals = []
    for premises in premises_list:
        for _ in range(animals_per_premises):
            animals.append(
                apply_device(lot["id"], producer["id"], serial, premises["id"])
            )
            serial += 1

    enrolled = enroll_producer(producer["id"])
    return {
        "producer": enrolled,
        "premises_list": premises_list,
        "premises": premises_list[0],
        "supplier": supplier,
        "lot": lot,
        "animals": animals,
        "producer_headers": make_producer_headers(producer["id"]),
    }


def setup_premises_under_active_hold(
    operation_type: str = "COW_CALF",
    capacity: int = 25,
    with_animal: bool = True,
) -> dict:
    """A producer's ACTIVE premises whose health_status has been driven to
    QUARANTINED by an activated hold order."""
    scenario = setup_two_premises_scenario(
        origin_type=operation_type, capacity=capacity, with_animal=with_animal
    )
    hold = propose_hold(
        scenario["origin"]["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2026-08-30T00:00:00Z",
    )
    scenario["hold"] = activate_hold(hold["id"])
    return scenario
