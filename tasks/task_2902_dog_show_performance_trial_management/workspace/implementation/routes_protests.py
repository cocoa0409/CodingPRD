"""Protests: filing, the review loop, decisions and the remedy cascade."""
from flask import Blueprint

import agg
from auth import authenticate, must_get, owner_check
import calc
from common import ALL_ROLES, PROTEST_TYPES, RESOLUTION_CODES, shift_instant
from envelope import list_response, object_response
from errors import fail
import shape
import store
from store import set_fields

bp = Blueprint("protests", __name__)

LIVE_PROTESTS = ("FILED", "UNDER_REVIEW", "EVIDENCE_REQUESTED")
PROTEST_DECISIONS = ["UPHOLD", "DISMISS"]
UPHOLD_CODES = ("DISQUALIFY_ENTRY", "VACATE_PLACEMENT", "WARNING")
REMEDY_CODES = ("DISQUALIFY_ENTRY", "VACATE_PLACEMENT")


def _window_open(cls, show):
    if cls["status"] in ("COMPLETED", "ABANDONED") and cls["completed_at"] is not None:
        deadline = shift_instant(cls["completed_at"], hours=calc.PROTEST_WINDOW_HOURS)
        return store.now() <= deadline
    return show["status"] == "IN_PROGRESS"


@bp.post("/protests")
def file_protest():
    user_id, _role = authenticate(["Handler"])
    body = shape.json_body()
    show_id = shape.string_field(body, "show_id")
    entry_id = shape.string_field(body, "entry_id")
    filed_by_handler_id = shape.string_field(body, "filed_by_handler_id")
    protest_type = shape.string_field(body, "protest_type", enum=PROTEST_TYPES)
    statement = shape.string_field(body, "statement")
    deposit_cents = shape.int_field(body, "deposit_cents", minimum=0)

    show = must_get("shows", show_id)
    entry = must_get("entries", entry_id)
    handler = must_get("handlers", filed_by_handler_id)

    owner_check(user_id, filed_by_handler_id)

    if entry["show_id"] != show_id:
        fail("ERR_INVALID_STATE", "The protested entry belongs to another show.")
    if show["status"] not in ("IN_PROGRESS", "COMPLETED", "RESULTS_FILED"):
        fail("ERR_INVALID_STATE",
             "A protest may not be filed while the show is %s." % show["status"])
    if handler["status"] != "ACTIVE":
        fail("ERR_HANDLER_SUSPENDED", "The handler is not ACTIVE.")

    cls = store.get("classes", entry["class_id"])
    if not _window_open(cls, show):
        fail("ERR_PROTEST_WINDOW_EXPIRED", "The protest window has closed.")

    for other in store.rows("protests"):
        if other["entry_id"] == entry_id and other["status"] in LIVE_PROTESTS:
            fail("ERR_INVALID_STATE",
                 "A live protest already exists against this entry.")

    if deposit_cents < calc.PROTEST_DEPOSIT_MIN_CENTS:
        fail("ERR_PROTEST_DEPOSIT_INSUFFICIENT",
             "The deposit must be at least %d cents."
             % calc.PROTEST_DEPOSIT_MIN_CENTS)

    rec = store.insert("protests", {
        "show_id": show_id,
        "entry_id": entry_id,
        "filed_by_handler_id": filed_by_handler_id,
        "protest_type": protest_type,
        "statement": statement,
        "deposit_cents": deposit_cents,
        "status": "FILED",
        "review_round": 0,
        "evidence_request": None,
        "evidence_note": None,
        "reviewed_by_user_id": None,
        "resolution_code": None,
        "deposit_refunded": False,
        "decided_at": None,
    })
    return object_response(store.serialize(rec), 201)


@bp.get("/protests/<protest_id>")
def read_protest(protest_id):
    authenticate(ALL_ROLES)
    return object_response(store.serialize(must_get("protests", protest_id)))


@bp.get("/protests")
def list_protests():
    authenticate(ALL_ROLES)
    limit, offset = shape.pagination()
    rows = shape.apply_filters(store.rows("protests"), {
        "show_id": "show_id",
        "entry_id": "entry_id",
        "filed_by_handler_id": "filed_by_handler_id",
        "status": "status",
    })
    items, total = shape.paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/protests/<protest_id>/begin-review")
def begin_review(protest_id):
    authenticate(["SanctionOfficer"])
    protest = must_get("protests", protest_id)
    shape.json_body()
    if protest["status"] != "FILED":
        fail("ERR_INVALID_STATE",
             "A protest in %s may not open a hearing." % protest["status"])
    set_fields(protest, status="UNDER_REVIEW",
               review_round=protest["review_round"] + 1)
    store.touch(protest)
    return object_response(store.serialize(protest))


@bp.post("/protests/<protest_id>/request-evidence")
def request_evidence(protest_id):
    authenticate(["SanctionOfficer"])
    protest = must_get("protests", protest_id)
    body = shape.json_body()
    evidence_request = shape.string_field(body, "evidence_request")
    if protest["status"] != "UNDER_REVIEW":
        fail("ERR_PROTEST_NOT_IN_REVIEW",
             "A protest in %s is not under review." % protest["status"])
    set_fields(protest, status="EVIDENCE_REQUESTED",
               evidence_request=evidence_request)
    store.touch(protest)
    return object_response(store.serialize(protest))


@bp.post("/protests/<protest_id>/resubmit-evidence")
def resubmit_evidence(protest_id):
    user_id, _role = authenticate(["Handler"])
    protest = must_get("protests", protest_id)
    body = shape.json_body()
    evidence_note = shape.string_field(body, "evidence_note")
    owner_check(user_id, protest["filed_by_handler_id"])
    if protest["status"] != "EVIDENCE_REQUESTED":
        fail("ERR_PROTEST_NOT_IN_REVIEW",
             "A protest in %s has no outstanding evidence request."
             % protest["status"])
    set_fields(protest, status="UNDER_REVIEW", evidence_note=evidence_note,
               review_round=protest["review_round"] + 1)
    store.touch(protest)
    return object_response(store.serialize(protest))


def _reopen_accepted_filing(show):
    for filing in agg.filings_of_show(show["id"]):
        if filing["filing_status"] != "ACCEPTED":
            continue
        removed = agg.strip_unsupported_titles(show["id"])
        set_fields(
            filing,
            filing_status="PENDING",
            amendment_count=filing["amendment_count"] + 1,
            championship_points_total_filed=show["points_awarded_total"],
            title_records_count=max(0, filing["title_records_count"] - removed),
        )
        store.touch(filing)
        if show["status"] == "RESULTS_FILED":
            set_fields(show, status="COMPLETED")


def _apply_remedy(protest, resolution_code):
    entry = store.get("entries", protest["entry_id"])
    cls = store.get("classes", entry["class_id"])
    show = store.get("shows", protest["show_id"])
    vacated = entry["placement"]

    if resolution_code == "DISQUALIFY_ENTRY":
        if entry["entry_status"] in ("CHECKED_IN", "JUDGED"):
            set_fields(entry, entry_status="DISQUALIFIED")
    set_fields(entry, placement=None, points_awarded=0)
    store.touch(entry)

    if vacated is not None:
        for other in agg.entries_of_class(cls["id"]):
            if other["id"] == entry["id"]:
                continue
            if other["entry_status"] != "JUDGED":
                continue
            if other["placement"] is not None and other["placement"] > vacated:
                set_fields(other, placement=other["placement"] - 1)
    agg.rerun_award(cls)
    if resolution_code == "DISQUALIFY_ENTRY":
        agg.recompute_class_counts(cls)
    _reopen_accepted_filing(show)


@bp.post("/protests/<protest_id>/decide")
def decide_protest(protest_id):
    user_id, _role = authenticate(["SanctionOfficer"])
    protest = must_get("protests", protest_id)
    body = shape.json_body()
    decision = shape.string_field(body, "decision", enum=PROTEST_DECISIONS)
    resolution_code = shape.string_field(
        body, "resolution_code", required=False, default=None,
        enum=RESOLUTION_CODES,
    )
    if decision == "UPHOLD":
        if resolution_code not in UPHOLD_CODES:
            fail("ERR_INVALID_REQUEST",
                 "An upheld protest requires a resolution_code of "
                 "DISQUALIFY_ENTRY, VACATE_PLACEMENT or WARNING.")
    else:
        if resolution_code != "NO_ACTION":
            fail("ERR_INVALID_REQUEST",
                 "A dismissed protest requires a resolution_code of NO_ACTION.")

    show = store.get("shows", protest["show_id"])
    if show["approved_by_user_id"] is not None and show["approved_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_CONFLICT",
             "The officer who approved the show may not decide its protests.")
    if protest["status"] != "UNDER_REVIEW":
        fail("ERR_PROTEST_NOT_IN_REVIEW",
             "A protest in %s is not under review." % protest["status"])

    upheld = decision == "UPHOLD"
    set_fields(
        protest,
        status="UPHELD" if upheld else "DISMISSED",
        resolution_code=resolution_code,
        reviewed_by_user_id=user_id,
        decided_at=store.now(),
        deposit_refunded=upheld,
    )
    store.touch(protest)
    if upheld and resolution_code in REMEDY_CODES:
        _apply_remedy(protest, resolution_code)
    return object_response(store.serialize(protest))
