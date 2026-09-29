"""UCC fixture filings and the title chain (PRD §3.9)."""
from flask import Blueprint

from core import (
    ApiError, clock, fmt_date, invalid, parse_date, sorted_rows, stamp_new, store,
    touch,
)
from guards import lookup
from serialize import ucc_filing_view
from web import (
    apply_filters, authenticate, created, filters, ok, ok_list, paginate,
    pagination, validate_body,
)

bp = Blueprint("ucc_routes", __name__)

FILING_TYPES = ("FIXTURE_FILING", "AMENDMENT")
FILING_STATUSES = ("FILED", "SUBORDINATION_REQUESTED", "SUBORDINATED",
                   "TERMINATION_REQUESTED", "TERMINATED")
SUBORDINATION_CASE_STATUSES = ("INITIATED", "CREDIT_REVIEW", "CREDIT_APPROVED")

FILING_SPECS = [
    {"name": "agreement_id", "kind": "id", "required": True},
    {"name": "filing_number", "kind": "str", "required": True, "minlen": 1,
     "maxlen": 32, "nonblank": True},
    {"name": "jurisdiction_code", "kind": "str", "required": True, "minlen": 1,
     "maxlen": 24, "nonblank": True},
    {"name": "filing_type", "kind": "enum", "required": True, "values": FILING_TYPES},
    {"name": "filed_date", "kind": "date", "required": True},
]


@bp.post("/servicing/ucc-filings")
def create_filing():
    authenticate(("TitleAgent", "PortfolioAdmin"))
    body = validate_body(FILING_SPECS)
    filed = parse_date(body["filed_date"])
    if filed > clock.today():
        raise invalid("filed_date may not fall after the current clock date.")
    ag = lookup("agreements", body["agreement_id"])
    for existing in store.ucc_filings.values():
        if existing["filing_number"] == body["filing_number"]:
            raise ApiError("ERR_DUPLICATE_FILING_NUMBER",
                           "That filing_number is already recorded.")
    row = {
        "agreement_id": ag["id"],
        "requested_by_transfer_case_id": None,
        "filing_number": body["filing_number"],
        "jurisdiction_code": body["jurisdiction_code"],
        "filing_type": body["filing_type"],
        "filed_date": fmt_date(filed),
        "terminated_date": None,
        "status": "FILED",
        "_subordination_requested_by": None,
    }
    stamp_new(row)
    store.ucc_filings[row["id"]] = row
    return created(ucc_filing_view(row))


@bp.get("/servicing/ucc-filings/<ucc_filing_id>")
def get_filing(ucc_filing_id):
    authenticate(("TitleAgent", "ServicingAgent", "PortfolioAdmin"))
    return ok(ucc_filing_view(lookup("ucc_filings", ucc_filing_id)))


@bp.get("/servicing/ucc-filings")
def list_filings():
    authenticate(("TitleAgent", "ServicingAgent", "PortfolioAdmin"))
    limit, offset = pagination()
    flt = filters([
        ("agreement_id", "str", None),
        ("requested_by_transfer_case_id", "str", None),
        ("jurisdiction_code", "str", None),
        ("filing_type", "enum", FILING_TYPES),
        ("status", "enum", FILING_STATUSES),
    ])
    rows = apply_filters(sorted_rows(list(store.ucc_filings.values())), flt)
    page, total = paginate(rows, limit, offset)
    return ok_list([ucc_filing_view(r) for r in page], limit, offset, total)


@bp.post("/servicing/ucc-filings/<ucc_filing_id>/request-subordination")
def request_subordination(ucc_filing_id):
    user_id, role = authenticate(("TitleAgent", "ServicingAgent"))
    validate_body([])
    filing = lookup("ucc_filings", ucc_filing_id)
    if filing["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a FILED filing may have subordination requested.")
    cases = [c for c in store.transfer_cases.values()
             if c["agreement_id"] == filing["agreement_id"]
             and c["status"] in SUBORDINATION_CASE_STATUSES]
    if not cases:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "No open transfer case on that agreement needs a "
                       "subordination.")
    cases.sort(key=lambda c: (c["created_at"], c["_seq"]))
    filing["status"] = "SUBORDINATION_REQUESTED"
    filing["requested_by_transfer_case_id"] = cases[0]["id"]
    filing["_subordination_requested_by"] = user_id
    touch(filing)
    return ok(ucc_filing_view(filing))


@bp.post("/servicing/ucc-filings/<ucc_filing_id>/record-subordination")
def record_subordination(ucc_filing_id):
    user_id, role = authenticate(("TitleAgent",))
    validate_body([])
    filing = lookup("ucc_filings", ucc_filing_id)
    # rung 7 — the same user may not both ask for and record a subordination
    if (filing.get("_subordination_requested_by") is not None
            and filing["_subordination_requested_by"] == user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The requesting user may not record the subordination.")
    if filing["status"] != "SUBORDINATION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBORDINATION_REQUESTED filing may be recorded as "
                       "subordinated.")
    filing["status"] = "SUBORDINATED"
    touch(filing)
    return ok(ucc_filing_view(filing))


@bp.post("/servicing/ucc-filings/<ucc_filing_id>/request-termination")
def request_termination(ucc_filing_id):
    authenticate(("TitleAgent", "ServicingAgent"))
    validate_body([])
    filing = lookup("ucc_filings", ucc_filing_id)
    if filing["status"] not in ("FILED", "SUBORDINATED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a FILED or SUBORDINATED filing may have termination "
                       "requested.")
    filing["status"] = "TERMINATION_REQUESTED"
    touch(filing)
    return ok(ucc_filing_view(filing))


@bp.post("/servicing/ucc-filings/<ucc_filing_id>/terminate")
def terminate_filing(ucc_filing_id):
    authenticate(("TitleAgent",))
    validate_body([])
    filing = lookup("ucc_filings", ucc_filing_id)
    if filing["status"] != "TERMINATION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a TERMINATION_REQUESTED filing may be terminated.")
    for case in store.transfer_cases.values():
        if (case["agreement_id"] == filing["agreement_id"]
                and case["status"] == "TITLE_CLEARED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A transfer case cleared on this filing is waiting to "
                           "close.")
    filing["status"] = "TERMINATED"
    filing["terminated_date"] = fmt_date(clock.today())
    touch(filing)
    return ok(ucc_filing_view(filing))
