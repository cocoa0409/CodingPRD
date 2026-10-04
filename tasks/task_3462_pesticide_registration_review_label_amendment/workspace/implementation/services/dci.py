"""Data call-in obligation ledger and its automatic transitions (PRD 3.7)."""
from db import store, touch


def linked_studies(dci_id):
    return [s for s in store["studies"].values() if s.get("data_call_in_id") == dci_id]


def compute_ledger(dci):
    """satisfied / pending / outstanding partition required_study_types as sets.

    satisfied: >= 1 ACCEPTED linked study of the type.
    pending:   no ACCEPTED but >= 1 RECEIVED linked study of the type.
    outstanding: the remainder. Order follows required_study_types.
    """
    studies = linked_studies(dci["id"])
    satisfied, pending, outstanding = [], [], []
    for study_type in dci["required_study_types"]:
        of_type = [s for s in studies if s["study_type"] == study_type]
        if any(s["status"] == "ACCEPTED" for s in of_type):
            satisfied.append(study_type)
        elif any(s["status"] == "RECEIVED" for s in of_type):
            pending.append(study_type)
        else:
            outstanding.append(study_type)
    return {
        "satisfied_study_types": satisfied,
        "pending_study_types": pending,
        "outstanding_study_types": outstanding,
    }


def _maybe_promote_case(dci):
    """Case DCI_PENDING -> UNDER_REVIEW once all of the case's DCIs are SATISFIED."""
    case = store["review_cases"][dci["review_case_id"]]
    if case["status"] != "DCI_PENDING":
        return
    case_dcis = [
        d for d in store["dcis"].values() if d["review_case_id"] == case["id"]
    ]
    if all(d["status"] == "SATISFIED" for d in case_dcis):
        case["status"] = "UNDER_REVIEW"
        touch(case)


def reconcile_after_change(dci):
    """Auto-transitions after a respond call or a linked-study decision.

    DCI in RESPONDED/DEFICIENT with every required type satisfied -> SATISFIED,
    then the owning case may return to UNDER_REVIEW.
    """
    ledger = compute_ledger(dci)
    if dci["status"] in ("RESPONDED", "DEFICIENT") and not ledger["outstanding_study_types"] \
            and not ledger["pending_study_types"]:
        dci["status"] = "SATISFIED"
        touch(dci)
        _maybe_promote_case(dci)
    return ledger
