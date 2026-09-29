"""Entity serializers.  Computed fields are refreshed at projection time."""

import derive
import store


def checkpoint(row):
    derive.refresh_checkpoint(row)
    return store.project(row)


def lane(row):
    row["equipment_state"] = derive.lane_equipment_state(row)
    return store.project(row)


def equipment_unit(row):
    return store.project(row)


def officer(row):
    derive.refresh_officer(row)
    return store.project(row)


def show_up_curve(row):
    return store.project(row)


def flight_schedule_entry(row):
    return store.project(row)


def time_band(row):
    return store.project(row)


def staffing_plan(row):
    return store.project(row)


def lane_assignment(row):
    derive.evaluate_break_due(row)
    return store.project(row, {"actual_minutes": derive.actual_minutes(row)})


def wait_time_observation(row):
    return store.project(row)


def escalation_ticket(row):
    return store.project(row)


def screening_referral(row):
    row["secondary_slot_held"] = row["state"] in ("RAISED", "IN_PROGRESS")
    return store.project(row)


def surge_detail(row):
    return store.project(row)


def many(fn, rows):
    return [fn(row) for row in rows]
