"""CouncilEvent endpoints: schedule, list, get, record-outcome."""
from flask import Blueprint, request

import db
from calculations import compute_yes_share_pct, vote_outcome
from errors import ApiError
from middleware import current_user, require_roles, require_fields, require_int, require_enum
from models import new_council_event, touch
from response import success_obj, success_list, json_body, parse_pagination, paginate
from routes_targets import get_target_or_404
from statemachines import reject_target_cascade
from util import (
    ALL_ROLES, EVENT_KINDS, parse_iso, get_clock, hearing_notice_deadline,
    REFERENDUM_TRIGGER_PCT,
)

bp = Blueprint("council_events", __name__)


def get_council_event_or_404(event_id):
    event = db.council_events.get(event_id)
    if event is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CouncilEvent not found")
    return event


def _referendum_available(target_id):
    """Latest recorded COUNCIL_VOTE is FAILED with yes_share_pct >= 50.00."""
    votes = [e for e in db.council_events_of_target(target_id)
             if e["kind"] == "COUNCIL_VOTE" and e["status"] in ("PASSED", "FAILED")]
    if not votes:
        return False
    votes.sort(key=lambda e: (e["created_at"], e["id"]))
    latest = votes[-1]
    return (latest["status"] == "FAILED"
            and latest["yes_share_pct"] is not None
            and latest["yes_share_pct"] >= REFERENDUM_TRIGGER_PCT)


@bp.route("/acquisitions/targets/<target_id>/council-events", methods=["POST"])
def create_council_event(target_id):
    _, role = current_user()
    require_roles(role, ["MunicipalClerk"])
    target = get_target_or_404(target_id)
    if target["status"] != "MUNICIPAL_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Target is not in MUNICIPAL_REVIEW")
    body = json_body()
    require_fields(body, ["kind", "scheduled_start", "scheduled_end"])
    kind = require_enum(body, "kind", EVENT_KINDS)
    start = parse_iso(body.get("scheduled_start"))
    end = parse_iso(body.get("scheduled_end"))
    if start is None or end is None:
        raise ApiError("ERR_INVALID_REQUEST", 422,
                       "scheduled_start/scheduled_end must be ISO 8601 timestamps")
    # Priority 6: window sanity.
    if not end > start:
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "scheduled_end must be strictly after scheduled_start")
    # Priority 7: half-open overlap against every prior event of the target.
    for other in db.council_events_of_target(target_id):
        o_start = parse_iso(other["scheduled_start"])
        o_end = parse_iso(other["scheduled_end"])
        if start < o_end and o_start < end:
            raise ApiError("ERR_EVENT_OVERLAP", 409,
                           "Event window overlaps an existing event of the target")
    # Priority 11: referendum availability gate.
    if kind == "REFERENDUM" and not _referendum_available(target_id):
        raise ApiError("ERR_REFERENDUM_NOT_AVAILABLE", 409,
                       "REFERENDUM requires a prior FAILED council vote in the referendum band")
    event = new_council_event(target["id"], kind, body["scheduled_start"],
                              body["scheduled_end"])
    return success_obj(event, status=201)


@bp.route("/acquisitions/targets/<target_id>/council-events", methods=["GET"])
def list_council_events(target_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    get_target_or_404(target_id)
    limit, offset = parse_pagination()
    records = db.council_events_of_target(target_id)
    kind = request.args.get("kind")
    if kind is not None:
        records = [e for e in records if e["kind"] == kind]
    records.sort(key=lambda e: (e["created_at"], e["id"]))
    page, total = paginate(records, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/acquisitions/council-events/<event_id>", methods=["GET"])
def get_council_event(event_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    return success_obj(get_council_event_or_404(event_id))


@bp.route("/acquisitions/council-events/<event_id>/record-outcome", methods=["POST"])
def record_outcome(event_id):
    _, role = current_user()
    require_roles(role, ["MunicipalClerk"])
    event = get_council_event_or_404(event_id)
    target = db.targets[event["target_id"]]
    # Priority 5: kind/state legality before business rules.
    if event["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Event is not in SCHEDULED")
    body = json_body()
    if event["kind"] == "PUBLIC_HEARING":
        if "yes_votes" in body or "no_votes" in body:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Votes may not be recorded against a PUBLIC_HEARING")
        event["status"] = "HELD"
        touch(event)
        return success_obj(event)

    # COUNCIL_VOTE / REFERENDUM: votes required, sum > 0.
    if "yes_votes" not in body or "no_votes" not in body:
        raise ApiError("ERR_INVALID_REQUEST", 422,
                       "yes_votes and no_votes are required for a vote outcome")
    yes_votes = require_int(body, "yes_votes", minimum=0)
    no_votes = require_int(body, "no_votes", minimum=0)
    if yes_votes + no_votes <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "yes_votes + no_votes must be > 0")
    share = compute_yes_share_pct(yes_votes, no_votes)
    passed, referendum_available, hard_fail = vote_outcome(event["kind"], share)

    # Priority 8: hearing notice for any council-vote outcome.
    if event["kind"] == "COUNCIL_VOTE":
        now = get_clock()
        hearings = [e for e in db.council_events_of_target(event["target_id"])
                    if e["kind"] == "PUBLIC_HEARING" and e["status"] == "HELD"]
        if not any(hearing_notice_deadline(parse_iso(h["scheduled_end"])) <= now
                   for h in hearings):
            raise ApiError("ERR_HEARING_NOTICE", 409,
                           "No HELD public hearing with sufficient notice for this target")

    event["yes_votes"] = yes_votes
    event["no_votes"] = no_votes
    event["yes_share_pct"] = share
    event["status"] = "PASSED" if passed else "FAILED"
    touch(event)

    if event["kind"] == "COUNCIL_VOTE":
        if passed:
            target["council_approved"] = True
            touch(target)
        elif referendum_available:
            # Close-call band: target stays in MUNICIPAL_REVIEW, no rejection.
            pass
        else:
            reject_target_cascade(target)
    else:  # REFERENDUM
        if passed:
            target["council_approved"] = True
            touch(target)
        else:
            reject_target_cascade(target)
    return success_obj(event)
