"""Judge certifications.

  POST /op/judges                    register a certified judge
  GET  /op/judges                    list certifications
  GET  /op/judges/{ref}              retrieve one
  POST /op/judges/{ref}/transition   RECORD_PRACTICE_EVENT / DECERTIFY

A judge certification is addressed by the caller-supplied `ref` value rather
than by a server-minted id (§2.11).
"""

from flask import Blueprint, request

import db as store
import models
import response as envelope
from errors import fail
from middleware import (
    ROLE_OPS_ADMIN, ROLE_JUDGE,
    STRING,
    require_role, check_body, check_query_enums, require_action,
)

bp = Blueprint("judges", __name__)

LEVELS = ("LEVEL_1", "LEVEL_2", "LEVEL_3")
JUDGE_STATUSES = ("ACTIVE", "DECERTIFIED")
JUDGE_ACTIONS = ("RECORD_PRACTICE_EVENT", "DECERTIFY")


@bp.route("/op/judges", methods=["POST"])
def create_judge():
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("judge_ref", "name", "level"),
        types={"judge_ref": STRING, "name": STRING, "level": STRING},
        enums={"level": LEVELS},
    )

    # judge_ref is globally unique across JudgeCertification rows.
    if body["judge_ref"] in store.db.judge_certifications:
        fail("ERR_DUPLICATE_JUDGE_REF",
             "judge_ref '%s' is already registered." % body["judge_ref"])

    row = store.insert_judge_certification(body["judge_ref"], body["name"], body["level"])
    return envelope.object_response(models.judge_view(row), status=201)


@bp.route("/op/judges", methods=["GET"])
def list_judges():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_JUDGE))
    check_query_enums(request, {"level": LEVELS, "status": JUDGE_STATUSES})
    rows = list(store.db.judge_certifications.values())
    for name in ("level", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response([models.judge_view(r) for r in rows], limit, offset)


@bp.route("/op/judges/<judge_ref>", methods=["GET"])
def get_judge(judge_ref):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_JUDGE))
    row = store.db.judge_certifications.get(judge_ref)
    if row is None:
        fail("ERR_NOT_FOUND", "JudgeCertification %s does not exist." % judge_ref)
    return envelope.object_response(models.judge_view(row))


@bp.route("/op/judges/<judge_ref>/transition", methods=["POST"])
def transition_judge(judge_ref):
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("action",),
        optional=("event_application_id",),
        types={"action": STRING, "event_application_id": STRING},
    )
    action = require_action(body, JUDGE_ACTIONS)

    row = store.db.judge_certifications.get(judge_ref)
    if row is None:
        fail("ERR_NOT_FOUND", "JudgeCertification %s does not exist." % judge_ref)

    if action == "RECORD_PRACTICE_EVENT":
        _record_practice(row, body)
    else:
        _decertify(row)

    return envelope.object_response(models.judge_view(row))


def _record_practice(row, body):
    """A self-loop on the status axis: the counter advances, the status does not.

    Recording is narrow by design: it advances the counter only when the
    judge's level is exactly LEVEL_2 and the cited application is both LOCAL
    tier and already REPORTED.
    """
    application_id = body.get("event_application_id")
    if not application_id:
        fail("ERR_INVALID_REQUEST",
             "event_application_id is required for RECORD_PRACTICE_EVENT.")
    application = store.db.event_applications.get(application_id)
    if application is None:
        fail("ERR_NOT_FOUND", "EventApplication %s does not exist." % application_id)

    if row["level"] != "LEVEL_2":
        fail("ERR_INVALID_STATE",
             "Practice events may only be recorded for a LEVEL_2 judge.")
    if application["tier"] != "LOCAL" or application["status"] != "REPORTED":
        fail("ERR_INVALID_STATE",
             "The cited event must be a LOCAL application in REPORTED status.")

    store.touch(row, practice_events=row["practice_events"] + 1)


def _decertify(row):
    """Decertification is permitted only when the judge is the subject of an
    enforcement case that has been escalated."""
    escalated = any(
        c["judge_ref"] == row["judge_ref"] and c["status"] == "ESCALATED"
        for c in store.db.enforcement_cases.values()
    )
    if not escalated:
        fail("ERR_INVALID_STATE",
             "A judge may only be decertified while the subject of an ESCALATED "
             "enforcement case.")
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE certification may be decertified.")
    store.touch(row, status="DECERTIFIED")