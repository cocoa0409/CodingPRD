"""Report submissions: draft creation (with version pinning), submit, the
decide fork, and the appeal loop (PRD 3.4, 3.6).
"""

from clock import clock
from domain import (
    BUDGET_REQUIRED_DOC_TYPES,
    LIVE_SUBMISSION_STATUSES,
    appeal_deadline,
    final_award_score,
    findings_for_round,
    posture_of,
    provisional_and_majors,
)
from envelope import ok
from errors import api_error
from auth import authenticate, authorize
from listing import list_response
from serialize import report_submission
from store import store, new_id, touch
from validate import (
    DOC_TYPES,
    get_body,
    pagination,
    query_filter,
    req_str,
)

_SUBMITTABLE_STATES = ("SUBMITTED", "APPEALED", "UNDER_REVIEW")


def _now():
    return clock.now_iso()


def _parse_budget_documents(body):
    raw = body.get("budget_documents")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise api_error("ERR_VALIDATION", "budget_documents must be a list")
    docs = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise api_error("ERR_VALIDATION", "each budget document must be an object")
        doc_type = entry.get("doc_type")
        if doc_type not in DOC_TYPES:
            raise api_error("ERR_VALIDATION", "doc_type must be POLICY, FINANCIAL_PLAN or COMMUNICATION")
        title = entry.get("title")
        if not isinstance(title, str):
            raise api_error("ERR_VALIDATION", "budget document title must be a string")
        page_count = entry.get("page_count")
        if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count <= 0:
            raise api_error("ERR_VALIDATION", "page_count must be positive")
        docs.append({"doc_type": doc_type, "title": title, "page_count": page_count})
    return docs


def create_submission():
    uid, role = authenticate()
    body = get_body()
    government_id = req_str(body, "government_id")
    cycle_id = req_str(body, "cycle_id")
    docs = _parse_budget_documents(body)
    authorize(role, ["GovernmentContact"])
    # body FKs in input order (PRD 2.7): government_id, then cycle_id
    if government_id not in store.governments:
        raise api_error("ERR_GOVERNMENT_NOT_FOUND", "government not found")
    cycle = store.award_cycles.get(cycle_id)
    if cycle is None:
        raise api_error("ERR_CYCLE_NOT_FOUND", "award cycle not found")
    # ownership (priority 5)
    if government_id != uid:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "government_id must equal the caller's identity")
    # priority 8: one live application per (government, cycle)
    for s in store.report_submissions.values():
        if (
            s["government_id"] == government_id
            and s["cycle_id"] == cycle_id
            and s["status"] in LIVE_SUBMISSION_STATUSES
        ):
            raise api_error(
                "ERR_DUPLICATE_SUBMISSION",
                "a live submission already exists for this government and cycle",
            )
    # priority 8: doc_type unique within the list
    seen = set()
    for d in docs:
        if d["doc_type"] in seen:
            raise api_error("ERR_DOCUMENT_TYPE_DUPLICATE", "duplicate doc_type in budget_documents")
        seen.add(d["doc_type"])
    # priority 10: budget documents are lawful only for BUDGET_PRESENTATION cycles
    if docs and cycle["program_type"] != "BUDGET_PRESENTATION":
        raise api_error(
            "ERR_PROGRAM_NOT_BUDGET",
            "budget_documents are allowed only for BUDGET_PRESENTATION cycles",
        )
    now = _now()
    s = {
        "id": new_id(),
        "government_id": government_id,
        "cycle_id": cycle_id,
        "budget_documents": docs,
        "program_type": cycle["program_type"],
        # version pinning (PRD 2.8): freeze the cycle's checklist at creation
        "pinned_checklist_version_id": cycle["checklist_version_id"],
        "pinned_checklist_stale": False,
        "appeal_round": 1,
        "status": "DRAFT",
        "final_score": None,
        "required_improvements": [],
        "award_conferred": False,
        "submitted_at": None,
        "decided_at": None,
        "conferred_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.report_submissions[s["id"]] = s
    return ok(report_submission(s), 201)


def submit_submission(submission_id):
    uid, role = authenticate()
    get_body()
    authorize(role, ["GovernmentContact"])
    s = store.report_submissions.get(submission_id)
    if s is None:
        raise api_error("ERR_SUBMISSION_NOT_FOUND", "report submission not found")
    if s["government_id"] != uid:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "only the owning government may submit")
    # state gate (6)
    if s["status"] != "DRAFT":
        raise api_error("ERR_SUBMISSION_STATE_INVALID", "submit requires status DRAFT")
    # pin integrity (8)
    if s["pinned_checklist_stale"]:
        raise api_error("ERR_CHECKLIST_PIN_STALE", "the pinned checklist has been superseded")
    # temporal gate (9): cycle posture must be OPEN
    cycle = store.award_cycles[s["cycle_id"]]
    if posture_of(cycle, clock.now()) != "OPEN":
        raise api_error("ERR_SUBMISSION_WINDOW_CLOSED", "the cycle's submission window is not open")
    # structural gate (10): BUDGET_PRESENTATION needs all three doc types
    if s["program_type"] == "BUDGET_PRESENTATION":
        present = {d["doc_type"] for d in s["budget_documents"]}
        if any(t not in present for t in BUDGET_REQUIRED_DOC_TYPES):
            raise api_error(
                "ERR_BUDGET_DOCUMENTS_INCOMPLETE",
                "budget submissions require POLICY, FINANCIAL_PLAN and COMMUNICATION documents",
            )
    now = _now()
    s["status"] = "SUBMITTED"
    s["submitted_at"] = now
    touch(s, now)
    cycle["submitted_count"] += 1
    touch(cycle, now)
    return ok(report_submission(s))


def decide_submission(submission_id):
    uid, role = authenticate()
    get_body()
    authorize(role, ["AwardsDirector"])
    s = store.report_submissions.get(submission_id)
    if s is None:
        raise api_error("ERR_SUBMISSION_NOT_FOUND", "report submission not found")
    # state gate (6) with the PRD 3.6 error split
    if s["status"] == "UNDER_REVIEW":
        raise api_error("ERR_FINDINGS_INCOMPLETE", "fewer than 3 current-round findings filed")
    if s["status"] != "DECISION_READY":
        raise api_error("ERR_SUBMISSION_STATE_INVALID", "decide requires status DECISION_READY")
    checklist = store.checklist_versions[s["pinned_checklist_version_id"]]
    final = final_award_score(s, checklist)
    _, majors = provisional_and_majors(s)
    now = _now()
    s["final_score"] = final
    s["decided_at"] = now
    if final >= checklist["pass_score"] and majors == 0:
        # branch A: DECIDED_AWARDED (terminal)
        s["status"] = "DECIDED_AWARDED"
        s["award_conferred"] = True
        s["conferred_at"] = now
        touch(s, now)
        cycle = store.award_cycles[s["cycle_id"]]
        cycle["conferred_count"] += 1
        touch(cycle, now)
        gov = store.governments[s["government_id"]]
        gov["lifetime_award_count"] += 1
        touch(gov, now)
    else:
        # branch B: DECIDED_DENIED; required_improvements = MAJOR comment texts
        # of current-round findings in finding submission order
        improvements = []
        for f in findings_for_round(s["id"], s["appeal_round"]):
            for c in f["comments"]:
                if c["severity"] == "MAJOR":
                    improvements.append(c["text"])
        s["status"] = "DECIDED_DENIED"
        s["required_improvements"] = improvements
        touch(s, now)
    return ok(report_submission(s))


def appeal_submission(submission_id):
    uid, role = authenticate()
    get_body()
    authorize(role, ["GovernmentContact"])
    s = store.report_submissions.get(submission_id)
    if s is None:
        raise api_error("ERR_SUBMISSION_NOT_FOUND", "report submission not found")
    if s["government_id"] != uid:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "only the owning government may appeal")
    # state gate (6) outranks the temporal gate (9)
    if s["status"] != "DECIDED_DENIED":
        raise api_error("ERR_SUBMISSION_STATE_INVALID", "appeal requires status DECIDED_DENIED")
    if clock.now() > appeal_deadline(s["decided_at"]):
        raise api_error("ERR_APPEAL_WINDOW_CLOSED", "the thirty-day appeal window has closed")
    now = _now()
    s["status"] = "APPEALED"
    s["appeal_round"] += 1
    # provisional_score / major_deficiency_total reset to null / 0 — automatic,
    # since both derive from the (now superseded) current round's findings.
    # Cancel the superseded round's still-open assignments.
    for a in store.review_assignments.values():
        if a["submission_id"] == s["id"] and a["status"] in ("OFFERED", "ACCEPTED"):
            a["status"] = "CANCELLED"
            touch(a, now)
            reviewer = store.reviewer_profiles.get(a["reviewer_id"])
            if reviewer is not None:
                touch(reviewer, now)
    touch(s, now)
    return ok(report_submission(s))


def get_submission(submission_id):
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "GovernmentContact", "AwardsDirector"])
    s = store.report_submissions.get(submission_id)
    if s is None:
        raise api_error("ERR_SUBMISSION_NOT_FOUND", "report submission not found")
    if role == "GovernmentContact" and s["government_id"] != uid:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "GovernmentContact sees only own submissions")
    return ok(report_submission(s))


def list_submissions():
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "GovernmentContact", "AwardsDirector"])
    limit, offset = pagination()
    rows = list(store.report_submissions.values())
    if role == "GovernmentContact":
        rows = [s for s in rows if s["government_id"] == uid]
    government_id = query_filter("government_id")
    if government_id is not None:
        rows = [s for s in rows if s["government_id"] == government_id]
    cycle_id = query_filter("cycle_id")
    if cycle_id is not None:
        rows = [s for s in rows if s["cycle_id"] == cycle_id]
    pinned = query_filter("pinned_checklist_version_id")
    if pinned is not None:
        rows = [s for s in rows if s["pinned_checklist_version_id"] == pinned]
    status = query_filter("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return list_response(rows, report_submission, limit, offset)


def register(app):
    app.add_url_rule("/gfoa/report-submissions", "create_submission", create_submission, methods=["POST"])
    app.add_url_rule("/gfoa/report-submissions", "list_submissions", list_submissions, methods=["GET"])
    app.add_url_rule("/gfoa/report-submissions/<submission_id>", "get_submission", get_submission, methods=["GET"])
    app.add_url_rule("/gfoa/report-submissions/<submission_id>/submit", "submit_submission", submit_submission, methods=["POST"])
    app.add_url_rule("/gfoa/report-submissions/<submission_id>/decide", "decide_submission", decide_submission, methods=["POST"])
    app.add_url_rule("/gfoa/report-submissions/<submission_id>/appeal", "appeal_submission", appeal_submission, methods=["POST"])
