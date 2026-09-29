"""The two test-driving capabilities of PRD 2.5."""
from flask import Blueprint

import shape
from authz import (ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN,
                  authenticate)
from envelope import ok
from store import db

bp = Blueprint("testing", __name__)


@bp.post("/ocs/_clock/set_current_utc")
def set_current_utc():
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST))
    fields = shape.fields()
    to_iso8601 = fields.instant("to_iso8601")
    # The clock may move forward or backward; setting it mutates no entity and fires
    # no lazy transition.
    db.current_utc = to_iso8601
    return ok({})


@bp.post("/ocs/_market/set_green_index")
def set_green_index():
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_BILLING_SPECIALIST))
    fields = shape.fields()
    index_micros = fields.integer("index_micros")
    # Replacing the quote reprices nothing on its own.
    db.green_index_micros = index_micros
    return ok({})
