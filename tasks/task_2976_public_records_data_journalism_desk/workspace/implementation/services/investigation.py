"""Investigation derived state: the finding-count partition and analysis readiness."""
import db

BUCKET_BY_STATUS = {
    "UNVERIFIED": "unverified_finding_count",
    "DOC_MATCHED": "doc_matched_finding_count",
    "SME_CONFIRMED": "sme_confirmed_finding_count",
    "SME_DISPUTED": "sme_disputed_finding_count",
}


def current_run(investigation_id):
    """The run with the highest run_sequence is by definition the current run."""
    runs = db.runs_of_investigation(investigation_id)
    if not runs:
        return None
    return max(runs, key=lambda r: r["run_sequence"])


def move_bucket(investigation, from_status, to_status):
    if from_status is not None:
        key = BUCKET_BY_STATUS[from_status]
        investigation[key] = investigation[key] - 1
    if to_status is not None:
        key = BUCKET_BY_STATUS[to_status]
        investigation[key] = investigation[key] + 1


def recompute_readiness(investigation):
    """READY when all seven conditions of PRD section 3.7 hold."""
    run = current_run(investigation["id"])
    ready = (
        run is not None
        and run["code_review_status"] == "APPROVED"
        and run["cost_allocation_status"] == "ALLOCATED"
        and investigation["sme_confirmed_finding_count"] >= 1
        and investigation["sme_disputed_finding_count"] == 0
        and investigation["unverified_finding_count"] == 0
        and investigation["doc_matched_finding_count"] == 0
    )
    investigation["analysis_readiness"] = "READY" if ready else "NOT_READY"
    return investigation["analysis_readiness"]


def desk_of(investigation):
    return db.find("desks", investigation["desk_id"])
