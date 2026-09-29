"""Path-segment and body foreign-key resolution (PRD section 2.7)."""
from db import db, ordered
from errors import ApiError


def _get(table, key, error_id):
    row = table.get(key)
    if row is None:
        raise ApiError(error_id, "No such resource: %s" % key)
    return row


def event(event_id):
    return _get(db.events, event_id, "ERR_EVENT_NOT_FOUND")


def venue(venue_id):
    return _get(db.venues, venue_id, "ERR_VENUE_NOT_FOUND")


def entry(entry_id):
    return _get(db.entries, entry_id, "ERR_SHORTLIST_ENTRY_NOT_FOUND")


def inspection(inspection_id):
    return _get(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")


def rfp(rfp_id):
    return _get(db.rfps, rfp_id, "ERR_RFP_NOT_FOUND")


def proposal(proposal_id):
    return _get(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")


def evaluation(evaluation_id):
    return _get(db.evaluations, evaluation_id, "ERR_PROPOSAL_NOT_FOUND")


def counter(counter_id):
    return _get(db.counters, counter_id, "ERR_COUNTER_NOT_FOUND")


def contract(contract_id):
    return _get(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")


def step(step_id):
    return _get(db.steps, step_id, "ERR_APPROVAL_STEP_NOT_FOUND")


def installment(installment_id):
    return _get(db.installments, installment_id, "ERR_INSTALLMENT_NOT_FOUND")


def benchmark(benchmark_id):
    return _get(db.benchmarks, benchmark_id, "ERR_BENCHMARK_NOT_FOUND")


def report(report_id):
    return _get(db.reports, report_id, "ERR_REPORT_NOT_FOUND")


def review(review_id):
    return _get(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")


# ------------------------------------------------------------ collections ----

def entries_of_event(event_id):
    return ordered([e for e in db.entries.values() if e["event_id"] == event_id])


def inspections_of_entry(entry_id):
    return ordered(
        [i for i in db.inspections.values() if i["shortlist_entry_id"] == entry_id]
    )


def inspections_of_venue(venue_id):
    return ordered([i for i in db.inspections.values() if i["venue_id"] == venue_id])


def rfps_of_event(event_id):
    return ordered([r for r in db.rfps.values() if r["event_id"] == event_id])


def proposals_of_rfp(rfp_id):
    return ordered([p for p in db.proposals.values() if p["rfp_id"] == rfp_id])


def proposals_of_event(event_id):
    rfp_ids = set(r["id"] for r in db.rfps.values() if r["event_id"] == event_id)
    return ordered([p for p in db.proposals.values() if p["rfp_id"] in rfp_ids])


def evaluations_of_proposal(proposal_id):
    return ordered(
        [e for e in db.evaluations.values() if e["proposal_id"] == proposal_id]
    )


def counters_of_proposal(proposal_id):
    return sorted(
        [c for c in db.counters.values() if c["proposal_id"] == proposal_id],
        key=lambda c: c["round_seq"],
    )


def contracts_of_event(event_id):
    return ordered([c for c in db.contracts.values() if c["event_id"] == event_id])


def contracts_of_venue(venue_id):
    return ordered([c for c in db.contracts.values() if c["venue_id"] == venue_id])


def steps_of_contract(contract_id):
    return sorted(
        [s for s in db.steps.values() if s["contract_id"] == contract_id],
        key=lambda s: s["step_seq"],
    )


def installments_of_contract(contract_id):
    return sorted(
        [i for i in db.installments.values() if i["contract_id"] == contract_id],
        key=lambda i: i["installment_seq"],
    )


def reports_of_event(event_id):
    return ordered([r for r in db.reports.values() if r["event_id"] == event_id])


def reviews_of_venue(venue_id):
    return ordered([r for r in db.reviews.values() if r["venue_id"] == venue_id])


def event_of_rfp(rfp_row):
    return db.events.get(rfp_row["event_id"])


def event_of_proposal(proposal_row):
    rfp_row = db.rfps.get(proposal_row["rfp_id"])
    if rfp_row is None:
        return None
    return db.events.get(rfp_row["event_id"])


def entry_for(event_id, venue_id):
    for row in entries_of_event(event_id):
        if row["venue_id"] == venue_id:
            return row
    return None


def find_benchmark(destination_tier, program_type):
    for row in db.benchmarks.values():
        if (row["destination_tier"] == destination_tier
                and row["program_type"] == program_type):
            return row
    return None


def live_contract_of_event(event_id):
    """The event's Contract that has not been voided/terminated or cancelled."""
    for row in reversed(contracts_of_event(event_id)):
        if (row["signature_state"] not in ("TERMINATED", "VOIDED")
                and row["approval_state"] not in ("REJECTED", "CANCELLED")):
            return row
    return None


def executed_contract_of_event(event_id):
    for row in reversed(contracts_of_event(event_id)):
        if row["signature_state"] == "EXECUTED":
            return row
    return None
