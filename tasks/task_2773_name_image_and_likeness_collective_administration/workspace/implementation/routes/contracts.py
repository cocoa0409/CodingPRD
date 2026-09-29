"""Deal contracts: individual deals, roster allocation, disclosure, activation."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import lookup
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("contracts", __name__)

DEAL_KINDS = ["INDIVIDUAL", "ROSTER_SHARE"]
DESIGNATIONS = ["UNRESTRICTED", "ROSTER_POOL", "CHARITY_PROGRAM"]
EXCLUSIVITY_CATEGORIES = ["NONE", "APPAREL", "BEVERAGE", "AUTOMOTIVE"]
LIFECYCLE_STATUSES = ["DRAFT", "ACTIVE", "COMPLETED", "TERMINATED", "VOIDED"]
PAYMENT_STATUSES = ["UNPAID", "PARTIALLY_PAID", "FULLY_PAID", "CLAWBACK_DUE"]
DISCLOSURE_STATUSES = ["DISCLOSURE_NOT_REQUIRED", "DISCLOSURE_PENDING",
                       "DISCLOSURE_ACCEPTED", "DISCLOSURE_RETURNED", "DISCLOSURE_LATE"]
TERMINATION_REASONS = ["TRANSFER_OUT", "INELIGIBILITY", "BREACH", "MUTUAL_RELEASE"]
ALLOCATION_MODES = ["EQUAL_SHARE", "WEIGHTED_BY_ROSTER_WEIGHT"]
ROSTER_SPORTS = ["FOOTBALL", "MENS_BASKETBALL", "WOMENS_BASKETBALL", "BASEBALL", "SOFTBALL"]


def _new_contract_row(collective, athlete, deal_kind, allocation_batch_code,
                      total_value_cents, funding_designation, exclusivity_category,
                      start_at, end_at):
    now = clock.now()
    needs_disclosure = total_value_cents >= calc.DISCLOSURE_THRESHOLD_CENTS
    row = {
        "id": store.new_id(),
        "collective_id": collective["id"],
        "athlete_id": athlete["id"],
        "deal_kind": deal_kind,
        "allocation_batch_code": allocation_batch_code,
        "total_value_cents": total_value_cents,
        "funding_designation": funding_designation,
        "exclusivity_category": exclusivity_category,
        "effective_start_at": start_at,
        "effective_end_at": end_at,
        "lifecycle_status": "DRAFT",
        "payment_status": "UNPAID",
        "disclosure_status": ("DISCLOSURE_PENDING" if needs_disclosure
                             else "DISCLOSURE_NOT_REQUIRED"),
        "disclosure_due_at": (clock.plus_hours(now, calc.DISCLOSURE_WINDOW_HOURS)
                              if needs_disclosure else None),
        "disclosure_submitted_at": None,
        "disclosure_return_count": 0,
        "clawback_amount_cents": 0,
        "termination_reason": "NONE",
        "sequence_no": store.next_seq("deal_contract"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.deal_contracts[row["id"]] = row
    return row


def _overlaps_half_open(a_start, a_end, b_start, b_end):
    """Adjacency is permitted: only a true overlap counts."""
    return a_start < b_end and b_start < a_end


def _exclusivity_conflict(athlete_id, category, start_at, end_at):
    if category == "NONE":
        return False
    for contract in derive.contracts_of_athlete(athlete_id):
        if contract["lifecycle_status"] not in ("DRAFT", "ACTIVE"):
            continue
        if contract["exclusivity_category"] != category:
            continue
        if _overlaps_half_open(start_at, end_at,
                               contract["effective_start_at"], contract["effective_end_at"]):
            return True
    return False


@bp.route("/nil/deal-contracts", methods=["POST"])
def create_contract():
    auth.authenticate([auth.COLLECTIVE_DIRECTOR])
    body = shape.body()
    collective_id = shape.string_field(body, "collective_id", required=True)
    athlete_id = shape.string_field(body, "athlete_id", required=True)
    total_value = shape.int_field(body, "total_value_cents", required=True, positive=True)
    start_at = shape.ts_field(body, "effective_start_at", required=True)
    end_at = shape.ts_field(body, "effective_end_at", required=True)
    designation = shape.enum_field(body, "funding_designation", DESIGNATIONS,
                                   default="UNRESTRICTED")
    exclusivity = shape.enum_field(body, "exclusivity_category", EXCLUSIVITY_CATEGORIES,
                                   default="NONE")
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_end_at must be strictly after effective_start_at.")

    collective = lookup.collective(collective_id)
    athlete = lookup.athlete(athlete_id)

    if athlete["collective_id"] != collective["id"]:
        raise ApiError("ERR_CROSS_COLLECTIVE_REFERENCE")
    if collective["funding_posture"] == "FROZEN":
        raise ApiError("ERR_COLLECTIVE_FUNDING_FROZEN")
    if athlete["eligibility_status"] != "ENROLLED":
        raise ApiError("ERR_ATHLETE_NOT_ENROLLED")
    if _exclusivity_conflict(athlete["id"], exclusivity, start_at, end_at):
        raise ApiError("ERR_EXCLUSIVITY_WINDOW_CONFLICT")
    projected = derive.athlete_annual_committed(athlete["id"]) + total_value
    if projected > calc.ATHLETE_ANNUAL_CAP_CENTS:
        raise ApiError("ERR_ATHLETE_ANNUAL_CAP_EXCEEDED")

    row = _new_contract_row(collective, athlete, "INDIVIDUAL", None, total_value,
                            designation, exclusivity, start_at, end_at)
    derive.sync_collective(collective)
    return envelope.object_response(serialize.deal_contract(row), 201)


@bp.route("/nil/deal-contracts/<contract_id>", methods=["GET"])
def read_contract(contract_id):
    auth.authenticate(auth.ALL_ROLES)
    row = lookup.deal_contract(contract_id)
    return envelope.object_response(serialize.deal_contract(row))


@bp.route("/nil/deal-contracts", methods=["GET"])
def list_contracts():
    auth.authenticate(auth.ALL_ROLES)
    limit, offset = envelope.read_pagination(request.args)
    collective_id = envelope.id_filter(request.args, "collective_id")
    athlete_id = envelope.id_filter(request.args, "athlete_id")
    batch_code = envelope.id_filter(request.args, "allocation_batch_code")
    deal_kind = envelope.enum_filter(request.args, "deal_kind", DEAL_KINDS)
    lifecycle = envelope.enum_filter(request.args, "lifecycle_status", LIFECYCLE_STATUSES)
    payment = envelope.enum_filter(request.args, "payment_status", PAYMENT_STATUSES)
    disclosure = envelope.enum_filter(request.args, "disclosure_status", DISCLOSURE_STATUSES)
    rows = store.ordered(store.deal_contracts.values())
    if collective_id is not None:
        rows = [r for r in rows if r["collective_id"] == collective_id]
    if athlete_id is not None:
        rows = [r for r in rows if r["athlete_id"] == athlete_id]
    if batch_code is not None:
        rows = [r for r in rows if r["allocation_batch_code"] == batch_code]
    if deal_kind is not None:
        rows = [r for r in rows if r["deal_kind"] == deal_kind]
    if lifecycle is not None:
        rows = [r for r in rows if r["lifecycle_status"] == lifecycle]
    if payment is not None:
        rows = [r for r in rows if r["payment_status"] == payment]
    if disclosure is not None:
        rows = [r for r in rows if r["disclosure_status"] == disclosure]
    return envelope.list_response([serialize.deal_contract(r) for r in rows], limit, offset)


@bp.route("/nil/deal-contracts/roster-allocations", methods=["POST"])
def roster_allocation():
    auth.authenticate([auth.COLLECTIVE_DIRECTOR])
    body = shape.body()
    collective_id = shape.string_field(body, "collective_id", required=True)
    batch_code = shape.string_field(body, "allocation_batch_code", required=True)
    sport = shape.enum_field(body, "sport", ROSTER_SPORTS, required=True)
    pool = shape.int_field(body, "pool_amount_cents", required=True)
    mode = shape.enum_field(body, "allocation_mode", ALLOCATION_MODES, required=True)
    start_at = shape.ts_field(body, "effective_start_at", required=True)
    end_at = shape.ts_field(body, "effective_end_at", required=True)
    designation = shape.enum_field(body, "funding_designation", DESIGNATIONS,
                                   default="UNRESTRICTED")
    exclusivity = shape.enum_field(body, "exclusivity_category", EXCLUSIVITY_CATEGORIES,
                                   default="NONE")
    expected = shape.int_field(body, "expected_collective_version", required=True)
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_end_at must be strictly after effective_start_at.")

    collective = lookup.collective(collective_id)

    if expected != collective["version"]:
        raise ApiError("ERR_STALE_COLLECTIVE_VERSION")
    if collective["funding_posture"] == "RESTRICTED":
        raise ApiError("ERR_COLLECTIVE_FUNDING_RESTRICTED")
    if collective["funding_posture"] == "FROZEN":
        raise ApiError("ERR_COLLECTIVE_FUNDING_FROZEN")

    roster = [a for a in derive.athletes_of_collective(collective["id"])
              if a["sport"] == sport and a["eligibility_status"] == "ENROLLED"]
    if not roster:
        raise ApiError("ERR_NO_ELIGIBLE_ATHLETES")

    weights = {}
    for athlete in roster:
        weights[athlete["id"]] = (1 if mode == "EQUAL_SHARE" else athlete["roster_weight"])
    total_weight = sum(weights.values())

    shares = {}
    for athlete in roster:
        shares[athlete["id"]] = calc.floor_div(pool * weights[athlete["id"]], total_weight)
    remainder = pool - sum(shares.values())
    distribution_order = sorted(roster, key=lambda a: (-weights[a["id"]], a["sequence_no"]))
    for index in range(remainder):
        athlete = distribution_order[index % len(distribution_order)]
        shares[athlete["id"]] += 1

    for athlete in roster:
        if _exclusivity_conflict(athlete["id"], exclusivity, start_at, end_at):
            raise ApiError("ERR_EXCLUSIVITY_WINDOW_CONFLICT")
    for athlete in roster:
        if shares[athlete["id"]] < calc.MIN_ROSTER_SHARE_CENTS:
            raise ApiError("ERR_ROSTER_SHARE_BELOW_MINIMUM")
    for athlete in roster:
        projected = derive.athlete_annual_committed(athlete["id"]) + shares[athlete["id"]]
        if projected > calc.ATHLETE_ANNUAL_CAP_CENTS:
            raise ApiError("ERR_ATHLETE_ANNUAL_CAP_EXCEEDED")

    # Evaluated last of all, so a cheaper violation always reports itself instead.
    colliding_codes = set()
    for contract in derive.contracts_of_collective(collective["id"]):
        if contract["lifecycle_status"] not in ("DRAFT", "ACTIVE"):
            continue
        if contract["allocation_batch_code"] is None:
            continue
        other = store.athletes.get(contract["athlete_id"])
        if other is None or other["sport"] != sport:
            continue
        # Closed-interval collision: touching endpoints DO collide here.
        if contract["effective_start_at"] <= end_at and start_at <= contract["effective_end_at"]:
            colliding_codes.add(contract["allocation_batch_code"])
    if len(colliding_codes) >= calc.MAX_OVERLAPPING_BATCHES:
        raise ApiError("ERR_BATCH_OVERLAP_CAPACITY_EXCEEDED")

    created = []
    for athlete in distribution_order:
        created.append(_new_contract_row(collective, athlete, "ROSTER_SHARE", batch_code,
                                        shares[athlete["id"]], designation, exclusivity,
                                        start_at, end_at))
    derive.bump(collective)
    derive.sync_collective(collective)

    amounts = [c["total_value_cents"] for c in created]
    return envelope.object_response({
        "collective_id": collective["id"],
        "allocation_batch_code": batch_code,
        "sport": sport,
        "allocation_mode": mode,
        "pool_amount_cents": pool,
        "created_contract_count": len(created),
        "allocated_total_cents": sum(amounts),
        "remainder_cents": remainder,
        "min_share_cents": min(amounts),
        "max_share_cents": max(amounts),
        "deal_contracts": [serialize.deal_contract(c) for c in created],
    }, 201)


def _require_draft(contract):
    if contract["lifecycle_status"] in derive.TERMINAL_LIFECYCLE:
        raise ApiError("ERR_CONTRACT_TERMINAL")
    if contract["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT")


@bp.route("/nil/deal-contracts/<contract_id>/compliance-submissions", methods=["POST"])
def compliance_submission(contract_id):
    auth.authenticate([auth.COLLECTIVE_DIRECTOR, auth.COMPLIANCE_OFFICER])
    body = shape.body()
    shape.string_field(body, "state_law_citation")
    shape.string_field(body, "association_rule_citation")
    contract = lookup.deal_contract(contract_id)

    _require_draft(contract)
    if contract["disclosure_status"] not in ("DISCLOSURE_PENDING", "DISCLOSURE_RETURNED"):
        raise ApiError("ERR_DISCLOSURE_STATE_INVALID")

    now = clock.now()
    contract["disclosure_submitted_at"] = now
    due = contract["disclosure_due_at"]
    if due is not None and now > due:
        contract["disclosure_status"] = "DISCLOSURE_LATE"
    else:
        contract["disclosure_status"] = "DISCLOSURE_PENDING"
    derive.bump(contract)
    return envelope.object_response(serialize.deal_contract(contract))


@bp.route("/nil/deal-contracts/<contract_id>/compliance-decisions", methods=["POST"])
def compliance_decision(contract_id):
    auth.authenticate([auth.INSTITUTION_REVIEWER])
    body = shape.body()
    decision = shape.enum_field(body, "decision", ["ACCEPT", "RETURN"], required=True)
    shape.string_field(body, "reviewer_note")
    contract = lookup.deal_contract(contract_id)

    _require_draft(contract)
    if contract["disclosure_submitted_at"] is None:
        raise ApiError("ERR_DISCLOSURE_NOT_SUBMITTED")
    if contract["disclosure_status"] not in ("DISCLOSURE_PENDING", "DISCLOSURE_LATE"):
        raise ApiError("ERR_DISCLOSURE_STATE_INVALID")

    if decision == "ACCEPT":
        contract["disclosure_status"] = "DISCLOSURE_ACCEPTED"
        derive.bump(contract)
    else:
        contract["disclosure_status"] = "DISCLOSURE_RETURNED"
        contract["disclosure_return_count"] += 1
        derive.bump(contract)
        if contract["disclosure_return_count"] >= calc.MAX_DISCLOSURE_RETURNS:
            derive.void_contract(contract)
    return envelope.object_response(serialize.deal_contract(contract))


@bp.route("/nil/deal-contracts/<contract_id>/activation", methods=["POST"])
def activate_contract(contract_id):
    auth.authenticate([auth.COLLECTIVE_DIRECTOR])
    contract = lookup.deal_contract(contract_id)

    _require_draft(contract)
    if contract["disclosure_status"] not in ("DISCLOSURE_NOT_REQUIRED", "DISCLOSURE_ACCEPTED"):
        raise ApiError("ERR_DISCLOSURE_NOT_CLEARED")
    athlete = store.athletes.get(contract["athlete_id"])
    if athlete is None or athlete["eligibility_status"] != "ENROLLED":
        raise ApiError("ERR_ATHLETE_NOT_ENROLLED")

    # Deliberately not gated on funding_posture: the value was committed at draft.
    contract["lifecycle_status"] = "ACTIVE"
    derive.bump(contract)
    return envelope.object_response(serialize.deal_contract(contract))


@bp.route("/nil/deal-contracts/<contract_id>/termination", methods=["POST"])
def terminate(contract_id):
    auth.authenticate([auth.COLLECTIVE_DIRECTOR, auth.COMPLIANCE_OFFICER])
    body = shape.body()
    reason = shape.enum_field(body, "termination_reason", TERMINATION_REASONS, required=True)
    contract = lookup.deal_contract(contract_id)

    if contract["lifecycle_status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_CONTRACT_TERMINAL")

    derive.terminate_contract(contract, reason)
    return envelope.object_response(serialize.deal_contract(contract))
