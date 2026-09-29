"""Multi-hop cascades (PRD sections 3.1, 3.5, 3.6 and 3.8)."""
import db
from services import investigation as inv_service
from services import ledger


def _ordered_investigations(rows):
    """created_at ascending then headline ascending."""
    rows = list(rows)
    rows.sort(key=lambda i: (i["created_at"], i["headline"]))
    return rows


HOLDABLE_STATUSES = ("ANALYSIS", "FINDINGS_LOCKED", "CLEARED")


def hold_investigations(investigations, hold_reason_code):
    """Move every eligible investigation to HOLD_LEGAL_REVIEW."""
    held = []
    for row in _ordered_investigations(investigations):
        if row["status"] in HOLDABLE_STATUSES:
            row["status"] = "HOLD_LEGAL_REVIEW"
            row["hold_reason_code"] = hold_reason_code
            db.touch(row)
            held.append(row)
    return held


def cancel_booked_sessions(investigation_ids, cancellation_reason_code):
    """Every BOOKED enclave session whose dataset belongs to one of the given
    investigations moves to CANCELLED, decrementing the owning enclave's
    booked_session_count."""
    target_ids = set(investigation_ids)
    dataset_ids = set()
    for dataset in db.all_of("datasets"):
        if dataset.get("investigation_id") in target_ids:
            dataset_ids.add(dataset["id"])
    cancelled = []
    sessions = sorted(
        db.all_of("enclave_sessions"), key=lambda s: (s["created_at"], s["_seq"])
    )
    for session in sessions:
        if session["status"] != "BOOKED" or session["dataset_id"] not in dataset_ids:
            continue
        session["status"] = "CANCELLED"
        session["cancellation_reason_code"] = cancellation_reason_code
        db.touch(session)
        enclave = db.find("secure_enclaves", session["enclave_id"])
        if enclave is not None:
            enclave["booked_session_count"] = enclave["booked_session_count"] - 1
            db.touch(enclave)
        cancelled.append(session)
    return cancelled


def source_exposure_incident(desk):
    """PRD section 3.1: LOCKDOWN plus two cascade hops."""
    desk["source_exposure_incident_count"] = desk["source_exposure_incident_count"] + 1
    ledger.recompute_posture(desk)
    # Hop one
    held = hold_investigations(db.investigations_of_desk(desk["id"]), "SOURCE_EXPOSURE_INCIDENT")
    # Hop two -- every BOOKED session on any dataset of any of this desk's
    # investigations (not merely the ones just held)
    all_ids = [i["id"] for i in db.investigations_of_desk(desk["id"])]
    cancel_booked_sessions(all_ids, "DESK_LOCKDOWN")
    db.touch(desk)
    return held


def litigation_authorized(desk, records_request):
    """Hops three, four and five of the appeal-denial cascade."""
    desk["litigation_exposure_count"] = desk["litigation_exposure_count"] + 1
    desk["open_request_count"] = desk["open_request_count"] - 1
    ledger.recompute_posture(desk)
    # Hop four: investigations reachable through this request's datasets
    reachable_ids = []
    for dataset in db.datasets_of_request(records_request["id"]):
        if dataset.get("investigation_id") and dataset["investigation_id"] not in reachable_ids:
            reachable_ids.append(dataset["investigation_id"])
    reachable = [db.find("investigations", i) for i in reachable_ids]
    reachable = [i for i in reachable if i is not None]
    held = hold_investigations(reachable, "LITIGATION_AUTHORIZED")
    # Hop five
    cancel_booked_sessions([i["id"] for i in held], "INVESTIGATION_LEGAL_HOLD")
    return held


def quarantine_dataset(dataset, quarantine_reason_code):
    """PRD section 3.6: three hops."""
    # Hop one
    dataset["status"] = "QUARANTINED"
    dataset["quarantine_reason_code"] = quarantine_reason_code
    dataset["allocated_cost_cents"] = 0
    db.touch(dataset)
    investigation_id = dataset.get("investigation_id")
    if not investigation_id:
        return None
    investigation = db.find("investigations", investigation_id)
    if investigation is None:
        return None
    # Hop two
    for run in db.runs_of_investigation(investigation_id):
        changed = False
        if run["code_review_status"] == "APPROVED":
            run["code_review_status"] = "CHANGES_REQUESTED"
            changed = True
        if run["cost_allocation_status"] == "ALLOCATED":
            run["cost_allocation_status"] = "NOT_ALLOCATED"
            run["allocated_total_cents"] = 0
            changed = True
        if changed:
            db.touch(run)
    # Hop three
    inv_service.recompute_readiness(investigation)
    if investigation["status"] == "FINDINGS_LOCKED":
        investigation["status"] = "ANALYSIS"
    db.touch(investigation)
    return investigation


def revoke_verification(finding, investigation):
    """PRD section 3.8: three hops."""
    previous_status = finding["verification_status"]
    # Hop one
    finding["verification_status"] = "UNVERIFIED"
    finding["matched_page"] = None
    finding["sme_verdict_rationale"] = None
    inv_service.move_bucket(investigation, previous_status, "UNVERIFIED")
    db.touch(finding)
    # Hop two
    for assignment in db.assignments_of_finding(finding["id"]):
        if assignment["status"] not in ("ASSIGNED", "COMPLETED"):
            continue
        was_assigned = assignment["status"] == "ASSIGNED"
        assignment["status"] = "RELEASED"
        assignment["verdict"] = None
        assignment["rationale"] = None
        db.touch(assignment)
        if was_assigned:
            reviewer = db.find("expert_reviewers", assignment["reviewer_id"])
            if reviewer is not None:
                reviewer["active_assignment_count"] = reviewer["active_assignment_count"] - 1
                db.touch(reviewer)
    # Hop three
    inv_service.recompute_readiness(investigation)
    if investigation["status"] == "FINDINGS_LOCKED":
        investigation["status"] = "ANALYSIS"
    db.touch(investigation)
    return finding
