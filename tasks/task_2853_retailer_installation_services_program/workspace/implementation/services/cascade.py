"""The four named cascades of PRD section 2.9, plus the scorecard-event ledger."""
import store
from services import calc


# --- immutable scorecard ledger ----------------------------------------------
def append_event(installer, event_type, occurred_at, source, project_id=None, csat_score=None):
    quality, timeliness, satisfaction = calc.event_deltas(event_type, csat_score)
    row = {
        "installer_id": installer["id"],
        "project_id": project_id,
        "event_type": event_type,
        "csat_score": csat_score,
        "quality_delta": quality,
        "timeliness_delta": timeliness,
        "satisfaction_delta": satisfaction,
        "occurred_at": occurred_at,
        "source": source,
    }
    store.insert("scorecard_events", row, common_fields=False)
    return row


def rescore_and_touch(installer):
    """Recompute both variants, apply the ACTIVE <-> PROBATION loop, bump version."""
    calc.rescore(installer)
    calc.probation_transition(installer)
    store.touch(installer)
    return installer


def project_completed_installer_id(project_id):
    """The installer_id of this project's COMPLETED assignment, if any."""
    for assignment in store.all_rows("installer_assignments"):
        if assignment["project_id"] == project_id and assignment["status"] == "COMPLETED":
            return assignment["installer_id"]
    return None


# --- shared release primitive -------------------------------------------------
def release_assignments(assignments, reason, revert_projects=True, touch_projects=True,
                        skip_touch_installer_id=None):
    """Release each assignment, decrement its installer, revert its project.

    `skip_touch_installer_id` names an installer whose `version` the *caller* owns.
    PRD 2.9 says every affected row's "`version` [is] incremented by one" per request,
    and PRD 3.9 says a removal "increments the firm's `version`" — once. So when the
    firm driving the cascade is also the owner of the released windows, its single
    increment is applied by the caller, not a second time here.
    """
    touched_installers = {}
    touched_projects = {}
    for assignment in assignments:
        assignment["status"] = "RELEASED"
        assignment["release_reason"] = reason
        store.touch(assignment)

        installer = store.get("installers", assignment["installer_id"])
        if installer is not None:
            calc.recompute_committed_minutes(installer)
            touched_installers[installer["id"]] = installer

        project = store.get("projects", assignment["project_id"])
        if project is not None and revert_projects and project["fulfillment_status"] == "SCHEDULED":
            project["fulfillment_status"] = "MEASURED"
            touched_projects[project["id"]] = project

    for installer in touched_installers.values():
        if installer["id"] == skip_touch_installer_id:
            continue
        store.touch(installer)
    if touch_projects:
        for project in touched_projects.values():
            store.touch(project)
    return list(touched_projects.values())


# --- SCOPE_CHANGE_PENDING -----------------------------------------------------
def scope_change_pending(project):
    """A reopened scope releases the project's own held work."""
    live = [
        a for a in store.all_rows("installer_assignments")
        if a["project_id"] == project["id"] and a["status"] in ("HELD", "CONFIRMED")
    ]
    release_assignments(live, "SCOPE_CHANGE_PENDING", revert_projects=False)


# --- INSTALLER_SUSPENDED ------------------------------------------------------
def suspend_if_unlicensed(installer):
    """Hops 2-4: a firm with no verified licence left loses its held work."""
    if installer["verified_credential_count"] > 0:
        return False
    if installer["status"] not in ("ACTIVE", "PROBATION"):
        return False
    installer["status"] = "SUSPENDED"
    live = [
        a for a in calc.installer_assignments(installer["id"])
        if a["status"] in ("HELD", "CONFIRMED")
    ]
    release_assignments(live, "INSTALLER_SUSPENDED",
                        skip_touch_installer_id=installer["id"])
    calc.recompute_committed_minutes(installer)
    return True


# --- INSTALLER_REMOVED --------------------------------------------------------
def remove_installer(installer, removal_reason):
    installer["status"] = "REMOVED"
    installer["removed_at"] = store.now()
    installer["removal_reason"] = removal_reason
    live = [
        a for a in calc.installer_assignments(installer["id"])
        if a["status"] in ("HELD", "CONFIRMED")
    ]
    release_assignments(live, "INSTALLER_REMOVED",
                        skip_touch_installer_id=installer["id"])
    calc.recompute_committed_minutes(installer)
    return installer


# --- PROJECT_CANCELLED --------------------------------------------------------
def cancel_project(project, cancel_reason, actor_role):
    """Settlement from the PRE-cancellation state, then the wide child sweep."""
    pre_fulfillment = project["fulfillment_status"]
    delivery = calc.project_delivery(project["id"])
    pre_delivery_status = delivery["status"] if delivery is not None else None
    customer = store.get("customers", project["customer_id"])

    result = calc.settlement(
        project, pre_fulfillment, delivery, pre_delivery_status, actor_role, customer)

    project["fulfillment_status"] = "CANCELLED"
    project["cancelled_at"] = store.now()
    project["cancel_reason"] = cancel_reason

    project["deposit_forfeited_cents"] = (int(project["deposit_forfeited_cents"])
                                         + result["retained_cents"])
    project["deposit_refunded_cents"] = (int(project["deposit_refunded_cents"])
                                        + result["refund_cents"])
    project["deposit_held_cents"] = 0
    project["financial_status"] = result["resulting_financial_status"]
    calc.recompute_money(project)

    for measurement in store.all_rows("measurements"):
        if measurement["project_id"] == project["id"] and measurement["status"] == "SCHEDULED":
            measurement["status"] = "VOIDED"
            measurement["voided_reason"] = "PROJECT_CANCELLED"
            store.touch(measurement)

    for order in store.all_rows("change_orders"):
        if (order["project_id"] == project["id"]
                and order["status"] in ("DRAFT", "PENDING_CUSTOMER", "REVISION_REQUESTED")):
            order["status"] = "SUPERSEDED"
            store.touch(order)

    live = [
        a for a in store.all_rows("installer_assignments")
        if a["project_id"] == project["id"]
        and a["status"] in ("HELD", "CONFIRMED", "IN_PROGRESS")
    ]
    release_assignments(live, "PROJECT_CANCELLED", revert_projects=False)

    for row in store.all_rows("material_deliveries"):
        if row["project_id"] == project["id"] and row["status"] != "RETURNED":
            row["status"] = "RETURNED"
            store.touch(row)

    return result
