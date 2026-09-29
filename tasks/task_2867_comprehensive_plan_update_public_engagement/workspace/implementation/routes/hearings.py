"""Adoption hearings and amendment tracking (PRD 3.9)."""
from flask import Blueprint

import constants as K
import serial
import validation as V
from db import add_days, bump, clock_now, db, new_row, sort_rows
from errors import ApiError
from response import (actor, authenticate, created, filter_param, ok, paginate,
                      pagination)
from services import planservice, repo

bp = Blueprint("hearings", __name__)

_READERS = K.ALL_ROLES
_OCCUPYING = ("SCHEDULED", "BLOCKED", "OPEN")


@bp.post("/planning/hearings")
def create_hearing():
    authenticate([K.ROLE_CLERK])
    data = V.body()
    plan_id = V.get_str(data, "plan_update_id", 1, None)
    body_type = V.get_enum(data, "body_type", K.BODY_TYPES)
    scheduled_start = V.get_instant(data, "scheduled_start")
    scheduled_end = V.get_instant(data, "scheduled_end")
    notice_published_at = V.get_instant(data, "notice_published_at")
    if scheduled_end <= scheduled_start:
        V.bad("scheduled_end must be strictly after scheduled_start.")

    plan = repo.plan(plan_id)
    planservice.ensure_not_adopted(plan)
    if plan["status"] not in ("STATE_CERTIFIED", "COMMISSION_RECOMMENDED"):
        raise ApiError("ERR_PLAN_NOT_CERTIFIED")

    siblings = [r for r in repo.hearings_of(plan["id"])
                if r["body_type"] == body_type]
    # Closed interval, no buffer: touching endpoints ARE a conflict here.
    for other in siblings:
        if other["status"] not in _OCCUPYING:
            continue
        if scheduled_start <= other["scheduled_end"] and \
                scheduled_end >= other["scheduled_start"]:
            raise ApiError("ERR_HEARING_SLOT_CONFLICT")
    same_day = [r for r in siblings
                if r["scheduled_start"].date() == scheduled_start.date()]
    if len(same_day) >= K.MAX_HEARINGS_PER_BODY_PER_DAY:
        raise ApiError("ERR_HEARING_DAILY_CAP_EXCEEDED")
    if notice_published_at > add_days(scheduled_start, -K.HEARING_NOTICE_DAYS):
        raise ApiError("ERR_NOTICE_PERIOD_TOO_SHORT")
    if body_type == "COUNCIL" and plan["status"] != "COMMISSION_RECOMMENDED":
        raise ApiError("ERR_COMMISSION_RECOMMENDATION_REQUIRED")

    row = new_row({
        "plan_update_id": plan["id"],
        "body_type": body_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "notice_published_at": notice_published_at,
        "status": "SCHEDULED",
        "outcome": None,
        "amendment_count": 0,
        "adopted_amendment_count": 0,
        "opened_at": None,
        "closed_at": None,
    })
    db.hearings[row["id"]] = row
    return created(serial.hearing(row))


@bp.get("/planning/hearings/<row_id>")
def read_hearing(row_id):
    authenticate(_READERS)
    return ok(serial.hearing(repo.hearing(row_id)))


@bp.post("/planning/hearings/<row_id>/open")
def open_hearing(row_id):
    authenticate([K.ROLE_CLERK])
    row = repo.hearing(row_id)
    plan = repo.plan(row["plan_update_id"])
    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_HEARING_NOT_SCHEDULED")
    if plan["compliance_posture"] != "CLEAR":
        raise ApiError("ERR_PLAN_POSTURE_BLOCKED")
    if clock_now() < row["scheduled_start"]:
        raise ApiError("ERR_HEARING_NOT_YET_STARTED")
    if row["body_type"] == "COUNCIL" and planservice.certified_review(plan) is None:
        raise ApiError("ERR_ENVIRONMENTAL_REVIEW_NOT_CERTIFIED")

    row["status"] = "OPEN"
    row["opened_at"] = clock_now()
    bump(row)
    return ok(serial.hearing(row))


@bp.post("/planning/hearings/<row_id>/outcome")
def record_outcome(row_id):
    authenticate([K.ROLE_CLERK])
    row = repo.hearing(row_id)
    data = V.body()
    outcome = V.get_enum(data, "outcome", K.HEARING_OUTCOMES)
    V.get_str(data, "minutes_note", 1, 4000, required=False, non_blank=False)
    plan = repo.plan(row["plan_update_id"])

    if row["status"] != "OPEN":
        raise ApiError("ERR_HEARING_NOT_OPEN")

    if outcome == "RECOMMEND":
        if row["body_type"] != "COMMISSION":
            raise ApiError("ERR_OUTCOME_NOT_VALID_FOR_BODY")
        if plan["status"] != "STATE_CERTIFIED":
            raise ApiError("ERR_PLAN_NOT_CERTIFIED")
        if plan["compliance_posture"] != "CLEAR":
            raise ApiError("ERR_PLAN_POSTURE_BLOCKED")
        if planservice.certified_review(plan) is None:
            raise ApiError("ERR_ENVIRONMENTAL_REVIEW_NOT_CERTIFIED")
        _reject_unresolved(row)
    elif outcome == "ADOPT":
        if row["body_type"] != "COUNCIL":
            raise ApiError("ERR_OUTCOME_NOT_VALID_FOR_BODY")
        if plan["status"] != "COMMISSION_RECOMMENDED":
            raise ApiError("ERR_PLAN_NOT_RECOMMENDED")
        if plan["compliance_posture"] != "CLEAR":
            raise ApiError("ERR_PLAN_POSTURE_BLOCKED")
        _reject_unresolved(row)
    elif outcome == "DENY":
        if plan["status"] not in ("STATE_CERTIFIED", "COMMISSION_RECOMMENDED"):
            raise ApiError("ERR_PLAN_NOT_CERTIFIED")

    row["outcome"] = outcome
    row["closed_at"] = clock_now()

    if outcome == "CONTINUE":
        row["status"] = "CONTINUED"
        bump(row)
    elif outcome == "RECOMMEND":
        row["status"] = "RECOMMENDED"
        bump(row)
        plan["status"] = "COMMISSION_RECOMMENDED"
        bump(plan)
    elif outcome == "ADOPT":
        row["status"] = "ADOPTED_OUT"
        bump(row)
        plan["status"] = "ADOPTED"
        plan["adopted_at"] = clock_now()
        for element in repo.elements_of(plan["id"]):
            if element["status"] == "APPROVED":
                element["status"] = "ADOPTED"
                bump(element)
        for action in repo.actions_of(plan["id"]):
            if action["status"] == "PENDING":
                action["status"] = "SCHEDULED"
                action["due_at"] = add_days(plan["adopted_at"],
                                            K.IMPLEMENTATION_DUE_DAYS)
                bump(action)
        bump(plan)
    else:
        row["status"] = "DENIED"
        bump(row)
        if row["body_type"] == "COUNCIL" and \
                plan["status"] == "COMMISSION_RECOMMENDED":
            plan["status"] = "DRAFTING"
            plan["state_review_status"] = "NOT_SUBMITTED"
            planservice.demote_approved_elements(plan, include_source=True)
            planservice.refresh(plan, force_block=True,
                                exclude_hearing_ids=(row["id"],))
            bump(plan)
        else:
            # A commission denial blocks every OTHER scheduled hearing.
            planservice.block_scheduled_hearings(plan,
                                                 exclude_ids=(row["id"],))
    return ok(serial.hearing(row))


def _reject_unresolved(hearing_row):
    for amendment in repo.amendments_of(hearing_row["id"]):
        if amendment["status"] == "PROPOSED":
            raise ApiError("ERR_UNRESOLVED_AMENDMENTS")


# --- amendments -------------------------------------------------------------

@bp.post("/planning/amendments")
def create_amendment():
    authenticate([K.ROLE_CLERK])
    data = V.body()
    hearing_id = V.get_str(data, "hearing_id", 1, None)
    element_id = V.get_str(data, "target_element_id", 1, None)
    summary = V.get_str(data, "summary", 1, 2000)
    policy_delta = V.get_int(data, "policy_delta", -50, 50)
    expected_version = V.get_int(data, "expected_element_version", 1)

    hearing = repo.hearing(hearing_id)
    element = repo.element(element_id)
    if hearing["status"] != "OPEN":
        raise ApiError("ERR_HEARING_NOT_OPEN")
    if element["status"] != "APPROVED":
        raise ApiError("ERR_ELEMENT_NOT_AMENDABLE")
    if expected_version != int(element["version"]):
        raise ApiError("ERR_STALE_ELEMENT_VERSION")
    if element["plan_update_id"] != hearing["plan_update_id"]:
        raise ApiError("ERR_CROSS_PLAN_AMENDMENT")

    row = new_row({
        "hearing_id": hearing["id"],
        "target_element_id": element["id"],
        "summary": summary,
        "policy_delta": policy_delta,
        "status": "PROPOSED",
        "element_version_at_proposal": expected_version,
        "applied_policy_count": None,
        "prior_element_status": None,
        "proposed_by_user_id": actor(),
    })
    db.amendments[row["id"]] = row
    hearing["amendment_count"] = int(hearing["amendment_count"]) + 1
    bump(hearing)
    # The element is docketed: its version moves even though content did not.
    bump(element)
    return created(serial.amendment(row))


@bp.get("/planning/amendments/<row_id>")
def read_amendment(row_id):
    authenticate(_READERS)
    return ok(serial.amendment(repo.amendment(row_id)))


@bp.get("/planning/amendments")
def list_amendments():
    authenticate(_READERS)
    limit, offset = pagination()
    hearing_id = filter_param("hearing_id")
    element_id = filter_param("target_element_id")
    status = filter_param("status")
    rows = sort_rows(list(db.amendments.values()))
    if hearing_id is not None:
        rows = [r for r in rows if r["hearing_id"] == hearing_id]
    if element_id is not None:
        rows = [r for r in rows if r["target_element_id"] == element_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, serial.amendment)


@bp.post("/planning/amendments/<row_id>/adopt")
def adopt_amendment(row_id):
    authenticate([K.ROLE_CLERK])
    row = repo.amendment(row_id)
    hearing = repo.hearing(row["hearing_id"])
    element = repo.element(row["target_element_id"])
    plan = repo.plan(hearing["plan_update_id"])

    if row["status"] != "PROPOSED":
        raise ApiError("ERR_AMENDMENT_NOT_PROPOSED")
    if hearing["status"] != "OPEN":
        raise ApiError("ERR_HEARING_NOT_OPEN")
    if actor() == row["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    new_count = int(element["policy_count"]) + int(row["policy_delta"])
    if new_count < 0:
        raise ApiError("ERR_POLICY_COUNT_NEGATIVE")

    row["prior_element_status"] = element["status"]
    element["policy_count"] = new_count
    row["applied_policy_count"] = new_count
    element["consistency_status"] = "STALE"
    bump(element)

    for link in repo.links_targeting(element["id"]):
        if link["status"] != "CLEARED":
            continue
        link["status"] = "STALE"
        link["staled_by_amendment_id"] = row["id"]
        bump(link)
        source = db.plan_elements.get(link["source_element_id"])
        if source is not None and source["id"] != element["id"] and \
                source["consistency_status"] != "STALE":
            source["consistency_status"] = "STALE"
            bump(source)

    row["status"] = "ADOPTED"
    bump(row)
    hearing["adopted_amendment_count"] = \
        int(hearing["adopted_amendment_count"]) + 1
    bump(hearing)
    planservice.refresh(plan, force_block=True)
    bump(plan)
    return ok(serial.amendment(row))


@bp.post("/planning/amendments/<row_id>/withdraw")
def withdraw_amendment(row_id):
    authenticate([K.ROLE_CLERK])
    row = repo.amendment(row_id)
    data = V.body()
    V.get_str(data, "withdrawal_reason", 1, 2000, required=False,
              non_blank=False)
    hearing = repo.hearing(row["hearing_id"])
    if row["status"] != "PROPOSED":
        raise ApiError("ERR_AMENDMENT_NOT_PROPOSED")
    if hearing["status"] != "OPEN":
        raise ApiError("ERR_HEARING_NOT_OPEN")
    row["status"] = "WITHDRAWN"
    bump(row)
    return ok(serial.amendment(row))


@bp.post("/planning/amendments/<row_id>/rescind")
def rescind_amendment(row_id):
    authenticate([K.ROLE_CLERK])
    row = repo.amendment(row_id)
    data = V.body()
    V.get_str(data, "rescission_reason", 1, 2000, non_blank=False)
    hearing = repo.hearing(row["hearing_id"])
    element = repo.element(row["target_element_id"])
    plan = repo.plan(hearing["plan_update_id"])

    if row["status"] != "ADOPTED":
        raise ApiError("ERR_AMENDMENT_NOT_ADOPTED")
    if hearing["status"] != "OPEN":
        raise ApiError("ERR_HEARING_NOT_OPEN")

    sources = []
    for link in list(db.consistency_links.values()):
        if link.get("staled_by_amendment_id") != row["id"]:
            continue
        link["status"] = "CLEARED"
        link["staled_by_amendment_id"] = None
        bump(link)
        source = db.plan_elements.get(link["source_element_id"])
        if source is not None:
            sources.append(source)

    element["policy_count"] = int(element["policy_count"]) - int(row["policy_delta"])
    if row["prior_element_status"] is not None:
        element["status"] = row["prior_element_status"]
    element["consistency_status"] = \
        planservice.element_consistency_from_links(element)
    bump(element)

    for source in sources:
        if source["id"] == element["id"]:
            continue
        if planservice.element_consistency_from_links(source) == "CLEARED" and \
                source["consistency_status"] != "CLEARED":
            source["consistency_status"] = "CLEARED"
            bump(source)

    row["status"] = "RESCINDED"
    bump(row)
    hearing["adopted_amendment_count"] = \
        int(hearing["adopted_amendment_count"]) - 1
    bump(hearing)
    planservice.refresh(plan)
    bump(plan)
    return ok(serial.amendment(row))
