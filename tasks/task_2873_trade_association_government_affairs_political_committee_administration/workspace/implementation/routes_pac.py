"""PAC prior approvals, segregated fund, candidates and contributions (PRD 3.8, 3.9)."""
from decimal import Decimal

from flask import Blueprint, g

import derive
from constants import (
    API_PREFIX, FILING_FEE_BASE_CENTS, INCUMBENCIES, JURISDICTIONS, LATE_PENALTY_CENTS,
    OFFICES, RESTRICTED_SURCHARGE_CENTS,
)
from core import (
    arg, authenticate, body, clock_date, coll, fail, filtered, format_instant, insert,
    iso_date, member_scope, now_dt, parse_date, respond, touch,
)
from serializers import dump, listing
from validate import get_date, get_district, get_enum, get_int, get_pct, get_str

bp = Blueprint("pac", __name__, url_prefix=API_PREFIX)

PAC_READ_ROLES = ["GovAffairsDirector", "ComplianceOfficer", "BoardTrustee"]


def _sync_member_solicitable(member_id):
    member = coll("members").get(member_id)
    if member is None:
        return
    snap = derive.snapshot(member, ("pac_solicitable",))
    member["pac_solicitable"] = derive.member_pac_solicitable(member)
    derive.touch_if_changed(member, snap)


# --------------------------------------------------------------------------- #
# Prior approvals
# --------------------------------------------------------------------------- #
@bp.post("/prior-approvals")
def request_prior_approval():
    authenticate(["ComplianceOfficer"])
    payload = body()
    member_id = get_str(payload, "member_id")
    calendar_year = get_int(payload, "calendar_year", minimum=2020, maximum=2100)
    solicitable_class_size = get_int(payload, "solicitable_class_size", minimum=1)
    effective_date = get_date(payload, "effective_date")
    expires_at_date = get_date(payload, "expires_at_date")
    member = derive.lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    for approval in derive.approvals_of_member(member_id):
        if approval["status"] not in ("REQUESTED", "GRANTED"):
            continue
        if derive.windows_collide(effective_date, expires_at_date,
                                  parse_date(approval["effective_date"]),
                                  parse_date(approval["expires_at_date"])):
            fail("ERR_PRIOR_APPROVAL_WINDOW_CONFLICT",
                 "This member already holds an approval window covering those days.")
    if effective_date > expires_at_date:
        fail("ERR_PRIOR_APPROVAL_WINDOW_INVALID",
             "effective_date must not fall after expires_at_date.")
    if effective_date.year != calendar_year or expires_at_date.year != calendar_year:
        fail("ERR_PRIOR_APPROVAL_WINDOW_INVALID",
             "Both window endpoints must fall inside calendar_year %s." % calendar_year)
    if (expires_at_date - effective_date).days > 365:
        fail("ERR_PRIOR_APPROVAL_WINDOW_INVALID", "The window may span no more than 365 days.")
    if solicitable_class_size > member["restricted_class_size"]:
        fail("ERR_CLASS_SIZE_EXCEEDED",
             "solicitable_class_size exceeds the member's restricted_class_size.")
    approval = insert("approvals", {
        "member_id": member_id,
        "calendar_year": calendar_year,
        "solicitable_class_size": solicitable_class_size,
        "effective_date": iso_date(effective_date),
        "expires_at_date": iso_date(expires_at_date),
        "status": "REQUESTED",
        "authorized_by_name": None,
        "granted_at": None,
        "granted_by_user_id": None,
        "revoked_at": None,
    })
    return respond(dump("approvals", approval), status=201)


@bp.post("/prior-approvals/<approval_id>/grant")
def grant_prior_approval(approval_id):
    authenticate(["MemberDelegate"])
    approval = derive.lookup("approvals", approval_id, "ERR_PRIOR_APPROVAL_NOT_FOUND")
    member_scope(approval["member_id"])
    payload = body()
    authorized_by_name = get_str(payload, "authorized_by_name", max_len=200)
    if approval["status"] != "REQUESTED":
        fail("ERR_INVALID_PRIOR_APPROVAL_STATE",
             "Only a REQUESTED prior approval can be granted.")
    member = derive.lookup("members", approval["member_id"], "ERR_MEMBER_NOT_FOUND")
    if member["status"] != "ACTIVE":
        fail("ERR_MEMBER_NOT_ACTIVE", "The granting member is not ACTIVE.")
    if clock_date() > parse_date(approval["expires_at_date"]):
        fail("ERR_PRIOR_APPROVAL_EXPIRED", "This approval window has already elapsed.")
    approval["status"] = "GRANTED"
    approval["authorized_by_name"] = authorized_by_name
    approval["granted_at"] = format_instant(now_dt())
    approval["granted_by_user_id"] = g.user_id
    touch(approval)
    _sync_member_solicitable(approval["member_id"])
    return respond(dump("approvals", approval))


@bp.post("/prior-approvals/<approval_id>/revoke")
def revoke_prior_approval(approval_id):
    authenticate(["MemberDelegate"])
    approval = derive.lookup("approvals", approval_id, "ERR_PRIOR_APPROVAL_NOT_FOUND")
    member_scope(approval["member_id"])
    if approval["status"] != "GRANTED":
        fail("ERR_INVALID_PRIOR_APPROVAL_STATE", "Only a GRANTED prior approval can be revoked.")
    approval["status"] = "REVOKED"
    approval["revoked_at"] = format_instant(now_dt())
    touch(approval)
    _sync_member_solicitable(approval["member_id"])
    return respond(dump("approvals", approval))


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #
@bp.post("/candidates")
def register_candidate():
    authenticate(["GovAffairsDirector"])
    payload = body()
    name = get_str(payload, "name", max_len=200)
    office = get_enum(payload, "office", OFFICES)
    jurisdiction_code = get_enum(payload, "jurisdiction_code", JURISDICTIONS)
    district_code = get_district(payload, "district_code")
    election_cycle = get_str(payload, "election_cycle", max_len=50)
    incumbency = get_enum(payload, "incumbency", INCUMBENCIES)
    voting_alignment_pct = get_pct(payload, "voting_alignment_pct")
    committee_relevance_score = get_int(payload, "committee_relevance_score",
                                       minimum=0, maximum=100)
    candidate = insert("candidates", {
        "name": name,
        "office": office,
        "jurisdiction_code": jurisdiction_code,
        "district_code": district_code,
        "election_cycle": election_cycle,
        "incumbency": incumbency,
        "voting_alignment_pct": float(voting_alignment_pct),
        "committee_relevance_score": committee_relevance_score,
        "latest_support_score": 0.0,
        "pending_support_cents": 0,
        "committed_support_cents": 0,
        "disbursed_support_cents": 0,
    })
    return respond(dump("candidates", candidate), status=201)


@bp.get("/candidates/<candidate_id>")
def read_candidate(candidate_id):
    authenticate(PAC_READ_ROLES)
    return respond(dump("candidates", derive.lookup(
        "candidates", candidate_id, "ERR_CANDIDATE_NOT_FOUND")))


@bp.get("/candidates/<candidate_id>/pac-contributions")
def list_candidate_contributions(candidate_id):
    authenticate(PAC_READ_ROLES)
    derive.lookup("candidates", candidate_id, "ERR_CANDIDATE_NOT_FOUND")
    rows = filtered(derive.candidate_contributions(candidate_id), status=arg("status"))
    return listing("contributions", rows)


# --------------------------------------------------------------------------- #
# Separate segregated fund
# --------------------------------------------------------------------------- #
def _fund(fund_id):
    return derive.lookup("funds", fund_id, "ERR_FUND_NOT_FOUND")


@bp.post("/segregated-funds")
def open_fund():
    authenticate(["ComplianceOfficer"])
    payload = body()
    name = get_str(payload, "name", max_len=200)
    fund_year = get_int(payload, "fund_year", minimum=2020, maximum=2100)
    jurisdiction_code = get_enum(payload, "jurisdiction_code", JURISDICTIONS)
    min_reserve_cents = get_int(payload, "min_reserve_cents", minimum=0)
    fund = insert("funds", {
        "name": name,
        "fund_year": fund_year,
        "jurisdiction_code": jurisdiction_code,
        "min_reserve_cents": min_reserve_cents,
        "receipts_total_cents": 0,
        "committed_balance_cents": 0,
        "disbursed_total_cents": 0,
        "filing_fee_accrued_cents": 0,
        "available_balance_cents": 0,
        "posture": "OPEN",
        "filings_completed_count": 0,
        "last_filed_period_code": None,
    })
    return respond(dump("funds", fund), status=201)


@bp.get("/segregated-funds/<fund_id>")
def read_fund(fund_id):
    authenticate(PAC_READ_ROLES)
    return respond(dump("funds", _fund(fund_id)))


@bp.get("/segregated-funds/<fund_id>/pac-contributions")
def list_fund_contributions(fund_id):
    authenticate(PAC_READ_ROLES)
    _fund(fund_id)
    rows = filtered(derive.fund_contributions(fund_id), status=arg("status"))
    return listing("contributions", rows)


@bp.post("/segregated-funds/<fund_id>/receipts")
def credit_receipt(fund_id):
    authenticate(["ComplianceOfficer"])
    fund = _fund(fund_id)
    payload = body()
    member_id = get_str(payload, "member_id")
    amount_cents = get_int(payload, "amount_cents", minimum=1)
    received_date = get_date(payload, "received_date")
    derive.lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    if derive.granted_approval_covering(member_id, clock_date()) is None:
        fail("ERR_PRIOR_APPROVAL_NOT_GRANTED",
             "This member holds no GRANTED prior approval covering today.")
    if received_date.year != fund["fund_year"]:
        fail("ERR_JURISDICTION_SCOPE_MISMATCH",
             "received_date must fall inside the fund's accounting year %s." % fund["fund_year"])
    snap = derive.snapshot(fund, derive.FUND_TRACKED)
    fund["receipts_total_cents"] = fund["receipts_total_cents"] + amount_cents
    derive.settle_fund(fund)
    derive.touch_if_changed(fund, snap)
    return respond(dump("funds", fund))


@bp.post("/segregated-funds/<fund_id>/filing-cycle")
def run_filing_cycle(fund_id):
    authenticate(["ComplianceOfficer"])
    fund = _fund(fund_id)
    payload = body()
    period_code = get_str(payload, "period_code", max_len=20)
    filed_on_date = get_date(payload, "filed_on_date")
    _start, _end, due, _cadence = derive.require_period(period_code, fund["jurisdiction_code"])
    snap = derive.snapshot(fund, derive.FUND_TRACKED)
    # STEP 1-2: the fee is assembled from the pre-cycle balance and pre-cycle posture.
    derive.compute_fund_balances(fund)
    pre_posture = derive.posture_for(fund)
    fee = FILING_FEE_BASE_CENTS
    if pre_posture == "RESTRICTED":
        fee += RESTRICTED_SURCHARGE_CENTS
    if filed_on_date > due:
        fee += LATE_PENALTY_CENTS
    # STEP 3-4: accrue the fee, then recompute the balance and propagate the posture.
    fund["filing_fee_accrued_cents"] = fund["filing_fee_accrued_cents"] + fee
    fund["filings_completed_count"] = fund["filings_completed_count"] + 1
    fund["last_filed_period_code"] = period_code
    fund["posture"] = pre_posture
    derive.settle_fund(fund)
    derive.touch_if_changed(fund, snap)
    # STEP 5: sweep every prior approval whose window has closed.
    today = clock_date()
    for approval in derive.rows_of("approvals"):
        if approval["status"] not in ("REQUESTED", "GRANTED"):
            continue
        if parse_date(approval["expires_at_date"]) >= today:
            continue
        was_granted = approval["status"] == "GRANTED"
        approval["status"] = "EXPIRED"
        touch(approval)
        if was_granted:
            _sync_member_solicitable(approval["member_id"])
    return respond(dump("funds", fund))


# --------------------------------------------------------------------------- #
# PAC contributions
# --------------------------------------------------------------------------- #
def _contribution(contribution_id):
    return derive.lookup("contributions", contribution_id, "ERR_CONTRIBUTION_NOT_FOUND")


def _settle(fund, candidate_ids):
    snap = derive.snapshot(fund, derive.FUND_TRACKED)
    derive.settle_fund(fund)
    derive.touch_if_changed(fund, snap)
    derive.refresh_candidates(candidate_ids)


@bp.post("/pac-contributions")
def propose_contribution():
    authenticate(["GovAffairsDirector"])
    payload = body()
    fund_id = get_str(payload, "fund_id")
    candidate_id = get_str(payload, "candidate_id")
    amount_cents = get_int(payload, "amount_cents", minimum=1)
    memo = get_str(payload, "memo", required=False, max_len=1000, allow_blank=True)
    _fund(fund_id)
    candidate = derive.lookup("candidates", candidate_id, "ERR_CANDIDATE_NOT_FOUND")
    score = derive.candidate_support_score(candidate)
    max_allowed_cents, _limit = derive.contribution_allowance(candidate, score)
    if amount_cents > max_allowed_cents:
        fail("ERR_CONTRIBUTION_LIMIT_EXCEEDED",
             "amount_cents %s exceeds max_allowed_cents %s." % (amount_cents, max_allowed_cents))
    contribution = insert("contributions", {
        "fund_id": fund_id,
        "candidate_id": candidate_id,
        "amount_cents": amount_cents,
        "memo": memo,
        "support_score": float(score),
        "max_allowed_cents": max_allowed_cents,
        "status": "PENDING_BOARD",
        "proposed_by_user_id": g.user_id,
        "board_approved_by_user_id": None,
        "disbursed_at": None,
        "voided_at": None,
        "void_reason": None,
    })
    snap = derive.snapshot(candidate, derive.CANDIDATE_TRACKED)
    derive.compute_candidate_totals(candidate)
    candidate["latest_support_score"] = float(score)
    derive.touch_if_changed(candidate, snap)
    return respond(dump("contributions", contribution), status=201)


@bp.get("/pac-contributions/<contribution_id>")
def read_contribution(contribution_id):
    authenticate(PAC_READ_ROLES)
    return respond(dump("contributions", _contribution(contribution_id)))


@bp.post("/pac-contributions/<contribution_id>/board-approve")
def board_approve(contribution_id):
    authenticate(["BoardTrustee"])
    contribution = _contribution(contribution_id)
    if contribution["status"] == "SUSPENDED":
        fail("ERR_CONTRIBUTION_SUSPENDED",
             "The fund's restricted posture has suspended this contribution.")
    if contribution["status"] != "PENDING_BOARD":
        fail("ERR_CONTRIBUTION_NOT_PENDING", "This contribution is not PENDING_BOARD.")
    if contribution["proposed_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "A contribution may not be approved by the operator who proposed it.")
    fund = _fund(contribution["fund_id"])
    if fund["posture"] != "OPEN":
        fail("ERR_FUND_RESTRICTED", "The fund's posture is RESTRICTED.")
    if contribution["amount_cents"] > fund["available_balance_cents"]:
        fail("ERR_INSUFFICIENT_FUND_BALANCE",
             "The fund's available balance does not cover this contribution.")
    contribution["status"] = "BOARD_APPROVED"
    contribution["board_approved_by_user_id"] = g.user_id
    touch(contribution)
    _settle(fund, [contribution["candidate_id"]])
    return respond(dump("contributions", contribution))


@bp.post("/pac-contributions/<contribution_id>/disburse")
def disburse_contribution(contribution_id):
    authenticate(["ComplianceOfficer"])
    contribution = _contribution(contribution_id)
    if contribution["status"] != "BOARD_APPROVED":
        fail("ERR_CONTRIBUTION_NOT_APPROVED", "Only a BOARD_APPROVED contribution is disbursed.")
    candidate = derive.lookup("candidates", contribution["candidate_id"],
                              "ERR_CANDIDATE_NOT_FOUND")
    limit = derive.rule(candidate["jurisdiction_code"])["per_candidate_election_limit_cents"]
    if contribution["amount_cents"] > contribution["max_allowed_cents"]:
        fail("ERR_CONTRIBUTION_LIMIT_EXCEEDED",
             "The contribution now exceeds its frozen max_allowed_cents.")
    if derive.candidate_absorbed_cents(candidate) > limit:
        fail("ERR_CONTRIBUTION_LIMIT_EXCEEDED",
             "The candidate's counted total exceeds the per-candidate limit.")
    contribution["status"] = "DISBURSED"
    contribution["disbursed_at"] = format_instant(now_dt())
    touch(contribution)
    _settle(_fund(contribution["fund_id"]), [contribution["candidate_id"]])
    return respond(dump("contributions", contribution))


@bp.post("/pac-contributions/<contribution_id>/void")
def void_contribution(contribution_id):
    authenticate(["ComplianceOfficer"])
    contribution = _contribution(contribution_id)
    payload = body()
    void_reason = get_str(payload, "void_reason", max_len=500)
    if contribution["status"] not in derive.ABSORBING_STATUSES:
        fail("ERR_CONTRIBUTION_NOT_PENDING", "This contribution has already been voided.")
    contribution["status"] = "VOIDED"
    contribution["voided_at"] = format_instant(now_dt())
    contribution["void_reason"] = void_reason
    touch(contribution)
    _settle(_fund(contribution["fund_id"]), [contribution["candidate_id"]])
    return respond(dump("contributions", contribution))
