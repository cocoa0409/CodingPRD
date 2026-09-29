"""Registry filings: reporting results and recording earned titles."""
from flask import Blueprint

import agg
from auth import authenticate, must_get
from common import ALL_ROLES
from envelope import list_response, object_response
from errors import fail
import shape
import store
from store import set_fields

bp = Blueprint("filings", __name__)

FILING_DECISIONS = ["ACCEPT", "REJECT"]
OPEN_PROTESTS = ("FILED", "UNDER_REVIEW", "EVIDENCE_REQUESTED")


def _has_open_protest(show_id):
    for protest in agg.protests_of_show(show_id):
        if protest["status"] in OPEN_PROTESTS:
            return True
    return False


@bp.post("/registry-filings")
def create_filing():
    authenticate(["ShowSecretary"])
    body = shape.json_body()
    show_id = shape.string_field(body, "show_id")
    show = must_get("shows", show_id)

    if show["status"] != "COMPLETED":
        fail("ERR_INVALID_STATE",
             "Results may only be filed for a COMPLETED show, not a %s one."
             % show["status"])
    for filing in agg.filings_of_show(show_id):
        if filing["filing_status"] in ("PENDING", "ACCEPTED"):
            fail("ERR_FILING_ALREADY_OPEN",
                 "The show already holds a %s filing." % filing["filing_status"])
    for cls in agg.classes_of_show(show_id):
        if cls["status"] not in ("COMPLETED", "ABANDONED"):
            fail("ERR_CLASSES_NOT_COMPLETE",
                 "Class %s is still %s." % (cls["class_code"], cls["status"]))
    if _has_open_protest(show_id):
        fail("ERR_OPEN_PROTEST_BLOCKS_FILING",
             "An open protest blocks the filing.")

    rec = store.insert("filings", {
        "show_id": show_id,
        "filing_status": "PENDING",
        "title_records_count": 0,
        "championship_points_total_filed": show["points_awarded_total"],
        "filed_at": store.now(),
        "adjudicated_at": None,
        "reject_reason": None,
        "amendment_count": 0,
    })
    return object_response(store.serialize(rec), 201)


@bp.get("/registry-filings/<filing_id>")
def read_filing(filing_id):
    authenticate(ALL_ROLES)
    return object_response(store.serialize(must_get("filings", filing_id)))


@bp.get("/shows/<show_id>/registry-filings")
def list_filings_of_show(show_id):
    authenticate(ALL_ROLES)
    must_get("shows", show_id)
    limit, offset = shape.pagination()
    rows = [f for f in store.rows("filings") if f["show_id"] == show_id]
    rows = shape.apply_filters(rows, {"filing_status": "filing_status"})
    items, total = shape.paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/registry-filings/<filing_id>/adjudicate")
def adjudicate_filing(filing_id):
    authenticate(["RegistryOfficer"])
    filing = must_get("filings", filing_id)
    body = shape.json_body()
    decision = shape.string_field(body, "decision", enum=FILING_DECISIONS)
    reject_reason = shape.string_field(body, "reject_reason", required=False,
                                      default=None)
    if decision == "REJECT" and reject_reason is None:
        fail("ERR_INVALID_REQUEST", "A REJECT decision requires a reject_reason.")

    if filing["filing_status"] != "PENDING":
        fail("ERR_INVALID_STATE",
             "A %s filing may not be adjudicated." % filing["filing_status"])
    show = store.get("shows", filing["show_id"])

    if decision == "REJECT":
        set_fields(
            filing,
            filing_status="REJECTED_INCOMPLETE",
            adjudicated_at=store.now(),
            reject_reason=reject_reason,
        )
        store.touch(filing)
        return object_response(store.serialize(filing))

    if show["status"] != "COMPLETED":
        fail("ERR_INVALID_STATE",
             "A filing may only be accepted while the show is COMPLETED.")
    if _has_open_protest(show["id"]):
        fail("ERR_OPEN_PROTEST_BLOCKS_FILING",
             "An open protest blocks acceptance of the filing.")

    recorded = agg.record_titles(show["id"])
    set_fields(
        filing,
        filing_status="ACCEPTED",
        adjudicated_at=store.now(),
        championship_points_total_filed=show["points_awarded_total"],
        title_records_count=recorded,
    )
    store.touch(filing)
    set_fields(show, status="RESULTS_FILED")
    return object_response(store.serialize(filing))
