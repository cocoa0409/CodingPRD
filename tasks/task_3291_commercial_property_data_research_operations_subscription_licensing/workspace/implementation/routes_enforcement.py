"""EnforcementCase endpoints, escalations, settlements and market re-grading (PRD 3.7)."""
from flask import Blueprint, request

import auth
import calc
import core
import lookups
import responses
from serializers import enforcement_case as ser_case

bp = Blueprint("enforcement", __name__, url_prefix="/data-research")

CASE_TYPES = {"AUDIT", "LITIGATION"}


def _terminate(contract):
    contract["status"] = "TERMINATED"
    core.touch(contract)
    for seat in lookups.seats_of(contract["id"]):
        seat["access_revoked"] = True
        seat["shared_flag"] = False
        core.touch(seat)


@bp.post("/enforcement-cases")
def create_case():
    auth.authorize(["EnforcementOfficer"])
    payload = core.body_of(request)
    organization_id = core.require_string(payload, "organization_id")
    contract_id = core.require_string(payload, "contract_id")
    case_type = core.require_enum(payload, "case_type", CASE_TYPES)
    finding_cents = core.require_int(payload, "finding_cents")
    fee_rate_pct = core.optional_number(payload, "fee_rate_pct", None)
    if fee_rate_pct is None:
        raise core.ApiError("ERR_INVALID_REQUEST", "Missing required field 'fee_rate_pct'.")
    org = lookups.get_organization(organization_id)
    contract = lookups.get_contract(contract_id)

    if finding_cents < 0:
        raise core.ApiError("ERR_INVALID_REQUEST", "finding_cents must be zero or greater.")

    penalty, _escalatable = calc.enforcement_penalty(finding_cents, fee_rate_pct)
    record = {
        "organization_id": org["id"],
        "contract_id": contract["id"],
        "case_type": case_type,
        "finding_cents": finding_cents,
        "fee_rate_pct": float(fee_rate_pct),
        "penalty_cents": penalty,
        "escalated_at": None,
        "escalated_from_case_id": None,
        "status": "OPEN",
    }
    core.stamp_created(record)
    core.enforcement_cases[record["id"]] = record
    return responses.ok_object(ser_case(record), 201)


@bp.get("/enforcement-cases")
def list_cases():
    auth.authorize(["EnforcementOfficer", "LicensingAdmin", "PlatformAdmin"])
    limit, offset = core.pagination_args(request)
    rows = list(core.enforcement_cases.values())
    for param, field in (
        ("organization_id", "organization_id"),
        ("contract_id", "contract_id"),
        ("escalated_from_case_id", "escalated_from_case_id"),
        ("status", "status"),
    ):
        wanted = request.args.get(param)
        if wanted:
            rows = [c for c in rows if c[field] == wanted]
    return responses.paged(rows, limit, offset, ser_case)


@bp.get("/enforcement-cases/<case_id>")
def get_case(case_id):
    auth.authorize(["EnforcementOfficer", "LicensingAdmin", "PlatformAdmin"])
    record = lookups.get_case(case_id)
    return responses.ok_object(ser_case(record))


@bp.get("/enforcement-cases/<case_id>/escalations")
def list_escalations(case_id):
    auth.authorize(["EnforcementOfficer", "LicensingAdmin"])
    lookups.get_case(case_id)
    limit, offset = core.pagination_args(request)
    rows = [c for c in core.enforcement_cases.values()
            if c["escalated_from_case_id"] == case_id]
    return responses.paged(rows, limit, offset, ser_case)


@bp.post("/enforcement-cases/<case_id>/escalations")
def escalate_case(case_id):
    auth.authorize(["EnforcementOfficer"])
    core.body_of(request)
    record = lookups.get_case(case_id)

    if record["case_type"] != "AUDIT":
        raise core.ApiError("ERR_LITIGATION_NOT_ESCALATABLE")
    if record["status"] != "OPEN":
        raise core.ApiError("ERR_INVALID_STATE")
    if record["penalty_cents"] < core.LITIGATION_PENALTY_THRESHOLD_CENTS:
        raise core.ApiError("ERR_PENALTY_BELOW_LITIGATION_FLOOR")
    contract = lookups.get_contract(record["contract_id"])
    if contract["audit_intensity"] != "ENHANCED":
        raise core.ApiError("ERR_LITIGATION_NOT_PERMITTED")

    record["status"] = "ESCALATED"
    record["escalated_at"] = core.fmt_dt(core.clock.now())
    core.touch(record)

    litigation = {
        "organization_id": record["organization_id"],
        "contract_id": record["contract_id"],
        "case_type": "LITIGATION",
        "finding_cents": record["finding_cents"],
        "fee_rate_pct": record["fee_rate_pct"],
        "penalty_cents": record["penalty_cents"],
        "escalated_at": record["escalated_at"],
        "escalated_from_case_id": record["id"],
        "status": "ESCALATED",
    }
    core.stamp_created(litigation)
    core.enforcement_cases[litigation["id"]] = litigation

    org = lookups.get_organization(record["organization_id"])
    org["status"] = "SUSPENDED"
    core.touch(org)
    terminated = []
    for other in lookups.contracts_of(org["id"]):
        if other["status"] in ("ACTIVE", "GRACE"):
            _terminate(other)
            terminated.append(other["id"])
    record["_terminated_contract_ids"] = terminated
    lookups.recompute_organization_counters(org)
    return responses.ok_object(ser_case(record))


@bp.post("/enforcement-cases/<case_id>/settlements")
def settle_case(case_id):
    auth.authorize(["EnforcementOfficer"])
    payload = core.body_of(request)
    settlement_cents = core.require_int(payload, "settlement_cents")
    record = lookups.get_case(case_id)

    if record["status"] != "ESCALATED":
        raise core.ApiError("ERR_INVALID_STATE")
    if settlement_cents < record["penalty_cents"]:
        raise core.ApiError("ERR_SETTLEMENT_INSUFFICIENT")

    record["status"] = "SETTLED"
    core.touch(record)

    org = lookups.get_organization(record["organization_id"])
    org["status"] = "ACTIVE"
    core.touch(org)
    # Repair the suspension's contract casualties: the contracts this escalation
    # terminated are restored to ACTIVE and their seats' access_revoked reset.
    terminated_ids = record.get("_terminated_contract_ids")
    if terminated_ids is None:
        terminated_ids = [c["id"] for c in lookups.contracts_of(org["id"])
                          if c["status"] == "TERMINATED"]
    for contract_id in terminated_ids:
        contract = core.contracts.get(contract_id)
        if contract is None:
            continue
        contract["status"] = "ACTIVE"
        contract["renewal_decision"] = "NONE"
        core.touch(contract)
        for seat in lookups.seats_of(contract["id"]):
            seat["access_revoked"] = False
            core.touch(seat)
    lookups.recompute_organization_counters(org)
    return responses.ok_object(ser_case(record))


@bp.post("/enforcement-cases/<case_id>/withdrawals")
def withdraw_case(case_id):
    auth.authorize(["EnforcementOfficer"])
    core.body_of(request)
    record = lookups.get_case(case_id)
    if record["status"] != "OPEN":
        raise core.ApiError("ERR_INVALID_STATE")
    record["status"] = "WITHDRAWN"
    core.touch(record)
    return responses.ok_object(ser_case(record))


@bp.post("/reports/market-escalations")
def market_escalations():
    actor = auth.authorize(["EnforcementOfficer", "ResearchAnalyst"])
    payload = core.body_of(request)
    markets = core.require_string_list(payload, "markets")
    core.require_string(payload, "reason_code")
    if actor.user is not None:
        org = lookups.get_organization(actor.user["organization_id"])
        if org["status"] != "ACTIVE":
            raise core.ApiError("ERR_UNAUTHORIZED")

    market_set = set(markets)
    touched = []

    # Pass 1 — DRAFT / RESEARCHING properties become RESTRICTED.
    for prop in list(core.properties.values()):
        if prop["market"] in market_set and prop["research_status"] in ("DRAFT", "RESEARCHING"):
            prop["land_posture"] = "RESTRICTED"
            calc.refresh_property_state(prop, "PROVISIONAL")
            touched.append(prop["id"])

    # Pass 2 — VERIFIED properties are frozen back to RESEARCHING.
    for prop in list(core.properties.values()):
        if prop["market"] in market_set and prop["research_status"] == "VERIFIED":
            prop["research_status"] = "RESEARCHING"
            prop["land_posture"] = "FROZEN"
            for attr in lookups.attributes_of(prop["id"]):
                if attr["proposed_status"] == "PENDING":
                    attr["proposed_status"] = "NONE"
                    attr["proposed_value"] = None
                    core.touch(attr)
            calc.refresh_property_state(prop, "PROVISIONAL")
            touched.append(prop["id"])

    return responses.ok_object({
        "escalated_property_ids": touched,
        "escalated_count": len(touched),
    })