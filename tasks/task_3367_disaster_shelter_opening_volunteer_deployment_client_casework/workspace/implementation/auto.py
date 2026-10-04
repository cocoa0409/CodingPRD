"""Clock-driven automatic transitions, evaluated to a fixed point.

They are not background jobs: every read and every write re-evaluates them, so
a single request may carry a resource through several automatic transitions
before the request itself is handled (PRD 2.10).
"""

from datetime import timedelta

import calc
import core
from core import clock, find, parse_instant, rows, touch


def sweep():
    for _ in range(12):
        changed = False
        changed |= _volunteer_credentials()
        changed |= _site_agreements()
        changed |= _deployments()
        changed |= _shifts()
        changed |= _blood_drives()
        changed |= _client_cases()
        if not changed:
            break


def _volunteer_credentials():
    changed = False
    for volunteer in rows("volunteers"):
        if volunteer["credential_status"] != "ACTIVE":
            continue
        expires = volunteer.get("credential_expires_at")
        if not expires or clock.now < parse_instant(expires):
            continue
        volunteer["credential_status"] = "EXPIRED"
        volunteer["deployment_availability"] = "UNAVAILABLE"
        touch(volunteer)
        region = find("regions", volunteer["home_region_id"])
        if region is not None:
            calc.refresh_region(region)
        changed = True
    return changed


def _site_agreements():
    changed = False
    for site in rows("shelter_sites"):
        if site["agreement_status"] not in ("APPROVED", "SUSPENDED"):
            continue
        expires = site.get("agreement_expires_at")
        if not expires or clock.now < parse_instant(expires):
            continue
        site["agreement_status"] = "EXPIRED"
        touch(site)
        changed = True
    return changed


def _shelter_staffing_changed(deployment):
    shelter_id = deployment.get("shelter_operation_id")
    if not shelter_id:
        return
    shelter = find("shelter_operations", shelter_id)
    if shelter is not None:
        calc.refresh_shelter_and_posture(shelter)


def _deployments():
    changed = False
    for deployment in rows("volunteer_deployments"):
        status = deployment["status"]
        if status == "APPROVED":
            lead = calc.lead_days(deployment["travel_mode"])
            threshold = parse_instant(deployment["rotation_start_at"]) - timedelta(days=lead)
            if clock.now >= threshold:
                deployment["status"] = "IN_TRANSIT"
                touch(deployment)
                changed = True
        if deployment["status"] == "IN_TRANSIT":
            if clock.now >= parse_instant(deployment["rotation_start_at"]):
                deployment["status"] = "ARRIVED"
                touch(deployment)
                _shelter_staffing_changed(deployment)
                changed = True
        if deployment["status"] == "ARRIVED":
            checked_in = any(
                shift["volunteer_deployment_id"] == deployment["id"]
                and shift["status"] == "CHECKED_IN"
                for shift in rows("shift_assignments"))
            if checked_in:
                deployment["status"] = "ON_SHIFT"
                touch(deployment)
                _shelter_staffing_changed(deployment)
                changed = True
    return changed


def _shifts():
    changed = False
    for shift in rows("shift_assignments"):
        status = shift["status"]
        if status == "SCHEDULED":
            deployment = find("volunteer_deployments", shift["volunteer_deployment_id"])
            if deployment is not None and deployment["status"] == "RECALLED":
                shift["status"] = "CANCELLED"
                touch(shift)
                changed = True
                continue
            grace = parse_instant(shift["shift_start_at"]) + timedelta(minutes=calc.NO_SHOW_GRACE_MINUTES)
            if clock.now >= grace:
                shift["status"] = "NO_SHOW"
                touch(shift)
                changed = True
        elif status == "CHECKED_IN":
            if clock.now >= parse_instant(shift["shift_end_at"]):
                shift["status"] = "COMPLETED"
                touch(shift)
                changed = True
    return changed


def _blood_drives():
    changed = False
    for drive in rows("blood_drives"):
        if drive["status"] == "PLANNED" and clock.now >= parse_instant(drive["scheduled_start_at"]):
            drive["status"] = "ACTIVE"
            touch(drive)
            changed = True
        if drive["status"] == "ACTIVE" and clock.now >= parse_instant(drive["scheduled_end_at"]):
            drive["status"] = "COMPLETED"
            touch(drive)
            region = find("regions", drive["region_id"])
            if region is not None:
                calc.refresh_region(region)
            changed = True
    return changed


def _client_cases():
    changed = False
    for case in rows("client_cases"):
        if case["status"] == "REFERRED":
            following = calc.case_status_after_referrals(case)
            if following != case["status"]:
                core.apply(case, {
                    "status": following,
                    "case_closure_eligible_at": calc.case_closure_eligible_at(case),
                })
                changed = True
        if case["status"] == "MONITORING":
            eligible = case.get("case_closure_eligible_at")
            if eligible and clock.now >= parse_instant(eligible):
                case["status"] = "CLOSED"
                touch(case)
                changed = True
    return changed
