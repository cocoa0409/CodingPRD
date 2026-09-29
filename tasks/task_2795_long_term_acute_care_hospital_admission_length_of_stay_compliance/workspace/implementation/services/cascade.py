"""The four-level discharge cascade and its compensating reversal (PRD 2.9, 3.5, 3.6)."""

from datetime import timedelta

import calc
import lookup
from auth import SYSTEM_ACTOR
from clock import now
from store import db, new_row, touch

from services import pricing, scoring

AUTO_QUERY_TYPE = "IDT_PARTICIPATION"
AUTO_QUERY_PROMPT = (
    "Auto-issued by the discharge cascade: this chart scored in the HIGH denial-risk band. "
    "Please document interdisciplinary team participation supporting the length of stay."
)


def issue_query(review, stay, query_type, prompt_text, issued_by_user_id):
    query = new_row("queries")
    issued_at = now()
    query.update({
        "denial_risk_review_id": review["id"],
        "stay_id": stay["id"],
        "answered_by_physician_id": None,
        "query_type": query_type,
        "prompt_text": prompt_text,
        "response_text": None,
        "issued_at": issued_at,
        "due_at": issued_at + timedelta(hours=calc.QUERY_RESPONSE_WINDOW_HOURS),
        "answered_at": None,
        "status": "ISSUED",
        "issued_by_user_id": issued_by_user_id,
        "closed_by_user_id": None,
    })
    db.queries[query["id"]] = query
    return query


def run_discharge(stay, discharged_at, disposition, estimated_cost_cents, actor_user_id):
    """Levels one through four of the discharge cascade.

    Level one discharges the stay and banks its covered length of stay, level two
    prices a DRAFT determination as SYSTEM, level three opens and scores the
    denial-risk review, and level four auto-issues a query when the band is HIGH.
    """
    # ---- level one ---- #
    stay["clinical_status"] = "DISCHARGED"
    stay["discharged_at"] = discharged_at
    stay["discharge_disposition"] = disposition
    stay["estimated_cost_cents"] = estimated_cost_cents
    stay["covered_los_days"] = calc.covered_los_days(stay)

    # ---- level two ---- #
    drg = pricing.drg_in_force(stay)
    determination = pricing.create_determination(stay, drg, SYSTEM_ACTOR, None)
    touch(stay)

    # ---- level three ---- #
    review = scoring.open_review(stay, actor_user_id if actor_user_id else SYSTEM_ACTOR)

    # ---- level four ---- #
    if review["risk_band"] == "HIGH":
        issue_query(review, stay, AUTO_QUERY_TYPE, AUTO_QUERY_PROMPT, SYSTEM_ACTOR)
        review["status"] = "QUERIES_ISSUED"

    return determination, review


def unwind_stay_money(stay, period):
    """Recombination runs the discharge cascade backwards on the reopened parent."""
    ledger_changed = False
    for determination in lookup.stay_determinations(stay["id"]):
        if determination["status"] not in ("DRAFT", "FINAL"):
            continue
        was_final = determination["status"] == "FINAL"
        determination["status"] = "VOIDED"
        determination["void_reason"] = "RECOMBINED"
        touch(determination)
        if was_final and period is not None:
            period["total_payment_cents"] -= determination["total_payment_cents"]
            period["final_determination_count"] -= 1
            ledger_changed = True

    review = lookup.stay_live_review(stay["id"])
    if review is not None:
        for query in lookup.review_queries(review["id"]):
            if query["status"] in ("ISSUED", "ANSWERED"):
                query["status"] = "VOIDED"
                touch(query)
        review["status"] = "VOIDED"
        touch(review)

    if ledger_changed:
        touch(period)
