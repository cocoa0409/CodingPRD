"""Multi-hop cascades that more than one endpoint can trigger."""

import derive
from store import db, new_row, now, touch


def retained_back_to_assigned(program):
    """Hop 3 of PRD 3.10 and part of the rescission unwind of PRD 3.8."""
    for appointment in derive.appointments_of(program["id"]):
        if appointment["state"] == "TEACH_OUT_RETAINED":
            appointment["state"] = "ASSIGNED"
            touch(appointment)


def maybe_complete_plan(plan):
    """The three-hop teach-out completion cascade of PRD 3.10.

    Hop 1: an IN_EFFECT plan with no open students completes.
    Hop 2: because the plan completed, the program discontinues and its
           catalog axis withdraws.
    Hop 3: because the program discontinued, retained appointments go back
           into the assigned pool and the waterfall re-derives.
    """
    if plan["state"] != "IN_EFFECT":
        return False
    if derive.plan_ledger(plan)["open_student_count"] != 0:
        return False

    plan["state"] = "COMPLETED"
    plan["completed_at"] = now()
    touch(plan)

    program = db.programs.get(plan["program_id"])
    if program is None:
        return True
    if program["lifecycle_state"] == "TEACH_OUT_ACTIVE":
        program["lifecycle_state"] = "DISCONTINUED"
        if program["catalog_status"] == "ADMISSIONS_CLOSED":
            program["catalog_status"] = "CATALOG_WITHDRAWN"
        touch(program)
        retained_back_to_assigned(program)
    return True


def mint_auto_notifications(decision):
    """Hop 3 of the ratification cascade (PRD 3.6): two AUTO_MINTED notices."""
    minted = []
    for agency_type, agency_code in (("ACCREDITOR", "REGIONAL-ACC"),
                                     ("STATE_AGENCY", "STATE-CHE")):
        row = new_row()
        row.update({
            "decision_id": decision["id"],
            "agency_type": agency_type,
            "agency_code": agency_code,
            "status": "PENDING",
            "due_at": derive.notice_due_at(decision, agency_type),
            "sent_at": None,
            "acknowledged_at": None,
            "transmitted_reference": None,
            "origin": "AUTO_MINTED",
            "overdue_marked_at": None,
        })
        db.notifications[row["id"]] = row
        minted.append(row)
    return minted
