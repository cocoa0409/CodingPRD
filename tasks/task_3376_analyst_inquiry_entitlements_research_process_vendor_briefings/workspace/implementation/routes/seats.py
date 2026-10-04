"""Seat endpoints (PRD 3.1)."""

import math

from flask import Blueprint, request

from db import db, serialize
from errors import ApiError, bad_request, invalid_state, unauthorized
from middleware import (
    authenticate,
    body,
    enum,
    optional_str,
    require_str,
)
from response import ok, ok_list
from services import scoring
from routes._common import page_of, require_client, require_seat

bp = Blueprint("seats", __name__)

RESEARCH_ROLES = ("EXECUTIVE_VIEWER", "PRACTITIONER", "ARCHITECT", "STRATEGIST")
SEAT_KINDS = ("NAMED", "SHARED")
SEAT_STATUSES = ("PROVISIONED", "ACTIVE", "REVOKED")
DOC_TYPES = (
    "MARKET_GUIDE",
    "COMPARATIVE_MATRIX",
    "HYPE_PROFILE",
    "CRITICAL_CAPABILITIES",
)


def _check_account_ownership(role, user_id, account_id):
    if role == "ClientAdmin" and user_id != account_id:
        raise unauthorized("A ClientAdmin may only act for its own ClientAccount.")


def _overrides(data):
    value = data.get("entitlement_override_types", [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise bad_request("entitlement_override_types must be an array.")
    for item in value:
        if not isinstance(item, str):
            raise bad_request("entitlement_override_types members must be strings.")
        if item not in DOC_TYPES:
            raise bad_request("Unknown document type in entitlement_override_types: %s" % item)
    return list(value)


@bp.post("/research/seats")
def create_seat():
    role, user_id = authenticate(["ClientAdmin", "PlatformAdmin"])
    data = body()
    account_id = require_str(data, "client_account_id")
    seat_email = require_str(data, "seat_email")
    research_role = enum(require_str(data, "research_role"), RESEARCH_ROLES, "research_role")
    seat_kind = enum(optional_str(data, "seat_kind", "NAMED") or "NAMED", SEAT_KINDS, "seat_kind")
    overrides = _overrides(data)

    account = require_client(account_id)
    _check_account_ownership(role, user_id, account["id"])

    for existing in scoring.seats_of(account["id"]):
        if existing.get("seat_email") == seat_email:
            raise ApiError(
                "ERR_DUPLICATE_SEAT_EMAIL",
                "seat_email already exists on this ClientAccount.",
                409,
            )

    seat_obj = db.create(
        client_account_id=account["id"],
        seat_email=seat_email,
        research_role=research_role,
        seat_kind=seat_kind,
        status="PROVISIONED",
        activated_at=None,
        revoked_at=None,
        entitlement_document_types=[],
        entitlement_override_types=overrides,
        last_inquiry_at=None,
    )
    db.seats[seat_obj["id"]] = seat_obj
    scoring.refresh_account(account)
    return ok(serialize(seat_obj), 201)


@bp.get("/research/seats/<seat_id>")
def read_seat(seat_id):
    authenticate([
        "ClientAdmin",
        "PlatformAdmin",
        "SeatHolder",
        "ResearchDirector",
        "ComplianceOfficer",
    ])
    return ok(serialize(require_seat(seat_id)), 200)


@bp.get("/research/seats")
def list_seats():
    authenticate(["ClientAdmin", "PlatformAdmin", "ResearchDirector", "ComplianceOfficer"])
    items = list(db.seats.values())
    account_id = request.args.get("client_account_id")
    status = request.args.get("status")
    research_role = request.args.get("research_role")
    if account_id:
        items = [s for s in items if s.get("client_account_id") == account_id]
    if status:
        items = [s for s in items if s.get("status") == status]
    if research_role:
        items = [s for s in items if s.get("research_role") == research_role]
    page, limit, offset, total = page_of(items)
    return ok_list(page, limit, offset, total)


@bp.post("/research/seats/<seat_id>/activate")
def activate_seat(seat_id):
    role, user_id = authenticate(["ClientAdmin", "PlatformAdmin"])
    seat_obj = require_seat(seat_id)
    _check_account_ownership(role, user_id, seat_obj.get("client_account_id"))
    account = require_client(seat_obj.get("client_account_id"))

    if seat_obj.get("status") != "PROVISIONED":
        raise invalid_state("Only a PROVISIONED seat can be activated.")
    if account.get("contract_status") != "ACTIVE":
        raise invalid_state("The owning account's contract is not ACTIVE.")

    seat_obj["status"] = "ACTIVE"
    seat_obj["activated_at"] = db.now()
    seat_obj["entitlement_document_types"] = scoring.entitlement_types(
        seat_obj.get("research_role"), seat_obj.get("entitlement_override_types")
    )
    db.touch(seat_obj)
    scoring.refresh_account(account)
    return ok(serialize(seat_obj), 200)


@bp.post("/research/seats/<seat_id>/revoke")
def revoke_seat(seat_id):
    role, user_id = authenticate(["ClientAdmin", "PlatformAdmin"])
    seat_obj = require_seat(seat_id)
    _check_account_ownership(role, user_id, seat_obj.get("client_account_id"))
    account = require_client(seat_obj.get("client_account_id"))

    current = seat_obj.get("status")
    if current not in ("PROVISIONED", "ACTIVE"):
        raise invalid_state("A REVOKED seat is terminal and cannot be revoked again.")

    seat_obj["status"] = "REVOKED"
    seat_obj["revoked_at"] = db.now()
    if current == "ACTIVE":
        seat_obj["entitlement_document_types"] = []
    db.touch(seat_obj)

    scoring.apply_derived(account)
    db.touch(account)

    contracted = account.get("seat_count_contracted", 0)
    if (
        account.get("contract_status") == "ACTIVE"
        and account.get("active_seat_count", 0) < math.ceil(contracted / 2.0)
    ):
        account["contract_status"] = "RENEWAL_REVIEW"
        db.touch(account)
    return ok(serialize(seat_obj), 200)
