"""Marketing material review, the cooling buffer, and custody account reads."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import respond
import schema
import serialize
import store
from authz import auth, is_partner, scope_partner_id, scope_rows, sod
from errors import fail

bp = Blueprint("marketing", __name__)
READ_ROLES = ("ProgramOfficer", "ComplianceOfficer", "RiskCommittee", "InternalAudit",
              "FintechPartner")
COOLING_DAYS = 3


def _posture_gate(partner):
    if partner["oversight_posture"] not in ("OPEN", "HEIGHTENED"):
        fail("ERR_POSTURE_BLOCKS_MARKETING", "posture blocks marketing")


@bp.post("/oversight/marketing-reviews")
@auth("FintechPartner", "ProgramOfficer")
def create_marketing_review():
    data = schema.body()
    partner = None
    agreement = None
    if data.get("partner_id") is not None:                           # rank 10
        partner = store.must("partners", data["partner_id"])
    if data.get("agreement_id") is not None:
        agreement = store.must("agreements", data["agreement_id"])
    if partner is not None:                                          # rank 12
        scope_partner_id(partner["id"])
    schema.req_str(data, "partner_id")                               # rank 18
    schema.req_str(data, "agreement_id")
    material_type = schema.req_enum(data, "material_type", schema.MATERIAL_TYPES)
    channel = schema.req_enum(data, "placement_channel", schema.PLACEMENT_CHANNELS)
    elements = schema.req_enum_array(data, "disclosure_elements",
                                     schema.DISCLOSURE_ELEMENTS, non_empty=False,
                                     default=[])
    apr = schema.req_bool(data, "apr_disclosed", False)
    fdic = schema.req_bool(data, "fdic_signage_correct", False)
    effective_from = schema.req_dt(data, "effective_from")
    effective_until = schema.req_dt(data, "effective_until")
    if agreement["partner_id"] != partner["id"]:                     # rank 22
        fail("ERR_AGREEMENT_PARTNER_MISMATCH", "agreement belongs to another partner")
    if partner["status"] in ("DILIGENCE_FAILED", "TERMINATED"):       # rank 32
        fail("ERR_PARTNER_TERMINAL", "partner is terminal")
    _posture_gate(partner)                                           # rank 50
    if effective_until < effective_from:                             # rank 60
        fail("ERR_INVALID_INTERVAL", "effective_until precedes effective_from")
    record = {
        "partner_id": partner["id"],
        "agreement_id": agreement["id"],
        "material_type": material_type,
        "placement_channel": channel,
        "disclosure_elements": elements,
        "apr_disclosed": apr,
        "fdic_signage_correct": fdic,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "status": "SUBMITTED",
        "review_round": 1,
        "change_requests": [],
        "risk_flags": [],
        "created_by_user_id": g.user_id,
        "decided_by_user_id": None,
    }
    record["risk_flags"] = calc.marketing_risk_flags(record, partner)
    store.insert("marketing_reviews", record)
    return respond.ok(serialize.marketing_review(record), 201)


@bp.get("/oversight/marketing-reviews")
@auth(*READ_ROLES)
def list_marketing_reviews():
    rows = store.rows("marketing_reviews")
    partner_id = schema.filter_str("partner_id")
    if partner_id is not None:
        rows = [r for r in rows if r["partner_id"] == partner_id]
    agreement_id = schema.filter_str("agreement_id")
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    material_type = schema.filter_enum("material_type", schema.MATERIAL_TYPES)
    if material_type is not None:
        rows = [r for r in rows if r["material_type"] == material_type]
    channel = schema.filter_enum("placement_channel", schema.PLACEMENT_CHANNELS)
    if channel is not None:
        rows = [r for r in rows if r["placement_channel"] == channel]
    status = schema.filter_enum("status", schema.MARKETING_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond.paginate(scope_rows(rows), serialize.marketing_review)


@bp.get("/oversight/marketing-reviews/<mid>")
@auth(*READ_ROLES)
def read_marketing_review(mid):
    review = store.must("marketing_reviews", mid)
    scope_partner_id(review["partner_id"])
    return respond.ok(serialize.marketing_review(review))


@bp.post("/oversight/marketing-reviews/<mid>/decide")
@auth("ComplianceOfficer")
def decide_marketing_review(mid):
    review = store.must("marketing_reviews", mid)                    # rank 8
    sod(review["created_by_user_id"])                                # rank 14
    data = schema.body()
    decision = schema.req_enum(data, "decision",                     # rank 18
                               ["APPROVE", "CHANGES_REQUESTED", "REJECT"])
    schema.opt_str(data, "decision_note")
    requests = None
    if decision == "CHANGES_REQUESTED":
        requests = schema.req_str_array(data, "change_requests", non_empty=True)
    if review["status"] != "SUBMITTED":                              # rank 34
        fail("ERR_MARKETING_NOT_DECIDABLE", "filing is not SUBMITTED")
    partner = store.get("partners", review["partner_id"])
    review["risk_flags"] = calc.marketing_risk_flags(review, partner)
    if decision == "APPROVE":
        _posture_gate(partner)                                       # rank 50
        if review["risk_flags"]:                                     # rank 54
            fail("ERR_DISCLOSURE_INCOMPLETE", "risk flags must be empty to approve")
        buffer_span = timedelta(days=COOLING_DAYS)
        for other in store.rows("marketing_reviews"):                # rank 63
            if other["id"] == review["id"] or other["status"] != "APPROVED":
                continue
            if other["partner_id"] != review["partner_id"] or \
                    other["material_type"] != review["material_type"] or \
                    other["placement_channel"] != review["placement_channel"]:
                continue
            if review["effective_from"] <= other["effective_until"] + buffer_span and \
                    other["effective_from"] <= review["effective_until"] + buffer_span:
                fail("ERR_DISCLOSURE_WINDOW_CONFLICT", "approved window conflict")
    review["decided_by_user_id"] = g.user_id
    if decision == "APPROVE":
        review["status"] = "APPROVED"
    elif decision == "REJECT":
        review["status"] = "REJECTED"
    else:
        review["status"] = "CHANGES_REQUESTED"
        review["change_requests"] = requests
    store.touch(review)
    return respond.ok(serialize.marketing_review(review))


@bp.post("/oversight/marketing-reviews/<mid>/resubmit")
@auth("FintechPartner")
def resubmit_marketing_review(mid):
    review = store.must("marketing_reviews", mid)                    # rank 8
    scope_partner_id(review["partner_id"])                           # rank 12
    data = schema.body()
    elements = schema.req_enum_array(data, "disclosure_elements",    # rank 18
                                     schema.DISCLOSURE_ELEMENTS, non_empty=False)
    apr = schema.req_bool(data, "apr_disclosed")
    fdic = schema.req_bool(data, "fdic_signage_correct")
    effective_from = schema.req_dt(data, "effective_from")
    effective_until = schema.req_dt(data, "effective_until")
    if review["status"] != "CHANGES_REQUESTED":                      # rank 34
        fail("ERR_MARKETING_NOT_CHANGES_REQUESTED", "filing is not CHANGES_REQUESTED")
    partner = store.get("partners", review["partner_id"])
    _posture_gate(partner)                                           # rank 50
    if effective_until < effective_from:                             # rank 60
        fail("ERR_INVALID_INTERVAL", "effective_until precedes effective_from")
    review["disclosure_elements"] = elements
    review["apr_disclosed"] = apr
    review["fdic_signage_correct"] = fdic
    review["effective_from"] = effective_from
    review["effective_until"] = effective_until
    review["status"] = "SUBMITTED"
    review["review_round"] = int(review["review_round"]) + 1
    review["change_requests"] = []
    review["created_by_user_id"] = g.user_id
    review["risk_flags"] = calc.marketing_risk_flags(review, partner)
    store.touch(review)
    return respond.ok(serialize.marketing_review(review))


@bp.get("/oversight/custody-accounts")
@auth(*READ_ROLES)
def list_custody_accounts():
    rows = store.rows("custody_accounts")
    partner_id = schema.filter_str("partner_id")
    if partner_id is not None:
        rows = [r for r in rows if r["partner_id"] == partner_id]
    account_type = schema.filter_enum("account_type", schema.ACCOUNT_TYPES)
    if account_type is not None:
        rows = [r for r in rows if r["account_type"] == account_type]
    status = schema.filter_enum("status", schema.ACCOUNT_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond.paginate(scope_rows(rows), serialize.custody_account)


@bp.get("/oversight/custody-accounts/<cid>")
@auth(*READ_ROLES)
def read_custody_account(cid):
    account = store.must("custody_accounts", cid)
    scope_partner_id(account["partner_id"])
    return respond.ok(serialize.custody_account(account))
