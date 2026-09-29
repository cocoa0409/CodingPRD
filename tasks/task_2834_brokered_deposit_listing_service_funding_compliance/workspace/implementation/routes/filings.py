import re

from flask import Blueprint

import calc
import db
import middleware as mw
import response
from errors import ApiError
from routes.institutions import find_institution

bp = Blueprint("filings", __name__)

PERIOD_RE = re.compile(r"^\d{4}Q[1-4]$")
REPORTED_FIELDS = ("rc_e_brokered_reported_cents", "rc_o_listing_reported_cents",
                   "rc_e_core_reported_cents")
WORKFLOW_ACTIONS = ("PREPARE", "ATTEST", "FILE", "OPEN_EXAM_REVIEW",
                    "REQUIRE_AMENDMENT", "ACCEPT")
READ_ROLES = ("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer",
              "TreasuryController", "Examiner")


def find_filing(filing_id):
    record = db.call_report_filings.get(filing_id)
    if record is None:
        raise ApiError("ERR_FILING_NOT_FOUND")
    return record


@bp.post("/institutions/<institution_id>/call-report-filings")
def create_filing(institution_id):
    mw.auth("SystemAdmin", "FundingDeskOfficer")
    find_institution(institution_id)
    data = mw.body()
    period = mw.req_str(data, "report_period")
    if not PERIOD_RE.match(period):
        raise mw.bad("report_period must be four digits followed by Q and 1-4.")
    reported = {field: mw.req_int(data, field, minimum=0)
                for field in REPORTED_FIELDS}

    for existing in db.call_report_filings.values():
        if (existing["institution_id"] == institution_id
                and existing["report_period"] == period):
            raise ApiError("ERR_DUPLICATE_KEY")

    record = {
        "institution_id": institution_id,
        "report_period": period,
        "status": "DRAFT",
        "computed_brokered_cents": 0,
        "computed_listing_cents": 0,
        "computed_core_cents": 0,
        "variance_cents": 0,
        "variance_bps": 0,
        "accuracy_status": "NOT_ASSESSED",
        "amendment_round": 0,
        "examiner_finding_note": None,
        "prepared_by_user_id": None,
        "attested_by_user_id": None,
    }
    record.update(reported)
    db.stamp_new(record)
    db.call_report_filings[record["id"]] = record
    return response.created(db.public(record))


@bp.get("/institutions/<institution_id>/call-report-filings")
def list_filings(institution_id):
    mw.auth(*READ_ROLES)
    find_institution(institution_id)
    limit, offset = mw.page()
    rows = [r for r in db.call_report_filings.values()
            if r["institution_id"] == institution_id]
    for field in ("status", "report_period"):
        wanted = mw.q(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows.sort(key=lambda r: (r["report_period"], r["created_at"], r["_seq"]))
    return response.listing(db.public_list(rows), limit, offset)


@bp.get("/call-report-filings/<filing_id>")
def read_filing(filing_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(find_filing(filing_id)))


FILING_TRANSITIONS = {
    "PREPARE": (("DRAFT", "AMENDMENT_REQUIRED"), "PREPARED"),
    "ATTEST": (("PREPARED",), "ATTESTED"),
    "FILE": (("ATTESTED",), "FILED"),
    "OPEN_EXAM_REVIEW": (("FILED",), "UNDER_EXAMINER_REVIEW"),
    "REQUIRE_AMENDMENT": (("UNDER_EXAMINER_REVIEW",), "AMENDMENT_REQUIRED"),
    "ACCEPT": (("UNDER_EXAMINER_REVIEW",), "ACCEPTED"),
}


@bp.post("/call-report-filings/<filing_id>/workflow-actions")
def workflow_actions(filing_id):
    user_id, _role = mw.auth("SystemAdmin", "FundingDeskOfficer",
                             "ComplianceReviewer", "Examiner")
    filing = find_filing(filing_id)
    data = mw.body()
    action = mw.req_enum(data, "action", WORKFLOW_ACTIONS)

    origins, target = FILING_TRANSITIONS[action]
    amending = action == "PREPARE" and filing["status"] == "AMENDMENT_REQUIRED"
    revised = {}
    if amending:
        for field in REPORTED_FIELDS:
            if field in data and data[field] is not None:
                revised[field] = mw.req_int(data, field, minimum=0)

    if filing["status"] not in origins:
        raise ApiError("ERR_FILING_STATE_INVALID")
    if action == "REQUIRE_AMENDMENT" and filing["amendment_round"] >= 2:
        raise ApiError("ERR_REVIEW_ROUND_LIMIT")
    if action == "ATTEST":
        if user_id == filing["prepared_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if filing["accuracy_status"] == "VARIANCE_MATERIAL":
            raise ApiError("ERR_FILING_VARIANCE_MATERIAL")

    institution = db.institutions.get(filing["institution_id"])
    filing["status"] = target
    if action == "PREPARE":
        filing.update(revised)
        calc.call_report_variance(filing, institution)
        filing["prepared_by_user_id"] = user_id
        filing["attested_by_user_id"] = None
    elif action == "ATTEST":
        filing["attested_by_user_id"] = user_id
    elif action == "REQUIRE_AMENDMENT":
        filing["amendment_round"] += 1
        filing["examiner_finding_note"] = mw.opt_str(data, "examiner_finding_note")
    elif action == "ACCEPT":
        filing["examiner_finding_note"] = mw.opt_str(data, "examiner_finding_note")
    db.bump(filing)
    return response.ok(db.public(filing))
