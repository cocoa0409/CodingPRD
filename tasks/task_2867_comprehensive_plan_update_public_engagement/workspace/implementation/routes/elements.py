"""Statutory elements, the review loop and the consistency graph (PRD 3.4, 3.5)."""
from flask import Blueprint, g

import constants as K
import serial
import validation as V
from db import bump, db, new_row, sort_rows
from errors import ApiError
from response import (actor, authenticate, created, filter_param, ok, paginate,
                      pagination)
from services import planservice, repo

bp = Blueprint("elements", __name__)

_READERS = K.ALL_ROLES


@bp.post("/planning/plan-elements")
def create_element():
    authenticate([K.ROLE_STAFF])
    data = V.body()
    plan_id = V.get_str(data, "plan_update_id", 1, None)
    element_type = V.get_enum(data, "element_type", K.REQUIRED_ELEMENT_TYPES)
    title = V.get_str(data, "title", 1, 160)
    draft_body = V.get_str(data, "draft_body", 1, 20000)
    policy_count = V.get_int(data, "policy_count", 0, None, required=False,
                             default=0)

    plan = repo.plan(plan_id)
    planservice.ensure_not_adopted(plan)
    if plan["status"] not in ("DRAFTING", "STATE_DEFICIENT"):
        raise ApiError("ERR_PLAN_NOT_DRAFTING")
    for existing in repo.elements_of(plan["id"]):
        if existing["element_type"] == element_type:
            raise ApiError("ERR_DUPLICATE_ELEMENT_TYPE")

    row = new_row({
        "plan_update_id": plan["id"],
        "element_type": element_type,
        "title": title,
        "draft_body": draft_body,
        "policy_count": policy_count,
        "status": "DRAFT",
        "consistency_status": "PENDING",
        "revision_round": 0,
        "authored_by_user_id": actor(),
        "reviewed_by_user_id": None,
    })
    db.plan_elements[row["id"]] = row
    return created(serial.element(row))


@bp.get("/planning/plan-elements/<row_id>")
def read_element(row_id):
    authenticate(_READERS)
    return ok(serial.element(repo.element(row_id)))


@bp.patch("/planning/plan-elements/<row_id>")
def revise_element(row_id):
    authenticate([K.ROLE_STAFF, K.ROLE_DIRECTOR])
    row = repo.element(row_id)
    data = V.body()
    title = V.get_str(data, "title", 1, 160, required=False)
    draft_body = V.get_str(data, "draft_body", 1, 20000, required=False)
    policy_count = V.get_int(data, "policy_count", 0, None, required=False)

    plan = db.plan_updates.get(row["plan_update_id"])
    if plan is not None:
        planservice.ensure_not_adopted(plan)
    if row["status"] not in ("DRAFT", "REVISION_REQUESTED", "ESCALATED"):
        raise ApiError("ERR_ELEMENT_NOT_AMENDABLE")
    # Rung 27: the escalation override sits at the very bottom of the ladder.
    if row["status"] == "ESCALATED" and g.user_role != K.ROLE_DIRECTOR:
        raise ApiError("ERR_ESCALATION_OVERRIDE_REQUIRED")

    if title is not None:
        row["title"] = title
    if draft_body is not None:
        row["draft_body"] = draft_body
    if policy_count is not None:
        row["policy_count"] = policy_count
    if row["status"] == "ESCALATED":
        row["revision_round"] = 0
    row["status"] = "DRAFT"
    bump(row)
    return ok(serial.element(row))


@bp.post("/planning/plan-elements/<row_id>/submit-review")
def submit_element(row_id):
    authenticate([K.ROLE_STAFF])
    row = repo.element(row_id)
    plan = db.plan_updates.get(row["plan_update_id"])
    if plan is not None:
        planservice.ensure_not_adopted(plan)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_ELEMENT_NOT_DRAFT")
    if int(row["policy_count"]) == 0:
        raise ApiError("ERR_ELEMENT_HAS_NO_POLICIES")
    row["status"] = "IN_REVIEW"
    bump(row)
    return ok(serial.element(row))


@bp.post("/planning/plan-elements/<row_id>/review-decision")
def review_element(row_id):
    authenticate([K.ROLE_DIRECTOR])
    row = repo.element(row_id)
    data = V.body()
    decision = V.get_enum(data, "decision", K.REVIEW_DECISIONS)
    V.get_str(data, "review_note", 1, 2000, required=False, non_blank=False)

    plan = repo.plan(row["plan_update_id"])
    planservice.ensure_not_adopted(plan)
    if row["status"] != "IN_REVIEW":
        raise ApiError("ERR_ELEMENT_NOT_IN_REVIEW")
    if row["element_type"] == "HOUSING":
        scenario_id = plan.get("adopted_scenario_id")
        scenario = db.growth_scenarios.get(scenario_id) if scenario_id else None
        if scenario is None or scenario["status"] != "ADOPTED":
            raise ApiError("ERR_SCENARIO_NOT_ADOPTED")
    if actor() == row["authored_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "APPROVE":
        for link in repo.links_sourced_from(row["id"]):
            if link["status"] != "CLEARED":
                raise ApiError("ERR_CONSISTENCY_UNRESOLVED")
        row["status"] = "APPROVED"
        row["reviewed_by_user_id"] = actor()
        row["consistency_status"] = "CLEARED"
        bump(row)
        planservice.refresh(plan)
        bump(plan)
    else:
        if int(row["revision_round"]) == K.MAX_REVISION_ROUNDS - 1:
            row["status"] = "ESCALATED"
            row["revision_round"] = K.MAX_REVISION_ROUNDS
        else:
            row["status"] = "REVISION_REQUESTED"
            row["revision_round"] = int(row["revision_round"]) + 1
        row["reviewed_by_user_id"] = actor()
        bump(row)
    return ok(serial.element(row))


# --- consistency links ------------------------------------------------------

def _reaches(start_id, goal_id):
    """Directed reachability over every link of the graph."""
    seen = set()
    stack = [start_id]
    while stack:
        current = stack.pop()
        if current == goal_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        for link in repo.links_sourced_from(current):
            if link["status"] in K.LINK_STATUSES:
                stack.append(link["target_element_id"])
    return False


@bp.post("/planning/consistency-links")
def create_link():
    authenticate([K.ROLE_STAFF])
    data = V.body()
    source_id = V.get_str(data, "source_element_id", 1, None)
    target_id = V.get_str(data, "target_element_id", 1, None)
    dependency_type = V.get_enum(data, "dependency_type", K.DEPENDENCY_TYPES)

    source = repo.element(source_id)
    target = repo.element(target_id)
    if source["plan_update_id"] != target["plan_update_id"]:
        raise ApiError("ERR_CROSS_PLAN_LINK")
    plan = repo.plan(source["plan_update_id"])
    planservice.ensure_not_adopted(plan)

    if source["id"] == target["id"]:
        raise ApiError("ERR_SELF_CONSISTENCY_LINK")
    for existing in repo.links_sourced_from(source["id"]):
        if existing["target_element_id"] == target["id"]:
            raise ApiError("ERR_DUPLICATE_CONSISTENCY_LINK")
    if _reaches(target["id"], source["id"]):
        raise ApiError("ERR_CONSISTENCY_CYCLE")

    row = new_row({
        "source_element_id": source["id"],
        "target_element_id": target["id"],
        "dependency_type": dependency_type,
        "status": "OPEN",
        "reconciliation_note": None,
        "reconciled_by_user_id": None,
        "staled_by_amendment_id": None,
    })
    db.consistency_links[row["id"]] = row
    if source["consistency_status"] == "CLEARED":
        source["consistency_status"] = "PENDING"
        bump(source)
    planservice.refresh(plan)
    bump(plan)
    return created(serial.link(row))


@bp.get("/planning/consistency-links/<row_id>")
def read_link(row_id):
    authenticate(_READERS)
    return ok(serial.link(repo.link(row_id)))


@bp.get("/planning/consistency-links")
def list_links():
    authenticate(_READERS)
    limit, offset = pagination()
    source_id = filter_param("source_element_id")
    target_id = filter_param("target_element_id")
    status = filter_param("status")
    dependency_type = filter_param("dependency_type")
    rows = sort_rows(list(db.consistency_links.values()))
    if source_id is not None:
        rows = [r for r in rows if r["source_element_id"] == source_id]
    if target_id is not None:
        rows = [r for r in rows if r["target_element_id"] == target_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if dependency_type is not None:
        rows = [r for r in rows if r["dependency_type"] == dependency_type]
    return paginate(rows, limit, offset, serial.link)


@bp.post("/planning/consistency-links/<row_id>/reconcile")
def reconcile_link(row_id):
    authenticate([K.ROLE_DIRECTOR])
    row = repo.link(row_id)
    data = V.body()
    note = V.get_str(data, "reconciliation_note", 1, 2000)

    source = db.plan_elements.get(row["source_element_id"])
    target = db.plan_elements.get(row["target_element_id"])
    plan = repo.plan(source["plan_update_id"])
    planservice.ensure_not_adopted(plan)
    if row["status"] not in ("OPEN", "STALE"):
        raise ApiError("ERR_LINK_ALREADY_CLEARED")
    if target["status"] not in ("IN_REVIEW", "APPROVED", "ADOPTED"):
        raise ApiError("ERR_TARGET_ELEMENT_NOT_REVIEWABLE")

    row["status"] = "CLEARED"
    row["reconciliation_note"] = note
    row["reconciled_by_user_id"] = actor()
    row["staled_by_amendment_id"] = None
    bump(row)
    if planservice.element_consistency_from_links(source) == "CLEARED":
        if source["consistency_status"] != "CLEARED":
            source["consistency_status"] = "CLEARED"
            bump(source)
    planservice.refresh(plan)
    bump(plan)
    return ok(serial.link(row))
