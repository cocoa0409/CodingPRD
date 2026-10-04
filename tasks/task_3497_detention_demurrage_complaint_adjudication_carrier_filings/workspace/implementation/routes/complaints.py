"""Complaint lifecycle: intake (frozen incentive-principle score), ombuds
rounds, adjudication, decision with reparations, appeal (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import store
from auth import require_roles, any_role
from clock import CLOCK
from envelope import ok_object, ok_list, paginate
from errors import (
    fail,
    ERR_CARRIER_NOT_FOUND,
    ERR_SHIPPER_NOT_FOUND,
    ERR_INVOICE_NOT_FOUND,
    ERR_COMPLAINT_NOT_FOUND,
    ERR_FORBIDDEN_RESOURCE_ACCESS,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_NOT_ACTIONABLE,
    ERR_COMPLAINT_FILING_WINDOW_EXPIRED,
    ERR_NOT_INVOICE_PARTY,
    ERR_RESPONDENT_NOT_INVOICE_CARRIER,
    ERR_EMPTY_SUBJECT_SET,
    ERR_COMPLAINT_NOT_DOCKETED,
    ERR_OMBUDS_ROUND_LIMIT_EXCEEDED,
    ERR_COMPLAINT_NOT_ADJUDICATING,
    ERR_APPEAL_NOT_ALLOWED,
    ERR_APPEAL_WINDOW_EXPIRED,
    ERR_ADJUDICATOR_CONFLICT,
)
from serialization import ser_complaint
from services import calc
from store import touch
from util import body, req_str, req_int, req_enum, is_int
from constants import COMPLAINT_FILING_WINDOW_DAYS, APPEAL_WINDOW_DAYS, OMBUDS_MAX_ROUNDS

bp = Blueprint("complaints", __name__)

ACTIONABLE_INVOICE_STATES = ("ISSUED", "DISPUTED", "PAID")


@bp.post("/fmc/complaints")
def file_complaint():
    uid, _role = require_roles("ShipperRep")
    b = body()
    # Rung 5: existence of body-referenced entities (and of the complaining
    # shipper, whose identity comes from the caller).
    if uid not in store.shippers:
        fail(ERR_SHIPPER_NOT_FOUND, "shipper account not found: %s" % uid)
    rcid = b.get("respondent_carrier_id")
    if isinstance(rcid, str) and rcid not in store.carriers:
        fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % rcid)
    sids = b.get("subject_invoice_ids")
    if isinstance(sids, list):
        for s in sids:
            if isinstance(s, str) and s not in store.invoices:
                fail(ERR_INVOICE_NOT_FOUND, "invoice not found: %s" % s)
    # Rung 6: scalar sanity.
    respondent_carrier_id = req_str(b, "respondent_carrier_id")
    reparations_claimed_cents = req_int(b, "reparations_claimed_cents", lo=1)
    if not isinstance(sids, list) or any(not isinstance(s, str) for s in sids):
        fail(ERR_INVALID_REQUEST,
             "subject_invoice_ids must be an array of invoice id strings")
    invoices = [store.invoices[s] for s in sids]
    # Rung 8: every subject invoice must be actionable.
    for inv in invoices:
        if inv["invoice_status"] not in ACTIONABLE_INVOICE_STATES:
            fail(ERR_INVOICE_NOT_ACTIONABLE,
                 "a VOIDED invoice leaves nothing to adjudicate")
    # Rung 9: 180-day filing window from the most recently issued subject invoice.
    now = CLOCK.now()
    if invoices:
        latest_issued = max(inv["issued_at"] for inv in invoices)
        if now > latest_issued + timedelta(days=COMPLAINT_FILING_WINDOW_DAYS):
            fail(ERR_COMPLAINT_FILING_WINDOW_EXPIRED,
                 "complaint filed more than 180 days after the latest subject "
                 "invoice's issued_at")
    # Rung 10: party and respondent consistency, per invoice in order.
    for inv in invoices:
        if inv["billed_party_shipper_id"] != uid:
            fail(ERR_NOT_INVOICE_PARTY,
                 "a subject invoice's billed party is not the complaining shipper")
        if inv["carrier_id"] != respondent_carrier_id:
            fail(ERR_RESPONDENT_NOT_INVOICE_CARRIER,
                 "a subject invoice was issued by a carrier other than the "
                 "respondent")
    # Rung 12: subject-set non-emptiness.
    if not sids:
        fail(ERR_EMPTY_SUBJECT_SET, "subject_invoice_ids must be a non-empty array")

    score = calc.incentive_principle_score(
        invoices, list(store.congestion_reports.values())
    )
    rec = store.base_record()
    rec.update(
        shipper_id=uid,
        respondent_carrier_id=respondent_carrier_id,
        subject_invoice_ids=list(sids),
        reparations_claimed_cents=reparations_claimed_cents,
        incentive_principle_score=score,
        complaint_status="DOCKETED",
        ombuds_officer_id=None,
        ombuds_rounds=0,
        informal_settlement_cents=None,
        presiding_judge_id=None,
        reparation_method=None,
        reparations_awarded_cents=0,
        decided_at=None,
        appeal_deadline=None,
    )
    store.complaints[rec["id"]] = rec
    return ok_object(ser_complaint(rec), 201)


@bp.get("/fmc/complaints")
def list_complaints():
    any_role()
    shipper_id = request.args.get("shipper_id")
    respondent = request.args.get("respondent_carrier_id")
    subject = request.args.get("subject_invoice_ids")
    recs = list(store.complaints.values())
    if shipper_id is not None:
        recs = [c for c in recs if c["shipper_id"] == shipper_id]
    if respondent is not None:
        recs = [c for c in recs if c["respondent_carrier_id"] == respondent]
    if subject is not None:
        recs = [c for c in recs if subject in c["subject_invoice_ids"]]
    page, limit, offset, total = paginate(recs)
    return ok_list([ser_complaint(c) for c in page], limit, offset, total)


@bp.get("/fmc/complaints/<complaintId>")
def get_complaint(complaintId):
    any_role()
    c = store.complaints.get(complaintId)
    if c is None:
        fail(ERR_COMPLAINT_NOT_FOUND, "complaint not found: %s" % complaintId)
    return ok_object(ser_complaint(c))


@bp.post("/fmc/complaints/<complaintId>/refer-ombuds")
def refer_ombuds(complaintId):
    require_roles("CommissionDocket")
    c = store.complaints.get(complaintId)
    if c is None:
        fail(ERR_COMPLAINT_NOT_FOUND, "complaint not found: %s" % complaintId)
    b = body()
    ombuds_officer_id = req_str(b, "ombuds_officer_id")
    if c["complaint_status"] != "DOCKETED":
        fail(ERR_COMPLAINT_NOT_DOCKETED,
             "refer-ombuds requires complaint status DOCKETED")
    if c["ombuds_rounds"] >= OMBUDS_MAX_ROUNDS:
        fail(ERR_OMBUDS_ROUND_LIMIT_EXCEEDED,
             "a further referral requires ombuds_rounds < 2")
    c["complaint_status"] = "OMBUDS"
    c["ombuds_officer_id"] = ombuds_officer_id
    touch(c)
    return ok_object(ser_complaint(c))


@bp.post("/fmc/complaints/<complaintId>/close-ombuds")
def close_ombuds(complaintId):
    uid, _role = require_roles("OmbudsOfficer")
    c = store.complaints.get(complaintId)
    if c is None:
        fail(ERR_COMPLAINT_NOT_FOUND, "complaint not found: %s" % complaintId)
    if uid != c["ombuds_officer_id"]:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "only the assigned ombuds officer may close the round")
    b = body()
    outcome = req_enum(b, "outcome", ("SETTLED", "FAILED"))
    settlement = b.get("settlement_amount_cents")
    if outcome == "SETTLED" and (settlement is None or not is_int(settlement)):
        fail(ERR_INVALID_REQUEST,
             "closing with outcome SETTLED requires a settlement_amount_cents")
    if c["complaint_status"] != "OMBUDS":
        fail(ERR_INVALID_REQUEST,
             "the complaint is not in an open ombuds round")
    if outcome == "SETTLED":
        c["complaint_status"] = "RESOLVED_INFORMAL"
        c["informal_settlement_cents"] = settlement
        shipper = store.shippers[c["shipper_id"]]
        shipper["total_recovery_cents"] += settlement
        touch(shipper)
    else:
        c["complaint_status"] = "DOCKETED"
        c["ombuds_rounds"] += 1
    touch(c)
    return ok_object(ser_complaint(c))


@bp.post("/fmc/complaints/<complaintId>/open-adjudication")
def open_adjudication(complaintId):
    uid, _role = require_roles("AdministrativeLawJudge")
    c = store.complaints.get(complaintId)
    if c is None:
        fail(ERR_COMPLAINT_NOT_FOUND, "complaint not found: %s" % complaintId)
    if c["complaint_status"] != "DOCKETED":
        fail(ERR_COMPLAINT_NOT_DOCKETED,
             "open-adjudication requires complaint status DOCKETED")
    if c["ombuds_officer_id"] is not None and uid == c["ombuds_officer_id"]:
        fail(ERR_ADJUDICATOR_CONFLICT,
             "the judge opening adjudication served as the most recent ombuds "
             "officer on this complaint")
    c["complaint_status"] = "ADJUDICATION_OPEN"
    c["presiding_judge_id"] = uid
    touch(c)
    return ok_object(ser_complaint(c))


@bp.post("/fmc/complaints/<complaintId>/decide")
def decide(complaintId):
    uid, _role = require_roles("AdministrativeLawJudge")
    c = store.complaints.get(complaintId)
    if c is None:
        fail(ERR_COMPLAINT_NOT_FOUND, "complaint not found: %s" % complaintId)
    if uid != c["presiding_judge_id"]:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "the decision belongs to the presiding judge alone")
    if c["complaint_status"] != "ADJUDICATION_OPEN":
        fail(ERR_COMPLAINT_NOT_ADJUDICATING,
             "decide requires complaint status ADJUDICATION_OPEN")
    invoices = [store.invoices[s] for s in c["subject_invoice_ids"]]
    method, award = calc.reparation_award(
        c["incentive_principle_score"], c["reparations_claimed_cents"], invoices
    )
    now = CLOCK.now()
    c["reparation_method"] = method
    c["reparations_awarded_cents"] = award
    c["decided_at"] = now
    c["appeal_deadline"] = now + timedelta(days=APPEAL_WINDOW_DAYS)
    c["complaint_status"] = "ADJUDICATION_DECIDED"
    shipper = store.shippers[c["shipper_id"]]
    shipper["total_recovery_cents"] += award
    touch(shipper)
    touch(c)
    return ok_object(ser_complaint(c))


@bp.post("/fmc/complaints/<complaintId>/appeal")
def appeal(complaintId):
    uid, role = require_roles("ShipperRep", "CarrierRep")
    c = store.complaints.get(complaintId)
    if c is None:
        fail(ERR_COMPLAINT_NOT_FOUND, "complaint not found: %s" % complaintId)
    if role == "ShipperRep":
        allowed = uid == c["shipper_id"]
    else:
        allowed = uid == c["respondent_carrier_id"]
    if not allowed:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "only the complainant shipper or the respondent carrier may appeal")
    if c["complaint_status"] != "ADJUDICATION_DECIDED":
        fail(ERR_APPEAL_NOT_ALLOWED,
             "appeal requires complaint status ADJUDICATION_DECIDED")
    if CLOCK.now() > c["appeal_deadline"]:
        fail(ERR_APPEAL_WINDOW_EXPIRED, "the appeal window has expired")
    c["complaint_status"] = "APPEALED"
    touch(c)
    return ok_object(ser_complaint(c))


@bp.post("/fmc/complaints/<complaintId>/resolve-appeal")
def resolve_appeal(complaintId):
    require_roles("CommissionAdmin")
    c = store.complaints.get(complaintId)
    if c is None:
        fail(ERR_COMPLAINT_NOT_FOUND, "complaint not found: %s" % complaintId)
    b = body()
    decision = req_enum(b, "decision", ("AFFIRM", "REVERSE"))
    if c["complaint_status"] != "APPEALED":
        fail(ERR_APPEAL_NOT_ALLOWED,
             "resolve-appeal requires complaint status APPEALED")
    if decision == "AFFIRM":
        c["complaint_status"] = "FINAL"
    else:
        shipper = store.shippers[c["shipper_id"]]
        shipper["total_recovery_cents"] -= c["reparations_awarded_cents"]
        touch(shipper)
        c["reparations_awarded_cents"] = 0
        c["complaint_status"] = "REVERSED"
    touch(c)
    return ok_object(ser_complaint(c))
