"""Quality/hemovigilance routes: transfusion reactions and recall/look-back
cases (PRD 3.7)."""

from flask import Blueprint, request

import errors as E
import logic
from common import (
    endpoint, get_body, req_str, opt_str, req_enum, req_bool, opt_dt,
    reaction_by_path, recall_by_path, fk_exists,
)
from constants import ROLES, REACTION_TYPES, SEVERITIES, SEVERE_REACTION_TYPES
from envelope import object_response, list_response
from errors import ApiError
from serializers import ser_reaction, ser_recall
from store import DB, new_entity, touch

bp = Blueprint("quality", __name__)

ALL = ROLES
TECH = ["BloodBankTechnologist"]
QO = ["QualityOfficer"]


# ---------------------------------------------------------------------------
# Transfusion reactions (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.post("/blood-bank/transfusion-reactions")
@endpoint(TECH)
def reaction_create(user_id, role):
    body = get_body()
    issue_record_id = req_str(body, "issue_record_id")
    reaction_type = req_enum(body, "reaction_type", REACTION_TYPES)
    severity = req_enum(body, "severity", SEVERITIES)
    symptoms = opt_str(body, "symptoms", default=None, allow_empty=True)
    issue = fk_exists(DB.issues, issue_record_id, "IssueRecord")
    if issue["status"] not in ("TRANSFUSION_STARTED", "TRANSFUSED"):
        raise ApiError(E.ERR_ISSUE_NOT_REACTIONABLE, 409, "Reaction report requires TRANSFUSION_STARTED or TRANSFUSED")
    reaction = new_entity({
        "issue_record_id": issue["id"],
        "patient_id": issue["patient_id"],
        "unit_id": issue["unit_id"],
        "reaction_type": reaction_type,
        "severity": severity,
        "symptoms": symptoms,
        "reported_by_user_id": user_id,
        "investigator_user_id": None,
        "clerical_check_passed": None,
        "dat_result": None,
        "hemolysis_present": None,
        "workup_recorded_at": None,
        "conclusion": None,
        "final_classification": None,
        "linked_recall_case_id": None,
        "status": "REPORTED",
    })
    DB.reactions[reaction["id"]] = reaction
    # A mid-transfusion report stops the transfusion and quarantine-holds the
    # unit under REACTION_PRECAUTION (no wastage record until concluded).
    if issue["status"] == "TRANSFUSION_STARTED":
        issue["status"] = "TRANSFUSION_STOPPED"
        touch(issue)
        unit = DB.units[issue["unit_id"]]
        if unit["status"] == "ISSUED":
            logic.hold_unit(unit, "REACTION_PRECAUTION")
        order = DB.orders.get(issue["order_id"]) if issue["order_id"] else None
        if order is not None:
            logic.on_issue_removed(order, issue)
    return object_response(ser_reaction(reaction), status=201)


@bp.get("/blood-bank/transfusion-reactions")
@endpoint(ALL)
def reaction_list(user_id, role):
    rows = list(DB.reactions.values())
    for param in ("issue_record_id", "patient_id", "unit_id", "status", "reaction_type", "linked_recall_case_id"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    return list_response(rows, request.args, ser_reaction)


@bp.get("/blood-bank/transfusion-reactions/<rid>")
@endpoint(ALL)
def reaction_get(rid, user_id, role):
    return object_response(ser_reaction(reaction_by_path(rid)))


@bp.post("/blood-bank/transfusion-reactions/<rid>/begin-investigation")
@endpoint(QO)
def reaction_begin(rid, user_id, role):
    reaction = reaction_by_path(rid)
    if reaction["status"] != "REPORTED":
        raise ApiError(E.ERR_REACTION_NOT_INVESTIGABLE, 409, "begin-investigation requires REPORTED")
    if user_id == reaction["reported_by_user_id"]:
        raise ApiError(
            E.ERR_SEGREGATION_OF_DUTIES, 403,
            "The investigator must differ from the reporting technologist",
        )
    reaction["investigator_user_id"] = user_id
    reaction["status"] = "INVESTIGATING"
    touch(reaction)
    return object_response(ser_reaction(reaction))


@bp.post("/blood-bank/transfusion-reactions/<rid>/record-workup")
@endpoint(QO)
def reaction_workup(rid, user_id, role):
    reaction = reaction_by_path(rid)
    body = get_body()
    clerical = req_bool(body, "clerical_check_passed")
    dat_result = req_enum(body, "dat_result", ["POSITIVE", "NEGATIVE"])
    hemolysis = req_bool(body, "hemolysis_present")
    if reaction["status"] != "INVESTIGATING":
        raise ApiError(E.ERR_REACTION_NOT_INVESTIGATING, 409, "record-workup requires INVESTIGATING")
    reaction["clerical_check_passed"] = clerical
    reaction["dat_result"] = dat_result
    reaction["hemolysis_present"] = hemolysis
    if reaction["workup_recorded_at"] is None:
        from store import now
        reaction["workup_recorded_at"] = now()
    touch(reaction)
    return object_response(ser_reaction(reaction))


def _dispose_reaction_held_unit(reaction, actor):
    """A unit involved in a reported reaction is never restocked."""
    unit = DB.units.get(reaction["unit_id"])
    if (
        unit is not None
        and unit["status"] == "QUARANTINED_HOLD"
        and unit["hold_reason"] == "REACTION_PRECAUTION"
    ):
        unit["status"] = "DISCARDED"
        unit["hold_origin_state"] = None
        unit["hold_reason"] = None
        touch(unit)
        logic.add_wastage(unit, "REACTION_INVESTIGATION", actor)


def _run_identification(recall):
    """Pin the implicated unit set per scope (PRD 3.7), sorted by unit
    created_at ASC then unit_number ASC."""
    if recall["scope_type"] == "DONOR":
        implicated = [
            u for u in DB.units.values()
            if u["donor_id"] == recall["donor_id"]
            and (recall["implicated_since"] is None or u["collected_at"] >= recall["implicated_since"])
        ]
    elif recall["scope_type"] == "LOT":
        implicated = [u for u in DB.units.values() if u["lot_number"] == recall["lot_number"]]
    else:  # UNIT scope: the named unit plus transitive derived descendants.
        implicated = []
        frontier = [recall["unit_id"]]
        seen = set()
        while frontier:
            uid = frontier.pop()
            if uid in seen:
                continue
            seen.add(uid)
            unit = DB.units.get(uid)
            if unit is None:
                continue
            implicated.append(unit)
            frontier.extend(
                child["id"] for child in DB.units.values()
                if child["derived_from_unit_id"] == uid
            )
    implicated.sort(key=lambda u: (u["created_at"], u["unit_number"]))
    recall["implicated_unit_ids"] = [u["id"] for u in implicated]
    recall["implicated_unit_count"] = len(implicated)
    implicated_ids = set(recall["implicated_unit_ids"])
    recall["transfused_issue_count"] = sum(
        1 for i in DB.issues.values()
        if i["unit_id"] in implicated_ids and i["status"] in ("TRANSFUSED", "TRANSFUSION_STOPPED")
    )


@bp.post("/blood-bank/transfusion-reactions/<rid>/conclude")
@endpoint(QO)
def reaction_conclude(rid, user_id, role):
    reaction = reaction_by_path(rid)
    body = get_body()
    conclusion = req_enum(body, "conclusion", ["CONFIRMED", "RULED_OUT"])
    final_classification = opt_str(body, "final_classification", default=None, allow_empty=True)
    if reaction["status"] != "INVESTIGATING":
        raise ApiError(E.ERR_REACTION_NOT_INVESTIGATING, 409, "conclude requires INVESTIGATING")
    if reaction["workup_recorded_at"] is None:
        raise ApiError(E.ERR_REACTION_WORKUP_MISSING, 409, "conclude requires a recorded workup first")
    reaction["conclusion"] = conclusion
    reaction["final_classification"] = final_classification
    reaction["status"] = conclusion
    touch(reaction)
    _dispose_reaction_held_unit(reaction, user_id)
    # Severe confirmed reactions auto-create + identify a DONOR-scope recall.
    if conclusion == "CONFIRMED" and reaction["reaction_type"] in SEVERE_REACTION_TYPES:
        unit = DB.units.get(reaction["unit_id"])
        recall = new_entity({
            "scope_type": "DONOR",
            "donor_id": unit["donor_id"] if unit is not None else None,
            "lot_number": None,
            "unit_id": None,
            "implicated_since": None,
            "reason": f"Auto-created from confirmed {reaction['reaction_type']} reaction {reaction['id']}",
            "disposition": "DESTRUCTION",
            "auto_created": True,
            "implicated_unit_ids": [],
            "implicated_unit_count": 0,
            "quarantined_count": 0,
            "transfused_issue_count": 0,
            "notifications_sent_count": 0,
            "status": "OPEN",
        })
        DB.recalls[recall["id"]] = recall
        _run_identification(recall)
        recall["status"] = "UNITS_IDENTIFIED"
        touch(recall)
        reaction["linked_recall_case_id"] = recall["id"]
        touch(reaction)
    return object_response(ser_reaction(reaction))


@bp.post("/blood-bank/transfusion-reactions/<rid>/close")
@endpoint(QO)
def reaction_close(rid, user_id, role):
    reaction = reaction_by_path(rid)
    if reaction["status"] not in ("CONFIRMED", "RULED_OUT"):
        raise ApiError(E.ERR_REACTION_NOT_CLOSABLE, 409, "close requires CONFIRMED or RULED_OUT")
    if reaction["linked_recall_case_id"] is not None:
        recall = DB.recalls.get(reaction["linked_recall_case_id"])
        if recall is None or recall["status"] not in ("NOTIFICATION_COMPLETE", "CLOSED"):
            raise ApiError(
                E.ERR_RECALL_INCOMPLETE, 409,
                "The linked recall must be NOTIFICATION_COMPLETE or CLOSED before closing the reaction",
            )
    reaction["status"] = "CLOSED"
    touch(reaction)
    return object_response(ser_reaction(reaction))


# ---------------------------------------------------------------------------
# Recall / look-back cases (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.post("/blood-bank/recall-cases")
@endpoint(QO)
def recall_create(user_id, role):
    body = get_body()
    scope_type = req_enum(body, "scope_type", ["DONOR", "LOT", "UNIT"])
    reason = req_str(body, "reason")
    disposition = req_enum(body, "disposition", ["DESTRUCTION", "MARKET_WITHDRAWAL"])
    donor_id = opt_str(body, "donor_id")
    lot_number = opt_str(body, "lot_number")
    unit_id = opt_str(body, "unit_id")
    implicated_since = opt_dt(body, "implicated_since")
    # Body FK: the scoping unit_id must resolve (pipeline stage 5).
    if unit_id is not None:
        fk_exists(DB.units, unit_id, "BloodUnit")
    # Scope fields must agree with the scope type (priority 20).
    scope_ok = True
    if scope_type == "DONOR":
        scope_ok = donor_id is not None and lot_number is None and unit_id is None
    elif scope_type == "LOT":
        scope_ok = lot_number is not None and donor_id is None and unit_id is None
    else:
        scope_ok = unit_id is not None and donor_id is None and lot_number is None
    if scope_type != "DONOR" and implicated_since is not None:
        scope_ok = False
    if not scope_ok:
        raise ApiError(E.ERR_RECALL_SCOPE_INVALID, 400, "Scope fields are inconsistent with scope_type")
    recall = new_entity({
        "scope_type": scope_type,
        "donor_id": donor_id,
        "lot_number": lot_number,
        "unit_id": unit_id,
        "implicated_since": implicated_since,
        "reason": reason,
        "disposition": disposition,
        "auto_created": False,
        "implicated_unit_ids": [],
        "implicated_unit_count": 0,
        "quarantined_count": 0,
        "transfused_issue_count": 0,
        "notifications_sent_count": 0,
        "status": "OPEN",
    })
    DB.recalls[recall["id"]] = recall
    return object_response(ser_recall(recall), status=201)


@bp.get("/blood-bank/recall-cases")
@endpoint(ALL)
def recall_list(user_id, role):
    rows = list(DB.recalls.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    scope_type = request.args.get("scope_type")
    if scope_type is not None:
        rows = [r for r in rows if r["scope_type"] == scope_type]
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        rows = [
            r for r in rows
            if r["unit_id"] == unit_id or unit_id in r["implicated_unit_ids"]
        ]
    return list_response(rows, request.args, ser_recall)


@bp.get("/blood-bank/recall-cases/<rid>")
@endpoint(ALL)
def recall_get(rid, user_id, role):
    return object_response(ser_recall(recall_by_path(rid)))


@bp.post("/blood-bank/recall-cases/<rid>/identify-units")
@endpoint(QO)
def recall_identify(rid, user_id, role):
    recall = recall_by_path(rid)
    if recall["status"] != "OPEN":
        raise ApiError(E.ERR_RECALL_NOT_IDENTIFIABLE, 409, "identify-units requires OPEN")
    _run_identification(recall)
    recall["status"] = "UNITS_IDENTIFIED"
    touch(recall)
    return object_response(ser_recall(recall))


@bp.post("/blood-bank/recall-cases/<rid>/execute-quarantine")
@endpoint(QO)
def recall_quarantine(rid, user_id, role):
    recall = recall_by_path(rid)
    if recall["status"] != "UNITS_IDENTIFIED":
        raise ApiError(E.ERR_RECALL_NOT_QUARANTINABLE, 409, "execute-quarantine requires UNITS_IDENTIFIED")
    moved = 0
    for unit_id in recall["implicated_unit_ids"]:
        unit = DB.units.get(unit_id)
        if unit is not None and unit["status"] in ("QUARANTINED", "AVAILABLE", "RESERVED"):
            logic.hold_unit(unit, "RECALL")
            moved += 1
    recall["quarantined_count"] = moved
    recall["status"] = "QUARANTINE_COMPLETE"
    touch(recall)
    return object_response(ser_recall(recall))


@bp.post("/blood-bank/recall-cases/<rid>/record-notification")
@endpoint(QO)
def recall_record_notification(rid, user_id, role):
    recall = recall_by_path(rid)
    body = get_body()
    issue_record_id = req_str(body, "issue_record_id")
    issue = fk_exists(DB.issues, issue_record_id, "IssueRecord")
    if recall["status"] != "QUARANTINE_COMPLETE":
        raise ApiError(
            E.ERR_RECALL_NOTIFICATIONS_NOT_COMPLETABLE, 409,
            "record-notification requires QUARANTINE_COMPLETE",
        )
    if issue["unit_id"] not in set(recall["implicated_unit_ids"]) or issue["status"] not in ("TRANSFUSED", "TRANSFUSION_STOPPED"):
        raise ApiError(E.ERR_ISSUE_NOT_IMPLICATED, 409, "Issue does not reference an implicated transfused unit")
    if issue["lookback_notified"]:
        raise ApiError(E.ERR_ISSUE_ALREADY_NOTIFIED, 409, "Issue is already marked lookback_notified")
    issue["lookback_notified"] = True
    touch(issue)
    recall["notifications_sent_count"] += 1
    touch(recall)
    return object_response(ser_recall(recall))


@bp.post("/blood-bank/recall-cases/<rid>/complete-notifications")
@endpoint(QO)
def recall_complete_notifications(rid, user_id, role):
    recall = recall_by_path(rid)
    if recall["status"] != "QUARANTINE_COMPLETE":
        raise ApiError(
            E.ERR_RECALL_NOTIFICATIONS_NOT_COMPLETABLE, 409,
            "complete-notifications requires QUARANTINE_COMPLETE",
        )
    implicated_ids = set(recall["implicated_unit_ids"])
    pending = any(
        i["unit_id"] in implicated_ids
        and i["status"] in ("TRANSFUSED", "TRANSFUSION_STOPPED")
        and not i["lookback_notified"]
        for i in DB.issues.values()
    )
    if pending:
        raise ApiError(E.ERR_NOTIFICATIONS_PENDING, 409, "Not all implicated transfused issues have been notified")
    recall["status"] = "NOTIFICATION_COMPLETE"
    touch(recall)
    return object_response(ser_recall(recall))


@bp.post("/blood-bank/recall-cases/<rid>/close")
@endpoint(QO)
def recall_close(rid, user_id, role):
    recall = recall_by_path(rid)
    if recall["status"] != "NOTIFICATION_COMPLETE":
        raise ApiError(E.ERR_RECALL_NOT_CLOSABLE, 409, "close requires NOTIFICATION_COMPLETE")
    for unit_id in recall["implicated_unit_ids"]:
        unit = DB.units.get(unit_id)
        if unit is None:
            continue
        if unit["status"] == "QUARANTINED_HOLD" and unit["hold_reason"] == "RECALL":
            if recall["disposition"] == "DESTRUCTION":
                unit["status"] = "DISCARDED"
                unit["hold_origin_state"] = None
                unit["hold_reason"] = None
                touch(unit)
                logic.add_wastage(unit, "RECALL_DESTRUCTION", "system")
            else:  # MARKET_WITHDRAWAL — returned, not wasted.
                unit["status"] = "RETURNED_TO_SUPPLIER"
                unit["hold_origin_state"] = None
                unit["hold_reason"] = None
                touch(unit)
    recall["status"] = "CLOSED"
    touch(recall)
    return object_response(ser_recall(recall))


@bp.post("/blood-bank/recall-cases/<rid>/void")
@endpoint(QO)
def recall_void(rid, user_id, role):
    recall = recall_by_path(rid)
    if recall["status"] not in ("OPEN", "UNITS_IDENTIFIED"):
        raise ApiError(E.ERR_RECALL_NOT_VOIDABLE, 409, "void requires OPEN or UNITS_IDENTIFIED (before quarantine executed)")
    recall["status"] = "VOIDED"
    touch(recall)
    return object_response(ser_recall(recall))
