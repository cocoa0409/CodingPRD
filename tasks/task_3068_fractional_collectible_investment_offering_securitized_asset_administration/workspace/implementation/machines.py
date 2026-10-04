"""Declared state machines and their legal transitions (§1.2)."""
from envelope import invalid_state

MACHINES = {
    "Artwork": {
        "initial": "APPRAISED",
        "terminal": ["SOLD"],
        "edges": [
            ("APPRAISED", "AUTHENTICATED"),
            ("AUTHENTICATED", "OFFERING_PENDING"),
            ("AUTHENTICATED", "HELD"),
            ("OFFERING_PENDING", "AUTHENTICATED"),
            ("OFFERING_PENDING", "UNDER_OFFERING"),
            ("UNDER_OFFERING", "HELD"),
            ("HELD", "SALE_PENDING"),
            ("SALE_PENDING", "HELD"),
            ("SALE_PENDING", "SOLD"),
        ],
        # Deliberately absent: HELD -> OFFERING_PENDING (the join node is not a
        # springboard back to the fork's upper branch).
        "absent": [("HELD", "OFFERING_PENDING")],
    },
    "Offering": {
        "initial": "DRAFT",
        "terminal": ["CLOSED", "WITHDRAWN", "OFFERING_ABANDONED"],
        "edges": [
            ("DRAFT", "QUALIFICATION_FILED"),
            ("QUALIFICATION_FILED", "ALLOCATED"),
            ("QUALIFICATION_FILED", "WITHDRAWN"),
            ("ALLOCATED", "HELD"),
            ("HELD", "ALLOCATED"),
            ("ALLOCATED", "SALE_PENDING"),
            ("SALE_PENDING", "ALLOCATED"),
            ("SALE_PENDING", "CLOSED"),
            ("ALLOCATED", "WITHDRAWN"),
            ("DRAFT", "OFFERING_ABANDONED"),
            ("QUALIFICATION_FILED", "OFFERING_ABANDONED"),
        ],
        "absent": [],
    },
    "Subscription": {
        "initial": "RECEIVED",
        "terminal": ["REJECTED", "EXPIRED", "WITHDRAWN"],
        "edges": [
            ("RECEIVED", "SUBSCRIBED"),
            ("RECEIVED", "SUITABILITY_SCREENED"),
            ("RECEIVED", "REJECTED"),
            ("SUBSCRIBED", "REALLOCATED"),
            ("SUBSCRIBED", "WAITLISTED"),
            ("WAITLISTED", "REALLOCATED"),
            ("REALLOCATED", "WAITLISTED"),
            ("SUBSCRIBED", "WITHDRAWN"),
            ("SUBSCRIBED", "EXPIRED"),
            ("WAITLISTED", "EXPIRED"),
            ("RECEIVED", "EXPIRED"),
        ],
        "absent": [],
    },
    "CustodyRecord": {
        "initial": "PENDING",
        "terminal": [],
        "edges": [("PENDING", "IN_CUSTODY"), ("IN_CUSTODY", "RELEASED"),
                  ("RELEASED", "IN_CUSTODY")],
        "absent": [],
    },
    "HoldingDecision": {
        "initial": "PENDING",
        "terminal": ["EXECUTED", "FAILED", "REJECTED"],
        "edges": [
            ("PENDING", "APPROVED"),
            ("APPROVED", "REJECTED"),
            ("PENDING", "REJECTED"),
            ("REJECTED", "PENDING"),
            ("APPROVED", "EXECUTED"),
            ("APPROVED", "FAILED"),
        ],
        "absent": [],
    },
    "TransferOrder": {
        "initial": "OPEN",
        "terminal": ["EXECUTED", "CANCELLED"],
        "edges": [
            ("OPEN", "MATCHED"),
            ("MATCHED", "OPEN"),
            ("MATCHED", "EXECUTED"),
            ("OPEN", "EXECUTED"),
            ("OPEN", "LAPSED"),
            ("LAPSED", "OPEN"),
            ("OPEN", "CANCELLED"),
            ("MATCHED", "CANCELLED"),
        ],
        "absent": [],
    },
    "InsurancePolicy": {
        "initial": "PENDING",
        "terminal": ["LAPSED"],
        "edges": [("PENDING", "FORCE"), ("FORCE", "LAPSED")],
        "absent": [],
    },
    "Investor": {
        "initial": "PENDING",
        "terminal": [],
        "edges": [
            ("PENDING", "APPROVED"),
            ("APPROVED", "EXPIRED"),
            ("EXPIRED", "APPROVED"),
            ("APPROVED", "REVOKED"),
        ],
        "absent": [],
    },
    "Appraisal": {
        "initial": "FILED",
        "terminal": [],
        "edges": [("FILED", "FILED")],
        "absent": [],
    },
}


def can(machine, frm, to):
    spec = MACHINES[machine]
    if (frm, to) in spec["absent"]:
        return False
    return (frm, to) in spec["edges"]


def require(machine, frm, to, message=None):
    if not can(machine, frm, to):
        raise invalid_state(message or
                            "%s cannot move from %s to %s." % (machine, frm, to))
    return True


def require_in(machine, state, allowed, message=None):
    if state not in allowed:
        raise invalid_state(message or
                            "%s is not in a state from which this operation is "
                            "a declared transition (status=%s)." % (machine, state))
    return True