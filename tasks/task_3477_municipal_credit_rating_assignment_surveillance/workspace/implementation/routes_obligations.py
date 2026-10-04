"""Disclosure obligations (PRD §3.5): listed in period order; the issuer's
submission is classified on-time/late by the clock and schedules the next
annual period while the rating is PUBLISHED."""
from flask import Blueprint, request

from auth import auth, authenticate
from constants import ROLE_ISSUER
from envelope import paginate, parse_pagination, success_array, success_object
from errors import (
    ERR_NOT_RESOURCE_OWNER,
    ERR_OBLIGATION_STATE_INVALID,
    raise_err,
)
from services_disclosure import (
    create_next_obligation,
    obligations_of,
    recompute_delinquent_flag,
    recompute_posture,
)
from store import db, touch
from validators import body, get_obligation, get_rating  # noqa: F401 (body kept for symmetry)

bp = Blueprint("obligations", __name__)


@bp.route("/muni/ratings/<rating_id>/disclosure-obligations", methods=["GET"])
def list_obligations(rating_id):
    authenticate()
    rating = get_rating(rating_id)
    items = obligations_of(rating["id"])  # period order
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/disclosure-obligations/<obligation_id>", methods=["GET"])
def get_one_obligation(obligation_id):
    authenticate()
    return success_object(get_obligation(obligation_id))


@bp.route("/muni/disclosure-obligations/<obligation_id>/submit", methods=["POST"])
def submit_obligation(obligation_id):
    user_id, role = auth([ROLE_ISSUER])
    obligation = get_obligation(obligation_id)
    rating = get_rating(obligation["rating_id"])

    # Priority 5: the issuer that owns the obligation's rating submits.
    if rating["issuer_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "only the rating's issuer may submit this disclosure")

    # Priority 6: an already-submitted obligation accepts no further submission.
    if obligation["status"] in ("SUBMITTED_ON_TIME", "SUBMITTED_LATE"):
        raise_err(ERR_OBLIGATION_STATE_INVALID, "obligation already submitted")

    clock = db.now()
    obligation["submitted_at"] = clock
    obligation["status"] = "SUBMITTED_ON_TIME" if clock <= obligation["due_at"] else "SUBMITTED_LATE"
    touch(obligation)

    # The next annual period is scheduled only while the rating is PUBLISHED;
    # a cure while WITHDRAWN creates nothing (PRD §3.5).
    if rating["status"] == "PUBLISHED":
        create_next_obligation(rating, obligation)
        recompute_posture(rating)
    recompute_delinquent_flag(rating["issuer_id"])
    return success_object(obligation)
