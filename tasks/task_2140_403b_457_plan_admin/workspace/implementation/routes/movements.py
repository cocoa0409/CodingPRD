"""Contract exchanges and plan-to-plan transfers."""
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

bp = Blueprint("movements", __name__)


def _own_movement(row):
    if g.role == "Participant":
        auth.require(row["participant_id"] == g.user_id)
    elif g.role == "PlanSponsorAdmin":
        owners = set()
        participant = store.participants.get(row["participant_id"])
        if participant:
            owners.add(participant["employer_id"])
        for key in ("source_plan_id", "destination_plan_id"):
            plan = store.plans.get(row[key])
            if plan:
                owners.add(plan["employer_id"])
        auth.require(g.user_id in owners)


def _admissibility(row):
    """exchange_transfer_admissibility -- ladder rungs 26, 27, 28, 42, 43."""
    src = store.vendor_accounts.get(row["source_vendor_account_id"])
    dst = store.vendor_accounts.get(row["destination_vendor_account_id"])
    sp = store.plans.get(row["source_plan_id"])
    dp = store.plans.get(row["destination_plan_id"])
    participant = store.participants.get(row["participant_id"])

    if row["request_kind"] == "CONTRACT_EXCHANGE":
        if calc.isa_covers(sp["id"], dst["vendor_id"], require_fresh=True) is None:   # rung 26
            raise ApiError("ERR_EXCHANGE_VENDOR_NOT_APPROVED",
                           "The receiving vendor has no active, current agreement with the "
                           "plan.")
        if sp["id"] != dp["id"] or not sp["permits_contract_exchanges"]:              # rung 27
            raise ApiError("ERR_TRANSFER_NOT_PERMITTED_BY_PLAN",
                           "The plan document or the shape of the movement forbids it.")
        if row["amount_cents"] > src["accumulated_benefit_cents"]:                     # rung 43
            raise ApiError("ERR_ACCUMULATED_BENEFIT_REDUCED",
                           "The exchange would reduce the participant's accumulated benefit.")
    else:
        if (sp["id"] == dp["id"] or not sp["permits_outgoing_transfers"]
                or not dp["permits_incoming_transfers"]
                or sp["plan_type"] != dp["plan_type"]):                               # rung 27
            raise ApiError("ERR_TRANSFER_NOT_PERMITTED_BY_PLAN",
                           "The plan document or the shape of the movement forbids it.")
        if participant["employer_id"] != dp["employer_id"]:                           # rung 28
            raise ApiError("ERR_TRANSFER_PARTICIPANT_NOT_ELIGIBLE",
                           "The participant does not belong to the receiving sponsor.")
        if row["amount_cents"] > src["accumulated_benefit_cents"]:                     # rung 42
            raise ApiError("ERR_TRANSFER_AMOUNT_EXCEEDS_BENEFIT",
                           "The transfer exceeds the source contract's accumulated benefit.")


@bp.post("/plan-admin/transfer-exchange-requests")
@endpoint(["PlanSponsorAdmin", "Participant"])
def create_movement():
    body = V.body_of(request)
    participant_id = V.req_str(body, "participant_id")
    request_kind = V.req_enum(body, "request_kind", calc.REQUEST_KINDS)
    source_plan_id = V.req_str(body, "source_plan_id")
    destination_plan_id = V.req_str(body, "destination_plan_id")
    source_vendor_account_id = V.req_str(body, "source_vendor_account_id")
    destination_vendor_account_id = V.req_str(body, "destination_vendor_account_id")
    amount_cents = V.req_int(body, "amount_cents", minimum=1)

    auth.participant(participant_id)                        # rung 5
    source_plan = auth.plan(source_plan_id)                 # rung 5
    destination_plan = auth.plan(destination_plan_id)       # rung 5
    auth.vendor_account(source_vendor_account_id)           # rung 5
    auth.vendor_account(destination_vendor_account_id)      # rung 5

    draft = {
        "participant_id": participant_id,
        "request_kind": request_kind,
        "source_plan_id": source_plan_id,
        "destination_plan_id": destination_plan_id,
        "source_vendor_account_id": source_vendor_account_id,
        "destination_vendor_account_id": destination_vendor_account_id,
        "amount_cents": amount_cents,
    }
    _own_movement(draft)                                    # rung 6
    for plan in (source_plan, destination_plan):            # rung 10
        if plan["status"] not in ("ACTIVE", "FROZEN"):
            raise ApiError("ERR_PLAN_NOT_ACTIVE", "The governing plan is %s." % plan["status"])
    _admissibility(draft)                                   # rungs 26-28, 42-43

    row = store.common_fields()
    row.update(draft)
    row.update({
        "state": "SUBMITTED",
        "vendor_rejection_reason": None,
        "denial_reason": None,
        "pre_move_source_benefit_cents": None,
        "pre_move_destination_benefit_cents": None,
        "executed_at": None,
        "resubmit_count": 0,
    })
    store.transfer_exchange_requests[row["id"]] = row
    return envelope.created(serialize.movement(row))


@bp.get("/plan-admin/transfer-exchange-requests/<row_id>")
@endpoint(auth.ALL_ROLES)
def get_movement(row_id):
    return envelope.ok(serialize.movement(auth.movement(row_id)))


@bp.get("/plan-admin/transfer-exchange-requests")
@endpoint(auth.ALL_ROLES)
def list_movements():
    args = request.args
    limit, offset = V.pagination(args)
    filters = {
        "participant_id": args.get("participant_id"),
        "source_plan_id": args.get("source_plan_id"),
        "destination_plan_id": args.get("destination_plan_id"),
        "source_vendor_account_id": args.get("source_vendor_account_id"),
        "destination_vendor_account_id": args.get("destination_vendor_account_id"),
    }
    request_kind = V.query_enum(args, "request_kind", calc.REQUEST_KINDS)
    state = V.query_enum(args, "state", calc.MOVEMENT_STATES)
    items = store.rows(store.transfer_exchange_requests)
    for key, value in filters.items():
        if value:
            items = [r for r in items if r[key] == value]
    if request_kind:
        items = [r for r in items if r["request_kind"] == request_kind]
    if state:
        items = [r for r in items if r["state"] == state]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.listing([serialize.movement(r) for r in page], limit, offset, total)


@bp.post("/plan-admin/transfer-exchange-requests/<row_id>/vendor-response")
@endpoint(["VendorRepresentative"])
def vendor_response(row_id):
    body = V.body_of(request)
    accepted = V.req_bool(body, "accepted")
    rejection_reason = V.opt_str(body, "rejection_reason")
    row = auth.movement(row_id)                             # rung 4
    dst = store.vendor_accounts.get(row["destination_vendor_account_id"])
    auth.require(dst is not None and dst["vendor_id"] == g.user_id)     # rung 6
    if row["state"] != "SUBMITTED":                         # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED movement may receive a vendor response.")
    if accepted:
        row["state"] = "ACCEPTED_BY_VENDOR"
    else:
        row["state"] = "REJECTED_BY_VENDOR"
        row["vendor_rejection_reason"] = rejection_reason
    store.touch(row)
    return envelope.ok(serialize.movement(row))


@bp.post("/plan-admin/transfer-exchange-requests/<row_id>/decision")
@endpoint(["ComplianceOfficer"])
def decide_movement(row_id):
    body = V.body_of(request)
    decision = V.req_enum(body, "decision", {"APPROVE", "DENY", "RESUBMIT"})
    note = V.opt_str(body, "note")
    row = auth.movement(row_id)                             # rung 4

    if decision == "APPROVE":
        allowed_from = ("ACCEPTED_BY_VENDOR",)
    elif decision == "DENY":
        allowed_from = ("ACCEPTED_BY_VENDOR", "SUBMITTED")
    else:
        allowed_from = ("REJECTED_BY_VENDOR",)
    if row["state"] not in allowed_from:                    # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s is not available from state %s." % (decision, row["state"]))

    if decision == "RESUBMIT":
        row["state"] = "SUBMITTED"
        row["vendor_rejection_reason"] = None
        row["resubmit_count"] += 1
        store.touch(row)
        return envelope.ok(serialize.movement(row))

    if decision == "DENY":
        row["state"] = "DENIED"
        row["denial_reason"] = note
        store.touch(row)
        return envelope.ok(serialize.movement(row))

    for key in ("source_plan_id", "destination_plan_id"):    # rung 12
        plan = store.plans.get(row[key])
        if plan and plan["compliance_posture"] != "CLEAR":
            raise ApiError("ERR_PLAN_UNDER_CORRECTION",
                           "A plan in the movement is under correction.")
    _admissibility(row)                                      # rungs 26-28, 42-43
    row["state"] = "APPROVED"
    store.touch(row)
    return envelope.ok(serialize.movement(row))


@bp.post("/plan-admin/transfer-exchange-requests/<row_id>/execute")
@endpoint(["PlanSponsorAdmin"])
def execute_movement(row_id):
    body = V.body_of(request)
    execution_date = V.req_date(body, "execution_date")
    row = auth.movement(row_id)                             # rung 4
    _own_movement(row)                                      # rung 6
    if row["state"] != "APPROVED":                          # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an APPROVED movement may be executed.")
    if execution_date > store.today():                      # rung 29
        raise ApiError("ERR_DATE_IN_FUTURE", "execution_date is in the future.")

    src = store.vendor_accounts.get(row["source_vendor_account_id"])
    dst = store.vendor_accounts.get(row["destination_vendor_account_id"])
    if row["amount_cents"] > src["accumulated_benefit_cents"]:
        if row["request_kind"] == "CONTRACT_EXCHANGE":       # rung 43
            raise ApiError("ERR_ACCUMULATED_BENEFIT_REDUCED",
                           "The exchange would reduce the participant's accumulated benefit.")
        raise ApiError("ERR_TRANSFER_AMOUNT_EXCEEDS_BENEFIT",   # rung 42
                       "The transfer exceeds the source contract's accumulated benefit.")

    row["pre_move_source_benefit_cents"] = src["accumulated_benefit_cents"]
    row["pre_move_destination_benefit_cents"] = dst["accumulated_benefit_cents"]
    src["accumulated_benefit_cents"] -= row["amount_cents"]
    dst["accumulated_benefit_cents"] += row["amount_cents"]
    derive.recompute_vendor_account(src)
    derive.recompute_vendor_account(dst)
    store.touch(src)
    store.touch(dst)
    row["state"] = "EXECUTED"
    row["executed_at"] = store.now_ts()
    store.touch(row)

    for pid in {src["participant_id"], dst["participant_id"]}:
        participant = store.participants.get(pid)
        if participant:
            derive.recompute_participant(participant, bump=True)
    return envelope.ok(serialize.movement(row))


@bp.post("/plan-admin/transfer-exchange-requests/<row_id>/reverse")
@endpoint(["ComplianceOfficer"])
def reverse_movement(row_id):
    body = V.body_of(request)
    V.req_str(body, "reason")
    row = auth.movement(row_id)                             # rung 4
    if row["state"] != "EXECUTED":                          # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an EXECUTED movement may be reversed.")
    src = store.vendor_accounts.get(row["source_vendor_account_id"])
    dst = store.vendor_accounts.get(row["destination_vendor_account_id"])
    src["accumulated_benefit_cents"] += row["amount_cents"]
    dst["accumulated_benefit_cents"] -= row["amount_cents"]
    derive.recompute_vendor_account(src)
    derive.recompute_vendor_account(dst)
    store.touch(src)
    store.touch(dst)
    row["state"] = "REVERSED"
    store.touch(row)
    for pid in {src["participant_id"], dst["participant_id"]}:
        participant = store.participants.get(pid)
        if participant:
            derive.recompute_participant(participant, bump=True)
    return envelope.ok(serialize.movement(row))
