"""FoiaRequest endpoints (PRD §3.9).

POST /records/foia-requests                     Researcher, 201
GET  /records/foia-requests                     all roles except Anonymous
GET  /records/foia-requests/{id}                all roles except Anonymous
POST /records/foia-requests/{id}/adjudicate     FoiaOfficer (RECEIVED or IN_REVIEW)
POST /records/foia-requests/{id}/appeal         Researcher (owner, windowed)
POST /records/foia-requests/{id}/decide-appeal  FoiaAppealsOfficer (SoD vs adjudicator)
"""
from flask import Blueprint, request

import calcs
import constants as C
from envelope import ok_list, ok_object
from errors import err
from helpers import (
    bump,
    get_collection,
    get_foia,
    load_researcher,
    require_active_researcher,
    touch_collection,
)
from store import DB, new_id, parse_dt, ts3, tsc
from validation import (
    body_fk,
    get_auth,
    get_body,
    list_page,
    req_enum,
    req_str,
    require_ownership,
    require_role,
)

bp = Blueprint("foia", __name__)

_ADJUDICATE_TARGET = {"GRANT": "GRANTED", "PARTIAL": "PARTIAL_GRANT", "DENY": "DENIED"}


def _bump_release_count(foia):
    collection = DB.collections[foia["collection_id"]]
    collection["foia_release_count"] += 1
    touch_collection(collection)   # priority recompute if QUEUED + version bump


@bp.post("/records/foia-requests")
def create_foia():
    uid, role = get_auth()                        # rung 1
    require_role(role, ["Researcher"])            # rung 2
    body = get_body()
    # rung 4: body FK existence in declared input order
    researcher_id = body_fk(body, "researcher_id")
    researcher = load_researcher(researcher_id)   # 404 + lazy expiry
    collection_id = body_fk(body, "collection_id")
    collection = get_collection(collection_id)
    require_ownership(uid, researcher_id)         # rung 5
    require_active_researcher(researcher)         # rung 9
    # rung 15: FOIA exists only for restricted records
    if collection["restriction_posture"] == "PUBLIC":
        raise err(
            "ERR_FOIA_NOT_REQUIRED",
            "the collection's records are already public",
        )
    description = req_str(body, "description_of_records")
    now = ts3(DB.now())
    foia = {
        "id": new_id(),
        "researcher_id": researcher_id,
        "collection_id": collection_id,
        "description_of_records": description,
        "status": "RECEIVED",
        "claimed_exemptions": [],
        "adjudicator_id": None,
        "decided_at": None,
        "appeal_reason": None,
        "appeal_decider_id": None,
        "appeal_decision": None,
        "remand_count": 0,
        "close_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.foias[foia["id"]] = foia
    return ok_object(foia, 201)


@bp.get("/records/foia-requests")
def list_foias():
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    filters = {}
    for k in ("researcher_id", "collection_id", "status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    page, total, limit, offset = list_page(DB.foias.values(), filters)
    return ok_list(page, total, limit, offset)


@bp.get("/records/foia-requests/<foia_id>")
def get_one_foia(foia_id):
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    return ok_object(get_foia(foia_id))


@bp.post("/records/foia-requests/<foia_id>/adjudicate")
def adjudicate_foia(foia_id):
    uid, role = get_auth()
    require_role(role, ["FoiaOfficer"])
    f = get_foia(foia_id)                         # rung 3
    # rung 8: decided-and-not-remanded requests reject with the endpoint code
    if f["status"] in ("GRANTED", "PARTIAL_GRANT", "DENIED"):
        raise err(
            "ERR_FOIA_ALREADY_ADJUDICATED",
            "request already stands adjudicated and has not been remanded",
        )
    if f["status"] not in ("RECEIVED", "IN_REVIEW"):
        raise err(
            "ERR_INVALID_STATE",
            "adjudicate requires status RECEIVED or IN_REVIEW",
        )
    # rung 15: decision shape + claimed exemptions
    body = get_body()
    decision = req_enum(body, "decision", C.FOIA_DECISIONS)
    if decision in ("PARTIAL", "DENY"):
        claimed = body.get("claimed_exemptions")
        if (
            not isinstance(claimed, list)
            or len(claimed) == 0
            or any(
                not isinstance(x, str) or x not in C.FOIA_EXEMPTION_CODES
                for x in claimed
            )
        ):
            raise err(
                "ERR_EXEMPTION_REQUIRED",
                "PARTIAL and DENY adjudications require claimed_exemptions as "
                "a non-empty subset of {B1, B3, B5}",
            )
        f["claimed_exemptions"] = list(claimed)
    else:
        f["claimed_exemptions"] = []   # a pure grant claims none
    f["status"] = _ADJUDICATE_TARGET[decision]
    f["adjudicator_id"] = uid
    f["decided_at"] = tsc(DB.now())
    bump(f)
    if decision == "GRANT":
        _bump_release_count(f)
    return ok_object(f)


@bp.post("/records/foia-requests/<foia_id>/appeal")
def appeal_foia(foia_id):
    uid, role = get_auth()
    require_role(role, ["Researcher"])
    f = get_foia(foia_id)                         # rung 3
    require_ownership(uid, f["researcher_id"])    # rung 5
    if f["status"] not in ("PARTIAL_GRANT", "DENIED"):   # rung 8
        raise err(
            "ERR_APPEAL_NOT_ALLOWED_STATE",
            "appeal requires status PARTIAL_GRANT or DENIED",
        )
    # rung 13: appeal window decided_at + 30 days, boundary inclusive
    if DB.now() > calcs.add_days(parse_dt(f["decided_at"]), C.APPEAL_WINDOW_DAYS):
        raise err("ERR_APPEAL_WINDOW_CLOSED", "the 30-day appeal window has closed")
    reason = req_str(get_body(), "appeal_reason")  # rung 15
    f["status"] = "APPEALED"
    f["appeal_reason"] = reason
    bump(f)
    return ok_object(f)


@bp.post("/records/foia-requests/<foia_id>/decide-appeal")
def decide_appeal(foia_id):
    uid, role = get_auth()
    require_role(role, ["FoiaAppealsOfficer"])
    f = get_foia(foia_id)                         # rung 3
    if f["status"] != "APPEALED":                 # rung 8
        raise err("ERR_FOIA_NOT_APPEALED", "decide-appeal requires status APPEALED")
    if uid == f["adjudicator_id"]:                # rung 11 segregation of duties
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            "the adjudicator of a FOIA request may not decide its appeal",
        )
    appeal_decision = req_enum(                   # rung 15
        get_body(), "appeal_decision", C.APPEAL_DECISIONS
    )
    f["appeal_decider_id"] = uid
    f["appeal_decision"] = appeal_decision
    if appeal_decision == "GRANT":
        f["status"] = "APPEAL_GRANTED"
        bump(f)
        _bump_release_count(f)
    elif appeal_decision == "UPHOLD":
        f["status"] = "APPEAL_UPHELD"
        bump(f)
    else:  # REMAND — back to IN_REVIEW for fresh adjudication
        f["status"] = "IN_REVIEW"
        f["remand_count"] += 1
        bump(f)
    return ok_object(f)
