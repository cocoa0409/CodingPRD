"""Action outcomes: listings, disclosure/effectuation ladder, sanctions (§3.8)."""
from flask import Blueprint

import constants as C
from auth import (authenticate, check_liaison_chain, institution_of_outcome,
                  require_role)
from calculations import cure_evidence_score
from db import STORE, add_months, fmt_dt
from errors import (ERR_ACTION_OUTCOME_NOT_FOUND, ERR_CANDIDACY_EXPIRED,
                    ERR_CURE_THRESHOLD_NOT_MET, ERR_INSTITUTION_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_REVIEW_CYCLE_NOT_FOUND, raise_err)
from helpers import (fetch_or_404, freeze_substantive_changes, get_body,
                     new_entity, paginate, req_enum, serialize, touch)
from response import success_list, success_object

bp = Blueprint("outcomes", __name__)


def _institution_for(outcome):
    inst_id = institution_of_outcome(outcome)
    return STORE.institutions.get(inst_id) if inst_id else None


def _apply_sanction(inst, outcome, level, now):
    outcome["sanction_level"] = level
    outcome["cure_deadline_at"] = fmt_dt(add_months(now, C.SANCTION_CURE_MONTHS[level]))
    inst["sanction_status"] = level
    freeze_substantive_changes(inst["id"])


@bp.get("/accreditation/review-cycles/<cycle_id>/action-outcomes")
def list_cycle_outcomes(cycle_id):
    actor = authenticate()
    cycle = fetch_or_404(STORE.review_cycles, cycle_id, ERR_REVIEW_CYCLE_NOT_FOUND)
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, cycle["institution_id"])
    items = [o for o in STORE.action_outcomes.values() if o["review_cycle_id"] == cycle_id]
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.get("/accreditation/institutions/<inst_id>/action-outcomes")
def list_institution_outcomes(inst_id):
    actor = authenticate()
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, inst_id)
    fetch_or_404(STORE.institutions, inst_id, ERR_INSTITUTION_NOT_FOUND)
    items = []
    for o in STORE.action_outcomes.values():
        if o["indicator_origin_institution_id"] == inst_id:
            items.append(o)
            continue
        if o["review_cycle_id"]:
            cycle = STORE.review_cycles.get(o["review_cycle_id"])
            if cycle is not None and cycle["institution_id"] == inst_id:
                items.append(o)
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.post("/accreditation/action-outcomes/<outcome_id>/advance")
def advance_outcome(outcome_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    outcome = fetch_or_404(STORE.action_outcomes, outcome_id, ERR_ACTION_OUTCOME_NOT_FOUND)
    now = STORE.now()
    inst = _institution_for(outcome)
    if outcome["status"] == "DRAFTED":
        # Public disclosure is mandatory for every action (§3.8).
        outcome["public_disclosure_text"] = (
            "Public notice: the commission has taken the action %s "
            "regarding institution %s." % (outcome["action_type"],
                                           inst["id"] if inst else "unknown"))
        outcome["disclosed_at"] = STORE.now_iso()
        outcome["status"] = "DISCLOSED"
        touch(outcome)
        return success_object(serialize(outcome))
    if outcome["status"] != "DISCLOSED":
        raise_err(ERR_INVALID_STATE, "The outcome is already EFFECTIVE")
    action = outcome["action_type"]
    if action == "GRANT_INITIAL" and inst is not None and inst["_candidacy_expires_dt"] is not None:
        if now > inst["_candidacy_expires_dt"]:
            raise_err(ERR_CANDIDACY_EXPIRED,
                      "The logical clock is past the institution's candidacy expiry")
    outcome["effective_at"] = STORE.now_iso()
    outcome["status"] = "EFFECTIVE"
    if inst is not None:
        if action == "REAFFIRMATION":
            inst["last_reaffirmed_at"] = STORE.now_iso()
            touch(inst)
        elif action == "GRANT_INITIAL":
            inst["accreditation_status"] = "ACCREDITED"
            inst["accredited_since"] = STORE.now_iso()
            touch(inst)
        elif action == "DENIAL":
            inst["accreditation_status"] = "DENIED_ENTRY"
            touch(inst)
        elif action == "WITHDRAWAL":
            inst["accreditation_status"] = "WITHDRAWN"
            inst["sanction_status"] = "MEMBERSHIP_REMOVED"
            touch(inst)
        elif action in C.SANCTION_LEVELS:
            _apply_sanction(inst, outcome, action, now)
            touch(inst)
    touch(outcome)
    return success_object(serialize(outcome))


@bp.post("/accreditation/action-outcomes/<outcome_id>/sanction-transition")
def sanction_transition(outcome_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    outcome = fetch_or_404(STORE.action_outcomes, outcome_id, ERR_ACTION_OUTCOME_NOT_FOUND)
    body = get_body()
    action = req_enum(body, "action", C.SANCTION_TRANSITION_ACTIONS)
    if outcome["status"] != "EFFECTIVE" or outcome["action_type"] not in C.SANCTION_LEVELS:
        raise_err(ERR_INVALID_STATE,
                  "Sanction transitions exist only on EFFECTIVE sanction outcomes")
    inst = _institution_for(outcome)
    now = STORE.now()
    if action == "OPEN_CURE_REVIEW":
        if outcome["cure_status"] != "NONE":
            raise_err(ERR_INVALID_STATE, "A cure review is already open or completed")
        outcome["cure_status"] = "UNDER_CURE_REVIEW"
        outcome["cure_review_opened_at"] = STORE.now_iso()
        outcome["_cure_opened_dt"] = now
        outcome["cure_threshold_snapshot"] = (
            C.BASE_CURE_SCORE + C.SANCTION_LEVEL_OFFSET[outcome["sanction_level"]])
        touch(outcome)
        return success_object(serialize(outcome))
    if action == "CURE":
        if outcome["cure_status"] != "UNDER_CURE_REVIEW":
            raise_err(ERR_CURE_THRESHOLD_NOT_MET, "No cure review is open on this outcome")
        score = cure_evidence_score(inst["id"], outcome["_cure_opened_dt"])
        if score < outcome["cure_threshold_snapshot"]:
            raise_err(ERR_CURE_THRESHOLD_NOT_MET,
                      "Cure evidence score %s is below the frozen threshold %s"
                      % (score, outcome["cure_threshold_snapshot"]))
        outcome["cure_status"] = "CURED"
        if inst is not None:
            inst["sanction_status"] = "NONE"
            touch(inst)
        touch(outcome)
        return success_object(serialize(outcome))
    # ESCALATE — single-step ladder; at SHOW_CAUSE it removes membership.
    level = outcome["sanction_level"]
    if level == "SHOW_CAUSE":
        if inst is not None:
            inst["sanction_status"] = "MEMBERSHIP_REMOVED"
            inst["accreditation_status"] = "WITHDRAWN"
            touch(inst)
        return success_object(serialize(outcome))
    new_level = C.SANCTION_LADDER_NEXT[level]
    outcome["sanction_level"] = new_level
    outcome["cure_deadline_at"] = fmt_dt(add_months(now, C.SANCTION_CURE_MONTHS[new_level]))
    outcome["cure_status"] = "NONE"
    outcome["cure_threshold_snapshot"] = None
    touch(outcome)
    if inst is not None:
        inst["sanction_status"] = new_level
        freeze_substantive_changes(inst["id"])
        touch(inst)
    return success_object(serialize(outcome))
