"""Rules enforcement cases.

  POST /op/enforcement-cases                   file a case
  GET  /op/enforcement-cases                   list cases
  GET  /op/enforcement-cases/{id}              retrieve one
  POST /op/enforcement-cases/{id}/transition   ESCALATE / CLOSE / REDUCE
"""

from flask import Blueprint, request

import db as store
import computed as calcs
import models
import response as envelope
from errors import fail
from middleware import (
    ROLE_OPS_ADMIN, ROLE_JUDGE,
    STRING, BOOLEAN,
    require_role, check_body, check_query_enums, require_action,
)

bp = Blueprint("enforcement", __name__)

OFFENSE_CLASSES = ("MINOR", "MAJOR", "SEVERE")
ENFORCEMENT_LEVELS = ("REGULAR", "COMPETITIVE", "PROFESSIONAL")
CASE_STATUSES = ("FILED", "ESCALATED", "CLOSED", "REDUCED")
CASE_ACTIONS = ("ESCALATE", "CLOSE", "REDUCE")


def _derive_violation_points(store_id):
    """Re-derive the owning store's reporting_violation_points."""
    store_row = store.db.stores.get(store_id)
    if store_row is None:
        return
    # The rollup is computed on read; touch the store so its version advances
    # with the enforcement action that changed the figure.
    store.touch(store_row)


@bp.route("/op/enforcement-cases", methods=["POST"])
def create_case():
    require_role(request, (ROLE_JUDGE,))
    body = check_body(
        request,
        required=("event_application_id", "player_ref", "judge_ref",
                  "offense_class", "rules_enforcement_level"),
        optional=("repeated_offense",),
        types={
            "event_application_id": STRING,
            "player_ref": STRING,
            "judge_ref": STRING,
            "offense_class": STRING,
            "rules_enforcement_level": STRING,
            "repeated_offense": BOOLEAN,
        },
        enums={
            "offense_class": OFFENSE_CLASSES,
            "rules_enforcement_level": ENFORCEMENT_LEVELS,
        },
    )

    application = store.db.event_applications.get(body["event_application_id"])
    if application is None:
        fail("ERR_NOT_FOUND",
             "EventApplication %s does not exist." % body["event_application_id"])

    # The flag may be supplied at filing and defaults to false when omitted.
    repeated = body.get("repeated_offense")
    if repeated is None:
        repeated = False

    row = store.insert_enforcement_case(
        body["event_application_id"], body["player_ref"], body["judge_ref"],
        body["offense_class"], body["rules_enforcement_level"], repeated)

    # penalty_points is computed once when the case is filed and never
    # recomputed by a later action; only current_points moves.
    row["penalty_points"] = calcs.penalty_points_for(
        body["offense_class"], body["rules_enforcement_level"])
    row["current_points"] = calcs.current_points_on_filing(row["penalty_points"])

    _derive_violation_points(application["store_id"])
    return envelope.object_response(models.enforcement_case_view(row), status=201)


@bp.route("/op/enforcement-cases", methods=["GET"])
def list_cases():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_JUDGE))
    check_query_enums(request, {"status": CASE_STATUSES})
    rows = list(store.db.enforcement_cases.values())
    for name in ("event_application_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response([models.enforcement_case_view(r) for r in rows],
                                  limit, offset)


@bp.route("/op/enforcement-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_JUDGE))
    row = store.db.enforcement_cases.get(case_id)
    if row is None:
        fail("ERR_NOT_FOUND", "RulesEnforcementCase %s does not exist." % case_id)
    return envelope.object_response(models.enforcement_case_view(row))


@bp.route("/op/enforcement-cases/<case_id>/transition", methods=["POST"])
def transition_case(case_id):
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("action",),
        optional=("reason",),
        types={"action": STRING, "reason": STRING},
    )
    action = require_action(body, CASE_ACTIONS)

    row = store.db.enforcement_cases.get(case_id)
    if row is None:
        fail("ERR_NOT_FOUND", "RulesEnforcementCase %s does not exist." % case_id)

    if row["status"] not in ("FILED", "ESCALATED"):
        fail("ERR_INVALID_STATE",
             "Only a FILED or ESCALATED case may be transitioned.")

    penalty = row["penalty_points"]
    if action == "ESCALATE":
        row["current_points"] = calcs.current_points_on_escalate(
            penalty, row["repeated_offense"])
        store.touch(row, status="ESCALATED")
    elif action == "CLOSE":
        row["current_points"] = calcs.current_points_on_close(penalty)
        store.touch(row, status="CLOSED")
    else:  # REDUCE
        row["current_points"] = calcs.current_points_on_reduce(penalty)
        store.touch(row, status="REDUCED")

    application = store.db.event_applications.get(row["event_application_id"])
    if application is not None:
        _derive_violation_points(application["store_id"])

    return envelope.object_response(models.enforcement_case_view(row))