from flask import Blueprint

from db import store, new_entity, touch, parse_date
from errors import ApiError, bad_request, not_found, invalid_state
from middleware import auth, body, need, need_date, is_int
from response import ok
from serialize import payment_json
import services as svc

bp = Blueprint("stipends", __name__)

PAYMENT_STATES = {"SCHEDULED", "APPROVED", "PAID", "FORFEITED", "CLAWED_BACK"}


def get_payment_or_404(payment_id):
    p = store.payments.get(payment_id)
    if p is None:
        not_found("StipendPayment not found")
    return p


@bp.route("/corps/members/<member_id>/stipend-payments", methods=["POST"])
def create_payment(member_id):
    uid, role = auth(["StipendAdministrator"])
    data = body()
    period_start = need_date(data, "period_start")
    period_end = need_date(data, "period_end")
    if parse_date(period_end) < parse_date(period_start):
        bad_request("period_end must be on or after period_start")
    m = store.members.get(member_id)
    if m is None:
        not_found("CorpsMember not found")
    if m["stipend_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409,
                       "Member stipend_status is not ACTIVE")
    for p in svc.payments_of_member(m["id"]):
        if p["period_start"] == period_start:
            raise ApiError("ERR_DUPLICATE_PAYMENT_PERIOD", 409,
                           "A payment with this period_start already exists")
    site = svc.site_of_member(m)
    period_days = (parse_date(period_end) - parse_date(period_start)).days + 1
    p = new_entity({
        "corps_member_id": m["id"],
        "period_start": period_start,
        "period_end": period_end,
        "period_days": period_days,
        "base_amount_cents": svc.stipend_base_amount(site),
        "final_gross_cents": None,
        "deduction_cents": 0,
        "net_amount_cents": None,
        "status": "SCHEDULED",
        "created_by": uid,
        "_outlay_cents": 0,
        "approved_by": None,
        "decision_reason": None,
    })
    store.payments[p["id"]] = p
    return ok(payment_json(p), 201)


@bp.route("/corps/stipend-payments/<payment_id>/state", methods=["POST"])
def payment_state(payment_id):
    uid, role = auth(["StipendAdministrator"])
    data = body()
    to_status = need(data, "to_status")
    if to_status not in PAYMENT_STATES:
        bad_request("to_status must be a valid StipendPayment status")
    deduction = data.get("deduction_cents")
    if deduction is not None and (not is_int(deduction) or deduction < 0):
        bad_request("deduction_cents must be a non-negative integer")
    reason = data.get("reason")
    if to_status in ("FORFEITED", "CLAWED_BACK"):
        if reason is None or not isinstance(reason, str) or not reason.strip():
            bad_request("reason is required for FORFEITED and CLAWED_BACK")
    elif reason is not None and not isinstance(reason, str):
        bad_request("reason must be a string")
    p = get_payment_or_404(payment_id)
    m = store.members.get(p["corps_member_id"])
    site = svc.site_of_member(m) if m else None

    # Segregation of duties (priority 4) precedes state legality.
    if to_status == "APPROVED" and p["created_by"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Approver must differ from the payment creator")

    cur = p["status"]
    if to_status == "APPROVED" and cur == "SCHEDULED":
        if m is None or m["stipend_status"] != "ACTIVE":
            raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409,
                           "Member stipend_status is not ACTIVE")
        deduction_cents = deduction if deduction is not None else 0
        gross, net = svc.stipend_final_amounts(p["base_amount_cents"],
                                               p["period_days"], deduction_cents)
        p["deduction_cents"] = deduction_cents
        p["final_gross_cents"] = gross
        p["net_amount_cents"] = net
        p["approved_by"] = uid
        p["status"] = "APPROVED"
    elif to_status == "PAID" and cur == "APPROVED":
        headroom = svc.site_ledger(site)["funding_headroom_cents"] if site else 0
        if headroom < p["net_amount_cents"]:
            raise ApiError("ERR_SITE_FUNDING_DEFICIT", 422,
                           "Site funding headroom cannot cover this payment")
        p["status"] = "PAID"
        p["_outlay_cents"] = p["net_amount_cents"]
    elif to_status == "FORFEITED" and cur in ("SCHEDULED", "APPROVED"):
        p["status"] = "FORFEITED"
        p["decision_reason"] = reason
    elif to_status == "CLAWED_BACK" and cur == "PAID":
        p["status"] = "CLAWED_BACK"
        p["_outlay_cents"] = 0
        p["decision_reason"] = reason
    else:
        invalid_state("StipendPayment status %s cannot transition to %s"
                      % (cur, to_status))
    touch(p)
    return ok(payment_json(p), 200)
