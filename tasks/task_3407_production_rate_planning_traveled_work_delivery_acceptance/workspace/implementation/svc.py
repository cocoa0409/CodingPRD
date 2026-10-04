"""Domain services: path lookups, serializers, and shared cascade helpers."""
import calc
from core import ApiError, db, dump, new_row, touch


# ---------------------------------------------------------------------------
# Lookups (ladder rung 3: path existence, validated left to right -> 404)
# ---------------------------------------------------------------------------
def need(collection, row_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND")
    return row


def need_program(program_id):
    return need(db.programs, program_id)


def need_rate_case(case_id):
    return need(db.rate_cases, case_id)


def need_supplier(supplier_id):
    return need(db.suppliers, supplier_id)


def need_commitment(commitment_id):
    return need(db.commitments, commitment_id)


def need_workforce_plan(plan_id):
    return need(db.workforce_plans, plan_id)


def need_customer(customer_id):
    return need(db.customers, customer_id)


def need_aircraft(aircraft_id):
    return need(db.aircraft, aircraft_id)


def need_work_package(package_id):
    return need(db.work_packages, package_id)


def need_rework_order(order_id):
    return need(db.rework_orders, order_id)


def need_escape(escape_id):
    return need(db.escapes, escape_id)


def need_flight_test(test_id):
    return need(db.flight_tests, test_id)


def need_storage(storage_id):
    return need(db.storages, storage_id)


def need_negotiation(negotiation_id):
    return need(db.negotiations, negotiation_id)


# ---------------------------------------------------------------------------
# Serializers -- computed fields are resolved live at read time (PRD 2.9)
# ---------------------------------------------------------------------------
def dump_program(program):
    return dump(program, extra=calc.program_computed(program))


def dump_rate_case(case):
    return dump(case)


def dump_supplier(supplier):
    return dump(supplier)


def dump_commitment(commitment):
    return dump(
        commitment,
        extra={
            "active_ordered_quantity": commitment["ordered_quantity"]
            - commitment["cancelled_quantity"]
        },
    )


def dump_workforce_plan(plan):
    return dump(plan, extra={"readiness_ratio": calc.readiness_ratio(plan)})


def dump_customer(customer):
    return dump(customer)


def dump_aircraft(aircraft):
    return dump(
        aircraft,
        extra={"rework_cost_total_cents": calc.aircraft_rework_total(aircraft["id"])},
    )


def dump_work_package(package):
    return dump(package)


def dump_rework_order(order):
    return dump(order)


def dump_escape(escape):
    return dump(escape, extra={"is_late_notification": calc.is_late_notification(escape)})


def dump_flight_test(test):
    return dump(test)


def dump_storage(storage):
    return dump(
        storage,
        extra={
            "next_preservation_due": calc.next_preservation_due(storage),
            "is_overdue": calc.is_overdue(storage),
        },
    )


def dump_negotiation(negotiation):
    return dump(negotiation)


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def create_rework_order(aircraft_id, source, hours_basis, work_package_id=None, escape_id=None):
    """Provisionally priced per PRD 3.5: hours basis * 15000 * source multiplier."""
    order = new_row(
        "ReworkOrder",
        aircraft_id=aircraft_id,
        work_package_id=work_package_id,
        escape_id=escape_id,
        source=source,
        estimated_cost_cents=calc.provisional_cost(hours_basis, source),
        actual_cost_cents=None,
        status="OPEN",
    )
    db.rework_orders[order["id"]] = order
    return order


def bubble_up_assembly(aircraft):
    """IN_PRODUCTION -> ASSEMBLY_COMPLETE once every work package of the aircraft
    (at least one must exist) sits in COMPLETE or TRAVELED (PRD 3.4)."""
    if aircraft["production_status"] != "IN_PRODUCTION":
        return
    packages = [
        wp for wp in db.work_packages.values() if wp["aircraft_id"] == aircraft["id"]
    ]
    if len(packages) >= 1 and all(
        wp["status"] in ("COMPLETE", "TRAVELED") for wp in packages
    ):
        aircraft["production_status"] = "ASSEMBLY_COMPLETE"
        touch(aircraft)


def any_open_rework(aircraft_id):
    return any(
        ro["aircraft_id"] == aircraft_id and ro["status"] == "OPEN"
        for ro in db.rework_orders.values()
    )


def expire_live_negotiations(aircraft_id):
    """On a failed flight test every live negotiation of the aircraft
    (PROPOSED or COUNTERED) auto-transitions to EXPIRED (PRD 3.8/3.9)."""
    for neg in db.negotiations.values():
        if neg["aircraft_id"] == aircraft_id and neg["status"] in ("PROPOSED", "COUNTERED"):
            neg["status"] = "EXPIRED"
            touch(neg)


def set_quality_hold(aircraft):
    if aircraft["quality_status"] != "HOLD":
        aircraft["quality_status"] = "HOLD"
        touch(aircraft)


def maybe_clear_quality_hold(aircraft):
    """Return quality_status to CLEAR when no escape on the aircraft remains in
    OPEN, ROOT_CAUSE, or DISPOSITIONED (PRD 3.6)."""
    remaining = any(
        e["aircraft_id"] == aircraft["id"] and e["status"] in calc.OPEN_ESCAPE_STATES
        for e in db.escapes.values()
    )
    if not remaining and aircraft["quality_status"] != "CLEAR":
        aircraft["quality_status"] = "CLEAR"
        touch(aircraft)
