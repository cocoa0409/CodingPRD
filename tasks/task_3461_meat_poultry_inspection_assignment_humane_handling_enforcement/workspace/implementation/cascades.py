"""Cascading side effects (PRD §2.11, §3.3, §3.4, §3.5).

One decision on a parent propagates to every dependent resource in the same
request; each resource a cascade touches gets its own updated_at refresh and
version increment (PRD §2.6/§2.11).
"""
import store
from store import insert, stamp_new, touch


# --- label hold helpers -------------------------------------------------------

def _hold_labels(establishment_id, from_statuses):
    for label in store.all_of("label_applications"):
        if (
            label["establishment_id"] == establishment_id
            and label["status"] in from_statuses
        ):
            label["_status_before_hold"] = label["status"]
            label["status"] = "HELD"
            touch(label)


def _block_windows(establishment_id):
    for window in store.all_of("shift_windows"):
        if window["establishment_id"] == establishment_id and window["status"] in (
            "PLANNED",
            "COVERAGE_GAP_FLAGGED",
        ):
            window["status"] = "BLOCKED"
            touch(window)


# --- establishment-level cascades (PRD §3.4) ----------------------------------

def cascade_suspension(establishment):
    """inspection_status -> SUSPENDED; suspension_count (derived) grows because
    the activating action is IN_EFFECT; PLANNED/COVERAGE_GAP_FLAGGED windows
    -> BLOCKED; UNDER_REVIEW label applications -> HELD; establishment
    version +1."""
    establishment["inspection_status"] = "SUSPENDED"
    _block_windows(establishment["id"])
    _hold_labels(establishment["id"], ("UNDER_REVIEW",))
    touch(establishment)


def cascade_withdrawal(establishment):
    """grant_status -> WITHDRAWN; inspection_status -> INACTIVE; windows
    -> BLOCKED; SUBMITTED/UNDER_REVIEW/HELD label applications -> REJECTED
    (reason: withdrawal); establishment version +1. Terminal for both
    dimensions (PRD §2.5)."""
    establishment["grant_status"] = "WITHDRAWN"
    establishment["inspection_status"] = "INACTIVE"
    _block_windows(establishment["id"])
    for label in store.all_of("label_applications"):
        if label["establishment_id"] == establishment["id"] and label["status"] in (
            "SUBMITTED",
            "UNDER_REVIEW",
            "HELD",
        ):
            label["status"] = "REJECTED"  # rejection reason: withdrawal
            touch(label)
    touch(establishment)


def cascade_withhold(establishment):
    """WITHHOLD_MARKS activation: SUBMITTED/UNDER_REVIEW label applications
    -> HELD. No establishment mutation."""
    _hold_labels(establishment["id"], ("SUBMITTED", "UNDER_REVIEW"))


def apply_activation(action, establishment):
    """Side effects of an EnforcementAction entering IN_EFFECT (PRD §3.4)."""
    action_type = action["action_type"]
    if action_type == "SUSPENSION":
        cascade_suspension(establishment)
    elif action_type == "WITHHOLD_MARKS":
        cascade_withhold(establishment)
    elif action_type == "WITHDRAWAL":
        cascade_withdrawal(establishment)
    # NOTICE_OF_INTENDED_ENFORCEMENT: no direct state change on other entities


def apply_lift(action, establishment):
    """Side effects of an EnforcementAction moving IN_EFFECT -> LIFTED (PRD §3.4).

    SUSPENSION: inspection_status SUSPENDED -> ACTIVE; every HELD label
    application -> UNDER_REVIEW; blocked windows stay BLOCKED. WITHHOLD_MARKS:
    every HELD label application returns to its pre-hold status. NOTICE and
    WITHDRAWAL lifts touch no other entity.
    """
    if action["action_type"] == "SUSPENSION":
        if establishment["inspection_status"] == "SUSPENDED":
            establishment["inspection_status"] = "ACTIVE"
            for label in store.all_of("label_applications"):
                if (
                    label["establishment_id"] == establishment["id"]
                    and label["status"] == "HELD"
                ):
                    label["status"] = "UNDER_REVIEW"
                    touch(label)
            touch(establishment)
    elif action["action_type"] == "WITHHOLD_MARKS":
        for label in store.all_of("label_applications"):
            if (
                label["establishment_id"] == establishment["id"]
                and label["status"] == "HELD"
            ):
                label["status"] = label.get("_status_before_hold") or "UNDER_REVIEW"
                touch(label)


# --- auto-created enforcement actions (PRD §3.3, §3.5, §3.6) -------------------

def auto_enforcement_action(establishment_id, action_type, basis, regulation_family, status):
    action = {
        "establishment_id": establishment_id,
        "action_type": action_type,
        "basis": basis,
        "regulation_family": regulation_family,
        "status": status,
        "auto_created": True,
        "effective_at": store.clock_now() if status == "IN_EFFECT" else None,
        "abatement_evidence": None,
    }
    stamp_new(action)
    return insert("enforcement_actions", action)


def maybe_auto_suspend_for_escalation(nr):
    """NR escalation ladder (PRD §3.3): when a record enters ESCALATED and the
    family's qualifying-NR count reaches NR_ESCALATION_THRESHOLD (>=3, exactly
    at threshold fires), auto-create a PROPOSED SUSPENSION / NR_LINKAGE
    action. Evaluated at the moment of the transition, with the just-escalated
    record counted in its ESCALATED state."""
    from calc import qualifying_nr_count, NR_ESCALATION_THRESHOLD

    count = qualifying_nr_count(nr["establishment_id"], nr["regulation_family"])
    if count >= NR_ESCALATION_THRESHOLD:
        auto_enforcement_action(
            nr["establishment_id"], "SUSPENSION", "NR_LINKAGE", nr["regulation_family"], "PROPOSED"
        )


def egregious_humane_cascade(establishment):
    """Confirmed EGREGIOUS event (PRD §3.5): auto-create an IN_EFFECT SUSPENSION
    with basis EGREGIOUS_HUMANE; its activation cascade fires immediately."""
    action = auto_enforcement_action(
        establishment["id"], "SUSPENSION", "EGREGIOUS_HUMANE", None, "IN_EFFECT"
    )
    cascade_suspension(establishment)
    return action


def cat3_transition_cascade(establishment):
    """A pathogen's recomputed category transitioned to CAT_3 from a different
    value (PRD §3.6): auto-create an IN_EFFECT NOTICE_OF_INTENDED_ENFORCEMENT
    with basis CATEGORY_3_PATHOGEN."""
    return auto_enforcement_action(
        establishment["id"],
        "NOTICE_OF_INTENDED_ENFORCEMENT",
        "CATEGORY_3_PATHOGEN",
        None,
        "IN_EFFECT",
    )


def cascade_inspector_deactivation(inspector):
    """Deactivation cancels every SCHEDULED assignment of the inspector."""
    for assignment in store.all_of("shift_assignments"):
        if assignment["inspector_id"] == inspector["id"] and assignment["status"] == "SCHEDULED":
            assignment["status"] = "CANCELLED"
            touch(assignment)
