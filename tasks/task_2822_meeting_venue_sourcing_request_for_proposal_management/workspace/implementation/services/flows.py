"""Shared state transitions and cross-aggregate side effects."""
import clock
import enums
import lookup
from db import db, touch
from errors import ApiError
from money import D, q2
from services import calc, rollups

ELIMINATED_BY_AWARD = "NOT_SELECTED"
CANCELLED_BY_ELIMINATION = "SHORTLIST_ELIMINATED"


# ------------------------------------------------------- shortlist entries ----

def cancel_planned_inspections(entry, reason):
    for inspection in lookup.inspections_of_entry(entry["id"]):
        if inspection["status"] == "PLANNED":
            inspection["status"] = "CANCELLED"
            inspection["cancel_reason"] = reason
            touch(inspection)
    rollups.refresh_inspection_count(entry)


def eliminate_entry(entry, reason):
    """Eliminate a shortlist entry, cancelling any planned inspections."""
    source = entry["status"]
    entry["status"] = "ELIMINATED"
    entry["elimination_reason"] = reason
    if source in ("INSPECTION_SCHEDULED", "RFP_ISSUED"):
        cancel_planned_inspections(entry, CANCELLED_BY_ELIMINATION)
    touch(entry)


# ---------------------------------------------------------------- contract ----

def room_block_capacity_guard(contract, event, venue):
    """room_night_inventory_invariant capacity guard (checked pre-increment)."""
    peak_sum = 0
    for other in lookup.contracts_of_venue(venue["id"]):
        if other["id"] == contract["id"]:
            continue
        if other["signature_state"] != "EXECUTED":
            continue
        other_event = db.events.get(other["event_id"])
        if other_event is None:
            continue
        if (other_event["start_date"] <= event["end_date"]
                and other_event["end_date"] >= event["start_date"]):
            peak_sum += other["peak_rooms_per_night"]
    if peak_sum + contract["peak_rooms_per_night"] > venue["guest_rooms_total"]:
        raise ApiError(
            "ERR_VENUE_ROOM_BLOCK_CAPACITY_EXCEEDED",
            "Overlapping executed room blocks exceed the venue inventory",
        )


def execute_contract(contract, event, venue):
    """The joined execution effects, applied exactly once."""
    contract["signature_state"] = "EXECUTED"
    contract["executed_at"] = clock.now()

    venue["blocked_room_nights"] = (
        venue["blocked_room_nights"] + contract["contracted_paid_room_nights"]
    )
    touch(venue)

    entry = lookup.entry_for(event["id"], contract["venue_id"])
    if entry is not None and entry["status"] == "RFP_ISSUED":
        entry["status"] = "AWARDED"
        touch(entry)

    if event["status"] == "AWARDED":
        event["status"] = "CONTRACTED"
    rollups.refresh_shortlisted_count(event)
    rollups.refresh_budget_envelope(event)
    touch(event)


def unwind_contract(contract):
    """Supersede a live contract when a fresh award lands on the event."""
    contract["approval_state"] = "CANCELLED"
    contract["signature_state"] = "VOIDED"
    for step in lookup.steps_of_contract(contract["id"]):
        if step["decision"] == "PENDING":
            step["decision"] = "SKIPPED"
            touch(step)
    for installment in lookup.installments_of_contract(contract["id"]):
        if installment["status"] == "SCHEDULED":
            installment["status"] = "CANCELLED"
            touch(installment)
    rollups.refresh_deposit_rollup(contract)
    touch(contract)
    prior = db.proposals.get(contract["proposal_id"])
    if prior is not None and prior["status"] == "AWARDED":
        prior["status"] = "REJECTED"
        touch(prior)


# ---------------------------------------------------------------- pricing ----

def require_benchmark(venue, event):
    benchmark = lookup.find_benchmark(
        venue["destination_tier"], event["program_type"]
    )
    if benchmark is None:
        raise ApiError(
            "ERR_BENCHMARK_NOT_CONFIGURED",
            "No rate benchmark exists for this destination tier and program type",
        )
    return benchmark


def apply_contracted_pricing(proposal, venue, benchmark):
    """Re-run the contracted variant and the benchmark comparison."""
    model = calc.cost_model(proposal, "CONTRACTED_BASIS")
    proposal["comp_room_nights"] = model["comp_room_nights"]
    proposal["paid_room_nights"] = model["paid_room_nights"]
    proposal["net_adr_usd"] = model["net_adr_usd"]
    proposal["total_cost_contracted_usd"] = model["total_cost_usd"]
    variance, status = calc.benchmark_compliance(
        model["net_adr_usd"],
        benchmark["benchmark_adr_usd"],
        venue["preferred_supplier_status"],
    )
    proposal["benchmark_variance_pct"] = variance
    proposal["compliance_status"] = status
    return model


def supplier_program_guards(event, venue, proposal, entry):
    """PRD section 2.8 band 14, in the declared order."""
    if venue["preferred_supplier_status"] == "SUSPENDED":
        raise ApiError("ERR_VENUE_SUSPENDED", "The venue is suspended")
    if event["preferred_program_only"]:
        snapshot = entry["program_status_at_shortlist"] if entry else None
        if snapshot != "IN_PROGRAM":
            raise ApiError(
                "ERR_PREFERRED_PROGRAM_REQUIRED",
                "This event admits preferred-program venues only",
            )
    if proposal["compliance_status"] == "NON_COMPLIANT":
        raise ApiError(
            "ERR_RATE_BENCHMARK_NON_COMPLIANT",
            "The bid is not benchmark compliant",
        )


# --------------------------------------------------------- award unwinding ----

def award_cascade(event, winner):
    """Reject the sibling live bids and unwind their sourcing artefacts."""
    for sibling in lookup.proposals_of_rfp(winner["rfp_id"]):
        if sibling["id"] == winner["id"]:
            continue
        if sibling["status"] not in enums.LIVE_PROPOSAL_STATUSES:
            continue
        sibling["status"] = "REJECTED"
        touch(sibling)
        entry = lookup.entry_for(event["id"], sibling["venue_id"])
        if entry is not None and entry["status"] != "ELIMINATED":
            eliminate_entry(entry, ELIMINATED_BY_AWARD)


def reject_contract_cascade(contract, event):
    """Approval rejection unwinds the contract and releases the commitment."""
    contract["approval_state"] = "REJECTED"
    for step in lookup.steps_of_contract(contract["id"]):
        if step["decision"] == "PENDING":
            step["decision"] = "SKIPPED"
            touch(step)
    if contract["signature_state"] in ("UNSIGNED", "PLANNER_SIGNED",
                                      "COUNTERSIGNED"):
        contract["signature_state"] = "VOIDED"
    for installment in lookup.installments_of_contract(contract["id"]):
        if installment["status"] == "SCHEDULED":
            installment["status"] = "CANCELLED"
            touch(installment)
    rollups.refresh_deposit_rollup(contract)

    proposal = db.proposals.get(contract["proposal_id"])
    if proposal is not None and proposal["status"] == "AWARDED":
        proposal["status"] = "REJECTED"
        touch(proposal)

    event["awarded_proposal_id"] = None
    event["committed_spend_usd"] = q2(0)
    if event["status"] == "AWARDED":
        event["status"] = "BID_REVIEW"
    rollups.refresh_event_rollup(event)
    rollups.refresh_budget_envelope(event)
    touch(event)
