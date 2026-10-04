"""Rulemaking domain: TransactionCodes, RuleProposals (+ close-ballot),
Ballots, and GuidanceDocuments (PRD sections 3.3 and 3.4)."""
import re
from datetime import timedelta

from flask import Blueprint, g, request

from auth import ROLES, require_roles
from clock import CLOCK, render_date, render_ts, render_ts3
from envelope import ok
from errors import fail
from store import DB, add_record, touch
from validation import (
    get_body,
    list_response,
    optional_bool,
    optional_nullable_date,
    require_bool,
    require_date,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("rulemaking", __name__)

ENTRY_CLASSES = ("DEBIT", "CREDIT")
AUTHORIZATION_TYPES = ("WRITTEN_SIGNED", "ORAL_RECORDED", "IMPLIED", "NONE")
PROPOSAL_STATES = (
    "DRAFT",
    "COMMENT_OPEN",
    "BALLOTING",
    "PASSED",
    "REJECTED",
    "RETURNED_FOR_REWORK",
    "EFFECTIVE",
    "SUPERSEDED",
)
VOTES = ("YEA", "NAY", "ABSTAIN")
_CODE_RE = re.compile(r"[A-Z]{2,3}")

# ballot_outcome_tally constants (exact integer cross-multiplication)
QUORUM_NUM = 1
QUORUM_DEN = 2
APPROVAL_NUM = 2
APPROVAL_DEN = 3

_TALLY_FIELD = {"YEA": "yea_count", "NAY": "nay_count", "ABSTAIN": "abstain_count"}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_transaction_code(tc):
    return {
        "id": tc["id"],
        "code": tc["code"],
        "entry_class": tc["entry_class"],
        "authorization_requirement": tc["authorization_requirement"],
        "return_timeframe_banking_days": tc["return_timeframe_banking_days"],
        "account_validation_required": tc["account_validation_required"],
        "warranty_obligations": tc["warranty_obligations"],
        "created_at": render_ts3(tc["created_at"]),
        "updated_at": render_ts3(tc["updated_at"]),
        "version": tc["version"],
    }


def serialize_proposal(rp):
    return {
        "id": rp["id"],
        "transaction_code_id": rp["transaction_code_id"],
        "title": rp["title"],
        "summary": rp["summary"],
        "effective_date": render_date(rp["effective_date"]),
        "status": rp["status"],
        "outcome": rp["outcome"],
        "comment_opened_at": render_ts(rp["comment_opened_at"]),
        "ballot_opened_at": render_ts(rp["ballot_opened_at"]),
        "yea_count": rp["yea_count"],
        "nay_count": rp["nay_count"],
        "abstain_count": rp["abstain_count"],
        "created_at": render_ts3(rp["created_at"]),
        "updated_at": render_ts3(rp["updated_at"]),
        "version": rp["version"],
    }


def serialize_ballot(b):
    return {
        "id": b["id"],
        "rule_proposal_id": b["rule_proposal_id"],
        "participant_id": b["participant_id"],
        "vote": b["vote"],
        "status": b["status"],
        "cast_at": render_ts(b["cast_at"]),
        "created_at": render_ts3(b["created_at"]),
        "updated_at": render_ts3(b["updated_at"]),
        "version": b["version"],
    }


def serialize_guidance(d):
    return {
        "id": d["id"],
        "rule_proposal_id": d["rule_proposal_id"],
        "transaction_code_id": d["transaction_code_id"],
        "title": d["title"],
        "body_ref": d["body_ref"],
        "effective_from": render_date(d["effective_from"]),
        "effective_until": render_date(d["effective_until"]),
        "status": d["status"],
        "created_at": render_ts3(d["created_at"]),
        "updated_at": render_ts3(d["updated_at"]),
        "version": d["version"],
    }


# ---------------------------------------------------------------------------
# Transaction codes
# ---------------------------------------------------------------------------


@bp.post("/transaction-codes")
@require_roles("PlatformAdmin")
def create_transaction_code():
    body = get_body()
    code = require_str(body, "code")
    if _CODE_RE.fullmatch(code) is None:
        fail("ERR_INVALID_REQUEST", "code must be 2-3 uppercase letters")
    entry_class = require_enum(body, "entry_class", ENTRY_CLASSES)
    authorization_requirement = require_enum(
        body, "authorization_requirement", AUTHORIZATION_TYPES
    )
    return_timeframe_banking_days = require_int(body, "return_timeframe_banking_days")
    if return_timeframe_banking_days < 1:
        fail("ERR_INVALID_REQUEST", "return_timeframe_banking_days must be >= 1")
    account_validation_required = require_bool(body, "account_validation_required")
    warranty_obligations = require_str(body, "warranty_obligations")
    for tc in DB.transaction_codes.values():
        if tc["code"] == code:
            fail("ERR_DUPLICATE_RESOURCE", "Transaction code %s already exists" % code)
    rec = add_record(
        "transaction_codes",
        {
            "code": code,
            "entry_class": entry_class,
            "authorization_requirement": authorization_requirement,
            "return_timeframe_banking_days": return_timeframe_banking_days,
            "account_validation_required": account_validation_required,
            "warranty_obligations": warranty_obligations,
        },
    )
    return ok(serialize_transaction_code(rec), 201)


@bp.get("/transaction-codes/<code_id>")
@require_roles(*ROLES)
def get_transaction_code(code_id):
    tc = DB.transaction_codes.get(code_id)
    if tc is None:
        fail("ERR_NOT_FOUND", "Transaction code %s not found" % code_id)
    return ok(serialize_transaction_code(tc))


@bp.get("/transaction-codes")
@require_roles(*ROLES)
def list_transaction_codes():
    return list_response(DB.transaction_codes.values(), serialize_transaction_code)


# ---------------------------------------------------------------------------
# Rule proposals
# ---------------------------------------------------------------------------


def get_proposal_or_404(proposal_id):
    rp = DB.rule_proposals.get(proposal_id)
    if rp is None:
        fail("ERR_NOT_FOUND", "Rule proposal %s not found" % proposal_id)
    return rp


def lock_cast_ballots(proposal):
    for b in DB.ballots.values():
        if b["rule_proposal_id"] == proposal["id"] and b["status"] == "CAST":
            b["status"] = "LOCKED"
            touch(b)


@bp.post("/rule-proposals")
@require_roles("PlatformAdmin")
def create_rule_proposal():
    body = get_body()
    transaction_code_id = require_str(body, "transaction_code_id")
    title = require_str(body, "title")
    summary = require_str(body, "summary")
    effective_date = require_date(body, "effective_date")
    # Shape-level constraint (priority 3): strictly after the creation date.
    if effective_date <= CLOCK.today():
        fail(
            "ERR_INVALID_REQUEST",
            "effective_date must be strictly after the creation date",
        )
    if transaction_code_id not in DB.transaction_codes:
        fail("ERR_NOT_FOUND", "Transaction code %s not found" % transaction_code_id)
    rec = add_record(
        "rule_proposals",
        {
            "transaction_code_id": transaction_code_id,
            "title": title,
            "summary": summary,
            "effective_date": effective_date,
            "status": "DRAFT",
            "outcome": None,
            "comment_opened_at": None,
            "ballot_opened_at": None,
            "yea_count": 0,
            "nay_count": 0,
            "abstain_count": 0,
        },
    )
    return ok(serialize_proposal(rec), 201)


@bp.get("/rule-proposals/<proposal_id>")
@require_roles(*ROLES)
def get_rule_proposal(proposal_id):
    return ok(serialize_proposal(get_proposal_or_404(proposal_id)))


@bp.get("/rule-proposals")
@require_roles(*ROLES)
def list_rule_proposals():
    filters = []
    status = request.args.get("status")
    if status is not None:
        filters.append(("status", status))
    transaction_code_id = request.args.get("transaction_code_id")
    if transaction_code_id is not None:
        filters.append(("transaction_code_id", transaction_code_id))
    return list_response(DB.rule_proposals.values(), serialize_proposal, filters)


@bp.post("/rule-proposals/<proposal_id>/transition")
@require_roles("PlatformAdmin")
def transition_rule_proposal(proposal_id):
    rp = get_proposal_or_404(proposal_id)
    body = get_body()
    to_state = require_enum(body, "to_state", PROPOSAL_STATES)
    current = rp["status"]
    today = CLOCK.today()

    if to_state == "COMMENT_OPEN":
        if current != "DRAFT":
            fail("ERR_INVALID_STATE", "Cannot transition %s to COMMENT_OPEN" % current)
        rp["status"] = "COMMENT_OPEN"
        rp["comment_opened_at"] = CLOCK.now()
    elif to_state == "BALLOTING":
        if current != "COMMENT_OPEN":
            fail("ERR_INVALID_STATE", "Cannot transition %s to BALLOTING" % current)
        if today < rp["comment_opened_at"].date() + timedelta(days=30):
            fail(
                "ERR_COMMENT_PERIOD_TOO_SHORT",
                "Comment period of 30 days has not elapsed",
            )
        rp["status"] = "BALLOTING"
        rp["ballot_opened_at"] = CLOCK.now()
    elif to_state == "RETURNED_FOR_REWORK":
        if current not in ("BALLOTING", "PASSED"):
            fail(
                "ERR_INVALID_STATE",
                "Cannot transition %s to RETURNED_FOR_REWORK" % current,
            )
        rp["status"] = "RETURNED_FOR_REWORK"
        lock_cast_ballots(rp)
    elif to_state == "DRAFT":
        if current != "RETURNED_FOR_REWORK":
            fail("ERR_INVALID_STATE", "Cannot transition %s to DRAFT" % current)
        rp["status"] = "DRAFT"
        rp["yea_count"] = 0
        rp["nay_count"] = 0
        rp["abstain_count"] = 0
        rp["outcome"] = None
    elif to_state == "EFFECTIVE":
        if current != "PASSED":
            fail("ERR_INVALID_STATE", "Cannot transition %s to EFFECTIVE" % current)
        if today < rp["effective_date"]:
            fail("ERR_EFFECTIVE_DATE_NOT_REACHED", "effective_date not yet reached")
        rp["status"] = "EFFECTIVE"
        # Supersede every OTHER EFFECTIVE proposal of the same transaction code.
        for other in DB.rule_proposals.values():
            if (
                other["id"] != rp["id"]
                and other["transaction_code_id"] == rp["transaction_code_id"]
                and other["status"] == "EFFECTIVE"
            ):
                other["status"] = "SUPERSEDED"
                touch(other)
    else:
        # PASSED / REJECTED arrive only via close-ballot; SUPERSEDED only via
        # the supersession cascade.
        fail("ERR_INVALID_STATE", "Cannot transition to %s" % to_state)

    touch(rp)
    return ok(serialize_proposal(rp))


@bp.post("/rule-proposals/<proposal_id>/close-ballot")
@require_roles("PlatformAdmin")
def close_ballot(proposal_id):
    rp = get_proposal_or_404(proposal_id)
    if rp["status"] != "BALLOTING":
        fail("ERR_INVALID_STATE", "Proposal is not in BALLOTING")
    today = CLOCK.today()
    if today < rp["ballot_opened_at"].date() + timedelta(days=14):
        fail("ERR_BALLOT_PERIOD_NOT_CLOSED", "Ballot period of 14 days has not elapsed")

    # ballot_outcome_tally — exact integer arithmetic only.
    eligible = sum(1 for p in DB.participants.values() if p["status"] == "ACTIVE")
    cast = sum(
        1
        for b in DB.ballots.values()
        if b["rule_proposal_id"] == rp["id"] and b["status"] == "CAST"
    )
    quorum_met = cast * QUORUM_DEN >= eligible * QUORUM_NUM
    if not quorum_met:
        rp["outcome"] = "REJECTED_NO_QUORUM"
        rp["status"] = "REJECTED"
    else:
        non_abstain = rp["yea_count"] + rp["nay_count"]
        if non_abstain == 0:
            rp["outcome"] = "REJECTED_VOTE"
            rp["status"] = "REJECTED"
        elif rp["yea_count"] * APPROVAL_DEN >= non_abstain * APPROVAL_NUM:
            rp["outcome"] = "PASSED_QUORUM"
            rp["status"] = "PASSED"
        else:
            rp["outcome"] = "REJECTED_VOTE"
            rp["status"] = "REJECTED"

    lock_cast_ballots(rp)
    touch(rp)
    return ok(serialize_proposal(rp))


# ---------------------------------------------------------------------------
# Ballots
# ---------------------------------------------------------------------------


@bp.post("/rule-proposals/<proposal_id>/ballots")
@require_roles("VotingDelegate")
def cast_ballot(proposal_id):
    rp = get_proposal_or_404(proposal_id)
    body = get_body()
    vote = require_enum(body, "vote", VOTES)
    for b in DB.ballots.values():
        if b["rule_proposal_id"] == proposal_id and b["participant_id"] == g.user_id:
            fail(
                "ERR_DUPLICATE_RESOURCE",
                "This participant has already cast a ballot on this proposal",
            )
    if rp["status"] != "BALLOTING":
        fail("ERR_INVALID_STATE", "Proposal is not in BALLOTING")
    participant = DB.participants.get(g.user_id)
    if participant is None or participant["status"] != "ACTIVE":
        fail("ERR_PARTICIPANT_NOT_ACTIVE", "Voting participant is not ACTIVE")
    rec = add_record(
        "ballots",
        {
            "rule_proposal_id": proposal_id,
            "participant_id": g.user_id,
            "vote": vote,
            "status": "CAST",
            "cast_at": CLOCK.now(),
        },
    )
    rp[_TALLY_FIELD[vote]] += 1
    touch(rp)
    return ok(serialize_ballot(rec), 201)


@bp.patch("/ballots/<ballot_id>")
@require_roles("VotingDelegate")
def recast_ballot(ballot_id):
    b = DB.ballots.get(ballot_id)
    if b is None:
        fail("ERR_NOT_FOUND", "Ballot %s not found" % ballot_id)
    if b["participant_id"] != g.user_id:
        fail("ERR_FORBIDDEN", "Ballot belongs to another participant")
    body = get_body()
    vote = require_enum(body, "vote", VOTES)
    if b["status"] != "CAST":
        fail("ERR_INVALID_STATE", "Ballot is not in CAST")
    rp = DB.rule_proposals.get(b["rule_proposal_id"])
    if rp is None or rp["status"] != "BALLOTING":
        fail("ERR_INVALID_STATE", "Proposal is not in BALLOTING")
    if vote == b["vote"]:
        fail("ERR_VOTE_UNCHANGED", "Recast vote equals the current vote")
    rp[_TALLY_FIELD[b["vote"]]] -= 1
    rp[_TALLY_FIELD[vote]] += 1
    touch(rp)
    b["vote"] = vote
    b["cast_at"] = CLOCK.now()
    touch(b)
    return ok(serialize_ballot(b))


@bp.get("/ballots/<ballot_id>")
@require_roles(*ROLES)
def get_ballot(ballot_id):
    b = DB.ballots.get(ballot_id)
    if b is None:
        fail("ERR_NOT_FOUND", "Ballot %s not found" % ballot_id)
    return ok(serialize_ballot(b))


@bp.get("/ballots")
@require_roles(*ROLES)
def list_ballots():
    filters = []
    rule_proposal_id = request.args.get("rule_proposal_id")
    if rule_proposal_id is not None:
        filters.append(("rule_proposal_id", rule_proposal_id))
    participant_id = request.args.get("participant_id")
    if participant_id is not None:
        filters.append(("participant_id", participant_id))
    return list_response(DB.ballots.values(), serialize_ballot, filters)


# ---------------------------------------------------------------------------
# Guidance documents
# ---------------------------------------------------------------------------


def _windows_overlap(from_a, until_a, from_b, until_b):
    """Half-open [from, until) overlap; null until is open-ended. Sharing an
    endpoint date is NOT an overlap."""
    return (until_b is None or from_a < until_b) and (until_a is None or from_b < until_a)


@bp.post("/guidance-documents")
@require_roles("PlatformAdmin")
def create_guidance_document():
    body = get_body()
    rule_proposal_id = require_str(body, "rule_proposal_id")
    transaction_code_id = require_str(body, "transaction_code_id")
    title = require_str(body, "title")
    body_ref = require_str(body, "body_ref")
    effective_from = require_date(body, "effective_from")
    effective_until = optional_nullable_date(body, "effective_until")
    if effective_until is not None and effective_until <= effective_from:
        fail(
            "ERR_INVALID_REQUEST",
            "effective_until must be null or strictly after effective_from",
        )
    supersede_prior = optional_bool(body, "supersede_prior", False)
    expected_version = require_int(body, "expected_transaction_code_version")

    rp = DB.rule_proposals.get(rule_proposal_id)
    if rp is None:
        fail("ERR_NOT_FOUND", "Rule proposal %s not found" % rule_proposal_id)
    tc = DB.transaction_codes.get(transaction_code_id)
    if tc is None:
        fail("ERR_NOT_FOUND", "Transaction code %s not found" % transaction_code_id)

    overlapping = [
        d
        for d in DB.guidance_documents.values()
        if d["transaction_code_id"] == transaction_code_id
        and d["status"] == "PUBLISHED"
        and _windows_overlap(
            effective_from, effective_until, d["effective_from"], d["effective_until"]
        )
    ]
    # Overlap is evaluated before the proposal-effectiveness check (3.4).
    if overlapping and not supersede_prior:
        fail(
            "ERR_GUIDANCE_WINDOW_OVERLAP",
            "Effective window overlaps PUBLISHED guidance of this transaction code",
        )
    if rp["status"] != "EFFECTIVE" or rp["transaction_code_id"] != transaction_code_id:
        fail(
            "ERR_PROPOSAL_NOT_EFFECTIVE",
            "Referenced rule proposal is not EFFECTIVE for this transaction code",
        )
    # OCC is evaluated LAST (2.7/2.8).
    if expected_version != tc["version"]:
        fail(
            "ERR_STALE_VERSION",
            "expected_transaction_code_version does not match current version",
        )

    rec = add_record(
        "guidance_documents",
        {
            "rule_proposal_id": rule_proposal_id,
            "transaction_code_id": transaction_code_id,
            "title": title,
            "body_ref": body_ref,
            "effective_from": effective_from,
            "effective_until": effective_until,
            "status": "PUBLISHED",
        },
    )
    if supersede_prior:
        for d in overlapping:
            d["status"] = "SUPERSEDED"
            touch(d)
        touch(tc)
    return ok(serialize_guidance(rec), 201)


@bp.get("/guidance-documents/<doc_id>")
@require_roles(*ROLES)
def get_guidance_document(doc_id):
    d = DB.guidance_documents.get(doc_id)
    if d is None:
        fail("ERR_NOT_FOUND", "Guidance document %s not found" % doc_id)
    return ok(serialize_guidance(d))


@bp.get("/guidance-documents")
@require_roles(*ROLES)
def list_guidance_documents():
    filters = []
    rule_proposal_id = request.args.get("rule_proposal_id")
    if rule_proposal_id is not None:
        filters.append(("rule_proposal_id", rule_proposal_id))
    transaction_code_id = request.args.get("transaction_code_id")
    if transaction_code_id is not None:
        filters.append(("transaction_code_id", transaction_code_id))
    status = request.args.get("status")
    if status is not None:
        filters.append(("status", status))
    return list_response(DB.guidance_documents.values(), serialize_guidance, filters)
