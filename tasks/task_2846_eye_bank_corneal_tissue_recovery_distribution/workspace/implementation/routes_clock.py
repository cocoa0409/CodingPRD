"""The logical clock capability (PRD 2.4). The clock is the only source of 'now'."""

from flask import Blueprint

import auth
import envelope
import store
import validate
from errors import ApiError

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector"))
    body = auth.body_dict()
    target = validate.req_dt(body, "to_iso8601")

    if target < store.now():
        raise ApiError(
            "ERR_CLOCK_REWIND_FORBIDDEN", "The logical clock never rewinds."
        )

    store.set_clock(target)
    return envelope.ok({"current_utc": store.iso(store.now())})
