"""The multi-row cascades of PRD 3.1, 3.8 and 3.9.

Every row a cascade touches has updated_at refreshed and version incremented,
and every collection a cascade walks is walked in created_at ascending order.
"""
import calc
import store
import util

UPLIST_ACTION_STATES = ("CONSULTATION_CONCLUDED", "HCP_DEVELOPMENT", "PERMITTED")


def plan_of_action(action):
    plans = store.where("plans", project_action_id=action["id"])
    return plans[0] if plans else None


def permit_of_plan(plan):
    permits = store.where("permits", hcp_id=plan["id"])
    return permits[0] if permits else None


# ------------------------------------------------- species uplisting --------


def uplisting_cascade(species):
    """Four hops.  A biological opinion already on file is deliberately left
    alone -- uplisting does not rewrite a signed document."""
    touched_proponents = {}

    # Hop 1: reevaluation flags on the species' live determinations.
    affected_rows = [
        row
        for row in store.ordered(store.values("determinations"))
        if row["species_id"] == species["id"]
        and row["presence_status"] in calc.CANDIDATE_STATUSES
    ]
    action_ids = []
    for row in affected_rows:
        row["requires_reevaluation"] = True
        store.touch(row)
        if row["project_action_id"] not in action_ids:
            action_ids.append(row["project_action_id"])

    # Hop 2: the actions those determinations reach, in created_at order.
    actions = [
        row
        for row in store.ordered(store.values("actions"))
        if row["id"] in action_ids and row["status"] in UPLIST_ACTION_STATES
    ]
    for action in actions:
        action["status"] = "REINITIATION_PENDING"
        action["reinitiation_reason"] = "SPECIES_UPLISTED"
        store.touch(action)

        # Hop 3: the active consultation, and only out of OPINION_ISSUED.
        consultation = store.get("consultations", action.get("active_consultation_id"))
        if consultation is not None and consultation["status"] == "OPINION_ISSUED":
            consultation["status"] = "REINITIATION_REQUIRED"
            consultation["reinitiation_triggered_at"] = store.now()
            consultation["reinitiation_count"] = consultation["reinitiation_count"] + 1
            store.touch(consultation)

        # Hop 4: the plan's assurance review flag, and the proponent's counters.
        plan = plan_of_action(action)
        if plan is not None:
            plan["assurance_review_required"] = True
            store.touch(plan)

        proponent = calc.proponent_of_action(action)
        if proponent is not None:
            touched_proponents[proponent["id"]] = proponent

    for proponent in touched_proponents.values():
        calc.refresh_compliance(proponent)


# ------------------------------------------------- take exceedance ----------


def take_exceedance_cascade(permit):
    """Hops two through five; hop one is the report row the caller just wrote."""
    permit["status"] = "SUSPENDED"
    permit["suspension_count"] = permit["suspension_count"] + 1
    store.touch(permit)

    plan = store.get("plans", permit["hcp_id"])
    if plan is not None and plan["plan_status"] == "IMPLEMENTING":
        plan["plan_status"] = "SUSPENDED_IMPLEMENTATION"
        plan["assurance_review_required"] = True
        store.touch(plan)

    action = store.get("actions", plan["project_action_id"]) if plan else None
    if action is not None and action["status"] == "PERMITTED":
        action["status"] = "REINITIATION_PENDING"
        action["reinitiation_reason"] = "TAKE_EXCEEDANCE"
        store.touch(action)

    if action is not None:
        consultation = store.get(
            "consultations", action.get("active_consultation_id")
        )
        if consultation is not None and consultation["status"] == "OPINION_ISSUED":
            consultation["status"] = "REINITIATION_REQUIRED"
            consultation["reinitiation_triggered_at"] = store.now()
            consultation["reinitiation_count"] = consultation["reinitiation_count"] + 1
            store.touch(consultation)
            calc.refresh_compliance(calc.proponent_of_action(action))


def unwind_suspension(permit):
    """The compensating path taken when a rejection brings consumed take
    strictly below the trigger while the permit is SUSPENDED."""
    permit["status"] = "ACTIVE"
    store.touch(permit)

    plan = store.get("plans", permit["hcp_id"])
    if plan is not None and plan["plan_status"] == "SUSPENDED_IMPLEMENTATION":
        plan["plan_status"] = "IMPLEMENTING"
        plan["assurance_review_required"] = False
        store.touch(plan)


# ------------------------------------------------- permit expiry ------------


def expire_permits():
    """Run after the logical clock is repositioned.  Three hops per permit, and
    the SECURED -> RELEASED hop carries no bank ledger change whatsoever."""
    clock = store.now()
    for permit in store.ordered(store.values("permits")):
        if permit["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if not util.at_midnight(permit["term_end"]) < clock:
            continue

        permit["status"] = "EXPIRED"
        store.touch(permit)

        plan = store.get("plans", permit["hcp_id"])
        if plan is None:
            continue
        if plan["plan_status"] in ("IMPLEMENTING", "SUSPENDED_IMPLEMENTATION"):
            plan["plan_status"] = "CLOSED"
            store.touch(plan)

        for commitment in calc.plan_commitments(plan, ("SECURED",)):
            commitment["status"] = "RELEASED"
            store.touch(commitment)
