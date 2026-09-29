"""Transitive cascades.  Programs fan out in created_at ASC order and their
placements in created_at ASC order within each program (PRD 2.11)."""

import calc
import db


def cancel_pending_placements(program):
    for placement in calc.placements_of_program(program["id"]):
        if placement["funding_status"] == "PENDING":
            placement["funding_status"] = "CANCELLED"
            db.bump(placement)


def programs_for_agreement(agreement_id):
    return db.by_created([p for p in db.programs.values()
                          if p.get("agreement_id") == agreement_id])


def suspend_programs_for_agreement(agreement):
    """Hop 3 of the agreement suspension cascade."""
    touched = set()
    for program in programs_for_agreement(agreement["id"]):
        if program["state"] not in ("CLASSIFIED", "OPEN_FOR_PLACEMENT"):
            continue
        program["state"] = "SUSPENDED"
        db.touch(program)
        cancel_pending_placements(program)
        touched.add(program["institution_id"])
    for institution_id in sorted(touched):
        calc.recompute_institution(db.institutions.get(institution_id))


def close_programs_for_agreement(agreement):
    """The agreement termination cascade."""
    touched = set()
    for program in programs_for_agreement(agreement["id"]):
        if program["state"] == "CLOSED":
            continue
        program["state"] = "CLOSED"
        db.touch(program)
        cancel_pending_placements(program)
        touched.add(program["institution_id"])
    for institution_id in sorted(touched):
        calc.recompute_institution(db.institutions.get(institution_id))


def activate_approved_plans(institution):
    """Hop 4 of the exception revocation cascade: a bank that has just gone
    FROZEN activates every APPROVED contingency plan at its selected stage."""
    plans = [p for p in db.contingency_plans.values()
             if p["institution_id"] == institution["id"] and p["status"] == "APPROVED"]
    plans.sort(key=lambda p: (p["effective_from"], p["created_at"], p["_seq"]))
    for plan in plans:
        plan["status"] = "ACTIVATED"
        calc.activate_plan_figures(plan, institution)
        db.bump(plan)


def revoke_exception(exception):
    """The four-hop exception revocation cascade."""
    exception["status"] = "REVOKED"
    exception["reporting_due_date"] = None

    affected = []
    for program in db.by_created(list(db.programs.values())):
        determination_id = program.get("governing_classification_id")
        if not determination_id:
            continue
        determination = db.classifications.get(determination_id)
        if determination is None:
            continue
        if determination.get("relied_exception_id") != exception["id"]:
            continue
        if program["state"] not in ("CLASSIFIED", "OPEN_FOR_PLACEMENT"):
            continue
        affected.append(program)

    touched = set()
    for program in affected:
        program["state"] = "RECLASSIFICATION_PENDING"
        program["attested_by_user_id"] = None
        db.touch(program)
        touched.add(program["institution_id"])
    exception["reliant_program_count"] = 0

    for program in affected:
        for placement in calc.placements_of_program(program["id"]):
            if placement["funding_status"] != "ACTIVE":
                continue
            placement["compliance_status"] = "FLAGGED"
            placement["classified_as"] = "BROKERED"
            db.bump(placement)

    for institution_id in sorted(touched):
        institution = db.institutions.get(institution_id)
        calc.recompute_institution(institution)
        if institution is not None and institution["concentration_posture"] == "FROZEN":
            activate_approved_plans(institution)
