"""The publication gate ladder and its read-only rehearsal (PRD section 3.9)."""
from datetime import timedelta

import clock
import db
from services import calculations

NOTICE_WINDOW_HOURS = 72
NOTICE_WINDOW = timedelta(hours=NOTICE_WINDOW_HOURS)

PUBLISHABLE_STATUSES = ("FINDINGS_LOCKED", "CLEARED")
UNRESOLVED_REQUEST_STATUSES = ("APPEAL_FILED", "LITIGATION_AUTHORIZED")


def lapse_notice_deadlines(investigation_id, persist=True):
    """The one automatic deadline transition: a record still in NOTICE_SENT whose
    response_deadline_at is at or before the logical clock moves to NO_RESPONSE."""
    now = clock.now()
    lapsed = []
    for record in db.subjects_of_investigation(investigation_id):
        if record["status"] != "NOTICE_SENT" or not record.get("response_deadline_at"):
            continue
        deadline = clock.instant_of(record["response_deadline_at"])
        if deadline is not None and deadline <= now:
            lapsed.append(record)
            if persist:
                record["status"] = "NO_RESPONSE"
                db.touch(record)
    return lapsed


def _traces_to_unresolved_request(investigation_id):
    for dataset in db.datasets_of_investigation(investigation_id):
        request = db.find("records_requests", dataset["request_id"])
        if request is not None and request["status"] in UNRESOLVED_REQUEST_STATUSES:
            return True
    return False


def _has_unsuppressed_source_field(dataset):
    if dataset is None:
        return False
    for field in db.fields_of_dataset(dataset["id"]):
        if field["is_source_identifying"] and not field["suppression_applied"]:
            return True
    return False


def evaluate_gates(investigation, desk, release_dataset, release_dataset_named,
                   check_release_required=True, lapsed_ids=()):
    """Run the ten publication gates in the ascending order of PRD section 2.11.

    Returns the error_id of the first violated gate, or None.
    """
    # Rung 13 -- desk posture
    if desk is not None and desk["security_posture"] == "LOCKDOWN":
        return "ERR_DESK_LOCKDOWN"
    # Rung 14 -- clearance requirement under RESTRICTED
    if desk is not None and desk["security_posture"] == "RESTRICTED" \
            and investigation["status"] != "CLEARED":
        return "ERR_INVESTIGATION_NOT_CLEARED"
    # Rung 17 -- unresolved source requests
    if _traces_to_unresolved_request(investigation["id"]):
        return "ERR_SOURCE_REQUEST_UNRESOLVED"
    # Rung 18 -- release-dataset presence
    if check_release_required:
        mode = investigation["publication_mode"]
        if mode in ("FULL_DATA_RELEASE", "AGGREGATES_ONLY") and not release_dataset_named:
            return "ERR_RELEASE_DATASET_REQUIRED"
        if mode == "METHODOLOGY_ONLY" and release_dataset_named:
            return "ERR_RELEASE_DATASET_REQUIRED"
    # Rung 19 -- source exposure
    if _has_unsuppressed_source_field(release_dataset):
        return "ERR_SOURCE_EXPOSURE_RISK"
    # Rung 20 -- disclosure risk
    aggregate_max, composite, _ = calculations.disclosure_risk_scores(release_dataset)
    _, applicable_score = calculations.applicable_risk(
        investigation["publication_mode"], aggregate_max, composite
    )
    if applicable_score > calculations.PUBLISH_RISK_CEILING:
        return "ERR_DISCLOSURE_RISK_TOO_HIGH"

    records = db.subjects_of_investigation(investigation["id"])
    # Rung 24 -- subject notice pending
    for record in records:
        if not record.get("notice_sent_at"):
            return "ERR_SUBJECT_NOTICE_PENDING"
    # Rung 25 -- notice sufficiency (checked before attempt sufficiency)
    now = clock.now()
    for record in records:
        status = record["status"]
        if status == "UNREACHABLE":
            continue
        sent_at = clock.instant_of(record["notice_sent_at"])
        if sent_at is None or (now - sent_at) < NOTICE_WINDOW:
            return "ERR_INSUFFICIENT_NOTICE"
    # Rung 26 -- attempt sufficiency
    for record in records:
        if record["attempt_count"] < 2:
            return "ERR_INSUFFICIENT_ATTEMPTS"
    # Rung 31 -- release-dataset linkage
    if release_dataset is not None and release_dataset.get("investigation_id") != investigation["id"]:
        return "ERR_DATASET_NOT_LINKED"
    return None


def notice_window_hours(investigation_id):
    """Minimum elapsed notice hours across notified records, 0 when none notified."""
    now = clock.now()
    elapsed = []
    for record in db.subjects_of_investigation(investigation_id):
        sent_at = clock.instant_of(record.get("notice_sent_at"))
        if sent_at is None:
            continue
        seconds = (now - sent_at).total_seconds()
        elapsed.append(int(seconds // 3600))
    if not elapsed:
        return 0
    return min(elapsed)
