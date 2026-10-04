"""Ratings (PRD §3.4, §3.5): reads, publication after the appeal window,
OCC-guarded surveillance actions (AFFIRM/UPGRADE/DOWNGRADE/WITHDRAW), and
reinstatement of non-disclosure withdrawals."""
from flask import Blueprint, request

import timeutil
from auth import auth, authenticate
from constants import (
    APPEAL_WINDOW_HOURS,
    CAUSE_REINSTATEMENT,
    CAUSE_SURVEILLANCE_ACTION,
    EVENT_RATING_ACTION,
    EVENT_RATING_PUBLISHED,
    EVENT_RATING_REINSTATED,
    EVENT_RATING_WITHDRAWN,
    NOTCH_SCALE,
    OUTLOOKS,
    RATING_ACTIONS,
    REINSTATE_WINDOW_DAYS,
    ROLE_LEAD_ANALYST,
    ROLE_SURVEILLANCE_OFFICER,
    WITHDRAW_REASONS_MANUAL,
)
from envelope import paginate, parse_pagination, success_array, success_object
from errors import (
    ERR_AFFIRM_BLOCKED_BY_POSTURE,
    ERR_APPEAL_PENDING,
    ERR_INVALID_REQUEST,
    ERR_NOTCH_STEP_INVALID,
    ERR_PUBLISH_WINDOW_NOT_ELAPSED,
    ERR_RATING_STATE_INVALID,
    ERR_REINSTATE_NOT_PERMITTED,
    ERR_REINSTATE_WINDOW_EXPIRED,
    ERR_REVIEW_PENDING,
    ERR_STALE_RATING_VERSION,
    ERR_UNRESOLVED_OBLIGATIONS,
    ERR_UPGRADE_BLOCKED_BY_POSTURE,
    raise_err,
)
from services_disclosure import (
    create_first_obligation,
    create_next_obligation,
    last_obligation,
    obligations_of,
    recompute_posture,
)
from store import db, notify, touch
from validators import (
    body,
    get_engagement,
    get_issuer,
    get_rating,
    is_int,
    optional_enum,
    present,
    require_enum,
    require_fields,
)

bp = Blueprint("ratings", __name__)


@bp.route("/muni/ratings", methods=["GET"])
def list_ratings():
    authenticate()
    items = list(db.ratings.values())
    for field in ("issuer_id", "engagement_id", "criteria_version_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [r for r in items if r.get(field) == value]
    # Insertion order: created_at ascending.
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/ratings/<rating_id>", methods=["GET"])
def get_one_rating(rating_id):
    authenticate()
    return success_object(get_rating(rating_id))


@bp.route("/muni/ratings/<rating_id>/publish", methods=["POST"])
def publish_rating(rating_id):
    auth([ROLE_LEAD_ANALYST])
    rating = get_rating(rating_id)
    payload = body()
    require_fields(payload, ["outlook", "rationale"])
    require_enum(payload, "outlook", OUTLOOKS)

    # Priority 6: only an ASSIGNED rating publishes.
    if rating["status"] != "ASSIGNED":
        raise_err(ERR_RATING_STATE_INVALID, "rating is not ASSIGNED")

    # Priority 9: the 120h appeal window must have elapsed (strictly).
    clock = db.now()
    if not (clock > timeutil.add_hours(rating["assigned_at"], APPEAL_WINDOW_HOURS)):
        raise_err(ERR_PUBLISH_WINDOW_NOT_ELAPSED, "the 120h appeal window has not elapsed")

    # A FILED appeal blocks publication until decided.
    if any(a["rating_id"] == rating["id"] and a["status"] == "FILED" for a in db.appeals.values()):
        raise_err(ERR_APPEAL_PENDING, "an appeal is pending for this rating")

    rating["outlook"] = payload["outlook"]
    rating["rationale"] = payload["rationale"]
    rating["published_at"] = clock
    rating["status"] = "PUBLISHED"
    touch(rating)

    engagement = get_engagement(rating["engagement_id"])
    engagement["status"] = "PUBLISHED"
    touch(engagement)

    issuer = get_issuer(rating["issuer_id"])
    create_first_obligation(rating, issuer)
    notify(
        rating["issuer_id"],
        EVENT_RATING_PUBLISHED,
        rating["id"],
        "Rating %s published at %s." % (rating["id"], rating["notch"]),
    )
    return success_object(rating)


@bp.route("/muni/ratings/<rating_id>/actions", methods=["POST"])
def rating_action(rating_id):
    auth([ROLE_LEAD_ANALYST, ROLE_SURVEILLANCE_OFFICER])
    rating = get_rating(rating_id)
    payload = body()

    # Priority 4: action/rationale/expected version required; withdraw_reason
    # present exactly when the action is WITHDRAW; enums in range.
    require_fields(payload, ["action", "rationale", "expected_rating_version"])
    action = require_enum(payload, "action", RATING_ACTIONS)
    if action == "WITHDRAW":
        if not present(payload, "withdraw_reason"):
            raise_err(ERR_INVALID_REQUEST, "withdraw_reason is required when action is WITHDRAW")
        if payload["withdraw_reason"] not in WITHDRAW_REASONS_MANUAL:
            raise_err(ERR_INVALID_REQUEST, "withdraw_reason must be ISSUER_REQUEST or CRITERIA")
    elif present(payload, "withdraw_reason"):
        raise_err(ERR_INVALID_REQUEST, "withdraw_reason is permitted only when action is WITHDRAW")
    new_notch = optional_enum(payload, "new_notch", NOTCH_SCALE)
    new_outlook = optional_enum(payload, "new_outlook", OUTLOOKS)

    # Priority 6: actions are permitted only while PUBLISHED.
    if rating["status"] != "PUBLISHED":
        raise_err(ERR_RATING_STATE_INVALID, "rating is not PUBLISHED")

    # Priority 7: OCC on the rating version.
    if not is_int(payload["expected_rating_version"]) or payload[
        "expected_rating_version"
    ] != rating["version"]:
        raise_err(ERR_STALE_RATING_VERSION, "expected_rating_version does not match the rating version")

    # Priority 10(l): an open criteria review gates every action.
    if rating["review_pending"]:
        raise_err(ERR_REVIEW_PENDING, "a criteria review is pending for this rating")

    # Per-action posture gates and the adjacent-notch rule.
    if action == "AFFIRM":
        if rating["surveillance_posture"] not in ("CURRENT", "GRACE"):
            raise_err(ERR_AFFIRM_BLOCKED_BY_POSTURE, "AFFIRM blocked while posture is DELINQUENT")
    elif action == "UPGRADE":
        if rating["surveillance_posture"] != "CURRENT":
            raise_err(ERR_UPGRADE_BLOCKED_BY_POSTURE, "UPGRADE requires a CURRENT posture")
        _require_one_step(rating["notch"], new_notch, better=True)
    elif action == "DOWNGRADE":
        _require_one_step(rating["notch"], new_notch, better=False)

    clock = db.now()
    if action == "WITHDRAW":
        rating["status"] = "WITHDRAWN"
        rating["withdraw_reason"] = payload["withdraw_reason"]
        rating["withdrawn_at"] = clock
        rating["notch_at_withdrawal"] = rating["notch"]
        if new_outlook is not None:
            rating["outlook"] = new_outlook
        touch(rating)
        notify(
            rating["issuer_id"],
            EVENT_RATING_WITHDRAWN,
            rating["id"],
            "Rating %s withdrawn (%s)." % (rating["id"], payload["withdraw_reason"]),
        )
        return success_object(rating)

    if action in ("UPGRADE", "DOWNGRADE"):
        rating["notch"] = new_notch
    if new_outlook is not None:
        rating["outlook"] = new_outlook
    rating["notch_history"].append(
        {"notch": rating["notch"], "changed_at": clock, "cause": CAUSE_SURVEILLANCE_ACTION}
    )
    touch(rating)
    notify(
        rating["issuer_id"],
        EVENT_RATING_ACTION,
        rating["id"],
        "Rating %s action %s; notch %s." % (rating["id"], action, rating["notch"]),
    )
    return success_object(rating)


def _require_one_step(current_notch, new_notch, better):
    """UPGRADE/DOWNGRADE move exactly one notch step on the scale."""
    if new_notch is None:
        raise_err(ERR_NOTCH_STEP_INVALID, "new_notch is required and must be one step away")
    current_idx = NOTCH_SCALE.index(current_notch)
    target_idx = current_idx - 1 if better else current_idx + 1
    if NOTCH_SCALE.index(new_notch) != target_idx:
        raise_err(ERR_NOTCH_STEP_INVALID, "new_notch must be exactly one notch step")


@bp.route("/muni/ratings/<rating_id>/reinstate", methods=["POST"])
def reinstate_rating(rating_id):
    auth([ROLE_SURVEILLANCE_OFFICER])
    rating = get_rating(rating_id)

    # Priority 6: WITHDRAWN only, and only for NON_DISCLOSURE withdrawals.
    if rating["status"] != "WITHDRAWN":
        raise_err(ERR_RATING_STATE_INVALID, "rating is not WITHDRAWN")
    if rating["withdraw_reason"] != "NON_DISCLOSURE":
        raise_err(ERR_REINSTATE_NOT_PERMITTED, "only non-disclosure withdrawals may be reinstated")

    # Priority 9: within 180 days of withdrawal (boundary allowed).
    clock = db.now()
    if clock > timeutil.add_days(rating["withdrawn_at"], REINSTATE_WINDOW_DAYS):
        raise_err(ERR_REINSTATE_WINDOW_EXPIRED, "the 180-day reinstatement window has expired")

    # Priority 10(n): every obligation of the rating must be resolved.
    obligations = obligations_of(rating["id"])
    if any(o["status"] not in ("SUBMITTED_ON_TIME", "SUBMITTED_LATE") for o in obligations):
        raise_err(ERR_UNRESOLVED_OBLIGATIONS, "all disclosure obligations must be resolved first")

    rating["status"] = "PUBLISHED"
    rating["notch"] = rating["notch_at_withdrawal"]
    recompute_posture(rating)  # all obligations resolved -> CURRENT
    if not any(o["status"] in ("PENDING", "OVERDUE", "DELINQUENT", "DEFAULTED") for o in obligations):
        last = last_obligation(rating["id"])
        if last is not None:
            create_next_obligation(rating, last)
    rating["notch_history"].append(
        {"notch": rating["notch"], "changed_at": clock, "cause": CAUSE_REINSTATEMENT}
    )
    touch(rating)
    notify(
        rating["issuer_id"],
        EVENT_RATING_REINSTATED,
        rating["id"],
        "Rating %s reinstated at %s." % (rating["id"], rating["notch"]),
    )
    return success_object(rating)
