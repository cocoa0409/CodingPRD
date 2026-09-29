"""LicenseAgreement — approval rights, term and the expiry cascade (PRD §3.2)."""

from flask import Blueprint, request

from db import db, new_row, now_iso, public, today, touch
from errors import ApiError
from middleware import EP, LM, LR, VOM, caller_id, roles
from response import list_response, object_response
from services import derive
from services.validate import Body

bp = Blueprint("agreements", __name__)

APPROVAL_SCOPES = ("CREATIVE_EXECUTION", "MERCHANDISE", "MARKETING")
OPEN_SUBMISSION_STATUSES = ("SUBMITTED", "IN_REVIEW", "CHANGES_REQUESTED")


@bp.post("/license-agreements")
@roles(LM)
def register_agreement():
    body = Body(require_body=True)
    licensor_name = body.string("licensor_name", min_len=1, max_len=120)
    ip_title = body.string("ip_title", min_len=1, max_len=120)
    rep_user_id = body.string("licensor_rep_user_id", min_len=1, max_len=64)
    royalty_rate_bps = body.integer("royalty_rate_bps", minimum=0, maximum=10000)
    merch_rate_bps = body.integer("merch_royalty_rate_bps", minimum=0, maximum=10000)
    minimum_guarantee = body.integer("minimum_guarantee_cents", minimum=0)
    scopes = body.enum_array("approval_scopes", APPROVAL_SCOPES, allow_empty=False)
    territory = body.string_array("territory_city_codes", allow_empty=False,
                                  min_len=3, max_len=3, pattern=r"^[A-Z]{3}$")
    term_start, term_start_raw = body.date_field("term_start_date")
    term_end, term_end_raw = body.date_field("term_end_date")

    if term_end <= term_start:
        raise ApiError("ERR_INVALID_WINDOW")

    row = new_row()
    row.update({
        "licensor_name": licensor_name,
        "ip_title": ip_title,
        "licensor_rep_user_id": rep_user_id,
        "royalty_rate_bps": royalty_rate_bps,
        "merch_royalty_rate_bps": merch_rate_bps,
        "minimum_guarantee_cents": minimum_guarantee,
        "approval_scopes": scopes,
        "territory_city_codes": territory,
        "term_start_date": term_start_raw,
        "term_end_date": term_end_raw,
        "open_submission_count": 0,
        "approved_submission_count": 0,
        "status": "DRAFT",
        "_term_start": term_start,
        "_term_end": term_end,
    })
    db.agreements[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/license-agreements/<agreement_id>")
@roles(LM, LR, EP, VOM)
def read_agreement(agreement_id):
    return object_response(public(derive.agreement(agreement_id)))


@bp.get("/license-agreements")
@roles(LM, LR, EP)
def list_agreements():
    rows = list(db.agreements.values())
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    city_code = request.args.get("city_code")
    if city_code:
        rows = [r for r in rows if city_code in r["territory_city_codes"]]
    return list_response(rows)


@bp.post("/license-agreements/<agreement_id>/activate")
@roles(LM)
def activate_agreement(agreement_id):
    agreement = derive.agreement(agreement_id)
    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_AGREEMENT_INVALID_STATE")
    # admissible only while the clock date is on or before term_end_date
    if today() > agreement["_term_end"]:
        raise ApiError("ERR_AGREEMENT_INVALID_STATE")
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return object_response(public(agreement))


@bp.post("/license-agreements/<agreement_id>/expire")
@roles(LM)
def expire_agreement(agreement_id):
    agreement = derive.agreement(agreement_id)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_INVALID_STATE")
    # rung 12 — the term must genuinely have elapsed
    if today() <= agreement["_term_end"]:
        raise ApiError("ERR_TERM_NOT_ENDED")

    stamp = now_iso()
    decider = caller_id()
    # hop 1 — every still-open submission is rejected
    for submission in derive.submissions_of_agreement(agreement):
        if submission["status"] in OPEN_SUBMISSION_STATUSES:
            submission["status"] = "REJECTED"
            submission["decision_note"] = "AGREEMENT_EXPIRED"
            submission["decided_at"] = stamp
            submission["decided_by_user_id"] = decider
            touch(submission)
    agreement["open_submission_count"] = 0
    agreement["status"] = "EXPIRED"
    touch(agreement)

    # hop 2 — runs that leaned on those approvals lose their clearance
    for run_row in derive.runs_of_agreement(agreement):
        if run_row["clearance_status"] == "CLEARED":
            run_row["clearance_status"] = "UNCLEARED"
            touch(run_row)
    return object_response(public(agreement))
