"""Review cycles, deficiency letters, and amendments (PRD 3.5)."""
from flask import Blueprint

from auth import ALL_ROLES, auth, own_application, require_role
from clock import add_months, today
from domain import PRIORITY_MONTHS, current_cycle
from envelope import sort_default, success_list, success_object
from errors import fail
from serialize import amendment, review_cycle
from state import STORE, create_entity, get, touch
from validate import body, opt_str, req_bool, req_enum, req_int

bp = Blueprint("cycles", __name__)


@bp.get("/generic-drug-review/applications/<app_id>/review-cycles")
def list_cycles(app_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    if get("applications", app_id) is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    items = [c for c in STORE["cycles"].values() if c["application_id"] == app_id]
    items.sort(key=lambda c: c["cycle_number"])
    return success_list([review_cycle(c) for c in items])


@bp.post("/generic-drug-review/review-cycles/<cycle_id>/issue-deficiency")
def issue_deficiency(cycle_id):
    _uid, role = auth()
    require_role(role, ["RegulatoryReviewer"])
    cycle = get("cycles", cycle_id)
    if cycle is None:
        fail("ERR_REVIEW_CYCLE_NOT_FOUND", "Review cycle id does not exist")
    b = body()
    summary = opt_str(b, "deficiency_summary", None)
    app = get("applications", cycle["application_id"])
    t = today()
    if cycle["status"] == "OPEN":
        if app["status"] != "RECEIVED":
            fail("ERR_INVALID_STATE",
                 "A deficiency letter requires the application to be RECEIVED")
        cycle["status"] = "CRL_ISSUED"
        cycle["deficiency_issued_date"] = t.isoformat()
        cycle["deficiency_response_due_date"] = add_months(t, 12).isoformat()
        if summary is not None:
            cycle["deficiency_summary"] = summary
        touch(cycle)
        return success_object(review_cycle(cycle), 201)
    if cycle["status"] == "AMENDMENT_RECEIVED":
        # Second round: this cycle closes SUPERSEDED and the next cycle opens
        # already in CRL_ISSUED with a fresh 12-month response clock.
        cycle["status"] = "CLOSED"
        cycle["closed_reason"] = "SUPERSEDED"
        touch(cycle)
        newc = create_entity("cycles", {
            "application_id": app["id"],
            "cycle_number": cycle["cycle_number"] + 1,
            "status": "CRL_ISSUED",
            "opened_date": t.isoformat(),
            "base_review_months": PRIORITY_MONTHS[app["review_priority"]],
            "major_amendment_extensions_count": 0,
            "deficiency_issued_date": t.isoformat(),
            "deficiency_response_due_date": add_months(t, 12).isoformat(),
            "deficiency_response_received_date": None,
            "deficiency_summary": summary,
            "closed_reason": None,
        })
        app["current_cycle_number"] = cycle["cycle_number"] + 1
        touch(app)
        return success_object(review_cycle(newc), 201)
    fail("ERR_INVALID_STATE",
         "A deficiency letter requires the cycle to be OPEN or "
         "AMENDMENT_RECEIVED")


@bp.post("/generic-drug-review/applications/<app_id>/amendments")
def create_amendment(app_id):
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    app = get("applications", app_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    own_application(uid, app)
    b = body()
    classification = req_enum(b, "classification", ("MAJOR", "MINOR"))
    contains_new_be_data = req_bool(b, "contains_new_be_data")
    expected = req_int(b, "expected_application_version")
    notes = opt_str(b, "notes", None)
    # Priority 6 OCC, then priority 7 state.
    if expected != app["version"]:
        fail("ERR_STALE_VERSION",
             "expected_application_version does not match the application's "
             "current version")
    if app["status"] not in ("RECEIVED", "TENTATIVE_APPROVAL"):
        fail("ERR_INVALID_STATE",
             "Amendments require the application to be RECEIVED or "
             "TENTATIVE_APPROVAL")
    t = today()
    amd = create_entity("amendments", {
        "application_id": app_id,
        "classification": classification,
        "contains_new_be_data": contains_new_be_data,
        "notes": notes,
        "submitted_date": t.isoformat(),
    })
    if app["status"] == "TENTATIVE_APPROVAL":
        # Reopening: back to RECEIVED, TA date cleared, fresh cycle OPEN.
        app["status"] = "RECEIVED"
        app["tentative_approval_date"] = None
        create_entity("cycles", {
            "application_id": app_id,
            "cycle_number": app["current_cycle_number"] + 1,
            "status": "OPEN",
            "opened_date": t.isoformat(),
            "base_review_months": PRIORITY_MONTHS[app["review_priority"]],
            "major_amendment_extensions_count":
                1 if classification == "MAJOR" else 0,
            "deficiency_issued_date": None,
            "deficiency_response_due_date": None,
            "deficiency_response_received_date": None,
            "deficiency_summary": None,
            "closed_reason": None,
        })
        app["current_cycle_number"] += 1
    else:
        cur = current_cycle(app)
        if cur is not None and cur["status"] == "CRL_ISSUED":
            # The deficiency response; always timely here because the clock
            # passing the due date would already have lapsed the cycle.
            cur["deficiency_response_received_date"] = t.isoformat()
            cur["status"] = "AMENDMENT_RECEIVED"
            if classification == "MAJOR":
                cur["major_amendment_extensions_count"] += 1
            touch(cur)
        elif cur is not None and cur["status"] in ("OPEN", "AMENDMENT_RECEIVED"):
            # Unsolicited amendment; MAJOR extends the current cycle's goal.
            if classification == "MAJOR":
                cur["major_amendment_extensions_count"] += 1
                touch(cur)
    touch(app)
    return success_object(amendment(amd), 201)


@bp.get("/generic-drug-review/applications/<app_id>/amendments")
def list_amendments(app_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    if get("applications", app_id) is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    items = [a for a in STORE["amendments"].values()
             if a["application_id"] == app_id]
    return success_list([amendment(a) for a in sort_default(items)])
