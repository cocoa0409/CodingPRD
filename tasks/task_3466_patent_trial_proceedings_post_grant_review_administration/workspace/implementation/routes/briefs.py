"""Briefs and expert declarations (PRD 3.5)."""

from flask import Blueprint

from db import store, strip_internal
from calculations import (
    brief_window_deadline, brief_overage_fee, PAGE_CAPS,
)
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_PHASE,
    ERR_BRIEF_WINDOW_CLOSED, ERR_BRIEF_SEQUENCE_VIOLATION,
    ERR_PAGE_LIMIT_EXCEEDED, ERR_NEW_EVIDENCE_IN_REPLY,
)
from helpers import (
    require_roles, get_body, req_string, req_int, req_enum, req_bool,
    success_object, list_response, ALL_ROLES,
)
from lookups import get_proceeding, get_brief, proceeding_context

bp = Blueprint("briefs", __name__)

BRIEF_TYPES = ("PO_RESPONSE", "PETITIONER_REPLY", "PO_SUR_REPLY")

# Phase each brief type may be accepted in, and the phase it advances to
# (None = phase unchanged; the sur-reply closes the record without advancing).
BRIEF_PHASE_RULES = {
    "PO_RESPONSE": (("INSTITUTED", "REMANDED"), "REPLY_WINDOW"),
    "PETITIONER_REPLY": (("REPLY_WINDOW",), "SUR_REPLY_WINDOW"),
    "PO_SUR_REPLY": (("SUR_REPLY_WINDOW",), None),
}


@bp.post("/ptab/proceedings/<proceedingId>/briefs")
def create_brief(proceedingId):
    user_id, _ = require_roles("Petitioner", "PatentOwner")
    proceeding = get_proceeding(proceedingId)
    body = get_body()

    # brief_type routes the ownership check (priority 4); an invalid type is
    # a schema failure (priority 5) that must surface first.
    raw_type = body.get("brief_type")
    if raw_type not in BRIEF_TYPES:
        raise_err(ERR_VALIDATION, f"brief_type must be one of {list(BRIEF_TYPES)}")
    brief_type = raw_type

    petition, patent = proceeding_context(proceeding)
    if brief_type == "PETITIONER_REPLY":
        if user_id != petition["petitioner_id"]:
            raise_err(ERR_NOT_RESOURCE_OWNER,
                      "PETITIONER_REPLY may be filed only by the proceeding's "
                      "petitioner")
    else:
        if user_id != patent["owner_id"]:
            raise_err(ERR_NOT_RESOURCE_OWNER,
                      f"{brief_type} may be filed only by the patent owner")

    page_count = req_int(body, "page_count", minimum=1)

    # State (priority 7): phase gate.
    allowed_phases, advance_to = BRIEF_PHASE_RULES[brief_type]
    if proceeding["phase"] not in allowed_phases:
        raise_err(ERR_INVALID_PHASE,
                  f"{brief_type} is not accepted in phase "
                  f"{proceeding['phase']}")

    # Statutory clock (priority 8): window anchored at cycle_anchor_date.
    now = store.clock.now()
    if now > brief_window_deadline(proceeding["_anchor_dt"], brief_type):
        raise_err(ERR_BRIEF_WINDOW_CLOSED,
                  f"the {brief_type} window has closed")

    # Domain (priority 9): one brief of each type per cycle, then page cap.
    for other in store.briefs.values():
        if (other["proceeding_id"] == proceeding["id"]
                and other["cycle"] == proceeding["briefing_cycle"]
                and other["brief_type"] == brief_type):
            raise_err(ERR_BRIEF_SEQUENCE_VIOLATION,
                      f"a {brief_type} brief already exists in this cycle")
    if page_count > PAGE_CAPS[brief_type]:
        raise_err(ERR_PAGE_LIMIT_EXCEEDED,
                  f"{brief_type} exceeds its hard cap of "
                  f"{PAGE_CAPS[brief_type]} pages")

    fee = brief_overage_fee(brief_type, page_count)
    brief = store.new_common()
    brief.update({
        "proceeding_id": proceeding["id"],
        "brief_type": brief_type,
        "author_user_id": user_id,
        "page_count": page_count,
        "overage_fee_cents": fee,
        "cycle": proceeding["briefing_cycle"],
    })
    store.briefs[brief["id"]] = brief

    proceeding["total_overage_fee_cents"] += fee
    if advance_to is not None:
        proceeding["phase"] = advance_to
    store.touch(proceeding)
    return success_object(strip_internal(brief), status=201)


@bp.get("/ptab/proceedings/<proceedingId>/briefs")
def list_briefs(proceedingId):
    require_roles(*ALL_ROLES)
    proceeding = get_proceeding(proceedingId)
    items = [b for b in store.briefs.values()
             if b["proceeding_id"] == proceeding["id"]]
    return list_response(items)


@bp.get("/ptab/briefs/<briefId>")
def get_brief_route(briefId):
    require_roles(*ALL_ROLES)
    return success_object(strip_internal(get_brief(briefId)))


@bp.post("/ptab/briefs/<briefId>/expert-declarations")
def create_declaration(briefId):
    user_id, _ = require_roles("Petitioner", "PatentOwner")
    brief = get_brief(briefId)
    # Ownership (priority 4): only the brief's author may attach declarations.
    if user_id != brief["author_user_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "expert declarations may be filed only by the brief's author")
    body = get_body()
    declarant_name = req_string(body, "declarant_name")
    page_count = req_int(body, "page_count", minimum=1)
    contains_new_evidence = req_bool(body, "contains_new_evidence")
    if brief["brief_type"] == "PETITIONER_REPLY" and contains_new_evidence:
        raise_err(ERR_NEW_EVIDENCE_IN_REPLY,
                  "a petitioner reply may not introduce new evidence")

    declaration = store.new_common()
    declaration.update({
        "brief_id": brief["id"],
        "declarant_name": declarant_name,
        "page_count": page_count,
        "contains_new_evidence": contains_new_evidence,
    })
    store.declarations[declaration["id"]] = declaration
    return success_object(strip_internal(declaration), status=201)


@bp.get("/ptab/briefs/<briefId>/expert-declarations")
def list_declarations(briefId):
    require_roles(*ALL_ROLES)
    brief = get_brief(briefId)
    items = [d for d in store.declarations.values()
             if d["brief_id"] == brief["id"]]
    return list_response(items)
