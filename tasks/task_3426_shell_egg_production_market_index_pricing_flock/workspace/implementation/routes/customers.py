"""Customers and commitments (PRD §3.5): onboarding, commitment booking,
activation, and the computed transition-progress fields."""

from flask import Blueprint, request

from auth import authenticate, require_role
from db import STORE, stamp_new, touch
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from helpers import get_commitment, get_customer, list_response
from serialize import serialize_commitment, serialize_customer
from util import PROGRAMS, REGIONS, SEGMENTS, success_object
from validate import apply_values, get_body, validate_payload

bp = Blueprint("customers", __name__)


@bp.route("/api/customers", methods=["POST"])
def create_customer():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    values, _raws = validate_payload(
        get_body(),
        {
            "name": {"kind": "string", "required": True},
            "segment": {"kind": "enum", "required": True, "enum": SEGMENTS},
            "credit_limit_cents": {"kind": "int", "required": True, "gt": 0},
        },
    )
    customer = {
        "name": values["name"],
        "segment": values["segment"],
        "credit_limit_cents": values["credit_limit_cents"],
        "outstanding_cents": 0,
        "status": "ACTIVE",
    }
    stamp_new(customer)
    STORE.customers[customer["id"]] = customer
    return success_object(serialize_customer(customer), 201)


@bp.route("/api/customers/<cid>", methods=["GET"])
def read_customer(cid):
    authenticate()
    return success_object(serialize_customer(get_customer(cid)))


@bp.route("/api/customers/<cid>/commitments", methods=["POST"])
def create_commitment(cid):
    _uid, role = authenticate()
    require_role(role, {"SalesManager"})
    customer = get_customer(cid)
    body = get_body()
    values, raws = validate_payload(
        body,
        {
            "program": {"kind": "enum", "required": True, "enum": PROGRAMS},
            "region_code": {"kind": "enum", "required": True, "enum": REGIONS},
            "weekly_dozen_committed": {"kind": "int", "required": True, "gt": 0},
            "price_adjustment_cents_per_dozen": {"kind": "int", "required": True},
            "effective_from": {"kind": "datetime", "required": True},
            "effective_to": {"kind": "datetime", "required": True},
            "cage_free_transition_deadline": {"kind": "datetime"},
            "required_cage_free_pct": {
                "kind": "number", "default": 0, "ge": 0, "le": 1,
            },
        },
    )
    if not values["effective_from"] < values["effective_to"]:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "effective_from must precede effective_to",
        )
    commitment = {
        "customer_id": customer["id"],
        "program": values["program"],
        "region_code": values["region_code"],
        "weekly_dozen_committed": values["weekly_dozen_committed"],
        "price_adjustment_cents_per_dozen": values[
            "price_adjustment_cents_per_dozen"
        ],
        "required_cage_free_pct": values["required_cage_free_pct"],
        "cage_free_transition_deadline": None,
        "_dt_cage_free_transition_deadline": None,
        "blocked_order_count": 0,
        "status": "PENDING",
    }
    apply_values(
        commitment,
        {"effective_from": values["effective_from"],
         "effective_to": values["effective_to"]},
        {"effective_from": raws["effective_from"],
         "effective_to": raws["effective_to"]},
    )
    if values.get("cage_free_transition_deadline") is not None:
        apply_values(
            commitment,
            {"cage_free_transition_deadline": values["cage_free_transition_deadline"]},
            {"cage_free_transition_deadline": raws["cage_free_transition_deadline"]},
        )
    stamp_new(commitment)
    STORE.commitments[commitment["id"]] = commitment
    return success_object(serialize_commitment(commitment), 201)


@bp.route("/api/commitments", methods=["GET"])
def list_commitments():
    authenticate()
    items = list(STORE.commitments.values())
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [c for c in items if c["customer_id"] == customer_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, serialize_commitment)


@bp.route("/api/commitments/<cid>", methods=["GET"])
def read_commitment(cid):
    authenticate()
    return success_object(serialize_commitment(get_commitment(cid)))


@bp.route("/api/commitments/<cid>/activate", methods=["POST"])
def activate_commitment(cid):
    _uid, role = authenticate()
    require_role(role, {"SalesManager"})
    commitment = get_commitment(cid)
    validate_payload(get_body(), {})
    if commitment["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "commitment is not PENDING")
    customer = STORE.customers.get(commitment["customer_id"])
    if customer is None or customer["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "customer is not ACTIVE")
    commitment["status"] = "ACTIVE"
    touch(commitment)
    return success_object(serialize_commitment(commitment))
