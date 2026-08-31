"""Loan, hardship and unforeseeable emergency requests."""
from flask import Blueprint, g, request

import auth
import calc
import derive
import envelope
import serialize
import store
import validate as V
from auth import endpoint
from errors import ApiError

bp = Blueprint("requests", __name__)


def _check_isa_perimeter(req, plan, participant):
    """Ladder rungs 24 then 25."""
    if req["request_type"] == "LOAN":
        accounts = calc.loan_accounts(participant["id"], plan)
        data_class = "shares_loan_data"
    else:
        va = store.vendor_accounts.get(req["vendor_account_id"])
        accounts = [va] if va is not None else []
        data_class = "shares_hardship_data"
    for va in accounts:
        if calc.isa_covers(va["plan_id"], va["vendor_id"], data_class) is None:
            raise ApiError("ERR_ISA_NOT_ACTIVE",
                           "A required information sharing agreement is absent or inactive.")
    for va in accounts:
        if calc.isa_covers(va["plan_id"], va["vendor_id"], data_class,
                           require_fresh=True) is None:
            raise ApiError("ERR_ISA_DATA_STALE",
                           "A required information sharing agreement's data feed is stale.")


@bp.post("/plan-admin/participant-requests")
@endpoint(["PlanSponsorAdmin", "Participant"])
def create_request():
    body = V.body_of(request)
    participant_id = V.req_str(body, "participant_id")
    plan_id = V.req_str(body, "plan_id")
    vendor_account_id = V.req_str(body, "vendor_account_id")
    request_type = V.req_enum(body, "request_type", calc.REQUEST_TYPES)
    requested_amount = V.req_int(body, "requested_amount_cents", minimum=1)
    stated_need = V.opt_int(body, "stated_need_cents", 0, minimum=0)
    estimated_taxes = V.opt_int(body, "estimated_taxes_cents", 0, minimum=0)
    safe_harbor = V.opt_enum(body, "safe_harbor_reason", calc.SAFE_HARBOR_REASONS, "NONE")
    emergency = V.opt_enum(body, "emergency_reason", calc.EMERGENCY_REASONS, "NONE")
    insurance = V.opt_int(body, "insurance_reimbursement_available_cents", 0, minimum=0)
    liquidatable = V.opt_int(body, "liquidatable_assets_cents", 0, minimum=0)
    cessation = V.opt_int(body, "deferral_cessation_relief_cents", 0, minimum=0)
    loan_term_months = V.opt_int(body, "loan_term_months", None, minimum=1)

    participant = auth.participant(participant_id)        # rung 5
    plan = auth.plan(plan_id)                             # rung 5
    va = auth.vendor_account(vendor_account_id)           # rung 5

    if g.role == "Participant":                           # rung 6
        auth.require(participant_id == g.user_id)
    else:
        auth.own_plan(plan)

    if plan["status"] not in ("ACTIVE", "FROZEN"):        # rung 10
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "The governing plan is %s." % plan["status"])
    if request_type == "LOAN" and plan["status"] == "FROZEN":     # rung 11
        raise ApiError("ERR_PLAN_FROZEN",
                       "No loan request may be created against a frozen plan.")
    if request_type == "LOAN" and participant["loan_eligibility_flag"] != "AVAILABLE":
        raise ApiError("ERR_LOAN_ELIGIBILITY_SUSPENDED",     # rung 15
                       "The participant's loan eligibility is suspended.")

    permitted = True                                       # rung 20
    if request_type == "HARDSHIP":
        permitted = plan["plan_type"] == "PLAN_403B" and plan["permits_hardship"]
    elif request_type == "UNFORESEEABLE_EMERGENCY":
        permitted = plan["plan_type"] == "PLAN_457B" and plan["permits_unforeseeable_emergency"]
    else:
        permitted = plan["permits_loans"]
    if not permitted:
        raise ApiError("ERR_DISTRIBUTION_TYPE_NOT_PERMITTED",
                       "The plan type or plan document does not permit this request type.")

    if request_type == "HARDSHIP" and safe_harbor == "NONE":      # rung 21
        raise ApiError("ERR_HARDSHIP_NOT_SAFE_HARBOR",
                       "A hardship must name a safe-harbour event.")
    if request_type == "UNFORESEEABLE_EMERGENCY" and emergency in (
            "NONE", "COLLEGE_TUITION", "PURCHASE_OF_HOME"):       # rung 22
        raise ApiError("ERR_UE_STANDARD_NOT_MET",
                       "The cited reason is not an unforeseeable emergency.")

    if request_type == "LOAN":
        capacity = calc.loan_maximum_available(participant, plan)
        if capacity["vested_total_cents"] <= 0:                   # rung 39
            raise ApiError("ERR_NO_VESTED_BALANCE",
                           "The loan aggregation set has no vested balance.")
        if requested_amount > capacity["maximum_loan_cents"]:     # rung 40
            raise ApiError("ERR_LOAN_LIMIT_EXCEEDED",
                           "The requested loan exceeds the computed maximum.")

    row = store.common_fields()
    row.update({
        "participant_id": participant_id,
        "plan_id": plan_id,
        "vendor_account_id": vendor_account_id,
        "request_type": request_type,
        "requested_amount_cents": requested_amount,
        "stated_need_cents": stated_need,
        "estimated_taxes_cents": estimated_taxes,
        "safe_harbor_reason": safe_harbor,
        "emergency_reason": emergency,
        "insurance_reimbursement_available_cents": insurance,
        "liquidatable_assets_cents": liquidatable,
        "deferral_cessation_relief_cents": cessation,
        "loan_term_months": loan_term_months,
        "state": "SUBMITTED",
        "max_approvable_cents": None,
        "approved_amount_cents": None,
        "submitted_by_user_id": g.user_id,
        "reviewed_by_user_id": None,
        "decided_by_user_id": None,
        "resubmission_count": 0,
        "denial_reason": None,
        "fulfillment_date": None,
    })
    store.participant_requests[row["id"]] = row
    return envelope.created(serialize.participant_request(row))


@bp.get("/plan-admin/participant-requests/<row_id>")
@endpoint(auth.ALL_ROLES)
def get_request(row_id):
    return envelope.ok(serialize.participant_request(auth.participant_request(row_id)))


@bp.get("/plan-admin/participant-requests")
@endpoint(auth.ALL_ROLES)
def list_requests():
    args = request.args
    limit, offset = V.pagination(args)
    participant_id = args.get("participant_id")
    plan_id = args.get("plan_id")
    vendor_account_id = args.get("vendor_account_id")
    request_type = V.query_enum(args, "request_type", calc.REQUEST_TYPES)
    state = V.query_enum(args, "state", calc.REQUEST_STATES)
    items = store.rows(store.participant_requests)
    if participant_id:
        items = [r for r in items if r["participant_id"] == participant_id]
    if plan_id:
        items = [r for r in items if r["plan_id"] == plan_id]
    if vendor_account_id:
        items = [r for r in items if r["vendor_account_id"] == vendor_account_id]
    if request_type:
        items = [r for r in items if r["request_type"] == request_type]
    if state:
        items = [r for r in items if r["state"] == state]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.listing([serialize.participant_request(r) for r in page], limit, offset,
                            total)


@bp.post("/plan-admin/participant-requests/<row_id>/decision")
@endpoint(["ComplianceOfficer"])
def decide_request(row_id):
    body = V.body_of(request)
    decision = V.req_enum(body, "decision",
                          {"BEGIN_REVIEW", "RETURN_FOR_INFO", "APPROVE", "DENY"})
    note = V.opt_str(body, "note")
    req = auth.participant_request(row_id)                  # rung 4

    if decision in ("APPROVE", "DENY") and req["reviewed_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",         # rung 7
                       "The officer who opened review may not decide the request.")

    expected_from = {"BEGIN_REVIEW": "SUBMITTED", "RETURN_FOR_INFO": "UNDER_REVIEW",
                     "APPROVE": "UNDER_REVIEW", "DENY": "UNDER_REVIEW"}[decision]
    if req["state"] != expected_from:                       # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s requires the request to be %s." % (decision, expected_from))

    if decision == "BEGIN_REVIEW":
        req["state"] = "UNDER_REVIEW"
        req["reviewed_by_user_id"] = g.user_id
        store.touch(req)
        return envelope.ok(serialize.participant_request(req))

    if decision == "RETURN_FOR_INFO":
        req["state"] = "RETURNED_FOR_INFO"
        store.touch(req)
        return envelope.ok(serialize.participant_request(req))

    if decision == "DENY":
        req["state"] = "DENIED"
        req["denial_reason"] = note
        req["decided_by_user_id"] = g.user_id
        store.touch(req)
        return envelope.ok(serialize.participant_request(req))

    # APPROVE
    plan = store.plans.get(req["plan_id"])
    participant = store.participants.get(req["participant_id"])
    va = store.vendor_accounts.get(req["vendor_account_id"])

    if req["request_type"] == "UNFORESEEABLE_EMERGENCY":     # rung 23
        relief = (req["insurance_reimbursement_available_cents"]
                  + req["liquidatable_assets_cents"]
                  + req["deferral_cessation_relief_cents"])
        if relief >= req["stated_need_cents"]:
            raise ApiError("ERR_UE_RELIEF_AVAILABLE",
                           "Other relief already meets or exceeds the stated need.")

    _check_isa_perimeter(req, plan, participant)             # rungs 24, 25

    if req["request_type"] == "LOAN":
        capacity = calc.loan_maximum_available(participant, plan)
        if capacity["vested_total_cents"] <= 0:              # rung 39
            raise ApiError("ERR_NO_VESTED_BALANCE",
                           "The loan aggregation set has no vested balance.")
        if req["requested_amount_cents"] > capacity["maximum_loan_cents"]:   # rung 40
            raise ApiError("ERR_LOAN_LIMIT_EXCEEDED",
                           "The requested loan exceeds the computed maximum.")
        max_approvable = capacity["maximum_loan_cents"]
    else:
        max_approvable, _ = calc.distribution_max_approvable(req, va)
        if req["requested_amount_cents"] > max_approvable:   # rung 41
            raise ApiError("ERR_DISTRIBUTION_EXCEEDS_NEED",
                           "The requested distribution exceeds the computed maximum.")

    req["state"] = "APPROVED"
    req["max_approvable_cents"] = max_approvable
    req["approved_amount_cents"] = req["requested_amount_cents"]
    req["decided_by_user_id"] = g.user_id
    store.touch(req)
    return envelope.ok(serialize.participant_request(req))


@bp.post("/plan-admin/participant-requests/<row_id>/resubmit")
@endpoint(["PlanSponsorAdmin", "Participant"])
def resubmit_request(row_id):
    body = V.body_of(request)
    requested_amount = V.opt_int(body, "requested_amount_cents", minimum=1)
    stated_need = V.opt_int(body, "stated_need_cents", minimum=0)
    estimated_taxes = V.opt_int(body, "estimated_taxes_cents", minimum=0)
    insurance = V.opt_int(body, "insurance_reimbursement_available_cents", minimum=0)
    liquidatable = V.opt_int(body, "liquidatable_assets_cents", minimum=0)
    cessation = V.opt_int(body, "deferral_cessation_relief_cents", minimum=0)

    req = auth.participant_request(row_id)                  # rung 4
    plan = store.plans.get(req["plan_id"])
    if g.role == "Participant":                             # rung 6
        auth.require(req["participant_id"] == g.user_id)
    else:
        auth.own_plan(plan)
    if req["state"] != "RETURNED_FOR_INFO":                 # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a RETURNED_FOR_INFO request may be resubmitted.")

    if requested_amount is not None:
        req["requested_amount_cents"] = requested_amount
    if stated_need is not None:
        req["stated_need_cents"] = stated_need
    if estimated_taxes is not None:
        req["estimated_taxes_cents"] = estimated_taxes
    if insurance is not None:
        req["insurance_reimbursement_available_cents"] = insurance
    if liquidatable is not None:
        req["liquidatable_assets_cents"] = liquidatable
    if cessation is not None:
        req["deferral_cessation_relief_cents"] = cessation
    req["state"] = "SUBMITTED"
    req["resubmission_count"] += 1
    req["reviewed_by_user_id"] = None
    req["submitted_by_user_id"] = g.user_id
    store.touch(req)
    return envelope.ok(serialize.participant_request(req))


@bp.post("/plan-admin/participant-requests/<row_id>/fulfill")
@endpoint(["PlanSponsorAdmin"])
def fulfill_request(row_id):
    body = V.body_of(request)
    fulfillment_date = V.req_date(body, "fulfillment_date")
    req = auth.participant_request(row_id)                  # rung 4
    plan = store.plans.get(req["plan_id"])
    auth.own_plan(plan)                                     # rung 6
    if req["state"] != "APPROVED":                          # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an APPROVED request may be fulfilled.")
    if fulfillment_date > store.today():                    # rung 29
        raise ApiError("ERR_DATE_IN_FUTURE", "fulfillment_date is in the future.")

    va = store.vendor_accounts.get(req["vendor_account_id"])
    participant = store.participants.get(req["participant_id"])
    amount = req["approved_amount_cents"]

    if req["request_type"] == "LOAN":
        va["outstanding_loan_balance_cents"] += amount
        va["highest_outstanding_loan_12mo_cents"] = max(
            va["highest_outstanding_loan_12mo_cents"], va["outstanding_loan_balance_cents"])
        store.touch(va)
        req["state"] = "DISBURSED"
    else:
        va["accumulated_benefit_cents"] -= amount
        derive.recompute_vendor_account(va)
        store.touch(va)
        req["state"] = "PAID"

    req["fulfillment_date"] = fulfillment_date.isoformat()
    store.touch(req)
    derive.recompute_participant(participant, bump=True)
    derive.recompute_plan_excess(plan)
    return envelope.ok(serialize.participant_request(req))
