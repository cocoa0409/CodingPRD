"""Data practice reviews: opening, findings, remediation, decision, reassignment.

PRD 3.3, 3.5 and 3.6.
"""
from flask import Blueprint

from core import auth, envelope, logic, serialize, store, validate
from core.errors import ApiError
from core.validate import F

bp = Blueprint("reviews", __name__)


@bp.post("/data-practice-reviews")
def open_review():
    auth.actor("PrivacyAnalyst", "PrivacyOfficeAdmin")
    data = validate.body([
        F("source_request_id", "str"),
        F("assigned_analyst_id", "str"),
        F("framework_set", "enum_array", members=set(logic.FRAMEWORKS), min_items=1,
          no_duplicates=True),
        F("estimated_minutes", "int", lo=15, hi=1200),
    ])
    source = auth.need("request", data["source_request_id"])
    analyst = auth.need("analyst", data["assigned_analyst_id"])

    if source["status"] != "TRIAGED_FOR_REVIEW":
        raise ApiError("ERR_REQUEST_NOT_TRIAGED")

    # Rung 42, the very bottom of the ladder.
    allocated = logic.analyst_allocated_minutes(analyst["id"])
    if allocated + data["estimated_minutes"] > analyst["review_capacity_minutes"]:
        raise ApiError("ERR_ANALYST_CAPACITY_EXCEEDED")

    application = store.applications[source["application_id"]]
    vendor = store.vendors[application["vendor_id"]]

    row = store.new_row({
        "source_request_id": source["id"],
        # Copied, never supplied and never rewritten (PRD 3.3).
        "application_id": application["id"],
        "vendor_id": vendor["id"],
        "assigned_analyst_id": analyst["id"],
        "decided_by_analyst_id": None,
        "framework_set": data["framework_set"],
        "estimated_minutes": data["estimated_minutes"],
        "status": "SCREENING",
        "round_number": 1,
        "open_findings_count": 0,
        "unresolved_findings_count": 0,
        "provisional_compliance_score": None,
        "final_compliance_score": None,
        "remediation_due_at": None,
        "decision_note": None,
    })
    store.reviews[row["id"]] = row

    logic.resum_analyst_minutes(analyst)
    if vendor["status"] == "REGISTERED":
        vendor["status"] = "UNDER_REVIEW"
        vendor["privacy_posture"] = logic.vendor_privacy_posture(vendor)
        store.bump(vendor)
    return envelope.created(serialize.review(row))


@bp.get("/data-practice-reviews")
def list_reviews():
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison")
    filters = envelope.query_filters({
        "source_request_id": None,
        "application_id": None,
        "vendor_id": None,
        "assigned_analyst_id": None,
        "decided_by_analyst_id": None,
        "status": set(logic.REVIEW_STATUSES),
    })
    rows = list(store.reviews.values())
    for key in ("source_request_id", "application_id", "vendor_id", "assigned_analyst_id",
                "decided_by_analyst_id", "status"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    return envelope.paged(store.ordered(rows), serialize.review)


@bp.get("/data-practice-reviews/<review_id>")
def read_review(review_id):
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison")
    return envelope.ok(serialize.review(auth.need("review", review_id)))


@bp.post("/data-practice-reviews/<review_id>/issue-findings")
def issue_findings(review_id):
    user_id, _role = auth.actor("PrivacyAnalyst")
    data = validate.body([
        F("findings_count", "int", lo=0),
        F("decision_note", "str", required=False),
    ])
    row = auth.need("review", review_id)
    # Rung 6: findings are authored only by the assigned analyst (PRD 3.5).
    auth.owner_or_403(user_id == row["assigned_analyst_id"])

    if row["status"] not in ("SCREENING", "REMEDIATION_SUBMITTED"):
        raise ApiError("ERR_REVIEW_STATE_INVALID")
    live = [c for c in logic.review_commitments(row["id"])
            if c["status"] in ("PROPOSED", "ACCEPTED")]
    if not live:
        raise ApiError("ERR_REVIEW_STATE_INVALID",
                       "At least one proposed or accepted commitment is required.")

    vendor = store.vendors[row["vendor_id"]]
    if vendor["privacy_posture"] == "FROZEN":
        raise ApiError("ERR_VENDOR_POSTURE_FROZEN")

    next_round = row["round_number"]
    if row["status"] == "REMEDIATION_SUBMITTED":
        next_round = row["round_number"] + 1
        if next_round > logic.FINDINGS_ROUND_MAX:
            raise ApiError("ERR_REMEDIATION_ROUND_LIMIT")

    row["round_number"] = next_round
    row["status"] = "FINDINGS_ISSUED"
    row["open_findings_count"] = data["findings_count"]
    row["unresolved_findings_count"] = data["findings_count"]
    row["remediation_due_at"] = store.clock() + store.hours(logic.REMEDIATION_WINDOW_HOURS)
    if "decision_note" in data:
        row["decision_note"] = data["decision_note"]

    application = store.applications[row["application_id"]]
    row["provisional_compliance_score"] = logic.compliance_score(
        row, vendor, application, "provisional")
    store.bump(row)
    return envelope.ok(serialize.review(row))


@bp.post("/data-practice-reviews/<review_id>/submit-remediation")
def submit_remediation(review_id):
    user_id, _role = auth.actor("VendorLiaison")
    data = validate.body([
        F("resolved_findings_count", "int", lo=0),
        F("remediation_note", "str", required=False),
    ])
    row = auth.need("review", review_id)
    # Rung 6: only the vendor's own liaison may answer the findings (PRD 3.5).
    auth.owner_or_403(user_id == row["vendor_id"])

    if row["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_REVIEW_STATE_INVALID")
    # Inclusive window: exactly at the deadline still succeeds.
    if row["remediation_due_at"] is not None and store.clock() > row["remediation_due_at"]:
        raise ApiError("ERR_REMEDIATION_WINDOW_CLOSED")

    unresolved = row["open_findings_count"] - data["resolved_findings_count"]
    if unresolved < 0:
        unresolved = 0
    row["status"] = "REMEDIATION_SUBMITTED"
    row["unresolved_findings_count"] = unresolved
    row["open_findings_count"] = unresolved
    if "remediation_note" in data:
        row["_remediation_note"] = data["remediation_note"]
    store.bump(row)
    return envelope.ok(serialize.review(row))


@bp.post("/data-practice-reviews/<review_id>/decide")
def decide_review(review_id):
    user_id, _role = auth.actor("PrivacyAnalyst")
    data = validate.body([
        F("disposition", "enum", members={"CLEAR", "CONDITIONAL", "BLOCK"}),
        F("decision_note", "str", required=False),
    ])
    row = auth.need("review", review_id)

    # Rung 7: a LEAD analyst who is not the assignee (PRD 3.6).
    acting = store.analysts.get(user_id)
    auth.sod_or_403(acting is not None
                    and acting["credential_level"] == "LEAD"
                    and user_id != row["assigned_analyst_id"])

    if row["status"] in ("SCREENING", "REMEDIATION_SUBMITTED"):
        raise ApiError("ERR_REVIEW_STATE_INVALID")
    if row["status"] in logic.TERMINAL_REVIEW_STATUSES:
        raise ApiError("ERR_REVIEW_ALREADY_DECIDED")

    disposition = data["disposition"]
    vendor = store.vendors[row["vendor_id"]]
    application = store.applications[row["application_id"]]

    if disposition == "CLEAR" and not vendor["subprocessor_disclosure_complete"]:
        raise ApiError("ERR_SUBPROCESSOR_DISCLOSURE_INCOMPLETE")

    # Rung 41: each disposition's own applicability condition.
    if disposition == "CLEAR" and row["unresolved_findings_count"] != 0:
        raise ApiError("ERR_DISPOSITION_NOT_APPLICABLE")
    if disposition == "CONDITIONAL" and row["unresolved_findings_count"] <= 0:
        raise ApiError("ERR_DISPOSITION_NOT_APPLICABLE")

    # Hop 1 -- the review's own row.
    row["status"] = {"CLEAR": "CLEARED", "CONDITIONAL": "CONDITIONAL", "BLOCK": "BLOCKED"}[
        disposition]
    row["decided_by_analyst_id"] = user_id
    if "decision_note" in data:
        row["decision_note"] = data["decision_note"]
    row["final_compliance_score"] = logic.compliance_score(row, vendor, application, "final")
    store.bump(row)

    for commitment in logic.review_commitments(row["id"]):
        if commitment["status"] == "PROPOSED":
            commitment["status"] = "SUPERSEDED"
            store.bump(commitment)
    logic.recompute_application_exposure(application)

    assignee = store.analysts.get(row["assigned_analyst_id"])
    if assignee is not None:
        logic.resum_analyst_minutes(assignee)

    # Hop 2 -- the application.
    if application["status"] == "IN_REVIEW":
        application["status"] = {
            "CLEAR": "APPROVED",
            "CONDITIONAL": "APPROVED_WITH_CONDITIONS",
            "BLOCK": "BLOCKED",
        }[disposition]
        store.bump(application)

    # Hop 3 -- every request of that application still awaiting the outcome.
    landing = "CLOSED_BLOCKED" if disposition == "BLOCK" else "CLOSED_APPROVED"
    teachers = set()
    for req in logic.application_requests(application["id"]):
        if req["status"] == "TRIAGED_FOR_REVIEW":
            req["status"] = landing
            store.bump(req)
            teachers.add(req["requester_teacher_id"])

    # Hop 4 -- the filing teachers' open counts.
    for teacher_id in teachers:
        logic.recount_teacher_requests(store.teachers[teacher_id])

    # The BLOCK branch alone revokes live catalog entries.
    if disposition == "BLOCK":
        revoked = False
        for entry in logic.application_entries(application["id"]):
            if entry["status"] in logic.ACTIVE_WINDOW_STATUSES:
                entry["status"] = "REVOKED"
                entry["revoked_reason"] = "REVIEW_BLOCKED"
                store.bump(entry)
                revoked = True
        if revoked:
            logic.recompute_application_visibility(application)

    # The vendor's registry standing, then risk_score, then posture.
    if vendor["status"] in ("REGISTERED", "UNDER_REVIEW"):
        vendor["status"] = {
            "CLEAR": "APPROVED",
            "CONDITIONAL": "CONDITIONAL",
            "BLOCK": "REJECTED",
        }[disposition]
    logic.recompute_vendor(vendor)
    return envelope.ok(serialize.review(row))


@bp.post("/data-practice-reviews/<review_id>/reassign")
def reassign_review(review_id):
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([F("assigned_analyst_id", "str")])
    row = auth.need("review", review_id)
    incoming = auth.need("analyst", data["assigned_analyst_id"])

    if row["status"] != "SCREENING":
        raise ApiError("ERR_REVIEW_STATE_INVALID")

    # Rung 42 carries all three remaining conditions (PRD 3.3).
    if incoming["id"] == row["assigned_analyst_id"]:
        raise ApiError("ERR_ANALYST_CAPACITY_EXCEEDED")
    if incoming["status"] != "ACTIVE":
        raise ApiError("ERR_ANALYST_CAPACITY_EXCEEDED")
    if (logic.analyst_allocated_minutes(incoming["id"]) + row["estimated_minutes"]
            > incoming["review_capacity_minutes"]):
        raise ApiError("ERR_ANALYST_CAPACITY_EXCEEDED")

    outgoing = store.analysts.get(row["assigned_analyst_id"])
    row["assigned_analyst_id"] = incoming["id"]
    store.bump(row)

    if outgoing is not None:
        logic.resum_analyst_minutes(outgoing)
    logic.resum_analyst_minutes(incoming)
    return envelope.ok(serialize.review(row))
