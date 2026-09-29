"""Third-party demands, the negotiation ledger, settlement and rescission."""

from datetime import timedelta

from flask import Blueprint

import calc
import serializers
from auth import require, CLAIM_READ
from common import filtered, lookup, paginate
from envelope import ok, created
from errors import fail
from shape import MISSING, f, filters, given, present, read_body
from store import base_row, db, ordered, touch

bp = Blueprint("demands", __name__)

DEMAND_SPEC = [
    f("claimant_name", "string", required=True),
    f("claimant_type", "string", required=True, enum=calc.CLAIMANT_TYPES),
    f("demand_amount_cents", "int", required=True, minimum=1),
    f("represented_by_counsel", "bool", required=True),
    f("demand_received_at", "instant", required=True),
]


@bp.post("/claims/<entity_id>/demands")
def create_demand(entity_id):
    require("ClaimsAdjuster")
    values = read_body(DEMAND_SPEC)
    claim = lookup("claims", entity_id)
    if claim["handling_status"] == "CLOSED":
        fail("ERR_CLAIM_STATE_INVALID", "A closed claim accepts no new demand")
    if values["demand_received_at"] > db.now:
        fail("ERR_FUTURE_TIMESTAMP", "demand_received_at may not be in the future")
    row = base_row()
    row["claim_id"] = claim["id"]
    row["claimant_name"] = values["claimant_name"]
    row["claimant_type"] = values["claimant_type"]
    row["demand_amount_cents"] = values["demand_amount_cents"]
    row["represented_by_counsel"] = values["represented_by_counsel"]
    row["demand_received_at"] = values["demand_received_at"]
    row["status"] = "DEMANDED"
    row["next_round_index"] = 1
    row["settled_amount_cents"] = None
    row["alae_cents"] = None
    row["settlement_total_cents"] = None
    row["settled_at"] = None
    row["settlement_reference"] = None
    row["rescission_count"] = 0
    row["_allocations"] = []
    db.demands[row["id"]] = row
    if claim["handling_status"] == "SETUP":
        claim["handling_status"] = "NEGOTIATION"
    touch(claim)
    return created(serializers.demand(row))


@bp.get("/claims/<entity_id>/demands")
def list_claim_demands(entity_id):
    require(*CLAIM_READ)
    claim = lookup("claims", entity_id)
    criteria = filters({
        "status": calc.DEMAND_STATUSES,
        "claimant_type": calc.CLAIMANT_TYPES,
    })
    criteria["claim_id"] = claim["id"]
    return paginate(filtered("demands", criteria), serializers.demand)


@bp.get("/demands/<entity_id>")
def read_demand(entity_id):
    require(*CLAIM_READ)
    return ok(serializers.demand(lookup("demands", entity_id)))


@bp.get("/demands")
def list_demands():
    require(*CLAIM_READ)
    criteria = filters({
        "claim_id": None,
        "status": calc.DEMAND_STATUSES,
        "claimant_type": calc.CLAIMANT_TYPES,
        "represented_by_counsel": "bool",
    })
    return paginate(filtered("demands", criteria), serializers.demand)


# ---------------------------------------------------------------------------
# Negotiation
# ---------------------------------------------------------------------------
@bp.post("/demands/<entity_id>/offers")
def make_offer(entity_id):
    user_id, _role = require("ClaimsAdjuster")
    values = read_body([f("carrier_offer_cents", "int", required=True, minimum=1)])
    demand = lookup("demands", entity_id)
    if demand["status"] not in ("DEMANDED", "COUNTER_OUTSTANDING"):
        fail("ERR_DEMAND_STATE_INVALID",
             "An offer may only be opened from DEMANDED or COUNTER_OUTSTANDING")
    offer = values["carrier_offer_cents"]
    if offer > demand["demand_amount_cents"]:
        fail("ERR_OFFER_EXCEEDS_DEMAND",
             "The carrier may not offer more than was demanded")
    standing = calc.standing_round(demand["id"])
    if standing is not None and offer <= standing["carrier_offer_cents"]:
        fail("ERR_OFFER_NOT_MONOTONIC",
             "A new offer must strictly exceed the standing offer")
    claim = db.claims[demand["claim_id"]]
    if demand["claimant_type"] == "THIRD_PARTY_BODILY_INJURY":
        score = calc.litigation_risk_score(claim)
        if calc.counsel_required(score) and not claim["counsel_assigned"]:
            fail("ERR_COUNSEL_REQUIRED",
                 "Counsel must be assigned before offering on this demand")
    if standing is not None:
        standing["outcome"] = "SUPERSEDED"
    row = base_row(with_version=False)
    row["demand_id"] = demand["id"]
    row["round_index"] = demand["next_round_index"]
    row["carrier_offer_cents"] = offer
    row["claimant_counter_cents"] = None
    row["gap_cents"] = None
    row["outcome"] = "OPEN"
    row["offered_by_user_id"] = user_id
    row["offered_at"] = db.now
    row["countered_at"] = None
    db.negotiation_rounds[row["id"]] = row
    demand["next_round_index"] += 1
    demand["status"] = "OFFER_OUTSTANDING"
    touch(demand)
    return created(serializers.negotiation_round(row))


@bp.post("/demands/<entity_id>/counters")
def record_counter(entity_id):
    require("ClaimsAdjuster")
    values = read_body([
        f("claimant_counter_cents", "int", required=True, minimum=1),
    ])
    demand = lookup("demands", entity_id)
    standing = calc.standing_round(demand["id"])
    if (demand["status"] != "OFFER_OUTSTANDING" or standing is None
            or standing["outcome"] != "OPEN"):
        fail("ERR_DEMAND_STATE_INVALID",
             "A counter may only be recorded against a standing open offer")
    counter = values["claimant_counter_cents"]
    if counter <= standing["carrier_offer_cents"]:
        fail("ERR_COUNTER_NOT_MONOTONIC",
             "The counter must strictly exceed the standing carrier offer")
    previous = None
    for row in calc.demand_rounds(demand["id"]):
        if row["id"] == standing["id"]:
            continue
        if row["claimant_counter_cents"] is not None:
            previous = row
    if previous is not None and counter > previous["claimant_counter_cents"]:
        fail("ERR_COUNTER_NOT_MONOTONIC",
             "Claimant positions may not increase")
    standing["claimant_counter_cents"] = counter
    standing["countered_at"] = db.now
    standing["gap_cents"] = counter - standing["carrier_offer_cents"]
    standing["outcome"] = "COUNTERED"
    demand["status"] = "COUNTER_OUTSTANDING"
    touch(demand)
    return ok(serializers.negotiation_round(standing))


@bp.get("/demands/<entity_id>/negotiation-rounds")
def list_rounds(entity_id):
    require(*CLAIM_READ)
    demand = lookup("demands", entity_id)
    criteria = filters({"outcome": calc.ROUND_OUTCOMES})
    outcome = criteria.get("outcome")
    rows = [r for r in calc.demand_rounds(demand["id"])
            if outcome is None or r["outcome"] == outcome]
    return paginate(rows, serializers.negotiation_round)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
@bp.post("/demands/<entity_id>/settle")
def settle(entity_id):
    require("ClaimsManager")
    values = read_body([f("settlement_reference", "string", required=True)])
    demand = lookup("demands", entity_id)
    if demand["status"] != "OFFER_OUTSTANDING":
        fail("ERR_DEMAND_STATE_INVALID",
             "A demand may only be settled from OFFER_OUTSTANDING")
    claim = db.claims[demand["claim_id"]]
    if claim["handling_status"] == "CLOSED":
        fail("ERR_CLAIM_STATE_INVALID", "A closed claim accepts no settlement")
    crash = db.crashes[claim["crash_id"]]
    year = calc.program_year_of(crash)
    if not calc.tower_well_formed(year):
        fail("ERR_POLICY_TOWER_MALFORMED",
             "The policy tower for program year %d is not well formed" % year)
    standing = calc.standing_round(demand["id"])
    indemnity, alae, total = calc.settlement_figures(
        standing["carrier_offer_cents"])
    entries, leftover = calc.allocate(claim, year, total)
    if leftover > 0:
        fail("ERR_COVERAGE_EXHAUSTED",
             "The policy tower has insufficient remaining capacity")
    if claim["outstanding_reserve_cents"] < total:
        fail("ERR_RESERVE_INSUFFICIENT",
             "The outstanding reserve does not cover this settlement")
    demand["settled_amount_cents"] = indemnity
    demand["alae_cents"] = alae
    demand["settlement_total_cents"] = total
    demand["settlement_reference"] = values["settlement_reference"]
    demand["settled_at"] = db.now
    demand["status"] = "SETTLED"
    demand["_allocations"] = [dict(entry) for entry in entries]
    touch(demand)
    standing["outcome"] = "ACCEPTED"
    claim["indemnity_paid_cents"] += indemnity
    claim["alae_paid_cents"] += alae
    claim["outstanding_reserve_cents"] -= total
    for entry in entries:
        existing = None
        for current in claim["layer_allocations"]:
            if current["policy_layer_id"] == entry["policy_layer_id"]:
                existing = current
                break
        if existing is None:
            claim["layer_allocations"].append(dict(entry))
        else:
            existing["allocated_cents"] += entry["allocated_cents"]
        if entry["layer_type"] == "SIR":
            claim["sir_eroded_cents"] += entry["allocated_cents"]
        else:
            claim["insured_paid_cents"] += entry["allocated_cents"]
    claim["layer_allocations"].sort(key=lambda e: e["layer_index"])
    siblings = [d for d in calc.claim_demands(claim["id"])
                if d["id"] != demand["id"]]
    open_states = ("DEMANDED", "OFFER_OUTSTANDING", "COUNTER_OUTSTANDING")
    if any(d["status"] in open_states for d in siblings):
        pass
    else:
        claim["handling_status"] = "SETTLEMENT_COMPLETE"
        base = claim["indemnity_paid_cents"] + claim["alae_paid_cents"]
        for subro in calc.claim_subrogations(claim["id"]):
            if subro["status"] != "DRAFT":
                continue
            subro["status"] = "READY_TO_PURSUE"
            subro["recoverable_base_cents"] = base
            subro["max_recoverable_cents"] = calc.max_recoverable(
                base, subro["at_fault_percentage"])
            touch(subro)
    touch(claim)
    return ok(serializers.demand(demand))


@bp.post("/demands/<entity_id>/rescind-settlement")
def rescind(entity_id):
    require("ClaimsManager")
    values = read_body([f("rescission_reason", "string", required=True)])
    demand = lookup("demands", entity_id)
    if demand["status"] != "SETTLED":
        fail("ERR_DEMAND_STATE_INVALID",
             "Only a SETTLED demand may have its settlement rescinded")
    claim = db.claims[demand["claim_id"]]
    if claim["handling_status"] == "CLOSED":
        fail("ERR_CLAIM_STATE_INVALID", "A closed claim blocks rescission")
    deadline = demand["settled_at"] + timedelta(
        hours=calc.RESCISSION_WINDOW_HOURS)
    if db.now > deadline:
        fail("ERR_RESCISSION_WINDOW_CLOSED",
             "The %d-hour rescission window has closed"
             % calc.RESCISSION_WINDOW_HOURS)
    indemnity = demand["settled_amount_cents"]
    alae = demand["alae_cents"]
    total = demand["settlement_total_cents"]
    allocations = demand["_allocations"]
    demand["settled_amount_cents"] = None
    demand["alae_cents"] = None
    demand["settlement_total_cents"] = None
    demand["settled_at"] = None
    demand["settlement_reference"] = None
    demand["status"] = "OFFER_OUTSTANDING"
    demand["rescission_count"] += 1
    demand["_allocations"] = []
    touch(demand)
    for row in calc.demand_rounds(demand["id"]):
        if row["outcome"] == "ACCEPTED":
            row["outcome"] = "OPEN"
    claim["indemnity_paid_cents"] -= indemnity
    claim["alae_paid_cents"] -= alae
    claim["outstanding_reserve_cents"] += total
    for entry in allocations:
        for current in list(claim["layer_allocations"]):
            if current["policy_layer_id"] != entry["policy_layer_id"]:
                continue
            current["allocated_cents"] -= entry["allocated_cents"]
            if current["allocated_cents"] <= 0:
                claim["layer_allocations"].remove(current)
            break
        if entry["layer_type"] == "SIR":
            claim["sir_eroded_cents"] -= entry["allocated_cents"]
        else:
            claim["insured_paid_cents"] -= entry["allocated_cents"]
    if claim["handling_status"] == "SETTLEMENT_COMPLETE":
        claim["handling_status"] = "NEGOTIATION"
    for subro in calc.claim_subrogations(claim["id"]):
        if subro["status"] != "READY_TO_PURSUE":
            continue
        subro["status"] = "DRAFT"
        subro["recoverable_base_cents"] = None
        subro["max_recoverable_cents"] = None
        touch(subro)
    touch(claim)
    return ok(serializers.demand(demand))
