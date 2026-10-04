"""ClientAccount endpoints (PRD 3.1, 3.4)."""

from flask import Blueprint

from db import db, serialize
from errors import ApiError, bad_request, invalid_state
from middleware import (
    authenticate,
    body,
    enum,
    require_int,
    require_str,
)
from response import ok
from services import scoring, state
from timeutil import parse_dt
from routes._common import require_client

bp = Blueprint("clients", __name__)

REGIONS = ("NA", "EMEA", "APAC")
REPRINT_TIERS = ("NONE", "STANDARD", "PREMIUM")
DECISIONS = ("RENEW", "CHURN")


def _instant(data, field):
    value = require_str(data, field)
    parsed = parse_dt(value)
    if parsed is None:
        raise bad_request("Field %s must be an ISO 8601 instant." % field)
    return parsed


@bp.post("/research/clients")
def create_client():
    authenticate(["PlatformAdmin"])
    data = body()
    legal_name = require_str(data, "legal_name")
    industry = require_str(data, "industry")
    region = enum(require_str(data, "region"), REGIONS, "region")
    contract_start = _instant(data, "contract_start_utc")
    contract_end = _instant(data, "contract_end_utc")
    seat_count = require_int(data, "seat_count_contracted")
    if seat_count < 1:
        raise bad_request("seat_count_contracted must be at least 1.")
    allowance = require_int(data, "inquiry_allowance_total")
    if allowance < 0:
        raise bad_request("inquiry_allowance_total must be at least 0.")
    reprint_tier = enum(require_str(data, "reprint_tier"), REPRINT_TIERS, "reprint_tier")

    account = db.create(
        legal_name=legal_name,
        industry=industry,
        region=region,
        contract_status="ACTIVE",
        contract_start_utc=contract_start,
        contract_end_utc=contract_end,
        seat_count_contracted=seat_count,
        inquiry_allowance_total=allowance,
        reprint_tier=reprint_tier,
        active_seat_count=0,
        provisioned_seat_count=0,
        revoked_seat_count=0,
        consumed_inquiry_units=0,
        reserved_inquiry_units=0,
        remaining_reserved_units=allowance,
        remaining_consumed_units=allowance,
        utilization_score=0.0,
        utilization_score_active_weighted=0.0,
        renewal_posture="HEALTHY",
        renewal_decided_at=None,
    )
    db.clients[account["id"]] = account
    scoring.refresh_account(account)
    return ok(serialize(account), 201)


@bp.get("/research/clients/<client_id>")
def read_client(client_id):
    authenticate(["PlatformAdmin", "ClientAdmin", "ResearchDirector", "ComplianceOfficer"])
    account = require_client(client_id)
    state.refresh_account_state(account)
    return ok(serialize(account), 200)


@bp.post("/research/clients/<client_id>/renewal-decisions")
def renewal_decision(client_id):
    authenticate(["ResearchDirector", "PlatformAdmin"])
    data = body()
    decision = enum(require_str(data, "decision"), DECISIONS, "decision")
    account = require_client(client_id)
    state.refresh_account_state(account)

    if account.get("contract_status") != "RENEWAL_REVIEW":
        raise invalid_state(
            "The account is not in RENEWAL_REVIEW; a renewal decision is not available."
        )

    if decision == "RENEW":
        if account.get("utilization_score_active_weighted", 0) < 40:
            raise ApiError(
                "ERR_RENEWAL_UTILIZATION_TOO_LOW",
                "The ACTIVE_WEIGHTED utilization score is below 40.",
                409,
            )
        provisioned = [s for s in scoring.seats_of(account["id"]) if s.get("status") == "PROVISIONED"]
        if provisioned:
            raise ApiError(
                "ERR_RENEWAL_UTILIZATION_TOO_LOW",
                "Every contracted seat must be activated or revoked before renewal.",
                409,
            )
        account["contract_status"] = "RENEWED"
        account["renewal_decided_at"] = db.now()
        scoring.apply_derived(account)
        db.touch(account)
        return ok(serialize(account), 200)

    # CHURN: the cascade revokes every ACTIVE seat and stops there.
    account["contract_status"] = "CHURNED"
    account["renewal_decided_at"] = db.now()
    for seat_obj in scoring.seats_of(account["id"]):
        if seat_obj.get("status") == "ACTIVE":
            seat_obj["status"] = "REVOKED"
            seat_obj["revoked_at"] = db.now()
            seat_obj["entitlement_document_types"] = []
            db.touch(seat_obj)
    scoring.apply_derived(account)
    db.touch(account)
    return ok(serialize(account), 200)
