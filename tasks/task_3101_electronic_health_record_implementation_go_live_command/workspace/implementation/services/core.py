"""Lookups, serialization and the generic state-transition engine."""

from db import DB, fmt_iso, now_iso
from errors import ERR_INVALID_STATE, fail

# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------


def children_by(table, field, value):
    return [row for row in table.values() if row.get(field) == value]


def program_facilities(program_id):
    return children_by(DB.facilities, "ehr_implementation_id", program_id)


def facility_departments(facility_id):
    return children_by(DB.departments, "facility_id", facility_id)


def department_build_items(department_id):
    return children_by(DB.system_build_items, "department_id", department_id)


def build_item_scenarios(build_item_id):
    return children_by(DB.test_scenarios, "system_build_item_id", build_item_id)


def scenario_defects(scenario_id):
    return children_by(DB.test_defects, "test_scenario_id", scenario_id)


def department_staff(department_id):
    return children_by(DB.staffs, "department_id", department_id)


def staff_assignments(staff_id):
    return children_by(DB.training_assignments, "staff_id", staff_id)


def staff_trainers(staff_id):
    return children_by(DB.credentialed_trainers, "staff_id", staff_id)


def staff_exams(staff_id):
    return children_by(DB.proficiency_exams, "staff_id", staff_id)


def program_channels(program_id):
    return children_by(DB.interface_channels, "ehr_implementation_id", program_id)


def channel_messages(channel_id):
    return children_by(DB.interface_messages, "interface_channel_id", channel_id)


def facility_orders(facility_id):
    return children_by(DB.patient_orders, "facility_id", facility_id)


def facility_tasks(facility_id):
    return children_by(DB.cutover_tasks, "facility_id", facility_id)


def program_cutover_tasks(program_id):
    return children_by(DB.cutover_tasks, "ehr_implementation_id", program_id)


def program_defects(program_id):
    return children_by(DB.test_defects, "ehr_implementation_id", program_id)


def program_build_items(program_id):
    return children_by(DB.system_build_items, "ehr_implementation_id", program_id)


def department_optimization_items(department_id):
    return children_by(DB.optimization_backlog_items, "department_id", department_id)


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------
def ts(value):
    return fmt_iso(value) if value is not None else None


def serialize(entity, row):
    return {
        key: serialize_value(value)
        for key, value in row.items()
        if not key.startswith("_") and not key.startswith("opened_utc")
    }


def serialize_value(value):
    from decimal import Decimal

    if value is None:
        return None
    if hasattr(value, "tzinfo") and hasattr(value, "isoformat"):
        return fmt_iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    return value


def stamp_created(row, extra=None):
    now = now_iso()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    if extra:
        row.update(extra)
    return row
