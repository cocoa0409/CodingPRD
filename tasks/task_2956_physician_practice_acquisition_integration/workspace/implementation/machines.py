"""The eleven state machines (PRD sections 2.9, 3.1-3.11).

Each table maps a machine name to ``{from_state: {request_key: transition}}``
where ``request_key`` is the value the caller names (a target state, or an
``action`` for the two action-driven machines) and ``transition`` is
``(to_state, actors, cascade_only)``.  A ``to_state`` of None means the landing
state is resolved by the handler because the transition branches.
"""

from errors import ApiError

DEAL_LEAD = frozenset(["DealLead"])
COMPLIANCE = frozenset(["ComplianceOfficer"])
ANALYST = frozenset(["ValuationAnalyst"])
DESIGNER = frozenset(["CompensationDesigner"])
MANAGER = frozenset(["IntegrationManager"])
PHYSICIAN = frozenset(["PracticePhysician"])
MANAGER_OR_COMPLIANCE = frozenset(["IntegrationManager", "ComplianceOfficer"])

CASCADE = frozenset()

# --- Acquisition.deal_status -----------------------------------------------
DEAL_STATUS_VALUES = ("SOURCING", "DILIGENCE", "BOARD_REVIEW", "SIGNED",
                      "CLOSED", "ABANDONED")
DEAL_STATUS = {
    "SOURCING": {
        "DILIGENCE": ("DILIGENCE", DEAL_LEAD, False),
        "ABANDONED": ("ABANDONED", DEAL_LEAD, False),
    },
    "DILIGENCE": {
        "BOARD_REVIEW": ("BOARD_REVIEW", DEAL_LEAD, False),
        "ABANDONED": ("ABANDONED", DEAL_LEAD, False),
    },
    "BOARD_REVIEW": {
        "DILIGENCE": ("DILIGENCE", DEAL_LEAD, False),
        "SIGNED": ("SIGNED", DEAL_LEAD, False),
        "ABANDONED": ("ABANDONED", DEAL_LEAD, False),
    },
    "SIGNED": {
        "CLOSED": ("CLOSED", DEAL_LEAD, False),
    },
    "CLOSED": {},
    "ABANDONED": {},
}

# --- Acquisition.compliance_clearance --------------------------------------
CLEARANCE_VALUES = ("PENDING", "CLEARED", "FLAGGED", "SUSPENDED")
CLEARANCE = {
    "PENDING": {
        "CLEARED": ("CLEARED", COMPLIANCE, False),
        "FLAGGED": ("FLAGGED", COMPLIANCE, False),
    },
    "CLEARED": {
        "FLAGGED": ("FLAGGED", COMPLIANCE, False),
    },
    "FLAGGED": {
        "CLEARED": ("CLEARED", COMPLIANCE, False),
        "SUSPENDED": ("SUSPENDED", COMPLIANCE, False),
    },
    "SUSPENDED": {
        "FLAGGED": ("FLAGGED", COMPLIANCE, False),
    },
}

# --- ValuationOpinion.status ----------------------------------------------
OPINION_STATUS_VALUES = ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED",
                         "SUPERSEDED")
OPINION_STATUS = {
    "DRAFT": {
        "SUBMITTED": ("SUBMITTED", ANALYST, False),
        "SUPERSEDED": ("SUPERSEDED", CASCADE, True),
    },
    "SUBMITTED": {
        "DRAFT": ("DRAFT", COMPLIANCE, False),
        "ACCEPTED": ("ACCEPTED", COMPLIANCE, False),
        "REJECTED": ("REJECTED", COMPLIANCE, False),
        "SUPERSEDED": ("SUPERSEDED", CASCADE, True),
    },
    "ACCEPTED": {
        "SUPERSEDED": ("SUPERSEDED", COMPLIANCE, False),
    },
    "REJECTED": {},
    "SUPERSEDED": {},
}

# --- CompensationPlan.status ----------------------------------------------
PLAN_STATUS_VALUES = ("DRAFT", "SUBMITTED", "APPROVED", "EXECUTED",
                      "COMPLIANCE_HOLD", "SUPERSEDED", "WITHDRAWN")
PLAN_STATUS = {
    "DRAFT": {
        "SUBMITTED": ("SUBMITTED", DESIGNER, False),
        "WITHDRAWN": ("WITHDRAWN", DESIGNER, False),
    },
    "SUBMITTED": {
        # Branches to DRAFT or WITHDRAWN on the bounded revision allowance.
        "DRAFT": (None, COMPLIANCE, False),
        "APPROVED": ("APPROVED", COMPLIANCE, False),
    },
    "APPROVED": {
        "EXECUTED": ("EXECUTED", PHYSICIAN, False),
        "WITHDRAWN": ("WITHDRAWN", COMPLIANCE, False),
    },
    "EXECUTED": {
        "COMPLIANCE_HOLD": ("COMPLIANCE_HOLD", COMPLIANCE, False),
        "SUPERSEDED": ("SUPERSEDED", CASCADE, True),
    },
    "COMPLIANCE_HOLD": {
        "EXECUTED": ("EXECUTED", COMPLIANCE, False),
        "SUPERSEDED": ("SUPERSEDED", COMPLIANCE, False),
    },
    "SUPERSEDED": {},
    "WITHDRAWN": {},
}

# --- PayerContract.novation_status (action driven) -------------------------
NOVATION_VALUES = ("NOT_REQUESTED", "NOTICE_SENT", "CONSENT_RECEIVED",
                   "NEW_AGREEMENT_PENDING", "NOVATED", "DENIED", "TERMINATED")
NOVATION_ACTIONS = ("SEND_NOTICE", "RECORD_CONSENT", "DENY",
                    "START_NEW_AGREEMENT", "NOVATE", "TERMINATE")
NOVATION = {
    "NOT_REQUESTED": {
        "SEND_NOTICE": ("NOTICE_SENT", MANAGER, False),
    },
    "NOTICE_SENT": {
        "RECORD_CONSENT": ("CONSENT_RECEIVED", MANAGER, False),
        "DENY": ("DENIED", MANAGER, False),
    },
    "CONSENT_RECEIVED": {
        "NOVATE": ("NOVATED", MANAGER, False),
    },
    "NEW_AGREEMENT_PENDING": {
        "NOVATE": ("NOVATED", MANAGER, False),
        "TERMINATE": ("TERMINATED", MANAGER, False),
    },
    "DENIED": {
        "START_NEW_AGREEMENT": ("NEW_AGREEMENT_PENDING", MANAGER, False),
        "TERMINATE": ("TERMINATED", MANAGER, False),
    },
    "NOVATED": {},
    "TERMINATED": {},
}

# --- CredentialingPackage.status ------------------------------------------
PACKAGE_STATUS_VALUES = ("DRAFT", "SUBMITTED", "IN_REVIEW", "APPROVED",
                         "DENIED", "WITHDRAWN")
PACKAGE_STATUS = {
    "DRAFT": {
        "SUBMITTED": ("SUBMITTED", MANAGER, False),
        "WITHDRAWN": ("WITHDRAWN", MANAGER, False),
    },
    "SUBMITTED": {
        "IN_REVIEW": ("IN_REVIEW", MANAGER, False),
        "WITHDRAWN": ("WITHDRAWN", MANAGER, False),
    },
    "IN_REVIEW": {
        "APPROVED": ("APPROVED", MANAGER, False),
        "DENIED": ("DENIED", MANAGER, False),
        "WITHDRAWN": ("WITHDRAWN", MANAGER, False),
    },
    "APPROVED": {},
    "DENIED": {},
    "WITHDRAWN": {},
}

# --- EhrMigrationBatch.status (action driven) -----------------------------
BATCH_STATUS_VALUES = ("STAGED", "EXTRACTED", "LOADED", "RECONCILED",
                       "FAILED", "ABORTED")
BATCH_ACTIONS = ("EXTRACT", "LOAD", "RECONCILE", "REQUEUE", "ABORT")
BATCH_STATUS = {
    "STAGED": {
        "EXTRACT": ("EXTRACTED", MANAGER, False),
    },
    "EXTRACTED": {
        "LOAD": ("LOADED", MANAGER, False),
    },
    "LOADED": {
        # Branches to RECONCILED, FAILED or ABORTED on the match rate.
        "RECONCILE": (None, MANAGER, False),
    },
    "FAILED": {
        "REQUEUE": ("STAGED", MANAGER, False),
        "ABORT": ("ABORTED", MANAGER, False),
    },
    "RECONCILED": {},
    "ABORTED": {},
}

# --- StaffTransitionOffer.status ------------------------------------------
OFFER_STATUS_VALUES = ("DRAFT", "EXTENDED", "ACCEPTED", "DECLINED",
                       "RESCINDED", "EXPIRED")
OFFER_STATUS = {
    "DRAFT": {
        "EXTENDED": ("EXTENDED", MANAGER, False),
        "RESCINDED": ("RESCINDED", MANAGER, False),
    },
    "EXTENDED": {
        "ACCEPTED": ("ACCEPTED", MANAGER, False),
        "DECLINED": ("DECLINED", MANAGER, False),
        "RESCINDED": ("RESCINDED", MANAGER, False),
        "EXPIRED": ("EXPIRED", MANAGER, False),
    },
    "ACCEPTED": {},
    "DECLINED": {},
    "RESCINDED": {},
    "EXPIRED": {},
}

# --- BillingConversion.status ---------------------------------------------
CONVERSION_STATUS_VALUES = ("NOT_STARTED", "ATTESTED", "NOTICES_ISSUED",
                            "CONVERTED", "WITHDRAWN")
CONVERSION_STATUS = {
    "NOT_STARTED": {
        "ATTESTED": ("ATTESTED", MANAGER, False),
        "WITHDRAWN": ("WITHDRAWN", MANAGER, False),
    },
    "ATTESTED": {
        "NOTICES_ISSUED": ("NOTICES_ISSUED", MANAGER, False),
        "WITHDRAWN": ("WITHDRAWN", MANAGER, False),
    },
    "NOTICES_ISSUED": {
        "CONVERTED": ("CONVERTED", MANAGER, False),
        "WITHDRAWN": ("WITHDRAWN", MANAGER, False),
    },
    "CONVERTED": {},
    "WITHDRAWN": {},
}

# --- ReadinessTask.status -------------------------------------------------
TASK_STATUS_VALUES = ("OPEN", "IN_PROGRESS", "COMPLETE", "WAIVED", "FAILED")
TASK_STATUS = {
    "OPEN": {
        "IN_PROGRESS": ("IN_PROGRESS", MANAGER_OR_COMPLIANCE, False),
        "WAIVED": ("WAIVED", COMPLIANCE, False),
    },
    "IN_PROGRESS": {
        "COMPLETE": ("COMPLETE", MANAGER_OR_COMPLIANCE, False),
        "WAIVED": ("WAIVED", COMPLIANCE, False),
        "FAILED": ("FAILED", MANAGER_OR_COMPLIANCE, False),
    },
    "COMPLETE": {
        # Cascade only: a direct request to fail a completed line is rejected.
        "FAILED": ("FAILED", CASCADE, True),
    },
    "WAIVED": {},
    "FAILED": {
        "IN_PROGRESS": ("IN_PROGRESS", MANAGER_OR_COMPLIANCE, False),
    },
}

# --- LiabilityItem.disposition -------------------------------------------
DISPOSITION_VALUES = ("UNASSIGNED", "ASSUMED", "EXCLUDED", "INDEMNIFIED",
                      "ESCROWED")
DISPOSITION = {
    "UNASSIGNED": {
        "ASSUMED": ("ASSUMED", DEAL_LEAD, False),
        "EXCLUDED": ("EXCLUDED", DEAL_LEAD, False),
        "INDEMNIFIED": ("INDEMNIFIED", DEAL_LEAD, False),
        "ESCROWED": ("ESCROWED", DEAL_LEAD, False),
    },
    "ASSUMED": {
        "ESCROWED": ("ESCROWED", DEAL_LEAD, False),
    },
    "ESCROWED": {
        "EXCLUDED": ("EXCLUDED", DEAL_LEAD, False),
    },
    "EXCLUDED": {},
    "INDEMNIFIED": {},
}


def resolve(table, from_state, request_key, role):
    """Rank 14 state transition legality, then the transition's own actor list.

    An undeclared or cascade-only transition is ERR_INVALID_STATE_TRANSITION;
    a declared transition requested by a role that is not its actor is
    ERR_FORBIDDEN_ROLE.
    """
    available = table.get(from_state, {})
    transition = available.get(request_key)
    if transition is None or transition[2]:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "'%s' is not available from state '%s'." % (request_key, from_state),
        )
    to_state, actors, _ = transition
    if role not in actors:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role '%s' may not perform '%s' from state '%s'."
            % (role, request_key, from_state),
        )
    return to_state


def invalid(from_state, request_key):
    return ApiError(
        "ERR_INVALID_STATE_TRANSITION",
        "'%s' is not available from state '%s'." % (request_key, from_state),
    )
