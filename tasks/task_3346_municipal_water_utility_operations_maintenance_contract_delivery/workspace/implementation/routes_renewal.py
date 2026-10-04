"""Renewal proposal and transition obligation endpoints — PRD 3.8, 3.9."""
from datetime import timedelta

import calc
import services
from core import (ApiError, DB, apply, arg, arg_bool, body, bump, create, dec,
                  endpoint, field, g, get, iso, now, now_iso, ordered, own,
                  paginate, parse_dt, set_status, str_field)

BENCHMARK_RATIO_CEILING = "1.25"
OBLIGATION_TYPES = ("ASSET_HANDOVER", "RECORDS_TRANSFER", "EMPLOYEE_REINSTATE",
                    "PERMIT_TRANSFER", "SPARES_INVENTORY", "SCADA_ACCESS")
TERMINAL_PROPOSAL_STATUSES = ("ACCEPTED", "REJECTED", "WITHDRAWN", "LAPSED")


def proposal_or_404(proposal_id):
    return get("proposals", proposal_id, "ERR_PROPOSAL_NOT_FOUND")


def obligation_or_404(obligation_id):
    return get("obligations", obligation_id, "ERR_OBLIGATION_NOT_FOUND")


def _submitted_for_round(contract_id, round_number):
    return [p for p in services.proposals_of(contract_id, "SUBMITTED")
            if int(p["round_number"]) == int(round_number)]


def _version_guard(contract, data):
    if data.get("expected_contract_version") is None:
        return
    try:
        expected = int(data["expected_contract_version"])
    except (TypeError, ValueError):
        raise ApiError("ERR_STALE_VERSION")
    if expected != int(contract["version"]):
        raise ApiError("ERR_STALE_VERSION")


# --------------------------------------------------------------------------
# renewal proposals
# --------------------------------------------------------------------------
@endpoint("/contracts/<id>/renewal-proposals", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_proposals(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    status = arg("status")
    round_number = arg("round_number")
    items = [p for p in services.proposals_of(contract["id"], status)
             if round_number is None or str(p["round_number"]) == str(round_number)]
    return paginate(ordered(items))


@endpoint("/contracts/<id>/renewal-proposals", ["POST"], ["OperatorAdmin"], status=201)
def submit_proposal(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    if contract["status"] != "RENEWAL_PENDING":
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    data = body()
    try:
        round_number = int(field(data, "round_number"))
        fee = int(field(data, "proposed_fee_cents"))
        term = int(field(data, "proposed_term_years"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "round_number, proposed_fee_cents and proposed_term_years must be integers.")
    if round_number < 1 or fee < 1 or term < 1:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "round_number, proposed_fee_cents and proposed_term_years must be at least 1.")
    submitted_by = str_field(data, "submitted_by")
    if submitted_by not in ("OPERATOR", "MUNICIPALITY"):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Unknown submitted_by.")
    if round_number != int(contract["renewal_round"]) + 1:
        raise ApiError("ERR_RENEWAL_ROUND_MISMATCH")
    if _submitted_for_round(contract["id"], round_number):
        raise ApiError("ERR_DUPLICATE_ROUND_PROPOSAL")
    municipality = DB["municipalities"].get(contract["municipality_id"])
    ratio = calc.benchmark_ratio(fee, municipality, contract) if municipality else 0.0
    if dec(ratio) > dec(BENCHMARK_RATIO_CEILING):
        raise ApiError("ERR_BENCHMARK_RATIO_EXCEEDED")
    if services.standards_of(contract["id"], "BREACHED"):
        raise ApiError("ERR_BREACH_UNRESOLVED_AT_RENEWAL")
    proposal = create("proposals",
                      contract_id=contract["id"],
                      round_number=round_number,
                      proposed_fee_cents=fee,
                      proposed_term_years=term,
                      submitted_by=submitted_by,
                      benchmark_ratio=ratio,
                      status="SUBMITTED")
    bump(contract)
    return proposal


@endpoint("/renewal-proposals/<id>", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_proposal(id):
    proposal = proposal_or_404(id)
    own(proposal)
    return proposal


@endpoint("/renewal-proposals/<id>/review", ["POST"], ["MunicipalityAdmin"])
def review_proposal(id):
    proposal = proposal_or_404(id)
    own(proposal)
    if proposal["status"] in TERMINAL_PROPOSAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if proposal["status"] != "SUBMITTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if dec(proposal.get("benchmark_ratio") or 0) > dec(BENCHMARK_RATIO_CEILING):
        raise ApiError("ERR_BENCHMARK_RATIO_EXCEEDED")
    set_status(proposal, "UNDER_REVIEW")
    return proposal


@endpoint("/renewal-proposals/<id>/counter", ["POST"], ["MunicipalityAdmin"])
def counter_proposal(id):
    proposal = proposal_or_404(id)
    own(proposal)
    data = body()
    try:
        fee = int(field(data, "proposed_fee_cents"))
        term = int(field(data, "proposed_term_years"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "proposed_fee_cents and proposed_term_years must be integers.")
    if fee < 1 or term < 1:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "proposed_fee_cents and proposed_term_years must be at least 1.")
    if proposal["status"] in TERMINAL_PROPOSAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if proposal["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][proposal["contract_id"]]
    next_round = int(contract["renewal_round"]) + 1
    set_status(proposal, "COUNTERED")
    municipality = DB["municipalities"].get(contract["municipality_id"])
    ratio = calc.benchmark_ratio(fee, municipality, contract) if municipality else 0.0
    create("proposals",
           contract_id=contract["id"],
           round_number=next_round,
           proposed_fee_cents=fee,
           proposed_term_years=term,
           submitted_by="MUNICIPALITY",
           benchmark_ratio=ratio,
           status="SUBMITTED")
    return proposal


@endpoint("/renewal-proposals/<id>/accept", ["POST"],
          ["MunicipalityAdmin", "OperatorAdmin"])
def accept_proposal(id):
    proposal = proposal_or_404(id)
    own(proposal)
    data = body()
    contract = DB["contracts"][proposal["contract_id"]]
    if proposal["status"] in TERMINAL_PROPOSAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if proposal["status"] == "COUNTERED":
        if g.actor_role != "OperatorAdmin":
            raise ApiError("ERR_ROLE_FORBIDDEN")
        if proposal["submitted_by"] != "MUNICIPALITY":
            raise ApiError("ERR_ALREADY_TERMINAL")
    elif proposal["status"] in ("SUBMITTED", "UNDER_REVIEW"):
        if proposal["submitted_by"] == "MUNICIPALITY":
            # the municipality's counter offer may be closed by either party
            if g.actor_role not in ("MunicipalityAdmin", "OperatorAdmin"):
                raise ApiError("ERR_ROLE_FORBIDDEN")
        elif g.actor_role != "MunicipalityAdmin":
            raise ApiError("ERR_ROLE_FORBIDDEN")
        if contract["status"] != "RENEWAL_PENDING":
            raise ApiError("ERR_CONTRACT_INVALID_STATE")
    else:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contract["status"] != "RENEWAL_PENDING":
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    _version_guard(contract, data)
    set_status(proposal, "ACCEPTED")
    for sibling in services.proposals_of(contract["id"]):
        if sibling is not proposal and sibling["status"] not in TERMINAL_PROPOSAL_STATUSES:
            set_status(sibling, "LAPSED")
    end = parse_dt(contract["contract_end_date"])
    set_status(contract, "RENEWED",
               renewal_round=int(contract["renewal_round"]) + 1,
               annual_fee_cents=int(proposal["proposed_fee_cents"]),
               contract_end_date=iso(end + timedelta(days=int(proposal["proposed_term_years"]) * 365)))
    return proposal


@endpoint("/renewal-proposals/<id>/reject", ["POST"], ["MunicipalityAdmin"])
def reject_proposal(id):
    proposal = proposal_or_404(id)
    own(proposal)
    str_field(body(), "rejection_reason")
    if proposal["status"] in TERMINAL_PROPOSAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if proposal["status"] != "SUBMITTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(proposal, "REJECTED")
    return proposal


@endpoint("/renewal-proposals/<id>/withdraw", ["POST"], ["OperatorAdmin"])
def withdraw_proposal(id):
    proposal = proposal_or_404(id)
    own(proposal)
    if proposal["status"] in TERMINAL_PROPOSAL_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if proposal["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(proposal, "WITHDRAWN")
    return proposal


# --------------------------------------------------------------------------
# transition obligations
# --------------------------------------------------------------------------
@endpoint("/contracts/<id>/transition-obligations", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_obligations(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    status = arg("status")
    obligation_type = arg("obligation_type")
    is_critical = arg_bool("is_critical")
    items = [o for o in services.obligations_of(contract["id"], status)
             if (obligation_type is None or o["obligation_type"] == obligation_type)
             and (is_critical is None or bool(o.get("is_critical")) == is_critical)]
    return paginate(ordered(items))


@endpoint("/contracts/<id>/transition-obligations", ["POST"], ["MunicipalityAdmin"], status=201)
def create_obligation_endpoint(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    data = body()
    obligation_type = str_field(data, "obligation_type")
    if obligation_type not in OBLIGATION_TYPES:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Unknown obligation_type.")
    due_at = parse_dt(field(data, "due_at"))
    try:
        penalty_per_day = int(field(data, "penalty_per_day_cents"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "penalty_per_day_cents must be an integer.")
    if penalty_per_day < 0:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "penalty_per_day_cents must be zero or greater.")
    start = services.handback_started_at(contract) if contract["status"] == "HANDING_BACK" else None
    if start is not None and due_at < start:
        raise ApiError("ERR_OBLIGATION_DUE_BEFORE_HANDOFF")
    status = "PENDING" if contract["status"] == "HANDING_BACK" else "DRAFT"
    return services.create_obligation(contract, obligation_type, due_at,
                                      bool(data.get("is_critical")), penalty_per_day,
                                      status=status)


@endpoint("/transition-obligations/<id>", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_obligation(id):
    obligation = obligation_or_404(id)
    own(obligation)
    return obligation


@endpoint("/transition-obligations/<id>/start", ["POST"], ["OperatorAdmin"])
def start_obligation(id):
    obligation = obligation_or_404(id)
    own(obligation)
    if obligation["status"] in ("SATISFIED", "WAIVED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if obligation["status"] != "PENDING":
        raise ApiError("ERR_ALREADY_TERMINAL")
    due = parse_dt(obligation.get("due_at"))
    if due is None or now() >= due:
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(obligation, "IN_PROGRESS")
    return obligation


@endpoint("/transition-obligations/<id>/satisfy", ["POST"],
          ["OperatorAdmin", "MunicipalityAdmin"])
def satisfy_obligation(id):
    obligation = obligation_or_404(id)
    own(obligation)
    str_field(body(), "evidence_reference")
    status = obligation["status"]
    if status in ("SATISFIED", "WAIVED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status in ("PENDING", "IN_PROGRESS"):
        pass
    elif status == "ESCALATED":
        if g.actor_role != "MunicipalityAdmin":
            raise ApiError("ERR_ROLE_FORBIDDEN")
    else:
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(obligation, "SATISFIED", completed_at=now_iso(),
               outstanding_days=0, withholding_cents=0)
    return obligation


@endpoint("/transition-obligations/<id>/dispute", ["POST"], ["OperatorAdmin"])
def dispute_obligation(id):
    obligation = obligation_or_404(id)
    own(obligation)
    str_field(body(), "dispute_basis")
    if obligation["status"] in ("SATISFIED", "WAIVED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if obligation["status"] != "OVERDUE":
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(obligation, "DISPUTED", _disputed_by=g.actor_id)
    return obligation


@endpoint("/transition-obligations/<id>/uphold", ["POST"], ["MunicipalityAdmin"])
def uphold_obligation(id):
    obligation = obligation_or_404(id)
    own(obligation)
    if obligation["status"] != "DISPUTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(obligation, "OVERDUE")
    services.refresh_obligation(obligation)
    return obligation


@endpoint("/transition-obligations/<id>/waive", ["POST"], ["MunicipalityAdmin"])
def waive_obligation(id):
    obligation = obligation_or_404(id)
    own(obligation)
    str_field(body(), "waiver_basis")
    if obligation["status"] in ("SATISFIED", "WAIVED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if obligation.get("is_critical"):
        raise ApiError("ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE")
    if obligation["status"] not in ("DISPUTED", "OVERDUE"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if obligation.get("_disputed_by") and obligation["_disputed_by"] == g.actor_id:
        raise ApiError("ERR_CROSS_TENANT_DENIED")
    set_status(obligation, "WAIVED", withholding_cents=0)
    return obligation


@endpoint("/transition-obligations/<id>/evaluate", ["POST"], ["MunicipalityAdmin"])
def evaluate_obligation_endpoint(id):
    obligation = obligation_or_404(id)
    own(obligation)
    if obligation["status"] in ("SATISFIED", "WAIVED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    services.evaluate_obligation(obligation)
    return obligation
