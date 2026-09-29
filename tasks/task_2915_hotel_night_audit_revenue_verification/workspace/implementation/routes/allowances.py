"""Allowances: tiered approval, bounded revision and compensating reversal."""
from flask import Blueprint

import db
import response
import shapes
from constants import (ALLOWANCE_STATUSES, APPROVAL_ROLES, PREFIX, REASON_CODES)
from errors import ApiError
from middleware import (ALL_ROLES, CONTROLLER, FRONT_DESK_AGENT, NIGHT_AUDITOR,
                        REVENUE_MANAGER, authenticate)
from money import ZERO, q2
from services import calc, derive, lookup, serial

bp = Blueprint("allowances", __name__, url_prefix=PREFIX)

RAISING_ROLES = [NIGHT_AUDITOR, FRONT_DESK_AGENT, REVENUE_MANAGER]
REVIEW_ROLES = [REVENUE_MANAGER, CONTROLLER]
REVISION_LIMIT = 2


def _property_of(allowance):
    folio = db.store.folios.get(allowance["folio_id"])
    return db.store.properties.get(folio["property_id"]) if folio else None


def _require_state(allowance, wanted, error_id, message):
    if allowance["status"] != wanted:
        raise ApiError(error_id, message)


def _require_not_originator(allowance, user_id):
    if allowance["requested_by_user_id"] == user_id:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN",
                       "The requester may not review their own allowance.")


@bp.route("/allowances", methods=["POST"])
def create_allowance():
    user_id, _role = authenticate(RAISING_ROLES)
    body = shapes.parse([
        shapes.Field("folio_id", "string", required=True),
        shapes.Field("business_date_id", "string", required=True),
        shapes.Field("requested_amount", "number", required=True, gt=0),
        shapes.Field("reason_code", "string", enum=REASON_CODES),
        shapes.Field("narrative", "string"),
        shapes.Field("supporting_document_reference", "string"),
    ])
    date_row = lookup.get_date(body["business_date_id"])
    folio = lookup.get_folio(body["folio_id"])
    lookup.require_not_archived(date_row)
    lookup.require_charges_open(date_row)
    if folio["property_id"] != date_row["property_id"]:
        raise ApiError("ERR_CROSS_PROPERTY_REFERENCE",
                       "The guest account belongs to a different property.")
    prop = db.store.properties[folio["property_id"]]
    requested = q2(body["requested_amount"])
    row = db.insert("allowances", {
        "_kind": "Allowance",
        "folio_id": folio["id"],
        "business_date_id": date_row["id"],
        "reverses_allowance_id": None,
        "reason_code": body["reason_code"],
        "requested_amount": requested,
        "approved_amount": None,
        "narrative": body["narrative"],
        "supporting_document_reference": body["supporting_document_reference"],
        "status": "DRAFT",
        "required_approval_role": calc.required_approval_role(
            requested,
            prop["allowance_manager_threshold_amount"],
            prop["allowance_controller_threshold_amount"],
        ),
        "revision_round": 0,
        "requested_by_user_id": user_id,
        "approved_by_user_id": None,
        "submitted_at": None,
        "approved_at": None,
    })
    return response.created(serial.allowance_out(row))


@bp.route("/allowances/<row_id>/submit", methods=["POST"])
def submit_allowance(row_id):
    authenticate(RAISING_ROLES)
    body = shapes.parse([
        shapes.Field("reason_code", "string", enum=REASON_CODES),
        shapes.Field("narrative", "string"),
        shapes.Field("supporting_document_reference", "string"),
    ])
    allowance = lookup.get_allowance(row_id)
    lookup.require_not_archived(lookup.get_date(allowance["business_date_id"]))
    if allowance["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise ApiError("ERR_ALLOWANCE_NOT_SUBMITTABLE",
                       "The allowance may not be submitted from its current state.")
    reason = body["reason_code"] or allowance["reason_code"]
    reference = body["supporting_document_reference"]
    if reference is None:
        reference = allowance["supporting_document_reference"]
    if reason is None:
        raise ApiError("ERR_REASON_CODE_REQUIRED",
                       "A reason code is required before submission.")
    if reason == "RATE_ERROR" and (reference is None or str(reference).strip() == ""):
        raise ApiError("ERR_SUPPORTING_DOCUMENT_REQUIRED",
                       "A rate-error allowance requires a supporting document.")
    allowance["reason_code"] = reason
    if body["narrative"] is not None:
        allowance["narrative"] = body["narrative"]
    allowance["supporting_document_reference"] = reference
    allowance["status"] = "SUBMITTED"
    allowance["submitted_at"] = db.now()
    derive.touch(allowance)
    return response.ok(serial.allowance_out(allowance))


@bp.route("/allowances/<row_id>/approve", methods=["POST"])
def approve_allowance(row_id):
    user_id, role = authenticate([NIGHT_AUDITOR, REVENUE_MANAGER, CONTROLLER])
    body = shapes.parse([shapes.Field("approved_amount", "number", required=True)])
    allowance = lookup.get_allowance(row_id)
    date_row = lookup.get_date(allowance["business_date_id"])
    folio = lookup.get_folio(allowance["folio_id"])
    lookup.require_not_archived(date_row)
    lookup.require_charges_open(date_row)
    if derive.folio_figures(folio)["settlement_status"] == "TRANSFERRED_TO_CITY_LEDGER":
        raise ApiError("ERR_FOLIO_ALREADY_TRANSFERRED",
                       "The account has been transferred to the city ledger.")
    _require_state(allowance, "SUBMITTED", "ERR_ALLOWANCE_NOT_PENDING",
                   "The allowance is not awaiting a decision.")
    _require_not_originator(allowance, user_id)
    if not calc.role_clears_tier(role, allowance["required_approval_role"]):
        raise ApiError("ERR_APPROVAL_TIER_INSUFFICIENT",
                       "The acting role sits below the frozen approval tier.")
    prop = db.store.properties[folio["property_id"]]
    threshold = prop["allowance_controller_threshold_amount"]
    if allowance["requested_amount"] >= threshold:
        if lookup.has_active_allowance_document(allowance["id"]) is None:
            raise ApiError("ERR_ALLOWANCE_DOCUMENT_MISSING",
                           "Active allowance-approval paperwork is required.")
    approved = q2(body["approved_amount"])
    if approved <= ZERO or approved > allowance["requested_amount"]:
        raise ApiError("ERR_APPROVED_AMOUNT_EXCEEDS_REQUEST",
                       "approved_amount must be positive and at most the request.")
    allowance["approved_amount"] = approved
    allowance["approved_by_user_id"] = user_id
    allowance["approved_at"] = db.now()
    allowance["status"] = "POSTED"
    derive.append_posting("ALLOWANCE", -approved, date_row, "ALLOWANCE_WORKFLOW",
                          user_id, folio=folio, reason_code=allowance["reason_code"],
                          allowance_id=allowance["id"])
    derive.touch(allowance)
    return response.ok(serial.allowance_out(allowance))


@bp.route("/allowances/<row_id>/reject", methods=["POST"])
def reject_allowance(row_id):
    user_id, _role = authenticate(REVIEW_ROLES)
    allowance = lookup.get_allowance(row_id)
    lookup.require_not_archived(lookup.get_date(allowance["business_date_id"]))
    _require_state(allowance, "SUBMITTED", "ERR_ALLOWANCE_NOT_PENDING",
                   "The allowance is not awaiting a decision.")
    _require_not_originator(allowance, user_id)
    allowance["status"] = "REJECTED"
    derive.touch(allowance)
    return response.ok(serial.allowance_out(allowance))


@bp.route("/allowances/<row_id>/return-for-revision", methods=["POST"])
def return_allowance(row_id):
    user_id, _role = authenticate(REVIEW_ROLES)
    allowance = lookup.get_allowance(row_id)
    lookup.require_not_archived(lookup.get_date(allowance["business_date_id"]))
    _require_state(allowance, "SUBMITTED", "ERR_ALLOWANCE_NOT_PENDING",
                   "The allowance is not awaiting a decision.")
    _require_not_originator(allowance, user_id)
    if int(allowance["revision_round"]) >= REVISION_LIMIT:
        raise ApiError("ERR_REVISION_LIMIT_REACHED",
                       "The allowance has exhausted its revision rounds.")
    allowance["status"] = "RETURNED_FOR_REVISION"
    allowance["revision_round"] = int(allowance["revision_round"]) + 1
    derive.touch(allowance)
    return response.ok(serial.allowance_out(allowance))


@bp.route("/allowances/<row_id>/reverse", methods=["POST"])
def reverse_allowance(row_id):
    user_id, _role = authenticate(REVIEW_ROLES)
    allowance = lookup.get_allowance(row_id)
    date_row = lookup.get_date(allowance["business_date_id"])
    folio = lookup.get_folio(allowance["folio_id"])
    lookup.require_not_archived(date_row)
    lookup.require_charges_open(date_row)
    _require_state(allowance, "POSTED", "ERR_ALLOWANCE_NOT_POSTED",
                   "Only a posted allowance may be reversed.")
    if allowance["reverses_allowance_id"] is not None:
        raise ApiError("ERR_ALREADY_A_REVERSAL",
                       "A compensating allowance may not itself be reversed.")
    amount = q2(allowance["approved_amount"])
    prop = db.store.properties[folio["property_id"]]
    compensating = db.insert("allowances", {
        "_kind": "Allowance",
        "folio_id": allowance["folio_id"],
        "business_date_id": allowance["business_date_id"],
        "reverses_allowance_id": allowance["id"],
        "reason_code": allowance["reason_code"],
        "requested_amount": amount,
        "approved_amount": amount,
        "narrative": allowance["narrative"],
        "supporting_document_reference": allowance["supporting_document_reference"],
        "status": "POSTED",
        "required_approval_role": calc.required_approval_role(
            amount,
            prop["allowance_manager_threshold_amount"],
            prop["allowance_controller_threshold_amount"],
        ),
        "revision_round": 0,
        "requested_by_user_id": user_id,
        "approved_by_user_id": user_id,
        "submitted_at": None,
        "approved_at": db.now(),
    })
    original_line = None
    for line in derive.postings():
        if line["allowance_id"] == allowance["id"] and \
                line["charge_type"] == "ALLOWANCE" and \
                line["reverses_posting_id"] is None:
            original_line = line
            break
    derive.append_posting("ALLOWANCE", amount, date_row, "ALLOWANCE_WORKFLOW",
                          user_id, folio=folio, reason_code=allowance["reason_code"],
                          allowance_id=compensating["id"],
                          reverses_posting_id=original_line["id"] if original_line else None)
    allowance["status"] = "REVERSED"
    derive.touch(allowance)
    return response.ok(serial.allowance_out(allowance))


@bp.route("/allowances/<row_id>", methods=["GET"])
def get_allowance(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.allowance_out(lookup.get_allowance(row_id)))


@bp.route("/allowances", methods=["GET"])
def list_allowances():
    authenticate(ALL_ROLES)
    rows = db.all_of("allowances")
    for key in ("folio_id", "business_date_id", "reverses_allowance_id",
                "status", "reason_code", "required_approval_role"):
        value = shapes.q(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, meta = shapes.page(rows, serial.allowance_out)
    return response.collection(items, meta)
