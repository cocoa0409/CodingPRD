"""Participant endpoints: create, list, get, consent, randomize, withdraw."""
from flask import Blueprint, request

import store
from clock import now_dt
from errors import raise_err
from serialize import participant_out
from services import (current_plan, recompute_enrollment,
                      recompute_quarantine, require_irb_coverage,
                      withdraw_participant)
from util import new_entity, ok_list, ok_obj, paginate, sort_created, touch
from validation import (ROLE_PARTICIPANT, ROLE_PRINCIPAL_INVESTIGATOR,
                        ROLE_STUDY_DIRECTOR, STAFF_ROLES, authenticate,
                        authorize, check_schema, get_json_body)

bp = Blueprint("participants", __name__)


def get_participant_or_404(participant_id):
    participant = store.participants.get(participant_id)
    if participant is None:
        raise_err("ERR_NOT_FOUND", "Participant not found")
    return participant


@bp.post("/evaluation/sites/<site_id>/participants")
def create_participant(site_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_STUDY_DIRECTOR])
    site = store.sites.get(site_id)
    if site is None:
        raise_err("ERR_NOT_FOUND", "Site not found")
    body = get_json_body()
    check_schema(body, {"external_ref": ("str", True)})
    if site["status"] not in ("RECRUITED", "ACTIVE"):
        raise_err("ERR_SITE_INVALID_STATE",
                  "Participants may only be identified at a RECRUITED or "
                  "ACTIVE site")
    participant = new_entity({
        "site_id": site_id,
        "external_ref": body["external_ref"],
        "status": "IDENTIFIED",
        "consent_form_version": None,
        "consented_at": None,
        "burden_total_minutes": 0,
        "withdrawal_reason": None,
    })
    store.participants[participant["id"]] = participant
    return ok_obj(participant_out(participant), 201)


@bp.get("/evaluation/participants")
def list_participants():
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    items = list(store.participants.values())
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    if site_id is not None:
        items = [p for p in items if p["site_id"] == site_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([participant_out(p) for p in page], limit, offset, total)


@bp.get("/evaluation/participants/<participant_id>")
def get_participant(participant_id):
    uid, role = authenticate()
    authorize(role, list(STAFF_ROLES) + [ROLE_PARTICIPANT])
    if role == ROLE_PARTICIPANT and uid != participant_id:
        raise_err("ERR_UNAUTHORIZED_ROLE",
                  "A Participant may read only its own record")
    return ok_obj(participant_out(get_participant_or_404(participant_id)))


@bp.post("/evaluation/participants/<participant_id>/consent")
def consent_participant(participant_id):
    uid, role = authenticate()
    authorize(role, [ROLE_PARTICIPANT])
    if uid != participant_id:
        raise_err("ERR_UNAUTHORIZED_ROLE",
                  "A Participant may consent only on its own record")
    participant = get_participant_or_404(participant_id)
    body = get_json_body()
    check_schema(body, {"consent_form_version": ("int", True)})
    if participant["status"] != "IDENTIFIED":
        raise_err("ERR_PARTICIPANT_INVALID_STATE",
                  "Only an IDENTIFIED participant can consent")
    site = store.sites.get(participant["site_id"])
    if site["status"] != "ACTIVE":
        raise_err("ERR_SITE_INVALID_STATE",
                  "Consent requires an ACTIVE site")
    proto = require_irb_coverage(site["study_id"])
    if body["consent_form_version"] != proto["consent_form_version"]:
        raise_err("ERR_CONSENT_VERSION_STALE",
                  "consent_form_version does not match the currently "
                  "approved protocol's consent_form_version")
    if site["enrolled_count"] >= site["max_participants"]:
        raise_err("ERR_SITE_CAPACITY_EXCEEDED",
                  "Site is at its max_participants capacity")
    participant["status"] = "CONSENTED"
    participant["consent_form_version"] = body["consent_form_version"]
    participant["consented_at"] = now_dt()
    touch(participant)
    recompute_enrollment(store.studies.get(site["study_id"]))
    return ok_obj(participant_out(participant))


@bp.post("/evaluation/participants/<participant_id>/randomize")
def randomize_participant(participant_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    participant = get_participant_or_404(participant_id)
    body = get_json_body()
    check_schema(body, {})
    if participant["status"] != "CONSENTED":
        raise_err("ERR_PARTICIPANT_INVALID_STATE",
                  "Only a CONSENTED participant can be randomized")
    site = store.sites.get(participant["site_id"])
    plan = current_plan(site["study_id"])
    if plan is None or plan["status"] != "LOCKED":
        raise_err("ERR_DESIGN_PLAN_INVALID_STATE",
                  "The study's current design plan must be LOCKED")
    slot = site["randomized_count"] % plan["randomization_ratio_den"]
    if slot < plan["randomization_ratio_num"]:
        participant["status"] = "RANDOMIZED_TREATMENT"
    else:
        participant["status"] = "RANDOMIZED_CONTROL"
    touch(participant)
    site["randomized_count"] += 1
    touch(site)
    return ok_obj(participant_out(participant))


@bp.post("/evaluation/participants/<participant_id>/withdraw")
def withdraw_participant_endpoint(participant_id):
    uid, role = authenticate()
    authorize(role, [ROLE_PARTICIPANT, ROLE_STUDY_DIRECTOR])
    if role == ROLE_PARTICIPANT and uid != participant_id:
        raise_err("ERR_UNAUTHORIZED_ROLE",
                  "A Participant may withdraw only its own record")
    participant = get_participant_or_404(participant_id)
    body = get_json_body()
    check_schema(body, {"reason": ("str", False)})
    if participant["status"] not in ("IDENTIFIED", "CONSENTED",
                                     "RANDOMIZED_TREATMENT",
                                     "RANDOMIZED_CONTROL"):
        raise_err("ERR_PARTICIPANT_INVALID_STATE",
                  "Participant is not in a withdrawable state")
    site = store.sites.get(participant["site_id"])
    study = store.studies.get(site["study_id"])
    withdraw_participant(participant, "PARTICIPANT_INITIATED")
    recompute_enrollment(study)
    recompute_quarantine(study)
    return ok_obj(participant_out(participant))
