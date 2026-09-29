"""The logical clock (PRD 2.4)."""
from flask import Blueprint

import db as store
from db import db
from middleware import (ROLE_EVALUATOR, ROLE_FACULTY_MENTOR,
                        ROLE_FINANCIAL_AID_OFFICER, ROLE_INTEGRITY_OFFICER,
                        ROLE_PLATFORM_ADMIN, ROLE_REGISTRAR, ROLE_STUDENT,
                        require)
from response import json_body, object_response
from services import shape

bp = Blueprint("clock", __name__)

SETTER_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_REGISTRAR, ROLE_INTEGRITY_OFFICER,
                ROLE_FINANCIAL_AID_OFFICER)
READER_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_REGISTRAR, ROLE_INTEGRITY_OFFICER,
                ROLE_FINANCIAL_AID_OFFICER, ROLE_FACULTY_MENTOR,
                ROLE_EVALUATOR, ROLE_STUDENT)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(*SETTER_ROLES)
    body = json_body()
    instant = shape.req_instant(body, "current_utc")
    db.set_clock(instant)
    return object_response({"current_utc": store.iso(db.now())})


@bp.route("/_clock", methods=["GET"])
def read_clock():
    require(*READER_ROLES)
    return object_response({"current_utc": store.iso(db.now())})
