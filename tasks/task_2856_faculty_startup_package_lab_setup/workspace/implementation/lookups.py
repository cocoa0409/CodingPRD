"""Existence resolution with the per-entity not-found codes of PRD 2.11."""

import store
from errors import fail

UNIT_TYPES = ("COLLEGE", "DEPARTMENT", "DEAN_OFFICE")


def get_unit(unit_id):
    unit = store.db.funding_units.get(unit_id)
    if unit is None:
        fail("ERR_RESOURCE_NOT_FOUND", "funding unit %s does not exist" % unit_id)
    return unit


def get_unit_typed(unit_id, unit_type, slot):
    """A unit whose unit_type does not match its slot is also a not-found."""
    unit = get_unit(unit_id)
    if unit["unit_type"] != unit_type:
        fail(
            "ERR_RESOURCE_NOT_FOUND",
            "%s must name a %s funding unit" % (slot, unit_type),
        )
    return unit


def get_faculty(faculty_id):
    record = store.db.faculty.get(faculty_id)
    if record is None:
        fail("ERR_FACULTY_NOT_FOUND", "faculty %s does not exist" % faculty_id)
    return record


def get_package(package_id):
    record = store.db.packages.get(package_id)
    if record is None:
        fail("ERR_PACKAGE_NOT_FOUND", "startup package %s does not exist" % package_id)
    return record


def get_tranche(tranche_id, package_id=None):
    record = store.db.tranches.get(tranche_id)
    if record is None or (package_id is not None and record["package_id"] != package_id):
        fail("ERR_TRANCHE_NOT_FOUND", "commitment tranche %s does not exist" % tranche_id)
    return record


def get_space(space_id):
    record = store.db.lab_spaces.get(space_id)
    if record is None:
        fail("ERR_SPACE_NOT_FOUND", "lab space %s does not exist" % space_id)
    return record


def get_project(project_id):
    record = store.db.renovation_projects.get(project_id)
    if record is None:
        fail("ERR_PROJECT_NOT_FOUND", "renovation project %s does not exist" % project_id)
    return record


def get_phase(project_id, phase_id):
    """A phase is only addressable through its own project (PRD 2.11)."""
    record = store.db.renovation_phases.get(phase_id)
    if record is None or record["project_id"] != project_id:
        fail(
            "ERR_PROJECT_NOT_FOUND",
            "renovation phase %s does not belong to project %s" % (phase_id, project_id),
        )
    return record


def get_order(order_id):
    record = store.db.equipment_orders.get(order_id)
    if record is None:
        fail("ERR_ORDER_NOT_FOUND", "equipment order %s does not exist" % order_id)
    return record


def get_appointment(appointment_id):
    record = store.db.staff_appointments.get(appointment_id)
    if record is None:
        fail("ERR_ORDER_NOT_FOUND", "staff appointment %s does not exist" % appointment_id)
    return record


def get_assignment_action(assignment_id):
    """Path id on a /space-assignments/{id}/... action endpoint."""
    record = store.db.space_assignments.get(assignment_id)
    if record is None:
        fail("ERR_ORDER_NOT_FOUND", "space assignment %s does not exist" % assignment_id)
    return record


def get_assignment_resource(assignment_id):
    """Path id on the plain space-assignment read."""
    record = store.db.space_assignments.get(assignment_id)
    if record is None:
        fail("ERR_RESOURCE_NOT_FOUND", "space assignment %s does not exist" % assignment_id)
    return record
