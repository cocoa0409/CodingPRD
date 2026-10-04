"""Workforce contracts, compliance reviews, and milestone attestation."""
from flask import Blueprint, request

import errors
from clock import now
from db import store
from envelope import success
from serializers import ser_contract, ser_milestone
from services import (
    maybe_auto_close_contract,
    new_entity,
    org_of_contract,
    org_of_milestone,
    recompute_posture,
    touch,
)
from validate import auth, field, get_body, paginate, require_role, sort_created

bp = Blueprint("contracts", __name__)


def _get_org(oid):
    org = store.member_orgs.get(oid)
    if org is None:
        errors.not_found("MemberOrg not found")
    return org


@bp.post("/donated-goods/workforce-contracts")
def create_contract():
    body = get_body()
    member_org_id = field(body, "member_org_id", "str", required=True)
    agency = field(body, "funding_agency", "str", required=True)
    start_date = field(body, "start_date", "datetime", required=True)
    end_date = field(body, "end_date", "datetime", required=True)
    value = field(body, "contract_value_cents", "int", required=True)
    headcount = field(body, "enrolled_headcount", "int", required=True)
    milestones_in = field(body, "milestones", "list", required=True)
    parsed = []
    for entry in milestones_in:
        if not isinstance(entry, dict):
            errors.invalid_request("Each milestone must be an object")
        desc = field(entry, "description", "str", required=True)
        target = field(entry, "target_date", "datetime", required=True)
        min_hc = field(entry, "min_headcount", "int", required=True)
        payout = field(entry, "payout_cents", "int", required=True)
        parsed.append((desc, target, min_hc, payout))
    uid, role = auth()
    require_role(role, {"ContractManager"})
    org = _get_org(member_org_id)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    with store.lock:
        # Closed-interval overlap: [start, end] both inclusive, so windows
        # that merely touch (a.end == b.start) DO overlap.
        for c in store.workforce_contracts.values():
            if (c["member_org_id"] == member_org_id
                    and c["funding_agency"] == agency
                    and start_date <= c["end_date"]
                    and c["start_date"] <= end_date):
                errors.contract_overlap()
        contract = new_entity()
        contract.update({
            "member_org_id": member_org_id,
            "funding_agency": agency,
            "start_date": start_date,
            "end_date": end_date,
            "contract_value_cents": value,
            "enrolled_headcount": headcount,
            "created_by_user_id": uid,
            "status": "ACTIVE",
            "compliance_posture": "COMPLIANT",
            "attested_payout_cents": 0,
            "missed_count": 0,
        })
        store.workforce_contracts[contract["id"]] = contract
        for desc, target, min_hc, payout in parsed:
            m = new_entity()
            m.update({
                "contract_id": contract["id"],
                "description": desc,
                "target_date": target,
                "min_headcount": min_hc,
                "payout_cents": payout,
                "status": "PENDING",
                "attested_by_user_id": None,
            })
            store.milestones[m["id"]] = m
    return success(ser_contract(contract), 201)


@bp.get("/donated-goods/member-orgs/<oid>/workforce-contracts")
def list_contracts(oid):
    auth()
    _get_org(oid)
    items = [c for c in store.workforce_contracts.values()
             if c["member_org_id"] == oid]
    agency = request.args.get("funding_agency")
    status = request.args.get("status")
    if agency is not None:
        items = [c for c in items if c["funding_agency"] == agency]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_contract(c) for c in page], 200,
                   response_type="array", pagination=meta)


def _get_contract(cid):
    contract = store.workforce_contracts.get(cid)
    if contract is None:
        errors.not_found("WorkforceContract not found")
    return contract


@bp.post("/donated-goods/workforce-contracts/<cid>/reviews")
def review_contract(cid):
    body = get_body()
    action = field(body, "action", "str", required=True, enum={"OPEN", "CLOSE"})
    _uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    contract = _get_contract(cid)
    org = org_of_contract(contract)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    with store.lock:
        if action == "OPEN":
            if contract["status"] != "ACTIVE":
                errors.invalid_state("Only an ACTIVE contract can enter review")
            # Attestation is frozen while UNDER_REVIEW.
            contract["status"] = "UNDER_REVIEW"
        else:  # CLOSE
            if contract["status"] != "UNDER_REVIEW":
                errors.invalid_state("Only an UNDER_REVIEW contract can close review")
            contract["status"] = "ACTIVE"
            clock = now()
            for m in store.milestones.values():
                if (m["contract_id"] == cid and m["status"] == "PENDING"
                        and m["target_date"] < clock):
                    m["status"] = "MISSED"
                    touch(m)
            recompute_posture(contract)
            maybe_auto_close_contract(contract)
        touch(contract)
    return success(ser_contract(contract), 200)


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

@bp.get("/donated-goods/milestones")
def list_milestones():
    auth()
    items = list(store.milestones.values())
    for param in ("contract_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [m for m in items if m[param] == val]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_milestone(m) for m in page], 200,
                   response_type="array", pagination=meta)


def _get_milestone(mid):
    milestone = store.milestones.get(mid)
    if milestone is None:
        errors.not_found("ContractMilestone not found")
    return milestone


@bp.get("/donated-goods/milestones/<mid>")
def get_milestone(mid):
    auth()
    return success(ser_milestone(_get_milestone(mid)), 200)


@bp.post("/donated-goods/milestones/<mid>/attest")
def attest_milestone(mid):
    get_body()
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    milestone = _get_milestone(mid)
    contract = store.workforce_contracts[milestone["contract_id"]]
    org = org_of_milestone(milestone)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    # Cross-entity gate: attestation is frozen unless the contract is ACTIVE.
    if milestone["status"] != "PENDING" or contract["status"] != "ACTIVE":
        errors.invalid_state(
            "Milestone must be PENDING and its contract ACTIVE to attest")
    if uid == contract["created_by_user_id"]:
        errors.segregation()
    if contract["enrolled_headcount"] < milestone["min_headcount"]:
        errors.headcount_shortfall()
    with store.lock:
        milestone["status"] = "ATTESTED"
        milestone["attested_by_user_id"] = uid
        # Double credit, in parallel: contract ledger AND the org's SEPARATE
        # contract-revenue ledger (never mingles with retail margin).
        contract["attested_payout_cents"] += milestone["payout_cents"]
        org["contract_revenue_cents"] += milestone["payout_cents"]
        maybe_auto_close_contract(contract)
        touch(milestone)
        touch(contract)
    return success(ser_milestone(milestone), 200)
