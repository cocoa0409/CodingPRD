"""ResearcherRegistration endpoints (PRD §3.7).

POST /records/researchers                 Anonymous, 201
GET  /records/researchers/{id}            all roles except Anonymous (lazy expiry)
POST /records/researchers/{id}/activate   ResearchRoomStaff (PENDING or EXPIRED)
"""
from flask import Blueprint

import calcs
import constants as C
from envelope import ok_object
from errors import err
from helpers import bump, load_researcher
from store import DB, new_id, ts3, tsc
from validation import get_auth, get_body, req_enum, req_str, require_role

bp = Blueprint("researchers", __name__)


@bp.post("/records/researchers")
def create_researcher():
    _uid, role = get_auth()                       # rung 1
    require_role(role, ["Anonymous"])             # rung 2
    body = get_body()
    # rung 12 (uniqueness) before rung 15 (shape)
    email_raw = body.get("email")
    if isinstance(email_raw, str) and email_raw != "" and any(
        r["email"] == email_raw for r in DB.researchers.values()
    ):
        raise err("ERR_EMAIL_EXISTS", "email already registered")
    # rung 15 shape
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    affiliation = req_enum(body, "affiliation", C.AFFILIATIONS)
    id_document = req_str(body, "id_document")
    now = ts3(DB.now())
    researcher = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "affiliation": affiliation,
        "id_document": id_document,
        "status": "PENDING",
        "card_expires_at": None,
        "suspension_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.researchers[researcher["id"]] = researcher
    return ok_object(researcher, 201)


@bp.get("/records/researchers/<researcher_id>")
def get_one_researcher(researcher_id):
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    # load applies the lazy ACTIVE -> EXPIRED evaluation first
    return ok_object(load_researcher(researcher_id))


@bp.post("/records/researchers/<researcher_id>/activate")
def activate_researcher(researcher_id):
    _uid, role = get_auth()
    require_role(role, ["ResearchRoomStaff"])
    r = load_researcher(researcher_id)            # rung 3 + lazy expiry
    if r["status"] not in ("PENDING", "EXPIRED"):  # rung 8
        raise err(
            "ERR_INVALID_STATE",
            "activate requires status PENDING or EXPIRED",
        )
    r["status"] = "ACTIVE"
    r["card_expires_at"] = tsc(
        calcs.anniversary_add(DB.now(), C.CARD_VALIDITY_YEARS)
    )
    bump(r)
    return ok_object(r)
