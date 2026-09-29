"""Publisher verdicts and milestone payments (PRD 3.5, 3.6, 2.11)."""

from flask import Blueprint, request

from calc import MAX_CURE_ROUNDS, cure_deadline, disbursement, reviewer_window_conflict
from envelope import created, success
from errors import ApiError
from guards import (
    ALL_ROLES,
    ROLE_PUBLISHER_FINANCE,
    ROLE_PUBLISHER_REVIEWER,
    agreement_of_milestone,
    agreement_of_payment,
    agreement_of_review,
    begin,
    body,
    find_build,
    find_payment,
    find_review,
    require_party,
    visible,
)
from ledger import (
    builds_of_milestone,
    engagements_of,
    evaluate_completion,
    recompute_ledger,
    reviews_of_build,
    unlock_dependents,
)
from listing import matches, paged
from serializers import payment as ser_payment
from serializers import review as ser_review
from store import db, fmt_instant, lock, new_id, now, now_iso, ordered, stamp_new, touch
from validation import Field, bad

bp = Blueprint("reviews", __name__)

REVIEW_FIELDS = (
    Field("build_id", "string", required=True),
    Field("verdict", "enum", required=True, values=("ACCEPTED", "CONDITIONAL", "REJECTED")),
    Field("review_window_start_at", "instant", required=True),
    Field("review_window_end_at", "instant", required=True),
    Field("conditions", "array", default=None, item="int"),
    Field("cure_days", "int", default=None, min=1, max=30),
    Field("notes", "string"),
)

AUTHORIZE_FIELDS = (Field("memo", "string"),)


def _accepting_reviewer(milestone):
    """The reviewer_user_id recorded on the accepting review of that milestone."""
    for build in builds_of_milestone(milestone):
        for review in reviews_of_build(build):
            if review["verdict"] == "ACCEPTED":
                return review["reviewer_user_id"]
    return None


@bp.post("/publisher-reviews")
def create_review():
    actor = begin([ROLE_PUBLISHER_REVIEWER])
    raw, data = body(REVIEW_FIELDS)
    verdict = data["verdict"]
    conditions = data["conditions"]
    # Structural conditional requirements of PRD 2.10.
    if verdict == "CONDITIONAL":
        if not conditions:
            bad("A CONDITIONAL verdict requires 'conditions' to be a non-empty array.")
    elif conditions:
        bad("An ACCEPTED or REJECTED verdict requires 'conditions' to be absent or empty.")
    cure_days = data["cure_days"]
    if cure_days is None:
        cure_days = 14

    with lock:
        # Rule 19: review creation resolves build_id.
        build = find_build(data["build_id"])
        milestone = db.milestones[build["milestone_id"]]
        agreement = agreement_of_milestone(milestone)
        require_party(actor, agreement)
        # Rule 23.
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        # Rule 33.
        if milestone["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_MILESTONE_NOT_UNDER_REVIEW")
        # Rule 34.
        if (
            build["gate_state"] == "SUPERSEDED"
            or build["build_number"] != milestone["latest_build_number"]
        ):
            raise ApiError("ERR_BUILD_SUPERSEDED")
        # Rule 50: cure rounds are finite.
        if verdict == "CONDITIONAL" and milestone["cure_count"] >= MAX_CURE_ROUNDS:
            raise ApiError("ERR_CURE_LIMIT_EXCEEDED")
        start = data["review_window_start_at"]
        end = data["review_window_end_at"]
        # Rule 53 deliberately precedes rule 54.
        if reviewer_window_conflict(actor.user_id, start, end):
            raise ApiError("ERR_REVIEWER_WINDOW_CONFLICT")
        # Rule 54.
        if not end > start:
            raise ApiError("ERR_INVALID_DATE_RANGE")
        # Rule 69.
        if verdict == "CONDITIONAL":
            limit = len(milestone["acceptance_criteria"])
            for index in conditions:
                if index < 0 or index >= limit:
                    raise ApiError("ERR_INVALID_CONDITION_INDEX")

        decided_at = now()
        row = {
            "id": new_id(),
            "build_id": build["id"],
            "reviewer_user_id": actor.user_id,
            "verdict": verdict,
            "conditions": list(conditions) if conditions else [],
            "cure_days": cure_days,
            "review_window_start_at": fmt_instant(start),
            "review_window_end_at": fmt_instant(end),
            "cure_deadline_at": None,
            "notes": data["notes"],
            "decided_at": fmt_instant(decided_at),
        }
        # PRD 2.4: a review exposes only id and created_at.
        row["created_at"] = now_iso()
        row["_seq"] = db.next_seq()

        if verdict == "ACCEPTED":
            _apply_acceptance(agreement, milestone)
        elif verdict == "CONDITIONAL":
            deadline = cure_deadline(decided_at, cure_days)
            row["cure_deadline_at"] = fmt_instant(deadline)
            milestone["status"] = "CURE_PENDING"
            milestone["cure_count"] += 1
            milestone["open_condition_indexes"] = list(conditions)
            milestone["cure_deadline_at"] = fmt_instant(deadline)
            touch(milestone)
        else:
            milestone["status"] = "IN_DEVELOPMENT"
            milestone["open_condition_indexes"] = []
            milestone["cure_deadline_at"] = None
            touch(milestone)
            build["gate_state"] = "SUPERSEDED"
            touch(build)

        db.reviews[row["id"]] = row
        touch(agreement)
        return created(ser_review(row))


def _apply_acceptance(agreement, milestone):
    """The five ordered cascade steps of PRD 3.5."""
    milestone["status"] = "ACCEPTED"
    milestone["accepted_at"] = now_iso()
    milestone["open_condition_indexes"] = []
    touch(milestone)

    # Step one: exactly one payment, its amount frozen at acceptance.
    payment = {
        "id": new_id(),
        "milestone_id": milestone["id"],
        "authorized_by_user_id": None,
        "scheduled_amount_cents": milestone["funded_amount_cents"] + milestone["uplift_cents"],
        "contractor_overrun_cents": None,
        "gross_amount_cents": None,
        "holdback_bps": None,
        "holdback_cents": None,
        "net_amount_cents": None,
        "status": "PENDING_AUTHORIZATION",
        "memo": None,
        "authorized_at": None,
    }
    stamp_new(payment)
    db.payments[payment["id"]] = payment

    # Step two: dependents are unlocked and their proposals promoted.
    unlock_dependents(agreement, milestone)

    # Step three: the posture is re-evaluated against the grown accepted value.
    recompute_ledger(agreement)

    # Step four: only when the posture has become RESTRICTED.
    if agreement["funding_posture"] == "RESTRICTED":
        for engagement in engagements_of(agreement):
            if engagement["status"] not in ("PROPOSED", "ACTIVE"):
                continue
            owner = db.milestones[engagement["milestone_id"]]
            if owner["status"] in ("DEFINED", "IN_DEVELOPMENT"):
                engagement["status"] = "SUSPENDED"
                touch(engagement)

    # Step five: completion, evaluated last of all.
    recompute_ledger(agreement)
    evaluate_completion(agreement)


@bp.get("/publisher-reviews/<rid>")
def read_review(rid):
    actor = begin(ALL_ROLES)
    with lock:
        review = find_review(rid)
        require_party(actor, agreement_of_review(review))
        return success(ser_review(review))


@bp.get("/publisher-reviews")
def list_reviews():
    actor = begin(ALL_ROLES)
    with lock:
        rows = [
            row for row in ordered(db.reviews.values())
            if matches(row, request.args, ("build_id", "reviewer_user_id", "verdict"))
        ]
        rows = visible(actor, rows, agreement_of_review)
        return paged(rows, request.args, ser_review)


@bp.get("/milestone-payments/<pid>")
def read_payment(pid):
    actor = begin(ALL_ROLES)
    with lock:
        payment = find_payment(pid)
        require_party(actor, agreement_of_payment(payment))
        return success(ser_payment(payment))


@bp.get("/milestone-payments")
def list_payments():
    actor = begin(ALL_ROLES)
    with lock:
        rows = [
            row for row in ordered(db.payments.values())
            if matches(row, request.args, ("milestone_id", "authorized_by_user_id", "status"))
        ]
        rows = visible(actor, rows, agreement_of_payment)
        return paged(rows, request.args, ser_payment)


@bp.post("/milestone-payments/<pid>/authorize")
def authorize_payment(pid):
    actor = begin([ROLE_PUBLISHER_FINANCE])
    _, data = body(AUTHORIZE_FIELDS)
    with lock:
        payment = find_payment(pid)
        milestone = db.milestones[payment["milestone_id"]]
        agreement = agreement_of_milestone(milestone)
        require_party(actor, agreement)
        # Rule 23, widened: ACTIVE or COMPLETED.
        if agreement["status"] not in ("ACTIVE", "COMPLETED"):
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        # Rule 35.
        if payment["status"] != "PENDING_AUTHORIZATION":
            raise ApiError("ERR_PAYMENT_NOT_PENDING")
        # Rule 45: the authorizing operator is not the accepting reviewer.
        if _accepting_reviewer(milestone) == actor.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

        computed = disbursement(payment, milestone)
        payment.update(computed)
        payment["status"] = "AUTHORIZED"
        payment["authorized_at"] = now_iso()
        payment["authorized_by_user_id"] = actor.user_id
        if data["memo"] is not None:
            payment["memo"] = data["memo"]
        touch(payment)

        recompute_ledger(agreement)
        # "moves recoupment_state from PRE_RECOUP to RECOUPING as soon as
        # advance_disbursed_cents is greater than zero".
        if (
            agreement["recoupment_state"] == "PRE_RECOUP"
            and agreement["advance_disbursed_cents"] > 0
        ):
            agreement["recoupment_state"] = "RECOUPING"
        touch(agreement)
        return success(ser_payment(payment))
