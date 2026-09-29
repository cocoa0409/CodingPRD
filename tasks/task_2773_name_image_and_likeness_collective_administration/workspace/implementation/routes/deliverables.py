"""Deliverables: promising, documenting, submitting and reviewing the work."""

from flask import Blueprint, request

import auth
import clock
import derive
import envelope
import lookup
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("deliverables", __name__)

DELIVERABLE_KINDS = ["APPEARANCE", "SOCIAL_POST", "CHARITY_WORK", "AUTOGRAPH_SESSION"]
DELIVERABLE_STATUSES = ["PENDING", "SUBMITTED", "REJECTED", "VERIFIED", "WAIVED", "FORFEITED"]
EVIDENCE_KINDS = ["ANALYTICS_SCREENSHOT", "SIGNED_ATTENDANCE_SHEET", "PHOTO_SET",
                  "ORGANISATION_LETTER"]
MAX_SUBMISSIONS = 3


def _athlete_ownership(role, user_id, deliverable_id):
    """Priority 4: an athlete caller may only act on their own deliverables."""
    if role != auth.ATHLETE:
        return
    deliverable = store.deliverables.get(deliverable_id)
    if deliverable is None:
        return
    contract = store.deal_contracts.get(deliverable["deal_contract_id"])
    athlete = store.athletes.get(contract["athlete_id"]) if contract is not None else None
    if athlete is None or athlete["portal_user_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE")


@bp.route("/nil/deal-contracts/<contract_id>/deliverables", methods=["POST"])
def create_deliverable(contract_id):
    auth.authenticate([auth.COLLECTIVE_DIRECTOR])
    # Nested addressing: the contract resolves before any body field is examined.
    contract = lookup.deal_contract(contract_id)
    body = shape.body()
    kind = shape.enum_field(body, "deliverable_kind", DELIVERABLE_KINDS, required=True)
    unit_value = shape.int_field(body, "unit_value_cents", required=True, positive=True)
    due_at = shape.ts_field(body, "due_at", required=True)
    required_hours = shape.int_field(body, "required_charity_hours_tenths", default=0, minimum=0)
    if kind == "CHARITY_WORK":
        if required_hours <= 0:
            raise ApiError("ERR_INVALID_REQUEST",
                           "required_charity_hours_tenths must be strictly greater than zero "
                           "for a CHARITY_WORK deliverable.")
    elif required_hours != 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "required_charity_hours_tenths must be exactly zero unless "
                       "deliverable_kind is CHARITY_WORK.")

    if contract["lifecycle_status"] in derive.TERMINAL_LIFECYCLE:
        raise ApiError("ERR_CONTRACT_TERMINAL")
    if due_at < contract["effective_start_at"] or due_at >= contract["effective_end_at"]:
        raise ApiError("ERR_DUE_OUTSIDE_CONTRACT_WINDOW")

    now = clock.now()
    row = {
        "id": store.new_id(),
        "deal_contract_id": contract["id"],
        "deliverable_kind": kind,
        "unit_value_cents": unit_value,
        "due_at": due_at,
        "required_charity_hours_tenths": required_hours,
        "charity_hours_tenths": 0,
        "status": "PENDING",
        "evidence_records": [],
        "submission_count": 0,
        "performed_at": None,
        "submitted_at": None,
        "late_flag": False,
        "verified_by_user_id": None,
        "verified_at": None,
        "sequence_no": store.next_seq("deliverable"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.deliverables[row["id"]] = row
    return envelope.object_response(serialize.deliverable(row), 201)


@bp.route("/nil/deal-contracts/<contract_id>/deliverables", methods=["GET"])
def list_deliverables(contract_id):
    auth.authenticate(auth.ALL_ROLES)
    contract = lookup.deal_contract(contract_id)
    limit, offset = envelope.read_pagination(request.args)
    status = envelope.enum_filter(request.args, "status", DELIVERABLE_STATUSES)
    kind = envelope.enum_filter(request.args, "deliverable_kind", DELIVERABLE_KINDS)
    rows = derive.deliverables_of_contract(contract["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if kind is not None:
        rows = [r for r in rows if r["deliverable_kind"] == kind]
    return envelope.list_response([serialize.deliverable(r) for r in rows], limit, offset)


@bp.route("/nil/deliverables/<deliverable_id>", methods=["GET"])
def read_deliverable(deliverable_id):
    auth.authenticate(auth.ALL_ROLES)
    row = lookup.deliverable(deliverable_id)
    return envelope.object_response(serialize.deliverable(row))


@bp.route("/nil/deliverables/<deliverable_id>/evidence", methods=["POST"])
def record_evidence(deliverable_id):
    role, user_id = auth.authenticate([auth.ATHLETE, auth.COLLECTIVE_DIRECTOR])
    _athlete_ownership(role, user_id, deliverable_id)
    body = shape.body()
    evidence_kind = shape.enum_field(body, "evidence_kind", EVIDENCE_KINDS, required=True)
    reference_label = shape.string_field(body, "reference_label", required=True)
    deliverable = lookup.deliverable(deliverable_id)

    if deliverable["status"] in derive.TERMINAL_DELIVERABLE:
        raise ApiError("ERR_DELIVERABLE_STATE_INVALID")

    deliverable["evidence_records"].append({
        "evidence_kind": evidence_kind,
        "reference_label": reference_label,
        "recorded_at": clock.now(),
        "sequence_no": len(deliverable["evidence_records"]) + 1,
    })
    derive.touch(deliverable)
    return envelope.object_response(serialize.deliverable(deliverable), 201)


@bp.route("/nil/deliverables/<deliverable_id>/submissions", methods=["POST"])
def submit_deliverable(deliverable_id):
    role, user_id = auth.authenticate([auth.ATHLETE, auth.COLLECTIVE_DIRECTOR])
    _athlete_ownership(role, user_id, deliverable_id)
    body = shape.body()
    performed_at = shape.ts_field(body, "performed_at", required=True)
    charity_hours = shape.int_field(body, "charity_hours_tenths", default=0, minimum=0)
    shape.string_field(body, "submission_note")
    deliverable = lookup.deliverable(deliverable_id)
    contract = store.deal_contracts.get(deliverable["deal_contract_id"])

    if contract is None or contract["lifecycle_status"] in derive.TERMINAL_LIFECYCLE:
        raise ApiError("ERR_CONTRACT_TERMINAL")
    if contract["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    if deliverable["status"] not in ("PENDING", "REJECTED"):
        raise ApiError("ERR_DELIVERABLE_STATE_INVALID")
    if len(deliverable["evidence_records"]) < 1:
        raise ApiError("ERR_EVIDENCE_INSUFFICIENT")
    if deliverable["deliverable_kind"] == "CHARITY_WORK":
        if charity_hours < deliverable["required_charity_hours_tenths"]:
            raise ApiError("ERR_CHARITY_HOURS_SHORTFALL")
    if deliverable["submission_count"] >= MAX_SUBMISSIONS:
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED")

    deliverable["status"] = "SUBMITTED"
    deliverable["submission_count"] += 1
    deliverable["performed_at"] = performed_at
    deliverable["submitted_at"] = clock.now()
    deliverable["charity_hours_tenths"] = charity_hours
    deliverable["late_flag"] = performed_at > deliverable["due_at"]
    derive.touch(deliverable)
    return envelope.object_response(serialize.deliverable(deliverable))


@bp.route("/nil/deliverables/<deliverable_id>/reviews", methods=["POST"])
def review_deliverable(deliverable_id):
    role, user_id = auth.authenticate([auth.COMPLIANCE_OFFICER])
    body = shape.body()
    decision = shape.enum_field(body, "decision", ["VERIFY", "REJECT", "WAIVE"], required=True)
    shape.string_field(body, "review_note")
    deliverable = lookup.deliverable(deliverable_id)

    if decision in ("VERIFY", "REJECT"):
        if deliverable["status"] != "SUBMITTED":
            raise ApiError("ERR_DELIVERABLE_STATE_INVALID")
    else:
        if deliverable["status"] not in ("PENDING", "SUBMITTED", "REJECTED"):
            raise ApiError("ERR_DELIVERABLE_STATE_INVALID")

    if decision == "VERIFY":
        deliverable["status"] = "VERIFIED"
    elif decision == "REJECT":
        deliverable["status"] = "REJECTED"
    else:
        deliverable["status"] = "WAIVED"
    if decision in ("VERIFY", "WAIVE"):
        deliverable["verified_by_user_id"] = user_id
        deliverable["verified_at"] = clock.now()
    derive.touch(deliverable)

    contract = store.deal_contracts.get(deliverable["deal_contract_id"])
    if contract is not None and decision in ("VERIFY", "WAIVE"):
        derive.maybe_complete_contract(contract)
    return envelope.object_response(serialize.deliverable(deliverable))
