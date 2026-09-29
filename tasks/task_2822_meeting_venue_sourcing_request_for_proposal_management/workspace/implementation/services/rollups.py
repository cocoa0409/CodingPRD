"""Derived-field recomputation (PRD sections 3.2, 3.4, 3.8, 3.9)."""
import enums
import lookup
from db import db
from money import D, q2
from services import calc


def refresh_shortlisted_count(event):
    event["shortlisted_venue_count"] = sum(
        1 for e in lookup.entries_of_event(event["id"])
        if e["status"] in enums.SHORTLISTED_COUNT_STATUSES
    )


def refresh_inspection_count(entry):
    entry["inspection_count"] = sum(
        1 for i in lookup.inspections_of_entry(entry["id"])
        if i["status"] in ("PLANNED", "COMPLETED")
    )


def refresh_submitted_count(rfp):
    rfp["submitted_count"] = sum(
        1 for p in lookup.proposals_of_rfp(rfp["id"])
        if p["status"] in enums.SUBMITTED_COUNT_STATUSES
    )


def live_proposals_of_event(event_id):
    return [
        p for p in lookup.proposals_of_event(event_id)
        if p["status"] in enums.LIVE_PROPOSAL_STATUSES
    ]


def refresh_event_rollup(event):
    """event_sourcing_rollup: cheapest live bid across every round."""
    refresh_shortlisted_count(event)
    live = [
        p for p in live_proposals_of_event(event["id"])
        if p.get("total_cost_contracted_usd") is not None
    ]
    if not live:
        event["best_total_cost_usd"] = None
        return
    best = None
    for proposal in live:
        if best is None:
            best = proposal
            continue
        if proposal["total_cost_contracted_usd"] < best["total_cost_contracted_usd"]:
            best = proposal
        elif proposal["total_cost_contracted_usd"] == best["total_cost_contracted_usd"]:
            if (proposal["created_at"], proposal["_seq"]) < (best["created_at"],
                                                             best["_seq"]):
                best = proposal
    event["best_total_cost_usd"] = q2(best["total_cost_contracted_usd"])


def refresh_budget_envelope(event):
    """budget_envelope_invariant."""
    event["budget_remaining_usd"] = q2(
        D(event["budget_ceiling_usd"])
        - D(event["committed_spend_usd"])
        - D(event["cancellation_liability_usd"])
    )


def refresh_venue_scores(venue):
    reviews = lookup.reviews_of_venue(venue["id"])
    venue["performance_review_count"] = len(reviews)
    weighted, simple = calc.performance_scores(reviews)
    venue["performance_score"] = weighted
    venue["performance_score_simple_mean"] = simple


def refresh_deposit_rollup(contract):
    rows = lookup.installments_of_contract(contract["id"])
    if not rows:
        return
    contract["deposit_paid_usd"] = q2(sum(
        (D(r["paid_amount_usd"]) for r in rows if r["status"] == "PAID"),
        D(0),
    ))
    contract["deposit_outstanding_usd"] = q2(sum(
        (D(r["amount_usd"]) for r in rows if r["status"] == "SCHEDULED"),
        D(0),
    ))


def refresh_approval_step_count(contract):
    contract["approval_step_count"] = len(lookup.steps_of_contract(contract["id"]))


def refresh_invited_count(rfp):
    rfp["invited_count"] = len(lookup.proposals_of_rfp(rfp["id"]))
