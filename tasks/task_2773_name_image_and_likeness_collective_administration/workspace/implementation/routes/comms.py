"""Communication logs: the immutable program-contact audit trail."""

from flask import Blueprint, request

import auth
import clock
import envelope
import lookup
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("comms", __name__)

ACTOR_ROLES = ["HEAD_COACH", "PROGRAM_STAFF", "COLLECTIVE_DIRECTOR", "COMPLIANCE_OFFICER"]
CHANNELS = ["DIRECT_MESSAGE", "TEAM_MEETING", "PUBLIC_POST", "INSTITUTION_PORTAL"]
TOPICS = ["DEAL_TERMS", "DEAL_SOLICITATION", "GENERAL_PROGRAM", "COMPLIANCE_NOTICE"]
VERDICTS = ["PERMITTED", "PERMITTED_WITH_DISCLOSURE", "PROHIBITED"]
PROGRAM_ACTORS = ("HEAD_COACH", "PROGRAM_STAFF")
DEAL_TOPICS = ("DEAL_TERMS", "DEAL_SOLICITATION")


def _adjudicate(collective, athlete, actor_role, channel, topic):
    """Four clauses, in order; the first that matches decides both fields."""
    if athlete is not None and athlete["eligibility_status"] != "ENROLLED":
        return "PROHIBITED", "ATHLETE_NOT_ENROLLED"
    if actor_role in PROGRAM_ACTORS and topic in DEAL_TOPICS:
        if collective["communication_policy"] == "STRICT_SEPARATION":
            return "PROHIBITED", "COACH_DEAL_TERMS_BARRED"
        if channel == "INSTITUTION_PORTAL":
            return "PERMITTED_WITH_DISCLOSURE", "MONITORED_CHANNEL_REQUIRED"
        return "PROHIBITED", "MONITORED_CHANNEL_REQUIRED"
    if actor_role == "COLLECTIVE_DIRECTOR" and topic == "DEAL_TERMS" and channel == "PUBLIC_POST":
        return "PERMITTED_WITH_DISCLOSURE", "MONITORED_CHANNEL_REQUIRED"
    return "PERMITTED", "POLICY_ALLOWS"


@bp.route("/nil/communication-logs", methods=["POST"])
def create_log():
    auth.authenticate([auth.COLLECTIVE_DIRECTOR, auth.COMPLIANCE_OFFICER])
    body = shape.body()
    collective_id = shape.string_field(body, "collective_id", required=True)
    actor_role = shape.enum_field(body, "actor_role", ACTOR_ROLES, required=True)
    channel = shape.enum_field(body, "channel", CHANNELS, required=True)
    topic = shape.enum_field(body, "topic", TOPICS, required=True)
    athlete_id = shape.string_field(body, "athlete_id")
    note = shape.string_field(body, "note", allow_empty=True)

    collective = lookup.collective(collective_id)
    athlete = lookup.athlete(athlete_id) if athlete_id is not None else None

    if athlete is not None and athlete["collective_id"] != collective["id"]:
        raise ApiError("ERR_CROSS_COLLECTIVE_REFERENCE")

    verdict, rationale = _adjudicate(collective, athlete, actor_role, channel, topic)
    now = clock.now()
    row = {
        "id": store.new_id(),
        "collective_id": collective["id"],
        "athlete_id": athlete["id"] if athlete is not None else None,
        "actor_role": actor_role,
        "channel": channel,
        "topic": topic,
        "note": note,
        "verdict": verdict,
        "rationale_code": rationale,
        "logged_at": now,
        "sequence_no": store.next_seq("communication_log"),
        "created_at": now,
    }
    store.communication_logs[row["id"]] = row
    return envelope.object_response(serialize.communication_log(row), 201)


@bp.route("/nil/communication-logs/<log_id>", methods=["GET"])
def read_log(log_id):
    auth.authenticate(auth.NON_ATHLETE_ROLES)
    row = lookup.communication_log(log_id)
    return envelope.object_response(serialize.communication_log(row))


@bp.route("/nil/communication-logs", methods=["GET"])
def list_logs():
    auth.authenticate(auth.NON_ATHLETE_ROLES)
    limit, offset = envelope.read_pagination(request.args)
    collective_id = envelope.id_filter(request.args, "collective_id")
    athlete_id = envelope.id_filter(request.args, "athlete_id")
    actor_role = envelope.enum_filter(request.args, "actor_role", ACTOR_ROLES)
    verdict = envelope.enum_filter(request.args, "verdict", VERDICTS)
    rows = store.ordered(store.communication_logs.values())
    if collective_id is not None:
        rows = [r for r in rows if r["collective_id"] == collective_id]
    if athlete_id is not None:
        rows = [r for r in rows if r["athlete_id"] == athlete_id]
    if actor_role is not None:
        rows = [r for r in rows if r["actor_role"] == actor_role]
    if verdict is not None:
        rows = [r for r in rows if r["verdict"] == verdict]
    return envelope.list_response([serialize.communication_log(r) for r in rows], limit, offset)
