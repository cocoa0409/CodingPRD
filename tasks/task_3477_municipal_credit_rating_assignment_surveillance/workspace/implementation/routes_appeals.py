"""Appeals (PRD §3.4): filed on new information within 120h of assignment,
one per rating; the chair's decision upholds (remand + re-deliberation) or
denies."""
from flask import Blueprint, request

import timeutil
from auth import auth, authenticate
from constants import (
    APPEAL_DECISIONS,
    APPEAL_WINDOW_HOURS,
    DOCUMENT_REGISTRY,
    EVENT_APPEAL_DENIED,
    EVENT_APPEAL_UPHELD,
    ROLE_COMMITTEE_CHAIR,
    ROLE_ISSUER,
)
from envelope import paginate, parse_pagination, success_array, success_object
from errors import (
    ERR_APPEAL_ALREADY_EXISTS,
    ERR_APPEAL_STATE_INVALID,
    ERR_APPEAL_WINDOW_CLOSED,
    ERR_INVALID_REQUEST,
    ERR_NO_NEW_INFORMATION,
    ERR_NOT_RESOURCE_OWNER,
    ERR_RATING_STATE_INVALID,
    raise_err,
)
from store import db, new_entity, notify, touch
from validators import (
    body,
    get_appeal,
    get_engagement,
    get_rating,
    present,
    require_enum,
    require_fields,
)

bp = Blueprint("appeals", __name__)


@bp.route("/muni/ratings/<rating_id>/appeals", methods=["POST"])
def file_appeal(rating_id):
    user_id, role = auth([ROLE_ISSUER])
    rating = get_rating(rating_id)
    payload = body()

    # Priority 4: the field must be present and a list.
    require_fields(payload, ["new_information_codes"])
    codes = payload["new_information_codes"]
    if not isinstance(codes, list):
        raise_err(ERR_INVALID_REQUEST, "new_information_codes must be a list")

    # Priority 5: the issuer that owns the rating files the appeal.
    if rating["issuer_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "only the rating's issuer may file an appeal")

    # Priority 6: appeals exist only while the rating is ASSIGNED.
    if rating["status"] != "ASSIGNED":
        raise_err(ERR_RATING_STATE_INVALID, "rating is not ASSIGNED")

    # Priority 9: the window is assigned_at + 120h inclusive.
    clock = db.now()
    if clock > timeutil.add_hours(rating["assigned_at"], APPEAL_WINDOW_HOURS):
        raise_err(ERR_APPEAL_WINDOW_CLOSED, "the 120h appeal window has closed")

    # Priority 10(f): one appeal per rating, then new-information only.
    if any(a["rating_id"] == rating["id"] for a in db.appeals.values()):
        raise_err(ERR_APPEAL_ALREADY_EXISTS, "an appeal already exists for this rating")
    engagement = get_engagement(rating["engagement_id"])
    received = set(engagement["received_document_codes"])
    if (
        not codes
        or any(code not in DOCUMENT_REGISTRY for code in codes)
        or any(code in received for code in codes)
    ):
        raise_err(
            ERR_NO_NEW_INFORMATION,
            "new_information_codes must be non-empty, registered, and disjoint from received documents",
        )

    ent = new_entity()
    ent.update(
        rating_id=rating["id"],
        new_information_codes=list(codes),
        status="FILED",
        decision_rationale=None,
        decided_at=None,
    )
    db.appeals[ent["id"]] = ent
    return success_object(ent, status=201)


@bp.route("/muni/ratings/<rating_id>/appeals", methods=["GET"])
def list_appeals(rating_id):
    authenticate()
    rating = get_rating(rating_id)
    items = [a for a in db.appeals.values() if a["rating_id"] == rating["id"]]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/appeals/<appeal_id>", methods=["GET"])
def get_one_appeal(appeal_id):
    authenticate()
    return success_object(get_appeal(appeal_id))


@bp.route("/muni/appeals/<appeal_id>/decide", methods=["POST"])
def decide_appeal(appeal_id):
    auth([ROLE_COMMITTEE_CHAIR])
    appeal = get_appeal(appeal_id)
    payload = body()
    require_fields(payload, ["decision", "rationale"])
    decision = require_enum(payload, "decision", APPEAL_DECISIONS)

    # Priority 6: only a FILED appeal can be decided.
    if appeal["status"] != "FILED":
        raise_err(ERR_APPEAL_STATE_INVALID, "appeal is not FILED")

    clock = db.now()
    appeal["status"] = decision
    appeal["decision_rationale"] = payload["rationale"]
    appeal["decided_at"] = clock
    touch(appeal)

    rating = get_rating(appeal["rating_id"])
    if decision == "UPHELD":
        # The rating is remanded (terminal); the engagement returns to
        # COMMITTEE_READY to re-deliberate on the new information.
        rating["status"] = "REMANDED"
        touch(rating)
        engagement = get_engagement(rating["engagement_id"])
        engagement["status"] = "COMMITTEE_READY"
        touch(engagement)
        notify(
            rating["issuer_id"],
            EVENT_APPEAL_UPHELD,
            rating["id"],
            "Appeal %s upheld; rating %s remanded for re-deliberation." % (appeal["id"], rating["id"]),
        )
    else:
        notify(
            rating["issuer_id"],
            EVENT_APPEAL_DENIED,
            rating["id"],
            "Appeal %s denied; rating %s stands." % (appeal["id"], rating["id"]),
        )
    return success_object(appeal)
