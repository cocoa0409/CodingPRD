"""Household derivations and the household state branches."""

import util
from db import store, touch
from services import zones


def device_requirements(household):
    """PRD 3.3: requirements derived from the home's physical shape."""
    household["required_smoke_devices"] = (
        household["sleeping_areas_count"] + household["storeys"]
    )
    household["required_co_devices"] = (
        1 if (household["fuel_burning_appliance"] or household["attached_garage"]) else 0
    )
    household["required_strobe_devices"] = (
        1 if household["hearing_impaired_occupants"] > 0 else 0
    )


def zone_of(household):
    return store.zones.get(household["zone_id"])


def on_visit_completed(visit, household):
    """The APPOINTMENT_SCHEDULED -> VISIT_COMPLETED transition and the zone
    survey counters it drives (PRD 3.6)."""
    household["status"] = "VISIT_COMPLETED"
    household["last_visit_completed_at"] = util.clock.now()
    touch(household)

    zone = zone_of(household)
    if zone is not None:
        zone["surveyed_units"] = zone["surveyed_units"] + 1
        if visit["pre_existing_working_smoke_alarms"] == 0:
            zone["surveyed_units_without_alarm"] = (
                zone["surveyed_units_without_alarm"] + 1
            )
        zone["served_household_count"] = zone["served_household_count"] + 1
        if zone["service_start_date"] is None:
            if zone["assessment_status"] == "TARGETED":
                zone["assessment_status"] = "SERVICE_ACTIVE"
            zone["service_start_date"] = util.clock.today()
        touch(zone)
        zones.reevaluate_service_state(zone)


def apply_cancel_branch(household, cancel_reason):
    """PRD 3.5: the four household branches a cancellation selects."""
    if cancel_reason in ("RESCHEDULE_REQUESTED", "ROUTE_CLOSED"):
        new_status = "INTAKE_QUEUED"
    elif cancel_reason == "OCCUPANT_REFUSED":
        new_status = "REFUSED"
    else:
        new_status = (
            "NO_CONTACT" if household["canvass_attempt_count"] >= 3 else "INTAKE_QUEUED"
        )
    household["status"] = new_status
    touch(household)
    if new_status in ("REFUSED", "NO_CONTACT"):
        zones.reevaluate_service_state(zone_of(household))


def follow_ups_of(household_id):
    rows = [f for f in store.follow_ups.values() if f["household_id"] == household_id]
    return sorted(rows, key=lambda r: r["attempt_no"])


def live_plan_of(household_id):
    """The household's own non-superseded plan (PRD 3.7)."""
    candidates = [
        p
        for p in store.escape_plans.values()
        if p["household_id"] == household_id and p["status"] != "SUPERSEDED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return candidates[-1]


def retention_figures(households):
    """PRD 3.7 retention selection rule.  Returns (eligible_count, rate)."""
    eligible = 0
    present = 0
    for household in households:
        if household["status"] not in ("VISIT_COMPLETED", "REVISIT_REQUIRED"):
            continue
        rows = [
            f
            for f in follow_ups_of(household["id"])
            if f["outcome"] in ("REACHED_ALARM_PRESENT", "REACHED_ALARM_MISSING")
        ]
        if not rows:
            continue
        selected = max(rows, key=lambda r: r["attempt_no"])
        eligible += 1
        if selected["outcome"] == "REACHED_ALARM_PRESENT":
            present += 1
    if eligible == 0:
        return 0, None
    rate = util.round_half_up(
        util.to_decimal(100 * present) / util.to_decimal(eligible), 2
    )
    return eligible, rate
